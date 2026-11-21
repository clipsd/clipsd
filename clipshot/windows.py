# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Список открытых окон для «Снимка окна» (окно выделения: чип «Окна ▾» и клавиша W).

Откуда берётся список:
- GNOME (Wayland): дополнение ClipSD внутри GNOME Shell, метод ListWindows (JSON). Только сам Shell знает все окна
  и их место: обычной программе под Wayland список окон не дают, а org.gnome.Shell.Introspect.GetWindows отвечает
  AccessDenied всем, кроме портала, и места окна не сообщает (GNOME 50.1, misc/introspect.js).
- Дополнение старое (нет ListWindows) или не стоит: окна XWayland через EWMH (_NET_CLIENT_LIST_STACKING). Список
  неполный: окна, которые работают прямо под Wayland, сюда не попадают. Окно выделения предлагает обновить дополнение.
- X11 без GNOME (KDE, XFCE, Cinnamon, MATE): EWMH, список полный.
- Windows: EnumWindows, видимая рамка DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS), скрытые окна
  (DWMWA_CLOAKED: другой рабочий стол, приостановленные программы Store) пропускаются.

Список просится в момент Alt+W, вместе со снимком стола, и приходит сигналом (WindowLister): медленное или зависшее
дополнение не задерживает окно выделения. Содержимое одного окна, закрытого другими, тоже приходит сигналом
(WindowGrab): дополнение GNOME рисует окно отдельно (paint_to_content), Windows через PrintWindow.

