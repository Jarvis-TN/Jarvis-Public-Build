"""Capture a voice-clone reference from your ElevenLabs 'Jarvis' voice.

Run this ONCE while you still have ElevenLabs access. It synthesizes a handful of
varied lines in your current cloned voice and stitches them into a single clean
mono WAV at voices/clone/reference.wav. The local XTTS engine (tts_engine:
"xtts") then clones THAT, so your offline Jarvis sounds like the paid one - with
no key and no per-character cost afterwards.

    python capture_voice_reference.py            # uses the EL voice from config
    python capture_voice_reference.py --play     # also play the result back

Cost: a few thousand characters of ElevenLabs synthesis (well under a minute of
audio) - a one-time spend to seed the free local clone.
"""

import os
import io
import sys
import wave

import numpy as np
import av

import jarvis

APP_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(APP_DIR, "voices", "clone")
OUT_WAV = os.path.join(OUT_DIR, "reference.wav")
TARGET_SR = 24000

# Varied lines (statements, a question, a longer sentence) give the cloner a
# fuller picture of the voice's prosody than one flat reading would.
LINES = [
    "Good evening, sir. All systems are online and functioning within normal parameters.",
    "I've taken the liberty of preparing your morning briefing.",
    "Shall I proceed, or would you prefer to review the details first?",
    "The figures are rather promising, though I'd advise a measure of caution.",
    "Of course. Consider it done.",
    "I'm detecting an anomaly in the data, sir - it may warrant your attention.",
    "Welcome home. I trust your day was productive.",
    "Right away. And might I say, an excellent choice.",
]


def _mp3_to_mono_int16(mp3_bytes, sr=TARGET_SR):
    """Decode ElevenLabs MP3 bytes to a mono int16 numpy array at `sr`."""
    container = av.open(io.BytesIO(mp3_bytes))
    resampler = av.AudioResampler(format="s16", layout="mono", rate=sr)
    out = []
    for frame in container.decode(audio=0):
        for rf in resampler.resample(frame):
            out.append(rf.to_ndarray().reshape(-1))
    for rf in resampler.resample(None):    # flush
        out.append(rf.to_ndarray().reshape(-1))
    container.close()
    if not out:
        return np.zeros(0, dtype=np.int16)
    return np.concatenate(out).astype(np.int16)


def main():
    cfg = jarvis.load_config()
    if not cfg.get("elevenlabs_api_key"):
        print("No ElevenLabs API key in config.json - can't capture a reference.")
        return 1
    from elevenlabs.client import ElevenLabs
    from elevenlabs import VoiceSettings
    client = ElevenLabs(api_key=cfg["elevenlabs_api_key"])
    voice_id = cfg.get("elevenlabs_voice_id")
    model_id = cfg.get("elevenlabs_model", "eleven_turbo_v2_5")
    settings = VoiceSettings(
        stability=float(cfg.get("el_stability", 0.45)),
        similarity_boost=float(cfg.get("el_similarity", 0.85)),
        style=float(cfg.get("el_style", 0.35)),
        use_speaker_boost=True,
        speed=float(cfg.get("el_speed", 1.12)),
    )

    print(f"Capturing reference from ElevenLabs voice {voice_id} ...")
    gap = np.zeros(int(0.35 * TARGET_SR), dtype=np.int16)   # short pause between lines
    pieces = []
    for i, line in enumerate(LINES, 1):
        try:
            audio = client.text_to_speech.convert(
                voice_id=voice_id, text=line, model_id=model_id,
                output_format="mp3_44100_128", voice_settings=settings)
            mp3 = b"".join(c for c in audio if c)
            pcm = _mp3_to_mono_int16(mp3)
            if len(pcm):
                pieces.append(pcm)
                pieces.append(gap)
            print(f"  [{i}/{len(LINES)}] {len(pcm)/TARGET_SR:.1f}s  \"{line[:48]}...\"")
        except Exception as e:
            print(f"  [{i}/{len(LINES)}] failed: {e}")

    if not pieces:
        print("Got no audio from ElevenLabs - nothing written.")
        return 1
    full = np.concatenate(pieces)
    os.makedirs(OUT_DIR, exist_ok=True)
    with wave.open(OUT_WAV, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(TARGET_SR)
        wf.writeframes(full.tobytes())
    secs = len(full) / TARGET_SR
    print(f"\nWrote {OUT_WAV} ({secs:.1f}s).")
    print("Set \"tts_engine\": \"xtts\" in config.json to use the local clone.")

    # persist the path so the engine finds it without further config
    try:
        jarvis.save_config_value("xtts_reference_wav", OUT_WAV)
    except Exception:
        pass

    if "--play" in sys.argv:
        try:
            import pygame
            pygame.mixer.init()
            pygame.mixer.music.load(OUT_WAV)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                pygame.time.wait(200)
        except Exception as e:
            print(f"(Couldn't play it back: {e})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
