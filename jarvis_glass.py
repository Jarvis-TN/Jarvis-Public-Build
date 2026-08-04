"""Jarvis "glass" front-end.

Runs the Jarvis engine (voice loop + tools + memory + live HUD bridge) headless and
shows the Three.js neural HUD as the app's face inside a native desktop window
(Edge WebView2 via pywebview) - no browser tab. The HUD reacts to the live assistant
over the WebSocket bridge, exactly like the browser version.

Launch with "Launch Jarvis HUD.bat" or:  pythonw jarvis_glass.py
"""

import os
import sys
import functools
import time
import threading
import traceback
import faulthandler
import http.server
import socketserver

os.chdir(os.path.dirname(os.path.abspath(__file__)))

import jarvis

try:
    import webview
except Exception as e:
    print("pywebview is required for the glass HUD. Run setup.bat again.\n  ", e)
    input("Press Enter to exit...")
    sys.exit(1)

APP_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(APP_DIR, "web")
WEB_PORT = 8791
GLASS_LOG = os.path.join(APP_DIR, "glass.log")


def _glog(*parts):
    """Append a line to glass.log - safe under pythonw (where print() raises
    because stdout is None) and a record of how far startup got."""
    try:
        with open(GLASS_LOG, "a", encoding="utf-8") as f:
            f.write(" ".join(str(p) for p in parts) + "\n")
    except Exception:
        pass


# Set True only by an explicit user quit (tray Quit / HUD close button) so the
# window-close handler can tell an intentional exit from a WebView2/GPU crash.
_QUIT = {"user": False}


