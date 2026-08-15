@echo off
rem Dexter one-time setup: venv, deps, config, icon, database, shortcut.
cd /d "%~dp0"
echo.
echo  === DEXTER SETUP ===
echo.

if not exist .venv (
    echo  Creating virtual environment...
    py -3.12 -m venv .venv 2>nul || python -m venv .venv
)
echo  Installing dependencies...
.venv\Scripts\python.exe -m pip install --upgrade pip --quiet
.venv\Scripts\python.exe -m pip install -r requirements.txt

if not exist config.json (
    copy config.example.json config.json >nul
    echo.
    echo  Created config.json - add your Anthropic and ElevenLabs keys there.
)

.venv\Scripts\python.exe make_icon.py

echo.
choice /M "Sync the full Pokemon database now (a few minutes, ~1000 species)"
if errorlevel 2 (
    echo  Skipped. Run later: .venv\Scripts\python.exe dexter_data.py sync
) else (
    .venv\Scripts\python.exe dexter_data.py sync
)

powershell -ExecutionPolicy Bypass -File make_shortcut.ps1

echo.
echo  Done. Launch Dexter from the desktop shortcut or "Launch Dexter.bat".
pause
