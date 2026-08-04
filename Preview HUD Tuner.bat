@echo off
REM ============================================================
REM  Serve the Jarvis web/ folder and open the HUD tuner in your
REM  browser. Use this to dial in the HUD look, then paste the
REM  "Copy JSON" values back to Claude to bake into the live HUD.
REM  Close the server window (this one) to stop it.
REM ============================================================
cd /d "%~dp0"
start "Jarvis HUD preview server" ".venv\Scripts\python.exe" -m http.server 8799 --directory web
REM give the server a moment, then open the tuner (and the live HUD) in the browser
timeout /t 1 >nul
start "" "http://localhost:8799/hud_tune.html"
start "" "http://localhost:8799/hud_aou.html"
exit /b 0