Названия окон показываются только на экране: в настройки, журнал и файлы они не пишутся.
Координаты в списке: глобальные логические точки Qt, те же, что у окна выделения (grab.virtual_geometry)."""

import json
import os
import sys
from dataclasses import dataclass, field

from PyQt6.QtCore import QCoreApplication, QObject, QPoint, QRect, QTimer, pyqtSignal
from PyQt6.QtGui import QGuiApplication

try:  # QtDBus есть только в Linux-сборках PyQt6
    from PyQt6.QtDBus import QDBusConnection, QDBusError, QDBusMessage
except ImportError:
    QDBusConnection = QDBusError = QDBusMessage = None

EXT_SERVICE = "org.gnome.Shell"
EXT_PATH = "/org/gnome/Shell/Extensions/ClipSD"
EXT_IFACE = "org.gnome.Shell.Extensions.ClipSD"

EXT_OK, EXT_OLD, EXT_MISSING = "ok", "old", "missing"   # дополнение GNOME: новое, без ListWindows, нет совсем
EXT_SLOW = "slow"        # дополнение не ответило вовремя (Shell занят): это не «старое», кнопка «Обновить» не нужна
LIST_TIMEOUT_MS = 1500   # дольше человек не ждёт: пока показывается неполный список EWMH, ответ ждётся дальше
LIST_WAIT_MS = 6000      # столько ждётся настоящий ответ дополнения; пришёл: список заменяется полным
GRAB_TIMEOUT_MS = 4000   # содержимое большого окна: PNG кодируется в Shell (замер 2560x1400: около 0,1 с)
NO_REPLY = ("org.freedesktop.DBus.Error.NoReply", "org.freedesktop.DBus.Error.Timeout",
            "org.freedesktop.DBus.Error.TimedOut")


@dataclass
class WinInfo:
    id: str                 # идентификатор окна у источника (Mutter id, XID, HWND)
    title: str
    app: str                # название программы (GNOME), имя exe без расширения (Windows), WM_CLASS (X11)
    icon: str = ""          # имя значка темы или путь к значку (GNOME, X11), путь к программе (Windows) или пусто
    rect: QRect = field(default_factory=QRect)   # видимая рамка окна без тени, глобальные точки Qt
    monitor: int = 0
    minimized: bool = False
    focused: bool = False
    z: int = 0              # порядок наложения: больше = выше
    pid: int = 0
    source: str = ""        # gnome-ext | ewmh | win32
    app_name: str = ""      # понятное имя программы для списка: описание exe (Windows), Name из .desktop (X11)


def display_app(win: WinInfo) -> str:
    """Имя программы, как его видит человек: app_name, иначе app (имя exe или WM_CLASS из строчных букв: с заглавной)."""
    name = " ".join((win.app_name or win.app or "").split())
    if name and name == name.lower():
        name = name[:1].upper() + name[1:]
    return name


# Слова, которые есть в именах многих программ и сами программу не называют: по ним дубль не ищется
_GENERIC_WORDS = {"microsoft", "windows", "google", "mozilla", "apple", "adobe", "corporation", "desktop", "app",
                  "application", "client", "the", "for", "and", "pro", "beta", "x64", "x86", "64", "32", "bit"}
APP_NAME_MAX = 28   # дальше имя программы обрезается («…»)


def _words(text: str) -> list:
    import re
    return re.findall(r"\w+", text.casefold())


def menu_app_name(title: str, app: str) -> str:
    """Имя программы для строки списка окон или пусто, если оно уже есть в заголовке: «ClipSD - Google Chrome»
    (Google Chrome), «Отчёт.docx - Word» (Microsoft Word: «Word» отдельным словом), «Telegram (3)» (Telegram
    Desktop). Общие слова (Microsoft, Windows, Google, Desktop) за имя программы не считаются."""
    app = " ".join((app or "").split())
    if not app:
        return ""
    t, a = " ".join((title or "").split()).casefold(), app.casefold()
    if a in t:
        return ""
    title_words = set(_words(t))
    if any(len(w) >= 3 and w not in _GENERIC_WORDS and w in title_words for w in _words(a)):
        return ""
    if len(app) > APP_NAME_MAX:
        app = app[:APP_NAME_MAX - 1].rstrip() + "…"
    return app


@dataclass
class WindowList:
    windows: list
    source: str             # gnome-ext | ewmh | win32 | none
    complete: bool          # False: видны не все окна (только XWayland)
    ext_state: str = ""     # только GNOME: EXT_OK, EXT_OLD, EXT_MISSING, EXT_SLOW
    final: bool = True      # False: временный список, пока ждётся ответ дополнения (придёт ещё один)
    failed: bool = False    # список не получен из-за ошибки (Windows): окно выделения работает как раньше


# --- пересчёт координат -------------------------------------------------------

def _qt_screens():
    return sorted(QGuiApplication.screens(), key=lambda s: (s.geometry().x(), s.geometry().y()))


def _union(rects):
    out = QRect()
    for r in rects:
        out = out.united(r)
    return out


def map_monitor_rect(rect: QRect, mon: dict, screens) -> QRect:
    """Прямоугольник в координатах Shell (логические точки сцены) -> глобальные точки Qt.

    ClipSD под Wayland работает через XWayland: при дробном масштабе и разном масштабе мониторов сетки Shell и Qt
    расходятся. Поэтому пересчёт идёт по монитору: место внутри монитора Shell переносится на тот же монитор Qt
    (мониторы сопоставляются по порядку слева направо, сверху вниз)."""
    qs = screens[min(max(mon.get("order", 0), 0), len(screens) - 1)].geometry()
    kx, ky = qs.width() / max(1, mon["w"]), qs.height() / max(1, mon["h"])
    return QRect(qs.x() + round((rect.x() - mon["x"]) * kx), qs.y() + round((rect.y() - mon["y"]) * ky),
                 max(1, round(rect.width() * kx)), max(1, round(rect.height() * ky)))


def map_stage_rect(rect: QRect, stage: QRect, virtual: QRect) -> QRect:
    """Запасной пересчёт, когда число мониторов у Shell и у Qt разное (монитор как раз подключают или снимают):
    весь стол Shell растягивается на весь стол Qt."""
    kx, ky = virtual.width() / max(1, stage.width()), virtual.height() / max(1, stage.height())
    return QRect(virtual.x() + round((rect.x() - stage.x()) * kx), virtual.y() + round((rect.y() - stage.y()) * ky),
                 max(1, round(rect.width() * kx)), max(1, round(rect.height() * ky)))


def parse_shell_json(text: str, screens=None) -> list:
    """Ответ ListWindows дополнения: {"windows": [...], "monitors": [...]} -> [WinInfo] сверху вниз по наложению."""
    data = json.loads(text)
    screens = list(screens if screens is not None else _qt_screens())
    monitors = list(data.get("monitors") or [])
    for i, m in enumerate(sorted(monitors, key=lambda m: (m["x"], m["y"]))):
        m["order"] = i
    by_index = {m["index"]: m for m in monitors}
    same = bool(screens) and len(monitors) == len(screens)
    stage = _union(QRect(m["x"], m["y"], m["w"], m["h"]) for m in monitors)
    virtual = _union(s.geometry() for s in screens)
    out = []
    for w in data.get("windows", []):
        mon = by_index.get(w.get("monitor", 0))
        r = QRect(int(w["x"]), int(w["y"]), int(w["w"]), int(w["h"]))
        if same and mon is not None:
            rect = map_monitor_rect(r, mon, screens)
        elif not stage.isEmpty() and not virtual.isEmpty():
            rect = map_stage_rect(r, stage, virtual)
        else:
            rect = r
        out.append(WinInfo(id=str(w.get("id", "")), title=w.get("title") or "", app=w.get("app") or "",
                           icon=w.get("icon") or "", rect=rect, monitor=(mon or {}).get("order", 0),
                           minimized=bool(w.get("minimized")), focused=bool(w.get("focused")),
                           z=int(w.get("z", 0)), pid=int(w.get("pid", 0) or 0), source="gnome-ext"))
    out.sort(key=lambda i: -i.z)
    return out


UNKNOWN_METHOD = "org.freedesktop.DBus.Error.UnknownMethod"


def ext_state_from_introspect(xml: str) -> str:
    """GDBus отвечает UnknownMethod и когда нет метода (старое дополнение), и когда нет самого объекта (дополнения
    нет или оно выключено); текст ошибки переведён на язык системы, по нему не различить. Различает описание объекта:
    есть интерфейс ClipSD, значит дополнение есть, но старое."""
    return EXT_OLD if f'interface name="{EXT_IFACE}"' in (xml or "") else EXT_MISSING


def ext_state_on_disk(state: str) -> str:
    """Дополнения в Shell нет, но оно лежит в папке пользователя (выключено или ждёт входа): помочь может то же
    «Обновить» (поставит и включит), а не «Установить»."""
    if state != EXT_MISSING:
        return state
    try:
        from . import gnome_ext
        return EXT_OLD if gnome_ext.installed_any() else state
    except Exception:   # noqa: BLE001 — проверка папки не должна мешать списку
        return state


# --- X11 и XWayland: EWMH -------------------------------------------------------

_desktop_cache = {"key": None, "by_wmclass": {}, "by_id": {}}


def _applications_dirs() -> list:
    data_home = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    dirs = [data_home] + (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
    return [os.path.join(d, "applications") for d in dirs if d]


def _read_desktop(path: str):
    """Раздел [Desktop Entry] файла .desktop: {ключ: значение} или None (не программа, скрытый, не читается)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read(65536)
    except OSError:
        return None
    entry, inside = {}, False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("["):
            if inside:
                break
            inside = line == "[Desktop Entry]"
            continue
        if inside and "=" in line and not line.startswith("#"):
            k, _sep, v = line.partition("=")
            entry.setdefault(k.strip(), v.strip())
    if entry.get("Type", "Application") != "Application" or entry.get("Hidden", "").lower() == "true":
        return None
    return entry


