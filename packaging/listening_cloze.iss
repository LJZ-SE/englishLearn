#define AppName "Listening Cloze"
#define AppVersion GetEnv("PACKAGE_VERSION")
#define AppPublisher "ListeningCloze"
#define AppExeName "ListeningCloze.exe"

[Setup]
AppId={{A89A163B-E483-4A30-B04E-221084CB95B7}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\ListeningCloze
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SourceDir=..
OutputDir=packaging\output
OutputBaseFilename=ListeningClozeSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
Uninstallable=yes
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Files]
Source: "dist\ListeningCloze\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："; Flags: unchecked

[Run]
Filename: "{app}\{#AppExeName}"; Description: "启动 {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
var
  DeleteUserData: Boolean;

function InitializeUninstall(): Boolean;
var
  KeepUserData: Integer;
begin
  { 默认保留题目进度、设置与音频缓存，只有用户明确选择“否”时才删除。 }
  KeepUserData := MsgBox(
    '是否保留学习进度、设置和音频缓存？' + #13#10 +
    '选择“是”可在重新安装后继续使用；选择“否”将永久删除这些数据。',
    mbConfirmation,
    MB_YESNO
  );
  DeleteUserData := KeepUserData = IDNO;
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and DeleteUserData then
    DelTree(ExpandConstant('{localappdata}\ListeningCloze'), True, True, True);
end;
