"""Tests for the context sensor, the attention broker's context gating, and the
weekday daily-brief schedule. Run: .venv\\Scripts\\python.exe tests\\test_context.py"""

import os
import sys
import threading
from collections import deque
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import jarvis_context as ctx

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


# --- jarvis_context pure helpers ------------------------------------------- #
def test_looks_busy():
    assert ctx.looks_busy("zoom.exe", "Zoom Meeting")
    assert ctx.looks_busy("chrome.exe", "Zoom Meeting - Google Chrome")
    assert ctx.looks_busy("POWERPNT.EXE", "Deck - PowerPoint Slide Show")
    assert ctx.looks_busy("x.exe", "y", extra_apps=["x.exe"])
    assert not ctx.looks_busy("chrome.exe", "Gmail - Inbox")
    assert not ctx.looks_busy(None, None)


def test_availability():
    assert ctx.availability(10, False, False) == "available"
    assert ctx.availability(999, False, False, away_idle_seconds=300) == "away"
    assert ctx.availability(10, True, False) == "away"        # locked overrides
    assert ctx.availability(10, False, True) == "busy"


def test_sample_never_raises():
    snap = ctx.sample()
    assert isinstance(snap, dict)
    assert snap.get("state") in ("available", "busy", "away")
    for k in ("app", "title", "idle", "locked", "busy"):
        assert k in snap


# --- engine: schedule + broker (imports the heavy engine module) ----------- #
def _engine():
    import jarvis
    return jarvis.JarvisEngine


def test_parse_hhmm():
    E = _engine()
    assert E._parse_hhmm("16:00") == (16, 0)
    assert E._parse_hhmm("9:5") == (9, 5)
    assert E._parse_hhmm("bad") == (16, 0)
    assert E._parse_hhmm("25:61") == (16, 0)


def test_daily_brief_due():
    E = _engine()
    wd = datetime(2026, 7, 8, 16, 30)
    while wd.weekday() >= 5:
        wd += timedelta(days=1)
    we = datetime(2026, 7, 8, 16, 30)
    while we.weekday() < 5:
        we += timedelta(days=1)
    today = wd.strftime("%Y-%m-%d")
    assert E._daily_brief_due(wd, None, 16, 0, 120) is True
    assert E._daily_brief_due(wd, today, 16, 0, 120) is False
    assert E._daily_brief_due(wd.replace(hour=15), None, 16, 0, 120) is False
    assert E._daily_brief_due(wd.replace(hour=18, minute=30), None, 16, 0, 120) is False
    assert E._daily_brief_due(we, None, 16, 0, 120) is False


def _skeleton(state, locked=False):
    E = _engine()
    e = E.__new__(E)
    e._attention_lock = threading.Lock()
    e._attention_q = deque()
    e._last_proactive_ts = 0.0
    e._paused = False
    e.state = "idle"
    e.mute_reason = ""
    e.current_affect = None
    e.context = {"state": state, "locked": locked}
    e.cfg = {"proactive_min_gap_seconds": 45, "context_awareness_enabled": True,
             "context_busy_gap_mult": 3.0, "context_busy_min_priority": 80,
             "proactive_defer_when_locked": True, "proactive_quiet_before_hour": 0}
    return e


def _queue(e, key, pri):
    fired = []
    e._propose_interruption(category=key, priority=pri, key=key,
                            fulfill=lambda: fired.append(key))
    return fired


def test_available_fires_highest():
    e = _skeleton("available")
    lo, hi = _queue(e, "low", 20), _queue(e, "high", 90)
    e._attention_tick()
    assert hi == ["high"] and lo == []


def test_busy_defers_low_keeps_high():
    e = _skeleton("busy")
    lo, hi = _queue(e, "low", 50), _queue(e, "high", 90)
    e._attention_tick()
    assert hi == ["high"]
    assert lo == [] and any(c["key"] == "low" for c in e._attention_q)


def test_busy_only_low_fires_nothing():
    e = _skeleton("busy")
    lo = _queue(e, "low", 50)
    assert e._attention_tick() is None and lo == []
    assert any(c["key"] == "low" for c in e._attention_q)


def test_locked_defers_everything():
    e = _skeleton("away", locked=True)
    hi = _queue(e, "high", 95)
    assert e._attention_tick() is None and hi == []
    assert any(c["key"] == "high" for c in e._attention_q)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            check(name, fn)
    total = _passed + _failed
    print(f"\n{_passed} passed, {_failed} failed, {total} total")
    sys.exit(1 if _failed else 0)
