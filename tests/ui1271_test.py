# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
"""Интерфейс 1.27.1: поля тени сообщаются оконному менеджеру (_GTK_FRAME_EXTENTS), панель окна выделения и полоса
перевода переносятся мышью, курсор «перемещение» над шапкой и свободными местами редактора.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/ui1271_test.py
"""
import json
import os
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
_cfg = os.path.join(tempfile.mkdtemp(prefix="clipsd-ui1271-"), "screen.json")
with open(_cfg, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1600, "height": 1000,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _cfg

from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PyQt6.QtGui import QColor, QImage, QMouseEvent, QPixmap
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
from clipshot import app as appmod, frame_extents, themes
from clipshot.editor import EditorWindow
from clipshot.selector import RegionSelector
failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def settle(n=6):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(15)


class Ctx:
    def __init__(self, **kw):
        self.config = dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True, **kw)
        self.icon = appmod.make_icon()

    def copy_image(self, image):
        self.clipboard = image

    def notify(self, text):
        pass

    def save_config(self):
        pass


def mk(**kw):
    ctx = Ctx(**kw)
    themes.apply_app(app, ctx.config)
    img = QImage(400, 300, QImage.Format.Format_ARGB32)
    img.fill(QColor("#cde"))
    ed = EditorWindow(img, ctx, QPoint(60, 40))
    ed.present()
    settle()
    return ed


def move_to(w, x, y, buttons=Qt.MouseButton.NoButton):
    QApplication.sendEvent(w, QMouseEvent(QEvent.Type.MouseMove, QPointF(x, y), w.mapToGlobal(QPointF(x, y)),
                                          Qt.MouseButton.NoButton, buttons, Qt.KeyboardModifier.NoModifier))


# --- 1. поля для оконного менеджера ---------------------------------------------------------------
check(frame_extents.frame_margins(16, 16, 16, 16) == (16, 16, 16, 16), "поля: масштаб 1, окно с тенью: 16 со всех сторон")
check(frame_extents.frame_margins(16, 16, 16, 16, ratio=2) == (32, 32, 32, 32), "поля умножаются на масштаб экрана (2 → 32)")
check(frame_extents.frame_margins(16, 16, 16, 16, ratio=1.5) == (24, 24, 24, 24), "масштаб 1,5 → 24")
check(frame_extents.frame_margins(16, 16, 16, 16, ratio=2, active=False) == (0, 0, 0, 0), "выключено: нули")

ed = mk()
check(ed.frame_extents_margins() == (16, 16, 16, 16), "редактор со своей шапкой: поля (16, 16, 16, 16)")
ed.showMaximized()
settle()
if not ed.isMaximized():
    ed.isMaximized = lambda: True   # офскрин-платформа может не разворачивать окно
check(ed.frame_extents_margins() == (0, 0, 0, 0), "развёрнутое окно: нулевые поля")
ed.close()
ed = mk(editor_system_title=True)
check(ed.frame_extents_margins() == (0, 0, 0, 0), "системный заголовок: нулевые поля")
ed.close()

# не падает без xcb (офскрин) и без python-xlib
ed = mk()
check(frame_extents.set_frame_extents(ed, 16, 16, 16, 16) is False, "офскрин (не xcb): тихо ничего не делает")
ed._sync_frame_extents()
ed.show()
settle()
ed.showMaximized()
settle()
ed.showNormal()
settle()
check(ed.isVisible(), "showEvent и смена состояния без xcb проходят без ошибок, окно живо")
real_name = frame_extents.QGuiApplication.platformName
frame_extents.QGuiApplication.platformName = staticmethod(lambda: "xcb")
saved_mod = sys.modules.get("Xlib"), sys.modules.get("Xlib.display")
sys.modules["Xlib"] = None   # импорт python-xlib даст ImportError
sys.modules["Xlib.display"] = None
try:
    ok = frame_extents.set_frame_extents(ed, 16, 16, 16, 16)
finally:
    frame_extents.QGuiApplication.platformName = real_name
    for name, mod in zip(("Xlib", "Xlib.display"), saved_mod):
        if mod is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = mod
