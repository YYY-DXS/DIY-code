@echo off
chcp 65001 >nul
setlocal
set "APP=%LOCALAPPDATA%\DSHPluginInstaller\app-pulse\DSH-Plugin-Pulse.exe"
if exist "%APP%" (
  start "" "%APP%"
  exit /b 0
)
if exist "%~dp0DSH-Plugin-Pulse.exe" (
  start "" "%~dp0DSH-Plugin-Pulse.exe"
  exit /b 0
)
if exist "%~dp0release\DSH-Plugin-Pulse\DSH-Plugin-Pulse.exe" (
  start "" "%~dp0release\DSH-Plugin-Pulse\DSH-Plugin-Pulse.exe"
  exit /b 0
)
echo 未找到 DSH-Plugin-Pulse.exe，尝试用 Python 源码启动...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-pulse.ps1"
pause
