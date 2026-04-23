#define MyAppName "Morgana Server"
#define MyAppVersion "0.2.4"
#define MyAppPublisher "X3M.AI Ltd"
#define MyAppURL "https://merlino.x3m.ai"
#define MyAppExeName "morgana-server.exe"

[Setup]
AppId={{A91A8797-9F22-4E30-8D4C-5B63E6B9AF8B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\Morgana Server
DefaultGroupName=Morgana Server
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
PrivilegesRequired=admin
WizardStyle=modern
WizardImageFile=assets\wizard.bmp
WizardSmallImageFile=assets\wizard-small.bmp
OutputDir=..\build\installer
OutputBaseFilename=Morgana-Server-Setup
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
Source: "..\build\dist\morgana-server.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\build\morgana-agent.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\tools\nssm.exe"; DestDir: "{app}\tools"; Flags: ignoreversion
Source: "..\scripts\post-install.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "assets\morgana-logo.fw.png"; DestDir: "{app}\assets"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Morgana Server\Open Dashboard"; Filename: "https://localhost:8888/ui/"
Name: "{autodesktop}\Morgana Dashboard"; Filename: "https://localhost:8888/ui/"; Tasks: desktopicon

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\post-install.ps1"" -AppDir ""{app}"" -DataDir ""{commonappdata}\Morgana"" -Port 8888 -ServiceName ""Morgana"""; Flags: runhidden waituntilterminated

[Code]
procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpFinished then
  begin
    WizardForm.FinishedLabel.Caption :=
      'Morgana is installed and running as a Windows service.' + #13#10 + #13#10 +
      '  URL:      https://localhost:8888/ui/' + #13#10 +
      '  Username: admin@admin.com' + #13#10 +
      '  Password: admin' + #13#10 +
      '  API key:  C:\ProgramData\Morgana\config\master-api-key.txt' + #13#10 + #13#10 +
      'NEXT STEP - Download Atomic Red Team scripts:' + #13#10 +
      '  1. Open https://localhost:8888/ui/' + #13#10 +
      '  2. Go to Scripts' + #13#10 +
      '  3. Click "Refresh Canary Scripts"' + #13#10 + #13#10 +
      'RECOMMENDED - Exclude Morgana from Windows Defender' + #13#10 +
      '  to prevent Red Team scripts from being quarantined:' + #13#10 +
      '  C:\ProgramData\Morgana\' + #13#10 +
      '  (Windows Security > Virus protection > Exclusions)';
  end;
end;
