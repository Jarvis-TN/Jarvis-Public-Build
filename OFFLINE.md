# Jarvis Offline Mode

Jarvis now works with **no internet** — the HUD renders, the voice speaks, and a
local brain handles practical commands. Here's what's offline-capable and what
still needs a connection.

## What works offline

| Area | Offline behavior |
|---|---|
| **Glass HUD** | Fully — Three.js is vendored locally (`web/vendor/three/`), so the WebGL HUD and its buttons load with no CDN. |
| **Speech-to-text** | Fully — Whisper runs locally. |
| **Voice (TTS)** | Fully — falls back to **Piper** (local neural voice). Online engines are skipped instantly when offline (no timeout). |
| **Brain** | A deterministic **offline handler** (`jarvis_offline.py`) covers: simple maths, time/date, battery/CPU/memory, finding/reading/opening local files, opening apps, timers, and notes. |

## Three brain tiers

Jarvis now picks a brain per turn:

1. **Online → Claude** (the full cloud brain).
2. **Offline + a local LLM configured → the local LLM** — free-form conversation
   *with tools*, fully offline (`jarvis_local_llm.py`).
3. **Otherwise → the deterministic offline handler** (`jarvis_offline.py`) for
   maths/time/system/files/timers/notes.

(Set `local_llm_when: "always"` to use the local model even when online — for
privacy or to avoid API cost.)

## Local LLM setup (optional, for offline conversation)

The local tier talks to any **OpenAI-compatible** server, so the runtime is
swappable. Easiest is **Ollama**:

1. Install Ollama from ollama.com.
2. Pull a tool-capable model: `ollama pull llama3.1:8b` (or `qwen2.5:7b`).
3. In `config.json`: `"local_llm_enabled": true` (model/endpoint default to
   Ollama). Restart Jarvis.

**Faster/better runtimes than Ollama** (same `/v1` API — just change
`local_llm_base_url`):
- **CPU:** Ollama/llama.cpp are equivalent (Ollama *is* llama.cpp under the hood).
- **NVIDIA GPU (your desktop):** **llama.cpp server** with CUDA, or
  **ExLlamaV2/TabbyAPI** (EXL2 quants) for the fastest single-user speed; **vLLM**
  only if you ever serve multiple users. Ollama with CUDA is already fast and by
  far the simplest — start there, swap later if you want more.

## What still needs a connection

Web search, weather, calendar/email (those tools hit the internet), and the
ElevenLabs voice *clone* quality. The local LLM covers conversation/reasoning
offline; the deterministic handler covers commands.

## How it decides

`respond()` does a fast, cached connectivity check (`_online()` — a 1.5s TCP probe
to the API, cached 15s). If there's no route to the cloud, the turn is handled by
`jarvis_offline.handle()` instead of failing. Anything it can't do returns an
honest "I'm offline, here's what I can still do."

## Try it (offline)

- "What's 15 percent of 240?" → *"That's 36."*
- "What time is it?" / "How's my battery?"
- "Find files called invoice" / "Read the file shopping list"
- "Open Notepad" / "Set a timer for 5 minutes" / "Remember that I parked on level 3"

## Setup for offline use

Run `python prefetch_models.py` once **while online** to cache everything offline
mode needs: Whisper, embeddings, the **Piper** voice, (and XTTS if you use the
clone). After that, Jarvis runs disconnected.

## Notes

- The active HUD is `web/hud_aou.html` (loaded by `jarvis_glass.py`). It's the one
  vendored for offline. The older `hud.html`/`index.html` still reference the CDN
  (they're not the launched HUD); re-run `vendor_three.py` logic for them if ever
  needed.
- To re-vendor or bump the Three.js version: `python vendor_three.py`.
