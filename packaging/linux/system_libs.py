#!/usr/bin/env python3
# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Shared libraries of the build machine inside a PyInstaller folder: prune the unused ones, list the rest with their
Debian package and its copyright file (for THIRD-PARTY-NOTICES.txt), refuse anything without a record.

    system_libs.py prune APPDIR           remove libraries no file of the build needs (iteratively), print them
    system_libs.py notices APPDIR OUT     write the notices section; exit 1 if a library has no package/copyright
    system_libs.py glibc APPDIR MAX       exit 1 if any file needs a GLIBC symbol version newer than MAX (2.35)

APPDIR is the PyInstaller output folder (with _internal/). A library counts as "of the build machine" when it is a real
file (not a link into a Python package) directly in _internal/; the files inside package folders (PyQt6/Qt6/lib,
cryptography, ...) and the Python extension modules are covered by the notices of their packages.
Needs: readelf (binutils), ldconfig, dpkg (Debian/Ubuntu build machine: ubuntu-22.04 in .github/workflows/linux.yml).
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

KEEP = re.compile(r"^libpython3")   # the interpreter itself: covered by the Python entry
C_ENV = dict(os.environ, LC_ALL="C", LANG="C")
# ldconfig lives in /sbin (/usr/sbin), often outside the PATH of a user
LDCONFIG = next((c for c in ("ldconfig", "/sbin/ldconfig", "/usr/sbin/ldconfig") if shutil.which(c)), "ldconfig")   # readelf and dpkg speak the system language otherwise


def elf_files(app: Path):
    for p in app.rglob("*"):
        if p.is_file() and not p.is_symlink():
            try:
                with open(p, "rb") as f:
                    if f.read(4) == b"\x7fELF":
                        yield p
            except OSError:
                pass


def needed(path: Path) -> set:
    out = subprocess.run(["readelf", "-d", str(path)], capture_output=True, text=True, env=C_ENV).stdout
    return set(re.findall(r"\(NEEDED\)\s+Shared library: \[([^\]]+)\]", out))


def top_libs(app: Path):
    internal = app / "_internal"
    return sorted(p for p in internal.iterdir() if p.name.startswith("lib") and ".so" in p.name
                  and p.is_file() and not p.is_symlink() and not KEEP.match(p.name))


def prune(app: Path) -> list:
    removed = []
    while True:
        files = list(elf_files(app))
        wanted = set()
        for f in files:
            wanted |= needed(f)
        gone = [lib for lib in top_libs(app) if lib.name not in wanted]
        if not gone:
            return removed
        for lib in gone:
            lib.unlink()
            removed.append(lib.name)


def ldconfig_paths() -> dict:
    out = subprocess.run([LDCONFIG, "-p"], capture_output=True, text=True, env=C_ENV).stdout
    paths = {}
    for m in re.finditer(r"^\s*(\S+) \(([^)]*)\) => (\S+)$", out, re.M):
        if "x86-64" in m.group(2):
            paths.setdefault(m.group(1), m.group(3))
    return paths


def package_of(path: str) -> str:
    candidates = [path, os.path.realpath(path)]
    for c in list(candidates):   # usrmerge: dpkg may know /lib/... or /usr/lib/...
        if c.startswith("/usr/lib/"):
            candidates.append(c[4:])
        elif c.startswith("/lib/"):
            candidates.append("/usr" + c)
    for c in candidates:
        r = subprocess.run(["dpkg", "-S", c], capture_output=True, text=True, env=C_ENV)
        if r.returncode == 0 and ":" in r.stdout:
            return r.stdout.split(":")[0].strip()
    return ""


def notices(app: Path) -> tuple:
    paths = ldconfig_paths()
    rows, texts, missing = [], {}, []
    for lib in top_libs(app):
        src = paths.get(lib.name, "")
        if not src:
            for d in ("/usr/lib/x86_64-linux-gnu", "/lib/x86_64-linux-gnu", "/usr/lib", "/lib"):
                if os.path.exists(os.path.join(d, lib.name)):
                    src = os.path.join(d, lib.name)
                    break
        pkg = package_of(src) if src else ""
        name = pkg.split(":")[0]
        copyright_file = Path("/usr/share/doc") / name / "copyright" if name else None
        if not pkg or copyright_file is None or not copyright_file.is_file():
            missing.append(f"{lib.name} (source {src or '?'}, package {pkg or '?'})")
            continue
        version = subprocess.run(["dpkg-query", "-W", "-f", "${Version}", name], capture_output=True, text=True).stdout
        rows.append(f"- {lib.name}: Ubuntu/Debian package {name} {version}")
        texts.setdefault(name, copyright_file.read_text(encoding="utf-8", errors="replace").strip())
    body = ("System libraries of the build machine (Ubuntu), copied unchanged into the build. Licence of each:\n"
            "the copyright file of its package, below. Source code: the Debian/Ubuntu source package of the same\n"
            "name and version (https://packages.ubuntu.com, https://sources.debian.org).\n\n" + "\n".join(rows) + "\n\n")
    for name, text in texts.items():
        body += "=" * 100 + f"\n{name}: /usr/share/doc/{name}/copyright\n" + "=" * 100 + "\n" + text + "\n\n"
    return body, missing


def glibc_too_new(app: Path, limit: str) -> list:
    lim = tuple(int(x) for x in limit.split("."))
    bad = []
    for f in elf_files(app):
        out = subprocess.run(["readelf", "-V", "--wide", str(f)], capture_output=True, text=True, env=C_ENV).stdout
        vers = {tuple(int(x) for x in v.split(".")) for v in re.findall(r"Name: GLIBC_([0-9]+(?:\.[0-9]+)+)", out)}
        top = max(vers, default=())
        if top > lim:
            bad.append(f"{f.relative_to(app)} needs GLIBC_{'.'.join(map(str, top))}")
    return bad


def main(argv) -> int:
    if len(argv) >= 2 and argv[0] == "prune":
        for name in prune(Path(argv[1])):
            print(f"system_libs: removed unused {name}")
        return 0
    if len(argv) == 3 and argv[0] == "notices":
        body, missing = notices(Path(argv[1]))
        if missing:
            for m in missing:
                print(f"system_libs: no package or copyright file for {m}", file=sys.stderr)
            return 1
        Path(argv[2]).write_text(body, encoding="utf-8")
        print(f"system_libs: {argv[2]}")
        return 0
    if len(argv) == 3 and argv[0] == "glibc":
        bad = glibc_too_new(Path(argv[1]), argv[2])
        for b in bad:
            print(f"system_libs: {b} (newer than {argv[2]})", file=sys.stderr)
        return 1 if bad else 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
