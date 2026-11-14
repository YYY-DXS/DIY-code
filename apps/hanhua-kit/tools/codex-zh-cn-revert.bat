@echo off
title Codex Chinese UI - Revert
echo ==========================================================
echo   Codex Desktop   Revert to English
echo ==========================================================
echo.
echo   FULLY QUIT Codex first (tray icon - right click - Exit),
echo   then press any key and click "Yes" on the UAC prompt.
echo.
pause
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0codex-zh-cn.ps1" -Revert -Pause %*
echo.
pause
exit /b
