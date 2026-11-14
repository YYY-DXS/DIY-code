# 打包 DSH 插件面板：网页版 + 原生脉冲版（onedir 绿色包 + zip）
# 说明：用 --onedir 而不是 --onefile，因为 onefile 需要向临时目录解包，
#       在部分受限环境（沙箱 / 严格 Temp 策略）下会失败；onedir 直接运行、零解包。
$ErrorActionPreference = 'Stop'
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $env:USERPROFILE '.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path $py)) { $py = 'python' }

& $py -c "import PyInstaller" *> $null
if ($LASTEXITCODE -ne 0) {
    throw "缺少 PyInstaller。请先运行：`"$py`" -m pip install pyinstaller"
}

function Build-App($name, $entry, $extraArgs) {
    Push-Location $dir
    try {
        $args = @('-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--noconsole',
                  '--name', $name, '--icon', 'assets/icon.ico',
                  '--add-data', 'catalog.json;.', $entry) + $extraArgs
        & $py @args
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller 失败: $name" }
        $built = Join-Path $dir "dist\$name"
        $relDir = Join-Path $dir "release\$name"
        if (Test-Path $relDir) { Remove-Item $relDir -Recurse -Force }
        New-Item -ItemType Directory -Force -Path $relDir | Out-Null
        Copy-Item (Join-Path $built "*") $relDir -Recurse -Force
        $zip = Join-Path $dir "release\$name-win64.zip"
        if (Test-Path $zip) { Remove-Item $zip -Force }
        Compress-Archive -Path (Join-Path $built "*") -DestinationPath $zip -Force
        $size = [math]::Round((Get-Item $zip).Length / 1MB, 1)
        Write-Host "打包完成：$relDir"
        Write-Host "分发包：$zip（$size MB）"
    } finally {
        Pop-Location
    }
}

Build-App "DSH-Plugin-Installer" "server.py" @('--add-data', 'ui.html;.')
Build-App "DSH-Plugin-Pulse" "pulse_panel.py" @()
