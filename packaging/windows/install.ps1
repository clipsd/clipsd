# ClipSD: установка для текущего пользователя Windows 10/11.
# Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко). SPDX-License-Identifier: GPL-3.0-or-later
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
$ErrorActionPreference = "Stop"
$Src  = Split-Path -Parent $MyInvocation.MyCommand.Path
$App  = Join-Path $env:LOCALAPPDATA "ClipSD"
$Venv = Join-Path $App "venv"
$Code = Join-Path $App "app"

function Say($t)  { Write-Host "==> $t" -ForegroundColor Cyan }
function Warn($t) { Write-Host "!!  $t" -ForegroundColor Yellow }

function Find-Python {
    $candidates = @()
    if (Get-Command py -ErrorAction SilentlyContinue) { $candidates += ,@("py", "-3") }
    foreach ($name in "python", "python3") {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        # Заглушку Microsoft Store (WindowsApps\python.exe) пропускаем
        if ($cmd -and $cmd.Source -notlike "*WindowsApps*") { $candidates += ,@($cmd.Source) }
    }
    $local = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue |
             Sort-Object FullName -Descending | Select-Object -First 1
    if ($local) { $candidates += ,@($local.FullName) }
    foreach ($c in $candidates) {
        try {
            $exe = $c[0]; $extra = @($c | Select-Object -Skip 1)
            & $exe @extra -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) { return ,$c }
        } catch { }
    }
    return $null
}

# 1. Python 3.9+
$py = Find-Python
if (-not $py) {
    Say "Python не найден, ставлю Python 3.12 через winget (только для этого пользователя)"
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Warn "Нет winget. Установите Python 3.12 с https://www.python.org/downloads/ и запустите установку снова."
        Read-Host "Enter: выход"; exit 1
    }
    winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
    $py = Find-Python
    if (-not $py) { Warn "Python установлен, но не найден. Перезапустите install.bat."; Read-Host "Enter: выход"; exit 1 }
}
$pyExe = $py[0]; $pyArgs = @($py | Select-Object -Skip 1)

# 2. Остановить прежнюю копию
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.ExecutablePath -like "$Venv*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

# 3. Файлы программы и окружение Python
Say "Копирую программу в $App"
New-Item -ItemType Directory -Force -Path $App | Out-Null
if (Test-Path $Code) { Remove-Item -Recurse -Force $Code }
New-Item -ItemType Directory -Force -Path $Code | Out-Null
Copy-Item -Recurse (Join-Path $Src "clipshot") $Code
Copy-Item (Join-Path $Src "LICENSE"), (Join-Path $Src "clipsd.ico") $Code
if (-not (Test-Path (Join-Path $Venv "Scripts\pythonw.exe"))) {
    Say "Создаю окружение Python"
    & $pyExe @pyArgs -m venv $Venv
}
Say "Ставлю PyQt6 (один раз, ~100 МБ)"
& (Join-Path $Venv "Scripts\python.exe") -m pip install --quiet --disable-pip-version-check "PyQt6>=6.5"
if ($LASTEXITCODE -ne 0) { Warn "Не удалось поставить PyQt6 (нет интернета?)"; Read-Host "Enter: выход"; exit 1 }

# 4. Ярлыки: меню «Пуск» и автозапуск
$pythonw = Join-Path $Venv "Scripts\pythonw.exe"
$shell = New-Object -ComObject WScript.Shell
$startMenu = Join-Path ([Environment]::GetFolderPath("Programs")) "ClipSD.lnk"
$startup   = Join-Path ([Environment]::GetFolderPath("Startup")) "ClipSD.lnk"
foreach ($path in $startMenu, $startup) {
    $lnk = $shell.CreateShortcut($path)
    $lnk.TargetPath = $pythonw
    $lnk.Arguments = "-m clipshot"
    $lnk.WorkingDirectory = $Code
    $lnk.IconLocation = (Join-Path $Code "clipsd.ico")
    $lnk.Description = "ClipSD: снимки экрана с редактором (Alt+W)"
    $lnk.Save()
}
Say "Ярлыки созданы: меню «Пуск» и автозапуск"

# 5. Запуск
Start-Process -FilePath $pythonw -ArgumentList "-m", "clipshot" -WorkingDirectory $Code

Say "Готово. ClipSD работает в трее (возле часов) и будет запускаться вместе с Windows."
Say "Нажмите Alt+W и выделите область экрана."
Warn "Если Alt+W не срабатывает: закройте Clip2net или другую программу, которая заняла это сочетание."
Read-Host "Enter: закрыть окно"
