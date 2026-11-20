@echo off
rem 把桌宠加入 Windows 开机启动（当前用户的 Startup 文件夹）
setlocal
set "LNK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\WhalePet.lnk"
set "TARGET=%~dp0启动鲸鱼娘桌宠.cmd"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('%LNK%'); $s.TargetPath = '%TARGET%'; $s.WorkingDirectory = '%~dp0'; $s.WindowStyle = 7; $s.Save(); Write-Host '已加入开机启动:' '%LNK%'"
if errorlevel 1 pause
