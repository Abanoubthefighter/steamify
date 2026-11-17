@echo off
rem Builds a copy of the app that runs without Python installed.
rem
rem The result is the folder dist\SteamStatsTracker. Start it with the
rem SteamStatsTracker.exe inside, and zip the whole folder to share it.

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo There is no .venv folder yet. Run run.bat once first, then try again.
    pause
    exit /b 1
)

echo Installing the build tools...
".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r requirements-dev.txt || goto :failed

rem --windowed   no console window behind the app
rem --add-data   the folders Flask reads at run time: "where they are now;where they go in the build"
echo Building. This takes a minute or two...
".venv\Scripts\python.exe" -m PyInstaller desktop.py ^
    --name SteamStatsTracker ^
    --windowed ^
    --noconfirm ^
    --log-level WARN ^
    --icon static\img\icon.ico ^
    --add-data "templates;templates" ^
    --add-data "static;static" || goto :failed

echo.
echo Done. Start the app with dist\SteamStatsTracker\SteamStatsTracker.exe
pause
exit /b 0

:failed
echo.
echo The build did not finish. Scroll up to see what went wrong.
pause
exit /b 1
