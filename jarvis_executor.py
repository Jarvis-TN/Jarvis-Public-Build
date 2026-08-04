"""Task executor - the jump from an agent that ACTS to one that FINISHES.

Jarvis's conversational loop fires a handful of tool calls inside one turn and
stops. Open loops are follow-up reminders. Neither actually WORKS a job to
completion. This module is the cold, testable substrate for one that does:

  * TaskLedger  - a persistent, step-by-step record of a task (goal, each action
                  and its verified outcome, final state). Survives across sessions
                  so a task can be resumed and reported on.
  * is_consequential() - the safety boundary: which tool calls change external
                  state (send / delete / purchase / run commands / self-edit /
                  browser data-entry) and therefore may NOT run autonomously. The
                  executor stops and asks rather than doing these on its own.
  * parse_outcome() - read the model's terminal signal: DONE: / BLOCKED: / neither.

The RUN loop itself lives in the engine (it needs the model + tool dispatch +
Phase-1 verification). This module stays pure: no model, no network.
"""

import os
import json
import threading
from datetime import datetime

APP_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORY_DIR = os.path.join(APP_DIR, "memory")
TASKS_PATH = os.path.join(MEMORY_DIR, "tasks.json")

# System directive appended to the base prompt while a task is being executed.
EXECUTOR_DIRECTIVE = (
    "\n\n--- TASK EXECUTION MODE ---\n"
    "You are now working AUTONOMOUSLY to COMPLETE a multi-step task for the user - "
    "this is not a conversation. Use your tools to actually get it done, step by step. "
    "After a tool result the system may append a [verification: ...] note; take it "
    "seriously - if a step FAILED, try a different approach ONCE, and if it still fails "
    "or you are stuck, stop. Keep going across as many tool calls as it takes. Do NOT "
    "ask the user questions mid-task and do NOT narrate every step aloud. Some actions "
    "change external state (sending, deleting, purchasing, running system commands, "
    "editing your own code, entering data into web forms) - you may NOT do those "
    "autonomously; if the task needs one, stop and report it. When the goal is FULLY "
    "achieved, reply with ONE line starting 'DONE:' then a one-sentence summary. If you "
    "cannot proceed without the user (approval, missing info, or a consequential step), "
    "reply with ONE line starting 'BLOCKED:' then exactly what you need from them."
)

# Tool basenames that change external state -> never run autonomously.
_CONSEQUENTIAL = {
    "send_email", "run_command", "write_own_code", "edit_own_code",
    "run_own_code", "restart_self",
}
_BROWSER_ENTRY = {
    "browser_type", "browser_fill_form", "browser_select_option",
    "browser_file_upload", "browser_run_code_unsafe", "browser_press_key",
    "browser_handle_dialog",
}
_CONSEQUENTIAL_PREFIXES = (
    "send_", "delete_", "remove_", "purchase_", "buy_", "pay_",
    "transfer_", "publish_", "post_",
)


def is_consequential(name):
    """True if a tool call would change external state and so must be approved by
    the user rather than run by the executor on its own. Handles MCP-namespaced
    names (mcp__server__tool) by looking at the bare tool name."""
    base = (name or "").split("__")[-1]
    if base in _CONSEQUENTIAL or base in _BROWSER_ENTRY:
        return True
    return base.startswith(_CONSEQUENTIAL_PREFIXES)


def parse_outcome(text):
    """Read the model's terminal signal from a final (no-tool) message.
    Returns (state, summary): state is 'done', 'blocked', or None (not terminal)."""
    t = (text or "").strip()
    up = t.upper()
    if "DONE:" in up:
        return "done", t[up.index("DONE:") + 5:].strip() or "completed"
    if "BLOCKED:" in up:
        return "blocked", t[up.index("BLOCKED:") + 8:].strip() or "need your input"
    return None, t


class TaskLedger:
    def __init__(self, path=TASKS_PATH):
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
                    d.setdefault("tasks", [])
                    d.setdefault("next_id", 1)
                    return d
            except Exception:
                pass
        return {"tasks": [], "next_id": 1}

    def _save(self):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            pass

    def open_task(self, goal, loop_id=None):
        with self._lock:
            tid = self._data["next_id"]
            self._data["next_id"] = tid + 1
            self._data["tasks"].append({
                "id": tid, "goal": (goal or "").strip(), "loop_id": loop_id,
                "state": "running", "result": "",
                "created": datetime.now().isoformat(timespec="seconds"),
                "updated": datetime.now().isoformat(timespec="seconds"),
                "steps": []})
            self._data["tasks"] = self._data["tasks"][-100:]
            self._save()
            return tid

    def _get(self, tid):
        for t in self._data["tasks"]:
            if t["id"] == tid:
                return t
        return None

    def add_step(self, tid, action, status, detail=""):
        with self._lock:
            t = self._get(tid)
            if t is not None:
                t["steps"].append({
                    "ts": datetime.now().isoformat(timespec="seconds"),
                    "action": action, "status": status, "detail": detail})
                t["updated"] = datetime.now().isoformat(timespec="seconds")
                self._save()

    def set_state(self, tid, state, result=""):
        with self._lock:
            t = self._get(tid)
            if t is not None:
                t["state"] = state
                t["result"] = result
                t["updated"] = datetime.now().isoformat(timespec="seconds")
                self._save()

    def get(self, tid):
        t = self._get(tid)
        return dict(t) if t else None

    def steps(self, tid):
        t = self._get(tid)
        return list(t["steps"]) if t else []

    def summary(self, tid):
        t = self._get(tid)
        if not t:
            return ""
        ok = sum(1 for s in t["steps"] if s["status"] == "ok")
        failed = sum(1 for s in t["steps"] if s["status"] == "failed")
        return (f"task {tid} [{t['state']}]: {t['goal']} - "
                f"{len(t['steps'])} steps ({ok} ok, {failed} failed)")
