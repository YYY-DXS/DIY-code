$ErrorActionPreference = "Stop"
$targetPath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "TechPulse.exe"))
$listening = netstat -ano | Select-String ':4173\s+.*LISTENING'
if (-not $listening) {
  Write-Output "Tech Pulse is not running."
  exit 0
}

$processIds = $listening | ForEach-Object {
  [int](($_.ToString() -split '\s+')[-1])
} | Select-Object -Unique

foreach ($processId in $processIds) {
  $process = Get-Process -Id $processId -ErrorAction Stop
  $actualPath = [IO.Path]::GetFullPath($process.Path)
  if (-not $actualPath.Equals($targetPath, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Port 4173 belongs to another program. No process was stopped."
  }
  Stop-Process -Id $processId -ErrorAction Stop
}
Write-Output "Tech Pulse has been stopped."
