# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Номера в редакторе (замечание владельца 21.11.2026).

1. Только что поставленный номер: ручка конца указателя не стоит на центре кружка и не закрывает цифру
   (картинка внутри кружка у выделенного номера та же, что у готового снимка), ручка снаружи кружка и тянется.
2. У каждого цвета свой счёт: красные 1, 2, 3, синие 1, 2, возврат к красному даёт 4. Выбор цвета сразу после
   постановки номера не перекрашивает этот номер, а задаёт цвет следующих.
3. Удаление, отмена и повтор, копия номера (Ctrl+щелчок), смена цвета у готового номера пересчитывают номера
   своего цвета, чужой цвет не трогают. Снимок (render) несёт те же цвета и числа.
4. Подсказка «Номер» дополнена «у каждого цвета своя нумерация» на всех 12 языках.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/nomera_po_cvetu_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import json
import os
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
os.environ.setdefault("CLIPSD_LANG", "ru")
_cfg = os.path.join(tempfile.mkdtemp(prefix="clipsd-nomera-"), "screen.json")
with open(_cfg, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1920, "height": 1080,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _cfg

from PyQt6.QtCore import QPoint, QPointF, QRect, Qt
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
from clipshot import app as appmod  # noqa: E402
from clipshot.editor import MOVE, NUMBER, EditorWindow  # noqa: E402
from clipshot.shapes import NUMBER_RADII  # noqa: E402

failures = []
checks = [0]
RED, BLUE = "#d60808", "#1e78ff"
LEFT, NOMOD, CTRL = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ControlModifier


def check(cond, msg):
    checks[0] += 1
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def settle(n=4):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(10)


class Ctx:
    def __init__(self):
        self.config = dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True)
        self.icon = appmod.make_icon()

    def save_config(self):
        pass

    def notify(self, text):
        pass


def make():
    img = QImage(480, 320, QImage.Format.Format_RGB32)
    img.fill(QColor("#e9edf2"))
    ed = EditorWindow(img, Ctx(), QPoint(0, 0))
    ed.present()
    settle()
    return ed


ed = make()
c = ed.canvas


def click(x, y, mods=NOMOD):
    QTest.mousePress(c, LEFT, mods, QPoint(x, y))
    QTest.mouseRelease(c, LEFT, mods, QPoint(x, y))
    settle(2)


def counts():
    """{цвет: [номера в порядке постановки]}"""
    out = {}
    for s in c.shapes:
        if s.kind == NUMBER:
            out.setdefault(s.color.name().lower(), []).append(s.number)
    return out


def pick(color):
    ed.select_color(color)
    settle(2)


# --- 1. ручка не закрывает цифру ---------------------------------------------------------------------
ed.select_tool(NUMBER)
pick(RED)
click(100, 80)
num = c.shapes[-1]
check(num.kind == NUMBER and c.selected is num, "номер поставлен и выделен")
h = num.handles()[0]
d = h - num.points[0]
r = NUMBER_RADII[num.size]
check((d.x() ** 2 + d.y() ** 2) ** 0.5 > r + 4, "ручка стоит снаружи кружка, а не на центре (расстояние %.1f, радиус %d)"
      % ((d.x() ** 2 + d.y() ** 2) ** 0.5, r))
selected_img = c.grab().toImage()
c.select(None)
settle(2)
plain_img = c.grab().toImage()
cx, cy = int(num.points[0].x()), int(num.points[0].y())
same = all(selected_img.pixelColor(cx + dx, cy + dy) == plain_img.pixelColor(cx + dx, cy + dy)
           for dx in range(-r, r + 1) for dy in range(-r, r + 1) if dx * dx + dy * dy <= (r - 3) ** 2)
check(same, "внутри кружка выделенный номер выглядит как готовый: маркер цифру не перекрывает")
# центр кружка: цвет цифры (белый) или фон кружка, но не синяя рамка ручки
ctr = selected_img.pixelColor(cx, cy)
check(ctr == plain_img.pixelColor(cx, cy), "пиксель в центре кружка тот же, что без выделения")
c.select(num)
settle(2)

# перетаскивание: кружок за тело, указатель за ручку
tail0 = QPointF(num.points[-1])
QTest.mousePress(c, LEFT, NOMOD, QPoint(cx - 5, cy))
QTest.mouseMove(c, QPoint(cx + 15, cy + 20))
QTest.mouseRelease(c, LEFT, NOMOD, QPoint(cx + 15, cy + 20))
settle(2)
check(num.points[0] != QPointF(cx, cy), "кружок номера по-прежнему тянется за тело")
hx, hy = int(num.handles()[0].x()), int(num.handles()[0].y())
QTest.mousePress(c, LEFT, NOMOD, QPoint(hx, hy))
QTest.mouseMove(c, QPoint(hx + 50, hy + 30))
QTest.mouseRelease(c, LEFT, NOMOD, QPoint(hx + 50, hy + 30))
settle(2)
tail = num.points[-1]
check(abs(tail.x() - (hx + 50)) < 2 and abs(tail.y() - (hy + 30)) < 2, "указатель тянется за ручку, как раньше")
check(num.handles()[0] == tail, "вытянутый указатель: ручка на его конце")

