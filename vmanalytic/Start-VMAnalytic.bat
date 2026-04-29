@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>&1
if errorlevel 1 (
  echo [VMAnalytic] Python launcher ^(py^) not found.
  echo Install Python 3.12+ from https://www.python.org/downloads/
  echo Enable "Add python.exe to PATH" or use: winget install Python.Python.3.12
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [VMAnalytic] Creating virtual environment...
  py -3 -m venv .venv
  if errorlevel 1 (
    echo Failed to create .venv
    pause
    exit /b 1
  )
)

call ".venv\Scripts\activate.bat"
echo [VMAnalytic] Installing dependencies ^(first run may take a minute^)...
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt
if errorlevel 1 (
  echo pip install failed.
  pause
  exit /b 1
)

set PYTHONPATH=%CD%
echo.
python local_server.py
if errorlevel 1 pause
