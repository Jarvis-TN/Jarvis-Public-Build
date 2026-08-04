# Jarvis — voice assistant powered by Claude

A desktop app you can talk to, in the spirit of Iron Man's J.A.R.V.I.S. Say
**"Hey Jarvis"** and just speak — it transcribes locally with Whisper, thinks with
Anthropic's Claude, and replies out loud in a calm British voice. A futuristic
arc-reactor HUD animates in time with its speech. It remembers your conversations
across sessions and folds older history into a long-term memory so it keeps
learning about you.

## Features

- 🎤 **Open-mic, always listening** — just speak; no wake word or button needed.
  Auto-**mutes during video calls** (when your webcam is active) and resumes after.
  A **Listen** button + `activation_mode` let you switch to "Hey Jarvis" or button-only.
- 🧠 **Thinks like Claude** — uses the Claude API as its brain.
- 🛠️ **Has hands (tool use)** — tells time, checks **weather**, **web search**, opens
  apps/websites, sets **timers** (announced aloud), reports **system status**, takes notes.
- 🔊 **Sound design + boot sequence** — power-up chord, wake chime, ambient thinking hum.
- 🪟 **Floating overlay** — frameless, always-on-top, translucent, draggable HUD.
- 🎚️ **Pick your mic** — choose any input device (🎚 button or tray) and it sticks.
- 🗔 **Runs in the tray** — minimize to the background; restore from the tray icon.
- 🚀 **Start with Windows** — optional auto-launch, then a spoken **daily briefing** on load.
- ✋ **Barge-in** — talk over Jarvis to interrupt/correct him; patient end-of-turn detection.
- 📅 **Google Calendar + Gmail** — reads your schedule and inbox (read-only); folds them into the daily briefing.
- 🧠 **Persistent semantic memory** — a local SQLite database with embedding-based recall;
  auto-captures durable facts about you and surfaces the relevant ones each turn (works offline).
- 🚀 **Voice app launcher** — "open Spotify," "launch OBS"; auto-finds installed programs from
  your Start Menu. Define multi-app **"setups"** (Stream-Deck-style) by voice and launch them by name.
- 🎙️ **Expressive British voice** — ElevenLabs neural voice with real butler-like
  inflection (free Edge British voice as fallback).
- 🌀 **Stark-grade HUD** — arc-reactor interface with a live frequency-spectrum ring
  driven by the actual voice, targeting brackets, telemetry readouts, and energy rings.
- 🧩 **Long-term memory** — every exchange is saved; older turns are summarized into
  a persistent memory the assistant carries forward.
- ⌨️ **Type too** — a text box for when you'd rather not speak.

## First-time setup

1. **Run `setup.bat`** — builds a private Python environment and installs everything.
2. **Add your API key** — open `config.json`, paste your Anthropic key into
   `"anthropic_api_key"`. Get one at <https://console.anthropic.com/settings/keys>.
3. **Launch** — double-click **`Launch Jarvis.bat`** or the **Jarvis** desktop icon.

> On first launch it downloads small models once: the Whisper speech model (~75 MB)
> and the wake-word model (~few MB). After that, startup is quick.

## Using it

- **Say "Hey Jarvis"** — then speak your request; pause and it responds.
- **Talk button / Space** — start listening without the wake word.
- **Stop** — interrupt Jarvis mid-sentence.
- **Text box** — type and press Enter.
- The **HUD** shows its state: STANDBY, LISTENING, PROCESSING, SPEAKING.

## Settings (`config.json`)

