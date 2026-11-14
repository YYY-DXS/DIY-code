$ErrorActionPreference = 'Stop'
# 修复/重建所有自制软件的桌面、开始菜单与开机启动快捷方式
# 用法：powershell -ExecutionPolicy Bypass -File .\fix-shortcuts.ps1

$repo = Split-Path -Parent $PSScriptRoot
$desktop = [Environment]::GetFolderPath('Desktop')
$programs = [Environment]::GetFolderPath('Programs')
$startup = [Environment]::GetFolderPath('Startup')
$startMenuFolder = Join-Path $programs '自制软件'
$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$shell = New-Object -ComObject WScript.Shell

New-Item -ItemType Directory -Force -Path $startMenuFolder | Out-Null

function Resolve-First([string[]]$Candidates) {
  foreach ($candidate in $Candidates) {
    if ($candidate -and (Test-Path -LiteralPath $candidate)) {
      return (Resolve-Path -LiteralPath $candidate).Path
    }
  }
  return $null
}

function Save-Shortcut([string]$Path, [string]$Target, [string]$Arguments, [string]$WorkDir, [string]$Icon, [string]$Description) {
  $shortcut = $shell.CreateShortcut($Path)
  $shortcut.TargetPath = $Target
  $shortcut.Arguments = if ($Arguments) { $Arguments } else { '' }
  if ($WorkDir) { $shortcut.WorkingDirectory = $WorkDir }
  if ($Icon) { $shortcut.IconLocation = $Icon }
  if ($Description) { $shortcut.Description = $Description }
  $shortcut.Save()
}

function Save-App([string]$Name, [string]$Target, [string]$Arguments, [string]$WorkDir, [string]$Icon, [string]$Description) {
  Save-Shortcut (Join-Path $desktop "$Name.lnk") $Target $Arguments $WorkDir $Icon $Description
  Save-Shortcut (Join-Path $startMenuFolder "$Name.lnk") $Target $Arguments $WorkDir $Icon $Description
  Write-Host ("  [{0}] {1}" -f $Name, $Target)
}

Write-Host "修复自制软件快捷方式..." -ForegroundColor Cyan

# 科技脉冲：优先仓库里的最新构建，其次桌面上已有的 TechPulse.exe
$techCandidates = @((Join-Path $repo 'apps\TechPulse\TechPulse.exe'))
$techCandidates += Get-ChildItem (Join-Path $desktop 'codex') -Recurse -Filter 'TechPulse.exe' -File -ErrorAction SilentlyContinue |
  Sort-Object LastWriteTime -Descending | ForEach-Object { $_.FullName }
$techPulse = Resolve-First $techCandidates
if ($techPulse) {
  $techDir = Split-Path -Parent $techPulse
  $techIcon = "$techPulse,0"
  Save-App '科技脉冲' $techPulse '' $techDir $techIcon '每日科技新闻与 DIY 项目雷达'
  Save-Shortcut (Join-Path $startup '科技脉冲.lnk') $techPulse '--background' $techDir $techIcon '登录后在后台启动科技脉冲日报服务'
} else {
  Write-Warning '找不到 TechPulse.exe，跳过科技脉冲快捷方式'
}

# 桌面小组件
$widgetScript = Join-Path $repo 'apps\desktop-widget\launch-widget.ps1'
if (Test-Path -LiteralPath $widgetScript) {
  $widgetArgs = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $widgetScript + '"'
  Save-App '桌面小组件' $powershell $widgetArgs (Split-Path -Parent $widgetScript) "$powershell,0" '天气 / DeepSeek 余额 / 系统资源浮窗'
} else {
  Write-Warning '找不到 desktop-widget\launch-widget.ps1'
}

# 电脑管家
$pcScript = Join-Path $repo 'apps\pc-toolkit\PcToolkitGui.ps1'
$pcIcon = "$powershell,0"
$pcIconPath = Join-Path $repo 'apps\pc-toolkit\assets\app.ico'
if (Test-Path -LiteralPath $pcIconPath) { $pcIcon = "$pcIconPath,0" }
if (Test-Path -LiteralPath $pcScript) {
  $pcArgs = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $pcScript + '"'
  Save-App '电脑管家' $powershell $pcArgs (Split-Path -Parent $pcScript) $pcIcon '系统体检 / 修复 / 清理 / 文件整理'
} else {
  Write-Warning '找不到 pc-toolkit\PcToolkitGui.ps1'
}

