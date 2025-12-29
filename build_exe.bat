@echo off
REM Build script for creating standalone executable
REM Requires: PyInstaller

setlocal enabledelayedexpansion

echo.
echo ================================================
echo  Build Flipper-Pineapple Manager Executable
echo ================================================
echo.

set "PY=py -3.13"

REM Check Python version
%PY% --version >nul 2>&1
if !ERRORLEVEL! neq 0 (
    echo ERROR: Python 3.13 not found. Please install Python.
    pause
    exit /b 1
)

echo Installing PyInstaller...
%PY% -m pip install -q PyInstaller

echo.
echo Building executable...
%PY% -m PyInstaller --onefile --windowed --name "Bad-Antics Device Manager" --icon=icon.ico --add-data "device_manager.py:." desktop_app.py

if !ERRORLEVEL! neq 0 (
    echo Build failed!
    pause
    exit /b 1
)

echo.
echo ================================================
echo  Build successful!
echo ================================================
echo.
echo Executable location: dist\Bad-Antics Device Manager.exe
echo.

pause
