# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Захват всего рабочего стола.

X11: напрямую через Qt (мгновенно).
Wayland: асинхронно — GNOME Shell (как gnome-screenshot) → xdg-desktop-portal → внешние утилиты.
Под Wayland снимок кодируется в PNG на стороне GNOME и занимает 0,5–3 с, поэтому захват
асинхронный: оверлей выделения показывается сразу, а замороженный кадр подставляется, когда готов.
"""

import atexit
import itertools
import os
import secrets
import shutil
import stat
import subprocess
import tempfile
from urllib.parse import unquote, urlparse

from .sysenv import child_env

from PyQt6.QtCore import QObject, QRect, QSize, Qt, QTimer, pyqtSignal, pyqtSlot
try:  # QtDBus есть только в Linux-сборках PyQt6; в Windows снимок делается через Qt напрямую
    from PyQt6.QtDBus import QDBusConnection, QDBusError, QDBusMessage
except ImportError:
    QDBusConnection = QDBusError = QDBusMessage = None
from PyQt6.QtGui import QGuiApplication, QPainter, QPixmap

from .i18n import tr


class CaptureError(RuntimeError):
    pass


# Имя из белого списка GNOME Shell: владельцу этого имени Shell разрешает org.gnome.Shell.Screenshot.
# Этим же механизмом пользуется штатный gnome-screenshot.
SHELL_ALLOWED_NAME = "org.gnome.Screenshot"
_counter = itertools.count(1)
_shell_name_owned = False


def is_wayland() -> bool:
    return os.environ.get("XDG_SESSION_TYPE") == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY"))


def virtual_geometry() -> QRect:
    """Логическая геометрия всех мониторов вместе."""
    union = QRect()
    for screen in QGuiApplication.screens():
        union = union.united(screen.geometry())
    return union


def claim_shell_name() -> bool:
    """Занять имя из белого списка GNOME Shell (один раз, в фоновой копии)."""
    global _shell_name_owned
    if QDBusConnection is None:
        return False
    if not _shell_name_owned and "GNOME" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper():
        bus = QDBusConnection.sessionBus()
        _shell_name_owned = bus.isConnected() and bus.registerService(SHELL_ALLOWED_NAME)
    return _shell_name_owned


_private_dir = None


def _is_private(path: str) -> bool:
    """Папка своя: настоящая папка (не ссылка), владелец этот пользователь, другим недоступна (0700)."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    owner_ok = not hasattr(os, "getuid") or st.st_uid == os.getuid()
    return stat.S_ISDIR(st.st_mode) and owner_ok and not st.st_mode & 0o077


def private_dir() -> str:
    """Личная временная папка ClipSD для снимков стола и окон: XDG_RUNTIME_DIR, если она своя и закрыта от других
    (обычно /run/user/<uid>, 0700); иначе своя папка 0700 во временной папке системы, убирается при выходе.
    Раньше без XDG_RUNTIME_DIR снимок шёл в общий /tmp с предсказуемым именем (проверка 1.33)."""
    global _private_dir
    if _private_dir is not None and _is_private(_private_dir):
        return _private_dir
    run = os.environ.get("XDG_RUNTIME_DIR")
    if run and _is_private(run):
        _private_dir = run
    else:
        _private_dir = tempfile.mkdtemp(prefix="clipsd-")   # 0700
        atexit.register(shutil.rmtree, _private_dir, True)
    return _private_dir


def _temp_png() -> str:
    """Новое имя файла в личной папке: номер процесса, счётчик и случайная часть (имя не угадать заранее; дополнение
    GNOME пишет файл только новым, существующий и ссылку не трогает)."""
    return os.path.join(private_dir(), f"clipshot-{os.getpid()}-{next(_counter)}-{secrets.token_hex(4)}.png")


def _load(path: str):
    """Прочитать снимок и удалить временный файл."""
    pixmap = QPixmap(path)
    try:
        os.unlink(path)
    except OSError:
        pass
    if pixmap.isNull():
        return None
    width = virtual_geometry().width()
    if width > 0:
        pixmap.setDevicePixelRatio(pixmap.width() / width)
    return pixmap


# Мониторы с разным масштабом (100 % и 150 %): весь стол собирается в большем масштабе, монитор 100 % в нём растянут.
# Родные снимки таких мониторов храним до следующего снимка: область на одном мониторе вырезается из его родного.
_native_shots = []   # [(логическая геометрия монитора, его снимок в родном масштабе)]


