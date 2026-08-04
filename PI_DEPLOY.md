# Jarvis on a Raspberry Pi (always-on headless host)

Goal: run Jarvis 24/7 on a Pi plugged into your home switch, so you can reach him
from your other devices (Telegram, the phone bridge, or a remote Cloudflare
tunnel) even when your PC is off. These bridges make only **outbound** connections
(to the Claude API + the relay), so **no port forwarding, no firewall changes, no
static public IP** are needed — plugging the Pi into your network is all the
"networking" required.

What runs on the Pi: the Jarvis **brain** (Claude API), **Whisper** STT (local),
**Piper** TTS (local, light), and whichever remote bridges you enable (Telegram,
phone, remote tunnel, MCP). What does NOT: the desktop HUD, your mic, and the heavy
voice clones (XTTS/Chatterbox) — those stay on your PC.

## 1. Shopping list

- **Raspberry Pi 5, 8 GB** (recommended — Whisper + audio want the headroom; Pi 4
  4 GB+ works but transcription is slower)
- **Official 27 W USB-C power supply** (Pi 5)
- **Active cooling** (Pi 5 official active cooler or a case with a fan)
- **Storage:** a 32 GB+ A2 microSD to start, or better a **USB-SSD** for reliability
- **Ethernet cable** (Pi → your switch) — wired is ideal for a server
- (Pi 5 has built-in Wi-Fi too if you ever need it)

## 2. Flash the OS (headless)

1. On your PC, install **Raspberry Pi Imager**.
2. Choose **Raspberry Pi OS Lite (64-bit)** (no desktop).
3. Click the **gear / Edit Settings** before writing and set:
   - **Hostname:** `jarvis`
   - **Enable SSH** (password or your public key)
   - **Username/password** (e.g. user `winston`)
   - Skip Wi-Fi (we'll use Ethernet) — or set it as a backup
4. Write to the SD/SSD, put it in the Pi.

## 3. Connect to your network (the switch part)

1. Plug the Pi into your **switch** with Ethernet and power it on. It gets an IP
   from your router via DHCP automatically — nothing else to configure.
2. From your PC: `ssh winston@jarvis.local` (mDNS). If `.local` doesn't resolve,
   find the Pi's IP in your **router's DHCP client list** and `ssh winston@<ip>`.
3. **Recommended:** in your router, add a **DHCP reservation** for the Pi's MAC so
   its IP never changes (handy for SSH). Optional, not required for the bot.

## 4. Install system packages

```bash
sudo apt update
sudo apt install -y python3-venv python3-dev python3-tk \
    libportaudio2 ffmpeg git build-essential
```
- `libportaudio2` — needed to import `sounddevice`
- `python3-tk` — Jarvis imports tkinter at module load even headless

## 5. Get the Jarvis files onto the Pi

Copy the project folder over (USB, `scp`, or git). Then:

```bash
cd ~/Jarvis
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-pi.txt
```

## 6. Configure

Create `config.json` on the Pi (copy from `config.example.json`) with at least:
```json
"anthropic_api_key": "sk-ant-...",
"tts_engine": "piper",
"telegram_enabled": true,
"telegram_bot_token": "<your bot token>"
```
(Keep secrets on the Pi only.) First run downloads the Whisper + Piper models.
Enable whichever bridges you want — `telegram_enabled`, `phone_bridge_enabled`,
`remote_access_enabled`, `mcp_enabled`.

## 7. Test it

```bash
.venv/bin/python serve_headless.py
```
You should see "Headless Jarvis online. Bridges: [...]" listing the bridges you
enabled (e.g. `['telegram']`). Message your Telegram bot to test it.

## 8. Run forever (systemd)

Create `/etc/systemd/system/jarvis.service` (adjust user/paths):
```ini
[Unit]
Description=Jarvis headless (brain + remote bridges)
After=network-online.target
Wants=network-online.target

[Service]
User=winston
WorkingDirectory=/home/winston/Jarvis
ExecStart=/home/winston/Jarvis/.venv/bin/python serve_headless.py
Restart=always
RestartSec=5
Environment=SDL_AUDIODRIVER=dummy

[Install]
WantedBy=multi-user.target
```
Then:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now jarvis
journalctl -u jarvis -f      # watch the logs
```
Now Jarvis starts on boot and restarts if it ever crashes — fully independent of
your PC.

## Notes / when the Pi arrives

- ARM wheels exist for everything in `requirements-pi.txt`; if any package fails
  to build, that's the one thing to debug live — ping me and we'll sort it.
- Use **`tts_engine: piper`** on the Pi (XTTS/Chatterbox need torch and are too
  heavy for a Pi). ElevenLabs also works if you prefer the online voice.
- The bridges need no inbound ports. The remote Cloudflare tunnel (for the phone
  bridge or remote HUD) is still outbound-only.
