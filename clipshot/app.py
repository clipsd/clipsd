# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""ClipSD: фоновое приложение в трее, глобальная клавиша, захват и окно редактора."""

import argparse
import json
import subprocess
import os
import sys
import threading
import time
from pathlib import Path

from PyQt6.QtCore import QObject, QPoint, QRect, QRectF, QSocketNotifier, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QFont, QGuiApplication, QIcon, QImage, QPainter, QPen, QPixmap
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication, QFileDialog, QMenu, QMessageBox, QSystemTrayIcon

from .editor import OCR as OCR_TOOL, EditorWindow
from .i18n import tr
from .grab import DesktopGrabber, claim_shell_name, grab_qt, is_wayland, virtual_geometry
from . import hidpi
from . import neighbor
from .ipc import QUIT_FOR_UPDATE, socket_path
from .sysenv import child_env, open_url
from .selector import RegionSelector

# Под Wayland оверлей показывается чуть позже запроса снимка, чтобы не попасть в кадр самому.
OVERLAY_DELAY_MS = 150

from . import paths  # noqa: E402

# Готовая сборка: ~/.config/clipsd (Windows %APPDATA%\ClipSD), из исходников: ~/.config/clipshot (paths.py)
CONFIG_PATH = paths.config_file()
DEFAULTS = {
    "hotkey_region": "Alt+W",       # снять область экрана → редактор
    "hotkey_fullscreen": "",        # снять весь экран → редактор (пусто — выключено)
    "builtin_hotkeys": "auto",      # auto | on | off — свой перехват клавиш под X11
    "tray_click": "region",         # region | menu — что делает клик по иконке
    "save_dir": "~/Загрузки" if os.path.isdir(os.path.expanduser("~/Загрузки")) else "~/Downloads",
    "auto_save": True,              # каждый снимок сразу сохраняется в auto_save_dir (после правок файл обновляется)
    "auto_save_dir": "~/Загрузки/Скриншоты" if os.path.isdir(os.path.expanduser("~/Загрузки"))
                     else "~/Downloads/Screenshots",
    "tool": "arrow",
    "color": "#d60808",
    "size": 2,
    "text_color": "",               # цвет текста в номере и сноске; пусто — авто
    "custom_colors": [],            # 1.32.1: свои цвета из «+» в палитре редактора (до трёх, новый вытесняет старый)
    "number_hint_count": 0,         # 1.34: сколько раз показана подсказка «Этот цвет: нумерация с N» (до трёх)
    "show_zoom": True,
    "show_size": True,
    "last_region": None,
    "settings_page": "general",     # 1.32: раздел окна настроек, открытый в прошлый раз
    "tour_selector_done": False,    # 1.32: знакомство с окном выделения уже показано (при первом выделении само)
    "tour_done": False,             # вводный курс уже показан (при первом редакторе показывается сам)
    "novoe_enabled": True,          # 1.34: после обновления окно «Новое в версии» и метки «Новое» (novoe.py)
    "ui_theme": "standard",
    "theme_chosen": False,
    "editor_system_title": False,   # окно редактора с системным заголовком (по умолчанию своя шапка и скруглённые углы)
    "editor_frame_style": "thin",   # вид рамки окна: thin (тонкая линия, 1.32), glow (со свечением), thick (толстая скруглённая), plain (без цветной рамки)
    "hotkey_both_layouts": True,    # сочетание сразу на обе раскладки (через расширение ClipSD в GNOME)          # оформление выбрано при первом запуске         # оформление: standard (светлое) или pro (тёмное, как в видеомонтаже)
    "eraser_mode": "object",        # ластик: object — объект целиком, part — частично
    "ocr_enabled": True,            # текст с картинки: кнопка «Текст», инструмент в редакторе (выкл. = без них)
    "ocr_langs": "auto",            # языки распознавания (Tesseract): auto = язык интерфейса + английский (1.31), или «rus+eng»
    "translate_enabled": True,      # кнопка «Перевести» при снимке (Ctrl+L): перевод поверх текста
    "translate_to": "auto",         # на какой язык переводить: auto = как в системе, или код языка (ru, en, bg…)
    "translate_alt": "en",          # если текст уже на этом языке: на какой переводить
    "translate_engine": "mymemory", # mymemory (без регистрации) или google (ключ Google Cloud); второй запасной
    "translate_view": "overlay",    # вид перевода: overlay (поверх текста) или card (карточкой); кнопка в шапке окошка
    "translate_email": "",          # почта для MyMemory: лимит 50 000 знаков в день вместо 5 000
    "ocr_select_mode": "range",     # выделение текста: range подряд (как на телефоне), marker маркером
    "ocr_quality": "accurate",      # accurate: увеличение ×3, точнее и медленнее; fast: без увеличения
    "tool_order": [],               # порядок кнопок инструментов (перетаскиванием в редакторе)
    "default_tool": "",             # инструмент по умолчанию: редактор открывается с ним; пусто: с последним (правая кнопка по инструменту)
    "remember_region": True,        # подсвечивать прошлую область при новом снимке
    "save_format": "png",           # png | jpg — формат по умолчанию при сохранении (PDF только вручную, 1.36)
    "pdf_page": "image",            # image | a4 — размер страницы PDF: по снимку или A4 (1.36)
    "insert_target_mode": "here",   # 22.11.2026: картинка с телефона/из файла: "here" в этот снимок, "apart" отдельным снимком
    "form_last": "round2",          # 1.34: последняя форма снимка (кнопка «Форма снимка» включает её одним щелчком)
    "form_radius": 28.0,            # 1.34: свой радиус скруглённых углов (точки), когда form_last = round
    "shape_background": "#ffffff",  # 1.34: фон за формой там, где нет прозрачности (JPG, запасная картинка буфера)
    "snapshot_size": "full",        # full: полное разрешение; screen: как на экране, 100% (уменьшено до размера в точках)
    "clip_html": hidpi.html_default(),   # в буфер вместе с картинкой HTML с размером в точках (при масштабе экрана ≠ 100%)
    "language": "auto",             # язык интерфейса: код (ru, en, de…) или auto = язык системы; см. language.config_choice
    "phone_full_size": False,           # «Скриншот/фото с телефона»: сохранять фото в полном размере (выкл.: под экран компьютера)
    "phone_wifi_note_hidden": False,   # «Фото с телефона»: напоминание «одна сеть Wi-Fi» больше не показывать
    "save_ask": True,               # True — Ctrl+S открывает окно выбора файла; False — сразу в save_dir            # [x, y, ш, в] прошлой области — предлагается при следующем снимке
}


