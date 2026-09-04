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

set "LAN_IP=%CLASH_CHECKER_LAN_IP%"
if "%LAN_IP%"=="" (
  for /f "usebackq delims=" %%I in (`powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\detect_lan_ip_windows.ps1"`) do set "LAN_IP=%%I"
)

set "CLASH_CHECKER_HOST=0.0.0.0"
set "CLASH_CHECKER_PORT=%PORT%"

if not "%LAN_IP%"=="" (
  if "%CLASH_CHECKER_PUBLIC_BASE_URL%"=="" set "CLASH_CHECKER_PUBLIC_BASE_URL=http://%LAN_IP%:%PORT%"
)

echo Local URL: http://127.0.0.1:%PORT%
if not "%CLASH_CHECKER_PUBLIC_BASE_URL%"=="" echo LAN URL:   %CLASH_CHECKER_PUBLIC_BASE_URL%
if "%CLASH_CHECKER_PUBLIC_BASE_URL%"=="" echo LAN IP was not detected. Set CLASH_CHECKER_PUBLIC_BASE_URL manually if needed.
echo If Windows Firewall asks, allow incoming connections for Python.

start "" powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "scripts\open_or_focus_url_windows.ps1" -Url "http://127.0.0.1:%PORT%"
"%VENV_PYTHON%" web.py
if errorlevel 1 goto fail
pause
exit /b 0

:launch_fail
if exist "%PORT_FILE%" del /q "%PORT_FILE%" >nul 2>nul
goto fail

:fail
echo.
echo Clash checker failed to start.
pause
exit /b 1
