$startup = [Environment]::GetFolderPath("Startup")
$shortcut = Join-Path $startup "科技脉冲.lnk"
if (Test-Path $shortcut) {
  Remove-Item -LiteralPath $shortcut -Force
  Write-Output "Startup shortcut removed."
} else {
  Write-Output "No Tech Pulse startup shortcut was found."
}