def _desktop_index():
    """Файлы .desktop из папок XDG (свои раньше системных): по StartupWMClass и по имени файла. Перечитываются,
    только если папки изменились (поставили или удалили программу)."""
    dirs = []
    for d in _applications_dirs():
        try:
            dirs.append((d, os.stat(d).st_mtime_ns))
        except OSError:
            continue
    key = tuple(dirs)
    if _desktop_cache["key"] == key:
        return _desktop_cache["by_wmclass"], _desktop_cache["by_id"]
    by_wmclass, by_id = {}, {}
    for d, _m in dirs:
        try:
            names = sorted(n for n in os.listdir(d) if n.endswith(".desktop"))
        except OSError:
            continue
        for n in names:
            entry = _read_desktop(os.path.join(d, n))
            if entry is None:
                continue
            wm = entry.get("StartupWMClass", "").casefold()
            if wm:
                by_wmclass.setdefault(wm, entry)
            stem = n[:-len(".desktop")].casefold()
            by_id.setdefault(stem, entry)
            by_id.setdefault(stem.rsplit(".", 1)[-1], entry)   # org.gnome.Nautilus -> nautilus
    _desktop_cache.update(key=key, by_wmclass=by_wmclass, by_id=by_id)
    return by_wmclass, by_id


def desktop_app(wm_class) -> tuple:
    """(Имя программы на языке ClipSD, значок) по WM_CLASS (instance, class) из файла .desktop или ("", "")."""
    try:
        by_wmclass, by_id = _desktop_index()
    except Exception:   # noqa: BLE001 — имя программы не должно мешать списку окон
        return "", ""
    names = [c.casefold() for c in (wm_class[1], wm_class[0]) if c]
    entry = next((by_wmclass[c] for c in names if c in by_wmclass), None) or \
        next((by_id[c] for c in names if c in by_id), None)
    if entry is None:
        return "", ""
    try:
        from .i18n import current
        lang = current()
    except Exception:   # noqa: BLE001
        lang = ""
    name = ""
    if lang:
        name = entry.get(f"Name[{lang}]") or next((v for k, v in entry.items() if k.startswith(f"Name[{lang}_")), "")
    return (name or entry.get("Name", "")), entry.get("Icon", "")

def from_ewmh(screens=None, display_factory=None):
    """Окна по EWMH. Под GNOME Wayland видны только окна XWayland (список неполный).

    Рамка: геометрия X-окна минус невидимая тень (_GTK_FRAME_EXTENTS у окон GTK с рамкой программы) плюс рамка
    оконного менеджера (_NET_FRAME_EXTENTS). Координаты X делятся на масштаб Qt (devicePixelRatio).
    display_factory: подмена Xlib.display.Display в тестах."""
    try:
        from Xlib import X, Xatom
        if display_factory is None:
            from Xlib import display
            display_factory = display.Display
    except ImportError:
        return None
    try:
        disp = display_factory()
    except Exception:   # noqa: BLE001 — нет X-сервера
        return None
    try:
        root = disp.screen().root
        atom = disp.intern_atom

        def prop(win, name, kind=X.AnyPropertyType):
            try:
                p = win.get_full_property(atom(name), kind)
            except Exception:   # noqa: BLE001 — окно закрылось на ходу
                return None
            return p.value if p is not None else None

        ids = prop(root, "_NET_CLIENT_LIST_STACKING") or prop(root, "_NET_CLIENT_LIST") or []
        active = prop(root, "_NET_ACTIVE_WINDOW")
        active = active[0] if active is not None and len(active) else 0
        utf8 = atom("UTF8_STRING")
        ok_types = {atom("_NET_WM_WINDOW_TYPE_NORMAL"), atom("_NET_WM_WINDOW_TYPE_DIALOG")}
        hidden, skip = atom("_NET_WM_STATE_HIDDEN"), atom("_NET_WM_STATE_SKIP_TASKBAR")
        screens = list(screens if screens is not None else _qt_screens())
        dpr = max((s.devicePixelRatio() for s in screens), default=1.0)
        out = []
        for z, xid in enumerate(ids):
            w = disp.create_resource_object("window", xid)
            types = set(prop(w, "_NET_WM_WINDOW_TYPE") or [])
            if types and not types & ok_types:
                continue
            state = set(prop(w, "_NET_WM_STATE") or [])
            if skip in state:
                continue
            name = prop(w, "_NET_WM_NAME", utf8)
            if name is None:
                name = prop(w, "WM_NAME", Xatom.STRING)
            title = name.decode("utf-8", "replace") if isinstance(name, bytes) else str(name or "")
            try:
                cls = w.get_wm_class() or ("", "")
                geo = w.get_geometry()
                pos = w.translate_coords(root, 0, 0)
            except Exception:   # noqa: BLE001 — окно закрылось на ходу
                continue
            x, y = -pos.x, -pos.y
            width, height = geo.width, geo.height
            gtk = prop(w, "_GTK_FRAME_EXTENTS")   # левая, правая, верхняя, нижняя невидимые поля (тень)
            if gtk is not None and len(gtk) == 4:
                x, y = x + gtk[0], y + gtk[2]
                width, height = width - gtk[0] - gtk[1], height - gtk[2] - gtk[3]
            net = prop(w, "_NET_FRAME_EXTENTS")   # рамка оконного менеджера снаружи окна
            if net is not None and len(net) == 4:
                x, y = x - net[0], y - net[2]
                width, height = width + net[0] + net[1], height + net[2] + net[3]
            pid = prop(w, "_NET_WM_PID")
            rect = QRect(round(x / dpr), round(y / dpr), max(1, round(width / dpr)), max(1, round(height / dpr)))
            centre = QPoint(rect.center())
            mon = next((i for i, s in enumerate(screens) if s.geometry().contains(centre)), 0)
            app_name, icon = desktop_app(cls)
            out.append(WinInfo(id=str(xid), title=title, app=cls[1] or cls[0], rect=rect, monitor=mon,
                               minimized=hidden in state, focused=xid == active, z=z,
                               pid=int(pid[0]) if pid is not None and len(pid) else 0, source="ewmh",
                               app_name=app_name, icon=icon or (cls[0] or cls[1] or "").casefold()))
        out.sort(key=lambda i: -i.z)
        return out
    finally:
        try:
            disp.close()
        except Exception:   # noqa: BLE001
            pass


