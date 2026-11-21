# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Интерфейс 1.29.1: понятный выход из режимов редактора. В режимах «Копирование текста», «Обрезка» и «Перевод» сверху
строка режима (значок, название, пояснение, крупная кнопка выхода на одном месте), инструменты рисования, палитра и толщина
скрыты; кнопка и Esc выходят, прежний инструмент и обычный вид возвращаются. Ввод текста и ластик: крупная подсказка выхода.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/ui1291_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import json
import os
import sys
import tempfile
import time

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
_cfg = os.path.join(tempfile.mkdtemp(prefix="clipsd-ui1291-"), "screen.json")
with open(_cfg, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1600, "height": 1000,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _cfg

from PyQt6.QtCore import QPoint, QRectF, Qt
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPixmap
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLabel

app = QApplication(sys.argv)
import clipshot
from clipshot import app as appmod, ocr, themes, translate, translate_ui
from clipshot.editor import CROP, ERASER, EditorWindow, MOVE, OCR, RECT, TRANSLATE, default_tool, MODE_TOOLS
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


class FakeEngine:
    name = "MyMemory"

    def translate(self, text, target, source=None):
        return "Перевод", "en"


translate.engines_from_config = lambda c: [FakeEngine()]
translate_ui.FloatingTranslation.request_more = lambda: None
translate.check_mymemory_email = lambda email, cb: cb("")
translate.check_google_key = lambda key, cb: cb("")
translate.usage_path = lambda: __import__("pathlib").Path(tempfile.mkdtemp(prefix="clipsd-ui1291-u-")) / "usage.json"
check(tuple(int(x) for x in clipshot.__version__.split(".")) >= (1, 29, 1), f"версия не ниже 1.29.1 ({clipshot.__version__})")


def letter(w=700, h=380):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor("#ffffff"))
    p = QPainter(img)
    p.setPen(QColor("#222222"))
    for i, line in enumerate(("Dear Ms. Taylor, thank you for your order.", "The shipment will leave on Monday.")):
        p.drawText(40, 60 + i * 40, line)
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
    ed.resize(1500, ed.height())   # 1.32: большие кнопки «Копировать текст» и «Перевести» видны только в широком окне
    settle()
    return ed, ctx


def done(ed):
    ed.canvas.modified, ed.exported = False, True
    ed.close()
    settle(2)


def vis(ed, w):
    return w.isVisibleTo(ed)


def drawing_hidden(ed):
    """Инструменты рисования, палитра, толщина и вся верхняя панель скрыты."""
    parts = [ed.panel, ed.tool_strip, ed.color_buttons["#d60808"], ed.custom_color, ed.size_group.buttons()[0], ed.undo_button]
    return not any(vis(ed, w) for w in parts)


def drawing_shown(ed):
    # 1.32: прямоугольник виден отдельной кнопкой или на значке свёрнутой группы «Фигуры» (после обрезки окно уже)
    parts = [ed.panel, ed.tool_strip, ed.color_buttons["#d60808"], ed.size_group.buttons()[0], ed.undo_button,
             ed.tool_strip.visible_widget(RECT)]
    return all(vis(ed, w) for w in parts)


def fake_words(ed):
    c = ed.canvas
    ratio = c.base.devicePixelRatio()
    words = [ocr.Word("Dear", QRectF(40, 48, 40, 14), 0), ocr.Word("Ms.", QRectF(86, 48, 24, 14), 0),
             ocr.Word("Taylor", QRectF(116, 48, 50, 14), 0)]
    c.set_words(words, ratio)


def esc(ed):
    QTest.keyClick(ed, Qt.Key.Key_Escape)
    settle()
    if ed.canvas.tool in (OCR, TRANSLATE, CROP):   # в тесте открыто несколько окон: активным может быть другое
        ed.escape()
        settle()


# --- общий вид режима ----------------------------------------------------------------------------------

MODES = {}


def enter_text(ed):
    fake_words(ed)
    QTest.mouseClick(ed.ocr_button, Qt.MouseButton.LeftButton)
    settle()


def enter_translate(ed):
    ed.tr_button.click()
    settle()


def enter_crop(ed):
    ed.tool_buttons[CROP].click()
    settle()


