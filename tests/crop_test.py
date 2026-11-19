# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
"""Обрезка в два шага: выделить, поправить (углы, стороны, перенос), подтвердить (кнопка, Enter, двойной щелчок) или отменить.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/crop_test.py
"""
import os
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
from clipshot import app as appmod
from clipshot.editor import CROP, EditorWindow, RECT
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


img = QImage(560, 340, QImage.Format.Format_RGB32)
img.fill(QColor("#dfe6ee"))
ed = EditorWindow(img, Ctx(), QPoint(50, 50))
ed.present()
for _ in range(6):
    app.processEvents(); QTest.qWait(20)
c = ed.canvas
L, NOMOD = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier


def drag(a, b, steps=6):
    QTest.mousePress(c, L, NOMOD, a)
    for i in range(1, steps + 1):
        QTest.mouseMove(c, QPoint(a.x() + (b.x() - a.x()) * i // steps, a.y() + (b.y() - a.y()) * i // steps))
    QTest.mouseRelease(c, L, NOMOD, b)
    app.processEvents()


def click(pt):
    drag(pt, pt, steps=1)


def start_crop(a=QPoint(100, 80), b=QPoint(400, 260)):
    ed.select_tool(CROP)
    drag(a, b)


# 1. Выделение не режет сразу
start_crop()
check(c.crop_pending and c.crop_rect == QRect(100, 80, 300, 180), f"рамка выделена и ждёт подтверждения: {c.crop_rect}")
check((c.base.width(), c.base.height()) == (560, 340), "снимок пока не обрезан")
check(not c.undo_stack, "в отмене пока ничего нет")
check(ed.info.text() == "Обрезка" and "Enter" in ed.info.toolTip(), "нижняя строка: «Обрезка», подробности во всплывающей подсказке")

# 2. Тянем правый нижний угол
drag(QPoint(400, 260), QPoint(450, 300))
check(c.crop_rect == QRect(100, 80, 350, 220), f"угол: {c.crop_rect}")
# левую сторону
drag(QPoint(100, 150), QPoint(60, 150))
check(c.crop_rect == QRect(60, 80, 390, 220), f"левая сторона: {c.crop_rect}")
# верхнюю
drag(QPoint(200, 80), QPoint(200, 40))
check(c.crop_rect == QRect(60, 40, 390, 260), f"верхняя сторона: {c.crop_rect}")
# перенос внутри
drag(QPoint(250, 170), QPoint(270, 190))
check(c.crop_rect == QRect(80, 60, 390, 260), f"перенос: {c.crop_rect}")
# перенос упирается в границы снимка
drag(QPoint(250, 170), QPoint(900, 900))
check(c.crop_rect.right() < 560 and c.crop_rect.bottom() < 340 and c.crop_rect.size() == QRect(0, 0, 390, 260).size(),
      f"перенос не выходит за снимок: {c.crop_rect}")
# нельзя вытянуть за границы и сжать в точку
drag(QPoint(c.crop_rect.right() + 1, 100), QPoint(2000, 100))
check(c.crop_rect.right() + 1 <= 560, f"сторона не уходит за снимок: {c.crop_rect}")
check(c.crop_pending, "рамка осталась ждать подтверждения")
check((c.base.width(), c.base.height()) == (560, 340), "после правок снимок всё ещё цел")

# 3. Кнопка «Обрезать»
c.cancel_crop()
start_crop(QPoint(100, 80), QPoint(300, 200))
check(c.crop_pending and ed.crop_ok_button.isEnabled(), "1.29.1: кнопка «Обрезать (Enter)» в строке режима доступна")
ed.crop_ok_button.click()
check((c.base.width(), c.base.height()) == (200, 120) and not c.crop_pending and c.tool != CROP, "кнопка «Обрезать»: снимок 200×120, режим завершён")
c.undo()
ed.select_tool(CROP)
check((c.base.width(), c.base.height()) == (560, 340), "Ctrl+Z возвращает снимок")

# 4. Кнопка «Отмена»
start_crop()
ed.crop_cancel_button.click()
check(not c.crop_pending and c.crop_rect is None and (c.base.width(), c.base.height()) == (560, 340) and c.tool != CROP, "кнопка «Отмена»: рамки нет, снимок цел, режим завершён")
ed.select_tool(CROP)

# 5. Enter подтверждает, Esc отменяет (через горячие клавиши окна)
start_crop(QPoint(50, 50), QPoint(250, 150))
QTest.keyClick(ed, Qt.Key.Key_Return)
app.processEvents()
check((c.base.width(), c.base.height()) == (200, 100), "Enter: обрезано")
c.undo()
ed.select_tool(CROP)
start_crop()
QTest.keyClick(ed, Qt.Key.Key_Escape)
check(not c.crop_pending and ed.isVisible(), "Esc: рамка отменена, окно осталось открытым")
ed.select_tool(CROP)

# 6. Двойной щелчок внутри рамки
start_crop(QPoint(100, 80), QPoint(300, 200))
QTest.mouseDClick(c, L, NOMOD, QPoint(200, 140))
app.processEvents()
check((c.base.width(), c.base.height()) == (200, 120) and c.tool != CROP, "двойной щелчок внутри рамки: обрезано и режим завершён, как «Обрезать»")
c.undo()
ed.select_tool(CROP)

# 7. Щелчок снаружи рамки: выделение заново
start_crop(QPoint(100, 80), QPoint(300, 200))
drag(QPoint(350, 250), QPoint(500, 320))
check(c.crop_pending and c.crop_rect == QRect(350, 250, 150, 70), f"клик снаружи: новая рамка {c.crop_rect}")
c.cancel_crop()

# 8. Смена инструмента убирает рамку
start_crop()
ed.select_tool(RECT)
check(not c.crop_pending and c.crop_rect is None, "смена инструмента убирает рамку")

# 9. Масштаб 200%
ed.select_tool(CROP)
ed.set_zoom(2.0)
app.processEvents(); QTest.qWait(30); app.processEvents()
drag(QPoint(200, 160), QPoint(600, 400))
check(c.crop_rect == QRect(100, 80, 200, 120), f"при 200% рамка в координатах снимка: {c.crop_rect}")
ed.crop_ok_button.click()
check((c.base.width(), c.base.height()) == (200, 120), "при 200% кнопка работает")
check(not hasattr(c, "_crop_buttons"), "встроенных кнопок под рамкой больше нет: один способ, строка режима сверху")
print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено: {len(failures)}")
from clipshot.exitutil import quick_exit
quick_exit(1 if failures else 0)