# --- Windows -------------------------------------------------------------------

WS_EX_TOOLWINDOW, WS_EX_APPWINDOW = 0x80, 0x40000


def alt_tab_like(rec: dict) -> bool:
    """Окно попадает в список, как в Alt+Tab: видимое, не служебное (WS_EX_TOOLWINDOW), без владельца или
    с WS_EX_APPWINDOW, не скрытое DWM (DWMWA_CLOAKED), с названием. rec: visible, exstyle, owner, cloaked, title."""
    if not rec["visible"] or rec["cloaked"] or not rec["title"].strip():
        return False
    if rec["exstyle"] & WS_EX_TOOLWINDOW:
        return False
    return not rec["owner"] or bool(rec["exstyle"] & WS_EX_APPWINDOW)


def win32_records_to_list(records, screens, exclude=()) -> list:
    """Записи окон Windows сверху вниз (как отдаёт EnumWindows) -> [WinInfo]. Отдельно от ctypes: проверяется
    в тестах на Linux. rec: hwnd, title, exe, pid, visible, exstyle, owner, cloaked, iconic, frame (x, y, w, h)
    в физических пикселях, foreground."""
    out = []
    n = len(records)
    for i, rec in enumerate(records):
        if rec["hwnd"] in exclude or not alt_tab_like(rec):
            continue
        if rec["iconic"]:
            rect, mon = QRect(), 0   # у свёрнутого окна Windows места нет (-32000), а PrintWindow его не снимает
        else:
            rect, mon = win_physical_to_qt(*rec["frame"], screens)
        exe = rec.get("exe") or ""
        shown = rec.get("app_exe", exe) or ""   # программа окна: у рамки магазинного приложения та, что внутри
        if is_host_exe(shown):
            shown = ""   # «Application Frame Host» человеку ничего не говорит: имя приложения уже в заголовке
        out.append(WinInfo(id=str(rec["hwnd"]), title=rec["title"], app=exe_stem(shown), icon=shown, rect=rect,
                           monitor=mon, minimized=bool(rec["iconic"]), focused=bool(rec.get("foreground")), z=n - i,
                           pid=int(rec.get("pid") or 0), source="win32",
                           app_name=(rec.get("desc") or "") if shown else ""))
    return out


# Процессы-рамки магазинных приложений Windows (UWP): само приложение работает в другом процессе, его окно
# Windows.UI.Core.CoreWindow лежит внутри рамки
HOST_EXES = {"applicationframehost", "wwahost"}


def exe_stem(path: str) -> str:
    return os.path.splitext(os.path.basename((path or "").replace("\\", "/")))[0]


def is_host_exe(path: str) -> bool:
    return exe_stem(path).casefold() in HOST_EXES


_desc_cache = {}
FILE_VER_GET_LOCALISED = 0x01   # описание на языке Windows (у системных программ оно в файле .mui)


def _version_api():
    import ctypes
    from ctypes import wintypes
    v = ctypes.WinDLL("version")
    LPCWSTR, DWORD, BOOL, UINT = wintypes.LPCWSTR, wintypes.DWORD, wintypes.BOOL, wintypes.UINT
    v.GetFileVersionInfoSizeExW.restype = DWORD
    v.GetFileVersionInfoSizeExW.argtypes = [DWORD, LPCWSTR, ctypes.POINTER(DWORD)]
    v.GetFileVersionInfoExW.restype = BOOL
    v.GetFileVersionInfoExW.argtypes = [DWORD, LPCWSTR, DWORD, DWORD, ctypes.c_void_p]
    v.VerQueryValueW.restype = BOOL
    v.VerQueryValueW.argtypes = [ctypes.c_void_p, LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(UINT)]
    return v


