@echo off
rem ClipSD: удаление. (C) 2026 Sergey Dayneko, GPL-3.0-or-later
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1"
