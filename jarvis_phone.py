"""Jarvis phone bridge - scan something with your phone, Jarvis comments on it.

Runs a small HTTP server on the LAN (0.0.0.0) so a phone on the same Wi-Fi can
load a camera page (installable to the home screen) at
    http://<desktop-ip>:<port>/phone.html?token=<token>
capture an image, and POST it to /scan. The desktop engine runs the image
through Claude's vision and returns spoken commentary, which the phone displays
and reads aloud.

SECURITY: this binds to the whole local network, so every request is gated by a
shared `token` (auto-generated, embedded in the pairing URL/QR). It is OFF by
default (phone_bridge_enabled). Only reachable from the LAN, never the internet,
unless the user deliberately forwards the port.
"""

import os
import io
import json
import base64
import socket
import threading
import http.server

APP_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(APP_DIR, "web")


def lan_ip():
    """Best-effort LAN IP of this machine (the address a phone would dial)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))     # no data sent; just selects the egress NIC
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def pairing_url(token, port, ip=None):
    return f"http://{ip or lan_ip()}:{port}/phone.html?token={token}"


def qr_svg(data, dark="#ffce92", light="#0a0703"):
    """An SVG QR code for `data`, or None if the QR lib is unavailable."""
    try:
        import segno
        buf = io.BytesIO()
        segno.make(data, error="m").save(buf, kind="svg", scale=9,
                                         dark=dark, light=light, border=3)
        svg = buf.getvalue().decode("utf-8")
        return svg[svg.find("<svg"):]
    except Exception:
        return None


def run_phone_bridge(token, on_scan, port=8770, host="0.0.0.0",
                     status_cb=None, web_dir=WEB_DIR):
    """Serve the phone page + handle token-gated image scans. Blocking - run in a
    daemon thread. `on_scan(image_bytes, prompt) -> commentary_text`."""
    def _log(msg):
        if status_cb:
            try:
                status_cb(msg)
            except Exception:
                pass

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=web_dir, **k)

        def log_message(self, *a):
            pass  # quiet

        def end_headers(self):
            # let the page be installed/cached as a home-screen app
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def _json(self, code, obj):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path.split("?")[0] != "/scan":
                return self._json(404, {"error": "not found"})
            try:
                length = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                return self._json(400, {"error": "bad request"})
            if data.get("token") != token:
                return self._json(403, {"error": "unauthorized"})
            img_b64 = data.get("image", "")
            if "," in img_b64[:64]:                 # strip a data: URL prefix if present
                img_b64 = img_b64.split(",", 1)[1]
            try:
                img = base64.b64decode(img_b64)
            except Exception:
                return self._json(400, {"error": "bad image"})
            if len(img) < 500:
                return self._json(400, {"error": "no image captured"})
            try:
                commentary = on_scan(img, (data.get("prompt") or "").strip())
            except Exception as e:
                return self._json(500, {"error": f"vision failed: {e}"})
            self._json(200, {"commentary": commentary})

    httpd = http.server.ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    httpd.allow_reuse_address = True
    _log(f"Phone bridge live at {pairing_url(token, port)}")
    try:
        httpd.serve_forever()
    except Exception:
        pass
