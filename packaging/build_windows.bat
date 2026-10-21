@echo off
rem Builds the Windows app: dist\Fasway\Fasway.exe and dist\Fasway-windows.zip (share the zip).
rem Usage: double-click build_exe.bat in the project folder, or run packaging\build_windows.bat
setlocal
cd /d "%~dp0\.."

echo [1/4] Preparing Python environment...
if not exist .venv (
    python -m venv .venv || goto :nopython
)
.venv\Scripts\python -m pip install -q --disable-pip-version-check -r requirements.txt pyinstaller || goto :err

echo [2/4] Drawing app icon...
.venv\Scripts\python packaging\make_icon.py >nul || goto :err

echo [3/4] Packaging with PyInstaller (about a minute)...
if exist dist\Fasway rmdir /s /q dist\Fasway
.venv\Scripts\python -m PyInstaller --noconfirm --clean --windowed --log-level WARN ^
  --name Fasway ^
  --icon "%CD%\packaging\build\Fasway.ico" ^
  --add-data "%CD%\web;web" ^
  --collect-data soundcard ^
  --hidden-import pystray._win32 ^
  --collect-submodules zeroconf ^
  --paths "%CD%" ^
  --distpath dist --workpath packaging\build\pyi --specpath packaging\build ^
  packaging\fasway_app.py || goto :err

echo [4/4] Creating zip...
powershell -NoProfile -Command "Compress-Archive -Force -Path dist\Fasway -DestinationPath dist\Fasway-windows.zip" || goto :err

echo.
echo Done!
echo   App:  %CD%\dist\Fasway\Fasway.exe
echo   Zip:  %CD%\dist\Fasway-windows.zip   ^<-- share this; unzip and run Fasway.exe
if /i not "%CI%"=="true" explorer dist
exit /b 0

:nopython
echo.
echo Python 3.10+ was not found. Install it from https://www.python.org/downloads/ (tick "Add to PATH").
goto :fail
:err
echo.
echo Build failed - see the messages above.
:fail
if /i not "%CI%"=="true" pause
exit /b 1
