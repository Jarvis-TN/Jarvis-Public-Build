@echo off
REM ---------------------------------------------------------------------------
REM Force-clear any stuck or leftover Jarvis processes - the invisible pythonw
REM that can keep holding the single-instance lock and make the next launch say
REM "Jarvis is already running". Run this if Jarvis won't boot or falsely reports
REM it's already running, then launch it again.
REM ---------------------------------------------------------------------------
echo Clearing any leftover Jarvis processes...
powershell -NoProfile -Command "$me=$PID; $p = Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $me -and ( ($_.Name -in 'python.exe','pythonw.exe' -and $_.CommandLine -match 'jarvis|serve_headless|serve_remote|vision_sidecar|chatterbox') -or $_.Name -eq 'cloudflared.exe' ) }; if ($p) { $p | ForEach-Object { Write-Host ('  stopping PID ' + $_.ProcessId + '  (' + $_.Name + ')'); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } } else { Write-Host '  none found - nothing to clear.' }"
echo.
echo Done. You can launch Jarvis again now.
pause
