#Requires -Version 5.1
param([ValidateSet('cpu','cu128')][string]$Compute = 'cu128', [switch]$Resume, [switch]$WaitForStart)
if ($WaitForStart -and [Console]::ReadLine() -ne 'GO') { exit 1 }
$ErrorActionPreference = 'Stop'
$env:PSModulePath = "$PSHOME\Modules"
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
$project = Split-Path -Parent $PSScriptRoot
$owned = Join-Path $project '.runtime'
$downloads = Join-Path $owned 'downloads'
$base = Join-Path $owned 'python'
$venv = Join-Path $owned 'venv'
$ownedPrefix = [IO.Path]::GetFullPath($owned).TrimEnd('\') + '\'
$activeRuntime = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" | Where-Object {
    $_.ExecutablePath -and $_.ExecutablePath.StartsWith($ownedPrefix, [StringComparison]::OrdinalIgnoreCase)
})
if ($activeRuntime.Count -gt 0) { throw 'Close the app before repairing its runtime, then retry setup.' }
New-Item -ItemType Directory -Path $downloads -Force | Out-Null
function Report-Setup($Stage, $Detail, $Progress = $null) {
    $event = @{ stage = $Stage; detail = $Detail; progress = $Progress }
    [Console]::WriteLine('SETUP ' + ($event | ConvertTo-Json -Compress))
}
function Expand-OwnedArchive($Archive, $Destination) {
    # Expand-Archive -Force removes existing files before extracting replacements.
    # Use the ZIP API so a locked file fails on open without first deleting it.
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $root = [IO.Path]::GetFullPath($Destination).TrimEnd('\') + '\'
    $zip = [IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        foreach ($entry in $zip.Entries) {
            $target = [IO.Path]::GetFullPath((Join-Path $Destination $entry.FullName))
            if (-not $target.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) { throw 'Archive path is outside the runtime folder.' }
            if (-not $entry.Name) { [IO.Directory]::CreateDirectory($target) | Out-Null }
            else {
                [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target)) | Out-Null
                [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $target, $true)
            }
        }
    } finally { $zip.Dispose() }
}
$ownership = Join-Path $owned 'setup-owned.txt'
$legacyOwned = $false
if (Test-Path -LiteralPath (Join-Path $owned 'ready.json')) {
    $ready = Get-Content -LiteralPath (Join-Path $owned 'ready.json') -Raw | ConvertFrom-Json
    $legacyOwned = $ready.python -eq '3.14.3' -and $ready.ffmpeg -eq '9.0.1' -and $ready.torch -eq '2.11.0'
}
if ((Test-Path -LiteralPath $venv) -and (-not $Resume -or (-not (Test-Path -LiteralPath $ownership) -and -not $legacyOwned))) {
    throw 'An existing runtime cannot be replaced automatically. See the setup log.'
}
if (-not (Test-Path -LiteralPath $ownership)) { 'easy-japanese-subtitles-private-runtime-v1' | Set-Content -LiteralPath $ownership -Encoding ASCII }
if ($legacyOwned) {
    # Do not advertise a usable runtime if a repair is cancelled halfway through.
    Remove-Item -LiteralPath (Join-Path $owned 'ready.json') -ErrorAction Stop
}
function Fetch-Verified($Url, $Destination, $Sha256) {
    $label = 'Python runtime'
    if ([IO.Path]::GetFileName($Destination).StartsWith('ffmpeg')) { $label = 'media tools' }
    if (-not (Test-Path -LiteralPath $Destination)) {
        Write-Host "Downloading $Url"
        $request = [Net.HttpWebRequest]::Create($Url)
        $request.Timeout = 60000
        $request.ReadWriteTimeout = 60000
        $response = $request.GetResponse()
        $inputStream = $null; $outputStream = $null
        try {
            $inputStream = $response.GetResponseStream()
            $outputStream = [IO.File]::Create("$Destination.partial")
            $buffer = New-Object byte[] 1048576
            $received = [long]0
            $timer = [Diagnostics.Stopwatch]::StartNew()
            while (($count = $inputStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
                $outputStream.Write($buffer, 0, $count)
                $received += $count
                if ($timer.ElapsedMilliseconds -ge 300) {
                    $fraction = $null
                    if ($response.ContentLength -gt 0) { $fraction = [Math]::Min(1, $received / $response.ContentLength) }
                    Report-Setup ("Downloading $label") (([Math]::Round($received / 1MB, 1)).ToString() + ' MB downloaded') $fraction
                    $timer.Restart()
                }
            }
        } finally {
            if ($outputStream) { $outputStream.Dispose() }
            if ($inputStream) { $inputStream.Dispose() }
            $response.Dispose()
        }
        Report-Setup 'Verifying download' ([IO.Path]::GetFileName($Destination))
        if ((Get-FileHash -LiteralPath "$Destination.partial" -Algorithm SHA256).Hash -ne $Sha256) { throw "Download checksum failed: $Url" }
        Move-Item -LiteralPath "$Destination.partial" -Destination $Destination
    }
    if ((Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash -ne $Sha256) { throw "Cached download checksum failed: $Destination" }
}
$pythonZip = Join-Path $downloads 'python/pythoncore-3.14-64-3.14.3.zip'
Report-Setup 'Preparing Python' 'Downloading the application runtime if needed'
New-Item -ItemType Directory -Path (Split-Path -Parent $pythonZip) -Force | Out-Null
Fetch-Verified 'https://www.python.org/ftp/python/3.14.3/python-3.14.3-amd64.zip' $pythonZip 'ec781bb03f9638d136b24da7c83b4db1652ce767848aa856a30bb87cfdb1abe4'
Report-Setup 'Preparing Python' 'Unpacking the application runtime'
$missingPython = @('python.exe','pythonw.exe','python314.dll','Lib/venv/__init__.py') | Where-Object { -not (Test-Path -LiteralPath (Join-Path $base $_)) }
if (-not $legacyOwned -or $missingPython) {
    Expand-OwnedArchive $pythonZip $base
}
$ffmpegZip = Join-Path $downloads 'ffmpeg-9.0.1-essentials.zip'
# Gyan's own versioned mirror, checked against the checksum published on gyan.dev.
Report-Setup 'Preparing media tools' 'Downloading FFmpeg and FFprobe if needed'
Fetch-Verified 'https://github.com/GyanD/codexffmpeg/releases/download/9.0.1/ffmpeg-9.0.1-essentials_build.zip' $ffmpegZip 'fec81ae03971d9dd4be3ebe02e263bd2ec1d789483f931bdba5f5715e65da2e9'
$ffmpeg = Join-Path $owned 'ffmpeg'
Report-Setup 'Preparing media tools' 'Unpacking FFmpeg and FFprobe'
$missingTools = @('ffmpeg.exe','ffprobe.exe') | Where-Object { -not (Test-Path -LiteralPath (Join-Path $ffmpeg "ffmpeg-9.0.1-essentials_build/bin/$_")) }
if (-not $legacyOwned -or $missingTools) {
    Expand-OwnedArchive $ffmpegZip $ffmpeg
}
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
Report-Setup 'Preparing environment' 'Creating the private Python environment'
& (Join-Path $base 'python.exe') -m venv $venv
if ($LASTEXITCODE -ne 0) { throw 'Could not create the private venv.' }
$python = Join-Path $venv 'Scripts/python.exe'
Report-Setup 'Installing transcription engine' 'Downloading and installing the engine. This may take several minutes.'
& $python -m pip --isolated install --no-cache-dir "torch==2.11.0+$Compute" --index-url "https://download.pytorch.org/whl/$Compute"
if ($LASTEXITCODE -ne 0) { throw 'Private PyTorch installation failed.' }
Report-Setup 'Installing application components' 'Downloading and installing required packages'
& $python -m pip --isolated install --no-cache-dir -r (Join-Path $project 'requirements.txt') -r (Join-Path $project 'requirements-dev.txt') -c (Join-Path $project 'constraints-windows-py314.txt') --index-url https://pypi.org/simple
if ($LASTEXITCODE -ne 0) { throw 'Private package installation failed.' }
Report-Setup 'Checking installation' 'Checking that the components work together'
& $python -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Private dependency check failed.' }
& $python -c 'import torch,transformers,whisper,fastapi,uvicorn,webview; from transformers import AutoModelForSpeechSeq2Seq,AutoProcessor'
if ($LASTEXITCODE -ne 0) { throw 'The installed engine could not load. See the setup log.' }
@{ python = '3.14.3'; torch = '2.11.0'; compute = $Compute; ffmpeg = '9.0.1'; powershell = $PSVersionTable.PSVersion.ToString() } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $owned 'ready.json') -Encoding UTF8
Write-Host "Private runtime prepared at $owned. No system Python, PATH, or FFmpeg installation was changed."
Report-Setup 'Complete' 'Setup finished' 1