def _read_description(path: str, api) -> str:
    import ctypes
    from ctypes import wintypes
    handle = wintypes.DWORD(0)
    size = api.GetFileVersionInfoSizeExW(FILE_VER_GET_LOCALISED, path, ctypes.byref(handle))
    if not size or size > (1 << 22):
        return ""
    buf = ctypes.create_string_buffer(size)
    if not api.GetFileVersionInfoExW(FILE_VER_GET_LOCALISED, path, 0, size, buf):
        return ""
    ptr, n = ctypes.c_void_p(), wintypes.UINT(0)
    pairs = []
    if api.VerQueryValueW(buf, "\\VarFileInfo\\Translation", ctypes.byref(ptr), ctypes.byref(n)) \
            and ptr.value and n.value >= 4:
        arr = (ctypes.c_uint16 * (min(n.value, 64) // 2)).from_address(ptr.value)
        pairs = [(arr[i], arr[i + 1]) for i in range(0, len(arr) - 1, 2)]
    for lang, cp in pairs + [(0x0409, 0x04B0), (0x0409, 0x04E4), (0x0000, 0x04B0)]:
        sub = f"\\StringFileInfo\\{lang:04X}{cp:04X}\\FileDescription"
        ptr, n = ctypes.c_void_p(), wintypes.UINT(0)
        if api.VerQueryValueW(buf, sub, ctypes.byref(ptr), ctypes.byref(n)) and ptr.value and n.value > 0:
            text = " ".join(ctypes.wstring_at(ptr.value, min(n.value, 512)).split("\0", 1)[0].split())
            if text:
                return text
    return ""


# Типы дисков GetDriveTypeW. Описание и значок программы читаются в потоке интерфейса (при Alt+W и в меню окон):
# только с дисков этого компьютера. Сетевой диск (подключённый Z: или путь \\сервер\папка) мог бы задержать окно
# выделения, пока отвечает (или не отвечает) сервер (1.34.1, В2 проверки 1.34.0).
DRIVE_REMOVABLE, DRIVE_FIXED, DRIVE_REMOTE, DRIVE_CDROM, DRIVE_RAMDISK = 2, 3, 4, 5, 6
LOCAL_DRIVES = (DRIVE_REMOVABLE, DRIVE_FIXED, DRIVE_RAMDISK)
DRIVE_CACHE_S = 60.0   # подключение диска меняется редко: тип запоминается на минуту
_drive_cache = {}


def _drive_type_win(root: str) -> int:
    """GetDriveTypeW для корня «C:\\». Сам вызов к серверу не обращается: тип берётся из списка дисков Windows."""
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32")
    fn = kernel32.GetDriveTypeW
    fn.argtypes = [wintypes.LPCWSTR]
    fn.restype = wintypes.UINT
    return int(fn(root))


def is_local_path(path: str, now: float = None) -> bool:
    r"""Путь на диске этого компьютера (встроенный, съёмный, RAM-диск), а не сетевой. UNC (\\сервер\…, //…,
    \\?\UNC\…), путь без буквы диска, сетевой и CD-диск, любая ошибка: False (покажется имя exe и буква)."""
    import time
    p = (path or "").replace("/", "\\")
    if p.startswith("\\\\?\\") or p.startswith("\\\\.\\"):
        p = p[4:]
        if p[:4].upper() == "UNC\\":
            return False
    if len(p) < 3 or p[1] != ":" or p[2] != "\\" or not p[0].isalpha():
        return False   # UNC и всё, где нет буквы диска
    root = p[0].upper() + ":\\"
    now = time.monotonic() if now is None else now
    hit = _drive_cache.get(root)
    if hit is not None and 0 <= now - hit[1] < DRIVE_CACHE_S:
        return hit[0]
    try:
        local = _drive_type_win(root) in LOCAL_DRIVES
    except Exception:   # noqa: BLE001 (не знаем, какой это диск: как сетевой)
        local = False
    _drive_cache[root] = (local, now)
    return local


def file_description(path: str, api=None) -> str:
    """Описание файла программы Windows (FileDescription из ресурса версии: «Microsoft Word», «Проводник»,
    «Google Chrome») или пусто. Запоминается по пути: при каждом Alt+W файлы заново не читаются.
    api: подмена version.dll в тестах (GetFileVersionInfoSizeExW, GetFileVersionInfoExW, VerQueryValueW)."""
    if not path:
        return ""
    key = path.casefold()
    if key in _desc_cache:
        return _desc_cache[key]
    if not is_local_path(path):
        return ""   # сетевой диск: не ждать сервер в потоке интерфейса (не запоминается: диск могут переподключить)
    try:
        desc = _read_description(path, api if api is not None else _version_api())
    except Exception:   # noqa: BLE001 — нет ресурса версии, файл недоступен: покажется имя exe
        desc = ""
    if len(_desc_cache) > 512:
        _desc_cache.clear()
    _desc_cache[key] = desc
    return desc


def win_physical_to_qt(x, y, w, h, screens):
    """Физические пиксели Windows -> точки Qt: Qt 6 оставляет левый верхний угол монитора в физических координатах
    и делит на масштаб только смещение внутри монитора («Qt 6 is Per-Monitor DPI Aware V2 by default»)."""
    cx, cy = x + w // 2, y + h // 2
    for i, s in enumerate(screens):
        g, k = s.geometry(), s.devicePixelRatio()
        if g.x() <= cx < g.x() + g.width() * k and g.y() <= cy < g.y() + g.height() * k:
            return QRect(g.x() + round((x - g.x()) / k), g.y() + round((y - g.y()) / k),
                         max(1, round(w / k)), max(1, round(h / k))), i
    return QRect(x, y, w, h), 0


def _win32_libs():
    """Свои экземпляры user32, dwmapi, kernel32, gdi32 с объявленными типами. Свои, а не ctypes.windll: типы,
    заданные здесь, не меняют вызовы в других местах программы (selector.force_foreground). Без типов ctypes
    принимает 64-битный номер окна за int и падает (ArgumentError) или режет его (проверка 1.33, В6)."""
    import ctypes
    from ctypes import wintypes
    user32, dwm, kernel32, gdi32 = (ctypes.WinDLL(n) for n in ("user32", "dwmapi", "kernel32", "gdi32"))
    HWND, BOOL, INT, UINT, DWORD = wintypes.HWND, wintypes.BOOL, ctypes.c_int, wintypes.UINT, wintypes.DWORD
    enum_proc = ctypes.WINFUNCTYPE(BOOL, HWND, wintypes.LPARAM)
    sig = {
        (user32, "EnumWindows"): (BOOL, [enum_proc, wintypes.LPARAM]),
        (user32, "EnumChildWindows"): (BOOL, [HWND, enum_proc, wintypes.LPARAM]),
        (user32, "GetClassNameW"): (INT, [HWND, wintypes.LPWSTR, INT]),
        (user32, "GetForegroundWindow"): (HWND, []),
        (user32, "GetWindowTextLengthW"): (INT, [HWND]),
        (user32, "GetWindowTextW"): (INT, [HWND, wintypes.LPWSTR, INT]),
        (user32, "GetWindowThreadProcessId"): (DWORD, [HWND, ctypes.POINTER(DWORD)]),
        (user32, "IsWindowVisible"): (BOOL, [HWND]),
        (user32, "IsWindow"): (BOOL, [HWND]),
        (user32, "IsIconic"): (BOOL, [HWND]),
        (user32, "GetWindowLongPtrW"): (ctypes.c_ssize_t, [HWND, INT]),
        (user32, "GetWindow"): (HWND, [HWND, UINT]),
        (user32, "GetWindowRect"): (BOOL, [HWND, ctypes.POINTER(wintypes.RECT)]),
        (user32, "PrintWindow"): (BOOL, [HWND, wintypes.HDC, UINT]),
        (user32, "GetDC"): (wintypes.HDC, [HWND]),
        (user32, "ReleaseDC"): (INT, [HWND, wintypes.HDC]),
        (dwm, "DwmGetWindowAttribute"): (ctypes.c_long, [HWND, DWORD, ctypes.c_void_p, DWORD]),
        (kernel32, "OpenProcess"): (wintypes.HANDLE, [DWORD, BOOL, DWORD]),
        (kernel32, "QueryFullProcessImageNameW"): (BOOL, [wintypes.HANDLE, DWORD, wintypes.LPWSTR, ctypes.POINTER(DWORD)]),
        (kernel32, "CloseHandle"): (BOOL, [wintypes.HANDLE]),
        (gdi32, "CreateCompatibleDC"): (wintypes.HDC, [wintypes.HDC]),
        (gdi32, "CreateCompatibleBitmap"): (wintypes.HBITMAP, [wintypes.HDC, INT, INT]),
        (gdi32, "SelectObject"): (wintypes.HGDIOBJ, [wintypes.HDC, wintypes.HGDIOBJ]),
        (gdi32, "DeleteObject"): (BOOL, [wintypes.HGDIOBJ]),
        (gdi32, "DeleteDC"): (BOOL, [wintypes.HDC]),
        (gdi32, "GetDIBits"): (INT, [wintypes.HDC, wintypes.HBITMAP, UINT, UINT, ctypes.c_void_p, ctypes.c_void_p, UINT]),
    }
    for (lib, name), (res, args) in sig.items():
        fn = getattr(lib, name)
        fn.restype, fn.argtypes = res, args
    return user32, dwm, kernel32, gdi32, enum_proc


def _win32_records():
    """Сырые записи окон Windows через ctypes (сверху вниз по наложению). Окно, которое не прочиталось (закрылось
    на ходу), пропускается; ошибка самого перечисления уходит наверх (WindowLister показывает «список не получен»)."""
    user32, dwm, kernel32, _gdi32, enum_proc = _win32_libs()
    foreground = user32.GetForegroundWindow() or 0
    hwnds = []
    proc = enum_proc(lambda h, _l: hwnds.append(h) or True)
    if not user32.EnumWindows(proc, 0):
        raise OSError("EnumWindows")
    out = []
    for hwnd in hwnds:
        try:
            out.append(_win32_record(hwnd, foreground, user32, dwm, kernel32, enum_proc))
        except Exception as exc:   # noqa: BLE001 — одно окно не прочиталось: список без него
            print(f"Окно Windows пропущено: {type(exc).__name__}", flush=True)
    return out


def _win32_record(hwnd, foreground, user32, dwm, kernel32, enum_proc=None):
    import ctypes
    from ctypes import wintypes
    GWL_EXSTYLE, GW_OWNER, DWMWA_EXTENDED_FRAME_BOUNDS, DWMWA_CLOAKED = -20, 4, 9, 14
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(max(1, length + 1))
    if length > 0:
        user32.GetWindowTextW(hwnd, buf, length + 1)
    cloaked = wintypes.DWORD(0)
    dwm.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
    r = wintypes.RECT()
    if dwm.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r), ctypes.sizeof(r)) != 0:
        user32.GetWindowRect(hwnd, ctypes.byref(r))
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    exe = _process_exe(pid.value, kernel32)
    app_exe = exe
    if is_host_exe(exe):   # рамка магазинного приложения: программа та, чьё окно CoreWindow внутри
        try:
            app_exe = _uwp_child_exe(hwnd, pid.value, user32, kernel32, enum_proc)
        except Exception:   # noqa: BLE001 — не нашлась: имя приложения и так в заголовке
            app_exe = ""
    return {"hwnd": int(hwnd or 0), "title": buf.value, "exe": exe, "pid": pid.value,
            "app_exe": app_exe, "desc": file_description(app_exe) if app_exe and not is_host_exe(app_exe) else "",
            "visible": bool(user32.IsWindowVisible(hwnd)), "exstyle": user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE),
            "owner": bool(user32.GetWindow(hwnd, GW_OWNER)), "cloaked": bool(cloaked.value),
            "iconic": bool(user32.IsIconic(hwnd)), "foreground": hwnd == foreground,
            "frame": (r.left, r.top, r.right - r.left, r.bottom - r.top)}


