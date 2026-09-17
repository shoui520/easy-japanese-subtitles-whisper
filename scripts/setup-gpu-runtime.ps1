param(
    [Parameter(Mandatory=$true)][ValidateSet('xpu','rocm')][string]$Compute,
    [Parameter(Mandatory=$true)][string]$PythonExecutable
)
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
# Separate environments: never replace the working CUDA/UI environment.
$runtimeDir = Join-Path $project ".runtimes\$Compute"
$python = Join-Path $runtimeDir 'Scripts\python.exe'
$version = & $PythonExecutable -c 'import sys,struct; print(str(sys.version_info.major)+"."+str(sys.version_info.minor)+"-"+str(struct.calcsize("P")*8))'
if ($LASTEXITCODE -ne 0) { throw 'The selected Python could not start.' }
if ($Compute -eq 'rocm' -and $version -ne '3.12-64') { throw 'This AMD ROCm profile needs 64-bit Python 3.12. Pass its python.exe using -PythonExecutable.' }
if ($Compute -eq 'xpu' -and $version -ne '3.14-64') { throw 'This Intel XPU profile uses the project constraints for 64-bit Python 3.14.' }
if (Test-Path -LiteralPath $runtimeDir) { throw 'This runtime folder already exists. Use its Python in Setup, or choose a new profile after reviewing the existing environment. It will not be overwritten.' }
& $PythonExecutable -m venv $runtimeDir
if ($LASTEXITCODE -ne 0) { throw 'Could not create the isolated GPU environment.' }
if ($Compute -eq 'xpu') {
    & $python -m pip install 'torch==2.11.0' --index-url https://download.pytorch.org/whl/xpu
    if ($LASTEXITCODE -ne 0) { throw 'Intel PyTorch installation failed.' }
    & $python -m pip install -r (Join-Path $project 'requirements.txt') -c (Join-Path $project 'constraints-windows-py314.txt')
} else {
    # Official AMD native Windows wheels; these are NOT the Linux ROCm wheels.
    $base = 'https://repo.radeon.com/rocm/windows/rocm-rel-7.2.1'
    & $python -m pip install "$base/rocm_sdk_core-7.2.1-py3-none-win_amd64.whl" "$base/rocm_sdk_devel-7.2.1-py3-none-win_amd64.whl" "$base/rocm_sdk_libraries_custom-7.2.1-py3-none-win_amd64.whl" "$base/rocm-7.2.1.tar.gz"
    if ($LASTEXITCODE -ne 0) { throw 'AMD runtime installation failed.' }
    & $python -m pip install "$base/torch-2.9.1%2Brocm7.2.1-cp312-cp312-win_amd64.whl"
    if ($LASTEXITCODE -ne 0) { throw 'AMD PyTorch installation failed.' }
    # Python 3.14's dependency freeze must not be forced onto Python 3.12.
    & $python -m pip install -r (Join-Path $project 'requirements.txt') 'torch==2.9.1+rocm7.2.1'
}
if ($LASTEXITCODE -ne 0) { throw 'Transcription package installation failed.' }
& $python -m pip check
if ($LASTEXITCODE -ne 0) { throw 'The runtime has incompatible dependencies.' }
Push-Location -LiteralPath $project
try {
    & $python -c 'import sys,torch; from app.devices import discover,select_device,smoke_test; d=select_device(sys.argv[1],discover(torch)); smoke_test(torch,d); print(d)' $Compute
    if ($LASTEXITCODE -ne 0) { throw 'Runtime installed, but the GPU check failed. Check GPU support and driver compatibility before using it.' }
} finally { Pop-Location }
Write-Host "GPU check passed. In Setup, select Python: $python"
Write-Host 'A basic GPU check is not a full transcription compatibility test. Test a short video with each model you intend to use.'
