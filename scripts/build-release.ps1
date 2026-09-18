#Requires -Version 5.1
param([ValidatePattern('^[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?$')][string]$Version = '0.1.0-preview.1')
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$name = "Easy-Japanese-Subtitles-$Version-windows-x64"
$dist = Join-Path $project 'dist'
$stage = Join-Path $dist $name
$zip = "$stage.zip"
if ((Test-Path -LiteralPath $stage) -or (Test-Path -LiteralPath $zip)) {
    throw 'This version already has build artifacts. Choose a new version or move the old artifacts before rebuilding.'
}
$internal = Join-Path $stage '_internal'
New-Item -ItemType Directory -Path $internal -Force | Out-Null
# Explicit allowlist: never copy environments, credentials, caches, logs or user media.
foreach ($file in @('LICENSE','anime_subs.py','requirements.txt','constraints-windows-py314.txt','constraints-windows-py312.txt')) {
    Copy-Item -LiteralPath (Join-Path $project $file) -Destination $internal
}
$appRoot = Join-Path $project 'app'
Get-ChildItem -LiteralPath $appRoot -Recurse -File | Where-Object {
    $_.Extension -in @('.py','.html','.css','.js') -and $_.FullName -notmatch '[\\/]__pycache__[\\/]'
} | ForEach-Object {
    $relative = $_.FullName.Substring($appRoot.Length + 1)
    $target = Join-Path (Join-Path $internal 'app') $relative
    New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
    Copy-Item -LiteralPath $_.FullName -Destination $target
}
New-Item -ItemType Directory -Path (Join-Path $internal 'scripts') -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $project 'scripts/setup-runtime.py') -Destination (Join-Path $internal 'scripts')
Copy-Item -LiteralPath (Join-Path $project 'scripts/install-progress.py') -Destination (Join-Path $internal 'scripts')
& (Join-Path $PSScriptRoot 'build-launcher.ps1') -OutputDirectory $stage -PortableRelease
& (Join-Path $PSScriptRoot 'build-native.ps1') -OutputDirectory (Join-Path $internal 'native')
& (Join-Path $PSScriptRoot 'test-release-security.ps1') -Path $stage
Add-Type -AssemblyName System.IO.Compression.FileSystem
[IO.Compression.ZipFile]::CreateFromDirectory($stage, $zip)
& (Join-Path $PSScriptRoot 'test-release-security.ps1') -Path $zip
$hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
"$hash  $name.zip" | Set-Content -LiteralPath "$zip.sha256" -Encoding ASCII
Write-Host "Release archive: $zip"
