#Requires -Version 5.1
<#
    电脑管家 PcToolkit v1.0
    ─────────────────────────────────────────────────────────────
    一个给你自己用的 Windows 体检 / 修复 / 整理工具。

    两种用法：
      1) 双击「启动.bat」→ 打开菜单，按数字选功能（推荐）
      2) 命令行：powershell -ExecutionPolicy Bypass -File PcToolkit.ps1 -Mode Scan

    安全设计：
      · 体检全部是只读的，不改动任何东西
      · 整理文件默认只出方案，确认后才移动，并且记录日志、可以一键撤销
      · 修复前会备份环境变量 / 注册表；垃圾清理只删缓存和临时文件
      · 需要管理员权限的操作会提示你授权，绝不偷偷提权
#>

[CmdletBinding()]
param(
    [ValidateSet('Menu', 'Scan', 'QuickScan', 'Report', 'Organize', 'Duplicates', 'Large', 'Clean', 'DeepClean', 'PrivacyScan', 'PrivacyClean', 'WipeFree', 'Repair', 'Undo')]
    [string]$Mode = 'Menu',

    # 真正执行改动（不加就是"预览/只读"）
    [switch]$Apply,

    # 全自动确认，不再逐个询问（给自动化用，慎用）
    [switch]$Yes,

    # 整理/查重/找大文件的范围
    [string[]]$Targets,

    # 整理方式：Category 按类型 / Date 按年月+类型 / Archive 按年份归档
    [ValidateSet('Category', 'Date', 'Archive')]
    [string]$Layout = 'Category',

    # 只整理 N 天以前改过的文件（0 = 全部都整理）
    [int]$MinAgeDays = 0,

    [switch]$Recurse,
    [switch]$IncludeHidden,
    [switch]$IncludeBrowserCache,
    [switch]$IncludeRecycleBin,
    [switch]$IncludeUpdateCache,
    [switch]$IncludeWinSxS,
    [switch]$IncludeAdvanced,
    [switch]$PrivacyBrowser,
    [switch]$PrivacyWindows,
    [switch]$Secure,
    [string]$Drive = 'C:',
    [switch]$ResetFirewall,
    [switch]$FixDisk,
    [int]$MinMB = 200,
    [int]$MinSizeKB = 64,

    # 报告输出目录（默认放在工具自己的"报告"文件夹）
    [string]$OutputRoot
)

$ErrorActionPreference = 'Continue'

# ---------------------------------------------------------------- 加载模块
$moduleDir = Join-Path $PSScriptRoot 'modules'
foreach ($m in @('Common.ps1', 'Diagnostics.ps1', 'Repairs.ps1', 'Organize.ps1', 'Report.ps1', 'Privacy.ps1')) {
    $p = Join-Path $moduleDir $m
    if (-not (Test-Path -LiteralPath $p)) {
        Write-Host "缺少模块文件：$p" -ForegroundColor Red
        exit 1
    }
    . $p
}

$script:AssumeYes = $Yes.IsPresent
Initialize-Toolkit -OutputRoot $OutputRoot

$script:Opt = [pscustomobject]@{
    Targets             = @()
    Layout              = $Layout
    MinAgeDays          = $MinAgeDays
    Recurse             = $Recurse.IsPresent
    IncludeHidden       = $IncludeHidden.IsPresent
    IncludeBrowserCache = $IncludeBrowserCache.IsPresent
    IncludeRecycleBin   = $IncludeRecycleBin.IsPresent
    IncludeUpdateCache  = $IncludeUpdateCache.IsPresent
    IncludeWinSxS       = $IncludeWinSxS.IsPresent
    ResetFirewall       = $ResetFirewall.IsPresent
    FixDisk             = $FixDisk.IsPresent
    MinMB               = $MinMB
    MinSizeKB           = $MinSizeKB
}
if ($Targets -and $Targets.Count -gt 0) { $script:Opt.Targets = $Targets }

