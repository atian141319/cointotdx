Add-Type -TypeDefinition 'using System.Runtime.InteropServices; public class BridgeDpi { [DllImport("user32.dll")] public static extern bool SetProcessDPIAware(); }'
[BridgeDpi]::SetProcessDPIAware() | Out-Null
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$evidenceDirectory=Join-Path $PSScriptRoot '..\evidence'
$screenBounds=[System.Windows.Forms.SystemInformation]::VirtualScreen
$screenBitmap=New-Object System.Drawing.Bitmap($screenBounds.Width,$screenBounds.Height)
$screenGraphics=[System.Drawing.Graphics]::FromImage($screenBitmap)
$screenGraphics.CopyFromScreen($screenBounds.Left,$screenBounds.Top,0,0,$screenBitmap.Size)
$screenBitmap.Save((Join-Path $evidenceDirectory 'desktop.png'))
$screenGraphics.Dispose()
$screenBitmap.Dispose()
$desktopRoot=[System.Windows.Automation.AutomationElement]::RootElement
$windows=$desktopRoot.FindAll([System.Windows.Automation.TreeScope]::Children,[System.Windows.Automation.Condition]::TrueCondition)
$windowEvidence=@()
foreach($window in $windows) {
  if($window.Current.ProcessId -eq (Get-Process tdxw -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Id)) {
    $windowEvidence+=@{Name=$window.Current.Name;ProcessId=$window.Current.ProcessId}
    $descendants=$window.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
    foreach($element in $descendants) { $windowEvidence+=@{Name=$element.Current.Name;Type=$element.Current.ControlType.ProgrammaticName;Id=$element.Current.AutomationId} }
  }
}
$windowEvidence | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 (Join-Path $evidenceDirectory 'uia.json')
$windowEvidence | ConvertTo-Json -Depth 4
