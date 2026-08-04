# Moving Jarvis to another PC (e.g. a faster desktop)

The whole build is just this folder. To recreate an **exact copy** on another
Windows PC, copy the files and rebuild the environment there — don't try to
regenerate the code, and don't reuse the old `.venv`.

## What to copy

Copy the entire `Jarvis` folder to the new PC (USB stick is fine). You can skip
two things to save space — they're rebuilt/refetched anyway:

- **`.venv\`** (several GB) — NOT portable (absolute paths). It gets deleted and
  rebuilt by `setup_desktop.bat`. Skip copying it.
- **`voices\`, `bin\`** — model weights / cloudflared re-download on first run.
  (Optional: copying `voices\clone\reference.wav` saves re-capturing your voice
  reference.)

Everything else — all the `.py` modules, `web\`, `config.json`, `*.bat`,
`requirements.txt` — is the build.

> ⚠ **Secrets travel with the folder.** `config.json` (Anthropic + ElevenLabs
> keys), `token.json` and `credentials.json` (Google OAuth) are in cleartext.
> A USB stick carrying them is a key you don't want to lose — wipe the stick
> afterwards, and only move between machines you control.

## Rebuild on the new PC

1. Install **Python 3.12** (the same the project targets).
2. Double-click **`setup_desktop.bat`**. It:
   - deletes any copied `.venv` and builds a fresh one,
   - **detects an NVIDIA GPU** and installs the matching PyTorch (CUDA build if
     present, CPU build otherwise),
   - installs all dependencies,
   - pre-downloads the model weights (Whisper, embeddings, XTTS voice clone),
   - regenerates the desktop shortcuts for that machine.
3. Confirm `config.json` has your API key, then launch via the **Jarvis HUD**
   shortcut.

That's it — same Jarvis, now on the faster box.

## Faster platform notes

- **HUD:** with a real GPU, the WebGL glass HUD hardware-accelerates — the
  cinematic `hud_aou.html` runs smooth (no software-render freezes / LITE mode).
  No code change needed.
- **Voice clone / STT:** the code is **device-aware** (`compute_device: "auto"`
  in config). On a GPU it automatically runs Whisper in `float16` and moves XTTS
  to CUDA — roughly real-time synthesis instead of ~2× slower on CPU. Force it
  with `compute_device: "cpu"` or `"cuda"` if you ever need to.
- If the CUDA torch install errors for your driver, edit the `cu121` in
  `setup_desktop.bat` to `cu124` or `cu128` and re-run.

## If you'd rather sync than carry a USB

The folder lives in OneDrive, so signing into the same OneDrive on the new PC
brings the source over automatically; then run `setup_desktop.bat`. (Or ask me to
`git init` it for a clean `git clone` / `git pull` workflow — `.gitignore`
already excludes the venv, secrets, and model weights.)