function Get-TargetsOrDefault {
    if ($script:Opt.Targets -and $script:Opt.Targets.Count -gt 0) { return $script:Opt.Targets }
    return (Get-DefaultOrganizeTargets)
}

# ---------------------------------------------------------------- 主菜单

function Show-Banner {
    Write-Host ''
    Write-Host '  ╔══════════════════════════════════════════════════════════╗' -ForegroundColor Cyan
    Write-Host '  ║                                                          ║' -ForegroundColor Cyan
    Write-Host '  ║            电 脑 管 家   PcToolkit  v1.0                 ║' -ForegroundColor Cyan
    Write-Host '  ║        体检 · 修复运行环境 · 整理文件 · 清理垃圾          ║' -ForegroundColor Cyan
    Write-Host '  ║                                                          ║' -ForegroundColor Cyan
    Write-Host '  ╚══════════════════════════════════════════════════════════╝' -ForegroundColor Cyan
    $adminText = '普通权限'
    if (Test-IsAdmin) { $adminText = '管理员权限' }
    Write-Host ("   当前：{0}　·　报告目录：{1}" -f $adminText, $script:ReportDir) -ForegroundColor DarkGray
}

function Show-MainMenu {
    while ($true) {
        Write-Host ''
        Write-Host '  ── 主菜单 ──────────────────────────────────────────────' -ForegroundColor DarkGray
        Write-Host '   [1] 一键体检           只读！看看电脑有什么问题（推荐先做）' -ForegroundColor White
        Write-Host '   [2] 整理文件           下载/桌面/文档按类型归类，可撤销' -ForegroundColor White
        Write-Host '   [3] 重复文件 / 大文件  找出重复副本和占空间的大文件' -ForegroundColor White
        Write-Host '   [4] 修复运行环境       环境变量 · 运行库 · 系统文件 · 网络' -ForegroundColor White
        Write-Host '   [5] 清理垃圾           临时文件 · 缓存 · 回收站 · 组件仓库' -ForegroundColor White
        Write-Host '   [6] 打开报告目录' -ForegroundColor White
        Write-Host '   [7] 撤销上次整理' -ForegroundColor White
        Write-Host '   [0] 退出' -ForegroundColor White
        Write-Host ''
        Write-Host -NoNewline '  请输入编号：' -ForegroundColor Yellow
        $choice = Read-Host
        switch ($choice.Trim()) {
            '1' { $diag = Invoke-Diagnostics; if ($diag) { Write-HealthReports -Diag $diag | Out-Null }; Wait-Continue }
            '2' { Show-OrganizeMenu }
            '3' { Show-SearchMenu }
            '4' { Show-RepairMenu }
            '5' { Show-CleanMenu }
            '6' { Open-PathInShell $script:ReportDir | Out-Null; Write-Info '已打开报告目录。'; Wait-Continue }
            '7' { Invoke-UndoOrganize | Out-Null; Wait-Continue }
            '0' { return }
            'q' { return }
            default { Write-Warn '请输入 0-7 之间的编号。' }
        }
    }
}