SPEC = [("text", OCR, enter_text, "text_top", "text_done_button", "Копирование текста", "Готово (Esc)"),
        ("crop", CROP, enter_crop, "crop_top", "crop_cancel_button", "Обрезка", "Отмена (Esc)"),
        ("translate", TRANSLATE, enter_translate, "tr_top", "tr_done_button", "Перевод", "Готово (Esc)")]
geom = {}
for key, tool, enter, top_name, exit_name, title, exit_label in SPEC:
    for how in ("button", "esc"):
        ed, ctx = mk(tool="rect")
        check(ed.canvas.tool == RECT and drawing_shown(ed), f"{key}/{how}: до входа обычный вид, выбран прямоугольник")
        enter(ed)
        top, btn = getattr(ed, top_name), getattr(ed, exit_name)
        check(ed.canvas.tool == tool, f"{key}/{how}: режим включён")
        check(vis(ed, top) and vis(ed, btn), f"{key}/{how}: строка режима и кнопка выхода видны")
        check(btn.text() == exit_label, f"{key}/{how}: кнопка выхода «{btn.text()}»")
        labels = [l.text() for l in top.findChildren(QLabel)]
        check(title in labels, f"{key}/{how}: в строке название «{title}» ({labels})")
        check(drawing_hidden(ed), f"{key}/{how}: инструменты рисования, палитра и толщина скрыты")
        check(btn.height() >= 36, f"{key}/{how}: кнопка выхода крупная ({btn.height()} px высотой)")
        if how == "button":
            geom[key] = (top.mapTo(ed, QPoint(0, 0)).y(), top.height(), top.width() - btn.geometry().right(), btn.height(), btn.width())
        if how == "button":
            btn.click()
        else:
            esc(ed)
        settle()
        check(ed.canvas.tool == RECT, f"{key}/{how}: выход вернул прежний инструмент ({ed.canvas.tool})")
        check(not vis(ed, top) and drawing_shown(ed), f"{key}/{how}: после выхода строка режима скрыта, инструменты снова видны")
        check(ed.tool_buttons[RECT].isChecked(), f"{key}/{how}: кнопка прямоугольника отмечена")
        done(ed)

check(geom["text"][:4] == geom["translate"][:4] and geom["text"][4] == geom["translate"][4] or
      (geom["text"][0] == geom["translate"][0] == geom["crop"][0] and geom["text"][1] == geom["translate"][1] == geom["crop"][1]),
      f"строка режима одной высоты и на одном месте во всех режимах: {geom}")
check(geom["text"][2] == geom["translate"][2], "кнопка выхода текста и перевода на одном месте (отступ справа одинаков)")
check(geom["text"][3] == geom["translate"][3] == geom["crop"][3], "кнопки выхода одной высоты")
check(geom["text"][4] == geom["translate"][4], f"кнопки «Готово (Esc)» текста и перевода одной ширины ({geom['text'][4]} и {geom['translate'][4]})")

# --- текст: полоса снизу ---------------------------------------------------------------------------------

ed, ctx = mk(tool="rect")
enter_text(ed)
check(vis(ed, ed.text_bottom) and not vis(ed, ed.bottom), "текст: внизу фиолетовая полоса вместо масштаба и сохранения")
check(not vis(ed, ed.save_button) and not vis(ed, ed.zoom_label), "текст: «Сохранить» и масштаб скрыты")
check(all(vis(ed, w) for w in (ed.text_mode_box, ed.text_mode_buttons["range"], ed.text_mode_buttons["marker"],
                               ed.text_copy_sel_button, ed.text_copy_all_button)), "текст: «Подряд / Маркер», «Скопировать выделенное», «Скопировать весь текст»")
check(ed.text_copy_sel_button.text().strip() == "Скопировать выделенное" and ed.text_copy_all_button.text().strip() == "Скопировать весь текст",
      "текст: подписи кнопок")
