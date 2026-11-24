# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Форма снимка в окне выделения (1.36.3). Слова владельца 24.11.2026: «эту форму я хочу задавать в момент ещё
первого экрана: сначала она прямоугольная, но я хочу круглую или скруглённую сделать».

1. Плитка «Форма снимка» в верхнем ряду панели (после «Закрепить»), внутри панели, плитки не налезают; щелчок включает
   последнюю форму (form_last) и выключает её; стрелка и правый щелчок открывают меню форм (те же пункты, что в
   редакторе), выбор запоминается; клавиша F; новое окно выделения снова прямоугольное.
2. Контур в рамке: за формой затемнение, внутри снимок как был; круг вписан по центру.
3. «Скопировать и закрыть», «Сохранить» (из окна, с окном выбора файла): картинка с формой (прозрачные углы, круг
   обрезан до квадрата). «Закрепить» без формы.
4. «Редактировать»: редактор открывается с формой во весь снимок, без шага отмены и без «изменено».
5. Подсказки на 12 языках, плитка помещается.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/forma_vydelenie_test.py
"""
import tmpclean  # noqa: F401
import json
import os
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
tmp = tempfile.mkdtemp(prefix="clipsd-forma-sel-")
for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[name] = os.path.join(tmp, name)
_screen = os.path.join(tmp, "screen.json")
with open(_screen, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1600, "height": 1000,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _screen

from PyQt6 import sip  # noqa: E402
from PyQt6.QtCore import QPoint, QRect, Qt, QTimer  # noqa: E402
from PyQt6.QtGui import QColor, QImage, QPainter, QPixmap  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

qapp = QApplication(sys.argv)
qapp.setQuitOnLastWindowClosed(False)
from clipshot import app as appmod, forma, i18n  # noqa: E402
from clipshot.i18n import tr  # noqa: E402
from clipshot.selector import RegionSelector  # noqa: E402

failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


def settle(ms=40):
    QTest.qWait(ms)


def safe_close(w):
    if not sip.isdeleted(w):
        w.close()


class Ctx:
    """Настройки программы для окна выделения (form_last, form_radius)."""

    def __init__(self, **cfg):
        self.config = dict(appmod.DEFAULTS, theme_chosen=True, tour_done=True, novoe_enabled=False, **cfg)

    def set_language(self, *_a, **_k):
        pass

    def save_config(self):
        pass


def desktop(w=1200, h=700):
    pm = QPixmap(w, h)
    pm.fill(QColor("#4a78b0"))
    p = QPainter(pm)
    p.fillRect(QRect(300, 200, 400, 250), QColor("#e0a030"))   # выделяемая область другого цвета
    p.end()
    return pm


def selector(ctx=None):
    s = RegionSelector(desktop(), QRect(0, 0, 1200, 700), last_rect=QRect(300, 200, 400, 250))
    s.lang_ctx = ctx
    s.resize(1200, 700)
    s.show()
    settle(60)
    return s


def tiles(s):
    return {k: r for k, _t, _sh, r in s._bar_layout()[0]}


def alpha(img, x, y):
    return img.pixelColor(x, y).alpha()


i18n.set_language("ru")
L, R, NOMOD = Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier

# --- 1. плитка, щелчок, меню, клавиша F ----------------------------------------------------------------------------
ctx = Ctx(form_last=forma.CIRCLE)
sel = selector(ctx)
keys = [k for k, *_ in sel._bar_buttons()]
check("form" in keys and keys.index("form") == keys.index("pin") + 1, f"плитка «Форма снимка» после «Закрепить»: {keys}")
buttons, bar, _hint = sel._bar_layout()
t = tiles(sel)
top = [r for k, r in t.items() if k in RegionSelector.BAR_TOP]
check(bar.contains(t["form"]) and t["form"].width() == RegionSelector.BAR_FORM_W
      and all(not top[i].intersects(top[j]) for i in range(len(top)) for j in range(i + 1, len(top))),
      f"плитка формы внутри панели, ширина {t['form'].width()}, плитки не налезают")
check(sel.form.is_rect, "окно выделения начинается с прямоугольника")
body = QPoint(t["form"].left() + 12, t["form"].center().y())
arrow = QPoint(t["form"].right() - 4, t["form"].center().y())
check(sel._button_at(body) == "form" and sel._button_at(arrow) == "form_menu", "значок плитки: включить, стрелка: меню")
QTest.mouseMove(sel, body)
sel.hover_button = sel._button_at(body)
check(sel.form_hint("F") == tr("selector.form_tip_off", name=tr("forma.circle"), hotkey="F"),
      "подсказка: щелчок включит последнюю форму (круг) и клавиша F")
QTest.mouseClick(sel, L, NOMOD, body)
settle()
check(sel.form.code == forma.CIRCLE and not sel._done, "щелчок по плитке: круг (последняя форма), окно открыто")
check(tr("forma.circle") in sel.form_hint("F"), "подсказка называет включённую форму")
QTest.mouseClick(sel, L, NOMOD, body)
settle()
check(sel.form.is_rect, "второй щелчок: снова прямоугольник")
QTest.keyClick(sel, Qt.Key.Key_F)
settle()
check(sel.form.code == forma.CIRCLE, "клавиша F включает форму")
QTest.keyClick(sel, Qt.Key.Key_F)
check(sel.form.is_rect, "F ещё раз: прямоугольник")

seen = {}


def pick_from_menu(code):
    def run():
        menu = getattr(sel, "_form_menu_open", None)
        if menu is None:
            seen["menu"] = None
            return
        acts = [a for a in menu.actions() if a.isCheckable()]
        seen["menu"] = [a.data() for a in acts]
        seen["checked"] = [a.data() for a in acts if a.isChecked()]
        next(a for a in acts if a.data() == code).trigger()
        menu.close()
    QTimer.singleShot(80, run)


pick_from_menu(forma.ROUND_L)
QTest.mouseClick(sel, L, NOMOD, arrow)
settle(150)
check(seen.get("menu") == list(forma.FORMS), f"стрелка: меню с шестью формами, как в редакторе ({seen.get('menu')})")
check(seen.get("checked") == [forma.RECT], "в меню отмечен прямоугольник")
check(sel.form.code == forma.ROUND_L and ctx.config["form_last"] == forma.ROUND_L and not sel._done,
      "из меню: большие скругления, запомнены как последняя форма, окно открыто")
pick_from_menu(forma.OVAL)
QTest.mouseClick(sel, R, NOMOD, body)
settle(150)
check(sel.form.code == forma.OVAL and not sel._done, "правый щелчок по плитке: меню форм, окно не закрылось")
check(seen.get("checked") == [forma.ROUND_L], "меню отмечает текущую форму")

# --- 2. контур в рамке -----------------------------------------------------------------------------------------------
sel.set_form(forma.CIRCLE)
settle()
shot = sel.grab().toImage()
k = shot.devicePixelRatio() or 1.0
center = shot.pixelColor(round(500 * k), round(325 * k))
corner = shot.pixelColor(round(310 * k), round(215 * k))
side = shot.pixelColor(round(320 * k), round(325 * k))     # слева от круга (круг 250 по центру: 375…625)
check(abs(center.red() - 0xe0) < 8 and abs(center.green() - 0xa0) < 8, f"внутри формы снимок как был ({center.name()})")
check(corner.red() < center.red() - 30 and side.red() < center.red() - 30,
      f"за кругом затемнение: угол {corner.name()}, сбоку {side.name()}")
path = forma.path(sel.form, 400, 250)
check(path.boundingRect() == forma.circle_rect(forma.Form(forma.CIRCLE), 400, 250)
      and abs(path.boundingRect().center().x() - 200) < 1e-6, "круг вписан в рамку по центру")
sel.set_form(forma.RECT)
shot = sel.grab().toImage()
check(abs(shot.pixelColor(round(320 * k), round(325 * k)).red() - 0xe0) < 8, "прямоугольник: рамка без затемнения внутри")

# --- 3. копирование, сохранение, закрепление ------------------------------------------------------------------------
sel.set_form(forma.CIRCLE)
done = []
sel.finished.connect(lambda pm, r: done.append((pm, r, sel.action, sel.form.copy())))
QTest.keyClick(sel, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
settle()
check(len(done) == 1 and done[0][2] == "copy" and done[0][3].code == forma.CIRCLE, "Ctrl+Enter: копирование, форма круг")

a = appmod.Clipshot(qapp)
a.save_config = lambda: None
notes = []
a.notify = lambda t, *_x: notes.append(t)
a.config.update(theme_chosen=True, tour_done=True, novoe_enabled=False, auto_save=False)
copied = []
a.copy_image = lambda image, config=None: copied.append(QImage(image))
a.selector = sel
a.insert_target = None
a._region_done(done[0][0], done[0][1])
settle()
img = copied[0] if copied else QImage()
check(not img.isNull() and img.width() == img.height() == 250, f"в буфер: круг обрезан до квадрата 250 × 250 ({img.width()} × {img.height()})")
check(alpha(img, 1, 1) == 0 and alpha(img, 125, 125) == 255, "в буфер: углы прозрачные, середина на месте")
safe_close(sel)

# «Сохранить» из окна выделения (окно остаётся открытым): файл с формой
saved = []


class SaveCtx(Ctx):
    def save_from_selector(self, selector_, pixmap, rect):
        saved.append(pixmap.toImage())
        return os.path.join(tmp, "a.png")


sel2 = selector(SaveCtx(form_last=forma.OVAL))
sel2.toggle_form()
check(sel2.form.code == forma.OVAL, "второе окно: щелчок включает овал")
sel2.save_here()
settle()
check(saved and saved[0].width() == 400 and alpha(saved[0], 1, 1) == 0 and alpha(saved[0], 200, 125) == 255,
      "«Сохранить»: файл с овалом, углы прозрачные")
done2 = []
sel2.finished.connect(lambda pm, r: done2.append((pm, r, sel2.action, sel2.form.copy())))
sel2._do("pin")
settle()
a.selector = sel2
pinned = []
a.pin_image = lambda image, top_left=None: pinned.append(QImage(image))
a._region_done(done2[0][0], done2[0][1])
check(pinned and not forma.has_transparency(pinned[0]), "«Закрепить»: снимок без формы (окошко прямоугольное)")
safe_close(sel2)

# --- 4. редактор открывается с формой --------------------------------------------------------------------------------
sel3 = selector(Ctx(form_last=forma.ROUND, form_radius=40.0))
sel3.toggle_form()
check(sel3.form.code == forma.ROUND and abs(sel3.form.radius - 40) < 1e-6, "свой радиус 40 из настроек")
done3 = []
sel3.finished.connect(lambda pm, r: done3.append((pm, r)))
QTest.keyClick(sel3, Qt.Key.Key_Return)
settle()
a.selector = sel3
n = len(a.editors)
a._region_done(done3[0][0], done3[0][1])
settle(120)
ed = a.editors[-1] if len(a.editors) > n else None
check(ed is not None and ed.canvas.form.code == forma.ROUND and abs(ed.canvas.form.radius - 40) < 1e-6
      and ed.canvas.form.box is None, "редактор открылся со скруглёнными углами 40, рамка формы во весь снимок")
check(ed is not None and ed.form_button.isChecked() and not ed.canvas.undo_stack and not ed.canvas.modified,
      "кнопка формы в редакторе включена, шага отмены нет, снимок не «изменён»")
if ed is not None:
    out = ed.canvas.render()
    check(alpha(out, 1, 1) == 0 and out.width() == 400, "готовая картинка редактора с формой")
    ed.exported = True
    ed.close()
safe_close(sel3)
sel4 = selector(Ctx(form_last=forma.CIRCLE))
check(sel4.form.is_rect, "следующее окно выделения снова прямоугольное (включённое состояние не запоминается)")
safe_close(sel4)

# --- 5. 12 языков --------------------------------------------------------------------------------------------------
for lang in i18n.LANGUAGES:
    i18n.set_language(lang)
    s = selector(Ctx(form_last=forma.CIRCLE))
    on, off = tr("selector.form_tip_on", name="X", hotkey="F"), tr("selector.form_tip_off", name="X", hotkey="F")
    check(all(v and "{" not in v and "—" not in v and "X" in v and "F" in v for v in (on, off)), f"{lang}: подсказки формы")
    t = tiles(s)
    b = s._bar_layout()[1]
    top = [r for k, r in t.items() if k in RegionSelector.BAR_TOP]
    check("form" in t and b.contains(t["form"])
          and all(not top[i].intersects(top[j]) for i in range(len(top)) for j in range(i + 1, len(top))),
          f"{lang}: плитка формы помещается, плитки не налезают")
    s.close()
i18n.set_language("ru")

print("ИТОГ:", "ВСЁ ХОРОШО" if not failures else f"{len(failures)} ошибок")
sys.exit(1 if failures else 0)