def write_json_atomic(path, data) -> None:
    """Запись без риска обрезанного файла: временный файл, fsync, затем os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)   # settings hold the e-mail for MyMemory
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def load_config(migrate: bool = False) -> dict:
    """migrate=True только при настоящем запуске программы: готовая сборка один раз копирует настройки 1.x."""
    if migrate:
        copied = paths.migrate_legacy(CONFIG_PATH.parent)
        if copied:
            print(f"Настройки ClipSD 1.x скопированы в {CONFIG_PATH.parent}: {', '.join(copied)}")
    config = dict(DEFAULTS)
    raw = None
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        config.update(raw)
    except (OSError, ValueError):
        pass
    from .language import config_choice
    config["language"] = config_choice(raw, CONFIG_PATH.exists(), CONFIG_PATH.parent)   # 1.x без поля: по-русски
    if isinstance(raw, dict) and "language" not in raw:
        config.setdefault("translate_auto_system", True)   # и язык перевода «auto» как раньше: язык системы
    return config


def make_icon() -> QIcon:
    from .icons import app_icon
    return app_icon()


class X11Hotkeys(threading.Thread):
    """Глобальные клавиши через XGrabKey: работают при любой раскладке (по коду клавиши)."""

    def __init__(self, bindings: dict, emit, on_error):
        super().__init__(daemon=True)
        self.bindings = bindings  # {"Alt+W": "region"}
        self.emit = emit
        self.on_error = on_error
        self.stopped = False

    def run(self):
        try:
            from Xlib import X, XK, display, error
        except ImportError:
            self.on_error(tr("app.err_xlib"))
            return
        modmap = {"alt": X.Mod1Mask, "ctrl": X.ControlMask, "control": X.ControlMask,
                  "shift": X.ShiftMask, "super": X.Mod4Mask, "win": X.Mod4Mask, "meta": X.Mod4Mask}
        try:
            disp = display.Display()
        except Exception as exc:   # noqa: BLE001 — нет X-дисплея (Wayland без XWayland, проверка без экрана)
            print(f"Глобальные клавиши X11 недоступны: {exc}")
            return
        root = disp.screen().root
        grabs = {}
        for combo, command in self.bindings.items():
            *mods, key = [part.strip() for part in combo.split("+")]
            mask = 0
            for mod in mods:
                mask |= modmap.get(mod.lower(), 0)
            from .keys import x_keysym_name
            keysym = XK.string_to_keysym(x_keysym_name(key) or key)
            keycode = disp.keysym_to_keycode(keysym)
            if not keycode:
                self.on_error(tr("app.err_unknown_key", combo=combo))
                continue
            catcher = error.CatchError(error.BadAccess)
            # Варианты с NumLock и CapsLock, иначе при включённом NumLock клавиша не сработает.
            for extra in (0, X.LockMask, X.Mod2Mask, X.LockMask | X.Mod2Mask):
                root.grab_key(keycode, mask | extra, True, X.GrabModeAsync, X.GrabModeAsync, onerror=catcher)
            disp.sync()
            if catcher.get_error():
                self.on_error(tr("app.err_grab_busy", combo=combo))
                continue
            grabs[(keycode, mask)] = command
        if not grabs:
            disp.close()
            return
        import select
        ignored = X.LockMask | X.Mod2Mask
        while not self.stopped:
            select.select([disp.fileno()], [], [], 0.5)
            while disp.pending_events():
                event = disp.next_event()
                if event.type == X.KeyPress:
                    command = grabs.get((event.detail, event.state & ~ignored & 0xFF))
                    if command:
                        self.emit(command)
        for keycode, mask in grabs:
            for extra in (0, X.LockMask, X.Mod2Mask, X.LockMask | X.Mod2Mask):
                root.ungrab_key(keycode, mask | extra)
        disp.sync()
        disp.close()

    def stop(self):
        self.stopped = True


class WinHotkeys(threading.Thread):
    """Windows: глобальные клавиши через RegisterHotKey (по коду клавиши, при любой раскладке)."""

    MODS = {"alt": 0x1, "ctrl": 0x2, "control": 0x2, "shift": 0x4, "win": 0x8, "super": 0x8}
    MOD_NOREPEAT = 0x4000
    KEYS = {"print": 0x2C, "printscreen": 0x2C, "space": 0x20, "insert": 0x2D, "pause": 0x13}

    def __init__(self, bindings: dict, emit, on_error):
        super().__init__(daemon=True)
        self.bindings = bindings
        self.emit = emit
        self.on_error = on_error
        self.thread_id = None

    def stop(self):
        if self.thread_id:
            import ctypes
            ctypes.windll.user32.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)  # WM_QUIT

    @classmethod
    def parse(cls, combo: str):
        """«Alt+W» → (модификаторы RegisterHotKey, код клавиши VK) или None."""
        *mods, key = [part.strip() for part in combo.split("+")]
        mask = cls.MOD_NOREPEAT
        for mod in mods:
            if mod.lower() not in cls.MODS:
                return None
            mask |= cls.MODS[mod.lower()]
        from .keys import windows_vk
        vk = windows_vk(key)
        return (mask, vk) if vk else None

    def run(self):
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        self.thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        commands = {}
        for i, (combo, command) in enumerate(self.bindings.items(), 1):
            parsed = self.parse(combo)
            if parsed is None:
                self.on_error(tr("app.err_unknown_key", combo=combo))
                continue
            mask, vk = parsed
            if not user32.RegisterHotKey(None, i, mask, vk):
                self.on_error(tr("app.err_hotkey_busy", combo=combo))
                continue
            commands[i] = command
        if not commands:
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == 0x0312 and msg.wParam in commands:  # WM_HOTKEY
                self.emit(commands[msg.wParam])
        for hotkey_id in commands:
            user32.UnregisterHotKey(None, hotkey_id)


class Clipshot(QObject):
    command_received = pyqtSignal(str)
    hotkey_failed = pyqtSignal(str)   # из потока горячих клавиш (X11, Windows): сообщение в главный поток очередью

    def __init__(self, qapp: QApplication, migrate: bool = False):
        super().__init__()
        from . import translate_ui   # лёгкий модуль (только Qt): кнопка «Ещё» на окошках перевода
        translate_ui.FloatingTranslation.request_more = self.capture_translate
        self.qapp = qapp
        self.config = load_config(migrate=migrate)
        from . import notifications   # колокольчик пишет в эти настройки и до первого редактора (лимит перевода)
        notifications.register(self)
        from . import i18n
        if i18n.choice() != self.config["language"]:
            # настройки 1.x скопированы только что (migrate): язык из них, а не тот, что взят до копирования
            i18n.set_language(self.config["language"])
        self.icon = make_icon()
        self.editors = []
        self.insert_target = None   # редактор, в который кладётся следующий снимок области
        self.selector = None
        self.last_trigger = 0.0
        self.server = None
        self.tray = None
        self.hotkeys = None   # поток своих горячих клавиш (X11 вне GNOME, Windows)
        self.quit_reason = ""  # почему программа выходит: "", "update", "signal"
        self._signal_pipe = None
        self._rating = None    # окно оценки (feedback.RatingFlow), пока открыто
        self.rating_draft = None   # 1.32.1: звёзды и отзыв окна оценки, закрытого через Alt+W (только в памяти)
        self._rating_timer = None
        self._rating_quiet_timer = None   # ждёт спокойной минуты, пока правила позволяют окно оценки
        self._rating_quiet_since = None   # с какого момента (time.monotonic) спокойно; None: не спокойно
        self._restart_asked_at = None     # когда человек нажал «Перезапустить сейчас» (time.monotonic)
        self._clipboard_at = None         # когда программа последний раз положила что-то в буфер (time.monotonic)
        self._capture_at = None           # снимок запрошен (щелчок по значку, Alt+W), окно выделения ещё не открыто
        try:
            QGuiApplication.clipboard().dataChanged.connect(self._clipboard_changed)
        except (AttributeError, RuntimeError):
            pass
        self.command_received.connect(self.handle_command)
        self.hotkey_failed.connect(self._show_hotkey_error)

    # --- запуск --------------------------------------------------------------

    def start(self, server_name: str, command: str = ""):
        """Запуск фоновой копии. command: команда из командной строки (region, full, open:...), выполняется через
        300 мс. С region и full снимок запрошен с самого начала, ещё до открытия канала команд: вопрос quit-for-update
        в эти 300 мс получает «busy:selector», а не «ok», после которого программа осталась бы с окном выделения, и
        помощник смены версии остановил бы её силой (Н1 проверки 1.32.3)."""
        if command in ("region", "full"):
            self._capture_requested()
        from . import novoe
        if novoe.on_start(self.config):   # 1.34: первая установка или обновление (версия в настройках)
            self.save_config()
        self._start(server_name)
        QTimer.singleShot(3000, self.schedule_otlozhit)   # отложенные окна, срок которых вышел за время, пока программа не работала
        if command:
            QTimer.singleShot(300, lambda: self.handle_command(command))

    def _start(self, server_name: str):
        self.install_signal_handlers()
        QLocalServer.removeServer(server_name)
        self.server = QLocalServer(self)
        # подключиться может только этот пользователь (Unix: права сокета; Windows: список доступа канала)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._on_connection)
        if not self.server.listen(server_name):
            print(f"Не удалось открыть канал команд {server_name}: {self.server.errorString()}")
        self._socket_id = self._socket_stat()
        QTimer.singleShot(1500, self._sync_gnome_hotkeys)   # после перезахода расширение ClipSD забирает клавиши
        if is_wayland() and not claim_shell_name():
            print("Имя org.gnome.Screenshot занято или не GNOME: снимки пойдут через портал")
        self._setup_tray()
        self._setup_hotkeys()
        from . import updater
        updater.start(self)   # итог прошлой попытки, метка запуска, проверка раз в 6 часов
        self._start_rating()
        QTimer.singleShot(1800, self.restore_after_restart)
        if os.name == "nt":
            try:
                from . import win_hdr
                import logging
                logging.getLogger("clipsd.hdr").warning("start: %s", win_hdr.states_line())   # цвет экрана Windows в журнал
            except Exception:   # noqa: BLE001
                pass

    # --- оценка программы (1.32, feedback.py) ---------------------------------

    RATING_FIRST_MS = 90_000        # первая проверка правил и очереди после запуска
    RATING_EVERY_MS = 3_600_000     # дальше раз в час, пока программа работает
    RATING_POLL_MS = 5_000          # пока правила позволяют окно: так часто смотреть, спокойно ли

    def _start_rating(self):
        from . import feedback
        feedback.note_use_day(self.config)
        self.save_config()
        self._rating_timer = QTimer(self)
        self._rating_timer.setInterval(self.RATING_EVERY_MS)
        self._rating_timer.timeout.connect(self._rating_tick)
        self._rating_timer.start()
        QTimer.singleShot(self.RATING_FIRST_MS, self._rating_tick)

    def _rating_tick(self):
        """Очередь неотправленных оценок (в фоне) и предложение оценить, если правила позволяют."""
        from . import feedback
        day = self.config.get("last_usage_day")
        feedback.note_use_day(self.config)   # программа работает сутками: день работы засчитывается и без перезапуска
        if self.config.get("last_usage_day") != day:
            self.save_config()
        feedback.flush_in_background()
        self.watch_rating_quiet()

    def watch_rating_quiet(self):
        """Правила показа выполнены: окно оценки придёт в спокойную минуту (1.32, Б1 проверки), как отложенное окно
        обновления: update_prompt.QUIET подряд нет окна выделения, редактора и других окон ClipSD. Раньше окно
        приходило через 2,5 с после закрытия редактора, ровно когда человек делает следующий снимок.
        Зовётся раз в час, после снимка и после закрытия редактора; таймер сам останавливается."""
        from . import feedback
        if feedback.is_open(self._rating) or not feedback.should_show_rating(self.config):
            return
        if self._rating_quiet_timer is None:
            self._rating_quiet_timer = QTimer(self)
            self._rating_quiet_timer.setInterval(self.RATING_POLL_MS)
            self._rating_quiet_timer.timeout.connect(self.rating_quiet_poll)
        if not self._rating_quiet_timer.isActive():
            self._rating_quiet_since = None
            self._rating_quiet_timer.start()

    def rating_quiet_poll(self, now: float = None) -> bool:
        """Таймер спокойной минуты для окна оценки. True, если окно показано. now: time.monotonic() (тесты)."""
        from . import feedback, update_prompt
        now = time.monotonic() if now is None else now
        if feedback.is_open(self._rating) or not feedback.should_show_rating(self.config):
            self._stop_rating_quiet()
            return False
        if self.rating_blocker():
            self._rating_quiet_since = None
            return False
        since = self._rating_quiet_since
        if since is None or since > now:
            self._rating_quiet_since = now
            return False
        if now - since < update_prompt.QUIET.total_seconds():
            return False
        if self.maybe_offer_rating():
            self._stop_rating_quiet()
            return True
        return False

    def _stop_rating_quiet(self):
        self._rating_quiet_since = None
        if self._rating_quiet_timer is not None:
            self._rating_quiet_timer.stop()

    def _note_activity(self):
        """Выделение или закрытый редактор: спокойная минута (окно оценки, отложенное окно обновления) считается
        заново. Таймеры смотрят раз в несколько секунд и короткий снимок между ними иначе бы не заметили."""
        self._rating_quiet_since = None
        updater = getattr(self, "_updater", None)
        if updater is not None:
            updater._prompt_quiet_since = None
            updater._recall_quiet_since = None   # срочное окно после Alt+W (update_prompt.recall_critical)

    def rating_blocker(self) -> str:
        """Почему окну оценки сейчас не время ("" = спокойно): окно выделения, редактор, модальное окно
        (update_prompt.busy_reason), меню, любое другое окно ClipSD (настройки, обновление, «О программе»)."""
        from . import update_prompt
        reason = update_prompt.busy_reason(self)
        if reason:
            return reason
        if QApplication.activeModalWidget() is not None or QApplication.activePopupWidget() is not None:
            return "dialog"
        from PyQt6.QtWidgets import QDialog
        if any(isinstance(w, QDialog) and w.isVisible() for w in QApplication.topLevelWidgets()):
            return "dialog"
        return ""

    def maybe_offer_rating(self) -> bool:
        """Открыть окно оценки, если правила позволяют и сейчас ничто не мешает (rating_blocker). Само по себе
        зовётся только после спокойной минуты (rating_quiet_poll)."""
        from . import feedback
        if feedback.is_open(self._rating) or not feedback.should_show_rating(self.config):
            return False
        if self.rating_blocker():
            return False
        self._rating = feedback.RatingFlow(self, auto=True)
        self._rating.open()
        return True

    def show_rating(self):
        """Пункт «Оценить ClipSD» (меню значка и «?» редактора): окно сразу, без правил показа."""
        from . import feedback
        flow = self._rating
        if feedback.is_open(flow):
            for w in (flow.dialog, flow.thanks):
                try:
                    if w is not None and w.isVisible():
                        w.raise_()
                        w.activateWindow()
                        return
                except RuntimeError:
                    pass
        self._rating = feedback.RatingFlow(self, auto=False)
        self._rating.open()

    def shutdown(self):
        """Выход: настройки записаны на диск, канал команд закрыт (сокет освобождён), дальше процесс завершается
        упорядоченно (exitutil.quick_exit)."""
        from PyQt6 import sip
        if self.tray is not None and not sip.isdeleted(self.tray):
            self.tray.hide()   # os._exit не вызывает деструкторы: без этого в Windows остаётся значок-призрак
        try:
            self.save_config()
        except Exception as exc:   # noqa: BLE001 — выход не должен упасть из-за записи настроек
            print(f"Не удалось записать настройки при выходе: {exc}")
        try:
            from . import phone_ui
            phone_ui.stop_all()   # приём фото с телефона закрывается вместе с программой
        except Exception as exc:   # noqa: BLE001
            print(f"Приём фото с телефона не закрыт: {exc}")
        if self.server is not None:
            # close() убирает файл канала по имени. Если на этом месте уже канал другой копии (Г6 проверки гонок),
            # его не трогать: процесс сейчас завершится, его соединения закроет система.
            current = self._socket_stat()
            if current is None or current == getattr(self, "_socket_id", None):
                self.server.close()

    def _socket_stat(self):
        """(устройство, inode) файла канала команд (Linux), None: файла нет или это Windows (там канал не файл)."""
        if os.name == "nt" or self.server is None:
            return None
        try:
            st = os.stat(self.server.fullServerName())
        except OSError:
            return None
        return (st.st_dev, st.st_ino)

    def _on_connection(self):
        sock = self.server.nextPendingConnection()

        def read():
            command = bytes(sock.readAll()).decode(errors="replace").strip()
            if command == QUIT_FOR_UPDATE:
                # clipsd-switch и запускатель Windows ждут «ok» или «busy» в том же соединении
                answer = self.answer_quit_for_update()
                sock.write(answer.encode() + b"\n")
                sock.flush()
                if answer == "ok":
                    QTimer.singleShot(200, self.quit_for_update_now)
            elif neighbor.is_probe(command):
                # вторая копия (другая сборка: с сайта или из Store) спрашивает, какая сборка работает
                sock.write(neighbor.reply_bytes())
                sock.flush()
            elif command:
                self.handle_command(command)

        sock.readyRead.connect(read)
        sock.disconnected.connect(sock.deleteLater)
        if sock.bytesAvailable():
            read()

    def _setup_tray(self, attempt=0):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            # При входе в систему панель GNOME может появиться позже ClipSD — пробуем ещё минуту.
            if attempt < 30:
                QTimer.singleShot(2000, lambda: self._setup_tray(attempt + 1))
            else:
                print("Системный трей недоступен: используйте Alt+W или clipsd --region")
            return
        from .icons import tray_icon
        self.tray = QSystemTrayIcon(tray_icon(), self)   # 1.36: значок у часов свой, логотип программы не меняется
        self.tray.setToolTip(self._tray_tip())
        self.tray.setContextMenu(self._build_tray_menu())
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _build_tray_menu(self) -> QMenu:
        """Меню значка у часов (1.36): разделы «Снимок» и «Инструменты», подменю «Обучение» и «Справка», язык, выход.
        У каждого пункта значок цвета темы; справа сочетание клавиш из настроек."""
        from . import icons, themes, updater
        from .language import make_menu
        from .menus import style_menu
        menu = QMenu()
        style_menu(menu, self.config)
        tokens = themes.tokens(self.config or {})
        color = tokens["text"] if tokens.get("dark") else "#2e3436"

        def add(target, key, text, slot, hotkey="", bold=False):
            action = QAction(icons.icon(key, color), text + (("\t" + hotkey) if hotkey else ""), target)
            action.setData(key)
            action.triggered.connect(slot)
            if bold:
                font = action.font()
                font.setBold(True)
                action.setFont(font)
            target.addAction(action)
            return action

        def section(text):
            action = QAction(text, menu)
            action.setEnabled(False)
            action.setProperty("clipsd_section", True)
            menu.addAction(action)

        def submenu(text, key):
            sub = QMenu(text, menu)
            style_menu(sub, self.config)
            sub.setIcon(icons.icon(key, color))
            menu.addMenu(sub)
            return sub

        section(tr("app.menu_sec_capture"))
        add(menu, "region", tr("app.menu_region"), lambda: self.capture_region(delay=250),
            self.config.get("hotkey_region") or "", bold=True)
        add(menu, "fullscreen", tr("app.menu_full"), lambda: self.capture_fullscreen(delay=250),
            self.config.get("hotkey_fullscreen") or "")
        add(menu, "record", tr("app.menu_record"), self.open_screen_recording)
        add(menu, "phone", tr("phone.menu"), lambda: self.open_phone())   # после 1.32: фото с телефона по QR-коду (phone_ui.py)
        add(menu, "image_open", tr("app.menu_open"), self.open_file)
        menu.addSeparator()
        section(tr("app.menu_sec_tools"))
        add(menu, "folder", tr("app.menu_folder"), self.open_folder)
        add(menu, "settings", tr("app.menu_settings"), lambda: self.open_settings())
        menu.addSeparator()
        learn = submenu(tr("app.menu_learn"), "cap")
        add(learn, "book", tr("ozn.menu"), lambda: self.open_oznakomlenie())   # 1.35: окно «Ознакомление» со всеми функциями
        add(learn, "bell", tr("novoe.menu"), lambda: self.show_novoe())   # 1.34: «Что нового» в любой момент (novoe.py)
        add(learn, "play", tr("app.menu_tour"), self.demo_tour)
        add(learn, "region", tr("app.menu_tour_selector"), self.demo_selector_tour)
        helpm = submenu(tr("app.menu_help"), "help")
        upd = updater.install_menu(helpm, self)   # «Проверить обновления» первым в «Справке»
        upd.setIcon(icons.icon("update", color))
        upd.setData("update")
        add(helpm, "star", tr("feedback.rate_title"), self.show_rating)
        add(helpm, "info", tr("app.menu_about"), self.show_about)
        menu.addMenu(make_menu(self, menu))   # «Язык · Language» с глобусом: подменю языков на самих себе
        menu.addSeparator()
        add(menu, "quit", tr("app.menu_quit"), self.qapp.quit)
        self._menu = menu
        return menu

    def set_language(self, choice: str):
        """Сменить язык интерфейса сразу (меню у часов, глобус редактора, знакомство, настройки)."""
        from . import i18n
        self.config["language"] = choice
        self.config.pop("translate_auto_system", None)   # язык выбран явно: перевод «auto» идёт за языком программы
        self.save_config()
        old = i18n.current()
        i18n.set_language(choice)
        if i18n.current() == old:
            return
        install_translations(self.qapp)
        from . import fonts
        fonts.add_cjk(self.qapp)   # китайский: запасные шрифты с иероглифами; другие языки: шрифт как был
        if self.tray is not None:
            self.tray.setContextMenu(self._build_tray_menu())
            self.tray.setToolTip(self._tray_tip())
        for editor in list(self.editors):
            if hasattr(editor, "retranslate"):
                editor.retranslate()   # панели строятся заново на новом языке, рисунки и режим остаются
        selector = getattr(self, "selector", None)
        if selector is not None:   # окно выделения открыто: подписи и чип языка тут же на новом языке
            selector._bar_forget()
            selector.update()

    def _tray_tip(self) -> str:
        tip = tr("app.tray_tip", hotkey=self.config['hotkey_region'] or tr("app.tray_click"))
        from . import build_info
        return f"{tip} · {build_info.preview_label()}" if build_info.is_preview() else tip

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger and self.config["tray_click"] == "region":
            self.capture_region(delay=250)

    def _setup_hotkeys(self):
        mode = self.config["builtin_hotkeys"]
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
        if sys.platform == "win32":
            bindings = {}
            if self.config["hotkey_region"]:
                bindings[self.config["hotkey_region"]] = "region"
            if self.config["hotkey_fullscreen"]:
                bindings[self.config["hotkey_fullscreen"]] = "full"
            if mode != "off" and bindings:
                self.hotkeys = WinHotkeys(bindings, self.command_received.emit, self._hotkey_error)
                self.hotkeys.start()
            return
        if mode == "off" or is_wayland():
            return
        if mode == "auto" and "GNOME" in desktop:
            return  # в GNOME клавишу назначает install.sh через системные сочетания клавиш
        bindings = {}
        if self.config["hotkey_region"]:
            bindings[self.config["hotkey_region"]] = "region"
        if self.config["hotkey_fullscreen"]:
            bindings[self.config["hotkey_fullscreen"]] = "full"
        if bindings:
            self.hotkeys = X11Hotkeys(bindings, self.command_received.emit, self._hotkey_error)
            self.hotkeys.start()

    def _sync_gnome_hotkeys(self):
        """Если работает расширение ClipSD, сочетания (с русским двойником) переносятся в него."""
        if sys.platform == "win32":
            return
        from .settings import GnomeHotkeys, ShellExtension
        try:
            ext = ShellExtension()
            if GnomeHotkeys.available() and ext.installed() and ext.active():
                GnomeHotkeys(ext=ext).apply(self.config["hotkey_region"], self.config["hotkey_fullscreen"],
                                            self.config.get("hotkey_both_layouts", True))
        except (RuntimeError, OSError, ValueError) as exc:
            print(f"Сочетания GNOME не обновлены: {exc}")

    def _hotkey_error(self, text):
        """Вызывается из потока горячих клавиш (X11, Windows): в главный поток сигналом, Qt доставит его очередью.
        Раньше здесь был QTimer.singleShot(0, qapp, функция): такого варианта в PyQt6 нет, вызов падал с TypeError
        в потоке, и сообщение «сочетание занято» не доходило до человека."""
        self.hotkey_failed.emit(text)

    def _show_hotkey_error(self, text):
        dialog = getattr(self, "_settings", None)
        if dialog is not None:   # окно настроек открыто (кнопка «Применить»): сообщение в самом окне
            try:
                dialog.show_apply_errors([text])
                return
            except RuntimeError:   # окно уже удалено
                pass
        self.notify(text)

    # --- команды -------------------------------------------------------------

    def handle_command(self, command: str):
        if command == "region":
            self.capture_region()
        elif command == "full":
            self.capture_fullscreen()
        elif command.startswith("open:"):
            self.open_editor(QImage(command[5:]), None)
        elif command == "demo":
            self.demo_tour()
        elif command == QUIT_FOR_UPDATE:
            # приходит от clipsd-switch и запускателя Windows перед сменой версии
            if self.answer_quit_for_update() == "ok":
                self.quit_for_update_now()
        elif command == "quit":
            self.save_config()
            self.qapp.quit()

    # --- выход для обновления и по сигналу ----------------------------------------

    RESTART_ASK_S = 120   # после «Перезапустить сейчас» спрятанное окно «С телефона» не держит обновление столько

    def restart_requested(self) -> None:
        """Человек сам нажал «Перезапустить сейчас»: помощник смены версии спросит программу (quit-for-update) ещё раз,
        и без этой пометки спрятанное окно «С телефона» снова ответило бы «busy» (бесконечное мигание окна)."""
        self._restart_asked_at = time.monotonic()
        self._explicit_at = time.monotonic()

    EXPLICIT_S = 1800   # «Обновить» нажато недавно: помощник смены версии может прийти позже (скачивание, установка)

    def explicit_restart(self) -> bool:
        at = getattr(self, "_explicit_at", None)
        return at is not None and 0 <= time.monotonic() - at < self.EXPLICIT_S

    def restart_asked(self) -> bool:
        at = getattr(self, "_restart_asked_at", None)
        return at is not None and 0 <= time.monotonic() - at < self.RESTART_ASK_S

    def quit_blocker(self) -> str:
        """Почему программу нельзя закрыть сейчас без потери работы ("" = можно).

        phone: открыто окно приёма «Скриншот/фото с телефона» (в том числе спрятанное после фото) или фото раскодируется;
        selector: открыто окно выделения (или вот-вот откроется: снимок запрошен); text: в редакторе набирается
        текст; unsaved: в редакторе есть пометки, которые не сохранены и не скопированы; dialog: открыто модальное
        окно (настройки и т.п.)."""
        if self.selector is not None or self.insert_target is not None or self.capture_pending():
            return "selector"
        for editor in list(self.editors):
            canvas = getattr(editor, "canvas", None)
            if canvas is None:
                continue
            if getattr(canvas, "text_edit", None) is not None:
                return "text"
            if getattr(editor, "exported", False):
                continue
            if getattr(canvas, "modified", False) or getattr(editor, "only_in_memory", False):
                return "unsaved"
        from . import phone_ui
        if phone_ui.is_busy(ignore_hidden=Clipshot.restart_asked(self)):
            return "phone"   # the reception from the phone is open (or a photo is being opened): like an unsaved editor
        modal = QApplication.activeModalWidget()
        if modal is not None and not modal.property("clipsd_closable"):
            return "dialog"   # a message of the updater («Что нового», an error) is simply closed on quitting
        return ""

    # --- перезапуск по решению человека (1.36.1) -------------------------------------------------------

    RECOVERY_KEY = "restart_restore"

    @staticmethod
    def recovery_dir() -> Path:
        return CONFIG_PATH.parent / "recovery"

    def blocker_widget(self, reason: str):
        """Окно, которое держит обновление (чтобы назвать его и вывести вперёд), или None."""
        if reason == "dialog":
            return QApplication.activeModalWidget()
        if reason == "selector":
            return self.selector
        if reason in ("text", "unsaved"):
            for editor in list(self.editors):
                canvas = getattr(editor, "canvas", None)
                if canvas is not None and (getattr(canvas, "text_edit", None) is not None or not getattr(editor, "exported", False)):
                    return editor
        if reason == "phone":
            from . import phone_ui
            return phone_ui.current_window()
        return None

    def release_for_restart(self) -> list:
        """Человек сам нажал «Обновить» или «Перезапустить сейчас»: освободить всё, что держало выход, не теряя работу.
        Вводимый текст фиксируется; окно выделения закрывается; приём с телефона останавливается; окна без работы
        закрываются, настройки применяются (OK), «О программе» и справочные окна закрываются; редакторы с несохранёнными
        пометками записываются в папку recovery (пометки вплавлены в картинку) и открываются заново после перезапуска.
        Буфер обмена не держит (человек согласился). Возвращает список сделанных шагов (для журнала); что не удалось
        закрыть само, остаётся причиной в quit_blocker."""
        steps = []
        for editor in list(self.editors):
            canvas = getattr(editor, "canvas", None)
            if canvas is not None and getattr(canvas, "text_edit", None) is not None:
                try:
                    canvas.commit_text()
                    steps.append("text committed")
                except Exception as exc:   # noqa: BLE001
                    steps.append(f"text commit failed: {exc}")
        if self.selector is not None:
            try:
                self.selector._finish(None)
                steps.append("selector cancelled")
            except Exception as exc:   # noqa: BLE001
                steps.append(f"selector cancel failed: {exc}")
        if self.insert_target is not None:
            self.insert_target = None
            steps.append("insert target dropped")
        try:
            from . import phone_ui
            if phone_ui.is_busy(ignore_hidden=True) or phone_ui.current_window() is not None:
                phone_ui.stop_all()
                steps.append("phone window closed")
        except Exception as exc:   # noqa: BLE001
            steps.append(f"phone close failed: {exc}")
        for _ in range(8):   # окно в окне: по одному, начиная с верхнего
            modal = QApplication.activeModalWidget()
            if modal is None or not modal.isVisible():
                break
            name = type(modal).__name__
            from PyQt6.QtWidgets import QDialog
            before = modal.isVisible()
            if modal is getattr(self, "_settings", None):
                modal.accept()   # настройки применяются и закрываются; не вышло применить: окно остаётся, это будет названо
                steps.append("settings applied and closed" if not modal.isVisible() else "settings could not be applied")
            elif isinstance(modal, QDialog):
                modal.reject()
                steps.append(f"dialog {name} closed")
            else:
                modal.close()
                steps.append(f"window {name} closed")
            QApplication.processEvents()
            from PyQt6 import sip
            if sip.isdeleted(modal) or not modal.isVisible():
                continue   # закрыто (WA_DeleteOnClose удаляет окно)
            if before:
                break
        saved = self._save_editors_for_restart()
        if saved:
            steps.append(f"editors saved for restore: {saved}")
        self._flush_clipboard()
        return steps

    def _save_editors_for_restart(self) -> int:
        """Несохранённые редакторы: исходная картинка и пометки (JSON) в recovery, список в настройках; редактор помечается
        сохранённым, чтобы выход не ждал его. После перезапуска restore_after_restart открывает их с теми же правимыми
        пометками. Не вышло записать пометки: картинка с вплавленными пометками (как раньше)."""
        import json
        from .shapes import shape_to_dict
        entries = []
        for editor in list(self.editors):
            canvas = getattr(editor, "canvas", None)
            if canvas is None or getattr(editor, "exported", False):
                continue
            if not (getattr(canvas, "modified", False) or getattr(editor, "only_in_memory", False)):
                continue
            try:
                folder = self.recovery_dir()
                folder.mkdir(parents=True, exist_ok=True)
                stem = f"{int(time.time())}-{len(entries) + 1}"
                path = folder / f"{stem}.png"
                marks = None
                try:
                    canvas.commit_text()
                    if canvas.base.save(str(path), "PNG"):
                        marks = folder / f"{stem}.json"
                        marks.write_text(json.dumps({"shapes": [shape_to_dict(s) for s in canvas.shapes]}), encoding="utf-8")
                    else:
                        marks = None
                except Exception:   # noqa: BLE001 - пометки не записались: запасной путь ниже
                    marks = None
                if marks is None:
                    if not editor.render_image().save(str(path), "PNG"):
                        continue
            except Exception as exc:   # noqa: BLE001 - не сохранилось: редактор остаётся и держит выход
                print(f"Спасение снимка перед обновлением не удалось: {exc}")
                continue
            entries.append(str(path))
            editor.exported = True
        if entries:
            self.config[self.RECOVERY_KEY] = list(self.config.get(self.RECOVERY_KEY) or []) + entries
            self.save_config()
        return len(entries)

    def restore_after_restart(self) -> int:
        """После обновления: снимки, спасённые перед перезапуском, открываются снова с теми же пометками."""
        import json
        from .shapes import shape_from_dict
        listed = list(self.config.get(self.RECOVERY_KEY) or [])
        if not listed:
            return 0
        self.config.pop(self.RECOVERY_KEY, None)
        self.save_config()
        opened = 0
        for name in listed:
            image = QImage(str(name))
            if image.isNull():
                continue
            marks = Path(name).with_suffix(".json")
            shapes = []
            if marks.exists():
                try:
                    shapes = [shape_from_dict(d) for d in json.loads(marks.read_text(encoding="utf-8")).get("shapes", [])]
                except Exception as exc:   # noqa: BLE001 - пометки не читаются: открывается картинка без них
                    print(f"Пометки восстановления не прочитаны: {exc}")
            editor = self.open_editor(image, None)
            if editor is not None:
                if shapes:
                    editor.canvas.shapes = shapes
                    editor.canvas.update()
                editor.canvas.modified = True   # не сохранён: при закрытии спросит, как раньше
                opened += 1
            for f in (Path(name), marks):
                try:
                    f.unlink()
                except OSError:
                    pass
        if opened:
            self.notify(tr("app.restored", n=opened))
        return opened

    @staticmethod
    def _flush_clipboard():
        """Windows: то, что программа скопировала, остаётся в буфере и после выхода (OleFlushClipboard)."""
        if os.name != "nt":
            return
        try:
            import ctypes
            ctypes.windll.ole32.OleFlushClipboard()
        except Exception:   # noqa: BLE001
            pass

    CLIPBOARD_HOLD_S = 120   # отложенное обновление ждёт столько после копирования снимка или текста (Г4)

    def _clipboard_changed(self):
        if self._owns_clipboard():
            self._clipboard_at = time.monotonic()

    @staticmethod
    def _owns_clipboard() -> bool:
        try:
            return QGuiApplication.clipboard().ownsClipboard()
        except RuntimeError:
            return False

    def clipboard_busy(self) -> bool:
        """Снимок или текст, который программа только что скопировала, живёт в её процессе (Windows, X11 без
        менеджера буфера): выход для обновления сейчас опустошил бы буфер обмена, вставлять было бы нечего (Г4
        проверки гонок). True CLIPBOARD_HOLD_S после копирования, пока буфер всё ещё наш (что-то скопировали в другой
        программе: уже не наш, ждать нечего)."""
        at = self._clipboard_at
        if at is None or time.monotonic() - at >= self.CLIPBOARD_HOLD_S:
            return False
        return self._owns_clipboard()

    def answer_quit_for_update(self) -> str:
        """Ответ на quit-for-update: «ok» (программа сейчас выйдет) или «busy» (обновление отложено). Если человек сам
        решил обновиться («Обновить», «Перезапустить сейчас»), сначала освобождается всё, что можно без потери работы
        (release_for_restart): обновление не откладывается из-за окон, которые он не просил держать."""
        if self.explicit_restart() and self.quit_blocker():
            steps = self.release_for_restart()
            import logging
            logging.getLogger("clipsd.updater").warning("explicit update: released the blockers: %s", steps)
        blocker = self.quit_blocker()
        if not blocker:
            return "ok"
        print(f"Обновление отложено: {blocker}")
        import logging
        logging.getLogger("clipsd.updater").warning("update deferred, still blocked by: %s", blocker)
        from . import updater
        updater.get_updater(self).note_deferred(blocker)
        return f"busy:{blocker}"   # the helper, install.sh and uninstall.sh name the reason

    def quit_for_update_now(self):
        # Между «ok» и этим моментом человек мог начать новую правку: тогда остаёмся. Помощник спросит
        # снова, получит «busy» и отложит обновление.
        blocker = self.quit_blocker()
        if blocker:
            from . import updater
            updater.get_updater(self).note_deferred(blocker)
            return
        self.quit_reason = self.quit_reason or "update"
        self.save_config()
        self.qapp.quit()

    def install_signal_handlers(self):
        """SIGTERM (systemctl stop, выход из сеанса, kill) завершает программу через Qt: настройки записаны."""
        if os.name == "nt" or self._signal_pipe is not None:
            return
        import signal
        import socket as _socket
        try:
            reader, writer = _socket.socketpair()
            reader.setblocking(False)
            writer.setblocking(False)
            signal.set_wakeup_fd(writer.fileno())
            signal.signal(signal.SIGTERM, self._on_sigterm)
        except (OSError, ValueError) as exc:   # не главный поток или нет socketpair
            print(f"Обработчик SIGTERM не установлен: {exc}")
            return
        notifier = QSocketNotifier(reader.fileno(), QSocketNotifier.Type.Read, self)
        notifier.activated.connect(self._drain_signal_pipe)
        self._signal_pipe = (reader, writer, notifier)

    def _drain_signal_pipe(self, *_):
        try:
            while self._signal_pipe[0].recv(64):
                pass
        except OSError:
            pass

    def _on_sigterm(self, signum, frame):
        QTimer.singleShot(0, self.quit_on_signal)

    def quit_on_signal(self):
        """SIGTERM обязан завершить программу: exit() выходит из цикла событий, не спрашивая окна редактора
        (quit() в Qt 6 сначала закрывает окна, и вопрос о несохранённом снимке ждал бы ответа без конца)."""
        self.quit_reason = "signal"
        self.save_config()
        self.qapp.exit(0)

    def _busy(self) -> bool:
        """Защита от двойного срабатывания (клавиша + системное сочетание, повторное нажатие)."""
        now = time.monotonic()
        if self.selector is not None or now - self.last_trigger < 0.5:
            return True
        self.last_trigger = now
        return False

    CLEAR_WAY_MS = 250   # закрытое перед выделением окно успевает исчезнуть с экрана до снимка: дольше анимации
                         # закрытия (GNOME 100-150 мс, Windows около 200 мс), задержка почти незаметна

    def clear_way_for_capture(self) -> int:
        """1.32 (Б1 проверки): Alt+W работает всегда. Окно оценки и окна обновления модальные: под ними окно
        выделения не получает ни мыши, ни клавиш, а на X11 ещё и держит клавиатуру (застывший экран без выхода).
        Перед выделением они закрываются, как кнопкой «Позже»: оценка по правилам снова через 30 дней (набранный
        отзыв остаётся черновиком до следующего открытия окна); предложение обновления «Позже» (updater._present:
        ещё 3 дня или 20 снимков); срочное придёт снова после снимка в спокойную минуту (update_prompt.recall_critical,
        1.32.1); прочие окна обновления (что нового, сбой, сведения) работы не держат, как и при выходе для
        обновления (quit_blocker). Возвращает, сколько мс подождать до снимка: 0, если ничего не закрывалось."""
        from PyQt6.QtWidgets import QDialog
        closed = self._rating is not None and self._rating.close_for_capture()
        critical = False
        for _ in range(8):   # окно в окне (сбой обновления -> отчёт): по одному, начиная с верхнего
            windows = [w for w in QApplication.topLevelWidgets()
                       if w.isVisible() and w.isModal() and w.property("clipsd_closable")]
            if not windows:
                break
            top = QApplication.activeModalWidget()
            w = top if top in windows else windows[0]
            critical = critical or (getattr(w, "critical", False) is True and type(w).__name__ == "OfferDialog")
            if isinstance(w, QDialog):
                w.reject()   # exec() окна вернёт выбор по умолчанию: «Позже» (OfferDialog), «Закрыть» (FailedDialog)
            else:
                w.close()
            closed = True
        updater = getattr(self, "_updater", None)
        if critical and updater is not None:
            from . import update_prompt
            update_prompt.recall_critical(updater)
        return self.CLEAR_WAY_MS if closed else 0

    def _modal_in_the_way(self):
        """Модальное окно, которое закрывать нельзя (настройки, «О программе», выбор оформления, вопрос редактора)."""
        modal = QApplication.activeModalWidget()
        return modal if modal is not None and modal.isVisible() else None

    CAPTURE_PENDING_S = 2.0   # снимок запрошен, окно выделения откроется через 250-350 мс: столько это «занято»

    def capture_pending(self) -> bool:
        """Снимок запрошен, а окно выделения ещё не открыто (щелчок по значку ждёт 250 мс, «Ещё» и снимок поверх
        редактора 300-350 мс). В эти доли секунды окно оценки, предложение обновления и выход для обновления тоже
        ждут: раньше они успевали встать вместо выделения, и щелчок пропадал (Г10 проверки гонок)."""
        at = self._capture_at
        return at is not None and 0 <= time.monotonic() - at < self.CAPTURE_PENDING_S

    def _capture_requested(self):
        self._capture_at = time.monotonic()

    def capture_region(self, delay=0):
        if not self._busy():
            self._capture_requested()
            QTimer.singleShot(max(delay, self.clear_way_for_capture()), self._start_region)

    def capture_translate(self):
        """«Ещё» на окошке перевода: выделить следующий кусок сразу в режиме перевода.
        Открытые окошки на это время прячутся (не попадут в снимок и не закроют текст), потом вернутся."""
        from . import translate_ui
        if self._busy():
            return
        self._capture_requested()
        self._float_hidden = translate_ui.hide_floating()
        QTimer.singleShot(max(300, self.clear_way_for_capture()), lambda: self._start_region(translate=True))

    def _start_region(self, full=False, translate=False):
        guide, self._guide = getattr(self, "_guide", None), None   # 1.36.1: подсказка шагов из «Ознакомления» (id пункта)
        self._capture_at = None   # дальше занятость видна по самому окну выделения
        self._note_activity()
        modal = self._modal_in_the_way()
        if modal is not None:
            # Под модальным окном выделение не получило бы ни мыши, ни клавиш: экран застыл бы. Такое окно держит
            # работу (настройки) или вопрос; вместо выделения оно поднимается, спрятанное на время снимка возвращается.
            self._region_done(None, QRect())
            modal.raise_()
            modal.activateWindow()
            return
        last = None if full else self._last_region()
        if not is_wayland():
            # X11: снимок мгновенный, оверлей сразу с замороженным кадром.
            self.selector = RegionSelector(grab_qt(), virtual_geometry(), self.config["show_zoom"],
                                           self.config["show_size"], last, full_screen=full)
            self.selector.ocr_enabled = self.config.get("ocr_enabled", True)
            self.selector.tr_cfg, self.selector.tr_save = self.config, self.save_config
            self.selector.lang_ctx = self
            self.selector.guide = guide
            self._attach_windows(self.selector)
            self.selector.finished.connect(self._region_done)
            self.selector.start_selection()
            if translate:
                self.selector.enter_translate()
            else:
                self._selector_tour(self.selector)
            return
        # Wayland: снимок готовится 0,5–3 с — оверлей показываем сразу «вживую», кадр подставим позже.
        selector = RegionSelector(None, virtual_geometry(), self.config["show_zoom"], self.config["show_size"],
                                  last, full_screen=full)
        selector.ocr_enabled = self.config.get("ocr_enabled", True)
        selector.tr_cfg, selector.tr_save = self.config, self.save_config
        selector.lang_ctx = self
        selector.guide = guide
        self._attach_windows(selector)
        selector.finished.connect(self._region_done)
        self.selector = selector
        if translate:
            selector.enter_translate()   # «Ещё» на окошке перевода: сразу режим перевода
        grabber = DesktopGrabber(self)

        def ready(pixmap):
            grabber.deleteLater()
            if self.selector is selector:
                selector.set_desktop(pixmap)

        def failed(text):
            grabber.deleteLater()
            self.notify(text)
            if self.selector is selector:
                selector.fail()

        grabber.ready.connect(ready)
        grabber.failed.connect(failed)
        grabber.start()
        def show_overlay():
            if self.selector is selector:
                selector.start_selection()
                if not translate:
                    self._selector_tour(selector)

        QTimer.singleShot(OVERLAY_DELAY_MS, show_overlay)

    def _attach_windows(self, selector):
        """«Снимок окна» (1.33): список окон просится сейчас, в момент Alt+W, вместе с кадром стола, и приходит
        сигналом (если дополнение GNOME медлит, сначала временный неполный, потом полный). Окно выделения уже закрыто
        (Esc) или открыто другое: поздний ответ отбрасывается, объект списка удаляется (проверка 1.33, О-М4)."""
        from . import windows
        if not windows.supported():
            return
        selector.windows_state = "loading"
        selector.window_ext_relogin = self._ext_relogin_pending()
        lister = windows.WindowLister(self)
        state = {"alive": True}

        def ready(wl):
            if wl.final:
                state["alive"] = False
                lister.deleteLater()
            if wl.ext_state == windows.EXT_OK and self.config.pop("gnome_ext_relogin", None):
                self.save_config()   # новое дополнение заработало после входа: напоминание больше не нужно
            if self.selector is selector:
                selector.window_grab = windows.WindowGrab if windows.can_grab(wl.source) else None
                selector.set_windows(wl)

        def closed(*_args):
            if state["alive"]:
                state["alive"] = False
                lister.cancel()
                lister.deleteLater()

        lister.ready.connect(ready)
        selector.finished.connect(closed)
        lister.start()

    def _ext_relogin_pending(self) -> bool:
        """Дополнение обновлено кнопкой и ждёт выхода из системы и входа. Если вход уже был (у GNOME Shell другое имя
        на шине), а дополнение всё равно не отвечает, напоминание снимается: снова видна кнопка «Обновить»."""
        flag = self.config.get("gnome_ext_relogin")
        if not flag:
            return False
        if isinstance(flag, str) and flag:
            from . import windows
            owner = windows.shell_owner()
            if owner and owner != flag:
                self.config.pop("gnome_ext_relogin", None)
                self.save_config()
                return False
        return True

    def update_gnome_extension(self):
        """Кнопка «Обновить» («Установить») в списке окон: дополнение ClipSD ставится в папку пользователя (пароль
        не нужен), потом честно говорится, что под Wayland GNOME подхватит его после выхода из сеанса и входа.
        Найдено старое дополнение ClipSD (поставлено вручную): окно с кнопкой «Заменить», без тупика."""
        from . import __version__, gnome_ext
        state, detail = gnome_ext.update(version=__version__)
        if state == gnome_ext.FOREIGN:
            if self._show_ext_card(tr("app.ext_old_title"), tr("app.ext_old_text"), "info",
                                   secondary=tr("app.ext_old_later"), primary=tr("app.ext_old_replace")) != "primary":
                return state   # «Не сейчас» или крестик: ничего не меняется
            state, detail = gnome_ext.update(version=__version__, replace=True, fallback=self._ext_hotkey_fallback)
            if state == gnome_ext.FAILED:
                self._sync_gnome_hotkeys()   # откат: сочетания снова по состоянию дополнения
        self._report_ext_state(state, detail)
        return state

    def _ext_hotkey_fallback(self):
        """Запасной Alt+W: обычное сочетание GNOME (без дополнения) включается до выключения старого дополнения."""
        from .settings import GnomeHotkeys
        if sys.platform == "win32" or not GnomeHotkeys.available():
            return
        GnomeHotkeys(ext=None).apply(self.config["hotkey_region"], self.config["hotkey_fullscreen"],
                                     self.config.get("hotkey_both_layouts", True))

    def _report_ext_state(self, state, detail):
        from . import gnome_ext, windows
        if state in (gnome_ext.INSTALLED, gnome_ext.UPDATED, gnome_ext.REPLACED):
            self.config["gnome_ext_relogin"] = windows.shell_owner() or True
            self.save_config()
            if state == gnome_ext.REPLACED:
                title, text = "app.ext_replaced_title", "app.ext_replaced_text"
            else:
                title = "app.ext_installed_title" if state == gnome_ext.INSTALLED else "app.ext_updated_title"
                text = "app.ext_relogin_text"
            if self._show_ext_card(tr(title), tr(text), "ok", tr("app.ext_logout")) == "secondary":
                gnome_ext.log_out()
        elif state == gnome_ext.USER_EXT_OFF:
            self._show_ext_card(tr("app.ext_userext_off_title"), tr("app.ext_userext_off_text"), "info")
        elif state == gnome_ext.UNSUPPORTED:
            self._show_ext_card(tr("app.ext_unsupported_title"), tr("app.ext_unsupported_text", version=detail), "info")
        else:
            reason = tr("app.ext_no_source") if state == gnome_ext.NO_SOURCE else (detail or "?")
            if self._show_ext_card(tr("app.ext_failed_title"), tr("app.ext_failed_text", reason=reason), "error",
                                   secondary=tr("app.ext_open_folder")) == "secondary":
                gnome_ext.open_folder()

    def _selector_tour(self, selector):
        """1.32: знакомство с окном выделения: при первом показе или по запросу из меню значка."""
        selector.tour_force = bool(getattr(self, "_force_selector_tour", False))
        self._force_selector_tour = False
        selector.maybe_start_tour()

    def demo_selector_tour(self):
        """Пункт меню значка: окно выделения с знакомством."""
        if self.selector is not None:
            return
        self._force_selector_tour = True
        self.capture_region(delay=250)

    def _last_region(self):
        if not self.config.get("remember_region", True):
            return None
        value = self.config.get("last_region")
        if isinstance(value, list) and len(value) == 4:
            return QRect(*[int(v) for v in value])
        return None

    def capture_into(self, editor):
        """Новый снимок области поверх уже открытого редактора: окно прячется на время выделения."""
        if self._busy():
            return
        self._capture_requested()
        self.insert_target = editor
        editor.hide()
        QTimer.singleShot(max(350, self.clear_way_for_capture()), self._start_region)   # дать окну исчезнуть с экрана

    def _region_done(self, pixmap, rect):
        hidden = getattr(self, "_float_hidden", None)
        if hidden:
            from . import translate_ui
            translate_ui.show_floating(hidden)   # окошки перевода, спрятанные на время выделения
        self._float_hidden = None
        action = getattr(self.selector, "action", "edit")
        full = getattr(self.selector, "full_mode", False)
        self.selector = None
        self._note_activity()
        if pixmap is not None and action != "record":
            from . import feedback
            feedback.note_capture(self.config)   # счётчик снимков и дней работы для окна оценки
            self.save_config()
            self.watch_rating_quiet()   # 20-й снимок: окно оценки в следующую спокойную минуту
        if action == "record":
            QTimer.singleShot(250, self.open_screen_recording)   # дать окну выделения исчезнуть
            return
        target, self.insert_target = self.insert_target, None
        if target is not None and target in self.editors:
            if pixmap is not None and action == "pin":
                self.pin_image(pixmap.toImage(), rect.topLeft())   # 1.36: «Закрепить» из выделения поверх открытого редактора
            elif pixmap is not None:
                target.canvas.insert_image(pixmap.toImage())
            target.show()
            target.raise_()
            target.activateWindow()
            from .selector import force_foreground
            force_foreground(target)
            return
        if pixmap is not None:
            from . import update_prompt
            update_prompt.note_shot(self.config)   # 1.32: снимки до отложенного окна обновления
            if not full:   # весь экран не запоминаем: в следующий раз предлагается прошлая обычная область
                self.config["last_region"] = [rect.x(), rect.y(), rect.width(), rect.height()]
                self.save_config()
            saved = self.autosave(pixmap.toImage())
            if action == "pin":
                self.pin_image(pixmap.toImage(), rect.topLeft())
                return
            if action == "save":
                self.save_quick(pixmap.toImage())
                return
            if action == "copy":
                self.copy_image(pixmap.toImage())
                self.notify(tr("app.copied_saved", path=saved) if saved else tr("app.copied"))
            else:
                editor = self.open_editor(pixmap.toImage(), rect.topLeft())
                if editor is not None:
                    editor.autosave_path = saved
                    editor.only_in_memory = not saved   # снимок не в файле: выход для обновления его бы потерял
                    if action == "ocr" and self.config.get("ocr_enabled", True):
                        editor.select_tool(OCR_TOOL)   # «Копировать текст»: редактор сразу в режиме текста

    def pin_image(self, image: QImage, top_left=None):
        """1.36: «Закрепить поверх окон»: снимок повисает окошком на месте области (zakrepit.py)."""
        from . import zakrepit
        return zakrepit.pin(self, image, top_left)

    def capture_fullscreen(self, delay=0):
        """Весь экран: окно выделения сразу с рамкой по краю экрана, надписью и кнопками в центре."""
        if not self._busy():
            self._capture_requested()
            QTimer.singleShot(max(delay, self.clear_way_for_capture()), lambda: self._start_region(full=True))

    def open_editor(self, image: QImage, origin):
        if image.isNull():
            self.notify(tr("app.open_failed"))
            return
        editor = EditorWindow(image, self, origin)
        editor.closed.connect(self._editor_closed)
        self.editors.append(editor)
        editor.present()
        if not self.config.get("theme_chosen"):
            # первый запуск: выбор оформления, затем курс. Таймер принадлежит окну: редактор, закрытый раньше 400 мс,
            # удаляет его вместе с собой (Г7 проверки гонок: окно выбора строилось над удалённым редактором и роняло
            # программу). У QTimer.singleShot в PyQt6 нет варианта с объектом-контекстом.
            timer = QTimer(editor)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda: self.first_run(editor))
            timer.start(400)
        elif not self.config.get("tour_done"):
            from . import novoe, otlozhit
            if not otlozhit.is_snoozed(self.config, "tour"):   # «Отложить» в знакомстве: вернётся, когда срок выйдет
                QTimer.singleShot(500, editor.start_tour)   # первый запуск: вводный курс
                novoe.window_done(self.config)   # всё знакомство и так покажет программу: окно новинок не нужно
        else:
            self._maybe_novoe(editor)
        return editor

    # --- новинки после обновления (1.34, novoe.py) -----------------------------------------------------

    NOVOE_DELAY_MS = 700   # окно новинок чуть позже окна редактора, как знакомство

    def _maybe_novoe(self, editor):
        """Первый редактор после обновления: одно окно «Новое в версии X». Таймер принадлежит окну (как у выбора
        оформления): редактор, закрытый раньше, удаляет его вместе с собой."""
        from . import novoe
        if not novoe.window_pending(self.config):
            return
        timer = QTimer(editor)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._novoe_from_editor(editor))
        timer.start(self.NOVOE_DELAY_MS)

    def _novoe_from_editor(self, editor):
        from PyQt6 import sip
        from . import novoe
        if editor not in self.editors or sip.isdeleted(editor) or getattr(editor, "tour", None) is not None:
            return
        if not novoe.window_pending(self.config):
            return   # уже показано
        if self.editors and self.editors[-1] is not editor:
            return   # открыт новый редактор: окно предложит его собственный таймер, над ним человек и работает
        if not self.editor_quiet(editor) or self.work_window_open():
            # 1.34.1 (Б1 проверки 1.34.0): Alt+W меньше чем через 0,7 с после редактора. Модальное окно новинок
            # поверх открытого (или запрошенного) выделения заморозило бы его. Ждём спокойного момента у этого же
            # редактора: выделение закрыто, редактор на экране, других модальных окон нет.
            self._retry_on_editor(editor, lambda: self._novoe_from_editor(editor))
            return
        self.show_novoe(editor, auto=True)

    def work_window_open(self) -> bool:
        """Человек сейчас работает: окно текста с картинки или режим текста, перевод (окошки и режим), редактор с
        несохранёнными пометками или набором текста. Окно «Новое в версии» (слова владельца 22.11.2026: всплыло
        поверх окна копирования текста) в такой момент не приходит, ждёт спокойной минуты."""
        from PyQt6 import sip

        def alive(w):
            try:
                return w is not None and not sip.isdeleted(w)
            except TypeError:   # не окно Qt (проверочные подставки)
                return False
        try:
            from . import translate_ui
            if any(alive(w) and w.isVisible() for w in list(translate_ui._floating)):
                return True
        except Exception:   # перевод не загружен: окошек нет
            pass
        ozn = getattr(self, "_ozn_window", None)
        if alive(ozn) and ozn.isVisible() and ozn.lesson.active:
            return True   # идёт урок в «Ознакомлении»: окно оценки, предложение обновления, «Новое в версии» не поверх него
        for ed in list(self.editors):
            if not alive(ed):
                continue
            for name in ("_text_panel", "_ocr_dialog"):
                w = getattr(ed, name, None)
                if alive(w) and w.isVisible():
                    return True
            canvas = getattr(ed, "canvas", None)
            if canvas is None:
                continue
            if canvas.tool in ("ocr", "translate") or getattr(canvas, "text_edit", None) is not None:
                return True
            if canvas.modified and not getattr(ed, "exported", False):
                return True
        return False

    QUIET_RETRY_MS = 1000   # окно знакомства или новинок ждёт спокойного момента: проверка раз в секунду

    def editor_quiet(self, editor) -> bool:
        """Можно ли сейчас показать окно, которое приходит к редактору по таймеру (выбор оформления, новинки,
        вопрос про обзор): окно выделения не открыто и не запрошено, снимок не вставляется в редактор, сам редактор
        виден и не свёрнут, другого модального окна нет. Иначе такое окно встало бы поверх выделения (Г8, Б1)."""
        if self.selector is not None or self.insert_target is not None or self.capture_pending():
            return False
        if self._modal_in_the_way() is not None:
            return False
        try:
            return editor.isVisible() and not editor.isMinimized()
        except RuntimeError:
            return False

    def _retry_on_editor(self, editor, again):
        """Повторить проверку позже. Таймер принадлежит редактору: закрытый редактор удаляет его вместе с собой."""
        timer = QTimer(editor)
        timer.setSingleShot(True)
        timer.timeout.connect(again)
        timer.timeout.connect(timer.deleteLater)
        timer.start(self.QUIET_RETRY_MS)

    def show_novoe_after_update(self, version: str) -> bool:
        """Обновление поставила сама программа (updater, спокойная минута): вместо окна «ClipSD обновлён» окно новинок
        с той же строкой «Обновление установлено». True: показано или уже было, окно «ClipSD обновлён» не нужно."""
        from . import __version__, novoe
        if version != __version__ or not novoe.enabled(self.config) or not novoe.items_since(self.config):
            return False
        if novoe.window_pending(self.config):
            self.show_novoe(None, auto=True, updated=True)
        return True

    def show_novoe(self, editor=None, auto=False, updated=False):
        """Окно «Новое в версии X» (меню значка «Что нового», первый редактор после обновления, updater).
        «Показать новое»: короткий курс по новым кнопкам в этом редакторе (нет редактора: в примере снимка), потом
        вопрос про обзор. Новинок этой версии в таблице нет: обычное окно «Что нового» с заметками версии."""
        from . import __version__, notifications, novoe
        notes = notifications.whats_new_notes(self.config, __version__)
        items = novoe.window_items(self.config)
        if not items:
            from . import updater
            updater.UpdaterUI().whats_new(__version__, notes)
            return "notes"
        if getattr(self, "_novoe_window", None) is not None:
            self._novoe_window.raise_()
            return "open"
        from . import otlozhit
        otlozhit.shown(self.config, "novoe")   # окно пришло (само или из меню): срок отложенного снят
        from PyQt6 import sip
        while True:
            box = novoe.make_window(__version__, items, editor, updated=updated, notes=bool(notes))
            if editor is None:
                box.place_centered()
            self._novoe_window = box
            try:
                box.exec()
            finally:
                self._novoe_window = None
            choice = box.choice
            if choice != "relang":
                break
            # язык сменили при открытом окне: то же окно на новом языке (М6 проверки 1.34.0)
            notes = notifications.whats_new_notes(self.config, __version__)
            items = novoe.window_items(self.config) or items
            if editor is not None and (editor not in self.editors or sip.isdeleted(editor)):
                editor = None
        if choice == "never":
            # «Не показывать новинки этой версии»: окно само не придёт, метки скрыты, точка колокольчика гаснет
            novoe.hide_version(self.config)
            self.mark_whatsnew_read()
        elif choice in ("show", "notes"):
            novoe.window_done(self.config)
            self.mark_whatsnew_read()   # человек посмотрел новое: точка на колокольчике гаснет (слова владельца 22.11.2026)
        elif choice == "snooze" or (auto and choice != "relang"):
            # «Отложить ▾» (в том числе у окна, открытого из меню значка) или крестик у окна, пришедшего само:
            # вернётся, когда срок выйдет, в спокойную минуту; после трёх откладываний подряд не раньше чем через неделю
            otlozhit.snooze(self.config, "novoe", box.delay or otlozhit.DEFAULT)
        else:
            self.mark_whatsnew_read()   # открыл сам (меню значка): он всё увидел
        self.save_config()
        if choice not in ("show", "notes"):
            self.schedule_otlozhit()
        if choice == "notes":
            from . import updater
            updater.UpdaterUI().whats_new(__version__, notes)
        elif choice == "show":
            QTimer.singleShot(200, lambda: self.open_oznakomlenie(focus_new=True, ask_after=True))
        return choice

    def mark_whatsnew_read(self):
        """«Что нового» установленной версии прочитано: точка на колокольчике гаснет, пункт остаётся справкой."""
        from . import __version__, notifications
        notifications.mark_read(self.config, [f"whatsnew:{__version__}"], self.save_config)

    def open_oznakomlenie(self, focus_new=False, ask_after=False, auto=False):
        """Окно «Ознакомление» (oznakomlenie.py): все функции, новое сверху. focus_new: сразу на первой новинке.
        ask_after: после закрытия один раз на версию вопрос «Хотите узнать о других функциях?», если человек смотрел
        только новое."""
        from . import novoe, oznakomlenie, otlozhit
        otlozhit.shown(self.config, "ozn")   # окно открыто (само, из меню или после срока): отложенное снято
        win = oznakomlenie.open_window(self, focus_new)
        if win is not None and hasattr(win, "set_auto"):
            win.set_auto(bool(auto or ask_after))   # открылось само: в меню «Отложить ▾» есть «Не открывать само»
        if oznakomlenie.new_ids(self.config):
            novoe.window_done(self.config)
            self.mark_whatsnew_read()   # открыл «Ознакомление» на новинках: «Что нового» прочитано
        if ask_after and win is not None:
            win.destroyed.connect(lambda *_: QTimer.singleShot(300, lambda: self._ask_overview()))
        return win

    def _ask_overview(self, editor=None, tries=0):
        """После окна «Ознакомление», открытого кнопкой «Показать новое»: «Хотите узнать о других функциях
        программы?» Один раз на версию, и только если человек смотрел одни новинки; «Да» открывает окно целиком."""
        from . import novoe, oznakomlenie, otlozhit
        if not novoe.ask_pending(self.config) or otlozhit.is_snoozed(self.config, "ozn"):
            return   # вопрос отложен или «Ознакомление» отложено: после возвращения окна спросим
        new = set(oznakomlenie.new_ids(self.config))
        seen = set(self.config.get("ozn_seen") or [])
        if seen - new:
            novoe.ask_done(self.config)   # уже смотрел и другие функции: спрашивать нечего
            self.save_config()
            return
        if (self.selector is not None or self.capture_pending() or self._modal_in_the_way() is not None
                or self.work_window_open()):
            if tries < 120:
                QTimer.singleShot(self.QUIET_RETRY_MS, lambda: self._ask_overview(None, tries + 1))   # не поверх работы
            return
        from . import otlozhit
        otlozhit.shown(self.config, "ask")
        box = novoe.make_question(None)
        box.exec()
        if box.choice == "snooze":
            otlozhit.snooze(self.config, "ask", box.delay or otlozhit.DEFAULT)   # спросит снова, когда срок выйдет
            self.save_config()
            self.schedule_otlozhit()
            return
        novoe.ask_done(self.config)   # «Не сейчас» и крестик: до следующей версии не спрашивает
        self.save_config()
        if box.choice == "primary":
            QTimer.singleShot(200, lambda: self.open_oznakomlenie())

    # --- «Отложить ▾»: возврат окон в спокойную минуту (otlozhit.py) --------------------------------------------

    OTL_MAX_WAIT_MS = 6 * 3600 * 1000   # таймер не длиннее шести часов: после сна и смены часов срок проверяется заново

    def _otl_timer_get(self):
        timer = getattr(self, "_otl_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._otlozhit_tick)
            self._otl_timer = timer
        return timer

    def schedule_otlozhit(self):
        """Поставить таймер на ближайший срок среди отложенных окон (одно место: настройки)."""
        from . import otlozhit
        timer = self._otl_timer_get()
        nxt = otlozhit.next_until(self.config)
        if nxt is None:
            timer.stop()
            return
        ms = int((nxt - otlozhit.now()) * 1000)
        timer.start(max(200, min(ms, self.OTL_MAX_WAIT_MS)))

    def otlozhit_quiet(self) -> bool:
        """Спокойная минута для окна, которое возвращается без редактора: нет выделения, вставки, запрошенного
        снимка, модальных окон, окон текста, перевода и несохранённого снимка."""
        return (self.selector is None and self.insert_target is None and not self.capture_pending()
                and self._modal_in_the_way() is None and not self.work_window_open()
                and getattr(self, "_novoe_window", None) is None)

    def _otlozhit_tick(self):
        from . import novoe, otlozhit
        due = otlozhit.due_topics(self.config)
        if not due:
            self.schedule_otlozhit()
            return
        if not self.otlozhit_quiet():
            self._otl_timer_get().start(self.QUIET_RETRY_MS)   # человек занят: ждём, раз в секунду смотрим снова
            return
        topic = due[0]
        try:
            if topic == "novoe":
                if novoe.enabled(self.config) and novoe.window_items(self.config):
                    self.show_novoe(None, auto=True)
                else:
                    otlozhit.clear(self.config, "novoe")
            elif topic == "ask":
                otlozhit.shown(self.config, "ask")
                self.save_config()
                self._ask_overview()
            elif topic == "ozn":
                ident = otlozhit.data(self.config, "ozn").get("id")
                otlozhit.shown(self.config, "ozn")
                self.save_config()
                win = self.open_oznakomlenie(ask_after=True, auto=True)
                if win is not None and ident:
                    win.select(ident)   # учебный показ продолжается с той же функции
            elif topic == "tour":
                editor = next((e for e in reversed(self.editors) if getattr(e, "tour", None) is None
                               and self.editor_quiet(e)), None)
                otlozhit.shown(self.config, "tour")
                self.save_config()
                if editor is not None:
                    editor.start_tour()
                # редактора нет: знакомство начнётся само при следующем редакторе (срок уже снят)
            elif topic == "tour_selector":
                otlozhit.shown(self.config, "tour_selector")   # покажется при следующем окне выделения
                self.save_config()
        finally:
            self.schedule_otlozhit()

    def _editor_closed(self, editor):
        if editor in self.editors:
            self.editors.remove(editor)
        updater = getattr(self, "_updater", None)
        if updater is not None:
            updater.deferred_soon(1000)   # отложенное обновление может пойти сейчас (один общий таймер, Г4)
        self._note_activity()
        self.watch_rating_quiet()   # окно оценки не сразу, а после спокойной минуты (rating_quiet_poll)

    def open_phone(self, target=None):
        """«Фото с телефона»: окно с QR-кодом; фото открывается в редакторе (target: вставить в этот снимок)."""
        from . import phone_ui
        return phone_ui.open_phone(self, target)

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(None, tr("app.open_title"), os.path.expanduser("~"),
                                              tr("app.open_filter"))
        if path:
            self.open_editor(QImage(path), None)

    def first_run(self, editor):
        """Первый запуск: выбрать оформление (с живым переключением), затем знакомство."""
        from PyQt6 import sip
        from . import themes
        from .theme_chooser import ThemeChooser
        if editor not in self.editors or sip.isdeleted(editor):
            return   # редактор уже закрыт: оформление предложит следующий снимок
        if not self.editor_quiet(editor):
            self._retry_on_editor(editor, lambda: self.first_run(editor))   # не поверх выделения (Б1 проверки 1.34.0)
            return

        def apply():
            themes.apply_app(self.qapp, self.config)
            for ed in list(self.editors):
                ed.refresh_theme()

        chooser = ThemeChooser(self, editor, on_change=apply)
        chooser.exec()
        self.config["theme_chosen"] = True
        self.save_config()
        from . import otlozhit
        if (not self.config.get("tour_done") and editor in self.editors
                and not otlozhit.is_snoozed(self.config, "tour")):
            QTimer.singleShot(300, editor.start_tour)

    def demo_tour(self):
        """Знакомство из меню трея: пример снимка и курс по нему."""
        editor = self.open_editor(demo_image(), None)
        if editor is not None:
            editor.demo_maker = demo_image   # пример рисует программа: при смене языка он перерисуется на новом
        if editor is not None and self.config.get("tour_done"):
            QTimer.singleShot(500, editor.start_tour)

    def build_about(self):
        """Окно «О программе» в стиле ClipSD: значок, название, версия, автор, лицензия, отсутствие гарантий."""
        from . import __author__, __version__
        from .dialogs import ClipDialog
        dlg = ClipDialog(None, tr("app.about_title"), tr("app.about_subtitle"),
                         "info", 520)
        dlg.icon.setPixmap(self.icon.pixmap(44, 44))
        from . import build_info
        dlg.title.setText(f"ClipSD {build_info.version_label(__version__)}")
        dlg.text(f"© 2026 {__author__}")
        dlg.text(tr("app.about_license"))
        # Name and icon (TRADEMARKS.md, GPLv3 section 7): the site page exists in Russian and English
        from html import escape
        from .i18n import current
        page = f"https://clipsd.github.io/{'ru' if current() == 'ru' else 'en'}/trademarks.html"
        terms = dlg.text(f'<a href="{page}">{escape(tr("app.about_trademark"))}</a>')
        terms.linkActivated.connect(open_url)   # not Qt's own opener: see sysenv.open_url
        dlg.text(tr("app.about_nowarranty"), "clipNote")
        from . import links   # 1.32: канал Telegram с новостями и обновлениями
        telegram = dlg.text(f'<a href="{links.TELEGRAM_URL}">{tr("links.telegram_about", url=links.TELEGRAM_SHORT)}</a>')
        telegram.setToolTip(tr("links.telegram_tip"))
        telegram.linkActivated.connect(open_url)   # not Qt's own opener: see sysenv.open_url
        self._about_telegram = telegram
        for url in ("https://clipsd.github.io", "https://github.com/clipsd/clipsd"):
            link = dlg.text(f'<a href="{url}">{url}</a>')
            link.linkActivated.connect(open_url)   # not Qt's own opener: see sysenv.open_url
        from . import errorlog
        if errorlog.log_exists():   # 1.36: журнал ошибок, если непредвиденные ошибки были
            log_link = dlg.link(tr("errlog.menu_open"))
            log_link.clicked.connect(errorlog.open_log_folder)
            dlg.open_log_button = log_link
        close = dlg.primary(tr("about.close"))
        close.clicked.connect(dlg.close)
        dlg.setStyleSheet(dlg.styleSheet() + " QLabel { font-size: 14px; } QLabel#clipNote { font-size: 14px; }"
                          " QLabel#clipSubtitle { font-size: 14px; }")
        return dlg

    def show_about(self):
        old = getattr(self, "_about", None)
        try:
            if old is not None and old.isVisible():   # уже открыто: поднять то же окно, второго не делать
                old.raise_()
                old.activateWindow()
                return
        except RuntimeError:   # окно было закрыто и удалено
            pass
        dlg = self.build_about()
        dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
        dlg.open_centered()
        self._about = dlg   # окно живёт, пока открыто

    def open_folder(self):
        key = "auto_save_dir" if self.config.get("auto_save", True) else "save_dir"
        folder = os.path.expanduser(self.config.get(key) or DEFAULTS[key])
        os.makedirs(folder, exist_ok=True)
        open_url(QUrl.fromLocalFile(folder))

    def open_config(self):
        self.save_config()
        open_url(QUrl.fromLocalFile(str(CONFIG_PATH)))

    def open_settings(self, parent=None):
        from .settings import SettingsDialog
        if getattr(self, "_settings", None) is not None:
            self._settings.raise_()
            self._settings.activateWindow()
            return
        dialog = SettingsDialog(self.config, parent)
        dialog.setWindowIcon(self.icon)
        dialog.update_ctx = self
        dialog.apply_handler = self.apply_settings   # «Применить» и «ОК»: сохранить и применить, не закрывая окно
        self._settings = dialog
        try:
            if dialog.exec() == dialog.DialogCode.Accepted:   # изменения уже применены самим окном (accept)
                if dialog.want_tour:
                    if parent is not None and hasattr(parent, "start_tour"):
                        QTimer.singleShot(200, parent.start_tour)
                    else:
                        self.config["tour_done"] = True
                        self.demo_tour()
                elif getattr(dialog, "want_selector_tour", False):
                    QTimer.singleShot(400, self.demo_selector_tour)
        finally:
            self._settings = None

    def apply_settings(self, values: dict) -> list:
        """Сохранить и применить настройки сразу, без перезапуска. Возвращает список ошибок
        [(поля, текст)]: то, что не удалось (сочетание, автозапуск), остальное применено."""
        from .settings import GnomeHotkeys, autostart_enabled, set_autostart
        errors = []
        autostart = values.pop("autostart", None)
        old_keys = {k: self.config.get(k) for k in ("hotkey_region", "hotkey_fullscreen", "hotkey_both_layouts")}
        keys_changed = (values["hotkey_region"] != self.config.get("hotkey_region")
                        or values["hotkey_fullscreen"] != self.config.get("hotkey_fullscreen")
                        or values.get("hotkey_both_layouts", True) != self.config.get("hotkey_both_layouts", True))
        language = values.pop("language", None)
        self.config.update(values)
        if keys_changed:
            failed = self._apply_hotkeys(GnomeHotkeys)
            if failed:
                errors.append((("hotkey_region", "hotkey_fullscreen", "hotkey_both_layouts"), failed))
                for key, value in old_keys.items():   # не вышло: в настройках остаётся прежнее, повторить можно
                    if value is None:
                        self.config.pop(key, None)
                    else:
                        self.config[key] = value
        self.save_config()
        if language is not None and language != self.config.get("language"):
            self.set_language(language)
        if self.tray is not None:
            self.tray.setToolTip(self._tray_tip())
        if autostart is not None and autostart != autostart_enabled():
            try:
                set_autostart(autostart)
            except (OSError, subprocess.SubprocessError) as exc:
                errors.append((("autostart",), tr("app.autostart_failed", error=exc)))
        from . import themes
        themes.apply_app(self.qapp, self.config)   # меню, подсказки, стандартные окна
        for editor in list(self.editors):
            editor.refresh_theme()   # новое оформление сразу в открытых окнах
        if errors and getattr(self, "_settings", None) is None:   # окна настроек нет: сообщение из значка
            for _keys, text in errors:
                self.notify(text)
        return errors

    def _apply_hotkeys(self, gnome_cls):
        """Новые сочетания вступают в силу сразу. Текст ошибки, если не вышло (GNOME), иначе None; на Windows и X11
        «занято» приходит позже из потока клавиш (_hotkey_error)."""
        if sys.platform != "win32" and gnome_cls.available():
            try:
                gnome_cls().apply(self.config["hotkey_region"], self.config["hotkey_fullscreen"],
                                  self.config.get("hotkey_both_layouts", True))
            except (RuntimeError, OSError, ValueError) as exc:
                return tr("app.gnome_hotkey_failed", error=exc)
            return None
        if self.hotkeys is not None:
            self.hotkeys.stop()
            self.hotkeys = None
        QTimer.singleShot(700, self._setup_hotkeys)   # дать старому потоку отпустить клавиши
        return None

    # --- общее для редактора -------------------------------------------------

    def open_screen_recording(self):
        """Запись видео встроенными средствами системы: GNOME — окно снимков в режиме видео,
        Windows 11 — запись «Ножниц» (Win+Shift+R)."""
        if sys.platform == "win32":
            try:
                import ctypes
                user32 = ctypes.windll.user32
                keys = (0x5B, 0x10, 0x52)          # Win, Shift, R
                for vk in keys:
                    user32.keybd_event(vk, 0, 0, 0)
                for vk in reversed(keys):
                    user32.keybd_event(vk, 0, 2, 0)  # KEYEVENTF_KEYUP
            except (AttributeError, OSError):
                self.notify(tr("app.record_snipping"))
            return
        if self._dbus_call("org.gnome.Shell", "/org/gnome/Shell/Extensions/ClipSD",
                           "org.gnome.Shell.Extensions.ClipSD", "OpenScreencast"):
            return
        # Расширение ещё не загружено (нужен один перезаход в систему). Системный «интерактивный снимок»
        # не подходит: GNOME открывает его в режиме «только снимок», без видео. Подсказываем сочетание GNOME.
        hotkey = "Ctrl+Shift+Alt+R"
        try:
            import subprocess
            value = subprocess.run(["gsettings", "get", "org.gnome.shell.keybindings", "show-screen-recording-ui"],
                                   capture_output=True, text=True, timeout=3, env=child_env()).stdout.strip()
            if value.startswith("['<"):
                hotkey = (value.split("'")[1].replace("<Ctrl>", "Ctrl+").replace("<Shift>", "Shift+")
                          .replace("<Alt>", "Alt+").replace("<Super>", "Super+").replace("<Primary>", "Ctrl+"))
        except (OSError, ValueError, IndexError):
            pass
        self.notify(tr("app.record_hotkey", hotkey=hotkey))

    def _dbus_call(self, service, path, interface, method, wait=True) -> bool:
        try:
            from PyQt6.QtDBus import QDBusConnection, QDBusMessage
        except ImportError:
            return False
        bus = QDBusConnection.sessionBus()
        if not bus.isConnected():
            return False
        msg = QDBusMessage.createMethodCall(service, path, interface, method)
        if not wait:
            return bus.send(msg)
        reply = bus.call(msg, timeout=3000)
        return reply.type() == QDBusMessage.MessageType.ReplyMessage

    def snapshot_path(self, ext: str = None) -> str:
        import datetime
        folder = os.path.expanduser(self.config.get("auto_save_dir") or DEFAULTS["auto_save_dir"])
        os.makedirs(folder, exist_ok=True)
        ext = ext or ("jpg" if self.config.get("save_format", "png") == "jpg" else "png")
        stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        # два снимка в одну секунду, в том числе в двух копиях программы: имя занимается сразу (Г9 проверки гонок)
        return hidpi.reserve_path(folder, f"Screenshot_{stamp}", ext)

    def autosave(self, image: QImage, ext: str = None, quality: int = None):
        """Каждый снимок сразу в папку для снимков (настройка auto_save). Путь файла или None.
        ext и quality: «Фото с телефона» сохраняет фото как JPEG (PNG с 12 Мп весит 8 МБ и пишется секунды)."""
        if not self.config.get("auto_save", True):
            return None
        try:
            path = self.snapshot_path(ext) if ext else self.snapshot_path()
        except OSError as exc:
            print(f"Автосохранение: нет папки: {exc}")
            return None
        if hidpi.save_image(image, path, self.config, quality):
            return path
        hidpi.discard_reserved(path)
        print(f"Автосохранение не удалось: {path}")
        return None

    def save_from_selector(self, selector, pixmap, rect):
        """«Сохранить» в окне выделения (с 1.34 окно не закрывается): окно выбора места (или сразу в save_dir, если
        save_ask выключен). Путь файла, None (отмена) или False (запись не удалась). Прошлая область запоминается, как
        при других действиях; автосохранение в папку снимков не делается: человек сам выбрал файл, а если потом
        скопирует или откроет редактор, снимок автосохранится как обычно."""
        from .editor import ask_save_path
        ask = self.config.get("save_ask", True)
        if ask:
            selector.suspend_for_dialog()
        try:
            path = ask_save_path(None, self.config)
        finally:
            if ask:
                selector.resume_after_dialog()
        if not path:
            return None
        if not hidpi.save_image(pixmap.toImage(), path, self.config):
            hidpi.discard_reserved(path)
            print(f"Сохранение не удалось: {path}")
            return False
        self.config["save_dir"] = os.path.dirname(path)
        if not getattr(selector, "full_mode", False) and self.config.get("remember_region", True):
            self.config["last_region"] = [rect.x(), rect.y(), rect.width(), rect.height()]
        self.save_config()
        print(tr("app.saved", path=path))
        return path

    def print_from_selector(self, selector, pixmap):
        """Ctrl+Shift+P в окне выделения (1.36): системное окно печати для снимка рамки. Окно выделения прячется на
        время окна печати и возвращается с тем же снимком. Принтеров нет и выбрано «Сохранить PDF»: окно выбора файла."""
        from . import pechat
        selector.suspend_for_dialog()
        try:
            image = pixmap.toImage()
            result = pechat.print_image(None, image, self.config, save_pdf=lambda: self._save_pdf_quick(image))
        finally:
            selector.resume_after_dialog()
        if result == "printed":
            self.notify(tr("pechat.sent"))
        elif result == "failed":
            self.notify(tr("pechat.failed"))

    def _save_pdf_quick(self, image: QImage):
        from .editor import ask_save_path
        path = ask_save_path(None, self.config, "pdf")
        if path and hidpi.save_image(image, path, self.config):
            self.config["save_dir"] = os.path.dirname(path)
            self.save_config()
            self.notify(tr("app.saved", path=path))
        elif path:
            hidpi.discard_reserved(path)
            self.notify(tr("app.save_failed", path=path))

    def save_quick(self, image: QImage):
        """Кнопка «Сохранить» под областью: окно выбора места (с папки «Загрузки»), без редактора."""
        from .editor import ask_save_path
        path = ask_save_path(None, self.config)
        if not path:
            return
        if hidpi.save_image(image, path, self.config):
            self.config["save_dir"] = os.path.dirname(path)
            self.save_config()
            self.notify(tr("app.saved", path=path))
        else:
            hidpi.discard_reserved(path)
            self.notify(tr("app.save_failed", path=path))

    def copy_image(self, image: QImage, config=None):
        """В буфер: PNG с плотностью экрана и, при масштабе ≠ 100%, HTML с размером в точках (настройки «Размер снимка»
        и «Вставлять в исходном размере»)."""
        hidpi.copy_image(image, config or self.config)

    def notify(self, text: str):
        print(text)
        if self.tray is not None:
            self.tray.showMessage("ClipSD", text, QSystemTrayIcon.MessageIcon.Information, 3000)

    def save_config(self):
        try:
            write_json_atomic(CONFIG_PATH, self.config)
        except OSError as exc:
            print(f"Не удалось сохранить настройки: {exc}")


DEMO_KEYS = ("app.demo_title", "app.demo_line1", "app.demo_line2", "app.demo_line3", "app.demo_button")


def demo_texts() -> dict:
    """Подписи примера снимка на текущем языке интерфейса (ключ -> текст)."""
    return {key: tr(key) for key in DEMO_KEYS}


def demo_image() -> QImage:
    """Пример снимка для знакомства с программой: все подписи на языке интерфейса (demo_texts), шрифт программы
    (при китайском с запасными шрифтами CJK, fonts.add_cjk). Окно знакомства перерисовывает его при смене языка
    (EditorWindow.demo_maker): 19.11.2026 на Windows язык сменили на болгарский, а пример остался по-русски."""
    texts = demo_texts()
    image = QImage(900, 520, QImage.Format.Format_RGB32)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    from PyQt6.QtGui import QLinearGradient
    grad = QLinearGradient(0, 0, 900, 520)
    grad.setColorAt(0, QColor("#e9eef5"))
    grad.setColorAt(1, QColor("#cfd9e6"))
    p.fillRect(image.rect(), grad)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#ffffff"))
    p.drawRoundedRect(QRectF(60, 60, 780, 400), 14, 14)
    from .themes import BLUE_BUTTON
    p.setBrush(QColor(BLUE_BUTTON))   # шапка примера: белый заголовок 5,8:1 (1.32)
    p.drawRoundedRect(QRectF(60, 60, 780, 56), 14, 14)
    p.drawRect(QRectF(60, 100, 780, 16))
    font = QFont()
    font.setPixelSize(22)
    font.setBold(True)
    p.setFont(font)
    p.setPen(QColor("#ffffff"))
    p.drawText(QRectF(84, 60, 600, 56), Qt.AlignmentFlag.AlignVCenter, texts["app.demo_title"])
    font.setPixelSize(17)
    font.setBold(False)
    p.setFont(font)
    p.setPen(QColor("#33373d"))
    for i, line in enumerate((texts["app.demo_line1"], texts["app.demo_line2"], texts["app.demo_line3"])):
        p.drawText(QRectF(84, 150 + i * 34, 740, 30), Qt.AlignmentFlag.AlignVCenter, line)
    p.setBrush(QColor("#2db400"))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(QRectF(84, 300, 180, 44), 8, 8)
    p.setPen(QColor("#ffffff"))
    p.drawText(QRectF(84, 300, 180, 44), Qt.AlignmentFlag.AlignCenter, texts["app.demo_button"])
    p.end()
    return image


def setup_fonts(qapp):
    """Чёткий текст: серое сглаживание и лёгкое выравнивание по вертикали.

    Qt берёт из системы цветное (субпиксельное) сглаживание; на жирном тексте оно даёт цветную кайму
    и буквы выглядят размытыми. Окна GNOME рисуют текст серым сглаживанием — делаем так же."""
    from . import fonts
    fonts.install(qapp)   # статический «ClipSD Sans»: настоящий жирный вместо программно утолщённого
    font = qapp.font()
    font.setStyleStrategy(QFont.StyleStrategy.NoSubpixelAntialias | QFont.StyleStrategy.PreferAntialias)
    font.setHintingPreference(QFont.HintingPreference.PreferVerticalHinting)
    qapp.setFont(font)


QT_LOCALES = {"ru": "ru_RU", "zh": "zh_CN", "pt": "pt_BR", "uk": "uk_UA"}   # какой файл qtbase_*.qm брать для языка


def install_translations(qapp):
    """Язык стандартных окон Qt (выбор файла, папки, цвета) по языку интерфейса, перевод идёт вместе с PyQt6."""
    from PyQt6.QtCore import QLibraryInfo, QLocale, QTranslator
    from . import i18n
    for old in getattr(qapp, "_translators", []):
        qapp.removeTranslator(old)
    qapp._translators = []
    lang = i18n.current()
    folder = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    for name in ("qtbase", "qt"):
        translator = QTranslator(qapp)
        if lang != "en" and translator.load(QLocale(QT_LOCALES.get(lang, lang)), name, "_", folder):
            qapp.installTranslator(translator)
            qapp._translators.append(translator)


INSTANCE_WAIT_S = 15   # другая копия держит замок, но канал ещё не открыт: столько ждать, чтобы отдать ей команду


def hand_over(server_name: str, command: str, own_kind: str = "") -> bool:
    """Передать команду запущенной копии. False: на канале никто не отвечает.
    Без команды и с own_kind (Windows: сборка с сайта и из Store делят канал) спрашивает работающую копию, какая она,
    и, если сборка другая, показывает сообщение «ClipSD уже работает», а не выходит молча (neighbor.py)."""
    sock = QLocalSocket()
    sock.connectToServer(server_name)
    if not sock.waitForConnected(300):
        return False
    probe = bool(own_kind) and not command
    if probe:
        sock.write(neighbor.probe_command(own_kind).encode())
    elif command:
        sock.write(command.encode())
    sock.waitForBytesWritten(1000)
    reply = ""
    if probe and sock.waitForReadyRead(neighbor.REPLY_WAIT_MS):
        reply = bytes(sock.readAll()).decode(errors="replace")
    sock.disconnectFromServer()
    if probe:
        neighbor.report(own_kind, reply)
    return True


def main() -> int:
    from . import errorlog, i18n
    errorlog.install()   # 1.36: непредвиденная ошибка пишется в журнал (errors.log), а не закрывает программу молча
    from .language import early_choice
    i18n.set_language(early_choice(CONFIG_PATH))   # до разбора командной строки и до первых окон
    if getattr(sys, "frozen", False):   # собранная программа: каталоги переводов попали в сборку?
        lines = i18n.selfcheck_lines()
        if not lines[0].startswith("i18n ok"):
            print("\n".join(lines), file=sys.stderr)
    parser = argparse.ArgumentParser(prog="clipsd", description=tr("app.cli_description"))
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--region", action="store_true", help=tr("app.cli_region"))
    group.add_argument("--full", action="store_true", help=tr("app.cli_full"))
    group.add_argument("--open", metavar="FILE", help=tr("app.cli_open"))
    group.add_argument("--quit", action="store_true", help=tr("app.cli_quit"))
    group.add_argument("--demo", action="store_true", help=tr("app.cli_demo"))
    group.add_argument("--selfcheck", nargs="?", const="-", metavar="REPORT", help=argparse.SUPPRESS)   # проверка сборки
    args = parser.parse_args()
    if args.selfcheck:   # как в 1.30: --selfcheck [ФАЙЛ] (без файла: в stdout)
        lines = i18n.selfcheck_lines()
        text = "\n".join(lines) + "\n"
        if args.selfcheck == "-":
            print(text, end="")
        else:
            with open(args.selfcheck, "w", encoding="utf-8") as fh:
                fh.write(text)
        return 0 if lines[0].startswith("i18n ok") else 1

    command = ("region" if args.region else "full" if args.full else
               f"open:{os.path.abspath(args.open)}" if args.open else "quit" if args.quit else
               "demo" if args.demo else "")

    # Под Wayland окна не могут сами выбирать своё положение, а редактор должен встать
    # на место снятой области, поэтому по умолчанию работаем через XWayland.
    # WM_CLASS окон = clipsd/ClipSD: по нему GNOME находит ярлык clipsd.desktop и его значок.
    os.environ.setdefault("RESOURCE_NAME", "clipsd")
    if is_wayland() and "QT_QPA_PLATFORM" not in os.environ:
        os.environ["QT_QPA_PLATFORM"] = "xcb"

    if sys.platform == "win32":
        # Своя группа в панели задач Windows и свой значок вместо значка Python.
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SergeyDayneko.ClipSD")
        except (AttributeError, OSError):
            pass

    qapp = QApplication(sys.argv)
    errorlog.attach(qapp)
    install_translations(qapp)
    setup_fonts(qapp)
    qapp.setApplicationName("ClipSD")
    qapp.setDesktopFileName("clipsd")
    qapp.setWindowIcon(make_icon())
    qapp.setQuitOnLastWindowClosed(False)
    server_name = socket_path()

    # Одна копия программы (Г6 проверки гонок): замок берётся до проверки канала и держится всё время работы. Замок
    # занят: другая копия работает или как раз запускается и ещё не открыла канал; команда отдаётся ей, когда канал
    # откроется. Раньше две копии, запущенные почти одновременно, обе оставались работать.
    from .ipc import InstanceLock
    lock = InstanceLock(server_name)
    own_kind = neighbor.own_kind() if neighbor.enabled() else ""   # сообщение «уже работает» только в Windows (две сборки)
    deadline = time.monotonic() + INSTANCE_WAIT_S
    while not lock.acquire():
        if hand_over(server_name, command, own_kind):
            return 0
        if time.monotonic() > deadline:
            print("ClipSD уже запущен, но не отвечает на команды", file=sys.stderr)
            return 1
        time.sleep(0.1)
    # Замок наш. Если ClipSD уже запущен (копия старой версии, без замка): передаём ему команду и выходим.
    if hand_over(server_name, command, own_kind):
        return 0
    if args.quit:
        return 0

    if os.environ.get("CLIPSD_NO_FAULTHANDLER") != "1":
        # Жёсткие падения: crash.log. После замка и передачи команды: повторный запуск, который отдал команду и вышел,
        # не пишет «запуск» в журнал работающей программы. Помощник обновления сюда не заходит.
        errorlog.enable_faulthandler()
    app = Clipshot(qapp, migrate=True)
    app.instance_lock = lock   # держится до конца процесса
    from . import themes
    themes.apply_app(qapp, app.config)
    app.start(server_name, command)
    if sys.platform == "win32":
        from .grab import prewarm_hdr
        QTimer.singleShot(3000, prewarm_hdr)   # HDR-мониторы: видеокарта и шейдер готовы к первому снимку
    errorlog.set_loop_running(True)
    rc = qapp.exec()
    errorlog.set_loop_running(False)
    app.shutdown()
    errorlog.disable_faulthandler()   # обычный выход: сбои выгрузки Qt на Windows не считаются падением
    return rc
