<#
    电脑管家 PcToolkit - 整理模块
    功能：按类型/日期归类文件（可撤销）、找重复文件、找大文件和老文件
    安全原则：默认只出"整理方案"，你确认后才真的移动；每一次移动都记进日志，可以一键撤销。
#>

function Get-OrganizeCategoryMap {
    # 顺序有意义：前面的先匹配
    return [ordered]@{
        '模型与打印'   = @('.stl', '.obj', '.3mf', '.step', '.stp', '.iges', '.igs', '.dwg', '.dxf', '.scad',
                            '.gcode', '.f3d', '.blend', '.fcstd', '.sldprt', '.sldasm', '.amf', '.ply', '.fbx',
                            '.gltf', '.glb', '.123dx', '.ipt', '.iam')
        '图片'         = @('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.heic', '.tif', '.tiff', '.svg',
                            '.psd', '.ai', '.cdr', '.raw', '.cr2', '.nef', '.arw', '.dng')
        '视频'         = @('.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.rmvb', '.ts', '.mpg', '.mpeg')
        '音频'         = @('.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a', '.wma', '.ape', '.mid', '.midi')
        '演示'         = @('.ppt', '.pptx', '.odp', '.dps', '.key')
        '表格'         = @('.xls', '.xlsx', '.csv', '.ods', '.et', '.tsv')
        '文档'         = @('.pdf', '.doc', '.docx', '.txt', '.md', '.rtf', '.odt', '.wps', '.pages',
                            '.epub', '.mobi', '.azw3', '.djvu', '.tex')
        '压缩包'       = @('.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.xz', '.iso', '.cab', '.tgz')
        '程序与安装包' = @('.exe', '.msi', '.msix', '.appx', '.appxbundle', '.apk', '.bat', '.cmd', '.reg')
        '代码'         = @('.py', '.js', '.ts', '.java', '.c', '.cpp', '.h', '.hpp', '.cs', '.go', '.rs', '.php',
                            '.html', '.htm', '.css', '.json', '.xml', '.yml', '.yaml', '.sh', '.ps1', '.ino',
                            '.lua', '.sql', '.ipynb', '.vb', '.asm', '.v', '.m')
        '字体'         = @('.ttf', '.otf', '.woff', '.woff2', '.fon', '.ttc')
    }
}

function Get-CategoryForFile {
    param([Parameter(Mandatory)][string]$Ext)
    $map = Get-OrganizeCategoryMap
    $e = $Ext.ToLower()
    foreach ($cat in $map.Keys) {
        if ($map[$cat] -contains $e) { return $cat }
    }
    return '其他'
}

function Get-DefaultOrganizeTargets {
    $list = New-Object System.Collections.ArrayList
    [void]$list.Add((Join-Path $env:USERPROFILE 'Downloads'))
    [void]$list.Add((Join-Path $env:USERPROFILE 'Desktop'))
    [void]$list.Add((Join-Path $env:USERPROFILE 'Documents'))
    return @($list | Where-Object { Test-Path -LiteralPath $_ })
}

function Get-UniqueDestination {
    param([Parameter(Mandatory)][string]$DestPath)
    if (-not (Test-Path -LiteralPath $DestPath)) { return $DestPath }
    $dir = Split-Path -Parent $DestPath
    $base = [System.IO.Path]::GetFileNameWithoutExtension($DestPath)
    $ext = [System.IO.Path]::GetExtension($DestPath)
    for ($i = 2; $i -lt 1000; $i++) {
        $candidate = Join-Path $dir ("{0} ({1}){2}" -f $base, $i, $ext)
        if (-not (Test-Path -LiteralPath $candidate)) { return $candidate }
    }
    return (Join-Path $dir ("{0}_{1}{2}" -f $base, (Get-Date -Format 'HHmmss'), $ext))
}

