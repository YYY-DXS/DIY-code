# DSH 插件脉冲面板（原生 Tkinter 窗口）启动器
$ErrorActionPreference = 'Stop'
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$runtime = Join-Path $env:USERPROFILE '.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python'
$pythonw = Join-Path $runtime 'pythonw.exe'
$python = Join-Path $runtime 'python.exe'
if (-not (Test-Path $pythonw)) { $pythonw = 'pythonw' }
if (-not (Test-Path $python)) { $python = 'python' }

Start-Process -FilePath $pythonw -ArgumentList @("`"$dir\pulse_panel.py`"") -WorkingDirectory $dir
Write-Host "DSH 插件脉冲面板已启动（原生窗口）。"
