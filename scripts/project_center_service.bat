@echo off
setlocal EnableExtensions

where py >nul 2>nul
if not errorlevel 1 (
  py -3 "%~dp0project_center_service" %*
  exit /b %ERRORLEVEL%
)

where python >nul 2>nul
if not errorlevel 1 (
  python "%~dp0project_center_service" %*
  exit /b %ERRORLEVEL%
)

echo ERROR: Python 3 is required to inspect the node checker service. 1>&2
exit /b 1
