@echo off
chcp 65001 >nul
title Install global AGENTS.md
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-global-context.ps1"
