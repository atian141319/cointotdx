$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$Stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$ReportPath = Join-Path $PSScriptRoot "cleanup-$Stamp.json"
$RelativeTargets = @(
    'r4/build',
    'r4/completion-20261002T114517Z/build',
    'r4/completion-20261002T114517Z/build-delivery',
    'r4/completion-20261002T114517Z/build-final',
    'r4/completion-20261002T114517Z/build-v2',
    'r4/completion-20261002T114517Z/build-v3',
    'r4/completion-review-20261002T124109Z',
    'r4/completion-review-20261002T124109Z-fresh',
    'r4/completion-review-20261002T124208Z-fresh'
)
$Processes = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -ne 'powershell.exe' -and $_.Name -ne 'pwsh.exe'
})
$Tracked = @(git -C $ProjectRoot ls-files)
$Plan = @()
foreach ($Relative in $RelativeTargets) {
    $Candidate = Join-Path $ProjectRoot $Relative
    if (-not (Test-Path -LiteralPath $Candidate)) { continue }
    $Resolved = (Resolve-Path -LiteralPath $Candidate).Path
    if (-not $Resolved.StartsWith($ProjectRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Target outside project: $Resolved"
    }
    $Contents = @(Get-ChildItem -LiteralPath $Resolved -Recurse -Force)
    $Top = Get-Item -LiteralPath $Resolved -Force
    if (@(@($Top) + $Contents | Where-Object {
        $_.Attributes -band [IO.FileAttributes]::ReparsePoint
    }).Count) { throw "Refuse reparse point: $Resolved" }
    if (@($Tracked | Where-Object { $_ -eq $Relative -or $_.StartsWith($Relative + '/') }).Count) {
        throw "Refuse tracked files: $Resolved"
    }
    if (@($Processes | Where-Object {
        ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($Resolved + '\', [StringComparison]::OrdinalIgnoreCase)) -or
        ($_.CommandLine -and $_.CommandLine.IndexOf($Resolved, [StringComparison]::OrdinalIgnoreCase) -ge 0)
    }).Count) { throw "Target referenced by running process: $Resolved" }
    $Files = @($Contents | Where-Object { -not $_.PSIsContainer })
    if ($Relative -like '*completion-review*') {
        $ArchiveRoot = $Resolved -replace '-fresh$', ''
        $ArchivePath = $ArchiveRoot + '.zip'
        $HashPath = $ArchiveRoot + '.sha256'
        if (-not (Test-Path -LiteralPath $ArchivePath) -or -not (Test-Path -LiteralPath $HashPath)) {
            throw "Missing retained archive/hash: $Resolved"
        }
        $Expected = ((Get-Content -LiteralPath $HashPath -Raw).Trim() -split '\s+')[0]
        if ((Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash -ne $Expected) {
            throw "Archive hash mismatch: $ArchivePath"
        }
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $Archive = [IO.Compression.ZipFile]::OpenRead($ArchivePath)
        try {
            foreach ($File in $Files) {
                $EntryName = $File.FullName.Substring($Resolved.Length + 1).Replace('\', '/')
                if ($EntryName -match '(^|/)__pycache__/[^/]+\.pyc$') { continue }
                if ($EntryName -eq 'evidence/windows/exact-data/market.sqlite3-shm') { continue }
                if ($EntryName -eq 'evidence/windows/exact-data/market.sqlite3-wal' -and $File.Length -eq 0) { continue }
                $Entry = $Archive.GetEntry($EntryName)
                if (-not $Entry) { throw "Not archived: $($File.FullName)" }
                $Stream = $Entry.Open()
                $Hasher = [Security.Cryptography.SHA256]::Create()
                try { $ArchivedHash = [BitConverter]::ToString($Hasher.ComputeHash($Stream)).Replace('-', '') }
                finally { $Stream.Dispose(); $Hasher.Dispose() }
                if ((Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash -ne $ArchivedHash) {
                    throw "Changed since archive: $($File.FullName)"
                }
            }
        } finally { $Archive.Dispose() }
    }
    $Plan += [pscustomobject]@{
        path = $Resolved; files = $Files.Count
        bytes = [long](($Files | Measure-Object -Property Length -Sum).Sum)
        status = 'verified_for_removal'
    }
}
$Receipt = [pscustomobject]@{utc = $Stamp; targets = $Plan; completed = $false}
$Receipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ReportPath -Encoding UTF8
foreach ($Item in $Plan) {
    Remove-Item -LiteralPath $Item.path -Recurse -Force
    $Item.status = 'removed'
    $Receipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ReportPath -Encoding UTF8
}
$Receipt.completed = $true
$Receipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ReportPath -Encoding UTF8
[pscustomobject]@{
    directories = $Plan.Count
    reclaimed_bytes = ($Plan | Measure-Object -Property bytes -Sum).Sum
    report = $ReportPath
} | ConvertTo-Json
