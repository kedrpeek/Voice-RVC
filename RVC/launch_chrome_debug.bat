@echo off
REM Launch Google Chrome with remote-debugging enabled so that auto_tts.py can attach via Selenium.
REM If Chrome is installed in a non-standard location, edit the CHROME_EXE variable below.

set "CHROME_EXE=C:\Program Files\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME_EXE%" (
    set "CHROME_EXE=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
)

if not exist "%CHROME_EXE%" (
    echo Could not find chrome.exe. Please edit CHROME_EXE in %~nx0.
    pause
    exit /b 1
)

REM Use project-local profile so we do not interfere with the main Chrome profile.
set "PROFILE_DIR=%~dp0chrome-profile"

REM Ensure profile directory exists
if not exist "%PROFILE_DIR%" mkdir "%PROFILE_DIR%"

REM Open the RVC Web UI automatically in a new window.
start "ChromeDebug" "%CHROME_EXE%" ^
    --remote-debugging-port=9222 ^
    --user-data-dir="%PROFILE_DIR%" ^
    --disable-popup-blocking ^
    --new-window ^
    http://127.0.0.1:6969/

exit /b 0 