@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PSEXE=powershell.exe"
if exist "%ProgramFiles%\PowerShell\7\pwsh.exe" set "PSEXE=%ProgramFiles%\PowerShell\7\pwsh.exe"

"%PSEXE%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0CreateShortcut.ps1" %*

echo.
pause >nul
