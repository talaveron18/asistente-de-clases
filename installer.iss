#define MyAppName "ARGOS"
#define MyAppVersion "0.7.0"
#define MyAppPublisher "Fernando Talaverón"
#define MyAppExeName "ARGOS.exe"

[Setup]
AppId={{A6AC0A8D-FF23-4C5B-AAD0-5E2D6A4C7C11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\ARGOS
DefaultGroupName=ARGOS
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=release
OutputBaseFilename=ARGOS-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupLogging=yes

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"; Flags: checkedonce

[Files]
Source: "dist\ARGOS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\ARGOS"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\ARGOS"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir ARGOS"; Flags: nowait postinstall skipifsilent
