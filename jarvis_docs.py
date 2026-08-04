"""Jarvis document RAG: a local index of text chunks pulled from the user's
files (txt/md/pdf/docx), searchable by semantic similarity using the same
embedding model as long-term memory (jarvis_memory). This lets Jarvis answer
questions about specific documents you point it at, rather than only what it
remembers about you.
"""

import os
import re
import sqlite3
import threading
from datetime import datetime

import numpy as np

import jarvis_memory

APP_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORY_DIR = os.path.join(APP_DIR, "memory")
DB_PATH = os.path.join(MEMORY_DIR, "documents.db")

CHUNK_SIZE = 1200       # characters per chunk (rough; broken on paragraph/sentence bounds)
CHUNK_OVERLAP = 150
MAX_FILES_PER_SCAN = 200

TEXT_EXTS = {".txt", ".md", ".markdown", ".log", ".csv", ".rtf"}
PDF_EXTS = {".pdf"}
DOCX_EXTS = {".docx"}
SUPPORTED_EXTS = TEXT_EXTS | PDF_EXTS | DOCX_EXTS


# --------------------------------------------------------------------------- #
#  Text extraction
# --------------------------------------------------------------------------- #
def _extract_text(path):
    """Pull plain text out of a supported file. Returns None for unsupported types."""
    ext = os.path.splitext(path)[1].lower()
    if ext in PDF_EXTS:
        from pypdf import PdfReader
        reader = PdfReader(path)
        return "\n\n".join((page.extract_text() or "") for page in reader.pages)
    if ext in DOCX_EXTS:
        import docx
        d = docx.Document(path)
        return "\n".join(p.text for p in d.paragraphs)
    if ext in TEXT_EXTS:
        for enc in ("utf-8", "utf-16", "latin-1"):
            try:
                with open(path, "r", encoding=enc) as f:
                    return f.read()
            except (UnicodeError, LookupError):
                continue
    return None