# --- 2. счёт по цветам -----------------------------------------------------------------------------------
ed = make()
c = ed.canvas
ed.select_tool(NUMBER)
pick(RED)
for y in (60, 110, 160):
    click(60, y)
check(counts() == {RED: [1, 2, 3]}, "красные 1, 2, 3: %s" % counts())
pick(BLUE)
check([s.color.name().lower() for s in c.shapes] == [RED] * 3, "выбор цвета сразу после номера не перекрашивает его")
click(200, 60)
click(200, 110)
check(counts() == {RED: [1, 2, 3], BLUE: [1, 2]}, "синие начинают с 1: %s" % counts())
pick(RED)
click(60, 210)
check(counts() == {RED: [1, 2, 3, 4], BLUE: [1, 2]}, "возврат к красному продолжает 4: %s" % counts())
check(ed.canvas.next_number() == 5 and ed.canvas.next_number(BLUE) == 3, "next_number считает по цвету")

# render: числа и цвета в готовом снимке
img = c.render()
r = NUMBER_RADII[c.shapes[0].size]
probe = lambda s: img.pixelColor(int(s.points[0].x()) + r - 3, int(s.points[0].y())).name().lower()  # noqa: E731
check(probe(c.shapes[0]) == RED and probe(c.shapes[3]) == BLUE, "снимок: красный и синий кружки на местах")

# --- 3. удаление, отмена, повтор ---------------------------------------------------------------------------
red2 = [s for s in c.shapes if s.kind == NUMBER and s.color.name().lower() == RED and s.number == 2][0]
c.select(red2)
c.delete_selected()
check(counts() == {RED: [1, 2, 3], BLUE: [1, 2]}, "удалили красный 2: красные 1, 2, 3 (счёт сомкнулся), синие не тронуты: %s" % counts())
check(c.next_number(RED) == 4 and c.next_number(BLUE) == 3, "следующие номера после удаления")
c.undo()
check(counts() == {RED: [1, 2, 3, 4], BLUE: [1, 2]}, "отмена вернула красные 1-4: %s" % counts())
c.redo()
check(counts() == {RED: [1, 2, 3], BLUE: [1, 2]}, "повтор снова удалил: %s" % counts())
c.undo()
blue_last = [s for s in c.shapes if s.color.name().lower() == BLUE and s.number == 2][0]
c.select(blue_last)
c.delete_selected()
check(counts() == {RED: [1, 2, 3, 4], BLUE: [1]} and c.next_number(BLUE) == 2, "удалили последний синий: следующий синий 2")
c.undo()

# копия Ctrl+щелчок: номер копии по цвету копируемого, а не по текущему цвету
ed.select_tool(MOVE)
pick(RED)
src = [s for s in c.shapes if s.color.name().lower() == BLUE and s.number == 2][0]
c.select(None)
sp = src.points[0]
click(int(sp.x()), int(sp.y()), CTRL)
check(counts().get(BLUE) == [1, 2, 3], "копия синего номера получила синий 3, хотя текущий цвет красный: %s" % counts())

# смена цвета у готового номера (инструмент не «Номер»): номера обоих цветов пересчитываются
ed.select_tool(MOVE)
c.select(None)
moved = [s for s in c.shapes if s.color.name().lower() == RED and s.number == 4][0]
c.select(moved)
c.tool = MOVE
c.set_color(BLUE)
check(counts().get(RED) == [1, 2, 3] and sorted(counts().get(BLUE)) == [1, 2, 3, 4], "перекрасили готовый красный 4: счёт у обоих цветов без пропусков: %s" % counts())
c.undo()
check(counts().get(RED) == [1, 2, 3, 4], "отмена перекраски вернула красный 4")

# --- 4. подсказка на 12 языках ---------------------------------------------------------------------------------
langs = sorted(d for d in os.listdir(os.path.join(os.path.dirname(here), "clipshot", "i18n"))
               if os.path.isdir(os.path.join(os.path.dirname(here), "clipshot", "i18n", d)) and not d.startswith("_"))
check(len(langs) == 12, "12 языков: %s" % langs)
for lang in langs:
    with open(os.path.join(os.path.dirname(here), "clipshot", "i18n", lang, "editor.json"), encoding="utf-8") as f:
        tip = json.load(f)["editor.tip_number"]
    check(len(tip.split("\n")) == 4 and "—" not in tip, "подсказка «Номер» (%s) из 4 строк, без длинного тире" % lang)

print("ИТОГ: проверок %d, провалов %d" % (checks[0], len(failures)))
sys.exit(1 if failures else 0)
