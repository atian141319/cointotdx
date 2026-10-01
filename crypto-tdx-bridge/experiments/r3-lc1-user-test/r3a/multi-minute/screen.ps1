Add-Type -AssemblyName System.Drawing
Add-Type -TypeDefinition 'using System;using System.Runtime.InteropServices;public class MScreen { [DllImport("user32.dll")] public static extern bool SetProcessDPIAware(); [StructLayout(LayoutKind.Sequential)] public struct R{public int L,T,Ri,B;} [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h,out R r);}'
[MScreen]::SetProcessDPIAware() | Out-Null
$msProcess=Get-Process tdxw
$msRect=New-Object MScreen+R
[MScreen]::GetWindowRect($msProcess.MainWindowHandle,[ref]$msRect) | Out-Null
$msBitmap=New-Object Drawing.Bitmap(($msRect.Ri-$msRect.L),($msRect.B-$msRect.T))
$msGraphics=[Drawing.Graphics]::FromImage($msBitmap)
$msGraphics.CopyFromScreen($msRect.L,$msRect.T,0,0,$msBitmap.Size)
$msBitmap.Save('D:\project\cointotdx\crypto-tdx-bridge\experiments\r3-lc1-user-test\r3a\multi-minute\evidence\physical-login.png')
$msGraphics.Dispose();$msBitmap.Dispose()
$msRect
