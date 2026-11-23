# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Автотест новых функций редактора ClipSD: сноска, стрелки, номера с указателем, ручки, правка.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/features_test.py [проект] [папка_картинок]
"""

import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import os
import sys

here = os.path.dirname(os.path.abspath(__file__))
project = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(here)
out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(here, "output")
sys.path.insert(0, project)
os.makedirs(out, exist_ok=True)

from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QCursor, QGuiApplication, QColor, QImage, QKeyEvent, QMouseEvent, QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)

from clipshot import app as appmod
from clipshot.editor import MOVE, TOOLS as TOOLS_LIST, EditorWindow
from clipshot.shapes import ARROW, CALLOUT, DARROW, FARROW, NUMBER, RECT, TEXT

failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


class Ctx:
    config = dict(appmod.DEFAULTS)
    icon = appmod.make_icon()
    clipboard = None

    def copy_image(self, image):
        Ctx.clipboard = image

    def notify(self, text):
        pass

    def save_config(self):
        pass


img = QImage(560, 340, QImage.Format.Format_RGB32)
img.fill(QColor("#dfe6ee"))
ed = EditorWindow(img, Ctx(), QPoint(50, 50))
ed.present()
app.processEvents()
c = ed.canvas


def move(x, y, mods=Qt.KeyboardModifier.NoModifier):
    QApplication.sendEvent(c, QMouseEvent(QEvent.Type.MouseMove, QPointF(x, y), c.mapToGlobal(QPointF(x, y)),
                                          Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, mods))


def drag(a, b, mods=Qt.KeyboardModifier.NoModifier, path=None):
    QTest.mousePress(c, Qt.MouseButton.LeftButton, mods, QPoint(*a))
    for x, y in (path or []) + [b]:
        move(x, y, mods)
    QTest.mouseRelease(c, Qt.MouseButton.LeftButton, mods, QPoint(*b))


def type_text(widget, text):
    for ch in text:
        for t in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            QApplication.sendEvent(widget, QKeyEvent(t, 0, Qt.KeyboardModifier.NoModifier, ch))


# Номер с выносным указателем; кружок и указатель двигаются по отдельности
ed.select_tool(NUMBER)
drag((60, 60), (150, 120), path=[(100, 90)])
num = c.shapes[-1]
check(num.kind == NUMBER and c.selected is num, "номер нарисован и сразу выделен")
tail_before = QPointF(num.points[-1])
drag((60, 60), (80, 40), path=[(70, 50)])          # тянем кружок
check(num.points[-1] == tail_before and num.points[0] == QPointF(80, 40), "кружок номера двигается без указателя")
drag((150, 120), (170, 150), path=[(160, 135)])    # тянем конец указателя (ручка)
check(num.points[-1] == QPointF(170, 150) and num.points[0] == QPointF(80, 40), "указатель номера двигается отдельно")
drag((80, 40), (90, 50), Qt.KeyboardModifier.ShiftModifier, path=[(85, 45)])
check(num.points[0] == QPointF(90, 50) and num.points[-1] == QPointF(180, 160), "Shift — номер с указателем вместе")
ed.select_tool(NUMBER)
drag((60, 200), (60, 200))
drag((60, 260), (60, 260))
check([s.number for s in c.shapes if s.kind == NUMBER] == [1, 2, 3], "номера 1, 2, 3 по порядку")

# Размер выделенного: кнопки и колесо
size_default = c.pen_size
ed.select_size(4)
check(c.selected.size == 4, "кнопка толщины меняет выделенный объект")
check(c.pen_size == size_default, "общая толщина для новых объектов не изменилась")
sel = c.selected
pos = sel.points[0]
QApplication.sendEvent(c, QWheelEvent(pos, c.mapToGlobal(pos), QPoint(), QPoint(0, -120),
                                      Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                                      Qt.ScrollPhase.NoScrollPhase, False))
check(sel.size == 3, "колесо мыши уменьшает размер выделенного")
check(ed.size_group.checkedId() == 3, "кнопки толщины показывают размер выделенного")

# Стрелка в обе стороны и свободная стрелка со сглаживанием
ed.select_tool(DARROW)
drag((250, 40), (400, 40))
check(c.shapes[-1].kind == DARROW, "стрелка в обе стороны")
ed.select_tool(FARROW)
wobble = [(220 + i * 6, 120 + (3 if i % 2 else -3) + (i * i) // 12) for i in range(1, 40)]
drag((220, 120), (460, 250), path=wobble)
fa = c.shapes[-1]
check(fa.kind == FARROW and len(fa.points) < len(wobble) // 2, f"свободная стрелка спрямлена ({len(fa.points)} точек из {len(wobble) + 2})")

# Ручки прямоугольника
ed.select_tool(RECT)
drag((300, 270), (380, 320))
r = c.shapes[-1]
drag((380, 320), (420, 330), path=[(400, 325)])
check(r.rect().right() == 420 and r.rect().bottom() == 330, "ручка угла меняет размер прямоугольника")

# Сноска: точка-цель → блок с текстом
ed.select_tool(CALLOUT)
drag((480, 300), (420, 200), path=[(450, 250)])
check(c.text_edit is not None, "сноска открывает поле ввода")
type_text(c.text_edit, "Сюда нажать")
QTest.keyClick(c.text_edit, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
co = c.shapes[-1]
check(co.kind == CALLOUT and co.text == "Сюда нажать" and co.points[0] == QPointF(480, 300), "сноска создана")
check(co.callout_box().right() <= c.width(), "блок сноски не вылезает за край снимка")

# Правка текста двойным кликом
ed.select_tool(MOVE)
box = co.callout_box().center().toPoint()
QTest.mouseDClick(c, Qt.MouseButton.LeftButton, pos=box)
check(c.text_edit is not None and c.text_edit.toPlainText() == "Сюда нажать", "двойной клик открывает сноску на правку")
type_text(c.text_edit, "!")
QTest.keyClick(c.text_edit, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
edited = [s for s in c.shapes if s.kind == CALLOUT]
check(len(edited) == 1 and edited[0].text == "Сюда нажать!", "правка сохранена, дубля нет")
c.undo()
check([s.text for s in c.shapes if s.kind == CALLOUT] == ["Сюда нажать"], "Ctrl+Z возвращает текст до правки")
c.select(None)

ed.grab().save(os.path.join(out, "6_editor_new_ui.png"))
c.render().save(os.path.join(out, "7_render_new_tools.png"))

# Узкий снимок: панель не уходит в меню, окно не уже панели
tiny = QImage(200, 120, QImage.Format.Format_RGB32)
tiny.fill(QColor("#c8d4e0"))
small = EditorWindow(tiny, Ctx(), QPoint(10, 10))
small.present()
app.processEvents()
screen_w = small._screen_area().width() - 20   # окно не шире экрана (в тесте экран 800 px)
check(small.width() >= min(small.panel.sizeHint().width(), screen_w),
      f"узкий снимок: окно {small.width()} px вмещает панель")
small.grab().save(os.path.join(out, "8_editor_small.png"))

# --- Цвет текста в номере и сноске, запоминание выбора ------------------------
ed2 = EditorWindow(img, Ctx(), QPoint(50, 50))
ed2.present()
app.processEvents()
c2 = ed2.canvas
ed2.select_tool(NUMBER)
QTest.mouseClick(c2, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
n2 = c2.shapes[-1]
check(n2.label_color() == QColor("#ffffff"), "цифра в номере по умолчанию белая")
ed2.select_text_color("#000000")
check(n2.label_color() == QColor("#000000"), "цвет текста меняет выделенный номер")
check(c2.text_color is None and Ctx.config["text_color"] == "", "правка выделенного не меняет общий цвет текста")
QTest.mouseClick(c2, Qt.MouseButton.LeftButton, pos=QPoint(200, 100))
check(c2.shapes[-1].label_color() == QColor("#ffffff"), "следующий номер рисуется с общим цветом текста")
c2.undo()
c2.undo()
check(c2.shapes[-1].label_color() == QColor("#ffffff") if c2.shapes else True, "Ctrl+Z отменяет смену цвета текста")
c2.select(None)
ed2.select_text_color("#000000")
ed2.select_color("#2db400")
ed2.select_size(5)
cfg = Ctx.config
check(cfg["tool"] == NUMBER and cfg["color"] == "#2db400" and cfg["size"] == 5 and cfg["text_color"] == "#000000",
      "выбор инструмента, цветов и толщины записан в настройки")
ed3 = EditorWindow(img, Ctx(), QPoint(50, 50))
check(ed3.canvas.tool == NUMBER and ed3.canvas.color == QColor("#2db400") and ed3.canvas.pen_size == 5
      and ed3.canvas.text_color == QColor("#000000") and ed3.size_group.checkedId() == 5
      and ed3.tool_buttons[NUMBER].isChecked() and ed3.color_buttons["#2db400"].isChecked(),
      "следующий снимок открывается с прошлым выбором")
ed2.grab().save(os.path.join(out, "9_text_color.png"))

# --- Перенумерация после удаления --------------------------------------------
ed4 = EditorWindow(img, Ctx(), QPoint(50, 50))
c4 = ed4.canvas
ed4.select_tool(NUMBER)
for x in (60, 120, 180, 240):
    QTest.mouseClick(c4, Qt.MouseButton.LeftButton, pos=QPoint(x, 100))
ed4.select_tool(MOVE)
QTest.mouseClick(c4, Qt.MouseButton.LeftButton, pos=QPoint(120, 100))
check(c4.selected is not None and c4.selected.number == 2, "выделен номер 2")
QTest.keyClick(c4, Qt.Key.Key_Delete)
nums = [(s.points[0].x(), s.number) for s in c4.shapes if s.kind == NUMBER]
check(nums == [(60, 1), (180, 2), (240, 3)], f"после удаления номера идут без пропуска: {nums}")
c4.undo()
check([s.number for s in c4.shapes if s.kind == NUMBER] == [1, 2, 3, 4], "Ctrl+Z возвращает прежнюю нумерацию")
QTest.mousePress(c4, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, QPoint(240, 100))
QTest.mouseRelease(c4, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, QPoint(240, 100))
check(c4.shapes[-1].number == 5, "копия номера получает следующий номер")

# --- Плавная линия и свободная фигура ----------------------------------------
from clipshot.shapes import FLINE, FSHAPE
import math as _m
ed7 = EditorWindow(img, Ctx(), QPoint(0, 0))
c7 = ed7.canvas
c = c7   # drag() рисует на текущем холсте c
ed7.select_tool(FLINE)
path = [(60 + i * 5, 150 + int(30 * _m.sin(i / 6)) + (2 if i % 2 else -2)) for i in range(1, 60)]
drag((60, 150), (360, 150), path=path)
fl = c7.shapes[-1]
check(fl.kind == FLINE and len(fl.points) < len(path) // 3, f"плавная линия сглажена ({len(fl.points)} точек из {len(path) + 2})")
ed7.select_tool(FSHAPE)
circle = [(300 + int(80 * _m.cos(a / 20)) + (2 if a % 2 else -2), 170 + int(60 * _m.sin(a / 20))) for a in range(0, 126)]
drag(circle[0], circle[-1], Qt.KeyboardModifier.ControlModifier, path=circle[1:-1])
fs = c7.shapes[-1]
check(fs.kind == FSHAPE and fs.filled and len(fs.points) < len(circle) // 3, f"свободная фигура: закрашена, {len(fs.points)} точек")
check(fs.hit(QPointF(300, 170)), "по закрашенной фигуре можно попасть кликом внутри")
c7.select(None)
ed7.select_tool(FSHAPE)
QTest.mousePress(c7, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(420, 40))
for x, y in ((470, 50), (500, 90), (480, 120)):
    move(x, y)
mid = c7.grab()
mid.save(os.path.join(out, "11_fshape_drawing.png"))
check(c7.current is not None and c7.current.kind == FSHAPE, "фигура в процессе рисования ещё не замкнута")
QTest.mouseRelease(c7, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(480, 120))
check(c7.current is None and c7.shapes[-1].kind == FSHAPE, "после отпускания фигура замкнулась")
c7.select(None)
ed7.select_tool(FSHAPE)
tri = [(80, 260), (120, 200), (160, 262), (100, 300)]
drag(tri[0], tri[-1], path=tri[1:-1])
check(c7.shapes[-1].kind == FSHAPE and not c7.shapes[-1].filled, "контур без Ctrl не закрашен")
c7.select(None)
c7.render().save(os.path.join(out, "10_fline_fshape.png"))

# --- Ластик ---------------------------------------------------------------------
from clipshot.editor import ERASER
from clipshot.shapes import LINE
ed8 = EditorWindow(img, Ctx(), QPoint(0, 0))
ed8.present()
c8 = ed8.canvas
c = c8
ed8.select_tool(NUMBER)
for x in (60, 120, 180):
    QTest.mouseClick(c8, Qt.MouseButton.LeftButton, pos=QPoint(x, 40))
ed8.select_tool(LINE)
drag((40, 150), (500, 150))
ed8.select_tool(LINE)
drag((40, 250), (500, 250))
c8.select(None)
check(not ed8.eraser_box.isVisible(), "кнопки режима ластика скрыты, пока ластик не выбран")
ed8.select_tool(ERASER)
check(ed8.eraser_box.isVisible(), "при ластике появились кнопки «Целиком» и «Частично»")
ed8.select_eraser_mode("object")
drag((120, 30), (120, 50))
nums = sorted(s.number for s in c8.shapes if s.kind == NUMBER)
check(nums == [1, 2], f"ластик целиком удалил номер, остальные перенумерованы: {nums}")
check(len(c8.shapes) == 4, "соседние объекты не задеты")
c8.undo()
check(len([s for s in c8.shapes if s.kind == NUMBER]) == 3, "Ctrl+Z возвращает стёртый объект")

ed8.select_eraser_mode("part")
ed8.select_size(3)
check(c8.eraser_width() == 22, "размер кисти по кнопке толщины")
lines = [s for s in c8.shapes if s.kind == LINE]
drag((270, 120), (270, 280))     # проходит через обе линии
check(all(len(s.erasures) == 1 for s in lines), "частично: без выделения стёрты куски обеих линий")
img8 = c8.render()
check(img8.pixelColor(270, 150) != lines[0].color and img8.pixelColor(150, 150).name() == lines[0].color.name(),
      "в месте прохода линия стёрта, рядом цела")
c8.undo()
check(all(not s.erasures for s in c8.shapes), "Ctrl+Z отменяет весь проход ластиком")
lines = [s for s in c8.shapes if s.kind == LINE]
c8.select(lines[0])
size_before = lines[0].size
ed8.select_size(5)
check(lines[0].size == size_before, "при ластике кнопки толщины не меняют выделенный объект")
drag((330, 120), (330, 280))
lines = [s for s in c8.shapes if s.kind == LINE]
check(len(lines[0].erasures) == 1 and not lines[1].erasures, "частично: стёрт только выделенный объект")
lines[0].translate(QPointF(0, 10))
check(lines[0].erasures[0][1][0].y() == 130, "стёртый кусок едет вместе с объектом")
c8.select(None)
c8.render().save(os.path.join(out, "12_eraser.png"))

# --- Вставка картинки поверх снимка -----------------------------------------
from clipshot.shapes import IMAGE
from PyQt6.QtGui import QGuiApplication
ed9 = EditorWindow(img, Ctx(), QPoint(0, 0))
ed9.select_tool(MOVE)
ed9.present()
c9 = ed9.canvas
big = QImage(1200, 600, QImage.Format.Format_RGB32)
big.fill(QColor("#ff8800"))
QGuiApplication.clipboard().setImage(big)
ed9.paste_image()
im = c9.shapes[-1] if c9.shapes else None
check(im is not None and im.kind == IMAGE, "Ctrl+V вставил картинку из буфера")
r = im.rect()
check(r.width() <= c9.width() * 0.9 + 1 and abs(r.width() / r.height() - 2.0) < 0.02,
      f"большая картинка уменьшена с сохранением пропорций: {r.width():.0f}×{r.height():.0f}")
check(c9.selected is im, "вставленная картинка сразу выделена")
corner = r.bottomRight()
c = c9
drag((int(corner.x()), int(corner.y())), (int(corner.x()) - 100, int(corner.y()) - 10))
r2 = im.rect()
check(r2.width() < r.width() and abs(r2.width() / r2.height() - 2.0) < 0.05, "ручка угла меняет размер, пропорции сохранены")
small_img = QImage(40, 30, QImage.Format.Format_RGB32)
small_img.fill(QColor("#0000ff"))
c9.insert_image(small_img, QPointF(100, 100))
check(c9.shapes[-1].rect().width() == 40, "маленькая картинка вставлена в натуральную величину")
c9.undo()
check(len(c9.shapes) == 1, "Ctrl+Z убирает вставку")
out_img = c9.render()
check(out_img.pixelColor(int(r2.center().x()), int(r2.center().y())).name() == "#ff8800", "вставка видна в итоговой картинке")
c9.select(None)
c9.render().save(os.path.join(out, "13_insert.png"))

# --- Меню правой кнопки и подсказка ----------------------------------------
from clipshot.shapes import RECT as _RECT
ed10 = EditorWindow(img, Ctx(), QPoint(0, 0))
ed10.present()
c10 = ed10.canvas
c = c10
ed10.select_tool(_RECT)
drag((50, 50), (200, 150))
rect_shape = c10.shapes[-1]
check("Выделено: прямоугольник" in ed10.info.text(), f"подсказка о выделенном: {ed10.info.text()!r}")
menu = ed10.build_context_menu(rect_shape)
names = [a.text() for a in menu.actions()]
check("Цвет" in names and "Толщина" in names and "Закрасить" in names and "Дублировать\tCtrl+D" in names
      and "Удалить\tDelete" in names, f"меню объекта: {names}")
color_menu = next(a.menu() for a in menu.actions() if a.text() == "Цвет")
default_color = QColor(c10.color)
next(a for a in color_menu.actions() if a.text() == "#1E78FF").trigger()
check(rect_shape.color.name() == "#1e78ff" and c10.color == default_color, "цвет из меню меняет только объект")
next(a for a in menu.actions() if a.text() == "Закрасить").trigger()
check(rect_shape.filled, "«Закрасить» из меню")
next(a for a in menu.actions() if a.text().startswith("Дублировать")).trigger()
check(len(c10.shapes) == 2 and c10.selected is c10.shapes[-1], "«Дублировать» из меню")
c10.restack_selected(False)
check(c10.shapes[0] is c10.selected, "«На задний план»")
ed10.escape()   # то, что делает Esc в этом окне (в тесте открыто много окон, активное другое)
check(c10.selected is None and ed10.isVisible(), "Esc сначала снимает выделение, окно остаётся")
check("Выделено" not in ed10.info.text(), "подсказка исчезла после снятия выделения")
empty = [a.text() for a in ed10.build_context_menu(None).actions()]
check(any(t.startswith("Вставить картинку из буфера") for t in empty) and "Настройки…\tCtrl+," in empty,
      f"меню пустого места: {empty}")

# --- Вводный курс ---------------------------------------------------------------
from clipshot.app import demo_image
Ctx.config["tour_done"] = False
ed11 = EditorWindow(demo_image(), Ctx(), QPoint(0, 0))
ed11.resize(1000, 760)
ed11.present()
app.processEvents()
ed11.start_tour()
app.processEvents()
tour = ed11.tour
check(tour is not None and tour.isVisible(), "курс запущен поверх окна")
holes = []
for i in range(len(tour.steps)):
    tour.show_step(i)
    app.processEvents()
    holes.append(tour.hole.isValid())
    if i in (0, 1, 4, 7):
        ed11.grab().save(os.path.join(out, f"14_tour_step{i + 1}.png"))
# 1.31: первый экран знакомства: выбор языка (без подсветки), второй: «Знакомство с ClipSD» (без подсветки)
check(holes[0] is False and holes[1] is False and holes[-1] is False and all(holes[2:-1]), f"подсветка у каждого шага с блоком: {holes}")
check(all(tour.card.geometry().intersects(tour.rect()) and tour.rect().contains(tour.card.geometry())
          for _ in [0]), "карточка внутри окна")
tour.show_step(0)
QTest.keyClick(tour, Qt.Key.Key_Right)
QTest.keyClick(tour, Qt.Key.Key_Right)
check(tour.index == 2, "стрелка вправо листает вперёд")
QTest.keyClick(tour, Qt.Key.Key_Left)
check(tour.index == 1, "стрелка влево листает назад")
c11 = ed11.canvas
ed11.select_tool(MOVE)
QTest.keyClick(tour, Qt.Key.Key_A)
check(c11.tool == MOVE, "буквы во время курса не переключают инструменты")
QTest.keyClick(tour, Qt.Key.Key_Escape)
app.processEvents()
check(ed11.tour is None and Ctx.config["tour_done"] is True and ed11.isVisible(),
      "Esc закрывает курс, окно остаётся, курс отмечен пройденным")
# 1.32: повторное знакомство («?», F1, меню значка, настройки) без шага выбора языка, первое: с ним
from clipshot.i18n import tr as _tr
first_steps = len(tour.steps)
ed11.start_tour()
check(not ed11.tour.with_language and len(ed11.tour.steps) == first_steps - 1
      and ed11.tour.steps[0][1] == _tr("tour.intro_title"),
      "повторное знакомство начинается со «Знакомство с ClipSD», без выбора языка")
ed11.tour.finish()
app.processEvents()
help_tour = next(a for a in ed11.help_menu.actions() if a.text() == _tr("app.menu_tour"))
help_tour.trigger()
app.processEvents()
check(ed11.tour is not None and not ed11.tour.with_language, "«?» → «Знакомство с программой»: без выбора языка")
ed11.tour.finish()
app.processEvents()
QTest.keyClick(ed11, Qt.Key.Key_F1)
app.processEvents()
check(ed11.tour is not None and not ed11.tour.with_language, "F1: знакомство без выбора языка")
ed11.tour.finish()
app.processEvents()
ed11.start_tour()
for _ in range(len(ed11.tour.steps)):
    ed11.tour.next.click()
check(ed11.tour is None, "кнопка «Готово» на последнем шаге закрывает курс")
opened = []
ed11.ctx.open_settings = lambda parent=None: opened.append(parent)
ed11.start_tour()
ed11.tour.show_step(len(ed11.tour.steps) - 1)
app.processEvents()
last = ed11.tour
check(last.action.isVisible() and "настройк" in last.action.text() and "заменить" in last.text.text(),
      "последний шаг: про смену сочетания и кнопка перехода в настройки")
ed11.grab().save(os.path.join(out, "15_tour_last.png"))
last.action.click()
check(ed11.tour is None and opened == [ed11], "кнопка закрывает курс и открывает настройки")

# --- Перестановка инструментов перетаскиванием -------------------------------
ed5 = EditorWindow(img, Ctx(), QPoint(0, 0))
ed5.present()
app.processEvents()
strip = ed5.tool_strip
first = strip.order()
check(first[0] == MOVE and first[-1] == "crop", "стандартный порядок инструментов")
target_x = strip.buttons()[1].geometry().center().x() - 5     # между 1-й и 2-й кнопкой
strip.move_tool(NUMBER, strip.index_at(target_x))
check(strip.order()[:3] == [MOVE, NUMBER, ARROW], f"номер перенесён ко второй позиции: {strip.order()[:4]}")
check(Ctx.config["tool_order"] == strip.order(), "порядок записан в настройки")
ed6 = EditorWindow(img, Ctx(), QPoint(0, 0))
check(ed6.tool_strip.order() == strip.order(), "новое окно открывается с тем же порядком")
QTest.mouseClick(ed6.tool_buttons[NUMBER], Qt.MouseButton.LeftButton)
check(ed6.canvas.tool == NUMBER, "клик по переставленной кнопке выбирает инструмент")
strip.set_order([t for t, _g, _tip, _k in TOOLS_LIST])
check(strip.order() == first and Ctx.config["tool_order"] == first, "возврат стандартного порядка")

# --- Повтор прошлой области в режиме выделения -------------------------------
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QPixmap
from clipshot.selector import RegionSelector


def selector(last):
    desk = QPixmap(800, 500)
    desk.fill(QColor("#8899aa"))
    res = {}
    sel = RegionSelector(desk, QRect(0, 0, 800, 500), last_rect=last)
    sel.finished.connect(lambda pm, r: res.update(rect=r))
    sel.show()
    app.processEvents()
    return sel, res


def sdrag(w, a, b):
    QTest.mousePress(w, Qt.MouseButton.LeftButton, pos=QPoint(*a))
    for k in range(1, 5):
        x, y = a[0] + (b[0] - a[0]) * k // 4, a[1] + (b[1] - a[1]) * k // 4
        QApplication.sendEvent(w, QMouseEvent(QEvent.Type.MouseMove, QPointF(x, y), w.mapToGlobal(QPointF(x, y)),
                                              Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                                              Qt.KeyboardModifier.NoModifier))
    QTest.mouseRelease(w, Qt.MouseButton.LeftButton, pos=QPoint(*b))


last = QRect(100, 100, 200, 150)
w, res = selector(last)
QTest.keyClick(w, Qt.Key.Key_Return)
check(res.get("rect") == last, "Enter снимает прошлую область")
w, res = selector(last)
QTest.mouseClick(w, Qt.MouseButton.LeftButton, pos=QPoint(150, 150))
check(res.get("rect") == last, "клик внутри прошлой области снимает её")
w, res = selector(last)
sdrag(w, (150, 150), (250, 190))
check("rect" not in res and w.kept == QRect(200, 140, 200, 150), "перетаскивание внутри сдвигает область")
QTest.keyClick(w, Qt.Key.Key_Return)
check(res.get("rect") == QRect(200, 140, 200, 150), "Enter снимает сдвинутую область")
w, res = selector(last)
from PyQt6.QtCore import Qt as _Qt
check(w._cursor_for(QPoint(300, 175)) == _Qt.CursorShape.SizeHorCursor, "курсор ↔ на правой стороне рамки")
check(w._cursor_for(QPoint(200, 250)) == _Qt.CursorShape.SizeVerCursor, "курсор ↕ на нижней стороне")
check(w._cursor_for(QPoint(100, 100)) == _Qt.CursorShape.SizeFDiagCursor, "диагональный курсор на углу")
check(w._cursor_for(QPoint(200, 175)) == _Qt.CursorShape.SizeAllCursor, "курсор перемещения внутри")
sdrag(w, (300, 250), (420, 330))            # тянем правый нижний угол
check("rect" not in res and w.kept == QRect(100, 100, 320, 230), f"угол меняет размер: {w.kept}")
sdrag(w, (100, 200), (60, 200))             # тянем левую сторону
check(w.kept == QRect(60, 100, 360, 230), f"сторона меняет размер: {w.kept}")
QTest.keyClick(w, Qt.Key.Key_Return)
check(res.get("rect") == QRect(60, 100, 360, 230), "Enter снимает область изменённого размера")
w, res = selector(last)
sdrag(w, (650, 40), (800, 160))   # в свободном месте (не на панели кнопок)
check(res.get("rect") == QRect(650, 40, 150, 120), "выделение снаружи — новая область")

# --- Панель действий под прошлой областью --------------------------------------
for key in ("edit", "copy", "save"):  # «record» проверяется отдельно
    w, res = selector(last)
    rect = next(r for k, _t, _s, r in w._bar_layout()[0] if k == key)
    QTest.mouseClick(w, Qt.MouseButton.LeftButton, pos=rect.center())
    check(res.get("rect") == last and w.action == key, f"кнопка «{key}» под рамкой снимает область")
w, res = selector(last)
rect = next(r for k, _t, _s, r in w._bar_layout()[0] if k == "record")
QTest.mouseClick(w, Qt.MouseButton.LeftButton, pos=rect.center())
check(w.action == "record" and "rect" in res and res["rect"].isNull(),
      "«Запись видео»: окно выделения закрывается без снимка, дальше открывается запись системы")
w, res = selector(last)
rect = next(r for k, _t, _s, r in w._bar_layout()[0] if k == "manual")
QTest.mouseClick(w, Qt.MouseButton.LeftButton, pos=rect.center())
check(w.kept is None and "rect" not in res and not w._bar_layout()[0], "«Выделить вручную»: рамка и панель исчезли, окно открыто")
sdrag(w, (150, 150), (330, 260))
check(res.get("rect") == QRect(150, 150, 180, 110), "после «Выделить вручную» область выделяется мышью")
w, res = selector(last)
QTest.keyClick(w, Qt.Key.Key_Delete)
check(w.kept is None and "rect" not in res, "Delete убирает прошлую рамку")
w, res = selector(last)
buttons, bar, hint = w._bar_layout()
check(bar.top() > last.top() + last.height(), "панель под рамкой и не закрывает её")
check(not bar.intersects(last), "панель не пересекает снимаемую область")
w, res = selector(last)
QTest.keyClick(w, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
check(res.get("rect") == last and w.action == "copy", "Ctrl+C: скопировать и закрыть")
w, res = selector(last)
QTest.keyClick(w, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
check(res.get("rect") == last and w.action == "copy", "Ctrl+Enter: скопировать и закрыть, как в редакторе")
w, res = selector(last)
buttons, bar, hint = w._bar_layout()
copy_rect = next(r for k, _t, _s, r in buttons if k == "copy")
check(buttons[-1][0] == "copy" and copy_rect.right() == max(r.right() for *_x, r in buttons),
      "«Скопировать и закрыть» последняя и у правого края панели")
w, res = selector(QRect(100, 380, 200, 100))
check(not w._bar_layout()[1].intersects(QRect(100, 380, 200, 100)), "у нижнего края панель уходит наверх")

# --- Весь экран: рамка по краю, надпись и кнопки в центре ----------------------
def full_selector():
    desk = QPixmap(800, 500)
    desk.fill(QColor("#8899aa"))
    res = {}
    sel = RegionSelector(desk, QRect(0, 0, 800, 500), full_screen=True)
    sel.finished.connect(lambda pm, r: res.update(rect=r, pm=pm))
    sel.show()
    app.processEvents()
    return sel, res


w, res = full_selector()
buttons, bar, hint = w._bar_layout()
screen_geo = QGuiApplication.screenAt(QCursor.pos()).geometry().intersected(QRect(0, 0, 800, 500))
check(w.full_mode and w.kept == QRect(0, 0, 800, 500), "весь экран: выбран весь стол")
check(abs(bar.center().x() - screen_geo.center().x()) <= 2 and abs(bar.center().y() - screen_geo.center().y()) <= 2,
      f"весь экран: панель по центру монитора {bar} {screen_geo}")
check(not w.bar_title_rect.isEmpty() and w.bar_title_rect.bottom() < min(r.top() for *_x, r in buttons),
      "весь экран: надпись «Снимок всего экрана» над кнопками")
img = w.grab().toImage()
edge = QColor(img.pixel(3, 250))
check(edge.blue() > 200 and edge.red() < 60, f"весь экран: толстая синяя рамка по краю {edge.name()}")
check(w._edge_at(QPoint(0, 250)) is None, "весь экран: края не тянутся")
QTest.keyClick(w, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
check(res.get("rect") == QRect(0, 0, 800, 500) and w.action == "copy", "весь экран: Ctrl+Enter копирует весь экран")
w, res = full_selector()
rect = next(r for k, _t, _s, r in w._bar_layout()[0] if k == "edit")
QTest.mouseClick(w, Qt.MouseButton.LeftButton, pos=rect.center())
check(res.get("rect") == QRect(0, 0, 800, 500) and w.action == "edit", "весь экран: «Редактировать»")
w, res = full_selector()
sdrag(w, (20, 20), (200, 150))
check(res.get("rect") == QRect(20, 20, 180, 130) and not w.full_mode, "весь экран: мышью выделяется обычная область")
w, res = full_selector()
QTest.keyClick(w, Qt.Key.Key_Escape)
check("rect" in res and res["rect"].isNull(), "весь экран: Esc отменяет")
w, res = selector(last)
keys = [k for k, *_x in w._bar_layout()[0]]
check(keys[-3:] == ["edit", "manual", "copy"] and "full" in keys,
      f"под областью: «Снимок всего экрана» есть, внизу «Редактировать», «Выделить заново», «Скопировать и закрыть» {keys}")
rect = next(r for k, _t, _s, r in w._bar_layout()[0] if k == "full")
QTest.mouseClick(w, Qt.MouseButton.LeftButton, pos=rect.center())
check("rect" not in res and w.full_mode and w.kept == QRect(0, 0, 800, 500)
      and "full" not in [k for k, *_x in w._bar_layout()[0]],
      "кнопка «Весь экран»: рамка по краю и кнопки в центре, сама кнопка скрыта")
QTest.keyClick(w, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
check(res.get("rect") == QRect(0, 0, 800, 500) and w.action == "copy", "после «Весь экран» Ctrl+Enter копирует весь стол")
w, res = selector(None)
QTest.keyClick(w, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
check(w.full_mode and "rect" not in res, "Ctrl+A: весь экран и при обычном выделении")
for make, name in ((lambda: selector(last), "под областью"), (full_selector, "весь экран")):
    w, res = make()
    buttons, bar, hint = w._bar_layout()
    close = w.bar_close_rect
    check(not close.isEmpty() and all(not close.intersects(r.adjusted(0, 0, -4, -4)) for *_x, r in buttons),
          f"{name}: крестик есть и не закрывает кнопки")
    QTest.mouseClick(w, Qt.MouseButton.LeftButton, pos=close.center())
    check("rect" in res and res["rect"].isNull(), f"{name}: крестик закрывает без снимка")
for make, name in ((lambda: selector(last), "под областью"), (lambda: selector(None), "обычное выделение"),
                   (full_selector, "весь экран")):
    w, res = make()
    corner = w._corner_rects()[0]
    if name == "под областью":
        r = w.kept
        check(r.contains(corner) and r.left() + r.width() - corner.right() <= 20 and corner.top() - r.top() <= 20
              and w._edge_at(corner.center()) is None and w._edge_at(corner.topRight()) is None,
              f"{name}: второй крестик внутри области у правого верхнего угла, стороны можно тянуть")
        w.kept = r.translated(60, 40)
        moved = w._corner_rects()[0]
        check(moved.translated(-60, -40) == corner, f"{name}: крестик ездит вместе с областью")
        w.kept = r
    else:
        check(corner.right() > w.width() - 80 and corner.top() < 80, f"{name}: второй крестик в правом верхнем углу экрана")
    QTest.mouseClick(w, Qt.MouseButton.LeftButton, pos=corner.center())
    check("rect" in res and res["rect"].isNull(), f"{name}: крестик в углу экрана закрывает без снимка")
w, res = selector(None)
QTest.mouseClick(w, Qt.MouseButton.LeftButton, pos=QPoint(400, 250))
check("rect" not in res and w.full_mode and w.kept.contains(QPoint(400, 250)),
      "простой клик без протягивания не снимает сразу, а показывает «Снимок всего экрана» с кнопками")
QTest.keyClick(w, Qt.Key.Key_Return)
check(res.get("rect") is not None and not res["rect"].isNull() and w.action == "edit", "после клика Enter снимает монитор")

# --- Автосохранение каждого снимка в папку --------------------------------------
import tempfile
from types import SimpleNamespace
tmp_dir = tempfile.mkdtemp(prefix="clipsd-autosave-")
fake_app = SimpleNamespace(config=dict(appmod.DEFAULTS, save_dir="~", auto_save_dir=tmp_dir, auto_save=True))
fake_app.snapshot_path = lambda: appmod.Clipshot.snapshot_path(fake_app)
pic = QImage(40, 30, QImage.Format.Format_RGB32)
pic.fill(QColor("#123456"))
first = appmod.Clipshot.autosave(fake_app, pic)
second = appmod.Clipshot.autosave(fake_app, pic)
check(first and second and first != second and os.path.isfile(first) and os.path.isfile(second),
      f"автосохранение: каждый снимок отдельным файлом в папке ({os.path.basename(first)}, {os.path.basename(second)})")
fake_app.config["auto_save"] = False
check(appmod.Clipshot.autosave(fake_app, pic) is None and len(os.listdir(tmp_dir)) == 2, "автосохранение выключено: файл не пишется")
check(os.path.basename(os.path.expanduser(appmod.DEFAULTS["auto_save_dir"])) in ("Скриншоты", "Screenshots"),
      f"автосохранение по умолчанию в «Загрузки/Скриншоты»: {appmod.DEFAULTS['auto_save_dir']}")
from clipshot import editor as editormod
asked = {}
real_dialog = editormod.QFileDialog.getSaveFileName
editormod.QFileDialog.getSaveFileName = staticmethod(lambda parent, title, start, filters, selected="": (asked.update(start=start) or (os.path.join(tmp_dir, "выбрано.png"), "")))
choice = editormod.ask_save_path(None, dict(appmod.DEFAULTS, save_dir=tmp_dir, save_ask=True))
editormod.QFileDialog.getSaveFileName = real_dialog
check(choice == os.path.join(tmp_dir, "выбрано.png") and os.path.dirname(asked.get("start", "")) == tmp_dir,
      "«Сохранить»: спрашивает куда, окно открывается в папке «Загрузки»")

print()
print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено {len(failures)}")
from clipshot.exitutil import quick_exit
quick_exit(1 if failures else 0)
