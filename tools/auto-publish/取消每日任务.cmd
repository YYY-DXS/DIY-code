@echo off
chcp 65001 >nul
title Remove daily task
schtasks /Delete /TN "DIY-AutoPublish" /F
echo.
pause
