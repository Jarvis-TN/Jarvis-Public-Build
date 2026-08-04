@echo off
title Jarvis Online URL
cd /d "%~dp0"
echo.
echo  Starting Jarvis remote access and generating a fresh online URL...
echo  (Keep this window OPEN - closing it takes the link offline.)
echo.
".venv\Scripts\python.exe" -u serve_remote.py
echo.
echo  The remote server stopped. Press any key to close.
pause >nul
