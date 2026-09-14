@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>&1
if not errorlevel 1 (
  set "PYTHON=py -3"
) else (
  set "PYTHON=python"
)

if not exist "backend\.venv\Scripts\python.exe" (
  echo Creating local Python environment...
  %PYTHON% -m venv backend\.venv
  if errorlevel 1 (
    echo Failed to create the Python environment. Install Python 3 and retry.
    exit /b 1
  )
  "backend\.venv\Scripts\python.exe" -m pip install -r backend\requirements.txt
  if errorlevel 1 exit /b 1
)

"backend\.venv\Scripts\python.exe" -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8787
