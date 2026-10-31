<#
    电脑管家 PcToolkit - 体检模块（只读，不改动任何东西）
    采集：系统概况 / 磁盘 / 垃圾体积 / 启动项 / 服务 / 设备 / 环境变量 / 运行库 /
          快捷方式断链 / 事件日志 / Windows 更新 / 磁盘健康
    所有采集都做了容错：某个接口不可用（WMI 损坏、无权限）只跳过并记录，不会中断体检。
#>

# ---------------------------------------------------------------- 单项采集

function Get-SystemOverview {
    $os = [ordered]@{
        Caption = '未知'; DisplayVersion = ''; Build = ''; Arch = $env:PROCESSOR_ARCHITECTURE
        ComputerName = $env:COMPUTERNAME; UserName = $env:USERNAME
        CPU = '未知'; RAM = '未知'; GPU = '未知'; Uptime = '未知'; LastBoot = $null
        WmiOk = $true; Notes = @()
    }
    $notes = New-Object System.Collections.ArrayList

    $cv = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
    $os.Caption = Get-RegValue $cv 'ProductName' '未知'
    $os.DisplayVersion = Get-RegValue $cv 'DisplayVersion' ''
    if (-not $os.DisplayVersion) { $os.DisplayVersion = Get-RegValue $cv 'ReleaseId' '' }
    $build = Get-RegValue $cv 'CurrentBuildNumber' ''
    $ubr = Get-RegValue $cv 'UBR' ''
    if ($build) { $os.Build = "$build.$ubr" }

    $os.CPU = Get-RegValue 'HKLM:\HARDWARE\DESCRIPTION\System\CentralProcessor\0' 'ProcessorNameString' '未知'

    $gpuKey = 'HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}'
    $gpus = @()
    try {
        Get-ChildItem $gpuKey -ErrorAction Stop | ForEach-Object {
            $d = Get-RegValue $_.PSPath 'DriverDesc'
            if ($d) { $gpus += $d }
        }
    } catch { }
    if ($gpus.Count -gt 0) { $os.GPU = ($gpus | Select-Object -Unique) -join ' + ' }

    try {
        $cs = Get-CimInstance Win32_ComputerSystem -ErrorAction Stop
        if ($cs.TotalPhysicalMemory) { $os.RAM = Format-Bytes $cs.TotalPhysicalMemory }
    } catch {
        $os.WmiOk = $false
        [void]$notes.Add('WMI/CIM 接口没有响应，内存、设备等部分信息可能读不到。')
    }

    try {
        $osInfo = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
        $os.LastBoot = $osInfo.LastBootUpTime
    } catch { }

    if (-not $os.LastBoot) {
        # WMI 不通时，用性能计数器算开机时长（比 TickCount64 在老系统上更可靠）
        try {
            $sec = (Get-Counter '\System\System Up Time' -ErrorAction Stop).CounterSamples[0].CookedValue
            if ($sec -gt 60) { $os.LastBoot = (Get-Date).AddSeconds(-1 * [double]$sec) }
        } catch { }
    }
    if (-not $os.LastBoot) {
        try {
            $ms = [Environment]::TickCount64
            if ($ms -gt 60000) { $os.LastBoot = (Get-Date).AddMilliseconds(-1 * [double]$ms) }
        } catch { }
    }
    if ($os.LastBoot) {
        $span = (Get-Date) - $os.LastBoot
        $os.Uptime = '{0}天 {1}小时 {2}分' -f [int]$span.TotalDays, $span.Hours, $span.Minutes
        if ($span.TotalDays -ge 7) {
            [void]$notes.Add(('已经连续开机 {0:N1} 天，建议重启一次让系统和驱动回到干净状态。' -f $span.TotalDays))
        }
    }

    $os.Notes = @($notes)
    return [pscustomobject]$os
}

