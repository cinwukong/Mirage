; Mirage installer (Inno Setup 6). Built by installer\build.ps1, which passes MyAppVersion, SourceDir and OutDir.
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\build\Mirage"
#endif
#ifndef OutDir
  #define OutDir "out"
#endif

[Setup]
AppId={{6C3F2E8B-9A41-4F7D-8E2B-5D1A7C9E4B30}
AppName=Mirage
AppVersion={#MyAppVersion}
AppVerName=Mirage {#MyAppVersion}
AppPublisher=Mirage
AppPublisherURL=https://github.com/cinwukong/Mirage
AppSupportURL=https://github.com/cinwukong/Mirage/issues
AppUpdatesURL=https://github.com/cinwukong/Mirage/releases
DefaultDirName={localappdata}\Programs\Mirage
DisableDirPage=auto
DisableProgramGroupPage=yes
DisableWelcomePage=no
PrivilegesRequired=lowest
OutputDir={#OutDir}
OutputBaseFilename=Mirage-Setup-{#MyAppVersion}
SetupIconFile={#SourceDir}\app\assets\mirage.ico
UninstallDisplayIcon={app}\Mirage.exe
UninstallDisplayName=Mirage
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
CloseApplications=force
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
WelcomeLabel2=This installs Mirage, a voice assistant for Windows that runs on your PC.%n%nAfter installing, Mirage walks you through setting up your microphone, its voice and its brain.

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked
Name: "startup"; Description: "Start Mirage when I log in to Windows"; GroupDescription: "Startup:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Mirage"; Filename: "{app}\Mirage.exe"; AppUserModelID: "Mirage.Assistant"
Name: "{autodesktop}\Mirage"; Filename: "{app}\Mirage.exe"; Tasks: desktopicon; AppUserModelID: "Mirage.Assistant"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Mirage"; ValueData: """{app}\Mirage.exe"" --tray"; Tasks: startup; Flags: uninsdeletevalue

[Run]
Filename: "{app}\Mirage.exe"; Description: "Start Mirage now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM Mirage.exe"; Flags: runhidden; RunOnceId: "StopMirage"

[UninstallDelete]
; Mirage updates itself and installs extras into its own folder, so remove all of it
Type: filesandordirs; Name: "{app}"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Data: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    Data := ExpandConstant('{localappdata}\Mirage');
    if DirExists(Data) and (MsgBox('Also delete your Mirage settings, what it remembers about you, your to-dos, chat history, and the downloaded voice and brain?' + #13#10 + #13#10 +
        Data + #13#10 + #13#10 + 'Notes older versions wrote to Documents\Mirage are kept either way.',
        mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES) then
      DelTree(Data, True, True, True);
  end;
end;
