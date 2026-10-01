param([ValidateSet('D','A','B','C','restore','audit')][string]$Group='D',[switch]$NoStart)
$ErrorActionPreference='Stop'
$env:PYTHONUTF8='1'
$running=@(Get-Process tdxw -ErrorAction SilentlyContinue)
if ($Group -ne 'audit' -and $running.Count -gt 0) {
    throw '请先正常关闭所有通达信窗口，再切换。不会强杀进程，也不会运行中写入。'
}
& python -B (Join-Path $PSScriptRoot 'diagnostic.py') $Group
if ($LASTEXITCODE -ne 0) { throw '诊断切换或恢复失败；请保留错误和备份' }
if ($Group -in @('D','A','B','C') -and !$NoStart) {
    $clientDirectory=Join-Path (Split-Path $PSScriptRoot -Parent) 'client'
    Start-Process -FilePath (Join-Path $clientDirectory 'tdxw.exe') -WorkingDirectory $clientDirectory -WindowStyle Normal
    Write-Host '请选游客行情；自选股应仅有999006、999007。右键测试行，明确选“查看行情”，记录提示和实际市场，再看日K，成功后再切1分钟。'
}
