param([string]$Keys='.927{ENTER}')
$targetProcess=Get-Process tdxw -ErrorAction Stop | Select-Object -First 1
$desktopShell=New-Object -ComObject WScript.Shell
if (!$desktopShell.AppActivate($targetProcess.Id)) { throw 'Unable to activate target window' }
Start-Sleep -Milliseconds 500
$desktopShell.SendKeys($Keys)
Start-Sleep -Milliseconds 700
& (Join-Path $PSScriptRoot 'desktop.ps1')
