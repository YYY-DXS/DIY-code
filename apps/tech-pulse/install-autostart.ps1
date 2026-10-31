$ErrorActionPreference = "Stop"
$appRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$nodePath = (Get-Command node -ErrorAction Stop).Source
$taskName = "TechPulse-DailyBriefing"
$action = New-ScheduledTaskAction `
  -Execute $nodePath `
  -Argument "server.mjs" `
  -WorkingDirectory $appRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -ExecutionTimeLimit ([TimeSpan]::Zero) `
  -RestartCount 3 `
  -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask `
  -TaskName $taskName `
  -Action $action `
  -Trigger $trigger `
  -Settings $settings `
  -Description "科技脉冲：登录后启动本地日报服务" `
  -Force | Out-Null
Write-Output "已启用登录自动启动。任务名：$taskName"
Write-Output "日报服务地址：http://127.0.0.1:4173"
