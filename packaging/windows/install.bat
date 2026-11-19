@echo off
rem ClipSD: установка. (C) 2026 Sergey Dayneko, GPL-3.0-or-later
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
