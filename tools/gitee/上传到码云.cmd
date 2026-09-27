@echo off
chcp 65001 >nul
title Upload project to Gitee
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0upload-to-gitee.ps1"