check(ok is False, "xcb, но python-xlib нет: тихо ничего не делает")
ed.close()


class FakeWin:
    def __init__(self, log):
        self.log = log

    def change_property(self, atom, typ, fmt, data):
        self.log.append((atom, typ, fmt, list(data)))


class FakeDisplay:
    def __init__(self):
        self.log, self.flushed, self.made = [], 0, []

    def create_resource_object(self, kind, wid):
        self.made.append((kind, wid))
        return FakeWin(self.log)

    def intern_atom(self, name):
        return "atom:" + name

    def flush(self):
        self.flushed += 1


fd = FakeDisplay()
frame_extents._write(fd, 77, (16, 16, 16, 16))
check(fd.log == [("atom:_GTK_FRAME_EXTENTS", 6, 32, [16, 16, 16, 16])] and fd.flushed == 1 and fd.made == [("window", 77)],
      "свойство: имя _GTK_FRAME_EXTENTS, тип CARDINAL (6), формат 32, четыре числа, flush")

# --- 6. панель окна выделения переносится ---------------------------------------------------------


def selector(last=QRect(100, 60, 300, 200), full=False):
    desk = QPixmap(1280, 720)   # 1.29: панель шире (868 точек в широком виде), место для переноса нужно
    desk.fill(QColor("#8899aa"))
    res = {}
    sel = RegionSelector(desk, QRect(0, 0, 1280, 720), last_rect=None if full else last, full_screen=full)
    sel.finished.connect(lambda pm, r: res.update(rect=r))
    sel.show()
    settle(3)
    return sel, res


def free_point(sel):
    bar = sel._bar_layout()[1]
    for dy in range(bar.height() - 3, 3, -3):
        for dx in range(6, bar.width() - 6, 7):
            pt = QPoint(bar.left() + dx, bar.top() + dy)
            if sel._bar_free_at(pt):
                return pt
    return None


def drag(w, a, b, steps=6):
    QTest.mousePress(w, Qt.MouseButton.LeftButton, pos=a)
    for k in range(1, steps + 1):
        x, y = a.x() + (b.x() - a.x()) * k // steps, a.y() + (b.y() - a.y()) * k // steps
        move_to(w, x, y, Qt.MouseButton.LeftButton)
    QTest.mouseRelease(w, Qt.MouseButton.LeftButton, pos=b)


