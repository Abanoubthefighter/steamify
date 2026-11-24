@echo off
rem Builds the app so it runs on a PC without Python.
rem
rem   dist\Steamify-<version>-Setup.exe   the installer to share
rem   dist\Steamify\                      the app itself, used to make the installer
rem
rem The installer step needs Inno Setup 6 (free): https://jrsoftware.org/isinfo.php

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo There is no .venv folder yet. Run run.bat once first, then try again.
    pause
    exit /b 1
)

echo Installing the build tools...
".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r requirements-dev.txt || goto :failed

echo Building the app. This takes a minute or two...
".venv\Scripts\python.exe" -m PyInstaller packaging\Steamify.spec --noconfirm --log-level WARN --distpath dist --workpath build || goto :failed

rem PyInstaller leaves a half-finished copy of the .exe in build\. It can't
rem find Python from there ("Failed to load Python DLL"), so remove it before
rem anyone double-clicks it by mistake.
rmdir /s /q build

set "ISCC="
for %%p in ("%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe") do (
    if exist %%p set "ISCC=%%~p"
)
if not defined ISCC (
    echo.
    echo The app is in dist\Steamify. Install Inno Setup 6 to also get an installer.
    pause
    exit /b 0
)

echo Packing the installer...
del /q dist\Steamify-*-Setup.exe 2>nul
"%ISCC%" /Q packaging\installer.iss || goto :failed

echo.
for %%f in (dist\Steamify-*-Setup.exe) do echo Done. The installer is %%f
pause
exit /b 0

:failed
echo.
echo The build did not finish. Scroll up to see what went wrong.
pause
exit /b 1
