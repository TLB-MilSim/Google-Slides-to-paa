@echo off
rem Command line use:  intel "<slides link>" "<output folder>" [options]
cd /d "%~dp0"
where python >nul 2>&1 || (
  echo Python was not found on PATH. Install it from https://www.python.org/downloads/
  exit /b 1
)
python "%~dp0tlbintelmaker.py" %*
