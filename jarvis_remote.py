"""Jarvis remote access - reach Jarvis from outside the home network.

The phone bridge (jarvis_phone) only binds the LAN. This module puts a public,
HTTPS tunnel in front of it using Cloudflare's free "quick tunnel" (cloudflared),
so the phone page is reachable from anywhere - no router port-forwarding, no
account, no inbound firewall holes (cloudflared makes an OUTBOUND connection to
Cloudflare and they proxy traffic back).

SECURITY POSTURE (important - this is internet-facing):
  * Only the phone bridge port is tunnelled. The HUD WebSocket bridge (which can
    trigger Claude turns and control the PC) is NEVER exposed.
  * The expensive endpoint (/scan -> a Claude vision call) is token-gated; the
    engine uses a STRONG token (>= 16 bytes) whenever remote access is on.
  * The trycloudflare URL is random and ephemeral - a fresh one each run, so it
    isn't a stable target.
This is appropriate for a single-user personal assistant. It is NOT hardened
multi-user infrastructure; treat the URL + token like a password.

cloudflared is a single static binary; we fetch it once into ./bin and cache it.
"""

import os
import re
import shutil
import threading
import subprocess
import urllib.request

APP_DIR = os.path.dirname(os.path.abspath(__file__))
BIN_DIR = os.path.join(APP_DIR, "bin")
CF_PATH = os.path.join(BIN_DIR, "cloudflared.exe")
CF_DOWNLOAD = ("https://github.com/cloudflare/cloudflared/releases/latest/"
               "download/cloudflared-windows-amd64.exe")

TUNNEL_RE = re.compile(r"https://[a-z0-9][-a-z0-9]*\.trycloudflare\.com")
# avoid a flashing console window when we spawn cloudflared on Windows
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def cloudflared_path():
    """Path to a usable cloudflared, or None if not present yet."""
    if os.path.exists(CF_PATH):
        return CF_PATH
    found = shutil.which("cloudflared")
    return found or None


def ensure_cloudflared(status_cb=None):
    """Return a path to cloudflared, downloading it into ./bin on first use.
    Returns None if it couldn't be obtained."""
    p = cloudflared_path()
    if p:
        return p

    def _log(m):
        if status_cb:
            try:
                status_cb(m)
            except Exception:
                pass

    try:
        os.makedirs(BIN_DIR, exist_ok=True)
        _log("Setting up remote access (downloading cloudflared, one-time)...")
        tmp = CF_PATH + ".part"
        req = urllib.request.Request(CF_DOWNLOAD, headers={"User-Agent": "JarvisAssistant"})
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f)
        os.replace(tmp, CF_PATH)
        return CF_PATH
    except Exception as e:
        _log(f"(Couldn't download cloudflared: {e})")
        try:
            if os.path.exists(CF_PATH + ".part"):
                os.remove(CF_PATH + ".part")
        except Exception:
            pass
        return None


class QuickTunnel:
    """A running Cloudflare quick tunnel in front of a local URL."""

    def __init__(self, local_url, on_url=None, status_cb=None):
        self.local_url = local_url
        self.on_url = on_url
        self.status_cb = status_cb
        self.url = None
        self._proc = None
        self._thread = None
        self._stopped = False

    def _log(self, m):
        if self.status_cb:
            try:
                self.status_cb(m)
            except Exception:
                pass

    def start(self):
        """Launch cloudflared and begin watching its output for the public URL.
        Non-blocking; the URL arrives asynchronously via on_url. Returns True if
        the process started."""
        exe = ensure_cloudflared(self.status_cb)
        if not exe:
            return False
        try:
            self._proc = subprocess.Popen(
                [exe, "tunnel", "--no-autoupdate", "--url", self.local_url],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, creationflags=_NO_WINDOW)
        except Exception as e:
            self._log(f"(Couldn't start the tunnel: {e})")
            return False
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()
        return True

    def _watch(self):
        try:
            for line in self._proc.stdout:
                if self._stopped:
                    break
                if self.url is None:
                    m = TUNNEL_RE.search(line)
                    if m:
                        self.url = m.group(0)
                        self._log(f"Remote access live at {self.url}")
                        if self.on_url:
                            try:
                                self.on_url(self.url)
                            except Exception:
                                pass
        except Exception:
            pass

    def stop(self):
        self._stopped = True
        if self._proc:
            try:
                self._proc.terminate()
            except Exception:
                pass
        self._proc = None

    def is_running(self):
        return self._proc is not None and self._proc.poll() is None


class NamedTunnel:
    """A persistent, STABLE Cloudflare tunnel run from a connector token.

    Unlike a quick tunnel (random ephemeral *.trycloudflare.com), a named tunnel
    keeps the same public hostname every run (e.g. jarvis.yourdomain.com). The
    hostname -> local-service mapping is configured once in the Cloudflare
    Zero Trust dashboard ("Networks -> Tunnels -> Public Hostname"); here we just
    run the connector with its token. Requires a domain on the user's Cloudflare
    account (that's what makes a fixed hostname possible)."""

    def __init__(self, token, status_cb=None):
        self.token = token
        self.status_cb = status_cb
        self.connected = False
        self._proc = None
        self._thread = None
        self._stopped = False

    def _log(self, m):
        if self.status_cb:
            try:
                self.status_cb(m)
            except Exception:
                pass

    def start(self):
        exe = ensure_cloudflared(self.status_cb)
        if not exe:
            return False
        if not (self.token or "").strip():
            self._log("(Named tunnel: no connector token configured.)")
            return False
        try:
            self._proc = subprocess.Popen(
                [exe, "tunnel", "--no-autoupdate", "run", "--token", self.token],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, creationflags=_NO_WINDOW)
        except Exception as e:
            self._log(f"(Couldn't start the named tunnel: {e})")
            return False
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()
        return True

    def _watch(self):
        try:
            for line in self._proc.stdout:
                if self._stopped:
                    break
                if not self.connected and ("Registered tunnel connection" in line
                                           or "Connection registered" in line):
                    self.connected = True
                    self._log("Named tunnel connected.")
        except Exception:
            pass

    def stop(self):
        self._stopped = True
        if self._proc:
            try:
                self._proc.terminate()
            except Exception:
                pass
        self._proc = None

    def is_running(self):
        return self._proc is not None and self._proc.poll() is None