# Codex 环境搬运
$codexCmd = Join-Path $repo 'apps\codex-portable\codex-portable.cmd'
if (Test-Path -LiteralPath $codexCmd) {
  Save-App 'Codex 环境搬运' $codexCmd '' (Split-Path -Parent $codexCmd) "$env:SystemRoot\System32\cmd.exe,0" 'Codex 工作环境盘点 / 打包 / 还原'
} else {
  Write-Warning '找不到 codex-portable.cmd'
}

# RAW 转 JPG
$rawCandidates = @((Join-Path $repo 'apps\outputs\RAW转JPG.exe'))
$rawCandidates += Get-ChildItem (Join-Path $desktop 'codex') -Recurse -Filter 'RAW*.exe' -File -ErrorAction SilentlyContinue |
  Sort-Object LastWriteTime -Descending | ForEach-Object { $_.FullName }
$rawExe = Resolve-First $rawCandidates
if ($rawExe) {
  $rawIcon = "$rawExe,0"
  $rawIconPath = Join-Path $repo 'apps\raw-to-jpg\build\app.ico'
  if (Test-Path -LiteralPath $rawIconPath) { $rawIcon = "$rawIconPath,0" }
  Save-App 'RAW 转 JPG' $rawExe '' (Split-Path -Parent $rawExe) $rawIcon '批量 RAW / 图片转 JPG'
} else {
  Write-Warning '找不到 RAW 转 JPG 的 exe'
}

# DSH 插件脉冲面板
$pulseExe = Resolve-First @((Join-Path $env:LOCALAPPDATA 'DSHPluginInstaller\app-pulse\DSH-Plugin-Pulse.exe'))
if ($pulseExe) {
  Save-App 'DSH 插件脉冲面板' $pulseExe '' (Split-Path -Parent $pulseExe) "$pulseExe,0" '可视化安装 / 卸载 / 诊断 DSH 插件'
} else {
  $pulseScript = Join-Path $repo 'apps\dsh-plugin-pulse\start-pulse.ps1'
  if (Test-Path -LiteralPath $pulseScript) {
    $pulseArgs = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $pulseScript + '"'
    Save-App 'DSH 插件脉冲面板' $powershell $pulseArgs (Split-Path -Parent $pulseScript) "$powershell,0" '可视化安装 / 卸载 / 诊断 DSH 插件'
  } else {
    Write-Warning '找不到 DSH 插件脉冲面板'
  }
}

# DSH 插件安装面板（网页版）
$installerExe = Resolve-First @((Join-Path $env:LOCALAPPDATA 'DSHPluginInstaller\app\DSH-Plugin-Installer.exe'))
if ($installerExe) {
  Save-App 'DSH 插件安装面板' $installerExe '' (Split-Path -Parent $installerExe) "$installerExe,0" 'DSH 插件安装面板（网页版）'
} else {
  $installerScript = Join-Path $repo 'apps\dsh-plugin-pulse\start.ps1'
  if (Test-Path -LiteralPath $installerScript) {
    $installerArgs = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $installerScript + '"'
    Save-App 'DSH 插件安装面板' $powershell $installerArgs (Split-Path -Parent $installerScript) "$powershell,0" 'DSH 插件安装面板（网页版）'
  } else {
    Write-Warning '找不到 DSH 插件安装面板'
  }
}

# DeepSeek Hub 面板
$hubExe = Join-Path $repo 'plugins\deepseek-hub\desktop\DeepSeekHubPanel.exe'
if (Test-Path -LiteralPath $hubExe) {
  Save-App 'DeepSeek Hub 面板' $hubExe '' (Split-Path -Parent $hubExe) "$hubExe,0" 'DeepSeek 会话同步与发布状态面板'
} else {
  Write-Warning '找不到 DeepSeekHubPanel.exe'
}