check(ed.text_sub.text() == "Нажмите на слово и тяните (или ведите маркером)", f"текст: пояснение «{ed.text_sub.text()}»")
check(ed.text_message.text() == ed.mode_hint.text() and "Выход" in ed.text_message.text(), f"текст: сообщение в полосе «{ed.text_message.text()}»")
ed.text_mode_buttons["marker"].click()
check(ed.canvas.text_mode == "marker" and "маркером" in ed.text_message.text(), "текст: «Маркер» переключает способ и сообщение")
ed.text_mode_buttons["range"].click()
ed.text_copy_all_button.click()
settle()
check(len(ed.canvas.text_sel) == 3, "текст: «Скопировать весь текст» выделяет все слова")
check("Dear Ms. Taylor" in (QApplication.clipboard().text() or ""), f"текст: весь текст в буфере «{QApplication.clipboard().text()}»")
ed.canvas.text_sel = {1}
QApplication.clipboard().setText("")
ed.text_copy_sel_button.click()
settle()
check("Ms." in QApplication.clipboard().text() and "Dear" not in QApplication.clipboard().text(), "текст: «Скопировать выделенное» копирует только выделенное")
ed.exit_text_mode()
check(ed.canvas.tool == RECT and not vis(ed, ed.text_bottom) and vis(ed, ed.bottom) and vis(ed, ed.save_button), "текст: после выхода снова масштаб и «Сохранить»")
check(ed.ocr_button.text().strip() == "Копировать текст" and (vis(ed, ed.ocr_button) or vis(ed, ed.tool_strip.visible_widget(OCR))),
      "текст: фиолетовая «Копировать текст» (в узком окне группа «Текст с картинки») остаётся входом")
check(ctx.config["tool"] == "rect", f"текст: режим не запомнен как инструмент ({ctx.config['tool']})")
done(ed)

# --- обрезка ---------------------------------------------------------------------------------------------

ed, ctx = mk(tool="rect")
enter_crop(ed)
check(not ed.crop_ok_button.isEnabled(), "обрезка: «Обрезать (Enter)» недоступна, пока рамки нет")
check(ed.crop_ok_button.text() == "Обрезать (Enter)" and ed.crop_cancel_button.text() == "Отмена (Esc)", "обрезка: кнопки «Обрезать (Enter)» и «Отмена (Esc)»")
check(vis(ed, ed.bottom), "обрезка: нижняя панель с размером и «Сохранить» остаётся")
sub = ed.crop_top.findChild(QLabel, "trSub").text()
check("Выделите область" in sub, f"обрезка: пояснение «{sub}»")
c = ed.canvas
QTest.mousePress(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(50, 50))
QTest.mouseMove(c, QPoint(200, 150))
QTest.mouseMove(c, QPoint(300, 200))
QTest.mouseRelease(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(300, 200))
settle()
check(c.crop_pending and ed.crop_ok_button.isEnabled(), "обрезка: рамка выделена, «Обрезать (Enter)» стала доступна")
size0 = (c.base.width(), c.base.height())
ed.crop_ok_button.click()
settle()
check((c.base.width(), c.base.height()) != size0 and c.base.width() < size0[0], f"обрезка: кнопка обрезала {size0} -> {(c.base.width(), c.base.height())}")
check(c.tool == RECT and drawing_shown(ed) and not vis(ed, ed.crop_top), "обрезка: после «Обрезать» режим завершён, обычный вид и прежний инструмент")
done(ed)

ed, ctx = mk(tool="rect")
enter_crop(ed)
c = ed.canvas
QTest.mousePress(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(50, 50))
QTest.mouseMove(c, QPoint(300, 200))
QTest.mouseRelease(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(300, 200))
settle()
size0 = (c.base.width(), c.base.height())
esc(ed)
check(c.tool == RECT and not c.crop_pending and (c.base.width(), c.base.height()) == size0 and ed.isVisible(),
      "обрезка: Esc с рамкой отменяет её, снимок цел, окно открыто, режим завершён")
check(drawing_shown(ed), "обрезка: после Esc инструменты видны")
enter_crop(ed)
QTest.mousePress(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(50, 50))
QTest.mouseMove(c, QPoint(300, 200))
QTest.mouseRelease(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(300, 200))
settle()
QTest.keyClick(ed, Qt.Key.Key_Return)
settle()
if c.tool == CROP:
    ed.enter_pressed()
    settle()
check(c.base.width() < size0[0] and c.tool == RECT, "обрезка: Enter обрезал и завершил режим")
enter_crop(ed)
ed.enter_pressed()
check(c.tool == CROP and not hasattr(ed, "clipboard"), "обрезка: Enter без рамки ничего не копирует и режим не покидает")
done(ed)

