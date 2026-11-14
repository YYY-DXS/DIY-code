@echo off
title Codex Chinese UI - Install
echo ==========================================================
echo   Codex Desktop   Chinese UI  (one click)
echo ==========================================================
echo.
echo   STEP 1: FULLY QUIT Codex first (tray icon - right click - Exit)
echo   STEP 2: come back here and press any key
echo   STEP 3: click "Yes" on the UAC prompt
echo.
pause
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0codex-zh-cn.ps1" -Pause %*
echo.
echo   Script finished. If a window flashed and vanished, check:
echo   %~dp0..\out\codex-i18n\boot.log
echo.
pause
exit /b
