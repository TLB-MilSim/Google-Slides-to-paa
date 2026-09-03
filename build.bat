@echo off
rem Builds the standalone executables into dist\ - maintainers only.
rem Users do not need this; they download the .exe from the Releases page.
setlocal
cd /d "%~dp0"

where python >nul 2>&1 || (echo Python not found on PATH. & pause & exit /b 1)

echo Installing build dependencies...
python -m pip install -q -r requirements.txt pyinstaller || (pause & exit /b 1)

rem requests, pymupdf and PIL are imported dynamically by require(), so
rem PyInstaller cannot see them - they are named explicitly below.
rem The excludes drop PyMuPDF's optional table-extraction stack, which is
rem unused here and roughly triples the size of the build.
set COMMON=--noconfirm --clean --onefile ^
 --icon "%~dp0assets\icon.ico" ^
 --add-data "%~dp0assets;assets" ^
 --paths "%~dp0." ^
 --workpath .build --distpath dist --specpath .build ^
 --hidden-import requests --hidden-import pymupdf --hidden-import PIL.Image ^
 --exclude-module scipy --exclude-module pandas --exclude-module numpy ^
 --exclude-module sqlalchemy --exclude-module cryptography ^
 --exclude-module matplotlib --exclude-module IPython --exclude-module pytest

echo.
echo Building IntelMaker.exe (GUI)...
python -m PyInstaller %COMMON% --windowed --name IntelMaker packaging\IntelMaker.py || (pause & exit /b 1)

echo.
echo Building intel.exe (command line)...
python -m PyInstaller %COMMON% --console --name intel packaging\intel.py || (pause & exit /b 1)

echo.
echo Done:
dir /b dist
pause
