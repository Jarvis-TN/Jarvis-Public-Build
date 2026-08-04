# Jarvis Offline Voice Clone (XTTS)

A free, fully-local replacement for ElevenLabs: clone a voice from a short
reference clip and synthesize speech on your own machine — no API key, no
per-character cost, works offline.

It is **not** a reimplementation of ElevenLabs' models (those are proprietary and
GPU-hosted). It's the open equivalent of the *capability* you wanted — reference
audio in, cloned voice out — using **Coqui XTTS v2**.

## Two local clone engines

`tts_engine` accepts two local-clone options (plus `elevenlabs`/`edge`/`piper`):

- **`xtts`** — Coqui XTTS v2, runs in the main environment. Good cloning quality.
- **`chatterbox`** — Resemble AI Chatterbox (Turbo). In blind tests listeners
  preferred it over **ElevenLabs Turbo 65%** of the time. Runs **isolated** (see
  below). GPU strongly recommended.

Either way the fallback chain ends at Piper, so Jarvis keeps talking even if a
clone fails to load: `xtts|chatterbox  →  (on failure)  →  piper`.

## Chatterbox (the "beats ElevenLabs" option) — isolated setup

Chatterbox has **hard dependency conflicts** with the XTTS/coqui stack (it pulls
`transformers 5.x` and downgrades torch/numpy, which breaks XTTS). So it runs in
its **own** virtual environment as a tiny local server, and Jarvis talks to it
over localhost — the two dependency worlds never touch.

1. Run **`setup_chatterbox.bat`** — builds `.venv-chatterbox`, installs
   `chatterbox-tts` (CUDA build if you have an NVIDIA GPU).
2. Make sure you have a reference clip (`voices/clone/reference.wav`, e.g. from
   `capture_voice_reference.py`).
3. Set `"tts_engine": "chatterbox"` in `config.json` and launch Jarvis. It starts
   the Chatterbox server (`chatterbox_server.py`) automatically and speaks through
   it; first launch downloads the model.

Config: `chatterbox_model` (`turbo`/`standard`), `chatterbox_reference_wav`,
`chatterbox_exaggeration` (0.5, raise for drama), `chatterbox_cfg_weight` (0.5),
`chatterbox_port` (8123). **Chatterbox is slow on CPU — it really wants the GPU
desktop.**

## One-time setup

1. **Capture a reference** of the voice you want (done while you still have EL):
   ```
   python capture_voice_reference.py
   ```
   Synthesizes ~30s from your ElevenLabs "Jarvis" voice into
   `voices/clone/reference.wav` and records its path in config. (Or set
   `xtts_reference_wav` to any clean ~10–30s WAV/clip of a voice you have rights
   to use.)

2. **Preview the clone** (first run downloads the ~1.8GB model):
   ```
   python preview_voice_clone.py
   ```
   Confirms it works and lets you hear it.

3. **Switch Jarvis to it**: set `"tts_engine": "xtts"` in `config.json`. Done —
   Jarvis now speaks in the cloned voice, offline and free.

## Config

| Key | Default | Meaning |
|---|---|---|
| `tts_engine` | `elevenlabs` | Set to `xtts` to use the local clone. |
| `xtts_reference_wav` | `""` | Reference clip to clone; blank → `voices/clone/reference.wav`. |
| `xtts_language` | `en` | Synthesis language. |
| `xtts_speed` | `1.0` | >1 faster, <1 slower. |
| `xtts_temperature` | `0.65` | Higher = more expressive/variable delivery. |

The speaker latents are computed from the reference **once** at load and cached,
so only the text is synthesized per sentence (the slow part on CPU is avoided).

## Performance & expectations

- **CPU-only** (this machine): a sentence takes a few seconds to synthesize. The
  gapless sentence-ahead pipeline (synthesize the next line while the current one
  plays) hides most of that, but it isn't as instant as the cloud API. A GPU
  would make it ~real-time.
- **Quality**: very good and recognizably the same voice, but not bit-identical
  to ElevenLabs.
- First load downloads ~1.8GB to the local model cache; after that it's offline.

## Dependencies & licensing

Adds `coqui-tts`, `torch`, `torchaudio` (CPU build). Notes from setup:
- Pin **`transformers>=4.57,<5`** — XTTS uses an API removed in transformers 5.x.
- Use **torch 2.8** (CPU) — torch ≥2.9 demands `torchcodec`; 2.8 uses `soundfile`.
- XTTS v2's model licence (Coqui Public Model Licence) is **non-commercial** —
  fine for personal use. Only clone voices you have the right to use.