function Get-OrganizePlan {
    param(
        [Parameter(Mandatory)][string[]]$Targets,
        [ValidateSet('Category', 'Date', 'Archive')][string]$Layout = 'Category',
        [int]$MinAgeDays = 0,
        [switch]$IncludeHidden,
        [switch]$Recurse,
        [int]$MaxFiles = 8000
    )
    $items = New-Object System.Collections.ArrayList
    $skipped = New-Object System.Collections.ArrayList
    $cutoff = (Get-Date).AddDays(-1 * $MinAgeDays)
    $toolRoot = $script:ToolRoot

    foreach ($root in $Targets) {
        if ([string]::IsNullOrWhiteSpace($root)) { continue }
        $resolved = $null
        try { $resolved = (Resolve-Path -LiteralPath $root -ErrorAction Stop).ProviderPath } catch { }
        if (-not $resolved) {
            [void]$skipped.Add([pscustomobject]@{ Path = $root; Reason = '目录不存在或无法访问' })
            continue
        }
        # 不要把工具自己的目录整理掉
        if ($resolved.StartsWith($toolRoot, [StringComparison]::OrdinalIgnoreCase)) { continue }

        $files = @()
        try {
            if ($Recurse) {
                $files = @(Get-ChildItem -LiteralPath $resolved -Recurse -File -Force:$IncludeHidden -ErrorAction SilentlyContinue)
            } else {
                $files = @(Get-ChildItem -LiteralPath $resolved -File -Force:$IncludeHidden -ErrorAction SilentlyContinue)
            }
        } catch { }

        foreach ($f in $files) {
            if ($items.Count -ge $MaxFiles) {
                [void]$skipped.Add([pscustomobject]@{ Path = $resolved; Reason = "文件太多，超过一次性处理上限 $MaxFiles，剩余未列入方案" })
                break
            }
            if ($f.FullName.StartsWith($toolRoot, [StringComparison]::OrdinalIgnoreCase)) { continue }
            if ($f.Name -in @('desktop.ini', 'thumbs.db', '.DS_Store')) { continue }
            if ($f.Extension -in @('.lnk', '.url', '.tmp', '.part', '.crdownload', '.download')) {
                [void]$skipped.Add([pscustomobject]@{ Path = $f.FullName; Reason = '快捷方式或未下载完的文件，保持原位' })
                continue
            }
            if ($f.Attributes -band [System.IO.FileAttributes]::System) {
                [void]$skipped.Add([pscustomobject]@{ Path = $f.FullName; Reason = '系统文件，保持原位' })
                continue
            }
            if ($f.Attributes -band [System.IO.FileAttributes]::Hidden -and -not $IncludeHidden) {
                continue
            }
            if ($MinAgeDays -gt 0 -and $f.LastWriteTime -gt $cutoff) {
                [void]$skipped.Add([pscustomobject]@{ Path = $f.FullName; Reason = "最近 $MinAgeDays 天内改过，太新，先不动" })
                continue
            }
            if (Test-FileLocked -Path $f.FullName) {
                [void]$skipped.Add([pscustomobject]@{ Path = $f.FullName; Reason = '文件正在被程序使用，先不动' })
                continue
            }

            $category = Get-CategoryForFile $f.Extension
            $destDir = $resolved
            switch ($Layout) {
                'Category' { $destDir = Join-Path $resolved $category }
                'Date'     { $destDir = Join-Path $resolved (Join-Path $f.LastWriteTime.ToString('yyyy年MM月') $category) }
                'Archive'  { $destDir = Join-Path $resolved ('_归档_' + $f.LastWriteTime.ToString('yyyy')) }
            }
            $destPath = Join-Path $destDir $f.Name
            if ($destPath -eq $f.FullName) { continue }

            [void]$items.Add([pscustomobject]@{
                Source   = $f.FullName
                Name     = $f.Name
                Ext      = $f.Extension
                Size     = $f.Length
                Modified = $f.LastWriteTime
                Category = $category
                DestDir  = $destDir
                DestPath = $destPath
                Root     = $resolved
                Layout   = $Layout
            })
        }
    }
    return [pscustomobject]@{ Items = @($items); Skipped = @($skipped); Targets = @($Targets); Layout = $Layout }
}

