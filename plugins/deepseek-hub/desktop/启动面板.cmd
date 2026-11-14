@echo off
chcp 65001 >nul
start "" powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0HubPanel.ps1"
