@echo off
REM ---------------------------------------------------------------------------
REM Launch a visible Chrome that Jarvis's Playwright MCP can drive over CDP.
REM
REM Jarvis connects to this window via --cdp-endpoint=http://localhost:9222
REM (set in config.json). Start THIS before asking Jarvis to browse.
REM
REM Chrome 136+ refuses remote debugging on the default profile, so we use a
REM dedicated profile at %LOCALAPPDATA%\JarvisChromeDebug. It persists, so any
REM sites you log into here stay logged in for next time. It is separate from
REM your everyday Chrome profile.
REM ---------------------------------------------------------------------------
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" ^
  --remote-debugging-port=9222 ^
  --user-data-dir="%LOCALAPPDATA%\JarvisChromeDebug" ^
  --no-first-run ^
  --no-default-browser-check