function Show-OrganizeMenu {
    while ($true) {
        Write-Host ''
        Write-Host '  ── 整理文件 ────────────────────────────────────────────' -ForegroundColor DarkGray
        $t = Get-TargetsOrDefault
        Write-Host ("   当前范围：{0}" -f ($t -join '、')) -ForegroundColor DarkGray
        Write-Host ("   整理方式：{0}，只整理 {1}" -f $script:Opt.Layout, $(if ($script:Opt.MinAgeDays -eq 0) { '全部文件' } else { "$($script:Opt.MinAgeDays) 天以前的文件" })) -ForegroundColor DarkGray
        Write-Host '   [1] 预览整理方案     只列清单，不动文件' -ForegroundColor White
        Write-Host '   [2] 执行整理         真的移动文件（会记录，可撤销）' -ForegroundColor White
        Write-Host '   [3] 选择整理范围     下载 / 桌面 / 文档 / 自定义路径' -ForegroundColor White
        Write-Host '   [4] 切换整理方式     按类型 / 按年月 / 按年份归档' -ForegroundColor White
        Write-Host '   [5] 排除最近改动的文件（避免整理刚下载的东西）' -ForegroundColor White
        Write-Host '   [6] 撤销上次整理' -ForegroundColor White
        Write-Host '   [0] 返回' -ForegroundColor White
        Write-Host -NoNewline '  请输入编号：' -ForegroundColor Yellow
        $c = Read-Host
        switch ($c.Trim()) {
            '1' { Invoke-OrganizeFiles -Targets (Get-TargetsOrDefault) -Layout $script:Opt.Layout -MinAgeDays $script:Opt.MinAgeDays -IncludeHidden:$script:Opt.IncludeHidden -Recurse:$script:Opt.Recurse | Out-Null; Wait-Continue }
            '2' { Invoke-OrganizeFiles -Targets (Get-TargetsOrDefault) -Layout $script:Opt.Layout -MinAgeDays $script:Opt.MinAgeDays -IncludeHidden:$script:Opt.IncludeHidden -Recurse:$script:Opt.Recurse -Apply | Out-Null; Wait-Continue }
            '3' { Select-OrganizeTargets }
            '4' { Select-OrganizeLayout }
            '5' { Select-MinAgeDays }
            '6' { Invoke-UndoOrganize | Out-Null; Wait-Continue }
            '0' { return }
            default { Write-Warn '请输入 0-6 之间的编号。' }
        }
    }
}

function Select-OrganizeTargets {
    Write-Host ''
    Write-Info '可多选，例如输入 13 表示下载 + 文档：'
    Write-Host '   [1] 下载    [2] 桌面    [3] 文档    [4] 自定义路径' -ForegroundColor White
    Write-Host -NoNewline '  你的选择（直接回车 = 下载 + 桌面 + 文档）：' -ForegroundColor Yellow
    $sel = Read-Host
    if ([string]::IsNullOrWhiteSpace($sel)) {
        $script:Opt.Targets = @()
        Write-Info '已恢复默认范围：下载 + 桌面 + 文档'
        return
    }
    $picked = New-Object System.Collections.ArrayList
    if ($sel -match '1') { [void]$picked.Add((Join-Path $env:USERPROFILE 'Downloads')) }
    if ($sel -match '2') { [void]$picked.Add((Join-Path $env:USERPROFILE 'Desktop')) }
    if ($sel -match '3') { [void]$picked.Add((Join-Path $env:USERPROFILE 'Documents')) }
    if ($sel -match '4') {
        Write-Host -NoNewline '  请输入完整路径：' -ForegroundColor Yellow
        $custom = Read-Host
        if ($custom -and (Test-Path -LiteralPath $custom)) { [void]$picked.Add($custom) }
        else { Write-Warn '这个路径不存在，已忽略。' }
    }
    if ($picked.Count -eq 0) { Write-Warn '没有选中任何位置，保持原范围。'; return }
    $script:Opt.Targets = @($picked)
    Write-Ok ('整理范围已设为：' + ($script:Opt.Targets -join '、'))
}

function Select-OrganizeLayout {
    Write-Host ''
    Write-Host '   [1] 按文件类型分文件夹（推荐）' -ForegroundColor White
    Write-Host '   [2] 按年月 + 类型分文件夹' -ForegroundColor White
    Write-Host '   [3] 全部放进按年份的"归档"文件夹' -ForegroundColor White
    Write-Host -NoNewline '  请输入编号：' -ForegroundColor Yellow
    $c = Read-Host
    switch ($c.Trim()) {
        '1' { $script:Opt.Layout = 'Category' }
        '2' { $script:Opt.Layout = 'Date' }
        '3' { $script:Opt.Layout = 'Archive' }
        default { Write-Warn '没变。'; return }
    }
    Write-Ok "整理方式已设为：$($script:Opt.Layout)"
}

