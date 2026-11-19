# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""THIRD-PARTY-NOTICES of the builds: packaging/linux/system_libs.py (prune, notices, glibc) on real libraries of
this machine in a temporary folder, packaging/make_notices.py (texts, Windows DLL check). No build is made.
The Linux part is skipped where readelf, ldconfig or dpkg are missing.

Run: python3 tests/notices_test.py
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packaging"))
import make_notices  # noqa: E402

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


tmp = Path(tempfile.mkdtemp(prefix="clipsd-notices-"))

# --- make_notices ------------------------------------------------------------------------------------------
lin = make_notices.build("linux", "SYSTEM SECTION")
win = make_notices.build("windows")
for name, text in (("linux", lin), ("windows", win)):
    check("GNU LESSER GENERAL PUBLIC LICENSE" in text and "Mozilla Public License Version 2.0" in text
          and "PyQt6 6.11.0" in text and "certifi 2026.10.23" in text, f"{name}: полные тексты LGPL, MPL, версии из requirements")
check("python-xlib" in lin and "ICU" in lin and "SYSTEM SECTION" in lin and "python-xlib" not in win,
      "linux: python-xlib, ICU и раздел системных библиотек; в windows их нет")
check("d3dcompiler_47" in win and "OpenSSL (libcrypto-3" in win and "Microsoft redistributable" in win,
      "windows: D3DCompiler, MSVC runtime, OpenSSL")
dlls = tmp / "win"
for rel in ("python312.dll", "libcrypto-3.dll", "libssl-3.dll", "libffi-8.dll", "VCRUNTIME140.dll", "vcruntime140_1.dll",
            "PyQt6/Qt6/bin/Qt6Core.dll", "PyQt6/Qt6/bin/d3dcompiler_47.dll", "PyQt6/Qt6/bin/opengl32sw.dll",
            "PyQt6/Qt6/bin/MSVCP140_2.dll", "PyQt6/Qt6/plugins/platforms/qwindows.dll"):
    (dlls / rel).parent.mkdir(parents=True, exist_ok=True)
    (dlls / rel).write_bytes(b"MZ")
check(make_notices.check_windows_dlls(str(dlls)) == [], "windows: все обычные DLL сборки имеют запись")
(dlls / "avcodec-61.dll").write_bytes(b"MZ")
check(make_notices.check_windows_dlls(str(dlls)) == ["avcodec-61.dll"], "windows: неизвестная DLL (ffmpeg) найдена, сборка упадёт")

# --- system_libs (Linux) -------------------------------------------------------------------------------------
spec = importlib.util.spec_from_file_location("system_libs", ROOT / "packaging/linux/system_libs.py")
sl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sl)
tools = all(shutil.which(t) for t in ("readelf", "dpkg", "dpkg-query")) and bool(shutil.which(sl.LDCONFIG))
paths = sl.ldconfig_paths() if tools else {}
zlib_mod = Path(paths["libpng16.so.16"]) if "libpng16.so.16" in paths else None   # an ELF that NEEDS libz.so.1
if not tools or "libz.so.1" not in paths or "libexpat.so.1" not in paths or zlib_mod is None:
    print("skip: Linux part (readelf/ldconfig/dpkg, libz, libexpat or libpng missing)")
else:
    app = tmp / "app"
    internal = app / "_internal"
    (internal / "lib-dynload").mkdir(parents=True)
    shutil.copy2(zlib_mod, internal / "lib-dynload" / zlib_mod.name)     # a root (inside a package folder) that NEEDS libz
    for name in ("libz.so.1", "libexpat.so.1"):
        shutil.copy2(paths[name], internal / name)
    needs_z = "libz.so.1" in sl.needed(internal / "lib-dynload" / zlib_mod.name)
    if not needs_z:
        print("skip: libpng of this system does not need libz")
    else:
        removed = sl.prune(app)
        check(removed == ["libexpat.so.1"] and (internal / "libz.so.1").exists(),
              f"prune: убрана библиотека, которая никому не нужна, нужная осталась ({removed})")
        body, missing = sl.notices(app)
        check(not missing and "libz.so.1: Ubuntu/Debian package zlib1g" in body and "/usr/share/doc/zlib1g/copyright" in body,
              "notices: у библиотеки пакет и его copyright")
        shutil.copy2(paths["libz.so.1"], internal / "libclipsdfake.so.1")
        body, missing = sl.notices(app)
        check(missing and "libclipsdfake.so.1" in missing[0], "notices: библиотека без пакета: сборка откажет")
        (internal / "libclipsdfake.so.1").unlink()
        r = subprocess.run([sys.executable, str(ROOT / "packaging/linux/system_libs.py"), "glibc", str(app), "99.0"],
                           capture_output=True, text=True)
        check(r.returncode == 0, "glibc: предел 99.0 не превышен")
        r = subprocess.run([sys.executable, str(ROOT / "packaging/linux/system_libs.py"), "glibc", str(app), "2.0"],
                           capture_output=True, text=True)
        check(r.returncode == 1 and "needs GLIBC_" in r.stderr, "glibc: библиотека новее предела: сборка откажет")

shutil.rmtree(tmp, ignore_errors=True)
print()
if failures:
    print(f"ИТОГ: {len(failures)} проверок не прошли")
    sys.exit(1)
print("ИТОГ: все проверки пройдены")
