# Build VMAnalytic.exe (PyInstaller one-file). Run on Windows from repo root.
# Prerequisites: Python 3.12+ on PATH (py launcher), network for pip.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "Installing PyInstaller..."
py -3 -m pip install --upgrade pip
py -3 -m pip install "pyinstaller>=6.0" -r requirements.txt

Write-Host "Building EXE (may take several minutes)..."
py -3 -m PyInstaller --clean --noconfirm vmanalytic.spec

$exe = Join-Path $PSScriptRoot "dist\VMAnalytic.exe"
if (Test-Path $exe) {
    Write-Host ""
    Write-Host "OK: $exe"
    Write-Host "Copy dist\VMAnalytic.exe anywhere and run; data is stored under %LOCALAPPDATA%\VMAnalytic"
} else {
    Write-Host "Build finished but EXE not found at expected path."
    exit 1
}
