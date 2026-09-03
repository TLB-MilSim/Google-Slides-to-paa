@echo off
rem One-time setup: installs the Python packages TLB Intel Maker needs.
rem Uses the same interpreter the launchers use, so the packages land in the right place.
cd /d "%~dp0"
where python >nul 2>&1 || (
  echo Python was not found on PATH. Install it from https://www.python.org/downloads/
  echo and tick "Add Python to PATH" during setup.
  pause
  exit /b 1
)
python -m pip install -r "%~dp0requirements.txt"
echo.
python -c "import pymupdf, PIL, requests; print('All dependencies OK')"
pause
