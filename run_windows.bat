@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PORT=%CLASH_CHECKER_PORT%"
if "%PORT%"=="" set "PORT=8080"
set "VENV_PYTHON=.venv\Scripts\python.exe"

echo Stopping old Clash checker service on port %PORT% if present...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$port=%PORT%; Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { if ($_ -and $_ -ne $PID) { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } }"
timeout /t 1 /nobreak >nul

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

set "CLASH_CHECKER_PORT=%PORT%"
start "" powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "scripts\open_or_focus_url_windows.ps1" -Url "http://127.0.0.1:%PORT%"
"%VENV_PYTHON%" web.py
if errorlevel 1 goto fail
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
