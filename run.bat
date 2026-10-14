@echo off
cd /d "%~dp0"
if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv || goto :err
    .venv\Scripts\python -m pip install --upgrade pip >nul
)
rem quick no-op when everything is already installed; picks up new requirements after updates
.venv\Scripts\python -m pip install -q --disable-pip-version-check -r requirements.txt || goto :err
.venv\Scripts\python -m fasway
goto :eof

:err
echo.
echo Setup failed. Make sure Python 3.10+ is installed and on PATH.
pause
