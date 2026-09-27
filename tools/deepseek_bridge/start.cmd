@echo off
chcp 65001 >nul
setlocal
set "PYTHONIOENCODING=utf-8"
set "BRIDGE_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%BRIDGE_PY%" set "BRIDGE_PY=python"
"%BRIDGE_PY%" "%~dp0server.py" %*
if errorlevel 1 pause
