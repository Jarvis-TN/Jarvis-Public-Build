"""Tests for dynamic audio/camera device handling: resolving a saved device to a
present one (falling back to default when it's gone), and the picker/reset methods
updating config + re-opening the right device. Run: .venv\\Scripts\\python.exe tests\\test_devices.py"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import jarvis

jarvis.save_config_value = lambda *a, **k: None      # never touch the real config.json

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


def test_resolve_output_device():
    jarvis.list_output_devices = lambda: ["Speakers (Realtek)", "Jabra Headset (USB)"]
    assert jarvis.resolve_output_device("headset") == "Jabra Headset (USB)"
    assert jarvis.resolve_output_device("realtek") == "Speakers (Realtek)"
    assert jarvis.resolve_output_device(None) is None            # default
    assert jarvis.resolve_output_device("") is None
    assert jarvis.resolve_output_device("nonexistent dongle") is None   # gone -> default


def test_resolve_input_falls_back_when_absent():
    jarvis.list_input_devices = lambda: [(0, "Default Mic"), (1, "Yeti (USB)")]
    assert jarvis.resolve_input_device("yeti") == 1
    assert jarvis.resolve_input_device("unplugged webcam mic") is None  # not present -> default
    assert jarvis.resolve_input_device(None) is None


def _engine():
    e = jarvis.JarvisEngine.__new__(jarvis.JarvisEngine)
    e.cfg = {"input_device": "old", "output_device": "old", "camera_name": "old", "camera_index": 3}
    e.transcript_cb = lambda *a: None
    e.status_cb = lambda *a: None
    e._reinit_calls = []
    e._reinit_mixer = lambda dev=None, wait=False: (e._reinit_calls.append((dev, wait)) or True)
    e._reopen_calls = []
    e._reopen_input_stream = lambda: (e._reopen_calls.append(True) or True)
    return e


def test_set_output_device():
    jarvis.list_output_devices = lambda: ["Speakers (Realtek)", "Jabra Headset (USB)"]
    e = _engine()
    e.set_output_device("headset")
    assert e.cfg["output_device"] == "headset"
    assert e._reinit_calls == [("Jabra Headset (USB)", True)]     # reinit on the resolved device
    e.set_output_device(None)
    assert e.cfg["output_device"] is None
    assert e._reinit_calls[-1] == (None, True)                    # None -> system default


def test_set_camera_device():
    e = _engine()
    e.set_camera_device("Logitech")
    assert e.cfg["camera_name"] == "Logitech" and e.cfg["camera_index"] is None
    e.set_camera_device(None)                                     # auto
    assert e.cfg["camera_name"] == "" and e.cfg["camera_index"] is None


def test_reset_devices_to_default():
    e = _engine()
    e.reset_devices_to_default()
    assert e.cfg["input_device"] is None and e.cfg["output_device"] is None
    assert e.cfg["camera_name"] == "" and e.cfg["camera_index"] is None
    assert e._reopen_calls == [True]                             # mic reopened
    assert e._reinit_calls == [(None, True)]                     # speaker -> default


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            check(name, fn)
    total = _passed + _failed
    print(f"\n{_passed} passed, {_failed} failed, {total} total")
    sys.exit(1 if _failed else 0)
