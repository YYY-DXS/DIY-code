#
  按 manifest.json 校验并更新 apps 下的文件。
  用法：双击 更新所有软件.cmd，或 powershell -File check-update.ps1
#>

$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}

$repoRoot = Split-Path -Parent $PSScriptRoot
$repo = 'YYY-DXS/DIY-code'
$branch = 'main'
$rawBase = "https://raw.githubusercontent.com/$repo/$branch"
$apiBase = "https://api.github.com/repos/$repo/contents"
$manifestRel = 'apps/manifest.json'

function Get-RemoteBytes([string]$rel) {
    try {
        $resp = Invoke-WebRequest -Uri "$rawBase/$rel" -UseBasicParsing -TimeoutSec 20
        if ($resp.StatusCode -eq 200) {
            # 用原始字节流，避免把 ico/png/exe 当文本写入后损坏
            if ($null -ne $resp.RawContentStream) { return $resp.RawContentStream.ToArray() }
            if ($resp.Content -is [byte[]]) { return $resp.Content }
            return [Text.Encoding]::UTF8.GetBytes([string]$resp.Content)
        }
    } catch { }
    try {
        $api = Invoke-RestMethod -Uri "$apiBase/$rel" -Headers @{ 'User-Agent' = 'diy-apps-updater' } -TimeoutSec 25
        if ($api.content) {
            return [Convert]::FromBase64String(($api.content -replace '\s', ''))
        }
    } catch { }
    return $null
}

function Test-TextFile([string]$path) {
    $ext = [IO.Path]::GetExtension($path).ToLowerInvariant()
    return -not ($ext -in @('.ico', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.exe', '.dll', '.zip', '.pdf', '.woff', '.woff2', '.mp4'))
}

function Get-NormalizedSha256([string]$path) {
    $bytes = [IO.File]::ReadAllBytes($path)
    if (Test-TextFile $path) {
        # 本地可能是 CRLF，GitHub 上是 LF；比较前统一成 LF
        $text = [Text.Encoding]::UTF8.GetString($bytes)
        $bytes = [Text.Encoding]::UTF8.GetBytes(($text -replace "`r`n", "`n"))
    }
    $sha = [Security.Cryptography.SHA256]::Create()
    return ([BitConverter]::ToString($sha.ComputeHash($bytes)) -replace '-', '').ToLowerInvariant()
}

Write-Host "检查更新：$repo" -ForegroundColor Cyan
$manifestBytes = Get-RemoteBytes $manifestRel
if (-not $manifestBytes) {
    Write-Host "拿不到清单，检查网络后重试。" -ForegroundColor Red
    Read-Host "按回车关闭"
    exit 1
}

$manifestText = if ($manifestBytes -is [byte[]]) { [Text.Encoding]::UTF8.GetString($manifestBytes) } else { [string]$manifestBytes }
$manifest = $manifestText | ConvertFrom-Json

$updated = 0
$failed = 0
foreach ($prop in $manifest.files.PSObject.Properties) {
    $rel = $prop.Name
    $want = [string]$prop.Value
    $local = Join-Path $repoRoot $rel
    $need = $true
    if (Test-Path -LiteralPath $local) {
        $have = Get-NormalizedSha256 $local
        if ($have -eq $want) { $need = $false }
    }
    if (-not $need) { continue }

    $bytes = Get-RemoteBytes $rel
    if (-not $bytes) {
        Write-Host "  失败：$rel" -ForegroundColor Yellow
        $failed++
        continue
    }
    $dir = Split-Path -Parent $local
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    if ($bytes -isnot [byte[]]) { $bytes = [Text.Encoding]::UTF8.GetBytes([string]$bytes) }
    $ext = [IO.Path]::GetExtension($local).ToLowerInvariant()
    if ((Test-TextFile $local) -and ($ext -in @('.cmd', '.bat', '.ps1'))) {
        # Windows 批处理 / PowerShell 落盘时保持 CRLF
        $text = [Text.Encoding]::UTF8.GetString($bytes)
        $text = $text -replace "`r`n", "`n"
        $text = $text -replace "`n", "`r`n"
        $bytes = [Text.Encoding]::UTF8.GetBytes($text)
    }
    [IO.File]::WriteAllBytes($local, $bytes)
    Write-Host "  更新：$rel" -ForegroundColor Green
    $updated++
}

Write-Host ""
if ($updated -eq 0 -and $failed -eq 0) {
    Write-Host "已经是最新版。" -ForegroundColor Green
} else {
    Write-Host "完成：更新 $updated 个文件，失败 $failed 个。" -ForegroundColor Green
}
Write-Host ""
Read-Host "按回车关闭"
