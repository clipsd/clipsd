# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
"""Перенос объектов зажатой правой кнопкой; правка текста и сноски одним щелчком.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/rightdrag_test.py
"""
import os
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QColor, QContextMenuEvent, QImage
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
from clipshot import app as appmod
from clipshot.editor import ARROW, EditorWindow, MOVE, RECT, TEXT
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
menus = []
c.context_requested.disconnect(ed.show_context_menu)   # настоящее меню модальное и повесило бы тест
c.context_requested.connect(lambda hit, pos: menus.append(hit))
L, R, NOMOD = Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier


def drag(button, a, b, steps=6):
    QTest.mousePress(c, button, NOMOD, a)
    for i in range(1, steps + 1):
        QTest.mouseMove(c, QPoint(a.x() + (b.x() - a.x()) * i // steps, a.y() + (b.y() - a.y()) * i // steps))
    QTest.mouseRelease(c, button, NOMOD, b)
    app.processEvents()


# Стрелка и прямоугольник нарисованы левой кнопкой
ed.select_tool(ARROW)
drag(L, QPoint(50, 50), QPoint(200, 50))
check(len(c.shapes) == 1, "стрелка нарисована")
arrow = c.shapes[0]
x0 = arrow.points[0].x()
ed.select_tool(RECT)   # инструмент не «Перемещение»: правой кнопкой всё равно можно переносить
drag(L, QPoint(300, 150), QPoint(400, 250))
rect = c.shapes[1]
c.select(None)

# 1. Правая кнопка с протягиванием двигает стрелку, меню не открывается
undo_before = len(c.undo_stack)
drag(R, QPoint(120, 50), QPoint(170, 110))
check(abs(arrow.points[0].x() - (x0 + 50)) < 1.5 and abs(arrow.points[0].y() - 110) < 1.5,
      f"стрелка перенесена правой кнопкой: {arrow.points[0].x():.0f},{arrow.points[0].y():.0f}")
check(menus == [], "после переноса меню не открылось")
check(len(c.undo_stack) == undo_before + 1, "перенос = одна запись в отмене")
check(len(c.shapes) == 2 and abs(rect.points[0].x() - 300) < 1.5, "второй объект не сдвинулся")
c.undo()
check(abs(c.shapes[0].points[0].x() - x0) < 1.5, "Ctrl+Z возвращает на место")

# 2. Правый щелчок без сдвига: меню действий
menus.clear()
drag(R, QPoint(120, 50), QPoint(120, 50), steps=1)
check(len(menus) == 1 and menus[0] is c.shapes[0], "правый щелчок по объекту: меню для него")
menus.clear()
drag(R, QPoint(20, 300), QPoint(20, 300), steps=1)
check(len(menus) == 1 and menus[0] is None, "правый щелчок по пустому месту: общее меню")

# 3. Системное событие меню от мыши не дублирует меню; с клавиатуры работает
menus.clear()
c.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(120, 50), c.mapToGlobal(QPoint(120, 50))))
check(menus == [], "системное меню от мыши игнорируется (нет двойного меню)")
c.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Keyboard, QPoint(120, 50), c.mapToGlobal(QPoint(120, 50))))
check(len(menus) == 1, "меню с клавиатуры (клавиша Menu) работает")

# 4. Правое протягивание по пустому месту ничего не двигает и меню не открывает
menus.clear()
before = [(s.points[0].x(), s.points[0].y()) for s in c.shapes]
drag(R, QPoint(20, 300), QPoint(80, 330))
check([(s.points[0].x(), s.points[0].y()) for s in c.shapes] == before and menus == [], "по пустому месту: ничего")

# 5. Перенос при увеличении 200%
ed.set_zoom(2.0)
app.processEvents(); QTest.qWait(30); app.processEvents()
x1 = c.shapes[1].points[0].x()
drag(R, QPoint(int((x1 + 10) * 2), 2 * 200), QPoint(int((x1 + 10) * 2) + 80, 2 * 200))
check(abs(c.shapes[1].points[0].x() - (x1 + 40)) < 2, "при 200% сдвиг на 80 px экрана = 40 px снимка")
ed.set_zoom(1.0)

# 6. Текст: один щелчок открывает правку (инструмент «Перемещение»)
ed.select_tool(TEXT)
c.start_text(QPointF(40, 250), TEXT)
c.text_edit.setPlainText("привет")
c.commit_text()
text = c.shapes[-1]
check(text.kind == TEXT and c.text_edit is None, "текст создан")
ed.select_tool(MOVE)
c.select(None)
tp = text.bounding_rect().center().toPoint()
drag(L, tp, tp, steps=1)
check(c.text_edit is not None and text not in c.shapes, "одиночный щелчок по тексту: правка открыта")
check(c.text_edit.toPlainText() == "привет", "в поле старый текст")
c.cancel_text()
check(text in c.shapes, "Esc возвращает текст на место")

# 7. Протянуть текст: переносится, правка не открывается
c.select(None)
x2 = text.points[0].x()
drag(L, tp, tp + QPoint(60, 0))
check(c.text_edit is None and abs(text.points[0].x() - (x2 + 60)) < 2, "протягивание текста переносит, а не открывает правку")

# 8. Инструмент «Текст»: щелчок по готовому тексту правит его, а не создаёт новый поверх
ed.select_tool(TEXT)
c.select(None)
n = len(c.shapes)
tp2 = text.bounding_rect().center().toPoint()
drag(L, tp2, tp2, steps=1)
check(c.text_edit is not None and c.text_edit.toPlainText() == "привет", "инструмент «Текст»: щелчок по тексту открывает его")
c.cancel_text()
check(len(c.shapes) == n, "новых объектов не появилось")
print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено: {len(failures)}")
from clipshot.exitutil import quick_exit
quick_exit(1 if failures else 0)
