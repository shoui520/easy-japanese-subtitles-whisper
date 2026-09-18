#Requires -Version 5.1
param([Parameter(Mandatory=$true)][string]$Path)
$ErrorActionPreference = 'Stop'
$target = (Resolve-Path -LiteralPath $Path).Path
$status = Get-MpComputerStatus
if (-not $status.AMServiceEnabled -or -not $status.AntivirusEnabled -or -not $status.RealTimeProtectionEnabled) {
    throw 'Release verification requires active Microsoft Defender protection. No release was approved.'
}
$scanner = Join-Path $env:ProgramFiles 'Windows Defender/MpCmdRun.exe'
if (-not (Test-Path -LiteralPath $scanner)) { throw 'Microsoft Defender command-line scanner was not found.' }
Write-Host "Scanning release with Defender definitions $($status.AntivirusSignatureVersion)"
# Diagnostic custom scan only: report detections without quarantining the
# evidence. This does NOT disable antivirus, real-time protection or exclusions.
& $scanner -Scan -ScanType 3 -File $target -DisableRemediation
$scanExit = $LASTEXITCODE
if ($scanExit -ne 0) {
    throw "Release blocked: Defender reported a detection or could not complete the scan (exit $scanExit). Do not publish; investigate or submit to Microsoft for review."
}
if (-not (Test-Path -LiteralPath $target)) { throw 'Release disappeared during verification; it must not be published.' }
Write-Host 'Local Defender scan passed. This is not a guarantee of cloud reputation or future scan results.'
