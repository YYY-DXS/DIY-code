@echo off
rem 取消桌宠的开机启动
setlocal
set "LNK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\WhalePet.lnk"
if exist "%LNK%" ( del "%LNK%" & echo 已取消开机启动 ) else ( echo 没有找到开机启动项 )
pause
