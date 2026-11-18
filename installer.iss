; Inno Setup 6 Script for Arch MCP
; Compiles Arch into a standalone Windows installer (dist\ArchSetup.exe)

#define MyAppName "Arch MCP"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "Arch Indexer"
#define MyAppExeName "arch.exe"

[Setup]
AppId={{D37F8E42-6B7C-4C93-8E5E-91B1F2742A9B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\Arch
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=ArchSetup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
ChangesEnvironment=yes
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "addtopath"; Description: "Add Arch to system PATH (enables 'arch' in terminal)"; GroupDescription: "Terminal Configuration:"; Flags: checkedonce
Name: "registerantigravity"; Description: "Register Arch MCP in Antigravity (mcp_config.json)"; GroupDescription: "IDE Integration:"; Flags: checkedonce

[Files]
Source: "dist\arch.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "scripts\register_mcp.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Run]
Filename: "powershell.exe"; \
    Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\register_mcp.ps1"" -Install -AppPath ""{app}\{#MyAppExeName}"""; \
    StatusMsg: "Registering Arch MCP in Antigravity configuration..."; \
    Flags: runhidden; \
    Tasks: registerantigravity

[UninstallRun]
Filename: "powershell.exe"; \
    Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\register_mcp.ps1"" -Uninstall"; \
    RunOnceId: "UnregisterArchMcp"; \
    Flags: runhidden

[Code]
const
  EnvironmentKey = 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment';

function NeedsAddPath(AppDir: string): Boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKEY_LOCAL_MACHINE, EnvironmentKey, 'Path', OrigPath) then
  begin
    Result := True;
    Exit;
  end;
  // Look for ;AppDir; in ;OrigPath;
  Result := Pos(';' + UpperCase(AppDir) + ';', ';' + UpperCase(OrigPath) + ';') = 0;
end;

procedure AddPath(AppDir: string);
var
  OrigPath: string;
begin
  if NeedsAddPath(AppDir) then
  begin
    if not RegQueryStringValue(HKEY_LOCAL_MACHINE, EnvironmentKey, 'Path', OrigPath) then
      OrigPath := '';

    if (Length(OrigPath) > 0) and (OrigPath[Length(OrigPath)] <> ';') then
      OrigPath := OrigPath + ';';

    OrigPath := OrigPath + AppDir;
    RegWriteStringValue(HKEY_LOCAL_MACHINE, EnvironmentKey, 'Path', OrigPath);
  end;
end;

procedure RemovePath(AppDir: string);
var
  OrigPath: string;
  P: Integer;
begin
  if RegQueryStringValue(HKEY_LOCAL_MACHINE, EnvironmentKey, 'Path', OrigPath) then
  begin
    P := Pos(';' + UpperCase(AppDir) + ';', ';' + UpperCase(OrigPath) + ';');
    if P > 0 then
    begin
      P := Pos(UpperCase(AppDir), UpperCase(OrigPath));
      if P > 0 then
      begin
        Delete(OrigPath, P, Length(AppDir));
        StringChangeEx(OrigPath, ';;', ';', True);
        if (Length(OrigPath) > 0) and (OrigPath[1] = ';') then
          Delete(OrigPath, 1, 1);
        if (Length(OrigPath) > 0) and (OrigPath[Length(OrigPath)] = ';') then
          Delete(OrigPath, Length(OrigPath), 1);
        RegWriteStringValue(HKEY_LOCAL_MACHINE, EnvironmentKey, 'Path', OrigPath);
      end;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('addtopath') then
  begin
    AddPath(ExpandConstant('{app}'));
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    RemovePath(ExpandConstant('{app}'));
  end;
end;
