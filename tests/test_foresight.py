"""Tests for foresight: the scheduling gate, the learning store, and the engine's
reason-then-propose flow (PASS = stay silent; a line = propose via the broker).
Run: .venv\\Scripts\\python.exe tests\\test_foresight.py"""

import os
import sys
import time
import tempfile
import threading
from collections import deque
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import jarvis_foresight as fs

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


# --- scheduling gate ------------------------------------------------------- #
def test_due_gate():
    now = datetime(2026, 7, 22, 10, 0)                      # 10:00, in active hours
    assert fs.due(now, 0, 45, 8, 22) is True                # never run -> due
    assert fs.due(now, now.timestamp() - 10 * 60, 45, 8, 22) is False   # only 10 min ago
    assert fs.due(now, now.timestamp() - 60 * 60, 45, 8, 22) is True    # 60 min ago
    early = datetime(2026, 7, 22, 6, 0)
    assert fs.due(early, 0, 45, 8, 22) is False             # before active hours
    late = datetime(2026, 7, 22, 23, 0)
    assert fs.due(late, 0, 45, 8, 22) is False              # after active hours


def test_due_gate_wraps_midnight():
    assert fs.due(datetime(2026, 7, 22, 23, 0), 0, 45, 22, 6) is True   # night window
    assert fs.due(datetime(2026, 7, 22, 12, 0), 0, 45, 22, 6) is False


# --- store + learning loop ------------------------------------------------- #
def _store():
    return fs.ForesightStore(path=os.path.join(tempfile.mkdtemp(), "foresight.json"))


def test_store_record_dedup_and_outcomes():
    s = _store()
    line = "Your deadline is tomorrow, sir - shall I start the draft?"
    k = fs.key_for(line)
    assert not s.already_today(k)
    s.record(line, k)
    assert s.already_today(k) and s.count() == 1
    assert line in s.recent_summaries()
    assert "surfaced" in s.outcomes_digest()
    s.mark_outcome(k, "engaged")
    assert "engaged" in s.outcomes_digest() and "surfaced" not in s.outcomes_digest()


def test_key_is_stable():
    assert fs.key_for("Hello there") == fs.key_for("hello there ")   # normalized + stable


# --- engine reason-then-propose -------------------------------------------- #
class _Block:
    def __init__(self, text):
        self.type, self.text = "text", text


class _Resp:
    def __init__(self, text):
        self.content = [_Block(text)]


class _Client:
    def __init__(self, text):
        self._text = text
        self.messages = self

    def create(self, **k):
        return _Resp(self._text)


def _engine(reply_text):
    import jarvis
    e = jarvis.JarvisEngine.__new__(jarvis.JarvisEngine)
    e.cfg = {"model": "claude-sonnet-5", "foresight_interval_minutes": 45, "foresight_priority": 45}
    e.history = [{"role": "user", "content": "remind me about the Q3 deck"}]
    e.context = {"state": "available", "app": None}
    e._attention_lock = threading.Lock()
    e._attention_q = deque()
    e._client = _Client(reply_text)
    e._get_foresight = lambda: _store()
    e._get_openloops = lambda: None
    e._get_patterns = lambda: None
    e._get_memdb = lambda: None
    e.transcript_cb = lambda *a: None
    e._last_foresight_key = None
    e._last_foresight_ts = 0.0
    return e


def test_pass_stays_silent():
    e = _engine("PASS")
    e._run_foresight()
    assert len(e._attention_q) == 0


def test_line_is_proposed_via_broker():
    e = _engine("Your Q3 deck deadline is tomorrow, sir - shall I start it?")
    e._run_foresight()
    assert len(e._attention_q) == 1
    cand = e._attention_q[0]
    assert cand["category"] == "foresight"
    assert "deadline" in cand["speak"].lower()
    # firing it records to the store and arms engagement tracking
    cand["on_fire"]()
    assert e._last_foresight_key and e._last_foresight_ts > 0


def test_bg_think_prefers_local_then_cloud():
    import jarvis
    import jarvis_local_llm
    e = jarvis.JarvisEngine.__new__(jarvis.JarvisEngine)
    e.cfg = {"model": "claude-sonnet-5", "local_llm_base_url": "http://x/v1",
             "local_llm_model": "m", "local_llm_api_key": "k", "local_llm_temperature": 0.6}
    e._client = _Client("CLOUD ANSWER")
    orig_chat = jarvis_local_llm.chat
    jarvis_local_llm.chat = lambda *a, **k: {"choices": [{"message": {"content": "LOCAL ANSWER"}}]}
    try:
        e._local_llm_available = lambda: True          # local reachable -> use it
        assert e._bg_think(None, "hi", 50) == "LOCAL ANSWER"
        assert e._bg_brain_available() is True
        e._local_llm_available = lambda: False         # no local -> cloud fallback
        assert e._bg_think(None, "hi", 50) == "CLOUD ANSWER"
        e._client = None                               # no brain at all -> empty
        assert e._bg_think(None, "hi", 50) == ""
        assert e._bg_brain_available() is False
    finally:
        jarvis_local_llm.chat = orig_chat


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            check(name, fn)
    total = _passed + _failed
    print(f"\n{_passed} passed, {_failed} failed, {total} total")
    sys.exit(1 if _failed else 0)
