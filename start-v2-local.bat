@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-v2-local.ps1"
if errorlevel 1 (
  echo.
  echo V2 startup failed. Review the message above.
  pause
  exit /b 1
)
endlocal
