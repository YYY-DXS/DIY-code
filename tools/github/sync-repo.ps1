<#
  从 GitHub 拉取仓库（国内直连被拦时自动走代理）。

  用法：
    双击「拉取仓库.cmd」，按提示输入 owner/repo
    或者命令行：powershell -File sync-repo.ps1 -Repo octocat/Hello-World

  已存在同名目录就执行拉取更新，否则克隆一份新的。
#>

param(
    [string]$Repo,
    [string]$Dest,
    [string]$Proxy = 'https://gh-proxy.com/'
)

# 用 Continue：git 的进度信息走 stderr，Stop 会把它当成致命错误中断脚本
$ErrorActionPreference = 'Continue'

# 这台机器上的 git 需要显式指定 helper 目录，否则 clone/fetch 会报
# "remote-https is not a git command"
$gitRoot = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git'
$gitBin = Join-Path $gitRoot 'mingw64\bin'
if (Test-Path -LiteralPath $gitBin) {
    $env:GIT_EXEC_PATH = $gitBin
    if ($env:PATH -notlike "*$gitBin*") { $env:PATH = "$gitBin;$env:PATH" }
}
$sslArgs = @('-c', 'http.sslBackend=openssl')

if (-not $Repo) {
    $Repo = Read-Host "要拉取的仓库（形如 owner/repo，或完整网址）"
}
if (-not $Repo) { Write-Host "没有输入仓库，退出。"; exit 1 }

# 把各种写法统一成 owner/repo
$slug = $Repo.Trim()
$slug = $slug -replace '^https?://github\.com/', ''
$slug = $slug -replace '^git@github\.com:', ''
$slug = $slug -replace '\.git$', ''
if ($slug -notmatch '^[\w.\-]+/[\w.\-]+$') {
    Write-Host "看不懂这个仓库写法：$Repo" -ForegroundColor Red
    Write-Host "正确写法举例：octocat/Hello-World"
    Read-Host "按回车退出"
    exit 1
}

$name = ($slug -split '/')[-1]
if (-not $Dest) { $Dest = Join-Path (Get-Location) $name }

$proxyUrl = "${Proxy}https://github.com/$slug.git"
$directUrl = "https://github.com/$slug.git"

Write-Host ""
Write-Host "仓库：$slug"
Write-Host "目录：$Dest"
Write-Host "通道：代理（$Proxy）"
Write-Host ""

if (Test-Path -LiteralPath (Join-Path $Dest '.git')) {
    Write-Host "本地已有仓库，执行更新..." -ForegroundColor Cyan
    & git -C $Dest @sslArgs pull --ff-only 2>&1 | ForEach-Object { Write-Host "  $_" }
} else {
    Write-Host "开始克隆..." -ForegroundColor Cyan
    & git @sslArgs clone $proxyUrl $Dest 2>&1 | ForEach-Object { Write-Host "  $_" }
}

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "完成：$Dest" -ForegroundColor Green
    if (Test-Path -LiteralPath (Join-Path $Dest '.git')) {
        & git -C $Dest @sslArgs log --oneline -1 2>&1 | ForEach-Object { Write-Host "  最新提交：$_" }
    }
} else {
    Write-Host ""
    Write-Host "失败了。可以试试把代理换成 https://gitclone.com/github.com/ 前缀，" -ForegroundColor Yellow
    Write-Host "或者检查网络。" -ForegroundColor Yellow
}
Write-Host ""
Read-Host "按回车关闭"
