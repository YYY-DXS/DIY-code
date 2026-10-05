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

robocopy $source $dest /E /XF .gitkeep /XF README.md /NFL /NDL /NJH /NJS /NP | Out-Null
Copy-Item -LiteralPath (Join-Path $source 'README.md') -Destination (Join-Path $dest '项目索引.md') -Force

# 清掉早期同步留下的两个多余文件（只动这两个，别的不碰）
foreach ($stale in @('README.md', '.gitkeep')) {
    $path = Join-Path $dest $stale
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -ErrorAction SilentlyContinue }
}

$count = (Get-ChildItem -LiteralPath $dest -Recurse -File | Measure-Object).Count
Write-Host "同步完成，目标文件夹现在有 $count 个文件。" -ForegroundColor Green
Write-Host "（只新增和覆盖，不会删除桌面上已有的东西）"
Write-Host ""
Read-Host "按回车关闭"
