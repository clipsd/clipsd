#!/usr/bin/env python3
# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""THIRD-PARTY-NOTICES.txt: the third-party components inside a ClipSD build and the full texts of their licences.

    python3 packaging/make_notices.py linux|windows OUT_FILE

Versions come from packaging/requirements-build-<platform>.txt (the exact pins of the build), the licence texts
from packaging/licenses/ (copied from the packages themselves, the Python and Debian distributions, mozilla.org).
build_linux.sh puts the result into the Linux archive, stage_windows.py next to the installer ([Files] in ClipSD.iss).
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LICENSES = ROOT / "packaging" / "licenses"

# (component, pin name or fixed version, licence, home page, licence files); platforms: both unless said
COMPONENTS = [
    ("Python", "3.12", "PSF-2.0 (with the licences of its parts: OpenSSL Apache-2.0, libffi MIT, bzip2, xz 0BSD, zlib)",
     "https://www.python.org", ["Python-PSF-2.0.txt", "Apache-2.0.txt", "libffi-MIT.txt", "bzip2.txt", "xz-0BSD.txt"]),
    ("PyQt6", "pyqt6", "GPL-3.0", "https://www.riverbankcomputing.com/software/pyqt/", ["GPL-3.0.txt"]),
    ("Qt 6 (PyQt6-Qt6)", "pyqt6-qt6", "LGPL-3.0; FreeType inside Qt: FTL", "https://www.qt.io , https://download.qt.io/archive/qt/",
     ["LGPL-3.0.txt", "FTL.txt"]),
    ("ICU (inside PyQt6-Qt6 for Linux)", "73", "Unicode-3.0 / ICU licence", "https://icu.unicode.org",
     ["ICU-Unicode.txt"], "linux"),
    ("Microsoft Visual C++ runtime, Universal C Runtime, D3DCompiler (d3dcompiler_47.dll in PyQt6-Qt6)", "14.x / 47",
     "Microsoft redistributable licence terms", "https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files",
     ["Microsoft-redistributable.txt"], "windows"),
    ("OpenSSL (libcrypto-3, libssl-3, inside Python for Windows)", "3.x", "Apache-2.0", "https://www.openssl.org",
     ["Apache-2.0.txt"], "windows"),
    ("PyQt6-sip", "pyqt6-sip", "BSD-2-Clause", "https://pypi.org/project/PyQt6-sip/", ["PyQt6-sip-BSD-2-Clause.txt"]),
    ("cryptography (with OpenSSL inside)", "cryptography", "Apache-2.0 or BSD-3-Clause; OpenSSL: Apache-2.0",
     "https://github.com/pyca/cryptography", ["Apache-2.0.txt", "cryptography-BSD-3-Clause.txt"]),
    ("cffi", "cffi", "MIT", "https://github.com/python-cffi/cffi", ["cffi-MIT.txt"]),
    ("pycparser", "pycparser", "BSD-3-Clause", "https://github.com/eliben/pycparser", ["pycparser-BSD-3-Clause.txt"]),
    ("certifi", "certifi", "MPL-2.0", "https://github.com/certifi/python-certifi", ["certifi.txt", "MPL-2.0.txt"]),
    ("PyInstaller bootloader", "pyinstaller", "GPL-2.0-or-later with the bootloader exception",
     "https://github.com/pyinstaller/pyinstaller", ["PyInstaller-COPYING.txt"]),
    ("python-xlib", "python-xlib", "LGPL-2.1-or-later", "https://github.com/python-xlib/python-xlib", ["LGPL-2.1.txt"], "linux"),
    ("six", "six", "MIT", "https://github.com/benjaminp/six", ["six-MIT.txt"], "linux"),
    ("fontTools", "fonttools", "MIT", "https://github.com/fonttools/fonttools", ["fontTools-MIT.txt"], "linux"),
    ("zxing-cpp (reads QR codes and barcodes from a screenshot, 1.36)", "zxing-cpp", "Apache-2.0",
     "https://github.com/zxing-cpp/zxing-cpp", ["Apache-2.0.txt"]),
    ("libxcb-cursor", "0.1 (Ubuntu 22.04)", "MIT", "https://gitlab.freedesktop.org/xorg/lib/libxcb-cursor",
     ["libxcb-cursor-MIT.txt"], "linux"),
    ("Twemoji graphics (the emoji stickers of the editor; a selection of 71 SVG files, unchanged; Copyright 2019 Twitter, Inc and other contributors)",
     "15.0", "CC-BY-4.0", "https://github.com/jdecked/twemoji", ["Twemoji-CC-BY-4.0.txt"]),
    ("Mesa llvmpipe software OpenGL (opengl32sw.dll in PyQt6-Qt6)", "in PyQt6-Qt6", "MIT; LLVM: Apache-2.0 WITH LLVM-exception",
     "https://www.mesa3d.org , https://llvm.org", ["Apache-2.0.txt", "LLVM-exception.txt"], "windows"),
]


