$ErrorActionPreference = 'Stop'
$ArchiveRoot = Join-Path $PSScriptRoot 'cold-archive-20261002T132219Z'
$ArchiverId = 14808
$Archiver = Get-CimInstance Win32_Process -Filter "ProcessId=$ArchiverId"
if ($Archiver -and $Archiver.CommandLine -like '*archive-cold-artifacts.py*') {
    $ArchiverProcess = Get-Process -Id $ArchiverId -ErrorAction Stop
    $ArchiverProcess.WaitForExit()
}
$PlanPath = Join-Path $ArchiveRoot 'removal-plan.json'
if (-not (Test-Path -LiteralPath $PlanPath)) { throw 'Archive did not complete verification; nothing removed' }
& (Join-Path $PSScriptRoot 'remove-archived-artifacts.ps1') -PlanPath $PlanPath
if (-not (Test-Path -LiteralPath (Join-Path $ArchiveRoot 'CLEANUP-RECEIPT.json'))) {
    throw 'Cleanup did not complete'
}
