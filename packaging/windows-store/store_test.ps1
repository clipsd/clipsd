# ClipSD: test of the Microsoft Store package (MSIX) on Windows, twice: A. a fresh install from the Store;
# B. an install over the settings of a Setup.exe copy. Install, selfcheck inside the package, start, second start,
# start at login untouched while the first-run card has no answer, quit, where the settings went, uninstall. Run by .github/workflows/windows.yml with Windows
# PowerShell 5.1 (its Appx module; this file has a BOM for it), as administrator: the test certificate goes into
# LocalMachine\TrustedPeople.
# Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко). SPDX-License-Identifier: GPL-3.0-or-later
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
#
#   -Package   ClipSD-<version>-x64-testsigned.msix (build_msix.ps1 -TestSign)
#   -Cert      ClipSD-test-signing.cer of the same build
#   -Manifest  AppxManifest.xml of the layout (identity name of the package)
#   -LogDir    selfcheck reports and the observed AppData behaviour
#   -KeepCert  leave the certificate trusted (the WACK step after this one installs the package again)
#
# Changes the current user's ClipSD settings: only for a disposable machine (CI runner, test VM).
param(
    [Parameter(Mandatory = $true)] [string]$Package,
    [Parameter(Mandatory = $true)] [string]$Cert,
    [Parameter(Mandatory = $true)] [string]$Manifest,
    [Parameter(Mandatory = $true)] [string]$LogDir,
    [switch]$KeepCert
)
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogDir = (Resolve-Path $LogDir).Path
$Package = (Resolve-Path $Package).Path

[xml]$M = Get-Content $Manifest -Encoding utf8
$Name = $M.Package.Identity.Name
$Alias = Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps\clipsd.exe"
$RealDir = Join-Path $env:APPDATA "ClipSD"
$RealConfig = Join-Path $RealDir "config.json"
$Summary = Join-Path $LogDir "store-test.txt"
$Warnings = @()

function Step([string]$Text) { Write-Host "==> $Text" -ForegroundColor Cyan; Add-Content $Summary "== $Text" -Encoding utf8 }
function Note([string]$Text) { Write-Host "    $Text"; Add-Content $Summary $Text -Encoding utf8 }
function Warn([string]$Text) { Write-Host "::warning title=MSIX::$Text"; Add-Content $Summary "WARNING: $Text" -Encoding utf8; $script:Warnings += $Text }
function Fail([string]$Text) { Add-Content $Summary "FAIL: $Text" -Encoding utf8; throw $Text }

function Wait-Until([scriptblock]$Condition, [int]$Seconds, [string]$What) {
    $end = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $end) {
        if (& $Condition) { return }
        Start-Sleep -Milliseconds 500
    }
    Fail "Не дождались за $Seconds с: $What"
}

function Invoke-Exe([string]$Exe, [string[]]$Arguments, [int]$TimeoutSeconds = 120) {
    # an app execution alias is a reparse point: Start-Process (ShellExecute) starts the packaged program
    if ($Arguments) { $p = Start-Process -FilePath $Exe -ArgumentList $Arguments -PassThru }
    else { $p = Start-Process -FilePath $Exe -PassThru }
    $null = $p.Handle
    if (-not $p.WaitForExit($TimeoutSeconds * 1000)) { Fail "$Exe $Arguments не завершился за $TimeoutSeconds с" }
    return $p.ExitCode
}

function Get-PackagedApp([string]$Root) {
    @(Get-Process -Name "ClipSD-app" -ErrorAction SilentlyContinue |
      Where-Object { $_.Path -and $_.Path.StartsWith($Root, [System.StringComparison]::OrdinalIgnoreCase) })
}

