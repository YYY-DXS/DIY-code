@echo off
chcp 65001 >nul
title Install daily task
setlocal
echo Installing a daily task that runs at 20:00...
schtasks /Create /TN "DIY-AutoPublish" /TR "\"%~dp0run-silent.cmd\"" /SC DAILY /ST 20:00 /F
if errorlevel 1 (
  echo.
  echo Failed. Try running this file as administrator.
) else (
  echo.
  echo Done. The task "DIY-AutoPublish" runs every day at 20:00.
  echo Run it manually anytime with:  schtasks /Run /TN "DIY-AutoPublish"
)
echo.
pause
