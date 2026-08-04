"""Post-action verification - a machine-readable outcome for every tool call.

Jarvis's tools answer in natural language ("I've created 'X.docx'...", "I couldn't
read that page, sir"). That reads well but tells the ENGINE nothing, so nothing
downstream can distinguish success from failure. This module classifies each tool
result as ok / failed / unknown so the rest of the system can act on it:

  * the model gets an explicit note when a call FAILED and can retry in the same
    turn instead of compounding the error,
  * a per-tool reliability record accumulates (ToolStats) - the track record the
    task executor (Phase 2) and earned autonomy (Phase 3) are built on.

Pure and local: phrase analysis plus a cheap filesystem check when a result names
a file it claims to have written. No model, no network.

Safety note: phrases are matched only against the HEAD of a result, because
content-returning tools (read_webpage, read_browser_page, web_search) hand back
arbitrary text that may contain words like "failed" deep inside. Tool errors are
short and come first; page content does not.
"""

import os
import re
import json
import threading
from datetime import datetime

APP_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORY_DIR = os.path.join(APP_DIR, "memory")
STATS_PATH = os.path.join(MEMORY_DIR, "tool_stats.json")

OK, FAILED, UNKNOWN = "ok", "failed", "unknown"
HEAD = 160          # only the first N chars are treated as a status message

_FAIL_PATTERNS = (
    "i couldn't", "couldn't", "i can't", "i'm afraid", "(tool error)",
    "unknown tool", "failed", "unavailable", "isn't available", "isn't installed",
    "isn't connected", "not connected", "not found", "no such", "didn't get written",
    "came out empty", "wasn't able", "no results", "nothing on that", "i won't",
    "refus", "denied", "not authorized", "no reply",
)
_OK_PATTERNS = (
    "i've created", "i've put together", "i've drawn up", "i've added",
    "i've made", "i've written", "i've sent", "done, sir", "saved",
    "opened it for you", "sent '", "sent to your", "i've closed",
)

_FILE_RE = re.compile(r"'([^'\\/:*?\"<>|]+\.[A-Za-z0-9]{2,5})'")
_DIR_RE = re.compile(r"([A-Za-z]:\\[^\s'\"]+)")


def _first_line(text, n=120):
    return (text.strip().splitlines() or [""])[0][:n]


def _verify_named_file(text):
    """If a result names both a file and a directory, confirm the file really
    exists and is non-empty. Returns a short detail string, or ''."""
    m, d = _FILE_RE.search(text), _DIR_RE.search(text)
    if not m or not d:
        return ""
    try:
        path = os.path.join(d.group(1).rstrip("\\"), m.group(1))
        if os.path.isfile(path):
            size = os.path.getsize(path)
            if size > 0:
                return f"{m.group(1)} exists ({size} bytes)"
    except Exception:
        pass
    return ""


def classify(tool_name, result):
    """Classify a tool result -> (status, detail). Never raises."""
    try:
        if result is None:
            return FAILED, "no result"
        if not isinstance(result, str):
            return UNKNOWN, ""          # image/content blocks - nothing to read
        text = result.strip()
        if len(text) < 3:
            return FAILED, "empty result"
        # Strongest evidence: the artifact it claims to have written is really there.
        detail = _verify_named_file(text)
        if detail:
            return OK, detail
        head = text[:HEAD].lower()
        if any(p in head for p in _FAIL_PATTERNS):
            return FAILED, _first_line(text)
        if any(p in head for p in _OK_PATTERNS):
            return OK, ""
        return UNKNOWN, ""
    except Exception:
        return UNKNOWN, ""


def annotate(out, status, detail=""):
    """Append a short note so the model can self-correct in the same turn. Only
    annotates on failure (or a positively verified artifact) - staying silent
    otherwise keeps the added token cost at essentially zero."""
    if not isinstance(out, str):
        return out
    if status == FAILED:
        return out + ("\n[verification: this tool call did NOT succeed"
                      + (f" ({detail})" if detail else "")
                      + ". Do not treat it as done - try a different approach or "
                        "tell the user plainly.]")
    if status == OK and detail:
        return out + f"\n[verification: confirmed - {detail}.]"
    return out


class ToolStats:
    """Per-tool reliability track record - how often each tool actually works."""

    def __init__(self, path=STATS_PATH):
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
                    d.setdefault("tools", {})
                    return d
            except Exception:
                pass
        return {"tools": {}}

    def _save(self):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            pass

    def record(self, tool, status):
        if status not in (OK, FAILED, UNKNOWN):
            status = UNKNOWN
        with self._lock:
            t = self._data["tools"].setdefault(tool, {"ok": 0, "failed": 0, "unknown": 0})
            t[status] = int(t.get(status, 0)) + 1
            t["last"] = datetime.now().isoformat(timespec="seconds")
            t["last_status"] = status
            self._save()

    def reliability(self, tool):
        """-> (decided, ok, failed, success_rate); 'unknown' outcomes don't count."""
        t = self._data["tools"].get(tool) or {}
        ok, failed = int(t.get("ok", 0)), int(t.get("failed", 0))
        decided = ok + failed
        return decided, ok, failed, (ok / decided if decided else 0.0)

    def summary(self, min_attempts=1, limit=12):
        rows = []
        for name in sorted(self._data["tools"]):
            decided, ok, failed, rate = self.reliability(name)
            if decided >= min_attempts:
                rows.append(f"- {name}: {ok}/{decided} ok ({rate:.0%})"
                            + (f", {failed} failed" if failed else ""))
        return "\n".join(rows[:limit])