ed, ctx = mk(tool="rect")
enter_crop(ed)
c = ed.canvas
QTest.mousePress(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(50, 50))
QTest.mouseMove(c, QPoint(300, 200))
QTest.mouseRelease(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(300, 200))
settle()
size0 = (c.base.width(), c.base.height())
QTest.mouseDClick(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(150, 120))
settle()
check(c.base.width() < size0[0] and c.tool == RECT and drawing_shown(ed), "обрезка: двойной щелчок в рамке обрезает и выходит из режима, как «Обрезать»")
check(not hasattr(c, "_crop_buttons"), "обрезка: встроенных кнопок под рамкой нет, один способ: строка режима сверху")
done(ed)

# --- выход из режимов не гоняет по кругу (проверка 1.29.1) -------------------------------------------------

def enter_any(ed, tool):
    if tool == OCR:
        fake_words(ed)
    ed.select_tool(tool)
    settle(2)


MODES4 = [OCR, TRANSLATE, CROP, ERASER]
bad = []
for first in MODES4:
    for second in MODES4:
        if first == second:
            continue
        ed, ctx = mk(tool="rect")
        enter_any(ed, first)
        enter_any(ed, second)
        presses = 0
        while ed.canvas.tool in MODE_TOOLS | {ERASER} and presses < 4:
            ed.escape()
            settle(2)
            presses += 1
        if not (ed.canvas.tool == RECT and presses <= 2 and drawing_shown(ed)):
            bad.append((first, second, presses, ed.canvas.tool))
        done(ed)
check(not bad, f"любые пары режимов: Esc до обычного вида не больше двух нажатий, без кругов {bad}")
ed, ctx = mk(tool="rect")
enter_any(ed, OCR)
enter_any(ed, CROP)
ed.crop_cancel_button.click()
settle()
check(ed.canvas.tool == RECT, "текст -> обрезка -> «Отмена»: сразу обычный вид и прежний инструмент (прямоугольник)")
enter_any(ed, TRANSLATE)
enter_any(ed, OCR)
ed.text_done_button.click()
settle()
check(ed.canvas.tool == RECT, "перевод -> текст -> «Готово»: обычный вид")
done(ed)

# --- обрезка: нижние кнопки, пояснение; тёмный значок ---------------------------------------------------------

ed, ctx = mk(tool="rect")
enter_crop(ed)
check(not any(vis(ed, b) for b in (ed.save_button, ed.copy_button, ed.copy_close_button)) and vis(ed, ed.bottom),
      "обрезка: «Сохранить», «Скопировать», «Скопировать и закрыть» скрыты, масштаб остался")
c = ed.canvas
QTest.mousePress(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(50, 50))
QTest.mouseMove(c, QPoint(300, 200))
QTest.mouseRelease(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(300, 200))
settle()
check("щелчок мимо рамки: выделить заново" in ed.crop_top.findChild(QLabel, "trSub").text(), "обрезка: в пояснении «щелчок мимо рамки: выделить заново»")
ed.exit_crop_mode()
check(all(vis(ed, b) for b in (ed.save_button, ed.copy_button, ed.copy_close_button)), "после обрезки «Сохранить» и «Скопировать» вернулись")
done(ed)
ed, ctx = mk(ui_theme="pro")
img = ed.text_copy_sel_button.icon().pixmap(18, 18).toImage()
light = max(QColor(img.pixelColor(x, y)).lightness() for x in range(img.width()) for y in range(img.height()) if QColor(img.pixelColor(x, y)).alpha() > 200)
check(light > 170, f"тёмное оформление: значок «Скопировать выделенное» светлый (яркость {light})")
done(ed)

# --- что запоминается ------------------------------------------------------------------------------------

check(MODE_TOOLS == {OCR, TRANSLATE, CROP}, "режимы: текст, перевод, обрезка")
check(default_tool({"default_tool": "crop"}) == "", "обрезка не может быть инструментом по умолчанию")
ed, ctx = mk(tool="rect")
enter_crop(ed)
check(ctx.config["tool"] == "rect", f"режим обрезки не запоминается как последний инструмент ({ctx.config['tool']})")
done(ed)
ed, ctx = mk(tool="crop")
check(ed.canvas.tool == MOVE and drawing_shown(ed), f"в настройках остался «crop» от старой версии: окно открывается обычным видом ({ed.canvas.tool})")
done(ed)

