# ClipSD: install, update, failure and uninstall test on Windows (run by .github/workflows/windows.yml, pwsh 7).
# Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко). SPDX-License-Identifier: GPL-3.0-or-later
#
#   -Setup      installer of the version under test
#   -SetupNext  installer of the same code with another version number (9.9.9), the "next release"
#   -LogDir     folder for installer logs and copies of launcher.log / update-result.json
#
# Changes the current user's installation of ClipSD: only for a disposable machine (CI runner, test VM).
param(
    [Parameter(Mandatory = $true)] [string]$Setup,
    [Parameter(Mandatory = $true)] [string]$SetupNext,
    [Parameter(Mandatory = $true)] [string]$LogDir
)
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogDir = (Resolve-Path $LogDir).Path

$Dir       = Join-Path $env:LOCALAPPDATA "Programs\ClipSD"
$Launcher  = Join-Path $Dir "ClipSD.exe"
$AppDir    = Join-Path $Dir "app"
$Staging   = Join-Path $Dir "staging"
$Previous  = Join-Path $Dir "previous"
$Failed    = Join-Path $Dir "failed"
$AppExe    = Join-Path $AppDir "ClipSD-app.exe"
$DataDir   = Join-Path $env:LOCALAPPDATA "ClipSD"
$Result    = Join-Path $DataDir "update-result.json"
$LaunchLog = Join-Path $DataDir "launcher.log"
$StartLnk  = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\ClipSD.lnk"
$AutoLnk   = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup\ClipSD.lnk"
$Aumid     = "SergeyDayneko.ClipSD"

function Step([string]$Text) { Write-Host "==> $Text" -ForegroundColor Cyan }

function Save-Logs {
    foreach ($f in $LaunchLog, $Result) {
        if (Test-Path $f) { Copy-Item $f $LogDir -Force }
    }
}

function Fail([string]$Text) {
    if (Test-Path $LaunchLog) { Write-Host "--- launcher.log"; Get-Content $LaunchLog -Tail 40 | Write-Host }
    if (Test-Path $Result) { Write-Host "--- update-result.json"; Get-Content $Result -Raw | Write-Host }
    Save-Logs
    throw $Text
}

function Wait-Until([scriptblock]$Condition, [int]$Seconds, [string]$What) {
    $end = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $end) {
        if (& $Condition) { return }
        Start-Sleep -Milliseconds 500
    }
    Fail "Не дождались за $Seconds с: $What"
}

# Start a process and wait for it alone (Start-Process -Wait would also wait for ClipSD started by it).
function Invoke-Exe([string]$Exe, [string[]]$Arguments, [int]$TimeoutSeconds = 180) {
    $p = Start-Process -FilePath $Exe -ArgumentList $Arguments -PassThru
    $null = $p.Handle   # keeps the handle so that ExitCode is available after exit
    if (-not $p.WaitForExit($TimeoutSeconds * 1000)) { Fail "$Exe не завершился за $TimeoutSeconds с" }
    return $p.ExitCode
}

