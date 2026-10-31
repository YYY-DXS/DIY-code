@echo off
chcp 65001 >nul
title PcToolkit - Console Version
cd /d "%~dp0"

set "PSEXE=powershell.exe"
if exist "%ProgramFiles%\PowerShell\7\pwsh.exe" set "PSEXE=%ProgramFiles%\PowerShell\7\pwsh.exe"
if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\pwsh.exe" set "PSEXE=%LOCALAPPDATA%\Microsoft\WindowsApps\pwsh.exe"

echo.
echo Starting PcToolkit console version...
echo.

"%PSEXE%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0PcToolkit.ps1" %*

if "%~1"=="" (
  echo.
  echo Tool exited. You can close this window.
  pause >nul
)