sel, res = selector()
bar0 = sel._bar_layout()[1]
pt = free_point(sel)
check(pt is not None, "на панели есть свободное место (не кнопки)")
move_to(sel, pt.x(), pt.y())
check(sel.cursor().shape() == Qt.CursorShape.SizeAllCursor, "курсор над свободным местом панели: перемещение")
btn = sel._bar_layout()[0][0][3].center()
move_to(sel, btn.x(), btn.y())
check(sel.cursor().shape() == Qt.CursorShape.PointingHandCursor, "над кнопкой панели курсор прежний (рука)")
drag(sel, pt, pt + QPoint(120, 150))
bar1 = sel._bar_layout()[1]
check(bar1.topLeft() == bar0.topLeft() + QPoint(120, 150), "сдвиг равен протягиванию (в пределах монитора)")
check(sel.kept == QRect(100, 60, 300, 200) and "rect" not in res, "рамка при переносе панели не двигается, окно не закрылось")
# за границы монитора не уходит
drag(sel, bar1.topLeft() + QPoint(10, 10), QPoint(5000, 5000))
b2 = sel._bar_layout()[1]
check(sel.rect().contains(b2), "панель не уходит за монитор")
sel.close()
settle(2)
sel, res = selector()
check(sel._bar_layout()[1].topLeft() == bar0.topLeft(), "после закрытия и нового открытия панель на обычном месте")
# щелчок без протягивания: по кнопке работает, по свободному месту ничего не делает
pt = free_point(sel)
QTest.mouseClick(sel, Qt.MouseButton.LeftButton, pos=pt)
check("rect" not in res and sel.kept is not None, "щелчок по свободному месту панели без протягивания: ничего не происходит")
drag(sel, pt, pt + QPoint(3, 1), steps=2)
check(sel._bar_layout()[1].topLeft() == bar0.topLeft(), "протягивание меньше порога панель не двигает")
buttons = {k: r for k, _t, _s, r in sel._bar_layout()[0]}
QTest.mouseClick(sel, Qt.MouseButton.LeftButton, pos=buttons["manual"].center())
check(sel.kept is None, "кнопка «Выделить вручную» по-прежнему нажимается")
sel.close()
# после переноса: кнопка под курсором нажимается на новом месте
sel, res = selector()
pt = free_point(sel)
drag(sel, pt, pt + QPoint(-60, 90))
buttons = {k: r for k, _t, _s, r in sel._bar_layout()[0]}
QTest.mouseClick(sel, Qt.MouseButton.LeftButton, pos=buttons["manual"].center())
check(sel.kept is None, "кнопка нажимается и на перенесённой панели")
sel.close()
# перенос рамки не закрывающей панели: панель остаётся; закрывающей: возвращается
sel, res = selector()
pt = free_point(sel)
drag(sel, pt, pt + QPoint(0, 120))
moved = sel._bar_layout()[1].topLeft()
drag(sel, QPoint(250, 120), QPoint(260, 100))   # рамку сдвинули чуть вверх: панель не закрывается
check(sel._bar_layout()[1].topLeft() == moved and sel.bar_pos is not None, "рамку сдвинули, панель не мешает: остаётся там, куда утащили")
sel.close()
# «весь экран»
sel, res = selector(full=True)
pt = free_point(sel)
check(pt is not None, "режим «весь экран»: есть свободное место панели")
b0 = sel._bar_layout()[1].topLeft()
drag(sel, pt, pt + QPoint(30, 80))
check(sel._bar_layout()[1].topLeft() == b0 + QPoint(30, 80), "режим «весь экран»: панель переносится")
sel.close()

# панель в режиме перевода (1.29: вместо полосы внизу та же панель, с подсвеченной плиткой перевода)
sel, res = selector()
sel.enter_translate()
settle(2)
b0 = sel._bar_layout()[1]
fp = free_point(sel)
check(fp is not None and sel._bar_free_at(fp), "панель режима перевода: свободное место найдено")
move_to(sel, fp.x(), fp.y())
check(sel.cursor().shape() == Qt.CursorShape.SizeAllCursor, "панель режима перевода: курсор «перемещение»")
drag(sel, fp, fp + QPoint(0, -150))
b1 = sel._bar_layout()[1]
check(abs(b1.top() - (b0.top() - 150)) < 1 and sel.translate_mode, "панель режима перевода переносится мышью")
sel.close()

# ручки рамки важнее свободного места панели: нижние ручки заходят под панель (панель на 6 px ниже рамки)
last = QRect(100, 60, 300, 200)
for name, (hx, hy), want_edge in (("нижняя левая", (100, 260), "bl"), ("нижняя правая", (400, 260), "br")):
    sel, res = selector(last)
    bar = sel._bar_layout()[1]
    probe = QPoint(hx, hy + 9)   # нижняя половина ручки: ниже угла рамки, внутри панели, если она там стоит
    in_bar = bar.contains(probe)
    check(in_bar and sel._edge_at(probe) == want_edge,
          f"{name} ручка: точка в нижней половине ручки лежит под панелью и всё равно ручка ({want_edge})")
    check(not sel._bar_free_at(probe), f"{name} ручка: это не свободное место панели")
    move_to(sel, probe.x(), probe.y())
    check(sel.cursor().shape() == Qt.CursorShape.SizeBDiagCursor if want_edge == "bl" else sel.cursor().shape() == Qt.CursorShape.SizeFDiagCursor,
          f"{name} ручка: курсор изменения размера, не «перемещение»")
    pos0 = sel._bar_layout()[1].topLeft()
    drag(sel, probe, probe + QPoint(20, 25))
    check(sel.bar_pos is None and sel.kept != last, f"{name} ручка: нажатие меняет размер рамки, панель не переносится")
    sel.close()
