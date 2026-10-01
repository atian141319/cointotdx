param([ValidateSet('start','initial','update','restore','status')][string]$Action='status')
$ErrorActionPreference='Stop'
$env:PYTHONUTF8='1'
$clientDirectory=Join-Path $PSScriptRoot 'client'
if ($Action -eq 'start') {
    if (@(Get-CimInstance Win32_Process -Filter "Name='tdxw.exe'").Count -gt 0) {
        throw '请先正常关闭所有通达信窗口，再启动项目内副本。不会强杀进程。'
    }
    $associationReceipt=Join-Path $PSScriptRoot 'evidence\registration-association-attempt.json'
    if (!(Test-Path -LiteralPath $associationReceipt)) {
        & python -B (Join-Path $PSScriptRoot 'experiment.py') associate
        if ($LASTEXITCODE -ne 0) { throw '候选缓存关联写入失败，未启动副本' }
    }
    foreach ($transaction in Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'transactions') -Filter changes.json -Recurse) {
        $receipt=Get-Content -LiteralPath $transaction.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($receipt.state -ne 'COMMITTED') { throw '发现未完成的写入批次，请先关闭副本并执行restore.cmd恢复，避免读取半批文件。' }
    }
    Start-Process -FilePath (Join-Path $clientDirectory 'tdxw.exe') -WorkingDirectory $clientDirectory -WindowStyle Normal
    Write-Host '显示试验副本已启动。候选999006=BTCUSDT显示试验，999007=ETHUSDT显示试验。注册识别尚待验证。'
    exit
}
& python -B (Join-Path $PSScriptRoot 'experiment.py') $Action
if ($LASTEXITCODE -ne 0) { throw '操作失败；不会强杀进程，备份和日志保留' }
