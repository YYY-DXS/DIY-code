<#
    电脑管家 PcToolkit - 修复模块
    包含：系统还原点 / 环境变量修复 / 垃圾清理 / 系统文件修复 / 磁盘检查 /
          网络组件修复 / 更新组件重置 / 图标缓存重建 / 运行库安装引导
    安全原则：默认"只看不改"，真正动手前都会显示要做什么并让你确认，能备份的一定先备份。
#>

function Remove-PathSafe {
    param([Parameter(Mandatory)][string]$Path, [switch]$Recurse)
    try {
        if ($Recurse) { Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop }
        else { Remove-Item -LiteralPath $Path -Force -ErrorAction Stop }
        return $true
    } catch { return $false }
}

function Confirm-RepairNotBusy {
    <#  开工前检查：有没有别的修复正在跑（别的窗口、或系统自己在更新）  #>
    $busyText = Test-OtherRepairRunning
    if (-not $busyText) { return $true }
    Write-Warn "检测到 $busyText"
    Write-Warn '两边同时修可能会互相干扰（例如两个 DISM 抢同一个系统映像），建议等它结束。'
    return (Confirm-Action '仍然继续吗？' $false)
}

function New-RestorePointSafe {
    Write-Section '创建系统还原点'
    if (-not (Assert-Admin '创建还原点需要管理员权限')) { return $false }
    try {
        $sr = Get-ComputerRestorePoint -ErrorAction Stop
        Write-Info ("当前已有 {0} 个还原点" -f @($sr).Count)
    } catch {
        Write-Skip '读取不到还原点列表（可能没开启系统保护）'
    }
    try {
        Enable-ComputerRestore -Drive "$env:SystemDrive\" -ErrorAction Stop
        Write-Ok '系统保护已开启'
    } catch {
        Write-Warn "开启系统保护失败（不影响继续）：$($_.Exception.Message)"
    }
    if (-not (Confirm-Action '现在创建一个还原点？（建议做，出问题可以回退）' $true)) {
        Write-Skip '跳过创建还原点'
        return $false
    }
    try {
        Checkpoint-Computer -Description ("PcToolkit 修复前备份 {0}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm')) -RestorePointType 'MODIFY_SETTINGS' -ErrorAction Stop
        Write-Ok '还原点创建成功'
        return $true
    } catch {
        Write-Warn "还原点创建失败：$($_.Exception.Message)"
        Write-Info '（Windows 默认 24 小时内只允许创建一个还原点，如果刚刚创建过可以忽略）'
        return $false
    }
}

# ---------------------------------------------------------------- 环境变量修复

function Get-CleanedPathEntries {
    <#  返回清理后的项数组以及被删掉/补上的记录  #>
    param(
        [string]$RawPath,
        [switch]$IsMachine
    )
    $removed = New-Object System.Collections.ArrayList
    $keptMissing = New-Object System.Collections.ArrayList
    $kept = New-Object System.Collections.ArrayList
    $seen = @{}

    $items = @()
    if (-not [string]::IsNullOrWhiteSpace($RawPath)) { $items = $RawPath.Split(';') }
    foreach ($raw in $items) {
        $entry = "$raw".Trim()
        if ([string]::IsNullOrWhiteSpace($entry)) {
            if ($items.Count -gt 1) { [void]$removed.Add('（空项）') }
            continue
        }
        $clean = $entry.Trim('"').Trim()
        if ($clean.EndsWith('\') -and $clean.Length -gt 3) { $clean = $clean.TrimEnd('\') }

        $expanded = $clean
        try { $expanded = [Environment]::ExpandEnvironmentVariables($clean) } catch { }

        $key = $expanded.TrimEnd('\').ToLower()
        if ($seen.ContainsKey($key)) {
            [void]$removed.Add("重复：$clean")
            continue
        }

        $exists = $false
        try { $exists = Test-Path -LiteralPath $expanded } catch { $exists = $false }
        if (-not $exists) {
            # 安全考虑：这几种情况不删，只提醒
            $keepIt = $false
            $why = ''
            if ($clean -match 'WindowsApps') {
                $keepIt = $true
                $why = '应用商店应用专用目录，暂时读不到也不影响使用'
            } else {
                $rootDrive = ''
                try { $rootDrive = [System.IO.Path]::GetPathRoot($expanded) } catch { }
                if ($rootDrive -and $rootDrive -notmatch ('^' + [regex]::Escape($env:SystemDrive))) {
                    $keepIt = $true
                    $why = "它在 $($rootDrive.TrimEnd('\')) 盘上，可能只是盘没插/没连（保留）"
                }
            }
            if ($keepIt) {
                [void]$keptMissing.Add("$clean —— $why")
            } else {
                [void]$removed.Add("目录不存在：$clean")
                continue
            }
        }
        $seen[$key] = $true
        [void]$kept.Add($clean)
    }

    $added = New-Object System.Collections.ArrayList
    $mustHave = @()
    if ($IsMachine) {
        $mustHave = @(
            '%SystemRoot%\system32',
            '%SystemRoot%',
            '%SystemRoot%\System32\Wbem',
            '%SystemRoot%\System32\WindowsPowerShell\v1.0\'
        )
    } else {
        $mustHave = @('%USERPROFILE%\AppData\Local\Microsoft\WindowsApps')
    }
    foreach ($m in $mustHave) {
        $expandedM = [Environment]::ExpandEnvironmentVariables($m)
        $keyM = $expandedM.TrimEnd('\').ToLower()
        if (-not $seen.ContainsKey($keyM)) {
            [void]$kept.Insert(0, $m)
            $seen[$keyM] = $true
            [void]$added.Add($m)
        }
    }

    return [pscustomobject]@{
        Entries = @($kept)
        Removed = @($removed)
        Added   = @($added)
        KeptMissing = @($keptMissing)
        Text    = (@($kept) -join ';')
        OriginalCount = $items.Count
    }
}

function Repair-EnvironmentVariables {
    param([switch]$Apply)
    Write-Section '环境变量修复'
    Write-Info '会做三件事：① 删掉 PATH 里不存在的目录 ② 去掉重复项和空项 ③ 补回系统必需的目录'

    $machineRaw = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $userRaw    = [Environment]::GetEnvironmentVariable('Path', 'User')
    $machine = Get-CleanedPathEntries -RawPath $machineRaw -IsMachine
    $user    = Get-CleanedPathEntries -RawPath $userRaw

    Write-Host ''
    Write-Info ("系统 PATH：{0} 项 → {1} 项" -f $machine.OriginalCount, $machine.Entries.Count)
    foreach ($r in $machine.Removed) { Write-Warn "  删除 $r" }
    foreach ($a in $machine.Added) { Write-Info "  补回 $a" }
    foreach ($k in $machine.KeptMissing) { Write-Info "  保留 $k" }
    Write-Info ("用户 PATH：{0} 项 → {1} 项" -f $user.OriginalCount, $user.Entries.Count)
    foreach ($r in $user.Removed) { Write-Warn "  删除 $r" }
    foreach ($a in $user.Added) { Write-Info "  补回 $a" }
    foreach ($k in $user.KeptMissing) { Write-Info "  保留 $k" }

    $tempPlan = New-Object System.Collections.ArrayList
    $defaultUserTemp = Join-Path $env:USERPROFILE 'AppData\Local\Temp'
    $defaultMachineTemp = Join-Path $env:windir 'Temp'
    foreach ($scope in @('User', 'Machine')) {
        $want = $defaultUserTemp
        if ($scope -eq 'Machine') { $want = $defaultMachineTemp }
        foreach ($var in @('TEMP', 'TMP')) {
            $cur = [Environment]::GetEnvironmentVariable($var, $scope)
            $needFix = $false
            if ([string]::IsNullOrWhiteSpace($cur)) { $needFix = $true }
            else {
                $exists = $false
                try { $exists = Test-Path -LiteralPath $cur } catch { }
                if (-not $exists) { $needFix = $true }
            }
            $curText = $cur
            if ([string]::IsNullOrWhiteSpace($curText)) { $curText = '（空）' }
            if ($needFix) {
                [void]$tempPlan.Add([pscustomobject]@{ Scope = $scope; Var = $var; From = $curText; To = $want })
            }
        }
    }
    if ($tempPlan.Count -gt 0) {
        Write-Host ''
        Write-Info '临时目录变量需要修复：'
        foreach ($p in $tempPlan) { Write-Warn ("  {0} 的 {1}：{2} → {3}" -f $p.Scope, $p.Var, $p.From, $p.To) }
    } else {
        Write-Ok 'TEMP / TMP 变量正常'
    }

    $changeCount = $machine.Removed.Count + $machine.Added.Count + $user.Removed.Count + $user.Added.Count + $tempPlan.Count
    if ($changeCount -eq 0) {
        Write-Ok '环境变量没有需要修复的地方。'
        return $false
    }

    if (-not $Apply) {
        Write-Host ''
        Write-Warn '当前是预览模式，没有做任何修改。想真的修复请选择"执行修复"。'
        return $false
    }
    if (-not (Assert-Admin '修改系统 PATH 需要管理员权限')) { return $false }
    if (-not (Confirm-RepairNotBusy)) { return $false }
    if (-not (Confirm-Action ("确认修改环境变量吗？（会先自动备份，共 {0} 处改动）" -f $changeCount) $true)) {
    if (-not (Confirm-Action ("确认修改环境变量吗？（会先自动备份，共 {0} 处改动）" -f $changeCount) $true)) {
        Write-Skip '已取消'
        return $false
    }

    Write-Step '备份当前环境变量...'
    Backup-RegistryKey 'HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment' 'HKLM_Environment' | Out-Null
    Backup-RegistryKey 'HKCU\Environment' 'HKCU_Environment' | Out-Null
    $pathBackup = Join-Path $script:BackupDir ('PATH备份_{0}.txt' -f (Get-Date -Format 'yyyyMMdd_HHmmss'))
    try {
        $lines = @(
            '# 这是修改前的 PATH 备份，格式：范围<TAB>内容',
            ('系统' + "`t" + $machineRaw),
            ('用户' + "`t" + $userRaw)
        )
        $utf8Bom = New-Object System.Text.UTF8Encoding($true)
        [System.IO.File]::WriteAllText($pathBackup, ($lines -join "`r`n"), $utf8Bom)
        Write-Info "PATH 明文备份：$pathBackup"
    } catch {
        Write-Warn "PATH 备份文件写入失败：$($_.Exception.Message)"
    }

    Write-Step '写入新的环境变量...'
    try {
        [Environment]::SetEnvironmentVariable('Path', $machine.Text, 'Machine')
        Write-Ok '系统 PATH 已更新'
    } catch {
        Write-Err "系统 PATH 更新失败：$($_.Exception.Message)"
    }
    try {
        [Environment]::SetEnvironmentVariable('Path', $user.Text, 'User')
        Write-Ok '用户 PATH 已更新'
    } catch {
        Write-Err "用户 PATH 更新失败：$($_.Exception.Message)"
    }
    if (($machine.Text).Length -gt 3000) {
        Write-Warn '系统 PATH 特别长，个别老程序可能读不全，建议以后把不常用的路径删掉。'
    }

    foreach ($p in $tempPlan) {
        try {
            if (-not (Test-Path -LiteralPath $p.To)) { New-Item -ItemType Directory -Path $p.To -Force | Out-Null }
            [Environment]::SetEnvironmentVariable($p.Var, $p.To, $p.Scope)
            Write-Ok ("{0} 的 {1} 已设置为 {2}" -f $p.Scope, $p.Var, $p.To)
        } catch {
            Write-Err ("{0} 的 {1} 设置失败：{2}" -f $p.Scope, $p.Var, $_.Exception.Message)
        }
    }

    # 让当前窗口立即可用
    try { $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User') } catch { }
    Write-Ok '环境变量修复完成（新开的程序才会完全生效）'
    return $true
}

# ---------------------------------------------------------------- 垃圾清理

function Clear-JunkTargets {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Name,
        [switch]$Apply
    )
    $result = [pscustomobject]@{ Name = $Name; Path = $Path; RemovedFiles = 0; RemovedBytes = [long]0; Skipped = 0; Ok = $false }
    if ([string]::IsNullOrWhiteSpace($Path)) { return $result }
    $exists = $false
    try { $exists = Test-Path -LiteralPath $Path } catch { }
    if (-not $exists) { return $result }

    $items = @()
    try { $items = @(Get-ChildItem -LiteralPath $Path -Force -ErrorAction SilentlyContinue) } catch { return $result }
    $result.Ok = $true

    foreach ($item in $items) {
        $size = 0
        if ($item.PSIsContainer) {
            $st = Get-FolderStats -Path $item.FullName -TimeoutSeconds 10
            $size = $st.Bytes
        } else {
            $size = Get-FileSizeSafe $item.FullName
        }
        if (-not $Apply) {
            $result.RemovedFiles = $result.RemovedFiles + 1
            $result.RemovedBytes = $result.RemovedBytes + $size
            continue
        }
        $ok = Remove-PathSafe -Path $item.FullName -Recurse:$item.PSIsContainer
        if ($ok) {
            $result.RemovedFiles = $result.RemovedFiles + 1
            $result.RemovedBytes = $result.RemovedBytes + $size
        } else {
            $result.Skipped = $result.Skipped + 1
        }
    }
    return $result
}

function Clear-TempFiles {
    param(
        [switch]$Apply,
        [switch]$IncludeBrowserCache,
        [switch]$IncludeRecycleBin,
        [switch]$IncludeUpdateCache,
        [switch]$IncludeWinSxS
    )
    Write-Section '清理垃圾文件'
    $la = $env:LOCALAPPDATA
    $targets = New-Object System.Collections.ArrayList
    [void]$targets.Add(@{ Name = '用户临时文件'; Path = $env:TEMP })
    [void]$targets.Add(@{ Name = 'Windows 临时文件'; Path = (Join-Path $env:windir 'Temp') })
    [void]$targets.Add(@{ Name = '错误报告存档'; Path = (Join-Path $la 'Microsoft\Windows\WER\ReportArchive') })
    [void]$targets.Add(@{ Name = '错误报告队列'; Path = (Join-Path $la 'Microsoft\Windows\WER\ReportQueue') })
    [void]$targets.Add(@{ Name = '系统崩溃转储'; Path = (Join-Path $env:windir 'Minidump') })
    if ($IncludeUpdateCache) {
        [void]$targets.Add(@{ Name = 'Windows 更新缓存'; Path = (Join-Path $env:windir 'SoftwareDistribution\Download') })
        [void]$targets.Add(@{ Name = '传递优化缓存'; Path = (Join-Path $env:windir 'SoftwareDistribution\DeliveryOptimization') })
    }
    if ($IncludeBrowserCache) {
        [void]$targets.Add(@{ Name = 'Edge 缓存'; Path = (Join-Path $la 'Microsoft\Edge\User Data\Default\Cache') })
        [void]$targets.Add(@{ Name = 'Chrome 缓存'; Path = (Join-Path $la 'Google\Chrome\User Data\Default\Cache') })
    }

    $results = New-Object System.Collections.ArrayList
    foreach ($t in $targets) {
        $r = Clear-JunkTargets -Path $t.Path -Name $t.Name -Apply:$Apply
        [void]$results.Add($r)
    }
    $rbBytes = [long]0
    if ($IncludeRecycleBin) {
        $rb = Get-RecycleBinInfo
        $rbBytes = $rb.Bytes
        if ($Apply -and $rb.Count -gt 0) {
            if (Confirm-Action ("清空回收站（{0} 个文件）？清空后无法用回收站恢复" -f $rb.Count) $false) {
                try { Clear-RecycleBin -Force -ErrorAction Stop; Write-Ok '回收站已清空' } catch { Write-Warn "回收站清空失败：$($_.Exception.Message)" }
            } else { $rbBytes = 0; Write-Skip '保留回收站内容' }
        }
    }

    $totalFiles = 0; $totalBytes = [long]0; $totalSkipped = 0
    Write-Host ''
    foreach ($r in $results) {
        if (-not $r.Ok) { continue }
        $totalFiles += $r.RemovedFiles; $totalBytes += $r.RemovedBytes; $totalSkipped += $r.Skipped
        $skipText = ''
        if ($r.Skipped -gt 0) { $skipText = "，{0} 项正在使用中已跳过" -f $r.Skipped }
        Write-Info ("{0}：{1}（{2} 项{3}）" -f $r.Name, (Format-Bytes $r.RemovedBytes), $r.RemovedFiles, $skipText)
    }
    if ($IncludeRecycleBin) { Write-Info ("回收站：{0}" -f (Format-Bytes $rbBytes)); $totalBytes += $rbBytes }
    Write-Host ''
    if ($Apply) { Write-Ok ("共清理 " + (Format-Bytes $totalBytes) + "（$totalFiles 项）") }
    else { Write-Warn ("可清理约 " + (Format-Bytes $totalBytes) + "（$totalFiles 项）—— 当前是预览，什么都没删") }

    if ($IncludeWinSxS) {
        Write-Host ''
        Write-Info 'WinSxS（系统组件仓库）清理：用微软官方 DISM，可以安全回收几个 GB。'
        if ($Apply) {
            if (Assert-Admin '清理 WinSxS 需要管理员权限') {
                if (Confirm-Action '开始清理系统组件仓库？（可能要 5-20 分钟，请不要关窗口）' $true) {
                    Invoke-Native -FilePath 'DISM.exe' -Arguments @('/Online', '/Cleanup-Image', '/StartComponentCleanup') -FriendlyName 'DISM 清理组件仓库' | Out-Null
                    Write-Ok '组件仓库清理完成'
                }
            }
        } else {
            Write-Info '  预览模式：真正清理时才会执行 DISM /Online /Cleanup-Image /StartComponentCleanup'
        }
    }
    return [pscustomobject]@{ TotalBytes = $totalBytes; TotalFiles = $totalFiles; Results = @($results) }
}

# ---------------------------------------------------------------- 系统文件修复

function Repair-SystemFiles {
    param([switch]$Apply)
    Write-Section '修复系统文件（DISM + SFC）'
    Write-Info '说明：先用 DISM 修复系统映像，再用 SFC 扫描并修复系统文件。'
    Write-Info '这是微软官方的修复方式，能解决很多"缺少 dll""系统功能异常""某个设置打不开"的问题。'
    Write-Warn '耗时较长（一般 10-30 分钟），期间不要关机，DISM 会联网从 Windows 更新下载修复文件。'

    if (-not $Apply) {
        Write-Host ''
        Write-Warn '当前是预览模式。真正执行时会依次运行：'
        Write-Info '  DISM /Online /Cleanup-Image /ScanHealth'
        Write-Info '  DISM /Online /Cleanup-Image /RestoreHealth'
        Write-Info '  sfc /scannow'
        return $false
    }
    if (-not (Assert-Admin '修复系统文件需要管理员权限')) { return $false }
    if (-not (Confirm-RepairNotBusy)) { return $false }
    if (-not (Confirm-Action '现在开始修复系统文件？' $true)) { Write-Skip '已取消'; return $false }

    Set-ToolkitLock '系统文件修复（DISM + SFC）'
    $c1 = Invoke-Native -FilePath 'DISM.exe' -Arguments @('/Online', '/Cleanup-Image', '/ScanHealth') -FriendlyName '第 1 步：检查系统映像健康状态'
    Set-ToolkitLock '系统文件修复（DISM + SFC）'
    $c1 = Invoke-Native -FilePath 'DISM.exe' -Arguments @('/Online', '/Cleanup-Image', '/ScanHealth') -FriendlyName '第 1 步：检查系统映像健康状态'
    if ($c1 -ne 0) { Write-Warn "ScanHealth 返回码 $c1（有些系统会返回非 0，属正常）" }

    $c2 = Invoke-Native -FilePath 'DISM.exe' -Arguments @('/Online', '/Cleanup-Image', '/RestoreHealth') -FriendlyName '第 2 步：修复系统映像（最慢的一步）'
    if ($c2 -eq 0) { Write-Ok 'DISM 修复成功' } else { Write-Warn "DISM 返回码 $c2，如果日志里有 0x800f081f 通常是没有网络或更新源问题" }

    $c3 = Invoke-Native -FilePath 'sfc.exe' -Arguments @('/scannow') -FriendlyName '第 3 步：扫描并修复系统文件'
    if ($c3 -eq 0) { Write-Ok 'SFC 扫描完成（详细信息看上面输出，或 C:\Windows\Logs\CBS\CBS.log）' }
    else { Write-Warn "SFC 返回码 $c3" }

    Clear-ToolkitLock
    Write-Warn '强烈建议重启电脑，让修复结果生效。'
    return $true
}
}

function Repair-DiskCheck {
    param([switch]$Apply, [switch]$Fix)
    Write-Section '磁盘检查'
    $drive = $env:SystemDrive
    if (-not $Apply) {
        Write-Info "预览模式。真正执行时会运行：chkdsk $drive /scan（只读扫描，不修也不重启）"
        if ($Fix) { Write-Info "另外会安排：chkdsk $drive /f（下次重启时自动修复文件系统错误）" }
        return $false
    }
    if (-not (Assert-Admin '磁盘检查需要管理员权限')) { return $false }
    if (-not (Confirm-RepairNotBusy)) { return $false }
    if (-not (Confirm-RepairNotBusy)) { return $false }

    Write-Info '先确认磁盘有没有被标记为"脏"（需要检查）...'
    $out = & fsutil.exe dirty query "$drive" 2>&1
    Write-Info "$out"

    if (-not (Confirm-Action "现在只读扫描 $drive（不修改任何东西，几分钟）？" $true)) { Write-Skip '已取消'; return $false }
    Set-ToolkitLock ('磁盘检查 ' + "$drive")
    $c = Invoke-Native -FilePath 'chkdsk.exe' -Arguments @("$drive", '/scan') -FriendlyName "chkdsk $drive /scan"
    Clear-ToolkitLock
    if ($c -eq 0) { Write-Ok '磁盘扫描完成，文件系统没有大问题' } else { Write-Warn "chkdsk 返回码 $c" }
    Clear-ToolkitLock
    if ($c -eq 0) { Write-Ok '磁盘扫描完成，文件系统没有大问题' } else { Write-Warn "chkdsk 返回码 $c" }

    if ($Fix) {
        Write-Host ''
        Write-Warn '接下来会安排在下次重启时修复文件系统（会锁盘几分钟，期间不要强制关机）。'
        if (Confirm-Action '要安排重启时修复吗？' $false) {
            try {
                $out2 = "Y`r`n" | & chkdsk.exe "$drive" /f 2>&1
                Write-Info "$out2"
                Write-Ok '已安排，下次重启会自动检查并修复'
            } catch {
                Write-Warn "安排失败：$($_.Exception.Message)"
            }
        }
    }
    return $true
}

# ---------------------------------------------------------------- 网络 / 更新 / 图标

function Repair-NetworkStack {
    param([switch]$Apply, [switch]$ResetFirewall)
    Write-Section '修复网络组件'
    Write-Info '会用 Windows 自带命令重置网络协议栈，专治：能连网但网页打不开、DNS 解析失败、'
    Write-Info '某些软件上不了网、代理设置残留、WinHTTP 代理被改坏等。'
    if ($ResetFirewall) { Write-Warn '你还选择了重置防火墙，这会删掉自己加过的所有防火墙规则，恢复默认。' }

    if (-not $Apply) {
        Write-Host ''
        Write-Warn '预览模式，真正执行时会依次运行：'
        Write-Info '  ipconfig /flushdns'
        Write-Info '  netsh winsock reset'
        Write-Info '  netsh int ip reset'
        Write-Info '  netsh int ipv4 reset / ipv6 reset'
        if ($ResetFirewall) { Write-Info '  netsh advfirewall reset' }
        Write-Info '  最后重启电脑'
        return $false
    }
    if (-not (Assert-Admin '重置网络需要管理员权限')) { return $false }
    if (-not (Confirm-Action '开始重置网络组件？（完成后需要重启电脑）' $true)) { Write-Skip '已取消'; return $false }

    Invoke-Native -FilePath 'ipconfig.exe' -Arguments @('/flushdns') -FriendlyName '清空 DNS 缓存' | Out-Null
    Invoke-Native -FilePath 'netsh.exe' -Arguments @('winsock', 'reset') -FriendlyName '重置 Winsock' | Out-Null
    Invoke-Native -FilePath 'netsh.exe' -Arguments @('int', 'ip', 'reset') -FriendlyName '重置 IP 协议栈' | Out-Null
    Invoke-Native -FilePath 'netsh.exe' -Arguments @('int', 'ipv4', 'reset') -FriendlyName '重置 IPv4' | Out-Null
    Invoke-Native -FilePath 'netsh.exe' -Arguments @('int', 'ipv6', 'reset') -FriendlyName '重置 IPv6' | Out-Null
    if ($ResetFirewall) {
        if (Confirm-Action '确认重置防火墙规则？（自定义规则会丢失）' $false) {
            Invoke-Native -FilePath 'netsh.exe' -Arguments @('advfirewall', 'reset') -FriendlyName '重置防火墙' | Out-Null
        }
    }
    Write-Ok '网络组件已重置'
    Write-Warn '必须重启电脑才会完全生效。'
    return $true
}

function Repair-UpdateComponents {
    param([switch]$Apply)
    Write-Section '重置 Windows 更新组件'
    Write-Info '专治：更新一直失败、卡在某个百分比、报 0x800700xx、更新历史打不开、'
    Write-Info 'Microsoft Store 装不了应用。做法是停掉更新服务、清掉下载缓存、重建缓存目录。'
    if (-not $Apply) {
        Write-Host ''
        Write-Warn '预览模式，真正执行时会：'
        Write-Info '  停止 wuauserv / BITS / CryptSvc / msiserver 服务'
        Write-Info '  把 C:\Windows\SoftwareDistribution 和 catroot2 改名备份（不删除）'
        Write-Info '  重新启动这些服务'
        return $false
    }
    if (-not (Assert-Admin '重置更新组件需要管理员权限')) { return $false }
    if (-not (Confirm-RepairNotBusy)) { return $false }
    if (-not (Confirm-Action '开始重置 Windows 更新组件？' $true)) { Write-Skip '已取消'; return $false }

    Set-ToolkitLock '重置 Windows 更新组件'
    $services = @('wuauserv', 'bits', 'cryptsvc', 'msiserver')
    Set-ToolkitLock '重置 Windows 更新组件'
    $services = @('wuauserv', 'bits', 'cryptsvc', 'msiserver')
    foreach ($s in $services) {
        try { Start-Service -Name $s -ErrorAction SilentlyContinue; Write-Log "启动服务 $s" } catch { }
    }
    Clear-ToolkitLock
    Write-Ok '更新组件已重置，系统会自动重建缓存'

    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    foreach ($folder in @('SoftwareDistribution', 'catroot2')) {
        $src = Join-Path $env:windir $folder
        if (Test-Path -LiteralPath $src) {
            $dst = "$src.old_$stamp"
            try {
                Move-Item -LiteralPath $src -Destination $dst -Force -ErrorAction Stop
                Write-Ok "$folder 已改名备份为 $(Split-Path -Leaf $dst)"
            } catch {
                Write-Warn "$folder 改名失败（可能有程序在用）：$($_.Exception.Message)"
            }
        }
    }
    foreach ($s in $services) {
        try { Start-Service -Name $s -ErrorAction SilentlyContinue; Write-Log "启动服务 $s" } catch { }
    }
    Clear-ToolkitLock
    Write-Ok '更新组件已重置，系统会自动重建缓存'
    Write-Info '提示：备份的 .old 目录确认更新正常后可以删掉（能腾出几个 GB）。'
    return $true
}

function Repair-IconCache {
    param([switch]$Apply)
    Write-Section '重建图标 / 缩略图缓存'
    Write-Info '专治：图标变成白纸、图标显示错乱、缩略图不刷新、文件夹图标不对。'
    if (-not $Apply) {
        Write-Warn '预览模式。真正执行时会关闭"文件资源管理器(explorer.exe)"，删除缓存文件后再打开。'
        Write-Info '（桌面和任务栏会闪一下，正在复制的文件建议先完成）'
        return $false
    }
    if (-not (Confirm-Action '开始重建图标缓存？（文件资源管理器会重启）' $true)) { Write-Skip '已取消'; return $false }

    $explorerDir = Join-Path $env:LOCALAPPDATA 'Microsoft\Windows\Explorer'
    $killed = $false
    try {
        Stop-Process -Name explorer -Force -ErrorAction Stop
        $killed = $true
        Start-Sleep -Milliseconds 1200
        Write-Info '已关闭文件资源管理器'
    } catch {
        Write-Warn "关闭资源管理器失败（继续尝试删缓存）：$($_.Exception.Message)"
    }
    $removed = 0
    try {
        foreach ($f in (Get-ChildItem -LiteralPath $explorerDir -Filter '*.db' -Force -ErrorAction SilentlyContinue)) {
            if (Remove-PathSafe -Path $f.FullName) { $removed++ }
        }
        foreach ($pat in @('iconcache*', 'thumbcache*')) {
            foreach ($f in (Get-ChildItem -LiteralPath $explorerDir -Filter $pat -Force -ErrorAction SilentlyContinue)) {
                if (Remove-PathSafe -Path $f.FullName) { $removed++ }
            }
        }
    } catch { }
    Write-Ok "已删除 $removed 个缓存文件"

    if ($killed) {
        try {
            Start-Process explorer.exe
            Write-Ok '文件资源管理器已重新启动'
        } catch { Write-Warn '请手动按 Ctrl+Shift+Esc → 运行新任务 → 输入 explorer' }
    }
    Write-Info '图标缓存会在打开文件夹时自动重建。'
    return $true
}

# ---------------------------------------------------------------- 运行库

function Show-RuntimeHelp {
    param([switch]$Install, [switch]$Apply)
    Write-Section '运行库检查与安装'
    $rt = Get-RuntimeReport
    Write-Info ("已检测到：" + $(if ($rt.VCpp.Count -eq 0) { '（没有检测到 VC++ 运行库）' } else { $rt.VCpp -join '、' }))
    Write-Info ".NET Framework：$($rt.NetFx)"
    if ($rt.VCppMissing.Count -eq 0) {
        Write-Ok '常用的 VC++ 运行库看起来是齐的。'
    } else {
        Write-Warn ('缺少：' + ($rt.VCppMissing -join '；'))
        Write-Info '很多游戏、建模软件、Office 插件都依赖它，缺了会报"缺少 xxx.dll"。'
        Write-Host ''
        Write-Info '微软官方下载地址（自己下载也一样）：'
        Write-Info '  64 位：https://aka.ms/vs/17/release/vc_redist.x64.exe'
        Write-Info '  32 位：https://aka.ms/vs/17/release/vc_redist.x86.exe'
    }

    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $Install) { return }
    if (-not $winget) {
        Write-Warn '没有找到 winget（应用安装器），请用上面的官方链接手动安装。'
        return
    }
    Write-Host ''
    Write-Info '检测到 winget，可以用它自动安装运行库（需要联网）。'
    if (-not $Apply) {
        Write-Warn '预览模式。真正执行时会运行：winget install Microsoft.VCRedist.2015+.x64 / .x86'
        return
    }
    if (-not (Confirm-Action '开始用 winget 安装/修复 VC++ 运行库？' $true)) { Write-Skip '已取消'; return }
    Invoke-Native -FilePath $winget.Source -Arguments @('install', '--id', 'Microsoft.VCRedist.2015+.x64', '--accept-package-agreements', '--accept-source-agreements', '-e') -FriendlyName '安装 VC++ x64' | Out-Null
    Invoke-Native -FilePath $winget.Source -Arguments @('install', '--id', 'Microsoft.VCRedist.2015+.x86', '--accept-package-agreements', '--accept-source-agreements', '-e') -FriendlyName '安装 VC++ x86' | Out-Null
    Write-Ok '运行库安装流程结束（如果提示已安装，说明本来就是好的）。'
}

function Repair-WinSxS {
    param([switch]$Apply)
    Write-Section '清理系统组件仓库（WinSxS）'
    Write-Info '用微软官方 DISM 清理旧的组件版本，通常能回收 2-8 GB，是安全的。'
    if (-not $Apply) {
        Write-Warn '预览模式。真正执行时会运行：DISM /Online /Cleanup-Image /StartComponentCleanup'
        return $false
    }
    if (-not (Assert-Admin '需要管理员权限')) { return $false }
    if (-not (Confirm-RepairNotBusy)) { return $false }
    if (-not (Confirm-Action '开始清理？（可能 5-20 分钟）' $true)) { Write-Skip '已取消'; return $false }
    Set-ToolkitLock '清理系统组件仓库 WinSxS'
    Invoke-Native -FilePath 'DISM.exe' -Arguments @('/Online', '/Cleanup-Image', '/StartComponentCleanup') -FriendlyName 'DISM 清理' | Out-Null
    Clear-ToolkitLock
    Write-Ok '完成'
    return $true
}

function Repair-FullRun {
    <#  一键按顺序修一遍：还原点 → 环境变量 → 垃圾 → 系统文件 → 磁盘 → 报告  #>
    param([switch]$Apply)
    Write-Title '一键修复（按安全顺序执行）'
    Write-Info '执行顺序：① 创建还原点 ② 修复环境变量 ③ 清理垃圾文件 ④ 修复系统文件 ⑤ 磁盘扫描'
    Write-Info '每一步都会先问你，可以不做的直接跳过。'
    if (-not $Apply) {
        Write-Warn '当前是预览模式：只会展示每一步会做什么，不会真的改。'
        Write-Info '真正执行时会依次：创建还原点 → 环境变量修复 → 清理垃圾 → DISM+SFC → chkdsk /scan'
        Write-Info '想真正执行，请在菜单里选择"一键修复"。'
        return
    }
    if (-not (Assert-Admin '一键修复里的系统级操作需要管理员权限')) { return }
    if (-not (Confirm-RepairNotBusy)) { return }
    Set-ToolkitLock '一键修复'
    New-RestorePointSafe | Out-Null
    Set-ToolkitLock '一键修复'
    New-RestorePointSafe | Out-Null
    Repair-EnvironmentVariables -Apply | Out-Null
    Clear-TempFiles -Apply -IncludeRecycleBin:$false | Out-Null
    Repair-SystemFiles -Apply | Out-Null
    Repair-DiskCheck -Apply | Out-Null
    Clear-ToolkitLock
    Write-Section '修复流程结束'
    Write-Section '修复流程结束'
    Write-Info '建议重启电脑，然后重新跑一次"一键体检"对比分数。'
}
