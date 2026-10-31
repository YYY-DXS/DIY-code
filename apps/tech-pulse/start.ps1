$ErrorActionPreference = "Stop"
$appRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$port = if ($env:PORT) { $env:PORT } else { "4173" }
$url = "http://127.0.0.1:$port"

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
  throw "未找到 Node.js。请先安装 Node.js 20 或更高版本。"
}

$env:PORT = $port
New-Item -ItemType Directory -Path (Join-Path $appRoot "data") -Force | Out-Null
Start-Process `
  -WindowStyle Hidden `
  -FilePath "node.exe" `
  -ArgumentList "server.mjs" `
  -WorkingDirectory $appRoot `
  -RedirectStandardOutput (Join-Path $appRoot "data\server.log") `
  -RedirectStandardError (Join-Path $appRoot "data\server-error.log")
Start-Sleep -Milliseconds 800
Start-Process $url
