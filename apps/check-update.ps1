<#
  按 apps/manifest.json 校验并更新已安装的自制软件。

  更新基准默认是 GitHub 上**最新的 Release tag**，不是 main —— 避免把未发布的
  开发中代码拉给下载用户。需要别的版本时用 -Ref 指定。

  用法：
    powershell -ExecutionPolicy Bypass -File check-update.ps1
    powershell -ExecutionPolicy Bypass -File check-update.ps1 -Check
    powershell -ExecutionPolicy Bypass -File check-update.ps1 -Ref v2.0.2
    powershell -ExecutionPolicy Bypass -File check-update.ps1 -Root D:\Tools

  目录约定（两种都支持）：
    仓库布局      <Root>\apps\pc-toolkit\...
    解压布局      <Root>\pc-toolkit\...        （各 zip 解压到同一层）
    插件同理      <Root>\plugins\deepseek-hub\... 或 <Root>\deepseek-hub\...
#>
[CmdletBinding()]
param(
    [string]$Root = '',
    [string]$Ref = '',
    [string]$Repo = 'YYY-DXS/DIY-code',
    [switch]$Check,
    [switch]$NoPause
)

$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
try {
    [Net.ServicePointManager]::SecurityProtocol =
        [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
} catch {}

$scriptDir = $PSScriptRoot
if (-not $scriptDir) { $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $Root) { $Root = Split-Path -Parent $scriptDir }
$Root = (Resolve-Path -LiteralPath $Root -ErrorAction SilentlyContinue).Path
if (-not $Root -or -not (Test-Path -LiteralPath $Root -PathType Container)) {
    Write-Host "找不到软件目录。用 -Root 指定各软件所在的那一层。" -ForegroundColor Red
    if (-not $NoPause) { Read-Host "按回车关闭" }
    exit 1
}

# 用 HttpClient 而不是 Invoke-WebRequest：后者在连接卡住时可能挂几分钟，
# 更新器要让用户看到明确结果而不是像死机。
$script:HttpClient = $null
function Get-UrlBytes([string]$url, [int]$timeoutSec = 25) {
    for ($attempt = 1; $attempt -le 2; $attempt++) {
        try {
            if (-not $script:HttpClient) {
                try { Add-Type -AssemblyName System.Net.Http -ErrorAction SilentlyContinue } catch { }
                $handler = New-Object System.Net.Http.HttpClientHandler
                $handler.AllowAutoRedirect = $true
                $client = New-Object System.Net.Http.HttpClient($handler)
                $client.Timeout = [TimeSpan]::FromSeconds(25)
                try { $client.DefaultRequestHeaders.UserAgent.ParseAdd('diy-apps-updater') } catch { }
                $script:HttpClient = $client
            }
            $task = $script:HttpClient.GetAsync($url)
            if (-not $task.Wait([TimeSpan]::FromSeconds($timeoutSec + 5))) { continue }
            $resp = $task.Result
            if (-not $resp.IsSuccessStatusCode) { return $null }
            $bodyTask = $resp.Content.ReadAsByteArrayAsync()
            if (-not $bodyTask.Wait([TimeSpan]::FromSeconds($timeoutSec))) { continue }
            return ,$bodyTask.Result
        } catch { continue }
    }
    return $null
}

function Resolve-Ref {
    param([string]$Wanted)
    if ($Wanted) { return $Wanted }
    try {
        $bytes = Get-UrlBytes "https://api.github.com/repos/$Repo/releases/latest"
        if ($bytes) {
            $release = [Text.Encoding]::UTF8.GetString($bytes) | ConvertFrom-Json
            if ($release -and $release.tag_name) { return [string]$release.tag_name }
        }
    } catch { }
    $versionFile = Join-Path $Root 'VERSION'
    if (Test-Path -LiteralPath $versionFile) {
        $version = (Get-Content -LiteralPath $versionFile -Raw -ErrorAction SilentlyContinue)
        if ($version -and $version.Trim()) { return ('v' + $version.Trim()) }
    }
    return ''
}

$resolvedRef = Resolve-Ref -Wanted $Ref
if (-not $resolvedRef) {
    Write-Host "拿不到最新 Release，也没有 VERSION 文件。" -ForegroundColor Red
    Write-Host "请用 -Ref vX.Y.Z 明确指定一个已发布的版本。" -ForegroundColor Yellow
    if (-not $NoPause) { Read-Host "按回车关闭" }
    exit 1
}
$rawBase = "https://raw.githubusercontent.com/$Repo/$resolvedRef"
$apiBase = "https://api.github.com/repos/$Repo/contents"

function Get-RemoteBytes([string]$rel) {
    $bytes = Get-UrlBytes "$rawBase/$rel"
    if ($bytes) { return $bytes }
    $apiBytes = Get-UrlBytes "$apiBase/$rel`?ref=$resolvedRef"
    if ($apiBytes) {
        try {
            $api = [Text.Encoding]::UTF8.GetString($apiBytes) | ConvertFrom-Json
            if ($api.content) { return [Convert]::FromBase64String(($api.content -replace '\s', '')) }
        } catch { }
    }
    return $null
}

function Test-TextRel([string]$rel) {
    $ext = [IO.Path]::GetExtension($rel).ToLowerInvariant()
    return -not ($ext -in @('.ico', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.exe', '.dll', '.zip', '.pdf', '.woff', '.woff2', '.mp4'))
}

# 本机数据永远不更新：配置里可能有 API Key，data/ 里有历史和状态。
# 清单万一混进这些路径，这里必须挡住，不能把用户自己的配置覆盖成默认值。
function Test-Protected([string]$rel) {
    if ($rel -match '(^|/)(data|logs?|\.dev)/') { return $true }
    if ($rel -match '(^|/)(config\.json|api\.txt|balance_history\.json|widget\.log)$') { return $true }
    return $false
}

function Get-NormalizedHashBytes([byte[]]$bytes, [string]$rel) {
    if (Test-TextRel $rel) {
        # 本地可能是 CRLF，仓库里是 LF；比较前统一成 LF
        $text = [Text.Encoding]::UTF8.GetString($bytes)
        $bytes = [Text.Encoding]::UTF8.GetBytes(($text -replace "`r`n", "`n"))
    }
    $sha = [Security.Cryptography.SHA256]::Create()
    return ([BitConverter]::ToString($sha.ComputeHash($bytes)) -replace '-', '').ToLowerInvariant()
}

function Get-NormalizedHashFile([string]$path, [string]$rel) {
    return Get-NormalizedHashBytes ([IO.File]::ReadAllBytes($path)) $rel
}

# 把清单里的仓库路径映射到本机位置；没装这个软件就返回空。
function Resolve-Target([string]$rel) {
    $parts = $rel -split '/'
    if ($parts.Count -lt 2) { return '' }
    $top = $parts[0]
    if ($parts.Count -eq 2) {
        $topDir = Join-Path $Root $top
        if (Test-Path -LiteralPath $topDir -PathType Container) { return (Join-Path $topDir $parts[1]) }
        return ''
    }
    $name = $parts[1]
    $rest = ($parts[2..($parts.Count - 1)] -join [IO.Path]::DirectorySeparatorChar)
    $candidates = @(
        (Join-Path (Join-Path $Root $top) $name),
        (Join-Path $Root $name)
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Container) {
            return (Join-Path $candidate $rest)
        }
    }
    return ''
}

Write-Host "更新基准：$Repo @ $resolvedRef" -ForegroundColor Cyan
Write-Host "软件目录：$Root"
if ($Check) { Write-Host "只检查，不写入。" -ForegroundColor Yellow }

$manifestBytes = Get-RemoteBytes 'apps/manifest.json'
if (-not $manifestBytes) {
    Write-Host "拿不到清单，检查网络后重试。" -ForegroundColor Red
    if (-not $NoPause) { Read-Host "按回车关闭" }
    exit 1
}
$manifest = [Text.Encoding]::UTF8.GetString($manifestBytes) | ConvertFrom-Json

$updated = 0
$same = 0
$missing = 0
$failed = 0
$mismatch = 0
$protected = 0

foreach ($prop in $manifest.files.PSObject.Properties) {
    $rel = [string]$prop.Name
    $want = ([string]$prop.Value).ToLowerInvariant()

    if (Test-Protected $rel) { $protected++; continue }

    $target = Resolve-Target $rel
    if (-not $target) { $missing++; continue }

    $need = $true
    if (Test-Path -LiteralPath $target) {
        $have = Get-NormalizedHashFile $target $rel
        if ($have -eq $want) { $same++; $need = $false }
    }
    if (-not $need) { continue }

    if ($Check) {
        Write-Host "  会更新：$rel" -ForegroundColor Yellow
        $updated++
        continue
    }

    $bytes = Get-RemoteBytes $rel
    if (-not $bytes) {
        Write-Host "  失败：$rel（下载不到）" -ForegroundColor Yellow
        $failed++
        continue
    }
    $got = Get-NormalizedHashBytes $bytes $rel
    if ($got -ne $want) {
        Write-Host "  失败：$rel（哈希不符，可能是下载被截断）" -ForegroundColor Yellow
        $mismatch++
        continue
    }

    $dir = Split-Path -Parent $target
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    $ext = [IO.Path]::GetExtension($target).ToLowerInvariant()
    if ((Test-TextRel $rel) -and ($ext -in @('.cmd', '.bat', '.ps1'))) {
        # Windows 批处理 / PowerShell 落盘时保持 CRLF
        $text = [Text.Encoding]::UTF8.GetString($bytes)
        $text = $text -replace "`r`n", "`n"
        $text = $text -replace "`n", "`r`n"
        $bytes = [Text.Encoding]::UTF8.GetBytes($text)
    }
    [IO.File]::WriteAllBytes($target, $bytes)
    Write-Host "  更新：$rel" -ForegroundColor Green
    $updated++
}

Write-Host ""
if ($updated -eq 0 -and $failed -eq 0 -and $mismatch -eq 0) {
    Write-Host "已经是最新版（$resolvedRef）。" -ForegroundColor Green
} else {
    Write-Host "完成：更新 $updated 个，已是最新 $same 个，失败 $failed 个，校验不符 $mismatch 个。" -ForegroundColor Green
}
if ($missing -gt 0) {
    Write-Host "未安装而跳过的文件：$missing 个（解压对应软件包后就地再跑一次即可）。" -ForegroundColor DarkGray
}
if ($protected -gt 0) {
    Write-Host "跳过受保护的本机数据：$protected 个（data/、config.json、api.txt 等不会被改动）。" -ForegroundColor DarkGray
}
Write-Host ""
if (-not $NoPause) { Read-Host "按回车关闭" }

if ($failed -gt 0 -or $mismatch -gt 0) { exit 1 }
exit 0
