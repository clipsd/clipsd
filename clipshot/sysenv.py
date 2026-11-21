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



def _system_dir() -> str:
    """Windows: system folder of programs that run natively in this process: System32 (GetSystemDirectoryW); a 32-bit
    ClipSD on 64-bit Windows: Sysnative (the real System32, not SysWOW64). OSError when Windows does not answer."""
    import ctypes
    import struct
    buf = ctypes.create_unicode_buffer(32768)
    if struct.calcsize("P") == 4:
        n = ctypes.windll.kernel32.GetWindowsDirectoryW(buf, len(buf))
        native = os.path.join(buf.value, "Sysnative") if n else ""
        if native and os.path.isdir(native):
            return native
    n = ctypes.windll.kernel32.GetSystemDirectoryW(buf, len(buf))
    if not n or n >= len(buf):
        raise OSError("GetSystemDirectoryW failed")
    return buf.value


def system_program(*parts) -> str:
    """Windows: full path of a Windows program in the system folder, e.g. system_program("netsh.exe") or
    system_program("WindowsPowerShell", "v1.0", "powershell.exe"). Never a bare name: CreateProcess and ShellExecute
    look for a bare name first in the folder of ClipSD, which a per-user install leaves writable for the user, so a
    planted powershell.exe there would run (as administrator, behind a UAC prompt naming ClipSD: Б4 of the 1.34.1
    review). OSError when the system folder is unknown."""
    path = os.path.join(_system_dir(), *parts)
    if not os.path.isabs(path):
        raise OSError(f"not absolute: {path}")
    return path


def powershell_exe() -> str:
    """Windows PowerShell 5.1 by full path (the OCR and the OCR language install use it)."""
    return system_program("WindowsPowerShell", "v1.0", "powershell.exe")


def encoded_command(script_text: str) -> str:
    """Script text for powershell -EncodedCommand: base64 of UTF-16LE (no script file anyone could swap)."""
    import base64
    return base64.b64encode(script_text.encode("utf-16-le")).decode("ascii")


PS_QUOTES = "'\u2018\u2019\u201a\u201b"   # PowerShell treats all of these as single quotes


def ps_quote(value: str) -> str:
    """A PowerShell single-quoted literal: nothing inside is expanded. ValueError for control characters and the
    typographic single quotes (PowerShell ends a quoted string on them too); the ASCII quote is doubled."""
    value = str(value)
    if any(ord(c) < 32 or c in PS_QUOTES[1:] for c in value):
        raise ValueError(f"unsafe for PowerShell: {value!r}")
    return "'" + value.replace("'", "''") + "'"


def elevated_powershell_parameters(script_text: str) -> str:
    """Command line for an elevated Windows PowerShell (run_elevated_wait): the whole script in -EncodedCommand."""
    return "-NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand " + encoded_command(script_text)


ERROR_CANCELLED = 1223   # ShellExecuteEx: the person refused the UAC prompt


def _shell_execute_info():
    import ctypes
    from ctypes import wintypes

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                    ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD), ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]
    return SHELLEXECUTEINFOW


class _WinApi:
    """The four calls of run_elevated_wait (tests replace this object)."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._execute = shell32.ShellExecuteExW
        self._execute.argtypes = [ctypes.c_void_p]
        self._execute.restype = wintypes.BOOL
        self.WaitForSingleObject = kernel32.WaitForSingleObject
        self.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.WaitForSingleObject.restype = wintypes.DWORD
        self.GetExitCodeProcess = kernel32.GetExitCodeProcess
        self.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        self.GetExitCodeProcess.restype = wintypes.BOOL
        self.CloseHandle = kernel32.CloseHandle
        self.CloseHandle.argtypes = [wintypes.HANDLE]
        self._ctypes = ctypes

    def ShellExecuteExW(self, info_ref):
        ok = self._execute(info_ref)
        return ok, (0 if ok else self._ctypes.get_last_error())


def run_elevated_wait(program: str, parameters: str, timeout_ms: int, api=None):
    """Windows: start a program as administrator (UAC prompt), hidden, and wait for it: ShellExecuteExW with
    SEE_MASK_NOCLOSEPROCESS, WaitForSingleObject, GetExitCodeProcess. Call it from a background thread.
    The elevated program gets only its command line: nothing is read from or written to the user's folders.
    Returns (exit code or None, reason, declined): declined is True when the UAC prompt was refused."""
    import ctypes
    from ctypes import wintypes
    if api is None:
        if sys.platform != "win32":
            return None, "not Windows", False
        api = _WinApi()
        try:
            ctypes.windll.ole32.CoInitializeEx(None, 0x2 | 0x4)   # ShellExecuteEx wants COM in its thread
        except (AttributeError, OSError):
            pass
    if not os.path.isabs(program):
        return None, f"not absolute: {program}", False
    info = _shell_execute_info()()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x40 | 0x100   # SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC
    info.lpVerb, info.lpFile, info.lpParameters, info.nShow = "runas", program, parameters, 0   # SW_HIDE
    ok, error = api.ShellExecuteExW(ctypes.byref(info))
    if not ok:
        return None, f"ShellExecuteEx {error}", error == ERROR_CANCELLED
    if not info.hProcess:
        return None, "no process handle", False
    try:
        if api.WaitForSingleObject(info.hProcess, timeout_ms) != 0:   # WAIT_OBJECT_0
            return None, "timeout", False
        code = wintypes.DWORD()
        if not api.GetExitCodeProcess(info.hProcess, ctypes.byref(code)):
            return None, "GetExitCodeProcess failed", False
        return code.value, "", False
    finally:
        api.CloseHandle(info.hProcess)
