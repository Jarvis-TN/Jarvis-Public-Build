# Dexter — a virtual Pokédex for your desktop

A desktop app that looks and behaves like the Pokédex from the animated
series: red clamshell body, a big blue lens that **flashes in sync with
Dexter's voice**, indicator LEDs, a screen that shows official artwork,
types, stats and dex flavor text, and a green console that types out
everything Dexter says. You can talk to it through your microphone —
ask Pokémon questions, or say *"I'm thinking of a Pokémon"* and Dexter
plays 20 questions and identifies it.

## Quick start (Windows)

1. Run `setup.bat` — creates the venv, installs deps, builds the icon,
   offers to sync the full Pokémon database, and puts a **Dexter shortcut
   on your desktop**.
2. Open `config.json` and add keys (all optional, see below).
3. Double-click the desktop shortcut (or `Launch Dexter.bat`).

Everything degrades gracefully: with no keys at all you still get the full
animated Pokédex, database browsing, voice questions (local Whisper), the
guessing game, and a Windows SAPI voice.

| Key in config.json | Unlocks |
|---|---|
| `elevenlabs_api_key` + `elevenlabs_voice_id` | Dexter's real voice (see below) |
| `anthropic_api_key` | Free-form Q&A via Claude ("who beats Garchomp?", "compare Blastoise and Gyarados") |

## The database

Synced once from **PokéAPI** (`python dexter_data.py sync`) into a local
SQLite file — after that Dexter is instant and fully offline. PokéAPI is the
canonical open aggregation of every mainline game's data, which is the same
underlying data the thousands of fan wikis republish. Per species it stores:
national dex number, name, genus, types, all six base stats, height/weight,
color/habitat/shape, legendary/mythical flags, generation, evolution parent,
capture rate, official artwork, and **English flavor text from every game
version**. Artwork downloads lazily into `data/sprites/` as you browse.

Free-form questions layer Claude on top, grounded with the matching database
row so the facts come from the dex.

## Dexter's voice (ElevenLabs)

Put your API key and a voice ID in `config.json`. Build the voice itself in
the ElevenLabs dashboard, two routes:

- **Voice Design** (recommended): describe the delivery — a flat, precise,
  slightly nasal electronic narrator, mid-pitched, deadpan — and iterate
  until it sounds like the show's Pokédex. No source audio needed.
- **Voice Lab cloning**: uploads require the rights/consent to the voice per
  ElevenLabs' terms, so cloning the show's voice actor directly from
  episodes isn't something their policy permits. Voice Design gets very
  close without that problem.

The app streams raw PCM from ElevenLabs and measures loudness ~30×/sec —
that's what drives the blue lens flash, so it tracks the actual audio.
Without ElevenLabs, Windows SAPI speaks and the lens pulses on a simulated
cadence.

## Talking to Dexter

Click **MIC** (or hold **SPACE**), speak, release. Recording also auto-stops
on silence. Transcription is local (faster-whisper, nothing leaves your PC).

Dexter is a question-answering repository first. A local knowledge engine
(the full 18×18 type chart plus the synced database) answers the common
question shapes **instantly and fully offline**, and whenever a Pokémon is
identified its image and stats flash up on the screen:

- *"What is Charizard weak against?"* → weaknesses, resistances, immunities
- *"What is Gyarados strong against?"* → super-effective coverage
- *"What type is Sylveon?"*, *"Is Mewtwo legendary?"*
- *"What are Pikachu's powers?"* → abilities with their effect text
- *"What does Eevee evolve into?"*, *"How fast is Jolteon?"*, *"stats"*
- *"Who would win, Charizard or Blastoise?"* → type edge + stat totals
- *"Does fire beat grass?"* → pure type matchups
- *"I'm thinking of a Pokémon"* → Dexter interrogates you and identifies it,
  flashing each guess on screen
- Anything it can't parse locally goes to Claude (if a key is set), grounded
  with the full database record — stats, abilities, computed weaknesses —
  so answers stay factual.
- Arrow keys / D-pad browse; the search box takes a name, dex number, or a
  typed question.

## Matching the show's look

All geometry and colors live in the `THEME` dict at the top of `dexter.py`.
When you have reference images from the show, adjust those values (lens
position/size, body reds, screen placement) — no logic changes needed.

## File map

| File | Purpose |
|---|---|
| `dexter.py` | The app: animated Pokédex UI (tkinter Canvas), state machine, worker thread |
| `dexter_data.py` | PokéAPI → SQLite sync + all queries (`sync`/`show` CLI) |
| `dexter_brain.py` | Claude Q&A (Dexter persona) + deterministic 20-questions engine |
| `dexter_voice.py` | ElevenLabs streaming TTS with live loudness → lens flash; SAPI fallback |
| `dexter_ears.py` | Push-to-talk mic capture + local Whisper transcription |
| `setup.bat` / `Launch Dexter.bat` / `make_shortcut.ps1` | Install, run, desktop shortcut |
| `make_icon.py` | Draws `dexter.ico` for the shortcut |

## Later: the Apple app

The Python/tkinter build won't port to Xcode directly, but the project is
split so the expensive parts carry over: the SQLite database and its schema
move as-is (SQLite is native on iOS/macOS), and ElevenLabs/Claude/PokéAPI are
plain HTTPS calls from Swift. The UI would be rebuilt in SwiftUI (which will
look even better — real gradients, springs, metal shaders for the lens), and
SFSpeechRecognizer replaces Whisper. One caution: distributing a Pokémon app
on the App Store runs into Nintendo/The Pokémon Company IP enforcement —
personal installs via Xcode or TestFlight are the realistic path.
