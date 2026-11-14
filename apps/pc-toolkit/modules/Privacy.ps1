<#
    电脑管家 PcToolkit - 深度清理 / 隐私痕迹模块
    参考火绒的垃圾清理分类与 PrivaZer 的隐私痕迹思路：
      - 深度垃圾：日志、转储、缩略图、更新缓存、Windows.old 等
      - 隐私痕迹：浏览器历史/Cookie/站点数据、最近记录、跳转列表、运行历史、DNS、剪贴板
      - 可选安全擦除：删除前用随机数据覆写文件
      - 可选空闲空间擦除：cipher /w
    安全原则：默认只扫描不删除；删除前要求确认；注册表先导出备份。
#>

function Get-DeepJunkTargets {
    param([switch]$IncludeAdvanced)
    $la = $env:LOCALAPPDATA
    $win = $env:windir
    $targets = New-Object System.Collections.ArrayList
    $add = {
        param($Name, $Path, $Kind = 'dir', $Pattern = '', $Note = '')
        [void]$targets.Add([pscustomobject]@{ Name = $Name; Path = $Path; Kind = $Kind; Pattern = $Pattern; Note = $Note })
    }
    & $add 'Windows 临时文件' (Join-Path $win 'Temp') 'dir'
    & $add '用户临时文件' $env:TEMP 'dir'
    & $add '错误报告存档' (Join-Path $la 'Microsoft\Windows\WER\ReportArchive') 'dir'
    & $add '错误报告队列' (Join-Path $la 'Microsoft\Windows\WER\ReportQueue') 'dir'
    & $add '系统崩溃转储' (Join-Path $win 'Minidump') 'dir'
    & $add '完整内存转储' (Join-Path $win 'MEMORY.DMP') 'file'
    & $add 'CBS 日志' (Join-Path $win 'Logs\CBS') 'dir'
    & $add 'DISM 日志' (Join-Path $win 'Logs\DISM') 'dir'
    & $add 'Windows 更新日志' (Join-Path $win 'Logs\WindowsUpdate') 'dir'
    & $add '传递优化缓存' (Join-Path $win 'SoftwareDistribution\DeliveryOptimization') 'dir'
    & $add '旧版 Windows 安装文件' (Join-Path $env:SystemDrive 'Windows.old') 'dir' '' '需要管理员；失败时请用磁盘清理'
    & $add '缩略图缓存' (Join-Path $la 'Microsoft\Windows\Explorer') 'pattern' 'thumbcache_*.db'
    & $add '图标缓存' (Join-Path $la 'Microsoft\Windows\Explorer') 'pattern' 'iconcache_*.db'
    if ($IncludeAdvanced) {
        & $add 'Prefetch 预读取' (Join-Path $win 'Prefetch') 'dir' '' '删除后前几次启动会慢一些'
        & $add '零售演示内容' (Join-Path $env:ProgramData 'Microsoft\Windows\RetailDemo') 'dir'
        & $add '字体缓存' (Join-Path $la 'Microsoft\Windows\Fonts') 'pattern' '*.dat' '被占用时会自动跳过'
    }
    return @($targets)
}

function Measure-PrivacyTarget {
    param([pscustomobject]$Target)
    $result = [pscustomobject]@{
        Name = $Target.Name; Path = $Target.Path; Kind = $Target.Kind; Pattern = $Target.Pattern
        Note = $Target.Note; Exists = $false; Items = 0; Bytes = [long]0; Risky = [bool]$Target.Risky
    }
    if ($Target.Kind -eq 'registry') {
        try {
            $key = Get-Item -LiteralPath $Target.Path -ErrorAction Stop
            $result.Exists = $true
            $result.Items = @($key.Property).Count
            $result.Bytes = 0
        } catch { }
        return $result
    }
    if ([string]::IsNullOrWhiteSpace($Target.Path)) { return $result }
    if ($Target.Kind -eq 'pattern') {
        try {
            $files = @(Get-ChildItem -LiteralPath $Target.Path -Filter $Target.Pattern -File -Force -ErrorAction SilentlyContinue)
            $result.Exists = $files.Count -gt 0
            $result.Items = $files.Count
            foreach ($f in $files) { $result.Bytes += (Get-FileSizeSafe $f.FullName) }
        } catch { }
        return $result
    }
    if (-not (Test-Path -LiteralPath $Target.Path)) { return $result }
    $result.Exists = $true
    if ($Target.Kind -eq 'file') {
        $result.Items = 1
        $result.Bytes = Get-FileSizeSafe $Target.Path
    } else {
        $stats = Get-FolderStats -Path $Target.Path -TimeoutSeconds 15
        $result.Items = $stats.Files
        $result.Bytes = $stats.Bytes
    }
    return $result
}

