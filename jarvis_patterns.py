"""Jarvis behavioural pattern store - the substrate for predictive pre-fetch.

Every meaningful thing the user does (currently: which intent-bearing tool they
trigger, e.g. checking the weather or their calendar) is logged with a timestamp.
`detect()` then mines that log for RECURRING, TIME-CLUSTERED routines - e.g. "checks
the weather most mornings around 8" - so Jarvis can surface that information just
before the user would normally ask for it.

Local SQLite only; no network, no embeddings. Cheap and fully offline.
"""

import os
import sqlite3
import threading
from datetime import datetime, date

APP_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORY_DIR = os.path.join(APP_DIR, "memory")
DB_PATH = os.path.join(MEMORY_DIR, "patterns.db")


def _hour_frac(dt):
    return dt.hour + dt.minute / 60.0 + dt.second / 3600.0


class PatternStore:
    def __init__(self, path=DB_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        with self._lock:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS activity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,          -- ISO timestamp
                    day TEXT NOT NULL,         -- YYYY-MM-DD (for distinct-day counting)
                    weekday INTEGER NOT NULL,  -- 0=Mon .. 6=Sun
                    hour REAL NOT NULL,        -- fractional hour of day [0,24)
                    topic TEXT NOT NULL,       -- short intent label, e.g. 'weather'
                    detail TEXT DEFAULT ''
                )
            """)
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS fired (
                    topic TEXT NOT NULL,
                    day TEXT NOT NULL,
                    PRIMARY KEY (topic, day)
                )
            """)
            self._conn.commit()

    # ---- writes --------------------------------------------------------- #
    def log(self, topic, detail="", ts=None):
        """Record one occurrence of `topic` at time `ts` (default: now)."""
        topic = (topic or "").strip().lower()
        if not topic:
            return
        dt = ts or datetime.now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO activity(ts, day, weekday, hour, topic, detail) VALUES (?,?,?,?,?,?)",
                (dt.isoformat(timespec="seconds"), dt.strftime("%Y-%m-%d"),
                 dt.weekday(), _hour_frac(dt), topic, (detail or "").strip()),
            )
            self._conn.commit()

    def mark_fired(self, topic, day=None):
        day = day or date.today().strftime("%Y-%m-%d")
        with self._lock:
            self._conn.execute("INSERT OR IGNORE INTO fired(topic, day) VALUES (?,?)",
                               (topic.lower(), day))
            self._conn.commit()

    def was_fired(self, topic, day=None):
        day = day or date.today().strftime("%Y-%m-%d")
        row = self._conn.execute("SELECT 1 FROM fired WHERE topic=? AND day=?",
                                 (topic.lower(), day)).fetchone()
        return row is not None

    def wipe(self):
        with self._lock:
            self._conn.execute("DELETE FROM activity")
            self._conn.execute("DELETE FROM fired")
            self._conn.commit()

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass

    # ---- reads ---------------------------------------------------------- #
    def count(self):
        return self._conn.execute("SELECT COUNT(*) AS c FROM activity").fetchone()["c"]

    def _mean_std(self, xs):
        n = len(xs)
        m = sum(xs) / n
        var = sum((x - m) ** 2 for x in xs) / n
        return m, var ** 0.5

    def detect(self, min_occurrences=3, min_distinct_days=3, hour_tolerance=1.5):
        """Mine the activity log for recurring, time-clustered routines.

        A topic qualifies if it occurred at least `min_occurrences` times across at
        least `min_distinct_days` distinct days, AND those occurrences cluster in
        time (std-dev of the hour-of-day <= `hour_tolerance`). Returns a list of
        dicts sorted by confidence (high first):
            {topic, typical_hour, occurrences, distinct_days, spread, confidence}
        `typical_hour` is the mean hour-of-day (fractional); pair it with a lead
        window to decide when to pre-fetch.
        """
        rows = self._conn.execute("SELECT topic, day, hour FROM activity").fetchall()
        by_topic = {}
        for r in rows:
            by_topic.setdefault(r["topic"], []).append((r["day"], r["hour"]))

        out = []
        for topic, entries in by_topic.items():
            occ = len(entries)
            days = {d for d, _ in entries}
            if occ < min_occurrences or len(days) < min_distinct_days:
                continue
            hours = [h for _, h in entries]
            mean, std = self._mean_std(hours)
            if std > hour_tolerance:
                continue  # happens at all sorts of times -> not a time routine
            # confidence: more occurrences + more distinct days + tighter clustering
            tightness = max(0.0, 1.0 - std / hour_tolerance)       # 1=perfectly tight
            volume = min(1.0, len(days) / 7.0)                      # a week of days -> full
            confidence = round(0.5 * tightness + 0.5 * volume, 3)
            out.append({
                "topic": topic,
                "typical_hour": round(mean, 3),
                "occurrences": occ,
                "distinct_days": len(days),
                "spread": round(std, 3),
                "confidence": confidence,
            })
        out.sort(key=lambda p: -p["confidence"])
        return out

    def due_now(self, lead_minutes=20, min_confidence=0.5, now=None,
                quiet_before_hour=6, **detect_kwargs):
        """Patterns whose typical time is within the next `lead_minutes` (or just
        passed within a short grace window) right now, above the confidence bar,
        and not already fired today. Returns them most-confident first."""
        now = now or datetime.now()
        nowh = _hour_frac(now)
        today = now.strftime("%Y-%m-%d")
        lead = lead_minutes / 60.0
        grace = 10.0 / 60.0  # also fire if we're up to 10 min past the typical time
        due = []
        for p in self.detect(**detect_kwargs):
            if p["confidence"] < min_confidence:
                continue
            if p["typical_hour"] < quiet_before_hour:
                continue
            delta = p["typical_hour"] - nowh
            if -grace <= delta <= lead and not self.was_fired(p["topic"], today):
                due.append(p)
        return due
