#Requires -Version 5.1
param([ValidateSet('cpu','cu128')][string]$Compute = 'cu128')
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
$project = Split-Path -Parent $PSScriptRoot
$owned = Join-Path $project '.runtime'
$downloads = Join-Path $owned 'downloads'
$base = Join-Path $owned 'python'
$venv = Join-Path $owned 'venv'
if (Test-Path -LiteralPath $venv) { throw 'The private venv already exists. Refusing to overwrite it.' }
New-Item -ItemType Directory -Path $downloads -Force | Out-Null
function Fetch-Verified($Url, $Destination, $Sha256) {
    if (-not (Test-Path -LiteralPath $Destination)) {
        Write-Host "Downloading $Url"
        Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile "$Destination.partial" -TimeoutSec 300
        if ((Get-FileHash -LiteralPath "$Destination.partial" -Algorithm SHA256).Hash -ne $Sha256) { throw "Download checksum failed: $Url" }
        Move-Item -LiteralPath "$Destination.partial" -Destination $Destination
    }
    if ((Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash -ne $Sha256) { throw "Cached download checksum failed: $Destination" }
}
$pythonZip = Join-Path $downloads 'python/pythoncore-3.14-64-3.14.3.zip'
New-Item -ItemType Directory -Path (Split-Path -Parent $pythonZip) -Force | Out-Null
Fetch-Verified 'https://www.python.org/ftp/python/3.14.3/python-3.14.3-amd64.zip' $pythonZip 'ec781bb03f9638d136b24da7c83b4db1652ce767848aa856a30bb87cfdb1abe4'
if (-not (Test-Path -LiteralPath $base)) { Expand-Archive -LiteralPath $pythonZip -DestinationPath $base }
$ffmpegZip = Join-Path $downloads 'ffmpeg-9.0.1-essentials.zip'
# Gyan's own versioned mirror, checked against the checksum published on gyan.dev.
Fetch-Verified 'https://github.com/GyanD/codexffmpeg/releases/download/9.0.1/ffmpeg-9.0.1-essentials_build.zip' $ffmpegZip 'fec81ae03971d9dd4be3ebe02e263bd2ec1d789483f931bdba5f5715e65da2e9'
$ffmpeg = Join-Path $owned 'ffmpeg'
if (-not (Test-Path -LiteralPath $ffmpeg)) { Expand-Archive -LiteralPath $ffmpegZip -DestinationPath $ffmpeg }
# Only this script process and its children get the isolated environment.
$env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
$env:PYTHONPATH = $null
$env:PYTHONHOME = $null
$env:PYTHONNOUSERSITE = '1'
$env:PYTHONUTF8 = '1'
$env:PIP_CONFIG_FILE = 'NUL'
$env:PIP_CACHE_DIR = Join-Path $owned 'pip-cache'
$env:TEMP = Join-Path $owned 'tmp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
& (Join-Path $base 'python.exe') -m venv $venv
if ($LASTEXITCODE -ne 0) { throw 'Could not create the private venv.' }
$python = Join-Path $venv 'Scripts/python.exe'
& $python -m pip --isolated install --no-cache-dir 'torch==2.11.0' --index-url "https://download.pytorch.org/whl/$Compute"
if ($LASTEXITCODE -ne 0) { throw 'Private PyTorch installation failed.' }
& $python -m pip --isolated install --no-cache-dir -r (Join-Path $project 'requirements.txt') -r (Join-Path $project 'requirements-dev.txt') -c (Join-Path $project 'constraints-windows-py314.txt') --index-url https://pypi.org/simple
if ($LASTEXITCODE -ne 0) { throw 'Private package installation failed.' }
& $python -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Private dependency check failed.' }
@{ python = '3.14.3'; torch = '2.11.0'; compute = $Compute; ffmpeg = '9.0.1'; powershell = $PSVersionTable.PSVersion.ToString() } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $owned 'ready.json') -Encoding UTF8
Write-Host "Private runtime prepared at $owned. No system Python, PATH, or FFmpeg installation was changed."
