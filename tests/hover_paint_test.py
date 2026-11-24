# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""1.36.1: отрисовка под мышью и в фокусе не падает (ошибка «QPen(NoPen, 1)» в «Ознакомлении» у владельца).

В тестах окна не бывают «под мышью» и «в фокусе», поэтому ветки paintEvent для наведения и фокуса не выполнялись, а у
владельца на Windows каждое наведение на строку списка давало окно «Что-то пошло не так». Исключение в paintEvent
PyQt6 не пробрасывает, а отдаёт в sys.excepthook: тест ставит свой excepthook и считает вызовы.

Проверяется: (1) каждая строка списка «Ознакомления» во всех состояниях (выбрана, под мышью без фокуса, в фокусе, обычная),
светлая и тёмная темы; (2) основные самописные виджеты: окно «Ознакомление», окно настроек, «О программе», редактор,
выделение, окно обновления рисуются с WA_UnderMouse и с фокусом без исключений.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/hover_paint_test.py
"""
import tmpclean  # noqa: F401
import os
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
tmp = tempfile.mkdtemp(prefix="clipsd-hov-")
for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[name] = os.path.join(tmp, name)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.pop("CLIPSD_LANG", None)

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QImage  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

qapp = QApplication(sys.argv)

from clipshot import app as appmod, i18n, novoe, oznakomlenie  # noqa: E402

failures = []
errors = []


def _hook(t, v, tb):
    import traceback
    errors.append("".join(traceback.format_exception(t, v, tb)))


sys.excepthook = _hook


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


def settle(ms=60):
    for _ in range(4):
        qapp.processEvents()
        QTest.qWait(max(1, ms // 4))


def paint_states(w, label):
    """Рисует виджет во всех состояниях: обычный, под мышью, в фокусе, под мышью и в фокусе."""
    before = len(errors)
    for under in (False, True):
        for focus in (False, True):
            w.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, under)
            if focus:
                w.setFocus(Qt.FocusReason.OtherFocusReason)
            else:
                w.clearFocus()
            w.grab()
            w.repaint()
    w.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
    check(len(errors) == before, f"{label}: рисуется во всех состояниях" + ("" if len(errors) == before else "\n" + errors[-1]))


i18n.set_language("ru")
a = appmod.Clipshot(qapp)
a.save_config = lambda: None
a.notify = lambda *_x: None
a.config.update(dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True))
novoe.on_start(a.config)

# --- 1. строки «Ознакомления» ---------------------------------------------------------------------------------
for dark in (False, True):
    a.config["theme"] = "dark" if dark else "light"
    win = a.open_oznakomlenie()
    settle(120)
    rows = list(win.rows.values())
    check(len(rows) >= 25, f"строк в списке: {len(rows)} ({'тёмная' if dark else 'светлая'})")
    before = len(errors)
    for row in rows:
        row.dark = dark
        for checked in (False, True):
            row.setChecked(checked)
            for under in (False, True):
                for focus in (False, True):
                    row.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, under)
                    row.setFocus(Qt.FocusReason.OtherFocusReason) if focus else row.clearFocus()
                    row.grab()
        row.setChecked(False)
        row.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
    check(len(errors) == before, f"каждая строка списка во всех состояниях ({'тёмная' if dark else 'светлая'})"
          + ("" if len(errors) == before else "\n" + errors[-1]))
    # реальное наведение мыши на строку
    row = rows[0]
    QTest.mouseMove(row, row.rect().center())
    settle(60)
    row.update()
    settle(60)
    check(len(errors) == before, "наведение мыши на строку без исключений")
    paint_states(win, "окно «Ознакомление»")
    win.close()
    settle(200)

# --- 2. остальные самописные окна -----------------------------------------------------------------------------
widgets = []
try:
    from clipshot import settings as st
    s = st.SettingsDialog(a.config)
    if s is not None:
        widgets.append(("окно настроек", s))
except Exception as e:  # noqa: BLE001
    print("пропуск настроек:", e)
for label, w in widgets:
    w.show()
    settle(100)
    paint_states(w, label)
    # все дочерние виджеты по очереди под мышью
    kids = [k for k in w.findChildren(QWidget) if k.isVisible()]
    before = len(errors)
    for k in kids:
        k.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
        k.grab()
        k.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
    check(len(errors) == before, f"{label}: {len(kids)} дочерних виджетов под мышью" + ("" if len(errors) == before else "\n" + errors[-1]))
    w.close()

# редактор
img = QImage(400, 300, QImage.Format.Format_RGB32)
img.fill(0xffffff)
from PyQt6.QtCore import QPoint  # noqa: E402
print("editor...", flush=True)
try:
    ed = a.open_editor(img, QPoint(50, 50))
except BaseException as exc:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    raise
print("editor opened", flush=True)
if ed is not None:
    ed.show()
    settle(150)
    paint_states(ed, "редактор")
    kids = [k for k in ed.findChildren(QWidget) if k.isVisible()]
    before = len(errors)
    for k in kids:
        k.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
        k.setFocus(Qt.FocusReason.OtherFocusReason)
        k.grab()
        k.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
    check(len(errors) == before, f"редактор: {len(kids)} дочерних виджетов под мышью и в фокусе"
          + ("" if len(errors) == before else "\n" + errors[-1]))
    ed.canvas.modified = False
    ed.close()
settle(100)

print("\nИТОГ:", "провалено %d" % len(failures) if failures else "всё хорошо")
sys.exit(1 if failures else 0)
