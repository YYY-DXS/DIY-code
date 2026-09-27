@echo off
chcp 65001 >nul
title Pull a GitHub repository
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0sync-repo.ps1"
