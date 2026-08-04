"""Jarvis long-term memory: a local SQLite store with semantic recall.

Each memory is a short statement (a fact, preference, person, project, routine, or
decision) with a timestamp and a vector embedding. Recall uses cosine similarity
over a small local embedding model (fastembed / ONNX - no internet needed after the
one-time model download), falling back to keyword matching if embeddings are
unavailable. This is the substrate for Jarvis "knowing you" and for future offline
operation.
"""

import os
import json
import sqlite3
import threading
from datetime import datetime

import numpy as np

APP_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORY_DIR = os.path.join(APP_DIR, "memory")
DB_PATH = os.path.join(MEMORY_DIR, "memory.db")
EMBED_MODEL = "BAAI/bge-small-en-v1.5"   # 384-dim, small, CPU-friendly

# --- recall ranking: relevance first, then nudge by how often a memory is used
# and how recently, so the things you keep coming back to outrank a one-off aside.
# Weights are small so cosine relevance still dominates (it sits ~0.3-0.9). ---
SALIENCE_WEIGHT = 0.06     # per unit of log(1 + use_count)
RECENCY_WEIGHT = 0.05      # scales an exp-decayed recency factor in [0, 1]
RECENCY_TAU_DAYS = 30.0    # how fast recency fades (higher = slower)
# Categories that are behaviourally load-bearing get a small standing boost so a
# hard rule or a stated preference tends to beat an incidental fact of equal cosine.
CATEGORY_BOOST = {"rule": 0.08, "preference": 0.04, "insight": 0.03, "decision": 0.02}


# --------------------------------------------------------------------------- #
#  Shared embedder - one ONNX model instance for both long-term memory and
#  the document index (jarvis_docs.py), so it's loaded into RAM only once.
# --------------------------------------------------------------------------- #
_embedder = None       # None=untried, False=unavailable, else loaded model
_embedder_lock = threading.Lock()


def get_embedder(model_name=EMBED_MODEL):
    global _embedder
    if _embedder is None:
        with _embedder_lock:
            if _embedder is None:
                try:
                    from fastembed import TextEmbedding
                    _embedder = TextEmbedding(model_name=model_name)
                except Exception:
                    _embedder = False
    return _embedder or None


def embed_text(text, model_name=EMBED_MODEL):
    """Return a unit-normalized embedding vector for `text`, or None if the
    embedding model is unavailable."""
    emb = get_embedder(model_name)
    if not emb:
        return None
    try:
        vec = np.asarray(list(emb.embed([text]))[0], dtype=np.float32)
        norm = float(np.linalg.norm(vec)) or 1.0
        return vec / norm
    except Exception:
        return None


def vec_to_blob(vec):
    return vec.astype(np.float32).tobytes() if vec is not None else None


def blob_to_vec(blob):
    if not blob:
        return None
    try:
        return np.frombuffer(blob, dtype=np.float32)
    except Exception:
        return None


