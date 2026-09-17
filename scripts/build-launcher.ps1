$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw 'Windows .NET Framework C# compiler was not found.' }
$outputDir = Join-Path $project 'build\launcher'
New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
$output = Join-Path $outputDir 'Easy Japanese Subtitles.exe'
& $compiler /nologo /target:winexe /optimize+ /reference:System.Windows.Forms.dll "/out:$output" (Join-Path $project 'launcher\Program.cs')
if ($LASTEXITCODE -ne 0) { throw 'Launcher compilation failed.' }
Write-Host "Built $output"
