# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Сообщение потока горячих клавиш доходит до человека (1.32.3).

Свои горячие клавиши (X11 вне GNOME, Windows) работают в отдельном потоке. Если сочетание занято другой программой или
клавиша неизвестна, поток зовёт Clipshot._hotkey_error. В 1.32.2 там был QTimer.singleShot(0, qapp, функция): такого
варианта в PyQt6 нет, вызов падал с TypeError внутри потока, и сообщение «сочетание занято» не показывалось.

Проверяется: настоящий поток X11Hotkeys без библиотеки Xlib (его сообщение об ошибке) и поток, как у Windows
(«сочетание занято»): сообщение приходит в главный поток (notify), исключений в потоках нет.

Запуск: python3 tests/hotkey_error_test.py
"""
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)
from clipshot import app as appmod  # noqa: E402
from clipshot.i18n import tr  # noqa: E402

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def wait_for(cond, limit=5.0):
    end = time.monotonic() + limit
    while not cond() and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)
    return cond()


thread_errors = []
threading.excepthook = lambda args: thread_errors.append(f"{args.exc_type.__name__}: {args.exc_value}")

ctx = appmod.Clipshot(app)
shown = []
ctx.notify = lambda text: shown.append((text, threading.current_thread() is threading.main_thread()))

# --- 1. настоящий поток X11Hotkeys, библиотеки Xlib нет: его сообщение об ошибке -------------------------------
saved = sys.modules.get("Xlib", "missing")
sys.modules["Xlib"] = None                    # import Xlib в потоке даёт ImportError
try:
    hk = appmod.X11Hotkeys({"Alt+W": "region"}, ctx.command_received.emit, ctx._hotkey_error)
    hk.start()
    hk.join(5)
finally:
    if saved == "missing":
        sys.modules.pop("Xlib", None)
    else:
        sys.modules["Xlib"] = saved
check(wait_for(lambda: bool(shown), 5), f"сообщение потока X11 дошло до человека ({shown})")
check(shown[:1] == [(tr("app.err_xlib"), True)], "текст «нет Xlib», показан из главного потока")

# --- 2. поток, как у Windows: сочетание занято другой программой ---------------------------------------------
shown.clear()
busy = tr("app.err_hotkey_busy", combo="Alt+W")
t = threading.Thread(target=ctx._hotkey_error, args=(busy,))
t.start()
t.join(5)
check(wait_for(lambda: bool(shown), 5) and shown[0] == (busy, True),
      f"«сочетание занято» из потока клавиш показано в главном потоке ({shown})")
check(not thread_errors, f"исключений в потоках нет {thread_errors}")

print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено {len(failures)}")
from clipshot.exitutil import quick_exit  # noqa: E402
quick_exit(1 if failures else 0)
