"""Jarvis context / situation sensor - the substrate for context-aware proactivity.

A cheap, local-only read of *what's going on right now* so Jarvis can time its
interruptions around the user's real availability (silent in a meeting or while
away; speaks up when free) instead of guessing from the clock alone.

All signals are gathered on Windows via ctypes / psutil - no network, no models:
  * foreground app + window title  (what the user is doing)
  * idle_seconds                   (how long since keyboard/mouse input)
  * is_locked                      (workstation locked / secure desktop)
  * derived availability state     available | busy | away

The pure helpers (looks_busy, availability) are import-light and deterministic so
the test-suite can exercise them without a live desktop. Everything degrades to a
neutral 'available' snapshot off-Windows or on any error - it never raises.
"""

import os

# Foreground apps that mean "don't interrupt" - a live call or a presentation.
MEETING_APPS = {
    "zoom.exe", "teams.exe", "ms-teams.exe", "msteams.exe",
    "webex.exe", "webexmta.exe", "gotomeeting.exe", "bluejeans.exe",
}
_MEETING_TITLE_HINTS = ("zoom meeting", "microsoft teams", "google meet",
                        " meet -", "webex", "- webex")


# --------------------------------------------------------------------------- #
#  Windows ctypes plumbing (set up once; every call is best-effort)
# --------------------------------------------------------------------------- #
def _win():
    """Return (user32, kernel32) with the needed prototypes set, or (None, None)."""
    if os.name != "nt":
        return None, None
    try:
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        k = ctypes.windll.kernel32
        # HWND/HANDLE are pointers - restype MUST be set or 64-bit handles truncate.
        u.GetForegroundWindow.restype = wintypes.HWND
        u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        u.GetWindowTextLengthW.restype = ctypes.c_int
        u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.GetWindowTextW.restype = ctypes.c_int
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        u.GetWindowThreadProcessId.restype = wintypes.DWORD
        u.OpenInputDesktop.restype = wintypes.HANDLE
        u.GetUserObjectInformationW.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
            wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        u.GetUserObjectInformationW.restype = wintypes.BOOL
        u.CloseDesktop.argtypes = [wintypes.HANDLE]
        k.GetTickCount.restype = wintypes.DWORD
        return u, k
    except Exception:
        return None, None


def foreground_app():
    """(process_name, window_title) of the focused window, or (None, None)."""
    u, _ = _win()
    if u is None:
        return (None, None)
    try:
        import ctypes
        from ctypes import wintypes
        hwnd = u.GetForegroundWindow()
        if not hwnd:
            return (None, None)
        n = u.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(hwnd, buf, n + 1)
        title = buf.value or None
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        name = None
        try:
            import psutil
            name = psutil.Process(pid.value).name()
        except Exception:
            name = None
        return (name, title)
    except Exception:
        return (None, None)


def idle_seconds():
    """Seconds since the last keyboard/mouse input (0.0 if unavailable)."""
    u, k = _win()
    if u is None or k is None:
        return 0.0
    try:
        import ctypes
        from ctypes import wintypes

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not u.GetLastInputInfo(ctypes.byref(lii)):
            return 0.0
        # 32-bit tick math; mask handles the ~49-day wrap so it never goes negative.
        elapsed = (k.GetTickCount() - lii.dwTime) & 0xFFFFFFFF
        return elapsed / 1000.0
    except Exception:
        return 0.0


def is_locked():
    """True if the workstation is locked (the input desktop can't be opened, or
    it isn't 'Default' - i.e. the secure/lock desktop is up)."""
    u, _ = _win()
    if u is None:
        return False
    try:
        import ctypes
        from ctypes import wintypes
        DESKTOP_READOBJECTS, UOI_NAME = 0x0001, 2
        hdesk = u.OpenInputDesktop(0, False, DESKTOP_READOBJECTS)
        if not hdesk:
            return True                                   # can't reach input desktop -> locked
        try:
            name = ctypes.create_unicode_buffer(256)
            needed = wintypes.DWORD()
            u.GetUserObjectInformationW(hdesk, UOI_NAME, name,
                                        ctypes.sizeof(name), ctypes.byref(needed))
            return (name.value or "").strip().lower() != "default"
        finally:
            u.CloseDesktop(hdesk)
    except Exception:
        return False


# --------------------------------------------------------------------------- #
#  Pure logic (deterministic + testable)
# --------------------------------------------------------------------------- #
def looks_busy(name, title, extra_apps=()):
    """Is the focused window a live call or a running slideshow?"""
    n = (name or "").strip().lower()
    t = (title or "").strip().lower()
    apps = set(MEETING_APPS) | {str(a).strip().lower() for a in (extra_apps or ())}
    if n in apps:
        return True
    if "slide show" in t:                                 # PowerPoint presenting
        return True
    return any(h in t for h in _MEETING_TITLE_HINTS)


def availability(idle, locked, busy, away_idle_seconds=300):
    """Collapse the raw signals into one label the attention broker can act on."""
    if locked:
        return "away"
    if idle is not None and idle >= away_idle_seconds:
        return "away"
    if busy:
        return "busy"
    return "available"


def sample(extra_meeting_apps=(), away_idle_seconds=300):
    """A full local snapshot of the current situation. Never raises."""
    name, title = foreground_app()
    idle = idle_seconds()
    locked = is_locked()
    busy = looks_busy(name, title, extra_meeting_apps)
    state = availability(idle, locked, busy, away_idle_seconds)
    return {"app": name, "title": title, "idle": round(idle, 1),
            "locked": locked, "busy": busy, "state": state}


def describe(ctx):
    """Short human phrase for logs/prompts, e.g. 'busy in zoom.exe' / 'away (idle 7m)'."""
    ctx = ctx or {}
    st = ctx.get("state", "available")
    app = ctx.get("app")
    if ctx.get("locked"):
        return "away (screen locked)"
    if st == "away":
        return f"away (idle {int((ctx.get('idle') or 0) // 60)}m)"
    if st == "busy":
        return f"busy in {app or 'a call'}"
    return f"available{f' in {app}' if app else ''}"
