#!/usr/bin/env bash
# ClipSD: self-contained Linux build (PyInstaller onedir) -> ClipSD-<version>-linux-x86_64.tar.gz
# Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко). SPDX-License-Identifier: GPL-3.0-or-later
#
# Usage: packaging/linux/build_linux.sh [OUT_DIR]        (default OUT_DIR: <repo>/dist)
# Env:   CLIPSD_BUILD_VENV  build venv (default <repo>/.venv-build-linux; never the program venv)
#        CLIPSD_PYTHON      python used to create the venv (default python3)
#        CLIPSD_MAX_MB      size limit of the archive (default 90, spec section 3)
# Intended to run on ubuntu-22.04 (glibc 2.35): the result then starts on every newer glibc.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$(mkdir -p "${1:-$ROOT/dist}" && cd "${1:-$ROOT/dist}" && pwd)"
VENV="${CLIPSD_BUILD_VENV:-$ROOT/.venv-build-linux}"
MAX_MB="${CLIPSD_MAX_MB:-90}"
cd "$ROOT"

python3 packaging/stamp_version.py --check

VER="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' clipshot/__init__.py)"
[ -n "$VER" ] || { echo "no __version__ in clipshot/__init__.py" >&2; exit 1; }
echo "==> ClipSD $VER (linux-x86_64)"

if [ ! -x "$VENV/bin/python" ]; then
  "${CLIPSD_PYTHON:-python3}" -m venv "$VENV"
fi
# Exact versions with hashes: the same build every time, nothing unexpected from PyPI.
"$VENV/bin/python" -m pip install --quiet --disable-pip-version-check --require-hashes --only-binary :all: \
  -r packaging/requirements-build-linux.txt

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "==> PyInstaller"
"$VENV/bin/python" -m PyInstaller --noconfirm --clean --name clipsd \
  --paths . --collect-submodules clipshot --collect-data clipshot \
  --distpath "$WORK/dist" --workpath "$WORK/build" --specpath "$WORK/spec" \
  --exclude-module tkinter --exclude-module unittest --exclude-module pydoc \
  --exclude-module PyQt6.QtQml --exclude-module PyQt6.QtQuick --exclude-module PyQt6.QtPdf \
  --exclude-module PyQt6.QtMultimedia --exclude-module PyQt6.QtBluetooth --exclude-module PyQt6.QtSql \
  --exclude-module PyQt6.QtOpenGL --exclude-module PyQt6.QtWebSockets --exclude-module PyQt6.QtTest \
  --exclude-module readline \
  packaging/linux/clipsd_launcher.py

APPDIR="$WORK/dist/clipsd"
[ -x "$APPDIR/clipsd" ] || { echo "PyInstaller did not produce clipsd" >&2; exit 1; }

# The Qt xcb plugin needs libxcb-cursor; a clean Ubuntu has no such package, so it must travel inside.
if ! find "$APPDIR" -name 'libxcb-cursor.so*' | grep -q .; then
  echo "libxcb-cursor is not inside the build: install libxcb-cursor0 on the build machine" >&2
  exit 1
fi

# Parts ClipSD never uses, with the system libraries only they pull in: the GTK 3 platform theme (gtk-3, gdk, atk, cairo,
# pango, gdk-pixbuf and, on newer systems, glycin and seccomp; Qt draws its own dialogs or uses the desktop portal)
# and the PDF image plugin (Qt Pdf). Then every system library no file of the build needs is removed.
echo "==> unused parts"
rm -f "$APPDIR/_internal/PyQt6/Qt6/plugins/platformthemes/libqgtk3.so" \
      "$APPDIR/_internal/PyQt6/Qt6/plugins/imageformats/libqpdf.so" \
      "$APPDIR/_internal/PyQt6/Qt6/lib/libQt6Pdf.so.6" "$APPDIR/_internal/libQt6Pdf.so.6"
python3 packaging/linux/system_libs.py prune "$APPDIR"

