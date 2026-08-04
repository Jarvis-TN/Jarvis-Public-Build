"""Shared logic for Jarvis's real-time gesture control - the cold, testable core.

This module holds NO camera or model code, only stdlib: the debounce/swipe math,
the event wire-format, and the paths to the isolated vision sidecar. Because it's
import-light it can be loaded from BOTH environments - the main .venv (engine +
tests) and the .venv-vision sidecar (which adds mediapipe/opencv on top).

Why a sidecar at all: mediapipe pulls opencv-contrib-python, which clashes with
the main env's pinned opencv-python-headless. So the webcam + gesture model run in
`.venv-vision` as a subprocess (vision_sidecar.py) that streams one JSON event per
line to the engine, which maps each to a window action.

Actions emitted:  move_left | move_right | screenshot | close_window
"""

import os
import json
import collections

APP_DIR = os.path.dirname(os.path.abspath(__file__))
SIDECAR_SCRIPT = os.path.join(APP_DIR, "vision_sidecar.py")
VISION_VENV_PY = os.path.join(APP_DIR, ".venv-vision", "Scripts", "python.exe")
GESTURE_MODEL = os.path.join(APP_DIR, "voices", "gesture", "gesture_recognizer.task")
GESTURE_MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/"
                     "gesture_recognizer/gesture_recognizer/float16/latest/"
                     "gesture_recognizer.task")

# Action names (the sidecar emits these; the engine maps them to OS actions).
MOVE_LEFT, MOVE_RIGHT, SCREENSHOT, CLOSE_WINDOW = (
    "move_left", "move_right", "screenshot", "close_window")
ACTIONS = (MOVE_LEFT, MOVE_RIGHT, SCREENSHOT, CLOSE_WINDOW)
# Actions that change/destroy state -> the engine can gate these behind a spoken yes.
DESTRUCTIVE = {CLOSE_WINDOW}

# MediaPipe built-in gesture label -> our static action (fire when held steady).
STATIC_GESTURE_ACTIONS = {"Victory": SCREENSHOT, "Closed_Fist": CLOSE_WINDOW}


def sidecar_installed():
    """True once setup_vision.bat has built the isolated venv."""
    return os.path.isfile(VISION_VENV_PY) and os.path.isfile(SIDECAR_SCRIPT)


def parse_event(line):
    """Parse one JSON line from the sidecar into a dict, or None if it isn't a
    well-formed event. Never raises - sidecar stdout can carry stray text."""
    line = (line or "").strip()
    if not line or not line.startswith("{"):
        return None
    try:
        obj = json.loads(line)
    except Exception:
        return None
    return obj if isinstance(obj, dict) and "type" in obj else None


class HoldDebouncer:
    """Fire a static gesture only once it's been held steady for `hold_frames`
    consecutive frames above `min_conf`, then not again until it's released and a
    `cooldown_s` has passed. Stops a flicker or a passing pose from triggering."""

    def __init__(self, hold_frames=8, cooldown_s=1.5, min_conf=0.6):
        self.hold_frames = max(1, int(hold_frames))
        self.cooldown_s = float(cooldown_s)
        self.min_conf = float(min_conf)
        self._name = None
        self._streak = 0
        self._latched = False           # already fired for the current hold
        self._last_fire = {}            # name -> ts

    def update(self, name, conf, now):
        """Feed the current top gesture (name/conf) at time `now`; returns the
        gesture name to fire, or None."""
        if not name or conf < self.min_conf:
            self._name, self._streak, self._latched = None, 0, False
            return None
        if name != self._name:
            self._name, self._streak, self._latched = name, 0, False
        self._streak += 1
        if self._latched or self._streak < self.hold_frames:
            return None
        if now - self._last_fire.get(name, -1e9) < self.cooldown_s:
            return None
        self._latched = True            # one fire per continuous hold
        self._last_fire[name] = now
        return name


class SwipeTracker:
    """Detect a horizontal open-palm swipe. Feed the palm x (normalized 0..1) each
    frame while the palm is open; a fast enough net move within `window_s` emits a
    direction, then holds off for `cooldown_s`. `invert` flips left/right."""

    def __init__(self, window_s=0.6, min_dx=0.22, cooldown_s=1.2, invert=False):
        self.window_s = float(window_s)
        self.min_dx = float(min_dx)
        self.cooldown_s = float(cooldown_s)
        self.invert = bool(invert)
        self._pts = collections.deque()   # (ts, x)
        self._last_swipe = -1e9

    def reset(self):
        self._pts.clear()

    def update(self, x, palm_open, now):
        if not palm_open or x is None:
            self._pts.clear()
            return None
        self._pts.append((now, float(x)))
        while self._pts and now - self._pts[0][0] > self.window_s:
            self._pts.popleft()
        if len(self._pts) < 3 or now - self._last_swipe < self.cooldown_s:
            return None
        dx = self._pts[-1][1] - self._pts[0][1]
        if abs(dx) < self.min_dx:
            return None
        self._last_swipe = now
        self._pts.clear()
        rightward = dx > 0
        if self.invert:
            rightward = not rightward
        return MOVE_RIGHT if rightward else MOVE_LEFT


class PalmToFistDetector:
    """Fire once the hand goes from an OPEN palm to a CLOSED fist within `window_s`
    - a deliberate 'grab' - rather than on a bare fist. The palm arms it, then the
    fist must hold `fist_hold` frames; a cooldown follows and a fresh palm re-arms.
    Much harder to trigger by accident than a static fist."""

    def __init__(self, window_s=1.2, fist_hold=4, cooldown_s=2.0, min_conf=0.5):
        self.window_s = float(window_s)
        self.fist_hold = max(1, int(fist_hold))
        self.cooldown_s = float(cooldown_s)
        self.min_conf = float(min_conf)
        self._armed_ts = None       # when an open palm was last seen (arms the grab)
        self._fist_streak = 0
        self._last_fire = -1e9
        self._latched = False

    def update(self, name, conf, now):
        """Feed the current top gesture (name/conf) at `now`; True on a completed grab."""
        if conf < self.min_conf:
            name = None
        if name == "Open_Palm":
            self._armed_ts = now                          # (re)arm while the palm shows
            self._fist_streak = 0
            self._latched = False
            return False
        if (name == "Closed_Fist" and self._armed_ts is not None
                and now - self._armed_ts <= self.window_s):
            self._fist_streak += 1
            if (not self._latched and self._fist_streak >= self.fist_hold
                    and now - self._last_fire >= self.cooldown_s):
                self._latched = True
                self._last_fire = now
                self._armed_ts = None
                self._fist_streak = 0
                return True
            return False
        if name is not None:                              # a lingering None keeps the arm
            self._fist_streak = 0
        return False