function Get-DeepJunkReport {
    param([switch]$IncludeAdvanced)
    $items = @(Get-DeepJunkTargets -IncludeAdvanced:$IncludeAdvanced | ForEach-Object { Measure-PrivacyTarget $_ })
    $bytes = [long]0; $count = 0
    foreach ($i in $items) { if ($i.Exists) { $bytes += $i.Bytes; $count += $i.Items } }
    return [pscustomobject]@{ Items = $items; TotalBytes = $bytes; TotalItems = $count }
}

function Clear-DeepJunk {
    param([switch]$Apply, [switch]$IncludeAdvanced)
    $script:AssumeYes = $true
    $report = Get-DeepJunkReport -IncludeAdvanced:$IncludeAdvanced
    Write-Section '深度垃圾扫描'
    foreach ($item in $report.Items) {
        if (-not $item.Exists) { continue }
        $mark = '可清理'
        if ($item.Note) { $mark = $item.Note }
        Write-Info ("{0}：{1}（{2} 项，{3}）" -f $item.Name, (Format-Bytes $item.Bytes), $item.Items, $mark)
    }
    Write-Host ''
    Write-Info ("合计：{0}（{1} 项）" -f (Format-Bytes $report.TotalBytes), $report.TotalItems)
    if (-not $Apply) { Write-Warn '当前是预览，什么都没删'; return $report }

    $removedBytes = [long]0; $removedItems = 0; $skipped = 0
    foreach ($item in $report.Items) {
        if (-not $item.Exists) { continue }
        switch ($item.Kind) {
            'file' { if (Remove-PathSafe -Path $item.Path) { $removedBytes += $item.Bytes; $removedItems += 1 } else { $skipped += 1 } }
            'dir' {
                $r = Clear-JunkTargets -Path $item.Path -Name $item.Name -Apply
                $removedBytes += $r.RemovedBytes; $removedItems += $r.RemovedFiles; $skipped += $r.Skipped
            }
            'pattern' {
                $files = @(Get-ChildItem -LiteralPath $item.Path -Filter $item.Pattern -File -Force -ErrorAction SilentlyContinue)
                foreach ($f in $files) {
                    $size = Get-FileSizeSafe $f.FullName
                    if (Remove-PathSafe -Path $f.FullName) { $removedBytes += $size; $removedItems += 1 } else { $skipped += 1 }
                }
            }
        }
    }
    Write-Host ''
    Write-Ok ("深度清理完成：{0}（{1} 项，{2} 项占用中已跳过）" -f (Format-Bytes $removedBytes), $removedItems, $skipped)
    return $report
}

function Get-BrowserPrivacyTargets {
    $la = $env:LOCALAPPDATA
    $app = $env:APPDATA
    $result = New-Object System.Collections.ArrayList
    $browsers = @(
        @{ Name = 'Edge'; Root = (Join-Path $la 'Microsoft\Edge\User Data') },
        @{ Name = 'Chrome'; Root = (Join-Path $la 'Google\Chrome\User Data') },
        @{ Name = 'Brave'; Root = (Join-Path $la 'BraveSoftware\Brave-Browser\User Data') }
    )
    foreach ($browser in $browsers) {
        if (-not (Test-Path -LiteralPath $browser.Root)) { continue }
        $profiles = @(Get-ChildItem -LiteralPath $browser.Root -Directory -Force -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -eq 'Default' -or $_.Name -like 'Profile *' })
        foreach ($profile in $profiles) {
            $p = $profile.FullName
            $tag = "$($browser.Name) [$($profile.Name)]"
            $add = {
                param($Name, $Path, $Kind = 'file', $Risky = $false)
                [void]$result.Add([pscustomobject]@{ Name = "$tag $Name"; Path = $Path; Kind = $Kind; Pattern = ''; Note = ''; Risky = $Risky })
            }
            & $add '历史记录' (Join-Path $p 'History')
            & $add 'Cookie' (Join-Path $p 'Network\Cookies')
            & $add 'Cookie(旧)' (Join-Path $p 'Cookies')
            & $add '自动填充' (Join-Path $p 'Web Data') $true
            & $add '访问过的链接' (Join-Path $p 'Visited Links')
            & $add '常去网站' (Join-Path $p 'Top Sites')
            & $add '缓存' (Join-Path $p 'Cache') 'dir'
            & $add '代码缓存' (Join-Path $p 'Code Cache') 'dir'
            & $add 'GPU 缓存' (Join-Path $p 'GPUCache') 'dir'
            & $add 'Service Worker 缓存' (Join-Path $p 'Service Worker\CacheStorage') 'dir'
            & $add '会话存储' (Join-Path $p 'Session Storage') 'dir' $true
            & $add '站点数据' (Join-Path $p 'Local Storage') 'dir' $true
        }
    }
    $firefoxRoot = Join-Path $app 'Mozilla\Firefox\Profiles'
    if (Test-Path -LiteralPath $firefoxRoot) {
        foreach ($profile in @(Get-ChildItem -LiteralPath $firefoxRoot -Directory -Force -ErrorAction SilentlyContinue)) {
            $p = $profile.FullName
            $tag = "Firefox [$($profile.Name)]"
            foreach ($pair in @(
                @('历史记录', 'places.sqlite'),
                @('Cookie', 'cookies.sqlite'),
                @('会话', 'sessionstore.jsonlz4')
            )) {
                [void]$result.Add([pscustomobject]@{ Name = "$tag $($pair[0])"; Path = (Join-Path $p $pair[1]); Kind = 'file'; Pattern = ''; Note = ''; Risky = $false })
            }
            foreach ($dir in @('cache2', 'startupCache')) {
                [void]$result.Add([pscustomobject]@{ Name = "$tag $dir"; Path = (Join-Path $p $dir); Kind = 'dir'; Pattern = ''; Note = ''; Risky = $false })
            }
        }
    }
    return @($result)
}