# --- ввод текста и ластик ----------------------------------------------------------------------------------

from clipshot import hints
ed, ctx = mk(tool="text")
c = ed.canvas
check(c.tool == "text", "ввод текста: инструмент T")
QTest.mouseClick(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(100, 200))
settle()
plate = ed.findChild(hints.HintPlate, "clipsdHint")
check(c.text_edit is not None and plate is not None and plate.isVisibleTo(ed), "ввод текста: открыто поле и крупная подсказка")
shown = (plate.text + " " + plate.sub) if plate else ""
check("Ctrl+Enter" in shown and "Esc" in shown, f"ввод текста: в подсказке «Готово: Ctrl+Enter» и «Отмена: Esc» ({shown!r})")
ed.canvas.cancel_text()
settle()
done(ed)

ed, ctx = mk(tool="rect")
ed.select_tool(ERASER)
settle()
plate = ed.findChild(hints.HintPlate, "clipsdHint")
shown = (plate.text + " " + plate.sub) if plate else ""
check("Esc" in shown and "Ластик" in shown, f"ластик: подсказка выхода ({shown!r})")
ed.escape()
settle()
check(ed.canvas.tool == RECT and ed.isVisible(), f"ластик: Esc вернул прежний инструмент и не закрыл окно ({ed.canvas.tool})")
done(ed)


# --- панель окна выделения: пять плиток сверху, четыре кнопки снизу (вариант А) -----------------------------

from clipshot.selector import RegionSelector


def selector(width, kept=None, cfg=None, translate=False):
    pm = QPixmap(width, 720)
    pm.fill(QColor("#4a78b0"))
    sel = RegionSelector(pm, QRect(0, 0, width, 720), last_rect=kept)
    sel.tr_cfg, sel.tr_save = dict(appmod.DEFAULTS, **(cfg or {})), lambda: None
    sel.show_zoom = False
    sel.resize(width, 720)
    sel.show()
    settle(3)
    return sel


