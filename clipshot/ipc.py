# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Связь с фоновой копией без загрузки Qt: команда от Alt+W доходит за миллисекунды.

Protocol: the client writes the raw UTF-8 command without a terminator. Only "quit-for-update" gets
a reply line on the same connection: "ok\\n" (the program quits now) or "busy\\n" (it cannot quit
without losing work, the update is deferred). Users of the reply: packaging/linux/clipsd-switch and
the Windows launcher (packaging/windows-exe/launcher/clipsd_launcher.c).

Where the channel lives:
- Linux: ${XDG_RUNTIME_DIR}/clipsd.sock; without XDG_RUNTIME_DIR (or when that path is too long) a private folder of this user
  (mode 0700): ${XDG_CACHE_HOME:-~/.cache}/clipsd/clipsd.sock, or <tmp>/clipsd-<uid>/clipsd.sock when
  that path is too long for a socket. Never a shared /tmp/clipsd.sock.
- Windows: QLocalServer pipe \\\\.\\pipe\\clipsd-<user SID> (the launcher builds the same name); the
  user name is used only when the SID cannot be read.
"""

import functools
import os
import re
import socket
import sys
import stat
import tempfile

SOCKET_NAME = "clipsd.sock"          # the package (installed build), since 1.30
SOURCE_SOCKET_NAME = "clipshot.sock"  # ClipSD run from the sources (a developer's working copy), as 1.29 and older:
                                      # the working copy and an installed package never talk to each other


def socket_name() -> str:
    return SOCKET_NAME if getattr(sys, "frozen", False) else SOURCE_SOCKET_NAME
_MAX_UNIX_PATH = 100          # sun_path is 108 bytes on Linux; keep a margin
QUIT_FOR_UPDATE = "quit-for-update"


@functools.lru_cache(maxsize=1)
def windows_user_id() -> str:
    """String SID of the current user ("S-1-5-21-..."), or the user name if the SID is unknown."""
    try:
        import ctypes
        from ctypes import wintypes
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.GetCurrentProcess.argtypes = []
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
        advapi32.OpenProcessToken.restype = wintypes.BOOL
        advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                                 ctypes.POINTER(wintypes.DWORD)]
        advapi32.GetTokenInformation.restype = wintypes.BOOL
        advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
        token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):  # TOKEN_QUERY
            raise OSError("OpenProcessToken")
        try:
            size = wintypes.DWORD(0)
            advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))   # 1 = TokenUser
            if not size.value:
                raise OSError("GetTokenInformation size")
            buf = ctypes.create_string_buffer(size.value)
            if not advapi32.GetTokenInformation(token, 1, buf, size, ctypes.byref(size)):
                raise OSError("GetTokenInformation")
            psid = ctypes.c_void_p.from_buffer(buf).value   # TOKEN_USER.User.Sid is the first field
            text = ctypes.c_void_p()
            if not advapi32.ConvertSidToStringSidW(psid, ctypes.byref(text)):
                raise OSError("ConvertSidToStringSidW")
            try:
                sid = ctypes.wstring_at(text.value)
            finally:
                kernel32.LocalFree(text)
        finally:
            kernel32.CloseHandle(token)
        if re.fullmatch(r"S-[0-9]+(-[0-9]+)+", sid or ""):
            return sid
    except (AttributeError, OSError, ValueError):
        pass
    return os.environ.get("USERNAME") or "user"


def _own_private_dir(path: str) -> bool:
    """Create path with mode 0700 if missing; True only for a real folder of this user, mode 0700."""
    try:
        os.makedirs(path, mode=0o700, exist_ok=True)
        st = os.lstat(path)
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
            return False
        if stat.S_IMODE(st.st_mode) != 0o700:
            os.chmod(path, 0o700)
        return True
    except OSError:
        return False


def private_dir() -> str:
    """Linux without XDG_RUNTIME_DIR: a folder only this user can enter."""
    cache = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    candidates = [os.path.join(cache, "clipsd"), os.path.join(tempfile.gettempdir(), f"clipsd-{os.getuid()}")]
    for folder in candidates:
        if len(os.path.join(folder, socket_name())) <= _MAX_UNIX_PATH and _own_private_dir(folder):
            return folder
    return candidates[0]   # listen() fails there and says why; never a shared folder


def socket_path() -> str:
    if os.name == "nt":  # Windows: имя именованного канала QLocalServer
        # the launcher (clipsd_launcher.c) builds the package name "clipsd-<SID>"
        return ("clipsd-" if getattr(sys, "frozen", False) else "clipshot-") + windows_user_id()
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    # a socket path longer than sun_path (108 bytes) cannot be listened on: then the private folder
    if runtime and os.path.isdir(runtime) and len(os.path.join(runtime, socket_name())) <= _MAX_UNIX_PATH:
        return os.path.join(runtime, socket_name())
    return os.path.join(private_dir(), socket_name())


def command_from_args(args) -> str:
    if args == ["--region"]:
        return "region"
    if args == ["--full"]:
        return "full"
    if args == ["--quit"]:
        return "quit"
    if args == ["--quit-for-update"]:   # internal: used by clipsd-switch when python3 is missing
        return QUIT_FOR_UPDATE
    if args == ["--demo"]:
        return "demo"
    if len(args) == 2 and args[0] == "--open":
        return "open:" + os.path.abspath(args[1])
    return ""


def request(command: str, timeout: float = 5.0, path: str = ""):
    """Send a command and read one reply line. None: no running copy (or Windows); "" no reply."""
    if not hasattr(socket, "AF_UNIX") or os.name == "nt":
        return None
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(path or socket_path())
            sock.sendall(command.encode())
            data = b""
            try:
                while b"\n" not in data and len(data) < 64:
                    chunk = sock.recv(64)
                    if not chunk:
                        break
                    data += chunk
            except OSError:   # timeout: the program does not answer
                pass
            return data.decode("ascii", "replace").strip()
    except OSError:
        return None


def send(command: str) -> bool:
    """Передать команду запущенной копии. False — фоновая копия не запущена (или Windows)."""
    if command == QUIT_FOR_UPDATE:
        # Prints the reply for clipsd-switch: ok | busy | none (no running copy or no answer).
        # Always True, so that the entry point never starts the program for this command.
        reply = request(command) or "none"
        try:
            print(reply, flush=True)
        except (AttributeError, OSError):   # windowed build without a console
            pass
        return True
    if not hasattr(socket, "AF_UNIX") or os.name == "nt":
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(1.0)
            sock.connect(socket_path())
            sock.sendall(command.encode())
        return True
    except OSError:
        return False
