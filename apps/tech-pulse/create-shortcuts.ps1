param([switch]$DryRun)

$ErrorActionPreference = "Stop"

$appRoot = $PSScriptRoot
# 发布包有两种形态：
#   1. TechPulse 文件夹里带编译好的 TechPulse.exe（release-readme 描述的方式）
#   2. 只有源码 + start.ps1（GitHub Release 里 apps/tech-pulse.zip 的方式）
$exeCandidates = @(
  (Join-Path $appRoot "TechPulse.exe"),
  (Join-Path (Split-Path -Parent $appRoot) "TechPulse\TechPulse.exe")
)
$exePath = $exeCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1

$desktop = [Environment]::GetFolderPath("Desktop")
$startup = [Environment]::GetFolderPath("Startup")
$shell = New-Object -ComObject WScript.Shell

$desktopShortcut = $shell.CreateShortcut((Join-Path $desktop "科技脉冲.lnk"))
$desktopShortcut.Description = "打开每日科技新闻与 DIY 项目雷达"

$startupShortcut = $shell.CreateShortcut((Join-Path $startup "科技脉冲.lnk"))
$startupShortcut.Description = "登录后在后台启动科技脉冲日报服务"

if ($exePath) {
  $packageRoot = Split-Path -Parent $exePath
  $desktopShortcut.TargetPath = $exePath
  $desktopShortcut.WorkingDirectory = $packageRoot
  $desktopShortcut.IconLocation = "$exePath,0"

  $startupShortcut.TargetPath = $exePath
  $startupShortcut.Arguments = "--background"
  $startupShortcut.WorkingDirectory = $packageRoot
  $startupShortcut.IconLocation = "$exePath,0"

  $mode = "TechPulse.exe（$exePath）"
} else {
  # 没有 exe 就退回 Node 源码启动方式：先确认 Node 可执行，再生成等价的快捷方式。
  $node = Get-Command node -ErrorAction SilentlyContinue
  if (-not $node) {
    throw @"
未找到 TechPulse.exe，也没有检测到 Node.js。

这个发行包是源码版，需要二选一：
  1. 安装 Node.js 20 或更高版本，然后重新运行本脚本；
  2. 在源码目录执行 npm install 与 npm run build:exe，生成 TechPulse.exe 后再运行本脚本。
"@
  }

  $powershell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
  if (-not (Test-Path -LiteralPath $powershell)) { $powershell = "powershell.exe" }

  $desktopShortcut.TargetPath = $powershell
  $desktopShortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$appRoot\start.ps1`""
  $desktopShortcut.WorkingDirectory = $appRoot
  $desktopShortcut.IconLocation = "$powershell,0"

  $startupShortcut.TargetPath = $node.Source
  $startupShortcut.Arguments = "server.mjs"
  $startupShortcut.WorkingDirectory = $appRoot
  $startupShortcut.WindowStyle = 7
  $startupShortcut.IconLocation = "$($node.Source),0"

  $mode = "Node.js（$($node.Source)）"
}

if ($DryRun) {
  Write-Output "启动方式：$mode"
  Write-Output "桌面快捷方式：$($desktopShortcut.TargetPath) $($desktopShortcut.Arguments)"
  Write-Output "开机启动快捷方式：$($startupShortcut.TargetPath) $($startupShortcut.Arguments)"
  return
}

$desktopShortcut.Save()
$startupShortcut.Save()

Write-Output "启动方式：$mode"
Write-Output "桌面快捷方式：$(Join-Path $desktop '科技脉冲.lnk')"
Write-Output "开机启动快捷方式：$(Join-Path $startup '科技脉冲.lnk')"
