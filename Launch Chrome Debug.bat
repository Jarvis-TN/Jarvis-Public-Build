@echo off
REM Relaunches Chrome with the remote-debugging port open, using your normal
REM profile (so you stay logged into everything - SPINS included), so Jarvis's
REM Playwright MCP server can attach to this exact window instead of spinning
REM up a fresh, unauthenticated browser.
echo Closing any running Chrome windows...
taskkill /F /IM chrome.exe /T >nul 2>&1
timeout /t 2 /nobreak >nul
echo Relaunching Chrome with remote debugging on port 9222...
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%LOCALAPPDATA%\Google\Chrome\User Data"
