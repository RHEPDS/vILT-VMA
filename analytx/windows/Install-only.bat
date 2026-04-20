@echo off
setlocal
title AnalytiX - Install dependencies only
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" -NoStart
if errorlevel 1 (
  echo Install failed.
  pause
  exit /b 1
)
echo.
pause
