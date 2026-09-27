@echo off
chcp 65001 >nul
title Sync repository
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0同步仓库.ps1" %*
