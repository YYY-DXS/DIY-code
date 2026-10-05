<#
  把项目文档同步一份到桌面的「DIY项目」文件夹。
  只复制、不删除：桌面上的其他文件原样保留。
#>

$ErrorActionPreference = 'Continue'

$repoRoot = Split-Path -Parent $PSScriptRoot
$source = Join-Path $repoRoot 'projects'
$dest = Join-Path $env:USERPROFILE 'Desktop\DIY项目'

if (-not (Test-Path -LiteralPath $source)) {
    Write-Host "找不到项目目录：$source" -ForegroundColor Red
    Read-Host "按回车退出"
    exit 1
}

if (-not (Test-Path -LiteralPath $dest)) {
    New-Item -ItemType Directory -Path $dest -Force | Out-Null
}

Write-Host "从 $source" -ForegroundColor Cyan
Write-Host "到 $dest" -ForegroundColor Cyan
Write-Host ""

# 注意 1：不能用 /XF README.md —— 子目录里的 README.md 是有用内容
# 注意 2：必须限制重试次数，否则遇到打不开的文件会无限重试（看起来像卡死）
robocopy $source $dest /E /XF .gitkeep /R:2 /W:2 /NFL /NDL /NJH /NJS /NP | Out-Null
Copy-Item -LiteralPath (Join-Path $source 'README.md') -Destination (Join-Path $dest '项目索引.md') -Force
foreach ($ext in @('html', 'docx')) {
    $from = Join-Path $source "README.$ext"
    if (Test-Path -LiteralPath $from) {
        Copy-Item -LiteralPath $from -Destination (Join-Path $dest "项目索引.$ext") -Force
    }
}

# 清掉根目录下多余的文件（只动这几个，别的不碰）
foreach ($stale in @('README.md', 'README.html', 'README.docx', '.gitkeep')) {
    $path = Join-Path $dest $stale
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -ErrorAction SilentlyContinue }
}

$count = (Get-ChildItem -LiteralPath $dest -Recurse -File | Measure-Object).Count
Write-Host "同步完成，目标文件夹现在有 $count 个文件。" -ForegroundColor Green
Write-Host "（只新增和覆盖，不会删除桌面上已有的东西）"
Write-Host ""
Read-Host "按回车关闭"
