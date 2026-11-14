# Dev helper: launch Lumen, grab a PNG, then close it.
#   powershell -ExecutionPolicy Bypass -File tools\shoot.ps1 -Demo -Out .dev\main.png
#
# NOTE: this file must stay ASCII-only. Windows PowerShell 5.1 reads .ps1 files
# using the OEM code page, so non-ASCII characters inside comments/strings can be
# mis-decoded and break the parser.
param(
    [string]$Out = ".dev\main.png",
    [string]$Py = "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe",
    [int]$Wait = 6,
    [switch]$Demo,
    [string]$Crop = "",
    [int]$Zoom = 2,
    [string]$Entry = "main.pyw",
    [ValidateSet("largest", "dialog")][string]$Target = "largest",
    [switch]$List,
    # Grab the rect the app itself reports as "[region] WxH+X+Y" in .dev/app.log.
    # Far more reliable than guessing which window belongs to the process.
    [switch]$RegionFromLog,
    # print = PrintWindow (works for occluded framed windows)
    # screen = CopyFromScreen (required for borderless popups)
    [ValidateSet("print", "screen")][string]$Mode = "print"
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class WinCap {
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr param);
    public delegate bool EnumProc(IntPtr hwnd, IntPtr param);

    // smallest=0 -> biggest visible window; smallest=1 -> smallest visible popup
    public static IntPtr FindByPid(uint pid, int smallest) {
        IntPtr found = IntPtr.Zero;
        long best = -1;
        EnumWindows(delegate(IntPtr h, IntPtr p) {
            uint owner;
            GetWindowThreadProcessId(h, out owner);
            if (owner != pid || !IsWindowVisible(h)) return true;
            RECT r;
            GetWindowRect(h, out r);
            long w = r.Right - r.Left;
            long ht = r.Bottom - r.Top;
            long area = w * ht;
            if (w < 200 || ht < 150) return true;   // skip hidden helper windows
            if (smallest == 1) { if (best >= 0 && area >= best) return true; }
            else { if (best >= 0 && area <= best) return true; }
            best = area;
            found = h;
            return true;
        }, IntPtr.Zero);
        return found;
    }

    public static string[] ListWindows(uint pid) {
        System.Collections.Generic.List<string> rows = new System.Collections.Generic.List<string>();
        EnumWindows(delegate(IntPtr h, IntPtr p) {
            uint owner;
            GetWindowThreadProcessId(h, out owner);
            if (owner != pid || !IsWindowVisible(h)) return true;
            RECT r;
            GetWindowRect(h, out r);
            rows.Add(string.Format("{0},{1},{2},{3} | {4}", r.Left, r.Top, r.Right - r.Left, r.Bottom - r.Top, h));
            return true;
        }, IntPtr.Zero);
        return rows.ToArray();
    }

    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
}
"@

$root = Split-Path -Parent $PSScriptRoot
$outPath = Join-Path $root $Out
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $outPath) | Out-Null

# -Demo only turns demo data on; it never overrides an env var the caller already set
if ($Demo -and -not $env:LUMEN_DEMO) { $env:LUMEN_DEMO = "1" }

$entry = Join-Path $root $Entry
$logPath = Join-Path $root ".dev\app.log"

# main.pyw has a single-instance guard (two instances would fight over the global
# hotkeys), so clear out any stale instance of THIS app before launching.
# Matches on the full path of this repo's entry script only.
Get-CimInstance Win32_Process -Filter "Name='python.exe' or Name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine.Contains($entry) } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 400

[void][WinCap]::SetProcessDPIAware()
# Start-Process does not quote arguments for you, and this path has spaces
$proc = Start-Process -FilePath $Py -ArgumentList ('"{0}"' -f $entry) -PassThru -RedirectStandardError $logPath

function Save-Region([int]$x, [int]$y, [int]$w, [int]$h, [string]$path) {
    $bmp = New-Object System.Drawing.Bitmap($w, $h)
    $gfx = [System.Drawing.Graphics]::FromImage($bmp)
    $gfx.CopyFromScreen($x, $y, 0, 0, (New-Object System.Drawing.Size($w, $h)))
    $gfx.Dispose()
    $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    $bmp.Dispose()
}

