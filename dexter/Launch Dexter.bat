@echo off
rem Launch Dexter with the venv's windowed Python (no console window).
cd /d "%~dp0"
if not exist .venv\Scripts\pythonw.exe (
    echo Run setup.bat first.
    pause
    exit /b 1
)
start "" .venv\Scripts\pythonw.exe dexter.py
