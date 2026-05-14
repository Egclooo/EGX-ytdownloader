@echo off
setlocal

cd /d "%~dp0"

set "APP_NAME=YT Downloader"
set "VENV_PYTHON=.venv\Scripts\python.exe"
set "ICON_ARGS="

if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
)

"%VENV_PYTHON%" -m pip install --upgrade pip
"%VENV_PYTHON%" -m pip install -r requirements.txt pyinstaller

if exist "assets\app.ico" (
  set "ICON_ARGS=--icon assets\app.ico"
)

"%VENV_PYTHON%" -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --windowed ^
  --name "%APP_NAME%" ^
  --add-data "ui;ui" ^
  %ICON_ARGS% ^
  app.py

if errorlevel 1 (
  echo.
  echo Build failed.
  pause
  exit /b 1
)

echo.
echo Built: %CD%\dist\%APP_NAME%\%APP_NAME%.exe
echo Put assets\app.ico in place before running this file if you want a custom icon.
pause
