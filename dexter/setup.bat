@echo off
rem Dexter one-time setup: venv, deps, config, icon, database, shortcut.
rem Writes setup_log.txt next to this script; window always stays open.
setlocal EnableExtensions
cd /d "%~dp0"
title Dexter Setup
echo.
echo  === DEXTER SETUP ===
echo.

if not exist requirements.txt (
    echo  ERROR: Can't find Dexter's files next to this script.
    echo.
    echo  You are probably running setup.bat from INSIDE the downloaded ZIP.
    echo  Close this window, right-click the ZIP, choose "Extract All...",
    echo  then run setup.bat from the extracted dexter folder.
    echo.
    pause
    exit /b 1
)

set "LOG=%~dp0setup_log.txt"
echo Dexter setup started %date% %time% > "%LOG%"

rem --- find a Python 3 interpreter ---
set "PYCMD="
py -3.12 --version >nul 2>&1
if not errorlevel 1 set "PYCMD=py -3.12"
if not defined PYCMD (
    py -3 --version >nul 2>&1
    if not errorlevel 1 set "PYCMD=py -3"
)
if not defined PYCMD (
    python --version >nul 2>&1
    if not errorlevel 1 set "PYCMD=python"
)
if not defined PYCMD (
    echo  ERROR: Python was not found on this PC.
    echo.
    echo  Install Python 3.12 from  https://www.python.org/downloads/
    echo  IMPORTANT: tick "Add python.exe to PATH" in the installer,
    echo  then run setup.bat again.
    echo.
    pause
    exit /b 1
)
echo  Using Python:
%PYCMD% --version
%PYCMD% --version >> "%LOG%" 2>&1

if not exist .venv (
    echo  Creating virtual environment...
    %PYCMD% -m venv .venv >> "%LOG%" 2>&1
)
if not exist .venv\Scripts\python.exe (
    echo  ERROR: Could not create the virtual environment.
    echo  Details are in setup_log.txt - send that file to Claude.
    echo.
    pause
    exit /b 1
)

echo  Installing dependencies (this can take a few minutes)...
.venv\Scripts\python.exe -m pip install --upgrade pip >> "%LOG%" 2>&1
.venv\Scripts\python.exe -m pip install -r requirements.txt >> "%LOG%" 2>&1
if errorlevel 1 (
    echo  ERROR: Dependency install failed.
    echo  Details are in setup_log.txt - send that file to Claude.
    echo.
    pause
    exit /b 1
)
echo  Dependencies OK.

if not exist config.json (
    copy config.example.json config.json >nul
    echo  Created config.json - add your Anthropic / ElevenLabs keys there.
)

.venv\Scripts\python.exe make_icon.py >> "%LOG%" 2>&1

echo.
choice /M "Sync the full Pokemon database now (a few minutes, ~1000 species)"
if errorlevel 2 (
    echo  Skipped. Run later: .venv\Scripts\python.exe dexter_data.py sync
) else (
    .venv\Scripts\python.exe dexter_data.py sync
)

powershell -NoProfile -ExecutionPolicy Bypass -File make_shortcut.ps1

echo.
echo  Done. Launch Dexter from the desktop shortcut or "Launch Dexter.bat".
echo.
pause
