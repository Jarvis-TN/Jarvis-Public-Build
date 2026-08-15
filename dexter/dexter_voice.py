"""Dexter's voice.

Primary engine: ElevenLabs, streaming raw PCM so we can measure loudness in
real time and drive the Pokedex's blue lens flash while Dexter talks.
Fallback: Windows SAPI via pyttsx3 (offline, no key needed) with a simulated
pulse so the lens still animates.

Voice cloning note: put your ElevenLabs voice ID in config.json
("elevenlabs_voice_id"). Build the voice itself in the ElevenLabs dashboard —
either Voice Design (describe the flat, robotic Pokedex delivery and iterate
until it sounds right; no source audio needed) or Voice Lab cloning, which
per ElevenLabs' terms requires the rights/consent for the voice you upload.
"""

from __future__ import annotations

import json
import math
import threading
import time

import requests


class DexterVoice:
    def __init__(self, cfg, on_level=None, on_state=None):
        """
        cfg: dict with elevenlabs_api_key / elevenlabs_voice_id / etc.
        on_level(0..1): called ~30x/sec with speech loudness (drives the lens).
        on_state("speaking"|"idle"): called at start/end of each utterance.
        """
        self.cfg = cfg
        self.on_level = on_level or (lambda level: None)
        self.on_state = on_state or (lambda state: None)
        self._sapi = None
        self._stop = threading.Event()
        self.last_error = None   # why the last utterance fell back to SAPI

    def stop(self):
        self._stop.set()

    def speak(self, text):
        """Blocking; call from a worker thread. Returns the engine used."""
        text = (text or "").strip()
        if not text:
            return None
        self._stop.clear()
        self.last_error = None
        self.on_state("speaking")
        try:
            engine = self.cfg.get("tts_engine", "auto")
            use_el = (engine in ("auto", "elevenlabs")
                      and self.cfg.get("elevenlabs_api_key")
                      and self.cfg.get("elevenlabs_voice_id"))
            if engine in ("auto", "elevenlabs") and not use_el:
                self.last_error = "ElevenLabs key or voice id missing in config.json"
            if use_el:
                try:
                    self._speak_elevenlabs(text)
                    return "elevenlabs"
                except Exception as exc:
                    self.last_error = str(exc)[:300]
                    if engine == "elevenlabs":
                        raise
            self._speak_sapi(text)
            return "sapi"
        finally:
            self.on_level(0.0)
            self.on_state("idle")

    # ------------------------------------------------------------ engines ---

    def _speak_elevenlabs(self, text):
        import numpy as np
        import sounddevice as sd

        voice_id = self.cfg["elevenlabs_voice_id"]
        url = (f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
               f"?output_format=pcm_22050")
        payload = {
            "text": text,
            "model_id": self.cfg.get("elevenlabs_model", "eleven_turbo_v2_5"),
            "voice_settings": {
                "stability": self.cfg.get("voice_stability", 0.65),
                "similarity_boost": self.cfg.get("voice_similarity", 0.85),
            },
        }
        r = requests.post(url, json=payload, stream=True, timeout=60,
                          headers={"xi-api-key": self.cfg["elevenlabs_api_key"]})
        if r.status_code != 200:
            raise RuntimeError(f"ElevenLabs {r.status_code}: {r.text[:200]}")

        # Download fully first (turbo streams fast), then play with per-block
        # RMS so the lens flash follows the actual audio, not network jitter.
        pcm = b"".join(chunk for chunk in r.iter_content(chunk_size=8192) if chunk)
        audio = np.frombuffer(pcm, dtype=np.int16)
        if audio.size == 0:
            raise RuntimeError("ElevenLabs returned no audio")

        block = 735  # 22050 Hz / 30 fps
        with sd.RawOutputStream(samplerate=22050, channels=1, dtype="int16") as out:
            for i in range(0, len(audio), block):
                if self._stop.is_set():
                    break
                chunk = audio[i:i + block]
                rms = float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))
                self.on_level(min(1.0, rms / 6000.0))
                out.write(chunk.tobytes())

    def _speak_sapi(self, text):
        import pyttsx3
        if self._sapi is None:
            self._sapi = pyttsx3.init()
            self._sapi.setProperty("rate", int(self.cfg.get("sapi_rate", 175)))
        pulse_done = threading.Event()

        def pulse():
            # No PCM access with SAPI, so approximate a talking cadence.
            t0 = time.time()
            while not pulse_done.is_set() and not self._stop.is_set():
                t = time.time() - t0
                level = 0.45 + 0.35 * math.sin(t * 9.0) * math.sin(t * 2.3)
                self.on_level(max(0.15, min(1.0, level)))
                time.sleep(0.033)

        thread = threading.Thread(target=pulse, daemon=True)
        thread.start()
        try:
            self._sapi.say(text)
            self._sapi.runAndWait()
        finally:
            pulse_done.set()
            thread.join(timeout=1)


if __name__ == "__main__":
    # Verbose self-diagnostic: run  .venv\Scripts\python.exe dexter_voice.py
    import os
    import traceback

    here = os.path.dirname(os.path.abspath(__file__))
    cfg, cfg_name = {}, None
    for name in ("config.json", "config.example.json"):
        path = os.path.join(here, name)
        if os.path.exists(path):
            cfg = json.load(open(path, encoding="utf-8"))
            cfg_name = name
            break
    print(f"config file : {cfg_name or 'NONE FOUND'}")
    key = cfg.get("elevenlabs_api_key") or ""
    vid = cfg.get("elevenlabs_voice_id") or ""
    print(f"api key     : {key[:6] + '...' + key[-4:] if key else 'MISSING'}")
    print(f"voice id    : {vid or 'MISSING'}")
    print(f"tts_engine  : {cfg.get('tts_engine', 'auto')}")

    if key:
        print("checking account ...")
        try:
            r = requests.get("https://api.elevenlabs.io/v1/voices",
                             headers={"xi-api-key": key}, timeout=30)
            print(f"  voices endpoint: HTTP {r.status_code}")
            if r.status_code == 200:
                voices = {v["voice_id"]: v["name"]
                          for v in r.json().get("voices", [])}
                for v_id, v_name in voices.items():
                    mark = "   <-- selected" if v_id == vid else ""
                    print(f"    {v_id}  {v_name}{mark}")
                if vid and vid not in voices:
                    print("  PROBLEM: the selected voice id is not in this "
                          "account's voice list. In ElevenLabs, open the "
                          "voice and add it to My Voices, or copy the exact "
                          "voice ID from its ... menu.")
            else:
                print("  PROBLEM: " + r.text[:300])
        except Exception:
            print("  PROBLEM reaching ElevenLabs:")
            traceback.print_exc()

    text = ("Pikachu. The Mouse Pokemon. When several of these Pokemon "
            "gather, their electricity could build and cause lightning "
            "storms.")
    voice = DexterVoice(cfg)
    if key and vid:
        print("synthesis test (forcing ElevenLabs) ...")
        try:
            voice._speak_elevenlabs(text)
            print("SUCCESS: that was the ElevenLabs Dexter voice.")
        except Exception:
            print("FAILED with:")
            traceback.print_exc()
    else:
        used = voice.speak(text)
        print(f"spoke via: {used} (ElevenLabs not configured)")
