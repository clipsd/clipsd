# ClipSD: the MSIX package for Microsoft Store from the layout of make_msix_layout.py.
# Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко). SPDX-License-Identifier: GPL-3.0-or-later
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
#
# Needs the Windows SDK (makepri.exe, makeappx.exe, signtool.exe; GitHub windows-latest has it).
#   -Layout     package content (OUT\layout of make_msix_layout.py, with AppxManifest.xml)
#   -PriSource  Assets and Strings only (OUT\pri): makepri indexes this folder
#   -OutDir     where the packages go
#   -TestSign   also a copy signed with a throwaway self-signed certificate (subject = Publisher of the
#               manifest) for a local test install, and its public part ClipSD-test-signing.cer. The private
#               key is deleted right after signing: nobody can sign anything else with it.
# Result: ClipSD-<version>-x64.msix (unsigned: Partner Center takes it, the Store signs it itself),
#         with -TestSign also ClipSD-<version>-x64-testsigned.msix and ClipSD-test-signing.cer,
#         pri\resources.pri.xml (readable list of the resources, for checking).
param(
    [Parameter(Mandatory = $true)] [string]$Layout,
    [Parameter(Mandatory = $true)] [string]$PriSource,
    [Parameter(Mandatory = $true)] [string]$OutDir,
    [switch]$TestSign
)
$ErrorActionPreference = "Stop"
$Layout = (Resolve-Path $Layout).Path
$PriSource = (Resolve-Path $PriSource).Path
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$OutDir = (Resolve-Path $OutDir).Path

function Find-SdkTool([string]$Name) {
    # the newest Windows SDK 10.x x64 folder that has the tool
    $kits = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
    $found = Get-ChildItem -Path $kits -Filter $Name -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.Directory.Name -eq "x64" -and $_.Directory.Parent.Name -match '^10\.\d+\.\d+\.\d+$' } |
        Sort-Object { [version]$_.Directory.Parent.Name } -Descending | Select-Object -First 1
    if (-not $found) { throw "Windows SDK: $Name не найден в $kits" }
    Write-Host "    $Name : $($found.FullName)"
    return $found.FullName
}

$Manifest = Join-Path $Layout "AppxManifest.xml"
[xml]$M = Get-Content $Manifest -Encoding utf8
$Identity = $M.Package.Identity
$Version = $Identity.Version -replace '\.0$', ''
Write-Host "==> ClipSD $($Identity.Version): $($Identity.Name), $($Identity.Publisher)" -ForegroundColor Cyan

$MakePri = Find-SdkTool "makepri.exe"
$MakeAppx = Find-SdkTool "makeappx.exe"

# --- resources.pri: images by scale / target size, the description in 12 languages -----------------------
Write-Host "==> makepri: resources.pri" -ForegroundColor Cyan
$Work = Join-Path $OutDir "pri"
New-Item -ItemType Directory -Force -Path $Work | Out-Null
$Config = Join-Path $Work "priconfig.xml"
& $MakePri createconfig /cf $Config /dq en-US /pv 10.0.0 /o
if ($LASTEXITCODE -ne 0) { throw "makepri createconfig не удался" }
# One resources.pri with every language and scale: no split resource packs (the <packaging> section)
[xml]$C = Get-Content $Config -Encoding utf8
$Packaging = $C.SelectSingleNode("/resources/packaging")
if ($Packaging) { [void]$Packaging.ParentNode.RemoveChild($Packaging) }
$C.Save($Config)
$Pri = Join-Path $Layout "resources.pri"
& $MakePri new /pr $PriSource /cf $Config /mn $Manifest /of $Pri /o
if ($LASTEXITCODE -ne 0) { throw "makepri new не удался" }
& $MakePri dump /if $Pri /of (Join-Path $Work "resources.pri.xml") /dt detailed /o
if ($LASTEXITCODE -ne 0) { throw "makepri dump не удался" }

# --- package -------------------------------------------------------------------------------------------
$Msix = Join-Path $OutDir "ClipSD-$Version-x64.msix"
Write-Host "==> makeappx: $Msix" -ForegroundColor Cyan
& $MakeAppx pack /d $Layout /p $Msix /o
if ($LASTEXITCODE -ne 0) { throw "makeappx pack не удался" }
Get-Item $Msix | Format-List Name, Length

if ($TestSign) {
    $SignTool = Find-SdkTool "signtool.exe"
    $Publisher = $Identity.Publisher
    Write-Host "==> Тестовая подпись (самоподписанный сертификат $Publisher, только для пробной установки)" -ForegroundColor Cyan
    # Code signing (EKU 1.3.6.1.5.5.7.3.3), not a CA (basic constraints empty), 30 days
    $Cert = New-SelfSignedCertificate -Type Custom -Subject $Publisher -KeyUsage DigitalSignature `
        -FriendlyName "ClipSD MSIX test signing (throwaway)" -CertStoreLocation "Cert:\CurrentUser\My" `
        -TextExtension @("2.5.29.37={text}1.3.6.1.5.5.7.3.3", "2.5.29.19={text}") -NotAfter (Get-Date).AddDays(30)
    try {
        $Signed = Join-Path $OutDir "ClipSD-$Version-x64-testsigned.msix"
        Copy-Item $Msix $Signed -Force
        & $SignTool sign /fd SHA256 /sha1 $Cert.Thumbprint /s My $Signed
        if ($LASTEXITCODE -ne 0) { throw "signtool sign не удался" }
        Export-Certificate -Cert $Cert -FilePath (Join-Path $OutDir "ClipSD-test-signing.cer") | Out-Null
    } finally {
        Remove-Item -Path "Cert:\CurrentUser\My\$($Cert.Thumbprint)" -DeleteKey -ErrorAction SilentlyContinue
        if (Test-Path "Cert:\CurrentUser\My\$($Cert.Thumbprint)") {
            Remove-Item -Path "Cert:\CurrentUser\My\$($Cert.Thumbprint)"
        }
    }
    Get-Item $Signed | Format-List Name, Length
}
Write-Host "==> Готово: $OutDir" -ForegroundColor Green
exit 0
