#Requires -Version 5.1
param([string]$OutputDirectory = '', [switch]$PortableRelease)
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw 'Windows .NET Framework C# compiler was not found.' }
$outputDir = Join-Path $project 'build\launcher'
if ($OutputDirectory) { $outputDir = [IO.Path]::GetFullPath($OutputDirectory) }
New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
$output = Join-Path $outputDir 'Easy Japanese Subtitles.exe'
$defines = '/define:DEVELOPMENT'
if ($PortableRelease) { $defines = '/define:PORTABLE_RELEASE' }
& $compiler /nologo /target:winexe /platform:x64 /optimize+ $defines /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll /reference:System.IO.Compression.dll /reference:System.IO.Compression.FileSystem.dll "/out:$output" (Join-Path $project 'launcher\Program.cs') (Join-Path $project 'launcher\SetupWindow.cs') (Join-Path $project 'launcher\ProcessJob.cs') (Join-Path $project 'launcher\RuntimeBootstrap.cs')
if ($LASTEXITCODE -ne 0) { throw 'Launcher compilation failed.' }
Write-Host "Built $output"
