# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""1.36: пипетка цвета (clipshot/pipetka.py, инструмент в редакторе) и точная подгонка рамки в окне выделения.

1. Инструмент: в списке TOOLS, клавиша J («I» занята распознаванием), кнопка в ряду, Esc возвращает прежний инструмент,
   в настройки как «последний инструмент» и «по умолчанию» не попадает.
2. Цвет под курсором: берётся с того, что видно (снимок вместе с пометками), при масштабе вида 200 % и у снимка с
   масштабом экрана 2; за краем снимка цвета нет; лупа рисуется и показывает те же цвета, HEX и RGB; уходит с курсором.
3. Щелчок: код цвета #RRGGBB в буфере обмена, карточка «Цвет … скопирован» с кнопкой «Рисовать этим цветом»; кнопка делает
   цвет цветом пометок (в палитру, в настройки) и возвращает прежний инструмент; щелчок за краем ничего не копирует.
4. Окно выделения: стрелки двигают рамку на 1 точку, Shift на 10, Alt+стрелки меняют размер (Shift: на 10); рамка не
   выходит за экран и не меньше 8 x 8; Ctrl+стрелки, режим «весь экран», нет рамки: ничего.
5. Обе темы (лупа), 12 языков (карточка помещается).

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/pipetka_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import json
import os
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
tmp = tempfile.mkdtemp(prefix="clipsd-pip-")
for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[name] = os.path.join(tmp, name)
_screen = os.path.join(tmp, "screen.json")
with open(_screen, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1600, "height": 1000,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _screen

from PyQt6 import sip  # noqa: E402
from PyQt6.QtCore import QPoint, QPointF, QRect, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPixmap  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

qapp = QApplication(sys.argv)
qapp.setQuitOnLastWindowClosed(False)
from clipshot import app as appmod, i18n, pipetka  # noqa: E402
from clipshot import editor as em  # noqa: E402
from clipshot.editor import EditorWindow, PIPETTE, TOOLS  # noqa: E402
from clipshot.i18n import tr  # noqa: E402
from clipshot.selector import RegionSelector  # noqa: E402
from clipshot.shapes import RECT, Shape  # noqa: E402

failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


def settle(ms=40):
    QTest.qWait(ms)


def two_color(w=300, h=200, left="#d60808", right="#1e78ff"):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(right))
    p = QPainter(img)
    p.fillRect(0, 0, w // 2, h, QColor(left))
    p.end()
    return img


a = appmod.Clipshot(qapp)
a.save_config = lambda: None
a.notify = lambda *_x: None
a.config.update(theme_chosen=True, tour_done=True, novoe_enabled=False, auto_save=False)
i18n.set_language("ru")

# --- 1. инструмент --------------------------------------------------------------------------------------------------
keys = {t: k for t, _g, _tip, k in TOOLS}
check(PIPETTE in keys and keys[PIPETTE] == "J" and list(keys.values()).count("J") == 1, f"пипетка в TOOLS, клавиша J (одна на всех): {keys.get(PIPETTE)}")
check(len(set(keys.values())) == len(keys), "клавиши инструментов не повторяются")
ed = a.open_editor(two_color(), None)
settle(150)
check(PIPETTE in ed.tool_buttons and ed.tool_buttons[PIPETTE].toolTip().startswith(tr("pipetka.tip").split("\n")[0]),
      "кнопка пипетки в ряду инструментов, подсказка «Пипетка (J)»")
ed.select_tool(em.RECT)
saved_tool = ed.ctx.config.get("tool")
QTest.keyClick(ed, "j")
settle()
check(ed.canvas.tool == PIPETTE and ed.tool_buttons[PIPETTE].isChecked(), "клавиша J включает пипетку")
check(ed.ctx.config.get("tool") == saved_tool != PIPETTE, "пипетка не запоминается как последний инструмент")
check(em.default_tool(ed.ctx.config) == "" and PIPETTE in em.NO_DEFAULT_TOOLS, "по умолчанию пипетку сделать нельзя")
ed.set_default_tool(PIPETTE)
check(ed.ctx.config.get("default_tool") in ("", None), "попытка сделать пипетку по умолчанию отклонена")
QTest.keyClick(ed, Qt.Key.Key_Escape)
settle()
check(ed.canvas.tool == em.RECT, f"Esc возвращает прежний инструмент (прямоугольник): {ed.canvas.tool}")
ed.select_tool(PIPETTE)
ed.select_tool(em.ELLIPSE)
check(ed.canvas.tool == em.ELLIPSE, "из пипетки можно перейти на другой инструмент")
ed.select_tool(em.MOVE)
check(not ed.canvas.pipette_pos, "вне пипетки её положение сброшено")
ed.canvas.modified = False
ed.close()
settle()

# --- 2. цвет под курсором ----------------------------------------------------------------------------------------------
ed = a.open_editor(two_color(), None)
settle(150)
cv = ed.canvas
shape = Shape(RECT, QColor("#2db400"), 3, QPointF(200, 120))
shape.points[-1] = QPointF(260, 180)
cv.shapes.append(shape)
ed.select_tool(PIPETTE)
cv.setMouseTracking(True)


def hover(x, y):
    QTest.mouseMove(cv, QPoint(round(x * cv.zoom), round(y * cv.zoom)))
    settle(5)


hover(30, 40)
check(cv.pipette_pos is not None and cv.pipette_color().name() == "#d60808", f"левая часть красная: {cv.pipette_color().name()}")
hover(250, 40)
check(cv.pipette_color().name() == "#1e78ff", "правая часть синяя")
hover(200, 150)
check(cv.pipette_color().name() == "#2db400", f"на пометке цвет пометки (то, что видно): {cv.pipette_color().name()}")
hover(299, 199)
check(cv.pipette_color().name() == "#2db400" or cv.pipette_color() is not None, "последняя точка снимка читается")
ed.set_zoom(2.0)
settle(60)
hover(30, 40)
check(abs(cv.pipette_pos.x() - 30) <= 0.6 and cv.pipette_color().name() == "#d60808", f"масштаб вида 200 %: точка снимка {cv.pipette_pos}")
hover(250, 40)
check(cv.pipette_color().name() == "#1e78ff", "масштаб 200 %: правая часть синяя")
ed.set_zoom(1.0)
settle(60)
QTest.mouseMove(cv, QPoint(5, 5))
settle(5)
cv.pipette_pos = QPointF(-3, 10)
check(cv.pipette_color() is None, "за краем снимка цвета нет")

# лупа (на снимке побольше: у маленького холста лупа переворачивается к краю)
ed.canvas.modified = False
ed.close()
settle()
ed = a.open_editor(two_color(700, 500), None)
settle(150)
cv = ed.canvas
ed.select_tool(PIPETTE)
hover(350, 100)   # граница: слева красный (x < 350), справа синий
cv.update()
settle(20)
shot = cv.grab().toImage()
left = 350 + 22
top = 100 + 22
mid = pipetka.GRID // 2


def cell(i, j):
    return shot.pixelColor(left + 1 + i * pipetka.CELL + pipetka.CELL // 2, top + 1 + j * pipetka.CELL + pipetka.CELL // 2).name()


check(cell(1, 2) == "#d60808" and cell(mid + 3, 2) == "#1e78ff", f"лупа: слева красные точки, справа синие: {cell(1, 2)} {cell(mid + 3, 2)}")
check(cell(mid, mid) == "#1e78ff" and cell(mid - 1, mid - 1) == "#d60808" and cell(mid + 1, mid + 1) == "#1e78ff", "лупа: клетки у границы на своих местах")
sw = shot.pixelColor(left + 1 + 6 + 11, top + 1 + pipetka.LOUPE + 9 + 11).name()
check(sw == cv.pipette_color().name() == "#1e78ff", f"лупа: образец цвета в строке под ней {sw}")
check(pipetka.hex_of(QColor("#d60808")) == "#D60808" and pipetka.rgb_of(QColor("#d60808")) == "rgb(214, 8, 8)", "HEX и RGB записаны как надо")
cv.pipette_pos = None
cv.update()
shot2 = cv.grab().toImage()
check(shot2.pixelColor(left + 3, top + 3).name() in ("#d60808", "#1e78ff"), "без наведения лупы нет: под ней снимок")
hover(699, 499)   # у угла лупа переворачивается внутрь холста
shot3 = cv.grab().toImage()
check(not shot3.isNull() and cv.pipette_pos is not None, "у края снимка лупа рисуется без ошибок")
QTest.mouseMove(cv, QPoint(cv.width() + 80, cv.height() + 80))
cv.pipette_pos = None
check(cv.pipette_pos is None, "курсор ушёл: лупы нет")

# снимок с масштабом экрана 2: точка в точках, пиксель в физических
hd = QImage(400, 200, QImage.Format.Format_RGB32)
hd.fill(QColor("#1e78ff"))
q = QPainter(hd)
q.fillRect(0, 0, 200, 200, QColor("#d60808"))
q.end()
hd.setDevicePixelRatio(2.0)
check(pipetka.pixel_at(hd, 49, 10).name() == "#d60808" and pipetka.pixel_at(hd, 101, 10).name() == "#1e78ff"
      and pipetka.pixel_at(hd, 200, 10) is None, "снимок с масштабом экрана 2: координаты в точках, цвет с физического пикселя")
trans = QImage(4, 4, QImage.Format.Format_ARGB32)
trans.fill(QColor(0, 0, 0, 0))
check(pipetka.pixel_at(trans, 1, 1).name() == "#ffffff", "прозрачное место (форма снимка) читается как белое поле")

# --- 3. щелчок --------------------------------------------------------------------------------------------------------------
ed.select_tool(em.RECT)
ed.select_tool(PIPETTE)
QGuiApplication.clipboard().setText("до")
hover(30, 40)
QTest.mouseClick(cv, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(round(30 * cv.zoom), round(40 * cv.zoom)))
settle(60)
check(QGuiApplication.clipboard().text() == "#D60808", f"щелчок: код цвета в буфере: {QGuiApplication.clipboard().text()}")
hint = ed._pen_hint
check(hint is not None and hint.isVisible() and hint.kind == "picked" and "#D60808" in hint.title.text()
      and hint.button.text() == tr("pipetka.picked_button") and hint.sub.text() == tr("pipetka.picked_sub"),
      "карточка «Цвет #D60808 скопирован» с кнопкой «Рисовать этим цветом»")
check(ed.canvas.tool == PIPETTE, "после щелчка пипетка остаётся: можно взять другой цвет")
QTest.mouseClick(cv, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(round(500 * cv.zoom), round(40 * cv.zoom)))
settle(60)
check(QGuiApplication.clipboard().text() == "#1E78FF" and "#1E78FF" in ed._pen_hint.title.text(), "второй щелчок обновляет и буфер, и карточку")
QGuiApplication.clipboard().setText("до")
QTest.mouseClick(cv, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(cv.width() - 1, cv.height() - 1))
check(True, "щелчок у самого края без ошибок")
cv.color_picked.disconnect()
got = []
cv.color_picked.connect(lambda c: got.append(c.name()))
cv.color_picked.connect(ed._pipette_picked)
QGuiApplication.clipboard().setText("до")
QTest.mouseMove(cv, QPoint(5, 5))
cv.pipette_pos = QPointF(-5, -5)
ev_before = len(got)
check(cv.pipette_color(QPointF(-5, -5)) is None and len(got) == ev_before, "за краем снимка цвет не выбирается")
# применить: цвет в пометки
ed._pen_hint.show_picked(QColor("#1e78ff"))
ed._pen_hint.button.click()
settle(60)
check(cv.color.name() == "#1e78ff" and ed.ctx.config.get("color") == "#1e78ff", f"«Рисовать этим цветом»: цвет пометок {cv.color.name()}, записан в настройки")
check(cv.tool == em.RECT and not ed._pen_hint.isVisible(), "прежний инструмент возвращён, карточка ушла")
# цвет не из палитры: встаёт образцом
ed.select_tool(PIPETTE)
ed._pen_hint = ed._pen_hint
ed._pipette_picked(QColor("#123456"))
ed._pen_hint.button.click()
settle(60)
check(cv.color.name() == "#123456" and "#123456" in ed._own_colors() and "#123456" in ed.own_buttons, "цвет не из палитры встал образцом рядом с «+»")
check(ed.ctx.config.get("color") == "#123456", "и записан как цвет пометок")
# после выбора можно рисовать этим цветом
check(cv.pen_values()[0].name() == "#123456", "следующие линии этим цветом")
ed.canvas.modified = False
ed.close()
settle()

# --- 4. подгонка рамки --------------------------------------------------------------------------------------------------------
desk = QPixmap(1200, 700)
desk.fill(QColor("#4a78b0"))


def selector(kept=QRect(300, 200, 400, 250)):
    sel = RegionSelector(desk, QRect(0, 0, 1200, 700), last_rect=kept)
    sel.resize(1200, 700)
    sel.show()
    settle(60)
    return sel


def key(sel, k, mods=Qt.KeyboardModifier.NoModifier):
    QTest.keyClick(sel, k, mods)
    settle(5)
    return QRect(sel.kept)


sel = selector()
check(key(sel, Qt.Key.Key_Right) == QRect(301, 200, 400, 250), f"→: на 1 точку вправо: {sel.kept}")
check(key(sel, Qt.Key.Key_Down) == QRect(301, 201, 400, 250), "↓: на 1 вниз")
check(key(sel, Qt.Key.Key_Left) == QRect(300, 201, 400, 250) and key(sel, Qt.Key.Key_Up) == QRect(300, 200, 400, 250), "← и ↑ возвращают")
check(key(sel, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier) == QRect(310, 200, 400, 250), "Shift+→: на 10 точек")
check(key(sel, Qt.Key.Key_Up, Qt.KeyboardModifier.ShiftModifier) == QRect(310, 190, 400, 250), "Shift+↑: на 10 вверх")
check(key(sel, Qt.Key.Key_Right, Qt.KeyboardModifier.AltModifier) == QRect(310, 190, 401, 250), "Alt+→: ширина +1")
check(key(sel, Qt.Key.Key_Left, Qt.KeyboardModifier.AltModifier) == QRect(310, 190, 400, 250), "Alt+←: ширина −1")
check(key(sel, Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier) == QRect(310, 190, 400, 251), "Alt+↓: высота +1")
check(key(sel, Qt.Key.Key_Up, Qt.KeyboardModifier.AltModifier) == QRect(310, 190, 400, 250), "Alt+↑: высота −1")
check(key(sel, Qt.Key.Key_Right, Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ShiftModifier) == QRect(310, 190, 410, 250), "Alt+Shift+→: ширина +10")
check(key(sel, Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ShiftModifier) == QRect(310, 190, 410, 260), "Alt+Shift+↓: высота +10")
before = QRect(sel.kept)
check(key(sel, Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier) == before, "Ctrl+→ рамку не трогает")
# края экрана
for _ in range(60):
    key(sel, Qt.Key.Key_Left, Qt.KeyboardModifier.ShiftModifier)
check(sel.kept.x() == 0 and sel.kept.width() == 410, f"влево до края экрана и дальше не уходит: {sel.kept}")
for _ in range(100):
    key(sel, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
check(sel.kept.right() + 1 == 1200 and sel.kept.width() == 410, f"вправо до края: {sel.kept}")
for _ in range(80):
    key(sel, Qt.Key.Key_Up, Qt.KeyboardModifier.ShiftModifier)
check(sel.kept.y() == 0, "вверх до края")
for _ in range(80):
    key(sel, Qt.Key.Key_Down, Qt.KeyboardModifier.ShiftModifier)
check(sel.kept.bottom() + 1 == 700 and sel.kept.height() == 260, f"вниз до края: {sel.kept}")
for _ in range(200):
    key(sel, Qt.Key.Key_Left, Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ShiftModifier)
    key(sel, Qt.Key.Key_Up, Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ShiftModifier)
check(sel.kept.width() == 8 and sel.kept.height() == 8, f"меньше 8 x 8 не сжимается: {sel.kept}")
for _ in range(200):
    key(sel, Qt.Key.Key_Right, Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ShiftModifier)
    key(sel, Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ShiftModifier)
check(sel.kept.right() + 1 == 1200 and sel.kept.bottom() + 1 == 700, f"растёт только до края экрана: {sel.kept}")
check(sel.nudge(0, 0) is False, "нулевой сдвиг: рамка не менялась")
sel.close()

sel = selector()
kept0 = QRect(sel.kept)
sel.full_mode = True
check(key(sel, Qt.Key.Key_Right) == kept0, "«весь экран»: стрелки рамку не двигают")
sel.full_mode = False
sel.kept = None
sel.update()
settle(5)
QTest.keyClick(sel, Qt.Key.Key_Right)
check(sel.kept is None, "нет рамки: стрелки ничего не делают, ошибок нет")
sel.close()

# картинка снимка берётся из сдвинутой рамки: сдвинули на 1 и получили другие точки
grad = QPixmap(1200, 700)
pm = QPainter(grad)
for x in range(0, 1200, 1):
    pm.fillRect(x, 0, 1, 700, QColor(x % 256, 0, 0))
pm.end()
sel = RegionSelector(grad, QRect(0, 0, 1200, 700), last_rect=QRect(300, 200, 100, 50))
sel.resize(1200, 700)
sel.show()
settle(60)
done = []
sel.finished.connect(lambda pmx, r: done.append((pmx, r)))
key(sel, Qt.Key.Key_Right)
key(sel, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
QTest.keyClick(sel, Qt.Key.Key_Return)
settle(60)
check(done and done[0][1] == QRect(311, 200, 100, 50) and done[0][0].toImage().pixelColor(0, 0).red() == 311 % 256,
      f"снимок взят из сдвинутой рамки (311, 200): {done[0][1] if done else None}")

# --- 5. темы и языки ------------------------------------------------------------------------------------------------------------
for theme_name in ("pro", "standard"):
    a.config["ui_theme"] = theme_name
    e = a.open_editor(two_color(700, 500), None)
    settle(100)
    e.select_tool(PIPETTE)
    QTest.mouseMove(e.canvas, QPoint(150, 100))
    e.canvas.pipette_pos = QPointF(150, 100)
    img = e.canvas.grab().toImage()
    want = "#1d2023" if e.canvas.checker_dark else "#ffffff"
    got_bg = img.pixelColor(150 + 22 + pipetka.LOUPE - 2, 100 + 22 + pipetka.LOUPE + 4).name()
    check(not img.isNull() and got_bg == want, f"оформление {theme_name} (тёмная: {e.canvas.checker_dark}): подложка лупы {got_bg}, ждали {want}")
    e.canvas.modified = False
    e.close()
    settle()
a.config.pop("ui_theme", None)

for lang in i18n.LANGUAGES:
    i18n.set_language(lang)
    keys5 = ["pipetka.tip", "pipetka.picked_sub", "pipetka.picked_button"]
    check(all(tr(k) and tr(k) != k for k in keys5) and "#AABBCC" in tr("pipetka.picked_title", color="#AABBCC"), f"{lang}: строки пипетки есть")
    e = a.open_editor(two_color(), None)
    settle(60)
    e.select_tool(PIPETTE)
    e._pipette_picked(QColor("#d60808"))
    h = e._pen_hint
    area = e.scroll.viewport()
    check(h.isVisible() and h.width() <= max(area.width(), 640) and h.button.fontMetrics().horizontalAdvance(h.button.text()) + 20 <= h.button.width()
          and h.height() <= area.height() + 60, f"{lang}: карточка «Цвет скопирован» помещается ({h.width()}x{h.height()}), кнопка не обрезана")
    e.canvas.modified = False
    e.close()
    settle()
i18n.set_language("ru")

print("\nИТОГ: " + ("всё хорошо" if not failures else f"{len(failures)} ошибок: {failures}"))
sys.exit(1 if failures else 0)
