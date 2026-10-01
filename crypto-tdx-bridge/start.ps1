param([ValidateSet('check','sync','run','status','gaps','export','stop','tdx-export')][string]$Action='check', [string]$Config='config.json', [string]$End='')
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
if (!(Test-Path -LiteralPath $Config)) { Copy-Item -LiteralPath 'config.example.json' -Destination $Config }
$bridgeArguments=@('bridge.py',$Action,'--config',$Config)
if ($End) { $bridgeArguments+=@('--end',$End) }
& python @bridgeArguments
exit $LASTEXITCODE