def pins(platform: str) -> dict:
    out = {}
    for line in (ROOT / "packaging" / f"requirements-build-{platform}.txt").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Za-z0-9_.\-]+)==([^\s\\;]+)", line)
        if m:
            out[re.sub(r"[-_.]+", "-", m.group(1)).lower()] = m.group(2)
    return out


# Windows: every DLL of the built program must match one of these (build.ps1 refuses an unknown one)
WINDOWS_DLLS = [
    (r"python3\d*\.dll", "Python"), (r"qt6\w*\.dll", "Qt 6"), (r"libcrypto-3(-x64)?\.dll", "OpenSSL"),
    (r"libssl-3(-x64)?\.dll", "OpenSSL"), (r"libffi-\d+\.dll", "libffi (Python)"), (r"sqlite3\.dll", "SQLite (Python)"),
    (r"(vcruntime140(_1|_threads)?|msvcp140(_\d|_atomic_wait|_codecvt_ids)?|concrt140|vccorlib140)\.dll",
     "Microsoft Visual C++ runtime"),
    (r"(ucrtbase|api-ms-win-[\w-]+)\.dll", "Universal C Runtime"), (r"d3dcompiler_47\.dll", "D3DCompiler"),
    (r"opengl32sw\.dll", "Mesa llvmpipe"), (r"q\w+\.dll", "Qt 6 plugin"),
]


def check_windows_dlls(folder: str) -> list:
    """DLL files of the built program folder that match no entry of WINDOWS_DLLS."""
    unknown = []
    for p in Path(folder).rglob("*"):
        if p.suffix.lower() == ".dll" and not any(re.fullmatch(pat, p.name, re.I) for pat, _ in WINDOWS_DLLS):
            unknown.append(str(p.relative_to(folder)))
    return sorted(unknown)


def build(platform: str, extra: str = "") -> str:
    versions = pins(platform)
    rows, files = [], []
    for item in COMPONENTS:
        name, pin, lic, url, texts = item[:5]
        if len(item) > 5 and item[5] != platform:
            continue
        if not any(ch.isdigit() for ch in pin):   # a package name: its exact pin must exist
            if pin not in versions:
                raise SystemExit(f"make_notices: {pin} is not pinned in requirements-build-{platform}.txt")
        version = versions.get(pin, pin)
        rows.append(f"- {name} {version}\n  licence: {lic}\n  source: {url}")
        files += [t for t in texts if t not in files]
    head = ("ClipSD: third-party components inside this build\n"
            "ClipSD itself: Copyright (C) 2026 Sergey Dayneko, GNU GPL v3 or later (files LICENSE, LICENSE.ru.txt),\n"
            "with additional terms on the name and icon under GPL section 7 (files TRADEMARKS.txt, TRADEMARKS.ru.txt).\n"
            "The source code of every component is available at the address given next to it.\n\n"
            "Portions of this software are copyright (C) 2026 The FreeType Project (www.freetype.org). All rights reserved.\n\n")
    body = "\n".join(rows)
    texts = []
    for f in files:
        texts.append("=" * 100 + f"\n{f}\n" + "=" * 100 + "\n" + (LICENSES / f).read_text(encoding="utf-8").strip() + "\n")
    return head + body + "\n\n\n" + (extra.strip() + "\n\n\n" if extra else "") + "FULL LICENCE TEXTS\n\n" + "\n".join(texts)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--check-windows-dlls":
        bad = check_windows_dlls(sys.argv[2])
        for b in bad:
            print(f"make_notices: no notice for {b}: add it to WINDOWS_DLLS and COMPONENTS", file=sys.stderr)
        sys.exit(1 if bad else 0)
    if len(sys.argv) not in (3, 4) or sys.argv[1] not in ("linux", "windows"):
        raise SystemExit("usage: make_notices.py linux|windows OUT_FILE [EXTRA_SECTION_FILE] | --check-windows-dlls DIR")
    extra = Path(sys.argv[3]).read_text(encoding="utf-8") if len(sys.argv) == 4 else ""
    Path(sys.argv[2]).write_text(build(sys.argv[1], extra), encoding="utf-8")
    print(f"make_notices: {sys.argv[2]}")
