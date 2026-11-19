# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
"""Масштаб вида в редакторе: кнопки, Ctrl+колесо, клавиши; рисование при любом масштабе; итоговый снимок.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/zoom_test.py
"""
import os
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QPointF, Qt, QEvent
from PyQt6.QtGui import QColor, QImage, QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QPushButton

app = QApplication(sys.argv)
from clipshot import app as appmod
from clipshot.editor import EditorWindow, RECT
failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


class Ctx:
    config = dict(appmod.DEFAULTS)
    icon = appmod.make_icon()
    def copy_image(self, image): pass
    def notify(self, text): pass
    def save_config(self): pass


def wheel(widget, pos, delta, mods):
    g = widget.mapToGlobal(pos)
    ev = QWheelEvent(QPointF(pos), QPointF(g), QPoint(0, 0), QPoint(0, delta), Qt.MouseButton.NoButton, mods,
                     Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(widget, ev)


def run(img_w, img_h, label):
    img = QImage(img_w, img_h, QImage.Format.Format_RGB32)
    img.fill(QColor("#dfe6ee"))
    ed = EditorWindow(img, Ctx(), QPoint(50, 50))
    ed.present()
    for _ in range(8):
        app.processEvents()
        QTest.qWait(20)
    return ed


ed = run(560, 340, "малый")
c = ed.canvas
check(c.zoom == 1.0 and ed.zoom_label.text() == "100%", "малый снимок открывается в 100%")
size100 = (c.width(), c.height())

ed.zoom_step(1)
check(abs(c.zoom - 1.25) < 1e-6 and c.width() == round(560 * 1.25), "плюс: 125%, холст вырос")
ed.zoom_step(-1); ed.zoom_step(-1)
check(abs(c.zoom - 0.75) < 1e-6 and ed.zoom_label.text() == "75%", "минус дважды: 75%, подпись обновилась")
ed.set_zoom(1.0)
check((c.width(), c.height()) == size100, "100%: исходный размер")

wheel(c, QPoint(100, 100), 120, Qt.KeyboardModifier.ControlModifier)
check(c.zoom > 1.0, "Ctrl+колесо вверх увеличивает")
wheel(c, QPoint(100, 100), -240, Qt.KeyboardModifier.ControlModifier)
check(c.zoom < 1.0, "Ctrl+колесо вниз уменьшает")
z = c.zoom
wheel(c, QPoint(100, 100), 120, Qt.KeyboardModifier.NoModifier)
check(c.zoom == z, "колесо без Ctrl масштаб не меняет")
ed.set_zoom(1.0)

# Рисуем при масштабе 200%: клик в точке холста (200, 120) = точка снимка (100, 60)
ed.set_zoom(2.0)
app.processEvents(); QTest.qWait(30); app.processEvents()
ed.select_tool(RECT)
QTest.mousePress(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(200, 120))
QTest.mouseMove(c, QPoint(300, 200))
QTest.mouseRelease(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(300, 200))
check(len(c.shapes) == 1, "фигура нарисована при 200%")
if c.shapes:
    pts = c.shapes[0].points
    check(abs(pts[0].x() - 100) < 1.5 and abs(pts[0].y() - 60) < 1.5 and abs(pts[-1].x() - 150) < 1.5,
          f"координаты фигуры в системе снимка, а не экрана: {pts[0].x():.0f},{pts[0].y():.0f} .. {pts[-1].x():.0f},{pts[-1].y():.0f}")
out = c.render()
check((out.width(), out.height()) == (c.base.width(), c.base.height()), "итоговый снимок не зависит от масштаба")

# Текстовое поле при масштабе
from clipshot.editor import TEXT
c.start_text(QPointF(40, 40), TEXT)
check(c.text_edit is not None and c.text_edit.pos() == QPoint(80, 80), "поле текста стоит в масштабированной точке")
c.cancel_text()

ed.zoom_fit(); app.processEvents()
vp = ed.scroll.viewport().size()
check(c.zoom <= 1.0 and c.width() <= vp.width() + 2 and c.height() <= vp.height() + 2, "«Вписать»: снимок целиком в окне, не крупнее 100%")

# Большой снимок (как два монитора): сразу вписывается
big = run(6000, 1440, "большой")
bc = big.canvas
check(bc.zoom < 0.6, f"большой снимок открывается целиком: {round(bc.zoom * 100)}%")
check(bc.width() <= big.scroll.viewport().width() + 2, "по ширине помещается без полосы прокрутки")
big.zoom_step(1)
check(not big._zoom_fit_mode and bc.zoom > 0.1, "ручной масштаб отключает автовписывание")
big.set_zoom(8.0); big.set_zoom(20.0)
check(bc.zoom == 8.0, "верхний предел 800%")
big.set_zoom(0.01)
check(abs(bc.zoom - 0.1) < 1e-6, "нижний предел 10%")
print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено: {len(failures)}")
from clipshot.exitutil import quick_exit
quick_exit(1 if failures else 0)
