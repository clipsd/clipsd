# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Г10 проверки гонок 1.32.2: щелчок по значку, а вместо окна выделения окно оценки.

Щелчок по значку откладывает окно выделения на 250 мс. В эти доли секунды программа считала, что ничего не открыто:
таймер окна оценки (раз в 5 с), отложенного предложения версии (раз в 30 с) и ответ на просьбу выйти для обновления
успевали сработать, а окно выделения, увидев модальное окно, не открывалось: щелчок пропадал.

Теперь запрошенный снимок (до открытия окна выделения) считается занятостью: окно оценки, предложение версии и выход
для обновления ждут. Момент задаёт тест: тик таймера вызывается сразу после щелчка, внутри 250 мс. Обратный порядок:
окно оценки уже открыто, потом щелчок: окно оценки закрывается, выделение открывается (как в 1.32).

Запуск: python3 tests/race_tray_click_test.py
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ["XDG_SESSION_TYPE"] = "x11"         # окно выделения X11: кадр сразу

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)
from clipshot import app as appmod, feedback, update_prompt  # noqa: E402

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


ctx = appmod.Clipshot(app)
ctx.config.update(theme_chosen=True, tour_done=True, usage_days=10, capture_count=30, rating_next_ts=0,
                  rating_shown=0, tour_selector_done=True)
check(feedback.should_show_rating(ctx.config), "окно оценки по правилам уже пора показать")

# --- 1. щелчок по значку, тик таймера оценки внутри 250 мс -------------------------------------------------
ctx._rating_quiet_since = time.monotonic() - 61     # спокойно больше минуты
ctx.capture_region(delay=250)                       # щелчок по значку (app._on_tray_activated)
check(update_prompt.busy_reason(ctx) == "selector", f"снимок запрошен: занято ({update_prompt.busy_reason(ctx)!r})")
check(ctx.quit_blocker() == "selector", f"снимок запрошен: выход для обновления ждёт ({ctx.quit_blocker()!r})")
shown = ctx.rating_quiet_poll()                     # тик таймера оценки в эти 250 мс
check(not shown and not feedback.is_open(ctx._rating), "окно оценки не открылось вместо выделения")
check(wait_for(lambda: ctx.selector is not None, 3), "окно выделения открылось по щелчку")
if ctx.selector is not None:
    QTest.keyClick(ctx.selector, Qt.Key.Key_Escape)
    wait_for(lambda: ctx.selector is None, 3)
check(not ctx.capture_pending() if hasattr(ctx, "capture_pending") else True,
      "после открытия окна выделения запроса снимка больше нет")

# --- 2. обратный порядок: окно оценки открыто, потом щелчок ------------------------------------------------
ctx.last_trigger = 0.0
ctx._rating_quiet_since = time.monotonic() - 61
check(ctx.maybe_offer_rating() and feedback.is_open(ctx._rating), "окно оценки открыто")
ctx.capture_region(delay=250)
check(wait_for(lambda: ctx.selector is not None, 3) and not feedback.is_open(ctx._rating),
      "щелчок при открытом окне оценки: оно закрыто, окно выделения открыто")
if ctx.selector is not None:
    QTest.keyClick(ctx.selector, Qt.Key.Key_Escape)

print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено {len(failures)}")
from clipshot.exitutil import quick_exit  # noqa: E402
quick_exit(1 if failures else 0)