function Select-MinAgeDays {
    Write-Host ''
    Write-Info '例如填 3，表示最近 3 天内改过的文件不动（适合怕整理到正在用的文件）。'
    Write-Host -NoNewline '  请输入天数（0 = 全部都整理）：' -ForegroundColor Yellow
    $c = Read-Host
    $n = 0
    if ([int]::TryParse($c.Trim(), [ref]$n) -and $n -ge 0) {
        $script:Opt.MinAgeDays = $n
        Write-Ok "已设置为：只有 $n 天以前的文件会被整理"
    } else {
        Write-Warn '输入无效，保持不变。'
    }
}

function Show-SearchMenu {
    while ($true) {
        Write-Host ''
        Write-Host '  ── 重复文件 / 大文件 ───────────────────────────────────' -ForegroundColor DarkGray
        Write-Host '   [1] 查找重复文件（按内容比对，只列清单）' -ForegroundColor White
        Write-Host '   [2] 查找重复文件，并把多余副本移到备份文件夹' -ForegroundColor White
        Write-Host '   [3] 查找大文件（列出最占空间的 50 个）' -ForegroundColor White
        Write-Host '   [0] 返回' -ForegroundColor White
        Write-Host -NoNewline '  请输入编号：' -ForegroundColor Yellow
        $c = Read-Host
        switch ($c.Trim()) {
            '1' { Invoke-DuplicateCleanup -Targets (Get-TargetsOrDefault) -MinSizeKB $script:Opt.MinSizeKB -Recurse:$script:Opt.Recurse | Out-Null; Wait-Continue }
            '2' { Invoke-DuplicateCleanup -Targets (Get-TargetsOrDefault) -MinSizeKB $script:Opt.MinSizeKB -Recurse:$script:Opt.Recurse -Apply | Out-Null; Wait-Continue }
            '3' { Invoke-LargeFileScan -Targets (Get-TargetsOrDefault) -MinMB $script:Opt.MinMB; Wait-Continue }
            '0' { return }
            default { Write-Warn '请输入 0-3 之间的编号。' }
        }
    }
}

function Show-RepairMenu {
    while ($true) {
        Write-Host ''
        Write-Host '  ── 修复运行环境 ────────────────────────────────────────' -ForegroundColor DarkGray
        Write-Host '   [1] 环境变量修复     清掉 PATH 里的无效/重复项，补回系统必需目录' -ForegroundColor White
        Write-Host '   [2] 系统文件修复     DISM + SFC，治"缺 dll""功能异常"（较慢）' -ForegroundColor White
        Write-Host '   [3] 运行库检查/安装  VC++ / .NET 是否齐全' -ForegroundColor White
        Write-Host '   [4] 网络组件修复     重置 winsock/IP 协议栈，治能上网但打不开网页' -ForegroundColor White
        Write-Host '   [5] 重置 Windows 更新组件  治更新一直失败' -ForegroundColor White
        Write-Host '   [6] 重建图标缓存     治图标变白纸、缩略图错乱' -ForegroundColor White
        Write-Host '   [7] 磁盘检查         chkdsk /scan' -ForegroundColor White
        Write-Host '   [8] 一键修复         按安全顺序把上面走一遍（会逐步询问）' -ForegroundColor White
        Write-Host '   [9] 先创建系统还原点（强烈建议修复前做）' -ForegroundColor White
        Write-Host '   [0] 返回' -ForegroundColor White
        Write-Host -NoNewline '  请输入编号：' -ForegroundColor Yellow
        $c = Read-Host
        switch ($c.Trim()) {
            '1' { Repair-EnvironmentVariables -Apply | Out-Null; Wait-Continue }
            '2' { Repair-SystemFiles -Apply | Out-Null; Wait-Continue }
            '3' { Show-RuntimeHelp -Install; Wait-Continue }
            '4' { Repair-NetworkStack -Apply -ResetFirewall:$script:Opt.ResetFirewall | Out-Null; Wait-Continue }
            '5' { Repair-UpdateComponents -Apply | Out-Null; Wait-Continue }
            '6' { Repair-IconCache -Apply | Out-Null; Wait-Continue }
            '7' { Repair-DiskCheck -Apply -Fix:$script:Opt.FixDisk | Out-Null; Wait-Continue }
            '8' { Repair-FullRun -Apply | Out-Null; Wait-Continue }
            '9' { New-RestorePointSafe | Out-Null; Wait-Continue }
            '0' { return }
            default { Write-Warn '请输入 0-9 之间的编号。' }
        }
    }
}

