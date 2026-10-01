param([int]$X,[int]$Y)
$targetProcess=Get-Process tdxw -ErrorAction Stop | Select-Object -First 1
$desktopShell=New-Object -ComObject WScript.Shell
if (!$desktopShell.AppActivate($targetProcess.Id)) { throw 'Unable to activate target window' }
Add-Type -TypeDefinition 'using System.Runtime.InteropServices; public class BridgeMouse { [DllImport("user32.dll")] public static extern bool SetProcessDPIAware(); [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y); [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint x,uint y,uint d, System.UIntPtr e); }'
[BridgeMouse]::SetProcessDPIAware() | Out-Null
Start-Sleep -Milliseconds 300
[BridgeMouse]::SetCursorPos($X,$Y) | Out-Null
[BridgeMouse]::mouse_event(2,0,0,0,[System.UIntPtr]::Zero)
[BridgeMouse]::mouse_event(4,0,0,0,[System.UIntPtr]::Zero)
Start-Sleep -Milliseconds 500
& (Join-Path $PSScriptRoot 'desktop.ps1')
