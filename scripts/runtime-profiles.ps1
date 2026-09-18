function Get-RuntimeProfile([string]$Compute) {
    if ($Compute -notin @('cpu','cu128','xpu','rocm')) { throw 'Unknown runtime profile.' }
    $profile = @{
        Compute = $Compute; Python = '3.14.3'; Dll = 'python314.dll'
        PythonUrl = 'https://www.python.org/ftp/python/3.14.3/python-3.14.3-amd64.zip'
        PythonHash = 'ec781bb03f9638d136b24da7c83b4db1652ce767848aa856a30bb87cfdb1abe4'
        Torch = "2.11.0+$Compute"; Index = "https://download.pytorch.org/whl/$Compute"
        Device = $Compute; Constraints = 'constraints-windows-py314.txt'; Sdk = @()
    }
    if ($Compute -eq 'cu128') { $profile.Device = 'cuda' }
    if ($Compute -eq 'rocm') {
        $profile.Python = '3.12.10'; $profile.Dll = 'python312.dll'
        $profile.PythonUrl = 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.zip'
        # Python Install Manager's official index-windows.json, PythonCore 3.12-64.
        $profile.PythonHash = '8649692de846c56a7189d6dae5c322ab20deb1b5908b6f39426b62a36f39415d'
        $profile.Torch = '2.9.1+rocm7.2.1'; $profile.Index = 'https://pypi.org/simple'
        $profile.Constraints = 'constraints-windows-py312.txt'
        $repo = 'https://repo.radeon.com/rocm/windows/rocm-rel-7.2.1'
        $profile.Sdk = @("$repo/rocm_sdk_core-7.2.1-py3-none-win_amd64.whl", "$repo/rocm_sdk_devel-7.2.1-py3-none-win_amd64.whl", "$repo/rocm_sdk_libraries_custom-7.2.1-py3-none-win_amd64.whl", "$repo/rocm-7.2.1.tar.gz")
        $profile.TorchRequirement = "$repo/torch-2.9.1%2Brocm7.2.1-cp312-cp312-win_amd64.whl"
    } else { $profile.TorchRequirement = "torch==$($profile.Torch)" }
    return $profile
}
