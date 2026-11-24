@echo off
setlocal
title Memory Lab Launcher
cd /d "%~dp0"
if not exist "%~dp0data" mkdir "%~dp0data"
echo Starting Memory Lab...
echo URL: http://127.0.0.1:8010
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-background.ps1" -OpenBrowser > "%~dp0data\launcher.log" 2>&1
set "TASK_EXIT=%ERRORLEVEL%"
type "%~dp0data\launcher.log"
echo.
if not "%TASK_EXIT%"=="0" (
  echo Startup failed. The details are above and in data\launcher.log.
) else (
  echo READY: http://127.0.0.1:8010
  echo This window can be closed. The service will keep running.
)
echo.
pause
exit /b %TASK_EXIT%
