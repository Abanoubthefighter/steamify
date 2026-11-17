@echo off
rem Builds a copy of the app that runs without Python installed.
rem
rem The result is the folder dist\SteamStatsTracker. The .exe inside only works
rem next to its _internal folder, so always move or zip the whole folder.

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo There is no .venv folder yet. Run run.bat once first, then try again.
    pause
    exit /b 1
)

echo Installing the build tools...
".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r requirements-dev.txt || goto :failed

echo Building. This takes a minute or two...
".venv\Scripts\python.exe" -m PyInstaller packaging\SteamStatsTracker.spec --noconfirm --log-level WARN --distpath dist --workpath build || goto :failed

rem PyInstaller leaves a half-finished copy of the .exe in build\. It can't
rem find Python from there ("Failed to load Python DLL"), so remove it before
rem anyone double-clicks it by mistake.
rmdir /s /q build

echo.
echo Done. Start the app with dist\SteamStatsTracker\SteamStatsTracker.exe
pause
exit /b 0

:failed
echo.
echo The build did not finish. Scroll up to see what went wrong.
pause
exit /b 1
