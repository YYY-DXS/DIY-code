<#
  一键同步：拉取远端 → 提交本地改动 → 推送。

  双击同目录的「同步仓库.cmd」运行，也可以加提交说明：
    powershell -File 同步仓库.ps1 -Message "补充飞艇模型资料"
#>

param([string]$Message)

$ErrorActionPreference = 'Continue'
$repoRoot = Split-Path -Parent $PSScriptRoot
$keyDir = Join-Path (Split-Path -Parent $repoRoot) '.keys'
$key = Join-Path $keyDir 'id_ed25519'
$knownHosts = Join-Path $keyDir 'known_hosts'

# 这台机器上的 git 需要显式指定 helper 目录，否则网络操作会失败
$gitBin = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\mingw64\bin'
if (Test-Path -LiteralPath $gitBin) {
    $env:GIT_EXEC_PATH = $gitBin
    if ($env:PATH -notlike "*$gitBin*") { $env:PATH = "$gitBin;$env:PATH" }
}

if (Test-Path -LiteralPath $key) {
    $env:GIT_SSH_COMMAND = "ssh -i `"$key`" -o UserKnownHostsFile=`"$knownHosts`" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
}

Set-Location $repoRoot

Write-Host "1/4 拉取远端更新" -ForegroundColor Cyan
git pull --ff-only 2>&1 | ForEach-Object { Write-Host "  $_" }

Write-Host "2/4 检查本地改动" -ForegroundColor Cyan
git add -A
$staged = git diff --cached --name-only
if ($staged) {
    if (-not $Message) { $Message = "同步 " + (Get-Date -Format 'yyyy-MM-dd HH:mm') }
    Write-Host "  发现 $($staged.Count) 个文件有改动："
    $staged | Select-Object -First 10 | ForEach-Object { Write-Host "    $_" }
} else {
    Write-Host "  没有需要提交的改动"
}

Write-Host "3/4 隐私检查" -ForegroundColor Cyan
$py = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path -LiteralPath $py)) { $py = 'python' }
$checker = Join-Path $repoRoot 'tools\security\privacy_check.py'
if (Test-Path -LiteralPath $checker) {
    $env:PYTHONIOENCODING = 'utf-8'
    & $py $checker
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "隐私检查没通过，已中止。把上面列出的内容处理掉再同步。" -ForegroundColor Red
        Write-Host "（确认要上传就手动 git commit 后 git push，检查只拦这个自动流程）" -ForegroundColor DarkGray
        Write-Host ""
        Read-Host "按回车关闭"
        exit 1
    }
} else {
    Write-Host "  找不到检查脚本，跳过。" -ForegroundColor Yellow
}

if ($staged) {
    git commit -m $Message 2>&1 | Select-Object -First 2 | ForEach-Object { Write-Host "  $_" }
}

Write-Host "4/4 推送到 GitHub" -ForegroundColor Cyan
git push 2>&1 | ForEach-Object { Write-Host "  $_" }

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "同步完成。" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "推送可能失败了，把上面的信息发给 Codex。" -ForegroundColor Yellow
}
Write-Host ""
Read-Host "按回车关闭"
