# ClipSD: the preview ("проба") installer, then a real installer over it, then removal (windows.yml, proba/* branches).
# Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко). SPDX-License-Identifier: GPL-3.0-or-later
#
#   -SetupPreview  preview installer (packaging/preview_build.py copy): the installed program must say "build: preview"
#   -SetupRelease  an ordinary installer of a later version: installed over the preview, it must say "build: release"
#                  (the same AppId: the owner's preview install is replaced cleanly by the real one)
#   -LogDir        folder for installer logs and selfcheck reports
#
# Changes the current user's installation of ClipSD: only for a disposable machine (CI runner, test VM).
param(
    [Parameter(Mandatory = $true)] [string]$SetupPreview,
    [Parameter(Mandatory = $true)] [string]$SetupRelease,
    [Parameter(Mandatory = $true)] [string]$LogDir
)
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogDir = (Resolve-Path $LogDir).Path

$Dir     = Join-Path $env:LOCALAPPDATA "Programs\ClipSD"
$AppExe  = Join-Path $Dir "app\ClipSD-app.exe"
$DataDir = Join-Path $env:LOCALAPPDATA "ClipSD"
$Silent  = @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")

function Step([string]$Text) { Write-Host "==> $Text" -ForegroundColor Cyan }

function Invoke-Exe([string]$Exe, [string[]]$Arguments, [int]$TimeoutSeconds = 180) {
    $p = Start-Process -FilePath $Exe -ArgumentList $Arguments -PassThru
    $null = $p.Handle   # keeps the handle so that ExitCode is available after exit
    if (-not $p.WaitForExit($TimeoutSeconds * 1000)) { throw "$Exe не завершился за $TimeoutSeconds с" }
    return $p.ExitCode
}

function Stop-App {
    Get-Process -Name "ClipSD-app" -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 2
}

function Install([string]$Exe, [string]$LogName) {
    Stop-App
    $log = Join-Path $LogDir $LogName
    $code = Invoke-Exe $Exe ($Silent + "/LOG=`"$log`"")
    if ($code -ne 0) {
        if (Test-Path $log) { Get-Content $log -Tail 40 | Write-Host }
        throw "Установщик $LogName завершился с кодом $code"
    }
    Stop-App
}

function Get-BuildKind([string]$Name) {
    if (-not (Test-Path $AppExe)) { throw "Нет $AppExe" }
    $report = Join-Path $LogDir "selfcheck-$Name.txt"
    Remove-Item $report -ErrorAction SilentlyContinue
    $env:QT_QPA_PLATFORM = "offscreen"
    $code = Invoke-Exe $AppExe @("--selfcheck", "`"$report`"") 120
    if (Test-Path $report) { Get-Content $report -Encoding utf8 | Write-Host }
    if ($code -ne 0 -or -not (Test-Path $report)) { throw "selfcheck установленной программы не прошёл (код $code)" }
    $lines = @(Get-Content $report -Encoding utf8)
    if ($lines -contains "build: preview") { return "preview" }
    if ($lines -contains "build: release") { return "release" }
    return "unknown"
}

function Get-UninstallEntries {
    @(Get-ChildItem "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall" |
      Where-Object { (Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue).DisplayName -like "ClipSD*" })
}

foreach ($f in $SetupPreview, $SetupRelease) { if (-not (Test-Path $f)) { throw "Нет установщика $f" } }

Step "1. Пробный установщик: установленная программа пробная"
Install $SetupPreview "preview-install.log"
$kind = Get-BuildKind "preview"
if ($kind -ne "preview") { throw "После пробного установщика сборка: $kind, ожидали preview" }

Step "2. Настоящий установщик поверх пробного: та же запись в списке программ, программа обычная"
Install $SetupRelease "release-over-preview.log"
$kind = Get-BuildKind "release"
if ($kind -ne "release") { throw "После обычного установщика поверх пробного сборка: $kind, ожидали release" }
if ((Get-UninstallEntries).Count -ne 1) { throw "Записей ClipSD в списке программ: $((Get-UninstallEntries).Count)" }

Step "3. Удаление убирает сохранённое срочное исправление и папку канала proba"
New-Item -ItemType Directory -Force -Path (Join-Path $DataDir "proba-channel") | Out-Null
foreach ($f in "critical-stable.json", "critical-stable.json.sig", "proba-channel\latest.json") {
    [IO.File]::WriteAllText((Join-Path $DataDir $f), "x")
}
$unins = Join-Path $Dir "unins000.exe"
if (-not (Test-Path $unins)) { throw "Нет $unins" }
$null = Invoke-Exe $unins ($Silent + "/LOG=`"$(Join-Path $LogDir 'preview-uninstall.log')`"")
# The Inno uninstaller restarts itself from a temporary folder and returns at once
$end = (Get-Date).AddSeconds(90)
while ((Test-Path $unins) -and (Get-Date) -lt $end) { Start-Sleep -Milliseconds 500 }
if (Test-Path $unins) { throw "Деинсталлятор не закончил за 90 с" }
foreach ($f in "critical-stable.json", "critical-stable.json.sig", "proba-channel") {
    if (Test-Path (Join-Path $DataDir $f)) { throw "После удаления остался $f" }
}
Write-Host "Пробная установка, настоящая поверх неё и удаление в порядке" -ForegroundColor Green
