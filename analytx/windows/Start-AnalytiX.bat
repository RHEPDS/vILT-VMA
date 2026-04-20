@echo off
setlocal
title AnalytiX
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
  echo Virtual environment not found.
  echo Please run first: windows\Install-and-Start.bat
  echo    or:  powershell -ExecutionPolicy Bypass -File windows\setup.ps1
  pause
  exit /b 1
)

echo Starting AnalytiX at http://127.0.0.1:8765
echo Press Ctrl+C to stop.
echo.
".venv\Scripts\python.exe" analytx_server.py
pause
