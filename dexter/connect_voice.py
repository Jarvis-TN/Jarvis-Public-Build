"""Interactive helper that connects Dexter to your ElevenLabs voice.

Run via "Connect Voice.bat" (or the update command). It asks for the API
key, verifies it against ElevenLabs immediately, finds the Dexter voice in
the account (by the configured ID, or by a voice literally named "Dexter"),
saves config.json, and plays a test line — retrying with a clear message on
every failure instead of dying.
"""

from __future__ import annotations

import json
import os

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(HERE, "config.json")
EXAMPLE = os.path.join(HERE, "config.example.json")
DEFAULT_VOICE = "VpT3HDP5RpTRd3xHsEO2"


def load():
    path = CFG if os.path.exists(CFG) else EXAMPLE
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save(cfg):
    with open(CFG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4)


def main():
    print("=" * 56)
    print("  CONNECT DEXTER'S VOICE  (ElevenLabs)")
    print("=" * 56)
    print()
    print("Get your key at elevenlabs.io -> profile icon (bottom left)")
    print("-> API Keys -> Create API Key (full/default permissions).")
    print()
    cfg = load()

    while True:
        key = input("Paste the API key here and press Enter\n"
                    "(right-click pastes into this window): ")
        key = key.strip().strip('"').strip("'")
        if not key:
            print("\nNothing was pasted. Try again (Ctrl+C quits).\n")
            continue
        if len(key) < 20 or " " in key:
            print("\nThat doesn't look like an API key - it's one long code "
                  "with no spaces.\nCopy it from elevenlabs.io -> API Keys "
                  "and try again.\n")
            continue

        print("\nChecking the key with ElevenLabs ...")
        try:
            r = requests.get("https://api.elevenlabs.io/v1/voices",
                             headers={"xi-api-key": key}, timeout=30)
        except Exception as exc:
            print(f"Could not reach ElevenLabs ({exc}).\n"
                  "Check the internet connection and try again.\n")
            continue
        if r.status_code == 401:
            print("ElevenLabs rejected the key (401 unauthorized).\n"
                  "Copy it again carefully - or create a NEW key and make "
                  "sure it has full/default permissions, not restricted.\n")
            continue
        if r.status_code != 200:
            print(f"Unexpected reply (HTTP {r.status_code}): "
                  f"{r.text[:200]}\nTry again.\n")
            continue

        all_voices = r.json().get("voices", [])
        voices = {v["voice_id"]: v["name"] for v in all_voices}
        # your own voices (cloned/designed), not the ~20 stock ones every
        # account ships with
        own = [v for v in all_voices
               if v.get("category", "premade") != "premade"]
        pool = own if own else all_voices
        print(f"Key accepted. {len(all_voices)} voices total "
              f"({len(all_voices) - len(own)} are ElevenLabs stock voices).")
        if not all_voices:
            print("\nThis account has no voices yet. Create and SAVE the "
                  "Dexter voice at elevenlabs.io (it must appear under "
                  "My Voices), then run this again.\n")
            continue

        print("\nYour voices:" if own else "\nAvailable voices:")
        for i, v in enumerate(pool, 1):
            print(f"   {i}. {v['name']}")

        # best guess: configured ID if present, else a name containing "dex"
        want = cfg.get("elevenlabs_voice_id") or DEFAULT_VOICE
        guess = next((v for v in pool if v["voice_id"] == want), None)
        if guess is None:
            guess = next((v for v in pool
                          if "dex" in v["name"].lower()), pool[0])
        choice = input(f"\nPress Enter to use '{guess['name']}', or type a "
                       "number from the list: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(pool):
            guess = pool[int(choice) - 1]
        picked = guess["voice_id"]

        cfg["elevenlabs_api_key"] = key
        cfg["elevenlabs_voice_id"] = picked
        save(cfg)
        print(f"\nSaved. Dexter will speak with: {voices[picked]}")
        print("Playing a test line ...")
        try:
            from dexter_voice import DexterVoice
            DexterVoice(cfg)._speak_elevenlabs(
                "I'm Dexter. Voice link established. All systems "
                "operational.")
            print("\nSUCCESS - that was Dexter's voice through your "
                  "speakers.\nYou're done: launch Dexter from the desktop "
                  "shortcut.")
        except Exception as exc:
            print(f"\nThe key and voice are saved, but the test playback "
                  f"failed with:\n  {exc}\nSend that line to Claude.")
        break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled.")
    input("\nPress Enter to close this window.")