function Get-WindowsPrivacyTargets {
    $la = $env:LOCALAPPDATA
    $app = $env:APPDATA
    $result = New-Object System.Collections.ArrayList
    $add = {
        param($Name, $Path, $Kind = 'dir', $Pattern = '', $Risky = $false)
        [void]$result.Add([pscustomobject]@{ Name = $Name; Path = $Path; Kind = $Kind; Pattern = $Pattern; Note = ''; Risky = $Risky })
    }
    $recent = Join-Path $app 'Microsoft\Windows\Recent'
    & $add '最近使用的文件' $recent 'dir'
    & $add '跳转列表（自动）' (Join-Path $recent 'AutomaticDestinations') 'dir'
    & $add '跳转列表（自定义）' (Join-Path $recent 'CustomDestinations') 'dir'
    & $add 'IE/Edge 旧缓存' (Join-Path $la 'Microsoft\Windows\INetCache') 'dir'
    & $add '缩略图缓存' (Join-Path $la 'Microsoft\Windows\Explorer') 'pattern' 'thumbcache_*.db'
    & $add 'PowerShell 命令历史' (Join-Path $app 'Microsoft\Windows\PowerShell\PSReadLine\ConsoleHost_history.txt') 'file'
    foreach ($key in @(
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\RunMRU',
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\TypedPaths',
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\RecentDocs',
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\ComDlg32\OpenSavePidlMRU',
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\ComDlg32\LastVisitedPidlMRU',
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Search\RecentApps',
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\WordWheelQuery'
    )) {
        & $add ("注册表痕迹：{0}" -f (Split-Path -Leaf $key)) $key 'registry'
    }
    return @($result)
}

function Get-PrivacyReport {
    param([switch]$IncludeBrowser = $true, [switch]$IncludeWindows = $true)
    $targets = New-Object System.Collections.ArrayList
    if ($IncludeBrowser) { foreach ($t in @(Get-BrowserPrivacyTargets)) { [void]$targets.Add($t) } }
    if ($IncludeWindows) { foreach ($t in @(Get-WindowsPrivacyTargets)) { [void]$targets.Add($t) } }
    $items = @($targets | ForEach-Object { Measure-PrivacyTarget $_ })
    $bytes = [long]0; $count = 0
    foreach ($i in $items) { if ($i.Exists) { $bytes += $i.Bytes; $count += $i.Items } }
    return [pscustomobject]@{ Items = $items; TotalBytes = $bytes; TotalItems = $count }
}

function Remove-PathSecure {
    param([Parameter(Mandatory)][string]$Path, [switch]$Recurse)
    try {
        if (Test-Path -LiteralPath $Path -PathType Container) {
            foreach ($f in @(Get-ChildItem -LiteralPath $Path -Recurse -Force -File -ErrorAction SilentlyContinue)) {
                [void](Remove-PathSecure -Path $f.FullName)
            }
            Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
            return $true
        }
        $info = New-Object System.IO.FileInfo($Path)
        if (-not $info.Exists) { return $true }
        if ($info.Length -gt 0 -and $info.Length -le 268435456) {
            $fs = [System.IO.File]::Open($Path, 'Open', 'ReadWrite', 'None')
            try {
                $buffer = New-Object byte[] 65536
                $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
                $left = $fs.Length
                while ($left -gt 0) {
                    $n = [Math]::Min($buffer.Length, $left)
                    $rng.GetBytes($buffer)
                    $fs.Write($buffer, 0, $n)
                    $left -= $n
                }
                $fs.Flush()
            } finally { $fs.Close(); $fs.Dispose() }
        }
        Remove-Item -LiteralPath $Path -Force -ErrorAction Stop
        return $true
    } catch { return $false }
}

