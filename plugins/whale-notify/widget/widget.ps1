param(
  [Parameter(Mandatory = $true)][string]$StatePath,
  [Parameter(Mandatory = $true)][string]$AssetsDir
)

# 鲸鱼娘桌面挂件：无边框透明置顶窗 + 系统托盘图标。
# 状态来自 Host 写的 state.json（带心跳 at）；超过 75 秒没更新就显示“离线”。

Add-Type -AssemblyName PresentationFramework
Add-Type -AssemblyName PresentationCore
Add-Type -AssemblyName WindowsBase
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$mutex = New-Object System.Threading.Mutex($false, 'Local\dsh-whale-pet-widget')
$owned = $false
try { $owned = $mutex.WaitOne(0) } catch { $owned = $false }
if (-not $owned) { exit 0 }

$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $StatePath
if (-not (Test-Path $scriptDir)) { New-Item -ItemType Directory -Force -Path $scriptDir | Out-Null }
$configPath = Join-Path $scriptDir 'widget.json'
$logPath = Join-Path $scriptDir 'widget.log'

function Log([string]$message) {
  try { Add-Content -LiteralPath $logPath -Value ("[{0:yyyy-MM-dd HH:mm:ss}] {1}" -f (Get-Date), $message) -Encoding UTF8 } catch { }
}
trap { Log ('TRAP: ' + $_.Exception.ToString()); exit 1 }
Log "start state=$StatePath assets=$AssetsDir"

$script:phase = ''
$script:armed = $false
$script:left = 0
$script:shutdownTimer = $null
$script:lastStateAt = [datetime]::MinValue
$script:statePhase = 'idle'
$script:lastChange = Get-Date
$script:player = New-Object System.Windows.Media.MediaPlayer
$script:player.Volume = 0.35
$script:notify = $null

function Read-Config {
  if (-not (Test-Path $configPath)) { return $null }
  try { return (Get-Content -LiteralPath $configPath -Raw -ErrorAction Stop | ConvertFrom-Json) } catch { return $null }
}

function Save-Config {
  $payload = @{ left = [int]$script:windowLeft; top = [int]$script:windowTop; armed = [bool]$script:armed } | ConvertTo-Json
  try { Set-Content -LiteralPath $configPath -Value $payload -Encoding UTF8 -ErrorAction Stop } catch { }
}

function Load-Image([string]$path) {
  if (-not (Test-Path $path)) { return $null }
  try {
    $bmp = New-Object System.Windows.Media.Imaging.BitmapImage
    $bmp.BeginInit()
    $bmp.CacheOption = [System.Windows.Media.Imaging.BitmapCacheOption]::OnLoad
    $bmp.UriSource = New-Object System.Uri $path
    $bmp.EndInit()
    return $bmp
  } catch { return $null }
}

function Brush([int]$r, [int]$g, [int]$b) {
  return New-Object System.Windows.Media.SolidColorBrush([System.Windows.Media.Color]::FromRgb($r, $g, $b))
}

[xml]$xaml = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="鲸鱼娘" Width="220" Height="250" WindowStyle="None"
        AllowsTransparency="True" Background="Transparent" Topmost="True"
        ShowInTaskbar="False" ResizeMode="NoResize" ShowActivated="False"
        WindowStartupLocation="Manual">
  <Grid>
    <Grid.RowDefinitions>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>
    <Image x:Name="Still" Grid.Row="0" Stretch="Uniform" RenderOptions.BitmapScalingMode="HighQuality"/>
    <Border Grid.Row="1" HorizontalAlignment="Center" Background="#F2FFFFFF" CornerRadius="10" Padding="8,3" Margin="0,2,0,0">
      <StackPanel Orientation="Horizontal">
        <Ellipse x:Name="Dot" Width="6" Height="6" Fill="#C9CCD1" Margin="0,0,5,0" VerticalAlignment="Center"/>
        <TextBlock x:Name="Chip" FontSize="11" Foreground="#3A4654" Text="空闲" VerticalAlignment="Center" FontFamily="Microsoft YaHei"/>
      </StackPanel>
    </Border>
    <TextBlock x:Name="Countdown" Grid.Row="2" Visibility="Collapsed" HorizontalAlignment="Center"
               FontSize="11" Foreground="#D9534F" Margin="0,2,0,4" Cursor="Hand"
               FontFamily="Microsoft YaHei" Text=""/>
  </Grid>