class MemoryDB:
    def __init__(self, path=DB_PATH, model_name=EMBED_MODEL):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path
        self.model_name = model_name
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                category TEXT DEFAULT 'fact',
                source TEXT DEFAULT 'auto',
                created_at TEXT,
                last_used TEXT,
                embedding BLOB
            )
        """)
        # small key/value scratchpad (e.g. the reflection watermark)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        # Additive migrations so an older memory.db gains the columns that power
        # salience/recency ranking and contradiction repair, without a rebuild.
        have = {r["name"] for r in self._conn.execute("PRAGMA table_info(memories)")}
        if "use_count" not in have:      # how often this memory has been recalled
            self._conn.execute("ALTER TABLE memories ADD COLUMN use_count INTEGER DEFAULT 0")
        if "status" not in have:         # 'active' | 'superseded' (kept for audit, not recalled)
            self._conn.execute("ALTER TABLE memories ADD COLUMN status TEXT DEFAULT 'active'")
        if "superseded_by" not in have:  # id of the memory that replaced this one
            self._conn.execute("ALTER TABLE memories ADD COLUMN superseded_by INTEGER")
        self._conn.commit()

    # ---- meta key/value (reflection state etc.) ------------------------- #
    def get_meta(self, key, default=None):
        row = self._conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key, value):
        with self._lock:
            self._conn.execute(
                "INSERT INTO meta(key, value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
            self._conn.commit()

    def _embed(self, text):
        return embed_text(text, self.model_name)

    _vec_to_blob = staticmethod(vec_to_blob)
    _blob_to_vec = staticmethod(blob_to_vec)

    # ---- writes --------------------------------------------------------- #
    def add(self, text, category="fact", source="auto", dedupe=True):
        text = (text or "").strip()
        if not text:
            return None
        vec = self._embed(text)
        with self._lock:
            rows = self._conn.execute("SELECT id, text, embedding FROM memories").fetchall()
            if dedupe:
                if vec is not None:
                    for r in rows:
                        ev = self._blob_to_vec(r["embedding"])
                        if ev is not None and ev.shape == vec.shape and float(np.dot(vec, ev)) > 0.93:
                            return r["id"]      # near-duplicate; skip
                else:
                    low = text.lower()
                    for r in rows:
                        if r["text"].lower() == low:
                            return r["id"]
            now = datetime.now().isoformat(timespec="seconds")
            cur = self._conn.execute(
                "INSERT INTO memories(text, category, source, created_at, last_used, embedding) "
                "VALUES (?,?,?,?,?,?)",
                (text, category, source, now, now, self._vec_to_blob(vec)),
            )
            self._conn.commit()
            return cur.lastrowid

    def delete(self, mem_id):
        with self._lock:
            self._conn.execute("DELETE FROM memories WHERE id=?", (mem_id,))
            self._conn.commit()

    def wipe(self):
        with self._lock:
            self._conn.execute("DELETE FROM memories")
            self._conn.commit()

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass

    # ---- reads ---------------------------------------------------------- #
    def count(self):
        return self._conn.execute("SELECT COUNT(*) AS c FROM memories").fetchone()["c"]

    def list_all(self, category=None, limit=200):
        if category:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE category=? ORDER BY created_at DESC LIMIT ?",
                (category, limit)).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM memories ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def max_id(self):
        row = self._conn.execute("SELECT MAX(id) AS m FROM memories").fetchone()
        return int(row["m"]) if row and row["m"] is not None else 0

    def recent(self, limit=40, exclude_categories=()):
        """Most-recent memories (newest first) for reflection input. Optionally
        skip categories (e.g. 'insight' so reflections don't feed on themselves)."""
        if exclude_categories:
            ph = ",".join("?" * len(exclude_categories))
            rows = self._conn.execute(
                f"SELECT * FROM memories WHERE category NOT IN ({ph}) "
                "ORDER BY id DESC LIMIT ?", (*exclude_categories, limit)).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM memories ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def count_since(self, min_id, exclude_categories=()):
        """How many memories were added after `min_id` (optionally excluding
        some categories) - drives the 'enough new material to reflect' trigger."""
        if exclude_categories:
            ph = ",".join("?" * len(exclude_categories))
            row = self._conn.execute(
                f"SELECT COUNT(*) AS c FROM memories WHERE id > ? AND category NOT IN ({ph})",
                (min_id, *exclude_categories)).fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) AS c FROM memories WHERE id > ?", (min_id,)).fetchone()
        return int(row["c"])

    def _recency_factor(self, row):
        """1.0 for a memory used just now, decaying toward 0 with age (days)."""
        stamp = row["last_used"] or row["created_at"]
        if not stamp:
            return 0.0
        try:
            age_days = (datetime.now() - datetime.fromisoformat(stamp)).total_seconds() / 86400.0
        except Exception:
            return 0.0
        return float(np.exp(-max(0.0, age_days) / RECENCY_TAU_DAYS))

    @staticmethod
    def _is_active(row):
        try:
            return (row["status"] or "active") == "active"
        except (IndexError, KeyError):
            return True   # pre-migration rows have no status column

    def by_category(self, category, limit=12):
        """Active memories of one category, newest/most-used first - for the
        always-injected standing blocks (rules, preferences) that shouldn't
        depend on winning a per-turn similarity search."""
        rows = [r for r in self._conn.execute(
                    "SELECT * FROM memories WHERE category=? ORDER BY id DESC", (category,)).fetchall()
                if self._is_active(r)]
        rows.sort(key=lambda r: (-(r["use_count"] or 0), -r["id"]))
        return [r["text"] for r in rows[:limit]]

    def search(self, query, k=5, min_score=0.30, exclude_categories=()):
        """Return up to k relevant memory strings for `query`.

        Ranking is relevance-first (cosine), then re-ordered within the relevant
        set by a small salience (how often recalled) + recency (how recently) +
        category boost, so the facts the user keeps returning to and just-learned
        updates surface ahead of equally-similar but stale one-offs. Superseded
        memories (replaced by a newer, contradicting fact) are never recalled.
        `exclude_categories` keeps categories with their own prompt block (rules,
        preferences) or internal use (reasoning traces) out of generic recall."""
        exc = set(exclude_categories or ())
        rows = [r for r in self._conn.execute("SELECT * FROM memories").fetchall()
                if self._is_active(r) and r["category"] not in exc]
        if not rows:
            return []
        qv = self._embed(query)
        hits = []
        if qv is not None:
            scored = []
            for r in rows:
                ev = self._blob_to_vec(r["embedding"])
                if ev is None or ev.shape != qv.shape:
                    continue
                cos = float(np.dot(qv, ev))
                boost = (SALIENCE_WEIGHT * float(np.log1p(max(0, r["use_count"] or 0)))
                         + RECENCY_WEIGHT * self._recency_factor(r)
                         + CATEGORY_BOOST.get(r["category"], 0.0))
                scored.append((cos, cos + boost, r))
            relevant = [(blend, r) for cos, blend, r in scored if cos >= min_score]
            relevant.sort(key=lambda x: -x[0])
            hits = [r for _b, r in relevant[:k]]
            if not hits and scored:        # nothing strong; offer the best couple by cosine
                scored.sort(key=lambda x: -x[0])
                hits = [r for _c, _b, r in scored[:min(2, k)]]
        else:
            words = [w for w in query.lower().split() if len(w) > 2]
            hits = [r for r in rows
                    if any(w in r["text"].lower() for w in words)][:k]
        if hits:
            now = datetime.now().isoformat(timespec="seconds")
            with self._lock:
                self._conn.executemany(
                    "UPDATE memories SET last_used=?, use_count=COALESCE(use_count,0)+1 WHERE id=?",
                    [(now, r["id"]) for r in hits])
                self._conn.commit()
        return [r["text"] for r in hits]

    # ---- contradiction repair ------------------------------------------- #
    def find_conflicts(self, text, lo=0.62, hi=0.93, exclude_id=None, limit=6):
        """Active memories that are on the SAME topic as `text` but not near-
        identical - the band where a new fact is likely an UPDATE to (or
        contradiction of) an existing one (e.g. 'lives in Nashville' vs 'moved to
        Austin', which sit around 0.74 cosine). The floor is deliberately loose;
        the engine's LLM adjudicator is the accuracy gate that decides which, if
        any, are genuinely superseded. Returns [{id, text, category, score}]
        most-similar first, capped at `limit`."""
        vec = self._embed(text)
        if vec is None:
            return []
        out = []
        for r in self._conn.execute("SELECT * FROM memories").fetchall():
            if not self._is_active(r) or r["id"] == exclude_id:
                continue
            ev = self._blob_to_vec(r["embedding"])
            if ev is None or ev.shape != vec.shape:
                continue
            s = float(np.dot(vec, ev))
            if lo <= s <= hi:
                out.append({"id": r["id"], "text": r["text"],
                            "category": r["category"], "score": s})
        out.sort(key=lambda x: -x["score"])
        return out[:limit]

    def supersede(self, old_id, new_id=None):
        """Retire a memory that a newer fact has contradicted/updated. It's kept
        (status='superseded') for audit but is no longer recalled."""
        with self._lock:
            self._conn.execute(
                "UPDATE memories SET status='superseded', superseded_by=? WHERE id=?",
                (new_id, old_id))
            self._conn.commit()

    # ---- one-time migration of the old notes.json -------------------------- #
    def migrate_notes(self, notes_path):
        if not os.path.exists(notes_path):
            return 0
        try:
            with open(notes_path, "r", encoding="utf-8") as f:
                notes = json.load(f)
        except Exception:
            return 0
        n = 0
        for entry in notes or []:
            txt = entry.get("note") if isinstance(entry, dict) else str(entry)
            if txt:
                self.add(txt, category="note", source="manual")
                n += 1
        try:
            os.rename(notes_path, notes_path + ".imported")
        except OSError:
            pass
        return n
