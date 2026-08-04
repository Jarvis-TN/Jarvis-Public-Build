@echo off
REM Launch Jarvis (no console window). If it won't start, run this
REM file from a terminal instead to see error messages, or run
REM debug-launch.bat which keeps the window open.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Virtual environment not found. Running setup first...
    call setup.bat
)
start "" ".venv\Scripts\pythonw.exe" "jarvis.py"
exit /b 0