# верхние ручки, когда панель стоит над рамкой (внизу нет места)
desk_last = QRect(100, 520, 300, 160)
sel, res = selector(desk_last)
bar = sel._bar_layout()[1]
check(bar.bottom() < desk_last.top() + 5, "панель стоит над рамкой")
for name, (hx, hy), want_edge in (("верхняя левая", (100, 520), "tl"), ("верхняя правая", (400, 520), "tr")):
    probe = QPoint(hx, hy - 8)
    check(bar.contains(probe) and sel._edge_at(probe) == want_edge and not sel._bar_free_at(probe),
          f"{name} ручка под панелью над рамкой: ручка, не свободное место ({want_edge})")
    drag(sel, probe, probe + QPoint(10, 10))
    check(sel.bar_pos is None, f"{name} ручка: нажатие не переносит панель")
    sel.kept = QRect(desk_last)
sel.close()

# окно «Текст с картинки»: поля для менеджера равны фактическим отступам его карточки
from clipshot import ocr
dlg = ocr.TextResultDialog("пример", "", None)
dlg.open_centered()
settle()
m = dlg.frame_extents_margins()
card_tl = dlg.card.mapTo(dlg, QPoint(0, 0))
check(m == (card_tl.x(), dlg.width() - (card_tl.x() + dlg.card.width()), card_tl.y(),
            dlg.height() - (card_tl.y() + dlg.card.height())) == (14, 18, 10, 18),
      f"«Текст с картинки»: поля {m} равны отступам карточки (14, 18, 10, 18), а не константе ClipDialog")
check(m != tuple(dlg.SHADOW_MARGINS[i] for i in (0, 2, 1, 3)), "это не константа SHADOW_MARGINS обычного окна")
dlg.close()
from clipshot.dialogs import ClipDialog
d2 = ClipDialog(None, "тест")
d2.open_centered()
settle()
m2 = d2.frame_extents_margins()
t2 = d2.card.mapTo(d2, QPoint(0, 0))
check(m2 == (t2.x(), d2.width() - t2.x() - d2.card.width(), t2.y(), d2.height() - t2.y() - d2.card.height()),
      f"обычный ClipDialog: поля {m2} равны отступам карточки")
d2.close()

# окошко перевода
from clipshot import translate_ui
fl = translate_ui.FloatingTranslation(QImage(200, 60, QImage.Format.Format_ARGB32), 1.0, QRect(300, 300, 200, 60), dict(appmod.DEFAULTS))
fm = fl.frame_extents_margins()
check(fm[0] == fm[1] == fm[3] == fl.MARGIN and fm[2] >= 0, f"окошко перевода: поля {fm} по отступам области от края окна")
fl.close()

# развёрнутое окно: курсор «перемещение» над шапкой не показывается
ed = mk()
check(ed.titlebar.cursor().shape() == Qt.CursorShape.SizeAllCursor, "обычное окно: шапка «перемещение»")
ed.isMaximized = lambda: True
ed._set_drag_containers()
check(ed.titlebar.cursor().shape() != Qt.CursorShape.SizeAllCursor and ed.panel.cursor().shape() != Qt.CursorShape.SizeAllCursor,
      "развёрнутое окно: над шапкой и панелями курсор «перемещение» не показывается")
ed.close()

# одно соединение python-xlib на процесс, повторное открытие при ошибке
class Boom(FakeDisplay):
    def flush(self):
        raise OSError("соединение оборвано")


opened = []
frame_extents._state.update(disp=None, atom=None, atom_disp=None)
real_name = frame_extents.QGuiApplication.platformName
frame_extents.QGuiApplication.platformName = staticmethod(lambda: "xcb")
import types
fake_x = types.ModuleType("Xlib")
fake_disp_mod = types.ModuleType("Xlib.display")
queue = [Boom(), FakeDisplay()]


def fake_Display():
    d = queue.pop(0) if queue else FakeDisplay()
    opened.append(d)
    return d