</Window>
'@

$reader = New-Object System.Xml.XmlNodeReader $xaml
$window = [Windows.Markup.XamlReader]::Load($reader)
$still = $window.FindName('Still')
$dot = $window.FindName('Dot')
$chip = $window.FindName('Chip')
$countdown = $window.FindName('Countdown')

$poses = @{
  idle = Load-Image (Join-Path $AssetsDir 'anim\idle.png')
  running = Load-Image (Join-Path $AssetsDir 'anim\running.png')
  waiting = Load-Image (Join-Path $AssetsDir 'anim\waiting.png')
  done = Load-Image (Join-Path $AssetsDir 'anim\done.png')
  error = Load-Image (Join-Path $AssetsDir 'anim\waiting.png')
  offline = Load-Image (Join-Path $AssetsDir 'anim\idle.png')
}

$labels = @{ idle = '空闲'; running = '运行中'; waiting = '等你回复'; done = '刚完成'; error = '出错了'; offline = '离线' }
$dots = @{
  idle = Brush 201 204 209
  running = Brush 77 107 254
  waiting = Brush 224 160 58
  done = Brush 47 170 107
  error = Brush 217 83 79
  offline = Brush 160 160 160
}

# 轻微浮动 + 摇摆
$group = New-Object System.Windows.Media.TransformGroup
$tilt = New-Object System.Windows.Media.RotateTransform
$float = New-Object System.Windows.Media.TranslateTransform
[void]$group.Children.Add($tilt)
[void]$group.Children.Add($float)
$still.RenderTransform = $group
$still.RenderTransformOrigin = New-Object System.Windows.Point(0.5, 0.5)

$floatAnim = New-Object System.Windows.Media.Animation.DoubleAnimation(0, -6, [TimeSpan]::FromSeconds(2.4))
$floatAnim.AutoReverse = $true
$floatAnim.RepeatBehavior = [System.Windows.Media.Animation.RepeatBehavior]::Forever
$ease = New-Object System.Windows.Media.Animation.SineEase
$ease.EasingMode = [System.Windows.Media.Animation.EasingMode]::EaseInOut
$floatAnim.EasingFunction = $ease
$float.BeginAnimation([System.Windows.Media.TranslateTransform]::YProperty, $floatAnim)

$tiltAnim = New-Object System.Windows.Media.Animation.DoubleAnimation(-1.5, 1.5, [TimeSpan]::FromSeconds(3.6))
$tiltAnim.AutoReverse = $true
$tiltAnim.RepeatBehavior = [System.Windows.Media.Animation.RepeatBehavior]::Forever
$tiltAnim.EasingFunction = $ease
$tilt.BeginAnimation([System.Windows.Media.RotateTransform]::AngleProperty, $tiltAnim)

function Speak([string]$name) {
  if (-not $name) { return }
  $path = Join-Path (Join-Path $AssetsDir 'voice') $name
  if (-not (Test-Path $path)) { return }
  try {
    $script:player.Open((New-Object System.Uri $path))
    $script:player.Play()
  } catch { }
}

function Pick-Voice([string[]]$names) {
  if ($names.Count -eq 0) { return '' }
  return $names[(Get-Random -Minimum 0 -Maximum $names.Count)]
}

function Stop-Countdown {
  if ($script:shutdownTimer -ne $null) { $script:shutdownTimer.Stop(); $script:shutdownTimer = $null }
  $script:left = 0
  $countdown.Visibility = [System.Windows.Visibility]::Collapsed
}

function Do-Shutdown {
  Stop-Countdown
  $script:armed = $false
  Update-ArmedMenu
  Save-Config
  Log 'shutdown scheduled'
  try { & shutdown.exe /s /t 15 | Out-Null } catch { }
}

function Step-Countdown {
  if ($script:left -le 0) { Do-Shutdown; return }
  $countdown.Text = ("{0} 秒后关机 · 点我取消" -f $script:left)
  $script:left -= 1
}

