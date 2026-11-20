# 从源码构建所有 Windows 可执行文件，产出带版本元数据的二进制到 dist-bin/
# 目的：代码签名（SignPath）要求「产物必须能从源码可验证地构建」，本地和 CI 用同一套脚本。
# 用法：
#   ./build-binaries.ps1                 # 用 VERSION 文件里的版本
#   ./build-binaries.ps1 -Version 2.0.9  # 指定版本
#   ./build-binaries.ps1 -PythonExe "C:\path\to\python.exe"
param(
    [string]$Version = "",
    [string]$PythonExe = "python",
    [string]$OutDir = "dist-bin"
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo

if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = (Get-Content (Join-Path $repo 'VERSION') -Raw).Trim()
}
$Version = $Version.TrimStart('v')
Write-Host "构建版本：$Version" -ForegroundColor Cyan

# CI 打 tag 时校验版本一致
if ($env:GITHUB_REF_TYPE -eq 'tag' -and $env:GITHUB_REF_NAME -ne "v$Version") {
    throw "标签 $($env:GITHUB_REF_NAME) 与 VERSION $Version 不一致"
}

$out = Join-Path $repo $OutDir
if (Test-Path $out) { Remove-Item $out -Recurse -Force }
New-Item -ItemType Directory -Force -Path $out | Out-Null

$csc = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path $csc)) { throw "找不到 csc.exe：$csc" }

$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("diysign-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null

try {
    # ---------- 1. DeepSeek Hub 面板启动器（C#）----------
    Write-Host "`n[1/3] DeepSeekHubPanel.exe" -ForegroundColor Yellow
    $infoFile = Join-Path $tmp 'launcher-info.cs'
    & (Join-Path $PSScriptRoot 'make-assembly-info.ps1') `
        -OutFile $infoFile -ProductName "DeepSeek Hub Panel" -Title "DeepSeek Hub 面板" `
        -Description "DeepSeek 网页会话同步面板启动器" -Version $Version
    & $csc /nologo /target:winexe /optimize+ `
        "/out:`"$out\DeepSeekHubPanel.exe`"" `
        "/win32icon:$repo\plugins\deepseek-hub\desktop\app.ico" `
        "$repo\plugins\deepseek-hub\desktop\Launcher.cs" `
        $infoFile
    if ($LASTEXITCODE -ne 0) { throw "DeepSeekHubPanel.exe 编译失败（$LASTEXITCODE）" }

    # ---------- 2. RAW 转 JPG（C# / WPF）----------
    Write-Host "`n[2/3] RAW转JPG.exe" -ForegroundColor Yellow
    $rawBuild = Join-Path $repo 'apps\raw-to-jpg\build.ps1'
    & $rawBuild
    $rawOut = Join-Path $repo 'apps\outputs\RAW转JPG.exe'
    if (-not (Test-Path $rawOut)) { throw "没有找到 RAW转JPG.exe 的构建产物：$rawOut" }
    Copy-Item $rawOut -Destination (Join-Path $out 'RAW转JPG.exe') -Force
    Remove-Item (Join-Path $repo 'apps\outputs') -Recurse -Force -ErrorAction SilentlyContinue

    # ---------- 3. DSH 插件面板（PyInstaller）----------
    Write-Host "`n[3/3] DSH-Plugin-Pulse" -ForegroundColor Yellow
    $appDir = Join-Path $repo 'apps\dsh-plugin-pulse'
    $verFile = Join-Path $tmp 'win-version.txt'
    & (Join-Path $PSScriptRoot 'make-version-info.ps1') `
        -OutFile $verFile -ProductName "DSH-Plugin-Pulse" `
        -FileDescription "DSH 插件面板：安装、卸载与兼容性诊断" -Version $Version
    Push-Location $appDir
    try {
        $env:PYI_VERSION_FILE = $verFile
        & $PythonExe -m PyInstaller --noconfirm --clean DSH-Plugin-Pulse.spec
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建失败（$LASTEXITCODE）" }
    } finally {
        Remove-Item Env:\PYI_VERSION_FILE -ErrorAction SilentlyContinue
        Pop-Location
    }
    $pulseDist = Join-Path $appDir 'dist\DSH-Plugin-Pulse'
    if (-not (Test-Path $pulseDist)) { throw "没有找到 PyInstaller 产物：$pulseDist" }
    Copy-Item $pulseDist -Destination $out -Recurse -Force

    # ---------- 校验元数据 + 生成哈希 ----------
    Write-Host "`n校验产品元数据" -ForegroundColor Yellow
    $exes = Get-ChildItem $out -Recurse -Filter *.exe -File
    foreach ($e in $exes) {
        $vi = $e.VersionInfo
        if ([string]::IsNullOrWhiteSpace($vi.ProductName) -or [string]::IsNullOrWhiteSpace($vi.ProductVersion)) {
            throw "$($e.Name) 缺少产品元数据（ProductName/ProductVersion）"
        }
        "{0}  →  {1} {2}" -f $e.Name, $vi.ProductName, $vi.ProductVersion
    }

    $lines = $exes | Sort-Object Name | ForEach-Object {
        $h = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
        "$h  $($_.Name)"
    }
    Set-Content -Path (Join-Path $out 'SHA256SUMS.txt') -Value $lines -Encoding utf8

    Write-Host "`n完成：$out（$($exes.Count) 个 exe）" -ForegroundColor Green
} finally {
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}
