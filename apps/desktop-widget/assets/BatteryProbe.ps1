$ErrorActionPreference = 'SilentlyContinue'
$result = @()
$devices = Get-PnpDevice -Class Bluetooth -Status OK -ErrorAction SilentlyContinue |
  Where-Object { $_.InstanceId -like 'BTHENUM\DEV_*' -or $_.InstanceId -like 'BTHLE\DEV_*' }
$audio = @($devices | Where-Object {
  $_.FriendlyName -match '耳机|Headphone|Headset|FreeBuds|Buds|Beats|AirPods|Speaker|音箱'
})
if ($audio.Count -eq 0) { $audio = @($devices | Select-Object -First 2) }
foreach ($device in $audio) {
  if (-not $device.FriendlyName) { continue }
  $result += @{ name = [string]$device.FriendlyName; percent = $null }
}
@{ battery = @($result) } | ConvertTo-Json -Compress -Depth 3