fake_disp_mod.Display = fake_Display
fake_x.display = fake_disp_mod
old = (sys.modules.get("Xlib"), sys.modules.get("Xlib.display"))
sys.modules["Xlib"], sys.modules["Xlib.display"] = fake_x, fake_disp_mod
try:
    ed = mk()
    n0 = len(opened)
    ok1 = frame_extents.set_frame_extents(ed, 16, 16, 16, 16)   # первое соединение рвётся: открывается второе, запись проходит
    n1 = len(opened)
    ok2 = frame_extents.set_frame_extents(ed, 16, 16, 16, 16)
    ok3 = frame_extents.set_frame_extents(ed, 16, 16, 16, 16)
    n2 = len(opened)
finally:
    frame_extents.QGuiApplication.platformName = real_name
    for name, mod in zip(("Xlib", "Xlib.display"), old):
        if mod is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = mod
    frame_extents._state.update(disp=None, atom=None, atom_disp=None)
check(ok1 and ok2 and ok3, "запись проходит; после обрыва соединение открывается заново")
check(len(opened) == 2, f"соединение одно на процесс: одно оборвалось, второе открыто заново и дальше используется (открытий: {len(opened)})")
check(len(opened[1].log) >= 3 and all(e[0] == "atom:_GTK_FRAME_EXTENTS" and e[2] == 32 for e in opened[1].log),
      "на новом соединении записи идут с тем же атомом и форматом 32")
ed.close()

# --- 7. курсоры редактора -------------------------------------------------------------------------
ed = mk()
shell = ed.shell


def deepest(w, pt_in_shell):
    return shell.childAt(pt_in_shell)


tb = ed.titlebar
mid = shell.mapFromGlobal(tb.mapToGlobal(QPoint(tb.width() // 2, tb.height() // 2)))
w_mid = deepest(shell, mid)
check(w_mid is not None and w_mid.cursor().shape() == Qt.CursorShape.SizeAllCursor, "середина шапки: курсор «перемещение»")
for btn_w in (tb.close_button, tb.min_button):
    check(btn_w.cursor().shape() == Qt.CursorShape.ArrowCursor, f"кнопка шапки ({btn_w.toolTip()}): обычная стрелка")
tool = next(iter(ed.tool_buttons.values()))
check(tool.cursor().shape() == Qt.CursorShape.ArrowCursor, "кнопка инструмента: обычная стрелка")
check(ed.panel.cursor().shape() == Qt.CursorShape.SizeAllCursor, "свободное место панели инструментов: «перемещение»")
# край окна: курсор изменения размера; после ухода с края сброшен
c = shell.card()
move_to(shell, int(c.center().x()), int(c.top()))
check(shell.cursor().shape() == Qt.CursorShape.SizeVerCursor, "верхний край окна: курсор изменения размера")
check(w_mid.cursor().shape() == Qt.CursorShape.SizeAllCursor, "шапка при этом сохраняет «перемещение», а не стрелки вверх-вниз")
move_to(shell, int(c.center().x()), int(c.top()) + 3 + 14)
check(shell.cursor().shape() != Qt.CursorShape.SizeVerCursor, "ушли с края внутрь: курсор изменения размера сброшен")
move_to(shell, int(c.center().x()), int(c.top()))
QApplication.sendEvent(shell, QEvent(QEvent.Type.Leave))
check(shell.cursor().shape() == Qt.CursorShape.ArrowCursor, "мышь покинула подложку: курсор изменения размера сброшен")
check(ed.canvas.parent().cursor().shape() != Qt.CursorShape.SizeVerCursor, "поле вокруг снимка не наследует курсор изменения размера")
# зона изменения размера не накрывает шапку
inside_top = QPointF(c.center().x(), c.top() + 10)
check(not shell.edge_at(inside_top), "10 px внутрь от верхнего края (шапка) не зона изменения размера")
check(bool(shell.edge_at(QPointF(c.center().x(), c.top() - 4))), "поле тени у края: зона изменения размера")
ed.close()

print()
print("ИТОГО: проверок", "ok" if not failures else f"провалено {len(failures)}")
from clipshot.exitutil import quick_exit
quick_exit(1 if failures else 0)
