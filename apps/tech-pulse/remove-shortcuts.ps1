$ErrorActionPreference = "Stop"
$desktop = [Environment]::GetFolderPath("Desktop")
$startup = [Environment]::GetFolderPath("Startup")
$targets = @(
  (Join-Path $desktop "科技脉冲.lnk"),
  (Join-Path $startup "科技脉冲.lnk")
)

foreach ($target in $targets) {
  if (Test-Path $target) {
    Remove-Item -LiteralPath $target -Force
    Write-Output "已移除：$target"
  }
}
