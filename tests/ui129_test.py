# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Интерфейс 1.29: панель окна выделения (два ряда, плитки, цвет у главных кнопок, три ширины без обрезки подписей),
перевод кусок за куском в окне выделения, редактор при переводе (строка «Перевод» сверху, бирюзовая полоса снизу),
инструмент по умолчанию (галочка, меню, config). Сеть и распознавание подменены.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/ui129_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import json
import os
import sys
import tempfile
import time
from types import SimpleNamespace

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
_cfg = os.path.join(tempfile.mkdtemp(prefix="clipsd-ui129-"), "screen.json")
with open(_cfg, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1600, "height": 1000,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _cfg

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QFontMetrics, QGuiApplication, QImage, QPainter, QPixmap
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMenu

app = QApplication(sys.argv)
import clipshot
from clipshot import app as appmod, themes, translate, translate_ui
from clipshot import editor as editormod
from clipshot.editor import ARROW, EditorWindow, OCR, RECT, TRANSLATE, default_tool
from clipshot.selector import RegionSelector
from clipshot.translate_ui import TranslateCard, TranslateMixin
failures = []
checks = [0]


def check(cond, msg):
    checks[0] += 1
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def settle(n=6):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(15)


def wait(cond, seconds=30):
    end = time.time() + seconds
    while not cond() and time.time() < end:
        app.processEvents()
        QTest.qWait(30)
    return cond()


translate.check_mymemory_email = lambda email, cb: cb("")
translate.check_google_key = lambda key, cb: cb("")
translate.usage_path = lambda: __import__("pathlib").Path(tempfile.mkdtemp(prefix="clipsd-ui129-u-")) / "usage.json"
check(tuple(int(x) for x in clipshot.__version__.split(".")) >= (1, 29, 1), f"версия не ниже 1.29.1 ({clipshot.__version__})")

# --- 1. Панель окна выделения ---------------------------------------------------------------------------

DESK_H = 720


def selector(width, kept=None, full=False, cfg=None):
    pm = QPixmap(width, DESK_H)
    pm.fill(QColor("#4a78b0"))
    sel = RegionSelector(pm, QRect(0, 0, width, DESK_H), last_rect=None if full else kept, full_screen=full)
    sel.tr_cfg, sel.tr_save = dict(appmod.DEFAULTS, **(cfg or {})), lambda: None
    sel.show_zoom = False
    sel.resize(width, DESK_H)
    sel.show()
    settle(3)
    return sel


EXPECT_ORDER = ["record", "full", "ocr", "translate", "translate_pick", "save", "edit", "manual", "copy"]
EXPECT_TEXT = {"record": "Запись видео", "full": "Снимок всего экрана", "save": "Сохранить", "ocr": "Копировать текст",
               "translate": "Перевести выделенное", "translate_pick": "Выделить и перевести", "edit": "Редактировать",
               "manual": "Выделить заново", "copy": "Скопировать и закрыть"}
for width, level in ((1280, "wide"), (800, "mid"), (480, "narrow")):
    sel = selector(width, QRect(width // 2 - 150, 90, 300, 200))
    sel.repaint()
    buttons, bar, hint = sel._bar_layout()
    rects = {k: r for k, _t, _s, r in buttons}
    texts = {k: t for k, t, _s, _r in buttons}
    check([k for k, *_x in buttons] == EXPECT_ORDER, f"{width}: порядок кнопок {[k for k, *_x in buttons]}")
    check(texts == EXPECT_TEXT, f"{width}: подписи кнопок")
    check(sel.bar_level["name"] == level, f"{width}: размер панели «{sel.bar_level['name']}» (ждали «{level}»)")
    top = [rects[k] for k in EXPECT_ORDER[:5]]
    bottom = [rects[k] for k in EXPECT_ORDER[5:]]
    check(len({(r.width(), r.height()) for r in top}) == 1 or max(r.width() for r in top) - min(r.width() for r in top) <= 1
          and len({r.height() for r in top}) == 1, f"{width}: шесть плиток верхнего ряда одинаковые ({sorted({r.width() for r in top})})")
    check(all(r.top() == top[0].top() for r in top) and all(r.top() == bottom[0].top() for r in bottom)
          and bottom[0].top() > top[0].bottom(), f"{width}: два ряда")
    check(abs(top[0].left() - bottom[0].left()) <= 1 and abs(top[-1].right() - bottom[-1].right()) <= 1,
          f"{width}: левый и правый края рядов совпадают ({top[0].left()}/{bottom[0].left()}, {top[-1].right()}/{bottom[-1].right()})")
    ws = [r.width() for r in bottom]   # 1.29.1: четыре нижние кнопки; в узком режиме «Сохранить» и «Редактировать» значки одной ширины
    check(all(a <= b for a, b in zip(ws, ws[1:])) and ws[1] < ws[2] < ws[3] and (level == "narrow" or ws[0] < ws[1]),
          f"{width}: чем правее, тем шире {ws}")
    check(all(bar.contains(r) for r in rects.values()), f"{width}: все кнопки внутри панели")
    flat = list(rects.values()) + [sel.bar_close_rect]
    check(not any(a.intersects(b) for i, a in enumerate(flat) for b in flat[i + 1:]), f"{width}: кнопки и крестик не пересекаются")
    cr = sel.bar_close_rect
    check(abs(cr.center().x() - bar.right()) <= 14 and abs(cr.center().y() - bar.top()) <= 14 and cr.right() < sel.width(),
          f"{width}: крестик «Закрыть (Esc)» на правом верхнем углу панели, на экране ({cr})")
    check(0 <= bar.left() and bar.right() < sel.width() and bar.bottom() < sel.height(), f"{width}: панель не выходит за экран {bar}")
    # подписи не обрезаются: каждая строка помещается в свою кнопку
    label_font, small_font = sel._bar_fonts(sel.bar_level)
    fm_l, fm_s = QFontMetrics(label_font), QFontMetrics(small_font)
    clipped = []
    if sel.bar_level["text"]:
        for key in EXPECT_ORDER[:5]:
            lines = sel._wrap(fm_l, texts[key], rects[key].width() - 12)
            if len(lines) > 2 or any(fm_l.horizontalAdvance(x) > rects[key].width() - 4 for x in lines):
                clipped.append(key)
        for key in EXPECT_ORDER[5:]:
            lvl = sel.bar_level
            bl_font, bs_font = sel._bar_bfonts(lvl)
            avail = rects[key].width() - lvl["pl"] - lvl["sq"] - lvl["gp"] - 6
            if QFontMetrics(bl_font).horizontalAdvance(texts[key]) > avail or QFontMetrics(bs_font).horizontalAdvance(sel.BAR_SUB[key]) > avail:
                clipped.append(key)
        if fm_s.horizontalAdvance(sel.BAR_SUB["translate"]) > rects["translate"].width() - 6:
            clipped.append("translate:sub")
    else:
        for key in ("manual", "copy"):
            label = sel._bar_label(key, texts[key], sel.bar_level)
            if QFontMetrics(sel._bar_bfonts(sel.bar_level)[0]).horizontalAdvance(label) > rects[key].width() - 14 - sel.bar_level["icon"] - 8 - 6:
                clipped.append(key)
    check(not clipped, f"{width}: подписи кнопок не обрезаются {clipped}")
    if level == "narrow":
        check(sel._bar_label("manual", "", sel.bar_level) == "Заново" and sel._bar_label("copy", "", sel.bar_level) == "Скопировать",
              "узкий режим: «Заново» и «Скопировать», «Редактировать» значком, верхний ряд значками")
    sel.close()

# ширина по содержимому, не по рамке: маленькая рамка, панель шире рамки
sel = selector(1280, QRect(600, 100, 120, 60))
bar = sel._bar_layout()[1]
check(bar.width() > 3 * 120 and bar.right() < sel.width(), f"маленькая рамка 120: панель {bar.width()} шире рамки и не за экраном")
sel.close()
# у правого края экрана: панель сдвинута, крестик на экране
sel = selector(1280, QRect(1100, 100, 160, 100))
bar = sel._bar_layout()[1]
check(bar.right() + 14 <= sel.width() and sel.bar_close_rect.right() < sel.width(), f"рамка у правого края: панель {bar} и крестик на экране")
sel.close()

# вторые строки, цвета и клавиши
sel = selector(1280, QRect(500, 90, 300, 200))
check(sel.BAR_SUB == {"save": "в файл", "edit": "или щелчок в рамке", "manual": "или обведите на пустом",
                      "copy": "в буфер обмена", "translate": "эту рамку", "translate_pick": "обведите другое место"}, "вторые мелкие строки")
# что реально нарисовано: перехватываем drawText панели
from clipshot import selector as selmod
drawn = []


class SpyPainter(QPainter):
    def drawText(self, *a):
        drawn.extend(x for x in a if isinstance(x, str))
        return super().drawText(*a)


real_painter = selmod.QPainter
selmod.QPainter = SpyPainter
sel.repaint()
selmod.QPainter = real_painter
check(all(w in " ".join(drawn).split() for t in EXPECT_TEXT.values() for w in t.split()) and not [t for t in drawn if "Ctrl" in t or "Enter" in t or "Delete" in t],
      f"нарисованы все подписи кнопок, клавиши на кнопках не пишутся ({len(drawn)} строк)")
shorts = {k: s for k, _t, s, _r in sel._bar_layout()[0]}
check(shorts["manual"] == "R или Delete" and shorts["edit"] == "Enter" and shorts["copy"] == "Ctrl+Enter", f"клавиши в подсказке: {shorts}")
sel.hover_button = "manual"
sel.repaint()
img = sel.grab().toImage()
ratio = img.width() / sel.width()


def px(r, dx=0.5, dy=0.5):
    return img.pixelColor(int((r.left() + r.width() * dx) * ratio), int((r.top() + r.height() * dy) * ratio))


sel.hover_button = None
sel.repaint()
img = sel.grab().toImage()
rects = {k: r for k, _t, _s, r in sel._bar_layout()[0]}


def close_to(c, hexcolor, tol=14):
    t = QColor(hexcolor)
    return abs(c.red() - t.red()) + abs(c.green() - t.green()) + abs(c.blue() - t.blue()) <= tol * 3


check(close_to(px(rects["copy"], 0.93, 0.5), themes.GREEN), f"«Скопировать и закрыть» зелёная ({px(rects['copy'], 0.93, 0.5).name()})")   # 1.32: #157a40
check(close_to(px(rects["manual"], 0.93, 0.5), "#e6f0fd"), f"«Выделить заново» голубая ({px(rects['manual'], 0.93, 0.5).name()})")
check(close_to(px(rects["edit"], 0.93, 0.5), "#ffffff"), f"«Редактировать» белая ({px(rects['edit'], 0.93, 0.5).name()})")
check(all(close_to(px(rects[k], 0.04, 0.5), "#f5f6f8") for k in EXPECT_ORDER[:5]), "у плиток нейтральный фон")


def has_color(r, hexcolor, tol=45):
    t = QColor(hexcolor)
    for yy in range(int(r.top() * ratio), int(r.bottom() * ratio), 2):
        for xx in range(int(r.left() * ratio), int(r.right() * ratio), 2):
            c = img.pixelColor(xx, yy)
            if abs(c.red() - t.red()) + abs(c.green() - t.green()) + abs(c.blue() - t.blue()) <= tol:
                return True
    return False


for key, col in (("record", "#d92d20"), ("full", "#2a6df4"), ("save", "#5a6270"), ("ocr", "#7c3aed"),
                 ("translate", "#0d9488"), ("translate_pick", "#0d9488")):
    check(has_color(rects[key], col), f"плитка «{EXPECT_TEXT[key]}»: цветной значок {col}")
# клавиша R и Delete снимают рамку
QTest.keyClick(sel, Qt.Key.Key_R)
check(sel.kept is None, "клавиша R: «Выделить заново» (рамка снята)")
sel.close()
from PyQt6.QtCore import QEvent
from PyQt6.QtGui import QKeyEvent
sel = selector(1280, QRect(500, 90, 300, 200))
sel.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, 0x6CB, Qt.KeyboardModifier.NoModifier, "к"))
check(sel.kept is None, "клавиша R на русской раскладке (символ «к»): «Выделить заново»")
sel.close()
sel = selector(1280, QRect(500, 90, 300, 200))
if sys.platform != "win32":
    sel.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, 0, Qt.KeyboardModifier.NoModifier, 27, 0, 0, ""))   # физическая клавиша R (X11)
    check(sel.kept is None, "физическая клавиша R (код 27) без символа: «Выделить заново»")
