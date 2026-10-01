param([ValidateSet('start','capture','keys','click','rightclick','windowclick','windowkeys','context','controlclick','close')][string]$Action='capture',
      [ValidatePattern('^[A-Za-z0-9_-]+$')][string]$Label='chart', [string]$Keys='', [int]$X=0,[int]$Y=0,[string]$ControlId='3003', [long]$TargetHandle=0)
$ErrorActionPreference='Stop'
$clientDirectory=Join-Path (Split-Path $PSScriptRoot -Parent) 'client'
$expected=(Join-Path $clientDirectory 'tdxw.exe')
$processes=@(Get-CimInstance Win32_Process -Filter "Name='tdxw.exe'")
if ($Action -eq 'start') {
    if ($processes.Count -gt 0) { throw '请正常关闭全部通达信窗口；不会强杀或复用原窗口' }
    Start-Process -FilePath $expected -WorkingDirectory $clientDirectory -WindowStyle Normal
    Start-Sleep -Seconds 3
    $processes=@(Get-CimInstance Win32_Process -Filter "Name='tdxw.exe'")
}
$target=@($processes | Where-Object { $_.ExecutablePath -eq $expected })
if ($target.Count -ne 1) { throw '未找到唯一的隔离副本进程' }
$targetId=[int]$target[0].ProcessId
$process=Get-Process -Id $targetId
if ($Action -eq 'close') {
    $sent=$process.CloseMainWindow()
    Start-Sleep -Seconds 2
    @{normal_close_requested=$sent;still_running=!!(Get-Process -Id $targetId -ErrorAction SilentlyContinue);path=$expected} | ConvertTo-Json
    exit
}
Add-Type -AssemblyName UIAutomationClient,UIAutomationTypes,System.Drawing
Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public class R3ACapture { [StructLayout(LayoutKind.Sequential)] public struct GUI { public int cbSize; public uint flags; public IntPtr active,focus,capture,menuOwner,moveSize,caret; public RECT caretRect; } [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h,out uint p); [DllImport("user32.dll")] public static extern bool GetGUIThreadInfo(uint t,ref GUI g); public static IntPtr Focus(IntPtr h) { uint p; uint t=GetWindowThreadProcessId(h,out p); GUI g=new GUI(); g.cbSize=Marshal.SizeOf(typeof(GUI)); return GetGUIThreadInfo(t,ref g) && g.focus!=IntPtr.Zero ? g.focus : h; } [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L,T,R,B; } [DllImport("user32.dll")] public static extern bool SetProcessDPIAware(); [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h,uint m,IntPtr w,IntPtr l); [DllImport("user32.dll")] public static extern IntPtr GetParent(IntPtr h); [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h,out RECT r); [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h,IntPtr dc,uint f); [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y); [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint x,uint y,uint d,UIntPtr e); }'
[R3ACapture]::SetProcessDPIAware() | Out-Null
$shell=New-Object -ComObject WScript.Shell
if (!$shell.AppActivate($targetId)) { throw '无法激活隔离副本' }
Start-Sleep -Milliseconds 300
if ($Action -eq 'controlclick') {
    $element=[System.Windows.Automation.AutomationElement]::FromHandle($process.MainWindowHandle)
    $controls=$element.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
    foreach ($control in $controls) {
        if ($control.Current.AutomationId -eq $ControlId) {
            $handle=[IntPtr]$control.Current.NativeWindowHandle
            $parent=[R3ACapture]::GetParent($handle)
            [R3ACapture]::PostMessage($parent,0x0111,[IntPtr][int]$ControlId,$handle) | Out-Null
        }
    }
}

if ($Action -eq 'keys') { $shell.SendKeys($Keys) }
if ($Action -eq 'windowkeys') {
    if ($Keys -in @('{F5}','{ENTER}','{ESC}')) {
        $key=13
        if ($Keys -eq '{F5}') { $key=116 }
        if ($Keys -eq '{ESC}') { $key=27 }
        $focus=[R3ACapture]::Focus($process.MainWindowHandle)
        [R3ACapture]::PostMessage($focus,0x0100,[IntPtr]$key,[IntPtr]1) | Out-Null
        if ($key -eq 13) { [R3ACapture]::PostMessage($focus,0x0102,[IntPtr]13,[IntPtr]1) | Out-Null }
        [R3ACapture]::PostMessage($focus,0x0101,[IntPtr]$key,[IntPtr]0) | Out-Null
    } else {
        foreach ($character in $Keys.ToCharArray()) {
            $focus=[R3ACapture]::Focus($process.MainWindowHandle)
            [R3ACapture]::PostMessage($focus,0x0100,[IntPtr][int]$character,[IntPtr]1) | Out-Null
            [R3ACapture]::PostMessage($focus,0x0101,[IntPtr][int]$character,[IntPtr]0) | Out-Null
            Start-Sleep -Milliseconds 150
        }
    }
}
if ($Action -eq 'context') {
    $focus=[R3ACapture]::Focus($process.MainWindowHandle)
    [R3ACapture]::PostMessage($focus,0x007B,$focus,[IntPtr](-1)) | Out-Null
}

