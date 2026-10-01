param([ValidateSet('启动','初始写入','增量更新','恢复','状态')][string]$操作='状态')
$ErrorActionPreference='Stop'
$env:PYTHONUTF8='1'
$clientDirectory=Join-Path $PSScriptRoot 'client'
if ($操作 -eq '启动') {
    $running=@(Get-CimInstance Win32_Process -Filter "Name='tdxw.exe'")
    if ($running.Count -gt 0) { throw '请先正常关闭当前通达信，再启动项目内副本，避免复用原窗口。脚本不会强杀。' }
    $testProgram=Join-Path $clientDirectory 'tdxw.exe'
    if (!(Test-Path -LiteralPath $testProgram)) { throw '隔离副本尚未准备好' }
    Start-Process -FilePath $testProgram -WorkingDirectory $clientDirectory -WindowStyle Hidden
    Write-Host '已启动项目内副本。若出现登录页，选离线分析；不登录交易账户。候选代码999006/999007，键入M1回车试切1分钟。'
    exit
}
$actions=@{'初始写入'='initial';'增量更新'='update';'恢复'='restore';'状态'='status'}
& python -B (Join-Path $PSScriptRoot 'experiment.py') $actions[$操作]
if ($LASTEXITCODE -ne 0) { throw '操作失败，详见上方错误；没有强杀客户端' }
