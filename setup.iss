; ============================================================
; Inno Setup Script - SaSa Mirror
; ============================================================

#define MyAppName "SaSa Mirror"
#define MyAppVersion "1.0"
#define MyAppPublisher "SamimStreams"
#define MyAppURL "https://github.com/samim"
#define MyAppExeName "SaSa Mirror.exe"
#define MyIconFile "icon.ico"

[Setup]
; Unique application identifier (Generated GUID)
AppId={{C8E24D9F-7A8B-4C6E-9E1D-4F2A1E8B0C3D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; Default installation directory: Program Files\SaSa Mirror
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes

; Output settings
OutputDir=installer_output
OutputBaseFilename=SaSaMirror_Setup_v{#MyAppVersion}
SetupIconFile={#MyIconFile}

; Compression settings for small installer size
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern

; Support 64-bit architecture
ArchitecturesInstallIn64BitMode=x64compatible

; Privileges required to install into Program Files
PrivilegesRequired=admin

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Main executable
Source: "dist\SaSa Mirror\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

; Bundle all files including the _internal folder and dependencies
Source: "dist\SaSa Mirror\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Start Menu Shortcut
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyIconFile}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"

; Desktop Shortcut
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; IconFilename: "{app}\{#MyIconFile}"

[Run]
; Option to launch application immediately after install completes
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent