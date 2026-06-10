; Inno Setup installer script for Chloride Exide Pipeline App
; Run with: iscc installer.iss  (after pyinstaller pipeline_app.spec has been run)
; Output: dist/PipelineApp-Setup-1.0.0.exe

#define AppName    "Chloride Exide Pipeline App"
#define AppVersion "1.0.0"
#define AppPublisher "Chloride Exide KE"
#define AppExeName "PipelineApp.exe"

[Setup]
AppId={{B4E7F2A1-3C8D-4F5E-9A2B-1D6C7E8F0A3B}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\Chloride Exide\Pipeline App
DefaultGroupName=Chloride Exide
AllowNoIcons=yes
OutputDir=dist
OutputBaseFilename=PipelineApp-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
; Require Windows 10+ (Edge WebView2 is pre-installed on Win10/11)
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; The single-file exe built by PyInstaller
Source: "dist\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion

; pipeline.env — pre-configured with DATABASE_URL for this deployment
; IMPORTANT: Create this file before building the installer (it is NOT bundled in the exe)
Source: "pipeline.env.example"; DestDir: "{app}"; DestName: "pipeline.env"; Flags: onlyifdoesntexist

[Icons]
Name: "{group}\{#AppName}";       Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Remove log files on uninstall but preserve pipeline.env (user's credentials)
Type: filesandordirs; Name: "{app}\logs"
