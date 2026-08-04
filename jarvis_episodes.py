"""Jarvis episodic memory - autobiographical recall of past conversations by TIME.

The flat conversation log has no per-turn timestamps, so "what did we talk about
last Tuesday / this morning" is unanswerable over it. This module segments the
conversation into time-stamped EPISODES (a short summary + when it happened + a
semantic embedding) as they occur, and answers time-scoped questions by parsing a
natural timeframe ("today", "yesterday", "last week", "last tuesday", "3 days
ago") into a date range and returning the episodes that fall in it - optionally
ranked by a semantic query too.

SQLite at memory/episodes.db; reuses jarvis_memory's shared embedder (no extra
model load). Cold-testable (no engine/network).
"""

import os
import sqlite3
import threading
from datetime import datetime, timedelta

import numpy as np

import jarvis_memory as _mem   # shared embedder + blob helpers

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "memory", "episodes.db")

_WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
             "friday": 4, "saturday": 5, "sunday": 6}


class EpisodeStore:
    def __init__(self, path=DB_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_ts TEXT, end_ts TEXT,
                summary TEXT NOT NULL,
                participants TEXT DEFAULT 'the user',
                turn_count INTEGER DEFAULT 0,
                embedding BLOB
            )
        """)
        self._conn.commit()

    def add(self, summary, start_ts, end_ts, participants="the user", turn_count=0):
        summary = (summary or "").strip()
        if not summary:
            return None
        vec = _mem.embed_text(summary)
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO episodes(start_ts,end_ts,summary,participants,turn_count,embedding) "
                "VALUES (?,?,?,?,?,?)",
                (start_ts, end_ts, summary, participants, int(turn_count),
                 _mem.vec_to_blob(vec)))
            self._conn.commit()
            return cur.lastrowid

    def count(self):
        return self._conn.execute("SELECT COUNT(*) AS c FROM episodes").fetchone()["c"]

    def search(self, query="", since=None, until=None, k=8):
        """Episodes in the [since, until] window (ISO strings, inclusive-ish),
        ranked by semantic similarity to `query` if given, else newest-first.
        Returns [{id,start,end,summary,participants,score}]."""
        rows = self._conn.execute("SELECT * FROM episodes").fetchall()
        out = []
        for r in rows:
            st = r["start_ts"] or r["end_ts"] or ""
            if since and st < since:
                continue
            if until and st > until:
                continue
            out.append(r)
        qv = _mem.embed_text(query) if query and query.strip() else None
        scored = []
        for r in out:
            score = 0.0
            if qv is not None:
                ev = _mem.blob_to_vec(r["embedding"])
                if ev is not None and ev.shape == qv.shape:
                    score = float(np.dot(qv, ev))
            scored.append((score, r))
        if qv is not None:
            scored.sort(key=lambda x: -x[0])
        else:
            scored.sort(key=lambda x: (x[1]["start_ts"] or ""), reverse=True)
        return [{"id": r["id"], "start": r["start_ts"], "end": r["end_ts"],
                 "summary": r["summary"], "participants": r["participants"],
                 "score": round(s, 3)} for s, r in scored[:k]]

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass


def parse_timeframe(text, now=None):
    """Turn a natural timeframe phrase into (since_iso, until_iso). Either bound
    may be None (open). Returns (None, None) if no timeframe is recognised."""
    now = now or datetime.now()
    t = (text or "").lower().strip()
    if not t:
        return (None, None)
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)

    def iso(d):
        return d.isoformat(timespec="seconds")

    def span(start, end):
        return (iso(start), iso(end))

    if "today" in t:
        return span(day, now)
    if "yesterday" in t:
        return span(day - timedelta(days=1), day)
    if "this morning" in t:
        return span(day, day.replace(hour=12))
    if "this afternoon" in t:
        return span(day.replace(hour=12), day.replace(hour=17))
    if "this evening" in t or "tonight" in t:
        return span(day.replace(hour=17), now)
    if "last week" in t:
        this_mon = day - timedelta(days=day.weekday())
        return span(this_mon - timedelta(days=7), this_mon)
    if "this week" in t:
        return span(day - timedelta(days=day.weekday()), now)
    if "last month" in t:
        return span(day - timedelta(days=30), day - timedelta(days=0))
    # "N days/weeks ago"
    import re
    m = re.search(r"(\d+)\s+(day|week)s?\s+ago", t)
    if m:
        n = int(m.group(1)) * (7 if m.group(2) == "week" else 1)
        d = day - timedelta(days=n)
        return span(d, d + timedelta(days=1))
    if "a few days ago" in t or "the other day" in t:
        return span(day - timedelta(days=4), day - timedelta(days=1))
    # "last <weekday>" / "<weekday>"
    for name, wd in _WEEKDAYS.items():
        if name in t:
            back = (day.weekday() - wd) % 7
            if back == 0:
                back = 7 if "last" in t else 0
            elif "last" in t and back < 7:
                pass  # most recent past occurrence
            target = day - timedelta(days=back)
            return span(target, target + timedelta(days=1))
    if "recently" in t or "lately" in t or "earlier" in t:
        return (iso(day - timedelta(days=7)), None)
    return (None, None)
