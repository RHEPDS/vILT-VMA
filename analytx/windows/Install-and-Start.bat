@echo off
setlocal
title AnalytiX - Install and start
cd /d "%~dp0.."
echo.
echo Running PowerShell setup (venv + dependencies) ...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
if errorlevel 1 (
  echo.
  echo Setup failed. See messages above.
  pause
  exit /b 1
)
echo.
pause
