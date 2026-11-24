; Inno Setup recipe: turns dist\Steamify into one Setup.exe.
; build_exe.bat runs it after PyInstaller is done; you don't need to run it by hand.
;
; The name and version are read from the built .exe, which got them from
; config.py, so config.py stays the only place they are written down.

; config.EXE_NAME: what PyInstaller called the .exe and its folder.
#define ExeName   "Steamify"
#define AppExe    ExeName + ".exe"
#define BuiltApp  SourcePath + "..\dist\" + ExeName + "\" + AppExe
#define AppName   GetFileDescription(BuiltApp)
#define AppVersion GetFileProductVersion(BuiltApp)
; config.APP_ID: the name of the app's "I'm already open" flag and of its data folder.
; It kept the old name on purpose when the app was renamed, so updates find the data.
#define AppKey "SteamStatsTracker"
; What the app was called before 1.4.0, so an update can tidy up after it.
#define OldExe  "SteamStatsTracker.exe"
#define OldName "Steam Stats Tracker"

[Setup]
; This ID is how Windows recognises the app across versions. Never change it,
; or a new version would install next to the old one instead of replacing it.
AppId={{A774707C-A3CE-45C1-A3F4-528A3DC5BFCB}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
VersionInfoVersion={#AppVersion}

; Install just for the current user, into %LOCALAPPDATA%\Programs. No admin
; password needed, same as apps like VS Code or Discord.
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#AppName}
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; WebView2, which draws the window, needs Windows 10 or newer.
MinVersion=10.0

; If the app is open, Setup and the uninstaller ask the user to close it first.
AppMutex={#AppKey}

WizardStyle=modern dynamic
SetupIconFile=..\static\img\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}

OutputDir=..\dist
OutputBaseFilename={#ExeName}-{#AppVersion}-Setup
Compression=lzma2/max
SolidCompression=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
; The app may be open with no window at all, hidden in the tray, so say where to find it.
SetupAppRunningError=%1 is still running, maybe hidden in the tray next to the clock.%n%nRight-click its icon there and choose Quit, then click OK to carry on (or Cancel to stop).
UninstallAppRunningError=%1 is still running, maybe hidden in the tray next to the clock.%n%nRight-click its icon there and choose Quit, then click OK to carry on (or Cancel to stop).

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; On an update, clear out the old program files first, so nothing from the
; previous version is left behind. Saved data lives elsewhere and isn't touched.
Type: filesandordirs; Name: "{app}\_internal"
; The .exe and shortcuts from before the rename, which the new ones replace.
Type: files; Name: "{app}\{#OldExe}"
Type: files; Name: "{autoprograms}\{#OldName}.lnk"
Type: files; Name: "{autodesktop}\{#OldName}.lnk"

[Files]
Source: "..\dist\{#ExeName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
const
  // Where "Start with Windows" (settings.exe, startup.py) puts the app, and
  // where Task Manager notes it was switched off there.
  RunKey = 'Software\Microsoft\Windows\CurrentVersion\Run';
  StartupApprovedKey = 'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run';

// When the app is removed: take it off the programs Windows starts at login
// (always, even in a silent uninstall), then ask about the saved data. The
// play history and the API key live in %LOCALAPPDATA%\SteamStatsTracker,
// outside the program folder, so updates keep them. Default answer: keep them.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep <> usPostUninstall then
    Exit;
  RegDeleteValue(HKEY_CURRENT_USER, RunKey, '{#AppKey}');
  RegDeleteValue(HKEY_CURRENT_USER, StartupApprovedKey, '{#AppKey}');
  DataDir := ExpandConstant('{localappdata}\{#AppKey}');
  if not DirExists(DataDir) or UninstallSilent() then
    Exit;
  if MsgBox('Also delete your saved data?' #13#13
      'That''s your play history, your Steam API key and your wallpaper pictures. Keep them if you might install the app again.',
      mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
    DelTree(DataDir, True, True, True);
end;
