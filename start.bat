@echo off
setlocal EnableDelayedExpansion

cd /d "%~dp0"

set "RESTART_COUNT=0"

:restart
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\start.ps1" -RestartCount %RESTART_COUNT%
set "EXIT_CODE=%ERRORLEVEL%"

if "%EXIT_CODE%"=="20" (
  set /a RESTART_COUNT+=1
  if !RESTART_COUNT! GEQ 2 (
    echo.
    echo The launcher updated but restart protection stopped another automatic restart.
    pause
    exit /b 1
  )
  echo.
  echo Update finished. Restarting launcher...
  goto restart
)

exit /b %EXIT_CODE%