function Show-OrganizePlan {
    param([Parameter(Mandatory)]$Plan, [int]$SampleCount = 12)
    if ($Plan.Items.Count -eq 0) {
        Write-Warn '没有需要整理的文件（可能都很整齐，或者都被跳过了）。'
        return
    }
    $totalSize = ($Plan.Items | Measure-Object -Property Size -Sum).Sum
    Write-Host ''
    Write-Info ("共 {0} 个文件，合计 {1}，准备这样归类：" -f $Plan.Items.Count, (Format-Bytes $totalSize))
    Write-Host ''
    Write-Host ('    {0,-14} {1,8}  {2,10}  {3}' -f '分类', '文件数', '体积', '将移动到') -ForegroundColor DarkGray
    Write-Host ('    ' + ('-' * 66)) -ForegroundColor DarkGray
    foreach ($g in ($Plan.Items | Group-Object Category | Sort-Object Count -Descending)) {
        $size = ($g.Group | Measure-Object -Property Size -Sum).Sum
        $dest = (($g.Group | Select-Object -First 1).DestDir).Replace($Plan.Items[0].Root, '…')
        Write-Host ('    {0,-14} {1,8}  {2,10}  {3}' -f $g.Name, $g.Count, (Format-Bytes $size), $dest) -ForegroundColor Gray
    }
    Write-Host ''
    Write-Host '    举个例子：' -ForegroundColor DarkGray
    foreach ($i in ($Plan.Items | Select-Object -First $SampleCount)) {
        $short = $i.Source
        if ($short.Length -gt 58) { $short = '…' + $short.Substring($short.Length - 57) }
        Write-Host ('      {0}  ->  {1}' -f $short, $i.Category) -ForegroundColor DarkGray
    }
    if ($Plan.Skipped.Count -gt 0) {
        Write-Host ''
        Write-Info ("有 {0} 项被跳过：" -f $Plan.Skipped.Count)
        foreach ($s in ($Plan.Skipped | Group-Object Reason | Sort-Object Count -Descending | Select-Object -First 5)) {
            Write-Info ("  {0} 项 - {1}" -f $s.Count, $s.Name)
        }
    }
}

function Invoke-OrganizeFiles {
    param(
        [string[]]$Targets,
        [ValidateSet('Category', 'Date', 'Archive')][string]$Layout = 'Category',
        [int]$MinAgeDays = 0,
        [switch]$IncludeHidden,
        [switch]$Recurse,
        [switch]$Apply
    )
    Write-Section '整理文件（按类型归类）'
    if (-not $Targets -or $Targets.Count -eq 0) { $Targets = Get-DefaultOrganizeTargets }
    if ($Targets.Count -eq 0) { Write-Err '没有找到可整理的位置。'; return $null }

    Write-Info ('整理范围：' + ($Targets -join '、'))
    $layoutText = '按文件类型分文件夹'
    if ($Layout -eq 'Date') { $layoutText = '按年月 + 类型分文件夹' }
    if ($Layout -eq 'Archive') { $layoutText = '全部移到按年份的"归档"文件夹' }
    Write-Info "整理方式：$layoutText"
    Write-Step '正在扫描并生成方案（不会改动文件）...'
    $plan = Get-OrganizePlan -Targets $Targets -Layout $Layout -MinAgeDays $MinAgeDays -IncludeHidden:$IncludeHidden -Recurse:$Recurse
    Show-OrganizePlan -Plan $plan

    if ($plan.Items.Count -eq 0) { return $null }
    if (-not $Apply) {
        Write-Host ''
        Write-Warn '以上只是方案，没有移动任何文件。'
        Write-Info '确认没问题后，选"执行整理"才会真的移动（会记录日志，可以撤销）。'
        return $plan
    }
    if (-not (Confirm-Action ("确认移动这 {0} 个文件吗？" -f $plan.Items.Count) $true)) {
        Write-Skip '已取消，文件没动。'
        return $null
    }

    $moves = New-Object System.Collections.ArrayList
    $failed = New-Object System.Collections.ArrayList
    $movedBytes = [long]0
    $i = 0
    foreach ($item in $plan.Items) {
        $i++
        if ($i % 25 -eq 0) { Write-Host -NoNewline "." -ForegroundColor DarkGray }
        try {
            if (-not (Test-Path -LiteralPath $item.DestDir)) { New-Item -ItemType Directory -Path $item.DestDir -Force | Out-Null }
            $finalDest = $item.DestPath
            if (Test-Path -LiteralPath $finalDest) { $finalDest = Get-UniqueDestination $finalDest }
            Move-Item -LiteralPath $item.Source -Destination $finalDest -ErrorAction Stop
            [void]$moves.Add([pscustomobject]@{
                From = $item.Source; To = $finalDest; Category = $item.Category
                Size = $item.Size; Time = (Get-Date)
            })
            $movedBytes += $item.Size
        } catch {
            [void]$failed.Add([pscustomobject]@{ Path = $item.Source; Reason = $_.Exception.Message })
            Write-Log "移动失败: $($item.Source) -> $($_.Exception.Message)" 'WARN'
        }
    }
    Write-Host ''
    Write-Ok ("已移动 {0} 个文件，共 {1}" -f $moves.Count, (Format-Bytes $movedBytes))
    if ($failed.Count -gt 0) {
        Write-Warn ("{0} 个文件没能移动（通常是被占用）：" -f $failed.Count)
        foreach ($f in ($failed | Select-Object -First 5)) { Write-Info "  $($f.Path) - $($f.Reason)" }
    }

    $logName = Join-Path $script:StateDir ('整理记录_{0}.json' -f (Get-Date -Format 'yyyyMMdd_HHmmss'))
    $payload = [pscustomobject]@{
        Time = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
        Computer = $env:COMPUTERNAME
        Layout = $plan.Layout
        Targets = $plan.Targets
        Moved = $moves.Count
        Bytes = $movedBytes
        Moves = @($moves)
    }
    try {
        $json = $payload | ConvertTo-Json -Depth 5
        $utf8Bom = New-Object System.Text.UTF8Encoding($true)
        [System.IO.File]::WriteAllText($logName, $json, $utf8Bom)
        Write-Info "移动记录：$logName"
        Write-Info '想还原？菜单里选"撤销上次整理"就行。'
    } catch {
        Write-Warn "写记录失败：$($_.Exception.Message)"
    }

    # 顺手写一份整理报告
    try {
        $sb = New-Object System.Text.StringBuilder
        [void]$sb.AppendLine('# 文件整理记录')
        [void]$sb.AppendLine('')
        [void]$sb.AppendLine(('- 时间：{0}' -f $payload.Time))
        [void]$sb.AppendLine(('- 范围：{0}' -f ($plan.Targets -join '、')))
        [void]$sb.AppendLine(('- 方式：{0}' -f $plan.Layout))
        [void]$sb.AppendLine(('- 移动：{0} 个文件，共 {1}' -f $moves.Count, (Format-Bytes $movedBytes)))
        [void]$sb.AppendLine('')
        [void]$sb.AppendLine('| 原位置 | 新位置 |')
        [void]$sb.AppendLine('| --- | --- |')
        foreach ($m in $moves) { [void]$sb.AppendLine(('| {0} | {1} |' -f $m.From, $m.To)) }
        $reportPath = New-ReportFileName '整理记录' 'md'
        Save-ReportFile -Path $reportPath -Content $sb.ToString() | Out-Null
        Write-Info "整理报告：$reportPath"
    } catch { }

    return $plan
}

