# DSH 插件安装面板启动器
$ErrorActionPreference = 'Stop'
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $env:USERPROFILE '.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path $py)) { $py = 'python' }

$proc = Start-Process -FilePath $py -ArgumentList @("`"$dir\server.py`"") -WorkingDirectory $dir -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 2
Start-Process "http://127.0.0.1:8790/"
Write-Host "DSH 插件安装面板已启动（PID $($proc.Id)）：http://127.0.0.1:8790/"
Write-Host "关闭面板：停止该 python 进程即可。"
