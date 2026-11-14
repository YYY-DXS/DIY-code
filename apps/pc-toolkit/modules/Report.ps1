<#
    电脑管家 PcToolkit - 报告模块
    把体检结果输出成：Markdown 报告 + 好看的 HTML 报告 + 可直接复制粘贴求助的问题清单
#>

function ConvertTo-HtmlSafe {
    param([string]$Text)
    if ($null -eq $Text) { return '' }
    $t = "$Text"
    $t = $t -replace '&', '&amp;'
    $t = $t -replace '<', '&lt;'
    $t = $t -replace '>', '&gt;'
    return $t
}

function New-ReportFileName {
    param([string]$Prefix, [string]$Extension)
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    return (Join-Path $script:ReportDir ('{0}_{1}.{2}' -f $Prefix, $stamp, $Extension))
}

function Save-ReportFile {
    param([string]$Path, [string]$Content)
    try {
        $dir = Split-Path -Parent $Path
        if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        $utf8Bom = New-Object System.Text.UTF8Encoding($true)
        [System.IO.File]::WriteAllText($Path, $Content, $utf8Bom)
        Write-Log "报告已写入: $Path"
        return $true
    } catch {
        Write-Err "写报告失败：$($_.Exception.Message)"
        return $false
    }
}

function Get-MarkdownReport {
    param([Parameter(Mandatory)]$Diag)

    $sb = New-Object System.Text.StringBuilder
    $w = { param($line) [void]$sb.AppendLine($line) }
    $t = $Diag.System

    & $w "# 电脑体检报告"
    & $w ""
    & $w ("- 生成时间：{0}" -f $Diag.GeneratedAt.ToString('yyyy-MM-dd HH:mm:ss'))
    & $w ("- 健康分：**{0} / 100**（等级 {1}）" -f $Diag.Score, $Diag.Grade)
    & $w ("- 体检用时：{0:N1} 秒" -f $Diag.DurationSeconds)
    & $w ("- 管理员权限：{0}" -f $(if ($Diag.IsAdmin) { '是' } else { '否（部分项目未检测）' }))
    & $w ""
    & $w "## 一、处理建议"
    & $w ""
    if ($Diag.Advice.Count -eq 0) { & $w "- 没有发现需要处理的问题。" }
    else {
        $i = 1
        foreach ($a in $Diag.Advice) { & $w ("{0}. {1}" -f $i, $a); $i++ }
    }
    & $w ""
    & $w "## 二、电脑概况"
    & $w ""
    & $w "| 项目 | 内容 |"
    & $w "| --- | --- |"
    & $w ("| 操作系统 | {0} {1} (Build {2}) |" -f $t.Caption, $t.DisplayVersion, $t.Build)
    & $w ("| 处理器 | {0} |" -f $t.CPU)
    & $w ("| 内存 | {0} |" -f $t.RAM)
    & $w ("| 显卡 | {0} |" -f $t.GPU)
    & $w ("| 开机时长 | {0} |" -f $t.Uptime)
    & $w ("| 计算机名 / 用户 | {0} / {1} |" -f $t.ComputerName, $t.UserName)
    & $w ""
    & $w "## 三、磁盘空间"
    & $w ""
    & $w "| 盘符 | 卷标 | 总容量 | 剩余 | 剩余比例 |"
    & $w "| --- | --- | --- | --- | --- |"
    foreach ($d in $Diag.Drives) {
        & $w ("| {0} | {1} | {2} | {3} | {4}% |" -f $d.Letter, $d.Label, (Format-Bytes $d.Total), (Format-Bytes $d.Free), $d.FreePct)
    }
    & $w ""
    & $w "## 四、垃圾文件体积"
    & $w ""
    & $w "| 项目 | 大小 | 文件数 | 说明 |"
    & $w "| --- | --- | --- | --- |"
    foreach ($j in ($Diag.Junk.Items | Where-Object { $_.Exists } | Sort-Object Bytes -Descending)) {
        $size = '未统计'
        if ($j.Measured) { $size = Format-Bytes $j.Bytes }
        if ($j.Truncated) { $size = "$size（超时，实际更大）" }
        & $w ("| {0} | {1} | {2} | {3} |" -f $j.Name, $size, $j.Files, $j.Hint)
    }
    & $w ("| **合计** | **{0}** | | |" -f (Format-Bytes $Diag.Junk.TotalBytes))
    & $w ""
    & $w "## 五、启动项"
    & $w ""
    & $w "| 名称 | 来源 | 命令 | 目标是否存在 |"
    & $w "| --- | --- | --- | --- |"
    foreach ($s in $Diag.Startup) {
        $exists = '未知'
        if ($s.Exists -eq $true) { $exists = '是' } elseif ($s.Exists -eq $false) { $exists = '**否（失效）**' }
        $cmd = "$($s.Command)"
        if ($cmd.Length -gt 90) { $cmd = $cmd.Substring(0, 90) + '...' }
        & $w ("| {0} | {1} | {2} | {3} |" -f $s.Name, $s.Source, $cmd, $exists)
    }
    & $w ""
    & $w "## 六、环境变量体检"
    & $w ""
    & $w ("- 系统 PATH：{0} 项（无效 {1} / 重复 {2} / 空项 {3}）" -f `
        $Diag.Env.MachinePath.RawCount, $Diag.Env.MachinePath.Missing.Count, $Diag.Env.MachinePath.Duplicates.Count, $Diag.Env.MachinePath.Empty)
    & $w ("- 用户 PATH：{0} 项（无效 {1} / 重复 {2} / 空项 {3}）" -f `
        $Diag.Env.UserPath.RawCount, $Diag.Env.UserPath.Missing.Count, $Diag.Env.UserPath.Duplicates.Count, $Diag.Env.UserPath.Empty)
    if ($Diag.Env.MachinePath.Missing.Count -gt 0) {
        & $w ""
        & $w "系统 PATH 里不存在的目录："
        foreach ($m in $Diag.Env.MachinePath.Missing) { & $w ('- `{0}`' -f $m) }
    }
    if ($Diag.Env.UserPath.Missing.Count -gt 0) {
        & $w ""
        & $w "用户 PATH 里不存在的目录："
        foreach ($m in $Diag.Env.UserPath.Missing) { & $w ('- `{0}`' -f $m) }
    }
    if ($Diag.Env.TempIssues.Count -gt 0) {
        & $w ""
        & $w "临时目录变量问题："
        foreach ($m in $Diag.Env.TempIssues) { & $w "- $m" }
    }
    if ($Diag.Env.CriticalMissing.Count -gt 0) {
        & $w ""
        & $w "关键变量问题："
        foreach ($m in $Diag.Env.CriticalMissing) { & $w "- **$m**" }
    }
    $diskOnly = @($Diag.Env.Tools | Where-Object { $_.FoundOnDisk -and -not $_.InPath })
    if ($diskOnly.Count -gt 0) {
        & $w ""
        & $w "装了但命令不在 PATH 里的工具（可能是 PATH 被改坏了）："
        foreach ($tl in $diskOnly) { & $w ("- {0}：{1}" -f $tl.Name, (($tl.Paths | Select-Object -First 3) -join ' ; ')) }
    }
    & $w ""
    & $w "## 七、运行库与组件"
    & $w ""
    & $w ("- VC++ 运行库：{0}" -f $(if ($Diag.Runtime.VCpp.Count -eq 0) { '未检测到' } else { ($Diag.Runtime.VCpp -join '、') }))
    foreach ($m in $Diag.Runtime.VCppMissing) { & $w ("- ⚠ {0}" -f $m) }
    & $w ("- .NET Framework：{0}" -f $Diag.Runtime.NetFx)
    if ($Diag.Runtime.DotNetRuntimes.Count -gt 0) {
        & $w "- .NET（新版运行时）："
        foreach ($r in $Diag.Runtime.DotNetRuntimes) { & $w ("  - {0}" -f $r) }
    }
    & $w ("- DirectX：{0}" -f $Diag.Runtime.DirectX)
    & $w ("- Windows Defender：{0}" -f $Diag.Runtime.Defender)
    & $w ""
    & $w "## 八、快捷方式断链"
    & $w ""
    & $w ("共检查 {0} 个，断链 {1} 个。" -f $Diag.Shortcuts.Total, $Diag.Shortcuts.Broken.Count)
    if ($Diag.Shortcuts.Broken.Count -gt 0) {
        & $w ""
        & $w "| 名称 | 指向 |"
        & $w "| --- | --- |"
        foreach ($b in $Diag.Shortcuts.Broken) { & $w ("| {0} | {1} |" -f $b.Name, $b.Target) }
    }
    & $w ""
    & $w "## 九、有问题的设备"
    & $w ""
    if ($Diag.Devices.Count -eq 0) { & $w "没有发现报错的设备。" }
    else {
        & $w "| 设备 | 类型 | 状态 |"
        & $w "| --- | --- | --- |"
        foreach ($d in $Diag.Devices) { & $w ("| {0} | {1} | {2} |" -f $d.Name, $d.Class, $d.Status) }
    }
    & $w ""
    & $w "## 十、开机自启但没运行的服务"
    & $w ""
    if ($Diag.Services.Count -eq 0) { & $w "没有异常。" }
    else {
        foreach ($s in $Diag.Services) { & $w ("- {0}（{1}）" -f $s.Name, $s.DisplayName) }
    }
    & $w ""
    & $w "## 十一、Windows 更新与磁盘"
    & $w ""
    & $w ("- 最近一次更新：{0}" -f $Diag.Update.LastHotfix)
    & $w ("- 待重启：{0}" -f $(if ($Diag.Update.PendingReboot) { ($Diag.Update.PendingReasons -join '；') } else { '无' }))
    foreach ($s in $Diag.Update.Services) { & $w ("- 服务 {0}：{1}（{2}）" -f $s.Name, $s.Status, $s.StartType) }
    foreach ($d in $Diag.Health.Disks) { & $w ("- 磁盘 {0}：{1} / {2}" -f $d.Name, $d.Health, $d.Status) }
    foreach ($w2 in $Diag.Health.Dirty) { & $w ("- ⚠ {0}" -f $w2) }
    & $w ""
    & $w "## 十二、最近 7 天的错误日志（前 30 条）"
    & $w ""
    if ($Diag.Events.Count -eq 0) { & $w "没有读取到错误事件（可能是权限不足）。" }
    else {
        & $w "| 时间 | 级别 | 来源 | 事件ID | 摘要 |"
        & $w "| --- | --- | --- | --- | --- |"
        foreach ($e in ($Diag.Events | Select-Object -First 30)) {
            $msg = "$($e.Message)" -replace '\|', '/'
            & $w ("| {0} | {1} | {2} | {3} | {4} |" -f $e.Time.ToString('MM-dd HH:mm'), $e.Level, $e.Provider, $e.Id, $msg)
        }
    }
    & $w ""
    & $w "---"
    & $w ""
    & $w ("由 {0} v{1} 生成" -f $script:ToolkitName, $script:ToolkitVersion)
    return $sb.ToString()
}

