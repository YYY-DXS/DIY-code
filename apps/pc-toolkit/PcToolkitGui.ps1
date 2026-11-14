#Requires -Version 5.1
<#
    电脑管家 PcToolkit - 图形界面版
    ─────────────────────────────────────────────────────────────
    普通使用：双击「启动.bat」（或桌面快捷方式）就会打开这个窗口。
    命令行启动：powershell -ExecutionPolicy Bypass -File PcToolkitGui.ps1
    开发者自检：powershell -ExecutionPolicy Bypass -File PcToolkitGui.ps1 -SelfTest

    界面只负责"问你要做什么"和"把引擎的输出显示出来"；
    真正的体检 / 修复 / 整理 / 清理逻辑都在 modules\*.ps1 里（命令行版共用同一套代码）。
#>

[CmdletBinding()]
param(
    # 报告输出目录（默认放在工具自己的「报告」文件夹）
    [string]$OutputRoot,
    # 内部自检：跑一次快速体检并把结果写进 _记录\自检结果.txt
    [switch]$SelfTest
)

$ErrorActionPreference = 'Stop'

$script:GuiRoot       = $PSScriptRoot
if (-not $script:GuiRoot) { $script:GuiRoot = (Get-Location).ProviderPath }
$script:ModuleDir     = Join-Path $script:GuiRoot 'modules'
$script:XamlPath      = Join-Path $script:GuiRoot 'ui\MainWindow.xaml'
$script:IconPath      = Join-Path $script:GuiRoot 'assets\app.ico'
$script:StateDir      = Join-Path $script:GuiRoot '_记录'
$script:OutputRootArg = $OutputRoot
$script:GuiLog        = Join-Path $script:StateDir ('GUI日志_{0}.log' -f (Get-Date -Format 'yyyyMMdd'))

try {
    if (-not (Test-Path -LiteralPath $script:StateDir)) { New-Item -ItemType Directory -Path $script:StateDir -Force | Out-Null }
} catch { }

