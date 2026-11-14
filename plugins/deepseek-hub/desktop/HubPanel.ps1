param(
  [string]$Knowledge = '',
  [string]$Repo = ''
)

if (-not $Knowledge) { $Knowledge = Join-Path $env:USERPROFILE 'Documents\deepseek-hub\knowledge' }
if (-not $Repo) {
  if ($env:DEEPSEEK_HUB_REPO) {
    $Repo = $env:DEEPSEEK_HUB_REPO
  } else {
    $repoCandidate = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
    if ($repoCandidate -and (Test-Path (Join-Path $repoCandidate '.git'))) {
      $Repo = $repoCandidate
    } else {
      $Repo = (Get-Location).Path
    }
  }
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# 科技脉冲（TechPulse）配色
$paper = [Drawing.ColorTranslator]::FromHtml('#f2f0e9')
$card  = [Drawing.ColorTranslator]::FromHtml('#fffef8')
$ink   = [Drawing.ColorTranslator]::FromHtml('#111914')
$muted = [Drawing.ColorTranslator]::FromHtml('#6f756f')
$acid  = [Drawing.ColorTranslator]::FromHtml('#d9ff57')
$orange= [Drawing.ColorTranslator]::FromHtml('#ff6b35')
$blue  = [Drawing.ColorTranslator]::FromHtml('#7dd3fc')
$line  = [Drawing.Color]::FromArgb(38, 17, 25, 20)

$mono  = New-Object Drawing.Font('Consolas', 10)
$monoS = New-Object Drawing.Font('Consolas', 8.5)
$monoXL= New-Object Drawing.Font('Consolas', 26, [Drawing.FontStyle]::Bold)
$sans  = New-Object Drawing.Font('Microsoft YaHei UI', 9)
$sansS = New-Object Drawing.Font('Microsoft YaHei UI', 8.5)

$form = New-Object Windows.Forms.Form
$form.Text = 'DeepSeek Hub'
$form.ClientSize = New-Object Drawing.Size(460, 340)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedSingle'
$form.MaximizeBox = $false
$form.BackColor = $paper
$form.Font = $sans
$icoPath = Join-Path $PSScriptRoot 'app.ico'
if (Test-Path $icoPath) { $form.Icon = [Drawing.Icon]::ExtractAssociatedIcon($icoPath) }

$canvas = New-Object Windows.Forms.Panel
$canvas.Dock = 'Fill'
$canvas.BackColor = $paper
$canvas.GetType().GetProperty('DoubleBuffered', [Reflection.BindingFlags]'NonPublic,Instance').SetValue($canvas, $true, $null)
$form.Controls.Add($canvas)

$script:snap = @{ conversations = 0; messages = 0; state = '空闲'; lastSync = '从未'; lastPublish = '从未'; auto = '60 分钟'; daily = '20:00'; error = ''; taken = Get-Date }
$script:phase = 0

function Read-Snapshot {
  $convs = @()
  $manifest = Join-Path $Knowledge 'data\manifest.json'
  if (Test-Path $manifest) {
    try { $convs = @((Get-Content $manifest -Raw -Encoding UTF8 | ConvertFrom-Json).conversations.PSObject.Properties.Value) } catch { }
  }
  $hub = $null
  $hs = Join-Path $Knowledge 'data\hub-state.json'
  if (Test-Path $hs) { try { $hub = Get-Content $hs -Raw -Encoding UTF8 | ConvertFrom-Json } catch { } }

  $msgs = ($convs | Measure-Object -Property messages -Sum).Sum
  $syncTs = ($convs | Measure-Object -Property synced_at -Maximum).Maximum
  if ($hub -and $hub.lastSyncAt) { $syncTs = $hub.lastSyncAt }

  $fmt = {
    param($v)
    if (-not $v) { return '从未' }
    try { ([datetimeoffset]::FromUnixTimeSeconds([int64]$v)).ToLocalTime().ToString('MM-dd HH:mm') } catch { '从未' }
  }
  $pub = '从未'
  $log = Join-Path $Repo 'tools\auto-publish\run.log'
  if (Test-Path $log) { $pub = (Get-Item $log).LastWriteTime.ToString('MM-dd HH:mm') }

  $script:snap = @{
    conversations = if ($convs.Count) { $convs.Count } else { 0 }
    messages      = if ($msgs) { [int]$msgs } else { 0 }
    state         = if ($hub -and $hub.running) { '同步中' } else { '空闲' }
    lastSync      = & $fmt $syncTs
    lastPublish   = $pub
    auto          = '60 分钟'
    daily         = '20:00'
    error         = if ($hub -and $hub.lastError) { [string]$hub.lastError } else { '' }
    taken         = Get-Date
  }
}

function Round-Rect([Drawing.Rectangle]$r, [int]$radius) {
  $p = New-Object Drawing.Drawing2D.GraphicsPath
  $d = $radius * 2
  $p.AddArc($r.X, $r.Y, $d, $d, 180, 90)
  $p.AddArc($r.Right - $d, $r.Y, $d, $d, 270, 90)
  $p.AddArc($r.Right - $d, $r.Bottom - $d, $d, $d, 0, 90)
  $p.AddArc($r.X, $r.Bottom - $d, $d, $d, 90, 90)
  $p.CloseFigure()
  return $p
}

$canvas.Add_Paint({
  param($sender, $e)
  $g = $e.Graphics
  $g.SmoothingMode = [Drawing.Drawing2D.SmoothingMode]::AntiAlias
  $g.TextRenderingHint = [Drawing.Text.TextRenderingHint]::ClearTypeGridFit
  $s = $script:snap

  # 背景 + 右上角酸绿光晕
  $g.Clear($paper)
  for ($i = 7; $i -ge 1; $i--) {
    $a = [int](2.2 * $i)
    $brush = New-Object Drawing.SolidBrush ([Drawing.Color]::FromArgb($a, 217, 255, 87))
    $size = 120 + $i * 44
    $g.FillEllipse($brush, 460 - $size + 60, -$size / 2, $size, $size)
    $brush.Dispose()
  }

  # 顶部标题
  $g.DrawString('DEEPSEEK HUB', $mono, (New-Object Drawing.SolidBrush $ink), 24, 20)
  $g.DrawString('网页对话 → 知识库 → GitHub', $sansS, (New-Object Drawing.SolidBrush $muted), 24, 40)
  $pen = New-Object Drawing.Pen $line, 1
  $g.DrawLine($pen, 24, 66, 436, 66)

  # 状态点
  $dotColor = if ($s.state -eq '同步中') { $orange } else { [Drawing.ColorTranslator]::FromHtml('#92a300') }
  $dot = New-Object Drawing.SolidBrush $dotColor
  $g.FillEllipse($dot, 356, 24, 9, 9)
  $g.DrawString($s.state, $sans, (New-Object Drawing.SolidBrush $ink), 372, 18)

  # 大数字
  $g.DrawString([string]$s.conversations, $monoXL, (New-Object Drawing.SolidBrush $ink), 22, 78)
  $g.DrawString('会话 / CONVERSATIONS', $monoS, (New-Object Drawing.SolidBrush $muted), 24, 126)
  $bar = New-Object Drawing.SolidBrush $acid
  $g.FillRectangle($bar, 24, 144, 64, 3)

  $g.DrawString([string]$s.messages, $monoXL, (New-Object Drawing.SolidBrush $ink), 240, 78)
  $g.DrawString('消息 / MESSAGES', $monoS, (New-Object Drawing.SolidBrush $muted), 242, 126)

  # 卡片
  $rect = New-Object Drawing.Rectangle 24, 172, 412, 108
  $path = Round-Rect $rect 10
  $g.FillPath((New-Object Drawing.SolidBrush $card), $path)
  $g.DrawPath((New-Object Drawing.Pen $line, 1), $path)

  $rows = @(
    @('最近同步', $s.lastSync),
    @('最近发布', $s.lastPublish),
    @('自动同步', $s.auto),
    @('每日发布', $s.daily)
  )
  $y = 186
  foreach ($r in $rows) {
    $g.DrawString($r[0], $sansS, (New-Object Drawing.SolidBrush $muted), 40, $y)
    $g.DrawString([string]$r[1], $mono, (New-Object Drawing.SolidBrush $ink), 150, ($y - 1))
    $y += 24
  }

  # 脉冲线
  $g.DrawLine((New-Object Drawing.Pen ([Drawing.Color]::FromArgb(28, 17, 25, 20)), 1), 24, 300, 436, 300)
  $x = 24 + ($script:phase % 380)
  $g.FillRectangle((New-Object Drawing.SolidBrush $acid), $x, 299, 46, 2)
  $g.FillRectangle((New-Object Drawing.SolidBrush $orange), [Math]::Min(434, $x + 46), 299, 8, 2)

  # 底部
  $g.DrawString(('每 3 秒刷新 · ' + $s.taken.ToString('HH:mm:ss')), $monoS, (New-Object Drawing.SolidBrush $muted), 24, 310)
  if ($s.error) {
    $msg = $s.error
    if ($msg.Length -gt 46) { $msg = $msg.Substring(0, 46) + '…' }
    $g.DrawString($msg, $monoS, (New-Object Drawing.SolidBrush $orange), 24, 326)
  }

  $pen.Dispose()
})

$timer = New-Object Windows.Forms.Timer
$timer.Interval = 400
$tick = 0
$timer.Add_Tick({
  $script:phase = ($script:phase + 14) % 380
  $script:tickCounter++
  if ($script:tickCounter % 8 -eq 0) { Read-Snapshot }
  $canvas.Invalidate()
})
$script:tickCounter = 0
Read-Snapshot
$timer.Start()
[void]$form.ShowDialog()
