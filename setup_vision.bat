@echo off
REM ---------------------------------------------------------------------------
REM Build the isolated vision venv for real-time gesture control (MediaPipe).
REM Kept separate from the main .venv on purpose: MediaPipe pulls
REM opencv-contrib-python, which would clash with the main env's pinned
REM opencv-python-headless. This sidecar owns the webcam and streams gesture
REM events to Jarvis. See vision_sidecar.py / jarvis_vision.py.
REM ---------------------------------------------------------------------------
setlocal
set HERE=%~dp0
echo Building .venv-vision ...
"%HERE%.venv\Scripts\python.exe" -m venv "%HERE%.venv-vision"
if errorlevel 1 py -3.12 -m venv "%HERE%.venv-vision"
"%HERE%.venv-vision\Scripts\python.exe" -m pip install --upgrade pip
"%HERE%.venv-vision\Scripts\python.exe" -m pip install -r "%HERE%requirements-vision.txt"
echo.
echo Vision venv ready.
echo Enable gestures by setting  "gesture_control_enabled": true  in config.json,
echo then restart Jarvis. To remove it entirely, run  Remove Gesture Control.bat
endlocal
