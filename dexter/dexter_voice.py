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

    def stop(self):
        self._stop.set()

    def speak(self, text):
        """Blocking; call from a worker thread. Returns the engine used."""
        text = (text or "").strip()
        if not text:
            return None
        self._stop.clear()
        self.on_state("speaking")
        try:
            engine = self.cfg.get("tts_engine", "auto")
            use_el = (engine in ("auto", "elevenlabs")
                      and self.cfg.get("elevenlabs_api_key")
                      and self.cfg.get("elevenlabs_voice_id"))
            if use_el:
                try:
                    self._speak_elevenlabs(text)
                    return "elevenlabs"
                except Exception:
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
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    cfg = {}
    for name in ("config.json", "config.example.json"):
        path = os.path.join(here, name)
        if os.path.exists(path):
            cfg = json.load(open(path, encoding="utf-8"))
            break
    voice = DexterVoice(cfg, on_level=lambda level: print(f"\rlevel {level:0.2f}", end=""))
    used = voice.speak("Pikachu. The Mouse Pokemon. When several of these "
                       "Pokemon gather, their electricity could build and "
                       "cause lightning storms.")
    print(f"\nspoke via: {used}")
