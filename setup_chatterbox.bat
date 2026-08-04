@echo off
REM ============================================================
REM  Chatterbox voice - ISOLATED setup.
REM  Chatterbox conflicts with Jarvis's main dependencies, so it
REM  gets its own virtual environment (.venv-chatterbox) and runs
REM  as a small local server the main app talks to. Best on a PC
REM  with an NVIDIA GPU - it's slow on CPU.
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"

echo.
echo  Creating the isolated Chatterbox environment...
"%PY%" -m venv .venv-chatterbox
if errorlevel 1 goto fail
".venv-chatterbox\Scripts\python.exe" -m pip install --upgrade pip

set "HASGPU="
where nvidia-smi >nul 2>nul && set "HASGPU=1"
if defined HASGPU (
    echo  NVIDIA GPU detected - installing CUDA PyTorch for Chatterbox...
    echo  (If it errors for your CUDA version, change cu124 below to cu121/cu126/cu128.)
    ".venv-chatterbox\Scripts\python.exe" -m pip install torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu124
)

echo.
echo  Installing chatterbox-tts (large - a few minutes)...
".venv-chatterbox\Scripts\python.exe" -m pip install chatterbox-tts
if errorlevel 1 goto fail

echo.
echo  ============================================================
echo   Chatterbox is set up in .venv-chatterbox.
echo   In config.json set "tts_engine": "chatterbox" and launch
echo   Jarvis - it starts the Chatterbox server automatically.
echo  ============================================================
echo.
pause
exit /b 0

:fail
echo.
echo  Setup failed. Scroll up to see the error.
pause
exit /b 1
