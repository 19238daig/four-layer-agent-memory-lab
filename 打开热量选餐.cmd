@echo off
setlocal
title Meal SQL Lab Launcher
cd /d "%~dp0"
if not exist "%~dp0data" mkdir "%~dp0data"
echo Starting Meal SQL Lab...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-background.ps1" -OpenBrowser -View meal > "%~dp0data\meal-launcher.log" 2>&1
set "TASK_EXIT=%ERRORLEVEL%"
type "%~dp0data\meal-launcher.log"
echo.
if not "%TASK_EXIT%"=="0" (
  echo Startup failed. See data\meal-launcher.log.
) else (
  echo READY: http://127.0.0.1:8010/?view=meal
  echo This window can be closed. The service will keep running.
)
echo.
pause
exit /b %TASK_EXIT%
