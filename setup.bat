@echo off
setlocal
title TLB Intel Maker setup
cd /d "%~dp0"

echo ============================================
echo   TLB Intel Maker setup
echo ============================================
echo.

set "SCRIPTARG="

rem A standalone build sitting next to this script needs no Python at all.
if exist "%~dp0TLB Intel Maker.exe" (
    echo Found TLB Intel Maker.exe - no Python needed.
    set "TARGET=%~dp0TLB Intel Maker.exe"
    set "ICON=%~dp0TLB Intel Maker.exe"
    goto shortcuts
)

echo No TLB Intel Maker.exe here, so setting up to run from source.
echo.

where python >nul 2>&1 || (
    echo   Python was not found on PATH.
    echo.
    echo   Either install Python 3 from https://www.python.org/downloads/
    echo   ^(tick "Add Python to PATH" during setup^), or download the
    echo   ready-made TLB Intel Maker.exe from the Releases page - it needs
    echo   no Python at all.
    echo.
    pause
    exit /b 1
)

echo Installing the required Python packages...
python -m pip install -q -r "%~dp0requirements.txt" || (
    echo.
    echo   Installing the packages failed. See the messages above.
    pause
    exit /b 1
)

python -c "import pymupdf, PIL, requests" 2>nul || (
    echo   The packages installed but could not be imported.
    pause
    exit /b 1
)
echo   packages OK.

rem pythonw runs the GUI without a console window behind it.
set "LAUNCHER=pythonw"
where pythonw >nul 2>&1 || set "LAUNCHER=python"
for /f "delims=" %%P in ('where %LAUNCHER%') do (
    set "TARGET=%%P"
    goto :got
)
:got
set "SCRIPTARG=-ScriptPath "%~dp0tlbintelmaker.py""
set "ICON=%~dp0assets\icon.ico"

:shortcuts
echo.
echo Creating shortcuts...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0packaging\make_shortcuts.ps1" -Target "%TARGET%" %SCRIPTARG% -WorkDir "%~dp0." -IconPath "%ICON%"

if errorlevel 1 (
    echo.
    echo   No shortcuts could be created, but TLB Intel Maker itself is ready.
    echo   Start it with TLB Intel Maker.bat in this folder.
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Done. Launch TLB Intel Maker from the Desktop
echo   or the Start Menu.
echo ============================================
echo.
pause
