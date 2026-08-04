@echo off
REM ---------------------------------------------------------------------------
REM Roll back real-time gesture control. Removes the isolated vision venv so the
REM sidecar can no longer run. The main Jarvis install is untouched.
REM After this, also set  "gesture_control_enabled": false  in config.json.
REM (Nothing else needs undoing - gestures are gated entirely behind that flag.)
REM ---------------------------------------------------------------------------
setlocal
set HERE=%~dp0
if exist "%HERE%.venv-vision" (
    echo Removing .venv-vision ...
    rmdir /s /q "%HERE%.venv-vision"
    echo Removed.
) else (
    echo .venv-vision not found - nothing to remove.
)
echo.
echo Gesture control rolled back. Set "gesture_control_enabled": false in
echo config.json if you had turned it on, then restart Jarvis.
endlocal
