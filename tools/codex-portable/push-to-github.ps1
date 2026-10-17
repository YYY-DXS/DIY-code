<#
  把 codex-portable 推到你的 GitHub 仓库。

  用法：
    双击「推到GitHub.cmd」
    或  powershell -ExecutionPolicy Bypass -File push-to-github.ps1 -Repo https://github.com/you/codex-portable.git

  凭据策略（按顺序）：
    1. 找到 Git Credential Manager → 弹浏览器登录，脚本不接触令牌
    2. 找不到 → 提示输入一次 Personal Access Token，只在内存和临时文件中存在，
       推送结束后立即清除，不写入 .git/config

  为什么需要 openssl 后端：Codex 自带的 git 用 schannel 时会报
  SEC_E_NO_CREDENTIALS，换成 openssl 才正常。
#>
param(
    [string]$Repo,
    [string]$User,
    [string]$Token,
    [string]$Branch = 'main'
)

$ErrorActionPreference = 'Continue'
Set-Location -LiteralPath $PSScriptRoot

function Fail($msg) { Write-Host ""; Write-Host $msg -ForegroundColor Red; Write-Host ""; Read-Host "按回车退出"; exit 1 }

# ---------------------------------------------------------------- git
$gitCmd = Get-Command git -ErrorAction SilentlyContinue
if (-not $gitCmd) {
    $candidates = @(
        (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe'),
        'C:\Program Files\Git\cmd\git.exe'
    )
    foreach ($c in $candidates) { if (Test-Path -LiteralPath $c) { $gitCmd = $c; break } }
}
if (-not $gitCmd) { Fail '找不到 git，请先安装 Git for Windows。' }
$gitExe = if ($gitCmd -is [string]) { $gitCmd } else { $gitCmd.Source }

$execPath = Join-Path (Split-Path (Split-Path $gitExe -Parent) -Parent) 'mingw64\libexec\git-core'
if (Test-Path -LiteralPath $execPath) { $env:GIT_EXEC_PATH = $execPath }
$sslArgs = @('-c', 'http.sslBackend=openssl')

if (-not (Test-Path (Join-Path $PSScriptRoot '.git'))) {
    Fail '当前目录不是 git 仓库（缺 .git），请从仓库目录运行本脚本。'
}

# ---------------------------------------------------------------- 目标
if (-not $Repo) {
    Write-Host '先在 GitHub 新建一个空仓库（建议私有，不要勾选 README 初始化）。' -ForegroundColor Cyan
    $Repo = Read-Host '仓库地址（如 https://github.com/you/codex-portable.git）'
}
$Repo = $Repo.Trim()
if ($Repo -match '^[\w.\-]+$') {
    # 只给了仓库名，补上用户名
    if (-not $User) { $User = Read-Host 'GitHub 用户名' }
    $Repo = "https://github.com/$User/$Repo"
} elseif ($Repo -notmatch '^(https://|git@)') {
    $Repo = 'https://github.com/' + $Repo.Trim('/')
}
if ($Repo -notmatch '\.git$') { $Repo = $Repo + '.git' }

if (-not $User) {
    $guess = if ($Repo -match 'github\.com[/:]([^/]+)/') { $Matches[1] } else { '' }
    $tip = if ($guess) { "（回车用 $guess）" } else { '' }
    $User = Read-Host ("GitHub 用户名" + $tip)
    if (-not $User) { $User = $guess }
}
if ($User) {
    & $gitExe config user.name $User
    & $gitExe config user.email ($User + '@users.noreply.github.com')
}

& $gitExe remote get-url origin *> $null
if ($LASTEXITCODE -eq 0) { & $gitExe remote set-url origin $Repo } else { & $gitExe remote add origin $Repo }

$count = (& $gitExe rev-list --count HEAD 2>$null)
if ($count -eq '1') {
    Write-Host '更新首条提交的作者信息...' -ForegroundColor DarkGray
    & $gitExe commit --amend --no-edit --reset-author | Out-Null
}

Write-Host ""
Write-Host "推送目标: $Repo" -ForegroundColor Cyan

# ---------------------------------------------------------------- 凭据
$gcm = Get-Command git-credential-manager -ErrorAction SilentlyContinue
if (-not $gcm) {
    foreach ($c in @(
        'C:\Program Files\Git\mingw64\bin\git-credential-manager.exe',
        'C:\Program Files (x86)\Git Credential Manager\git-credential-manager.exe')) {
        if (Test-Path -LiteralPath $c) { $gcm = $c; break }
    }
}

$askpassFile = $null
$code = 1
try {
    if ($gcm) {
        Write-Host '使用 Git Credential Manager（会弹出浏览器登录）' -ForegroundColor DarkGray
        $credArgs = @()
    } else {
        if (-not $Token) {
            Write-Host ''
            Write-Host '本机没有 Git Credential Manager，需要一次 Personal Access Token。' -ForegroundColor Yellow
            Write-Host 'GitHub → Settings → Developer settings → Personal access tokens，勾选 repo 权限。' -ForegroundColor DarkGray
            Write-Host '令牌只用于本次推送，不会保存到仓库配置。' -ForegroundColor DarkGray
            $sec = Read-Host '粘贴 Token（不显示）' -AsSecureString
            $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
            try { $Token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
            finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
        }
        if ([string]::IsNullOrWhiteSpace($Token)) { Fail '没有令牌，无法推送。' }

        $askpassFile = Join-Path ([System.IO.Path]::GetTempPath()) ('cp-askpass-' + [guid]::NewGuid().ToString('N') + '.cmd')
        @'
@echo off
echo %~1 | findstr /i "username" >nul
if %errorlevel%==0 (echo %GP_USER%) else (echo %GP_TOKEN%)
'@ | Set-Content -LiteralPath $askpassFile -Encoding ASCII
        $env:GIT_ASKPASS = $askpassFile
        $env:GP_USER = $User
        $env:GP_TOKEN = $Token
        $env:GIT_TERMINAL_PROMPT = '0'
        $credArgs = @('-c', 'credential.helper=')
    }

    # 有令牌时顺手把空仓库建出来（已存在就跳过）
    if (-not $gcm -and $Repo -match 'github\.com/([^/]+)/([^/]+?)(\.git)?$') {
        $owner = $Matches[1]
        $repoName = $Matches[2]
        $body = @{
            name        = $repoName
            private     = $true
            description = 'Codex 数据整理与迁移工具：分类盘点、打包、还原、加密'
        } | ConvertTo-Json
        try {
            $null = Invoke-RestMethod -Uri 'https://api.github.com/user/repos' -Method Post `
                -Headers @{ Authorization = "token $Token"; 'User-Agent' = 'codex-portable' } `
                -Body $body -ContentType 'application/json' -TimeoutSec 30
            Write-Host "已创建私有仓库 $owner/$repoName" -ForegroundColor Green
        } catch {
            Write-Host '仓库已存在或无法自动创建，继续尝试推送' -ForegroundColor DarkGray
        }
    }

    Write-Host ''
    & $gitExe @sslArgs @credArgs push -u origin "HEAD:$Branch"
    $code = $LASTEXITCODE
} finally {
    if ($askpassFile -and (Test-Path -LiteralPath $askpassFile)) { Remove-Item -LiteralPath $askpassFile -Force }
    Remove-Item Env:\GP_TOKEN -ErrorAction SilentlyContinue
    Remove-Item Env:\GP_USER -ErrorAction SilentlyContinue
    Remove-Item Env:\GIT_ASKPASS -ErrorAction SilentlyContinue
    $Token = $null
}

Write-Host ""
if ($code -eq 0) {
    Write-Host '推送成功' -ForegroundColor Green
    Write-Host ('仓库主页：' + ($Repo -replace '\.git$', '')) -ForegroundColor Green
} else {
    Write-Host '推送失败。常见原因：' -ForegroundColor Yellow
    Write-Host '  1. GitHub 上还没创建这个空仓库'
    Write-Host '  2. 令牌没有 repo 权限，或已过期'
    Write-Host '  3. 用户名和仓库路径不匹配'
    Write-Host '  4. 网络问题：可改用 SSH 地址 git@github.com:you/codex-portable.git'
}
Write-Host ""
Read-Host "按回车退出"
