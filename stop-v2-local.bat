@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop-v2-local.ps1"
if errorlevel 1 (
  echo.
  echo V2 shutdown needs attention. Review the message above.
  pause
  exit /b 1
)
endlocal
