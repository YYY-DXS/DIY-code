@echo off
chcp 65001 >nul
setlocal
set "PYTHONIOENCODING=utf-8"
set "BRIDGE_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%BRIDGE_PY%" set "BRIDGE_PY=python"

echo Stopping old service...
"%BRIDGE_PY%" "%~dp0stop.py"

timeout /t 2 /nobreak >nul

echo Starting new service...
start "" wscript.exe "%~dp0autostart.vbs"
timeout /t 3 /nobreak >nul

echo.
echo Done. You can close this window.
timeout /t 5 >nul
