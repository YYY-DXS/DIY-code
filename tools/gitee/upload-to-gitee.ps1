<#
  把当前项目提交并推送到码云（Gitee）。

  为什么需要你自己运行：这台机器上只有你的账号能登录码云，
  Codex 这边没有网络权限，也不该接触你的密码。

  运行方式：双击同目录下的「上传到码云.cmd」
#>

$ErrorActionPreference = 'Continue'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$logPath = Join-Path $PSScriptRoot 'push-log.txt'
$branch = 'main'

Set-Location $repoRoot

function Write-Log {
    param([string]$Text)
    $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Add-Content -LiteralPath $logPath -Value "[$stamp] $Text" -Encoding UTF8
}

function Invoke-Step {
    param([string]$Title, [scriptblock]$Action)
    Write-Host ""
    Write-Host "== $Title ==" -ForegroundColor Cyan
    Write-Log "== $Title =="
    $lines = & $Action 2>&1
    $code = $LASTEXITCODE
    foreach ($line in $lines) {
        Write-Host $line
        Add-Content -LiteralPath $logPath -Value ("    " + $line) -Encoding UTF8
    }
    return $code
}

Write-Host "=== 上传项目到码云 (Gitee) ===" -ForegroundColor Green
Write-Host "项目目录：$repoRoot"
Write-Log "=== 开始：$repoRoot ==="

# --- 环境检查 -------------------------------------------------------------

& git --version *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "找不到 git，请先安装 Git for Windows。" -ForegroundColor Red
    Write-Log "错误：找不到 git"
    Read-Host "按回车退出"
    exit 1
}

# --- 收集信息 -------------------------------------------------------------

$user = Read-Host "你的码云用户名（登录名，不是昵称）"
if (-not $user) {
    Write-Host "用户名不能为空。" -ForegroundColor Red
    Read-Host "按回车退出"
    exit 1
}
$repoName = Read-Host "仓库名（在码云上建的那个，直接回车用 new-project）"
if (-not $repoName) { $repoName = 'new-project' }
$displayName = Read-Host "提交记录里显示的名字（直接回车用 $user）"
if (-not $displayName) { $displayName = $user }
$email = Read-Host "邮箱（直接回车用 $user@users.noreply.gitee.com）"
if (-not $email) { $email = "$user@users.noreply.gitee.com" }

$remoteUrl = "https://gitee.com/$user/$repoName.git"
Write-Host ""
Write-Host "将推送到：$remoteUrl" -ForegroundColor Yellow
$confirm = Read-Host "确认继续？(Y/n)"
if ($confirm -and $confirm.ToLower() -ne 'y') {
    Write-Host "已取消。"
    exit 0
}
Write-Log "用户=$user 仓库=$repoName 远端=$remoteUrl"

# --- 提交 -----------------------------------------------------------------

Invoke-Step "配置提交身份" {
    git config user.name $displayName
    git config user.email $email
    git config user.name
    git config user.email
} | Out-Null

Invoke-Step "暂存文件" { git add -A } | Out-Null

$staged = git diff --cached --name-only
if ($staged) {
    Invoke-Step "创建提交（共 $($staged.Count) 个文件）" {
        git commit -m "初始提交：DeepSeek 同步桥与项目工具"
    } | Out-Null
} else {
    Write-Host "没有新文件需要提交。" -ForegroundColor DarkGray
    Write-Log "无新文件，跳过提交"
}

# --- 远端与推送 -----------------------------------------------------------

& git remote get-url origin *> $null
if ($LASTEXITCODE -eq 0) {
    Invoke-Step "更新远端地址" { git remote set-url origin $remoteUrl } | Out-Null
} else {
    Invoke-Step "添加远端地址" { git remote add origin $remoteUrl } | Out-Null
}

Invoke-Step "重命名分支为 $branch" { git branch -M $branch } | Out-Null

Write-Host ""
Write-Host "接下来会要求登录码云（弹出窗口或命令行提示），输入账号密码即可。" -ForegroundColor Yellow
Write-Host "如果提示仓库不存在，说明还没在码云上建仓库，或者仓库名填错了。" -ForegroundColor Yellow
Write-Host ""

$pushCode = Invoke-Step "推送到码云" { git push -u origin $branch }

Write-Host ""
if ($pushCode -eq 0) {
    Write-Host "推送成功！" -ForegroundColor Green
    Write-Host "仓库地址：$remoteUrl"
    Write-Log "推送成功：$remoteUrl"
} else {
    Write-Host "推送失败（退出码 $pushCode）。" -ForegroundColor Red
    Write-Host "把窗口里的报错，或者 tools\gitee\push-log.txt 发给 Codex 即可。" -ForegroundColor Yellow
    Write-Log "推送失败，退出码 $pushCode"
}

Write-Host ""
Write-Host "日志文件：$logPath"
Read-Host "按回车关闭窗口"
