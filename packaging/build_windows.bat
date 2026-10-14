@echo off
rem Builds dist\Fasway\Fasway.exe (+ dist\Fasway-windows.zip) for sharing with Windows users.
cd /d "%~dp0\.."
if not exist .venv python -m venv .venv
.venv\Scripts\python -m pip install -q -r requirements.txt pyinstaller || goto :err
.venv\Scripts\python packaging\make_icon.py || goto :err
.venv\Scripts\python -m PyInstaller --noconfirm --clean --windowed ^
  --name Fasway ^
  --icon "%CD%\packaging\build\Fasway.ico" ^
  --add-data "%CD%\web;web" ^
  --paths "%CD%" ^
  --distpath dist --workpath packaging\build\pyi --specpath packaging\build ^
  packaging\fasway_app.py || goto :err
powershell -NoProfile -Command "Compress-Archive -Force -Path dist\Fasway -DestinationPath dist\Fasway-windows.zip"
echo Built dist\Fasway\Fasway.exe and dist\Fasway-windows.zip
goto :eof
:err
echo Build failed.
exit /b 1
