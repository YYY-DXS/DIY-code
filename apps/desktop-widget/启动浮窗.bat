@echo off
chcp 65001 >nul
rem 启动器会先确认 Python 与 Pillow，再拉起浮窗
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch-widget.ps1"
if errorlevel 1 (
    echo.
    pause
)