def grab_qt() -> QPixmap:
    screens = QGuiApplication.screens()
    union = virtual_geometry()
    ratios = [screen.devicePixelRatio() for screen in screens]
    ratio = max(ratios)
    mixed = max(ratios) - min(ratios) > 0.01
    _native_shots.clear()
    result = QPixmap(union.size() * ratio)
    result.setDevicePixelRatio(ratio)
    result.fill(Qt.GlobalColor.black)
    painter = QPainter(result)
    for screen in screens:
        geo = screen.geometry()
        shot = screen.grabWindow(0)
        if mixed and shot.devicePixelRatio() < ratio - 0.01:
            _native_shots.append((QRect(geo), shot))
        painter.drawPixmap(QRect(geo.topLeft() - union.topLeft(), geo.size()), shot)
    painter.end()
    return result


def native_region(pixmap: QPixmap, rect: QRect) -> QPixmap:
    """Снимок области в масштабе её монитора (rect: глобальные точки, pixmap: вырезан из всего стола).

    Один масштаб на всех мониторах: снимок без изменений. Разный, а область целиком на мониторе с меньшим масштабом:
    берём его родные пиксели (X11, Windows), иначе возвращаем растянутые пиксели к родному масштабу. Тогда плотность
    в PNG (96 dpi × масштаб) и размер в точках совпадают с тем, что было на этом мониторе."""
    screens = QGuiApplication.screens()
    if pixmap.isNull() or len(screens) < 2:
        return pixmap
    ratios = [screen.devicePixelRatio() for screen in screens]
    ratio = pixmap.devicePixelRatio()
    if max(ratios) - min(ratios) <= 0.01 or abs(ratio - max(ratios)) > 0.01:
        return pixmap   # масштаб один или стол снят не Qt-шным масштабом (GNOME под Wayland): не трогаем
    for geo, shot in _native_shots:
        if geo.contains(rect):
            native = shot.devicePixelRatio()
            local = rect.translated(-geo.topLeft())
            out = shot.copy(QRect(round(local.x() * native), round(local.y() * native),
                                  max(1, round(local.width() * native)), max(1, round(local.height() * native))))
            out.setDevicePixelRatio(native)
            return out
    screen = QGuiApplication.screenAt(rect.center())
    if screen is None or not screen.geometry().contains(rect):
        return pixmap   # область на нескольких мониторах: полный масштаб
    native = screen.devicePixelRatio()
    if native >= ratio - 0.01:
        return pixmap
    out = pixmap.scaled(QSize(max(1, round(rect.width() * native)), max(1, round(rect.height() * native))),
                        Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    out.setDevicePixelRatio(native)
    return out


_EXTERNAL_TOOLS = (
    ("grim", lambda path: ["grim", path]),
    ("spectacle", lambda path: ["spectacle", "--background", "--nonotify", "--fullscreen", "--output", path]),
    ("gnome-screenshot", lambda path: ["gnome-screenshot", "--file", path]),
)


def grab_external():
    for name, command in _EXTERNAL_TOOLS:
        if not shutil.which(name):
            continue
        path = _temp_png()
        try:
            subprocess.run(command(path), timeout=15, check=True, env=child_env(),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (subprocess.SubprocessError, OSError):
            continue
        pixmap = _load(path)
        if pixmap is not None:
            return pixmap
    return None


def _slot(*types):
    """pyqtSlot с типами QtDBus; без QtDBus (Windows) — обычный метод."""
    if QDBusConnection is None:
        return lambda fn: fn
    return pyqtSlot(*[{"QDBusMessage": QDBusMessage, "QDBusError": QDBusError}[t] for t in types])


class DesktopGrabber(QObject):
    """Асинхронный снимок всего стола: ready(QPixmap) или failed(str). Объект одноразовый."""

    ready = pyqtSignal(QPixmap)
    failed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bus = QDBusConnection.sessionBus() if QDBusConnection is not None else None
        self.path = ""
        self.request_path = ""

    def start(self):
        if not is_wayland():
            QTimer.singleShot(0, lambda: self.ready.emit(grab_qt()))
        elif self.bus is not None and "GNOME" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper():
            self._ext()
        elif claim_shell_name():
            self._shell()
        else:
            self._portal()

    # --- расширение ClipSD внутри GNOME Shell (GNOME 50+) ----------------------

    def _ext(self):
        """GNOME 50 закрыл org.gnome.Shell.Screenshot для org.gnome.Screenshot, портал без фокуса не спрашивает
        доступ. Снимок делает расширение ClipSD (clipsd@clipsd.github.io или прежнее, метод Grab); его нет или старое: прежний путь."""
        self.path = _temp_png()
        msg = QDBusMessage.createMethodCall("org.gnome.Shell", "/org/gnome/Shell/Extensions/ClipSD",
                                            "org.gnome.Shell.Extensions.ClipSD", "Grab")
        msg.setArguments([self.path])
        if not self.bus.callWithCallback(msg, self._ext_ok, self._ext_err, 20000):
            self._fallback()

    def _fallback(self):
        if claim_shell_name():
            self._shell()
        else:
            self._portal()

    @_slot("QDBusMessage")
    def _ext_ok(self, reply):
        args = reply.arguments()
        pixmap = _load(self.path) if args and args[0] else None
        if pixmap is None:
            self._fallback()
        else:
            self.ready.emit(pixmap)

    @_slot("QDBusError", "QDBusMessage")
    def _ext_err(self, error, _msg):
        print(f"Расширение ClipSD не дало снимок ({error.name()}), пробую GNOME Shell", flush=True)
        self._fallback()

    # --- GNOME Shell ---------------------------------------------------------

    def _shell(self):
        self.path = _temp_png()
        msg = QDBusMessage.createMethodCall("org.gnome.Shell.Screenshot", "/org/gnome/Shell/Screenshot",
                                            "org.gnome.Shell.Screenshot", "Screenshot")
        msg.setArguments([False, False, self.path])  # без курсора, без вспышки
        if not self.bus.callWithCallback(msg, self._shell_ok, self._shell_err, 20000):
            self._portal()

    @_slot("QDBusMessage")
    def _shell_ok(self, reply):
        args = reply.arguments()
        pixmap = _load(self.path) if args and args[0] else None
        if pixmap is None:
            self._portal()
        else:
            self.ready.emit(pixmap)

    @_slot("QDBusError", "QDBusMessage")
    def _shell_err(self, error, _msg):
        print(f"GNOME Shell не дал снимок ({error.name()}), пробую портал")
        self._portal()

    # --- xdg-desktop-portal --------------------------------------------------

    def _portal(self):
        if not self.bus.isConnected():
            self._external()
            return
        sender = self.bus.baseService().lstrip(":").replace(".", "_")
        token = f"clipshot{os.getpid()}_{next(_counter)}"
        self.request_path = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        self.bus.connect("org.freedesktop.portal.Desktop", self.request_path, "org.freedesktop.portal.Request",
                         "Response", self._portal_response)
        msg = QDBusMessage.createMethodCall("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
                                            "org.freedesktop.portal.Screenshot", "Screenshot")
        msg.setArguments(["", {"handle_token": token, "interactive": False}])
        if not self.bus.callWithCallback(msg, self._portal_sent, self._portal_err, 20000):
            self._external()

    @_slot("QDBusMessage")
    def _portal_sent(self, _reply):
        pass  # сам снимок придёт сигналом Response

    @_slot("QDBusError", "QDBusMessage")
    def _portal_err(self, error, _msg):
        print(f"Портал скриншотов недоступен ({error.name()})")
        self._external()

    @_slot("QDBusMessage")
    def _portal_response(self, msg):
        self.bus.disconnect("org.freedesktop.portal.Desktop", self.request_path, "org.freedesktop.portal.Request",
                            "Response", self._portal_response)
        code, results = (list(msg.arguments()) + [1, {}])[:2]
        uri = results.get("uri", "") if isinstance(results, dict) else ""
        # Портал кладёт файл в ~/Изображения — _load его удаляет.
        pixmap = _load(unquote(urlparse(uri).path)) if code == 0 and uri else None
        if pixmap is None:
            print(f"Портал скриншотов отказал (код {code})")
            self._external()
        else:
            self.ready.emit(pixmap)

    # --- внешние утилиты -----------------------------------------------------

    def _external(self):
        pixmap = grab_external()
        if pixmap is None:
            self.failed.emit(tr("grab.wayland_failed"))
        else:
            self.ready.emit(pixmap)
