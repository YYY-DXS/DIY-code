<#
  把「DeepSeek 知识库」的指引写进 Codex 的全局 AGENTS.md，
  这样在任意项目的新对话里，Codex 都会自动知道去查这份记录。

  幂等：重复运行安全，会先备份原文件。想撤销就把 .bak 覆盖回去。
#>

param(
    # 默认写到 Codex 的全局 AGENTS.md；传参数是为了方便自测
    [string]$Target
)

$ErrorActionPreference = 'Stop'

$source = Join-Path $PSScriptRoot 'AGENTS.global.md'
$target = if ($Target) { $Target } else { Join-Path $env:USERPROFILE '.codex\AGENTS.md' }
$marker = '<!-- deepseek-knowledge-base -->'

if (-not (Test-Path -LiteralPath $source)) {
    Write-Host "找不到要写入的内容：$source" -ForegroundColor Red
    Read-Host "按回车退出"
    exit 1
}

$incoming = Get-Content -LiteralPath $source -Raw -Encoding UTF8
$targetDir = Split-Path -Parent $target
if (-not (Test-Path -LiteralPath $targetDir)) {
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
}

$existing = ''
if (Test-Path -LiteralPath $target) {
    $existing = Get-Content -LiteralPath $target -Raw -Encoding UTF8
}

if ($existing -and $existing.Trim()) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $backup = "$target.bak-$stamp"
    Copy-Item -LiteralPath $target -Destination $backup -Force
    Write-Host "已备份原文件到：$backup" -ForegroundColor DarkGray
}

if ($existing -match [regex]::Escape($marker)) {
    Write-Host "检测到之前写过这份内容，只替换这一段，其余保留。" -ForegroundColor Yellow
    # 只替换我们自己的那一段，用户后来加的内容原样保留
    $head = $existing.Substring(0, $existing.IndexOf($marker)).TrimEnd()
    $final = if ($head) { $head + "`r`n`r`n---`r`n`r`n" + $incoming } else { $incoming }
}
elseif ($existing -and $existing.Trim()) {
    Write-Host "原文件已有其他内容，追加到末尾。" -ForegroundColor Yellow
    $final = $existing.TrimEnd() + "`r`n`r`n---`r`n`r`n" + $incoming
}
else {
    $final = $incoming
}

Set-Content -LiteralPath $target -Value $final -Encoding UTF8 -NoNewline

$size = (Get-Item -LiteralPath $target).Length
Write-Host ""
Write-Host "完成：$target（$size 字节）" -ForegroundColor Green
Write-Host "现在打开一个全新对话（建议换个项目试试），问一句「我最看重哪几个项目」，"
Write-Host "如果它能说出置顶会话里的内容，就说明生效了。"
Write-Host ""
Read-Host "按回车关闭"