| Field | What it does |
|-------|--------------|
| `anthropic_api_key` | Your Claude API key (kept local, never shared). |
| `model` | `claude-sonnet-4-6` (smart + cheap) or `claude-opus-4-8` (smartest). |
| `tts_engine` | `elevenlabs` (expressive, needs key) or `edge` (free, robotic-ish). |
| `elevenlabs_api_key` | Your ElevenLabs key. Get one at <https://elevenlabs.io>. |
| `elevenlabs_voice_id` | Which voice. Default is "George" (British). Browse the ElevenLabs Voice Library and paste any voice's ID here. |
| `elevenlabs_model` | `eleven_turbo_v2_5` (fast) or `eleven_multilingual_v2` (richest). |
| `el_stability` | 0–1. Lower = more expressive/varied inflection; higher = steadier. |
| `el_style` | 0–1. Higher = more dramatic delivery. |
| `el_speed` | Speaking pace, ~0.7–1.2. Default `1.12`. |
| `voice` (Edge fallback) | Used only if ElevenLabs is off/unavailable. `en-GB-ThomasNeural`, etc. |
| `voice_rate` / `voice_pitch` | Edge-fallback delivery tuning. |
| `whisper_model` | `base.en` (fast), `small.en` (more accurate), `tiny.en` (fastest). |
| `stream_replies` | Start speaking the first sentence while the rest is still being written (used when tools are off). |
| `tools_enabled` | Let Jarvis use tools (time, weather, web search, open apps/sites, timers, system status, notes). |
| `sounds_enabled` | UI sound effects + ambient hum. |
| `boot_sequence` | Animated power-up + startup chord on launch. |
| `overlay_mode` | Frameless, always-on-top, translucent floating window. Set `false` for a normal window. |
| `overlay_opacity` | Overlay translucency, 0–1 (e.g. `0.95`). |
| `show_chat` | Start with the transcript visible. Default `false` for a clean HUD-only view; toggle anytime with the **▤ Chat** button. |
| `activation_mode` | `open` (always listening, just speak), `wake` ("Hey Jarvis"), or `button` (Talk/Space only). |
| `pause_on_camera` | Auto-mute the mic whenever your webcam is in use (video calls), then resume when it's free. |
| `open_onset_threshold` | Open-mic sensitivity: how loud speech must be to start a turn (raise to `0.03+` if it triggers on background noise). |
| `silence_hang_seconds` | How long you must pause before your turn is considered finished. Raise it (e.g. `2.2`) if Jarvis jumps in while you're still thinking. |
| `barge_in` | Let you interrupt Jarvis by speaking over it (it stops and listens). |
| `barge_in_threshold` | How loud you must be to interrupt. **On speakers, raise this** (e.g. `0.1`) so Jarvis's own voice doesn't trip it; headphones work best at the default. |
| `barge_in_frames` | How long sustained speech (×~80ms) confirms an interrupt. |
| `input_device` | Which microphone to use (device name substring, e.g. `"HyperX QuadCast"`). `null` = Windows default. Pick it live via the 🎚 button or the tray. |
| `minimize_to_tray` | Show a system-tray icon; the **—** button hides Jarvis to the tray (still listening). |
| `start_minimized` | Launch hidden in the tray (used automatically when started with Windows). |
| `daily_briefing` | On launch, Jarvis speaks a short briefing using his tools (date, weather, system, notes). |
| `briefing_location` | City for the briefing's weather, e.g. `"Nashville, TN"`. Blank = skip weather. |
| `briefing_once_per_day` | Only brief on the first launch each day. |
| `calendar_reminders` | Spoken heads-up (with a chime) before timed Google Calendar meetings. |
| `calendar_reminder_minutes` | How far ahead to remind you (default 10). |
| `calendar_poll_seconds` | How often the watcher checks the calendar (default 60). |
| `memory_db` | Persistent long-term memory (SQLite + semantic recall) in `memory/memory.db`. |
| `memory_autocapture` | After each turn, auto-extract durable facts about you into memory. |
| `memory_recall_k` | How many relevant memories to surface into context per turn. |
| `memory_extract_model` | Model used for fact extraction (blank = main model). |
| `wake_word_enabled` | Turn the "Hey Jarvis" listener on/off. |
| `wake_threshold` | 0–1; lower = easier to trigger, higher = fewer false wakes. |
| `greet_on_start` | Whether it greets you aloud on launch. |
| `silence_threshold` | Mic sensitivity (lower = more sensitive). |
| `silence_hang_seconds` | How long a pause ends your turn. |
| `max_history_turns` | Recent turns sent to Claude before older ones get summarized. |

## Google Calendar + Gmail (optional)

Jarvis can read your schedule and inbox. One-time setup:

1. In Google Cloud Console, create a project, enable the **Gmail API** and **Google
   Calendar API**, configure the OAuth consent screen (External, add yourself as a
   test user), and create an **OAuth client ID → Desktop app**.
2. Download the client JSON, rename it to **`credentials.json`**, and put it in the
   Jarvis folder.
3. Connect your account: tray icon → **Connect Google account** (or run
   `python connect_google.py`). A browser opens once; approve access.

It's **read-only** (calendar + Gmail). The login token lives in `token.json` and,
while the Cloud project is in "Testing", expires about every **7 days** — just run
**Connect Google account** again to refresh. Delete `token.json` to disconnect.

## Memory

- `memory/conversation.json` — full running transcript (reloaded each launch).
- `memory/longterm.json` — the rolling long-term summary the assistant remembers.
- To **wipe its memory**, delete both files.

## Cost

Pay-as-you-go via your Anthropic key. A spoken exchange with Sonnet is typically a
fraction of a cent; the periodic memory summary adds a tiny bit. Set a monthly cap
in the Anthropic Console under Billing.

## Troubleshooting

- **Won't start / closes instantly:** run `debug-launch.bat` to see errors.
- **Wake word won't trigger:** lower `wake_threshold` (e.g. `0.4`); speak "Hey Jarvis"
  clearly. Make sure the right mic is your Windows default.
- **It triggers on its own:** raise `wake_threshold` (e.g. `0.6`).
- **Doesn't hear your command:** lower `silence_threshold` (e.g. `0.008`).
- **No voice / playback error:** check default speakers; the voice needs internet.

## How it's built

Single-file Python app (`jarvis.py`): `tkinter` Canvas HUD; a persistent
`sounddevice` mic stream feeding `openWakeWord` (hands-free "hey_jarvis") and an
energy-based VAD; `faster-whisper` for local speech-to-text; the `anthropic` SDK for
the brain with rolling long-term-memory summarization; and `edge-tts` + `pygame` for
speech, with `av` decoding the audio envelope so the HUD animates in sync.