TOP5 = ["record", "full", "ocr", "phone", "translate", "translate_pick"]   # 1.34: шесть плиток
BOTTOM4 = ["save", "edit", "manual", "copy"]
# 1.34 (вариант Б): на экранах с подписями «Сохранить» и «Другая область» равные мелкие отдельным рядом, под ними крупные:
# широкая «Редактировать» и поуже «Скопировать и закрыть»; на 800 размер «wide»
for width, level in ((1280, "wide"), (800, "wide"), (480, "narrow")):
    sel = selector(width, QRect(width // 2 - 150, 90, 300, 200))
    sel.repaint()
    buttons, bar, hint = sel._bar_layout()
    rects = {k: r for k, _t, _s, r in buttons}
    texts = {k: t for k, t, _s, _r in buttons}
    check([k for k, *_x in buttons] == TOP5 + BOTTOM4, f"{width}: пять плиток сверху и четыре кнопки снизу {[k for k, *_x in buttons]}")
    choice = sel._choice(sel.bar_level)
    ws = [rects[k].width() for k in BOTTOM4]
    if choice:
        check(all(rects[k].top() == rects["record"].top() for k in TOP5) and rects["save"].top() == rects["manual"].top()
              and rects["edit"].top() == rects["copy"].top() > rects["save"].bottom() > rects["record"].bottom(),
              f"{width}: «Сохранить» в мелком ряду под плитками, крупные ниже")
        check(ws[1] > ws[3] and abs(ws[0] - ws[2]) <= 1, f"{width}: «Редактировать» шире «Скопировать», мелкие равные {ws}")
        check(rects["record"].left() == rects["edit"].left() and abs(rects["translate_pick"].right() - rects["copy"].right()) <= 1,
              f"{width}: края рядов совпадают")
    else:
        check(all(rects[k].top() == rects["record"].top() for k in TOP5) and all(rects[k].top() == rects["save"].top() for k in BOTTOM4)
              and rects["save"].top() > rects["record"].bottom(), f"{width}: «Сохранить» стоит в нижнем ряду, не в верхнем")
        check(all(a <= b for a, b in zip(ws, ws[1:])) and ws[1] < ws[3], f"{width}: нижние кнопки, чем правее, тем шире {ws}")
        check(rects["record"].left() == rects["save"].left() and abs(rects["translate_pick"].right() - rects["copy"].right()) <= 1,
              f"{width}: края рядов совпадают")
    check(sel.bar_level["name"] == level, f"{width}: размер панели «{sel.bar_level['name']}»")
    lv = sel.bar_level
    if lv["text"]:
        check(rects["copy"].height() == lv["btn_h"] + 10 and (level != "wide" or lv["btn_h"] == 52),
              f"{width}: высота крупных кнопок {rects['copy'].height()}")
        bl, bs = sel._bar_bfonts(lv)
        fb, fs = QFontMetrics(bl), QFontMetrics(bs)
        fl = QFontMetrics(sel._bar_fonts(lv)[0])
        bad = [k for k in ("edit", "copy") if fb.horizontalAdvance(texts[k]) > rects[k].width() - lv["pl"] - lv["sq"] - 6 - lv["gp"] - 4
               or fs.horizontalAdvance(sel._choice_sub(k)) > rects[k].width() - lv["pl"] - lv["sq"] - 6 - lv["gp"] - 4]
        bad += [k for k in ("save", "manual") if fl.horizontalAdvance(texts[k]) > rects[k].width() - 12 - 16 - 7 - 6]
        check(not bad, f"{width}: подписи и пояснения нижних кнопок не обрезаются {bad}")
        if level == "wide":
            check(lv["bl"] == 15 and abs(lv["bs"] - 11) < 0.01 and lv["sq"] == 32, "широкий (1.31.1, компактнее): название 15, пояснение 11, квадрат значка 32")
    else:
        check(sel._bar_label("copy", "", lv) == "Скопировать" and sel._bar_label("manual", "", lv) == "Заново",
              f"{width}: узкий режим: значки и короткие подписи")
    sel.close()
check(selector.__name__ == "selector" and RegionSelector.BAR_SUB["save"] == "в файл" and RegionSelector.BAR_SUB["edit"] == "или щелчок в рамке"
      and RegionSelector.BAR_SUB["manual"] == "или обведите на пустом" and RegionSelector.BAR_SUB["copy"] == "в буфер обмена", "пояснения кнопок по эскизу")
sel = selector(1280, QRect(500, 90, 300, 200))
sel._do("translate")
settle(2)
sel.repaint()
btns = {k: r for k, _t, _s, r in sel._bar_layout()[0]}
check(all(k in btns for k in BOTTOM4) and sel.translate_mode and set(sel.BAR_DISABLED_IN_TR) >= {"save", "edit", "copy"}, "режим перевода: нижние кнопки на месте, «Сохранить», «Редактировать», «Скопировать» бледные, как раньше")
sel.close()
sel = selector(1280, QRect(500, 90, 300, 200), cfg={"translate_enabled": False})
keys = [k for k, *_x in sel._bar_layout()[0]]
check(keys == ["record", "full", "ocr", "phone"] + BOTTOM4, f"перевод выключен: три плитки и четыре кнопки {keys}")
sel.close()

# --- строка режима перевода в окне выделения: шрифт и длинные языки ----------------------------------------------

from clipshot import selector as selmod
sel = selector(1280, QRect(500, 90, 300, 200))
sel._do("translate")
settle(2)
fonts_used = {}


class FontSpy(QPainter):
    def drawText(self, *a):
        for x in a:
            if isinstance(x, str):
                fonts_used[x] = self.font().pixelSize()
        return super().drawText(*a)


real_painter = selmod.QPainter
selmod.QPainter = FontSpy
sel.repaint()
selmod.QPainter = real_painter
small = sel.bar_level["small"]
ctl = [(t, r) for _k, t, r in sel.tr_ctl_rects]
check(ctl and all(fonts_used.get(t) == small for t, _r in ctl), f"строка режима перевода: кнопки нарисованы шрифтом {small} px {[(t, fonts_used.get(t)) for t, _r in ctl][:3]}")
bold = QFont()
bold.setPixelSize(small)
bold.setBold(True)
check(all(QFontMetrics(bold).horizontalAdvance(t) <= r.width() for t, r in ctl), "строка режима перевода: подписи кнопок помещаются в свои рамки")
sel.close()

print(f"ИТОГ: проверок {checks[0]}, ", "все пройдены" if not failures else f"провалено: {len(failures)}")
from clipshot.exitutil import quick_exit
quick_exit(1 if failures else 0)