function Invoke-Selfcheck([string]$Report) {
    $code = Invoke-Exe $Alias @("--selfcheck", "`"$Report`"") 180
    if (-not (Test-Path $Report)) { Fail "selfcheck через clipsd.exe не записал отчёт (код $code)" }
    $lines = Get-Content $Report -Encoding utf8
    $lines | ForEach-Object { Note "    $_" }
    if ($code -ne 0) { Fail "selfcheck в пакете: код $code" }
    return $lines
}

Set-Content $Summary "ClipSD MSIX test $(Get-Date -Format s)" -Encoding utf8

Step "Сертификат тестовой подписи в LocalMachine\TrustedPeople"
$Imported = Import-Certificate -FilePath $Cert -CertStoreLocation "Cert:\LocalMachine\TrustedPeople"
Note "thumbprint $($Imported.Thumbprint), subject $($Imported.Subject)"

function Install-Package {
    Step "Add-AppxPackage $Package"
    try {
        Add-AppxPackage -Path $Package
    } catch {
        Note ($_ | Out-String)
        Note (Get-AppxLog -All -ErrorAction SilentlyContinue | Select-Object -Last 40 | Format-List | Out-String)
        Fail "Пакет не установился"
    }
    $p = Get-AppxPackage -Name $Name
    if (-not $p) { Fail "Get-AppxPackage -Name ${Name}: пакета нет после установки" }
    Note "PackageFullName $($p.PackageFullName)"
    Note "InstallLocation $($p.InstallLocation)"
    Wait-Until { Test-Path $Alias } 30 "появился $Alias (app execution alias)"
    return $p
}

function Get-StartupState([string]$Report) {
    $lines = Invoke-Selfcheck $Report
    return ($lines | Where-Object { $_ -like "startup task: *" })
}

# Start, a second start (goes to the running copy), quit. The first-run card ("Start ClipSD with Windows")
# stays unanswered: the start at login must stay off, also after the quit closed the card.
function Start-AndQuit($Pkg, [string]$Tag) {
    $root = $Pkg.InstallLocation
    Step "[$Tag] запуск ClipSD из пакета (как из меню «Пуск»)"
    $null = Start-Process -FilePath $Alias -PassThru
    Wait-Until { (Get-PackagedApp $root).Count -ge 1 } 60 "ClipSD-app.exe из пакета запустился"
    Start-Sleep -Seconds 10
    if ((Get-PackagedApp $root).Count -lt 1) { Fail "ClipSD-app.exe из пакета закрылся сразу после запуска" }
    Note "запущен: $((Get-PackagedApp $root)[0].Path)"
    Step "[$Tag] второй запуск: команда уходит в открытый ClipSD, второй копии нет"
    $null = Invoke-Exe $Alias $null 60
    Start-Sleep -Seconds 2
    if ((Get-PackagedApp $root).Count -ne 1) { Fail "второй запуск оставил $((Get-PackagedApp $root).Count) процессов ClipSD-app.exe" }
    Step "[$Tag] автозапуск, пока карточка первого запуска без ответа"
    $task = Get-StartupState (Join-Path $LogDir "selfcheck-$Tag-running.txt")
    if ($task -eq "startup task: enabled") { Fail "автозапуск включился без ответа на карточке (в манифесте Enabled=false)" }
    if ($task -ne "startup task: disabled") { Warn "[$Tag] ожидали 'startup task: disabled', получили '$task'" }
    Step "[$Tag] выход: clipsd --quit"
    $null = Invoke-Exe $Alias @("--quit") 60
    Wait-Until { (Get-PackagedApp $root).Count -eq 0 } 30 "ClipSD-app.exe закрылся по --quit"
    $task = Get-StartupState (Join-Path $LogDir "selfcheck-$Tag-after-quit.txt")
    if ($task -ne "startup task: disabled") {
        Warn "[$Tag] после выхода с открытой карточкой автозапуск '$task' (ожидали disabled: выход программы не ответ)"
    }
}

function Remove-Package($Pkg) {
    Step "Удаление пакета"
    Remove-AppxPackage -Package $Pkg.PackageFullName
    Wait-Until { -not (Get-AppxPackage -Name $Name) } 60 "пакет удалён"
    Start-Sleep -Seconds 3
    $private = Join-Path $env:LOCALAPPDATA "Packages\$($Pkg.PackageFamilyName)"
    Note "личная папка пакета после удаления: $(if (Test-Path $private) { 'осталась' } else { 'удалена' })"
    if (Test-Path $Alias) { Warn "после удаления осталось короткое имя $Alias" }
}

try {
    # --- A. A fresh install from the Store: no ClipSD from the website on this computer -----------------------
    Step "A. Чистая установка из Store (сборки с сайта на компьютере не было)"
    if (Test-Path $RealDir) { Fail "на чистой машине уже есть ${RealDir}: сценарий A не проверить" }
    $Pkg = Install-Package
    $Family = $Pkg.PackageFamilyName
    $PrivateConfig = Join-Path $env:LOCALAPPDATA "Packages\$Family\LocalCache\Roaming\ClipSD\config.json"

    Step "selfcheck внутри пакета"
    $lines = Invoke-Selfcheck (Join-Path $LogDir "selfcheck-packaged.txt")
    if (-not ($lines -contains "build: store")) { Fail "selfcheck в пакете: нет 'build: store'" }
    if (-not ($lines -contains "package: $($Pkg.PackageFullName)")) { Fail "selfcheck в пакете: нет 'package: $($Pkg.PackageFullName)'" }
    $task = $lines | Where-Object { $_ -like "startup task: *" }
    if (-not $task -or $task -eq "startup task: unavailable") { Warn "StartupTask недоступна в пакете: '$task'" }

    Start-AndQuit $Pkg "A"

    # The checkbox "Start ClipSD with Windows" (first-run card, settings) calls RequestEnableAsync / Disable
    # through ctypes: here the same code runs inside the real package, on and off again
    Step "A. Автозапуск: включить и выключить тем же кодом, что у галочки (WinRT StartupTask)"
    $report = Join-Path $LogDir "selfcheck-startup-toggle.txt"
    $code = Invoke-Exe $Alias @("--selfcheck-startup", "`"$report`"") 120
    if (-not (Test-Path $report)) { Fail "--selfcheck-startup не записал отчёт (код $code)" }
    $toggle = Get-Content $report -Encoding utf8
    $toggle | ForEach-Object { Note "    $_" }
    if ($toggle -match "FAILED") { Fail "включение автозапуска через WinRT упало (см. $report)" }
    if ($code -ne 0) { Warn "автозапуск не переключился как ожидали (код $code): см. $report" }
    Step "A. Где оказались настройки чистой Store-сборки"
    $realA = Test-Path $RealConfig
    $privateA = Test-Path $PrivateConfig
    Note "настоящая папка $RealConfig : $(if ($realA) { 'есть' } else { 'нет' })"
    Note "личная папка пакета $PrivateConfig : $(if ($privateA) { 'есть' } else { 'нет' })"
    if (-not $realA -and -not $privateA) { Fail "A: настройки Store-сборки не записались никуда" }
    if ($privateA) { Copy-Item $PrivateConfig (Join-Path $LogDir "config-A-private.json") }
    if ($realA) { Copy-Item $RealConfig (Join-Path $LogDir "config-A-real.json") }
    Remove-Package $Pkg
    Note "A. после удаления: настоящая папка $(if (Test-Path $RealConfig) { 'есть' } else { 'нет' }), личная $(if (Test-Path $PrivateConfig) { 'есть' } else { 'нет' })"

    # --- B. The Store build over the settings of a Setup.exe copy of ClipSD ----------------------------------
    Step "B. Установка из Store поверх настроек сборки с сайта"
    New-Item -ItemType Directory -Force -Path $RealDir | Out-Null
    # UTF-8 without BOM, as ClipSD writes it (Set-Content -Encoding utf8 of PowerShell 5.1 would add a BOM)
    [System.IO.File]::WriteAllText($RealConfig,
        '{"store_probe": "from-setup", "theme_chosen": true, "tour_done": true, "update_check": true}',
        (New-Object System.Text.UTF8Encoding($false)))
    $RealHash = (Get-FileHash $RealConfig).Hash
    $Pkg = Install-Package
    $PrivateConfig = Join-Path $env:LOCALAPPDATA "Packages\$($Pkg.PackageFamilyName)\LocalCache\Roaming\ClipSD\config.json"
    Start-AndQuit $Pkg "B"
    Step "B. Где оказались настройки"
    $realChanged = (Get-FileHash $RealConfig).Hash -ne $RealHash
    $privateB = Test-Path $PrivateConfig
    Note "настоящая папка $RealConfig : $(if ($realChanged) { 'ИЗМЕНЕНА (Store-сборка пишет прямо в неё)' } else { 'не изменилась' })"
    Note "личная папка пакета $PrivateConfig : $(if ($privateB) { 'есть' } else { 'нет' })"
    $Saved = if ($privateB) { $PrivateConfig } else { $RealConfig }
    Copy-Item $Saved (Join-Path $LogDir "config-B-after-quit.json")
    if ((Get-Content $Saved -Raw -Encoding utf8) -notmatch '"store_probe"\s*:\s*"from-setup"') {
        Fail "Store-сборка не подхватила настройки сборки с сайта ($Saved без store_probe)"
    }
    Note "настройки сборки с сайта подхвачены: да ($Saved)"
    Remove-Package $Pkg
    if (-not (Test-Path $RealConfig)) { Fail "удаление Store-сборки стёрло настройки сборки с сайта $RealConfig" }
    $after = Get-Content $RealConfig -Raw -Encoding utf8
    Note "B. после удаления настройки в настоящей папке: $(if ($after -match '"store_probe"') { 'на месте' } else { 'без store_probe' })"
} finally {
    Get-Process -Name "ClipSD-app" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    if (-not $KeepCert) {
        Remove-Item -Path "Cert:\LocalMachine\TrustedPeople\$($Imported.Thumbprint)" -ErrorAction SilentlyContinue
    }
}
Step "Готово: $(if ($Warnings) { "$($Warnings.Count) предупреждений" } else { 'без предупреждений' })"
exit 0
