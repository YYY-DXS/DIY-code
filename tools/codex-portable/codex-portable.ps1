<#
  codex-portable —— Codex 数据整理与迁移工具
  ------------------------------------------------------------------
  零依赖：只需要 Windows PowerShell 5.1 或 PowerShell 7。

  子命令：
    scan       盘点本机 Codex 相关数据，按 A/B/C/D 四类给出体积和去向
    export     按分类打包（默认含隐私、不含缓存、不含密钥）
    restore    在新电脑上还原，自动改写旧用户名的绝对路径
    verify     校验迁移包完整性
    protect    AES-256 加密一个文件（用于隐私包）
    unprotect  解密
    selftest   用假数据完整跑一遍 export → restore → verify

  示例：
    .\codex-portable.ps1 scan
    .\codex-portable.ps1 export -Dest "E:\Codex迁移包"
    .\codex-portable.ps1 restore -Package "D:\Codex迁移包" -NewUser alice
    .\codex-portable.ps1 protect -Path "隐私.tar.gz" -OutFile "隐私.tar.gz.enc"
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('scan','export','restore','verify','protect','unprotect','selftest','help')]
    [string]$Command = 'help',

    [string]$Dest,
    [string]$Package,
    [string]$Profile = $env:USERPROFILE,
    [string]$NewUser = $env:USERNAME,
    [string]$OldUser,
    [string]$Path,
    [string]$OutFile,
    [string]$Password,

    [switch]$SkipPrivate,
    [switch]$IncludeCaches,
    [switch]$IncludeSecrets,
    [switch]$Lean,
    [switch]$Repo,
    [int]$MaxFileMB = 0,
    [switch]$Zip,
    [switch]$DryRun,
    [switch]$Deep,
    [switch]$Json
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$script:ToolVersion = '1.0.0'

# ---------------------------------------------------------------- 输出
function Write-Head { param([string]$Text) Write-Host ""; Write-Host ("== " + $Text) -ForegroundColor Cyan }
function Write-Ok   { param([string]$Text) Write-Host ("   [+] " + $Text) -ForegroundColor Green }
function Write-Warn { param([string]$Text) Write-Host ("   [!] " + $Text) -ForegroundColor Yellow }
function Write-Bad  { param([string]$Text) Write-Host ("   [x] " + $Text) -ForegroundColor Red }
function Write-Item { param([string]$Text) Write-Host ("   - " + $Text) }

# ---------------------------------------------------------------- 路径
function Get-Ctx {
    if ([string]::IsNullOrWhiteSpace($script:Profile)) { throw '拿不到用户目录（-Profile 为空）' }
    $home_ = $script:Profile
    [pscustomobject]@{
        Home        = $home_
        Project     = Join-Path $home_ 'Documents\ChatGPT\New project'
        Knowledge   = Join-Path $home_ 'Documents\ChatGPT\New project\knowledge\deepseek'
        Codex       = Join-Path $home_ '.codex'
        DesktopWork = Join-Path $home_ 'Desktop\codex'
        Desktop     = Join-Path $home_ 'Desktop'
        Startup     = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup'
    }
}

function Get-SizeInfo {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return [pscustomobject]@{ Exists = $false; MB = 0.0; Files = 0 } }
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    if (-not $item) { return [pscustomobject]@{ Exists = $false; MB = 0.0; Files = 0 } }
    if (-not $item.PSIsContainer) {
        return [pscustomobject]@{ Exists = $true; MB = [math]::Round($item.Length / 1MB, 2); Files = 1 }
    }
    $sum = Get-ChildItem -LiteralPath $Path -Recurse -Force -File -ErrorAction SilentlyContinue |
           Measure-Object -Sum Length
    [pscustomobject]@{ Exists = $true; MB = [math]::Round($sum.Sum / 1MB, 2); Files = $sum.Count }
}

function Get-SizePruned {
    param([string]$Path, [string[]]$SkipNames = @())
    if (-not (Test-Path -LiteralPath $Path)) { return [pscustomobject]@{ Exists = $false; MB = 0.0; Files = 0 } }
    $total = [long]0
    $count = 0
    $stack = New-Object System.Collections.Stack
    $stack.Push($Path)
    while ($stack.Count -gt 0) {
        $dir = $stack.Pop()
        try { foreach ($f in [System.IO.Directory]::EnumerateFiles($dir)) { $total += (New-Object System.IO.FileInfo $f).Length; $count++ } } catch { }
        try {
            foreach ($d in [System.IO.Directory]::EnumerateDirectories($dir)) {
                $n = [System.IO.Path]::GetFileName($d)
                if ($SkipNames -contains $n) { continue }
                if ($n -match '^jdk-' -or $n -match '-venv$' -or $n -match '^gradle-') { continue }
                $stack.Push($d)
            }
        } catch { }
    }
    [pscustomobject]@{ Exists = $true; MB = [math]::Round($total / 1MB, 2); Files = $count }
}

function Copy-Tree {
    param(
        [Parameter(Mandatory)][string]$From,
        [Parameter(Mandatory)][string]$To,
        [string[]]$ExcludeDirs = @(),
        [string[]]$ExcludeFiles = @()
    )
    if (-not (Test-Path -LiteralPath $From)) { Write-Warn "跳过（不存在）：$From"; return }
    if ($script:DryRun) { Write-Ok "[试运行] $From  ->  $To"; return }
    New-Item -ItemType Directory -Force -Path $To | Out-Null
    $a = @($From, $To, '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/R:1', '/W:1', '/MT:8')
    if ($ExcludeDirs.Count -gt 0)  { $a += '/XD'; $a += $ExcludeDirs }
    if ($ExcludeFiles.Count -gt 0) { $a += '/XF'; $a += $ExcludeFiles }
    $null = & robocopy @a
    if ($LASTEXITCODE -ge 8) { throw "robocopy 失败（退出码 $LASTEXITCODE）：$From" }
    Write-Ok "$From  ->  $To"
}

$script:JunkDirs  = @('__pycache__', '.pytest_cache', 'node_modules', '.gradle', '.idea', '.venv', 'venv')
$script:JunkFiles = @('*.pyc', '*.pyo', 'Thumbs.db', 'desktop.ini')
$script:CacheNames = @('android-sdk', 'gradle-home', '.cxx', '.cache', '.sandbox-bin', 'plugins',
                       '.tmp', 'node_modules', 'vendor_imports', 'sqlite', 'computer-use',
                       'extract', 'site-packages')
$script:CacheRegex = '^(jdk-\d|gradle-[0-9]|.+-venv$|venv$|\.venv$)'

# ---------------------------------------------------------------- scan
function Get-ProjectSecretFiles {
    param($Ctx)
    if (-not (Test-Path -LiteralPath $Ctx.Project)) { return @() }
    @(Get-ChildItem -LiteralPath $Ctx.Project -Recurse -File -Force -ErrorAction SilentlyContinue -Depth 4 |
        Where-Object {
            $_.FullName -notmatch '\\knowledge\\|\\node_modules\\|\\\.git\\|\\\.recon\\' -and
            ($_.Name -eq 'token.txt' -or ($_.Name -eq 'config.json' -and $_.Directory.Name -eq 'data'))
        } | Select-Object -First 20)
}

