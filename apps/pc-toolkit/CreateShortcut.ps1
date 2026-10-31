<#
    在桌面（和开始菜单）创建「电脑管家」快捷方式。
    注意：文件名故意用英文，因为 .bat 里写中文文件名容易因为编码出问题。
    想自己改名字，改下面 $Name 就行。
#>

[CmdletBinding()]
param(
    # 只建到指定目录（默认：桌面 + 开始菜单）
    [string]$TargetDir,
    # 不建开始菜单快捷方式
    [switch]$NoStartMenu,
    [string]$Name = '电脑管家'
)

$ErrorActionPreference = 'Continue'

$root = $PSScriptRoot
if (-not $root) { $root = (Get-Location).ProviderPath }

$modulePath = Join-Path $root 'modules\Shortcut.ps1'
if (-not (Test-Path -LiteralPath $modulePath)) {
    Write-Host "找不到模块文件：$modulePath" -ForegroundColor Red
    return
}
. $modulePath

Write-Host ''
Write-Host '正在创建「电脑管家」快捷方式...' -ForegroundColor Cyan

$params = @{ ToolRoot = $root; Name = $Name }
if ($TargetDir) { $params.TargetDir = $TargetDir }
if (-not $NoStartMenu -and -not $TargetDir) { $params.IncludeStartMenu = $true }

$res = New-ToolkitShortcut @params

foreach ($p in $res.Made) {
    Write-Host ("  已创建：" + $p) -ForegroundColor Green
    $info = Test-ToolkitShortcut -LnkPath $p
    if ($info) {
        Write-Host ("     启动程序：" + $info.Target) -ForegroundColor DarkGray
        Write-Host ("     图标：" + $info.IconLocation) -ForegroundColor DarkGray
    }
}
foreach ($f in $res.Failed) {
    Write-Host ("  失败：" + $f) -ForegroundColor Yellow
}

Write-Host ''
if ($res.Ok) {
    Write-Host '完成！以后从桌面双击「电脑管家」就能打开窗口（不会弹黑框）。' -ForegroundColor Cyan
    Write-Host '想删掉：直接删除桌面那个图标就行，不影响工具本身。'
    if ($res.Failed.Count -gt 0) {
        Write-Host ''
        Write-Host '开始菜单那一个没建成功也没关系，桌面能用的就够了。' -ForegroundColor DarkGray
    }
} else {
    if ($res.Message) { Write-Host $res.Message -ForegroundColor Yellow }
    Write-Host '如果桌面建不了，可以直接双击 启动.bat 打开窗口，效果一样。' -ForegroundColor Cyan
}
Write-Host ''
