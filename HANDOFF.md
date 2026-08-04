# Jarvis — Handoff / New-Account Setup

Everything to move Jarvis to a new account/machine (e.g. personal → enterprise)
and keep building. The package is source-only — it rebuilds its environment on
arrival.

## What's in the package

- All source (`jarvis.py` + every `jarvis_*.py`, `serve_*.py`, `google_integration.py`)
- `web/` (HUD pages + vendored Three.js so the HUD works offline)
- `tests/`, all `*.bat` launchers, `requirements*.txt`, `setup*.bat`, `config.example.json`
- **`CLAUDE.md`** — auto-loaded by Claude Code so the new session understands the project
- `memory/` — your Jarvis's accumulated memory/notes/open-loops (your data)

## NOT in the package (rebuilt or re-added on the new machine)

- `.venv/`, `.venv-chatterbox/` — virtual envs are not portable; rebuilt by setup
- `__pycache__/`, `*.pyc`, logs
- **Secrets** — `config.json`, `token.json`, `credentials.json` were **excluded on
  purpose**. Add your ENTERPRISE keys fresh (see step 3). (For Google, re-run
  `connect_google.py` to make a new `token.json`.)
- Model weights (Whisper/embeddings/XTTS re-download; Piper/speaker/face models
  re-download) — run `prefetch_models.py`.

## Setup on the new machine

1. **Install Python 3.12.**
2. Unzip the project somewhere (e.g. `Documents\Code\Jarvis`), then run **`setup.bat`**
   (builds `.venv` + installs `requirements.txt`).
3. Copy `config.example.json` → `config.json` and fill in your **enterprise**
   `anthropic_api_key` (and any others you use: ElevenLabs, etc.).
   Recommended for the new machine: `"frontend": "tk"` (see note below).
4. `.venv\Scripts\python.exe prefetch_models.py` (once, online) to cache the models.
5. Launch with **`Launch Jarvis.bat`** (or the desktop icon). Regenerate desktop
   shortcuts with `make_shortcuts.ps1` if you want them.
6. (Optional) Chatterbox voice clone: `setup_chatterbox.bat`. Raspberry Pi / always-on
   host: see `PI_DEPLOY.md` + `setup_pi.sh`.

## Making the new Claude Code account "recognize what you've done"

- `CLAUDE.md` is read automatically when you open the project — that alone gives a
  fresh session full context.
- (Optional) To carry over Claude Code's own memory files too, copy the folder
  `~/.claude/projects/<project>/memory/` on the old machine to the same location on
  the new one (only matters if the project path differs).

## Note on the glass HUD

The glass WebGL HUD (`"frontend": "glass"`) runs correctly on the original machine
(verified 2026-06-30 — WebView2 runtime v149 present; a WebView2 window hosting
`hud_aou.html` opens and closes cleanly under the venv `pythonw.exe`). The earlier
"won't launch" reports were a stale leftover-process / single-instance-mutex
collision, since cleared — not a real WebView2 defect.

On a *new* machine the HUD still depends on a healthy Edge WebView2 runtime. If
`glass` doesn't open there, either stay on `"frontend": "tk"` (the classic window
is always reliable, and `jarvis.py` auto-falls back to it if glass ever throws) or
render `web/hud_aou.html` in Chrome against the live WS bridge (port 8765).
