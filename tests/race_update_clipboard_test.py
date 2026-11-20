# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Н6 проверки 1.32.3: снимок, скопированный во время загрузки обновления, не пропадает из буфера обмена.

После «Обновить» окно загрузки пишет «Можно продолжать работу». Человек копирует снимок, загрузка кончается, и
программа сразу уходила на перезапуск, унося снимок из буфера (Windows всегда, X11 без менеджера буфера). В
отложенном обновлении такое ожидание уже было (Г4), теперь и здесь: установка ждёт, пока буфер держит только что
скопированное (не дольше 2 минут после копирования).

Момент задаёт тест: «буфер занят» подменён флагом (у Qt offscreen своего буфера нет). Порядки: буфер занят, когда
загрузка кончилась (установка ждёт и начинается, когда буфер освободился); буфер свободен (установка сразу).

Запуск: python3 tests/race_update_clipboard_test.py
"""
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)
from clipshot import updater as up  # noqa: E402

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


launched = []
up.launch_windows_installer = lambda path, lang, popen=None: launched.append(time.monotonic())


class UI:
    def __getattr__(self, name):
        return lambda *a, **k: None


busy = [True]


class Ctx:
    config = {}

    def save_config(self):
        pass

    def notify(self, text):
        pass

    def quit_blocker(self):
        return ""

    def clipboard_busy(self):
        return busy[0]


u = up.Updater(Ctx(), kind="windows", installed="2.0.0", ui=UI())
u.CLIPBOARD_POLL_MS = 100
manifest = types.SimpleNamespace(version="2.0.1", notes={"en": "n", "ru": "n"}, channel="stable")
setup = Path(up.downloads_dir()) / "ClipSD-2.0.1-Setup.exe"

# --- 1. загрузка кончилась, а снимок только что скопирован ----------------------------------------------------
u.busy = True
u._pending = (manifest, "t" * 32)
u.install(setup, manifest, "t" * 32)
wait_for(lambda: False, 0.5)
check(not launched and not up.attempt_path().exists(),
      "пока буфер держит только что скопированный снимок, установка не начинается")
busy[0] = False                       # снимок вставлен или прошло 2 минуты
check(wait_for(lambda: bool(launched), 3), "буфер освободился: установка началась")
check(len(launched) == 1, f"установка одна ({len(launched)})")
up._unlink(up.attempt_path())

# --- 2. буфер свободен: установка сразу, как раньше --------------------------------------------------------------
launched.clear()
u._pending = (manifest, "t" * 32)
t0 = time.monotonic()
u.install(setup, manifest, "t" * 32)
check(len(launched) == 1 and launched[0] - t0 < 0.5, "буфер свободен: установка сразу")
up._unlink(up.attempt_path())

print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено {len(failures)}")
from clipshot.exitutil import quick_exit  # noqa: E402
quick_exit(1 if failures else 0)
