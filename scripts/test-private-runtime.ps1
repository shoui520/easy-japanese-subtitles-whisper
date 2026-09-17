#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$owned = Join-Path $project '.runtime'
$env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
foreach ($name in @('PYTHONPATH','PYTHONHOME','PYTHONUSERBASE','VIRTUAL_ENV','CONDA_PREFIX','CUDA_PATH','CUDA_HOME','HF_TOKEN','HUGGING_FACE_HUB_TOKEN','TRANSFORMERS_CACHE','HUGGINGFACE_HUB_CACHE')) {
    [Environment]::SetEnvironmentVariable($name, $null, 'Process')
}
$env:PYTHONNOUSERSITE = '1'
$env:PYTHONUTF8 = '1'
$env:HF_HOME = Join-Path $owned 'models/huggingface'
$env:HF_HUB_CACHE = Join-Path $env:HF_HOME 'hub'
$env:HF_HUB_DISABLE_IMPLICIT_TOKEN = '1'
$env:HF_HUB_DISABLE_TELEMETRY = '1'
$env:XDG_CACHE_HOME = Join-Path $owned 'cache'
$env:TEMP = Join-Path $owned 'tmp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
Write-Host "Verification shell: $($PSVersionTable.PSVersion)"
Write-Host "PATH: $env:PATH"
Push-Location -LiteralPath $project
try {
    & (Join-Path $owned 'venv/Scripts/python.exe') -s -m tests.verify_private_runtime
    if ($LASTEXITCODE -ne 0) { throw 'Private runtime verification failed. See the retained test artifacts.' }
} finally { Pop-Location }
