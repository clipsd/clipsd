# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Г8 проверки гонок 1.32.2: окно сбоя обновления и «Что нового» по таймеру поверх окна выделения.

check_previous_attempt (через 2 с после запуска, через 10 мин после начала установки, раз в минуту) и наблюдение за
помощником открывали модальное окно сбоя и «Что нового», не глядя на окно выделения. Окно выделения держит клавиатуру,
под модальным окном оно не получало ни мыши, ни клавиш: выделение застывало.

Теперь эти окна при открытом окне выделения или редакторе ждут спокойной минуты (как предложение версии и окно
оценки), а при пустом экране показываются сразу. Окно выделения настоящее, окна обновления записываются, часы
подменены (спокойная минута проходит по команде теста). Порядки: окно выделения открыто, потом таймер; ничего не
открыто, потом таймер (окно сразу).

Запуск: python3 tests/race_update_window_selector_test.py
"""
import os
import sys
import time
from datetime import timedelta
from pathlib import Path

# окно выделения X11 (кадр берётся сразу), а не Wayland: проверке нужен открытый оверлей, а не снимок через GNOME
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ["XDG_SESSION_TYPE"] = "x11"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)
from clipshot import app as appmod, updater as up  # noqa: E402

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


class UI:
    def __init__(self):
        self.shown = []

    def failed(self, version, report, title, hint=""):
        self.shown.append(("failed", ctx.selector is not None, QApplication.activeModalWidget()))
        return "close"

    def whats_new(self, version, markdown):
        self.shown.append(("whats_new", ctx.selector is not None, None))

    def __getattr__(self, name):
        return lambda *a, **k: None


ctx = appmod.Clipshot(app)
ctx.config.update(theme_chosen=True, tour_done=True, tour_selector_done=True)
NOW = up.utcnow()
clock = [NOW]
ui = UI()
u = up.Updater(ctx, kind="linux", installed="1.32.2", ui=ui, clock=lambda: clock[0])
ctx._updater = u
poll = getattr(u, "quiet_poll", lambda: False)


def open_selector():
    ctx.capture_region()
    return wait_for(lambda: ctx.selector is not None and ctx.selector.isVisible(), 5)


def close_selector():
    sel = ctx.selector
    QTest.keyClick(sel, Qt.Key.Key_Escape)
    wait_for(lambda: ctx.selector is None, 5)
    ctx.last_trigger = 0.0


def quiet_minute():
    """Таймер спокойной минуты дважды: начало отсчёта, затем через 61 с по подменённым часам."""
    poll()
    clock[0] += timedelta(seconds=61)
    poll()


# --- 1. окно выделения открыто, по таймеру приходит итог прошлой (неудачной) попытки ------------------------------
up.write_attempt(up.attempt_path(), "1.32.2", "1.32.3", NOW - timedelta(minutes=11))
check(open_selector(), "окно выделения открыто")
u.check_previous_attempt()                   # таймер «через 2 с после запуска» / «через 10 мин после установки»
app.processEvents()
check(not ui.shown, f"пока открыто окно выделения, окна сбоя нет ({ui.shown})")
close_selector()
check(not ui.shown, "окно выделения закрыто: окно сбоя ждёт спокойной минуты")
quiet_minute()
check([s[0] for s in ui.shown] == ["failed"] and not ui.shown[0][1],
      f"после спокойной минуты окно сбоя показано, окна выделения нет ({ui.shown})")

# --- 2. то же с «Что нового» (программа уже новая) --------------------------------------------------------------
ui.shown.clear()
u2 = up.Updater(ctx, kind="linux", installed="1.32.3", ui=ui, clock=lambda: clock[0])
poll = getattr(u2, "quiet_poll", lambda: False)
up.write_attempt(up.attempt_path(), "1.32.2", "1.32.3", clock[0] - timedelta(minutes=1))
check(open_selector(), "окно выделения открыто")
u2.check_previous_attempt()
app.processEvents()
check(not ui.shown, f"пока открыто окно выделения, «Что нового» нет ({ui.shown})")
close_selector()
quiet_minute()
check([s[0] for s in ui.shown] == ["whats_new"], f"после спокойной минуты «Что нового» показано ({ui.shown})")

# --- 3. обратный случай: ничего не открыто, окно сразу ---------------------------------------------------------
ui.shown.clear()
up.write_attempt(up.attempt_path(), "1.32.2", "1.32.3", clock[0] - timedelta(minutes=11))
u3 = up.Updater(ctx, kind="linux", installed="1.32.2", ui=ui, clock=lambda: clock[0])
u3.check_previous_attempt()
check([s[0] for s in ui.shown] == ["failed"], "ничего не открыто: окно сбоя показывается сразу, как раньше")

print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено {len(failures)}")
from clipshot.exitutil import quick_exit  # noqa: E402
quick_exit(1 if failures else 0)
