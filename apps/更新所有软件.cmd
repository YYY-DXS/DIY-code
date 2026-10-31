@echo off
chcp 65001 >nul
title Update all apps
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0check-update.ps1"