# Lumen 译
$lumenEntry = Join-Path $repo 'apps\lumen-translate\main.pyw'
$lumenPy = Resolve-First @(
  (Join-Path $env:USERPROFILE '.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\pythonw.exe'),
  (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe')
)
if ((Test-Path -LiteralPath $lumenEntry) -and $lumenPy) {
  $lumenArgs = '"' + $lumenEntry + '"'
  $lumenIcon = "$lumenPy,0"
  $lumenIconPath = Join-Path $repo 'apps\lumen-translate\assets\lumen.ico'
  if (Test-Path -LiteralPath $lumenIconPath) { $lumenIcon = "$lumenIconPath,0" }
  Save-App 'Lumen 译' $lumenPy $lumenArgs (Split-Path -Parent $lumenEntry) $lumenIcon '划词 / 截图翻译'
} else {
  Write-Warning '找不到 Lumen 译的入口或 pythonw'
}

# 汉化工具（命令行）
$hanhuaCmd = Join-Path $repo 'apps\hanhua-kit\run.cmd'
if (Test-Path -LiteralPath $hanhuaCmd) {
  Save-App '汉化工具' $hanhuaCmd '' (Split-Path -Parent $hanhuaCmd) "$env:SystemRoot\System32\cmd.exe,0" '通用软件汉化流水线（命令行）'
} else {
  Write-Warning '找不到 hanhua-kit\run.cmd'
}

# 清理旧的重复快捷方式
Remove-Item (Join-Path $desktop 'TechPulse.exe.lnk') -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $desktop 'Lumen Translate.lnk') -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $programs '电脑管家.lnk') -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $programs '科技脉冲.lnk') -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $programs 'Lumen Translate.lnk') -Force -ErrorAction SilentlyContinue

# 修复开机启动的 VBS（桌面小组件 / DeepSeek 同步桥）
if (Test-Path -LiteralPath $widgetScript) {
  $widgetVbs = @'
Dim sh
Set sh = CreateObject("WScript.Shell")
sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""__SCRIPT__""", 0, False
'@.Replace('__SCRIPT__', $widgetScript)
  Set-Content -LiteralPath (Join-Path $startup '桌面小组件.vbs') -Value $widgetVbs -Encoding ASCII
  Write-Host "  [桌面小组件.vbs] $widgetScript"
}

$bridgeServer = Join-Path $repo 'tools\deepseek_bridge\server.py'
$dshPython = Join-Path $env:USERPROFILE '.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
if ((Test-Path -LiteralPath $bridgeServer) -and (Test-Path -LiteralPath $dshPython)) {
  $bridgeVbs = @'
Dim fso, shell, python, backend
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
python = "__PYTHON__"
backend = "__BACKEND__"
If Not fso.FileExists(python) Then python = "python"
If Not fso.FileExists(backend) Then WScript.Quit
shell.Run """" & python & """ """ & backend & """", 0, False
'@.Replace('__PYTHON__', $dshPython).Replace('__BACKEND__', $bridgeServer)
  Set-Content -LiteralPath (Join-Path $startup 'DeepSeek同步桥.vbs') -Value $bridgeVbs -Encoding ASCII
  Write-Host "  [DeepSeek同步桥.vbs] $bridgeServer"
}

# 修复旧的“桌面美化启动器”开机项
$enhanceCandidates = @(
  (Join-Path $desktop 'codex\2026-10-23\new-chat\outputs\Start-DesktopEnhancements.ps1'),
  (Join-Path $repo 'codex\2026-10-23\new-chat\outputs\Start-DesktopEnhancements.ps1')
)
$enhance = Resolve-First $enhanceCandidates
if ($enhance) {
  $enhanceIcon = "$powershell,0"
  $rainmeter = 'C:\Program Files\Rainmeter\Rainmeter.exe'
  if (Test-Path -LiteralPath $rainmeter) { $enhanceIcon = "$rainmeter,0" }
  $enhanceArgs = '-NoLogo -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $enhance + '" -StartupMode'
  Save-Shortcut (Join-Path $startup '桌面美化启动器.lnk') $powershell $enhanceArgs (Split-Path -Parent $enhance) $enhanceIcon '登录后启动桌面美化组件'
  Write-Host "  [桌面美化启动器] $enhance"
}

Write-Host ""
Write-Host "完成。桌面与开始菜单「自制软件」文件夹已更新。" -ForegroundColor Green