function Get-LatestOrganizeLog {
    try {
        $logs = Get-ChildItem -LiteralPath $script:StateDir -Filter '整理记录_*.json' -File -ErrorAction SilentlyContinue |
                Sort-Object LastWriteTime -Descending
        if (-not $logs -or @($logs).Count -eq 0) { return $null }
        return @($logs)[0].FullName
    } catch { return $null }
}

function Invoke-UndoOrganize {
    param([switch]$Apply)
    Write-Section '撤销上次整理'
    $log = Get-LatestOrganizeLog
    if (-not $log) {
        Write-Info '没有找到整理记录，说明还没用这个工具整理过文件。'
        return $false
    }
    Write-Info "使用记录：$log"
    $data = $null
    try {
        $data = Get-Content -LiteralPath $log -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        Write-Err "读取记录失败：$($_.Exception.Message)"
        return $false
    }
    $moves = @($data.Moves)
    Write-Info ("这份记录包含 {0} 次移动（{1}）" -f $moves.Count, $data.Time)
    if ($moves.Count -eq 0) { Write-Info '没有可撤销的内容。'; return $false }

    $restorable = 0
    $conflict = 0
    foreach ($m in $moves) {
        if (-not (Test-Path -LiteralPath $m.To)) { continue }
        if (Test-Path -LiteralPath $m.From) { $conflict++ } else { $restorable++ }
    }
    Write-Info ("可以放回原处：{0} 个；原位置已被占用需要改名：{1} 个" -f $restorable, $conflict)
    if (-not $Apply) {
        Write-Warn '当前是预览模式，按"执行撤销"才会真的移动回去。'
        return $false
    }
    if (-not (Confirm-Action '确认把文件放回原来的位置吗？' $true)) { Write-Skip '已取消'; return $false }

    $done = 0; $fail = 0
    $dirsToCheck = @{}
    foreach ($m in $moves) {
        try {
            if (-not (Test-Path -LiteralPath $m.To)) { continue }
            $origDir = Split-Path -Parent $m.From
            if (-not (Test-Path -LiteralPath $origDir)) { New-Item -ItemType Directory -Path $origDir -Force | Out-Null }
            $target = $m.From
            if (Test-Path -LiteralPath $target) { $target = Get-UniqueDestination $target }
            Move-Item -LiteralPath $m.To -Destination $target -ErrorAction Stop
            $dirsToCheck[(Split-Path -Parent $m.To)] = $true
            $done++
        } catch {
            $fail++
            Write-Log "撤销失败: $($m.To) -> $($_.Exception.Message)" 'WARN'
        }
    }
    Write-Ok "已放回 $done 个文件"
    if ($fail -gt 0) { Write-Warn "$fail 个文件没能放回" }

    # 清理空目录
    foreach ($dir in $dirsToCheck.Keys) {
        try {
            if ((Test-Path -LiteralPath $dir) -and @(Get-ChildItem -LiteralPath $dir -Force -ErrorAction SilentlyContinue).Count -eq 0) {
                Remove-PathSafe -Path $dir | Out-Null
            }
        } catch { }
    }

    try {
        $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
        Move-Item -LiteralPath $log -Destination ($log + ".已撤销_$stamp") -Force -ErrorAction SilentlyContinue
    } catch { }
    Write-Info '撤销完成，记录文件已标记为已撤销。'
    return $true
}