sel.close()
sel = selector(1280, QRect(500, 90, 300, 200))
sel.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, 0x6CB, Qt.KeyboardModifier.ControlModifier, "к"))
check(sel.kept is not None or sel.action == "record", "Ctrl+к не считается клавишей R без Ctrl")
sel.close()
sel = selector(1280, QRect(500, 90, 300, 200))
QTest.keyClick(sel, Qt.Key.Key_Delete)
check(sel.kept is None, "Delete по-прежнему работает")
sel.close()
sel = selector(1280, QRect(500, 90, 300, 200))
res = []
sel.finished.connect(lambda pm, r: res.append(r))
QTest.keyClick(sel, Qt.Key.Key_R, Qt.KeyboardModifier.ControlModifier)
check(sel.action == "record" and len(res) == 1 and res[0].isNull() and not sel.translate_mode,
      f"Ctrl+R запускает запись видео (действие {sel.action}), а не «Выделить заново»")
sel.close()
# режим «весь экран» и выбор монитора
sel = selector(1280, full=True)
keys = [k for k, *_x in sel._bar_layout()[0]]
check(sel.full_mode and "full" not in keys and keys[-4:] == ["save", "edit", "manual", "copy"] and len(keys) == 8, f"«весь экран»: кнопки {keys}")
check(sel._full_title() == "Снимок всего экрана", "«весь экран»: заголовок «Снимок всего экрана»")
sel.select_monitor(None)
check(sel.kept == sel.rect(), "«весь экран»: выбор «все мониторы» работает")
sel.close()
# выключенные перевод и распознавание
sel = selector(1280, QRect(500, 90, 300, 200), cfg={"translate_enabled": False})
keys = [k for k, *_x in sel._bar_layout()[0]]
check("translate" not in keys and "translate_pick" not in keys and len(keys) == 7, f"перевод выключен: на панели {keys}")
bar = sel._bar_layout()
check(abs(bar[0][0][3].left() - bar[0][3][3].left()) <= 1 and abs(bar[0][2][3].right() - bar[0][6][3].right()) <= 1,
      "перевод выключен: верхний ряд из трёх плиток, края рядов совпадают")
