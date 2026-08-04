"""Headless remote server - Jarvis's phone-scan vision, reachable from anywhere.

Runs ONLY the phone bridge behind a public Cloudflare tunnel: no microphone, no
HUD, no GUI. Use it to keep a lightweight, always-on remote endpoint (e.g. on a
home PC) so you can scan something with your phone from anywhere and get Jarvis's
spoken commentary back. The full voice app opens the very same tunnel
automatically when `remote_access_enabled` is true - this is the standalone,
GUI-less way to do just the remote piece.

    pythonw serve_remote.py      (or:  python serve_remote.py  to watch the log)
"""

import os
import sys
import time
import base64
import secrets
import threading
import subprocess
from datetime import datetime

import anthropic

import jarvis
import jarvis_phone
import jarvis_remote

APP_DIR = os.path.dirname(os.path.abspath(__file__))
LINK_FILE = os.path.join(APP_DIR, "last_remote_url.txt")


def publish_link(link):
    """Show the fresh URL prominently, copy it to the clipboard, and save it to a
    file so it's easy to grab and share."""
    print("\n" + "=" * 64)
    print("  YOUR REMOTE LINK (copied to clipboard - keep it private):")
    print("  " + link)
    print("=" * 64 + "\n")
    try:
        subprocess.run("clip", input=link, text=True, shell=True)
    except Exception:
        pass
    try:
        with open(LINK_FILE, "w", encoding="utf-8") as f:
            f.write(link + "\n")
    except Exception:
        pass


def main():
    if not jarvis.single_instance_lock():
        print("Jarvis is already running - close the other copy first:")
        for pid, cl in jarvis.running_instances():
            print(f"  PID {pid}: {cl}")
        print("(End it in Task Manager / 'taskkill /PID <pid> /F', or reboot, then re-run.)")
        return 1
    cfg = jarvis.load_config()
    key = cfg.get("anthropic_api_key", "")
    if not key:
        print("No Anthropic API key in config.json - can't run the remote server.")
        return 1
    client = anthropic.Anthropic(api_key=key)
    model = cfg.get("model", "claude-sonnet-4-6")
    port = int(cfg.get("phone_bridge_port", 8770))

    # internet-facing endpoint -> require a strong token (upgrade a short one)
    tok = (cfg.get("phone_bridge_token") or "").strip()
    if len(tok) < 20:
        tok = secrets.token_urlsafe(16)
        jarvis.save_config_value("phone_bridge_token", tok)

    system = jarvis.SYSTEM_PROMPT.format(
        name=cfg.get("assistant_name", "Jarvis"),
        date=datetime.now().strftime("%A, %d %B %Y"),
        memory="")

    def on_scan(jpeg_bytes, prompt=""):
        """Same shape as JarvisEngine.commentary_on_image, self-contained."""
        b64 = base64.b64encode(jpeg_bytes).decode("ascii")
        ask = (prompt or "").strip() or (
            "I just scanned this with my phone camera. Identify what it is and give a "
            "brief, natural spoken commentary - anything useful, interesting, or worth "
            "knowing. Keep it to a few sentences.")
        resp = client.messages.create(
            model=model, max_tokens=512, system=system,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64",
                 "media_type": "image/jpeg", "data": b64}},
                {"type": "text", "text": ask}]}])
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        return text or "I'm afraid I couldn't make that out, sir."

    threading.Thread(
        target=jarvis_phone.run_phone_bridge,
        args=(tok, on_scan), kwargs=dict(port=port, status_cb=print),
        daemon=True).start()
    time.sleep(1.5)

    provider = (cfg.get("remote_access_provider") or "cloudflare").lower()
    cf_token = (cfg.get("cloudflare_tunnel_token") or "").strip()

    if provider in ("cloudflare-named", "named") and cf_token:
        host = (cfg.get("cloudflare_hostname") or "").strip().rstrip("/")
        tunnel = jarvis_remote.NamedTunnel(cf_token, status_cb=print)
        if not tunnel.start():
            print("Couldn't start the named tunnel (cloudflared unavailable).")
            return 1
        print(f"Phone bridge on :{port}; running named tunnel...")
        if host:
            publish_link(f"https://{host}/phone.html?token={tok}")
        else:
            print("(Set 'cloudflare_hostname' in config to see your fixed link.)")
    else:
        def on_url(url):
            publish_link(f"{url}/phone.html?token={tok}")
        tunnel = jarvis_remote.QuickTunnel(f"http://127.0.0.1:{port}",
                                           on_url=on_url, status_cb=print)
        if not tunnel.start():
            print("Couldn't start the tunnel (cloudflared unavailable).")
            return 1
        print(f"Phone bridge on :{port}; opening public tunnel...")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        tunnel.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
