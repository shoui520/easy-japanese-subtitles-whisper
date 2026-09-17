param([ValidateSet('cpu','cu128')][string]$Compute = 'cu128')
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $project
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Install Python with Python Install Manager, then run setup again.' }
}
& '.\.venv\Scripts\python.exe' -m pip install torch==2.11.0 --index-url "https://download.pytorch.org/whl/$Compute"
if ($LASTEXITCODE -ne 0) { throw 'PyTorch setup failed. Check the connection and Python version.' }
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt -r requirements-dev.txt -c constraints-windows-py314.txt
if ($LASTEXITCODE -ne 0) { throw 'Package setup failed. See the message above.' }
& (Join-Path $PSScriptRoot 'build-launcher.ps1')
Write-Host 'Setup complete. Open build\launcher\Easy Japanese Subtitles.exe to start the desktop app.'
