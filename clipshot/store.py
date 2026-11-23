# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Microsoft Store build (MSIX package, packaging/windows-store): package identity, the Store page,
start at login through the StartupTask of the package.

- A Store build (build_info.is_store(), or any process with an MSIX package identity) never updates
  itself: the Store installs new versions. updater.install_kind() returns "store", "Check for updates"
  opens store_url().
- Start at login: the manifest declares uap5:StartupTask TaskId=STARTUP_TASK_ID with Enabled="false"; the
  first start shows a card with "Start ClipSD with Windows", ticked (store_welcome.py), and turns the task on
  when the person closes it ticked: the consent that Store policy 10.2.8 asks for, the same choice as the
  ticked option of the Setup.exe installer (owner's decision 19.11.2026). A packaged app
  cannot use a shortcut in the Startup folder: new files under AppData are redirected into the private
  folder of the package, Windows never sees that shortcut. The checkbox of the settings window reads and
  changes the task through Windows.ApplicationModel.StartupTask (WinRT, called with ctypes: no extra
  packages in the build). For a packaged desktop app RequestEnableAsync shows no dialog. The person
  stays in control in Windows Settings > Apps > Startup; if they turned ClipSD off there
  (DisabledByUser) the program may not turn it on again, it opens that page instead.
- Nothing here does anything outside Windows or without a package identity: the functions answer
  "" / False / "unavailable".
"""

import os
import threading
import time
import urllib.parse

from . import build_info

STARTUP_TASK_ID = "ClipSDStartup"   # TaskId of uap5:StartupTask in packaging/windows-store/AppxManifest.xml.in
STARTUP_SETTINGS_URL = "ms-settings:startupapps"   # Windows Settings > Apps > Startup
STORE_PDP = "ms-windows-store://pdp/"

# Windows.ApplicationModel.StartupTaskState
STATES = {0: "disabled", 1: "disabled_by_user", 2: "enabled", 3: "disabled_by_policy", 4: "enabled_by_policy"}
ENABLED_STATES = ("enabled", "enabled_by_policy")
UNAVAILABLE = "unavailable"   # no package identity, not Windows, or the WinRT call failed
WINRT_TIMEOUT_S = 10

_backend = None   # tests: an object with state(), enable(), disable() returning STATES values


class StartupError(Exception):
    """The start at login could not be set as asked; state is the resulting StartupTaskState
    ("disabled_by_user", "disabled_by_policy", "enabled_by_policy") or UNAVAILABLE."""

    def __init__(self, state: str, detail: str = ""):
        super().__init__(f"{state}: {detail}" if detail else state)
        self.state = state
        self.detail = detail


# --- package identity ------------------------------------------------------------------------------

ERROR_INSUFFICIENT_BUFFER = 122   # the process has a package; APPMODEL_ERROR_NO_PACKAGE (15700) when not


def _package_string(function: str) -> str:
    if os.name != "nt":
        return ""
    try:
        import ctypes
        func = getattr(ctypes.windll.kernel32, function)
        length = ctypes.c_uint32(0)
        if func(ctypes.byref(length), None) != ERROR_INSUFFICIENT_BUFFER or not length.value:
            return ""
        buf = ctypes.create_unicode_buffer(length.value)
        if func(ctypes.byref(length), buf) != 0:
            return ""
        return buf.value
    except (AttributeError, OSError, ValueError):
        return ""


def package_full_name() -> str:
    """Full name of the MSIX package this process runs from ("" when not packaged)."""
    return _package_string("GetCurrentPackageFullName")


def package_family_name() -> str:
    return _package_string("GetCurrentPackageFamilyName")


def has_package_identity() -> bool:
    return bool(package_full_name())


def is_store_build() -> bool:
    """Built for the Store, or running with a package identity: updates come from the Store only."""
    return build_info.is_store() or has_package_identity()


def store_url() -> str:
    """Product page in the Store app: by the Store ID from Partner Center, else by the package family
    name of this process; "" when neither is known (the caller opens the website)."""
    product = build_info.store_product_id()
    if product:
        return STORE_PDP + "?productid=" + urllib.parse.quote(product, safe="")
    family = package_family_name()
    if family:
        return STORE_PDP + "?PFN=" + urllib.parse.quote(family, safe="")
    return ""


def open_startup_settings() -> bool:
    from .sysenv import open_url
    return open_url(STARTUP_SETTINGS_URL)


# --- start at login (StartupTask) -----------------------------------------------------------------

def startup_state() -> str:
    """One of STATES values, or UNAVAILABLE."""
    if not has_package_identity():
        return UNAVAILABLE
    try:
        return _startup_call("state")
    except (OSError, StartupError):
        return UNAVAILABLE


def startup_enabled() -> bool:
    return startup_state() in ENABLED_STATES


def set_startup(enabled: bool) -> str:
    """Turn the start at login on or off. Returns the new state; raises StartupError when the result is
    not what was asked (turned off by the person in Windows Settings, decided by a policy, no package)."""
    if not has_package_identity():
        raise StartupError(UNAVAILABLE, "no package identity")
    try:
        state = _startup_call("enable" if enabled else "disable")
    except OSError as exc:
        raise StartupError(UNAVAILABLE, str(exc)) from exc
    if (state in ENABLED_STATES) != bool(enabled):
        raise StartupError(state)
    return state


def selfcheck_lines() -> list:
    """For the selfcheck of a Store build: the package and the state of the start at login."""
    full = package_full_name()
    lines = [f"package: {full or 'none'}"]
    if full:
        lines.append(f"startup task: {startup_state()}")
    return lines


def _startup_call(action: str) -> str:
    """Run one StartupTask action in its own thread (multithreaded apartment): the Qt main thread is a
    single-threaded apartment, waiting there for a WinRT operation could block it."""
    if _backend is not None:
        return getattr(_backend, action)()
    result = {}

    def work():
        try:
            result["state"] = _winrt_startup(action)
        except Exception as exc:   # noqa: BLE001 (reported to the caller as OSError)
            result["error"] = exc

    thread = threading.Thread(target=work, name="clipsd-startup-task", daemon=True)
    thread.start()
    thread.join(WINRT_TIMEOUT_S + 2)
    if thread.is_alive():
        raise OSError("StartupTask: no answer from Windows")
    if "error" in result:
        error = result["error"]
        raise error if isinstance(error, OSError) else OSError(f"StartupTask: {error}")
    return result["state"]


# --- WinRT through ctypes -------------------------------------------------------------------------
# Vtable slots (IUnknown 0-2, IInspectable 3-5), checked against the Windows SDK metadata (windows-rs):
#   IStartupTaskStatics {EE5B60BD-A148-41A7-B26E-E8B88A1E62F8}: 6 GetForCurrentPackageAsync, 7 GetAsync(HSTRING, op**)
#   IStartupTask {F75C23C8-B5F2-4F6C-88DD-36CB1D599D17}: 6 RequestEnableAsync(op**), 7 Disable(), 8 get_State(int*)
#   IAsyncOperation<T>: 6 put_Completed, 7 get_Completed, 8 GetResults(T*)
#   IAsyncInfo {00000036-0000-0000-C000-000000000046}: 6 get_Id, 7 get_Status(int*), 8 get_ErrorCode(HRESULT*)
IID_STARTUP_TASK_STATICS = "EE5B60BD-A148-41A7-B26E-E8B88A1E62F8"
IID_ASYNC_INFO = "00000036-0000-0000-C000-000000000046"
STARTUP_TASK_CLASS = "Windows.ApplicationModel.StartupTask"
RO_INIT_MULTITHREADED = 1
ASYNC_STARTED, ASYNC_COMPLETED = 0, 1


def _winrt_startup(action: str) -> str:
    import ctypes
    from ctypes import POINTER, byref, c_int32, c_long, c_uint32, c_void_p, c_wchar_p

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16), ("Data3", ctypes.c_uint16),
                    ("Data4", ctypes.c_ubyte * 8)]

    def guid(text):
        import uuid
        u = uuid.UUID(text)
        g = GUID(u.fields[0], u.fields[1], u.fields[2])
        for i, b in enumerate(u.bytes[8:]):
            g.Data4[i] = b
        return g

    def check(hr, what):
        if hr < 0:
            raise OSError(f"{what}: HRESULT 0x{hr & 0xFFFFFFFF:08X}")

    def method(obj, index, *argtypes):
        vtable = ctypes.cast(obj, POINTER(POINTER(c_void_p))).contents
        return ctypes.WINFUNCTYPE(c_long, c_void_p, *argtypes)(vtable[index])

    def release(obj):
        if obj:
            ctypes.WINFUNCTYPE(c_uint32, c_void_p)(ctypes.cast(obj, POINTER(POINTER(c_void_p))).contents[2])(obj)

    combase = ctypes.windll.combase
    combase.RoInitialize.argtypes = [c_int32]
    combase.RoInitialize.restype = c_long
    combase.WindowsCreateString.argtypes = [c_wchar_p, c_uint32, POINTER(c_void_p)]
    combase.WindowsCreateString.restype = c_long
    combase.WindowsDeleteString.argtypes = [c_void_p]
    combase.WindowsDeleteString.restype = c_long
    combase.RoGetActivationFactory.argtypes = [c_void_p, POINTER(GUID), POINTER(c_void_p)]
    combase.RoGetActivationFactory.restype = c_long

    def hstring(text):
        h = c_void_p()
        check(combase.WindowsCreateString(text, len(text), byref(h)), "WindowsCreateString")
        return h

    def wait(op, what):
        """Poll the operation (no completion handler: nothing to implement in ctypes) and return it."""
        info = c_void_p()
        check(method(op, 0, POINTER(GUID), POINTER(c_void_p))(op, byref(guid(IID_ASYNC_INFO)), byref(info)),
              f"{what}: IAsyncInfo")
        try:
            status = c_int32(ASYNC_STARTED)
            deadline = time.monotonic() + WINRT_TIMEOUT_S
            while True:
                check(method(info, 7, POINTER(c_int32))(info, byref(status)), f"{what}: Status")
                if status.value != ASYNC_STARTED:
                    break
                if time.monotonic() > deadline:
                    raise OSError(f"{what}: timeout")
                time.sleep(0.02)
            if status.value != ASYNC_COMPLETED:
                code = c_long(0)
                method(info, 8, POINTER(c_long))(info, byref(code))
                raise OSError(f"{what}: status {status.value}, HRESULT 0x{code.value & 0xFFFFFFFF:08X}")
        finally:
            release(info)

    initialized = combase.RoInitialize(RO_INIT_MULTITHREADED) >= 0
    class_name = task_id = None
    statics = op = task = op2 = None
    try:
        class_name = hstring(STARTUP_TASK_CLASS)
        task_id = hstring(STARTUP_TASK_ID)
        statics = c_void_p()
        check(combase.RoGetActivationFactory(class_name, byref(guid(IID_STARTUP_TASK_STATICS)), byref(statics)),
              "RoGetActivationFactory(StartupTask)")
        op = c_void_p()
        check(method(statics, 7, c_void_p, POINTER(c_void_p))(statics, task_id, byref(op)), "StartupTask.GetAsync")
        wait(op, "StartupTask.GetAsync")
        task = c_void_p()
        check(method(op, 8, POINTER(c_void_p))(op, byref(task)), "StartupTask.GetAsync result")
        if not task:
            raise OSError(f"no StartupTask {STARTUP_TASK_ID} in the package manifest")
        state = c_int32(0)
        if action == "enable":
            op2 = c_void_p()
            check(method(task, 6, POINTER(c_void_p))(task, byref(op2)), "StartupTask.RequestEnableAsync")
            wait(op2, "StartupTask.RequestEnableAsync")
            check(method(op2, 8, POINTER(c_int32))(op2, byref(state)), "StartupTask.RequestEnableAsync result")
        else:
            if action == "disable":
                check(method(task, 7)(task), "StartupTask.Disable")
            check(method(task, 8, POINTER(c_int32))(task, byref(state)), "StartupTask.State")
        return STATES.get(state.value, UNAVAILABLE)
    finally:
        for obj in (op2, task, op, statics):
            release(obj)
        for h in (task_id, class_name):
            if h:
                combase.WindowsDeleteString(h)
        if initialized:
            combase.RoUninitialize()
