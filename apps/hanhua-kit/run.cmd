@echo off
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
rem Hanhua Kit launcher: run the CLI from this folder without installing.
cd /d "%~dp0"
set "PY=%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -m hanhua %*
if "%~1"=="" pause
