<#
    电脑管家 PcToolkit - 公共基础模块
    职责：控制台输出、日志、权限提升、确认交互、目录体积统计、备份、外部命令调用
    兼容：Windows PowerShell 5.1 与 PowerShell 7+
#>

if (-not $script:ToolkitLoaded) {
    $script:ToolkitName    = '电脑管家 PcToolkit'
    $script:ToolkitVersion = '1.0'
    $script:ToolRoot       = Split-Path -Parent $PSScriptRoot
    $script:ReportDir      = Join-Path $script:ToolRoot '报告'
    $script:StateDir       = Join-Path $script:ToolRoot '_记录'
    $script:BackupDir      = Join-Path $script:StateDir '备份'
    $script:LogFile        = $null
    $script:ToolkitLoaded  = $true
}

function Initialize-Toolkit {
    [CmdletBinding()]
    param([string]$OutputRoot)

    if ($OutputRoot) {
        $script:ReportDir = $OutputRoot
        $script:StateDir  = Join-Path $OutputRoot '_记录'
        $script:BackupDir = Join-Path $script:StateDir '备份'
    }
    foreach ($dir in @($script:ReportDir, $script:StateDir, $script:BackupDir)) {
        if (-not (Test-Path -LiteralPath $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
        }
    }

    try {
        [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
        $OutputEncoding = New-Object System.Text.UTF8Encoding($false)
    } catch { }

    $script:LogFile = Join-Path $script:StateDir ('运行日志_{0}.log' -f (Get-Date -Format 'yyyyMMdd'))
    Write-Log ("======== 启动 {0} v{1} | 管理员={2} | PS={3} ========" -f $script:ToolkitName, $script:ToolkitVersion, (Test-IsAdmin), $PSVersionTable.PSVersion.ToString())
}

# ---------------------------------------------------------------- 控制台输出

function Write-Log {
    param(
        [Parameter(Position = 0)][string]$Message,
        [Parameter(Position = 1)][ValidateSet('INFO', 'OK', 'WARN', 'ERR', 'STEP')][string]$Level = 'INFO'
    )
    if (-not $script:LogFile) { return }
    $line = '{0} [{1}] {2}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Level, $Message
    try { Add-Content -LiteralPath $script:LogFile -Value $line -Encoding UTF8 -ErrorAction SilentlyContinue } catch { }
}

function Write-Line { param([string]$Char = '-', [ConsoleColor]$Color = 'DarkGray')
    Write-Host ($Char * 68) -ForegroundColor $Color }

function Write-Title { param([string]$Text)
    Write-Host ''
    Write-Host ('=' * 68) -ForegroundColor Cyan
    Write-Host ("  $Text") -ForegroundColor Cyan
    Write-Host ('=' * 68) -ForegroundColor Cyan
    Write-Log "---- $Text ----" }

function Write-Section { param([string]$Text)
    Write-Host ''
    Write-Host ("▎$Text") -ForegroundColor Cyan
    Write-Host ('-' * 60) -ForegroundColor DarkGray
    Write-Log "-- $Text" }

function Write-Info { param([string]$Text)
    Write-Host "  $Text" -ForegroundColor Gray; Write-Log $Text }

function Write-Ok { param([string]$Text)
    Write-Host "  [OK]  $Text" -ForegroundColor Green; Write-Log $Text 'OK' }

function Write-Warn { param([string]$Text)
    Write-Host "  [注意] $Text" -ForegroundColor Yellow; Write-Log $Text 'WARN' }

function Write-Err { param([string]$Text)
    Write-Host "  [问题] $Text" -ForegroundColor Red; Write-Log $Text 'ERR' }

function Write-Step { param([string]$Text)
    Write-Host "  >> $Text" -ForegroundColor White; Write-Log $Text 'STEP' }

function Write-Skip { param([string]$Text)
    Write-Host "  [跳过] $Text" -ForegroundColor DarkGray; Write-Log $Text }

function Format-Bytes {
    param([double]$Bytes)
    if ($null -eq $Bytes -or [double]::IsNaN($Bytes)) { return '0 B' }
    $units = @('B', 'KB', 'MB', 'GB', 'TB', 'PB')
    $i = 0
    $v = [double]$Bytes
    while ([Math]::Abs($v) -ge 1024 -and $i -lt ($units.Count - 1)) { $v = $v / 1024; $i++ }
    if ($i -eq 0) { return ('{0:N0} {1}' -f $v, $units[$i]) }
    return ('{0:N2} {1}' -f $v, $units[$i])
}

# ---------------------------------------------------------------- 交互 / 权限

function Test-IsAdmin {
    try {
        $id = [Security.Principal.WindowsIdentity]::GetCurrent()
        return ([Security.Principal.WindowsPrincipal]$id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    } catch { return $false }
}

function Confirm-Action {
    param(
        [Parameter(Position = 0)][string]$Prompt = '确认执行吗？',
        [Parameter(Position = 1)][bool]$Default = $false
    )
    if ($script:AssumeYes) { Write-Host "  (已用 -Yes 自动确认：$Prompt)" -ForegroundColor DarkYellow; return $true }
    $suffix = 'Y/n'
    if (-not $Default) { $suffix = 'y/N' }
    while ($true) {
        Write-Host -NoNewline "  $Prompt [$suffix] " -ForegroundColor Yellow
        $answer = Read-Host
        if ([string]::IsNullOrWhiteSpace($answer)) { return $Default }
        switch ($answer.Trim().ToLower()) {
            { $_ -in @('y', 'yes', '是', '好', '1') } { return $true }
            { $_ -in @('n', 'no', '否', '不', '0', 'q') } { return $false }
            default { Write-Host '  请输入 y 或 n。' -ForegroundColor DarkYellow }
        }
    }
}

function Wait-Continue {
    if ($script:AssumeYes) { return }
    Write-Host ''
    Write-Host -NoNewline '  按回车继续...' -ForegroundColor DarkGray
    [void](Read-Host)
}

function Restart-Elevated {
    param([string[]]$ExtraArguments = @())
    $exe = 'powershell.exe'
    try {
        $proc = Get-Process -Id $PID -ErrorAction Stop
        if ($proc.Path) { $exe = $proc.Path }
    } catch { }
    $scriptPath = Join-Path $script:ToolRoot 'PcToolkit.ps1'
    $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"{0}"' -f $scriptPath)) + $ExtraArguments
    Write-Info "正在请求管理员权限重新启动：$exe"
    try {
        Start-Process -FilePath $exe -Verb RunAs -ArgumentList ($argList -join ' ') | Out-Null
        return $true
    } catch {
        Write-Err "提权失败（可能被取消了）：$($_.Exception.Message)"
        Write-Info "你也可以手动操作：右键开始菜单 → 终端(管理员)，然后运行 启动.bat"
        return $false
    }
}

function Assert-Admin {
    param([string]$Why = '这个功能需要管理员权限')
    if (Test-IsAdmin) { return $true }
    Write-Warn $Why
    if (Confirm-Action '现在用管理员权限重新打开工具？' $true) {
        Restart-Elevated | Out-Null
        Write-Info '新的管理员窗口已经打开，请在那边继续操作，本窗口可以关闭了。'
        Wait-Continue
        return $false
    }
    Write-Info '已跳过（没有管理员权限做不了这一步）。'
    return $false
}

# ---------------------------------------------------------------- 系统小工具

function Test-PendingReboot {
    $reasons = New-Object System.Collections.ArrayList
    try {
        if (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending') {
            [void]$reasons.Add('组件安装(CBS)待重启')
        }
    } catch { }
    try {
        if (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired') {
            [void]$reasons.Add('Windows 更新待重启')
        }
    } catch { }
    try {
        $pfro = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager' -Name PendingFileRenameOperations -ErrorAction SilentlyContinue).PendingFileRenameOperations
        if ($pfro) { [void]$reasons.Add('有文件等待重启后才能替换') }
    } catch { }
    return [pscustomobject]@{ Pending = ($reasons.Count -gt 0); Reasons = @($reasons) }
}

function Get-FolderStats {
    <#  安全统计目录体积：跳过联接点（避免死循环），超时自动中断  #>
    param(
        [Parameter(Mandatory)][string]$Path,
        [int]$TimeoutSeconds = 25
    )
    $result = [pscustomobject]@{
        Path = $Path; Exists = $false; Files = 0; Bytes = [long]0; Skipped = 0; Truncated = $false
    }
    if ([string]::IsNullOrWhiteSpace($Path)) { return $result }
    try { if (-not (Test-Path -LiteralPath $Path)) { return $result } } catch { return $result }
    $result.Exists = $true

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $stack = New-Object System.Collections.Stack
    $stack.Push($Path)
    while ($stack.Count -gt 0) {
        if ((Get-Date) -gt $deadline) { $result.Truncated = $true; break }
        $dir = $stack.Pop()
        try {
            foreach ($f in [System.IO.Directory]::EnumerateFiles($dir)) {
                try {
                    $len = (New-Object System.IO.FileInfo($f)).Length
                    $result.Files = $result.Files + 1
                    $result.Bytes = $result.Bytes + $len
                } catch { $result.Skipped = $result.Skipped + 1 }
            }
        } catch { $result.Skipped = $result.Skipped + 1 }
        try {
            foreach ($d in [System.IO.Directory]::EnumerateDirectories($dir)) {
                try {
                    $attr = [System.IO.File]::GetAttributes($d)
                    if (($attr -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { continue }
                } catch { continue }
                $stack.Push($d)
            }
        } catch { $result.Skipped = $result.Skipped + 1 }
    }
    return $result
}

function Get-FileSizeSafe {
    param([string]$Path)
    try { return (New-Object System.IO.FileInfo($Path)).Length } catch { return 0 }
}

function Test-FileLocked {
    param([Parameter(Mandatory)][string]$Path)
    try {
        $stream = [System.IO.File]::Open($Path, 'Open', 'ReadWrite', 'None')
        $stream.Close(); $stream.Dispose()
        return $false
    } catch { return $true }
}

function Backup-TextFile {
    param([Parameter(Mandatory)][string]$Path, [string]$Tag = 'txt')
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    $dest = Join-Path $script:BackupDir ('{0}_{1}_{2}' -f $Tag, (Get-Date -Format 'yyyyMMdd_HHmmss'), (Split-Path -Leaf $Path))
    try {
        Copy-Item -LiteralPath $Path -Destination $dest -Force
        Write-Log "备份文件: $Path -> $dest"
        return $dest
    } catch {
        Write-Warn "备份失败：$($_.Exception.Message)"
        return $null
    }
}

function Backup-RegistryKey {
    param([Parameter(Mandatory)][string]$KeyPath, [Parameter(Mandatory)][string]$FileName)
    $dest = Join-Path $script:BackupDir ('{0}_{1}.reg' -f (Get-Date -Format 'yyyyMMdd_HHmmss'), $FileName)
    try {
        $reg = (Get-Command reg.exe -ErrorAction SilentlyContinue).Source
        if (-not $reg) { $reg = 'reg.exe' }
        & $reg export $KeyPath $dest /y 2>&1 | Out-Null
        if (Test-Path -LiteralPath $dest) {
            Write-Log "备份注册表: $KeyPath -> $dest"
            return $dest
        }
        return $null
    } catch {
        Write-Log "注册表备份失败: $($_.Exception.Message)" 'WARN'
        return $null
    }
}

function Get-RegValue {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Name,
        [string]$Default = $null
    )
    try {
        $v = (Get-ItemProperty -Path $Path -Name $Name -ErrorAction Stop).$Name
        if ($null -eq $v) { return $Default }
        return $v
    } catch { return $Default }
}

function Invoke-Native {
    <#  运行外部程序：实时显示输出 + 写入日志 + 返回退出码  #>
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$Arguments = @(),
        [string]$FriendlyName,
        [switch]$Quiet
    )
    $exe = $FilePath
    try {
        $cmd = Get-Command $FilePath -ErrorAction Stop
        if ($cmd.Source) { $exe = $cmd.Source }
    } catch { }

    if ($FriendlyName) { Write-Step $FriendlyName }
    Write-Log ("RUN: {0} {1}" -f $exe, ($Arguments -join ' '))

    $global:LASTEXITCODE = 0
    try {
        & $exe @Arguments 2>&1 | ForEach-Object {
            $line = "$_"
            if (-not $Quiet) { Write-Host "    $line" -ForegroundColor DarkGray }
            Write-Log "  | $line"
        }
        $code = $LASTEXITCODE
    } catch {
        Write-Err "命令执行失败：$($_.Exception.Message)"
        Write-Log "ERROR: $($_.Exception.Message)" 'ERR'
        return 1
    }
    if ($null -eq $code) { $code = 0 }
    Write-Log ("EXIT CODE: {0}" -f $code)
    return [int]$code
}

function Open-PathInShell {
    param([Parameter(Mandatory)][string]$Path)
    try {
        if (Test-Path -LiteralPath $Path) { Invoke-Item -LiteralPath $Path; return $true }
        Write-Warn "路径不存在：$Path"
        return $false
    } catch {
        Write-Warn "打开失败：$($_.Exception.Message)"
        return $false
    }
}

# ---------------------------------------------------------------- 防重复执行

function Get-ToolkitLockFile {
    return (Join-Path $script:StateDir '任务运行中.lock')
}

function Get-BusySystemProcessNames {
    <#  正在跑的系统修复类进程（DISM / SFC / 磁盘检查）  #>
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

function Test-OtherRepairRunning {
    <#  返回 $null 表示没有别的修复在跑；否则返回一句描述  #>
    $parts = New-Object System.Collections.ArrayList
    try {
        $lock = Get-ToolkitLockFile
        if (Test-Path -LiteralPath $lock) {
            $data = $null
            try { $data = Get-Content -LiteralPath $lock -Raw -Encoding UTF8 | ConvertFrom-Json } catch { }
            $alive = $false
            $otherPid = 0
            if ($data -and $data.pid) { [void][int]::TryParse("$($data.pid)", [ref]$otherPid) }
            if ($otherPid -gt 0 -and $otherPid -ne $PID) {
                try { $alive = $null -ne (Get-Process -Id $otherPid -ErrorAction Stop) } catch { $alive = $false }
            }
            if ($alive) {
                $title = ''
                if ($data.title) { $title = $data.title }
                [void]$parts.Add("另一个电脑管家窗口正在执行「$title」（PID $otherPid）")
            } elseif ($otherPid -ne $PID) {
                Remove-PathSafe -Path $lock | Out-Null
            }
        }
    } catch { }
    $busy = Get-BusySystemProcessNames
    if ($busy.Count -gt 0) { [void]$parts.Add('系统里正在运行：' + ($busy -join '、')) }
    if ($parts.Count -eq 0) { return $null }
    return ($parts -join '；')
}

function Set-ToolkitLock {
    param([string]$Title = '未知任务')
    try {
        $lock = Get-ToolkitLockFile
        $dir = Split-Path -Parent $lock
        if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        $payload = [pscustomobject]@{
            pid   = $PID
            title = $Title
            start = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
            user  = $env:USERNAME
        }
        [System.IO.File]::WriteAllText($lock, ($payload | ConvertTo-Json), (New-Object System.Text.UTF8Encoding($true)))
    } catch { }
}

function Clear-ToolkitLock {
    try {
        $lock = Get-ToolkitLockFile
        if (Test-Path -LiteralPath $lock) {
            $data = $null
            try { $data = Get-Content -LiteralPath $lock -Raw -Encoding UTF8 | ConvertFrom-Json } catch { }
            if (-not $data -or -not $data.pid -or "$($data.pid)" -eq "$PID") {
                Remove-PathSafe -Path $lock | Out-Null
            }
        }
    } catch { }
}

function Get-RecycleBinInfo {
    <#  用 Shell COM 读取回收站，无需管理员  #>
    $info = [pscustomobject]@{ Ok = $false; Count = 0; Bytes = [long]0 }
    try {
        $shell = New-Object -ComObject Shell.Application
        $bin = $shell.NameSpace(0xA)
        if ($null -ne $bin) {
            foreach ($item in $bin.Items()) {
                $info.Count = $info.Count + 1
                try {
                    $raw = $bin.GetDetailsOf($item, 3)
                    if ($raw) { $info.Bytes = $info.Bytes + [long]($raw -replace '[^0-9]', '') }
                } catch { }
            }
            $info.Ok = $true
        }
    } catch { }
    return $info
}
