"""Headless Jarvis for an always-on host (Raspberry Pi / home server / VPS).

Runs the Jarvis BRAIN plus whichever remote bridges are enabled in config -
phone bridge, remote tunnel, Telegram, MCP - with NO desktop microphone, HUD,
or GUI. The brain is the Claude API; speech-to-text is local Whisper; voice is
local Piper (set "tts_engine": "piper"). This is what you run on the Pi so Jarvis
is reachable from your other devices even when your PC is off.

    python serve_headless.py

It does NOT open the mic or the HUD - those belong to the desktop app (jarvis.py).
"""

import os
# Let pygame.mixer.init() (called in the engine constructor) succeed on a headless
# box with no sound card.
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import sys
import time
import threading

import jarvis


def main():
    if not jarvis.single_instance_lock():
        print("Jarvis is already running - close the other copy first:")
        for pid, cl in jarvis.running_instances():
            print(f"  PID {pid}: {cl}")
        print("(End it in Task Manager / 'taskkill /PID <pid> /F', or reboot, then re-run.)")
        return 1
    cfg = jarvis.load_config()
    if not cfg.get("anthropic_api_key"):
        print("Set anthropic_api_key in config.json first.")
        return 1

    def status(m):
        print(f"  {m}", flush=True)

    def transcript(role, text):
        print(f"[{role}] {text}", flush=True)

    print("Starting headless Jarvis...", flush=True)
    engine = jarvis.JarvisEngine(cfg, status, transcript)
    engine._running = True            # background bridges loop on this flag
    try:
        engine.ensure_models()        # preload Whisper + the Claude client
    except Exception as e:
        print(f"(model load issue: {e})", flush=True)

    started = []
    if cfg.get("mcp_enabled") and cfg.get("mcp_servers"):
        threading.Thread(target=engine._get_mcp, daemon=True).start()
        started.append("mcp")
    if cfg.get("phone_bridge_enabled") or cfg.get("remote_access_enabled"):
        threading.Thread(target=engine._run_phone_bridge, daemon=True).start()
        started.append("phone")
    if cfg.get("remote_access_enabled"):
        threading.Thread(target=engine._run_remote_access, daemon=True).start()
        started.append("remote")
    if cfg.get("telegram_enabled") and cfg.get("telegram_bot_token"):
        threading.Thread(target=engine._run_telegram_bridge, daemon=True).start()
        started.append("telegram")

    print(f"Headless Jarvis online. Bridges: {started}", flush=True)

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
