param(
    [ValidateSet('playpause', 'next', 'previous')]
    [string]$Action = 'playpause'
)

$ErrorActionPreference = 'SilentlyContinue'
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
$boolType = [bool]
$manager = Await ($managerType::RequestAsync()) $managerType
$ok = $false
if ($manager) {
  $sessions = @($manager.GetSessions())
  if ($sessions.Count -gt 0) {
    $session = $sessions[0]
    switch ($Action) {
      'next' { $ok = [bool](Await ($session.TrySkipNextAsync()) $boolType) }
      'previous' { $ok = [bool](Await ($session.TrySkipPreviousAsync()) $boolType) }
      default { $ok = [bool](Await ($session.TryTogglePlayPauseAsync()) $boolType) }
    }
  }
}
@{ ok = $ok } | ConvertTo-Json -Compress
