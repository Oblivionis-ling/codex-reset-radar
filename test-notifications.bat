@echo off
setlocal
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\test-notifications.ps1" %*
if errorlevel 1 (
  echo.
  echo Notification test command failed. Review the message above.
  exit /b 1
)
endlocal