function Install([string]$Exe, [string[]]$Arguments, [string]$LogName) {
    $log = Join-Path $LogDir $LogName
    $code = Invoke-Exe $Exe ($Arguments + "/LOG=`"$log`"")
    if ($code -ne 0) {
        if (Test-Path $log) { Get-Content $log -Tail 40 | Write-Host }
        Fail "Установщик $LogName завершился с кодом $code"
    }
}

# ClipSD-app.exe processes started from {app}\app
function Get-AppProcesses {
    @(Get-Process -Name "ClipSD-app" -ErrorAction SilentlyContinue |
      Where-Object { $_.Path -and $_.Path -like "*\Programs\ClipSD\app\ClipSD-app.exe" })
}

function Stop-App {
    Get-Process -Name "ClipSD-app" -ErrorAction SilentlyContinue | Stop-Process -Force
    Wait-Until { (Get-AppProcesses).Count -eq 0 } 20 "ClipSD-app.exe закрылся"
}

function Get-Version([string]$Exe) { (Get-Item $Exe).VersionInfo.ProductVersion }

function Read-Result {
    if (-not (Test-Path $Result)) { return $null }
    return Get-Content $Result -Raw | ConvertFrom-Json
}

function Assert-Result([string]$Expected, [string]$Reason) {
    $r = Read-Result
    if (-not $r) { Fail "Нет update-result.json (ожидали $Expected/$Reason)" }
    if ($r.result -ne $Expected -or $r.reason -ne $Reason) {
        Fail "update-result.json: $($r.result)/$($r.reason), ожидали $Expected/$Reason"
    }
    Write-Host "    update-result.json: $($r.result)/$($r.reason) $($r.from) -> $($r.to)"
}

function Get-UninstallEntries {
    @(Get-ChildItem "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall" |
      Where-Object { (Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue).DisplayName -like "ClipSD*" })
}

function Assert-Shortcut([string]$Lnk) {
    if (-not (Test-Path $Lnk)) { Fail "Нет ярлыка $Lnk" }
    $target = (New-Object -ComObject WScript.Shell).CreateShortcut($Lnk).TargetPath
    if ($target -notlike "*\Programs\ClipSD\ClipSD.exe") { Fail "Ярлык $Lnk ведёт на $target, а не на запускатель" }
    # AppUserModelID of the shortcut through the shell property system; the shell may be unavailable on a
    # service desktop, so a missing value is only a warning.
    try {
        $folder = (New-Object -ComObject Shell.Application).NameSpace((Split-Path $Lnk))
        $id = $folder.ParseName((Split-Path $Lnk -Leaf)).ExtendedProperty("System.AppUserModel.ID")
        if ($id -eq $Aumid) { Write-Host "    AppUserModelID ярлыка: $id" }
        else { Write-Warning "AppUserModelID ярлыка $Lnk = '$id', ожидали $Aumid" }
    } catch {
        Write-Warning "AppUserModelID ярлыка не прочитан: $($_.Exception.Message)"
    }
}

function Assert-Running([string]$Version) {
    Wait-Until { (Get-AppProcesses).Count -ge 1 } 30 "ClipSD-app.exe запустился"
    Start-Sleep -Seconds 5
    if ((Get-AppProcesses).Count -lt 1) { Fail "ClipSD-app.exe закрылся сразу после запуска" }
    $v = Get-Version $AppExe
    if ($Version -and $v -ne $Version) { Fail "Работает версия $v, ожидали $Version" }
    Write-Host "    работает ClipSD $v"
}

foreach ($f in $Setup, $SetupNext) { if (-not (Test-Path $f)) { Fail "Нет установщика $f" } }
$Silent = @("/SUPPRESSMSGBOXES", "/NORESTART")

# 1 ------------------------------------------------------------------------------------------------------
Step "1. Первая тихая установка: запускатель + app, ярлыки на запускатель, язык установщика для программы"
$CfgBefore = Test-Path (Join-Path $env:APPDATA "ClipSD\config.json")
Install $Setup (@("/VERYSILENT", "/LANG=de") + $Silent) "install1.log"
$LangFile = Join-Path $env:APPDATA "ClipSD\installer-language"
if (-not $CfgBefore) {
    if (-not (Test-Path $LangFile)) { Fail "Новая установка: нет $LangFile (язык установщика для программы)" }
    $got = (Get-Content -LiteralPath $LangFile -Raw).Trim()
    if ($got -ne "de") { Fail "installer-language: '$got', ожидали de (/LANG=de)" }
    Write-Host "    installer-language: $got"
} else { Write-Warning "config.json уже был до установки: installer-language не проверяется" }
foreach ($f in $Launcher, $AppExe, (Join-Path $Dir "LICENSE"), (Join-Path $Dir "LICENSE.ru.txt")) {
    if (-not (Test-Path $f)) { Fail "Не установлен $f" }
}
foreach ($d in $Staging, $Previous) { if (Test-Path $d) { Fail "После первой установки есть $d" } }
$V1 = Get-Version $AppExe
Assert-Shortcut $StartLnk
if (Test-Path $AutoLnk) { Assert-Shortcut $AutoLnk } else { Write-Warning "Нет ярлыка автозапуска (галочка по умолчанию включена)" }
Start-Process $Launcher | Out-Null
Assert-Running $V1
if ((Get-UninstallEntries).Count -ne 1) { Fail "Записей ClipSD в списке программ: $((Get-UninstallEntries).Count)" }

# 2 ------------------------------------------------------------------------------------------------------
Step "2. Тихая переустановка поверх работающей без /UPDATE: переключение, программа не запускается"
$old = Get-AppProcesses
Install $Setup (@("/VERYSILENT") + $Silent) "install2.log"
foreach ($p in $old) { if (-not $p.WaitForExit(10000)) { Fail "Прежняя копия ClipSD не закрылась" } }
Start-Sleep -Seconds 2
if ((Get-AppProcesses).Count -ne 0) { Fail "После тихой переустановки без /UPDATE ClipSD запущен" }
if (Test-Path $Staging) { Fail "staging остался после переключения" }
if (-not (Test-Path $AppExe)) { Fail "Нет app\ClipSD-app.exe после переключения" }
if (-not (Test-Path $Previous)) { Fail "Нет previous после переключения" }
Assert-Result "ok" "switched"
if ((Get-UninstallEntries).Count -ne 1) { Fail "Записей ClipSD в списке программ: $((Get-UninstallEntries).Count)" }

# 3 ------------------------------------------------------------------------------------------------------
Step "3. Обновление /SILENT /UPDATE=1 при работающей программе: работает новая версия"
Start-Process $Launcher | Out-Null
Assert-Running $V1
$old = Get-AppProcesses
$launcherHash = (Get-FileHash $Launcher).Hash
Remove-Item $Result -Force -ErrorAction SilentlyContinue
Install $SetupNext (@("/SILENT", "/UPDATE=1") + $Silent) "update.log"
foreach ($p in $old) { if (-not $p.WaitForExit(10000)) { Fail "Старая версия не закрылась" } }
Assert-Running "9.9.9"
Assert-Result "ok" "switched"
$r = Read-Result
if ($r.from -ne $V1 -or $r.to -ne "9.9.9") { Fail "update-result.json: from=$($r.from) to=$($r.to)" }
if (Test-Path $Staging) { Fail "staging остался после обновления" }
Write-Host "    previous: $(if (Test-Path $Previous) { 'есть (удалит новая версия через 60 с)' } else { 'удалён' })"
if ((Get-FileHash $Launcher).Hash -ne $launcherHash) { Fail "Запускатель заменён, хотя его версия не менялась" }
Assert-Shortcut $StartLnk
$entries = Get-UninstallEntries
if ($entries.Count -ne 1) { Fail "Записей ClipSD в списке программ: $($entries.Count), нужна одна" }
$shown = (Get-ItemProperty $entries[0].PSPath).DisplayVersion
if ($shown -ne "9.9.9") { Fail "В списке программ версия $shown, ожидали 9.9.9" }

# 4 ------------------------------------------------------------------------------------------------------
Step "4. Сбой: неполная копия в staging (нет .complete) -> остаётся рабочая версия"
$before = Get-AppProcesses | ForEach-Object Id
New-Item -ItemType Directory -Force -Path $Staging | Out-Null
Copy-Item $AppExe $Staging
Set-Content (Join-Path $Staging "broken.bin") "interrupted copy"
Remove-Item $Result -Force -ErrorAction SilentlyContinue
$code = Invoke-Exe $Launcher @("--switch") 120
if ($code -ne 1) { Fail "Запускатель вернул $code, ожидали 1 (не удалось)" }
Assert-Result "failed" "staging-incomplete"
if (Test-Path $Staging) { Fail "Неполная staging не удалена" }
if ((Get-Version $AppExe) -ne "9.9.9") { Fail "Рабочая версия изменилась" }
$after = Get-AppProcesses | ForEach-Object Id
if (((@($before) | Sort-Object) -join ",") -ne ((@($after) | Sort-Object) -join ",")) {
    Fail "Работающая программа была закрыта или перезапущена"
}

# 5 ------------------------------------------------------------------------------------------------------
Step "5. Сбой: папку app держит другой процесс -> 30 с повторов, остаётся рабочая версия, staging удалён"
Stop-App
Copy-Item $AppDir $Staging -Recurse
Set-Content (Join-Path $Staging ".complete") "test"
# A process whose working folder is app keeps the folder from being renamed (like Explorer or antivirus).
# One process without children, so that stopping it releases the folder.
$holder = Start-Process -FilePath (Join-Path $PSHOME "pwsh.exe") -ArgumentList "-NoProfile", "-Command", "Start-Sleep 120" `
          -WorkingDirectory $AppDir -WindowStyle Hidden -PassThru
try {
    Start-Sleep -Seconds 3
    Remove-Item $Result -Force -ErrorAction SilentlyContinue
    $code = Invoke-Exe $Launcher @("--switch", "--no-start") 120
} finally {
    Stop-Process -Id $holder.Id -Force -ErrorAction SilentlyContinue
    $holder.WaitForExit(10000) | Out-Null
}
if ($code -ne 1) { Fail "Запускатель вернул $code, ожидали 1 (не удалось)" }
Assert-Result "failed" "app-locked"
if (Test-Path $Staging) { Fail "staging не удалён после неудачного переключения" }
if ((Get-Version $AppExe) -ne "9.9.9") { Fail "Рабочая версия изменилась" }

# 6 ------------------------------------------------------------------------------------------------------
Step "6. Восстановление после выключения посреди переключения: нет app, есть previous"
Start-Sleep -Seconds 2
if (Test-Path $Previous) { Remove-Item $Previous -Recurse -Force }
Move-Item $AppDir $Previous
Remove-Item $Result -Force -ErrorAction SilentlyContinue
Start-Process $Launcher | Out-Null
Assert-Running "9.9.9"
if (Test-Path $Previous) { Fail "previous не вернулся на место app" }
Assert-Result "recovered" "restored-previous"

# 7 ------------------------------------------------------------------------------------------------------
Step "7. Готовая staging и программа не запущена: переключение при следующем запуске"
Stop-App
Copy-Item $AppDir $Staging -Recurse
Set-Content (Join-Path $Staging ".complete") "test"
Remove-Item $Result -Force -ErrorAction SilentlyContinue
Start-Process $Launcher | Out-Null
Assert-Running "9.9.9"
Assert-Result "ok" "switched-at-start"
if (Test-Path $Staging) { Fail "staging остался" }
if (Test-Path (Join-Path $AppDir ".complete")) { Fail "Отметка .complete осталась в app" }

# 8 ------------------------------------------------------------------------------------------------------
Step "8. Новая версия не запускается (нет отметки started-<версия>) -> откат на прежнюю"
# The previous step started 9.9.9 under the start check: wait for its mark, so it is the confirmed version.
Wait-Until { Test-Path (Join-Path $DataDir "started-9.9.9") } 90 "отметка started-9.9.9 от работающей версии"
Assert-Running "9.9.9"
$before = Get-AppProcesses
# A "new version" that exits at once and never writes the start mark: a copy of PING.EXE named ClipSD-app.exe
New-Item -ItemType Directory -Force -Path $Staging | Out-Null
Copy-Item (Join-Path $env:SystemRoot "System32\PING.EXE") (Join-Path $Staging "ClipSD-app.exe")
Set-Content (Join-Path $Staging ".complete") "test"
Remove-Item $Result -Force -ErrorAction SilentlyContinue
$code = Invoke-Exe $Launcher @("--switch") 240
foreach ($p in $before) { if (-not $p.WaitForExit(10000)) { Fail "Прежняя копия не закрылась по quit-for-update" } }
if ($code -ne 1) { Fail "Запускатель вернул $code, ожидали 1 (откат)" }
Assert-Result "failed" "not-started"
$r = Read-Result
if ($r.from -ne "9.9.9" -or $r.to -eq "9.9.9") { Fail "update-result.json: from=$($r.from) to=$($r.to)" }
Assert-Running "9.9.9"
foreach ($d in $Staging, $Failed, $Previous) { if (Test-Path $d) { Fail "После отката остался $d" } }

# 9 ------------------------------------------------------------------------------------------------------
Step "9. Удаление при работающей программе (/PURGE=1): нет app, previous, staging, ярлыков, записи, снимков ClipSD"
Save-Logs
$unins = Join-Path $Dir "unins000.exe"
if (-not (Test-Path $unins)) { Fail "Нет $unins" }
# /PURGE=1: ClipSD screenshots go from the autosave folder named in the settings of this version
# ({userappdata}\ClipSD\config.json, UTF-8, a Cyrillic folder name); other files in it stay.
# Written right before the uninstaller: the running program rewrites the file only on its own events.
$ShotDir = Join-Path $env:USERPROFILE "ClipSD-проверка\Снимки экрана"
New-Item -ItemType Directory -Force -Path $ShotDir | Out-Null
$MineShot = Join-Path $ShotDir "Screenshot_2026-01-02_03-04-05.png"
$ForeignShot = Join-Path $ShotDir "holiday.png"
foreach ($f in $MineShot, $ForeignShot) { [IO.File]::WriteAllText($f, "x") }
$UserCfg = Join-Path $env:APPDATA "ClipSD\config.json"
New-Item -ItemType Directory -Force -Path (Split-Path $UserCfg) | Out-Null
[IO.File]::WriteAllText($UserCfg, (@{ auto_save_dir = $ShotDir } | ConvertTo-Json -Compress), (New-Object Text.UTF8Encoding $false))
$null = Invoke-Exe $unins (@("/VERYSILENT", "/PURGE=1") + $Silent + "/LOG=`"$(Join-Path $LogDir 'uninstall.log')`"")
# The Inno uninstaller restarts itself from a temporary folder and returns at once
Wait-Until { -not (Test-Path $unins) } 90 "деинсталлятор закончил"
if (Test-Path -LiteralPath $MineShot) { Fail "/PURGE=1: снимок ClipSD в папке с кириллицей не удалён (config.json не прочитан как UTF-8?)" }
if (-not (Test-Path -LiteralPath $ForeignShot)) { Fail "/PURGE=1: удалён чужой файл $ForeignShot" }
if (Test-Path -LiteralPath (Split-Path $UserCfg)) { Fail "/PURGE=1: остались настройки $(Split-Path $UserCfg)" }
Remove-Item -LiteralPath (Split-Path $ShotDir) -Recurse -Force
Wait-Until { (Get-AppProcesses).Count -eq 0 } 20 "ClipSD-app.exe снят при удалении"
foreach ($d in $AppDir, $Previous, $Staging, $Launcher, $StartLnk, $AutoLnk, $Result, $LaunchLog) {
    if (Test-Path $d) { Fail "После удаления остался $d" }
}
if (Test-Path $Dir) {
    $left = @(Get-ChildItem $Dir -Recurse -Force)
    if ($left.Count) { Fail "После удаления в папке программы остались: $($left.FullName -join ', ')" }
}
if ((Get-UninstallEntries).Count -ne 0) { Fail "Запись ClipSD осталась в списке программ" }
Write-Host "Установка, обновление, сбои и удаление в порядке" -ForegroundColor Green
