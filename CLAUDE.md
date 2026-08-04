# CLAUDE.md — Jarvis project context

This file is auto-loaded by Claude Code. It tells you (Claude) what this project
is and how it's built, so you can continue development without re-deriving it.

## What this is

**Jarvis** — a voice-activated desktop assistant for Windows, in the spirit of
Tony Stark's J.A.R.V.I.S. Say "Hey Jarvis" (or open-mic) and speak: it transcribes
locally (Whisper), thinks with the Anthropic Claude API (agentic tool loop),
replies out loud in a British voice, and shows a reactive arc-reactor HUD.
Conversations persist across sessions with long-term + semantic memory.

Single main file: `jarvis.py` (the `JarvisEngine` class is the core). It is NOT a
git repo. Backups of major versions live in `backups/` (`jarvis_pre_*.py`).

## Stack & how to run

- **Python 3.12** in a venv at `.venv/` (rebuild with `setup.bat`; never copy a venv).
- **Run:** `Launch Jarvis.bat` / the desktop shortcut (uses `.venv\Scripts\pythonw.exe jarvis.py`).
  Do NOT double-click `jarvis.py` directly — Windows opens it with the base Python
  (no deps). Headless (bot only, no GUI): `serve_headless.py`.
- **Brain:** Claude API. Model + keys in `config.json` (gitignored; has real keys).
  `config.example.json` is the template. Config auto-heals small JSON typos.
- **Headless test pattern:** construct `JarvisEngine.__new__(JarvisEngine)` and set
  only the attrs a method needs — avoids booting audio/models. Tests use this.

## Module map

| File | Purpose |
|---|---|
| `jarvis.py` | Engine (`JarvisEngine`), tk UI (`JarvisApp`), config, TTS/STT, HUD bridge, all watchers, `main()` |
| `jarvis_tools.py` | `TOOLS` schemas + `dispatch()` — the agentic tool layer (~52 tools) |
| `jarvis_glass.py` | WebGL "glass" HUD front-end via pywebview/WebView2 (see Known issues) |
| `jarvis_memory.py` | SQLite semantic memory (fastembed embeddings, no torch) |
| `jarvis_docs.py` | Document RAG index (SQLite + embeddings) |
| `jarvis_patterns.py` | Behavioural pattern store (routine learning, predictive pre-fetch) |
| `jarvis_persona.py` | Self-improvement / persona refinement store |
| `jarvis_autonomy.py` | Proactive act/ask decision rule, open-loops store, action log, approval gate |
| `jarvis_authority.py` | Guarded self-editing of own code (sandboxed + backup + compile-check + auto-revert) and PC commands (`run_command`, catastrophic hard-stop list). Tools: run/read/edit/write_own_code, restart_self |
| `jarvis_affect.py` | Prosody read of the user's voice (energy/rate/pauses/pitch → tone label) to adapt verbosity, TTS voice, and proactivity gating |
| `jarvis_episodes.py` | Time-indexed conversation episodes + `parse_timeframe`; the `recall_episode` tool answers "what did we discuss last Tuesday" |
| `jarvis_knowledge.py` | Local knowledge/answer cache (Q→A by question embedding); stable repeats are served from memory with no API call (hybrid serve/context, volatile-gated) |
| `jarvis_offline.py` | Deterministic offline brain (math/time/system/files/timers/notes) |
| `jarvis_local_llm.py` | Local-LLM tier client (OpenAI-compatible: Ollama/llama.cpp/etc.) |
| `jarvis_web.py` | `read_webpage` fetcher with a hard SSRF guard |
| `jarvis_remote.py` | Cloudflare tunnel (quick + named) for remote access |
| `jarvis_phone.py` | LAN phone bridge (scan → Claude vision commentary) |
| `jarvis_telegram.py` | Telegram front-end (text) |
| `jarvis_mcp.py` | MCP client — connect external tool servers (namespaced `mcp__<server>__<tool>`) |
| `jarvis_voiceid.py` / `jarvis_faceid.py` | Speaker-ID / face-auth (local, ONNX) |
| `google_integration.py` | Google Calendar (read) + Gmail (read + **compose/send**). Scope `gmail.compose`; sends are gated behind a spoken confirmation via `engine.arm_approval` -> `_resolve_pending_approval`. Tools: `create_email_draft`, `send_email`. Adding the send scope means token.json must be re-consented (`connect_google.py`). |
| `serve_headless.py` | Headless runner (bridges + brain, no mic/HUD) for a Pi/VPS |
| `serve_remote.py` | Standalone phone-bridge + tunnel |
| `web/` | HUD pages (`hud_holo.html` — WebGL2 particle `<jarvis-hologram>` — is the active HUD; `hud_aou.html` kept as fallback) + `hologram.js` engine + vendored Three.js (`web/vendor/three/`, offline) |
| `tests/` | `test_autonomy`, `test_web`, `test_remote`, `test_mcp` (run with `.venv\Scripts\python.exe tests\<name>.py`) |

