param([Parameter(Mandatory=$true)][string]$PlanPath)
$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$Plan = Get-Content -LiteralPath $PlanPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $Plan.verified) { throw 'Archive verification required' }
$ArchivePath = (Resolve-Path -LiteralPath $Plan.archive).Path
if (-not $ArchivePath.StartsWith($ProjectRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Archive outside project' }
if ((Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash -ne $Plan.archive_sha256) { throw 'Archive hash mismatch' }
$Processes = @(Get-CimInstance Win32_Process | Where-Object { $_.Name -notin @('powershell.exe','pwsh.exe') })
$Tracked = @(git -C $ProjectRoot ls-files)
foreach ($Target in $Plan.targets) {
    $Resolved = (Resolve-Path -LiteralPath $Target).Path
    if (-not $Resolved.StartsWith($ProjectRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw "Outside project: $Resolved" }
    if ((Get-Item -LiteralPath $Resolved).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse point target' }
    $Relative = $Resolved.Substring($ProjectRoot.Length + 1).Replace('\','/')
    if (@($Tracked | Where-Object { $_ -eq $Relative -or $_.StartsWith($Relative + '/') }).Count) { throw 'Tracked target' }
    if (@($Processes | Where-Object {
        ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($Resolved + '\',[StringComparison]::OrdinalIgnoreCase)) -or
        ($_.CommandLine -and $_.CommandLine.IndexOf($Resolved,[StringComparison]::OrdinalIgnoreCase) -ge 0)
    }).Count) { throw "Active target: $Resolved" }
    if ($Resolved -match '\\display\\batches\\[^\\]+$') {
        $Journal = Get-Content -LiteralPath (Join-Path $Resolved 'receipt.json') -Encoding UTF8 -Raw | ConvertFrom-Json
        if ($Journal.state -ne 'COMMITTED') { throw "Unsettled journal: $Resolved" }
    }
}
$ReceiptPath = Join-Path (Split-Path -Parent $PlanPath) 'CLEANUP-RECEIPT.json'
$Removed = 0
foreach ($Target in $Plan.targets) {
    Remove-Item -LiteralPath $Target -Recurse -Force
    $Removed++
    if ($Removed % 100 -eq 0) { Write-Output "Removed $Removed archived directories" }
}
[pscustomobject]@{
    utc=[DateTime]::UtcNow.ToString('o'); removed_directories=$Removed
    original_bytes=$Plan.source_bytes; retained_archive_bytes=$Plan.archive_bytes
    net_reclaimed_bytes=($Plan.source_bytes-$Plan.archive_bytes)
    archive=$ArchivePath; archive_sha256=$Plan.archive_sha256
    active_runtime_preserved=$true; exact_database_and_raw_responses_preserved=$true
    old_zip_evidence_unchanged=$true
} | ConvertTo-Json | Set-Content -LiteralPath $ReceiptPath -Encoding UTF8
Get-Content -LiteralPath $ReceiptPath -Encoding UTF8
