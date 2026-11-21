param(
    [string]$OutFile = '',
    [switch]$Once
)

$ErrorActionPreference = 'SilentlyContinue'
if (-not $OutFile) { $OutFile = Join-Path $PSScriptRoot 'media-state.json' }
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}

Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and
  $_.GetParameters().Count -eq 1 -and
  $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]

function Await($op, $type) {
  if ($null -eq $op) { return $null }
  try {
    $task = $asTaskGeneric.MakeGenericMethod($type).Invoke($null, @($op))
    $task.Wait(-1) | Out-Null
    return $task.Result
  } catch {
    return $null
  }
}

$managerType = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows.Media.Control, ContentType = WindowsRuntime]
$propsType = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties, Windows.Media.Control, ContentType = WindowsRuntime]
$timelineType = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionTimelineProperties, Windows.Media.Control, ContentType = WindowsRuntime]

$manager = $null
try { $manager = Await ($managerType::RequestAsync()) $managerType } catch {}

function Get-BtBattery {
  $result = @()
  try {
    $devices = Get-PnpDevice -Class Bluetooth -Status OK -ErrorAction SilentlyContinue |
      Where-Object { $_.InstanceId -like 'BTHLE\*' }
    foreach ($device in $devices) {
      $value = $null
      foreach ($key in @(
        '{104EA319-6EE2-4701-BD47-8DDBF425BBE5} 2',
        'DEVPKEY_Bluetooth_Battery',
        'DEVPKEY_Device_BatteryLevel'
      )) {
        $prop = Get-PnpDeviceProperty -InstanceId $device.InstanceId -KeyName $key -ErrorAction SilentlyContinue
        if ($prop -and $null -ne $prop.Data) { $value = $prop.Data; break }
      }
      if ($null -eq $value) { continue }
      $percent = $null
      if ($value -is [byte[]] -and $value.Length -gt 0) {
        $percent = [int]$value[0]
      } elseif ($value -is [array] -and $value.Length -gt 0) {
        $percent = [int]$value[0]
      } else {
        $match = [regex]::Match([string]$value, '(\d{1,3})')
        if ($match.Success) { $percent = [int]$match.Groups[1].Value }
      }
      if ($null -ne $percent) {
        $result += @{ name = [string]$device.FriendlyName; percent = [Math]::Max(0, [Math]::Min(100, $percent)) }
      }
    }
  } catch {}
  return @($result)
}

$battery = @()
$lastBattery = [DateTimeOffset]::Now.ToUnixTimeSeconds()

while ($true) {
  $media = @{}
  if ($null -ne $manager) {
    $sessions = @($manager.GetSessions())
    if ($sessions.Count -gt 0) {
      $session = $sessions[0]
      $props = Await ($session.TryGetMediaPropertiesAsync()) $propsType
      $info = $session.GetPlaybackInfo()
      $title = ''
      $artist = ''
      $album = ''
      if ($props) {
        $title = [string]$props.Title
        $artist = [string]$props.Artist
        $album = [string]$props.AlbumTitle
      }
      $status = ''
      if ($info) { $status = [string]$info.PlaybackStatus }
      $position = 0.0
      $duration = 0.0
      try {
        $timeline = $session.GetTimelineProperties()
        if ($null -ne $timeline) {
          $position = [double]$timeline.Position.TotalSeconds
          $duration = [double]$timeline.EndTime.TotalSeconds
        }
      } catch {}
      $media = @{
        app = [string]$session.SourceAppUserModelId
        title = $title
        artist = $artist
        album = $album
        status = $status
        position = $position
        duration = $duration
      }
    }
  }
  $now = [DateTimeOffset]::Now.ToUnixTimeSeconds()
  if ($now - $lastBattery -ge 30) {
    $lastBattery = $now
    $battery = Get-BtBattery
  }
  $json = @{ media = $media; battery = $battery } | ConvertTo-Json -Compress -Depth 5
  try {
    $tmp = $OutFile + '.tmp'
    [IO.File]::WriteAllText($tmp, $json, (New-Object Text.UTF8Encoding($false)))
    Move-Item -LiteralPath $tmp -Destination $OutFile -Force
  } catch {}
  if ($Once) { break }
  Start-Sleep -Milliseconds 1000
}
