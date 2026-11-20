# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Г12 проверки гонок 1.32.2: «Проверить обновления» во время тихой проверки.

Человек жмёт «Проверить обновления» в меню значка или в колокольчике ровно тогда, когда идёт тихая проверка (60 с
после запуска или раз в сутки). В 1.32.2 нажатие при занятой проверке молча выходило, а тихая проверка заканчивалась
как тихая: обычная новая версия уходила в колокольчик, окна не было. Кнопка не отвечала.

Теперь нажатие присоединяется к идущей проверке: её итог приходит окном, как после любого нажатия. Момент задаёт
тест: ответ канала ждёт сигнала (Event, предел 10 с). Порядки: тихая проверка, потом нажатие (новая версия: окно
предложения; версия та же: «установлена последняя»); нажатие, потом тихая проверка по таймеру (окно одно).

Запуск: python3 tests/race_manual_check_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import shutil
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)
import channel_sign as cs  # noqa: E402
from clipshot import updater as up  # noqa: E402

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


keys = Path(tempfile.mkdtemp(prefix="clipsd-race-keys-"))
try:
    PUB = cs.keygen(keys / "s.pem")
    PRIV = cs.load_private(keys / "s.pem")
finally:
    shutil.rmtree(keys, ignore_errors=True)
NOW = datetime.now(timezone.utc)


def channel(version):
    doc = cs.dump({"schema": 1, "channel": "stable", "version": version, "released": cs.utc(NOW - timedelta(days=1)),
                   "expires": cs.utc(NOW + timedelta(days=30)),
                   "files": {p: {"url": f"https://example.invalid/f-{p}", "size": 10, "sha256": "0" * 64}
                             for p in ("windows", "linux")},
                   "notes": {"en": "n", "ru": "n"}})
    return doc, cs.sign_bytes(PRIV, doc)


def wait_for(cond, limit=10.0):
    end = time.monotonic() + limit
    while not cond() and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)
    return cond()


class UI:
    def __init__(self):
        self.shown = []

    def offer(self, manifest, installed, critical=False):
        self.shown.append("offer")
        return "later"

    def info(self, text):
        self.shown.append("info")

    def error(self, text):
        self.shown.append("error")

    def __getattr__(self, name):
        return lambda *a, **k: None


class Ctx:
    editors = []
    selector = insert_target = None

    def __init__(self):
        self.config = {}

    def save_config(self):
        pass

    def notify(self, text):
        pass

    def quit_blocker(self):
        return ""


def make(version):
    doc, sig = channel(version)
    release = threading.Event()
    requests = []

    def fetch(url, limit):
        if not url.endswith(".sig"):
            requests.append(url)
            release.wait(10)                 # ответ канала: когда скажет тест
        return sig if url.endswith(".sig") else doc

    ui = UI()
    u = up.Updater(Ctx(), fetch=fetch, kind="linux", installed="2.0.0", ui=ui, stable_keys=[PUB], test_keys=[])
    return u, ui, release, requests


# --- 1. тихая проверка идёт, человек жмёт кнопку; новая версия ---------------------------------------------------
u, ui, release, requests = make("2.0.1")
check(u.check_now(manual=False), "тихая проверка началась")
check(wait_for(lambda: bool(requests), 5), "запрос к каналу идёт")
u.check_now(manual=True)                      # «Проверить обновления» в этот момент
release.set()
check(wait_for(lambda: not u.busy and ui.shown, 10), "проверка закончилась")
check(ui.shown == ["offer"], f"нажатие во время тихой проверки: показано окно «Доступна версия» ({ui.shown})")
check(len(requests) == 1, f"второй запрос к каналу не отправлялся ({len(requests)})")

# --- 2. то же, версия та же: «установлена последняя версия» ------------------------------------------------------
u, ui, release, requests = make("2.0.0")
u.check_now(manual=False)
wait_for(lambda: bool(requests), 5)
u.check_now(manual=True)
release.set()
check(wait_for(lambda: not u.busy and ui.shown, 10) and ui.shown == ["info"],
      f"нажатие во время тихой проверки, обновлений нет: окно «установлена последняя версия» ({ui.shown})")

# --- 3. обратный порядок: нажатие, потом таймер тихой проверки ----------------------------------------------------
u, ui, release, requests = make("2.0.1")
check(u.check_now(manual=True), "ручная проверка началась")
wait_for(lambda: bool(requests), 5)
check(u.check_now(manual=False) is False, "таймер тихой проверки во время ручной ничего не начинает")
release.set()
check(wait_for(lambda: not u.busy and ui.shown, 10) and ui.shown == ["offer"],
      f"окно предложения одно ({ui.shown})")

# --- 4. тихая проверка без нажатия: окна нет, как раньше (колокольчик) ------------------------------------------
u, ui, release, requests = make("2.0.1")
u.check_now(manual=False)
release.set()
wait_for(lambda: not u.busy and bool(requests), 10)
wait_for(lambda: False, 0.3)
check(ui.shown == [], f"тихая проверка без нажатия: окна нет, версия в колокольчике ({ui.shown})")

print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено {len(failures)}")
from clipshot.exitutil import quick_exit  # noqa: E402
quick_exit(1 if failures else 0)
