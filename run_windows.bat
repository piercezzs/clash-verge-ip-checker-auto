@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "VENV_PYTHON=.venv\Scripts\python.exe"
set "PORT_FILE=%TEMP%\clash-checker-port-%RANDOM%-%RANDOM%.txt"

call scripts\project_center_service.bat launch-port > "%PORT_FILE%"
if errorlevel 1 goto launch_fail
set /p "PORT="<"%PORT_FILE%"
del /q "%PORT_FILE%" >nul 2>nul
if "%PORT%"=="" goto fail

set "CLASH_CHECKER_PORT=%PORT%"
start "" powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "scripts\open_or_focus_url_windows.ps1" -Url "http://127.0.0.1:%PORT%"
"%VENV_PYTHON%" web.py
if errorlevel 1 goto fail
exit /b 0

:launch_fail
if exist "%PORT_FILE%" del /q "%PORT_FILE%" >nul 2>nul
goto fail

:fail
echo.
echo Clash checker failed to start.
pause
exit /b 1
