"""Preview the local XTTS voice clone (offline).

Synthesizes a sample line by cloning voices/clone/reference.wav (your captured
ElevenLabs voice) and saves voices/clone/_preview.wav, then plays it. The first
run downloads the XTTS model (~1.8GB, one time). Use it to hear the clone and to
confirm the offline engine works before switching tts_engine to "xtts".

    python preview_voice_clone.py
    python preview_voice_clone.py "A custom line to say"
"""

import os
import sys
import time
import wave

import numpy as np

import jarvis

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "voices", "clone", "_preview.wav")
DEFAULT_LINE = ("Good evening, sir. My voice is now running entirely offline, "
                "cloned from your own reference. No subscription required.")


def main():
    line = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_LINE
    # Build the real engine object without booting audio/models, then call the
    # actual integration method so this verifies the shipping code path.
    eng = jarvis.JarvisEngine.__new__(jarvis.JarvisEngine)
    eng.cfg = dict(jarvis.load_config())
    eng.status_cb = lambda m: print(m)
    eng._xtts = None
    eng._xtts_model = None
    eng._xtts_latents = None
    eng._xtts_failed = False

    ref = eng._xtts_reference()
    if not ref:
        print("No reference clip found. Run capture_voice_reference.py first.")
        return 1
    print(f"Reference: {ref}")

    print("Loading model (first run downloads ~1.8GB)...")
    t0 = time.time()
    eng._synth_xtts(line, OUT)
    dt = time.time() - t0

    with wave.open(OUT, "rb") as w:
        n, sr = w.getnframes(), w.getframerate()
        data = np.frombuffer(w.readframes(n), dtype="<i2")
    dur = n / sr if sr else 0
    rms = int(np.sqrt(np.mean(data.astype(np.float64) ** 2))) if len(data) else 0
    print(f"Synthesized {dur:.1f}s of audio in {dt:.1f}s "
          f"({dt / dur:.2f}x realtime) | rms={rms} | -> {OUT}")
    if rms < 50:
        print("WARNING: output looks silent.")
        return 1

    try:
        import pygame
        pygame.mixer.init()
        pygame.mixer.music.load(OUT)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.wait(200)
    except Exception as e:
        print(f"(Saved, but couldn't play it here: {e}. Open the WAV to listen.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