function Write-GuiLog {
    param([string]$Text)
    try {
        Add-Content -LiteralPath $script:GuiLog -Value ('{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Text) -Encoding UTF8
    } catch { }
}

function Show-GuiMessage {
    param([string]$Text, [string]$Title = '电脑管家', [string]$Icon = 'Information')
    try {
        [void][System.Windows.MessageBox]::Show($Text, $Title, 'OK', $Icon)
    } catch {
        try { [void][System.Windows.Forms.MessageBox]::Show($Text, $Title) } catch { Write-Host $Text }
    }
}

function Show-GuiConfirm {
    param([string]$Text, [string]$Title = '确认')
    if ($script:SelfTest) { return $true }
    try {
        return ([System.Windows.MessageBox]::Show($Text, $Title, 'YesNo', 'Warning') -eq 'Yes')
    } catch { return $false }
}

try {
    Add-Type -AssemblyName PresentationFramework
    Add-Type -AssemblyName PresentationCore
    Add-Type -AssemblyName WindowsBase
    Add-Type -AssemblyName System.Xaml
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
} catch {
    Write-GuiLog "加载界面组件失败: $($_ | Out-String)"
    Show-GuiMessage "无法加载 Windows 界面组件。" -Title '电脑管家启动失败' -Icon 'Error'
    exit 1
}

try {
    if (-not (Test-Path -LiteralPath $script:XamlPath)) { throw "找不到界面文件：$($script:XamlPath)" }
    $xamlDoc = [xml](Get-Content -LiteralPath $script:XamlPath -Raw -Encoding UTF8)
    $xamlReader = New-Object System.Xml.XmlNodeReader $xamlDoc
    $window = [System.Windows.Markup.XamlReader]::Load($xamlReader)
} catch {
    Write-GuiLog "加载 XAML 失败: $($_ | Out-String)"
    Show-GuiMessage ("界面文件加载失败：`n" + $_.Exception.Message + "`n`n请确认 ui\MainWindow.xaml 没有被改动或删除。") -Title '电脑管家启动失败' -Icon 'Error'
    exit 1
}

# ================================================================ 控件引用
$script:Ctl = @{}
$ctlNames = @(
    'NavList', 'AdminBadge', 'AdminText', 'AdminButton', 'OpenReportButton', 'ExitButton',
    'PageScan', 'ChkQuick', 'BtnScan', 'BtnOpenLastReport', 'ScoreValue', 'ScoreGrade', 'ScoreHint',
    'PageOrganize', 'ChkDownloads', 'ChkDesktop', 'ChkDocuments', 'ChkCustom', 'BtnBrowse', 'TxtCustomPath',
    'CmbLayout', 'TxtMinAge', 'BtnPreviewOrganize', 'BtnApplyOrganize', 'BtnUndoOrganize',
    'PageClean', 'ChkCleanBrowser', 'ChkCleanRecycle', 'ChkCleanUpdate', 'ChkCleanWinSxS',
    'BtnPreviewClean', 'BtnApplyClean',
    'PageRepair', 'BtnRestorePoint', 'BtnEnvRepair', 'BtnSysRepair', 'BtnRuntime',
    'BtnNetRepair', 'BtnUpdateRepair', 'BtnIconRepair', 'BtnDiskCheck', 'BtnFullRepair',
    'PageFind', 'ChkRecurse', 'TxtMinSizeKB', 'TxtMinMB', 'BtnFindDup', 'BtnMoveDup', 'BtnFindLarge',
    'PageHelp', 'BtnMakeShortcut', 'BtnOpenHelp', 'BtnConsoleVersion', 'BtnOpenToolFolder',
    'TaskLabel', 'ProgBar', 'BtnToggleLog', 'BtnStop', 'BtnClearLog', 'BtnCopyLog', 'LogBox'
)
foreach ($n in $ctlNames) { $script:Ctl[$n] = $window.FindName($n) }

$pageOrder = @('PageScan', 'PageOrganize', 'PageClean', 'PageRepair', 'PageFind', 'PageHelp')

try {
    if (Test-Path -LiteralPath $script:IconPath) {
        $window.Icon = [System.Windows.Media.Imaging.BitmapFrame]::Create([uri]$script:IconPath)
        $appIcon = $window.FindName('AppIcon')
        if ($appIcon) { $appIcon.Source = $window.Icon }
    }
} catch { Write-GuiLog "设置窗口图标失败: $($_.Exception.Message)" }

# 快捷方式模块（图形界面里也能建桌面图标）
try {
    $shortcutModule = Join-Path $script:ModuleDir 'Shortcut.ps1'
    if (Test-Path -LiteralPath $shortcutModule) { . $shortcutModule }
} catch { Write-GuiLog "加载快捷方式模块失败: $($_.Exception.Message)" }

# ================================================================ 日志显示
$script:BrushCache = @{}
function Get-LogBrush {
    param([string]$Hex)
    if (-not $script:BrushCache.ContainsKey($Hex)) {
        $color = [System.Windows.Media.Color][System.Windows.Media.ColorConverter]::ConvertFromString($Hex)
        $brush = New-Object System.Windows.Media.SolidColorBrush -ArgumentList $color
        $brush.Freeze()
        $script:BrushCache[$Hex] = $brush
    }
    return $script:BrushCache[$Hex]
}

$logDoc = New-Object System.Windows.Documents.FlowDocument
$logPara = New-Object System.Windows.Documents.Paragraph
$logPara.Margin = New-Object System.Windows.Thickness 0
[void]$logDoc.Blocks.Add($logPara)
$script:Ctl['LogBox'].Document = $logDoc
$script:LogPara = $logPara
$script:LogLineCount = 0

function Add-LogLine {
    param([string]$Text, [string]$Level = 'INFO')
    if ($null -eq $Text) { $Text = '' }
    $color = '#374151'
    if ($Level -eq 'ERR') { $color = '#DC2626' }
    elseif ($Level -eq 'WARN') { $color = '#B45309' }
    else {
        if     ($Text -match '^\s*\[问题\]') { $color = '#DC2626' }
        elseif ($Text -match '^\s*\[注意\]') { $color = '#B45309' }
        elseif ($Text -match '^\s*\[OK\]')   { $color = '#15803D' }
        elseif ($Text -match '^\s*\[跳过\]') { $color = '#9AA0A6' }
        elseif ($Text -match '^\s*>>')       { $color = '#2F6FED' }
        elseif ($Text -match '═{3,}')        { $color = '#0E7490' }
        elseif ($Text -match '^\s*▎')        { $color = '#0E7490' }
    }
    if ($Text -ne '') {
        $run = New-Object System.Windows.Documents.Run -ArgumentList $Text
        $run.Foreground = Get-LogBrush $color
        [void]$script:LogPara.Inlines.Add($run)
    }
    [void]$script:LogPara.Inlines.Add((New-Object System.Windows.Documents.LineBreak))
    $script:LogLineCount++
    if ($script:LogPara.Inlines.Count -gt 9000) {
        while ($script:LogPara.Inlines.Count -gt 7000) {
            $script:LogPara.Inlines.Remove($script:LogPara.Inlines.FirstInline)
        }
    }
    if (-not $script:SelfTest) {
        try { $script:Ctl['LogBox'].ScrollToEnd() } catch { }
    }
}

function Clear-Log {
    $script:LogPara.Inlines.Clear()
    $script:LogLineCount = 0
}

function Get-LogText {
    try {
        $range = New-Object System.Windows.Documents.TextRange($script:LogPara.ContentStart, $script:LogPara.ContentEnd)
        return $range.Text
    } catch { return '' }
}

# ================================================================ 任务运行环境
$script:TaskQueue     = New-Object System.Collections.Concurrent.ConcurrentQueue[object]
$script:Running       = $false
$script:CurrentPs     = $null
$script:CurrentHandle = $null
$script:TaskName      = ''
$script:LastHtml      = $null
$script:LastResult    = @{}
$script:SelfTestLog   = New-Object System.Collections.ArrayList
$script:SelfTestDone  = $false
$script:CustomPath    = $null
$script:DetachOnClose = $false
$script:LockFile      = Join-Path $script:StateDir '任务运行中.lock'

function Get-BusyRepairProcesses {
    <#  系统里正在跑 DISM / SFC / 磁盘检查 时返回它们的名字  #>
    $found = New-Object System.Collections.ArrayList
    foreach ($n in @('Dism', 'DismHost', 'sfc', 'chkdsk')) {
        try {
            foreach ($p in (Get-Process -Name $n -ErrorAction SilentlyContinue)) {
                [void]$found.Add(("{0}(PID {1})" -f $p.Name, $p.Id))
            }
        } catch { }
    }
    return @($found)
}

function Get-OtherTaskLock {
    <#  别的窗口正在跑任务时返回它的信息；过期锁会自动清掉  #>
    if (-not (Test-Path -LiteralPath $script:LockFile)) { return $null }
    $data = $null
    try { $data = Get-Content -LiteralPath $script:LockFile -Raw -Encoding UTF8 | ConvertFrom-Json } catch { return $null }
    $otherPid = 0
    if ($data -and $data.pid) { [void][int]::TryParse("$($data.pid)", [ref]$otherPid) }
    if ($otherPid -le 0 -or $otherPid -eq $PID) { return $null }
    $alive = $false
    try { $alive = $null -ne (Get-Process -Id $otherPid -ErrorAction Stop) } catch { $alive = $false }
    if (-not $alive) {
        try { Remove-Item -LiteralPath $script:LockFile -Force } catch { }
        return $null
    }
    return $data
}

function Set-TaskLock {
    param([string]$Title)
    try {
        $payload = [pscustomobject]@{
            pid   = $PID
            title = $Title
            start = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
            user  = $env:USERNAME
        }
        [System.IO.File]::WriteAllText($script:LockFile, ($payload | ConvertTo-Json), (New-Object System.Text.UTF8Encoding($true)))
    } catch { }
}

function Clear-TaskLock {
    try {
        if (-not (Test-Path -LiteralPath $script:LockFile)) { return }
        $data = $null
        try { $data = Get-Content -LiteralPath $script:LockFile -Raw -Encoding UTF8 | ConvertFrom-Json } catch { }
        if (-not $data -or -not $data.pid -or "$($data.pid)" -eq "$PID") {
            Remove-Item -LiteralPath $script:LockFile -Force -ErrorAction SilentlyContinue
        }
    } catch { }
}

function ConvertTo-PSLiteral {
    param($Value)
    if ($Value -is [bool]) { if ($Value) { return '$true' } else { return '$false' } }
    if ($Value -is [int] -or $Value -is [long] -or $Value -is [double]) {
        return (Convert.ToString($Value, [System.Globalization.CultureInfo]::InvariantCulture))
    }
    if ($null -eq $Value) { return '$null' }
    return "'" + (("$Value") -replace "'", "''") + "'"
}

function New-EngineScript {
    param([hashtable]$Parameters, [string]$Body)
    $sb = New-Object System.Text.StringBuilder
    [void]$sb.AppendLine('$ErrorActionPreference = ''Continue''')
    foreach ($m in @('Common', 'Diagnostics', 'Repairs', 'Organize', 'Report')) {
        [void]$sb.AppendLine((". '{0}\{1}.ps1'" -f $script:ModuleDir, $m))
    }
    [void]$sb.AppendLine('$script:AssumeYes = $true')
    [void]$sb.AppendLine('function Assert-Admin { param([string]$Why) if (Test-IsAdmin) { return $true }; Write-Err ("这一步需要管理员权限：" + $Why); return $false }')
    if ($script:OutputRootArg) {
        [void]$sb.AppendLine('Initialize-Toolkit -OutputRoot ' + (ConvertTo-PSLiteral $script:OutputRootArg))
    } else {
        [void]$sb.AppendLine('Initialize-Toolkit')
    }
    if ($Parameters) {
        foreach ($k in $Parameters.Keys) {
            [void]$sb.AppendLine(('${0} = {1}' -f $k, (ConvertTo-PSLiteral $Parameters[$k])))
        }
    }
    [void]$sb.AppendLine($Body)
    return $sb.ToString()
}

function Register-StreamHandlers {
    param($Ps)
    $Ps.Streams.Information.add_DataAdded({
        param($sender, $e)
        try {
            $item = $sender[$e.Index]
            $msg = ''
            if ($item.MessageData) { $msg = $item.MessageData.ToString() } else { $msg = "$item" }
            $script:TaskQueue.Enqueue(@{ Kind = 'log'; Text = $msg; Level = 'INFO' })
        } catch { }
    })
    $Ps.Streams.Warning.add_DataAdded({
        param($sender, $e)
        try { $script:TaskQueue.Enqueue(@{ Kind = 'log'; Text = "$($sender[$e.Index].Message)"; Level = 'WARN' }) } catch { }
    })
    $Ps.Streams.Error.add_DataAdded({
        param($sender, $e)
        try { $script:TaskQueue.Enqueue(@{ Kind = 'log'; Text = "$($sender[$e.Index])"; Level = 'ERR' }) } catch { }
    })
}

function Get-AllButtons {
    param($Parent)
    $list = New-Object System.Collections.ArrayList
    try {
        foreach ($child in [System.Windows.LogicalTreeHelper]::GetChildren($Parent)) {
            if ($child -is [System.Windows.Controls.Button]) { [void]$list.Add($child) }
            if ($child -is [System.Windows.DependencyObject]) {
                foreach ($b in (Get-AllButtons $child)) { [void]$list.Add($b) }
            }
        }
    } catch { }
    return @($list)
}

$script:AlwaysEnabled = @('BtnStop', 'BtnCopyLog', 'BtnClearLog', 'BtnToggleLog', 'ExitButton', 'AdminButton')
$script:ActionButtons = @(Get-AllButtons $window | Where-Object { $_.Name -and ($script:AlwaysEnabled -notcontains $_.Name) })

function Set-UiBusy {
    param([bool]$Busy)
    if ($Busy) {
        $script:Ctl['ProgBar'].Visibility = 'Visible'
        $script:Ctl['TaskLabel'].Text = '正在执行...'
    } else {
        $script:Ctl['ProgBar'].Visibility = 'Hidden'
        $script:Ctl['TaskLabel'].Text = '就绪'
    }
    $script:Ctl['BtnStop'].IsEnabled = $Busy
    foreach ($b in $script:ActionButtons) { try { $b.IsEnabled = -not $Busy } catch { } }
}

function Start-EngineTask {
    param([string]$Title, [string]$Body, [hashtable]$Parameters = @{}, [switch]$RepairTask)
    if ($script:Running) { Show-GuiMessage '已经有一个任务在跑了，等它结束再点别的。'; return }

    # 防重复执行：别的窗口在跑任务时先问一句
    $other = Get-OtherTaskLock
    if ($other) {
        $msg = "另一个「电脑管家」窗口正在执行任务：`n`n  $($other.title)（PID $($other.pid)，开始于 $($other.start)）`n`n两边同时执行可能会互相干扰（比如同时移动同一批文件）。`n确定还要现在开始吗？"
        if (-not (Show-GuiConfirm $msg '任务冲突')) { Add-LogLine '已取消（另一个窗口正在执行任务）。' 'WARN'; return }
    }

    # 修复类任务：如果系统里已经有 DISM / SFC / 磁盘检查在跑，提醒一句
    if ($RepairTask) {
        $busy = Get-BusyRepairProcesses
        if ($busy.Count -gt 0) {
            $msg = "检测到系统里正在运行：`n`n  " + ($busy -join "`n  ") + "`n`n可能是你另一个窗口（命令行版）在修复，也可能是 Windows 自己在更新。`n两个修复同时跑容易互相干扰（例如两个 DISM 抢同一个系统映像）。`n`n建议等它结束再开始。要强行继续吗？"
            if (-not (Show-GuiConfirm $msg '系统正在修复中')) {
                Add-LogLine ('已取消：检测到 ' + ($busy -join '、') + '，等它结束再开始更安全。') 'WARN'
                return
            }
        }
    }

    $script:Running = $true
    $script:TaskName = $Title
    Set-UiBusy $true
    Set-TaskLock $Title
    Add-LogLine ''
    Add-LogLine ('═══════ 任务：' + $Title + '　' + (Get-Date -Format 'HH:mm:ss') + ' ═══════')
    $code = New-EngineScript -Parameters $Parameters -Body $Body
    Write-GuiLog "==== 启动任务：$Title ===="
    $ps = [powershell]::Create()
    [void]$ps.AddScript($code)
    Register-StreamHandlers -Ps $ps
    try {
        $handle = $ps.BeginInvoke()
    } catch {
        Add-LogLine ('任务启动失败：' + $_.Exception.Message) 'ERR'
        Write-GuiLog "任务启动失败: $($_ | Out-String)"
        $script:Running = $false
        Set-UiBusy $false
        Clear-TaskLock
        try { $ps.Dispose() } catch { }
        return
    }
    $script:CurrentPs = $ps
    $script:CurrentHandle = $handle
}

function Apply-ResultMarker {
    param([string]$Line)
    $payload = $Line.Substring(11)
    $data = @{}
    foreach ($part in $payload.Split('|')) {
        $idx = $part.IndexOf('=')
        if ($idx -gt 0) { $data[$part.Substring(0, $idx)] = $part.Substring($idx + 1) }
    }
    $script:LastResult = $data
    if ($data.ContainsKey('score')) {
        $score = 0
        [void][int]::TryParse($data['score'], [ref]$score)
        $color = '#15803D'
        if ($score -lt 90) { $color = '#B45309' }
        if ($score -lt 75) { $color = '#EA580C' }
        if ($score -lt 60) { $color = '#DC2626' }
        $script:Ctl['ScoreValue'].Text = "$score"
        $script:Ctl['ScoreValue'].Foreground = Get-LogBrush $color
        $grade = ''
        if ($data.ContainsKey('grade')) { $grade = $data['grade'] }
        $script:Ctl['ScoreGrade'].Text = "健康分 / 100　等级 $grade"
        $script:Ctl['ScoreHint'].Text = ('体检完成：{0} 分（等级 {1}）。主要问题和修复顺序看下面的日志；完整报告在「报告」文件夹里，HTML 可以用浏览器打开。' -f $score, $grade)
    }
    if ($data.ContainsKey('html')) {
        $script:LastHtml = $data['html']
        Write-GuiLog "报告: $($data['html'])"
    }
}

function Show-TaskLine {
    param([string]$Text, [string]$Level = 'INFO')
    if ($Text -like '##RESULT##*') { Apply-ResultMarker -Line $Text; return }
    Add-LogLine -Text $Text -Level $Level
    if ($script:SelfTest) { [void]$script:SelfTestLog.Add($Text) }
}

function Complete-Task {
    $ps = $script:CurrentPs
    Write-GuiLog "==== 任务结束：$($script:TaskName) ===="
    try {
        $out = $ps.EndInvoke($script:CurrentHandle)
        if ($out) {
            foreach ($o in $out) { if ($null -ne $o) { Show-TaskLine -Text "$o" } }
        }
    } catch {
        Add-LogLine ('任务异常：' + $_.Exception.Message) 'ERR'
        Write-GuiLog "任务异常: $($_ | Out-String)"
    }
    try { $ps.Dispose() } catch { }
    $script:CurrentPs = $null
    $script:CurrentHandle = $null
    $script:Running = $false
    Clear-TaskLock
    Set-UiBusy $false
    Add-LogLine ('─────── 结束：' + $script:TaskName + '　' + (Get-Date -Format 'HH:mm:ss') + ' ───────')
    $script:SelfTestDone = $true
}

function Invoke-Drain {
    $count = 0
    $item = $null
    while ($count -lt 500 -and $script:TaskQueue.TryDequeue([ref]$item)) {
        $count++
        if ($null -eq $item) { continue }
        if ($item.Kind -eq 'log') { Show-TaskLine -Text $item.Text -Level $item.Level }
    }
    if ($script:Running -and $script:CurrentHandle -and $script:CurrentHandle.IsCompleted) {
        $again = 0
        while ($again -lt 500 -and $script:TaskQueue.TryDequeue([ref]$item)) {
            $again++
            if ($null -ne $item -and $item.Kind -eq 'log') { Show-TaskLine -Text $item.Text -Level $item.Level }
        }
        Complete-Task
    }
}

$script:DrainTimer = New-Object System.Windows.Threading.DispatcherTimer
$script:DrainTimer.Interval = [TimeSpan]::FromMilliseconds(120)
$script:DrainTimer.add_Tick({ Invoke-Drain })
$script:DrainTimer.Start()

# ================================================================ 引擎任务脚本
$BodyScan = @'
$diag = Invoke-Diagnostics -Quick:$param_Quick
if ($null -eq $diag) { Write-Err '体检没有返回结果，请检查日志。'; return }
$paths = Write-HealthReports -Diag $diag -NoOpen
Write-Host ('##RESULT##|score={0}|grade={1}|html={2}|md={3}|txt={4}' -f $diag.Score, $diag.Grade, $paths.Html, $paths.Markdown, $paths.Text)
Write-Host ''
Write-Ok ('体检完成：{0} 分（等级 {1}）。' -f $diag.Score, $diag.Grade)
'@

$BodyOrganizePlan = @'
$targets = @($param_Targets.Split('|') | Where-Object { $_ })
$plan = Invoke-OrganizeFiles -Targets $targets -Layout $param_Layout -MinAgeDays $param_MinAgeDays -Recurse:$param_Recurse
if ($null -eq $plan) { Write-Warn '没有生成整理方案。'; return }
$bytes = 0
try { $bytes = ($plan.Items | Measure-Object -Property Size -Sum).Sum } catch { }
Write-Host ('##RESULT##|organizePlan={0}|bytes={1}' -f $plan.Items.Count, $bytes)
'@

$BodyOrganizeApply = @'
$targets = @($param_Targets.Split('|') | Where-Object { $_ })
$null = Invoke-OrganizeFiles -Targets $targets -Layout $param_Layout -MinAgeDays $param_MinAgeDays -Recurse:$param_Recurse -Apply
Write-Host '##RESULT##|organizeApply=done'
'@

$BodyOrganizeUndo = @'
$null = Invoke-UndoOrganize -Apply
Write-Host '##RESULT##|organizeUndo=done'
'@

$BodyClean = @'
$null = Clear-TempFiles -Apply:$param_Apply -IncludeBrowserCache:$param_Browser -IncludeRecycleBin:$param_Recycle -IncludeUpdateCache:$param_UpdateCache -IncludeWinSxS:$param_WinSxS
Write-Host '##RESULT##|clean=done'
'@

$BodyRestorePoint = @'
$null = New-RestorePointSafe
Write-Host '##RESULT##|restorePoint=done'
'@

$BodyEnvRepair = @'
$null = Repair-EnvironmentVariables -Apply
Write-Host '##RESULT##|envRepair=done'
'@

$BodySysRepair = @'
$null = Repair-SystemFiles -Apply
Write-Host '##RESULT##|systemFileRepair=done'
'@

$BodyRuntime = @'
Show-RuntimeHelp -Install:$param_Install
Write-Host '##RESULT##|runtime=done'
'@

$BodyNetRepair = @'
$null = Repair-NetworkStack -Apply -ResetFirewall:$param_Firewall
Write-Host '##RESULT##|network=done'
'@

$BodyUpdateRepair = @'
$null = Repair-UpdateComponents -Apply
Write-Host '##RESULT##|updateReset=done'
'@

$BodyIconRepair = @'
$null = Repair-IconCache -Apply
Write-Host '##RESULT##|iconCache=done'
'@

$BodyDiskCheck = @'
$null = Repair-DiskCheck -Apply
Write-Host '##RESULT##|diskCheck=done'
'@

$BodyFullRepair = @'
$null = Repair-FullRun -Apply
Write-Host '##RESULT##|fullRepair=done'
'@

$BodyFindDup = @'
$targets = @($param_Targets.Split('|') | Where-Object { $_ })
$res = Find-DuplicateFiles -Targets $targets -MinSizeKB $param_MinSizeKB -Recurse:$param_Recurse
$waste = 0
try { $waste = ($res.Groups | Measure-Object -Property WasteBytes -Sum).Sum } catch { }
Write-Host ('##RESULT##|dupGroups={0}|waste={1}' -f $res.Groups.Count, $waste)
'@

$BodyMoveDup = @'
$targets = @($param_Targets.Split('|') | Where-Object { $_ })
$null = Invoke-DuplicateCleanup -Targets $targets -MinSizeKB $param_MinSizeKB -Recurse:$param_Recurse -Apply
Write-Host '##RESULT##|dupCleanup=done'
'@

$BodyFindLarge = @'
$targets = @($param_Targets.Split('|') | Where-Object { $_ })
Invoke-LargeFileScan -Targets $targets -MinMB $param_MinMB
Write-Host '##RESULT##|largeScan=done'
'@

# ================================================================ 辅助逻辑
function Invoke-Ui {
    param([scriptblock]$Action, [string]$Tag = 'ui')
    try { & $Action }
    catch {
        Write-GuiLog "界面操作出错[$Tag]: $($_ | Out-String)"
        Add-LogLine ('界面操作出错：' + $_.Exception.Message) 'ERR'
    }
}

function Test-IsAdminNow {
    try {
        $id = [Security.Principal.WindowsIdentity]::GetCurrent()
        return ([Security.Principal.WindowsPrincipal]$id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    } catch { return $false }
}

function Update-AdminBadge {
    if (Test-IsAdminNow) {
        $script:Ctl['AdminText'].Text = '管理员权限'
        $script:Ctl['AdminText'].Foreground = Get-LogBrush '#15803D'
        $script:Ctl['AdminBadge'].Background = Get-LogBrush '#ECFDF3'
        $script:Ctl['AdminButton'].Content = '已是管理员'
        $script:Ctl['AdminButton'].IsEnabled = $false
    } else {
        $script:Ctl['AdminText'].Text = '普通权限'
        $script:Ctl['AdminText'].Foreground = Get-LogBrush '#B26A00'
        $script:Ctl['AdminBadge'].Background = Get-LogBrush '#FFF7E6'
        $script:Ctl['AdminButton'].Content = '以管理员身份重启'
        $script:Ctl['AdminButton'].IsEnabled = $true
    }
}

function Restart-GuiElevated {
    $exe = 'powershell.exe'
    try { $exe = (Get-Process -Id $PID).Path } catch { }
    $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden',
                 '-File', ('"' + (Join-Path $script:GuiRoot 'PcToolkitGui.ps1') + '"'))
    if ($script:OutputRootArg) { $argList += @('-OutputRoot', ('"' + $script:OutputRootArg + '"')) }
    Write-GuiLog ("请求以管理员身份重启：" + $exe + ' ' + ($argList -join ' '))
    try {
        Start-Process -FilePath $exe -Verb RunAs -ArgumentList ($argList -join ' ') | Out-Null
        $script:DetachOnClose = $true
        $window.Close()
        return $true
    } catch {
        Write-GuiLog "提权失败: $($_.Exception.Message)"
        Show-GuiMessage ("提权失败（可能被取消了）：`n" + $_.Exception.Message) -Title '电脑管家' -Icon 'Warning'
        return $false
    }
}

function Test-AdminReady {
    param([string]$Why = '这一步需要管理员权限')
    if (Test-IsAdminNow) { return $true }
    $ask = $Why + "`n`n现在用管理员身份重新打开「电脑管家」吗？`n（当前窗口会关闭，在新窗口里继续操作）"
    if (Show-GuiConfirm $ask '需要管理员权限') { Restart-GuiElevated | Out-Null }
    return $false
}

function Get-SelectedTargets {
    $list = New-Object System.Collections.ArrayList
    if ($script:Ctl['ChkDownloads'].IsChecked) { [void]$list.Add((Join-Path $env:USERPROFILE 'Downloads')) }
    if ($script:Ctl['ChkDesktop'].IsChecked)   { [void]$list.Add((Join-Path $env:USERPROFILE 'Desktop')) }
    if ($script:Ctl['ChkDocuments'].IsChecked) { [void]$list.Add((Join-Path $env:USERPROFILE 'Documents')) }
    if ($script:Ctl['ChkCustom'].IsChecked -and $script:CustomPath) { [void]$list.Add($script:CustomPath) }
    $result = New-Object System.Collections.ArrayList
    foreach ($p in $list) {
        if ($p -and (Test-Path -LiteralPath $p)) { [void]$result.Add($p) }
    }
    return @($result)
}

function Get-LayoutValue {
    $idx = $script:Ctl['CmbLayout'].SelectedIndex
    if ($idx -eq 1) { return 'Date' }
    if ($idx -eq 2) { return 'Archive' }
    return 'Category'
}

function Get-IntFromBox {
    param([string]$Name, [int]$Default = 0)
    $box = $script:Ctl[$Name]
    $n = 0
    if ($box -and [int]::TryParse(("$($box.Text)").Trim(), [ref]$n) -and $n -ge 0) { return $n }
    if ($box) { $box.Text = "$Default" }
    return $Default
}

function Get-MinAgeValue { return (Get-IntFromBox -Name 'TxtMinAge' -Default 0) }

function Show-TargetsMissingHint {
    Add-LogLine '没有选中任何有效目录：请到「整理文件」页面勾选 下载/桌面/文档，或点「选择文件夹」加一个自定义目录。' 'WARN'
}

# ================================================================ 事件绑定：导航与顶部
$script:Ctl['NavList'].add_SelectionChanged({
    Invoke-Ui {
        $idx = $script:Ctl['NavList'].SelectedIndex
        if ($idx -lt 0 -or $idx -ge $pageOrder.Count) { return }
        for ($i = 0; $i -lt $pageOrder.Count; $i++) {
            if ($i -eq $idx) { $script:Ctl[$pageOrder[$i]].Visibility = 'Visible' }
            else { $script:Ctl[$pageOrder[$i]].Visibility = 'Collapsed' }
        }
    } 'NavList'
})
$script:Ctl['NavList'].SelectedIndex = 0

$script:Ctl['AdminButton'].add_Click({
    Invoke-Ui {
        if (Test-IsAdminNow) { Show-GuiMessage '现在已经是管理员权限了。'; return }
        Restart-GuiElevated | Out-Null
    } 'AdminButton'
})

$script:Ctl['OpenReportButton'].add_Click({
    Invoke-Ui {
        $dir = $script:ReportDirForGui
        if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        Start-Process explorer.exe $dir
    } 'OpenReportButton'
})

$script:Ctl['ExitButton'].add_Click({ Invoke-Ui { $window.Close() } 'ExitButton' })

# ================================================================ 事件绑定：体检
$script:Ctl['BtnScan'].add_Click({
    Invoke-Ui {
        $quick = ($script:Ctl['ChkQuick'].IsChecked -eq $true)
        Start-EngineTask -Title '一键体检' -Body $BodyScan -Parameters @{ param_Quick = $quick }
    } 'BtnScan'
})

$script:Ctl['BtnOpenLastReport'].add_Click({
    Invoke-Ui {
        if ($script:LastHtml -and (Test-Path -LiteralPath $script:LastHtml)) {
            Start-Process $script:LastHtml
            return
        }
        $dir = $script:ReportDirForGui
        $latest = $null
        try {
            $latest = Get-ChildItem -LiteralPath $dir -Filter '体检报告_*.html' -ErrorAction SilentlyContinue |
                      Sort-Object LastWriteTime -Descending | Select-Object -First 1
        } catch { }
        if ($latest) { Start-Process $latest.FullName }
        else { Show-GuiMessage '还没有生成过体检报告，先点「开始体检」。' }
    } 'BtnOpenLastReport'
})

# ================================================================ 事件绑定：整理
$script:Ctl['BtnBrowse'].add_Click({
    Invoke-Ui {
        $dlg = New-Object System.Windows.Forms.FolderBrowserDialog
        $dlg.Description = '选择要整理的文件夹'
        $dlg.ShowNewFolderButton = $false
        if ($dlg.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
            $script:CustomPath = $dlg.SelectedPath
            $script:Ctl['TxtCustomPath'].Text = $script:CustomPath
            $script:Ctl['ChkCustom'].IsChecked = $true
        }
    } 'BtnBrowse'
})

$script:Ctl['BtnPreviewOrganize'].add_Click({
    Invoke-Ui {
        $targets = Get-SelectedTargets
        if ($targets.Count -eq 0) { Show-TargetsMissingHint; return }
        Start-EngineTask -Title '预览整理方案' -Body $BodyOrganizePlan -Parameters @{
            param_Targets    = ($targets -join '|')
            param_Layout     = (Get-LayoutValue)
            param_MinAgeDays = (Get-MinAgeValue)
            param_Recurse    = $false
        }
    } 'BtnPreviewOrganize'
})

$script:Ctl['BtnApplyOrganize'].add_Click({
    Invoke-Ui {
        $targets = Get-SelectedTargets
        if ($targets.Count -eq 0) { Show-TargetsMissingHint; return }
        $layoutText = @('按文件类型分文件夹', '按年月 + 类型分文件夹', '全部移到按年份的归档文件夹')[$script:Ctl['CmbLayout'].SelectedIndex]
        $msg = "准备整理这些位置：`n" + ($targets -join "`n") + "`n`n归类方式：$layoutText`n只整理 " + (Get-MinAgeValue) + " 天以前改动过的文件`n`n文件会被移动到对应分类文件夹（不会删除），移动记录会保存，随时可以在左边「整理文件」里撤销。`n`n确定开始吗？"
        if (-not (Show-GuiConfirm $msg '执行整理')) { Add-LogLine '已取消执行整理。' 'WARN'; return }
        Start-EngineTask -Title '执行整理' -Body $BodyOrganizeApply -Parameters @{
            param_Targets    = ($targets -join '|')
            param_Layout     = (Get-LayoutValue)
            param_MinAgeDays = (Get-MinAgeValue)
            param_Recurse    = $false
        }
    } 'BtnApplyOrganize'
})

$script:Ctl['BtnUndoOrganize'].add_Click({
    Invoke-Ui {
        if (-not (Show-GuiConfirm "把上次整理移动过的文件放回原来的位置？`n（如果原位置已经有别的文件，会自动改名，不会覆盖）" '撤销整理')) { return }
        Start-EngineTask -Title '撤销上次整理' -Body $BodyOrganizeUndo
    } 'BtnUndoOrganize'
})

# ================================================================ 事件绑定：清理
$script:Ctl['BtnPreviewClean'].add_Click({
    Invoke-Ui {
        Start-EngineTask -Title '预览可清理体积' -Body $BodyClean -Parameters @{
            param_Apply       = $false
            param_Browser     = ($script:Ctl['ChkCleanBrowser'].IsChecked -eq $true)
            param_Recycle     = $false
            param_UpdateCache = ($script:Ctl['ChkCleanUpdate'].IsChecked -eq $true)
            param_WinSxS      = $false
        }
    } 'BtnPreviewClean'
})

$script:Ctl['BtnApplyClean'].add_Click({
    Invoke-Ui {
        $browser = ($script:Ctl['ChkCleanBrowser'].IsChecked -eq $true)
        $update  = ($script:Ctl['ChkCleanUpdate'].IsChecked -eq $true)
        $recycle = ($script:Ctl['ChkCleanRecycle'].IsChecked -eq $true)
        $sxS     = ($script:Ctl['ChkCleanWinSxS'].IsChecked -eq $true)

        $lines = New-Object System.Collections.ArrayList
        [void]$lines.Add('· 临时文件、错误报告、崩溃转储')
        if ($browser) { [void]$lines.Add('· 浏览器缓存（Edge / Chrome）') }
        if ($update)  { [void]$lines.Add('· Windows 更新下载缓存') }
        if ($recycle) { [void]$lines.Add('· 回收站（清空后无法恢复！）') }
        if ($sxS)     { [void]$lines.Add('· 系统组件仓库 WinSxS（较慢）') }
        $msg = "将要清理：`n" + ($lines -join "`n") + "`n`n正在被程序占用的文件会自动跳过，不会硬删。`n`n确定开始清理吗？"
        if (-not (Show-GuiConfirm $msg '执行清理')) { Add-LogLine '已取消清理。' 'WARN'; return }

        if ($sxS -and -not (Test-IsAdminNow)) {
            if (-not (Test-AdminReady '清理系统组件仓库（WinSxS）需要管理员权限。')) { return }
        }
        Start-EngineTask -Title '执行清理' -Body $BodyClean -Parameters @{
            param_Apply       = $true
            param_Browser     = $browser
            param_Recycle     = $recycle
            param_UpdateCache = $update
            param_WinSxS      = $sxS
        } -RepairTask:$sxS
    } 'BtnApplyClean'
})

# ================================================================ 事件绑定：修复
$script:Ctl['BtnRestorePoint'].add_Click({
    Invoke-Ui {
        if (-not (Test-AdminReady '创建系统还原点需要管理员权限。')) { return }
        if (-not (Show-GuiConfirm "现在创建一个系统还原点？`n`n之后做的修复如果出问题，可以回退到现在的状态。`n（Windows 默认 24 小时内只允许建一个还原点，如果刚建过会提示失败，可以忽略）" '创建还原点')) { return }
        Start-EngineTask -Title '创建系统还原点' -Body $BodyRestorePoint -RepairTask
    } 'BtnRestorePoint'
})

$script:Ctl['BtnEnvRepair'].add_Click({
    Invoke-Ui {
        if (-not (Test-AdminReady '修改系统环境变量需要管理员权限。')) { return }
        $msg = "检查并修复 PATH / TEMP 等环境变量？`n`n· 删掉指向不存在目录的项（外接盘上的会保留）`n· 去掉重复项和空项`n· 补回系统必需目录（System32 等）`n· 修好 TEMP / TMP`n`n改之前会自动把注册表和 PATH 明文备份到「_记录\备份」。"
        if (-not (Show-GuiConfirm $msg '环境变量修复')) { return }
        Start-EngineTask -Title '环境变量修复' -Body $BodyEnvRepair -RepairTask
    } 'BtnEnvRepair'
})

$script:Ctl['BtnSysRepair'].add_Click({
    Invoke-Ui {
        if (-not (Test-AdminReady '修复系统文件需要管理员权限。')) { return }
        $msg = "用微软官方方式修复系统文件，依次执行：`n`nDISM /Online /Cleanup-Image /ScanHealth`nDISM /Online /Cleanup-Image /RestoreHealth`nsfc /scannow`n`n适用于：缺少系统 dll、某个设置打不开、系统功能异常、更新总失败。`n耗时 10-30 分钟，期间不要关机（DISM 会联网下载修复文件）。`n`n现在开始吗？"
        if (-not (Show-GuiConfirm $msg '系统文件修复')) { return }
        Start-EngineTask -Title '系统文件修复（DISM + SFC）' -Body $BodySysRepair -RepairTask
    } 'BtnSysRepair'
})

$script:Ctl['BtnRuntime'].add_Click({
    Invoke-Ui {
        $ask = "先检查 VC++ / .NET 运行库是不是齐全。`n`n如果缺，要不要顺便用 winget 自动安装？`n（需要联网；选「否」就只告诉你官方下载地址）"
        $install = (Show-GuiConfirm $ask '运行库检查')
        if ($install -and -not (Test-IsAdminNow)) {
            if (-not (Test-AdminReady '安装运行库需要管理员权限。')) { return }
        }
        Start-EngineTask -Title '运行库检查' -Body $BodyRuntime -Parameters @{ param_Install = $install }
    } 'BtnRuntime'
})

$script:Ctl['BtnNetRepair'].add_Click({
    Invoke-Ui {
        if (-not (Test-AdminReady '重置网络组件需要管理员权限。')) { return }
        $fw = Show-GuiConfirm "重置网络协议栈（winsock / IP / DNS 缓存）。`n`n适用于：能连网但网页打不开、DNS 解析失败、某些软件上不了网、代理设置残留。`n做完需要重启电脑。`n`n要不要顺便把防火墙规则也重置成默认？`n（选「是」= 删掉自己加过的所有防火墙规则；选「否」= 只重置网络协议）" '重置网络组件'
        if (-not (Show-GuiConfirm "确认开始重置网络组件？完成后记得重启电脑。" '重置网络组件')) { return }
        Start-EngineTask -Title '重置网络组件' -Body $BodyNetRepair -Parameters @{ param_Firewall = $fw } -RepairTask
    } 'BtnNetRepair'
})

$script:Ctl['BtnUpdateRepair'].add_Click({
    Invoke-Ui {
        if (-not (Test-AdminReady '重置 Windows 更新组件需要管理员权限。')) { return }
        $msg = "重置 Windows 更新组件？`n`n适用于：更新一直失败、卡在某个百分比、报 0x800700xx、更新历史打不开、Store 装不了应用。`n`n做法：停止更新相关服务 → 把 SoftwareDistribution 和 catroot2 改名备份（不删除）→ 重新启动服务。`n`n现在开始吗？"
        if (-not (Show-GuiConfirm $msg '重置更新组件')) { return }
        Start-EngineTask -Title '重置 Windows 更新组件' -Body $BodyUpdateRepair -RepairTask
    } 'BtnUpdateRepair'
})

$script:Ctl['BtnIconRepair'].add_Click({
    Invoke-Ui {
        $msg = "重建图标 / 缩略图缓存？`n`n适用于：图标变成白纸、图标显示错乱、缩略图不刷新、文件夹图标不对。`n执行时「文件资源管理器」会重启一下（桌面和任务栏会闪，正在复制的文件建议先等它完成）。"
        if (-not (Show-GuiConfirm $msg '重建图标缓存')) { return }
        Start-EngineTask -Title '重建图标缓存' -Body $BodyIconRepair
    } 'BtnIconRepair'
})

$script:Ctl['BtnDiskCheck'].add_Click({
    Invoke-Ui {
        if (-not (Test-AdminReady '磁盘检查需要管理员权限。')) { return }
        $msg = "对系统盘做只读扫描（chkdsk /scan）？`n`n只检查、不修改、不重启，一般几分钟。`n如果扫描发现文件系统有问题，再去命令行版里选「磁盘检查 + 重启修复」。"
        if (-not (Show-GuiConfirm $msg '磁盘检查')) { return }
        Start-EngineTask -Title '磁盘检查' -Body $BodyDiskCheck -RepairTask
    } 'BtnDiskCheck'
})

$script:Ctl['BtnFullRepair'].add_Click({
    Invoke-Ui {
        if (-not (Test-AdminReady '一键修复需要管理员权限。')) { return }
        $msg = "一键修复会按安全顺序依次执行：`n`n① 创建系统还原点`n② 修复环境变量`n③ 清理临时文件`n④ 系统文件修复（DISM + SFC，最慢的一步）`n⑤ 系统盘只读扫描`n`n整个过程可能 20-40 分钟，下面日志会实时滚动。做完重启，再体检一次就能对比分数。`n`n确定开始吗？"
        if (-not (Show-GuiConfirm $msg '一键修复')) { return }
        Start-EngineTask -Title '一键修复' -Body $BodyFullRepair -RepairTask
    } 'BtnFullRepair'
})

# ================================================================ 事件绑定：重复 / 大文件
$script:Ctl['BtnFindDup'].add_Click({
    Invoke-Ui {
        $targets = Get-SelectedTargets
        if ($targets.Count -eq 0) { Show-TargetsMissingHint; return }
        Start-EngineTask -Title '查找重复文件' -Body $BodyFindDup -Parameters @{
            param_Targets   = ($targets -join '|')
            param_MinSizeKB = (Get-IntFromBox -Name 'TxtMinSizeKB' -Default 64)
            param_Recurse   = ($script:Ctl['ChkRecurse'].IsChecked -eq $true)
        }
    } 'BtnFindDup'
})

$script:Ctl['BtnMoveDup'].add_Click({
    Invoke-Ui {
        $targets = Get-SelectedTargets
        if ($targets.Count -eq 0) { Show-TargetsMissingHint; return }
        $msg = "把重复文件里多余的副本移动到「_重复文件备份_时间戳」文件夹？`n`n注意：这不是删除，只是搬走，你确认没问题后自己把那个备份文件夹删掉就行。`n每组保留第一个副本。"
        if (-not (Show-GuiConfirm $msg '搬走重复副本')) { return }
        Start-EngineTask -Title '搬走重复副本' -Body $BodyMoveDup -Parameters @{
            param_Targets   = ($targets -join '|')
            param_MinSizeKB = (Get-IntFromBox -Name 'TxtMinSizeKB' -Default 64)
            param_Recurse   = ($script:Ctl['ChkRecurse'].IsChecked -eq $true)
        }
    } 'BtnMoveDup'
})

$script:Ctl['BtnFindLarge'].add_Click({
    Invoke-Ui {
        $targets = Get-SelectedTargets
        if ($targets.Count -eq 0) { Show-TargetsMissingHint; return }
        Start-EngineTask -Title '查找大文件' -Body $BodyFindLarge -Parameters @{
            param_Targets = ($targets -join '|')
            param_MinMB   = (Get-IntFromBox -Name 'TxtMinMB' -Default 200)
        }
    } 'BtnFindLarge'
})

# ================================================================ 事件绑定：说明页与日志工具
$script:Ctl['BtnOpenHelp'].add_Click({
    Invoke-Ui {
        $md = Join-Path $script:GuiRoot '使用说明.md'
        if (Test-Path -LiteralPath $md) { Start-Process $md } else { Show-GuiMessage '找不到 使用说明.md' }
    } 'BtnOpenHelp'
})

$script:Ctl['BtnMakeShortcut'].add_Click({
    Invoke-Ui {
        if (-not (Get-Command New-ToolkitShortcut -ErrorAction SilentlyContinue)) {
            Show-GuiMessage '快捷方式模块没有加载成功，请直接用「启动.bat」打开窗口，或运行 CreateShortcut.ps1。'
            return
        }
        $res = New-ToolkitShortcut -ToolRoot $script:GuiRoot -IncludeStartMenu
        foreach ($p in $res.Made) { Add-LogLine ('已创建快捷方式：' + $p) 'OK' }
        foreach ($f in $res.Failed) { Add-LogLine ('快捷方式失败：' + $f) 'WARN' }
        if ($res.Ok) {
            $msg = "已经在这些位置创建了「电脑管家」快捷方式：`n`n" + ($res.Made -join "`n") + "`n`n以后从桌面双击就能打开这个窗口（不会弹黑框）。`n想删掉就直接删除那个图标，不影响工具本身。"
            if ($res.Failed.Count -gt 0) { $msg += "`n`n（有 $($res.Failed.Count) 个位置没建成功，通常是权限或安全软件保护，一般不影响使用。）" }
            Show-GuiMessage $msg '创建桌面快捷方式'
        } else {
            $msg = "没能创建快捷方式。`n`n" + $res.Message + "`n`n失败详情：`n" + ($res.Failed -join "`n") + "`n`n没关系——直接双击「启动.bat」打开窗口，效果完全一样。"
            Show-GuiMessage $msg '创建桌面快捷方式' 'Warning'
        }
    } 'BtnMakeShortcut'
})

$script:Ctl['BtnConsoleVersion'].add_Click({
    Invoke-Ui {
        $bat = Join-Path $script:GuiRoot '启动-命令行版.bat'
        if (Test-Path -LiteralPath $bat) { Start-Process $bat } else { Show-GuiMessage '找不到 启动-命令行版.bat' }
    } 'BtnConsoleVersion'
})

$script:Ctl['BtnOpenToolFolder'].add_Click({
    Invoke-Ui { Start-Process explorer.exe $script:GuiRoot } 'BtnOpenToolFolder'
})

$script:Ctl['BtnClearLog'].add_Click({ Invoke-Ui { Clear-Log } 'BtnClearLog' })

$script:Ctl['BtnToggleLog'].add_Click({
    Invoke-Ui {
        $box = $script:Ctl['LogBox']
        if ($box.Visibility -eq 'Visible') {
            $box.Visibility = 'Collapsed'
            $script:Ctl['BtnToggleLog'].Content = '展开日志'
        } else {
            $box.Visibility = 'Visible'
            $script:Ctl['BtnToggleLog'].Content = '收起日志'
        }
    } 'BtnToggleLog'
})

$script:Ctl['BtnCopyLog'].add_Click({
    Invoke-Ui {
        $text = Get-LogText
        if ([string]::IsNullOrWhiteSpace($text)) { Show-GuiMessage '日志还是空的。'; return }
        try {
            [System.Windows.Clipboard]::SetText($text)
            Show-GuiMessage '日志已经复制到剪贴板，可以直接粘贴给别人看。'
        } catch {
            Show-GuiMessage ('复制失败：' + $_.Exception.Message)
        }
    } 'BtnCopyLog'
})

$script:Ctl['BtnStop'].add_Click({
    Invoke-Ui {
        if (-not $script:Running) { return }
        $msg = "尝试中止当前任务？`n`n如果是 DISM / SFC 这类系统命令，可能需要等系统命令自己跑完才会真正停下。"
        if (-not (Show-GuiConfirm $msg '中止任务')) { return }
        try {
            $script:CurrentPs.Stop()
            Add-LogLine '已请求中止任务...' 'WARN'
        } catch {
            Add-LogLine ('中止失败：' + $_.Exception.Message) 'ERR'
        }
    } 'BtnStop'
})

$window.add_Closing({
    param($sender, $e)
    if ($script:Running -and -not $script:DetachOnClose) {
        $r = [System.Windows.MessageBox]::Show("还有任务正在运行（可能是系统修复）。`n`n真的关闭窗口吗？", '任务正在运行', 'YesNo', 'Warning')
        if ($r -eq 'No') { $e.Cancel = $true }
    }
    if (-not $e.Cancel -and -not $script:Running) { Clear-TaskLock }
})

# ================================================================ 启动
function Pump-Dispatcher {
    param([int]$Milliseconds = 150)
    $script:PumpFrame = New-Object System.Windows.Threading.DispatcherFrame
    $pumpTimer = New-Object System.Windows.Threading.DispatcherTimer
    $pumpTimer.Interval = [TimeSpan]::FromMilliseconds($Milliseconds)
    $pumpTimer.add_Tick({ $script:PumpFrame.Continue = $false })
    $pumpTimer.Start()
    [System.Windows.Threading.Dispatcher]::PushFrame($script:PumpFrame)
    $pumpTimer.Stop()
}

$script:ReportDirForGui = if ($script:OutputRootArg) { $script:OutputRootArg } else { Join-Path $script:GuiRoot '报告' }
if (-not (Test-Path -LiteralPath $script:ReportDirForGui)) {
    try { New-Item -ItemType Directory -Path $script:ReportDirForGui -Force | Out-Null } catch { }
}

Update-AdminBadge
Clear-Log
Add-LogLine '电脑管家已启动。'
Add-LogLine ('工作目录：' + $script:GuiRoot)
Add-LogLine ('报告目录：' + $script:ReportDirForGui)
if (Test-IsAdminNow) {
    Add-LogLine '当前是管理员权限，所有修复功能都可以直接用。' 'OK'
} else {
    Add-LogLine '当前是普通权限：体检、整理文件、清理临时文件都能正常用；修复类操作会提示你用管理员身份重启。' 'WARN'
}
Add-LogLine '建议第一步：左边选「一键体检」，点「开始体检」看看电脑现在什么状态。'
Write-GuiLog '==== 界面启动 ===='

if ($SelfTest) {
    Write-Host '[自检] 检查控件绑定...'
    $missingCtl = @()
    foreach ($n in $ctlNames) { if ($null -eq $script:Ctl[$n]) { $missingCtl += $n } }
    Write-Host ('[自检] 控件 {0} 个，缺失 {1} 个；可操作按钮 {2} 个' -f $script:Ctl.Count, $missingCtl.Count, $script:ActionButtons.Count)

    Write-Host '[自检] 通过界面链路跑一次快速体检...'
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $script:Ctl['NavList'].SelectedIndex = 0
    Start-EngineTask -Title '自检：一键体检' -Body $BodyScan -Parameters @{ param_Quick = $true }
    $deadline = (Get-Date).AddMinutes(8)
    while (-not $script:SelfTestDone -and (Get-Date) -lt $deadline) { Pump-Dispatcher -Milliseconds 150 }
    $sw.Stop()

    $lines = @()
    $lines += '==== 电脑管家 GUI 自检结果 ===='
    $lines += ('时间：{0}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
    $lines += ('PowerShell：{0}' -f $PSVersionTable.PSVersion)
    $lines += ('线程模式：{0}' -f [System.Threading.Thread]::CurrentThread.GetApartmentState())
    $lines += ('管理员：{0}' -f (Test-IsAdminNow))
    $lines += ('控件数：{0}（缺失 {1}）' -f $script:Ctl.Count, $missingCtl.Count)
    if ($missingCtl.Count -gt 0) { $lines += ('缺失控件：' + ($missingCtl -join ', ')) }
    $lines += ('可操作按钮数：{0}' -f $script:ActionButtons.Count)
    $lines += ('任务完成：{0}（耗时 {1:N1} 秒）' -f $script:SelfTestDone, $sw.Elapsed.TotalSeconds)
    $lines += ('日志行数：{0}' -f $script:LogLineCount)
    $lines += ('结果标记：' + (($script:LastResult.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ' ; '))

    # 验证「创建桌面快捷方式」这条链路（只写到临时目录，不动真实桌面）
    $shortcutTest = '未执行'
    if (Get-Command New-ToolkitShortcut -ErrorAction SilentlyContinue) {
        $tmpDir = Join-Path $env:TEMP ('PcToolkitShortcutTest_' + (Get-Random))
        try {
            $r = New-ToolkitShortcut -ToolRoot $script:GuiRoot -TargetDir $tmpDir
            $shortcutTest = ('生成 {0} 个，成功={1}' -f @($r.Made).Count, $r.Ok)
            if (@($r.Made).Count -gt 0) {
                $info = Test-ToolkitShortcut -LnkPath $r.Made[0]
                if ($info) {
                    $shortcutTest += ('；目标=' + (Split-Path -Leaf $info.Target) + '；参数含界面脚本=' + ($info.Arguments -match 'PcToolkitGui\.ps1') + '；图标=' + (Test-Path -LiteralPath ($info.IconLocation -replace ',0$', '')))
                }
            }
            foreach ($f in @($r.Failed)) { $shortcutTest += "；失败=$f" }
        } catch {
            $shortcutTest = '异常：' + $_.Exception.Message
        }
        try { Remove-Item -LiteralPath $tmpDir -Recurse -Force -ErrorAction SilentlyContinue } catch { }
    } else {
        $shortcutTest = 'New-ToolkitShortcut 没有加载（按钮会不可用）'
    }
    $lines += ('快捷方式链路：{0}' -f $shortcutTest)

    if ($script:LastHtml) {
        $htmlExists = Test-Path -LiteralPath $script:LastHtml
        $htmlSize = 0
        if ($htmlExists) { $htmlSize = (Get-Item -LiteralPath $script:LastHtml).Length }
        $lines += ('HTML 报告：{0}（存在={1}，{2} 字节）' -f $script:LastHtml, $htmlExists, $htmlSize)
    } else {
        $lines += 'HTML 报告：<没有拿到路径>'
    }
    $lines += ''
    $lines += '---- 日志前 20 行 ----'
    $lines += @($script:SelfTestLog | Select-Object -First 20)
    $lines += ''
    $lines += '---- 日志后 15 行 ----'
    $lines += @($script:SelfTestLog | Select-Object -Last 15)

    $outFile = Join-Path $script:StateDir '自检结果.txt'
    try {
        [System.IO.File]::WriteAllText($outFile, ($lines -join "`r`n"), (New-Object System.Text.UTF8Encoding($true)))
        Write-Host ('[自检] 结果已写入：' + $outFile)
    } catch { Write-Host ('[自检] 写结果失败：' + $_.Exception.Message) }
    foreach ($l in $lines) { Write-Host $l }

    $selfTestOk = ($missingCtl.Count -eq 0) -and $script:SelfTestDone -and ($script:LogLineCount -gt 5)
    Write-Host ('[自检] 结论：' + $(if ($selfTestOk) { '通过' } else { '不通过' }))
    exit $(if ($selfTestOk) { 0 } else { 1 })
}

[void]$window.ShowDialog()
