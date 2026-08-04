@echo off
REM Launch Jarvis with the WebGL neural HUD as its window (no browser tab).
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" "jarvis_glass.py"
exit /b 0
