@echo off
chcp 65001 >nul
setlocal
set "PYTHONIOENCODING=utf-8"
set "AUTOPUB_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%AUTOPUB_PY%" set "AUTOPUB_PY=python"
"%AUTOPUB_PY%" "%~dp0auto_publish.py" --min-score 6 >> "%~dp0run.log" 2>&1
