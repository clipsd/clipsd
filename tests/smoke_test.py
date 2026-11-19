# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
"""Смоук-тест Clipshot без экрана: выделение области и все инструменты редактора.

Запуск из корня проекта:
    QT_QPA_PLATFORM=offscreen python3 tests/smoke_test.py
Картинки окон сохраняются в tests/output/ — их стоит открыть и посмотреть глазами.
Код выхода 0 — все проверки пройдены.
"""

import os
import sys

here = os.path.dirname(os.path.abspath(__file__))
project = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(here)
out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(here, "output")
sys.path.insert(0, project)
os.makedirs(out, exist_ok=True)

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPixmap
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)

from clipshot import app as appmod
from clipshot.editor import CROP, MOVE, EditorWindow
from clipshot.selector import RegionSelector
from clipshot.shapes import ARROW, BLUR, ELLIPSE, LINE, MARKER, NUMBER, PENCIL, RECT, TEXT

failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def fake_desktop(w=800, h=500):
    pix = QPixmap(w, h)
    p = QPainter(pix)
    grad = QLinearGradient(0, 0, w, h)
    grad.setColorAt(0, QColor("#335"))
    grad.setColorAt(1, QColor("#9ad"))
    p.fillRect(0, 0, w, h, grad)
    for i in range(0, w, 40):
        p.fillRect(i, 100, 20, 20, QColor("#fc0"))
    p.setPen(Qt.GlobalColor.white)
    p.drawText(50, 60, "Fake desktop: Clipshot smoke test")
    p.end()
    return pix


# --- 1. Выделение области ---------------------------------------------------
desktop = fake_desktop()
result = {}
sel = RegionSelector(desktop, QRect(0, 0, 800, 500))
sel.finished.connect(lambda pm, r: result.update(pm=pm, rect=r))
sel.show()
QTest.mouseMove(sel, QPoint(100, 80))
sel.grab().save(os.path.join(out, "1_selector_crosshair.png"))
QTest.mousePress(sel, Qt.MouseButton.LeftButton, pos=QPoint(100, 80))
QTest.mouseMove(sel, QPoint(420, 300))
sel.cursor_pos = QPoint(420, 300)
sel.grab().save(os.path.join(out, "2_selector_dragging.png"))
QTest.mouseRelease(sel, Qt.MouseButton.LeftButton, pos=QPoint(420, 300))
check(result.get("pm") is not None, "выделение возвращает картинку")
check(result.get("pm") is not None and result["pm"].size().width() == 320 and result["pm"].size().height() == 220,
      f"размер вырезанной области 320x220 (получено {result.get('pm') and result['pm'].size()})")
check(result.get("rect") == QRect(100, 80, 320, 220), f"глобальный прямоугольник {result.get('rect')}")

# Esc — отмена
result.clear()
sel2 = RegionSelector(desktop, QRect(0, 0, 800, 500))
sel2.finished.connect(lambda pm, r: result.update(pm=pm, rect=r))
sel2.show()
QTest.keyClick(sel2, Qt.Key.Key_Escape)
check("pm" in result and result["pm"] is None, "Esc в выделении отменяет снимок")


# --- 2. Редактор --------------------------------------------------------------
class Ctx:
    config = dict(appmod.DEFAULTS)
    icon = appmod.make_icon()
    clipboard = None
    notes = []

    def copy_image(self, image):
        Ctx.clipboard = image

    def notify(self, text):
        Ctx.notes.append(text)

    def save_config(self):
        pass


ctx = Ctx()
shot = desktop.copy(QRect(100, 80, 500, 320)).toImage()
ed = EditorWindow(shot, ctx, QPoint(100, 80))
ed.present()
app.processEvents()
c = ed.canvas
check(c.size().width() == 500 and c.size().height() == 320, "холст редактора равен размеру снимка")


def drag(tool, a, b, mods=Qt.KeyboardModifier.NoModifier, steps=5):
    c.set_tool(tool)
    QTest.mousePress(c, Qt.MouseButton.LeftButton, mods, QPoint(*a))
    for i in range(1, steps + 1):
        x = a[0] + (b[0] - a[0]) * i // steps
        y = a[1] + (b[1] - a[1]) * i // steps
        # QTest.mouseMove не передаёт кнопки/модификаторы — шлём событие напрямую.
        from PyQt6.QtCore import QPointF
        from PyQt6.QtGui import QMouseEvent
        from PyQt6.QtCore import QEvent
        ev = QMouseEvent(QEvent.Type.MouseMove, QPointF(x, y), c.mapToGlobal(QPointF(x, y)),
                         Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, mods)
        QApplication.sendEvent(c, ev)
    QTest.mouseRelease(c, Qt.MouseButton.LeftButton, mods, QPoint(*b))


