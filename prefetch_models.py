"""Pre-download the model weights Jarvis needs that DON'T travel in the project
folder (they live in per-user caches): Whisper STT, fastembed embeddings, and
the XTTS voice-clone model. Run this once on a new machine (with internet) so the
first real launch isn't slow - and so Jarvis is ready to work offline afterwards.

    python prefetch_models.py

Honors compute_device in config (uses the GPU if present). Safe to re-run.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    import jarvis
    cfg = jarvis.load_config()
    dev_pref = cfg.get("compute_device", "auto")
    print(f"Compute device preference: {dev_pref}")

    # 1) Whisper STT
    try:
        print("\n[1/3] Whisper speech model...")
        from faster_whisper import WhisperModel
        dev = "cpu"
        ctype = "int8"
        try:
            import torch
            if dev_pref != "cpu" and torch.cuda.is_available():
                dev, ctype = "cuda", "float16"
        except Exception:
            pass
        WhisperModel(cfg.get("whisper_model", "base.en"), device=dev, compute_type=ctype)
        print(f"      ok ({dev})")
    except Exception as e:
        print(f"      skipped: {e}")

    # 2) fastembed (semantic memory + document RAG)
    try:
        print("\n[2/3] fastembed embedding model...")
        from fastembed import TextEmbedding
        emb = TextEmbedding("BAAI/bge-small-en-v1.5")
        list(emb.embed(["warm up"]))
        print("      ok")
    except Exception as e:
        print(f"      skipped: {e}")

    # 3) Piper - the offline voice (used whenever there's no internet)
    try:
        print("\n[3/4] Piper offline voice...")
        import jarvis
        eng = jarvis.JarvisEngine.__new__(jarvis.JarvisEngine)
        eng.cfg = cfg
        eng.status_cb = lambda m: None
        eng._piper = None
        eng._get_piper()    # downloads the voice model if missing
        print("      ok")
    except Exception as e:
        print(f"      skipped: {e}")

    # 4) XTTS voice clone (only if it's the chosen engine or a reference exists)
    try:
        ref = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "voices", "clone", "reference.wav")
        want_xtts = cfg.get("tts_engine") == "xtts" or os.path.exists(ref) \
            or (cfg.get("xtts_reference_wav") or "").strip()
        if want_xtts:
            print("\n[4/4] XTTS voice-clone model (~1.8GB)...")
            os.environ.setdefault("COQUI_TOS_AGREED", "1")
            from TTS.api import TTS
            TTS("tts_models/multilingual/multi-dataset/xtts_v2")
            print("      ok")
        else:
            print("\n[4/4] XTTS skipped (tts_engine is not 'xtts' and no reference.wav).")
    except Exception as e:
        print(f"      skipped: {e}")

    print("\nDone. Models are cached locally; Jarvis can now run offline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