function Get-DriveReport {
    $list = New-Object System.Collections.ArrayList
    try {
        foreach ($d in [System.IO.DriveInfo]::GetDrives()) {
            try {
                if (-not $d.IsReady) { continue }
                $total = $d.TotalSize
                $free  = $d.AvailableFreeSpace
                if ($total -le 0) { continue }
                $pct = [Math]::Round(100 * $free / $total, 1)
                [void]$list.Add([pscustomobject]@{
                    Letter = $d.Name.TrimEnd('\')
                    Label  = $d.VolumeLabel
                    Type   = "$($d.DriveType)"
                    Total  = $total
                    Free   = $free
                    FreePct = $pct
                })
            } catch { }
        }
    } catch { }
    return @($list)
}

function Get-JunkReport {
    param([int]$TimeoutSeconds = 15, [switch]$Quick)

    $la = $env:LOCALAPPDATA
    $targets = New-Object System.Collections.ArrayList
    $add = {
        param($Name, $Path, $Hint)
        [void]$targets.Add([pscustomobject]@{ Name = $Name; Path = $Path; Hint = $Hint })
    }

    & $add '用户临时文件' $env:TEMP '可以清'
    & $add 'Windows 临时文件' (Join-Path $env:windir 'Temp') '可以清'
    & $add 'Windows 更新缓存' (Join-Path $env:windir 'SoftwareDistribution\Download') '可以清'
    & $add '系统崩溃转储' (Join-Path $env:windir 'Minidump') '可以清'
    & $add '错误报告存档' (Join-Path $la 'Microsoft\Windows\WER\ReportArchive') '可以清'
    & $add '错误报告队列' (Join-Path $la 'Microsoft\Windows\WER\ReportQueue') '可以清'
    & $add '缩略图/图标缓存' (Join-Path $la 'Microsoft\Windows\Explorer') '可以清'
    & $add 'Edge 浏览器缓存' (Join-Path $la 'Microsoft\Edge\User Data\Default\Cache') '可以清'
    & $add 'Chrome 浏览器缓存' (Join-Path $la 'Google\Chrome\User Data\Default\Cache') '可以清'
    & $add '旧系统备份 Windows.old' (Join-Path $env:SystemDrive '\Windows.old') '可以清（确认不需要回退旧系统）'
    & $add '传递优化缓存' (Join-Path $env:windir 'SoftwareDistribution\DeliveryOptimization') '可以清'
    $downloads = Join-Path $env:USERPROFILE 'Downloads'
    & $add '下载文件夹' $downloads '请不要直接清空，用「整理文件」归类'

    $list = New-Object System.Collections.ArrayList
    $totalBytes = [long]0
    foreach ($t in $targets) {
        if ($Quick) {
            $exists = $false
            try { $exists = Test-Path -LiteralPath $t.Path } catch { }
            [void]$list.Add([pscustomobject]@{
                Name = $t.Name; Path = $t.Path; Exists = $exists; Files = 0; Bytes = [long]0
                Truncated = $false; Hint = $t.Hint; Measured = $false
            })
            continue
        }
        $st = Get-FolderStats -Path $t.Path -TimeoutSeconds $TimeoutSeconds
        if ($st.Exists) { $totalBytes = $totalBytes + $st.Bytes }
        [void]$list.Add([pscustomobject]@{
            Name = $t.Name; Path = $t.Path; Exists = $st.Exists; Files = $st.Files; Bytes = $st.Bytes
            Truncated = $st.Truncated; Hint = $t.Hint; Measured = $true
        })
    }

    $rb = Get-RecycleBinInfo
    [void]$list.Add([pscustomobject]@{
        Name = '回收站'; Path = 'Shell:RecycleBinFolder'; Exists = ($rb.Count -gt 0); Files = $rb.Count
        Bytes = $rb.Bytes; Truncated = $false; Hint = '可以清'; Measured = $rb.Ok
    })
    if ($rb.Ok) { $totalBytes = $totalBytes + $rb.Bytes }

    foreach ($f in @('hiberfil.sys', 'pagefile.sys', 'swapfile.sys')) {
        $p = Join-Path $env:SystemDrive $f
        $len = Get-FileSizeSafe $p
        if ($len -gt 0) {
            [void]$list.Add([pscustomobject]@{
                Name = "$f（系统文件，不要删除）"; Path = $p; Exists = $true; Files = 1; Bytes = $len
                Truncated = $false; Hint = '系统占用，用 powercfg/系统设置调整'; Measured = $true
            })
        }
    }

    return [pscustomobject]@{ Items = @($list); TotalBytes = $totalBytes }
}

function Get-StartupReport {
    $list = New-Object System.Collections.ArrayList
    $sources = @(
        @{ Path = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run';       Name = '当前用户启动项' }
        @{ Path = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce';   Name = '当前用户一次性启动项' }
        @{ Path = 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Run';       Name = '全局启动项' }
        @{ Path = 'HKLM:\Software\Microsoft\Windows\CurrentVersion\RunOnce';   Name = '全局一次性启动项' }
        @{ Path = 'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run'; Name = '全局启动项(32位)' }
    )
    foreach ($src in $sources) {
        try {
            if (-not (Test-Path $src.Path)) { continue }
            $props = Get-ItemProperty -Path $src.Path -ErrorAction Stop
            foreach ($p in $props.PSObject.Properties) {
                if ($p.Name -like 'PS*') { continue }
                $cmd = "$($p.Value)"
                $exe = Get-ExecutableFromCommand $cmd
                $exists = $null
                if ($exe) { $exists = (Test-Path -LiteralPath $exe) }
                [void]$list.Add([pscustomobject]@{
                    Name = $p.Name; Source = $src.Name; Command = $cmd; Exe = $exe; Exists = $exists
                })
            }
        } catch { }
    }

    foreach ($folder in @(
            (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup'),
            (Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs\Startup'))) {
        try {
            if (-not (Test-Path -LiteralPath $folder)) { continue }
            foreach ($f in (Get-ChildItem -LiteralPath $folder -File -Force -ErrorAction SilentlyContinue)) {
                if ($f.Name -eq 'desktop.ini') { continue }
                [void]$list.Add([pscustomobject]@{
                    Name = $f.Name; Source = '启动文件夹'; Command = $f.FullName; Exe = $f.FullName; Exists = $true
                })
            }
        } catch { }
    }

    try {
        foreach ($s in (Get-CimInstance Win32_StartupCommand -ErrorAction Stop)) {
            if ($s.Location -like 'Startup Folder*' -or $s.Location -like 'Registry*') {
                $exe = Get-ExecutableFromCommand $s.Command
                $exists = $null
                if ($exe) { $exists = (Test-Path -LiteralPath $exe) }
                [void]$list.Add([pscustomobject]@{
                    Name = $s.Name; Source = "系统启动项($($s.Location))"; Command = $s.Command; Exe = $exe; Exists = $exists
                })
            }
        }
    } catch { }

    # 去重：同名同命令只留一条
    $seen = @{}
    $dedup = New-Object System.Collections.ArrayList
    foreach ($item in $list) {
        $key = "$($item.Name)|$($item.Command)".ToLower()
        if ($seen.ContainsKey($key)) { continue }
        $seen[$key] = $true
        [void]$dedup.Add($item)
    }
    return @($dedup)
}

function Get-ExecutableFromCommand {
    param([string]$Command)
    if ([string]::IsNullOrWhiteSpace($Command)) { return $null }
    $c = $Command.Trim()
    if ($c.StartsWith('"')) {
        $end = $c.IndexOf('"', 1)
        if ($end -gt 1) { return $c.Substring(1, $end - 1) }
    }
    $m = [regex]::Match($c, '^(?<path>[A-Za-z]:\\[^"'']*?\.(exe|cmd|bat|com|ps1))(\s|$)')
    if ($m.Success) { return $m.Groups['path'].Value }
    $m2 = [regex]::Match($c, '^([^\s]+\.(exe|cmd|bat|com|ps1))', 'IgnoreCase')
    if ($m2.Success) { return $m2.Groups[1].Value }
    return $null
}

function Get-ServiceReport {
    $list = New-Object System.Collections.ArrayList
    try {
        foreach ($s in (Get-Service -ErrorAction Stop)) {
            $startType = $null
            try { $startType = "$($s.StartType)" } catch { $startType = $null }
            if (-not $startType -or $startType -eq '') {
                # 老系统上 Get-Service 可能没有 StartType，用注册表兜底（2=自动）
                $start = Get-RegValue ("HKLM:\SYSTEM\CurrentControlSet\Services\{0}" -f $s.Name) 'Start' $null
                if ($null -ne $start) {
                    if ($start -eq 2) { $startType = 'Automatic' } else { $startType = "Start=$start" }
                }
            }
            if ($startType -eq 'Automatic' -and "$($s.Status)" -ne 'Running') {
                [void]$list.Add([pscustomobject]@{
                    Name = $s.Name; DisplayName = $s.DisplayName; Status = "$($s.Status)"; StartType = $startType
                })
            }
        }
    } catch { }
    return @($list)
}

function Get-DeviceReport {
    $bad = New-Object System.Collections.ArrayList
    try {
        foreach ($d in (Get-PnpDevice -ErrorAction Stop)) {
            if ($d.Status -in @('Error', 'Unknown') -and $d.Present) {
                [void]$bad.Add([pscustomobject]@{ Name = $d.FriendlyName; Status = "$($d.Status)"; Class = $d.Class })
            }
        }
    } catch { }
    return @($bad)
}

function Get-PathEntryReport {
    <#  分析一条 PATH：空项 / 重复 / 带引号 / 路径不存在  #>
    param([string]$PathValue)
    $raw = @()
    if (-not [string]::IsNullOrWhiteSpace($PathValue)) { $raw = $PathValue.Split(';') }
    $empty = 0; $dup = @(); $missing = @(); $quoted = @(); $ok = 0; $benign = @()
    $seen = @{}
    foreach ($e in $raw) {
        $t = "$e"
        if ([string]::IsNullOrWhiteSpace($t)) { $empty++; continue }
        $trim = $t.Trim()
        if ($trim.StartsWith('"') -or $trim.EndsWith('"')) { $quoted += $trim }
        $key = $trim.Trim('"').TrimEnd('\').ToLower()
        if ($seen.ContainsKey($key)) { $dup += $trim; continue }
        $seen[$key] = $true
        $expanded = ''
        try { $expanded = [Environment]::ExpandEnvironmentVariables($trim.Trim('"')) } catch { $expanded = $trim.Trim('"') }
        try {
            if (Test-Path -LiteralPath $expanded) { $ok++ } else { $missing += $trim }
        } catch { $missing += $trim }
    }
    # 把"其实不算问题"的项目挑出来：应用商店目录、其他盘（可能没插）
    $realMissing = New-Object System.Collections.ArrayList
    foreach ($m in $missing) {
        $benignItem = $false
        if ($m -match 'WindowsApps') { $benignItem = $true }
        else {
            $rootDrive = ''
            try { $rootDrive = [System.IO.Path]::GetPathRoot([Environment]::ExpandEnvironmentVariables($m.Trim('"'))) } catch { }
            if ($rootDrive -and $rootDrive -notmatch ('^' + [regex]::Escape($env:SystemDrive))) { $benignItem = $true }
        }
        if ($benignItem) { $benign += $m } else { [void]$realMissing.Add($m) }
    }
    return [pscustomobject]@{
        RawCount = $raw.Count; Empty = $empty; Duplicates = @($dup)
        Missing = @($realMissing); MissingBenign = @($benign); Quoted = @($quoted); Ok = $ok
    }
}

function Get-EnvReport {
    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $userPath    = [Environment]::GetEnvironmentVariable('Path', 'User')
    $mReport = Get-PathEntryReport $machinePath
    $uReport = Get-PathEntryReport $userPath

    $tempIssues = New-Object System.Collections.ArrayList
    foreach ($scope in @('User', 'Machine')) {
        foreach ($var in @('TEMP', 'TMP')) {
            $v = [Environment]::GetEnvironmentVariable($var, $scope)
            if ([string]::IsNullOrWhiteSpace($v)) {
                [void]$tempIssues.Add("$scope 的 $var 没有设置")
                continue
            }
            try {
                if (-not (Test-Path -LiteralPath $v)) { [void]$tempIssues.Add("$scope 的 $var 指向不存在的目录：$v") }
            } catch { [void]$tempIssues.Add("$scope 的 $var 无法访问：$v") }
        }
    }

    # 常见工具：PATH 里找不到，但硬盘上装了
    $toolCandidates = @{
        'Python'  = @("$env:LOCALAPPDATA\Programs\Python", 'C:\Python*', "$env:ProgramFiles\Python*")
        'Node.js' = @("$env:ProgramFiles\nodejs", "$env:ProgramFiles\nodejs\node.exe")
        'Git'     = @("$env:ProgramFiles\Git\cmd", "$env:ProgramFiles\Git\cmd\git.exe", "${env:ProgramFiles(x86)}\Git\cmd")
        'Java'    = @("$env:ProgramFiles\Java", "$env:ProgramFiles\Eclipse Adoptium", "$env:ProgramFiles\Microsoft\jdk*")
        'dotnet'  = @("$env:ProgramFiles\dotnet\dotnet.exe")
        'VS Code' = @("$env:LOCALAPPDATA\Programs\Microsoft VS Code\Code.exe", "$env:ProgramFiles\Microsoft VS Code\Code.exe")
        '7-Zip'   = @("$env:ProgramFiles\7-Zip\7z.exe", "${env:ProgramFiles(x86)}\7-Zip\7z.exe")
        'FFmpeg'  = @("$env:ProgramFiles\ffmpeg\bin", 'C:\ffmpeg\bin')
        'Arduino' = @("$env:LOCALAPPDATA\Programs\Arduino IDE", "$env:ProgramFiles\Arduino IDE")
        'KiCad'   = @("$env:ProgramFiles\KiCad", 'C:\Program Files\KiCad')
    }
    $tools = New-Object System.Collections.ArrayList
    foreach ($name in ($toolCandidates.Keys | Sort-Object)) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        $inPath = $null -ne $cmd
        $paths = @()
        foreach ($pat in $toolCandidates[$name]) {
            try {
                $hits = Get-Item -Path $pat -ErrorAction SilentlyContinue
                foreach ($h in $hits) { $paths += $h.FullName }
            } catch { }
        }
        [void]$tools.Add([pscustomobject]@{
            Name = $name; InPath = $inPath; FoundOnDisk = ($paths.Count -gt 0); Paths = @($paths)
        })
    }

    $critical = New-Object System.Collections.ArrayList
    foreach ($pair in @(
            @{ Name = 'windir'; Scope = 'Machine' },
            @{ Name = 'ComSpec'; Scope = 'Machine' }, @{ Name = 'PATHEXT'; Scope = 'Machine' })) {
        $v = [Environment]::GetEnvironmentVariable($pair.Name, $pair.Scope)
        if ([string]::IsNullOrWhiteSpace($v)) { [void]$critical.Add("系统变量 $($pair.Name) 缺失") }
    }
    # SystemRoot 是系统启动时临时生成的变量，只能从当前进程读，不能去注册表找
    if ([string]::IsNullOrWhiteSpace($env:SystemRoot)) {
        [void]$critical.Add('环境变量 SystemRoot 缺失（正常应该指向 C:\Windows）')
    } elseif (-not (Test-Path -LiteralPath $env:SystemRoot)) {
        [void]$critical.Add("SystemRoot 指向的目录不存在：$env:SystemRoot")
    }
    $sys32 = Join-Path $env:windir 'System32'
    $machineEntries = @()
    if ($machinePath) { $machineEntries = $machinePath.Split(';') | ForEach-Object { $_.Trim().Trim('"').TrimEnd('\').ToLower() } }
    if ($machineEntries -notcontains $sys32.ToLower()) { [void]$critical.Add('系统 PATH 里缺少 C:\Windows\System32（很多软件会因此报错）') }

    return [pscustomobject]@{
        MachinePath = $mReport
        UserPath    = $uReport
        TempIssues  = @($tempIssues)
        Tools       = @($tools)
        CriticalMissing = @($critical)
        MachinePathRaw = $machinePath
        UserPathRaw    = $userPath
    }
}

function Get-RuntimeReport {
    $vc = New-Object System.Collections.ArrayList
    $vcNames = New-Object System.Collections.ArrayList
    try {
        $keys = @(
            'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
            'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
        )
        foreach ($k in $keys) {
            try {
                foreach ($item in (Get-ItemProperty $k -ErrorAction SilentlyContinue)) {
                    $n = "$($item.DisplayName)"
                    if ($n -match 'Microsoft Visual C\+\+\s*(?<year>20\d\d)\s*Redistributable') {
                        $year = $Matches['year']
                        $arch = 'x64'
                        if ($k -like '*WOW6432Node*') { $arch = 'x86' }
                        $tag = "VC++ $year ($arch)"
                        if (-not $vcNames.Contains($tag)) { [void]$vcNames.Add($tag) }
                    }
                }
            } catch { }
        }
    } catch { }
    foreach ($t in ($vcNames | Sort-Object)) { [void]$vc.Add($t) }

    $missing = New-Object System.Collections.ArrayList
    if (-not ($vcNames | Where-Object { $_ -eq 'VC++ 2015-2022 (x64)' -or $_ -match 'VC\+\+ 20(1[5-9]|2[0-9]) \(x64\)' })) {
        [void]$missing.Add('未检测到 VC++ 2015-2022 x64 运行库')
    }
    if (-not ($vcNames | Where-Object { $_ -match '\(x86\)' })) {
        [void]$missing.Add('未检测到 32 位 VC++ 运行库（x86）')
    }

    $netFx = '未知'
    $rel = Get-RegValue 'HKLM:\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full' 'Release'
    if ($rel) {
        $relInt = 0
        [void][int]::TryParse("$rel", [ref]$relInt)
        $map = @(
            @{ Min = 533320; Ver = '4.8.1+' }, @{ Min = 528040; Ver = '4.8' }, @{ Min = 461808; Ver = '4.7.2' },
            @{ Min = 461308; Ver = '4.7.1' }, @{ Min = 460798; Ver = '4.7' },   @{ Min = 394802; Ver = '4.6.2' },
            @{ Min = 394254; Ver = '4.6.1' }, @{ Min = 393295; Ver = '4.6' },   @{ Min = 379893; Ver = '4.5.2' },
            @{ Min = 378675; Ver = '4.5.1' }, @{ Min = 378389; Ver = '4.5' }
        )
        foreach ($m in $map) {
            if ($relInt -ge $m.Min) { $netFx = "$($m.Ver) (Release $relInt)"; break }
        }
    }

    $dotnetRuntimes = @()
    try {
        $dotnet = Get-Command dotnet -ErrorAction SilentlyContinue
        if ($dotnet) {
            $out = & $dotnet.Source --list-runtimes 2>&1
            $dotnetRuntimes = @($out | Where-Object { "$_" -match '^Microsoft\.' })
        }
    } catch { }

    $directx = Get-RegValue 'HKLM:\SOFTWARE\Microsoft\DirectX' 'Version' '未知'

    $defender = '未查询'
    try {
        $mp = Get-MpComputerStatus -ErrorAction Stop
        $defender = "实时保护=$($mp.RealTimeProtectionEnabled) 病毒库=$($mp.AntivirusSignatureLastUpdated)"
        if (-not $mp.RealTimeProtectionEnabled) { $defender = "$defender（实时保护是关闭的，注意风险）" }
    } catch { }

    return [pscustomobject]@{
        VCpp = @($vc); VCppMissing = @($missing); NetFx = $netFx
        DotNetRuntimes = @($dotnetRuntimes); DirectX = $directx; Defender = $defender
    }
}

function Get-ShortcutReport {
    $broken = New-Object System.Collections.ArrayList
    $total = 0
    $shell = $null
    try { $shell = New-Object -ComObject WScript.Shell } catch {
        return [pscustomobject]@{ Broken = @(); Total = 0; Skipped = $true }
    }

    $folders = New-Object System.Collections.ArrayList
    [void]$folders.Add($env:USERPROFILE + '\Desktop')
    [void]$folders.Add($env:PUBLIC + '\Desktop')
    [void]$folders.Add($env:APPDATA + '\Microsoft\Windows\Start Menu\Programs')
    [void]$folders.Add($env:ProgramData + '\Microsoft\Windows\Start Menu\Programs')

    foreach ($folder in $folders) {
        try {
            if (-not (Test-Path -LiteralPath $folder)) { continue }
            foreach ($lnk in (Get-ChildItem -LiteralPath $folder -Recurse -Filter *.lnk -File -Force -ErrorAction SilentlyContinue)) {
                $total++
                try {
                    $sc = $shell.CreateShortcut($lnk.FullName)
                    $target = $sc.TargetPath
                    if ([string]::IsNullOrWhiteSpace($target)) { continue }
                    if ($target -match '^(ms-|shell:)' -or $target.StartsWith('::')) { continue }
                    if ($target.StartsWith('\\')) { continue }   # 网络位置/共享盘，连不上很正常，不算断链
                    if (-not (Test-Path -LiteralPath $target)) {
                        [void]$broken.Add([pscustomobject]@{
                            Path = $lnk.FullName; Target = $target; Name = $lnk.BaseName
                            Reason = '目标文件不存在（软件可能已被卸载或移动）'
                        })
                    }
                } catch { }
            }
        } catch { }
    }
    return [pscustomobject]@{ Broken = @($broken); Total = $total; Skipped = $false }
}

function Get-EventReport {
    param([int]$Days = 7, [int]$MaxEvents = 120)
    $list = New-Object System.Collections.ArrayList
    try {
        $since = (Get-Date).AddDays(-1 * $Days)
        $evts = Get-WinEvent -FilterHashtable @{ LogName = @('System', 'Application'); Level = @(1, 2); StartTime = $since } -MaxEvents $MaxEvents -ErrorAction Stop
        foreach ($e in $evts) {
            $msg = ''
            try { $msg = ($e.Message -split "`r?`n")[0] } catch { }
            if ($msg.Length -gt 200) { $msg = $msg.Substring(0, 200) + '...' }
            [void]$list.Add([pscustomobject]@{
                Time = $e.TimeCreated; Level = "$($e.LevelDisplayName)"; Provider = $e.ProviderName
                Id = $e.Id; Log = $e.LogName; Message = $msg
            })
        }
    } catch { }
    return @($list)
}

function Get-UpdateReport {
    $last = '-'
    try {
        $hf = Get-HotFix -ErrorAction Stop | Sort-Object InstalledOn -Descending | Select-Object -First 1
        if ($hf) { $last = "$($hf.HotFixID) $($hf.Description) ($($hf.InstalledOn))" }
    } catch { }
    $svc = @()
    foreach ($n in @('wuauserv', 'BITS', 'CryptSvc', 'msiserver')) {
        try {
            $s = Get-Service -Name $n -ErrorAction Stop
            $svc += [pscustomobject]@{ Name = $n; Status = "$($s.Status)"; StartType = "$($s.StartType)" }
        } catch { }
    }
    $pr = Test-PendingReboot
    return [pscustomobject]@{ LastHotfix = $last; Services = @($svc); PendingReboot = $pr.Pending; PendingReasons = $pr.Reasons }
}

function Get-DiskHealthReport {
    $list = New-Object System.Collections.ArrayList
    try {
        foreach ($d in (Get-PhysicalDisk -ErrorAction Stop)) {
            [void]$list.Add([pscustomobject]@{
                Name = $d.FriendlyName; Media = "$($d.MediaType)"; Health = "$($d.HealthStatus)"
                Status = "$($d.OperationalStatus)"; Size = Format-Bytes $d.Size
            })
        }
    } catch { }
    $dirty = New-Object System.Collections.ArrayList
    if (Test-IsAdmin) {
        try {
            foreach ($d in [System.IO.DriveInfo]::GetDrives()) {
                try {
                    if (-not $d.IsReady -or $d.DriveType -ne 'Fixed') { continue }
                    $letter = $d.Name.Substring(0, 2)
                    $out = & fsutil.exe dirty query $letter 2>&1
                    if ("$out" -match '是脏的|is dirty') { [void]$dirty.Add("$letter 标记为需要检查（建议运行磁盘检查）") }
                } catch { }
            }
        } catch { }
    }
    return [pscustomobject]@{ Disks = @($list); Dirty = @($dirty) }
}

# ---------------------------------------------------------------- 综合体检

function Invoke-Diagnostics {
    param([switch]$Quick)

    Write-Title "电脑体检（只读，不会改动任何东西）"
    $sw = [System.Diagnostics.Stopwatch]::StartNew()

    Write-Step '读取系统概况...'
    $system = Get-SystemOverview
    Write-Info "$($system.Caption) $($system.DisplayVersion) (Build $($system.Build)) $($system.Arch)"
    Write-Info "CPU: $($system.CPU)"
    Write-Info "内存: $($system.RAM)    显卡: $($system.GPU)"
    Write-Info "开机时长: $($system.Uptime)"
    Write-Log ("系统概况: {0}" -f ($system | ConvertTo-Json -Compress))

    Write-Step '检查磁盘剩余空间...'
    $drives = Get-DriveReport
    foreach ($d in $drives) {
        $color = 'Gray'
        if ($d.FreePct -lt 10) { $color = 'Red' } elseif ($d.FreePct -lt 20) { $color = 'Yellow' }
        $txt = ('{0} {1} 剩余 {2} / 共 {3}（{4}%）' -f $d.Letter, $d.Label, (Format-Bytes $d.Free), (Format-Bytes $d.Total), $d.FreePct)
        Write-Host "  $txt" -ForegroundColor $color
        Write-Log $txt
    }

    if ($Quick) {
        Write-Skip '快速模式：跳过垃圾体积统计（只记录目录是否存在）'
    } else {
        Write-Step '统计垃圾文件体积（临时文件/缓存/回收站，可能要一两分钟）...'
    }
    $junk = Get-JunkReport -Quick:$Quick
    if (-not $Quick) {
        foreach ($j in ($junk.Items | Where-Object { $_.Exists -and $_.Bytes -gt 0 } | Sort-Object Bytes -Descending)) {
            $txt = ('{0}：{1}（{2} 个文件）{3}' -f $j.Name, (Format-Bytes $j.Bytes), $j.Files, $(if ($j.Truncated) { ' [统计超时，实际更大]' } else { '' }))
            Write-Info $txt
        }
        Write-Info ('合计约 ' + (Format-Bytes $junk.TotalBytes))
    }

    Write-Step '检查启动项...'
    $startup = Get-StartupReport
    $deadStartup = @($startup | Where-Object { $_.Exists -eq $false })
    Write-Info ("共 {0} 个启动项，其中 {1} 个指向的文件已经不存在" -f $startup.Count, $deadStartup.Count)
    foreach ($s in $deadStartup) { Write-Warn "失效启动项：$($s.Name) → $($s.Command)" }

    Write-Step '检查后台服务...'
    $services = Get-ServiceReport
    Write-Info ("开机自启但当前没运行的服务：{0} 个" -f $services.Count)
    foreach ($s in ($services | Select-Object -First 8)) { Write-Info "  $($s.Name) - $($s.DisplayName)" }

    Write-Step '检查有问题的硬件设备...'
    $devices = Get-DeviceReport
    if ($devices.Count -eq 0) { Write-Ok '没有发现报错的设备' }
    foreach ($d in $devices) { Write-Warn "设备异常：$($d.Name) [$($d.Class)] 状态=$($d.Status)" }

    Write-Step '检查环境变量（PATH / TEMP 等）...'
    $envReport = Get-EnvReport
    Write-Info ("系统 PATH：{0} 项，其中无效 {1} 项、重复 {2} 项、空项 {3} 个" -f `
        $envReport.MachinePath.RawCount, $envReport.MachinePath.Missing.Count, $envReport.MachinePath.Duplicates.Count, $envReport.MachinePath.Empty)
    Write-Info ("用户 PATH：{0} 项，其中无效 {1} 项、重复 {2} 项、空项 {3} 个" -f `
        $envReport.UserPath.RawCount, $envReport.UserPath.Missing.Count, $envReport.UserPath.Duplicates.Count, $envReport.UserPath.Empty)
    foreach ($m in $envReport.MachinePath.Missing) { Write-Warn "系统 PATH 里这个目录不存在：$m" }
    foreach ($m in $envReport.UserPath.Missing) { Write-Warn "用户 PATH 里这个目录不存在：$m" }
    foreach ($m in (@($envReport.MachinePath.MissingBenign) + @($envReport.UserPath.MissingBenign))) {
        Write-Info "这个 PATH 项现在读不到（商店目录或外接盘），先不动它：$m"
    }
    foreach ($t in $envReport.TempIssues) { Write-Warn $t }
    foreach ($c in $envReport.CriticalMissing) { Write-Err $c }

    Write-Step '检查运行库（VC++ / .NET / DirectX）...'
    $runtime = Get-RuntimeReport
    Write-Info ("VC++ 运行库：{0}" -f (($runtime.VCpp -join ', ') -replace '^$', '一个都没检测到'))
    foreach ($m in $runtime.VCppMissing) { Write-Warn $m }
    Write-Info ".NET Framework：$($runtime.NetFx)"
    if ($runtime.DotNetRuntimes.Count -gt 0) { Write-Info (".NET 运行时：" + (($runtime.DotNetRuntimes | Select-Object -First 6) -join ' | ')) }
    Write-Info "DirectX：$($runtime.DirectX)"
    Write-Info "Windows Defender：$($runtime.Defender)"

    Write-Step '检查桌面/开始菜单的快捷方式（找断链）...'
    $shortcuts = Get-ShortcutReport
    Write-Info ("共检查 {0} 个快捷方式，断链 {1} 个" -f $shortcuts.Total, $shortcuts.Broken.Count)
    foreach ($b in ($shortcuts.Broken | Select-Object -First 10)) { Write-Warn "$($b.Name) → $($b.Target)" }

    Write-Step '读取最近的错误日志（7 天）...'
    $events = Get-EventReport
    Write-Info ("最近 7 天严重/错误事件：{0} 条" -f $events.Count)
    foreach ($g in ($events | Group-Object Provider, Id | Sort-Object Count -Descending | Select-Object -First 5)) {
        Write-Info ("  {0} 次 - {1}" -f $g.Count, $g.Name)
    }
    $dllErrors = @($events | Where-Object { $_.Message -match '\.dll' })
    foreach ($e in ($dllErrors | Select-Object -First 5)) {
        Write-Warn "疑似缺少/损坏的 dll：$($e.Provider) #$($e.Id) - $($e.Message)"
    }

    Write-Step '检查 Windows 更新状态...'
    $update = Get-UpdateReport
    Write-Info "最近一次更新：$($update.LastHotfix)"
    foreach ($s in $update.Services) { Write-Info "服务 $($s.Name)：$($s.Status) / $($s.StartType)" }
    if ($update.PendingReboot) { Write-Warn ('有待重启的更新：' + ($update.PendingReasons -join '；')) }
    else { Write-Ok '没有待重启的更新' }

    Write-Step '检查磁盘健康...'
    $health = Get-DiskHealthReport
    foreach ($d in $health.Disks) {
        $msg = "磁盘 $($d.Name)（$($d.Media)，$($d.Size)）：$($d.Health) / $($d.Status)"
        if ($d.Health -eq 'Healthy') { Write-Ok $msg } else { Write-Warn $msg }
    }
    foreach ($w in $health.Dirty) { Write-Warn $w }
    if ($health.Disks.Count -eq 0) { Write-Skip '读不到物理磁盘信息（可能是权限或 WMI 问题）' }

    # ---- 打分 ----
    $score = 100
    $advice = New-Object System.Collections.ArrayList
    $missingPath = $envReport.MachinePath.Missing.Count + $envReport.UserPath.Missing.Count
    if ($missingPath -gt 0) {
        $score -= [Math]::Min(10, $missingPath * 2)
        [void]$advice.Add("环境变量 PATH 里有 $missingPath 条无效路径，建议用「修复 → 环境变量修复」清理（会自动备份）。")
    }
    $dupEmpty = $envReport.MachinePath.Duplicates.Count + $envReport.UserPath.Duplicates.Count + $envReport.MachinePath.Empty + $envReport.UserPath.Empty
    if ($dupEmpty -gt 0) { $score -= [Math]::Min(5, $dupEmpty); [void]$advice.Add("PATH 里有 $dupEmpty 条重复或空项，会让系统找程序变慢。") }
    if ($envReport.TempIssues.Count -gt 0) { $score -= 5; [void]$advice.Add('TEMP/TMP 变量异常，某些软件安装和编译会失败。') }
    if ($envReport.CriticalMissing.Count -gt 0) { $score -= 10; [void]$advice.Add('系统关键环境变量异常，优先修复。') }
    if ($junk.TotalBytes -gt 5GB) {
        $pen = 5; if ($junk.TotalBytes -gt 20GB) { $pen = 10 }
        $score -= $pen
        [void]$advice.Add(('垃圾文件约 ' + (Format-Bytes $junk.TotalBytes) + '，可以用「清理垃圾」释放。'))
    }
    $sysDrive = $drives | Where-Object { $_.Letter -eq $env:SystemDrive }
    if ($sysDrive) {
        if ($sysDrive.FreePct -lt 8) { $score -= 20; [void]$advice.Add('系统盘剩余空间不到 8%，会明显影响性能和更新，尽快清理。') }
        elseif ($sysDrive.FreePct -lt 15) { $score -= 10; [void]$advice.Add('系统盘剩余空间低于 15%，建议清理。') }
    }
    if ($deadStartup.Count -gt 0) { $score -= [Math]::Min(5, $deadStartup.Count); [void]$advice.Add("有 $($deadStartup.Count) 个失效启动项，建议清理（每次开机系统都要试一遍）。") }
    if ($startup.Count -gt 12) { $score -= 3; [void]$advice.Add("启动项有 $($startup.Count) 个，偏多，开机会变慢。") }
    if ($shortcuts.Broken.Count -gt 0) { $score -= [Math]::Min(5, $shortcuts.Broken.Count); [void]$advice.Add("有 $($shortcuts.Broken.Count) 个快捷方式指向的软件已经不存在。") }
    if ($devices.Count -gt 0) { $score -= [Math]::Min(9, $devices.Count * 3); [void]$advice.Add('有硬件设备报错，通常需要重装对应驱动。') }
    if ($services.Count -gt 0) { $score -= [Math]::Min(6, $services.Count * 2); [void]$advice.Add("有 $($services.Count) 个自动服务没在运行，如果不是你自己关的，可以试着修复系统组件。") }
    if ($runtime.VCppMissing.Count -gt 0) { $score -= 5; [void]$advice.Add('运行库不全（VC++ 2015-2022），新装的游戏/软件容易报缺少 dll。') }
    if ($update.PendingReboot) { $score -= 3; [void]$advice.Add('有待重启的更新，重启后再做修复效果更好。') }
    if ($events.Count -gt 30) { $score -= 5; [void]$advice.Add('最近错误日志偏多，建议先修复系统文件再看。') }
    if ($system.WmiOk -eq $false) { $score -= 5; [void]$advice.Add('WMI 服务没有正常响应，很多系统工具会读不到信息，建议修复 WMI/系统文件。') }
    if ($score -lt 0) { $score = 0 }
    if ($score -gt 100) { $score = 100 }

    $grade = 'A'
    if ($score -lt 90) { $grade = 'B' }
    if ($score -lt 75) { $grade = 'C' }
    if ($score -lt 60) { $grade = 'D' }

    $sw.Stop()
    Write-Section "体检结果"
    $color = 'Green'
    if ($score -lt 90) { $color = 'Yellow' }
    if ($score -lt 75) { $color = 'Red' }
    Write-Host ("  健康分：$score / 100   等级：$grade") -ForegroundColor $color
    Write-Log "健康分: $score ($grade)"
    if ($advice.Count -eq 0) { Write-Ok '没有发现需要处理的问题，电脑状态不错。' }
    else {
        Write-Host '  建议按顺序处理：' -ForegroundColor Cyan
        $i = 1
        foreach ($a in $advice) { Write-Host "   $i) $a" -ForegroundColor Gray; $i++ }
    }
    Write-Info ("体检用时 {0:N1} 秒" -f $sw.Elapsed.TotalSeconds)

    return [pscustomobject]@{
        GeneratedAt = (Get-Date)
        IsAdmin = (Test-IsAdmin)
        Score = $score
        Grade = $grade
        Advice = @($advice)
        System = $system
        Drives = @($drives)
        Junk = $junk
        Startup = @($startup)
        DeadStartup = @($deadStartup)
        Services = @($services)
        Devices = @($devices)
        Env = $envReport
        Runtime = $runtime
        Shortcuts = $shortcuts
        Events = @($events)
        Update = $update
        Health = $health
        DurationSeconds = $sw.Elapsed.TotalSeconds
    }
}
