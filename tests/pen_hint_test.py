# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Цвет и толщина выделенного объекта, подсказка у палитры, свои цвета, маркер вплотную (1.32.1).

Замечание владельца 20.11.2026: «я выделил, а мне цвет не понравился, я раз, другой нажал, следующую линию веду,
он опять не тем цветом». Решение владельца: при выделенном объекте нажатый цвет (палитра, «+», свой образец, меню
правой кнопки, «A») и толщина меняют только его, у палитры появляется подсказка «Цвет изменён только у этого объекта.
Новые линии будут прежнего цвета» и кнопка «Рисовать дальше этим цветом». Ничего не выделено: цвет сразу текущий.
Свои цвета из «+» остаются образцами (до трёх). Новая линия маркером вплотную к только что проведённой рисуется,
а не сдвигает прошлую. Правка готового текста не подменяет цвет следующих линий.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/pen_hint_test.py
"""
import json
import os
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
# экран задан явно (как в editor1321_test, но крупный): при QT_SCALE_FACTOR выше 1 окно иначе ужимается под экран по умолчанию,
# двойной щелчок промахивается мимо текста, и поле правки не открывается
_cfg = os.path.join(tempfile.mkdtemp(prefix="clipsd-pen-"), "screen.json")
with open(_cfg, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 3840, "height": 2160,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _cfg

from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PyQt6.QtGui import QColor, QEnterEvent, QImage, QKeyEvent, QMouseEvent, QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QColorDialog

app = QApplication(sys.argv)
from clipshot import app as appmod
from clipshot import i18n
from clipshot.dialogs import PALETTES
from clipshot.editor import MOVE, OWN_COLORS_MAX, EditorWindow, PenHint
from clipshot.i18n import tr
from clipshot.shapes import ARROW, MARKER, NUMBER, TEXT

failures = []
RED, GREEN, BLUE, YELLOW = "#d60808", "#2db400", "#1e78ff", "#ffd800"
PINK, TEAL, BROWN, OLIVE = "#e8368f", "#00a6a6", "#8a5a2b", "#6b7d1e"


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


class Ctx:
    config = dict(appmod.DEFAULTS)
    icon = appmod.make_icon()
    saves = 0

    def copy_image(self, image):
        pass

    def notify(self, text):
        pass

    def save_config(self):
        Ctx.saves += 1


DIALOG = {"answer": PINK, "calls": 0}


def fake_dialog(*_a, **_k):
    DIALOG["calls"] += 1
    return QColor(DIALOG["answer"])


QColorDialog.getColor = staticmethod(fake_dialog)
img = QImage(640, 360, QImage.Format.Format_RGB32)
img.fill(QColor("#eef1f5"))


def editor(color=RED, keep_config=False, **kw):
    if not keep_config:
        Ctx.config = dict(appmod.DEFAULTS, color=color, **kw)
    ed = EditorWindow(img, Ctx(), QPoint(40, 40))
    ed.present()
    app.processEvents()
    return ed, ed.canvas


def done(ed):
    ed.exported = True
    ed.close()
    app.processEvents()


def drag(c, a, b):
    QTest.mousePress(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(*a))
    mid = QPointF((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    for pt in (mid, QPointF(*b)):
        QApplication.sendEvent(c, QMouseEvent(QEvent.Type.MouseMove, pt, c.mapToGlobal(pt), Qt.MouseButton.NoButton,
                                              Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    QTest.mouseRelease(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(*b))
    app.processEvents()


def type_text(widget, text):
    if widget is None:   # поле правки не открылось: проверка выше уже провалена, процесс не роняем
        return
    for ch in text:
        for t in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            QApplication.sendEvent(widget, QKeyEvent(t, 0, Qt.KeyboardModifier.NoModifier, ch))


def checked(ed):
    b = ed.color_group.checkedButton()
    return QColor(b.color).name() if b is not None and b.color else None


def hint(ed):
    return ed._pen_hint if ed._pen_hint is not None and ed._pen_hint.isVisible() else None


def ratio(a, b):
    def lum(c):
        c = QColor(c)
        ch = [v / 255 for v in (c.red(), c.green(), c.blue())]
        ch = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in ch]
        return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# 1. Сценарий владельца: маркер, провёл, нажал другой цвет, повёл следующую линию
ed, c = editor(YELLOW)
ed.select_tool(MARKER)
drag(c, (40, 60), (300, 60))
first = c.shapes[-1]
QTest.mouseMove(ed.color_buttons[GREEN])   # мышь на палитре, как при настоящем щелчке
ed.color_buttons[GREEN].click()
app.processEvents()
h = hint(ed)
check(first.color == QColor(GREEN), "нажал зелёный: проведённая линия зелёная")
check(c.color == QColor(YELLOW) and Ctx.config["color"] == YELLOW, "цвет следующих линий остался жёлтым (и в настройках)")
check(h is not None and h.title.text() == tr("editor.pen_hint_color_title") and h.sub.text() == tr("editor.pen_hint_color_sub")
      and h.button.text() == tr("editor.pen_hint_color_button"), "у палитры подсказка: цвет изменён только у этого объекта")
check(h is not None and h.sample.isVisibleTo(h) and YELLOW in h.sample.styleSheet(), "образец в подсказке: прежний жёлтый")
check(h is not None and h.parent() is ed and not h.isWindow(), "подсказка не отдельное окно: карточка внутри редактора")
sel = first.bounding_rect()
busy = QRect(c.mapTo(ed, sel.topLeft().toPoint()), sel.size().toSize())
check(h is not None and not h.geometry().intersects(busy), "подсказка не закрывает выделенную линию")
pal_bottom = ed.color_buttons[GREEN].mapTo(ed, QPoint(0, ed.color_buttons[GREEN].height())).y()
check(h is not None and h.geometry().top() >= pal_bottom, "подсказка ниже палитры, панель не закрывает")
check(h is not None and h.timer.isActive() and 0 < h.timer.remainingTime() <= PenHint.SHOW_MS * 1.1,   # грубый таймер Qt: до 5 %
      "подсказка уйдёт сама через несколько секунд")
ed.color_buttons[BLUE].click()
app.processEvents()
check(len(ed.findChildren(PenHint)) == 1 and hint(ed) is h and h.pending == {"color": BLUE},
      "ещё раз сменил цвет: та же подсказка обновилась, а не появилась вторая")
QTest.mousePress(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(40, 160))
app.processEvents()
check(hint(ed) is None, "начал вести следующую линию: подсказка ушла")
QTest.mouseRelease(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(40, 160))
drag(c, (40, 160), (300, 160))
check(c.shapes[-1].color == QColor(YELLOW), "следующая линия прежнего жёлтого цвета, как и обещала подсказка")
done(ed)

# 1б. Щелчок по самой карточке мимо кнопки закрывает её, как щелчок по снимку (П3)
ed, c = editor(YELLOW)
ed.select_tool(MARKER)
drag(c, (40, 60), (300, 60))
ed.color_buttons[GREEN].click()
h = hint(ed)
shapes_before = len(c.shapes)
body = QPoint(6, h.height() // 2)   # левый край карточки: ни кнопка, ни текст
check(h is not None and h.childAt(body) is None, "точка на карточке мимо кнопки найдена")
QTest.mouseClick(h, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, body)
app.processEvents()
check(hint(ed) is None and len(c.shapes) == shapes_before and c.color == QColor(YELLOW) and Ctx.config["color"] == YELLOW,
      "щелчок по карточке мимо кнопки: карточка закрылась, линия не началась, цвет пера прежний")
ed.color_buttons[BLUE].click()
h = hint(ed)
QTest.mouseClick(h.sub, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(3, 3))
app.processEvents()
check(hint(ed) is None, "щелчок по тексту карточки её тоже закрывает")
ed.color_buttons[GREEN].click()
hint(ed).button.click()
app.processEvents()
check(c.color == QColor(GREEN) and Ctx.config["color"] == GREEN and hint(ed) is None, "кнопка «Рисовать дальше этим цветом» работает как раньше")
done(ed)

# 2. «Рисовать дальше этим цветом»
ed, c = editor(YELLOW)
ed.select_tool(MARKER)
drag(c, (40, 60), (300, 60))
ed.color_buttons[GREEN].click()
saves = Ctx.saves
hint(ed).button.click()
app.processEvents()
check(c.color == QColor(GREEN) and Ctx.config["color"] == GREEN and Ctx.saves > saves,
      "«Рисовать дальше этим цветом»: зелёный стал текущим и записан в настройки")
check(hint(ed) is None, "после кнопки подсказка ушла")
drag(c, (40, 160), (300, 160))
check(c.shapes[-1].color == QColor(GREEN), "следующая линия зелёная")
check(c.shapes[0].color == QColor(GREEN), "первая линия тоже зелёная")
done(ed)

# 3. Ничего не выделено: цвет сразу текущий, без подсказки
ed, c = editor(RED)
ed.select_tool(ARROW)
ed.color_buttons[BLUE].click()
check(c.color == QColor(BLUE) and Ctx.config["color"] == BLUE and hint(ed) is None,
      "ничего не выделено: синий сразу текущий, подсказки нет")
drag(c, (40, 60), (300, 120))
check(c.shapes[-1].color == QColor(BLUE), "стрелка синяя")
ed.color_buttons[BLUE].click()
check(hint(ed) is None, "выделенной стрелке нажал тот же цвет, что у новых линий: подсказывать нечего")
ed.color_buttons[GREEN].click()
ed.color_buttons[BLUE].click()
check(hint(ed) is None and c.shapes[-1].color == QColor(BLUE), "вернул стрелке цвет новых линий: подсказка ушла")
done(ed)

# 4. Старый объект, выделенный щелчком; смена инструмента и снятие выделения убирают подсказку
ed, c = editor(RED)
ed.select_tool(ARROW)
drag(c, (40, 60), (300, 120))
old = c.shapes[-1]
drag(c, (40, 220), (300, 280))
ed.select_tool(MOVE)
QTest.mouseClick(c, Qt.MouseButton.LeftButton, pos=QPoint(170, 90))
app.processEvents()
check(c.selected is old, "щелчком выделена старая стрелка")
ed.color_buttons[BLUE].click()
check(old.color == QColor(BLUE) and c.color == QColor(RED) and hint(ed) is not None,
      "старая стрелка синяя, новые линии красные, подсказка есть")
c.select(None)
app.processEvents()
check(hint(ed) is None and checked(ed) == RED, "сняли выделение: подсказка ушла, палитра показывает красный")
QTest.mouseClick(c, Qt.MouseButton.LeftButton, pos=QPoint(170, 90))
ed.color_buttons[GREEN].click()
ed.select_tool(ARROW)
app.processEvents()
check(hint(ed) is None, "сменил инструмент: подсказка ушла")
done(ed)

# 5. Толщина по тому же правилу; цвет и толщина вместе
ed, c = editor(RED)
ed.select_tool(ARROW)
drag(c, (40, 60), (300, 120))
arrow = c.shapes[-1]
size0 = c.pen_size
ed.select_size(4)
h = hint(ed)
check(arrow.size == 4 and c.pen_size == size0 and Ctx.config["size"] == size0, "толщина 4 только у стрелки, новые линии прежней толщины")
check(h is not None and h.title.text() == tr("editor.pen_hint_size_title") and h.button.text() == tr("editor.pen_hint_size_button")
      and not h.sample.isVisibleTo(h), "подсказка про толщину, без образца цвета")
ed.color_buttons[GREEN].click()
check(hint(ed) is h and h.title.text() == tr("editor.pen_hint_both_title") and h.button.text() == tr("editor.pen_hint_both_button"),
      "и цвет, и толщина: подсказка «Изменён только этот объект»")
h.button.click()
check(c.color == QColor(GREEN) and c.pen_size == 4 and Ctx.config["color"] == GREEN and Ctx.config["size"] == 4,
      "«Рисовать дальше так же»: и цвет, и толщина стали текущими")
ed.select_tool(ARROW)
drag(c, (40, 220), (300, 280))
pos = c.shapes[-1].points[-1]
size_before = c.pen_size
QApplication.sendEvent(c, QWheelEvent(pos, c.mapToGlobal(pos), QPoint(), QPoint(0, 120), Qt.MouseButton.NoButton,
                                      Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False))
app.processEvents()
check(c.shapes[-1].size == size_before + 1 and c.pen_size == size_before and hint(ed) is not None
      and hint(ed).kind == "size", "колесо над выделенной стрелкой: толщина у неё, подсказка про толщину")
done(ed)

# 6. Меню правой кнопки «Цвет» и «A» (цвет цифры в номере)
ed, c = editor(RED)
ed.select_tool(ARROW)
drag(c, (40, 60), (300, 120))
menu = ed.build_context_menu(c.shapes[-1])
colors = next(a.menu() for a in menu.actions() if a.text() == tr("editor.color"))
next(a for a in colors.actions() if a.text() == BLUE.upper()).trigger()
check(c.shapes[-1].color == QColor(BLUE) and c.color == QColor(RED) and hint(ed) is not None, "цвет из меню: только объект и подсказка")
ed.select_tool(NUMBER)
QTest.mouseClick(c, Qt.MouseButton.LeftButton, pos=QPoint(100, 250))
app.processEvents()
num = c.shapes[-1]
ed.select_text_color("#000000")
check(num.label_color() == QColor("#000000") and c.text_color is None and hint(ed) is not None
      and hint(ed).kind == "color", "«A»: чёрная цифра только у номера, подсказка про цвет")
hint(ed).button.click()
check(c.text_color == QColor("#000000") and Ctx.config["text_color"] == "#000000", "«Рисовать дальше этим цветом»: чёрная цифра для новых номеров")
QTest.mouseClick(c, Qt.MouseButton.LeftButton, pos=QPoint(200, 250))
app.processEvents()
check(c.shapes[-1].label_color() == QColor("#000000"), "следующий номер с чёрной цифрой")
done(ed)

# 7. Подсказка уходит сама; пока мышь на ней, держится
ed, c = editor(RED)
ed.select_tool(ARROW)
drag(c, (40, 60), (300, 120))
ed.color_buttons[GREEN].click()
h = hint(ed)
QApplication.sendEvent(h, QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5)))
check(not h.timer.isActive(), "мышь на подсказке: она не уходит")
QApplication.sendEvent(h, QEvent(QEvent.Type.Leave))
check(h.timer.isActive() and h.timer.interval() == PenHint.LINGER_MS, "мышь ушла: подсказка уйдёт через пару секунд")
h.timer.timeout.emit()
app.processEvents()
check(hint(ed) is None and c.color == QColor(RED), "время вышло: подсказка ушла, цвет новых линий прежний")
done(ed)

# 8. Правка готового текста не подменяет цвет следующих линий
ed, c = editor(RED)
ed.select_tool(TEXT)
QTest.mouseClick(c, Qt.MouseButton.LeftButton, pos=QPoint(60, 60))
type_text(c.text_edit, "Текст")
QTest.keyClick(c.text_edit, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
app.processEvents()
text = c.shapes[-1]
ed.select_tool(ARROW)
ed.color_buttons[BLUE].click()
ed.select_tool(MOVE)
QTest.mouseDClick(c, Qt.MouseButton.LeftButton, pos=text.bounding_rect().center().toPoint())
app.processEvents()
check(c.text_edit is not None and c.color == QColor(RED), "двойной щелчок: поле правки красное, как сам текст")
type_text(c.text_edit, "!")
QTest.keyClick(c.text_edit, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
app.processEvents()
check(c.shapes[-1].text == "Текст!" and c.shapes[-1].color == QColor(RED), "текст поправлен и остался красным")
check(c.color == QColor(BLUE) and Ctx.config["color"] == BLUE, "после правки цвет следующих линий снова синий")
ed.select_tool(MOVE)
QTest.mouseDClick(c, Qt.MouseButton.LeftButton, pos=c.shapes[-1].bounding_rect().center().toPoint())
app.processEvents()
ed.color_buttons[GREEN].click()
check(hint(ed) is not None and c.text_edit is not None, "во время правки текста нажал зелёный: подсказка, поле правки открыто")
hint(ed).button.click()
QTest.keyClick(c.text_edit, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
app.processEvents()
check(c.shapes[-1].color == QColor(GREEN) and c.color == QColor(GREEN) and Ctx.config["color"] == GREEN,
      "«Рисовать дальше этим цветом» во время правки: после неё новые линии зелёные")
ed.select_tool(MOVE)
QTest.mouseDClick(c, Qt.MouseButton.LeftButton, pos=c.shapes[-1].bounding_rect().center().toPoint())
app.processEvents()
ed.select_size(5)
QTest.keyClick(c.text_edit, Qt.Key.Key_Escape)
app.processEvents()
check(c.pen_size == appmod.DEFAULTS["size"] and Ctx.config["size"] == appmod.DEFAULTS["size"],
      "размер во время правки и отмена Esc: толщина следующих линий прежняя")
done(ed)

# 9. Свои цвета из «+»
ed, c = editor(RED)
ed.select_tool(ARROW)
DIALOG["answer"], DIALOG["calls"] = PINK, 0
ed.custom_color.click()
app.processEvents()
check(PINK in ed.own_buttons and Ctx.config["custom_colors"] == [PINK] and c.color == QColor(PINK) and checked(ed) == PINK,
      "«+», розовый: встал образцом, выбран, записан в настройки")
check(ed.custom_color.color is None and ed.custom_color.text() == "+", "«+» остался «+»")
row = ed.panel_row2
check(row.indexOf(ed.own_buttons[PINK]) == row.indexOf(ed.custom_color) - 1, "свой образец стоит перед «+»")
ed.color_buttons[BLUE].click()
ed.own_buttons[PINK].click()
check(c.color == QColor(PINK) and DIALOG["calls"] == 1, "щелчок по своему образцу: розовый выбран сразу, окно не открылось")
for col in (TEAL, BROWN, OLIVE):
    DIALOG["answer"] = col
    ed.custom_color.click()
app.processEvents()
check(list(ed.own_buttons) == [TEAL, BROWN, OLIVE] and Ctx.config["custom_colors"] == [TEAL, BROWN, OLIVE]
      and len(ed.own_buttons) == OWN_COLORS_MAX, "четвёртый свой цвет вытеснил самый старый (розовый)")
check(all(ed.color_group.id(b) != -1 or b in ed.color_group.buttons() for b in ed.own_buttons.values())
      and PINK not in [QColor(b.color).name() for b in ed.color_group.buttons() if b.color], "вытесненный образец убран из палитры")
DIALOG["answer"] = RED
ed.custom_color.click()
check(list(ed.own_buttons) == [TEAL, BROWN, OLIVE] and checked(ed) == RED, "цвет основной палитры через «+» не дублируется")
drag(c, (40, 60), (300, 120))
DIALOG["answer"] = PINK
ed.custom_color.click()
check(c.shapes[-1].color == QColor(PINK) and c.color == QColor(RED) and PINK in ed.own_buttons and hint(ed) is not None,
      "«+» при выделенной стрелке: перекрашена она, цвет запомнен образцом, подсказка есть")
menu = ed.build_context_menu(c.shapes[-1])
colors = next(a.menu() for a in menu.actions() if a.text() == tr("editor.color"))
check(PINK.upper() in [a.text() for a in colors.actions()], "свои цвета есть в меню правой кнопки «Цвет»")
saved = list(Ctx.config["custom_colors"])
done(ed)
ed, c = editor(keep_config=True)
check(list(ed.own_buttons) == saved, "новый снимок: свои цвета на месте")
ed.forget_own_color(BROWN)
check(BROWN not in ed.own_buttons and BROWN not in Ctx.config["custom_colors"], "«Убрать из палитры»: образец и запись ушли")
done(ed)
ed, c = editor("#123456")
check("#123456" in ed.own_buttons and checked(ed) == "#123456", "свой цвет из 1.32.0 (был текущим) встал в палитру образцом")
done(ed)

# 9б. «Убрать из палитры» текущего цвета: образец уходит насовсем, цвет пера прежний (П2)
ed, c = editor("#123456")
check("#123456" in ed.own_buttons and c.color == QColor("#123456"), "свой цвет 1.32.0 встал образцом")
ed.forget_own_color("#123456")
check("#123456" not in ed.own_buttons and c.color == QColor("#123456"), "убрал текущий свой цвет: образца нет, цвет пера прежний")
done(ed)
ed, c = editor(keep_config=True)
check("#123456" not in ed.own_buttons and Ctx.config["custom_colors"] == [] and c.color == QColor("#123456"),
      "следующий снимок: убранный образец не вернулся, цвет пера прежний")
done(ed)

# 9а. Мусор в настройках custom_colors не роняет редактор (замечание П1 проверки 1.32.1)
for junk in (5, 1.5, True, "zzz", "#e8368f", {"a": 1}, None, []):
    ed, c = editor(RED, custom_colors=junk)
    check(list(ed.own_buttons) == [] and ed._own_colors() == [], f"custom_colors = {junk!r}: считается пустым списком, редактор открылся")
    done(ed)
ed, c = editor(RED, custom_colors=[None, 1, "zzz", ["#00a6a6"], TEAL, BROWN, TEAL, OLIVE, PINK])
check(ed._own_colors() == [BROWN, OLIVE, PINK] and list(ed.own_buttons) == [BROWN, OLIVE, PINK],
      "список с мусором: берутся только корректные цвета без повторов, не больше трёх (последние)")
done(ed)

# 10. Маркер: новая линия вплотную к только что проведённой
ed, c = editor(YELLOW)
ed.select_tool(MARKER)
drag(c, (40, 60), (300, 60))
first = c.shapes[-1]
before = [QPointF(p) for p in first.points]
drag(c, (40, 72), (300, 72))
check(len(c.shapes) == 2 and first.points == before, "вторая линия на 12 px ниже: нарисована новая, прошлая на месте")
second = c.shapes[-1]
QTest.mouseClick(c, Qt.MouseButton.LeftButton, pos=QPoint(150, 72))
app.processEvents()
check(c.selected is second and len(c.shapes) == 2, "щелчок по только что проведённой линии выделил её")
drag(c, (150, 72), (150, 112))
check(len(c.shapes) == 2 and abs(second.points[0].y() - 112) < 1, "после щелчка линию можно тянуть")
ed.select_tool(ARROW)
drag(c, (40, 200), (300, 260))
arrow = c.shapes[-1]
start = QPointF(arrow.points[0])
drag(c, (170, 230), (190, 250))
check(len(c.shapes) == 3 and arrow.points[0] == start + QPointF(20, 20), "только что нарисованную стрелку по-прежнему можно тянуть сразу")
done(ed)

# 11. Контраст подсказки (4,5:1) в обеих темах и ширина на 12 языках
for dark in (False, True):
    p = PALETTES[dark]
    for fg, name in ((p["text"], "заголовок и кнопка"), (p["muted"], "пояснение")):
        r = ratio(fg, p["card"])
        check(r >= 4.5, f"{'тёмная' if dark else 'светлая'} тема: {name} {r:.1f}:1")
    check(ratio(p["text"], p["soft"]) >= 4.5, f"{'тёмная' if dark else 'светлая'} тема: кнопка под мышью")
ed, c = editor(RED)
wide, langs = [], set()
env_lang = os.environ.pop("CLIPSD_LANG", None)   # иначе язык из окружения важнее выбранного
for lang in i18n.LANGUAGES:
    langs.add(i18n.set_language(lang))
    h = PenHint(ed)
    for kind in ("color", "size", "both"):
        h.show_kind(kind, QColor(RED))
        if h.sizeHint().width() > 640 or h.button.width() < h.button.fontMetrics().horizontalAdvance(h.button.text()):
            wide.append((lang, kind, h.sizeHint().width()))
    h.dismiss()
    h.deleteLater()
if env_lang is not None:
    os.environ["CLIPSD_LANG"] = env_lang
i18n.set_language("ru")
check(langs == set(i18n.LANGUAGES), f"проверены все 12 языков: {sorted(langs)}")
check(not wide, f"подсказка на 12 языках не шире 640 px, подпись кнопки целиком: {wide}")
done(ed)

print(f"\n{'ВСЁ ХОРОШО' if not failures else 'ОШИБКИ: ' + str(len(failures))}")
sys.exit(1 if failures else 0)