function Get-KnownItems {
    param($Ctx)
    $items = @()
    # A 类：项目目录下除知识库外的每个子目录，逐个列出
    if (Test-Path -LiteralPath $Ctx.Project) {
        Get-ChildItem -LiteralPath $Ctx.Project -Directory -Force -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -notin @('knowledge', '.git', '_deepseek_unzip_tmp') } |
            ForEach-Object {
                $items += [pscustomobject]@{ Class='A'; Name=('项目 ' + $_.Name); Path=$_.FullName }
            }
    }
    $items += @(
        [pscustomobject]@{ Class='A'; Name='工作区产物 Desktop\codex'; Path=$Ctx.DesktopWork }
        [pscustomobject]@{ Class='A'; Name='项目约定 AGENTS.md';       Path=(Join-Path $Ctx.Project 'AGENTS.md') }

        [pscustomobject]@{ Class='B'; Name='DeepSeek 聊天记录';        Path=$Ctx.Knowledge }
        [pscustomobject]@{ Class='B'; Name='Codex 会话记录';           Path=(Join-Path $Ctx.Codex 'sessions') }
        [pscustomobject]@{ Class='B'; Name='Codex 归档会话';           Path=(Join-Path $Ctx.Codex 'archived_sessions') }
        [pscustomobject]@{ Class='B'; Name='Codex 长期记忆';           Path=(Join-Path $Ctx.Codex 'memories_1.sqlite') }
        [pscustomobject]@{ Class='B'; Name='Codex 对话历史库';         Path=(Join-Path $Ctx.Codex 'thread_history_1.sqlite') }
        [pscustomobject]@{ Class='B'; Name='Codex 状态库';             Path=(Join-Path $Ctx.Codex 'state_5.sqlite') }

        [pscustomobject]@{ Class='C'; Name='Codex 配置（含 API Key）'; Path=(Join-Path $Ctx.Codex 'config.toml') }
        [pscustomobject]@{ Class='C'; Name='Codex 登录凭据';           Path=(Join-Path $Ctx.Codex 'auth.json') }

        [pscustomobject]@{ Class='D'; Name='Codex 沙箱与插件缓存';     Path=(Join-Path $Ctx.Codex '.sandbox-bin') }
        [pscustomobject]@{ Class='D'; Name='Codex 运行日志';           Path=(Join-Path $Ctx.Codex 'logs_2.sqlite') }
        [pscustomobject]@{ Class='D'; Name='Codex 插件缓存';           Path=(Join-Path $Ctx.Codex 'plugins') }
    )
    # 项目里可能藏着密钥：data\config.json、token.txt 之类
    foreach ($f in (Get-ProjectSecretFiles -Ctx $Ctx)) {
        $items += [pscustomobject]@{ Class='C'; Name=('凭据 ' + $f.Name); Path=$f.FullName }
    }
    $pruneForCode = $script:CacheNames + @('.git')
    foreach ($i in $items) {
        $s = if ($i.Class -eq 'A' -and (Test-Path -LiteralPath $i.Path) -and (Get-Item -LiteralPath $i.Path).PSIsContainer) {
            Get-SizePruned -Path $i.Path -SkipNames $pruneForCode
        } else {
            Get-SizeInfo -Path $i.Path
        }
        $i | Add-Member -NotePropertyName Exists -NotePropertyValue $s.Exists -Force
        $i | Add-Member -NotePropertyName MB -NotePropertyValue $s.MB -Force
        $i | Add-Member -NotePropertyName Files -NotePropertyValue $s.Files -Force
    }
    $items
}

function Find-CacheDirs {
    param($Ctx)
    $found = @()
    $roots = @($Ctx.DesktopWork, $Ctx.Project)
    foreach ($root in $roots) {
        if (-not (Test-Path -LiteralPath $root)) { continue }
        $hits = Get-ChildItem -LiteralPath $root -Recurse -Directory -Force -ErrorAction SilentlyContinue |
                Where-Object {
                    ($script:CacheNames -contains $_.Name -or $_.Name -match $script:CacheRegex) -and
                    $_.FullName -notmatch '\\node_modules\\|\\site-packages\\'
                }
        foreach ($h in $hits) { $found += $h.FullName }
    }
    $found | Sort-Object -Unique
}

function Get-CachePaths {
    param([string]$Root, [switch]$PatternOnly)
    if (-not (Test-Path -LiteralPath $Root)) { return @() }
    @(Get-ChildItem -LiteralPath $Root -Recurse -Directory -Force -ErrorAction SilentlyContinue |
        Where-Object {
            (($script:CacheNames -contains $_.Name) -or ($_.Name -match $script:CacheRegex)) -and
            (-not $PatternOnly -or $_.Name -match $script:CacheRegex) -and
            $_.FullName -notmatch '\\node_modules\\|\\site-packages\\'
        } | Select-Object -ExpandProperty FullName)
}

function Invoke-Scan {
    $ctx = Get-Ctx
    Write-Host "codex-portable $script:ToolVersion  |  盘点 $($ctx.Home)"

    $items = @(Get-KnownItems -Ctx $ctx)
    $labels = @{ A = 'A 代码（可上云）'; B = 'B 隐私（需加密）'; C = 'C 密钥（勿上传）'; D = 'D 缓存（不搬）' }

    $summary = foreach ($cls in 'A','B','C','D') {
        $group = @($items | Where-Object { $_.Class -eq $cls -and $_.Exists })
        [pscustomobject]@{
            Class = $cls
            Label = $labels[$cls]
            MB    = [math]::Round(($group | Measure-Object -Property MB -Sum).Sum, 1)
            Files = ($group | Measure-Object -Property Files -Sum).Sum
            Items = $group.Count
        }
    }

    $cacheDirs = @(Find-CacheDirs -Ctx $ctx)
    $cacheMB = 0.0
    foreach ($d in $cacheDirs) { $cacheMB += (Get-SizeInfo -Path $d).MB }
    if ($cacheDirs.Count -gt 0) {
        $summary[3].MB    = [math]::Round($summary[3].MB + $cacheMB, 1)
        $summary[3].Items = $summary[3].Items + $cacheDirs.Count
    }

    if ($Json) {
        [pscustomobject]@{
            version = $script:ToolVersion
            home    = $ctx.Home
            summary = $summary
            items   = $items
            caches  = $cacheDirs
        } | ConvertTo-Json -Depth 5
        return
    }

    Write-Head '四类数据'
    $summary | Format-Table @{n='类';e={$_.Class}}, Label,
        @{n='体积(MB)';e={$_.MB};align='right'},
        @{n='文件数';e={$_.Files};align='right'},
        @{n='项';e={$_.Items};align='right'} -AutoSize | Out-String -Width 120 | Write-Host

    Write-Head '明细'
    foreach ($cls in 'A','B','C','D') {
        $group = @($items | Where-Object { $_.Class -eq $cls -and $_.Exists })
        if ($group.Count -eq 0) { continue }
        Write-Host ("  [$cls] " + $labels[$cls]) -ForegroundColor DarkGray
        foreach ($g in $group) { Write-Item ("{0,-28} {1,8:N1} MB  {2}" -f $g.Name, $g.MB, $g.Path) }
    }

    if ($cacheDirs.Count -gt 0) {
        Write-Host '  [D] 构建缓存目录' -ForegroundColor DarkGray
        foreach ($d in $cacheDirs) { Write-Item ("{0,8:N1} MB  {1}" -f (Get-SizeInfo -Path $d).MB, $d) }
    }

    Write-Head '大文件（GitHub 单文件上限 100 MB）'
    $big = @()
    foreach ($root in @($ctx.Project, $ctx.DesktopWork, $ctx.Codex)) {
        if (-not (Test-Path -LiteralPath $root)) { continue }
        $big += Get-ChildItem -LiteralPath $root -Recurse -Force -File -ErrorAction SilentlyContinue |
                Where-Object { $_.Length -gt 50MB -and $_.FullName -notmatch '\\node_modules\\|\\android-sdk\\|\\jdk-17' }
    }
    $big = @($big | Sort-Object Length -Descending | Select-Object -First 12)
    if ($big.Count -eq 0) { Write-Item '（没有超过 50 MB 的文件）' }
    foreach ($b in $big) {
        $mark = if ($b.Length -gt 100MB) { '超限' } else { '警告' }
        Write-Item ("{0,8:N1} MB  [{1}]  {2}" -f ($b.Length / 1MB), $mark, $b.FullName)
    }

    Write-Head '建议'
    Write-Item '代码类（A）→ 私有仓库；隐私类（B）→ 加密后上传或移动硬盘；密钥（C）→ 单独带；缓存（D）→ 不搬'
    Write-Item '打包迁移：.\codex-portable.ps1 export -Dest "E:\Codex迁移包"'
}

