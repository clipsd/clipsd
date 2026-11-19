; ClipSD: installer for Windows 10/11 (Inno Setup 6). Copyright (C) 2026 Sergey Dayneko, GPL-3.0-or-later
; Built by packaging\build.ps1 inside the folder made by packaging/stage_windows.py:
;   dist\ClipSD-app\       the program (PyInstaller onedir, ClipSD-app.exe)
;   dist\launcher\ClipSD.exe  the permanent launcher (C, packaging\launcher\clipsd_launcher.c)
;
; Layout on disk (architecture.md 4.2, ADR-0008):
;   {app}\ClipSD.exe   launcher: shortcuts, pinned icon and autostart point here, the path never changes
;   {app}\app\         working version
;   {app}\staging\     a new version written by an update; complete when staging\.complete exists
;   {app}\previous\    the version before the last switch
; First install writes straight into {app}\app. Any later install writes into {app}\staging and runs
; "ClipSD.exe --switch": the running ClipSD is asked to quit, the folders are renamed, ClipSD starts again.
; The running ClipSD is never killed, except once when moving from 1.x (old layout, see PrepareToInstall).
;
; Command line: /UPDATE=1 (used by the program's updater together with /SILENT): switch to the new
; version and start it even in silent mode. Without /UPDATE the behaviour is the one of the wizard.

#define AppName "ClipSD"
#ifndef AppVersion
  #define AppVersion "1.31.1"
#endif
#define LauncherExe "ClipSD.exe"
#define ProgramExe "ClipSD-app.exe"
#define AppUserModelID "SergeyDayneko.ClipSD"

; "What's new" page from CHANGELOG/<version>/<language>.md, prepared by stage_windows.py as whatsnew\<language>.txt
#if FileExists(AddBackslash(SourcePath) + "..\whatsnew\en.txt")
  #define WhatsNew
#endif

[Setup]
AppId={{7C5B0E52-3F7A-4C1E-9D8B-C1A9D5E0B7A1}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Sergey Dayneko
AppCopyright=(C) 2026 Sergey Dayneko
; Current user only, no administrator rights: %LOCALAPPDATA%\Programs\ClipSD
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
; Language of the installer = language of Windows; the list dialog appears only when there is no match
LanguageDetectionMethod=uilanguage
ShowLanguageDialog=auto
; Autostart and desktop icon are NOT restored from the ticks of the previous install: over an existing
; install they are taken from the fact (is the shortcut there now), see WantAutostart / WantDesktop.
; The user may have switched autostart off in ClipSD's own settings, a silent update must not bring it back.
UsePreviousTasks=no
OutputDir=..\dist
OutputBaseFilename=ClipSD-{#AppVersion}-Setup
SetupIconFile=..\clipsd.ico
UninstallDisplayIcon={app}\{#LauncherExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; The running ClipSD keeps working while the new version is written into staging: nothing to close
CloseApplications=no
RestartApplications=no
VersionInfoVersion={#AppVersion}
VersionInfoDescription=ClipSD Setup

[Languages]
; 11 official translations of Inno Setup 6 + ChineseSimplified.isl from its unofficial set (languages\).
; Russian gets the Russian licence page (summary + official English text), the others the official GPL text.
#ifdef WhatsNew
Name: "en"; MessagesFile: "compiler:Default.isl"; LicenseFile: "..\LICENSE"; InfoBeforeFile: "..\whatsnew\en.txt"
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"; LicenseFile: "..\LICENSE.ru.txt"; InfoBeforeFile: "..\whatsnew\ru.txt"
Name: "bg"; MessagesFile: "compiler:Languages\Bulgarian.isl"; LicenseFile: "..\LICENSE"; InfoBeforeFile: "..\whatsnew\bg.txt"
Name: "uk"; MessagesFile: "compiler:Languages\Ukrainian.isl"; LicenseFile: "..\LICENSE"; InfoBeforeFile: "..\whatsnew\uk.txt"
Name: "de"; MessagesFile: "compiler:Languages\German.isl"; LicenseFile: "..\LICENSE"; InfoBeforeFile: "..\whatsnew\de.txt"
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"; LicenseFile: "..\LICENSE"; InfoBeforeFile: "..\whatsnew\fr.txt"
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"; LicenseFile: "..\LICENSE"; InfoBeforeFile: "..\whatsnew\es.txt"
Name: "it"; MessagesFile: "compiler:Languages\Italian.isl"; LicenseFile: "..\LICENSE"; InfoBeforeFile: "..\whatsnew\it.txt"
Name: "pt"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"; LicenseFile: "..\LICENSE"; InfoBeforeFile: "..\whatsnew\pt.txt"
Name: "pl"; MessagesFile: "compiler:Languages\Polish.isl"; LicenseFile: "..\LICENSE"; InfoBeforeFile: "..\whatsnew\pl.txt"
Name: "tr"; MessagesFile: "compiler:Languages\Turkish.isl"; LicenseFile: "..\LICENSE"; InfoBeforeFile: "..\whatsnew\tr.txt"
Name: "zh"; MessagesFile: "languages\ChineseSimplified.isl"; LicenseFile: "..\LICENSE"; InfoBeforeFile: "..\whatsnew\zh.txt"
#else
Name: "en"; MessagesFile: "compiler:Default.isl"; LicenseFile: "..\LICENSE"
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"; LicenseFile: "..\LICENSE.ru.txt"
Name: "bg"; MessagesFile: "compiler:Languages\Bulgarian.isl"; LicenseFile: "..\LICENSE"
Name: "uk"; MessagesFile: "compiler:Languages\Ukrainian.isl"; LicenseFile: "..\LICENSE"
Name: "de"; MessagesFile: "compiler:Languages\German.isl"; LicenseFile: "..\LICENSE"
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"; LicenseFile: "..\LICENSE"
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"; LicenseFile: "..\LICENSE"
Name: "it"; MessagesFile: "compiler:Languages\Italian.isl"; LicenseFile: "..\LICENSE"
Name: "pt"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"; LicenseFile: "..\LICENSE"
Name: "pl"; MessagesFile: "compiler:Languages\Polish.isl"; LicenseFile: "..\LICENSE"
Name: "tr"; MessagesFile: "compiler:Languages\Turkish.isl"; LicenseFile: "..\LICENSE"
Name: "zh"; MessagesFile: "languages\ChineseSimplified.isl"; LicenseFile: "..\LICENSE"
#endif

[CustomMessages]
en.TaskAutostart=Start ClipSD with Windows
en.TaskDesktop=Desktop icon
en.TaskGroup=Additional options:
en.IconComment=Screenshots with an editor (Alt+W)
en.UninstallName=Uninstall ClipSD
en.RunDemo=Launch ClipSD and show the feature tour
en.PurgeCheck=Also delete settings and logs (including ClipSD screenshots in the autosave folder)
en.PurgeTitle=ClipSD uninstallation
ru.TaskAutostart=Запускать ClipSD вместе с Windows
ru.TaskDesktop=Значок на рабочем столе
ru.TaskGroup=Дополнительно:
ru.IconComment=Снимки экрана с редактором (Alt+W)
ru.UninstallName=Удалить ClipSD
ru.RunDemo=Запустить ClipSD и показать знакомство с возможностями программы
ru.PurgeCheck=Удалить также настройки и журналы (и снимки ClipSD в папке автосохранения)
ru.PurgeTitle=Удаление ClipSD
bg.TaskAutostart=Стартиране на ClipSD заедно с Windows
bg.TaskDesktop=Икона на работния плот
bg.TaskGroup=Допълнително:
bg.IconComment=Снимки на екрана с редактор (Alt+W)
bg.UninstallName=Деинсталиране на ClipSD
bg.RunDemo=Стартиране на ClipSD и представяне на възможностите на програмата
bg.PurgeCheck=Изтрий също настройките и дневниците (и снимките на ClipSD в папката за автоматично запазване)
bg.PurgeTitle=Деинсталиране на ClipSD
uk.TaskAutostart=Запускати ClipSD разом з Windows
uk.TaskDesktop=Значок на робочому столі
uk.TaskGroup=Додатково:
uk.IconComment=Знімки екрана з редактором (Alt+W)
uk.UninstallName=Видалити ClipSD
uk.RunDemo=Запустити ClipSD і показати огляд можливостей програми
uk.PurgeCheck=Видалити також налаштування та журнали (і знімки ClipSD у папці автозбереження)
uk.PurgeTitle=Видалення ClipSD
de.TaskAutostart=ClipSD mit Windows starten
de.TaskDesktop=Desktopsymbol
de.TaskGroup=Zusätzlich:
de.IconComment=Screenshots mit Editor (Alt+W)
de.UninstallName=ClipSD deinstallieren
de.RunDemo=ClipSD starten und die Einführung in die Funktionen anzeigen
de.PurgeCheck=Auch Einstellungen und Protokolle löschen (und ClipSD-Screenshots im Ordner für automatisches Speichern)
de.PurgeTitle=Deinstallation von ClipSD
fr.TaskAutostart=Démarrer ClipSD avec Windows
fr.TaskDesktop=Icône sur le bureau
fr.TaskGroup=Options supplémentaires :
fr.IconComment=Captures d'écran avec éditeur (Alt+W)
fr.UninstallName=Désinstaller ClipSD
fr.RunDemo=Lancer ClipSD et afficher la visite guidée des fonctionnalités
fr.PurgeCheck=Supprimer aussi les paramètres et les journaux (et les captures ClipSD du dossier d'enregistrement automatique)
fr.PurgeTitle=Désinstallation de ClipSD
es.TaskAutostart=Iniciar ClipSD con Windows
es.TaskDesktop=Icono en el escritorio
es.TaskGroup=Opciones adicionales:
es.IconComment=Capturas de pantalla con editor (Alt+W)
es.UninstallName=Desinstalar ClipSD
es.RunDemo=Iniciar ClipSD y mostrar el recorrido
es.PurgeCheck=Eliminar también la configuración y los registros (y las capturas de ClipSD de la carpeta de guardado automático)
es.PurgeTitle=Desinstalación de ClipSD
it.TaskAutostart=Avvia ClipSD all'avvio di Windows
it.TaskDesktop=Icona sul desktop
it.TaskGroup=Opzioni aggiuntive:
it.IconComment=Screenshot con editor (Alt+W)
it.UninstallName=Disinstalla ClipSD
it.RunDemo=Avvia ClipSD e mostra la presentazione
it.PurgeCheck=Elimina anche impostazioni e registri (e gli screenshot di ClipSD nella cartella di salvataggio automatico)
it.PurgeTitle=Disinstallazione di ClipSD
pt.TaskAutostart=Iniciar o ClipSD com o Windows
pt.TaskDesktop=Ícone na área de trabalho
pt.TaskGroup=Opções adicionais:
pt.IconComment=Capturas de tela com editor (Alt+W)
pt.UninstallName=Desinstalar o ClipSD
pt.RunDemo=Iniciar o ClipSD e mostrar o tour
pt.PurgeCheck=Excluir também as configurações e os registros (e as capturas do ClipSD na pasta de salvamento automático)
pt.PurgeTitle=Desinstalação do ClipSD
pl.TaskAutostart=Uruchamiaj ClipSD razem z systemem Windows
pl.TaskDesktop=Ikona na pulpicie
pl.TaskGroup=Zadania dodatkowe:
pl.IconComment=Zrzuty ekranu z edytorem (Alt+W)
pl.UninstallName=Odinstaluj ClipSD
pl.RunDemo=Uruchom ClipSD i pokaż przewodnik
pl.PurgeCheck=Usuń także ustawienia i dzienniki (oraz zrzuty ClipSD w folderze autozapisu)
pl.PurgeTitle=Odinstalowanie ClipSD
tr.TaskAutostart=ClipSD'yi Windows ile başlat
tr.TaskDesktop=Masaüstü simgesi
tr.TaskGroup=Ek seçenekler:
tr.IconComment=Düzenleyicili ekran görüntüleri (Alt+W)
tr.UninstallName=ClipSD'yi kaldır
tr.RunDemo=ClipSD'yi başlat ve turu göster
tr.PurgeCheck=Ayarları ve günlükleri de sil (ve otomatik kayıt klasöründeki ClipSD ekran görüntülerini)
tr.PurgeTitle=ClipSD'yi kaldırma
zh.TaskAutostart=随 Windows 启动 ClipSD
zh.TaskDesktop=桌面图标
zh.TaskGroup=附加选项：
zh.IconComment=带编辑器的截图工具（Alt+W）
zh.UninstallName=卸载 ClipSD
zh.RunDemo=启动 ClipSD 并显示导览
zh.PurgeCheck=同时删除设置和日志（以及自动保存文件夹中 ClipSD 的截图）
zh.PurgeTitle=卸载 ClipSD

[Tasks]
Name: "autostart"; Description: "{cm:TaskAutostart}"; GroupDescription: "{cm:TaskGroup}"
Name: "desktopicon"; Description: "{cm:TaskDesktop}"; GroupDescription: "{cm:TaskGroup}"; Flags: unchecked

[Files]
; Launcher: no ignoreversion, so Inno replaces it only when its file version (launcher_version.h) is newer
Source: "..\dist\launcher\{#LauncherExe}"; DestDir: "{app}"
Source: "..\dist\ClipSD-app\*"; DestDir: "{app}\{code:PayloadDir}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE.ru.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD-PARTY-NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion
; preview (proba) installers only: the mark next to the program (stage_windows.py writes ..\PREVIEW)
#if FileExists(AddBackslash(SourcePath) + "..\PREVIEW")
Source: "..\PREVIEW"; DestDir: "{app}\{code:PayloadDir}"; Flags: ignoreversion
#endif
; README in Russian (README.txt) and English (README.en.txt) are both installed; the one shown at the end of
; the wizard follows the installer language: Russian for ru, English for the other 11 languages
Source: "..\README.txt"; DestDir: "{app}"; Flags: ignoreversion isreadme; Languages: ru
Source: "..\README.txt"; DestDir: "{app}"; Flags: ignoreversion; Languages: en bg uk de fr es it pt pl tr zh
Source: "..\README.en.txt"; DestDir: "{app}"; Flags: ignoreversion isreadme; Languages: en bg uk de fr es it pt pl tr zh
Source: "..\README.en.txt"; DestDir: "{app}"; Flags: ignoreversion; Languages: ru
; Must stay the LAST entry: files are copied in this order, and the launcher switches to staging only
; when this marker exists (a copy interrupted by a power loss has no marker and is never used)
Source: "staging-complete.txt"; DestDir: "{app}\staging"; DestName: ".complete"; Flags: ignoreversion; Check: IsStagingMode

[InstallDelete]
; A staging left by an interrupted update is never reused
Type: filesandordirs; Name: "{app}\staging"
Type: filesandordirs; Name: "{app}\failed"
; Leftovers of an interrupted first install
Type: filesandordirs; Name: "{app}\app"; Check: IsFreshMode
; Old install.bat installation (Python + venv in %LOCALAPPDATA%\ClipSD). The rest of that folder stays:
; the launcher keeps update-result.json and launcher.log there
Type: filesandordirs; Name: "{localappdata}\ClipSD\venv"; Check: IsLegacyScriptInstall
Type: filesandordirs; Name: "{localappdata}\ClipSD\app"; Check: IsLegacyScriptInstall

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#LauncherExe}"; Comment: "{cm:IconComment}"; AppUserModelID: "{#AppUserModelID}"
Name: "{autoprograms}\{cm:UninstallName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#LauncherExe}"; Comment: "{cm:IconComment}"; AppUserModelID: "{#AppUserModelID}"; Check: WantDesktop
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#LauncherExe}"; AppUserModelID: "{#AppUserModelID}"; Check: WantAutostart

[Run]
; /UPDATE=1 (from the program's updater): switch to the new version and start it, also in silent mode.
; Setup waits for the launcher, so its exit means the switch is over (the updater must not block on Setup).
Filename: "{app}\{#LauncherExe}"; Parameters: "{code:SwitchArg}"; Check: IsUpdateParam
; Silent install over an existing 2.x without /UPDATE: switch, do not start ClipSD (as before in silent mode)
Filename: "{app}\{#LauncherExe}"; Parameters: "--switch --no-start"; Check: IsSilentOverInstall
; Wizard: tick on the last page (on by default) starts ClipSD and shows the introduction.
; Without the tick ClipSD still starts, without the introduction (see CurStepChanged, ssDone).
Filename: "{app}\{#LauncherExe}"; Parameters: "{code:SwitchPrefix}--demo"; Description: "{cm:RunDemo}"; Flags: nowait postinstall skipifsilent; Check: not IsUpdateParam

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM {#LauncherExe}"; Flags: runhidden; RunOnceId: "StopClipSDLauncher"
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM {#ProgramExe}"; Flags: runhidden; RunOnceId: "StopClipSDApp"

[UninstallDelete]
; The autostart shortcut may also have been made by ClipSD itself (Settings -> autostart)
Type: files; Name: "{userstartup}\{#AppName}.lnk"
; After a switch the files live in other folders than the ones Inno wrote: remove all three
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\previous"
Type: filesandordirs; Name: "{app}\staging"
Type: files; Name: "{app}\{#LauncherExe}"
; Service files of the launcher. Logs, reports, telemetry, outbox, updates, update-*.json and started-* are removed
; in CurUninstallStepChanged; settings and screenshots only if the user ticks the box on the uninstall page.
Type: files; Name: "{localappdata}\ClipSD\update-result.json"
Type: files; Name: "{localappdata}\ClipSD\update-result.json.tmp"
Type: files; Name: "{localappdata}\ClipSD\launcher.log"
Type: dirifempty; Name: "{localappdata}\ClipSD"

[Code]
var
  PayloadMode: String;  { '' = not decided yet, 'app' = first install, 'staging' = update }
  HadPrevious: Boolean;       { an ClipSD uninstall entry existed when Setup started }
  AutostartBefore: Boolean;   { the Startup shortcut existed when Setup started (1.x removal may delete it later) }
  DesktopBefore: Boolean;
  TasksPreset: Boolean;
  PurgeUser: Boolean;         { uninstall: delete settings and screenshots too }

function AppPath(const Rel: String): String;
begin
  Result := ExpandConstant('{app}\' + Rel);
end;

// ClipSD 1.x: the PyInstaller program itself was ClipSD.exe in the program folder, with _internal next to it
function IsLegacyLayout(): Boolean;
begin
  Result := FileExists(AppPath('{#LauncherExe}')) and DirExists(AppPath('_internal'));
end;

{ The even older install.bat installation: Python venv in %LOCALAPPDATA%\ClipSD }
function IsLegacyScriptInstall(): Boolean;
begin
  Result := FileExists(ExpandConstant('{localappdata}\ClipSD\venv\Scripts\pythonw.exe'));
end;

// Where the program files go. Decided once, before the first file is copied, and cached:
// after the copy app\ClipSD-app.exe exists in both modes.
function PayloadDir(Param: String): String;
begin
  if PayloadMode = '' then
  begin
    if FileExists(AppPath('app\{#ProgramExe}')) then
      PayloadMode := 'staging'
    else
      PayloadMode := 'app';
  end;
  Result := PayloadMode;
end;

function IsStagingMode(): Boolean;
begin
  Result := PayloadDir('') = 'staging';
end;

function IsFreshMode(): Boolean;
begin
  Result := PayloadDir('') = 'app';
end;

function IsUpdateParam(): Boolean;
begin
  Result := ExpandConstant('{param:UPDATE|0}') = '1';
end;

function IsSilentOverInstall(): Boolean;
begin
  Result := WizardSilent() and not IsUpdateParam() and IsStagingMode();
end;

{ Launcher arguments for /UPDATE=1: switch when a new version sits in staging, otherwise just start }
function SwitchArg(Param: String): String;
begin
  if IsStagingMode() then
    Result := '--switch'
  else
    Result := '';
end;

function SwitchPrefix(Param: String): String;
begin
  if IsStagingMode() then
    Result := '--switch '
  else
    Result := '';
end;

{ Only for the move from 1.x: the old program has to be closed before its files are removed. }
procedure StopRunning();
var
  Code: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM {#LauncherExe}', '', SW_HIDE, ewWaitUntilTerminated, Code);
  { install.bat version runs as pythonw.exe from %LOCALAPPDATA%\ClipSD\venv }
  Exec('powershell.exe',
    '-NoProfile -ExecutionPolicy Bypass -Command "Get-Process pythonw,python -ErrorAction SilentlyContinue | ' +
    'Where-Object { $_.Path -like ($env:LOCALAPPDATA + ''\ClipSD\*'') } | Stop-Process -Force"',
    '', SW_HIDE, ewWaitUntilTerminated, Code);
  Sleep(500);
end;

function OldUninstaller(): String;
var
  Key: String;
begin
  { Uninstall entry of the installed ClipSD (same AppId) }
  Key := ExpandConstant('Software\Microsoft\Windows\CurrentVersion\Uninstall\{#emit SetupSetting("AppId")}_is1');
  Result := '';
  if not RegQueryStringValue(HKCU, Key, 'UninstallString', Result) then
    RegQueryStringValue(HKLM, Key, 'UninstallString', Result);
  Result := RemoveQuotes(Result);
end;

{ Only for the move from 1.x: remove 1.x completely with its own uninstaller so the two layouts never mix.
  User settings (~/.config/clipshot) are not touched. }
procedure RemoveOldVersion();
var
  Uninstaller, OldExe, OldDir: String;
  Code, i: Integer;
begin
  Uninstaller := OldUninstaller();
  if (Uninstaller = '') or not FileExists(Uninstaller) then
    Exit;
  OldDir := RemoveBackslash(ExtractFilePath(Uninstaller));
  OldExe := OldDir + '\{#LauncherExe}';
  Exec(Uninstaller, '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART', '', SW_HIDE, ewWaitUntilTerminated, Code);
  { The Inno uninstaller restarts itself from a temporary folder and returns at once: wait for it }
  for i := 1 to 60 do
  begin
    if not FileExists(Uninstaller) and not FileExists(OldExe) then
      Break;
    Sleep(500);
  end;
  { Leftovers go together with the folder, but only if it is the program folder named ClipSD }
  if (CompareText(ExtractFileName(OldDir), 'ClipSD') = 0) and DirExists(OldDir) then
    DelTree(OldDir, True, True, True);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  if IsLegacyLayout() then
  begin
    Log('ClipSD 1.x layout found: closing it and removing it once');
    StopRunning();
    RemoveOldVersion();
  end
  else if IsLegacyScriptInstall() then
    StopRunning();
  { Decide after a possible removal of 1.x }
  PayloadMode := '';
  Log('ClipSD program files go to the folder ' + PayloadDir(''));
  Result := '';
end;

{ Taking the state of the shortcuts BEFORE anything is changed: the removal of 1.x deletes the Startup shortcut }
function InitializeSetup(): Boolean;
begin
  HadPrevious := OldUninstaller() <> '';
  AutostartBefore := FileExists(ExpandConstant('{userstartup}\{#AppName}.lnk'));
  DesktopBefore := FileExists(ExpandConstant('{autodesktop}\{#AppName}.lnk'));
  Result := True;
end;

{ Over an existing install (and without an explicit /TASKS) the shortcut follows the fact, not the previous ticks }
function UseFact(): Boolean;
begin
  Result := HadPrevious and (ExpandConstant('{param:TASKS|}') = '');
end;

function WantAutostart(): Boolean;
begin
  if UseFact() and (WizardSilent() or IsUpdateParam()) then
    Result := AutostartBefore
  else
    Result := WizardIsTaskSelected('autostart');
end;

function WantDesktop(): Boolean;
begin
  if UseFact() and (WizardSilent() or IsUpdateParam()) then
    Result := DesktopBefore
  else
    Result := WizardIsTaskSelected('desktopicon');
end;

{ Wizard over an existing install: the boxes start as the shortcuts are now }
procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpSelectTasks) and UseFact() and not TasksPreset then
  begin
    TasksPreset := True;
    if AutostartBefore then WizardSelectTasks('autostart') else WizardSelectTasks('!autostart');
    if DesktopBefore then WizardSelectTasks('desktopicon') else WizardSelectTasks('!desktopicon');
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Code: Integer;
begin
  { Wizard without the autostart tick: remove a startup shortcut left by an earlier install. Silent installs
    (updates) follow the fact: the shortcut is recreated only if it existed before. }
  if (CurStep = ssPostInstall) and not WizardSilent() and not WantAutostart() then
    DeleteFile(ExpandConstant('{userstartup}\{#AppName}.lnk'));
  { New installation (no settings yet): the program starts in the language of this installer
    (clipshot/language.py, installer_choice). Over an existing install the settings already hold the language. }
  if (CurStep = ssPostInstall) and not FileExists(ExpandConstant('{userappdata}\ClipSD\config.json')) then
  begin
    ForceDirectories(ExpandConstant('{userappdata}\ClipSD'));
    SaveStringToFile(ExpandConstant('{userappdata}\ClipSD\installer-language'), ActiveLanguage(), False);
  end;
  { Introduction tick removed: still switch and start ClipSD in the tray }
  if (CurStep = ssDone) and not WizardSilent() and not IsUpdateParam() and (WizardForm.RunList.Items.Count > 0)
     and not WizardForm.RunList.Checked[0] then
    ExecAsOriginalUser(ExpandConstant('{app}\{#LauncherExe}'), SwitchArg(''), ExpandConstant('{app}'),
      SW_SHOWNORMAL, ewNoWait, Code);
end;

{ ---------------- uninstall ---------------- }

{ Question on the uninstall page; silent uninstall: /PURGE=1 deletes the user data, otherwise it stays }
function InitializeUninstall(): Boolean;
var
  F: TSetupForm;
  Box: TNewCheckBox;
  Ok, Cancel: TNewButton;
begin
  Result := True;
  PurgeUser := ExpandConstant('{param:PURGE|0}') = '1';
  if UninstallSilent() then
    Exit;
  F := CreateCustomForm(ScaleX(440), ScaleY(150), False, True);
  try
    F.Caption := ExpandConstant('{cm:PurgeTitle}');
    Box := TNewCheckBox.Create(F);
    Box.Parent := F;
    Box.Left := ScaleX(16);
    Box.Top := ScaleY(16);
    Box.Width := F.ClientWidth - ScaleX(32);
    Box.Height := ScaleY(48);
    Box.Checked := False;
    Box.Caption := ExpandConstant('{cm:PurgeCheck}');
    Ok := TNewButton.Create(F);
    Ok.Parent := F;
    Ok.Caption := SetupMessage(msgButtonOK);
    Ok.ModalResult := mrOk;
    Ok.Default := True;
    Ok.Width := ScaleX(90);
    Ok.Height := ScaleY(26);
    Ok.Left := F.ClientWidth - ScaleX(200);
    Ok.Top := F.ClientHeight - ScaleY(40);
    Cancel := TNewButton.Create(F);
    Cancel.Parent := F;
    Cancel.Caption := SetupMessage(msgButtonCancel);
    Cancel.ModalResult := mrCancel;
    Cancel.Cancel := True;
    Cancel.Width := ScaleX(90);
    Cancel.Height := ScaleY(26);
    Cancel.Left := F.ClientWidth - ScaleX(100);
    Cancel.Top := Ok.Top;
    F.Position := poScreenCenter;
    if F.ShowModal() = mrOk then
      PurgeUser := Box.Checked
    else
      Result := False;
  finally
    F.Free();
  end;
end;

{ Name made by ClipSD autosave: Screenshot_YYYY-MM-DD_HH-MM-SS[_N].png|jpg }
function IsClipSDShot(const Name: String): Boolean;
var
  i: Integer;
  Tail: String;
begin
  Result := False;
  if (Length(Name) < 34) or (Copy(Name, 1, 11) <> 'Screenshot_') then
    Exit;
  for i := 12 to 30 do
    case i of
      16, 19: if Name[i] <> '-' then Exit;
      22: if Name[i] <> '_' then Exit;
      25, 28: if Name[i] <> '-' then Exit;
    else
      if (Name[i] < '0') or (Name[i] > '9') then Exit;
    end;
  Tail := Copy(Name, 31, Length(Name));
  if (Length(Tail) > 4) and (Tail[1] = '_') then
  begin
    i := 2;
    while (i <= Length(Tail)) and (Tail[i] >= '0') and (Tail[i] <= '9') do
      i := i + 1;
    if i = 2 then Exit;
    Tail := Copy(Tail, i, Length(Tail));
  end;
  Result := (Tail = '.png') or (Tail = '.jpg');
end;

procedure DeleteShots(const Dir: String);
var
  R: TFindRec;
begin
  if FindFirst(Dir + '\*', R) then
  try
    repeat
      if ((R.Attributes and FILE_ATTRIBUTE_DIRECTORY) = 0) and IsClipSDShot(R.Name) then
        DeleteFile(Dir + '\' + R.Name);
    until not FindNext(R);
  finally
    FindClose(R);
  end;
  RemoveDir(Dir);   { only if it became empty }
end;

{ The string value of "Key" in a JSON text: the escapes \" \\ \/ are decoded; empty when the key is missing,
  the value is not a string or holds anything else escaped (\uXXXX, control characters: never in a folder
  ClipSD writes, so such a value is left alone rather than guessed). }
function JsonStringValue(const Text, Key: String): String;
var
  I: Integer;
  C: Char;
  Value: String;
begin
  Result := '';
  I := Pos('"' + Key + '"', Text);
  if I = 0 then Exit;
  I := I + Length(Key) + 2;
  while (I <= Length(Text)) and ((Text[I] = ' ') or (Text[I] = #9) or (Text[I] = #10) or (Text[I] = #13)) do
    I := I + 1;
  if (I > Length(Text)) or (Text[I] <> ':') then Exit;
  I := I + 1;
  while (I <= Length(Text)) and ((Text[I] = ' ') or (Text[I] = #9) or (Text[I] = #10) or (Text[I] = #13)) do
    I := I + 1;
  if (I > Length(Text)) or (Text[I] <> '"') then Exit;
  I := I + 1;
  Value := '';
  while I <= Length(Text) do
  begin
    C := Text[I];
    if C = '"' then
    begin
      Result := Value;
      Exit;
    end;
    if C = '\' then
    begin
      I := I + 1;
      if I > Length(Text) then Exit;
      C := Text[I];
      if (C <> '"') and (C <> '\') and (C <> '/') then Exit;
    end;
    Value := Value + C;
    I := I + 1;
  end;
end;

{ auto_save_dir from the settings file (UTF-8, as the program writes it: a folder name in Cyrillic and other
  scripts stays intact); empty if it cannot be read or is not deeper than one level in the profile }
function AutoSaveDir(const Cfg: String): String;
var
  Raw: AnsiString;
  Text, Home: String;
begin
  Result := '';
  if not FileExists(Cfg) or not LoadStringFromFile(Cfg, Raw) then Exit;
  Text := Utf8Decode(Raw);
  if (Length(Text) > 0) and (Text[1] = #$FEFF) then
    Delete(Text, 1, 1);
  Result := JsonStringValue(Text, 'auto_save_dir');
  StringChangeEx(Result, '/', '\', True);
  Home := GetEnv('USERPROFILE');
  if (Length(Result) > 0) and (Result[1] = '~') then
    Result := Home + Copy(Result, 2, Length(Result));
  if (Home = '') or (CompareText(Copy(Result, 1, Length(Home) + 1), Home + '\') <> 0) or
     (Pos('\', Copy(Result, Length(Home) + 2, Length(Result))) = 0) then
    Result := '';
end;

procedure DeleteMatching(const Dir, Mask: String);
var
  R: TFindRec;
begin
  if FindFirst(Dir + '\' + Mask, R) then
  try
    repeat
      if (R.Attributes and FILE_ATTRIBUTE_DIRECTORY) = 0 then
        DeleteFile(Dir + '\' + R.Name)
      else if (R.Name <> '.') and (R.Name <> '..') then
        DelTree(Dir + '\' + R.Name, True, True, True);
    until not FindNext(R);
  finally
    FindClose(R);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Data, Cfg, Dir, Home: String;
begin
  if CurUninstallStep <> usUninstall then
    Exit;
  Data := ExpandConstant('{localappdata}\ClipSD');
  { Always: what the program and the updater wrote while working }
  DelTree(Data + '\logs', True, True, True);
  DelTree(Data + '\reports', True, True, True);
  DelTree(Data + '\telemetry', True, True, True);
  DelTree(Data + '\outbox', True, True, True);
  DelTree(Data + '\updates', True, True, True);
  DeleteMatching(Data, 'update-*.json');
  DeleteMatching(Data, 'started-*');
  DeleteMatching(Data, 'critical-*');        { saved signed document of a pending security fix (+ .sig) }
  DelTree(Data + '\proba-channel', True, True, True);   { the preview channel folder (owner's tests) }
  DeleteFile(ExpandConstant('{userappdata}\ClipSD\installer-language'));   { written by this installer }
  // Only on request: settings and ClipSD screenshots. The folder comes from the settings of this version
  // (userappdata\ClipSD\config.json), from the 1.x file only when that one has none.
  if PurgeUser then
  begin
    Home := GetEnv('USERPROFILE');
    Dir := AutoSaveDir(ExpandConstant('{userappdata}\ClipSD\config.json'));
    if Dir = '' then
    begin
      Cfg := Home + '\.config\clipshot\config.json';
      Dir := AutoSaveDir(Cfg);
    end;
    if Dir <> '' then
      DeleteShots(Dir);
    DelTree(Home + '\.config\clipshot', True, True, True);
    DelTree(Home + '\.config\clipsd', True, True, True);
    DelTree(ExpandConstant('{userappdata}\ClipSD'), True, True, True);
  end;
end;
