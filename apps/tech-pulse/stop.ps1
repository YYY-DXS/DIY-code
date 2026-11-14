$listening = netstat -ano | Select-String ':4173\s+.*LISTENING'
if (-not $listening) {
  Write-Output "科技脉冲未在运行。"
  exit 0
}

$processIds = $listening | ForEach-Object {
  [int](($_.ToString() -split '\s+')[-1])
} | Select-Object -Unique
foreach ($processId in $processIds) {
  $process = Get-Process -Id $processId -ErrorAction Stop
  if ($process.ProcessName -ne "node") {
    throw "端口 4173 被非 Node 进程占用，为避免误停已取消操作。"
  }
  Stop-Process -Id $processId -ErrorAction Stop
}
Write-Output "科技脉冲已停止。"
