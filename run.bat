@echo off
rem Double-click this file to open Steam Stats Tracker.
rem
rem The first run makes a private Python environment in the .venv folder and
rem installs what the app needs. After that it only opens the window, unless
rem requirements.txt changed since: then it installs what's new first.

cd /d "%~dp0"

set "PYTHON=py"
where py >nul 2>nul || set "PYTHON=python"

if not exist ".venv\Scripts\python.exe" (
    echo Setting things up for the first run. This takes a minute...
    %PYTHON% -m venv .venv || goto :failed
)

rem .venv\.ready is a copy of the requirements.txt that was last installed.
fc /b requirements.txt ".venv\.ready" >nul 2>nul || (
    echo Installing what the app needs...
    ".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r requirements.txt || goto :failed
    copy /y requirements.txt ".venv\.ready" >nul
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