def _process_exe(pid, kernel32) -> str:
    import ctypes
    from ctypes import wintypes
    hp = kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not hp:
        return ""
    try:
        size = wintypes.DWORD(1024)
        path = ctypes.create_unicode_buffer(1024)
        return path.value if kernel32.QueryFullProcessImageNameW(hp, 0, path, ctypes.byref(size)) else ""
    finally:
        kernel32.CloseHandle(hp)


def _uwp_child_exe(hwnd, host_pid, user32, kernel32, enum_proc) -> str:
    """Программа магазинного приложения в рамке ApplicationFrameHost: процесс дочернего окна
    Windows.UI.Core.CoreWindow (у свёрнутого или приостановленного приложения его может не быть: тогда пусто)."""
    import ctypes
    from ctypes import wintypes
    children = []
    proc = enum_proc(lambda h, _l: children.append(h) or len(children) < 64)
    user32.EnumChildWindows(hwnd, proc, 0)
    name = ctypes.create_unicode_buffer(64)
    for child in children:
        if user32.GetClassNameW(child, name, 64) and name.value == "Windows.UI.Core.CoreWindow":
            cpid = wintypes.DWORD(0)
            user32.GetWindowThreadProcessId(child, ctypes.byref(cpid))
            if cpid.value and cpid.value != host_pid:
                return _process_exe(cpid.value, kernel32)
    return ""


def from_win32(exclude=(), screens=None):
    if sys.platform != "win32":
        return None
    return win32_records_to_list(_win32_records(), list(screens if screens is not None else _qt_screens()), exclude)


