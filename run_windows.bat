@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PORT=%CLASH_CHECKER_PORT%"
if "%PORT%"=="" set "PORT=8080"
set "VENV_PYTHON=.venv\Scripts\python.exe"

call scripts\project_center_service.bat stop
if errorlevel 1 goto fail
call scripts\project_center_service.bat prepare
if errorlevel 1 goto fail

set "CLASH_CHECKER_PORT=%PORT%"
start "" powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "scripts\open_or_focus_url_windows.ps1" -Url "http://127.0.0.1:%PORT%"
"%VENV_PYTHON%" web.py
if errorlevel 1 goto fail
exit /b 0

:fail
echo.
echo Clash checker failed to start.
pause
exit /b 1
