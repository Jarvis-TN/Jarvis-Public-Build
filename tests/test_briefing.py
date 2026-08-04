"""Tests for the startup briefing flow: intro first, THEN an opt-in day recap
(ask-first), vs the legacy merged greeting+recap.
Run: .venv\\Scripts\\python.exe tests\\test_briefing.py"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import jarvis

jarvis._save_json = lambda *a, **k: None          # never touch real memory files in tests

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


def _skeleton(ask_recap):
    e = jarvis.JarvisEngine.__new__(jarvis.JarvisEngine)
    e.cfg = {"briefing_ask_recap": ask_recap, "face_auth_enabled": False,
             "assistant_name": "Jarvis", "briefing_location": "", "max_history_turns": 10}
    e._pending_approval = None
    e.history = []
    e._flush_queue = lambda: None
    return e


def test_ask_first_intro_then_offer():
    e = _skeleton(ask_recap=True)
    events = []
    e._boot_intro = lambda: events.append("intro")
    e._mark_briefed_today = lambda: events.append("marked")
    spoken = []
    e.speak = lambda t: spoken.append(t)
    e._daily_briefing()
    # introduction happens first, and today's opener is marked done
    assert events == ["intro", "marked"], events
    # a recap is OFFERED (spoken question), not delivered
    assert spoken and "recap of the rest of your day" in spoken[0].lower(), spoken
    # the spoken yes/no gate is armed to fire the recap on a 'yes'
    assert e._pending_approval is not None
    assert e._pending_approval["fulfill"] == e._deliver_day_recap
    assert e._pending_approval["trigger"] == "briefing"


def test_intro_text_is_greeting_plus_datetime_only():
    e = _skeleton(ask_recap=True)
    spoken = []
    e.speak = lambda t: spoken.append(t)
    e.greeted_name = ""
    e._boot_intro()                                   # real intro
    line = spoken[0]
    assert "online and at your service" in line       # the introduction
    assert "the time is" in line.lower()              # date + time headline
    # the intro must NOT contain recap content (weather/news/headlines)
    low = line.lower()
    assert "weather" not in low and "headline" not in low and "news" not in low


def test_legacy_merged_when_disabled():
    e = _skeleton(ask_recap=False)
    events = []
    e._boot_intro = lambda: events.append("intro")     # should NOT be called
    e._mark_briefed_today = lambda: None
    e._system_prompt = lambda: "sys"
    e._agentic_respond = lambda s, sent: "merged briefing text"
    e.status_cb = lambda *a: None
    e.transcript_cb = lambda *a: None

    class _FX:
        def start_hum(self): pass
        def stop_hum(self): pass
    e.fx = _FX()
    e._daily_briefing()
    assert "intro" not in events                       # no separate intro path
    assert e._pending_approval is None                 # no opt-in gate armed


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            check(name, fn)
    total = _passed + _failed
    print(f"\n{_passed} passed, {_failed} failed, {total} total")
    sys.exit(1 if _failed else 0)
