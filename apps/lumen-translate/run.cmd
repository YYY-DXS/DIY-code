@echo off
rem Lumen Translate launcher.
rem ASCII-only comments on purpose: cmd.exe reads .cmd files with the OEM
rem code page, so non-ASCII comments here can be parsed as commands.
rem Uses the bundled Codex Python runtime; no dependencies to install.
setlocal
set "LUMEN_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%LUMEN_PY%" (
    set "LUMEN_PY=pythonw"
    where pythonw >nul 2>nul || set "LUMEN_PY=python"
)
start "" "%LUMEN_PY%" "%~dp0main.pyw"
endlocal
