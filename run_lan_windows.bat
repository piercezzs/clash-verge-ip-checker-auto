@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "VENV_PYTHON=.venv\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
  call :create_venv
  if errorlevel 1 goto fail
)
if not exist "%VENV_PYTHON%" (
  echo Virtual environment Python not found: %VENV_PYTHON%
  goto fail
)

"%VENV_PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 goto fail

set "PORT=%CLASH_CHECKER_PORT%"
if "%PORT%"=="" set "PORT=8080"

echo Stopping old Clash checker service on port %PORT% if present...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$port=%PORT%; Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { if ($_ -and $_ -ne $PID) { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } }"
timeout /t 1 /nobreak >nul

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

:create_venv
echo Creating Python virtual environment...
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -m venv .venv
  if not errorlevel 1 exit /b 0
)

where python >nul 2>nul
if not errorlevel 1 (
  python -m venv .venv
  if not errorlevel 1 exit /b 0
)

echo Failed to create Python virtual environment. Install Python 3 and ensure either py or python is available.
exit /b 1

:fail
echo.
echo Clash checker failed to start.
pause
exit /b 1