def _chunk(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """Split text into overlapping chunks, preferring paragraph/sentence breaks
    so a chunk doesn't sever a thought mid-sentence."""
    text = re.sub(r"\n{3,}", "\n\n", (text or "").strip())
    if not text:
        return []
    chunks = []
    start, n = 0, len(text)
    while start < n:
        end = min(start + size, n)
        if end < n:
            brk = text.rfind("\n\n", start + size // 2, end)
            if brk == -1:
                brk = text.rfind(". ", start + size // 2, end)
            if brk != -1:
                end = brk + 1
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return chunks


# --------------------------------------------------------------------------- #
#  The index
# --------------------------------------------------------------------------- #
class DocIndex:
    def __init__(self, path=DB_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_path TEXT NOT NULL,
                doc_name TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                mtime REAL,
                indexed_at TEXT,
                embedding BLOB
            )
        """)
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_doc_path ON chunks(doc_path)")
        self._conn.commit()

    # ---- indexing -------------------------------------------------------- #
    def index_file(self, path):
        """(Re)index one file if it's new or changed since last time.
        Returns (n_chunks_indexed, status) where status is one of
        'indexed' | 'unchanged' | 'unsupported' | 'empty' | 'not found'."""
        path = os.path.abspath(os.path.expanduser(path))
        if not os.path.isfile(path):
            return 0, "not found"
        if os.path.splitext(path)[1].lower() not in SUPPORTED_EXTS:
            return 0, "unsupported"
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = None
        with self._lock:
            row = self._conn.execute(
                "SELECT mtime FROM chunks WHERE doc_path=? LIMIT 1", (path,)).fetchone()
        if row is not None and mtime is not None and row["mtime"] == mtime:
            return 0, "unchanged"
        try:
            text = _extract_text(path)
        except Exception:
            return 0, "unreadable"
        if not text or not text.strip():
            return 0, "empty"
        pieces = _chunk(text)
        if not pieces:
            return 0, "empty"
        name = os.path.basename(path)
        now = datetime.now().isoformat(timespec="seconds")
        rows = []
        for i, piece in enumerate(pieces):
            vec = jarvis_memory.embed_text(piece)
            rows.append((path, name, i, piece, mtime, now, jarvis_memory.vec_to_blob(vec)))
        with self._lock:
            self._conn.execute("DELETE FROM chunks WHERE doc_path=?", (path,))
            self._conn.executemany(
                "INSERT INTO chunks(doc_path, doc_name, chunk_index, text, mtime, "
                "indexed_at, embedding) VALUES (?,?,?,?,?,?,?)", rows)
            self._conn.commit()
        return len(pieces), "indexed"

    def index_path(self, path, max_files=MAX_FILES_PER_SCAN):
        """Index a single file, or every supported file under a directory
        (recursive, capped at max_files). Returns a list of
        (path, n_chunks, status) tuples."""
        path = os.path.abspath(os.path.expanduser(path))
        if os.path.isfile(path):
            n, status = self.index_file(path)
            return [(path, n, status)]
        if not os.path.isdir(path):
            return [(path, 0, "not found")]
        results = []
        for dirpath, _dirs, files in os.walk(path):
            for fn in files:
                if os.path.splitext(fn)[1].lower() not in SUPPORTED_EXTS:
                    continue
                if len(results) >= max_files:
                    return results
                fp = os.path.join(dirpath, fn)
                n, status = self.index_file(fp)
                results.append((fp, n, status))
        return results

    def remove_path(self, path):
        """Drop a file (or every file under a folder) from the index."""
        path = os.path.abspath(os.path.expanduser(path))
        with self._lock:
            if os.path.isdir(path):
                cur = self._conn.execute(
                    "DELETE FROM chunks WHERE doc_path LIKE ? ESCAPE '\\'",
                    (path.rstrip("\\/").replace("%", r"\%").replace("_", r"\_") + os.sep + "%",))
            else:
                cur = self._conn.execute("DELETE FROM chunks WHERE doc_path=?", (path,))
            self._conn.commit()
            return cur.rowcount

    def wipe(self):
        with self._lock:
            self._conn.execute("DELETE FROM chunks")
            self._conn.commit()

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass

    # ---- reads ----------------------------------------------------------- #
    def count(self):
        return self._conn.execute("SELECT COUNT(*) AS c FROM chunks").fetchone()["c"]

    def documents(self):
        """One summary row per indexed file: name, path, chunk count, last indexed."""
        rows = self._conn.execute(
            "SELECT doc_path, doc_name, COUNT(*) AS chunks, MAX(indexed_at) AS indexed_at "
            "FROM chunks GROUP BY doc_path ORDER BY indexed_at DESC").fetchall()
        return [dict(r) for r in rows]

    def search(self, query, k=5, min_score=0.25):
        """Return up to k relevant chunks for `query`, each as
        {doc, path, chunk, text, score}, best first."""
        rows = self._conn.execute("SELECT * FROM chunks").fetchall()
        if not rows:
            return []
        qv = jarvis_memory.embed_text(query)
        if qv is not None:
            scored = []
            for r in rows:
                ev = jarvis_memory.blob_to_vec(r["embedding"])
                if ev is None or ev.shape != qv.shape:
                    continue
                scored.append((float(np.dot(qv, ev)), r))
            scored.sort(key=lambda x: -x[0])
            hits = [(s, r) for s, r in scored[:k] if s >= min_score]
            if not hits and scored:        # nothing strong; offer the best couple anyway
                hits = scored[:min(2, k)]
        else:
            words = [w for w in query.lower().split() if len(w) > 2]
            hits = [(1.0, r) for r in rows
                    if any(w in r["text"].lower() for w in words)][:k]
        return [{"doc": r["doc_name"], "path": r["doc_path"], "chunk": r["chunk_index"],
                 "text": r["text"], "score": round(s, 3)} for s, r in hits]