if ($Action -eq 'windowclick') {
    $clickHandle=$process.MainWindowHandle
    if ($TargetHandle) {
        [uint32]$ownerId=0
        [R3ACapture]::GetWindowThreadProcessId([IntPtr]$TargetHandle,[ref]$ownerId) | Out-Null
        if ($ownerId -ne $targetId) { throw 'Target handle belongs to another process' }
        $clickHandle=[IntPtr]$TargetHandle
    }
    $point=[IntPtr](($Y -shl 16) -bor ($X -band 65535))
    [R3ACapture]::PostMessage($clickHandle,0x0201,[IntPtr]1,$point) | Out-Null
    [R3ACapture]::PostMessage($clickHandle,0x0202,[IntPtr]0,$point) | Out-Null
}
if ($Action -in @('click','rightclick')) {
    $rect=New-Object R3ACapture+RECT
    [R3ACapture]::GetWindowRect($process.MainWindowHandle,[ref]$rect) | Out-Null
    [R3ACapture]::SetCursorPos($rect.L+$X,$rect.T+$Y) | Out-Null
    $down=2; $up=4
    if ($Action -eq 'rightclick') { $down=8; $up=16 }
    [R3ACapture]::mouse_event($down,0,0,0,[UIntPtr]::Zero)
    [R3ACapture]::mouse_event($up,0,0,0,[UIntPtr]::Zero)
}
Start-Sleep -Milliseconds 900
$stamp=Get-Date -Format 'yyyyMMdd-HHmmssfff'
$prefix=Join-Path (Join-Path $PSScriptRoot 'evidence') ($Label+'-'+$stamp)
$root=[System.Windows.Automation.AutomationElement]::RootElement
$windows=$root.FindAll([System.Windows.Automation.TreeScope]::Children,[System.Windows.Automation.Condition]::TrueCondition)
$items=@();$number=0
foreach($window in $windows) {
    if ($window.Current.ProcessId -ne $targetId) { continue }
    $number++
    $items+=@{name=$window.Current.Name;type='window';rect=$window.Current.BoundingRectangle.ToString();handle=$window.Current.NativeWindowHandle}
    $handle=[IntPtr]$window.Current.NativeWindowHandle
    $rect=New-Object R3ACapture+RECT
    if ([R3ACapture]::GetWindowRect($handle,[ref]$rect) -and $rect.R -gt $rect.L -and $rect.B -gt $rect.T) {
        $bitmap=New-Object System.Drawing.Bitmap(($rect.R-$rect.L),($rect.B-$rect.T))
        $graphics=[System.Drawing.Graphics]::FromImage($bitmap);$dc=$graphics.GetHdc()
        $printed=[R3ACapture]::PrintWindow($handle,$dc,2);$graphics.ReleaseHdc($dc)
        if ($printed) { $bitmap.Save($prefix+'-'+$number+'.png');Write-Output ($prefix+'-'+$number+'.png') }
        $graphics.Dispose();$bitmap.Dispose()
    }
    foreach($element in $window.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)) {
        if (($element.Current.Name.Length -gt 0 -and $element.Current.AutomationId -eq '') -and $element.Current.NativeWindowHandle) {
            $dialogHandle=[IntPtr]$element.Current.NativeWindowHandle
            $dialogRect=New-Object R3ACapture+RECT
            [R3ACapture]::GetWindowRect($dialogHandle,[ref]$dialogRect) | Out-Null
            if ($dialogRect.R -gt $dialogRect.L -and $dialogRect.B -gt $dialogRect.T) {
                $dialogBitmap=New-Object System.Drawing.Bitmap(($dialogRect.R-$dialogRect.L),($dialogRect.B-$dialogRect.T))
                $dialogGraphics=[System.Drawing.Graphics]::FromImage($dialogBitmap);$dialogDc=$dialogGraphics.GetHdc()
                [R3ACapture]::PrintWindow($dialogHandle,$dialogDc,2) | Out-Null
                $dialogGraphics.ReleaseHdc($dialogDc);$dialogBitmap.Save($prefix+'-dialog-'+$element.Current.NativeWindowHandle+'.png')
                $dialogGraphics.Dispose();$dialogBitmap.Dispose()
            }
        }
        $items+=@{name=$element.Current.Name;type=$element.Current.ControlType.ProgrammaticName;id=$element.Current.AutomationId;handle=$element.Current.NativeWindowHandle;rect=$element.Current.BoundingRectangle.ToString()}
    }
}
@{process_id=$targetId;actual_executable=$target[0].ExecutablePath;command_line=$target[0].CommandLine;action=$Action;keys=$Keys;elements=$items} | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 ($prefix+'.json')
$items | Where-Object { $_.name } | ConvertTo-Json -Depth 4
