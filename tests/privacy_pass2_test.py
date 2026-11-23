# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""В2 проверки 1.36.1: второй проход распознавания «Скрыть личные данные» и смена снимка.

Второй проход (усиление контраста) идёт в фоне. Пока он шёл: (1) снимок обрезали: старые слова к новому снимку не
относятся, итог игнорируется, кружок убран, ничего не размыто; (2) окно закрыли: итог игнорируется без ошибок;
(3) человек нажал «Скрыть личные данные» ещё раз: итог прежнего прохода игнорируется, работает только новый.
Без смены снимка второй проход по-прежнему даёт панель с находкой. Распознавание подменено (ocr.start).

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/privacy_pass2_test.py
"""
import tmpclean  # noqa: F401
import os
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
tmp = tempfile.mkdtemp(prefix="clipsd-pass2-")
for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[name] = os.path.join(tmp, name)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.pop("CLIPSD_LANG", None)

from PyQt6.QtCore import QPoint, QRectF  # noqa: E402
from PyQt6.QtGui import QImage  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

qapp = QApplication(sys.argv)
qapp.setQuitOnLastWindowClosed(False)
from clipshot import app as appmod, i18n, ocr  # noqa: E402
from clipshot.ocr import Word  # noqa: E402

failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


i18n.set_language("ru")
a = appmod.Clipshot(qapp)
a.notify = lambda *_x: None
a.config.update(dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True, privacy_second_pass=True))
a.save_config = lambda: None

calls = []


class Job:
    words = []


def fake_start(image, done, *args, **kw):
    calls.append(done)
    return Job()


ocr.start = fake_start
WORDS = [Word("Почта:", QRectF(500, 300, 60, 16), 0), Word("ivan@example.org", QRectF(570, 300, 160, 16), 0)]


def editor():
    img = QImage(800, 400, QImage.Format.Format_RGB32)
    img.fill(0xFFFFFF)
    ed = a.open_editor(img, QPoint(40, 40))
    QTest.qWait(150)
    ed.canvas.set_words(list(WORDS), 1.0)
    return ed


def spinners(ed):
    from clipshot.busy import BusySpinner
    return [w for w in ed.scroll.viewport().findChildren(BusySpinner) if w.isVisible()]


def close(ed):
    ed.canvas.modified = False
    ed.exported = True
    ed.close()
    QTest.qWait(80)


# 0. без смены снимка второй проход даёт находку
ed = editor()
calls.clear()
ed.hide_personal()
QTest.qWait(30)
check(len(calls) == 1 and ed._privacy_pass2 is not None and ed.privacy_session is None, "второй проход запущен, панель ждёт его")
calls[-1]("", "")
QTest.qWait(30)
check(ed.privacy_session is not None and ed._privacy_pass2 is None and not spinners(ed), "без смены снимка: находка показана, кружок убран")
close(ed)

# 1. снимок обрезали, пока шёл второй проход
ed = editor()
calls.clear()
ed.hide_personal()
QTest.qWait(30)
ed.canvas.base = ed.canvas.base.copy(200, 200, 600, 200)
n0 = len(ed.canvas.shapes)
calls[-1]("", "")
QTest.qWait(30)
check(ed.privacy_session is None and len(ed.canvas.shapes) == n0, "снимок сменился: старые слова не размываются, панели нет")
check(ed._privacy_pass2 is None and not spinners(ed), "снимок сменился: кружок остановлен, проход закончен")
close(ed)

# 2. окно закрыли, пока шёл второй проход
ed = editor()
calls.clear()
ed.hide_personal()
QTest.qWait(30)
done_late = calls[-1]
close(ed)
try:
    done_late("", "")
    late_ok = True
except Exception as exc:   # noqa: BLE001
    late_ok = False
    print("исключение:", exc)
check(late_ok and ed._privacy_pass2 is None, "окно закрыто: запоздавший итог второго прохода игнорируется без ошибок")

# 3. новое нажатие «Скрыть личные данные»: итог прежнего прохода игнорируется
ed = editor()
calls.clear()
ed.hide_personal()
QTest.qWait(30)
old_done = calls[-1]
ed.hide_personal()
QTest.qWait(30)
check(len(calls) == 2 and ed._privacy_pass2 is not None, "новое нажатие запускает новый второй проход")
check(len(spinners(ed)) <= 1, f"кружок один ({len(spinners(ed))})")
old_done("", "")
QTest.qWait(30)
check(ed.privacy_session is None and ed._privacy_pass2 is not None, "итог прежнего прохода игнорируется, новый ещё идёт")
calls[-1]("", "")
QTest.qWait(30)
check(ed.privacy_session is not None and ed._privacy_pass2 is None and not spinners(ed), "итог нового прохода показан")
close(ed)

print("\nИТОГ:", "провалено %d" % len(failures) if failures else "всё хорошо")
sys.exit(1 if failures else 0)
