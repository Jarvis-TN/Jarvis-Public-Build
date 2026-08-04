@echo off
REM ============================================================
REM  Make Frames - DRAG A VIDEO FILE ONTO THIS ICON to use it.
REM  (Do not double-click it. Drop your .mp4 on top of it.)
REM  It pulls still frames (zoomed to the hologram) and opens
REM  the folder so you can pick the clearest ones for Claude.
REM ============================================================
setlocal
cd /d "%~dp0"

if "%~1"=="" (
  echo.
  echo   No video was dropped in.
  echo   HOW TO USE: drag your .mp4 file and drop it ON TOP of "Make Frames.bat".
  echo.
  pause
  exit /b
)

echo.
echo   Video: %~1
echo.
echo   Press Enter to accept the [default] for each question.
echo.
set "START=0"
set /p "START=  Start time in seconds [0]: "
set "END=0"
set /p "END=  End time in seconds (0 = whole clip) [0]: "
set "COUNT=24"
set /p "COUNT=  How many frames [24]: "
set "ZOOM=0.6"
set /p "ZOOM=  Zoom into center, 0.4-1.0 (1 = no zoom) [0.6]: "

echo.
echo   Extracting frames...
".venv\Scripts\python.exe" "extract_frames.py" "%~1" --start %START% --end %END% --count %COUNT% --zoom %ZOOM% --out "frames"

echo.
echo   Opening the frames folder...
start "" "%~dp0frames"
echo.
echo   Done. Pick the clearest frames and send them to Claude.
pause
