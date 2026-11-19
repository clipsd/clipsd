# ClipSD: удаление для текущего пользователя Windows. (C) 2026 Sergey Dayneko, GPL-3.0-or-later
$App = Join-Path $env:LOCALAPPDATA "ClipSD"
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.ExecutablePath -like "$App*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path ([Environment]::GetFolderPath("Programs")) "ClipSD.lnk"),
                                                 (Join-Path ([Environment]::GetFolderPath("Startup")) "ClipSD.lnk")
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $App
Write-Host "ClipSD удалён. Настройки остались в $env:USERPROFILE\.config\clipshot (удалите вручную, если не нужны)."
Read-Host "Enter: закрыть окно"
