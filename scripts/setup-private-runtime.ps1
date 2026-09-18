#Requires -Version 5.1
param([ValidateSet('cpu','cu128','xpu','rocm')][string]$Compute = 'cu128', [switch]$Resume, [switch]$WaitForStart)
if ($WaitForStart -and [Console]::ReadLine() -ne 'GO') { exit 1 }
$ErrorActionPreference = 'Stop'
$env:PSModulePath = "$PSHOME\Modules"
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
$project = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'runtime-profiles.ps1')
$profile = Get-RuntimeProfile $Compute
$owned = Join-Path $project '.runtime'
$downloads = Join-Path $owned 'downloads'
$profileRoot = Join-Path $owned "profiles/$Compute"
$base = Join-Path $profileRoot 'python'
$venv = Join-Path $profileRoot 'venv'
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
# Invalidate only the profile being repaired; preserve another working profile.
if ((Test-Path -LiteralPath (Join-Path $owned 'ready.json')) -and $ready.profile -eq $Compute) {
    Remove-Item -LiteralPath (Join-Path $owned 'ready.json') -ErrorAction Stop
}
function Fetch-Verified($Url, $Destination, $Sha256) {
    $label = 'Python runtime'
    if ([IO.Path]::GetFileName($Destination).StartsWith('ffmpeg')) { $label = 'media tools' }
    if ([IO.Path]::GetFileName($Destination).StartsWith('pip-')) { $label = 'package installer' }
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
            $elapsed = [Diagnostics.Stopwatch]::StartNew()
            while (($count = $inputStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
                $outputStream.Write($buffer, 0, $count)
                $received += $count
                if ($timer.ElapsedMilliseconds -ge 300) {
                    $fraction = $null
                    if ($response.ContentLength -gt 0) { $fraction = [Math]::Min(1, $received / $response.ContentLength) }
                    $speed = $received / [Math]::Max(0.001, $elapsed.Elapsed.TotalSeconds)
                    $detail = '{0:N1} MB downloaded | {1:N1} MB/s' -f ($received / 1MB), ($speed / 1MB)
                    if ($response.ContentLength -gt 0) {
                        $remaining = [TimeSpan]::FromSeconds([Math]::Max(0, ($response.ContentLength - $received) / $speed))
                        $detail = '{0:N1} / {1:N1} MB ({2:P0}) | {3:N1} MB/s | about {4}m {5:D2}s left' -f ($received / 1MB), ($response.ContentLength / 1MB), $fraction, ($speed / 1MB), ([int][Math]::Floor($remaining.TotalMinutes)), $remaining.Seconds
                    }
                    Report-Setup ("Downloading $label") $detail $fraction
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
$pythonZip = Join-Path $downloads "python/python-$($profile.Python)-amd64.zip"
Report-Setup 'Preparing Python' 'Downloading the application runtime if needed'
New-Item -ItemType Directory -Path (Split-Path -Parent $pythonZip) -Force | Out-Null
Fetch-Verified $profile.PythonUrl $pythonZip $profile.PythonHash
Report-Setup 'Preparing Python' 'Unpacking the application runtime'
$missingPython = @('python.exe','pythonw.exe',$profile.Dll,'Lib/venv/__init__.py') | Where-Object { -not (Test-Path -LiteralPath (Join-Path $base $_)) }
if ($missingPython) {
    Expand-OwnedArchive $pythonZip $base
}
$ffmpegZip = Join-Path $downloads 'ffmpeg-9.0.1-essentials.zip'
# Gyan's own versioned mirror, checked against the checksum published on gyan.dev.
Report-Setup 'Preparing media tools' 'Downloading FFmpeg and FFprobe if needed'
Fetch-Verified 'https://github.com/GyanD/codexffmpeg/releases/download/9.0.1/ffmpeg-9.0.1-essentials_build.zip' $ffmpegZip 'fec81ae03971d9dd4be3ebe02e263bd2ec1d789483f931bdba5f5715e65da2e9'
$ffmpeg = Join-Path $owned 'ffmpeg'
Report-Setup 'Preparing media tools' 'Unpacking FFmpeg and FFprobe'
$missingTools = @('ffmpeg.exe','ffprobe.exe') | Where-Object { -not (Test-Path -LiteralPath (Join-Path $ffmpeg "ffmpeg-9.0.1-essentials_build/bin/$_")) }
if ($missingTools) {
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
Report-Setup 'Preparing transcription engine' 'Checking which components need downloading'
# Python 3.12 ships an older pip without raw progress. Download the pinned wheel
# with byte progress before installing it offline, then use the tested adapter.
Report-Setup 'Preparing installer' 'Updating the package installer'
$pipVersion = & $python -c 'import pip; print(pip.__version__)'
if ($pipVersion -ne '25.3') {
    $pipWheel = Join-Path $downloads 'pip-25.3-py3-none-any.whl'
    Fetch-Verified 'https://files.pythonhosted.org/packages/44/3c/d717024885424591d5376220b5e836c2d5293ce2011523c9de23ff7bf068/pip-25.3-py3-none-any.whl' $pipWheel '9655943313a94722b7774661c21049070f6bbb0a1516bf02f7c8d5d9201514cd'
    Report-Setup 'Preparing installer' 'Installing the downloaded package installer'
    & $python -m pip --isolated install --no-index --no-deps $pipWheel
    if ($LASTEXITCODE -ne 0) { throw 'Could not prepare the package installer.' }
}
if ($profile.Sdk.Count) {
    & $python -u (Join-Path $PSScriptRoot 'install-progress.py') 'AMD runtime libraries' install --no-cache-dir @($profile.Sdk) --index-url https://pypi.org/simple
    if ($LASTEXITCODE -ne 0) { throw 'AMD runtime library installation failed.' }
}
& $python -u (Join-Path $PSScriptRoot 'install-progress.py') 'transcription engine' install --no-cache-dir $profile.TorchRequirement --index-url $profile.Index
if ($LASTEXITCODE -ne 0) { throw 'Private PyTorch installation failed.' }
Report-Setup 'Installing application components' 'Downloading and installing required packages'
& $python -u (Join-Path $PSScriptRoot 'install-progress.py') 'application components' install --no-cache-dir -r (Join-Path $project 'requirements.txt') -c (Join-Path $project $profile.Constraints) "torch==$($profile.Torch)" --index-url https://pypi.org/simple
if ($LASTEXITCODE -ne 0) { throw 'Private package installation failed.' }
Report-Setup 'Checking installation' 'Checking that the components work together'
& $python -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Private dependency check failed.' }
& $python -c 'import torch,transformers,whisper,fastapi,uvicorn,webview; from transformers import AutoModelForSpeechSeq2Seq,AutoProcessor'
if ($LASTEXITCODE -ne 0) { throw 'The installed engine could not load. See the setup log.' }
Report-Setup 'Checking processing device' 'Testing the selected runtime on your PC'
Push-Location -LiteralPath $project
try {
    & $python -m app.setup_check $profile.Device
    if ($LASTEXITCODE -ne 0) { throw 'The selected processing device could not run. Choose a compatible runtime or CPU.' }
} finally { Pop-Location }
@{ python = $profile.Python; torch = $profile.Torch; compute = $Compute; profile = $Compute; ffmpeg = '9.0.1'; powershell = $PSVersionTable.PSVersion.ToString() } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $owned 'ready.json') -Encoding UTF8
Write-Host "Private runtime prepared at $owned. No system Python, PATH, or FFmpeg installation was changed."
Report-Setup 'Complete' 'Setup finished' 1