# ---------------------------------------------------------------- export
function Assert-DestOutsideSources {
    param([string]$Destination, $Ctx)
    $destFull = [System.IO.Path]::GetFullPath($Destination).TrimEnd('\')
    foreach ($root in @($Ctx.Project, $Ctx.Codex, $Ctx.DesktopWork)) {
        if (-not (Test-Path -LiteralPath $root)) { continue }
        $rootFull = (Resolve-Path -LiteralPath $root).Path.TrimEnd('\')
        if ($destFull -ieq $rootFull -or $destFull.StartsWith($rootFull + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "导出目录不能放在源目录里面：`n  目标: $destFull`n  源  : $rootFull`n换一个位置（移动硬盘根目录，或桌面上独立的文件夹）。"
        }
    }
}

function Get-OurShortcutInfo {
    param([string]$LnkPath)
    $sh = New-Object -ComObject WScript.Shell
    try { return $sh.CreateShortcut($LnkPath) } catch { return $null }
}

function Test-IsOurs {
    param([string]$Text)
    foreach ($m in @('Documents\ChatGPT\New project', 'Desktop\codex', '\.codex\')) {
        if ($Text -like ("*" + $m + "*")) { return $true }
    }
    return $false
}

function Invoke-Export {
    $ctx = Get-Ctx
    if (-not $Dest) {
        $removable = $null
        try {
            $removable = [System.IO.DriveInfo]::GetDrives() |
                Where-Object { $_.DriveType -eq 'Removable' -and $_.IsReady -and $_.AvailableFreeSpace -gt 5GB } |
                Select-Object -First 1
        } catch { }
        if ($removable) { $Dest = Join-Path $removable.RootDirectory.FullName 'Codex迁移包' }
        else { $Dest = Join-Path $ctx.Desktop 'Codex迁移包'; Write-Warn "没找到可移动盘，改到：$Dest" }
    }
    if (-not [System.IO.Path]::IsPathRooted($Dest)) { $Dest = Join-Path (Get-Location).Path $Dest }
    Assert-DestOutsideSources -Destination $Dest -Ctx $ctx
    if (Test-Path -LiteralPath $Dest) {
        if (Get-ChildItem -LiteralPath $Dest -Force | Select-Object -First 1) {
            throw "目标目录已存在且非空：$Dest"
        }
    }
    if (-not $DryRun) { New-Item -ItemType Directory -Force -Path $Dest | Out-Null }

    $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Write-Host "codex-portable $script:ToolVersion  |  导出"
    Write-Host "  来源: $($ctx.Home)"
    Write-Host "  目标: $Dest"

    # 01 代码
    Write-Head '01 项目源码'
    $projExclude = $script:JunkDirs + @('knowledge', '.git', '_deepseek_unzip_tmp')
    if ($Lean) { $projExclude += @('.recon') }
    Copy-Tree -From $ctx.Project -To (Join-Path $Dest '01-项目源码\New project') `
              -ExcludeDirs $projExclude -ExcludeFiles $script:JunkFiles

    # 02 隐私
    if (-not $SkipPrivate) {
        Write-Head '02 DeepSeek 聊天记录（隐私）'
        Copy-Tree -From $ctx.Knowledge -To (Join-Path $Dest '02-DeepSeek知识库\deepseek') `
                  -ExcludeDirs $script:JunkDirs -ExcludeFiles $script:JunkFiles
    } else {
        Write-Warn '已跳过隐私数据（-SkipPrivate）'
    }

    # 03 工作区
    Write-Head '03 Codex 工作区产物'
    $workExclude = $script:JunkDirs + @('.git')
    if (-not $IncludeCaches) {
        $workExclude += @('android-sdk', 'gradle-home', 'extract', '.cxx', '.cache', 'site-packages')
        $workExclude += (Get-CachePaths -Root $ctx.DesktopWork -PatternOnly)
    }
    $workExclude += $Dest
    Copy-Tree -From $ctx.DesktopWork -To (Join-Path $Dest '03-Codex工作区\Desktop-codex') `
              -ExcludeDirs $workExclude -ExcludeFiles $script:JunkFiles

    # 04 Codex 数据
    Write-Head '04 Codex 应用数据'
    $outCodex = Join-Path $Dest '04-Codex应用数据\.codex'
    if (-not $DryRun) { New-Item -ItemType Directory -Force -Path $outCodex | Out-Null }
    foreach ($name in @('AGENTS.md','models.json','installation_id','.codex-global-state.json')) {
        $src = Join-Path $ctx.Codex $name
        if (Test-Path -LiteralPath $src) {
            if (-not $DryRun) { Copy-Item -LiteralPath $src -Destination $outCodex -Force }
            Write-Ok $name
        }
    }
    foreach ($sub in @('rules','visualizations')) {
        $src = Join-Path $ctx.Codex $sub
        if (Test-Path -LiteralPath $src) { Copy-Tree -From $src -To (Join-Path $outCodex $sub) -ExcludeDirs $script:JunkDirs -ExcludeFiles $script:JunkFiles }
    }
    if (-not $SkipPrivate) {
        foreach ($sub in @('sessions','archived_sessions')) {
            $src = Join-Path $ctx.Codex $sub
            if (Test-Path -LiteralPath $src) { Copy-Tree -From $src -To (Join-Path $outCodex $sub) }
        }
        foreach ($db in @('thread_history_1.sqlite','memories_1.sqlite','state_5.sqlite','goals_1.sqlite')) {
            $src = Join-Path $ctx.Codex $db
            if (Test-Path -LiteralPath $src) {
                if (-not $DryRun) { Copy-Item -LiteralPath $src -Destination $outCodex -Force }
                Write-Ok $db
            }
        }
    }

    # 05 启动项与快捷方式
    Write-Head '05 开机自启项与快捷方式'
    $outStartup = Join-Path $Dest '05-启动项与快捷方式\Startup'
    $outLnk = Join-Path $Dest '05-启动项与快捷方式\桌面快捷方式'
    if (-not $DryRun) {
        New-Item -ItemType Directory -Force -Path $outStartup, $outLnk | Out-Null
    }
    $others = New-Object System.Collections.Generic.List[string]
    Get-ChildItem -LiteralPath $ctx.Startup -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -in '.vbs', '.bat', '.cmd', '.lnk' -and $_.Name -ne 'desktop.ini' } |
        ForEach-Object {
            $body = ''
            if ($_.Extension -in '.vbs', '.bat', '.cmd') {
                try { $body = Get-Content -LiteralPath $_.FullName -Raw -Encoding Default } catch { }
            }
            if ((Test-IsOurs $body) -or $_.Name -match 'codex') {
                if (-not $DryRun) { Copy-Item -LiteralPath $_.FullName -Destination $outStartup -Force }
                Write-Ok ("自启项: " + $_.Name)
            } else {
                $others.Add("启动项: " + $_.Name)
            }
        }
    Get-ChildItem -LiteralPath $ctx.Desktop -Filter *.lnk -File -ErrorAction SilentlyContinue | ForEach-Object {
        $s = Get-OurShortcutInfo -LnkPath $_.FullName
        $blob = ''
        if ($s) { $blob = "$($s.TargetPath) $($s.Arguments) $($s.WorkingDirectory)" }
        if (Test-IsOurs $blob) {
            if (-not $DryRun) { Copy-Item -LiteralPath $_.FullName -Destination $outLnk -Force }
            Write-Ok ("快捷方式: " + $_.Name)
        } else {
            $others.Add("快捷方式: " + $_.Name + " -> " + $s.TargetPath)
        }
    }
    if (-not $DryRun) {
        $lines = @('# 未随包迁移的启动项与快捷方式', '', '这些与 Codex 无关，需要时在新电脑上自己重建。', '')
        if ($others.Count -eq 0) { $lines += '（无）' } else { $lines += ($others | ForEach-Object { "- $_" }) }
        $lines | Set-Content -LiteralPath (Join-Path $Dest '05-启动项与快捷方式\其他快捷方式清单.md') -Encoding UTF8
    }

    # 06 密钥（默认不导出）
    if ($IncludeSecrets) {
        Write-Head '06 密钥（危险：明文）'
        $outSec = Join-Path $Dest '06-密钥'
        $outCodexSec = Join-Path $outSec 'codex'
        $outProjSec  = Join-Path $outSec 'project'
        if (-not $DryRun) { New-Item -ItemType Directory -Force -Path $outCodexSec, $outProjSec | Out-Null }
        foreach ($name in @('config.toml','auth.json')) {
            $src = Join-Path $ctx.Codex $name
            if (Test-Path -LiteralPath $src) {
                if (-not $DryRun) { Copy-Item -LiteralPath $src -Destination (Join-Path $outCodexSec $name) -Force }
                Write-Warn "明文密钥: .codex\$name"
            }
        }
        foreach ($f in (Get-ProjectSecretFiles -Ctx $ctx)) {
            $rel = $f.FullName.Substring($ctx.Project.Length).TrimStart('\')
            $dst = Join-Path $outProjSec $rel
            if (-not $DryRun) {
                New-Item -ItemType Directory -Force -Path (Split-Path $dst -Parent) | Out-Null
                Copy-Item -LiteralPath $f.FullName -Destination $dst -Force
            }
            Write-Warn "明文密钥: $rel"
        }
    }

    # 超大文件（GitHub 单文件 100 MB 上限）
    if ($MaxFileMB -gt 0 -and -not $DryRun) {
        Write-Head "剔除超过 $MaxFileMB MB 的文件"
        $limit = [long]$MaxFileMB * 1MB
        $huge = @(Get-ChildItem -LiteralPath $Dest -Recurse -File -Force -ErrorAction SilentlyContinue |
                  Where-Object { $_.Length -gt $limit })
        $lines = @("# 已剔除的超大文件（>$MaxFileMB MB）", '',
                   '这些文件体积超过 GitHub 单文件限制，没有放进迁移包。原文件仍在旧电脑上。', '')
        foreach ($h in $huge) {
            $rel = $h.FullName.Substring($Dest.Length).TrimStart('\')
            $lines += ("- {0}  ({1:N1} MB)" -f $rel, ($h.Length / 1MB))
            Remove-Item -LiteralPath $h.FullName
        }
        if ($huge.Count -eq 0) { Write-Ok '没有超限文件' }
        else { Write-Warn ("剔除 $($huge.Count) 个文件") }
        New-Item -ItemType Directory -Force -Path (Join-Path $Dest '00-清单') | Out-Null
        $lines | Set-Content -LiteralPath (Join-Path $Dest '00-清单\已剔除的超大文件.md') -Encoding UTF8
    }

    # 00 清单
    Write-Head '00 生成清单'
    $meta = Join-Path $Dest '00-清单'
    if (-not $DryRun) { New-Item -ItemType Directory -Force -Path $meta | Out-Null }
    $rows = New-Object System.Collections.Generic.List[object]
    if (-not $DryRun) {
        Get-ChildItem -LiteralPath $Dest -Recurse -File -Force -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -notlike "*\00-清单\*" } |
            ForEach-Object {
                $hash = ''
                try { $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash } catch { }
                $rows.Add([pscustomobject]@{
                    Path   = $_.FullName.Substring($Dest.Length).TrimStart('\')
                    SizeMB = [math]::Round($_.Length / 1MB, 3)
                    SHA256 = $hash
                })
            }
        $rows | Sort-Object Path | Export-Csv -LiteralPath (Join-Path $meta '文件清单.csv') -NoTypeInformation -Encoding UTF8

        $envLines = @(
            '# 导出环境快照', '',
            "| 项目 | 值 |", "| --- | --- |",
            "| 工具版本 | $script:ToolVersion |",
            "| 导出时间 | $stamp |",
            "| 计算机名 | $env:COMPUTERNAME |",
            "| 用户名 | $env:USERNAME |",
            "| 用户目录 | $($ctx.Home) |",
            "| 隐私数据 | $(if ($SkipPrivate) { '未包含' } else { '已包含' }) |",
            "| 密钥 | $(if ($IncludeSecrets) { '已包含（明文）' } else { '未包含' }) |",
            "| PowerShell | $($PSVersionTable.PSVersion) |"
        )
        $envLines | Set-Content -LiteralPath (Join-Path $meta '环境信息.md') -Encoding UTF8

        @'
本迁移包可能含有私人内容，注意保管：

  * 02-DeepSeek知识库\      全部聊天记录
  * 04-Codex应用数据\.codex\sessions\   与 Codex 的对话
  * 06-密钥\                明文 API Key（只有加 -IncludeSecrets 时才有）

建议用移动硬盘直接拷贝；走网盘前请先用 codex-portable.ps1 protect 加密。
'@ | Set-Content -LiteralPath (Join-Path $meta '请先读我-敏感信息.txt') -Encoding UTF8
        Write-Ok ("文件清单.csv（" + $rows.Count + " 个文件）")
    }

    if ($Zip -and -not $DryRun) {
        Write-Head '打包压缩'
        $zipPath = $Dest.TrimEnd('\') + '.tar.gz'
        if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
        & tar.exe -a -c -f $zipPath -C (Split-Path $Dest -Parent) (Split-Path $Dest -Leaf)
        if ($LASTEXITCODE -eq 0) { Write-Ok $zipPath } else { Write-Warn 'tar 打包失败' }
    }

    Write-Head '完成'
    Write-Host ("  位置: " + $Dest)
    if ($rows.Count -gt 0) { Write-Host ("  文件: " + $rows.Count) }
    Write-Host "  下一步: 新电脑上运行 restore -Package <该目录>"
}

# ---------------------------------------------------------------- restore
function Backup-File {
    param([string]$FilePath)
    if (-not (Test-Path -LiteralPath $FilePath)) { return }
    $bak = $FilePath + '.bak-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
    if (-not $DryRun) { Copy-Item -LiteralPath $FilePath -Destination $bak -Force }
    Write-Warn ("已备份: " + (Split-Path $bak -Leaf))
}

function Invoke-Restore {
    $ctx = Get-Ctx
    if (-not $Package) { throw '请用 -Package 指定迁移包目录' }
    if (-not (Test-Path -LiteralPath $Package)) { throw "找不到迁移包：$Package" }
    $Package = (Resolve-Path -LiteralPath $Package).Path
    if (-not $OldUser) {
        $infoPath = Join-Path $Package '00-清单\环境信息.md'
        $OldUser = $env:USERNAME
        if (Test-Path -LiteralPath $infoPath) {
            $m = Select-String -LiteralPath $infoPath -Pattern '^\|\s*用户名\s*\|\s*([^|]+)\|' -Encoding UTF8
            if ($m) { $OldUser = $m.Matches[0].Groups[1].Value.Trim() }
        }
    }
    $oldProfile = "C:\Users\$OldUser"
    $newProfile = $ctx.Home.TrimEnd('\')
    $rewrite = ($OldUser -ine $NewUser)

    Write-Host "codex-portable $script:ToolVersion  |  还原"
    Write-Host "  迁移包: $Package"
    Write-Host "  旧用户: $OldUser  ->  新用户: $NewUser"
    if ($rewrite) { Write-Warn '用户名不同，将改写配置文件中的绝对路径' }
    if ($DryRun) { Write-Warn '试运行模式，不写入任何文件' }

    # 地基
    Write-Head '1 地基检查'
    $pyw = Join-Path $ctx.Home '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe'
    $pyOk = Test-Path -LiteralPath $pyw
    if ($pyOk) { Write-Ok "Codex Python: $pyw" }
    else { Write-Bad '未找到 Codex 自带 Python，请先安装并启动一次 Codex 桌面版' }

    Write-Head '2 项目源码'
    $projectDst = $ctx.Project
    Copy-Tree -From (Join-Path $Package '01-项目源码\New project') -To $projectDst
    foreach ($k in @('02-DeepSeek知识库\deepseek', '02-隐私\deepseek')) {
        $src = Join-Path $Package $k
        if (Test-Path -LiteralPath $src) {
            Copy-Tree -From $src -To (Join-Path $projectDst 'knowledge\deepseek')
            break
        }
    }

    Write-Head '3 工作区'
    Copy-Tree -From (Join-Path $Package '03-Codex工作区\Desktop-codex') -To $ctx.DesktopWork

    Write-Head '4 Codex 应用数据'
    $codexSrc = Join-Path $Package '04-Codex应用数据\.codex'
    if (Test-Path -LiteralPath $codexSrc) {
        if (-not $DryRun) { New-Item -ItemType Directory -Force -Path $ctx.Codex | Out-Null }
        foreach ($name in @('AGENTS.md','models.json','installation_id','.codex-global-state.json')) {
            $src = Join-Path $codexSrc $name
            if (Test-Path -LiteralPath $src) {
                Backup-File (Join-Path $ctx.Codex $name)
                if (-not $DryRun) { Copy-Item -LiteralPath $src -Destination $ctx.Codex -Force }
                Write-Ok $name
            }
        }
        foreach ($sub in @('rules','visualizations','sessions')) {
            $src = Join-Path $codexSrc $sub
            if (Test-Path -LiteralPath $src) { Copy-Tree -From $src -To (Join-Path $ctx.Codex $sub) }
        }
        foreach ($db in @('thread_history_1.sqlite','memories_1.sqlite','state_5.sqlite','goals_1.sqlite')) {
            $src = Join-Path $codexSrc $db
            if (Test-Path -LiteralPath $src) {
                Backup-File (Join-Path $ctx.Codex $db)
                if (-not $DryRun) { Copy-Item -LiteralPath $src -Destination $ctx.Codex -Force }
                Write-Ok $db
            }
        }
    }

    $secretSrc = Join-Path $Package '06-密钥'
    if (Test-Path -LiteralPath $secretSrc) {
        Write-Warn '迁移包里含明文密钥，正在放回原位置'
        $codexSec = Join-Path $secretSrc 'codex'
        if (Test-Path -LiteralPath $codexSec) {
            Get-ChildItem -LiteralPath $codexSec -File -Force | ForEach-Object {
                $dst = Join-Path $ctx.Codex $_.Name
                Backup-File $dst
                if (-not $DryRun) {
                    New-Item -ItemType Directory -Force -Path $ctx.Codex | Out-Null
                    Copy-Item -LiteralPath $_.FullName -Destination $dst -Force
                }
                Write-Ok ('.codex\' + $_.Name)
            }
        }
        $projSec = Join-Path $secretSrc 'project'
        if (Test-Path -LiteralPath $projSec) {
            Get-ChildItem -LiteralPath $projSec -Recurse -File -Force | ForEach-Object {
                $rel = $_.FullName.Substring($projSec.Length).TrimStart('\')
                $dst = Join-Path $ctx.Project $rel
                Backup-File $dst
                if (-not $DryRun) {
                    New-Item -ItemType Directory -Force -Path (Split-Path $dst -Parent) | Out-Null
                    Copy-Item -LiteralPath $_.FullName -Destination $dst -Force
                }
                Write-Ok $rel
            }
        }
    }

    if ($rewrite) {
        Write-Head "5 改写路径（$oldProfile -> $newProfile）"
        $ext = @('.ps1','.cmd','.bat','.vbs','.py','.pyw','.json','.toml','.js','.mjs','.html','.css',
                 '.xml','.kt','.kts','.gradle','.ini','.cfg','.yaml','.yml','.txt','.md','.rules')
        $changed = 0
        foreach ($root in @($ctx.Project, $ctx.DesktopWork, $ctx.Codex)) {
            if (-not (Test-Path -LiteralPath $root)) { continue }
            Get-ChildItem -LiteralPath $root -Recurse -File -Force -ErrorAction SilentlyContinue |
                Where-Object { $ext -contains $_.Extension -and $_.Length -lt 5MB -and
                               $_.FullName -notmatch '\\knowledge\\|\\.recon\\|\\node_modules\\|\\android-sdk\\|\\jdk-17' } |
                ForEach-Object {
                    $raw = Get-Content -LiteralPath $_.FullName -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
                    if ($null -ne $raw -and $raw.IndexOf($oldProfile, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
                        $new = $raw -ireplace [regex]::Escape($oldProfile), $newProfile
                        if (-not $DryRun) { Set-Content -LiteralPath $_.FullName -Value $new -NoNewline -Encoding UTF8 }
                        $changed++
                    }
                }
        }
        Write-Ok "改写 $changed 个文件"
    }

    Write-Head '6 开机自启'
    $startupSrc = Join-Path $Package '05-启动项与快捷方式\Startup'
    if (Test-Path -LiteralPath $startupSrc) {
        if (-not $DryRun) { New-Item -ItemType Directory -Force -Path $ctx.Startup | Out-Null }
        Get-ChildItem -LiteralPath $startupSrc -File -ErrorAction SilentlyContinue | ForEach-Object {
            $dst = Join-Path $ctx.Startup $_.Name
            if (-not $DryRun) {
                $text = Get-Content -LiteralPath $_.FullName -Raw -Encoding Default
                if ($rewrite) { $text = $text -ireplace [regex]::Escape($oldProfile), $newProfile }
                Set-Content -LiteralPath $dst -Value $text -NoNewline -Encoding Default
            }
            Write-Ok $_.Name
        }
    }

    Write-Head '7 桌面快捷方式'
    $sh = New-Object -ComObject WScript.Shell
    if (-not $DryRun) {
        # 自动为「目录下有 main.pyw」的项目建快捷方式，不依赖具体项目名
        $made = @()
        if (Test-Path -LiteralPath $ctx.Project) {
            Get-ChildItem -LiteralPath $ctx.Project -Directory -Force -ErrorAction SilentlyContinue |
                Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'main.pyw') } |
                ForEach-Object {
                    $lnk = $sh.CreateShortcut((Join-Path $ctx.Desktop ($_.Name + '.lnk')))
                    $lnk.TargetPath = if ($pyOk) { $pyw } else { 'pythonw.exe' }
                    $lnk.Arguments = '"' + (Join-Path $_.FullName 'main.pyw') + '"'
                    $lnk.WorkingDirectory = $_.FullName
                    $ico = Get-ChildItem -LiteralPath (Join-Path $_.FullName 'assets') -Filter *.ico -File -ErrorAction SilentlyContinue |
                           Select-Object -First 1
                    if ($ico) { $lnk.IconLocation = $ico.FullName + ',0' }
                    $lnk.Save()
                    $made += $_.Name
                    Write-Ok ($_.Name + '.lnk')
                }
        }

        $lnkSrc = Join-Path $Package '05-启动项与快捷方式\桌面快捷方式'
        if (Test-Path -LiteralPath $lnkSrc) {
            Get-ChildItem -LiteralPath $lnkSrc -Filter *.lnk -File | ForEach-Object {
                if ($made -contains $_.BaseName) { return }
                $dst = Join-Path $ctx.Desktop $_.Name
                Copy-Item -LiteralPath $_.FullName -Destination $dst -Force
                if ($rewrite) {
                    try {
                        $s = $sh.CreateShortcut($dst)
                        $s.TargetPath       = $s.TargetPath       -ireplace [regex]::Escape($oldProfile), $newProfile
                        $s.Arguments        = $s.Arguments        -ireplace [regex]::Escape($oldProfile), $newProfile
                        $s.WorkingDirectory = $s.WorkingDirectory -ireplace [regex]::Escape($oldProfile), $newProfile
                        $s.IconLocation     = $s.IconLocation     -ireplace [regex]::Escape($oldProfile), $newProfile
                        $s.Save()
                    } catch { Write-Warn ("修路径失败: " + $_.Name) }
                }
            }
            Write-Ok '其他快捷方式'
        }
    }

    Write-Head '完成，剩余手工步骤'
    Write-Host @"
  1. 浏览器扩展无法跨机器复制，需要在新电脑上装一次
  2. 若迁移包里含本机同步服务，打开 127.0.0.1:8765 安装浏览器脚本
  3. 重启一次电脑，确认开机自启项生效
  4. 双击桌面快捷方式，验证应用能正常启动
"@ -ForegroundColor White
    if (Test-Path -LiteralPath (Join-Path $ctx.Project 'tools')) {
        $srv = Get-ChildItem -LiteralPath (Join-Path $ctx.Project 'tools') -Recurse -Filter 'server.py' -File -ErrorAction SilentlyContinue |
               Select-Object -First 1
        if ($srv) { Write-Item ('检测到本机服务：' + $srv.FullName) }
    }
    if (-not $pyOk) { Write-Bad '注意：没找到 Codex 自带 Python，依赖它的桌面应用可能无法启动' }
}

# ---------------------------------------------------------------- verify
function Invoke-Verify {
    if (-not $Package) { throw '请用 -Package 指定迁移包目录' }
    if (-not (Test-Path -LiteralPath $Package)) { throw "找不到迁移包：$Package" }
    $Package = (Resolve-Path -LiteralPath $Package).Path
    $manifest = Join-Path $Package '00-清单\文件清单.csv'
    Write-Host "codex-portable $script:ToolVersion  |  校验 $Package"

    $problems = 0
    foreach ($d in @('01-项目源码\New project','04-Codex应用数据\.codex','00-清单')) {
        if (Test-Path -LiteralPath (Join-Path $Package $d)) { Write-Ok $d }
        else { Write-Bad ("缺少: " + $d); $problems++ }
    }

    if (-not (Test-Path -LiteralPath $manifest)) {
        Write-Bad '缺少 00-清单\文件清单.csv，无法逐个校验'
        return
    }

    $rows = Import-Csv -LiteralPath $manifest -Encoding UTF8
    $missing = 0; $bad = 0; $checked = 0
    foreach ($r in $rows) {
        $p = Join-Path $Package $r.Path
        if (-not (Test-Path -LiteralPath $p)) { $missing++; if ($missing -le 10) { Write-Warn ("缺失: " + $r.Path) }; continue }
        if ($Deep) {
            $h = (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash
            if ($h -ne $r.SHA256) { $bad++; if ($bad -le 10) { Write-Warn ("校验不符: " + $r.Path) } }
        }
        $checked++
    }
    Write-Ok "清单 $($rows.Count) 条，存在 $checked 条，缺失 $missing 条"
    if ($Deep) { Write-Ok "深度校验：不符 $bad 条" }
    else { Write-Item '（加 -Deep 可逐个复核 SHA256）' }
    if ($missing -gt 0 -or $bad -gt 0) {
        Write-Bad '校验未通过'
        exit 1
    }
    Write-Ok '校验通过'
}

# ---------------------------------------------------------------- protect
function Read-Password {
    if ($script:Password) { return $script:Password }
    $sec = Read-Host '输入密码（不会显示）' -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}

function Invoke-Protect {
    if (-not $Path -or -not $OutFile) { throw '用法: protect -Path <文件> -OutFile <文件.enc>' }
    if (-not (Test-Path -LiteralPath $Path)) { throw "找不到文件：$Path" }
    $pw = Read-Password
    if ([string]::IsNullOrEmpty($pw)) { throw '密码不能为空' }

    $plain = [System.IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $Path).Path)
    $salt = New-Object byte[] 16
    $iv   = New-Object byte[] 16
    $rng  = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($salt); $rng.GetBytes($iv); $rng.Dispose()

    $kdf = New-Object System.Security.Cryptography.Rfc2898DeriveBytes(
        $pw, $salt, 120000, [System.Security.Cryptography.HashAlgorithmName]::SHA256)
    $keyMat = $kdf.GetBytes(64)
    $kdf.Dispose()
    $encKey = $keyMat[0..31]
    $macKey = $keyMat[32..63]

    $aes = [System.Security.Cryptography.Aes]::Create()
    $aes.Mode = 'CBC'; $aes.Padding = 'PKCS7'; $aes.Key = $encKey; $aes.IV = $iv
    $cipher = $aes.CreateEncryptor().TransformFinalBlock($plain, 0, $plain.Length)
    $aes.Dispose()

    $hmac = New-Object System.Security.Cryptography.HMACSHA256(,$macKey)
    $macInput = New-Object byte[] ($salt.Length + $iv.Length + $cipher.Length)
    [Array]::Copy($salt, 0, $macInput, 0, $salt.Length)
    [Array]::Copy($iv, 0, $macInput, $salt.Length, $iv.Length)
    [Array]::Copy($cipher, 0, $macInput, $salt.Length + $iv.Length, $cipher.Length)
    $mac = $hmac.ComputeHash($macInput)
    $hmac.Dispose()

    $outPath = [System.IO.Path]::GetFullPath($OutFile)
    $fs = [System.IO.File]::Create($outPath)
    try {
        $magic = [System.Text.Encoding]::ASCII.GetBytes('CPB1')
        $fs.Write($magic, 0, 4); $fs.Write($salt, 0, 16); $fs.Write($iv, 0, 16); $fs.Write($mac, 0, 32)
        $fs.Write($cipher, 0, $cipher.Length)
    } finally { $fs.Dispose() }
    Write-Ok ("已加密: $outPath  (" + [math]::Round((Get-Item $outPath).Length / 1MB, 1) + " MB)")
    Write-Warn '密码丢了就解不回来，请记到密码管理器里'
}

function Invoke-Unprotect {
    if (-not $Path -or -not $OutFile) { throw '用法: unprotect -Path <文件.enc> -OutFile <文件>' }
    if (-not (Test-Path -LiteralPath $Path)) { throw "找不到文件：$Path" }
    $pw = Read-Password
    $bytes = [System.IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $Path).Path)
    if ($bytes.Length -lt 68) { throw '文件太短，不是本工具生成的密文' }
    $magic = [System.Text.Encoding]::ASCII.GetString($bytes, 0, 4)
    if ($magic -ne 'CPB1') { throw "格式不对（魔数 $magic）" }
    $salt = $bytes[4..19]; $iv = $bytes[20..35]; $mac = $bytes[36..67]
    $cipher = $bytes[68..($bytes.Length - 1)]

    $kdf = New-Object System.Security.Cryptography.Rfc2898DeriveBytes(
        $pw, $salt, 120000, [System.Security.Cryptography.HashAlgorithmName]::SHA256)
    $keyMat = $kdf.GetBytes(64); $kdf.Dispose()
    $encKey = $keyMat[0..31]; $macKey = $keyMat[32..63]

    $hmac = New-Object System.Security.Cryptography.HMACSHA256(,$macKey)
    $macInput = New-Object byte[] ($salt.Length + $iv.Length + $cipher.Length)
    [Array]::Copy($salt, 0, $macInput, 0, 16)
    [Array]::Copy($iv, 0, $macInput, 16, 16)
    [Array]::Copy($cipher, 0, $macInput, 32, $cipher.Length)
    $calc = $hmac.ComputeHash($macInput); $hmac.Dispose()
    $diff = 0
    for ($i = 0; $i -lt 32; $i++) { $diff = $diff -bor ($calc[$i] -bxor $mac[$i]) }
    if ($diff -ne 0) { throw '密码错误，或文件被篡改' }

    $aes = [System.Security.Cryptography.Aes]::Create()
    $aes.Mode = 'CBC'; $aes.Padding = 'PKCS7'; $aes.Key = $encKey; $aes.IV = $iv
    $plain = $aes.CreateDecryptor().TransformFinalBlock($cipher, 0, $cipher.Length)
    $aes.Dispose()
    [System.IO.File]::WriteAllBytes([System.IO.Path]::GetFullPath($OutFile), $plain)
    Write-Ok ("已解密: $OutFile")
}

# ---------------------------------------------------------------- selftest
function New-FakeHome {
    param([string]$Root)
    $spec = @{
        'Documents\ChatGPT\New project\AGENTS.md' = '# 假项目约定'
        'Documents\ChatGPT\New project\demo-app\main.pyw' = 'print("demo")'
        'Documents\ChatGPT\New project\demo-app\data\config.json' = '{"key":"fake"}'
        'Documents\ChatGPT\New project\tools\demo_bridge\server.py' = 'print("server")'
        'Documents\ChatGPT\New project\knowledge\deepseek\index.md' = '# 假知识库'
        '.codex\config.toml' = 'model = "x"'
        '.codex\AGENTS.md' = '# 假全局约定'
        '.codex\rules\default.rules' = 'allow = true'
        '.codex\sessions\s.jsonl' = '{"x":1}'
        '.codex\memories_1.sqlite' = 'fake-db'
        'Desktop\codex\2026-09-26\sample\outputs\demo-app\app.py' = 'print("app")'
        'Desktop\codex\2026-09-26\sample\work\android-sdk\junk.txt' = '应被排除'
        'AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\demo-bridge.vbs' = "backend = ""C:\Users\demo\Documents\ChatGPT\New project\tools\demo_bridge\server.py"""
    }
    foreach ($k in $spec.Keys) {
        $full = Join-Path $Root $k
        New-Item -ItemType Directory -Force -Path (Split-Path $full -Parent) | Out-Null
        Set-Content -LiteralPath $full -Value $spec[$k] -Encoding UTF8
    }
}

function Invoke-Selftest {
    $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ('codex-portable-selftest-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
    $fakeOld = Join-Path $tmp 'oldhome'
    $fakeNew = Join-Path $tmp 'newhome'
    $pkg     = Join-Path $tmp 'pkg'
    New-Item -ItemType Directory -Force -Path $fakeOld, $fakeNew, $pkg | Out-Null
    New-FakeHome -Root $fakeOld

    $oldAppData = $env:APPDATA
    $fail = 0
    try {
        $env:APPDATA = Join-Path $fakeOld 'AppData\Roaming'
        Write-Head 'selftest 1/4 扫描'
        $scanJson = & $PSCommandPath scan -Profile $fakeOld -Json
        if ($scanJson -match '"Class"') { Write-Ok 'scan 输出 JSON' } else { Write-Bad 'scan 输出异常'; $fail++ }

        Write-Head 'selftest 2/4 导出'
        & $PSCommandPath export -Profile $fakeOld -Dest $pkg | Out-Null
        foreach ($p in @('01-项目源码\New project\demo-app\main.pyw',
                         '02-DeepSeek知识库\deepseek\index.md',
                         '04-Codex应用数据\.codex\memories_1.sqlite',
                         '00-清单\文件清单.csv')) {
            if (Test-Path -LiteralPath (Join-Path $pkg $p)) { Write-Ok $p } else { Write-Bad ("缺: " + $p); $fail++ }
        }
        if (Test-Path -LiteralPath (Join-Path $pkg '03-Codex工作区\Desktop-codex\2026-09-26\sample\work\android-sdk')) {
            Write-Bad '构建缓存没有被排除'; $fail++
        } else { Write-Ok '构建缓存已排除' }

        Write-Head 'selftest 2b/4 导出（-Repo 模式）'
        $bigFile = Join-Path $fakeOld 'Desktop\codex\big.bin'
        [System.IO.File]::WriteAllBytes($bigFile, (New-Object byte[] (60MB)))
        $pkgRepo = Join-Path $tmp 'pkg-repo'
        & $PSCommandPath export -Profile $fakeOld -Dest $pkgRepo -Repo | Out-Null
        if (Test-Path -LiteralPath (Join-Path $pkgRepo '03-Codex工作区\Desktop-codex\big.bin')) {
            Write-Bad '超大文件没有被剔除'; $fail++
        } else { Write-Ok '60 MB 文件已剔除' }
        if (Test-Path -LiteralPath (Join-Path $pkgRepo '02-DeepSeek知识库')) {
            Write-Bad '-Repo 模式仍然带上了隐私'; $fail++
        } else { Write-Ok '隐私已排除' }
        if (Test-Path -LiteralPath (Join-Path $pkgRepo '00-清单\已剔除的超大文件.md')) {
            Write-Ok '剔除清单已生成'
        } else { Write-Bad '缺少剔除清单'; $fail++ }

        Write-Head 'selftest 3/4 还原（换用户名）'
        $env:APPDATA = Join-Path $fakeNew 'AppData\Roaming'
        & $PSCommandPath restore -Profile $fakeNew -Package $pkg -NewUser tester -OldUser demo | Out-Null
        $restoredVbs = Join-Path $fakeNew 'AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\demo-bridge.vbs'
        if ((Test-Path -LiteralPath $restoredVbs) -and ((Get-Content -LiteralPath $restoredVbs -Raw) -like "*$fakeNew*")) {
            Write-Ok '自启项已还原且路径已改写'
        } else { Write-Bad '自启项还原/改写失败'; $fail++ }
        if (Test-Path -LiteralPath (Join-Path $fakeNew 'Documents\ChatGPT\New project\knowledge\deepseek\index.md')) {
            Write-Ok '知识库已还原'
        } else { Write-Bad '知识库缺失'; $fail++ }

        Write-Head 'selftest 3b/4 密钥导出与还原'
        $pkgSec = Join-Path $tmp 'pkg-sec'
        & $PSCommandPath export -Profile $fakeOld -Dest $pkgSec -IncludeSecrets | Out-Null
        if ((Test-Path -LiteralPath (Join-Path $pkgSec '06-密钥\codex\config.toml')) -and
            (Test-Path -LiteralPath (Join-Path $pkgSec '06-密钥\project\demo-app\data\config.json'))) {
            Write-Ok '密钥按相对路径打包'
        } else { Write-Bad '密钥打包结构不对'; $fail++ }
        & $PSCommandPath restore -Profile $fakeNew -Package $pkgSec -NewUser demo -OldUser demo | Out-Null
        if ((Test-Path -LiteralPath (Join-Path $fakeNew '.codex\config.toml')) -and
            (Test-Path -LiteralPath (Join-Path $fakeNew 'Documents\ChatGPT\New project\demo-app\data\config.json'))) {
            Write-Ok '密钥已还原到原位置'
        } else { Write-Bad '密钥还原失败'; $fail++ }

        Write-Head 'selftest 4/4 加解密'
        $secretFile = Join-Path $tmp 'secret.txt'
        $encFile = Join-Path $tmp 'secret.enc'
        $decFile = Join-Path $tmp 'secret.out'
        Set-Content -LiteralPath $secretFile -Value 'hello 隐私内容 12345' -Encoding UTF8
        & $PSCommandPath protect -Path $secretFile -OutFile $encFile -Password 'test-pass' | Out-Null
        & $PSCommandPath unprotect -Path $encFile -OutFile $decFile -Password 'test-pass' | Out-Null
        if ((Get-Content -LiteralPath $decFile -Raw) -eq (Get-Content -LiteralPath $secretFile -Raw)) {
            Write-Ok 'AES-256 往返一致'
        } else { Write-Bad '加解密不一致'; $fail++ }
        $bad = $false
        try { & $PSCommandPath unprotect -Path $encFile -OutFile (Join-Path $tmp 'x.out') -Password 'wrong' | Out-Null } catch { $bad = $true }
        if ($bad) { Write-Ok '错误密码被拒绝' } else { Write-Bad '错误密码没被拒绝'; $fail++ }
    } finally {
        $env:APPDATA = $oldAppData
        Remove-Item -LiteralPath $tmp -Recurse -ErrorAction SilentlyContinue
    }

    Write-Head 'selftest 结果'
    if ($fail -eq 0) { Write-Ok '全部通过'; exit 0 } else { Write-Bad "$fail 项失败"; exit 1 }
}

# ---------------------------------------------------------------- help
function Show-Help {
    Write-Host @'
codex-portable —— Codex 数据整理与迁移工具

用法:
  .\codex-portable.ps1 <子命令> [参数]

子命令:
  scan        盘点数据，按 A 代码 / B 隐私 / C 密钥 / D 缓存 分类
  export      打包导出
                -Dest <目录>        导出位置（默认自动找移动盘）
                -SkipPrivate        不含聊天记录与 Codex 会话
                -IncludeCaches      连安卓/JDK 构建缓存一起导出
                -IncludeSecrets     连明文密钥一起导出（危险）
                -Lean               跳过 .recon 反编译素材（省 100 MB）
                -MaxFileMB <n>      剔除超过 n MB 的文件（GitHub 用 50）
                -Repo               适合上传 GitHub：= -SkipPrivate -Lean -MaxFileMB 50
                -Zip                额外打 tar.gz
  restore     在新电脑还原
                -Package <目录>     迁移包位置
                -NewUser <名字>     新电脑用户名（默认当前用户）
                -OldUser <名字>     旧电脑用户名（默认从包里读）
                -DryRun             只看动作不落盘
  verify      校验迁移包
                -Package <目录> [-Deep 逐个核对 SHA256]
  protect     加密文件    -Path <文件> -OutFile <文件.enc> [-Password <密码>]
  unprotect   解密文件    -Path <文件.enc> -OutFile <文件> [-Password <密码>]
  selftest    用假数据跑一遍完整流程

分类模型:
  A 代码   → 私有仓库（GitHub / 码云）
  B 隐私   → 加密后上传，或移动硬盘
  C 密钥   → 永不入库，单独带
  D 缓存   → 不搬，新电脑重装
'@ -ForegroundColor Gray
}

# ---------------------------------------------------------------- 入口
switch ($Command) {
    'scan'      { Invoke-Scan }
    'export'    {
        if ($Repo) {
            $SkipPrivate = $true
            $Lean = $true
            if ($MaxFileMB -le 0) { $MaxFileMB = 50 }
        }
        Invoke-Export
    }
    'restore'   { Invoke-Restore }
    'verify'    { Invoke-Verify }
    'protect'   { Invoke-Protect }
    'unprotect' { Invoke-Unprotect }
    'selftest'  { Invoke-Selftest }
    default     { Show-Help }
}
