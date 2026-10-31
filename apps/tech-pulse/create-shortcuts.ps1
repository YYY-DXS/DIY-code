$ErrorActionPreference = "Stop"
$packageRoot = Join-Path (Split-Path -Parent $PSScriptRoot) "TechPulse"
$exePath = Join-Path $packageRoot "TechPulse.exe"
if (-not (Test-Path $exePath)) {
  throw "未找到 TechPulse.exe，请先运行 npm run build:exe。"
}

$desktop = [Environment]::GetFolderPath("Desktop")
$startup = [Environment]::GetFolderPath("Startup")
$shell = New-Object -ComObject WScript.Shell

$desktopShortcut = $shell.CreateShortcut((Join-Path $desktop "科技脉冲.lnk"))
$desktopShortcut.TargetPath = $exePath
$desktopShortcut.WorkingDirectory = $packageRoot
$desktopShortcut.IconLocation = "$exePath,0"
$desktopShortcut.Description = "打开每日科技新闻与 DIY 项目雷达"
$desktopShortcut.Save()

$startupShortcut = $shell.CreateShortcut((Join-Path $startup "科技脉冲.lnk"))
$startupShortcut.TargetPath = $exePath
$startupShortcut.Arguments = "--background"
$startupShortcut.WorkingDirectory = $packageRoot
$startupShortcut.IconLocation = "$exePath,0"
$startupShortcut.Description = "登录后在后台启动科技脉冲日报服务"
$startupShortcut.Save()

Write-Output "桌面快捷方式：$(Join-Path $desktop '科技脉冲.lnk')"
Write-Output "开机启动快捷方式：$(Join-Path $startup '科技脉冲.lnk')"
