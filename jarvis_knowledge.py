"""Jarvis knowledge cache - a local, growing store of answers to STABLE questions.

When Claude answers a question that doesn't depend on live/personal/action data
(pure reasoning or general knowledge), the answer is logged here keyed by the
question's embedding. A later repeat - or a close paraphrase - can then be served
straight from local memory with NO API call, and the offline/local-LLM tiers can
draw on it too. Every stable answer makes the next one more likely to be free, so
the assistant edges toward offline by accretion.

Volatile/time-sensitive answers (weather, calendar, email, news, system, the time)
are NEVER written here - the engine decides that by which tools a turn used and by
the question's intent - so nothing stale is ever replayed.

SQLite at memory/knowledge.db; reuses jarvis_memory's shared embedder. Cold-testable.
"""

import os
import sqlite3
import threading
from datetime import datetime

import numpy as np

import jarvis_memory as _mem   # shared ONNX embedder + blob helpers

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "memory", "knowledge.db")


class KnowledgeCache:
    def __init__(self, path=DB_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS qa (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                created_at TEXT,
                last_used TEXT,
                use_count INTEGER DEFAULT 0,
                embedding BLOB
            )
        """)
        self._conn.commit()

    def add(self, question, answer, dedupe_threshold=0.93):
        """Cache a Q->A. If a very-similar question already exists, refresh its
        answer + timestamp instead of adding a duplicate."""
        question = (question or "").strip()
        answer = (answer or "").strip()
        if not question or not answer:
            return None
        vec = _mem.embed_text(question)
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock:
            if vec is not None:
                for r in self._conn.execute("SELECT id, embedding FROM qa").fetchall():
                    ev = _mem.blob_to_vec(r["embedding"])
                    if ev is not None and ev.shape == vec.shape and float(np.dot(vec, ev)) > dedupe_threshold:
                        self._conn.execute(
                            "UPDATE qa SET answer=?, created_at=?, last_used=? WHERE id=?",
                            (answer, now, now, r["id"]))
                        self._conn.commit()
                        return r["id"]
            cur = self._conn.execute(
                "INSERT INTO qa(question, answer, created_at, last_used, use_count, embedding) "
                "VALUES (?,?,?,?,0,?)", (question, answer, now, now, _mem.vec_to_blob(vec)))
            self._conn.commit()
            return cur.lastrowid

    def lookup(self, question):
        """Return (best_similarity, row_dict) for the closest cached question, or
        (0.0, None) if the cache is empty / embeddings unavailable."""
        rows = self._conn.execute("SELECT * FROM qa").fetchall()
        if not rows:
            return 0.0, None
        qv = _mem.embed_text(question)
        if qv is None:
            return 0.0, None
        best_s, best_r = 0.0, None
        for r in rows:
            ev = _mem.blob_to_vec(r["embedding"])
            if ev is None or ev.shape != qv.shape:
                continue
            s = float(np.dot(qv, ev))
            if s > best_s:
                best_s, best_r = s, r
        return best_s, (dict(best_r) if best_r is not None else None)

    def mark_used(self, qa_id):
        with self._lock:
            self._conn.execute(
                "UPDATE qa SET use_count=COALESCE(use_count,0)+1, last_used=? WHERE id=?",
                (datetime.now().isoformat(timespec="seconds"), qa_id))
            self._conn.commit()

    def count(self):
        return self._conn.execute("SELECT COUNT(*) AS c FROM qa").fetchone()["c"]

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass
