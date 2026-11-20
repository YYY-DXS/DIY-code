# 把一个插件从 DIY-code/plugins/<Name> 发布成独立仓库
#
# 为什么需要改名：插件现在的包名是 @local/xxx（未发布的占位 scope），
# dsh 从 GitHub 安装后要按 package.json 的 name 解析 cordis.patch.yml 里的行，
# 所以独立仓库必须用一个真实、唯一的包名，并把 patch 里的 name 一起改掉。
#
# 用法：
#   ./publish-plugin.ps1 -Name query-bridge -RepoName dsh-query-bridge
#       只在本地生成到 _staging/<RepoName>，不推送
#   ./publish-plugin.ps1 -Name query-bridge -RepoName dsh-query-bridge -Push
#       生成后 git init + commit，并推送到 github:YYY-DXS/<RepoName>（仓库需先存在）
param(
    [Parameter(Mandatory = $true)][string]$Name,
    [Parameter(Mandatory = $true)][string]$RepoName,
    [string]$Owner = "YYY-DXS",
    [string]$OutRoot = "",
    [switch]$Push,
    [string]$Version = "0.1.0"
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$src = Join-Path $repo "plugins\$Name"
if (-not (Test-Path $src)) { throw "找不到插件目录：$src" }
if ([string]::IsNullOrWhiteSpace($OutRoot)) { $OutRoot = Join-Path (Split-Path -Parent $repo) "_staging" }

$dst = Join-Path $OutRoot $RepoName
if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }
New-Item -ItemType Directory -Force -Path $OutRoot | Out-Null
Copy-Item $src -Destination $dst -Recurse -Force

# ---------- package.json ----------
$pkgPath = Join-Path $dst 'package.json'
$pkg = Get-Content $pkgPath -Raw -Encoding UTF8 | ConvertFrom-Json
$description = $pkg.description

$updates = [ordered]@{
    name       = $RepoName
    version    = $Version
    private    = $false
    license    = "MIT"
    keywords   = @("dsh", "dsh-plugin", "deepseek-harness", "deepseek", ($RepoName -replace '^dsh-', ''))
    homepage   = "https://github.com/$Owner/$RepoName#readme"
    repository = [pscustomobject]@{ type = "git"; url = "git+https://github.com/$Owner/$RepoName.git" }
    bugs       = [pscustomobject]@{ url = "https://github.com/$Owner/$RepoName/issues" }
    engines    = [pscustomobject]@{ node = ">=18"; dsh = ">=0.1.0-rc.6 <0.3.0-0" }
}
foreach ($k in $updates.Keys) {
    $pkg | Add-Member -NotePropertyName $k -NotePropertyValue $updates[$k] -Force
}

# files 里补上 README / LICENSE，保证 npm 包和 GitHub 安装都带上
$files = @($pkg.files)
foreach ($extra in @("README.md", "LICENSE")) {
    if ($files -notcontains $extra) { $files += $extra }
}
$pkg | Add-Member -NotePropertyName files -NotePropertyValue $files -Force
($pkg | ConvertTo-Json -Depth 10).Replace("\u003e", ">").Replace("\u003c", "<") | Set-Content $pkgPath -Encoding UTF8

# ---------- cordis.patch.yml：把 @local/<Name> 换成新包名 ----------
$patchPath = Join-Path $dst 'cordis.patch.yml'
if (Test-Path $patchPath) {
    $patch = Get-Content $patchPath -Raw -Encoding UTF8
    $patch = $patch.Replace("@local/$Name", $RepoName)
    Set-Content $patchPath -Value $patch -Encoding UTF8 -NoNewline
}

# ---------- LICENSE / README ----------
Copy-Item (Join-Path $repo 'LICENSE') -Destination (Join-Path $dst 'LICENSE') -Force

$readme = @"
# $RepoName

$description

DeepSeek Harness（DSH）插件。**本仓库是发布镜像**，源码与开发在 [DIY-code](https://github.com/$Owner/DIY-code) 的 `plugins/$Name/`；两份内容由 `tools/publish-plugin.ps1` 同步，不要只改这里。

## 安装

``````bash
dsh plugin add github:$Owner/$RepoName
``````

安装后在 **设置 → 插件** 里确认该行已启用；首次使用前按下面「配置」填好路径。

## 配置

``````yaml
$(if (Test-Path $patchPath) { (Get-Content $patchPath -Raw -Encoding UTF8).Trim() } else { '# 无' })
``````

## 兼容性

- DSH：``>=0.1.0-rc.6 <0.3.0-0``
- Node：``>=18``
- 平台：Windows

## 许可

MIT，见 [LICENSE](LICENSE)。
"@
Set-Content (Join-Path $dst 'README.md') -Value $readme -Encoding UTF8

# ---------- .gitignore ----------
@"
node_modules/
__pycache__/
*.pyc
*.log
dist/
build/
"@ | Set-Content (Join-Path $dst '.gitignore') -Encoding UTF8

Write-Host "已生成：$dst" -ForegroundColor Green
Write-Host ("  包名：{0}  版本：{1}" -f $pkg.name, $pkg.version)
Get-ChildItem $dst | Select-Object Name, Length | Format-Table -AutoSize | Out-String | Write-Host

if ($Push) {
    $remote = "git@github.com:$Owner/$RepoName.git"
    git -C $dst init -q -b main
    git -C $dst config user.name $Owner
    git -C $dst config user.email "319005595+$Owner@users.noreply.github.com"
    git -C $dst add -A
    git -C $dst commit -q -m "初始化：$RepoName $Version（从 DIY-code/plugins/$Name 拆出）"
    git -C $dst remote add origin $remote
    git -C $dst push -u origin main
    if ($LASTEXITCODE -ne 0) { throw "推送失败，仓库 $remote 可能还不存在（需要先在 GitHub 上创建空的 public 仓库）" }
    Write-Host "已推送：https://github.com/$Owner/$RepoName" -ForegroundColor Green
} else {
    Write-Host "未推送。确认无误后加 -Push 重新运行，或手动 git init/push。" -ForegroundColor Yellow
}