function Show-CleanMenu {
    while ($true) {
        Write-Host ''
        Write-Host '  ── 清理垃圾 ────────────────────────────────────────────' -ForegroundColor DarkGray
        Write-Host ("   浏览器缓存：{0}　回收站：{1}　更新缓存：{2}　组件仓库：{3}" -f `
                $(if ($script:Opt.IncludeBrowserCache) { '清' } else { '保留' }), `
                $(if ($script:Opt.IncludeRecycleBin) { '清' } else { '保留' }), `
                $(if ($script:Opt.IncludeUpdateCache) { '清' } else { '保留' }), `
                $(if ($script:Opt.IncludeWinSxS) { '清' } else { '保留' })) -ForegroundColor DarkGray
        Write-Host '   [1] 预览可清理的体积（安全，只统计）' -ForegroundColor White
        Write-Host '   [2] 执行清理（临时文件 + 错误报告 + 转储）' -ForegroundColor White
        Write-Host '   [3] 切换：是否清浏览器缓存' -ForegroundColor White
        Write-Host '   [4] 切换：是否清空回收站' -ForegroundColor White
        Write-Host '   [5] 切换：是否清 Windows 更新缓存' -ForegroundColor White
        Write-Host '   [6] 切换：是否清理系统组件仓库 WinSxS（省几个 GB）' -ForegroundColor White
        Write-Host '   [0] 返回' -ForegroundColor White
        Write-Host -NoNewline '  请输入编号：' -ForegroundColor Yellow
        $c = Read-Host
        switch ($c.Trim()) {
            '1' {
                Clear-TempFiles -IncludeBrowserCache:$script:Opt.IncludeBrowserCache -IncludeRecycleBin:$script:Opt.IncludeRecycleBin -IncludeUpdateCache:$script:Opt.IncludeUpdateCache | Out-Null
                Wait-Continue
            }
            '2' {
                if (Assert-Admin '清理 Windows 临时目录需要管理员权限（用户临时文件不需要）') {
                    Clear-TempFiles -Apply -IncludeBrowserCache:$script:Opt.IncludeBrowserCache -IncludeRecycleBin:$script:Opt.IncludeRecycleBin -IncludeUpdateCache:$script:Opt.IncludeUpdateCache -IncludeWinSxS:$script:Opt.IncludeWinSxS | Out-Null
                }
                Wait-Continue
            }
            '3' { $script:Opt.IncludeBrowserCache = -not $script:Opt.IncludeBrowserCache; Write-Ok ("浏览器缓存：{0}" -f $(if ($script:Opt.IncludeBrowserCache) { '清理' } else { '保留' })) }
            '4' { $script:Opt.IncludeRecycleBin = -not $script:Opt.IncludeRecycleBin; Write-Ok ("回收站：{0}" -f $(if ($script:Opt.IncludeRecycleBin) { '清空' } else { '保留' })) }
            '5' { $script:Opt.IncludeUpdateCache = -not $script:Opt.IncludeUpdateCache; Write-Ok ("更新缓存：{0}" -f $(if ($script:Opt.IncludeUpdateCache) { '清理' } else { '保留' })) }
            '6' { $script:Opt.IncludeWinSxS = -not $script:Opt.IncludeWinSxS; Write-Ok ("组件仓库：{0}" -f $(if ($script:Opt.IncludeWinSxS) { '清理' } else { '保留' })) }
            '0' { return }
            default { Write-Warn '请输入 0-6 之间的编号。' }
        }
    }
}

