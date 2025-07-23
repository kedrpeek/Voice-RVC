@echo off
REM -----------------------------------------------------------
REM Launch Chrome with remote-debugging (port 9222) but using
REM a *temporary* user-data-dir inside %%TEMP%%.
REM The profile folder will be deleted automatically after
REM the Chrome window is closed.
REM -----------------------------------------------------------

setlocal enabledelayedexpansion

REM Locate chrome.exe (adjust if installed elsewhere)
set "CHROME_EXE=C:\Program Files\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME_EXE%" set "CHROME_EXE=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME_EXE%" (
    echo [ERROR] Не удалось найти chrome.exe. Отредактируйте переменную CHROME_EXE.
    pause
    exit /b 1
)

REM Create temporary profile directory
set "TMP_PROFILE=%TEMP%\chrome-rvc-%RANDOM%%RANDOM%"
mkdir "%TMP_PROFILE%"

REM Inform user
echo [INFO] Запускаю Chrome с временным профилем: %TMP_PROFILE%

start "ChromeDebugTemp" /wait "%CHROME_EXE%" ^
    --remote-debugging-port=9222 ^
    --user-data-dir="%TMP_PROFILE%" ^
    --disable-popup-blocking ^
    --new-window ^
    http://127.0.0.1:6969/

REM When Chrome window is closed, cleanup
if exist "%TMP_PROFILE%" (
    echo [INFO] Удаляю временный профиль...
    rmdir /s /q "%TMP_PROFILE%"
)

echo [OK] Готово.
endlocal
exit /b 0 