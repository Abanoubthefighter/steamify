@echo off
rem Double-click this file to open Steam Stats Tracker.
rem
rem The first run makes a private Python environment in the .venv folder and
rem installs what the app needs. After that it only opens the window.

cd /d "%~dp0"

set "PYTHON=py"
where py >nul 2>nul || set "PYTHON=python"

if not exist ".venv\.ready" (
    echo Setting things up for the first run. This takes a minute...
    %PYTHON% -m venv .venv || goto :failed
    ".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r requirements.txt || goto :failed
    echo ok> ".venv\.ready"
)

rem pythonw runs the app without leaving a console window open behind it.
start "" ".venv\Scripts\pythonw.exe" desktop.py
exit /b 0

:failed
echo.
echo Setup did not finish. Is Python installed? You can get it from
echo https://www.python.org/downloads/ (tick "Add python.exe to PATH" in the installer).
pause
exit /b 1
