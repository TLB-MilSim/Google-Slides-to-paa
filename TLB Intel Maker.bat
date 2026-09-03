@echo off
rem Launches the TLB Intel Maker GUI without a console window.
cd /d "%~dp0"
where pythonw >nul 2>&1 && (start "" pythonw "%~dp0tlbintelmaker.py" --gui & exit /b)
where python  >nul 2>&1 && (start "" python  "%~dp0tlbintelmaker.py" --gui & exit /b)
echo Python was not found on PATH. Install it from https://www.python.org/downloads/
echo and tick "Add Python to PATH" during setup.
pause