function Get-HtmlReport {
    param([Parameter(Mandatory)]$Diag)
    $t = $Diag.System
    $e = { param($x) ConvertTo-HtmlSafe "$x" }

    $scoreColor = '#16a34a'
    if ($Diag.Score -lt 90) { $scoreColor = '#ca8a04' }
    if ($Diag.Score -lt 75) { $scoreColor = '#ea580c' }
    if ($Diag.Score -lt 60) { $scoreColor = '#dc2626' }

    $sb = New-Object System.Text.StringBuilder
    $w = { param($line) [void]$sb.AppendLine($line) }

    & $w '<!DOCTYPE html>'
    & $w '<html lang="zh-CN"><head><meta charset="utf-8">'
    & $w '<meta name="viewport" content="width=device-width, initial-scale=1">'
    & $w ("<title>电脑体检报告 {0}</title>" -f $Diag.GeneratedAt.ToString('yyyy-MM-dd HH:mm'))
    & $w @'
<style>
  :root { --bg:#0f172a; --card:#ffffff; --line:#e2e8f0; --muted:#64748b; --accent:#2563eb; }
  * { box-sizing: border-box; }
  body { margin:0; padding:28px 16px 60px; background:#f1f5f9; color:#0f172a;
         font-family:"Microsoft YaHei","PingFang SC","Segoe UI",system-ui,sans-serif; line-height:1.65; }
  .wrap { max-width:1040px; margin:0 auto; }
  .head { background:linear-gradient(135deg,#1e3a8a,#2563eb); color:#fff; border-radius:18px;
          padding:26px 28px; display:flex; gap:24px; align-items:center; flex-wrap:wrap;
          box-shadow:0 10px 30px rgba(37,99,235,.25); }
  .score { width:118px; height:118px; border-radius:50%; background:#fff; color:var(--accent);
           display:flex; flex-direction:column; align-items:center; justify-content:center; flex:0 0 auto; }
  .score b { font-size:40px; line-height:1; }
  .score span { font-size:12px; color:#64748b; }
  .head h1 { margin:0 0 6px; font-size:24px; }
  .head p { margin:2px 0; font-size:14px; opacity:.92; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:14px;
          padding:18px 20px; margin-top:18px; box-shadow:0 2px 8px rgba(15,23,42,.04); }
  .card h2 { margin:0 0 12px; font-size:17px; border-left:4px solid var(--accent); padding-left:10px; }
  table { border-collapse:collapse; width:100%; font-size:13.5px; }
  th, td { border-bottom:1px solid var(--line); padding:7px 9px; text-align:left; vertical-align:top; }
  th { background:#f8fafc; color:#475569; font-weight:600; white-space:nowrap; }
  tr:hover td { background:#f8fafc; }
  .bad { color:#dc2626; font-weight:600; }
  .warn { color:#ca8a04; }
  .good { color:#16a34a; }
  ul, ol { margin:6px 0 0; padding-left:22px; }
  li { margin:3px 0; }
  code { background:#f1f5f9; padding:1px 5px; border-radius:4px; font-size:12.5px; }
  .muted { color:var(--muted); font-size:13px; }
  .pill { display:inline-block; padding:2px 9px; border-radius:999px; font-size:12px; background:#eff6ff; color:#1d4ed8; margin-right:6px; }
  @media print { body { background:#fff; } .card { break-inside:avoid; } }
</style></head><body><div class="wrap">
'@
    & $w '<div class="head">'
    & $w ('  <div class="score" style="color:{0}"><b>{1}</b><span>健康分 / 100　等级 {2}</span></div>' -f $scoreColor, $Diag.Score, $Diag.Grade)
    & $w '  <div>'
    & $w '    <h1>电脑体检报告</h1>'
    & $w ('    <p>生成时间：{0}</p>' -f $Diag.GeneratedAt.ToString('yyyy-MM-dd HH:mm:ss'))
    & $w ('    <p>{0} {1}（Build {2}）　·　{3}</p>' -f (& $e $t.Caption), (& $e $t.DisplayVersion), (& $e $t.Build), (& $e $t.Arch))
    & $w ('    <p>CPU：{0}</p>' -f (& $e $t.CPU))
    & $w ('    <p>内存：{0}　显卡：{1}</p>' -f (& $e $t.RAM), (& $e $t.GPU))
    & $w ('    <p>开机时长：{0}　·　体检用时 {1:N1} 秒　·　管理员权限：{2}</p>' -f (& $e $t.Uptime), $Diag.DurationSeconds, $(if ($Diag.IsAdmin) { '是' } else { '否' }))
    & $w '  </div>'
    & $w '</div>'

    & $w '<div class="card"><h2>处理建议（按顺序做）</h2>'
    if ($Diag.Advice.Count -eq 0) { & $w '<p class="good">没有发现需要处理的问题。</p>' }
    else {
        & $w '<ol>'
        foreach ($a in $Diag.Advice) { & $w ('<li>{0}</li>' -f (& $e $a)) }
        & $w '</ol>'
    }
    & $w '</div>'

    & $w '<div class="card"><h2>磁盘空间</h2><table><tr><th>盘符</th><th>卷标</th><th>总容量</th><th>剩余</th><th>剩余比例</th><th>状态</th></tr>'
    foreach ($d in $Diag.Drives) {
        $cls = 'good'; $note = '充足'
        if ($d.FreePct -lt 20) { $cls = 'warn'; $note = '偏低' }
        if ($d.FreePct -lt 10) { $cls = 'bad'; $note = '紧张，建议清理' }
        & $w ('<tr><td><b>{0}</b></td><td>{1}</td><td>{2}</td><td>{3}</td><td class="{4}">{5}%</td><td>{6}</td></tr>' -f `
                (& $e $d.Letter), (& $e $d.Label), (Format-Bytes $d.Total), (Format-Bytes $d.Free), $cls, $d.FreePct, $note)
    }
    & $w '</table></div>'

    & $w '<div class="card"><h2>垃圾文件体积</h2><table><tr><th>项目</th><th>大小</th><th>文件数</th><th>说明</th></tr>'
    foreach ($j in ($Diag.Junk.Items | Where-Object { $_.Exists } | Sort-Object Bytes -Descending)) {
        $size = '未统计'
        if ($j.Measured) { $size = Format-Bytes $j.Bytes }
        if ($j.Truncated) { $size = "$size（超时）" }
        & $w ('<tr><td>{0}</td><td>{1}</td><td>{2}</td><td class="muted">{3}</td></tr>' -f (& $e $j.Name), $size, $j.Files, (& $e $j.Hint))
    }
    & $w ('<tr><td><b>合计</b></td><td><b>{0}</b></td><td></td><td></td></tr>' -f (Format-Bytes $Diag.Junk.TotalBytes))
    & $w '</table></div>'

    & $w '<div class="card"><h2>启动项</h2><table><tr><th>名称</th><th>来源</th><th>命令</th><th>目标</th></tr>'
    foreach ($s in $Diag.Startup) {
        $exists = '<span class="muted">未知</span>'
        if ($s.Exists -eq $true) { $exists = '<span class="good">存在</span>' }
        elseif ($s.Exists -eq $false) { $exists = '<span class="bad">已失效</span>' }
        $cmd = "$($s.Command)"; if ($cmd.Length -gt 110) { $cmd = $cmd.Substring(0, 110) + '...' }
        & $w ('<tr><td>{0}</td><td class="muted">{1}</td><td><code>{2}</code></td><td>{3}</td></tr>' -f (& $e $s.Name), (& $e $s.Source), (& $e $cmd), $exists)
    }
    & $w '</table></div>'

    & $w '<div class="card"><h2>环境变量体检</h2>'
    & $w ('<p><span class="pill">系统 PATH {0} 项</span><span class="pill">用户 PATH {1} 项</span></p>' -f $Diag.Env.MachinePath.RawCount, $Diag.Env.UserPath.RawCount)
    & $w '<table><tr><th>范围</th><th>无效路径</th><th>重复</th><th>空项</th></tr>'
    & $w ('<tr><td>系统 PATH</td><td class="{0}">{1}</td><td>{2}</td><td>{3}</td></tr>' -f $(if ($Diag.Env.MachinePath.Missing.Count -gt 0) { 'bad' } else { 'good' }), $Diag.Env.MachinePath.Missing.Count, $Diag.Env.MachinePath.Duplicates.Count, $Diag.Env.MachinePath.Empty)
    & $w ('<tr><td>用户 PATH</td><td class="{0}">{1}</td><td>{2}</td><td>{3}</td></tr>' -f $(if ($Diag.Env.UserPath.Missing.Count -gt 0) { 'bad' } else { 'good' }), $Diag.Env.UserPath.Missing.Count, $Diag.Env.UserPath.Duplicates.Count, $Diag.Env.UserPath.Empty)
    & $w '</table>'
    $missingAll = @($Diag.Env.MachinePath.Missing) + @($Diag.Env.UserPath.Missing)
    if ($missingAll.Count -gt 0) {
        & $w '<p><b>PATH 里已经不存在的目录：</b></p><ul>'
        foreach ($m in $missingAll) { & $w ('<li><code>{0}</code></li>' -f (& $e $m)) }
        & $w '</ul>'
    }
    if ($Diag.Env.TempIssues.Count -gt 0) {
        & $w '<p><b>临时目录问题：</b></p><ul>'
        foreach ($m in $Diag.Env.TempIssues) { & $w ('<li class="warn">{0}</li>' -f (& $e $m)) }
        & $w '</ul>'
    }
    if ($Diag.Env.CriticalMissing.Count -gt 0) {
        & $w '<p><b>关键变量问题：</b></p><ul>'
        foreach ($m in $Diag.Env.CriticalMissing) { & $w ('<li class="bad">{0}</li>' -f (& $e $m)) }
        & $w '</ul>'
    }
    $diskOnly = @($Diag.Env.Tools | Where-Object { $_.FoundOnDisk -and -not $_.InPath })
    if ($diskOnly.Count -gt 0) {
        & $w '<p><b>装了但命令用不了（不在 PATH 里）：</b></p><ul>'
        foreach ($tl in $diskOnly) { & $w ('<li>{0}：<code>{1}</code></li>' -f (& $e $tl.Name), (& $e (($tl.Paths | Select-Object -First 2) -join ' ; '))) }
        & $w '</ul>'
    }
    & $w '</div>'

    & $w '<div class="card"><h2>运行库与组件</h2><table><tr><th>项目</th><th>检测结果</th></tr>'
    & $w ('<tr><td>VC++ 运行库</td><td>{0}</td></tr>' -f (& $e ($(if ($Diag.Runtime.VCpp.Count -eq 0) { '未检测到' } else { $Diag.Runtime.VCpp -join '、' }))))
    foreach ($m in $Diag.Runtime.VCppMissing) { & $w ('<tr><td></td><td class="warn">⚠ {0}</td></tr>' -f (& $e $m)) }
    & $w ('<tr><td>.NET Framework</td><td>{0}</td></tr>' -f (& $e $Diag.Runtime.NetFx))
    if ($Diag.Runtime.DotNetRuntimes.Count -gt 0) {
        $runtimes = @($Diag.Runtime.DotNetRuntimes | Select-Object -First 8)
        $runtimeText = ''
        foreach ($r in $runtimes) { $runtimeText += ('{0}<br>' -f (& $e $r)) }
        & $w ('<tr><td>.NET 新版运行时</td><td>{0}</td></tr>' -f $runtimeText)
    }
    & $w ('<tr><td>DirectX</td><td>{0}</td></tr>' -f (& $e $Diag.Runtime.DirectX))
    & $w ('<tr><td>Windows Defender</td><td>{0}</td></tr>' -f (& $e $Diag.Runtime.Defender))
    & $w '</table></div>'

    & $w ('<div class="card"><h2>快捷方式断链（{0} / {1}）</h2>' -f $Diag.Shortcuts.Broken.Count, $Diag.Shortcuts.Total)
    if ($Diag.Shortcuts.Broken.Count -eq 0) { & $w '<p class="good">没有断链的快捷方式。</p>' }
    else {
        & $w '<table><tr><th>名称</th><th>指向的目标</th></tr>'
        foreach ($b in $Diag.Shortcuts.Broken) { & $w ('<tr><td>{0}</td><td><code>{1}</code></td></tr>' -f (& $e $b.Name), (& $e $b.Target)) }
        & $w '</table>'
    }
    & $w '</div>'

    & $w '<div class="card"><h2>有问题的硬件设备</h2>'
    if ($Diag.Devices.Count -eq 0) { & $w '<p class="good">没有发现报错的设备。</p>' }
    else {
        & $w '<table><tr><th>设备</th><th>类型</th><th>状态</th></tr>'
        foreach ($d in $Diag.Devices) { & $w ('<tr><td>{0}</td><td>{1}</td><td class="bad">{2}</td></tr>' -f (& $e $d.Name), (& $e $d.Class), (& $e $d.Status)) }
        & $w '</table>'
    }
    & $w '</div>'

    & $w '<div class="card"><h2>开机自启但没运行的服务</h2>'
    if ($Diag.Services.Count -eq 0) { & $w '<p class="good">没有异常。</p>' }
    else {
        & $w '<ul>'
        foreach ($s in $Diag.Services) { & $w ('<li>{0}（{1}）</li>' -f (& $e $s.Name), (& $e $s.DisplayName)) }
        & $w '</ul>'
    }
    & $w '</div>'

    & $w '<div class="card"><h2>Windows 更新与磁盘健康</h2><ul>'
    & $w ('<li>最近一次更新：{0}</li>' -f (& $e $Diag.Update.LastHotfix))
    & $w ('<li>待重启：{0}</li>' -f (& $e $(if ($Diag.Update.PendingReboot) { $Diag.Update.PendingReasons -join '；' } else { '无' })))
    foreach ($s in $Diag.Update.Services) { & $w ('<li>服务 {0}：{1}（{2}）</li>' -f (& $e $s.Name), (& $e $s.Status), (& $e $s.StartType)) }
    foreach ($d in $Diag.Health.Disks) { & $w ('<li>磁盘 {0}：{1} / {2}</li>' -f (& $e $d.Name), (& $e $d.Health), (& $e $d.Status)) }
    foreach ($msg in $Diag.Health.Dirty) { & $w ('<li class="warn">⚠ {0}</li>' -f (& $e $msg)) }
    & $w '</ul></div>'

    & $w '<div class="card"><h2>最近 7 天错误日志（前 30 条）</h2>'
    if ($Diag.Events.Count -eq 0) { & $w '<p class="muted">没有读取到错误事件（可能是权限不足）。</p>' }
    else {
        & $w '<table><tr><th>时间</th><th>级别</th><th>来源</th><th>ID</th><th>摘要</th></tr>'
        foreach ($ev in ($Diag.Events | Select-Object -First 30)) {
            & $w ('<tr><td>{0}</td><td>{1}</td><td>{2}</td><td>{3}</td><td class="muted">{4}</td></tr>' -f `
                    $ev.Time.ToString('MM-dd HH:mm'), (& $e $ev.Level), (& $e $ev.Provider), $ev.Id, (& $e $ev.Message))
        }
        & $w '</table>'
    }
    & $w '</div>'

    & $w ('<p class="muted">由 {0} v{1} 生成 · 报告只反映生成时刻的状态</p>' -f (& $e $script:ToolkitName), $script:ToolkitVersion)
    & $w '</div></body></html>'
    return $sb.ToString()
}

function Get-IssueList {
    <#  生成一段可以直接复制给 AI 或发给懂电脑的人的文字  #>
    param([Parameter(Mandatory)]$Diag)
    $t = $Diag.System
    $sb = New-Object System.Text.StringBuilder
    $w = { param($line) [void]$sb.AppendLine($line) }

    & $w '【我把电脑体检结果贴给你，请帮我判断该怎么修】'
    & $w ''
    & $w ("系统：{0} {1} Build {2} {3}" -f $t.Caption, $t.DisplayVersion, $t.Build, $t.Arch)
    & $w ("CPU：{0}；内存：{1}；显卡：{2}" -f $t.CPU, $t.RAM, $t.GPU)
    & $w ("开机时长：{0}；健康分：{1}" -f $t.Uptime, $Diag.Score)
    & $w ("磁盘：" + (($Diag.Drives | ForEach-Object { "{0} 剩余 {1}%" -f $_.Letter, $_.FreePct }) -join '，'))
    & $w ('待重启：' + $(if ($Diag.Update.PendingReboot) { $Diag.Update.PendingReasons -join '；' } else { '无' }))
    & $w ''
    & $w '发现的问题：'
    if ($Diag.Advice.Count -eq 0) { & $w '- （体检没发现问题）' }
    foreach ($a in $Diag.Advice) { & $w ("- $a") }
    if ($Diag.Env.MachinePath.Missing.Count -gt 0) {
        & $w ''
        & $w '系统 PATH 无效项：'
        foreach ($m in $Diag.Env.MachinePath.Missing) { & $w ("- $m") }
    }
    if ($Diag.Devices.Count -gt 0) {
        & $w ''
        & $w '报错设备：'
        foreach ($d in $Diag.Devices) { & $w ("- $($d.Name) [$($d.Class)] $($d.Status)") }
    }
    $dllErrors = @($Diag.Events | Where-Object { $_.Message -match '\.dll' })
    if ($dllErrors.Count -gt 0) {
        & $w ''
        & $w '和 dll 有关的报错：'
        foreach ($e2 in ($dllErrors | Select-Object -First 8)) { & $w ("- $($e2.Provider) #$($e2.Id): $($e2.Message)") }
    }
    $dead = @($Diag.DeadStartup)
    if ($dead.Count -gt 0) {
        & $w ''
        & $w '失效启动项：'
        foreach ($s in $dead) { & $w ("- $($s.Name) → $($s.Command)") }
    }
    return $sb.ToString()
}

function Write-HealthReports {
    param([Parameter(Mandatory)]$Diag, [switch]$NoOpen)

    $mdPath   = New-ReportFileName '体检报告' 'md'
    $htmlPath = New-ReportFileName '体检报告' 'html'
    $txtPath  = New-ReportFileName '问题清单' 'txt'

    Save-ReportFile -Path $mdPath   -Content (Get-MarkdownReport -Diag $Diag) | Out-Null
    Save-ReportFile -Path $htmlPath -Content (Get-HtmlReport -Diag $Diag)     | Out-Null
    Save-ReportFile -Path $txtPath  -Content (Get-IssueList -Diag $Diag)      | Out-Null

    Write-Section '报告已生成'
    Write-Info "HTML 报告：$htmlPath"
    Write-Info "Markdown 报告：$mdPath"
    Write-Info "求助清单（可以直接复制给别人）：$txtPath"

    if (-not $NoOpen) {
        Open-PathInShell $htmlPath | Out-Null
    }
    return [pscustomobject]@{ Html = $htmlPath; Markdown = $mdPath; Text = $txtPath }
}
