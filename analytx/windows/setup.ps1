#Requires -Version 5.1
<#
.SYNOPSIS
    Creates a Python venv, installs AnalytiX dependencies, and optionally starts the web app.
.DESCRIPTION
    Run from the repository (e.g. right-click -> Run with PowerShell, or from cmd:
    powershell -ExecutionPolicy Bypass -File windows\setup.ps1
.PARAMETER NoStart
    If set, do not start the server after a successful install.
#>
param(
    [switch]$NoStart
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

function Get-PythonExe {
    foreach ($cmd in @(
            @{ Name = "py"; Args = @("-3", "-c", "import sys; print(sys.executable)") },
            @{ Name = "python"; Args = @("-c", "import sys; print(sys.executable)") }
        )) {
        try {
            $out = & $cmd.Name @($cmd.Args) 2>$null
            if ($out) {
                $p = ($out | Out-String).Trim()
                if ($p -and (Test-Path -LiteralPath $p)) { return $p }
            }
        }
        catch {
            continue
        }
    }
    return $null
}

Write-Host "AnalytiX – Windows setup" -ForegroundColor Cyan
Write-Host "Project root: $Root"

$pyExe = Get-PythonExe
if (-not $pyExe) {
    Write-Host ""
    Write-Host "ERROR: Python 3 was not found in PATH." -ForegroundColor Red
    Write-Host "Install Python 3.10+ from https://www.python.org/downloads/windows/"
    Write-Host "Enable: 'Add python.exe to PATH', then open a new terminal and run this script again."
    Write-Host "Or install with winget (admin): winget install Python.Python.3.12"
    exit 1
}

Write-Host "Using Python: $pyExe" -ForegroundColor Green

$venvDir = Join-Path $Root ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$venvPip = Join-Path $venvDir "Scripts\pip.exe"

if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "Creating virtual environment in .venv ..."
    & $pyExe -m venv $venvDir
}

if (-not (Test-Path -LiteralPath $venvPip)) {
    Write-Host "ERROR: venv was created but pip was not found at $venvPip" -ForegroundColor Red
    exit 1
}

Write-Host "Upgrading pip ..."
& $venvPython -m pip install --upgrade pip -q

$req = Join-Path $Root "requirements.txt"
if (-not (Test-Path -LiteralPath $req)) {
    Write-Host "ERROR: requirements.txt not found at $req" -ForegroundColor Red
    exit 1
}

Write-Host "Installing packages from requirements.txt (this may take a few minutes) ..."
& $venvPython -m pip install -r $req
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: pip install failed." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Setup finished successfully." -ForegroundColor Green

if ($NoStart) {
    Write-Host "Start the app later with: windows\Start-AnalytiX.bat"
    exit 0
}

$server = Join-Path $Root "analytx_server.py"
Write-Host ""
Write-Host "Starting AnalytiX: http://127.0.0.1:8765" -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop the server."
Write-Host ""
& $venvPython $server
