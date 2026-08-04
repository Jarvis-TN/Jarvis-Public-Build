@echo off
REM Preview the deployed HUD (web\hud_aou.html - Age of Ultron hologram) in your
REM browser. This does NOT touch your main Jarvis app. Close this window to stop.
cd /d "%~dp0web"
echo.
echo   Opening the HUD preview in your browser...
echo   (Keep this window open while viewing. Close it to stop.)
echo.
start "" "http://localhost:8795/hud_aou.html"
"..\.venv\Scripts\python.exe" -m http.server 8795