if ($RegionFromLog) {
    Start-Sleep -Seconds $Wait
    $hit = $null
    if (Test-Path $logPath) {
        $hit = Select-String -Path $logPath -Pattern '\[region\] (\d+)x(\d+)\+(-?\d+)\+(-?\d+)' | Select-Object -Last 1
    }
    if (-not $hit) {
        if (-not $proc.HasExited) { $proc.Kill() }
        throw "no [region] line found in app.log"
    }
    $rw = [int]$hit.Matches[0].Groups[1].Value
    $rh = [int]$hit.Matches[0].Groups[2].Value
    $rx = [int]$hit.Matches[0].Groups[3].Value
    $ry = [int]$hit.Matches[0].Groups[4].Value
    Write-Output ("region {0},{1} {2}x{3}" -f $rx, $ry, $rw, $rh)
    Save-Region $rx $ry $rw $rh $outPath
    Start-Sleep -Milliseconds 200
    if (-not $proc.HasExited) { $proc.Kill() }
    Write-Output ("saved: {0}" -f $outPath)
    Get-Content $logPath -ErrorAction SilentlyContinue | Select-Object -Last 6
    return
}

[IntPtr]$hwnd = [IntPtr]::Zero
for ($i = 0; $i -lt $Wait; $i++) {
    Start-Sleep -Seconds 1
    if ($proc.HasExited) { throw "process exited early (startup exception?)" }
    # keep polling to the deadline: a dialog can show up after the main window
    # NOTE: do not name this $mode - PowerShell variables are case-insensitive and
    # it would collide with the $Mode parameter (which has a ValidateSet).
    $dialogPick = 0
    if ($Target -eq "dialog") { $dialogPick = 1 }
    [IntPtr]$candidate = [WinCap]::FindByPid([uint32]$proc.Id, $dialogPick)
    if ([int64]$candidate -ne 0) { $hwnd = $candidate }
}
if ($hwnd -eq [IntPtr]::Zero) {
    if (-not $proc.HasExited) { $proc.Kill() }
    throw "main window not found for PID $($proc.Id)"
}

if ($List) {
    Write-Output "--- windows of PID $($proc.Id) ---"
    [WinCap]::ListWindows([uint32]$proc.Id) | ForEach-Object { Write-Output $_ }
    if (-not $proc.HasExited) { $proc.Kill() }
    return
}

[void][WinCap]::SetForegroundWindow($hwnd)
Start-Sleep -Milliseconds 600

$rect = New-Object WinCap+RECT
[void][WinCap]::GetWindowRect($hwnd, [ref]$rect)
$w = $rect.Right - $rect.Left
$h = $rect.Bottom - $rect.Top
Write-Output ("target hwnd={0} rect={1},{2} {3}x{4}" -f $hwnd, $rect.Left, $rect.Top, $w, $h)
if ($w -le 0 -or $h -le 0) {
    if (-not $proc.HasExited) { $proc.Kill() }
    throw "bad window rect: $($rect.Left),$($rect.Top),$($rect.Right),$($rect.Bottom)"
}

$bmp = New-Object System.Drawing.Bitmap($w, $h)
$gfx = [System.Drawing.Graphics]::FromImage($bmp)
if ($Mode -eq "screen") {
    $gfx.CopyFromScreen($rect.Left, $rect.Top, 0, 0, (New-Object System.Drawing.Size($w, $h)))
} else {
    $hdc = $gfx.GetHdc()
    # 2 = PW_RENDERFULLCONTENT, keeps the dark native title bar
    [void][WinCap]::PrintWindow($hwnd, $hdc, 2)
    $gfx.ReleaseHdc($hdc)
}
$gfx.Dispose()
$bmp.Save($outPath, [System.Drawing.Imaging.ImageFormat]::Png)

if ($Crop) {
    $parts = $Crop.Split(",") | ForEach-Object { [int]$_ }
    $src = New-Object System.Drawing.Rectangle($parts[0], $parts[1], $parts[2], $parts[3])
    $cropBmp = New-Object System.Drawing.Bitmap(($parts[2] * $Zoom), ($parts[3] * $Zoom))
    $cg = [System.Drawing.Graphics]::FromImage($cropBmp)
    $cg.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::NearestNeighbor
    $cg.DrawImage($bmp, (New-Object System.Drawing.Rectangle(0, 0, ($parts[2] * $Zoom), ($parts[3] * $Zoom))), $src, [System.Drawing.GraphicsUnit]::Pixel)
    $cg.Dispose()
    $cropPath = [System.IO.Path]::Combine(
        [System.IO.Path]::GetDirectoryName($outPath),
        [System.IO.Path]::GetFileNameWithoutExtension($outPath) + "-crop.png"
    )
    $cropBmp.Save($cropPath, [System.Drawing.Imaging.ImageFormat]::Png)
    $cropBmp.Dispose()
    Write-Output ("crop:  {0}" -f $cropPath)
}

$bmp.Dispose()

Start-Sleep -Milliseconds 300
if (-not $proc.HasExited) { $proc.Kill() }
Write-Output ("saved: {0} ({1}x{2})" -f $outPath, $w, $h)
if ((Test-Path $logPath) -and (Get-Item $logPath).Length -gt 0) {
    Write-Output "--- stderr ---"
    Get-Content $logPath | Select-Object -Last 20
}
