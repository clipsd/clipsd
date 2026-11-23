# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""1.36: «Закрепить поверх окон» (clipshot/zakrepit.py).

1. Окошко: флаги (поверх всех, без рамки), размер = размер снимка, перенос мышью, колесо меняет размер (точка под
   курсором остаётся на месте, пределы), Ctrl+колесо прозрачность (пределы), двойной щелчок и Esc закрывают,
   крестик под мышью закрывает.
2. Меню правой кнопки: копировать, сохранить, открыть в редакторе, прозрачность, закрыть (+ «закрыть все» при нескольких).
3. Несколько закреплённых сразу: у каждого свой размер и прозрачность, закрытие одного другие не трогает, close_all.
4. Wayland: на «родном» Wayland честная подсказка в окошке (не больше HINT_TIMES раз), без Wayland подсказки нет,
   программа не падает.
5. Редактор: кнопка «Закрепить» внизу и F3 закрепляют снимок С ПОМЕТКАМИ, редактор остаётся открытым; учебный редактор
   ничего не закрепляет. Окно выделения: плитка «Закрепить» и F3 заканчивают выделение действием pin; приложение
   закрепляет область на её месте, редактор не открывается.
6. 12 языков: подписи плитки, кнопки, меню и подсказки есть и не пустые, плитка помещается.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/zakrepit_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import json
import os
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
tmp = tempfile.mkdtemp(prefix="clipsd-pin-")
for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[name] = os.path.join(tmp, name)
_screen = os.path.join(tmp, "screen.json")
with open(_screen, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1600, "height": 1000,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _screen

from PyQt6 import sip  # noqa: E402
from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QImage, QMouseEvent, QPixmap, QWheelEvent  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

qapp = QApplication(sys.argv)
qapp.setQuitOnLastWindowClosed(False)
from clipshot import app as appmod, i18n, ocr, otdelno, zakrepit  # noqa: E402
from clipshot.editor import EditorWindow  # noqa: E402
from clipshot.i18n import tr  # noqa: E402
from clipshot.selector import RegionSelector  # noqa: E402
from clipshot.shapes import RECT, Shape  # noqa: E402

failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


class Ctx:
    """Минимальный ctx окошка: настройки, копирование и открытие редактора записываются."""

    def __init__(self):
        self.config = dict(appmod.DEFAULTS, theme_chosen=True, tour_done=True, novoe_enabled=False,
                           save_dir=os.path.join(tmp, "save"), save_ask=False, save_format="png")
        os.makedirs(self.config["save_dir"], exist_ok=True)
        self.copied, self.opened, self.saves = [], [], 0

    def copy_image(self, image, config=None):
        self.copied.append(QImage(image))

    def open_editor(self, image, origin):
        self.opened.append(QImage(image))
        return None

    def autosave(self, image):
        return ""

    def save_config(self):
        self.saves += 1


def pic(w=400, h=300, color="#2a6df4"):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    return img


def wheel(win, delta, mods=Qt.KeyboardModifier.NoModifier, at=None):
    at = at or QPointF(win.width() / 2, win.height() / 2)
    ev = QWheelEvent(at, win.mapToGlobal(at), QPoint(0, 0), QPoint(0, delta), Qt.MouseButton.NoButton, mods,
                     Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(win, ev)


def gone(w):
    """Окошко закрыто (WA_DeleteOnClose: объект может быть уже удалён)."""
    return sip.isdeleted(w) or not w.isVisible()


def mouse(win, kind, local, global_pos, button=Qt.MouseButton.LeftButton, down=True):
    """Событие мыши с настоящими глобальными координатами (QTest даёт местные: при переносе окна они «плывут»)."""
    buttons = button if down else Qt.MouseButton.NoButton
    ev = QMouseEvent(kind, QPointF(local), QPointF(global_pos), button, buttons, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(win, ev)


def safe_close(w):
    if not sip.isdeleted(w):
        w.close()


def settle(ms=40):
    QTest.qWait(ms)


ctx = Ctx()
i18n.set_language("ru")

# --- 1. окошко ---------------------------------------------------------------------------------------------------
zakrepit.close_all()
win = zakrepit.pin(ctx, pic(), QPoint(200, 150))
settle()
flags = win.windowFlags()
check(bool(flags & Qt.WindowType.WindowStaysOnTopHint), "поверх всех окон: WindowStaysOnTopHint")
check(bool(flags & Qt.WindowType.FramelessWindowHint), "без рамки: FramelessWindowHint")
check(win.isVisible() and win in zakrepit.OPEN and len(zakrepit.OPEN) == 1, "окошко показано и записано в список закреплённых")
check(win.size().width() == 400 and win.size().height() == 300 and win.pos() == QPoint(200, 150),
      f"размер снимка 400x300 на заданном месте: {win.size()} {win.pos()}")
check(win.opacity == 1.0 and win.scale == 1.0, "сначала без прозрачности и в натуральную величину")
check(win.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating), "закрепление не отнимает ввод у другой программы")

# перенос мышью (offscreen: система переносить не умеет, окошко двигает само). Глобальные координаты настоящие
start = win.pos()
g0 = QPoint(300, 250)
mouse(win, QEvent.Type.MouseButtonPress, QPoint(100, 100), g0)
mouse(win, QEvent.Type.MouseMove, QPoint(100, 100), g0 + QPoint(60, 40))
mouse(win, QEvent.Type.MouseMove, QPoint(100, 100), g0 + QPoint(90, 70))
mouse(win, QEvent.Type.MouseButtonRelease, QPoint(100, 100), g0 + QPoint(90, 70), down=False)
settle()
check(win.pos() == start + QPoint(90, 70), f"перенос мышью на (90, 70): {start} -> {win.pos()}")
moved_to = win.pos()
mouse(win, QEvent.Type.MouseButtonPress, QPoint(50, 50), QPoint(400, 400))
mouse(win, QEvent.Type.MouseMove, QPoint(50, 50), QPoint(401, 400))
mouse(win, QEvent.Type.MouseButtonRelease, QPoint(50, 50), QPoint(401, 400), down=False)
check(win.pos() == moved_to, "щелчок без заметного движения окошко не двигает")

# колесо: размер. Точка под курсором остаётся на месте
anchor = QPointF(100, 75)
before = win.mapToGlobal(anchor.toPoint())
wheel(win, 120, at=anchor)
settle()
check(abs(win.scale - 1.1) < 1e-6 and win.width() == 440 and win.height() == 330, f"колесо вверх: +10 %: {win.scale} {win.size()}")
frac = (before - win.pos())
check(abs(frac.x() / win.width() - 100 / 400) < 0.02 and abs(frac.y() / win.height() - 75 / 300) < 0.02,
      "точка под курсором при изменении размера остаётся под курсором")
for _ in range(80):
    wheel(win, -120)
check(win.scale >= zakrepit.SCALE_MIN and min(win.width(), win.height()) >= zakrepit.MIN_SIDE - 1,
      f"меньше предела не сжимается: {win.scale} {win.size()}")
for _ in range(120):
    wheel(win, 120)
check(abs(win.scale - zakrepit.SCALE_MAX) < 1e-6 and win.width() == 3200, f"больше предела не растёт: {win.scale} {win.size()}")
win.set_scale(1.0)
check(win.size().width() == 400, "set_scale(1) возвращает натуральный размер")

# Ctrl+колесо: прозрачность
wheel(win, -120, Qt.KeyboardModifier.ControlModifier)
check(abs(win.opacity - 0.9) < 1e-6 and win.scale == 1.0, f"Ctrl+колесо вниз: прозрачнее на 0,1, размер прежний: {win.opacity}")
for _ in range(30):
    wheel(win, -120, Qt.KeyboardModifier.ControlModifier)
check(abs(win.opacity - zakrepit.OPACITY_MIN) < 1e-6, f"прозрачность не ниже {zakrepit.OPACITY_MIN}: {win.opacity}")
for _ in range(30):
    wheel(win, 120, Qt.KeyboardModifier.ControlModifier)
check(win.opacity == 1.0, "прозрачность не выше 1")

# отрисовка: картинка видна, прозрачность меняет цвет, подсказка рисуется
win.set_opacity(1.0)
shot = QPixmap(win.size())
shot.fill(Qt.GlobalColor.transparent)
win.render(shot)
c1 = shot.toImage().pixelColor(200, 150)
check(abs(c1.blue() - 0xf4) < 3 and c1.alpha() == 255, f"рисуется снимок: {c1.name()}")
win.set_opacity(0.5)
shot2 = QPixmap(win.size())
shot2.fill(Qt.GlobalColor.transparent)
win.render(shot2)
c2 = shot2.toImage().pixelColor(200, 150)
check(0.4 < c2.alphaF() < 0.6, f"прозрачность 50 %: альфа {c2.alphaF():.2f}")
win.set_opacity(1.0)

# крестик под мышью
check(not win._hover, "мыши над окошком нет: крестика нет")
win._hover = True
cross = win.cross_rect().center().toPoint()
QTest.mousePress(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, cross)
QTest.mouseRelease(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, cross)
settle()
check(win not in zakrepit.OPEN and gone(win), "крестик закрывает")

# двойной щелчок и Esc
w2 = zakrepit.pin(ctx, pic(200, 120))
settle()
QTest.mouseDClick(w2, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(60, 60))
settle()
check(w2 not in zakrepit.OPEN and gone(w2), "двойной щелчок закрывает")
w3 = zakrepit.pin(ctx, pic(200, 120))
settle()
QTest.keyClick(w3, Qt.Key.Key_Escape)
settle()
check(w3 not in zakrepit.OPEN and gone(w3), "Esc закрывает")
check(zakrepit.pin(ctx, QImage()) is None and zakrepit.pin(ctx, None) is None and not zakrepit.OPEN, "пустая картинка: ничего не закрепляется")

# картинка с масштабом экрана: размер окошка в точках
hd = pic(600, 400)
hd.setDevicePixelRatio(2.0)
w4 = zakrepit.pin(ctx, hd)
check(w4.size().width() == 300 and w4.size().height() == 200, f"снимок 600x400 с масштабом 2 даёт окошко 300x200: {w4.size()}")
w4.close()

# --- 2. меню ----------------------------------------------------------------------------------------------------
m = zakrepit.pin(ctx, pic(300, 200, "#d60808"), QPoint(50, 50))
settle()
menu = m.build_menu()
texts = [a.text().split("\t")[0] for a in menu.actions() if not a.isSeparator()]
check(texts == [tr("zakrepit.menu_copy"), tr("zakrepit.menu_save"), tr("zakrepit.menu_editor"),
                tr("zakrepit.menu_opacity"), tr("zakrepit.menu_close")], f"меню: {texts}")
acts = {a.text().split("\t")[0]: a for a in menu.actions() if not a.isSeparator()}
acts[tr("zakrepit.menu_copy")].trigger()
check(len(ctx.copied) == 1 and ctx.copied[0].pixelColor(5, 5).name() == "#d60808" and m.flash_text == tr("zakrepit.copied"),
      "«Копировать»: картинка ушла в буфер, в окошке «Скопировано»")
import clipshot.editor as editormod  # noqa: E402
orig_ask = editormod.ask_save_path
target = os.path.join(tmp, "save", "pin.png")
editormod.ask_save_path = lambda parent, cfg: target
acts[tr("zakrepit.menu_save")].trigger()
saved = QImage(target)
check(os.path.exists(target) and saved.width() == 300 and saved.pixelColor(5, 5).name() == "#d60808", "«Сохранить…»: файл записан")
check(m.flash_text == tr("zakrepit.saved", name="pin.png"), "после сохранения в окошке «Сохранено: pin.png»")
editormod.ask_save_path = lambda parent, cfg: None
check(m.save_image() is None, "отмена окна выбора файла: ничего не записано, окошко живо")
editormod.ask_save_path = orig_ask
acts[tr("zakrepit.menu_editor")].trigger()
check(len(ctx.opened) == 1 and ctx.opened[0].width() == 300 and m in zakrepit.OPEN, "«Открыть в редакторе»: открыт новый снимок, закрепление осталось")
sub = next(a for a in menu.actions() if a.text() == tr("zakrepit.menu_opacity")).menu()
values = [a.text() for a in sub.actions()]
check(values == ["100 %", "75 %", "50 %", "25 %"] and sub.actions()[0].isChecked(), f"прозрачность в меню: {values}, отмечена текущая")
sub.actions()[2].trigger()
check(m.opacity == 0.5, "«Прозрачность 50 %» применяется")
menu2 = m.build_menu()
sub2 = next(a for a in menu2.actions() if a.text() == tr("zakrepit.menu_opacity")).menu()
check(sub2.actions()[2].isChecked() and not sub2.actions()[0].isChecked(), "в новом меню отмечена прозрачность 50 %")
check(all(a.text() != tr("zakrepit.menu_close_all") for a in menu2.actions()), "одно закреплённое: пункта «Закрыть все» нет")
next(a for a in menu2.actions() if a.text().startswith(tr("zakrepit.menu_close"))).trigger()
settle()
check(m not in zakrepit.OPEN, "«Закрыть» из меню")

# --- 3. несколько сразу --------------------------------------------------------------------------------------------
ws = [zakrepit.pin(ctx, pic(200 + 40 * i, 150, c), QPoint(300, 300)) for i, c in enumerate(("#d60808", "#2db400", "#1e78ff"))]
settle()
check(len(zakrepit.OPEN) == 3 and all(w.isVisible() for w in ws), "три закреплённых сразу")
check(len({(w.pos().x(), w.pos().y()) for w in ws}) == 3, f"на одно место не ложатся: {[w.pos() for w in ws]}")
wheel(ws[0], 120)
wheel(ws[1], -120, Qt.KeyboardModifier.ControlModifier)
check(ws[0].scale > 1 and ws[1].scale == 1 and ws[1].opacity < 1 and ws[2].scale == 1 and ws[2].opacity == 1.0,
      "у каждого свой размер и прозрачность")
menu3 = ws[0].build_menu()
check(any(a.text() == tr("zakrepit.menu_close_all") for a in menu3.actions()), "несколько закреплённых: есть «Закрыть все закреплённые»")
ws[1].close()
settle()
check(len(zakrepit.OPEN) == 2 and ws[0] in zakrepit.OPEN and ws[2] in zakrepit.OPEN, "закрытие одного другие не трогает")
zakrepit.close_all()
settle()
check(not zakrepit.OPEN and all(gone(w) for w in ws), "close_all закрывает все")

# --- 4. Wayland ----------------------------------------------------------------------------------------------------
check(zakrepit.native_wayland() is False, "в тесте (offscreen) это не родной Wayland")
c4 = Ctx()
p0 = zakrepit.pin(c4, pic())
check(p0.hint_text == "" and c4.config.get("zakrepit_hint_shown") is None, "не Wayland: подсказки про «поверх всех» нет")
p0.close()
real = zakrepit.native_wayland
zakrepit.native_wayland = lambda: True
try:
    hints = []
    for i in range(zakrepit.HINT_TIMES + 2):
        p = zakrepit.pin(c4, pic())
        hints.append(p.hint_text)
        p.close()
    check(hints[0] == tr("zakrepit.wayland_hint") and all(hints[:zakrepit.HINT_TIMES]) and not any(hints[zakrepit.HINT_TIMES:]),
          f"родной Wayland: честная подсказка первые {zakrepit.HINT_TIMES} раза, потом нет")
    check(c4.config.get("zakrepit_hint_shown") == zakrepit.HINT_TIMES and c4.saves >= zakrepit.HINT_TIMES, "число показов запомнено в настройках")
    p = zakrepit.pin(Ctx(), pic(120, 80))   # узкое окошко: подсказка рисуется внутри окошка без падения
    shot = QPixmap(p.size())
    p.render(shot)
    check(p.hint_text != "" and not shot.isNull(), "подсказка в маленьком окошке рисуется без ошибок")
    p._clear_notes()
    check(p.hint_text == "", "подсказка гаснет")
    p.close()
finally:
    zakrepit.native_wayland = real

# --- 5. редактор и окно выделения ------------------------------------------------------------------------------------
a = appmod.Clipshot(qapp)
a.save_config = lambda: None
notes = []
a.notify = lambda t, *_x: notes.append(t)
a.config.update(theme_chosen=True, tour_done=True, novoe_enabled=False, auto_save=False, save_dir=os.path.join(tmp, "save"))
ed = a.open_editor(pic(500, 300, "#ffffff"), None)
settle(120)
check(ed.pin_button is not None and ed.pin_button.accessibleName() == tr("zakrepit.button") and ed.pin_button.toolTip() == tr("zakrepit.tip"),
      "в редакторе кнопка «Закрепить» с подсказкой")
ed.resize(1300, ed.height())
settle(150)
check(not ed._bottom_compact and ed.pin_button.isVisible() and ed.pin_button.accessibleName() == tr("zakrepit.button"),
      "в широком окне внизу видна кнопка «Закрепить» (значок, подпись в подсказке)")
ed.resize(ed._need_bottom[0] + ed._rim()[0] + 4, ed.height())   # подписи ещё помещаются, а места под значок уже нет
settle(150)
check(not ed._bottom_compact and not ed.pin_button.isVisible(), "места мало: «Закрепить» уходит первой, подписи «Сохранить» и «Скопировать» остаются")
ed.resize(ed.minimumWidth(), ed.height())
settle(150)
check(ed._bottom_compact and not ed.pin_button.isVisible() and ed.min_content_width() <= ed.width()
      and ed.min_content_width() == max(ed._need_row1[-1], ed._need_row2[-1], ed._need_bottom[1], ed._title_need()[1] if ed._title_need() else 0),
      "в самом узком окне кнопки внизу нет, самая узкая ширина окна прежняя")
menu_all = ed.build_all_tools_menu()
check(ed.all_tools_pin in menu_all.actions() and ed.all_tools_pin.text() == tr("zakrepit.menu_pin"),
      "«Закрепить» есть в меню «Все инструменты»")
n_menu = len(zakrepit.OPEN)
ed.all_tools_pin.trigger()
settle()
check(len(zakrepit.OPEN) == n_menu + 1, "пункт меню «Все инструменты» закрепляет")
zakrepit.close_all()
ed.resize(1300, ed.height())
settle(150)
shape = Shape(RECT, QColor("#d60808"), 4, QPointF(10, 10))
shape.points[-1] = QPointF(150, 100)
ed.canvas.shapes.append(shape)
ed.canvas.modified = True
n0 = len(zakrepit.OPEN)
ed.pin_button.click()
settle()
check(len(zakrepit.OPEN) == n0 + 1, "кнопка «Закрепить» закрепила снимок")
pw = zakrepit.OPEN[-1]
check(pw.image.width() == 500 and pw.image.pixelColor(10, 10) == QColor("#d60808"), "закреплён снимок вместе с пометками")
check(ed.isVisible() and not ed.exported, "редактор остался открытым, снимок не считается скопированным")
pw.close()
settle()
ed.activateWindow()
settle()
ed.canvas.setFocus()
QTest.keyClick(ed, Qt.Key.Key_F3)
settle()
check(len(zakrepit.OPEN) == n0 + 1, "F3 в редакторе закрепляет")
zakrepit.close_all()
ed.ctx.config["save_dir"] = os.path.join(tmp, "save")
ed.training = True   # окно «Ознакомление»: учебный снимок ничего не закрепляет
ed.pin_image()
check(not zakrepit.OPEN, "учебный редактор: ничего не закрепляется")
ed.training = False
ed.canvas.modified = False
ed.close()
settle()

# окно выделения
desk = QPixmap(1200, 700)
desk.fill(QColor("#4a78b0"))
sel = RegionSelector(desk, QRect(0, 0, 1200, 700), last_rect=QRect(300, 200, 400, 250))
sel.resize(1200, 700)
sel.show()
settle(80)
keys = [k for k, *_ in sel._bar_buttons()]
check("pin" in keys and "pin" in RegionSelector.BAR_TOP and keys.index("pin") == keys.index("phone") + 1, f"в панели выделения плитка «Закрепить»: {keys}")
buttons, bar, hint = sel._bar_layout()
tile = {k: (t, s, r) for k, t, s, r in buttons}["pin"]
check(tile[0] == tr("zakrepit.tile_title") and tile[1] == "F3" and not tile[2].isEmpty() and bar.contains(tile[2]),
      f"плитка «Закрепить» (F3) лежит внутри панели: {tile[0]} {tile[1]} {tile[2]}")
done = []
sel.finished.connect(lambda pm, r: done.append((pm, r, sel.action)))
QTest.keyClick(sel, Qt.Key.Key_F3)
settle()
check(len(done) == 1 and done[0][2] == "pin" and done[0][0] is not None and done[0][0].width() > 0,
      "F3 в окне выделения: действие pin, снимок области передан")
check(done and done[0][1].topLeft() == QPoint(300, 200), f"область на своём месте: {done[0][1] if done else None}")

# узкий экран (800 px): плитки «Закрепить» нет (подписи остальных важнее), F3 работает
desk8 = QPixmap(800, 600)
desk8.fill(QColor("#4a78b0"))
sel8 = RegionSelector(desk8, QRect(0, 0, 800, 600), last_rect=QRect(250, 60, 300, 220))
sel8.resize(800, 600)
sel8.show()
settle(60)
keys8 = [k for k, *_x in sel8._bar_layout()[0]]
check("pin" not in keys8 and sel8.bar_level["name"] == "wide", f"экран 800 px: плитки «Закрепить» нет, панель крупная: {sel8.bar_level['name']}")
done8 = []
sel8.finished.connect(lambda pm, r: done8.append(sel8.action))
QTest.keyClick(sel8, Qt.Key.Key_F3)
settle()
check(done8 == ["pin"], "экран 800 px: F3 всё равно закрепляет")
safe_close(sel8)

# приложение закрепляет область на её месте и не открывает редактор
n_ed = len(a.editors)
a.selector = sel
a.insert_target = None
a._region_done(done[0][0], done[0][1])
settle()
check(len(zakrepit.OPEN) == 1 and zakrepit.OPEN[0].pos() == QPoint(300, 200) and zakrepit.OPEN[0].size() == done[0][0].toImage().size() / (done[0][0].devicePixelRatio() or 1),
      f"приложение закрепило область на месте {zakrepit.OPEN[0].pos() if zakrepit.OPEN else None}")
check(len(a.editors) == n_ed, "редактор при «Закрепить» не открывается")
zakrepit.close_all()
safe_close(sel)

# плитка мышью
sel2 = RegionSelector(desk, QRect(0, 0, 1200, 700), last_rect=QRect(300, 200, 400, 250))
sel2.resize(1200, 700)
sel2.show()
settle(80)
done2 = []
sel2.finished.connect(lambda pm, r: done2.append(sel2.action))
buttons2, _b, _h = sel2._bar_layout()
r = {k: rr for k, _t, _s, rr in buttons2}["pin"]
QTest.mouseClick(sel2, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, r.center())
settle()
check(done2 == ["pin"], f"щелчок по плитке «Закрепить»: {done2}")
safe_close(sel2)

# --- 6. 12 языков -------------------------------------------------------------------------------------------------------
keys6 = ["zakrepit.button", "zakrepit.tip", "zakrepit.tile_title", "zakrepit.tile_sub", "zakrepit.menu_copy", "zakrepit.menu_save",
         "zakrepit.menu_editor", "zakrepit.menu_pin", "zakrepit.menu_opacity", "zakrepit.menu_close", "zakrepit.menu_close_all", "zakrepit.copied",
         "zakrepit.wayland_hint", "zakrepit.window_name", "zakrepit.pinned_toast", "zakrepit.training"]
for lang in i18n.LANGUAGES:
    i18n.set_language(lang)
    vals = [tr(k) for k in keys6]
    check(all(v and v != k and "{" not in v for v, k in zip(vals, keys6)), f"{lang}: строки есть")
    check(tr("zakrepit.saved", name="a.png").endswith("a.png") and "{" not in tr("zakrepit.saved", name="a.png"), f"{lang}: «Сохранено: a.png»")
    pw = zakrepit.pin(Ctx(), pic(160, 100))
    menu = pw.build_menu()
    check(len(menu.actions()) >= 5 and all(a.text() for a in menu.actions() if not a.isSeparator()), f"{lang}: меню окошка")
    pw.close()
    sel3 = RegionSelector(desk, QRect(0, 0, 1200, 700), last_rect=QRect(300, 200, 400, 250))
    sel3.resize(1200, 700)
    sel3.show()
    settle(30)
    btns, bar3, _h = sel3._bar_layout()
    got = {k: (t, rr) for k, t, _s, rr in btns}
    top = [rr for k, (t, rr) in got.items() if k in RegionSelector.BAR_TOP]
    check(got["pin"][0] == tr("zakrepit.tile_title") and all(bar3.contains(rr) for rr in top)
          and all(not top[i].intersects(top[j]) for i in range(len(top)) for j in range(i + 1, len(top))),
          f"{lang}: плитка «Закрепить» помещается, плитки не налезают друг на друга")
    sel3.close()
i18n.set_language("ru")
settle()

print("\nИТОГ: " + ("всё хорошо" if not failures else f"{len(failures)} ошибок: {failures}"))
sys.exit(1 if failures else 0)
