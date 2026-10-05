@echo off
chcp 65001 >nul
title Sync projects to Desktop
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0sync-to-desktop.ps1"
