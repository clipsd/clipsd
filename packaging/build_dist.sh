#!/usr/bin/env bash
# Собрать архивы ClipSD: Linux (самодостаточная сборка) и исходники для сборки Windows-установщика.
# (C) 2026 Sergey Dayneko, GPL-3.0-or-later
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:?папка для архивов}"
VER="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/clipshot/__init__.py")"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$OUT"

crlf_bom() {  # $1 исходник, $2 цель: текст для Windows (CRLF, UTF-8 с BOM)
  python3 - "$1" "$2" <<'PY'
import sys
t = open(sys.argv[1], encoding="utf-8-sig").read().replace("\r\n", "\n").replace("\n", "\r\n")
open(sys.argv[2], "w", encoding="utf-8-sig", newline="").write(t)
PY
}

# Linux: self-contained build (PyInstaller); needs the build packages, see .github/workflows/linux.yml
"$ROOT/packaging/linux/build_linux.sh" "$OUT"

# Windows: исходники в раскладке build.ps1 (сборка exe и Setup.exe идёт на Windows или в облаке GitHub)
python3 "$ROOT/packaging/stage_windows.py" "$WORK/windows/ClipSD" >/dev/null
(cd "$WORK/windows" && zip -qr "$OUT/ClipSD-$VER-windows-source.zip" ClipSD)
ls -la "$OUT"/ClipSD-"$VER"-*