function Start-Countdown {
  if ($script:shutdownTimer -ne $null) { return }
  $script:left = 60
  $countdown.Visibility = [System.Windows.Visibility]::Visible
  $script:shutdownTimer = New-Object System.Windows.Threading.DispatcherTimer
  $script:shutdownTimer.Interval = [TimeSpan]::FromSeconds(1)
  $script:shutdownTimer.Add_Tick({ Step-Countdown })
  $script:shutdownTimer.Start()
  Step-Countdown
}

function Update-NotifyText([string]$next) {
  if ($script:notify -eq $null) { return }
  $label = $labels[$next]
  if ($label -eq $null) { $label = '空闲' }
  try { $script:notify.Text = "鲸鱼娘 · $label" } catch { }
  if ($script:statusItem -ne $null) {
    try { $script:statusItem.Text = "状态：$label" } catch { }
  }
}

function Set-Phase([string]$next) {
  if (-not $labels.ContainsKey($next)) { $next = 'idle' }
  # 关机倒计时期间保持“完成”姿势
  if ($next -eq 'idle' -and $script:shutdownTimer -ne $null) { return }
  if ($script:phase -eq $next) { return }
  $script:phase = $next
  Log "phase -> $next"
  if ($poses[$next] -ne $null) { $still.Source = $poses[$next] }
  $chip.Text = $labels[$next]
  $dot.Fill = $dots[$next]
  Update-NotifyText $next
  $now = Get-Date
  $idleMinutes = ($now - $script:lastChange).TotalMinutes
  $script:lastChange = $now
  # 只有“好久不用、又开始干活”时才说话；其余状态切换保持安静
  if ($next -eq 'running' -and $idleMinutes -gt 30) {
    Log ("resume after {0:N0} min idle -> speak" -f $idleMinutes)
    Speak (Pick-Voice @('welcome.mp3', 'chat-1.mp3', 'chat-2.mp3'))
  }
  if ($next -eq 'done' -and $script:armed) { Start-Countdown }
  if ($next -eq 'running') { Stop-Countdown }
}

function EffectivePhase {
  if ($script:lastStateAt -eq [datetime]::MinValue) { return 'offline' }
  if (((Get-Date) - $script:lastStateAt).TotalSeconds -gt 75) { return 'offline' }
  return $script:statePhase
}

function Poll-State {
  if (-not (Test-Path $StatePath)) { return }
  try {
    $raw = Get-Content -LiteralPath $StatePath -Raw -ErrorAction Stop
    if (-not $raw) { return }
    $state = $raw | ConvertFrom-Json
    if ($state.at) {
      $script:lastStateAt = [DateTimeOffset]::FromUnixTimeMilliseconds([long]$state.at).LocalDateTime
    } else {
      $script:lastStateAt = (Get-Item $StatePath).LastWriteTime
    }
    if ($state.phase) { $script:statePhase = $state.phase }
    Set-Phase (EffectivePhase)
  } catch { }
}

# 位置
$config = Read-Config
$area = [System.Windows.SystemParameters]::WorkArea
$defaultLeft = $area.Right - 240
$defaultTop = $area.Bottom - 320
$window.Left = $defaultLeft
$window.Top = $defaultTop
if ($config -ne $null -and $config.left -ne $null -and $config.top -ne $null) {
  $candidateLeft = [double]$config.left
  $candidateTop = [double]$config.top
  if ($candidateLeft -ge $area.Left -and $candidateLeft -le ($area.Right - 120) -and $candidateTop -ge $area.Top -and $candidateTop -le ($area.Bottom - 80)) {
    $window.Left = $candidateLeft
    $window.Top = $candidateTop
  } else {
    Log "saved position $candidateLeft,$candidateTop outside work area; using the default corner"
  }
}
$script:windowLeft = $window.Left
$script:windowTop = $window.Top
Log ("window at {0},{1}" -f $window.Left, $window.Top)

