@echo off
rem Connect Dexter to your ElevenLabs voice (asks for the API key, tests it).
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo Run setup.bat first.
    pause
    exit /b 1
)
.venv\Scripts\python.exe connect_voice.py
