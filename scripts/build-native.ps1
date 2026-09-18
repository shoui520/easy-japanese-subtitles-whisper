#Requires -Version 5.1
param([string]$OutputDirectory = '')
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $project 'build/native' }
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$compiler = Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
$output = Join-Path $OutputDirectory 'EasySubs.Native.dll'
& $compiler /nologo /target:library /platform:x64 /optimize+ /reference:System.Windows.Forms.dll "/out:$output" (Join-Path $project 'launcher/NativeDrop.cs')
if ($LASTEXITCODE -ne 0) { throw 'Native file-drop component compilation failed.' }