# ---------------------------------------------------------------- 重复文件

function Find-DuplicateFiles {
    param(
        [Parameter(Mandatory)][string[]]$Targets,
        [int]$MinSizeKB = 64,
        [switch]$Recurse
    )
    $files = New-Object System.Collections.ArrayList
    $minBytes = $MinSizeKB * 1KB
    foreach ($root in $Targets) {
        $resolved = $null
        try { $resolved = (Resolve-Path -LiteralPath $root -ErrorAction Stop).ProviderPath } catch { continue }
        try {
            $found = @()
            if ($Recurse) { $found = @(Get-ChildItem -LiteralPath $resolved -Recurse -File -Force -ErrorAction SilentlyContinue) }
            else { $found = @(Get-ChildItem -LiteralPath $resolved -File -Force -ErrorAction SilentlyContinue) }
            foreach ($f in $found) {
                if ($f.Length -ge $minBytes) { [void]$files.Add($f) }
            }
        } catch { }
    }

    # 先按大小分组，只有大小相同的才去算哈希（快很多）
    $bySize = @{}
    foreach ($f in $files) {
        $key = "$($f.Length)"
        if (-not $bySize.ContainsKey($key)) { $bySize[$key] = New-Object System.Collections.ArrayList }
        [void]$bySize[$key].Add($f)
    }
    $dupGroups = New-Object System.Collections.ArrayList
    $checked = 0
    foreach ($key in $bySize.Keys) {
        $group = $bySize[$key]
        if ($group.Count -lt 2) { continue }
        $byHash = @{}
        foreach ($f in $group) {
            $checked++
            if ($checked % 20 -eq 0) { Write-Host -NoNewline '.' -ForegroundColor DarkGray }
            try {
                $h = (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256 -ErrorAction Stop).Hash
            } catch { continue }
            if (-not $byHash.ContainsKey($h)) { $byHash[$h] = New-Object System.Collections.ArrayList }
            [void]$byHash[$h].Add($f)
        }
        foreach ($h in $byHash.Keys) {
            $g = $byHash[$h]
            if ($g.Count -lt 2) { continue }
            [void]$dupGroups.Add([pscustomobject]@{
                Hash = $h
                Size = $g[0].Length
                Keep = $g[0].FullName
                Files = @($g | ForEach-Object { $_.FullName })
                WasteBytes = ([long]$g[0].Length) * ($g.Count - 1)
            })
        }
    }
    Write-Host ''
    return [pscustomobject]@{
        Groups = @($dupGroups | Sort-Object WasteBytes -Descending)
        ScannedFiles = $files.Count
        HashedFiles = $checked
    }
}

