@echo off
REM One-click Google (Calendar + Gmail) sign-in / re-auth for Jarvis.
REM A browser opens; sign in and approve. Saves token.json.
cd /d "%~dp0"
".venv\Scripts\python.exe" "connect_google.py"
echo.
echo (You can close this window.)
pause
