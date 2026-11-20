@echo off
rem 启动鲸鱼娘桌面挂件（无窗口控制台；单实例，重复启动会直接退出）
setlocal
set "STATE=%TEMP%\dsh-whale-pet\state.json"
powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0widget\widget.ps1" -StatePath "%STATE%" -AssetsDir "%~dp0assets"