# Releases are built on ubuntu-22.04 (glibc 2.35) by .github/workflows/linux.yml. A build that needs a newer glibc
# would not start on Ubuntu 22.04, Debian 12 and their relatives: refused (a local test build may pass
# CLIPSD_ALLOW_NEW_GLIBC=1, it is never a release).
if [ "${CLIPSD_ALLOW_NEW_GLIBC:-0}" != 1 ]; then
  python3 packaging/linux/system_libs.py glibc "$APPDIR" 2.35 ||
    { echo "the build needs a glibc newer than 2.35: build it on ubuntu-22.04 (GitHub Actions)" >&2; exit 1; }
else
  # marked so that it can never pass for a release: file LOCALTEST next to the program, "build: localtest" in the
  # selfcheck, "-localtest" in the archive name; tools/release.sh assemble refuses all three
  echo "!!  CLIPSD_ALLOW_NEW_GLIBC=1: glibc not checked, this archive is for local tests only (localtest)"
  printf '%s\n' "ClipSD local test build: glibc not checked, never a release." > "$APPDIR/LOCALTEST"
fi

# Every system library left has its Debian package and copyright file in THIRD-PARTY-NOTICES.txt, or the build fails
python3 packaging/linux/system_libs.py notices "$APPDIR" "$WORK/system-libs.txt" ||
  { echo "a library of the build has no package or copyright file (see above)" >&2; exit 1; }

echo "==> selfcheck"
CHECK_OUT="$(QT_QPA_PLATFORM=offscreen "$APPDIR/clipsd" --selfcheck)"
printf '%s\n' "$CHECK_OUT"
# the built program must be exactly the kind of these sources: preview only with clipshot/_preview_build.py
WANT="build: release"
[ ! -f clipshot/_preview_build.py ] || WANT="build: preview"
if [ -f "$APPDIR/LOCALTEST" ]; then
  if [ "$WANT" = "build: release" ]; then WANT="build: localtest"; else WANT="${WANT}-localtest"; fi
fi
grep -qx "$WANT" <<<"$CHECK_OUT" || { echo "selfcheck: expected '$WANT'" >&2; exit 1; }

# Release folder clipsd-<version>/
REL="$WORK/clipsd-$VER"
mkdir -p "$REL"
cp -a "$APPDIR/." "$REL/"
cp packaging/linux/clipsd-switch packaging/linux/install.sh packaging/linux/uninstall.sh "$REL/"
cp packaging/linux/README.txt "$REL/README.txt"
cp packaging/linux/README.en.txt "$REL/README.en.txt"
cp LICENSE LICENSE.ru.txt "$REL/"
python3 packaging/make_notices.py linux "$REL/THIRD-PARTY-NOTICES.txt" "$WORK/system-libs.txt"
cp -r packaging/gnome-extension "$REL/"
find "$REL" -name '__pycache__' -prune -exec rm -rf {} +
chmod 755 "$REL/clipsd-switch" "$REL/install.sh" "$REL/uninstall.sh"
printf '%s\n' "$VER" > "$REL/VERSION"

# Reproducible archive: sorted names, fixed owner, time of the last commit
EPOCH="$(git -C "$ROOT" log -1 --format=%ct 2>/dev/null || date +%s)"
# a preview build (packaging/preview_build.py) is never named like a release one
KIND=""
[ ! -f clipshot/_preview_build.py ] || KIND="-proba"
[ ! -f "$APPDIR/LOCALTEST" ] || KIND="$KIND-localtest"
ARCHIVE="$OUT/ClipSD-$VER$KIND-linux-x86_64.tar.gz"
tar -C "$WORK" --sort=name --owner=0 --group=0 --numeric-owner --mtime="@$EPOCH" -cf - "clipsd-$VER" | gzip -9n > "$ARCHIVE"

SIZE_MB=$(( ($(stat -c %s "$ARCHIVE") + 1048575) / 1048576 ))
echo "==> $ARCHIVE (${SIZE_MB} MB)"
if [ "$SIZE_MB" -gt "$MAX_MB" ]; then
  echo "archive is larger than ${MAX_MB} MB (spec 3)" >&2
  exit 1
fi
