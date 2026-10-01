param([string]$Label='desktop',[string]$Keys='', [int]$X=-1,[int]$Y=-1)
$ErrorActionPreference='Stop'
$root=Join-Path $PSScriptRoot 'client'
$process=Get-CimInstance Win32_Process -Filter "Name='tdxw.exe'" | Where-Object { $_.ExecutablePath -eq (Join-Path $root 'tdxw.exe') } | Select-Object -First 1
if (!$process) { throw 'No isolated client process' }
$shell=New-Object -ComObject WScript.Shell
if (!$shell.AppActivate([int]$process.ProcessId)) { throw 'Cannot activate isolated client' }
Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public class R3Mouse { [DllImport("user32.dll")] public static extern bool SetProcessDPIAware(); [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y); [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint x,uint y,uint d, UIntPtr e); }'
[R3Mouse]::SetProcessDPIAware() | Out-Null
if ($Keys) { $shell.SendKeys($Keys) }
if ($X -ge 0 -and $Y -ge 0) {
    [R3Mouse]::SetCursorPos($X,$Y) | Out-Null
    [R3Mouse]::mouse_event(2,0,0,0,[UIntPtr]::Zero)
    [R3Mouse]::mouse_event(4,0,0,0,[UIntPtr]::Zero)
}
Start-Sleep -Milliseconds 1000
Add-Type -AssemblyName System.Windows.Forms,System.Drawing,UIAutomationClient,UIAutomationTypes
$bounds=[System.Windows.Forms.SystemInformation]::VirtualScreen
$bitmap=New-Object System.Drawing.Bitmap($bounds.Width,$bounds.Height)
$graphics=[System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($bounds.Left,$bounds.Top,0,0,$bitmap.Size)
$evidence=Join-Path $PSScriptRoot 'evidence'
$labelPath=Join-Path $evidence ($Label+'-'+(Get-Date -Format 'yyyyMMdd-HHmmssfff'))
$bitmap.Save($labelPath+'.png'); $graphics.Dispose(); $bitmap.Dispose()
$windows=[System.Windows.Automation.AutomationElement]::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children,[System.Windows.Automation.Condition]::TrueCondition)
$output=@()
foreach($window in $windows) {
    if ($window.Current.ProcessId -ne $process.ProcessId) { continue }
    $output+=@{name=$window.Current.Name;type='window'}
    foreach($element in $window.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)) {
        $output+=@{name=$element.Current.Name;type=$element.Current.ControlType.ProgrammaticName;id=$element.Current.AutomationId;rect=$element.Current.BoundingRectangle.ToString()}
    }
}
$output | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 ($labelPath+'.json')
Write-Output ($labelPath+'.png')
$output | ConvertTo-Json -Depth 4
