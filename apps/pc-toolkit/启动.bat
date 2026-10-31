@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PSEXE=powershell.exe"
if exist "%ProgramFiles%\PowerShell\7\pwsh.exe" set "PSEXE=%ProgramFiles%\PowerShell\7\pwsh.exe"
if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\pwsh.exe" set "PSEXE=%LOCALAPPDATA%\Microsoft\WindowsApps\pwsh.exe"

start "" "%PSEXE%" -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0PcToolkitGui.ps1"
exit /b 0
