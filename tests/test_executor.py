"""Tests for Phase 2, the task executor: the consequential-action gate, outcome
parsing, the task ledger, and the engine run loop (completes a job; blocks on a
consequential step). Run: .venv\\Scripts\\python.exe tests\\test_executor.py"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import jarvis_executor as EX

_passed = _failed = 0


def check(name, fn):
    global _passed, _failed
    try:
        fn()
        print(f"  PASS  {name}")
        _passed += 1
    except Exception as e:
        print(f"  FAIL  {name}: {e}")
        _failed += 1


# --- pure helpers ---------------------------------------------------------- #
def test_is_consequential():
    for n in ("send_email", "run_command", "edit_own_code", "restart_self",
              "browser_type", "mcp__playwright__browser_fill_form", "delete_file"):
        assert EX.is_consequential(n), n
    for n in ("create_document", "read_browser_page", "web_search", "get_calendar",
              "create_email_draft", "create_presentation", "media_control",
              "mcp__playwright__browser_snapshot"):
        assert not EX.is_consequential(n), n


def test_parse_outcome():
    assert EX.parse_outcome("DONE: built the deck")[0] == "done"
    assert EX.parse_outcome("DONE: built the deck")[1] == "built the deck"
    assert EX.parse_outcome("BLOCKED: I need your card")[0] == "blocked"
    assert EX.parse_outcome("still working on it")[0] is None


def test_ledger():
    led = EX.TaskLedger(path=os.path.join(tempfile.mkdtemp(), "tasks.json"))
    tid = led.open_task("build the Q3 deck", loop_id=7)
    led.add_step(tid, "create_presentation", "ok", "Deck.pptx exists")
    led.add_step(tid, "read_browser_page", "failed", "not connected")
    led.set_state(tid, "done", "deck built")
    t = led.get(tid)
    assert t["state"] == "done" and t["loop_id"] == 7 and len(t["steps"]) == 2
    assert "1 ok, 1 failed" in led.summary(tid)


# --- engine run loop ------------------------------------------------------- #
class _T:
    def __init__(self, text):
        self.type, self.text = "text", text


class _U:
    def __init__(self, name, inp, id="u1"):
        self.type, self.name, self.input, self.id = "tool_use", name, inp, id


class _Resp:
    def __init__(self, blocks):
        self.content, self.stop_reason = blocks, "end_turn"


class _Client:
    def __init__(self, scripted):
        self._q, self.messages = list(scripted), self

    def create(self, **k):
        return self._q.pop(0)


def _engine(scripted):
    import jarvis
    e = jarvis.JarvisEngine.__new__(jarvis.JarvisEngine)
    e.cfg = {"model": "m", "task_max_steps": 8, "task_allow_consequential": False,
             "agentic_max_tokens": 4096}
    e._running = True
    e._task_running = True                      # start_task would have set this
    e._client = _Client(scripted)
    e.tasks = EX.TaskLedger(path=os.path.join(tempfile.mkdtemp(), "tasks.json"))
    e._system_prompt = lambda: "SYS"
    e._pick_model = lambda diff, text: "m"
    e._all_tools = lambda: []
    e._dispatch_tool = lambda name, args: "ok, done"
    e._wrap_untrusted = lambda name, raw: raw
    e._verify_tool_outcome = lambda name, raw: ("ok", "")
    e._annotate_result_quality = lambda name, out, diff, status, detail: out
    e._get_openloops = lambda: None
    e.status_cb = lambda *a: None
    e.transcript_cb = lambda *a: None
    e._proposals = []
    e._propose_interruption = lambda **kw: e._proposals.append(kw)
    return e


def test_run_task_completes():
    e = _engine([
        _Resp([_U("create_document", {"title": "Notes", "content": "..."})]),
        _Resp([_T("DONE: created the notes document.")]),
    ])
    e._run_task("write up my notes")
    t = e.tasks.get(1)
    assert t["state"] == "done", t
    assert [s["action"] for s in t["steps"]] == ["create_document"]
    assert e._task_running is False
    assert e._proposals and e._proposals[0]["category"] == "task"
    assert "finished" in e._proposals[0]["speak"].lower()


def test_run_task_blocks_on_consequential():
    e = _engine([
        _Resp([_U("send_email", {"to": "x@y.com", "body": "hi"})]),     # not allowed
        _Resp([_T("BLOCKED: I need your OK to send that email.")]),
    ])
    e._run_task("email the vendor")
    t = e.tasks.get(1)
    assert t["state"] == "blocked", t
    step = t["steps"][0]
    assert step["action"] == "send_email" and step["status"] == "blocked"
    assert e._proposals and "paused" in e._proposals[0]["speak"].lower()


def test_start_task_guards():
    import jarvis
    e = jarvis.JarvisEngine.__new__(jarvis.JarvisEngine)
    e.cfg = {}
    e._client = object()
    e._task_running = True
    assert "already working" in e.start_task("do a thing")
    e._task_running = False
    e._client = None
    assert "brain" in e.start_task("do a thing")
    assert e.start_task("") == "What would you like me to work on, sir?"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            check(name, fn)
    total = _passed + _failed
    print(f"\n{_passed} passed, {_failed} failed, {total} total")
    sys.exit(1 if _failed else 0)
