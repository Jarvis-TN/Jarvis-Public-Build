@echo off
REM ============================================================
REM  Jarvis - one-time setup: builds a private Python virtual
REM  environment and installs everything Jarvis needs.
REM ============================================================
setlocal
cd /d "%~dp0"

set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"

echo.
echo  Creating virtual environment...
"%PY%" -m venv .venv
if errorlevel 1 goto fail

echo  Upgrading pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip

echo  Installing dependencies (this can take a few minutes)...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail

echo.
echo  ============================================================
echo   Setup complete!
echo.
echo   1. Open config.json and paste your Anthropic API key.
echo   2. Double-click "Launch Jarvis.bat" (or the desktop icon).
echo  ============================================================
echo.
pause
exit /b 0

:fail
echo.
echo  Setup failed. Scroll up to see the error.
pause
exit /b 1
