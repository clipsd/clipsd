# ClipSD: build of ClipSD-app.exe, the launcher ClipSD.exe and the installer ClipSD-<version>-Setup.exe for Windows.
# Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко). SPDX-License-Identifier: GPL-3.0-or-later
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
#
# Runs inside the folder made by packaging/stage_windows.py (CI and build_dist.sh).
# Needs: Python 3.12 x64, Visual Studio 2022+ or Build Tools with "Desktop development with C++" (cl.exe, rc.exe),
#        Inno Setup 6 (winget install JRSoftware.InnoSetup); without it the build fails.
# Run:   powershell -ExecutionPolicy Bypass -File packaging\build.ps1 [-AppOnly]
# Result: dist\ClipSD-app\ClipSD-app.exe (program), dist\launcher\ClipSD.exe (launcher),
#         dist\ClipSD-<version>-Setup.exe (installer)
# -AppOnly: only the program and its selfcheck (the Microsoft Store package of packaging/windows-store needs
#           neither the launcher nor the installer: Windows starts ClipSD-app.exe and the Store updates it).
param([switch]$AppOnly)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Venv = Join-Path $Root ".venv-build"
$Py   = Join-Path $Venv "Scripts\python.exe"
Set-Location $Root

# The only version source is clipshot\__init__.py; every stamped file must agree with it.
python packaging\stamp_version.py --check
if ($LASTEXITCODE -ne 0) { throw "Номер версии в файлах сборки не совпадает с clipshot\__init__.py: python packaging/stamp_version.py" }

$Version = (Select-String -Path "clipshot\__init__.py" -Pattern '__version__ = "(.+)"').Matches[0].Groups[1].Value
Write-Host "==> ClipSD $Version" -ForegroundColor Cyan

if (-not (Test-Path $Py)) {
    Write-Host "==> Окружение сборки" -ForegroundColor Cyan
    python -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw "python -m venv не удался" }
}
# Exact versions with hashes: the same build every time, nothing unexpected from PyPI.
& $Py -m pip install --quiet --disable-pip-version-check --require-hashes --only-binary ":all:" `
    -r packaging\requirements-build-windows.txt
if ($LASTEXITCODE -ne 0) { throw "pip install не удался" }

Write-Host "==> PyInstaller: dist\ClipSD-app\ClipSD-app.exe" -ForegroundColor Cyan
& $Py -m PyInstaller --noconfirm --clean --windowed `
    --name ClipSD-app `
    --icon clipsd.ico `
    --version-file packaging\version_info.txt `
    --paths . `
    --collect-submodules clipshot --collect-data clipshot `
    --add-data "$Root\CHANGELOG;CHANGELOG" `
    --distpath dist --workpath build `
    --exclude-module tkinter --exclude-module unittest --exclude-module pydoc `
    --exclude-module PyQt6.QtQml --exclude-module PyQt6.QtQuick --exclude-module PyQt6.QtPdf `
    --exclude-module PyQt6.QtMultimedia --exclude-module PyQt6.QtBluetooth --exclude-module PyQt6.QtSql `
    --exclude-module PyQt6.QtOpenGL --exclude-module PyQt6.QtWebSockets --exclude-module PyQt6.QtTest `
    packaging\clipsd_app_entry.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller не удался" }

# Every DLL of the program has its notice in THIRD-PARTY-NOTICES.txt (packaging/make_notices.py WINDOWS_DLLS)
python packaging\make_notices.py --check-windows-dlls dist\ClipSD-app
if ($LASTEXITCODE -ne 0) { throw "В сборке есть DLL без записи в THIRD-PARTY-NOTICES.txt (см. выше)" }
Get-ChildItem dist\ClipSD-app -Recurse -Filter *.dll | ForEach-Object { $_.Name } | Sort-Object -Unique | Write-Host

# The built exe itself: imports, Ed25519 vector through the update channel code, certificate store (no network).
# The exe is windowed, so the result comes back in a file; the wait has a time limit.
Write-Host "==> selfcheck: dist\ClipSD-app\ClipSD-app.exe --selfcheck" -ForegroundColor Cyan
$App = Join-Path $Root "dist\ClipSD-app\ClipSD-app.exe"
$Report = Join-Path $Root "build\selfcheck.txt"
Remove-Item $Report -ErrorAction SilentlyContinue
$QtPlatform = $env:QT_QPA_PLATFORM
$env:QT_QPA_PLATFORM = "offscreen"
$proc = Start-Process -FilePath $App -ArgumentList @("--selfcheck", "`"$Report`"") -PassThru
$null = $proc.Handle   # keep the handle: otherwise Windows PowerShell 5.1 may lose ExitCode
if (-not $proc.WaitForExit(120000)) { $proc.Kill(); throw "selfcheck не завершился за 120 с" }
$env:QT_QPA_PLATFORM = $QtPlatform
if (Test-Path $Report) { Get-Content $Report -Encoding utf8 | Write-Host }
if ($proc.ExitCode -ne 0 -or -not (Test-Path $Report)) { throw "selfcheck собранной программы не прошёл (код $($proc.ExitCode))" }
# The built program must be exactly the kind of these sources: preview only with clipshot\_preview_build.py,
# Microsoft Store only with clipshot\_store_build.py (packaging/stage_windows.py --store)
$Want = if (Test-Path (Join-Path $Root "clipshot\_preview_build.py")) { "build: preview" }
        elseif (Test-Path (Join-Path $Root "clipshot\_store_build.py")) { "build: store" }
        else { "build: release" }
