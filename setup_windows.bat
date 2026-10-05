@echo off
REM HANDSYNC first-time setup: creates .venv, installs packages, downloads the hand model.
cd /d "%~dp0"
echo.
echo === HANDSYNC setup ===
set PYCMD=
py -3.12 --version >nul 2>nul && set PYCMD=py -3.12
if "%PYCMD%"=="" (
    python --version 2>nul | findstr /B /C:"Python 3.12" >nul && set PYCMD=python
)
if "%PYCMD%"=="" (
    echo.
    echo [ERROR] Python 3.12 was not found.
    echo Install Python 3.12 64-bit from https://www.python.org/downloads/windows/
    echo and tick "Add python.exe to PATH", then run this file again.
    pause
    exit /b 1
)
echo Using: %PYCMD%
if not exist ".venv\Scripts\python.exe" (
    %PYCMD% -m venv .venv || goto :fail
)
call ".venv\Scripts\python.exe" -m pip install --upgrade pip || goto :fail
call ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :fail
call ".venv\Scripts\python.exe" download_model.py
echo.
echo Setup finished. Start HANDSYNC with run_windows.bat
pause
exit /b 0
:fail
echo.
echo [ERROR] Setup failed. Read the messages above (internet connection? Python 3.12 64-bit?).
pause
exit /b 1
