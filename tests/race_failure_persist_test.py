# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Н2 проверки 1.32.3: окно сбоя обновления, ждущее спокойной минуты, не пропадает при выходе программы.

С 1.32.3 окно сбоя при открытом редакторе или окне выделения ждёт спокойной минуты (Г8). Запись попытки к этому моменту
уже удалена: если программа выходила раньше (выход из сеанса, перезагрузка), окно не показывалось никогда, и человек
не узнавал, что обновление не встало. Теперь ждущее окно хранится на диске до показа, следующий запуск его покажет.

Порядки: окно ждёт, программа выходит, следующий запуск показывает окно; окно показано в той же работе (после
спокойной минуты), следующий запуск ничего не показывает; программа уже новой версии: старое окно не показывается.

Запуск: python3 tests/race_failure_persist_test.py
"""
import sys
from datetime import timedelta
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
        self.failed_shown = []

    def failed(self, version, report, title, hint=""):
        self.failed_shown.append(version)
        return "close"

    def __getattr__(self, name):
        return lambda *a, **k: None


class Ctx:
    def __init__(self, editor_open):
        self.config = {}
        self.editors = [object()] if editor_open else []
        self.selector = self.insert_target = None

    def save_config(self):
        pass

    def notify(self, text):
        pass

    def quit_blocker(self):
        return ""


NOW = up.utcnow()
clock = [NOW]


def updater(installed="1.32.2", editor_open=False):
    ui = UI()
    u = up.Updater(Ctx(editor_open), kind="linux", installed=installed, ui=ui, clock=lambda: clock[0])
    return u, ui


def failed_attempt():
    up.write_attempt(up.attempt_path(), "1.32.2", "1.32.3", NOW - timedelta(minutes=11))


saved = up.mark_dir() / getattr(up, "FAILURE_PENDING", "update-failure-pending.json")

# --- 1. окно ждёт (открыт редактор), программа выходит, следующий запуск ----------------------------------------
failed_attempt()
u1, ui1 = updater(editor_open=True)
u1.check_previous_attempt()
check(not ui1.failed_shown, "редактор открыт: окно сбоя ждёт спокойной минуты")
check(not up.attempt_path().exists(), "запись попытки уже удалена (как и раньше)")
# программа вышла, не дождавшись; следующий запуск, ничего не открыто
u2, ui2 = updater()
u2.check_previous_attempt()
check(ui2.failed_shown == ["1.32.3"], f"следующий запуск показывает окно сбоя ({ui2.failed_shown})")
u3, ui3 = updater()
u3.check_previous_attempt()
check(not ui3.failed_shown and not saved.exists(), "показанное окно больше не повторяется")

# --- 2. окно показано в той же работе: следующий запуск ничего не показывает -------------------------------------
failed_attempt()
u1, ui1 = updater(editor_open=True)
u1.check_previous_attempt()
u1.check_previous_attempt()                          # таймер ещё раз: окно в очереди одно
u1.ctx.editors = []                                  # редактор закрыт
poll = getattr(u1, "quiet_poll", lambda: False)
poll()
clock[0] += timedelta(seconds=61)
poll()
check(ui1.failed_shown == ["1.32.3"], f"после спокойной минуты окно сбоя одно ({ui1.failed_shown})")
u2, ui2 = updater()
u2.check_previous_attempt()
check(not ui2.failed_shown, "следующий запуск: окно уже было показано, повтора нет")

# --- 3. программа уже новой версии: старое окно не показывается ------------------------------------------------
failed_attempt()
u1, ui1 = updater(editor_open=True)
u1.check_previous_attempt()
u2, ui2 = updater(installed="1.32.3")
u2.check_previous_attempt()
check(not ui2.failed_shown and not saved.exists(), "версия уже новая: окно сбоя прошлой попытки не показано, запись убрана")

print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено {len(failures)}")
from clipshot.exitutil import quick_exit  # noqa: E402
quick_exit(1 if failures else 0)