# 托盘图标
try {
  $script:notify = New-Object System.Windows.Forms.NotifyIcon
  $icoPath = Join-Path $AssetsDir 'tray.ico'
  if (Test-Path $icoPath) { $script:notify.Icon = New-Object System.Drawing.Icon $icoPath }
  $script:notify.Text = '鲸鱼娘 · 空闲'
  $menu = New-Object System.Windows.Forms.ContextMenuStrip
  $script:statusItem = New-Object System.Windows.Forms.ToolStripMenuItem '状态：空闲'
  $script:statusItem.Enabled = $false
  $showItem = New-Object System.Windows.Forms.ToolStripMenuItem '显示 / 隐藏'
  $armItem = New-Object System.Windows.Forms.ToolStripMenuItem '完成后关机'
  $armItem.CheckOnClick = $true
  $armItem.Checked = $script:armed
  $cancelItem = New-Object System.Windows.Forms.ToolStripMenuItem '取消关机倒计时'
  $quitItem = New-Object System.Windows.Forms.ToolStripMenuItem '退出鲸鱼娘'
  [void]$menu.Items.Add($script:statusItem)
  [void]$menu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator))
  [void]$menu.Items.Add($showItem)
  [void]$menu.Items.Add($armItem)
  [void]$menu.Items.Add($cancelItem)
  [void]$menu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator))
  [void]$menu.Items.Add($quitItem)
  $script:notify.ContextMenuStrip = $menu
  $showItem.Add_Click({ if ($window.Visibility -eq 'Visible') { $window.Hide() } else { $window.Show() } })
  $armItem.Add_Click({
    $script:armed = $armItem.Checked
    if (-not $script:armed) { Stop-Countdown }
    Save-Config
  })
  $cancelItem.Add_Click({
    Stop-Countdown
    try { & shutdown.exe /a | Out-Null } catch { }
  })
  $quitItem.Add_Click({ $window.Close() })
  $script:notify.Add_MouseClick({
    param($sender, $eventArgs)
    if ($eventArgs.Button -eq [System.Windows.Forms.MouseButtons]::Left) {
      if ($window.Visibility -eq 'Visible') { $window.Hide() } else { $window.Show() }
    }
  })
  $script:notify.Visible = $true
  Log 'tray icon ready'
} catch {
  Log ('tray failed: ' + $_.Exception.Message)
}

$armItemRef = $menu.Items | Where-Object { $_.Text -eq '完成后关机' }
function Update-ArmedMenu {
  if ($armItemRef -ne $null) { try { $armItemRef.Checked = $script:armed } catch { } }
}

$still.Add_MouseLeftButtonDown({ try { $window.DragMove() } catch { } })
$window.Add_LocationChanged({ $script:windowLeft = $window.Left; $script:windowTop = $window.Top })
$window.Add_Closed({
  Save-Config
  Stop-Countdown
  if ($script:notify -ne $null) {
    try { $script:notify.Visible = $false; $script:notify.Dispose() } catch { }
  }
  try { $script:player.Close() } catch { }
  try { $mutex.ReleaseMutex() } catch { }
  Log 'closed'
})

$poll = New-Object System.Windows.Threading.DispatcherTimer
$poll.Interval = [TimeSpan]::FromMilliseconds(400)
$poll.Add_Tick({ Poll-State })
$poll.Start()

$beat = New-Object System.Windows.Threading.DispatcherTimer
$beat.Interval = [TimeSpan]::FromSeconds(2)
$beat.Add_Tick({ Set-Phase (EffectivePhase) })
$beat.Start()

# 不再定时嘟囔：声音只留给开机与久别重逢

Log 'showing'
$script:bootGreet = New-Object System.Windows.Threading.DispatcherTimer
$script:bootGreet.Interval = [TimeSpan]::FromSeconds(3)
$script:bootGreet.Add_Tick({
  $script:bootGreet.Stop()
  # Windows PowerShell 5.1 没有 TickCount64，用 32 位 TickCount；读不到就不打招呼
  $ticks = $null
  try { $ticks = [Environment]::TickCount } catch { $ticks = $null }
  if ($ticks -ne $null -and ([TimeSpan]::FromMilliseconds([double]$ticks)).TotalMinutes -lt 10) {
    Log 'boot -> speak welcome'
    Speak 'welcome.mp3'
  } else {
    Log 'no boot greeting (machine has been up a while)'
  }
})
$script:bootGreet.Start()
$window.ShowDialog() | Out-Null
