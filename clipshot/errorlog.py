# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Общий перехват непредвиденных ошибок (1.36): журнал errors.log и продолжение работы вместо молчаливого закрытия.

Причина (23.11.2026): в PyQt6 необработанное исключение в слоте ведёт к qFatal/abort, и программа без консоли (сборка
PyInstaller на Windows) просто закрывается. Теперь sys.excepthook, threading.excepthook и sys.unraisablehook ставятся
при старте до создания окон: исключение пишется в журнал и поглощается, окно «Что-то пошло не так» (не чаще раза в
минуту, повторы только в журнал) говорит, что работа продолжается. Ошибка до цикла событий: запись в журнал и обычный
выход. Для жёстких падений (не Python-исключения) faulthandler пишет в crash.log рядом.

Журнал без личных данных: путь домашней папки заменяется на ~, имя пользователя в путях на <user>, текст в кавычках
из сообщений об ошибках (там мог оказаться распознанный, переведённый или скопированный текст) стирается, значения
переменных не пишутся. Файл до 500 КБ, ротация в errors.log.1 (один старый файл).
"""
import os
import re
import sys
import threading
import time
import traceback
from pathlib import Path

MAX_BYTES = 500_000
SHOW_INTERVAL_S = 60.0     # окно «Что-то пошло не так» не чаще раза в минуту
MAX_RECORDS = 300          # на один запуск: защита от лавины одинаковых ошибок
CODE_ERRORS = ("AttributeError", "NameError", "UnboundLocalError", "ImportError", "ModuleNotFoundError")

state = {"loop": False, "bridge": None, "last_shown": None, "records": 0, "open_window": None,
         "clock": time.monotonic, "frozen_file": None, "last_report": ""}


# --- пути ---------------------------------------------------------------------------------------------------------

def data_folder() -> Path:
    """Та же папка, что у ocr.log и обновления: %LOCALAPPDATA%\\ClipSD или ~/.local/share/clipsd."""
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local") / "ClipSD"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "clipsd"


def log_path() -> Path:
    return data_folder() / "errors.log"


def crash_path() -> Path:
    return data_folder() / "crash.log"


# --- очистка личного ---------------------------------------------------------------------------------------------

def scrub(text: str) -> str:
    """Убрать из строки путь домашней папки и имена пользователей из путей."""
    text = str(text)
    try:
        home = str(Path.home())
    except (RuntimeError, KeyError, OSError):
        home = ""
    for variant in {home, home.replace("\\", "/"), home.replace("/", "\\")}:
        if len(variant) > 3:
            text = re.sub(re.escape(variant), "~", text, flags=re.IGNORECASE if os.name == "nt" else 0)
    text = re.sub(r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s\"']+", "~", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<![\w.])/(?:home|Users)/[^/\s\"']+", "~", text)
    return text.replace("\r", "")


def _mask_quotes(message: str) -> str:
    """Текст в кавычках стирается: в сообщении KeyError или ValueError мог оказаться текст пользователя."""
    message = re.sub(r"'[^'\n]*'", "'…'", message)
    return re.sub(r'"[^"\n]*"', '"…"', message)


def _describe(exc: BaseException) -> str:
    name = type(exc).__name__
    try:
        message = str(exc)
    except Exception:   # сообщение само бросает: не важно
        message = ""
    if name not in CODE_ERRORS:
        message = _mask_quotes(message)
    message = scrub(" ".join(message.split()))[:300]
    return f"{name}: {message}" if message else name


def _frames(tb) -> list:
    lines = []
    for frame in traceback.extract_tb(tb):
        path = scrub(frame.filename)
        marker = path.replace("\\", "/").rfind("clipshot/")
        if marker >= 0:
            path = path.replace("\\", "/")[marker:]
        lines.append(f"  {path}:{frame.lineno} in {frame.name}")
        if frame.line:
            lines.append(f"      {scrub(frame.line.strip())[:200]}")
    return lines


def trace_text(exc_type, exc, tb) -> str:
    """Трассировка без значений переменных: файл:строка, имя функции, строка кода, тип ошибки и очищенное сообщение
    (цепочка «во время обработки…» тоже)."""
    chain, seen, cur = [], set(), exc
    while cur is not None and id(cur) not in seen and len(chain) < 4:
        seen.add(id(cur))
        chain.append(cur)
        cur = cur.__cause__ or (None if cur.__suppress_context__ else cur.__context__)
    out = []
    for item in reversed(chain):
        out.extend(_frames(item.__traceback__ if item is not exc else tb))
        out.append(_describe(item))
        if item is not exc:
            out.append("(затем:)")
    return "\n".join(out)


def system_line() -> str:
    import platform
    from . import __version__
    try:
        osname = f"{platform.system()} {platform.release()} {platform.version()}"
    except Exception:
        osname = sys.platform
    kind = "собрана" if getattr(sys, "frozen", False) else "из исходников"
    extra = ""
    if os.name == "nt":   # 1.36.1: цвет экрана Windows (тусклые снимки), чтобы увидеть без вопросов владельцу
        try:
            from . import win_hdr
            extra = "display color: " + win_hdr.states_line()
        except Exception:   # noqa: BLE001
            extra = ""
    return scrub(f"ClipSD {__version__} ({kind}), {osname}, Python {platform.python_version()}" + (f"\n{extra}" if extra else ""))


def make_report(where: str, exc_type, exc, tb) -> str:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    return f"[{stamp}] {where}\n{system_line()}\n{trace_text(exc_type, exc, tb)}\n"


# --- журнал -------------------------------------------------------------------------------------------------------

def write_log(report: str) -> bool:
    """Запись в errors.log; выше 500 КБ старый файл уходит в errors.log.1 (прежний .1 заменяется). Сбой записи
    молчит: журнал не должен ронять программу."""
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if path.stat().st_size + len(report.encode("utf-8")) > MAX_BYTES:
                os.replace(path, path.with_name(path.name + ".1"))
        except FileNotFoundError:
            pass
        with open(path, "a", encoding="utf-8") as f:
            f.write("=" * 8 + " " + report + "\n")
        return True
    except OSError:
        return False


# --- перехват -----------------------------------------------------------------------------------------------------

def handle(where: str, exc_type, exc, tb) -> None:
    """Общая обработка: в журнал, затем (в цикле событий, не чаще раза в минуту) окно. Сама никогда не бросает."""
    try:
        if state["records"] >= MAX_RECORDS:
            return
        state["records"] += 1
        report = make_report(where, exc_type, exc, tb)
        state["last_report"] = report
        write_log(report)
        if state["loop"] and state["bridge"] is not None:
            state["bridge"].failed.emit(report)   # из другого потока доставится в основной (queued)
    except Exception:
        pass


def _excepthook(exc_type, exc, tb):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return
    handle("слот или основной поток", exc_type, exc, tb)


def _thread_hook(args):
    if args.exc_type is SystemExit:
        return
    handle(f"поток {getattr(args.thread, 'name', '?')}", args.exc_type, args.exc_value, args.exc_traceback)


def _unraisable_hook(unraisable):
    if unraisable.exc_type is None:
        return
    handle("при освобождении объекта", unraisable.exc_type, unraisable.exc_value, unraisable.exc_traceback)


def install() -> None:
    """Ставит перехватчики. Вызывается в начале main() до создания QApplication и окон."""
    sys.excepthook = _excepthook
    threading.excepthook = _thread_hook
    sys.unraisablehook = _unraisable_hook


def enable_faulthandler() -> bool:
    """Жёсткие падения (не Python-исключения) пишутся в crash.log. Только основная программа: помощник обновления и
    тесты не вызывают. Без консоли (sys.stderr None) файл обязателен."""
    try:
        import faulthandler
        path = crash_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tidy_crash_log(path)
        if path.exists() and path.stat().st_size > 100_000:
            os.replace(path, path.with_name(path.name + ".1"))
        state["frozen_file"] = open(path, "a", encoding="utf-8")
        state["frozen_file"].write(f"--- запуск {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        state["frozen_file"].flush()
        faulthandler.enable(file=state["frozen_file"], all_threads=True)
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def disable_faulthandler() -> None:
    """При обычном выходе: ни один сбой выгрузки Qt в Windows не пишется как «падение»; пустой crash.log удаляется."""
    try:
        import faulthandler
        faulthandler.disable()
        f = state.get("frozen_file")
        if f is not None:
            f.close()
            state["frozen_file"] = None
            tidy_crash_log(crash_path())
    except (OSError, ValueError, RuntimeError):
        pass


def tidy_crash_log(path: Path) -> None:
    """crash.log без сбоя (только строки «--- запуск») удаляется; с настоящим сбоем: личные пути заменяются на ~."""
    try:
        if not path.exists():
            return
        text = path.read_text(encoding="utf-8", errors="replace")
        if all(not ln.strip() or ln.startswith("--- запуск") for ln in text.splitlines()):
            path.unlink()
            return
        clean = scrub(text)
        if clean != text.replace("\r", ""):
            path.write_text(clean, encoding="utf-8")
    except (OSError, ValueError, RuntimeError):
        pass


def crash_text() -> str:
    """Содержимое crash.log для показа, копирования и отправки: без личных путей."""
    try:
        return scrub(crash_path().read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return ""


def log_exists() -> bool:
    try:
        return log_path().is_file()
    except OSError:
        return False


def open_log_folder() -> bool:
    from . import sysenv
    from PyQt6.QtCore import QUrl
    return sysenv.open_url(QUrl.fromLocalFile(str(log_path().parent)))


# --- окно ---------------------------------------------------------------------------------------------------------

def attach(qapp) -> None:
    """Связка с основным потоком Qt: ошибки из любых потоков показываются окном в основном. Вызывается после
    создания QApplication; окно разрешается, когда начался цикл событий (set_loop_running)."""
    from PyQt6.QtCore import QObject, pyqtSignal

    class Bridge(QObject):
        failed = pyqtSignal(str)

    bridge = Bridge(qapp)
    bridge.failed.connect(show_window)
    state["bridge"] = bridge


def set_loop_running(running: bool = True) -> None:
    state["loop"] = running


def should_show() -> bool:
    now = state["clock"]()
    last = state["last_shown"]
    return last is None or now - last >= SHOW_INTERVAL_S


def show_window(report: str):
    """Окно «Что-то пошло не так», не чаще раза в минуту и не второе поверх открытого. Возвращает окно или None."""
    try:
        old = state["open_window"]
        try:
            if old is not None and old.isVisible():
                return None
        except RuntimeError:
            pass
        if not should_show():
            return None
        state["last_shown"] = state["clock"]()
        dlg = build_window(report)
        state["open_window"] = dlg
        dlg.setProperty("clipsd_closable", True)   # не мешает Alt+W и выходу для обновления
        dlg.show()
        return dlg
    except Exception:
        return None


def build_window(report: str):
    from PyQt6.QtGui import QGuiApplication
    from PyQt6.QtWidgets import QPushButton
    from . import sysenv, updater
    from .dialogs import MessageCard
    from .i18n import tr
    dlg = MessageCard(None, tr("errlog.title"), tr("errlog.text"), "warning", primary=tr("errlog.close"),
                      secondary=tr("errlog.copy"), modal=False, width=620)
    dlg.report = report
    dlg.status = dlg.status_label()

    def copy():
        QGuiApplication.clipboard().setText(report)
        dlg.show_status(dlg.status, tr("errlog.copied"), "ok")
        dlg.copy_done = True

    def send():
        """Только по нажатию: с приёмником (updater.REPORT_ENDPOINT) отправка, без него письмо в поддержку."""
        title = "Непредвиденная ошибка"
        if updater.REPORT_ENDPOINT:
            ok = updater.send_report(report, title, kind="error")
            dlg.show_status(dlg.status, tr("updater.report.sent" if ok else "updater.report.send_failed"),
                            "ok" if ok else "error")
        else:
            sysenv.open_url(updater.mail_url("ClipSD: " + title, report))
        dlg.send_done = True

    dlg.secondary_button.clicked.disconnect()   # «Скопировать отчёт» не закрывает окно
    dlg.secondary_button.clicked.connect(copy)
    dlg.send_button = QPushButton(tr("errlog.send"))
    dlg.send_button.setObjectName("clipSecondary")
    dlg.send_button.setCursor(dlg.secondary_button.cursor())
    dlg.footer_right.insertWidget(dlg.footer_right.indexOf(dlg.secondary_button) + 1, dlg.send_button)
    dlg.send_button.clicked.connect(send)
    dlg.copy_report, dlg.send_report = copy, send
    return dlg
