; Inno Setup script for the NASS desktop application.
;
; Build the PyInstaller bundle first, then compile this file:
;
;   ISCC.exe packaging\installer.iss
;
; Output: installer_output\NASS_v<version>_Setup.exe

#define MyAppName "Nasimango Auto-Stocking System"
#define MyAppVersion "1.0.1"
#define MyAppPublisher "Nasimango"
#define MyAppExeName "NASS_v" + MyAppVersion + ".exe"

[Setup]
AppId={{D5A3BC6C-6A1C-4A54-9E49-1B7E8AB12345}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\NASS
DefaultGroupName=NASS
OutputDir=..\installer_output
OutputBaseFilename=NASS_v{#MyAppVersion}_Setup
Compression=lzma2
SolidCompression=no
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayIcon={app}\{#MyAppExeName}

[Files]
Source: "..\dist\NASS_v{#MyAppVersion}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\NASS"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\NASS"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch NASS"; Flags: nowait postinstall skipifsilent
