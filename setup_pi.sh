#!/usr/bin/env bash
# One-shot Jarvis setup for a Raspberry Pi (Raspberry Pi OS, 64-bit).
# Run from the Jarvis project folder on the Pi:
#     chmod +x setup_pi.sh
#     ./setup_pi.sh            # install everything
#     ./setup_pi.sh --service  # also install the auto-start service
set -e
cd "$(dirname "$0")"

echo "== Jarvis Raspberry Pi setup =="
echo "[1/4] System packages (needs sudo)..."
sudo apt update
sudo apt install -y python3-venv python3-dev python3-tk \
    libportaudio2 ffmpeg git build-essential

echo "[2/4] Python virtual environment..."
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip

echo "[3/4] Python dependencies (several minutes on a Pi)..."
.venv/bin/python -m pip install -r requirements-pi.txt

echo "[4/4] Pre-downloading models (Whisper + Piper)..."
.venv/bin/python prefetch_models.py || true

echo
echo "Base setup complete."
echo "  Next: put your keys in config.json"
echo "        (copy config.example.json) and set \"tts_engine\": \"piper\"."
echo "  Test: .venv/bin/python serve_headless.py"

if [ "$1" = "--service" ]; then
    echo
    echo "Installing the auto-start service..."
    USER_NAME="$(whoami)"
    DIR="$(pwd)"
    sudo tee /etc/systemd/system/jarvis.service >/dev/null <<EOF
[Unit]
Description=Jarvis headless (brain + remote bridges)
After=network-online.target
Wants=network-online.target

[Service]
User=$USER_NAME
WorkingDirectory=$DIR
ExecStart=$DIR/.venv/bin/python serve_headless.py
Restart=always
RestartSec=5
Environment=SDL_AUDIODRIVER=dummy

[Install]
WantedBy=multi-user.target
EOF
    sudo systemctl daemon-reload
    sudo systemctl enable --now jarvis
    echo "Service installed + started. Watch logs with: journalctl -u jarvis -f"
fi
