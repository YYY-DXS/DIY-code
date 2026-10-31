@echo off
chcp 65001 >nul
rem 优先用 Codex 自带的 Python，没有就用系统里的 pythonw
set "PYW=C:\Users\sally\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe"
if exist "%PYW%" (
    start "" "%PYW%" "%~dp0widget.py"
    exit /b
)
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw "%~dp0widget.py"
    exit /b
)
echo 没有找到 Python，请先安装 Python 3.10 以上版本（安装时勾选 Add to PATH）
pause
