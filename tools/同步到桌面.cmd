@echo off
chcp 65001 >nul
title Sync projects to Desktop
setlocal
set "REPO=%~dp0.."
set "DEST=%USERPROFILE%\Desktop\DIY项目"

if not exist "%DEST%" mkdir "%DEST%"

echo Copying project files to %DEST% ...
robocopy "%REPO%\projects" "%DEST%" /E /NFL /NDL /NJH /NJS /NP >nul
copy /Y "%REPO%\projects\README.md" "%DEST%\项目索引.md" >nul

echo.
echo Done.
echo (Existing files on the Desktop are kept, nothing is deleted.)
pause
