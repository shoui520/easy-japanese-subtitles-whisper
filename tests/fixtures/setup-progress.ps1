param([switch]$Resume, [switch]$WaitForStart, [string]$Compute)
if ($WaitForStart -and [Console]::ReadLine() -ne 'GO') { exit 1 }
if ($env:SETUP_EXPECTED_PROFILE -and $Compute -ne $env:SETUP_EXPECTED_PROFILE) { exit 9 }
[Console]::WriteLine('SETUP {"stage":"Downloading media tools","detail":"Test progress","progress":0.5}')
Start-Sleep -Milliseconds 300
[Console]::WriteLine('SETUP {"stage":"Installing application components","detail":"1 of 4 packages installed (25%)\nInstalling numpy - 0m 01s elapsed","progress":0.25}')
Start-Sleep -Milliseconds 300
if ($env:SETUP_TEST_FAIL -eq '1') {
    [Console]::WriteLine('SETUP {"stage":"Device check failed","detail":"Choose a compatible driver or CPU.","progress":null,"error":"Choose a compatible driver or CPU."}')
    exit 1
}
$root = Split-Path -Parent $PSScriptRoot
New-Item -ItemType Directory -Path (Join-Path $root '.runtime') -Force | Out-Null
'{}' | Set-Content -LiteralPath (Join-Path $root '.runtime/ready.json')
[Console]::WriteLine('SETUP {"stage":"Complete","detail":"Finished","progress":1}')
