# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""1.36.1: боковая панель «Скрыть личные данные» появляется сбоку и не уменьшает снимок (слова владельца 23.11.2026).

Окно растёт вбок на ширину панели, масштаб и размер поля снимка те же, окно остаётся на экране (сдвигается, если у края),
при закрытии панели геометрия возвращается; если окно тронули, снимается только ширина панели.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/panel_side_test.py
"""
import tmpclean  # noqa: F401
import json
import os
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
tmp = tempfile.mkdtemp(prefix="clipsd-panel-")
for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[name] = os.path.join(tmp, name)
screen = os.path.join(tmp, "screen.json")
with open(screen, "w", encoding="utf-8") as f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1900, "height": 1000, "logicalDpi": 144, "logicalBaseDpi": 96}]}, f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + screen
os.environ.pop("CLIPSD_LANG", None)

from PyQt6.QtCore import QPoint, QRect  # noqa: E402
from PyQt6.QtGui import QGuiApplication, QImage  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

qapp = QApplication(sys.argv)
from clipshot import app as appmod, i18n  # noqa: E402

failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


def settle(ms=120):
    for _ in range(5):
        qapp.processEvents()
        QTest.qWait(max(1, ms // 5))


i18n.set_language("ru")
a = appmod.Clipshot(qapp)
a.notify = lambda *_x: None
a.save_config = lambda: None
a.config.update(dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True))
img = QImage(700, 420, QImage.Format.Format_RGB32)
img.fill(0xFFFFFF)
area = QGuiApplication.primaryScreen().availableGeometry()
for label, at in (("в середине экрана", QPoint(200, 120)), ("у правого края", QPoint(area.right() - 760, 120))):
    ed = a.open_editor(img, at)
    ed.show()
    ed.zoom_fit()
    settle(300)
    g0, z0, c0, w0 = QRect(ed.geometry()), ed.canvas.zoom, ed.canvas.size(), ed.width()
    ed.privacy_panel.show()
    settle(300)
    grown = ed.width() - w0
    check(grown >= ed.privacy_panel.width(), f"{label}: окно выросло на ширину панели ({grown} >= {ed.privacy_panel.width()})")
    check(abs(ed.canvas.zoom - z0) < 0.01 and abs(ed.canvas.width() - c0.width()) <= 8, f"{label}: масштаб и поле снимка те же ({z0} → {ed.canvas.zoom}; {c0.width()}x{c0.height()} → {ed.canvas.width()}x{ed.canvas.height()})")
    check(area.contains(ed.geometry()), f"{label}: окно целиком на экране")
    ed.privacy_panel.hide()
    settle(300)
    check(ed.geometry() == g0, f"{label}: после закрытия геометрия как была ({ed.geometry()} против {g0})")
    ed.canvas.modified = False
    ed.exported = True
    ed.close()
    settle(100)
# окно тронули, пока панель открыта: снимается только ширина панели
ed = a.open_editor(img, QPoint(200, 120))
ed.show()
settle(300)
w0 = ed.width()
ed.privacy_panel.show()
settle(300)
ed.move(ed.x() + 40, ed.y())
settle(100)
ed.privacy_panel.hide()
settle(300)
check(ed.width() == w0, f"окно передвинули: после закрытия панели ширина как была ({ed.width()} против {w0})")
ed.canvas.modified = False
ed.exported = True
ed.close()
print("\nИТОГ:", "провалено %d" % len(failures) if failures else "всё хорошо")
sys.exit(1 if failures else 0)
