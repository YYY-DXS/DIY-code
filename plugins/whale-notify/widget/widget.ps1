param(
  [Parameter(Mandatory = $true)][string]$StatePath,
  [Parameter(Mandatory = $true)][string]$AssetsDir
)

# 鲸鱼娘桌面挂件：无边框透明置顶窗，读 Host 写的 state.json 切换表情与语音。
# 单实例；关掉后不会自动重开（重启 DSH 或重新启用插件才会）。

Add-Type -AssemblyName PresentationFramework
Add-Type -AssemblyName PresentationCore
Add-Type -AssemblyName WindowsBase

$mutex = New-Object System.Threading.Mutex($false, 'Local\dsh-whale-pet-widget')
$owned = $false
try { $owned = $mutex.WaitOne(0) } catch { $owned = $false }
if (-not $owned) { exit 0 }

$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $StatePath
if (-not (Test-Path $scriptDir)) { New-Item -ItemType Directory -Force -Path $scriptDir | Out-Null }
$configPath = Join-Path $scriptDir 'widget.json'

$script:phase = ''
$script:armed = $false
$script:left = 0
$script:shutdownTimer = $null
$script:player = New-Object System.Windows.Media.MediaPlayer
$script:player.Volume = 0.9

function Read-Config {
  if (-not (Test-Path $configPath)) { return $null }
  try { return (Get-Content -LiteralPath $configPath -Raw -ErrorAction Stop | ConvertFrom-Json) } catch { return $null }
}

function Save-Config {
  $payload = @{ left = [int]$window.Left; top = [int]$window.Top; armed = [bool]$script:armed } | ConvertTo-Json
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
        <Button x:Name="ArmButton" Content="关" FontSize="11" Width="20" Height="18" Margin="8,0,0,0" Padding="0"
                BorderThickness="0" Background="Transparent" FontFamily="Microsoft YaHei"
                ToolTip="武装：完成一轮后 60 秒关机"/>
        <Button x:Name="CloseButton" Content="×" FontSize="13" Width="18" Height="18" Margin="2,0,0,0" Padding="0"
                BorderThickness="0" Background="Transparent" ToolTip="关闭桌宠"/>
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
$armButton = $window.FindName('ArmButton')
$closeButton = $window.FindName('CloseButton')
$countdown = $window.FindName('Countdown')

$poses = @{
  idle = Load-Image (Join-Path $AssetsDir 'anim\idle.png')
  running = Load-Image (Join-Path $AssetsDir 'anim\running.png')
  waiting = Load-Image (Join-Path $AssetsDir 'anim\waiting.png')
  done = Load-Image (Join-Path $AssetsDir 'anim\done.png')
  error = Load-Image (Join-Path $AssetsDir 'anim\waiting.png')
}

$labels = @{ idle = '空闲'; running = '运行中'; waiting = '等你回复'; done = '刚完成'; error = '出错了' }
$dots = @{
  idle = Brush 201 204 209
  running = Brush 77 107 254
  waiting = Brush 224 160 58
  done = Brush 47 170 107
  error = Brush 217 83 79
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

function Update-ArmButton {
  if ($script:armed) {
    $armButton.Background = Brush 224 160 58
    $armButton.Foreground = Brush 255 255 255
    $armButton.Content = '关'
    $armButton.ToolTip = '已武装：完成一轮后 60 秒关机，点此取消'
  } else {
    $armButton.Background = New-Object System.Windows.Media.SolidColorBrush([System.Windows.Media.Colors]::Transparent)
    $armButton.Foreground = Brush 58 70 84
    $armButton.Content = '关'
    $armButton.ToolTip = '武装：完成一轮后 60 秒关机'
  }
}

function Stop-Countdown {
  if ($script:shutdownTimer -ne $null) { $script:shutdownTimer.Stop(); $script:shutdownTimer = $null }
  $script:left = 0
  $countdown.Visibility = [System.Windows.Visibility]::Collapsed
}

function Do-Shutdown {
  Stop-Countdown
  $script:armed = $false
  Save-Config
  Update-ArmButton
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

function Set-Phase([string]$next) {
  if (-not $labels.ContainsKey($next)) { $next = 'idle' }
  # 关机倒计时期间保持“完成”姿势，别被 Host 的 idle 复位打断
  if ($next -eq 'idle' -and $script:shutdownTimer -ne $null) { return }
  if ($script:phase -eq $next) { return }
  $script:phase = $next
  if ($poses[$next] -ne $null) { $still.Source = $poses[$next] }
  $chip.Text = $labels[$next]
  $dot.Fill = $dots[$next]
  switch ($next) {
    'running' { Speak (Pick-Voice @('running-1.mp3', 'running-2.mp3')) }
    'waiting' { Speak 'approval.mp3' }
    'done' { Speak (Pick-Voice @('done-1.mp3', 'done-2.mp3')) }
    'error' { Speak 'sad.mp3' }
  }
  if ($next -eq 'done' -and $script:armed) { Start-Countdown }
  if ($next -eq 'running') { Stop-Countdown }
}

function Poll-State {
  if (-not (Test-Path $StatePath)) { return }
  try {
    $raw = Get-Content -LiteralPath $StatePath -Raw -ErrorAction Stop
    if (-not $raw) { return }
    $state = $raw | ConvertFrom-Json
    if ($state.phase) { Set-Phase $state.phase }
  } catch { }
}

# 位置：优先上次的位置，否则右下角
$config = Read-Config
$area = [System.Windows.SystemParameters]::WorkArea
if ($config -ne $null -and $config.left -ne $null -and $config.top -ne $null) {
  $window.Left = [double]$config.left
  $window.Top = [double]$config.top
} else {
  $window.Left = $area.Right - 240
  $window.Top = $area.Bottom - 320
}
# 武装状态不跨进程恢复：每次启动都从“未武装”开始，避免几天前武装的实例误触发关机
Update-ArmButton

$still.Add_MouseLeftButtonDown({ try { $window.DragMove() } catch { } })
$window.Add_MouseLeftButtonUp({ Save-Config })
$closeButton.Add_Click({ $window.Close() })
$armButton.Add_Click({
  $script:armed = -not $script:armed
  if (-not $script:armed) { Stop-Countdown }
  Update-ArmButton
  Save-Config
})
$countdown.Add_MouseLeftButtonDown({
  Stop-Countdown
  & shutdown.exe /a | Out-Null
})

$poll = New-Object System.Windows.Threading.DispatcherTimer
$poll.Interval = [TimeSpan]::FromMilliseconds(400)
$poll.Add_Tick({ Poll-State })
$poll.Start()

# 每 10 分钟若无事发生，随机嘟囔一句
$chatter = New-Object System.Windows.Threading.DispatcherTimer
$chatter.Interval = [TimeSpan]::FromMinutes(10)
$chatter.Add_Tick({
  if ($script:phase -eq 'idle' -or $script:phase -eq 'running') {
    Speak (Pick-Voice @('chat-1.mp3', 'chat-2.mp3'))
  }
})
$chatter.Start()

$window.Add_Closed({
  Stop-Countdown
  $poll.Stop()
  $chatter.Stop()
  try { $script:player.Close() } catch { }
  try { $mutex.ReleaseMutex() } catch { }
})

$window.ShowDialog() | Out-Null
