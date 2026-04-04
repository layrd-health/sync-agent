; Inno Setup script for Layrd Sync Agent
; Requires Inno Setup 6.x (https://jrsoftware.org/isinfo.php)
; Build with: iscc installer.iss

#define MyAppName "Layrd Sync"
#define MyAppVersion "0.4.1"
#define MyAppPublisher "Layrd Health"
#define MyAppURL "https://thelayrd.com"
#define MyAppExeName "LayrdSync.exe"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=LayrdSyncSetup-{#MyAppVersion}
SetupIconFile=layrd_sync\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "autostart"; Description: "Start automatically when I log in"; GroupDescription: "Other:"

[InstallDelete]
; Clean old _internal folder to prevent stale dist-info metadata
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "dist\LayrdSync\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{#MyAppName} (Debug)"; Filename: "{app}\LayrdSyncDebug.exe"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; Auto-start on login (user-level, no admin needed)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "LayrdSync"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "taskkill"; Parameters: "/F /IM LayrdSync.exe"; Flags: runhidden; RunOnceId: "KillLayrdSync"

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\LayrdSync"
