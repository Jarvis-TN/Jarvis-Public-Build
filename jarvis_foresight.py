"""Jarvis foresight store - the substrate for anticipatory, unprompted help.

Foresight = quietly looking ahead and surfacing ONE genuinely useful thing the
user didn't ask for, by connecting their goals, habits, calendar and recent work.
This module is the cold, testable part: a pure scheduling gate plus a small
JSON-backed store that records every nudge Jarvis surfaces and HOW IT LANDED
(engaged vs ignored). That track record is fed back into the reasoner so Jarvis
gets better over time at what's actually worth interrupting for - the "learning
to help" loop. No model, no network here; the engine does the reasoning.
"""

import os
import json
import hashlib
import threading
from datetime import datetime, date

APP_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORY_DIR = os.path.join(APP_DIR, "memory")
FORESIGHT_PATH = os.path.join(MEMORY_DIR, "foresight.json")


def key_for(line):
    """A stable dedup key for a foresight line (stable across restarts)."""
    return "fs:" + hashlib.sha1((line or "").strip().lower().encode("utf-8")).hexdigest()[:12]


def due(now, last_run_ts, interval_minutes, active_start_hour=8, active_end_hour=22):
    """True if a foresight pass should run: within active hours AND at least
    `interval_minutes` since the last. `now` is a datetime; last_run_ts is epoch.
    active_start/end may wrap midnight (e.g. 22..6)."""
    h = now.hour
    if active_start_hour <= active_end_hour:
        in_hours = active_start_hour <= h < active_end_hour
    else:
        in_hours = h >= active_start_hour or h < active_end_hour
    if not in_hours:
        return False
    return (now.timestamp() - float(last_run_ts or 0)) >= float(interval_minutes) * 60.0


class ForesightStore:
    def __init__(self, path=FORESIGHT_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._data = self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    d = json.load(f)
                if isinstance(d, dict):
                    d.setdefault("log", [])
                    return d
            except Exception:
                pass
        return {"log": []}

    def _save(self):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            pass

    def recent_summaries(self, n=8):
        return [e.get("summary", "") for e in self._data["log"][-n:] if e.get("summary")]

    def already_today(self, key):
        today = date.today().isoformat()
        return any(e.get("key") == key and e.get("day") == today for e in self._data["log"])

    def record(self, summary, key, outcome="surfaced"):
        with self._lock:
            self._data["log"].append({
                "ts": datetime.now().isoformat(timespec="seconds"),
                "day": date.today().isoformat(),
                "summary": summary, "key": key, "outcome": outcome})
            self._data["log"] = self._data["log"][-200:]         # keep the file small
            self._save()

    def mark_outcome(self, key, outcome):
        with self._lock:
            for e in reversed(self._data["log"]):
                if e.get("key") == key:
                    e["outcome"] = outcome
                    self._save()
                    return

    def outcomes_digest(self, n=12):
        """Recent nudges and how they landed - fed back so the reasoner prefers the
        kinds that engaged and avoids the kinds that were ignored."""
        rows = [e for e in self._data["log"] if e.get("summary")][-n:]
        return "\n".join(f'- "{e["summary"]}" -> {e.get("outcome", "surfaced")}' for e in rows)

    def count(self):
        return len(self._data["log"])