def _install_crash_diagnostics():
    """Turn a silent death into a diagnosable one. Under pythonw.exe stdout/stderr
    are None and native faults (PyAV/pygame/CTranslate2 segfaults) vanish with no
    trace, which is why glass.log just 'ends'. This captures:
      - a C-level stack on a native fault via faulthandler,
      - uncaught Python exceptions on the main thread AND worker threads.
    On the next incident: a C-stack dump in glass_stderr.log = native segfault;
    a Python traceback = Python-level bug; nothing at all = a clean window/renderer
    close (the WebView2/GPU path)."""
    try:
        f = open(os.path.join(APP_DIR, "glass_stderr.log"), "a", encoding="utf-8", buffering=1)
        f.write("\n=== diagnostics armed " + time.strftime("%Y-%m-%d %H:%M:%S") + " ===\n")
        sys.stdout = f
        sys.stderr = f
        faulthandler.enable(file=f, all_threads=True)
    except Exception:
        pass

    def _hook(exc_type, exc, tb):
        _glog("UNCAUGHT:", "".join(traceback.format_exception(exc_type, exc, tb)))
    sys.excepthook = _hook
    try:  # threading.excepthook is Python 3.8+
        def _thook(args):
            _glog("THREAD UNCAUGHT:",
                  "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))
        threading.excepthook = _thook
    except Exception:
        pass


def _start_watchdog(engine):
    """Log thread count + memory + mic-queue depth to glass.log every 30s. If these
    climb every phrase, the crash is a Python-side leak; if they stay flat while the
    app still dies, that points at the WebView2/GPU renderer instead."""
    def run():
        try:
            import psutil
            p = psutil.Process(os.getpid())
        except Exception:
            p = None
        while True:
            time.sleep(30)
            try:
                rss = (p.memory_info().rss // (1024 * 1024)) if p else -1
                q = engine._audio_q.qsize() if getattr(engine, "_audio_q", None) is not None else -1
                _glog("[watchdog]", "threads=%d" % threading.active_count(),
                      "rss_mb=%d" % rss, "audio_q=%d" % q)
            except Exception:
                pass
    threading.Thread(target=run, daemon=True).start()


class _NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    """Serve the page with no-cache headers so each launch loads the latest HUD."""
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        super().end_headers()

    def log_message(self, *args):
        pass  # quiet


def _start_web_server():
    """Serve the web/ folder locally (ES modules need http, not file://)."""
    handler = functools.partial(_NoCacheHandler, directory=WEB_DIR)
    httpd = socketserver.TCPServer(("127.0.0.1", WEB_PORT), handler)
    httpd.allow_reuse_address = True
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def _setup_tray(window, engine):
    """System-tray menu so glass mode has controls without the tk window."""
    try:
        import pystray
        from PIL import Image
    except Exception as e:
        print("Tray unavailable:", e)
        return None
    try:
        image = Image.open(os.path.join(APP_DIR, "jarvis.ico"))
    except Exception:
        image = Image.new("RGB", (64, 64), "#7fe8ff")

    def _show(i=None, it=None):
        try: window.show()
        except Exception: pass

    def _hide(i=None, it=None):
        try: window.hide()
        except Exception: pass

    def _mute(i=None, it=None):
        try: engine.toggle_listening()
        except Exception: pass

    # Pin / always-on-top, toggled from the native tray (not the HUD).
    pin_state = {"on": bool(jarvis.load_config().get("glass_on_top", True))}

    def _toggle_pin(i=None, it=None):
        pin_state["on"] = not pin_state["on"]
        try: window.on_top = pin_state["on"]
        except Exception: pass
        try: jarvis.save_config_value("glass_on_top", pin_state["on"])
        except Exception: pass

    def _connect_google(i=None, it=None):
        def run():
            try:
                import google_integration as g
                g.authorize_interactive()
            except Exception as e:
                print("Google connect failed:", e)
        threading.Thread(target=run, daemon=True).start()

    def _toggle_startup(i=None, it=None):
        jarvis.set_run_on_startup(not jarvis.is_run_on_startup())

    def _quit(i=None, it=None):
        _QUIT["user"] = True
        _arm_hard_exit()
        try: engine.stop()
        except Exception: pass
        try: window.destroy()
        except Exception: pass
        os._exit(0)

    mic_items = [pystray.MenuItem("System default", lambda i, it: engine.set_input_device(None))]
    for _idx, name in jarvis.list_input_devices():
        mic_items.append(pystray.MenuItem(
            name, (lambda nm: (lambda i, it: engine.set_input_device(nm)))(name)))

    out_items = [pystray.MenuItem("System default", lambda i, it: engine.set_output_device(None))]
    for name in jarvis.list_output_devices():
        out_items.append(pystray.MenuItem(
            name, (lambda nm: (lambda i, it: engine.set_output_device(nm)))(name)))

    cam_items = [pystray.MenuItem("Auto (system default)", lambda i, it: engine.set_camera_device(None))]
    for name in jarvis.list_camera_names():
        cam_items.append(pystray.MenuItem(
            name, (lambda nm: (lambda i, it: engine.set_camera_device(nm)))(name)))

    menu = pystray.Menu(
        pystray.MenuItem("Show HUD", _show, default=True),
        pystray.MenuItem("Hide", _hide),
        pystray.MenuItem("Pin on top", _toggle_pin, checked=lambda it: pin_state["on"]),
        pystray.MenuItem("Microphone", pystray.Menu(*mic_items)),
        pystray.MenuItem("Speaker", pystray.Menu(*out_items)),
        pystray.MenuItem("Camera", pystray.Menu(*cam_items)),
        pystray.MenuItem("Reset devices to system default",
                         lambda i, it: engine.reset_devices_to_default()),
        pystray.MenuItem("Mute / Unmute mic", _mute),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Connect Google account", _connect_google),
        pystray.MenuItem("Start with Windows", _toggle_startup,
                         checked=lambda it: jarvis.is_run_on_startup()),
        pystray.MenuItem("Quit Jarvis", _quit),
    )
    icon = pystray.Icon("jarvis", image, "J.A.R.V.I.S.", menu)
    threading.Thread(target=icon.run, daemon=True).start()
    return icon


class _HudApi:
    """Tiny JS-callable bridge so the frameless HUD can drive its own window
    (minimize / close / resize) - there's no OS titlebar to do it. Deliberately
    minimal and one-shot; window pinning stays on the tray to avoid the repeated
    on-top toggling that historically upset WebView2."""
    def __init__(self):
        self.window = None
        self.engine = None

    def minimize(self):
        try:
            self.window.minimize()
        except Exception:
            pass

    def close_app(self):
        _QUIT["user"] = True
        _arm_hard_exit()
        try:
            if self.engine:
                self.engine.stop()
        except Exception:
            pass
        try:
            self.window.destroy()
        except Exception:
            pass
        os._exit(0)

    def set_size(self, width, height):
        try:
            self.window.resize(max(360, int(width)), max(360, int(height)))
        except Exception:
            pass


def _arm_hard_exit(seconds=4.0):
    """Guarantee this process actually dies within `seconds`, even if engine.stop()
    or window.destroy() hangs on a device/subprocess. A lingering process keeps
    holding the single-instance mutex, which makes the NEXT launch falsely report
    'Jarvis is already running' and sometimes fail to boot."""
    import threading
    t = threading.Timer(seconds, lambda: os._exit(0))
    t.daemon = True
    t.start()


def main():
    _install_crash_diagnostics()
    if not jarvis.single_instance_lock():
        if not (jarvis.offer_to_end_running() and jarvis.single_instance_lock()):
            return
    cfg = jarvis.load_config()

    # Engine runs headless; the HUD shows its state via the WebSocket bridge.
    # Log to a file (NOT print): under pythonw stdout is None, so print() raises
    # and would crash every engine thread - and gives us no diagnostics. glass.log
    # captures how far startup got.
    engine = jarvis.JarvisEngine(
        cfg,
        status_cb=lambda s: _glog("status:", s),
        transcript_cb=lambda role, text: _glog(f"[{role}]", text),
    )

    _start_web_server()

    _glog("=== glass start", time.strftime("%Y-%m-%d %H:%M:%S"), "===")
    if cfg.get("anthropic_api_key"):
        engine.start()   # voice loop + tools + HUD bridge (ws://localhost:8765)
    else:
        _glog("No Anthropic API key in config.json - HUD will run idle.")
    _glog("engine.start() returned; creating HUD window...")
    _start_watchdog(engine)

    # Optional WebView2/Chromium GPU-softening flags (empty by default = no change).
    # If crashes persist, set "hud_gpu_args" in config.json to "--disable-gpu-compositing"
    # (softer) or "--disable-gpu" (forces software WebGL) to test whether the GPU is
    # the trigger. Must be set before the window is created.
    gpu_args = (cfg.get("hud_gpu_args") or "").strip()
    if gpu_args:
        os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = gpu_args
        _glog("WebView2 browser args:", gpu_args)

    # Frameless / floating HUD: no OS window chrome, so Jarvis can be dragged
    # anywhere and shown/minimised/closed/resized from controls on the HUD itself
    # (plus the tray). Optional full transparency turns him into a floating orb.
    frameless = bool(cfg.get("hud_frameless", True))
    transparent = bool(cfg.get("hud_transparent", False))
    hud_params = f"app=1&v={int(time.time())}"
    if frameless:
        hud_params += "&frameless=1"
    if transparent:
        hud_params += "&transparent=1"
    hud_api = _HudApi()
    window = webview.create_window(
        "J.A.R.V.I.S.",
        f"http://localhost:{WEB_PORT}/hud_holo.html?{hud_params}",   # WebGL2 particle hologram HUD (<jarvis-hologram>); cache-bust each launch (hud_aou.html kept as fallback)
        width=940, height=940,
        background_color=("#00000000" if transparent else "#03060a"),
        resizable=True, min_size=(360, 360),
        frameless=frameless, easy_drag=False,   # dragging handled by a drag-region layer in the page
        transparent=transparent,
        js_api=hud_api,
        on_top=bool(cfg.get("glass_on_top", True)),   # stay reachable; toggle via tray "Pin on top"
    )
    hud_api.window = window
    hud_api.engine = engine

    # Secondary "display" window - an equally-sized HUD-styled window (no orb)
    # that Jarvis raises to show drawings / schematics / disambiguation sketches.
    # It only ever appears when there's something to show. Robust to the user
    # closing it: closing the X just hides it, but if a backend destroys it
    # anyway we transparently recreate it on the next draw - so it always
    # comes back. The page replays the current visual on (re)connect.
    vp = {"win": None}

    def _make_viewport():
        w = webview.create_window(
            "J.A.R.V.I.S. — Display",
            f"http://localhost:{WEB_PORT}/viewport.html?v={int(time.time())}",
            width=940, height=940, background_color="#03060a",
            resizable=True, min_size=(460, 460), hidden=True,
        )

        def _closing():
            try:
                w.hide()
            except Exception:
                pass
            return False          # cancel the real close -> just hide it

        def _closed():
            if vp["win"] is w:    # it really got destroyed; allow recreation
                vp["win"] = None

        w.events.closing += _closing
        w.events.closed += _closed
        vp["win"] = w
        return w

    _make_viewport()

    def _show_viewport():
        w = vp["win"] or _make_viewport()
        try:
            w.show()
        except Exception:
            try:                  # window was destroyed under us -> rebuild + show
                _make_viewport().show()
            except Exception:
                pass

    def _hide_viewport():
        w = vp["win"]
        if w is not None:
            try:
                w.hide()
            except Exception:
                pass

    engine._viewport_show = _show_viewport
    engine._viewport_hide = _hide_viewport

    def _on_closed():
        # If the user didn't explicitly quit, the window vanished on its own -
        # most likely a WebView2 renderer/GPU-process crash. Record which it was
        # so the next incident is classifiable from the log alone.
        if _QUIT["user"]:
            _glog("WINDOW CLOSED (user quit)")
        else:
            _glog("WINDOW CLOSED unexpectedly - no user quit; likely WebView2/GPU renderer crash")
        _arm_hard_exit()
        try:
            engine.stop()
        except Exception:
            pass
        os._exit(0)

    window.events.closed += _on_closed
    _setup_tray(window, engine)   # tray controls (mic, mute, Google, startup, quit)
    _glog("calling webview.start() - HUD window should appear now")
    try:
        webview.start()   # blocks on the main thread until the window closes
    except Exception:
        import traceback
        _glog("webview.start() FAILED:\n" + traceback.format_exc())
        raise
    _glog("webview.start() returned (window closed)")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        tb = traceback.format_exc()
        try:
            jarvis._log_startup_crash(tb)
        except Exception:
            pass
        # Glass HUD failed - fall back to the classic window so we don't die silently.
        try:
            import tkinter as tk
            cfg = jarvis.load_config()
            root = tk.Tk()
            jarvis.JarvisApp(root, cfg)
            root.mainloop()
        except Exception:
            pass