if (-not ((Get-Content $Report -Encoding utf8) -contains $Want)) { throw "selfcheck: ожидали '$Want'" }
if ($AppOnly) {
    Write-Host "==> Готово (только программа): dist\ClipSD-app\ClipSD-app.exe" -ForegroundColor Green
    exit 0
}

# --- launcher (C, MSVC) ---------------------------------------------------------------------------------
function Enter-Msvc {
    # cl.exe already on PATH (Developer PowerShell): nothing to do.
    if (Get-Command cl.exe -ErrorAction SilentlyContinue) { return }
    $vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
    if (-not (Test-Path $vswhere)) { throw "Не найден Visual Studio (vswhere.exe): нужен компилятор C (cl.exe)" }
    $vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath |
          Select-Object -First 1
    if (-not $vs) { throw "В Visual Studio нет компонента C++ (Microsoft.VisualStudio.Component.VC.Tools.x86.x64)" }
    $vcvars = Join-Path $vs "VC\Auxiliary\Build\vcvars64.bat"
    if (-not (Test-Path $vcvars)) { throw "Не найден $vcvars" }
    # Run vcvars64.bat in cmd and copy the resulting environment into this PowerShell process.
    $lines = & cmd.exe /d /c "`"$vcvars`" >nul 2>&1 && set"
    if ($LASTEXITCODE -ne 0) { throw "vcvars64.bat завершился с ошибкой" }
    foreach ($line in $lines) {
        if ($line -match '^([^=]+)=(.*)$') { [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], "Process") }
    }
    if (-not (Get-Command cl.exe -ErrorAction SilentlyContinue)) { throw "cl.exe не найден после vcvars64.bat" }
}

Write-Host "==> Запускатель: dist\launcher\ClipSD.exe" -ForegroundColor Cyan
Enter-Msvc
$LSrc = Join-Path $Root "packaging\launcher"
$LObj = Join-Path $Root "build\launcher"
$LOut = Join-Path $Root "dist\launcher"
New-Item -ItemType Directory -Force -Path $LObj, $LOut | Out-Null
& rc.exe /nologo /I "$LSrc" /I "$Root" /fo "$LObj\clipsd_launcher.res" "$LSrc\clipsd_launcher.rc"
if ($LASTEXITCODE -ne 0) { throw "rc.exe не удался" }
# /O1 small code, /MT static runtime (no vcruntime DLL next to the launcher), /utf-8 source encoding.
& cl.exe /nologo /O1 /MT /W4 /utf-8 /GS /DUNICODE /D_UNICODE `
    "/Fo$LObj\clipsd_launcher.obj" "/Fe$LOut\ClipSD.exe" "$LSrc\clipsd_launcher.c" "$LObj\clipsd_launcher.res" `
    /link /SUBSYSTEM:WINDOWS /MANIFEST:NO /DYNAMICBASE /NXCOMPAT /OPT:REF /OPT:ICF `
    kernel32.lib user32.lib shell32.lib version.lib
if ($LASTEXITCODE -ne 0) { throw "cl.exe не удался" }
if (-not (Test-Path "$LOut\ClipSD.exe")) { throw "Запускатель не собран" }

# --- installer ------------------------------------------------------------------------------------------
$Iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
          "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) {
    # No installer is a failed build: a caller must never take a half build for a release.
    Write-Host "    Собраны только dist\ClipSD-app\ClipSD-app.exe и dist\launcher\ClipSD.exe" -ForegroundColor Yellow
    throw "Inno Setup 6 не найден, установщик не собран: winget install JRSoftware.InnoSetup"
}
Write-Host "==> Inno Setup: установщик" -ForegroundColor Cyan
& $Iscc "/DAppVersion=$Version" packaging\ClipSD.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup не удался" }
Write-Host "==> Готово: dist\ClipSD-$Version-Setup.exe" -ForegroundColor Green