sel.close()

# --- 2. Перевод кусок за куском в окне выделения -------------------------------------------------------

spawned = []


def fake_start(self, run=True):
    """Окошко перевода: без распознавания и сети (только показать)."""
    spawned.append(self)
    self.show()


RealStart = translate_ui.FloatingTranslation.start
translate_ui.FloatingTranslation.start = fake_start
full_runs = []
RealFullRun = translate_ui.FullRun
translate_ui.FullRun = lambda *a, **k: full_runs.append((a, k))


def drag(w, a, b):
    QTest.mousePress(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, a)
    QTest.mouseMove(w, QPoint((a.x() + b.x()) // 2, (a.y() + b.y()) // 2))
    QTest.mouseMove(w, b)
    QTest.mouseRelease(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, b)
    app.processEvents()


sel = selector(1280, QRect(100, 100, 300, 120))
fin = []
sel.finished.connect(lambda pm, r: fin.append(r))
sel._do("translate")
settle(2)
check(not fin and sel.translate_mode and sel.kept is None, "«Перевести выделенное» со стоящей рамкой: окно не закрылось, режим перевода")
check(len(spawned) == 1 and spawned[0].tr_cards[0].region.size() == QRect(100, 100, 300, 120).size(), "переведена стоящая рамка (первый кусок)")
sel.repaint()
check(sel.bar_hint_text == "Режим перевода: обведите следующий кусок, он тоже переведётся · Esc: завершить",
      f"строка подсказки бирюзовая: «{sel.bar_hint_text}»")
img = sel.grab().toImage()
ratio = img.width() / sel.width()
rects = {k: r for k, _t, _s, r in sel._bar_layout()[0]}
hint_rect = sel._bar_layout()[2]
tile = rects["translate"]
c_tile = img.pixelColor(int((tile.left() + 8) * ratio), int((tile.top() + tile.height() / 2) * ratio))
c_other = img.pixelColor(int((rects["save"].left() + 8) * ratio), int((rects["save"].top() + rects["save"].height() / 2) * ratio))
c_hint = img.pixelColor(int((hint_rect.left() + 3) * ratio), int((hint_rect.top() + hint_rect.height() / 2) * ratio))
check(abs(c_tile.green() - c_tile.red()) > 15 and c_other.green() - c_other.red() < 8, f"плитка перевода подсвечена бирюзой ({c_tile.name()}), остальные нет ({c_other.name()})")
check(abs(c_hint.green() - c_hint.red()) > 15 and c_hint.green() > 200, f"строка подсказки залита бирюзовым ({c_hint.name()})")
drag(sel, QPoint(500, 300), QPoint(800, 400))
check(not fin and sel.translate_mode and len(spawned) == 2, f"обвели следующий кусок: он переведён сразу, окно открыто (окошек {len(spawned)})")
sz = spawned[1].tr_cards[0].region.size()
check(abs(sz.width() - 300) <= 1 and abs(sz.height() - 100) <= 1, f"второе окошко по обведённой области {sz}")
drag(sel, QPoint(60, 300), QPoint(170, 380))   # левее панели (в режиме перевода она внизу по центру)
check(len(spawned) == 3 and not fin, "третий кусок подряд")
check(all(w.isVisible() for w in spawned), "переводы остаются отдельными окошками на экране")
QTest.keyClick(sel, Qt.Key.Key_Escape)
check(not sel.translate_mode and not fin and all(w.isVisible() for w in spawned), "первый Esc: режим перевода завершён, окошки остались, окно выделения открыто")
QTest.keyClick(sel, Qt.Key.Key_Escape)
check(len(fin) == 1 and fin[0].isNull() and all(w.isVisible() for w in spawned), "второй Esc: окно выделения закрыто, окошки остались")
for w in spawned:
    w.close()
spawned.clear()
# рамки нет
sel = selector(1280)
fin = []
sel.finished.connect(lambda pm, r: fin.append(r))
sel._do("translate")
sel.repaint()
check(sel.translate_mode and sel.bar_hint_text == "Режим перевода: обведите кусок, он переведётся · Esc: завершить"
      and not spawned, f"рамки нет: подсказка «{sel.bar_hint_text}»")
drag(sel, QPoint(300, 300), QPoint(600, 380))
check(len(spawned) == 1 and sel.translate_mode and not fin, "обведённый кусок переводится, окно открыто")
# кнопки панели в режиме перевода: перевод всего экрана; значок плитки не закрывает окно
rects = {k: r for k, _t, _s, r in sel._bar_layout()[0]}
QTest.mouseClick(sel, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, rects["translate"].center())
check(sel.translate_mode and not fin, "щелчок по плитке «Перевести выделенное» в режиме перевода: режим остаётся")
sel.repaint()
rect_all = next(r for k, _t, r in sel.tr_ctl_rects if k == "trc:all")   # 1.31.1: «Весь экран» в строке режима перевода
QTest.mouseClick(sel, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, rect_all.center())
check(len(full_runs) == 1 and len(fin) == 1, "«Перевести весь экран» в режиме перевода: запущен перевод монитора, окно выделения закрылось (как в 1.28)")
check(full_runs[0][0][2] == QRect(0, 0, 1280, DESK_H).translated(sel.origin) or full_runs[0][0][2].size() == QRect(0, 0, 1280, DESK_H).size(),
      f"первым переводится монитор: {full_runs[0][0][2]}")
for w in spawned:
    w.close()
spawned.clear()
# «Перевести весь экран» без режима: окно тоже остаётся, подсказка «следующий кусок»
sel = selector(1280, QRect(100, 100, 300, 120))
fin = []
sel.finished.connect(lambda pm, r: fin.append(r))
sel.start_translate_all()
sel.repaint()
check(bool(fin) and len(full_runs) == 2, "«Перевести весь экран» при стоящей рамке: окно выделения закрылось, перевод монитора запущен")
sel.close()
# узкая панель: подсказка режима перевода не обрезается
sel = selector(480)
sel._do("translate")
sel.repaint()
bar = sel._bar_layout()
hf = sel._bar_fonts(sel.bar_level)[1]
hf.setBold(True)
need = QFontMetrics(hf).horizontalAdvance(sel.bar_hint_text)
check(need <= bar[2].width() - 16 or QFontMetrics(hf).boundingRect(QRect(0, 0, bar[2].width() - 16, 1000), Qt.TextFlag.TextWordWrap,
                                                                    sel.bar_hint_text).height() <= bar[2].height(),
      f"узкая панель: подсказка режима перевода «{sel.bar_hint_text}» помещается")
sel.close()

# кнопки, которые в режиме перевода не работают: бледные, подсказка «Сначала завершите перевод: Esc»
sel = selector(1280, QRect(100, 100, 300, 120))
fin = []
sel.finished.connect(lambda pm, r: fin.append(r))
sel._do("translate")
sel.repaint()
img = sel.grab().toImage()
ratio = img.width() / sel.width()
rects = {k: r for k, _t, _s, r in sel._bar_layout()[0]}
c_copy = img.pixelColor(int((rects["copy"].left() + rects["copy"].width() * 0.93) * ratio), int(rects["copy"].center().y() * ratio))
check(not close_to(c_copy, themes.GREEN, 30) and c_copy.green() > 150, f"«Скопировать и закрыть» в режиме перевода бледная ({c_copy.name()})")
for key in ("copy", "edit", "save", "ocr", "record", "full"):
    QTest.mouseClick(sel, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, rects[key].center())
check(sel.translate_mode and not fin and sel.action == "edit", "бледные кнопки в режиме перевода ничего не делают")
sel.hover_button = "copy"
drawn.clear()
selmod.QPainter = SpyPainter
sel.repaint()
selmod.QPainter = real_painter
check("Сначала завершите перевод: Esc" in drawn, "при наведении на бледную кнопку подсказка «Сначала завершите перевод: Esc»")
check(sel.translate_mode, "режим перевода не сбит")
sel.close()

# --- 2б. Плашки окошек: настоящие окошки с распознаванием, без подмены start --------------------------------

translate_ui.FloatingTranslation.start = RealStart
translate_ui.FullRun = RealFullRun


class FakeEngine:
    name = "MyMemory"

    def translate(self, text, target, source=None):
        return "Перевод: " + text[:40], "en"


translate.engines_from_config = lambda c: [FakeEngine()]
from clipshot import ocr as ocrmod
if ocrmod.engine_name() == "tesseract":
    def dense_page(w=1280, h=720, top=4):
        """Три плотных абзаца у верхнего края: промежутки между ними 4 точки."""
        img = QImage(w, h, QImage.Format.Format_RGB32)
        img.fill(QColor("#ffffff"))
        p = QPainter(img)
        f = p.font()
        f.setPixelSize(18)
        p.setFont(f)
        p.setPen(QColor("#1d2330"))
        y = top
        for para in range(3):
            for line in range(2):
                p.drawText(40, y + 18 + line * 22, "Free delivery to Porto in four days" if line == 0 else "Please confirm the order today")
            y += 52
        p.end()
        return QPixmap.fromImage(img)

    REGIONS = [QRect(36, 2, 420, 48), QRect(36, 54, 420, 48), QRect(36, 106, 420, 48)]

    def alive(ws):
        return [w for w in ws if not hidden_w(w)]

    def hidden_w(w):
        try:
            return not w.isVisible()
        except RuntimeError:
            return True

    def area_of(w):
        return QRect(w.mapToGlobal(w.tr_cards[0].region.topLeft()), w.tr_cards[0].region.size())

    def chip_of(w):
        c = w.tr_cards[0].chip
        return QRect(w.mapToGlobal(c.topLeft().toPoint()), c.size().toSize())

    def screen_rect():
        return QGuiApplication.primaryScreen().availableGeometry()

    before = list(translate_ui._floating)
    pm = dense_page()
    sel = RegionSelector(pm, QRect(0, 0, 1280, 720))
    sel.tr_cfg, sel.tr_save = dict(appmod.DEFAULTS), lambda: None
    sel.show_zoom = False
    sel.resize(1280, 720)
    sel.show()
    settle(3)
    fin = []
    sel.finished.connect(lambda pm_, r: fin.append(r))
    sel._do("translate")
    for r in REGIONS:
        drag(sel, r.topLeft(), r.bottomRight())
    wins = [w for w in translate_ui._floating if w not in before]
    check(len(wins) == 3 and all(w.mini for w in wins), f"режим перевода: три окошка, все без плашки ({len(wins)})")
    check(wait(lambda: all(w.tr_cards[0].state in ("done", "error") for w in wins), 90), "три плотных абзаца переведены настоящим распознаванием")
    for w in wins:
        w.repaint()
    settle(3)
    check(all(list(w.tr_cards[0].buttons) == ["close"] and w.tr_cards[0].chip.isNull() for w in wins),
          f"пока окно выделения в режиме перевода: у окошек нет плашки, только крестик {[list(w.tr_cards[0].buttons) for w in wins]}")
    for w in wins:
        cl = w.tr_cards[0].buttons["close"]
        check(w.tr_cards[0].region.contains(cl.toAlignedRect()), f"крестик внутри области куска {cl}")
    # кнопки в строке панели относятся к последнему окошку; щелчок по окошку выбирает его
    sel.repaint()
    check(sel._tr_current_win() is wins[-1], "кнопки строки перевода относятся к последнему переведённому окошку")
    wins[0].select_hook(wins[0])
    check(sel._tr_current_win() is wins[0], "щелчок по окошку выбирает его")
    sel._tr_select(wins[-1])
    bar = sel._bar_layout()[1]
    for w in wins:
        g = QRect(sel.mapFromGlobal(w.frameGeometry().topLeft()), w.frameGeometry().size())
        check(not g.intersects(bar), f"окошко не ложится на панель окна выделения (окошко {g}, панель {bar})")
    ctl = {k: r for k, _t, r in sel.tr_ctl_rects}
    cur = wins[-1]
    QGuiApplication.clipboard().clear()
    QTest.mouseClick(sel, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, ctl["trc:copy"].center())
    check(QGuiApplication.clipboard().text() == cur.tr_cards[0].text() and cur.tr_cards[0].text(), "«Скопировать» в строке панели: перевод последнего окошка")
    QTest.mouseClick(sel, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, ctl["trc:orig"].center())
    check(cur.tr_cards[0].show_original and not wins[0].tr_cards[0].show_original, "«Оригинал» в панели: только у выбранного окошка")
    QTest.mouseClick(sel, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, ctl["trc:tr"].center())
    check(not cur.tr_cards[0].show_original, "«Перевод» в панели: снова перевод")
    QGuiApplication.clipboard().clear()
    QTest.keyClick(sel, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    check(QGuiApplication.clipboard().text() == "\n\n".join(w.tr_cards[0].text() for w in wins), "Ctrl+C в режиме перевода: переводы всех окошек")
    # «Ещё» у окошка при открытом окне выделения
    from PyQt6.QtWidgets import QMenu
    real_exec = QMenu.exec
    QMenu.exec = lambda self, *a, **k: None
    QTest.mouseClick(sel, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, ctl["trc:more"].center())
    texts = [a.text() for a in cur.tr_more_menu.actions() if not a.isSeparator()]
    QMenu.exec = real_exec
    check(texts[0] == "Сервис: Google" and texts[1] == "Сервис: MyMemory" and texts[2].startswith("Осталось") and texts[2].endswith("сегодня")
          and "Скопировать все переводы" in texts and texts[-1] == "Перевести ещё кусок", f"меню «Ещё»: {texts}")
    check(any(t.startswith("Указать почту") for t in texts), "почта не указана: в меню «Указать почту: 50 000 в день…»")
    QGuiApplication.clipboard().clear()
    cur._tr_more_action("copyall")
    check(QGuiApplication.clipboard().text() == "\n\n".join(w.tr_cards[0].text() for w in wins), "«Скопировать все переводы»: тексты всех окошек")
    cur._tr_more_action("engine", "google")
    check(sel.tr_cfg["translate_engine"] == "google" or cur.tr_cfg["translate_engine"] == "google", "«Сервис: Google» переключает сервис")
    cur._tr_more_action("engine", "mymemory")
    QTest.keyClick(sel, Qt.Key.Key_Escape)   # первый Esc: режим завершён, плашки возвращаются
    for w in wins:
        w.repaint()
    settle(3)
    check(not fin and all(not w.mini for w in wins), "первый Esc: окно выделения открыто, у окошек появились плашки")
    cur._tr_more_action("more")
    check(sel.translate_mode and not fin, "«Перевести ещё кусок» при открытом окне выделения: в нём снова режим перевода (не глотается)")
    QTest.keyClick(sel, Qt.Key.Key_Escape)
    for w in wins:
        w.repaint()
    settle(3)
    areas = [area_of(w) for w in wins]
    scr = screen_rect()
    for i, w in enumerate(wins):
        ch = chip_of(w)
        bad = [j for j, a in enumerate(areas) if ch.intersects(a)]
        check(not bad and scr.contains(ch), f"плашка окошка {i} {ch} снаружи всех областей {areas} (пересечения {bad}), на экране")
    QTest.keyClick(sel, Qt.Key.Key_Escape)
    for w in wins:
        w.close()
    # без окна выделения: те же три плотных абзаца у верхнего края, окна создаются подряд
    before = list(translate_ui._floating)
    crops = [pm.toImage().copy(r) for r in REGIONS]
    wins = []
    for r, crop in zip(REGIONS, crops):
        w = translate_ui.FloatingTranslation(crop, 1.0, QRect(r), dict(appmod.DEFAULTS), None)
        w.start()
        wins.append(w)
    check(wait(lambda: all(w.tr_cards[0].state in ("done", "error") for w in wins), 90), "обычный перевод: три окошка готовы")
    for w in wins:
        w.repaint()
    settle(3)
    areas = [area_of(w) for w in wins]
    check(all(abs(a.top() - r.top()) <= 1 for a, r in zip(areas, REGIONS)), f"области окошек на месте оригинала {areas}")
    for i, w in enumerate(wins):
        ch = chip_of(w)
        bad = [j for j, a in enumerate(areas) if ch.intersects(a)]
        check(not bad and scr.contains(ch) and not w.tr_cards[0].chip.isNull(),
              f"обычный перевод, окошко {i}: плашка {ch} не на областях {bad}, на экране {scr.contains(ch)}, сторона {w.chip_side}")
    # одно окошко у самого верхнего края: плашка под областью или справа, не над ней. Три плотных окошка ещё открыты,
    # и их плашки стоят справа: свободного места рядом может не быть, тогда окошко зажато (плашки нет, крестик, 1.32.2)
    solo = translate_ui.FloatingTranslation(crops[0], 1.0, QRect(36, 0, 420, 48), dict(appmod.DEFAULTS), None)
    check(solo.chip_side in ("below", "right") or (solo.crowded and solo.chip_side == "none"),
          f"окошко у верхнего края: плашка {solo.chip_side} (зажато: {solo.crowded}), не над областью")
    solo.close()
    for w in wins:
        w.close()
    # --- висячие ссылки: окно выделения закрыто, а окошки живут; перевод заканчивается после закрытия ---
    errors = []
    old_hook = sys.excepthook
    sys.excepthook = lambda t, v, tb: errors.append(repr(v))

    class SlowEngine:
        name = "MyMemory"

        def translate(self, text, target, source=None):
            time.sleep(1.2)
            return "Перевод: " + text[:40], "en"
    before = list(translate_ui._floating)
    sel = RegionSelector(dense_page(), QRect(0, 0, 1280, 720))
    sel.tr_cfg, sel.tr_save = dict(appmod.DEFAULTS), lambda: None
    sel.show_zoom = False
    sel.resize(1280, 720)
    sel.show()
    settle(3)
    sel._do("translate")
    drag(sel, REGIONS[0].topLeft(), REGIONS[0].bottomRight())
    check(wait(lambda: all(w.tr_cards[0].state in ("done", "error") for w in translate_ui._floating if w not in before), 90), "первый кусок переведён")
    translate.engines_from_config = lambda c: [SlowEngine()]
    drag(sel, REGIONS[1].topLeft(), REGIONS[1].bottomRight())
    wins = [w for w in translate_ui._floating if w not in before]
    check(len(wins) == 2, "два куска")
    QTest.keyClick(sel, Qt.Key.Key_Escape)
    QTest.keyClick(sel, Qt.Key.Key_Escape)
    settle(3)
    check(all(w.select_hook is None and w.more_hook is None and w.tr_state_hook is None for w in wins),
          "после закрытия окна выделения у окошек нет ссылок на него (select_hook, more_hook, tr_state_hook)")
    real_exec = QMenu.exec
    QMenu.exec = lambda self, *a, **k: None
    for w in wins:
        w.repaint()
        for name in ("lang", "copy", "orig", "view", "more", "close"):
            btn = w.tr_cards[0].buttons.get(name) if w.tr_cards else None
            if btn is None or not w.isVisible():
                continue
            QTest.mouseClick(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, btn.center().toPoint())
            w.repaint()
    QMenu.exec = real_exec
    QTest.mouseClick(wins[0], Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(30, 30))
    check(wait(lambda: all((not w.isVisible()) or w.tr_cards[0].state in ("done", "error") for w in wins), 60),
          "перевод, закончившийся после закрытия окна выделения, дошёл до окошка")
    settle(5)
    check(not errors, f"без исключений при щелчках по окошкам и кнопкам после закрытия окна выделения {errors}")
    sys.excepthook = old_hook
    translate.engines_from_config = lambda c: [FakeEngine()]
    for w in wins:
        try:
            w.close()
        except RuntimeError:
            pass   # окошко уже закрыто крестиком

    # --- плашка обходит ещё не переведённый текст (чернила на кадре экрана) ---
    def page_with(paras):
        img = QImage(1280, 720, QImage.Format.Format_RGB32)
        img.fill(QColor("#ffffff"))
        p = QPainter(img)
        f = p.font()
        f.setPixelSize(18)
        p.setFont(f)
        p.setPen(QColor("#1d2330"))
        for r in paras:
            p.drawText(r.left(), r.top() + 18, "Free delivery to Porto in four days")
            p.drawText(r.left(), r.top() + 40, "Please confirm the order today")
        p.end()
        return QPixmap.fromImage(img)

    def case(paras, regions, translate_idx, label):
        before_ = list(translate_ui._floating)
        sel_ = RegionSelector(page_with(paras), QRect(0, 0, 1280, 720))
        sel_.tr_cfg, sel_.tr_save = dict(appmod.DEFAULTS), lambda: None
        sel_.show_zoom = False
        sel_.resize(1280, 720)
        sel_.show()
        settle(3)
        sel_._do("translate")
        for i in translate_idx:
            drag(sel_, regions[i].topLeft(), regions[i].bottomRight())
        ws = [w for w in translate_ui._floating if w not in before_]
        wait(lambda: all(w.tr_cards[0].state in ("done", "error") for w in ws), 90)
        QTest.keyClick(sel_, Qt.Key.Key_Escape)   # плашки возвращаются
        for w in ws:
            w.repaint()
        settle(3)
        untranslated = [r.adjusted(-2, -2, 2, 2) for i, r in enumerate(paras) if i not in translate_idx]
        for k, w in enumerate(ws):
            ch = chip_of(w)
            bad = [r for r in untranslated if ch.intersects(r)]
            check(not bad and not w.tr_cards[0].chip.isNull(), f"{label}, окошко {k}: плашка {ch} ({w.chip_side}) не на непереведённых строках {bad}")
        QTest.keyClick(sel_, Qt.Key.Key_Escape)
        for w in ws:
            w.close()
    p3 = [QRect(40, 4 + 52 * i, 300, 44) for i in range(3)]
    r3 = [QRect(36, 2 + 52 * i, 420, 48) for i in range(3)]
    case(p3, r3, (0, 2), "три плотных абзаца, переведены 1-й и 3-й")
    p7 = [QRect(40, 20 + 52 * i, 300, 44) for i in range(12)]
    r7 = [QRect(36, 18 + 52 * i, 420, 48) for i in range(12)]
    case(p7, r7, (5,), "одиночный кусок посередине страницы")
else:
    print("распознавания Tesseract нет: проверки плашек окошек пропущены")

# --- 3. Редактор при переводе ----------------------------------------------------------------------------


def letter(w=900, h=440):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor("#ffffff"))
    p = QPainter(img)
    f = p.font()
    f.setPixelSize(20)
    p.setFont(f)
    p.setPen(QColor("#1d2330"))
    for i, line in enumerate(("Dear Ms. Taylor,", "thank you for your order.", "Free delivery to Porto.")):
        p.drawText(60, 70 + i * 30, line)
    p.end()
    return img


class Ctx:
    def __init__(self, **kw):
        self.config = dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True, **kw)
        self.icon = appmod.make_icon()
        self.saved = 0

    def copy_image(self, image):
        self.clipboard = image

    def notify(self, text):
        pass

    def save_config(self):
        self.saved += 1


def mk(**kw):
    ctx = Ctx(**kw)
    themes.apply_app(app, ctx.config)
    ed = EditorWindow(letter(), ctx, QPoint(60, 40))
    ed.present()
    settle()
    return ed, ctx


def done(ed):
    ed.canvas.modified, ed.exported = False, True
    ed.close()
    themes.apply_app(app, {"ui_theme": "standard"})


def block(text, src="en", tgt="ru", rect=QRectF(60, 50, 300, 24)):
    return {"rect": QRectF(rect), "draw": QRectF(rect), "text": text, "orig": "orig", "src": src, "tgt": tgt,
            "bg": QColor("#ffffff"), "fg": QColor("#101010"), "px": 16, "engine": "MyMemory"}


def add_card(layer, texts, skipped=0, total=0, partial=False):
    card = TranslateCard(QRect(40, 40, 400, 120))
    card.state, card.view = "done", "overlay"
    card.blocks = [block(t) for t in texts]
    card.skipped, card.total, card.partial = skipped, total, partial
    card.content = QRectF(card.region)
    layer.tr_cards.append(card)
    layer.update()
    return card


ed, ctx = mk()
ed.set_zoom(1.0)
visible = lambda w: w.isVisibleTo(ed)
check(visible(ed.panel) and visible(ed.bottom) and not visible(ed.tr_top) and not visible(ed.tr_bottom), "до перевода: обычный вид, строки перевода нет")
ed.select_tool(TRANSLATE)
settle()
check(not visible(ed.panel) and not visible(ed.tool_strip) and not any(visible(b) for b in ed.color_buttons.values())
      and not visible(ed.size_group.button(1)) and not visible(ed.undo_button),
      "перевод: скрыты инструменты рисования, палитра, толщина, отмена")
check(not visible(ed.bottom) and not visible(ed.save_button) and not visible(ed.copy_button) and not visible(ed.zoom_label),
      "перевод: скрыты масштаб и кнопки «Сохранить», «Скопировать», «Скопировать и закрыть»")
labels = [lb.text() for lb in ed.tr_top.findChildren(type(ed.tr_message))]
check(visible(ed.tr_top) and "Перевод" in labels and ed.tr_done_button.text() == "Готово (Esc)" and visible(ed.tr_done_button),
      f"сверху строка «Перевод» и «Готово (Esc)» {labels}")
check(visible(ed.tr_bottom) and ed.tr_bottom.objectName() == "trBottom", "внизу бирюзовая полоса")
check(all(visible(w) for w in (ed.tr_message, ed.tr_lang_button, ed.tr_show_tr, ed.tr_show_orig, ed.tr_view_overlay, ed.tr_view_card, ed.tr_copy_button)),
      "в полосе: сообщение, язык, «Перевод / Оригинал», «Поверх текста / Карточкой», «Скопировать перевод»")
check([ed.tr_show_tr.text(), ed.tr_show_orig.text(), ed.tr_view_overlay.text(), ed.tr_view_card.text()] == ["Перевод", "Оригинал", "Поверх текста", "Карточкой"]
      and "Скопировать перевод" in ed.tr_copy_button.text(), "подписи переключателей")
check(ed.tr_bottom.styleSheet() == "" and "#0b8f84" in ed.styleSheet(), "полоса бирюзовая (стиль окна)")
layer = ed.tr_layer
card = add_card(layer, ["Дорогая госпожа Тейлор,"], skipped=2, total=3)
layer.repaint()
settle()
check(card.chip.isNull() and not card.buttons and card.handle.isNull(), "плашка перевода поверх снимка не рисуется")
img = layer.grab().toImage()
teal_chip = 0
for yy in range(0, 30):
    for xx in range(0, img.width(), 4):
        c = img.pixelColor(xx, yy)
        if c.alpha() > 200 and c.green() > 120 and c.red() < 40:
            teal_chip += 1
check(teal_chip == 0, "над переводом нет бирюзовой плашки с кнопками")
ed._update_info()
check(ed.tr_message.text() == "Переведено: 1 абзац. Уже на русском, оставлено как есть: 2", f"сообщение о пропуске: «{ed.tr_message.text()}»")
check("→ Русский" in ed.tr_lang_button.text() or "Русский" in ed.tr_lang_button.text(), f"кнопка языка: «{ed.tr_lang_button.text()}»")
# склонения
cases = [(1, 0, 0, False, "Переведено: 1 абзац"), (2, 0, 0, False, "Переведено: 2 абзаца"), (5, 0, 0, False, "Переведено: 5 абзацев"),
         (21, 0, 0, False, "Переведено: 21 абзац"), (22, 0, 0, False, "Переведено: 22 абзаца"), (11, 0, 0, False, "Переведено: 11 абзацев"),
         (1, 0, 21, True, "Переведено, сколько хватило лимита: 1 из 21 абзаца"),
         (2, 0, 22, True, "Переведено, сколько хватило лимита: 2 из 22 абзацев"),
         (1, 0, 31, True, "Переведено, сколько хватило лимита: 1 из 31 абзаца"),
         (3, 0, 11, True, "Переведено, сколько хватило лимита: 3 из 11 абзацев"),
         (1, 0, 3, True, "Переведено, сколько хватило лимита: 1 из 3 абзацев"),
         (3, 21, 0, False, "Переведено: 3 абзаца. Уже на русском, оставлено как есть: 21")]
for m, n, k, partial, want in cases:
    got = TranslateMixin._tr_partial_text(SimpleNamespace(blocks=[0] * m, skipped=n, total=k, partial=partial))
    check(got == want, f"склонение: «{got}»")
# переключатели
ed.tr_show_orig.click()
check(card.show_original and ed.tr_show_orig.isChecked() and not ed.tr_show_tr.isChecked(), "«Оригинал»: показан исходный текст у всех кусков")
ed.tr_show_tr.click()
check(not card.show_original and ed.tr_show_tr.isChecked(), "«Перевод»: снова перевод")
ed.tr_view_card.click()
settle()
check(ctx.config["translate_view"] == "card" and len(layer.floats) == 1 and not layer.tr_cards and ed.tr_view_card.isChecked(),
      "«Карточкой»: кусок переехал в окошко, переключатель показывает выбор")
ed.tr_view_overlay.click()
settle()
check(ctx.config["translate_view"] == "overlay" and len(layer.tr_cards) == 1 and not layer.floats and ed.tr_view_overlay.isChecked(),
      "«Поверх текста»: кусок вернулся на снимок")
ed.tr_copy_button.click()
check(QGuiApplication.clipboard().text() == "Дорогая госпожа Тейлор,", f"«Скопировать перевод»: в буфере «{QGuiApplication.clipboard().text()}»")
# Готово возвращает обычный вид
QTest.mouseClick(ed.tr_done_button, Qt.MouseButton.LeftButton)
settle()
check(ed.canvas.tool != TRANSLATE and visible(ed.panel) and visible(ed.bottom) and visible(ed.tool_strip) and visible(ed.zoom_label)
      and not visible(ed.tr_top) and not visible(ed.tr_bottom), "«Готово (Esc)»: обычный вид вернулся")
ed.select_tool(TRANSLATE)
settle()
check(not visible(ed.panel) and visible(ed.tr_bottom), "снова перевод: панели скрыты")
ed.escape()
settle()
check(ed.canvas.tool != TRANSLATE and visible(ed.panel) and visible(ed.bottom) and not visible(ed.tr_top), "Esc: обычный вид вернулся")
done(ed)
# полный вид перевода всего снимка и перенос сообщения
ed, ctx = mk()
ed.select_tool(TRANSLATE)
check("Обведите мышью кусок" in ed.tr_message.text() or ed.tr_message.text() == ed.MODE_HINTS[TRANSLATE], f"до перевода сообщение «{ed.tr_message.text()}»")
done(ed)

# --- 4. Инструмент по умолчанию ---------------------------------------------------------------------------

ed, ctx = mk(tool="arrow")
check(default_tool(ctx.config) == "" and ed.canvas.tool == ARROW, "по умолчанию инструмента нет: открылся с последним (стрелка)")
check(not any(b.default_mark for b in ed.tool_buttons.values()), "галочки нет ни на одной кнопке")
tip_rect = ed.tool_buttons[RECT].toolTip()
check(tip_rect.endswith("Правая кнопка мыши: сделать инструментом по умолчанию"), "подсказка неотмеченного: последняя строка про правую кнопку")
menu = ed.build_tool_menu(RECT)
texts = [a.text() for a in menu.actions() if not a.isSeparator()]
check(texts == ["Сделать прямоугольник инструментом по умолчанию", "Без инструмента по умолчанию: открывать с последним",
                "Вернуть стандартный порядок инструментов"], f"меню неотмеченного: {texts}")
# правая кнопка по инструменту (меню без блокировки)
shown = []
real_exec = QMenu.exec
QMenu.exec = lambda self, *a, **k: (shown.append([x.text() for x in self.actions() if not x.isSeparator()]), None)[1]
rect_w = ed.tool_strip.visible_widget(RECT)   # 1.32: в узком окне прямоугольник на значке группы «Фигуры»
pos = rect_w.mapTo(ed.tool_strip, rect_w.rect().center())
ed._tool_strip_menu(pos)
QMenu.exec = real_exec
check(shown and shown[0][0] == "Сделать прямоугольник инструментом по умолчанию", f"правая кнопка по инструменту открывает меню этого инструмента: {shown}")
next(a for a in menu.actions() if a.text().startswith("Сделать")).trigger()
check(ctx.config["default_tool"] == "rect" and ctx.saved >= 1, "выбор записан в config (default_tool = rect) и сохранён")
marks = [t for t, b in ed.tool_buttons.items() if b.default_mark]
check(marks == [RECT], f"галочка одна, на прямоугольнике: {marks}")
check(ed.tool_buttons[RECT].toolTip().endswith("✓ Инструмент по умолчанию: включается при каждом открытии редактора")
      and ed.tool_buttons[ARROW].toolTip().endswith("Правая кнопка мыши: сделать инструментом по умолчанию"), "подсказки: отмеченного и остальных")
b = ed.tool_buttons[RECT]
shot = b.grab().toImage()
r = shot.devicePixelRatio()
c = shot.pixelColor(int((b.width() - 9) * r), int((b.height() - 4) * r))
check(abs(c.red() - 0x1f) < 40 and abs(c.green() - 0x9d) < 40 and abs(c.blue() - 0x55) < 50, f"зелёная галочка в правом нижнем углу кнопки ({c.name()})")
c2 = ed.tool_buttons[ARROW].grab().toImage().pixelColor(int((b.width() - 9) * r), int((b.height() - 4) * r))
check(not (c2.green() > 130 and c2.red() < 90), "на других кнопках галочки нет")
texts = [a.text() for a in ed.build_tool_menu(RECT).actions() if not a.isSeparator()]
check(texts[0] == "✓ Прямоугольник: инструмент по умолчанию", f"меню отмеченного: «{texts[0]}»")
texts = [a.text() for a in ed.build_tool_menu(ARROW).actions() if not a.isSeparator()]
check(texts[0] == "Сделать стрелку инструментом по умолчанию", f"меню другого инструмента: «{texts[0]}»")
ed.set_default_tool(ARROW)
check([t for t, bb in ed.tool_buttons.items() if bb.default_mark] == [ARROW] and ctx.config["default_tool"] == "arrow", "галочка переехала на стрелку")
ed.set_default_tool(RECT)
done(ed)
ed, ctx2 = mk(tool="arrow", default_tool="rect")
check(ed.canvas.tool == RECT and ed.tool_buttons[RECT].isChecked() and ed.tool_buttons[RECT].default_mark,
      "редактор открылся с инструментом по умолчанию (прямоугольник), хотя последним была стрелка")
ed.select_tool(ARROW)
check(ctx2.config["default_tool"] == "rect" and ctx2.config["tool"] == "arrow", "смена инструмента внутри сеанса не меняет инструмент по умолчанию")
menu = ed.build_tool_menu(ARROW)
next(a for a in menu.actions() if a.text().startswith("Без инструмента")).trigger()
check(ctx2.config["default_tool"] == "" and not any(bb.default_mark for bb in ed.tool_buttons.values()), "«Без инструмента по умолчанию»: пусто, галочка снята")
done(ed)
ed, ctx3 = mk(tool="arrow", default_tool="")
check(ed.canvas.tool == ARROW, "пусто: открывается с последним инструментом")
done(ed)
ed, ctx4 = mk(tool="arrow", default_tool="ocr")
check(ed.canvas.tool == ARROW and default_tool(ctx4.config) == "", "режимы («Копировать текст», перевод) по умолчанию не включаются")
menu = ed.build_tool_menu(OCR)
check(not any(a.text().startswith("Сделать") for a in menu.actions()), "у режима «Копировать текст» пункта «Сделать…» нет")
ed.tool_strip.set_order([t for t, _g, _tip, _k in editormod.TOOLS][::-1])
next(a for a in ed.build_tool_menu(RECT).actions() if a.text().startswith("Вернуть")).trigger()
check(ed.tool_strip.order() == [t for t, _g, _tip, _k in editormod.TOOLS], "«Вернуть стандартный порядок»: порядок возвращён")
done(ed)
check(appmod.DEFAULTS.get("default_tool", None) == "", "в настройках по умолчанию default_tool пустой")

# --- 5. Мелочи 1.28 ---------------------------------------------------------------------------------------

state_calls = []


class Job:
    def cancel(self):
        pass


translate.start = lambda *a, **k: Job()
translate_ui.FullRun = RealFullRun
run = translate_ui.FullRun(QImage(10, 10, QImage.Format.Format_RGB32), dict(appmod.DEFAULTS), QRect(0, 0, 10, 10), QRect(0, 0, 10, 10).size(),
                           lambda r: None, say=lambda t: None, on_state=lambda: state_calls.append(1))
n0 = len(state_calls)


def boom(*a, **k):
    raise RuntimeError("тест: неожиданная ошибка")


run._done_inner = boom
real_report = translate_ui._report
translate_ui._report = lambda owner=None: None
run._done([], "", None)
translate_ui._report = real_report
check(len(state_calls) > n0 and run.closed, f"FullRun._done: после неожиданной ошибки состояние сообщено редактору ({len(state_calls) - n0} раз), окошко закрыто")
src = open(os.path.join(here, "threads_test.py"), encoding="utf-8").read()
check("def wait(cond, seconds=300)" in src, "tests/threads_test.py ждёт до 300 с")
src = open(os.path.join(os.path.dirname(here), "packaging", "windows-exe", "clipsd_app_entry.py"), encoding="utf-8").read()
check("quick_exit(main())" in src and "sys.exit" not in src, "запускатель exe выходит через quick_exit")

print(f"ИТОГ: проверок {checks[0]}, ", "все пройдены" if not failures else f"провалено: {len(failures)}")
from clipshot.exitutil import quick_exit
quick_exit(1 if failures else 0)