function Clear-PrivacyTraces {
    param([switch]$Apply, [switch]$IncludeBrowser = $true, [switch]$IncludeWindows = $true, [switch]$Secure)
    $script:AssumeYes = $true
    if ($IncludeBrowser) {
        $running = @(Get-Process -Name msedge, chrome, brave, firefox -ErrorAction SilentlyContinue)
        if ($running.Count -gt 0) {
            Write-Warn '检测到浏览器正在运行，浏览器历史/Cookie/缓存会被占用，本次先跳过浏览器部分。'
            $IncludeBrowser = $false
        }
    }
    $report = Get-PrivacyReport -IncludeBrowser:$IncludeBrowser -IncludeWindows:$IncludeWindows
    Write-Section '隐私痕迹扫描'
    foreach ($item in $report.Items) {
        if (-not $item.Exists) { continue }
        $risk = ''
        if ($item.Risky) { $risk = '（可能退出登录）' }
        Write-Info ("{0}：{1}（{2} 项）{3}" -f $item.Name, (Format-Bytes $item.Bytes), $item.Items, $risk)
    }
    Write-Host ''
    Write-Info ("合计：{0}（{1} 项）" -f (Format-Bytes $report.TotalBytes), $report.TotalItems)
    if (-not $Apply) { Write-Warn '当前是预览，什么都没删'; return $report }

    $removedBytes = [long]0; $removedItems = 0; $skipped = 0
    foreach ($item in $report.Items) {
        if (-not $item.Exists) { continue }
        if ($item.Kind -eq 'registry') {
            $backupPath = $item.Path -replace '^HKCU:\\', 'HKCU\' -replace '^HKLM:\\', 'HKLM\'
            $null = Backup-RegistryKey -KeyPath $backupPath -FileName (($item.Name -replace '[^\w\-]', '_'))
            try { Remove-Item -LiteralPath $item.Path -Recurse -Force -ErrorAction Stop; $removedItems += $item.Items }
            catch { $skipped += 1 }
            continue
        }
        if ($item.Kind -eq 'file') {
            $ok = if ($Secure) { Remove-PathSecure -Path $item.Path } else { Remove-PathSafe -Path $item.Path }
            if ($ok) { $removedBytes += $item.Bytes; $removedItems += 1 } else { $skipped += 1 }
            continue
        }
        if ($item.Kind -eq 'dir') {
            if ($Secure) {
                if (Remove-PathSecure -Path $item.Path -Recurse) { $removedBytes += $item.Bytes; $removedItems += $item.Items } else { $skipped += 1 }
            } else {
                $r = Clear-JunkTargets -Path $item.Path -Name $item.Name -Apply
                $removedBytes += $r.RemovedBytes; $removedItems += $r.RemovedFiles; $skipped += $r.Skipped
            }
            continue
        }
        if ($item.Kind -eq 'pattern') {
            $files = @(Get-ChildItem -LiteralPath $item.Path -Filter $item.Pattern -File -Force -ErrorAction SilentlyContinue)
            foreach ($f in $files) {
                $size = Get-FileSizeSafe $f.FullName
                $ok = if ($Secure) { Remove-PathSecure -Path $f.FullName } else { Remove-PathSafe -Path $f.FullName }
                if ($ok) { $removedBytes += $size; $removedItems += 1 } else { $skipped += 1 }
            }
        }
    }
    try { Set-Clipboard -Value $null -ErrorAction SilentlyContinue } catch { }
    try { & ipconfig.exe /flushdns 2>&1 | Out-Null; Write-Ok 'DNS 缓存已刷新' } catch { }
    Write-Host ''
    Write-Ok ("隐私清理完成：{0}（{1} 项，{2} 项占用中已跳过）" -f (Format-Bytes $removedBytes), $removedItems, $skipped)
    return $report
}

function Invoke-FreeSpaceWipe {
    param([string]$Drive = 'C:')
    $Drive = $Drive.TrimEnd('\')
    if ($Drive -notmatch '^[A-Za-z]:$') { $Drive = 'C:' }
    if (-not (Assert-Admin '擦除空闲空间需要管理员权限')) { return }
    if (-not (Confirm-Action ("用 cipher /w:{0} 擦除该盘空闲空间？`n`n这会把已删除文件的残留数据覆写掉（PrivaZer 效果），可能耗时几十分钟，期间可以继续用电脑。" -f $Drive) $false)) { return }
    Write-Info ("开始擦除 {0} 的空闲空间，请耐心等待..." -f $Drive)
    Invoke-Native -FilePath 'cipher.exe' -Arguments @("/w:$Drive") -FriendlyName "擦除 $Drive 空闲空间" | Out-Null
    Write-Ok '空闲空间擦除完成'
}
