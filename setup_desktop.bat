@echo off
REM ============================================================
REM  Jarvis - desktop / new-PC rebuild.
REM  Use this after copying the Jarvis folder to another machine
REM  (e.g. via USB). It rebuilds the virtual environment from
REM  scratch, installs the right PyTorch for your hardware
REM  (NVIDIA GPU -> CUDA build, otherwise CPU), pre-downloads the
REM  model weights, and regenerates the desktop shortcuts.
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"

echo.
echo  Jarvis desktop rebuild
echo  ----------------------

REM A copied .venv is NOT portable (absolute paths) - remove and rebuild.
if exist ".venv" (
    echo  Removing the copied virtual environment (it isn't portable)...
    rmdir /s /q ".venv"
)

echo  Creating a fresh virtual environment...
"%PY%" -m venv .venv
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip install --upgrade pip

REM --- detect an NVIDIA GPU --------------------------------------------------
set "HASGPU="
where nvidia-smi >nul 2>nul && set "HASGPU=1"

if defined HASGPU (
    echo.
    echo  NVIDIA GPU detected - installing the CUDA build of PyTorch...
    echo  (If this errors for your CUDA version, change cu121 below to cu124/cu128.)
    ".venv\Scripts\python.exe" -m pip install "torch<2.9" "torchaudio<2.9" --index-url https://download.pytorch.org/whl/cu121
    if errorlevel 1 echo  (CUDA torch failed - the CPU build from requirements will be used instead.)
) else (
    echo.
    echo  No NVIDIA GPU detected - using the CPU build of PyTorch.
)

echo.
echo  Installing all dependencies (a few minutes)...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail

echo.
echo  Pre-downloading model weights (Whisper, embeddings, voice clone)...
".venv\Scripts\python.exe" prefetch_models.py

echo.
echo  Regenerating desktop shortcuts for this machine...
powershell -NoProfile -ExecutionPolicy Bypass -File "make_shortcuts.ps1"

echo.
echo  ============================================================
echo   Desktop rebuild complete.
echo.
if defined HASGPU (
    echo   GPU mode is ON ^(compute_device "auto" will use it^).
    echo   The cinematic HUD and the local voice clone will run fast.
) else (
    echo   Running in CPU mode.
)
echo   1. Check config.json has your Anthropic API key.
echo   2. Launch with the "Jarvis HUD" desktop shortcut.
echo  ============================================================
echo.
pause
exit /b 0

:fail
echo.
echo  Setup failed. Scroll up to see the error.
pause
exit /b 1
