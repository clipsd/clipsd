# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Environment for programs ClipSD starts (systemd-run, clipsd-switch, systemctl, gsettings, tesseract...).

The Linux package is a PyInstaller build. Its bootloader puts into the environment of ClipSD itself:
LD_LIBRARY_PATH = <versions/N>/_internal (the libraries of the build, made on Ubuntu 22.04), _PYI_* (its own
bookkeeping) and, through the PyQt runtime hook, QT_PLUGIN_PATH / QML2_IMPORT_PATH inside the build. A system
program started with that environment loads the OLD libraries of the build instead of its own: on Ubuntu 26.04
systemd-run and systemctl stop with "OPENSSL_3.4.0 not found", /usr/bin/env, mkdir, cat (rust coreutils) with
"LIBSYSTEMD_254 not found", tesseract with "GLIBCXX_3.4.32 not found". ClipSD 1.31.0 lost its update that way
(19.11.2026): the switch helper died at its first line and nothing was switched.

child_env() returns the environment the person's session had: LD_LIBRARY_PATH as it was before the bootloader
(LD_LIBRARY_PATH_ORIG, or without the folders of the build), no _PYI_*, no Qt paths into the build. Changing
os.environ itself would not help the program (the dynamic loader read LD_LIBRARY_PATH at start) and would take
the plugin folder away from Qt, so only the environment of a child is cleaned. Run from the sources nothing of
this is there and the environment is returned as it is.
"""
import os
import sys

PYI_PREFIX = "_PYI_"
QT_PATH_VARS = ("QT_PLUGIN_PATH", "QML2_IMPORT_PATH")
ORIG_SUFFIX = "_ORIG"


def bundle_dirs() -> list:
    """Folders of the PyInstaller build this process runs from ([] when run from the sources)."""
    dirs = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.append(os.path.realpath(meipass))
    if getattr(sys, "frozen", False):
        dirs.append(os.path.realpath(os.path.dirname(sys.executable)))
    return dirs


def _inside(path: str, dirs) -> bool:
    if not path:
        return False
    real = os.path.realpath(path)
    return any(real == d or real.startswith(d.rstrip(os.sep) + os.sep) for d in dirs)


def _without(value: str, dirs) -> str:
    return os.pathsep.join(p for p in value.split(os.pathsep) if p and not _inside(p, dirs))


def child_env(base=None) -> dict:
    """A copy of the environment for an external program, without what the PyInstaller build put in for itself."""
    env = dict(os.environ if base is None else base)
    dirs = bundle_dirs()
    if not dirs and not any(k.startswith(PYI_PREFIX) for k in env):
        return env   # from the sources: nothing to clean
    for name in ("LD_LIBRARY_PATH", "LIBPATH"):   # LIBPATH: the same variable of the bootloader on AIX
        orig = env.pop(name + ORIG_SUFFIX, None)
        if orig is not None:
            value = orig                          # the bootloader saved the person's own value
        else:
            value = _without(env.get(name, ""), dirs)
        if value:
            env[name] = value
        else:
            env.pop(name, None)
    for name in QT_PATH_VARS:
        if name in env:
            value = _without(env[name], dirs)
            if value:
                env[name] = value
            else:
                env.pop(name)
    for name in [k for k in env if k.startswith(PYI_PREFIX)]:
        del env[name]
    # a frozen program started from here (the new version) is an independent program, not a child of this build
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def open_url(url) -> bool:
    """Open an address or a local file (QUrl or str) in the person's program for it.

    Qt opens addresses on Linux through xdg-open, started with the environment of this process: in the package
    that means the libraries of the build, and on Ubuntu 26.04 xdg-open's gio, tr, basename do not start ("Open
    website", the bug report page, the folder of snapshots did nothing). In the package xdg-open is started here
    with child_env(); elsewhere, and when that fails, Qt does it as before."""
    from PyQt6.QtCore import QUrl
    from PyQt6.QtGui import QDesktopServices
    qurl = url if isinstance(url, QUrl) else QUrl(str(url))
    if sys.platform.startswith("linux") and bundle_dirs():
        import shutil
        import subprocess
        tool = shutil.which("xdg-open")
        if tool:
            try:
                subprocess.Popen([tool, qurl.toString()], env=child_env(), start_new_session=True, close_fds=True,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except OSError:
                pass
    return QDesktopServices.openUrl(qurl)
