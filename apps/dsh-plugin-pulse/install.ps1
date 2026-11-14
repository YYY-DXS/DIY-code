# 安装 DSH 插件面板（网页版 + 原生脉冲版）到 %LOCALAPPDATA%，并创建两个桌面快捷方式
$ErrorActionPreference = 'Stop'
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ws = New-Object -ComObject WScript.Shell
$desk = [Environment]::GetFolderPath('Desktop')

function Find-Src($name) {
    foreach ($cand in @((Join-Path $dir $name), (Join-Path $dir "dist\$name"), (Join-Path $dir "release\$name"))) {
        if (Test-Path (Join-Path $cand "$name.exe")) { return $cand }
    }
    return $null
}

function Install-App($name, $appName, $lnkName, $desc) {
    $src = Find-Src $name
    if (-not $src) { Write-Warning "跳过 $name：找不到可安装的目录（先运行 build.ps1 或解压绿色包）"; return }
    $app = Join-Path $env:LOCALAPPDATA "DSHPluginInstaller\$appName"
    if (Test-Path $app) { Remove-Item $app -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $app | Out-Null
    Copy-Item (Join-Path $src "*") $app -Recurse -Force
    $exe = Join-Path $app "$name.exe"
    $lnk = $ws.CreateShortcut((Join-Path $desk $lnkName))
    $lnk.TargetPath = $exe
    $lnk.WorkingDirectory = $app
    $lnk.IconLocation = "$exe,0"
    $lnk.Description = $desc
    $lnk.Save()
    Write-Host "已安装：$app"
    Write-Host "桌面快捷方式：$lnkName"
}

# 原生脉冲版（推荐）
Install-App "DSH-Plugin-Pulse" "app-pulse" "DSH 插件脉冲面板.lnk" "DSH 插件脉冲面板 - 原生桌面窗口 · 插件库 · 一键安装 · 兼容性诊断"
# 网页版（备用）
Install-App "DSH-Plugin-Installer" "app" "DSH 插件安装面板（网页版）.lnk" "DSH 插件安装面板 - 本地网页版"

Write-Host ""
Write-Host "完成。双击「DSH 插件脉冲面板」即可打开（原生窗口，不启动浏览器）。"
