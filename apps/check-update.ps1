<#
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
        if ($resp.StatusCode -eq 200) { return $resp.Content }
    } catch { }
    try {
        $api = Invoke-RestMethod -Uri "$apiBase/$rel" -Headers @{ 'User-Agent' = 'diy-apps-updater' } -TimeoutSec 25
        if ($api.content) {
            return [Convert]::FromBase64String(($api.content -replace '\s', ''))
        }
    } catch { }
    return $null
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
        $have = (Get-FileHash -Algorithm SHA256 -LiteralPath $local).Hash.ToLower()
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
    if ($bytes -is [byte[]]) { [IO.File]::WriteAllBytes($local, $bytes) }
    else { [IO.File]::WriteAllText($local, [string]$bytes, [Text.UTF8Encoding]::new($false)) }
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