drag(ARROW, (30, 30), (150, 90))
drag(LINE, (30, 120), (160, 140), Qt.KeyboardModifier.ShiftModifier)
drag(RECT, (200, 30), (300, 90))
drag(RECT, (320, 30), (380, 70), Qt.KeyboardModifier.ControlModifier)
drag(ELLIPSE, (200, 120), (300, 200), Qt.KeyboardModifier.ShiftModifier)
drag(MARKER, (30, 200), (180, 205))
drag(PENCIL, (30, 240), (180, 290))
drag(BLUR, (330, 120), (480, 200))
drag(NUMBER, (420, 250), (470, 290))
drag(NUMBER, (380, 250), (380, 250))
check(len(c.shapes) == 10, f"нарисовано 10 объектов (получено {len(c.shapes)})")
check([s.number for s in c.shapes if s.kind == NUMBER] == [1, 2], "номера идут по порядку 1, 2")
line = c.shapes[1]
check(abs(line.points[-1].y() - line.points[0].y()) < 0.01, "Shift выравнивает линию по горизонтали")
check(c.shapes[3].filled, "Ctrl рисует закрашенный прямоугольник")

# Текст
c.set_tool(TEXT)
QTest.mouseClick(c, Qt.MouseButton.LeftButton, pos=QPoint(220, 230))
check(c.text_edit is not None, "клик инструментом «Текст» открывает поле ввода")
from PyQt6.QtCore import QEvent as _QEvent
from PyQt6.QtGui import QKeyEvent


def type_text(widget, text):
    # QTest.keyClicks не умеет кириллицу (падает), поэтому шлём настоящие события клавиатуры.
    for ch in text:
        for t in (_QEvent.Type.KeyPress, _QEvent.Type.KeyRelease):
            QApplication.sendEvent(widget, QKeyEvent(t, 0, Qt.KeyboardModifier.NoModifier, ch))


type_text(c.text_edit, "Привет")
QTest.keyClick(c.text_edit, Qt.Key.Key_Return)  # Enter — новая строка, окно не закрывается
type_text(c.text_edit, "Clipshot")
check(ed.isVisible(), "Enter во время ввода текста не закрывает редактор")
QTest.keyClick(c.text_edit, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
check(c.text_edit is None and c.shapes[-1].kind == TEXT and c.shapes[-1].text == "Привет\nClipshot",
      "Ctrl+Enter завершает ввод текста")

ed.grab().save(os.path.join(out, "3_editor_all_tools.png"))

# Перемещение и дублирование
count = len(c.shapes)
c.set_tool(MOVE)
target = c.shapes[2]
before = target.rect().topLeft()
QTest.mousePress(c, Qt.MouseButton.LeftButton, pos=QPoint(250, 60))
from PyQt6.QtCore import QEvent, QPointF
from PyQt6.QtGui import QMouseEvent
for x in (260, 270, 280):
    QApplication.sendEvent(c, QMouseEvent(QEvent.Type.MouseMove, QPointF(x, 60), c.mapToGlobal(QPointF(x, 60)),
                                          Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                                          Qt.KeyboardModifier.NoModifier))
QTest.mouseRelease(c, Qt.MouseButton.LeftButton, pos=QPoint(280, 60))
check(abs(target.rect().topLeft().x() - before.x() - 30) < 0.01, "«Перемещение» сдвигает объект")
QTest.mousePress(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, QPoint(280, 60))
QTest.mouseRelease(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, QPoint(280, 60))
check(len(c.shapes) == count + 1, "Ctrl+клик дублирует объект")
QTest.keyClick(c, Qt.Key.Key_Delete)
check(len(c.shapes) == count, "Delete удаляет выделенный объект")

# Отмена / повтор
c.undo()
check(len(c.shapes) == count + 1, "Ctrl+Z отменяет удаление")
c.redo()
check(len(c.shapes) == count, "Ctrl+Y повторяет удаление")

# Кадрирование
drag(CROP, (20, 20), (420, 300))
check(c.crop_pending and c.base.size().width() == 500 and c.base.size().height() == 320, "кадрирование: выделение не режет сразу, ждёт подтверждения")
c.confirm_crop()   # второй шаг: «Обрезать» / Enter
check(c.base.width() == 400 and c.base.height() == 280, f"кадрирование 400x280 (получено {c.base.size()})")
ed.grab().save(os.path.join(out, "4_editor_after_crop.png"))
c.undo()
check(c.base.width() == 500, "отмена кадрирования возвращает размер")

# Копирование и закрытие
final = c.render()
final.save(os.path.join(out, "5_final_render.png"))
ed.copy_to_clipboard()
app.processEvents()
check(Ctx.clipboard is not None and Ctx.clipboard.size() == final.size(), "«Скопировать» кладёт картинку в буфер")
check(ed.isVisible(), "после «Скопировать» окно остаётся открытым")
check(ed.toast.isVisible() and "Скопировано" in ed.toast.text(), "всплыло сообщение «Скопировано в буфер обмена»")
ed.close()
app.processEvents()
try:
    closed = not ed.isVisible()
except RuntimeError:  # окно уже удалено (WA_DeleteOnClose) — значит закрыто
    closed = True
check(closed, "после копирования окно закрывается без вопроса о сохранении")
ed2 = EditorWindow(shot, ctx, QPoint(100, 80))
ed2.present()
app.processEvents()
Ctx.clipboard = None
ed2.copy_close_button.click()
app.processEvents()
try:
    closed2 = not ed2.isVisible()
except RuntimeError:
    closed2 = True
check(Ctx.clipboard is not None and closed2, "«Скопировать и закрыть» копирует и закрывает окно")

print()
print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено {len(failures)}")
from clipshot.exitutil import quick_exit
quick_exit(1 if failures else 0)
