@echo off
setlocal
set "APP=%LOCALAPPDATA%\DSHPluginInstaller\app\DSH-Plugin-Installer.exe"
if exist "%APP%" (
  start "" "%APP%"
  exit /b 0
)
if exist "%~dp0DSH-Plugin-Installer.exe" (
  start "" "%~dp0DSH-Plugin-Installer.exe"
  exit /b 0
)
if exist "%~dp0release\DSH-Plugin-Installer\DSH-Plugin-Installer.exe" (
  start "" "%~dp0release\DSH-Plugin-Installer\DSH-Plugin-Installer.exe"
  exit /b 0
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