## Major features (all built and in-tree)

Agentic tool use; long-term + semantic memory with reflective insights; document
RAG; **universal recall** (fuses memory+docs+email+calendar); autonomy layer
(proactive act/ask engine, standing goals/open-loops, approval gate, action log,
attention broker, ambient watch, predictive pre-fetch, self-improvement);
**offline mode** (vendored Three.js HUD, deterministic offline brain, Piper voice,
online→local-LLM→deterministic brain tiers); vision (screen + camera); voice-print
and face auth; **voice engines** `elevenlabs | edge | piper | xtts | chatterbox`
(xtts/chatterbox = local voice clones; chatterbox runs isolated in
`.venv-chatterbox`); Google Calendar/Gmail read + **Gmail write (draft + confirmation-gated send)** + **commitment capture**;
**PC control** (create/print documents); **media control** (system media keys +
play); front-ends: desktop HUD, LAN phone, **remote** (Cloudflare tunnel),
**Telegram**; **MCP client** (fetch + **Playwright browser control** wired: autonomous navigate/scroll/click/type/read-page/screenshot via `@playwright/mcp`, headless). Playwright MCP needs **Node.js 18+** on PATH (`npx`); launched as `cmd /c npx -y @playwright/mcp@latest --headless`. Browsers pre-installed to `%LOCALAPPDATA%\ms-playwright`.

## Conventions & gotchas

- **Single instance:** `single_instance_lock()` (named mutex) blocks a 2nd copy;
  `offer_to_end_running()` names/kills a stale holder.
- **Voice is spoken** — replies must be plain text (no markdown/symbols); `_clean_speech` strips them.
- **`_synth` picks ONE engine per reply** (`_resolve_tts_engine`: online→EL, offline→Piper) — never mid-reply mixing; retries transient failures.
- **Config edits** via `save_config_value(key, val)` (safe JSON write). Users hand-edit config and break JSON; the loader auto-heals leading-dot decimals + trailing commas.
- **Dependency pins that MUST hold:** `transformers>=4.57,<5` (XTTS), `torch>=2.1,<2.9` + `torchaudio` (avoids torchcodec), `numpy<2.2`. Chatterbox conflicts with the XTTS stack → its own venv.
- **Model weights** (Whisper/openwakeword/fastembed/XTTS) download to user caches, NOT the project. Piper voice + speaker/face models live in `voices/`. Run `prefetch_models.py` once online.
- Secrets live in `config.json`, `token.json`, `credentials.json` (gitignored). `.gitignore` also excludes venvs, `memory/`, `bin/`, model dirs, logs.

## HUD front-ends

`frontend: "glass"` (the default) shows the WebGL neural HUD in a native WebView2
window via `jarvis_glass.py`; `frontend: "tk"` shows the classic tk arc-reactor
window. Both drive the same engine. The glass HUD was verified working on the
original machine (2026-06-30, WebView2 runtime v149) — an earlier "won't launch"
episode was a stale leftover-process / single-instance-mutex collision, not a
WebView2 defect. If glass ever fails to open, `jarvis.py` auto-falls back to the
tk window; you can also render `web/hud_holo.html` in Chrome connected to the live
engine via the WS bridge (port 8765). `jarvis_glass.py` opens `hud_holo.html`
(`hud_aou.html` remains as a fallback). The hologram reacts to live state via
`window.jarvis.setState(...)` and to TTS/mic loudness via `window.jarvis.setLevel(0..1)`
(fed from the bridge's `{state, level}` messages).

