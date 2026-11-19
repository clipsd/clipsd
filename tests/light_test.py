# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
"""Лёгкость: при обычном снимке и в редакторе распознавание, перевод и сеть не загружаются и не работают в фоне;
они подключаются только по кнопке.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/light_test.py
"""
import os
import sys
import threading

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtGui import QColor, QImage, QPixmap
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
from clipshot import app as appmod
from clipshot.editor import EditorWindow
from clipshot.selector import RegionSelector
failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


HEAVY = ("clipshot.translate", "clipshot.ocr", "urllib.request", "http.client", "ssl")
pm = QPixmap(800, 600)
pm.fill(QColor("#ffffff"))
sel = RegionSelector(pm, QRect(0, 0, 800, 600), last_rect=QRect(50, 50, 300, 200))
sel.tr_cfg = dict(appmod.DEFAULTS)
sel.show()
app.processEvents()
sel.grab()


class Ctx:
    config = dict(appmod.DEFAULTS)
    icon = appmod.make_icon()
    def copy_image(self, image): pass
    def notify(self, text): pass
    def save_config(self): pass


ed = EditorWindow(QImage(400, 300, QImage.Format.Format_RGB32), Ctx(), QPoint(0, 0))
ed.present()
app.processEvents()
ed.grab()
loaded = [m for m in HEAVY if m in sys.modules]
check(not loaded, f"обычный снимок и редактор: распознавание, перевод и сеть не загружены ({loaded or 'ничего'})")
check(threading.active_count() == 1, f"фоновых потоков нет: {threading.active_count() - 1}")
check(not sel.tr_timer.isActive(), "таймер кружка перевода не крутится без перевода")
print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено: {len(failures)}")
from clipshot.exitutil import quick_exit
quick_exit(1 if failures else 0)