function Invoke-DuplicateCleanup {
    param(
        [string[]]$Targets,
        [int]$MinSizeKB = 64,
        [switch]$Recurse,
        [switch]$Apply
    )
    Write-Section '查找重复文件'
    if (-not $Targets -or $Targets.Count -eq 0) { $Targets = Get-DefaultOrganizeTargets }
    Write-Info ('查找范围：' + ($Targets -join '、'))
    Write-Info ("只统计大于 $MinSizeKB KB 的文件；判定方式是内容哈希（SHA256），不是只看文件名。")
    Write-Step '统计中（文件多的时候要等一会儿）...'
    $res = Find-DuplicateFiles -Targets $Targets -MinSizeKB $MinSizeKB -Recurse:$Recurse
    if ($res.Groups.Count -eq 0) {
        Write-Ok '没有发现内容相同的重复文件。'
        return
    }
    $waste = ($res.Groups | Measure-Object -Property WasteBytes -Sum).Sum
    Write-Host ''
    Write-Info ("检查了 {0} 个文件，发现 {1} 组重复，多占空间约 {2}" -f $res.ScannedFiles, $res.Groups.Count, (Format-Bytes $waste))
    $n = 0
    foreach ($g in ($res.Groups | Select-Object -First 10)) {
        $n++
        Write-Host ("  第 {0} 组（{1}，多占 {2}）" -f $n, (Format-Bytes $g.Size), (Format-Bytes $g.WasteBytes)) -ForegroundColor Gray
        foreach ($f in $g.Files) {
            $mark = '    '
            if ($f -eq $g.Keep) { $mark = '  保留' }
            Write-Host ("  $mark $f") -ForegroundColor DarkGray
        }
    }
    if ($res.Groups.Count -gt 10) { Write-Info ("（只显示了前 10 组，共 {0} 组）" -f $res.Groups.Count) }

    # 报告
    try {
        $sb = New-Object System.Text.StringBuilder
        [void]$sb.AppendLine('# 重复文件清单')
        [void]$sb.AppendLine('')
        [void]$sb.AppendLine(('- 生成时间：{0}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')))
        [void]$sb.AppendLine(('- 扫描文件数：{0}，重复组数：{1}，多占空间：{2}' -f $res.ScannedFiles, $res.Groups.Count, (Format-Bytes $waste)))
        [void]$sb.AppendLine('')
        $gi = 0
        foreach ($g in $res.Groups) {
            $gi++
            [void]$sb.AppendLine(('## 第 {0} 组（{1} 个副本，每个 {2}）' -f $gi, $g.Files.Count, (Format-Bytes $g.Size)))
            [void]$sb.AppendLine('')
            foreach ($f in $g.Files) {
                $tag = '- '
                if ($f -eq $g.Keep) { $tag = '- [建议保留] ' }
                $line = $tag + '`' + $f + '`'
                [void]$sb.AppendLine($line)
            }
            [void]$sb.AppendLine('')
        }
        $p = New-ReportFileName '重复文件' 'md'
        Save-ReportFile -Path $p -Content $sb.ToString() | Out-Null
        Write-Info "清单已保存：$p"
    } catch { }

    if (-not $Apply) {
        Write-Host ''
        Write-Warn '当前只是清单，没有删除或移动任何文件。'
        Write-Info '真正执行时，多余的副本会被移到"_重复文件备份_时间戳"文件夹里（不是删除），确认没问题你再自己删。'
        return
    }
    if (-not (Confirm-Action ("把 {0} 组重复文件里的多余副本移到备份文件夹？" -f $res.Groups.Count) $false)) {
        Write-Skip '已取消'
        return
    }
    $backupRoot = Join-Path ($Targets[0]) ('_重复文件备份_' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
    $moved = 0; $movedBytes = [long]0
    $gi = 0
    foreach ($g in $res.Groups) {
        $gi++
        $groupDir = Join-Path $backupRoot ("组{0}" -f $gi)
        foreach ($f in $g.Files) {
            if ($f -eq $g.Keep) { continue }
            try {
                if (-not (Test-Path -LiteralPath $groupDir)) { New-Item -ItemType Directory -Path $groupDir -Force | Out-Null }
                $dest = Get-UniqueDestination (Join-Path $groupDir (Split-Path -Leaf $f))
                Move-Item -LiteralPath $f -Destination $dest -ErrorAction Stop
                $moved++
                $movedBytes += $g.Size
            } catch {
                Write-Log "移动重复文件失败: $f - $($_.Exception.Message)" 'WARN'
            }
        }
    }
    Write-Ok ("已移动 {0} 个重复副本（{1}）到：{2}" -f $moved, (Format-Bytes $movedBytes), $backupRoot)
    Write-Info '确认文件都没问题后，你可以把这个备份文件夹整个删掉。'
}

