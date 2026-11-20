# 从源码构建 Windows 可执行文件，产出带产品名/版本元数据的二进制到 dist-bin/
# 目的：代码签名（SignPath）要求「产物必须能从源码可验证地构建」，本地和 CI 用同一套脚本。
# 用法：
#   ./build-binaries.ps1                       # 全部构建 + 校验 + 生成哈希
#   ./build-binaries.ps1 -Only launcher        # 只构建某一个（CI 里拆成独立步骤，失败点更清楚）
#   ./build-binaries.ps1 -Only checksum        # 只做元数据校验与哈希
#   ./build-binaries.ps1 -PythonExe C:\path\to\python.exe
param(
    [string]$Version = "",
    [string]$PythonExe = "python",
    [string]$OutDir = "dist-bin",
    [ValidateSet('all', 'launcher', 'raw', 'pulse', 'checksum')]
    [string]$Only = 'all'
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo

if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = (Get-Content (Join-Path $repo 'VERSION') -Raw).Trim()
}
$Version = $Version.TrimStart('v')

$out = Join-Path $repo $OutDir
$csc = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path $csc)) {
    $csc = "C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe"
}

function Initialize-OutDir {
    if (-not (Test-Path $out)) { New-Item -ItemType Directory -Force -Path $out | Out-Null }
}

function Get-TempDir {
    $t = Join-Path ([System.IO.Path]::GetTempPath()) ("diysign-" + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $t | Out-Null
    return $t
}

function Build-Launcher {
    Write-Host "[launcher] DeepSeekHubPanel.exe" -ForegroundColor Yellow
    if (-not (Test-Path $csc)) { throw "找不到 csc.exe" }
    Initialize-OutDir
    $tmp = Get-TempDir
    try {
        $info = Join-Path $tmp 'launcher-info.cs'
        & (Join-Path $PSScriptRoot 'make-assembly-info.ps1') `
            -OutFile $info -ProductName "DeepSeek Hub Panel" -Title "DeepSeek Hub 面板" `
            -Description "DeepSeek 网页会话同步面板启动器" -Version $Version
        & $csc /nologo /target:winexe /optimize+ `
            "/out:`"$out\DeepSeekHubPanel.exe`"" `
            "/win32icon:`"$repo\plugins\deepseek-hub\desktop\app.ico`"" `
            "`"$repo\plugins\deepseek-hub\desktop\Launcher.cs`"" `
            "`"$info`""
        if ($LASTEXITCODE -ne 0) { throw "DeepSeekHubPanel.exe 编译失败（csc 退出码 $LASTEXITCODE）" }
    } finally {
        Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Build-RawJpg {
    Write-Host "[raw] RAW转JPG.exe" -ForegroundColor Yellow
    Initialize-OutDir
    # 预检：WPF 依赖的 GAC 程序集缺失时，先在这里说清楚，别等 csc 抛一堆引用错误
    $refs = @(
        "C:\Windows\Microsoft.NET\assembly\GAC_MSIL\WindowsBase\v4.0_4.0.0.0__31bf3856ad364e35\WindowsBase.dll",
        "C:\Windows\Microsoft.NET\assembly\GAC_64\PresentationCore\v4.0_4.0.0.0__31bf3856ad364e35\PresentationCore.dll",
        "C:\Windows\Microsoft.NET\assembly\GAC_MSIL\System.Xaml\v4.0_4.0.0.0__b77a5c561934e089\System.Xaml.dll"
    )
    $missing = $refs | Where-Object { -not (Test-Path $_) }
    if ($missing) { throw "缺少 WPF 依赖：`n$($missing -join "`n")" }

    & (Join-Path $repo 'apps\raw-to-jpg\build.ps1')
    $built = Join-Path $repo 'apps\outputs\RAW转JPG.exe'
    if (-not (Test-Path $built)) { throw "没有找到 RAW转JPG.exe 的构建产物：$built" }
    Copy-Item $built -Destination (Join-Path $out 'RAW转JPG.exe') -Force
    Remove-Item (Join-Path $repo 'apps\outputs') -Recurse -Force -ErrorAction SilentlyContinue
}

function Build-Pulse {
    Write-Host "[pulse] DSH-Plugin-Pulse" -ForegroundColor Yellow
    Initialize-OutDir
    $appDir = Join-Path $repo 'apps\dsh-plugin-pulse'
    $tmp = Get-TempDir
    try {
        $verFile = Join-Path $tmp 'win-version.txt'
        & (Join-Path $PSScriptRoot 'make-version-info.ps1') `
            -OutFile $verFile -ProductName "DSH-Plugin-Pulse" `
            -FileDescription "DSH 插件面板：安装、卸载与兼容性诊断" -Version $Version
        Push-Location $appDir
        try {
            $env:PYI_VERSION_FILE = $verFile
            & $PythonExe -m PyInstaller --noconfirm --clean DSH-Plugin-Pulse.spec
            if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建失败（退出码 $LASTEXITCODE）" }
        } finally {
            Remove-Item Env:\PYI_VERSION_FILE -ErrorAction SilentlyContinue
            Pop-Location
        }
        $dist = Join-Path $appDir 'dist\DSH-Plugin-Pulse'
        if (-not (Test-Path $dist)) { throw "没有找到 PyInstaller 产物：$dist" }
        Copy-Item $dist -Destination $out -Recurse -Force
    } finally {
        Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Complete-Build {
    Write-Host "[checksum] 校验元数据并生成 SHA256SUMS.txt" -ForegroundColor Yellow
    $exes = @(Get-ChildItem $out -Recurse -Filter *.exe -File -ErrorAction SilentlyContinue)
    if ($exes.Count -eq 0) { throw "$out 里没有 exe，构建可能没成功" }
    foreach ($e in $exes) {
        $vi = $e.VersionInfo
        if ([string]::IsNullOrWhiteSpace($vi.ProductName) -or [string]::IsNullOrWhiteSpace($vi.ProductVersion)) {
            throw "$($e.Name) 缺少产品元数据（ProductName/ProductVersion）"
        }
        "{0}  →  {1} {2}" -f $e.Name, $vi.ProductName, $vi.ProductVersion
    }
    $lines = $exes | Sort-Object Name | ForEach-Object {
        "{0}  {1}" -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower(), $_.Name
    }
    Set-Content -Path (Join-Path $out 'SHA256SUMS.txt') -Value $lines -Encoding utf8
    Write-Host "完成：$out（$($exes.Count) 个 exe）" -ForegroundColor Green
}

Write-Host "版本：$Version ｜ 阶段：$Only ｜ csc：$csc" -ForegroundColor Cyan

if ($env:GITHUB_REF_TYPE -eq 'tag' -and $env:GITHUB_REF_NAME -ne "v$Version") {
    throw "标签 $($env:GITHUB_REF_NAME) 与 VERSION $Version 不一致"
}

switch ($Only) {
    'launcher' { Build-Launcher }
    'raw' { Build-RawJpg }
    'pulse' { Build-Pulse }
    'checksum' { Complete-Build }
    'all' {
        if (Test-Path $out) { Remove-Item $out -Recurse -Force }
        Build-Launcher
        Build-RawJpg
        Build-Pulse
        Complete-Build
    }
}
