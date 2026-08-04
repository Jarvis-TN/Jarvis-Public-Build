"""Tests for gesture-control logic: the pure debounce/swipe math + event parsing
(jarvis_vision), and the engine's gesture->action routing.
Run: .venv\\Scripts\\python.exe tests\\test_vision.py"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import jarvis_vision as jv

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


def test_parse_event():
    assert jv.parse_event('{"type":"ready"}') == {"type": "ready"}
    assert jv.parse_event('{"type":"gesture","action":"screenshot"}')["action"] == "screenshot"
    assert jv.parse_event("not json") is None
    assert jv.parse_event('{"no":"type"}') is None
    assert jv.parse_event("") is None


def test_hold_debouncer_fires_after_hold():
    d = jv.HoldDebouncer(hold_frames=3, cooldown_s=1.0, min_conf=0.5)
    assert d.update("Victory", 0.9, 0.0) is None
    assert d.update("Victory", 0.9, 0.0) is None
    assert d.update("Victory", 0.9, 0.0) == "Victory"     # 3rd consecutive = fire
    assert d.update("Victory", 0.9, 0.0) is None          # latched until released


def test_hold_debouncer_resets_on_change_and_lowconf():
    d = jv.HoldDebouncer(hold_frames=2, cooldown_s=0.0, min_conf=0.5)
    assert d.update("Victory", 0.9, 0.0) is None
    assert d.update("Closed_Fist", 0.9, 0.0) is None       # changed -> streak resets
    assert d.update("Closed_Fist", 0.9, 0.0) == "Closed_Fist"
    d2 = jv.HoldDebouncer(hold_frames=2, min_conf=0.6)
    assert d2.update("Victory", 0.4, 0.0) is None          # below conf -> ignored
    assert d2.update("Victory", 0.9, 0.0) is None


def test_hold_debouncer_cooldown():
    d = jv.HoldDebouncer(hold_frames=1, cooldown_s=5.0, min_conf=0.5)
    assert d.update("Victory", 0.9, 100.0) == "Victory"
    d.update(None, 0.0, 100.5)                             # release
    assert d.update("Victory", 0.9, 102.0) is None         # still cooling down
    d.update(None, 0.0, 102.5)
    assert d.update("Victory", 0.9, 106.0) == "Victory"    # cooldown elapsed


def test_swipe_direction():
    s = jv.SwipeTracker(window_s=0.6, min_dx=0.2, cooldown_s=1.0)
    assert s.update(0.30, True, 0.0) is None
    assert s.update(0.50, True, 0.1) is None
    assert s.update(0.72, True, 0.2) == jv.MOVE_RIGHT
    s2 = jv.SwipeTracker(window_s=0.6, min_dx=0.2, cooldown_s=1.0)
    s2.update(0.72, True, 0.0); s2.update(0.5, True, 0.1)
    assert s2.update(0.30, True, 0.2) == jv.MOVE_LEFT


def test_swipe_needs_open_palm_and_invert():
    s = jv.SwipeTracker(min_dx=0.2, cooldown_s=1.0)
    assert s.update(0.3, False, 0.0) is None               # palm closed -> tracking cleared
    assert s.update(0.7, False, 0.1) is None
    inv = jv.SwipeTracker(min_dx=0.2, cooldown_s=1.0, invert=True)
    inv.update(0.30, True, 0.0); inv.update(0.55, True, 0.1)
    assert inv.update(0.72, True, 0.2) == jv.MOVE_LEFT     # inverted


def test_swipe_below_threshold():
    s = jv.SwipeTracker(min_dx=0.4, cooldown_s=1.0)
    s.update(0.40, True, 0.0); s.update(0.45, True, 0.1)
    assert s.update(0.50, True, 0.2) is None               # only 0.10 travel


def test_palm_to_fist_grab():
    g = jv.PalmToFistDetector(window_s=1.0, fist_hold=2, cooldown_s=1.0, min_conf=0.5)
    assert g.update("Closed_Fist", 0.9, 0.0) is False       # bare fist, no prior palm
    assert g.update("Open_Palm", 0.9, 0.1) is False         # arm
    assert g.update("Closed_Fist", 0.9, 0.2) is False       # 1 fist frame
    assert g.update("Closed_Fist", 0.9, 0.3) is True        # 2nd -> grab fires
    assert g.update("Closed_Fist", 0.9, 0.4) is False       # latched until re-armed


def test_palm_to_fist_window_and_rearm():
    g = jv.PalmToFistDetector(window_s=0.5, fist_hold=1, cooldown_s=0.0, min_conf=0.5)
    g.update("Open_Palm", 0.9, 0.0)
    assert g.update("Closed_Fist", 0.9, 1.0) is False        # fist too late (> window)
    g.update("Open_Palm", 0.9, 2.0)                          # re-arm
    assert g.update("Closed_Fist", 0.9, 2.2) is True         # in time -> fires


def test_palm_to_fist_lowconf_ignored():
    g = jv.PalmToFistDetector(window_s=1.0, fist_hold=1, min_conf=0.6)
    g.update("Open_Palm", 0.9, 0.0)
    assert g.update("Closed_Fist", 0.4, 0.1) is False        # low-conf fist ignored
    assert g.update("Closed_Fist", 0.9, 0.2) is True


# --- engine gesture -> action routing -------------------------------------- #
def _engine(close_confirm=True):
    import jarvis
    e = jarvis.JarvisEngine.__new__(jarvis.JarvisEngine)
    e.cfg = {"gesture_announce_actions": False,
             "gesture_close_needs_confirm": close_confirm}
    calls = []
    e._snap_window = lambda d, s=True: calls.append(("snap", d))
    e._gesture_screenshot = lambda s=True: calls.append(("shot",))
    e._close_active_window = lambda s=True: calls.append(("close",))
    e._gesture_confirm_close = lambda: calls.append(("confirm_close",))
    return e, calls


def test_routing_maps_each_action():
    e, calls = _engine(close_confirm=True)
    e._handle_gesture_event("move_left")
    e._handle_gesture_event("move_right")
    e._handle_gesture_event("screenshot")
    e._handle_gesture_event("close_window")
    e._handle_gesture_event("bogus")                        # ignored
    assert calls == [("snap", "left"), ("snap", "right"), ("shot",), ("confirm_close",)]


def test_routing_close_without_confirm():
    e, calls = _engine(close_confirm=False)
    e._handle_gesture_event("close_window")
    assert calls == [("close",)]


# --- shared camera frame (sidecar feed -> vision tool / face-auth) ---------- #
def _jpeg(h, w):
    import numpy as np, cv2
    img = np.zeros((h, w, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


def test_shared_camera_frame_fresh_stale_missing():
    import time as _t
    import jarvis_tools as tools

    class Eng:
        pass
    e = Eng(); e._cam_frame_jpeg = _jpeg(48, 64); e._cam_frame_ts = _t.time()
    f = tools._shared_camera_frame(e)
    assert f is not None and f.shape[0] == 48 and f.shape[1] == 64   # decoded BGR
    e._cam_frame_ts = _t.time() - 100                                # stale
    assert tools._shared_camera_frame(e) is None
    e.__dict__["_cam_frame_jpeg"] = None                             # missing
    e._cam_frame_ts = _t.time()
    assert tools._shared_camera_frame(e) is None
    assert tools._shared_camera_frame(None) is None                  # no engine


def test_capture_prefers_shared_frame():
    import time as _t
    import jarvis_tools as tools

    class Eng:
        pass
    e = Eng(); e._cam_frame_jpeg = _jpeg(40, 50); e._cam_frame_ts = _t.time()
    frame, how = tools.capture_camera_frame(None, e)                 # never opens a device
    assert frame is not None and how == "the live gesture camera"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            check(name, fn)
    total = _passed + _failed
    print(f"\n{_passed} passed, {_failed} failed, {total} total")
    sys.exit(1 if _failed else 0)
