$taskName = "TechPulse-DailyBriefing"
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if (-not $task) {
  Write-Output "未找到自动启动任务，无需移除。"
  exit 0
}
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
Write-Output "已移除登录自动启动任务。当前已运行的服务不会自动停止。"