# ---------------------------------------------------------------- 命令行模式

function Invoke-CliMode {
    switch ($Mode) {
        'Scan'      { $d = Invoke-Diagnostics; if ($d) { Write-HealthReports -Diag $d | Out-Null } }
        'QuickScan' { $d = Invoke-Diagnostics -Quick; if ($d) { Write-HealthReports -Diag $d | Out-Null } }
        'Report'    { $d = Invoke-Diagnostics; if ($d) { $p = Write-HealthReports -Diag $d -NoOpen; Write-Host $p.Html } }
        'Organize'  { Invoke-OrganizeFiles -Targets (Get-TargetsOrDefault) -Layout $script:Opt.Layout -MinAgeDays $script:Opt.MinAgeDays -IncludeHidden:$script:Opt.IncludeHidden -Recurse:$script:Opt.Recurse -Apply:$Apply | Out-Null }
        'Duplicates' {
            if ($Apply) { Invoke-DuplicateCleanup -Targets (Get-TargetsOrDefault) -MinSizeKB $script:Opt.MinSizeKB -Recurse:$script:Opt.Recurse -Apply | Out-Null }
            else { Invoke-DuplicateCleanup -Targets (Get-TargetsOrDefault) -MinSizeKB $script:Opt.MinSizeKB -Recurse:$script:Opt.Recurse | Out-Null }
        }
        'Large'     { Invoke-LargeFileScan -Targets (Get-TargetsOrDefault) -MinMB $script:Opt.MinMB | Out-Null }
        'Clean'     { Clear-TempFiles -Apply:$Apply -IncludeBrowserCache:$script:Opt.IncludeBrowserCache -IncludeRecycleBin:$script:Opt.IncludeRecycleBin -IncludeUpdateCache:$script:Opt.IncludeUpdateCache -IncludeWinSxS:$script:Opt.IncludeWinSxS | Out-Null }
        'DeepClean' { Clear-DeepJunk -Apply:$Apply -IncludeAdvanced:$IncludeAdvanced | Out-Null }
        'PrivacyScan' {
            $r = Get-PrivacyReport -IncludeBrowser -IncludeWindows
            $r.Items | Where-Object { $_.Exists } | Select-Object Name, @{n='MB';e={[math]::Round($_.Bytes/1MB,2)}}, Items | Format-Table -AutoSize
            Write-Host ('隐私痕迹合计：' + (Format-Bytes $r.TotalBytes) + '（' + $r.TotalItems + ' 项）')
        }
        'PrivacyClean' {
            $incB = $PrivacyBrowser -or (-not $PrivacyBrowser -and -not $PrivacyWindows)
            $incW = $PrivacyWindows -or (-not $PrivacyBrowser -and -not $PrivacyWindows)
            Clear-PrivacyTraces -Apply:$Apply -IncludeBrowser:$incB -IncludeWindows:$incW -Secure:$Secure | Out-Null
        }
        'WipeFree'  { Invoke-FreeSpaceWipe -Drive $Drive }
        'Repair'    {
            if ($Apply) { Repair-FullRun -Apply | Out-Null }
            else {
                Repair-EnvironmentVariables | Out-Null
                Repair-SystemFiles | Out-Null
                Show-RuntimeHelp | Out-Null
                Repair-NetworkStack | Out-Null
                Repair-UpdateComponents | Out-Null
                Repair-IconCache | Out-Null
                Repair-DiskCheck -Fix:$script:Opt.FixDisk | Out-Null
            }
        }
        'Undo'      { Invoke-UndoOrganize -Apply:$Apply | Out-Null }
    }
}

# ---------------------------------------------------------------- 入口

if ($Mode -eq 'Menu') {
    Show-Banner
    Write-Info ("日志文件：{0}" -f $script:LogFile)
    Show-MainMenu
    Write-Host ''
    Write-Info '再见！记得定期跑一次"一键体检"。'
} else {
    Invoke-CliMode
}