def grab_window_win32(win: WinInfo):
    """Содержимое окна Windows, даже закрытого другими: PrintWindow с PW_RENDERFULLCONTENT (2; есть в winuser.h
    с Windows 8.1, на странице Learn не описан). Свёрнутое окно так не снять. Ошибки ловит WindowGrab."""
    if sys.platform != "win32" or win.minimized:
        return None
    import ctypes
    from ctypes import wintypes
    from PyQt6.QtGui import QImage, QPixmap
    user32, dwm, _kernel32, gdi32, _enum = _win32_libs()
    hwnd = wintypes.HWND(int(win.id))
    if not user32.IsWindow(hwnd):
        return None   # окно закрылось после списка
    full, vis = wintypes.RECT(), wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(full))
    if dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(vis), ctypes.sizeof(vis)) != 0:
        vis = full
    w, h = full.right - full.left, full.bottom - full.top
    if w <= 0 or h <= 0:
        return None
    screen_dc = user32.GetDC(None)
    dc = gdi32.CreateCompatibleDC(screen_dc)
    bmp = gdi32.CreateCompatibleBitmap(screen_dc, w, h)
    old = gdi32.SelectObject(dc, bmp)
    try:
        if not user32.PrintWindow(hwnd, dc, 2):
            return None

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                        ("biClrImportant", wintypes.DWORD)]
        info = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)   # сверху вниз
        buf = ctypes.create_string_buffer(w * h * 4)
        if not gdi32.GetDIBits(dc, bmp, 0, h, buf, ctypes.byref(info), 0):
            return None
        img = QImage(buf.raw, w, h, w * 4, QImage.Format.Format_RGB32).copy(
            vis.left - full.left, vis.top - full.top, vis.right - vis.left, vis.bottom - vis.top)
    finally:
        gdi32.SelectObject(dc, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(dc)
        user32.ReleaseDC(None, screen_dc)
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(pm.width() / max(1, win.rect.width()))
    return pm


# --- общее ---------------------------------------------------------------------

def is_gnome() -> bool:
    return "GNOME" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper()


def is_wayland() -> bool:
    return os.environ.get("XDG_SESSION_TYPE") == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY"))


def supported() -> bool:
    """Список окон на этой системе вообще возможен (Windows, GNOME, X11)."""
    return sys.platform == "win32" or is_gnome() or not is_wayland()


def _bus():
    if QDBusConnection is None:
        return None
    bus = QDBusConnection.sessionBus()
    return bus if bus.isConnected() else None


def _slot(*types):
    from PyQt6.QtCore import pyqtSlot
    if QDBusConnection is None:
        return lambda fn: fn
    return pyqtSlot(*[{"QDBusMessage": QDBusMessage, "QDBusError": QDBusError}[t] for t in types])


def shell_owner() -> str:
    """Уникальное имя GNOME Shell на шине сеанса (":1.23"): после выхода из системы и входа оно другое. По нему
    ClipSD узнаёт, был ли вход после «Обновить» (напоминание о входе не висит вечно)."""
    bus = _bus()
    if bus is None:
        return ""
    try:
        reply = bus.interface().serviceOwner(EXT_SERVICE)
        return reply.value() if reply.isValid() else ""
    except Exception:   # noqa: BLE001
        return ""


def _unlink_quiet(path):
    try:
        if path:
            os.unlink(path)
    except OSError:
        pass


class WindowLister(QObject):
    """Список окон сигналом ready(WindowList). Объект одноразовый.

    GNOME: дополнение отвечает обычно за несколько миллисекунд. Не ответило за LIST_TIMEOUT_MS (Shell занят):
    приходит временный список окон XWayland (final=False, EXT_SLOW, без кнопки «Обновить»), а настоящий ответ
    ждётся до LIST_WAIT_MS и, если пришёл, заменяет его. cancel(): ответ больше не нужен (окно выделения закрыто
    раньше, чем ответило дополнение): поздний ответ молча отбрасывается. Windows: любая ошибка ctypes даёт пустой
    список с failed=True, а не падение программы (проверка 1.33, В6)."""

    ready = pyqtSignal(object)

    def __init__(self, parent=None, screens=None):
        super().__init__(parent)
        self.screens = screens
        self._done = False
        self._provisional_sent = False
        self.bus = None
        self._slow = QTimer(self)
        self._slow.setSingleShot(True)
        self._slow.timeout.connect(self._provisional)

    def start(self):
        if sys.platform == "win32":
            QTimer.singleShot(0, self._win32)
            return
        self.bus = _bus() if is_gnome() else None
        if self.bus is None:
            QTimer.singleShot(0, self._fallback)
            return
        msg = QDBusMessage.createMethodCall(EXT_SERVICE, EXT_PATH, EXT_IFACE, "ListWindows")
        if not self.bus.callWithCallback(msg, self._ok, self._err, LIST_WAIT_MS):
            QTimer.singleShot(0, self._fallback)
            return
        self._slow.start(LIST_TIMEOUT_MS)

    def cancel(self):
        self._done = True
        self._slow.stop()

    def _emit(self, wl):
        if self._done:
            return
        if wl.final:
            self._done = True
            self._slow.stop()
        self.ready.emit(wl)

    def _win32(self):
        try:
            wl = WindowList(from_win32(screens=self.screens) or [], "win32", True)
        except Exception as exc:   # noqa: BLE001 — окно выделения работает и без списка
            print(f"Список окон Windows не получен: {type(exc).__name__}: {exc}", flush=True)
            wl = WindowList([], "win32", False, failed=True)
        self._emit(wl)

    def _ewmh_list(self, ext_state, final=True):
        """Окна EWMH. Под GNOME Wayland список неполный."""
        try:
            wins = from_ewmh(self.screens) or []
        except Exception as exc:   # noqa: BLE001
            print(f"Окна X11 не получены: {type(exc).__name__}", flush=True)
            wins = []
        gnome = is_gnome()
        return WindowList(wins, "ewmh" if wins or not gnome else "none", not (gnome and is_wayland()),
                          ext_state if gnome else "", final)

    def _fallback(self, ext_state=""):
        """Нет дополнения нового вида (или не GNOME): EWMH."""
        if not self._done:
            self._emit(self._ewmh_list(ext_state or EXT_MISSING))

    def _provisional(self):
        """Дополнение молчит дольше LIST_TIMEOUT_MS: пока неполный список, ответ ждётся дальше."""
        if not self._done and not self._provisional_sent:
            self._provisional_sent = True
            self._emit(self._ewmh_list(EXT_SLOW, final=False))

    @_slot("QDBusMessage")
    def _ok(self, reply):
        if self._done:
            return
        args = reply.arguments()
        try:
            wins = parse_shell_json(args[0], self.screens)
        except (IndexError, ValueError, KeyError, TypeError):
            self._fallback(EXT_OLD)
            return
        self._emit(WindowList(wins, "gnome-ext", True, EXT_OK))

    @_slot("QDBusError", "QDBusMessage")
    def _err(self, error, _msg):
        if self._done:
            return
        name = error.name()
        print(f"Список окон от дополнения GNOME не получен ({name}), беру окна XWayland", flush=True)
        if name in NO_REPLY:
            self._fallback(EXT_SLOW)   # Shell занят: это не старое дополнение, кнопка «Обновить» не поможет
            return
        if name == UNKNOWN_METHOD and self.bus is not None:
            msg = QDBusMessage.createMethodCall(EXT_SERVICE, EXT_PATH, "org.freedesktop.DBus.Introspectable", "Introspect")
            if self.bus.callWithCallback(msg, self._introspect_ok, self._introspect_err, 1000):
                return
        self._fallback(ext_state_on_disk(EXT_OLD if name == UNKNOWN_METHOD else EXT_MISSING))

    @_slot("QDBusMessage")
    def _introspect_ok(self, reply):
        args = reply.arguments()
        self._fallback(ext_state_on_disk(ext_state_from_introspect(args[0] if args else "")))

    @_slot("QDBusError", "QDBusMessage")
    def _introspect_err(self, _error, _msg):
        self._fallback(ext_state_on_disk(EXT_MISSING))


class WindowGrab(QObject):
    """Содержимое одного окна сигналом done(QPixmap | None). Одноразовый. None: окна уже нет, оно свёрнуто, оно не на
    текущем рабочем столе, источник не умеет (X11) или случилась ошибка.

    Живёт у приложения, а не у окна выделения: если окно выделения закрыли раньше ответа, ответ всё равно приходит
    сюда и временный PNG с содержимым окна удаляется. Ответ позже GRAB_TIMEOUT_MS: файл, который Shell всё же запишет,
    удаляется ещё несколько раз в течение минуты (проверка 1.33, О-М1)."""

    done = pyqtSignal(object)
    LATE_SWEEP_MS = (2000, 10000, 60000)

    def __init__(self, win: WinInfo, parent=None):
        super().__init__(parent if parent is not None else QCoreApplication.instance())
        self.win = win
        self.path = ""
        self._finished = False

    def start(self):
        if self.win.source == "win32":
            QTimer.singleShot(0, self._win32)
            return
        bus = _bus() if self.win.source == "gnome-ext" else None
        if bus is None:
            QTimer.singleShot(0, lambda: self._finish(None))
            return
        from .grab import _temp_png
        self.path = _temp_png()
        msg = QDBusMessage.createMethodCall(EXT_SERVICE, EXT_PATH, EXT_IFACE, "GrabWindow")
        msg.setArguments([self.win.id, self.path])
        if not bus.callWithCallback(msg, self._ok, self._err, GRAB_TIMEOUT_MS):
            QTimer.singleShot(0, lambda: self._finish(None))

    def _win32(self):
        try:
            pm = grab_window_win32(self.win)
        except Exception as exc:   # noqa: BLE001 — нет содержимого: остаётся кадр как был
            print(f"Содержимое окна Windows не получено: {type(exc).__name__}", flush=True)
            pm = None
        self._finish(pm)

    def _finish(self, pixmap):
        if self._finished:
            return
        self._finished = True
        self.done.emit(pixmap)
        self.deleteLater()

    def _load(self):
        from PyQt6.QtGui import QPixmap
        pm = QPixmap(self.path) if self.path else QPixmap()
        _unlink_quiet(self.path)   # временный файл в XDG_RUNTIME_DIR, как у снимка стола (grab._load)
        if pm.isNull():
            return None
        pm.setDevicePixelRatio(pm.width() / max(1, self.win.rect.width()))
        return pm

    @_slot("QDBusMessage")
    def _ok(self, reply):
        args = reply.arguments()
        self._finish(self._load() if args and args[0] else None)

    @_slot("QDBusError", "QDBusMessage")
    def _err(self, error, _msg):
        print(f"Содержимое окна не получено ({error.name()})", flush=True)
        path = self.path
        _unlink_quiet(path)
        for ms in self.LATE_SWEEP_MS:   # Shell может дописать файл после того, как ответа перестали ждать
            QTimer.singleShot(ms, lambda p=path: _unlink_quiet(p))
        self._finish(None)


def can_grab(source: str) -> bool:
    """Источник умеет отдавать содержимое окна, закрытого другими."""
    return source in ("gnome-ext", "win32")


def top_window_at(windows, pos: QPoint):
    """Самое верхнее несвёрнутое окно под точкой (глобальные точки Qt) или None."""
    for w in sorted(windows, key=lambda i: -i.z):
        if not w.minimized and w.rect.contains(pos):
            return w
    return None


def is_covered(win: WinInfo, windows) -> bool:
    """Окно хоть немного закрыто окнами выше него."""
    return any(o.z > win.z and not o.minimized and o.rect.intersects(win.rect) for o in windows if o is not win)
