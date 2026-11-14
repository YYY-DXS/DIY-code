<#
    Codex 桌面端 汉化 / 还原（一键脚本）

    做两件事：
      1. 打开被官方远端开关锁住的 enable_i18n（改 app.asar 里一行 JS，等长替换，不动目录表）
      2. 补上官方 zh-CN 语言包漏翻的 4 条文案
    并自动夺取 / 还原 app.asar 的属主与权限，全程写日志。

    请通过 codex-zh-cn-install.bat（汉化）或 codex-zh-cn-revert.bat（还原）双击运行。
    直接命令行可加参数：-DryRun 只构建校验不写入；-NoElevate 不提权（排错用）。
#>
[CmdletBinding()]
param(
    [switch]$Revert,
    [switch]$DryRun,
    [switch]$NoRelaunch,
    [switch]$Pause,
    [switch]$NoElevate,
    [string]$KitRoot = "",
    [string]$Python  = (Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe")
)

if (-not $KitRoot) { $KitRoot = Split-Path -Parent $PSScriptRoot }

$ErrorActionPreference = 'Stop'
$script:exitCode = 0
$outRoot = Join-Path $KitRoot 'out\codex-i18n'
$bootLog = Join-Path $outRoot 'boot.log'

function Say($msg, $color = 'Gray') { Write-Host $msg -ForegroundColor $color }
function Step($n, $msg) { Write-Host "`n[$n] $msg" -ForegroundColor Cyan }
function Note($msg) {
    Write-Host $msg
    try {
        New-Item -ItemType Directory -Force -Path $outRoot | Out-Null
        Add-Content -Path $bootLog -Encoding UTF8 -Value ("{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg)
    } catch { }
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin  = ([Security.Principal.WindowsPrincipal]$identity).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)

Note ("启动脚本  Admin=$isAdmin  Revert=$Revert  DryRun=$DryRun")

# ---------------------------------------------------------------- 0. 提权
if (-not $isAdmin -and -not $NoElevate) {
    Say '需要管理员权限（要修改 WindowsApps 下的 app.asar），正在弹出 UAC…' Yellow
    Say '请在弹出的窗口里点「是」；如果没看到 UAC 窗口，看下屏幕右下角。' Yellow
    $childArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"", '-Pause')
    if ($Revert)     { $childArgs += '-Revert' }
    if ($DryRun)     { $childArgs += '-DryRun' }
    if ($NoRelaunch) { $childArgs += '-NoRelaunch' }
    try {
        Start-Process powershell -Verb RunAs -ArgumentList $childArgs
        Note '已请求提权，本窗口退出（管理员的那个窗口才是干活的窗口）'
    } catch {
        Note ("提权失败或被取消：{0}" -f $_.Exception.Message)
        Say "提权失败或被取消：$($_.Exception.Message)" Red
        Say '两个办法：' Yellow
        Say '  1) 重新双击桌面入口，并在 UAC 弹窗里点「是」；' Yellow
        Say '  2) 右键 tools\codex-zh-cn-install.bat → 「以管理员身份运行」。' Yellow
        if ($Pause) { Read-Host '按回车键关闭窗口' | Out-Null }
    }
    exit 1
}

if (-not $isAdmin) { Say '注意：-NoElevate 模式没有管理员权限，写入步骤会失败（仅用于排错）。' Yellow }

$user  = "$env:USERDOMAIN\$env:USERNAME"
$py    = $Python
$tool  = Join-Path $KitRoot 'tools\ui_patch.py'
$fixes = Join-Path $KitRoot 'demo\codex-ui-fixes.csv'
$patchFlag    = Join-Path $outRoot 'flag\patch.json'
$patchLocale  = Join-Path $outRoot 'locale\patch.json'
$backupFlag   = Join-Path $outRoot 'backup-flag.bin'
$backupLocale = Join-Path $outRoot 'backup-locale.bin'

try {
    New-Item -ItemType Directory -Force -Path $outRoot | Out-Null
    Start-Transcript -Path (Join-Path $outRoot 'install.log') -Append | Out-Null
} catch { }

try {
    if (-not (Test-Path $py))   { throw "找不到 python：$py" }
    if (-not (Test-Path $tool)) { throw "找不到 ui_patch.py：$tool" }

    # ------------------------------------------------ 1. 找到 app.asar
    Step 1 '定位 Codex 的 app.asar'
    $candidates = @()

    # 兜底 1：AppX 注册信息（普通用户可读）
    $pkg = Get-AppxPackage -Name 'OpenAI.Codex' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pkg -and $pkg.InstallLocation) {
        $candidates += Join-Path $pkg.InstallLocation 'app\resources\app.asar'
    }

    # 兜底 2：注册表里的 MSIX 包注册项（普通用户可读，沙箱里可能被拒）
    $repoKey = 'HKCU:\Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\Repository\Packages'
    try {
        Get-ChildItem $repoKey -ErrorAction Stop |
            Where-Object PSChildName -like 'OpenAI.Codex*' |
            ForEach-Object {
                $root = (Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue).PackageRootFolder
                if ($root) { $candidates += Join-Path $root 'app\resources\app.asar' }
            }
    } catch { }

    # 兜底 3：从 ~/.codex/config.toml 里翻出应用路径（不依赖管理员、不枚举目录）
    foreach ($cfg in @((Join-Path $env:USERPROFILE '.codex\config.toml'), (Join-Path $env:USERPROFILE '.codex-mcp\config.toml'))) {
        if (-not (Test-Path $cfg)) { continue }
        try {
            $cfgText = Get-Content -Raw -LiteralPath $cfg
            $pattern = '(?i)([A-Z]:\\[^"\r\n]*\\app\\ChatGPT\.exe)'
            foreach ($hit in [regex]::Matches($cfgText, $pattern)) {
                $appPath = $hit.Groups[1].Value
                $candidates += Join-Path (Split-Path $appPath -Parent) 'resources\app.asar'
            }
        } catch { }
    }

    # 兜底 4：枚举 WindowsApps（需要管理员，脚本提权后可用）
    $candidates += Get-ChildItem 'C:\Program Files\WindowsApps' -Directory -Force -ErrorAction SilentlyContinue |
        Where-Object Name -like 'OpenAI.Codex_*' |
        ForEach-Object { Join-Path $_.FullName 'app\resources\app.asar' }
    $candidates += Get-ChildItem "$env:LOCALAPPDATA\Programs" -Directory -ErrorAction SilentlyContinue |
        Where-Object Name -like '*Codex*' |
        ForEach-Object { Join-Path $_.FullName 'resources\app.asar' }

    $asar = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $asar) { throw '没找到 app.asar，请确认 Codex 桌面端已安装。' }
    $appDir = Split-Path (Split-Path $asar -Parent) -Parent
    Say "  app.asar : $asar"
    Say "  应用目录 : $appDir"
    Note "找到 asar: $asar"

    # ------------------------------------------------ 2. 检查进程
    $procNames = @('ChatGPT', 'Codex', 'codex')
    if ($Revert) {
        Say "`n模式：还原英文"
    } else {
        Step 2 '检查 Codex 是否已退出'
        $alive = Get-Process -Name $procNames -ErrorAction SilentlyContinue
        if ($alive) {
            Say ("  仍在运行：" + (($alive | Select-Object -ExpandProperty ProcessName -Unique) -join ', ')) Yellow
            Say '  先尝试温和关闭窗口…' Yellow
            $alive | Where-Object { $_.MainWindowHandle -ne 0 } | ForEach-Object { $_.CloseMainWindow() | Out-Null }
            Start-Sleep -Seconds 5
            $alive = Get-Process -Name $procNames -ErrorAction SilentlyContinue
            if ($alive) {
                throw '请手动完全退出 Codex（右下角托盘图标 → 右键 → 退出；只关窗口不算），然后重新双击本脚本。'
            }
        }
        Say '  已退出，可以开始打补丁'
    }

    # ------------------------------------------------ 3. 构建补丁
    if (-not $Revert) {
        Step 3 '构建并校验补丁（此步骤不修改任何已安装文件）'
        & $py $tool build --asar $asar --locale zh-CN --fixes $fixes --outdir (Join-Path $outRoot 'locale')
        if ($LASTEXITCODE -ne 0) { throw '语言包补丁构建失败' }
        & $py $tool build-text --asar $asar --entry-needle enable_i18n `
            --find 's?.get(`enable_i18n`,!1)' --replace '!0' --outdir (Join-Path $outRoot 'flag')
        if ($LASTEXITCODE -ne 0) { throw 'i18n 开关补丁构建失败' }
        Note '两个补丁构建并校验通过'
    }
    if ($DryRun) {
        Say "`n-DryRun 完成：补丁已构建并校验，没有写入任何文件。" Green
        Say "产物目录：$outRoot" Green
        Note 'DryRun 结束'
        return
    }

    # ------------------------------------------------ 4. 临时取得写权限
    Step 4 '临时取得 app.asar 的写权限'
    takeown /f "$asar" | Out-Null
    icacls "$asar" /grant "$($user):(F)" | Out-Null
    Say '  已授权（脚本结束时会还原属主与权限）'

    try {
        if ($Revert) {
            Step 5 '还原英文（写回原始字节）'
            $pairs = @(
                @{ json = $patchFlag;   bak = $backupFlag },
                @{ json = $patchLocale; bak = $backupLocale }
            )
            foreach ($pair in $pairs) {
                if (-not (Test-Path $pair.json) -or -not (Test-Path $pair.bak)) {
                    Say "  跳过（没有备份记录）：$($pair.json)" Yellow
                    continue
                }
                $d = Get-Content -Raw -Encoding UTF8 $pair.json | ConvertFrom-Json
                $bytes = [IO.File]::ReadAllBytes($pair.bak)
                $fs = [IO.File]::Open($asar, 'Open', 'Write', 'None')
                try {
                    $fs.Seek([int64]$d.offset, 'Begin') | Out-Null
                    $fs.Write($bytes, 0, $bytes.Length)
                } finally { $fs.Close() }
                Say "  已还原：$($d.inner)"
            }
        }
        else {
            Step 5 '写入补丁'
            & $py $tool apply --patch $patchLocale --backup $backupLocale --asar $asar
            if ($LASTEXITCODE -ne 0) { throw '语言包补丁写入失败' }
            & $py $tool apply --patch $patchFlag --backup $backupFlag --asar $asar
            if ($LASTEXITCODE -ne 0) { throw 'i18n 开关补丁写入失败' }

            Step 6 '校验写入结果'
            & $py $tool verify --patch $patchLocale --asar $asar
            & $py $tool verify --patch $patchFlag   --asar $asar
            Note '补丁写入并校验完成'
        }
    }
    finally {
        icacls "$asar" /remove:g "$($user)" | Out-Null
        icacls "$asar" /setowner "NT AUTHORITY\SYSTEM" | Out-Null
        Say "`n已还原 app.asar 的属主与权限。"
    }

    # ------------------------------------------------ 7. 启动
    if (-not $NoRelaunch) {
        Step 7 '启动 Codex'
        $exe = Join-Path $appDir 'ChatGPT.exe'
        if (Test-Path $exe) {
            Start-Process $exe
            Say '  已启动。首次启动加载语言包会稍慢一点。'
        } else {
            Say "  没找到 ChatGPT.exe，请从开始菜单启动 Codex。（$exe）" Yellow
        }
    }

    if ($Revert) {
        Say "`n已还原成英文界面。" Green
    } else {
        Say "`n汉化完成。" Green
        Say '如果界面还是英文：Settings → General → Language 选「中文（中国）」，或重启一次 Codex。' Green
        Say '想还原英文：双击同目录下的 codex-zh-cn-revert.bat' Cyan
    }
}
catch {
    $script:exitCode = 1
    Write-Host "`n出错了：$($_.Exception.Message)" -ForegroundColor Red
    Write-Host "日志：$outRoot\install.log（以及 boot.log）—— 把这段发给我，我接着查。" -ForegroundColor Yellow
    Note ("失败：{0}" -f $_.Exception.Message)
}
finally {
    try { Stop-Transcript | Out-Null } catch { }
    if ($Pause) { Read-Host '按回车键关闭窗口' | Out-Null }
}

exit $script:exitCode