# ---------------------------------------------------------------- 大文件 / 旧文件

function Invoke-LargeFileScan {
    param(
        [string[]]$Targets,
        [int]$MinMB = 200,
        [int]$Top = 50,
        [int]$OlderThanDays = 0,
        [switch]$Recurse
    )
    Write-Section '查找占空间的大文件'
    if (-not $Targets -or $Targets.Count -eq 0) {
        $Targets = @($env:USERPROFILE)
    }
    Write-Info ('查找范围：' + ($Targets -join '、'))
    Write-Info ("筛选：超过 $MinMB MB" + $(if ($OlderThanDays -gt 0) { "，且 $OlderThanDays 天没改动过" } else { '' }))
    $minBytes = $MinMB * 1MB
    $cut = (Get-Date).AddDays(-1 * $OlderThanDays)
    $list = New-Object System.Collections.ArrayList
    foreach ($root in $Targets) {
        $resolved = $null
        try { $resolved = (Resolve-Path -LiteralPath $root -ErrorAction Stop).ProviderPath } catch { continue }
        Write-Step "扫描 $resolved ..."
        try {
            $found = @(Get-ChildItem -LiteralPath $resolved -Recurse -File -Force -ErrorAction SilentlyContinue)
            foreach ($f in $found) {
                if ($f.Length -lt $minBytes) { continue }
                if ($OlderThanDays -gt 0 -and $f.LastWriteTime -gt $cut) { continue }
                [void]$list.Add([pscustomobject]@{
                    Size = $f.Length; Modified = $f.LastWriteTime; Path = $f.FullName
                    Ext = $f.Extension; Folder = $f.DirectoryName
                })
            }
        } catch { }
    }
    $top2 = @($list | Sort-Object Size -Descending | Select-Object -First $Top)
    Write-Host ''
    if ($top2.Count -eq 0) { Write-Ok "没有超过 $MinMB MB 的文件。"; return }
    $sum = ($top2 | Measure-Object -Property Size -Sum).Sum
    Write-Info ("最大的 {0} 个文件合计 {1}" -f $top2.Count, (Format-Bytes $sum))
    Write-Host ''
    Write-Host ('    {0,10}  {1}  {2}' -f '大小', '修改时间', '路径') -ForegroundColor DarkGray
    foreach ($f in $top2) {
        $p = $f.Path
        if ($p.Length -gt 78) { $p = '…' + $p.Substring($p.Length - 77) }
        Write-Host ('    {0,10}  {1}  {2}' -f (Format-Bytes $f.Size), $f.Modified.ToString('yyyy-MM-dd'), $p) -ForegroundColor Gray
    }
    try {
        $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
        $csv = Join-Path $script:ReportDir ("大文件清单_{0}.csv" -f $stamp)
        $md  = Join-Path $script:ReportDir ("大文件清单_{0}.md" -f $stamp)
        $top2 | Select-Object @{n='大小';e={Format-Bytes $_.Size}}, @{n='字节';e={$_.Size}}, @{n='修改时间';e={$_.Modified}}, @{n='路径';e={$_.Path}} |
            Export-Csv -LiteralPath $csv -NoTypeInformation -Encoding UTF8
        $sb = New-Object System.Text.StringBuilder
        [void]$sb.AppendLine('# 大文件清单')
        [void]$sb.AppendLine('')
        [void]$sb.AppendLine(('生成时间：{0}　范围：{1}　筛选：大于 {2} MB' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), ($Targets -join '、'), $MinMB))
        [void]$sb.AppendLine('')
        [void]$sb.AppendLine('| 大小 | 修改时间 | 路径 |')
        [void]$sb.AppendLine('| --- | --- | --- |')
        foreach ($f in $top2) { [void]$sb.AppendLine(('| {0} | {1} | {2} |' -f (Format-Bytes $f.Size), $f.Modified.ToString('yyyy-MM-dd'), $f.Path)) }
        Save-ReportFile -Path $md -Content $sb.ToString() | Out-Null
        Write-Host ''
        Write-Info "清单已保存：$md"
        Write-Info "（同一份数据的 CSV：$csv）"
    } catch { }
}
