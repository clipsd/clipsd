# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Отложенные вызовы редактора после закрытия окна (Linux CI, прогон 45288065564, срез 6f4411e).

privacy_small_grey_test падал аварийно (Aborted, core dumped): set_zoom ставил QTimer.singleShot(0, keep_point), окно
закрывали и удаляли раньше, keep_point обращался к удалённому QScrollArea, RuntimeError в обработчике Qt роняет PyQt6.
Проверяется: later() не вызывает функцию удалённого владельца; масштаб, «Вписать», панель «Скрыть личные данные» сбоку
(рост окна, подгонка снимка) и сразу закрытие с удалением окна, затем цикл событий: программа не падает, исключений нет.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/later_closed_test.py
"""
import tmpclean  # noqa: F401
import os
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
tmp = tempfile.mkdtemp(prefix="clipsd-later-")
for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[name] = os.path.join(tmp, name)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.pop("CLIPSD_LANG", None)

from PyQt6 import sip  # noqa: E402
from PyQt6.QtCore import QPoint, QRectF  # noqa: E402
from PyQt6.QtGui import QImage  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

qapp = QApplication(sys.argv)
qapp.setQuitOnLastWindowClosed(False)
from clipshot import app as appmod, i18n  # noqa: E402
from clipshot.later import later  # noqa: E402
from clipshot.ocr import Word  # noqa: E402

failures = []
errors = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


real_hook = sys.excepthook
sys.excepthook = lambda t, v, tb: (errors.append(f"{t.__name__}: {v}"), real_hook(t, v, tb))

# 1. later(): владелец удалён до срока
calls = []
w = QWidget()
later(w, 0, lambda: calls.append(w.width()))
sip.delete(w)
QTest.qWait(50)
check(calls == [] and not errors, "later: владелец удалён, функция не вызвана")
w = QWidget()
later(w, 0, lambda: calls.append("ok"))
QTest.qWait(50)
check(calls == ["ok"], "later: живой владелец, функция вызвана")
check(later(w, 0, lambda: None) is not None, "later возвращает таймер")
sip.delete(w)
check(later(w, 0, lambda: calls.append("dead")) is None, "later с уже удалённым владельцем: таймер не создаётся")

i18n.set_language("ru")
a = appmod.Clipshot(qapp)
a.notify = lambda *_x: None
a.config.update(dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True, privacy_second_pass=False))
a.save_config = lambda: None


def editor():
    img = QImage(1200, 800, QImage.Format.Format_RGB32)
    img.fill(0xFFFFFF)
    ed = a.open_editor(img, QPoint(40, 40))
    QTest.qWait(150)
    return ed


def kill(ed):
    """Закрыть и сразу удалить окно, раньше отложенных вызовов."""
    ed.canvas.modified = False
    ed.exported = True
    ed.close()
    sip.delete(ed)


def scenario(name, act):
    errors.clear()
    ed = editor()
    act(ed)
    kill(ed)
    QTest.qWait(300)
    check(not errors, f"{name}: окно удалено раньше отложенного вызова, ошибок нет {errors}")


scenario("масштаб (keep_point)", lambda ed: ed.set_zoom(2.0))
scenario("масштаб с точкой (keep_point)", lambda ed: ed.zoom_by(0.5))
scenario("«Вписать»", lambda ed: (ed.set_zoom(2.0), ed.zoom_fit()))


def privacy(ed):
    ed.canvas.set_words([Word("Почта:", QRectF(500, 300, 60, 16), 0), Word("ivan@example.org", QRectF(570, 300, 160, 16), 0)], 1.0)
    ed.set_zoom(1.5)
    ed._zoom_fit_mode = True
    ed.hide_personal()   # панель сбоку: окно растёт, снимок подгоняется отложенно


scenario("панель «Скрыть личные данные» сбоку", privacy)


def privacy_close_panel(ed):
    privacy(ed)
    QTest.qWait(50)
    ed.privacy_panel.hide()   # панель ушла: окно возвращает размер, снимок подгоняется отложенно
    ed.set_zoom(0.7)


scenario("панель закрыта и снова масштаб", privacy_close_panel)

sys.excepthook = real_hook
print("\nИТОГ:", "провалено %d" % len(failures) if failures else "всё хорошо")
sys.exit(1 if failures else 0)
