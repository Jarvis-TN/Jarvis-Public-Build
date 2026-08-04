@echo off
REM Launch Jarvis WITH a console window so you can see any errors.
cd /d "%~dp0"
".venv\Scripts\python.exe" "jarvis.py"
echo.
echo (Jarvis has closed.)
pause
