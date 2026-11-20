# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Н3 проверки 1.32.3: «Проверить обновления», пока открыто окно сбоя обновления.

Пока окно сбоя на экране, программа занята (Г5), и нажатие «Проверить обновления» молча ничего не делало. Теперь оно
поднимает окно сбоя (там «Повторить»). Окно сбоя записывается, нажатие делается изнутри него (как из меню значка во
время вложенного цикла событий). Обратный порядок: окна нет, нажатие начинает обычную проверку.

Запуск: python3 tests/race_manual_check_failure_test.py
"""
import sys
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


class UI:
    def __init__(self):
        self.events = []

    def failed(self, version, report, title, hint=""):
        self.events.append("failed")
        self.events.append(("pressed", u.check_now(manual=True)))   # «Проверить обновления» при открытом окне
        return "close"

    def failure_show(self):
        self.events.append("failure_show")

    def __getattr__(self, name):
        return lambda *a, **k: self.events.append(name)


class Ctx:
    config = {}
    editors = []
    selector = insert_target = None

    def save_config(self):
        pass

    def notify(self, text):
        pass

    def quit_blocker(self):
        return ""


requests = []
ui = UI()
u = up.Updater(Ctx(), fetch=lambda url, limit: requests.append(url) or b"", kind="linux", installed="2.0.0", ui=ui,
               sync=True, stable_keys=[], test_keys=[])
record = {"from": "2.0.0", "to": "2.0.1", "attempt_id": "deadbeef0000", "trace_id": "t", "time": up.uc.format_utc(up.utcnow())}
u._show_failure(record, "no_start_mark", "switch")
check("failure_show" in ui.events, f"нажатие при открытом окне сбоя поднимает его ({ui.events})")
check(not requests, "второй запрос к каналу поверх окна сбоя не отправлялся")
ui.events.clear()
check(u.check_now(manual=True) is True and requests, "окна сбоя нет: нажатие начинает обычную проверку")

real = up.UpdaterUI()
real.failure_show()                        # окна сбоя нет: ничего не делает
check(getattr(real, "_failed", None) is None, "настоящий UpdaterUI без окна сбоя: failure_show ничего не делает")

print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено {len(failures)}")
from clipshot.exitutil import quick_exit  # noqa: E402
quick_exit(1 if failures else 0)
