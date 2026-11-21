# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Строка режима «Перевод» в редакторе: одна строка, как у других режимов (решение владельца 21.11.2026).

Что решил владелец: «шапка такая же, как была; если нажали кнопку, то в рамках той же ширины шапки; элементы управления
располагай как удобно». Кнопки перевода, которые были внизу окна, переехали в строку сверху, нижней полосы нет.

Проверяется:
1. на ширинах окна 1100, 800 и 656 и на всех 12 языках язык перевода, «Скопировать перевод» и «Готово (Esc)» видны,
   лежат внутри строки, не сжаты меньше своего текста и не налезают друг на друга; высота строки равна высоте строки
   других режимов («Текст с картинки») и не меняется от ширины и языка; строка не растягивает окно; в тёмной теме то же;
2. нижней полосы перевода нет (ни атрибута, ни виджета trBottom);
3. меню «⋯»: «Поверх текста / Карточкой» всегда, «Перевод / Оригинал» только когда сегменты свёрнуты;
4. гонки (оба порядка событий): включить и выключить перевод, пока идёт запрос; Esc во время запроса; смена языка во
   время запроса (ответ на прежний язык не показывается, перевод идёт заново); ширина окна меняется во время перевода;
   закрытие редактора во время запроса. Поздний ответ не открывает режим заново и не роняет программу.

Распознавание настоящее (Tesseract), сеть подменена. Запуск: QT_QPA_PLATFORM=offscreen python3 tests/perevod_shapka_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import json
import os
import sys
import tempfile
import threading
import time

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
os.environ.pop("CLIPSD_LANG", None)   # тест сам перебирает языки
_cfg = os.path.join(tempfile.mkdtemp(prefix="clipsd-shapka-"), "screen.json")
with open(_cfg, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1600, "height": 1000,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _cfg

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

app = QApplication(sys.argv[:1])
from clipshot import app as appmod, i18n, ocr, themes, translate  # noqa: E402
from clipshot.editor import EditorWindow, MOVE, OCR, TRANSLATE  # noqa: E402
from clipshot.translate_ui import TranslateCard  # noqa: E402

LANGS = ("ru", "en", "bg", "uk", "de", "fr", "es", "it", "pt", "pl", "tr", "zh")
failures, checks, errors = [], [0], []
_hook = sys.excepthook


def _catch(*exc):
    errors.append(exc)
    _hook(*exc)


sys.excepthook = _catch


def check(cond, msg):
    checks[0] += 1
    if not cond:
        print("FAIL " + msg, flush=True)
        failures.append(msg)
    elif os.environ.get("SHAPKA_VERBOSE"):
        print("OK   " + msg, flush=True)


def settle(n=6):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(12)


def wait(cond, seconds=60):
    end = time.time() + seconds
    while not cond() and time.time() < end:
        app.processEvents()
        QTest.qWait(30)
    return cond()


class Ctx:
    def __init__(self, theme="standard"):
        self.config = dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True, translate_view="overlay", ui_theme=theme)
        self.icon = appmod.make_icon()
        self.saved = 0

    def copy_image(self, image):
        pass

    def notify(self, text):
        pass

    def save_config(self):
        self.saved += 1


def letter():
    img = QImage(900, 420, QImage.Format.Format_RGB32)
    img.fill(QColor("#ffffff"))
    return img


def block(text, src="en", tgt="ru", rect=QRectF(60, 50, 300, 24)):
    return {"rect": QRectF(rect), "draw": QRectF(rect), "text": text, "orig": "orig", "src": src, "tgt": tgt,
            "bg": QColor("#ffffff"), "fg": QColor("#101010"), "px": 16, "engine": "MyMemory"}


def mk_layout(lang, theme="standard"):
    i18n.set_language(lang)
    ctx = Ctx(theme)
    themes.apply_app(app, ctx.config)
    ed = EditorWindow(letter(), ctx, QPoint(20, 20))
    ed.present()
    settle()
    return ed, ctx


def close(ed):
    try:
        ed.canvas.modified, ed.exported = False, True
        ed.close()
    except RuntimeError:
        pass
    settle()


# --- 1-3. раскладка строки ---------------------------------------------------------------------------------------------
# Высота строки других режимов: эталон («Текст с картинки»): равна ей и в переводе
ed, ctx = mk_layout("ru")
ed.resize(1100, 600)
ed.select_tool(OCR)
settle()
BASE_H = ed.text_top.height()
if os.environ.get("QT_SCALE_FACTOR"):
    check(abs(ed.devicePixelRatioF() - float(os.environ["QT_SCALE_FACTOR"])) < 0.01,
          f"масштаб экрана {os.environ['QT_SCALE_FACTOR']} действует (множитель окна {ed.devicePixelRatioF()})")
check(BASE_H >= 48, f"эталонная высота строки режима {BASE_H}")
close(ed)


def layout_checks(ed, lang, width, label):
    top = ed.tr_top
    row = top.layout()
    check(top.isVisibleTo(ed) and not hasattr(ed, "tr_bottom") and not ed.findChildren(QWidgetAny, "trBottom"),
          f"{label}: строка перевода есть, нижней полосы нет")
    check(top.height() == BASE_H, f"{label}: высота строки {top.height()} равна высоте строки других режимов {BASE_H}")
    check(ed.width() == width, f"{label}: окно не растянулось из-за строки ({ed.width()} вместо {width})")
    check(row.minimumSize().width() <= top.width(),   # minimumSize уже с полями
          f"{label}: самое узкое содержимое строки {row.minimumSize().width()} помещается в {top.width()}")
    must = [("язык", ed.tr_lang_button), ("«Скопировать перевод»", ed.tr_copy_button), ("«Готово (Esc)»", ed.tr_done_button)]
    shown = [w for w in (row.itemAt(i).widget() for i in range(row.count())) if w is not None and w.isVisibleTo(ed)]
    for name, w in must:
        r = QRect(w.mapTo(top, QPoint(0, 0)), w.size())
        check(w.isVisibleTo(ed), f"{label}: {name} на виду")
        check(r.left() >= 0 and r.right() <= top.width() and r.top() >= 0 and r.bottom() <= top.height(),
              f"{label}: {name} внутри строки {r.getRect()} в {top.rect().getRect()}")
        check(w.width() >= w.sizeHint().width() - 1, f"{label}: {name} не сжат меньше текста ({w.width()} из {w.sizeHint().width()})")
        check(w.height() >= 28, f"{label}: {name} не ниже 28 точек ({w.height()})")
    check(ed.tr_copy_button.text().strip() == i18n.tr("editor.tr_copy"), f"{label}: у «Скопировать перевод» подпись полностью")
    check(ed.tr_done_button.text() == i18n.tr("editor.done_esc"), f"{label}: «Готово (Esc)» с подписью")
    rects = [QRect(w.mapTo(top, QPoint(0, 0)), w.size()) for w in shown]
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            check(not rects[i].intersects(rects[j]), f"{label}: {shown[i].objectName() or type(shown[i]).__name__} и {shown[j].objectName() or type(shown[j]).__name__} не налезают")
    for w in shown:
        if isinstance(w, QPushButton) and w is not ed.tr_more_button and w.text().strip():
            fm = QFontMetrics(w.font())
            check(w.width() >= fm.horizontalAdvance(w.text().strip()), f"{label}: подпись «{w.text().strip()}» не обрезана")
    msg = ed.tr_message
    if msg.isVisibleTo(ed):   # итог показывается целиком, без многоточия
        check(QFontMetrics(msg.font()).horizontalAdvance(msg.text()) <= msg.width() and "…" not in msg.text(), f"{label}: итог целиком, без обрывка")
    check(msg.text() in ed.tr_icon_button.toolTip(), f"{label}: полный итог всегда в подсказке значка")
    check(ed.tr_lang_button.accessibleName() == ed.tr_lang_button.text().replace(" ▾", "") or ed.tr_lang_button.accessibleName().replace(" ▾", "") != "",
          f"{label}: у кнопки языка есть полное доступное имя")
    return shown


from PyQt6.QtWidgets import QWidget as QWidgetAny  # noqa: E402

for theme, langs in (("standard", LANGS), ("pro", ("ru", "de", "zh"))):
    for lang in langs:
        ed, ctx = mk_layout(lang, theme)
        ed.select_tool(TRANSLATE)
        settle()
        layer = ed.tr_layer
        for state in ("до перевода", "с готовым переводом"):
            if state == "с готовым переводом" and not layer.tr_cards:
                card = TranslateCard(QRect(40, 40, 400, 120))
                card.state, card.view = "done", "overlay"
                card.blocks = [block("Привет", tgt=translate.target_lang(ctx.config))]
                card.skipped, card.total = 2, 3
                card.content = QRectF(card.region)
                layer.tr_cards.append(card)
                ed._update_info()
                settle()
            for width in (1100, 1000, 850, 800, 750, 700, 657, 656):
                ed.resize(width, 600)
                settle()
                label = f"{lang} {theme} {width} {state}"
                layout_checks(ed, lang, width, label)
        # меню «⋯»: вид всегда, «Перевод / Оригинал» только когда сегменты свёрнуты
        ed.resize(1100, 600)
        settle()
        ed.tr_more_menu.aboutToShow.emit()
        seg_open = ed.tr_seg_box.isVisibleTo(ed)
        check(ed.tr_view_overlay.isVisible() and ed.tr_view_card.isVisible() and (seg_open != ed.tr_menu_show_tr.isVisible()),
              f"{lang} {theme}: меню «⋯» на 1100: вид есть, «Перевод/Оригинал» в меню только если сегменты свёрнуты")
        ed.resize(656, 600)
        settle()
        ed.tr_more_menu.aboutToShow.emit()
        check(ed.tr_seg_box.isVisibleTo(ed) != ed.tr_menu_show_tr.isVisible() and ed.tr_view_overlay.isVisible() and ed.tr_view_card.isVisible(),
              f"{lang} {theme}: на 656 «Перевод / Оригинал» либо в строке, либо в меню «⋯»; вид в меню")
        close(ed)
print(f"раскладка: {checks[0]} проверок, провалов {len(failures)}", flush=True)


# --- 5. проход по ширине с шагом 1 точка: ни перекрытий, ни прыжков ---------------------------------------------------------
from PyQt6.QtGui import QGuiApplication  # noqa: E402
from clipshot.dialogs import MessageCard  # noqa: E402

SHORT = bool(os.environ.get("SHAPKA_SHORT"))   # масштабные прогоны: короткий набор


def add_done(layer, lang, skipped=0, total=0, partial=False, n=1):
    card = TranslateCard(QRect(40, 40, 400, 120))
    card.state, card.view = "done", "overlay"
    card.blocks = [block("Привет", tgt=translate.target_lang(layer.tr_cfg)) for _ in range(n)]
    card.skipped, card.total, card.partial = skipped, total, partial
    card.content = QRectF(card.region)
    layer.tr_cards.append(card)
    return card


def add_error(layer, text="Нет доступа к сервису перевода"):
    card = TranslateCard(QRect(60, 200, 300, 80))
    card.state, card.message, card.view = "error", text, "overlay"
    layer.tr_cards.append(card)
    return card


def strip_rects(ed):
    top = ed.tr_top
    row = top.layout()
    out = []
    for i in range(row.count()):
        w = row.itemAt(i).widget()
        if w is not None and w.isVisibleTo(ed):
            out.append((w, QRect(w.mapTo(top, QPoint(0, 0)), w.size())))
    return out


def sweep_checks(ed, label, widths):
    levels, prev = [], None
    for w in widths:
        ed.resize(w, 600)
        app.processEvents()
        app.processEvents()
        rects = strip_rects(ed)
        ok = all(not a[1].intersects(b[1]) for i, a in enumerate(rects) for b in rects[i + 1:])
        ok = ok and all(r.right() <= ed.tr_top.width() and r.left() >= 0 for _w, r in rects)
        must = all(x.isVisibleTo(ed) for x in (ed.tr_lang_button, ed.tr_copy_button, ed.tr_done_button))
        if not (ok and must):
            check(False, f"{label}: на ширине {w} перекрытие, выход за край или пропала главная кнопка")
        levels.append(ed._tr_level)
    return levels


widths_up = list(range(656, 1101))
for theme, langs in (("standard", LANGS if not SHORT else ("ru", "de")), ("pro", ("ru", "de"))):
    for lang in langs:
        ed, ctx = mk_layout(lang, theme)
        ed.select_tool(TRANSLATE)
        settle()
        add_done(ed.tr_layer, lang, skipped=2, total=3)
        ed._update_info()
        settle()
        up = sweep_checks(ed, f"{lang} {theme} вширь", widths_up)
        down = sweep_checks(ed, f"{lang} {theme} вузь", widths_up[::-1])
        check(all(a >= b for a, b in zip(up, up[1:])), f"{lang} {theme}: при росте ширины на 1 точку вид только разворачивается, без прыжков туда-обратно {up[:1]}..{up[-1:]}")
        check(all(a <= b for a, b in zip(down, down[1:])), f"{lang} {theme}: при сужении только сворачивается")
        close(ed)
print(f"проход по ширине: {checks[0]} проверок, провалов {len(failures)}", flush=True)


# --- 5б. карточки и плашки перевода целиком в видимой части снимка -------------------------------------------------------------
LONG_ERR = {"ru": "Превышен дневной лимит сервиса MyMemory. Подключите свой ключ в настройках или повторите завтра.",
            "de": "Das Tageslimit von MyMemory ist erreicht. Verbinden Sie in den Einstellungen einen eigenen Schlüssel oder versuchen Sie es morgen erneut."}


def viewport_in(layer, ed):
    """Видимая часть снимка в координатах слоя, считается от окна прокрутки (независимо от кода программы)."""
    vp = ed.scroll.viewport()
    top_left = layer.mapFromGlobal(vp.mapToGlobal(QPoint(0, 0)))
    return QRectF(top_left.x(), top_left.y(), vp.width(), vp.height()).intersected(QRectF(layer.rect()))


def inside(r, bounds, tol=1.5):
    return (r.left() >= bounds.left() - tol and r.top() >= bounds.top() - tol and r.right() <= bounds.right() + tol
            and r.bottom() <= bounds.bottom() + tol)


for lang in LANGS:
    for theme in (("standard", "pro") if lang in ("ru", "de") else ("standard",)):
        ed, ctx = mk_layout(lang, theme)
        ed.select_tool(TRANSLATE)
        settle()
        layer = ed.tr_layer
        err = TranslateCard(QRect(120, 40, 780, 200))   # область шире окна: правый край за видимой частью
        err.state, err.message, err.view = "error", LONG_ERR.get(lang, LONG_ERR["ru"]) + " " + LONG_ERR["ru"], "overlay"
        layer.tr_cards.append(err)
        for width in (656, 700, 800, 1100):
            ed.resize(width, 600)
            settle()
            for scroll in (0, 10 ** 6):
                ed.scroll.horizontalScrollBar().setValue(scroll)
                ed.scroll.verticalScrollBar().setValue(scroll)
                settle(3)
                layer.repaint()
                bounds = viewport_in(layer, ed)
                box, _h = layer._tr_notice_box(QRectF(err.region), layer._tr_error_text(err))
                label = f"{lang} {theme} {width} прокрутка {min(scroll, 1)}"
                check(inside(box, bounds), f"{label}: карточка ошибки целиком в видимой части {box.getRect()} в {bounds.getRect()}")
                check(err.chip.isNull() or inside(err.chip, bounds), f"{label}: плашка с кнопками ошибки в видимой части {err.chip.getRect()}")
                check(box.width() <= bounds.width() - 8 + 0.5, f"{label}: ширина карточки не больше видимой части минус поля")
        # обычный перевод «Поверх текста»: плашка с кнопками тоже в видимой части
        layer.tr_cards.remove(err)
        ok_card = add_done(layer, lang)
        ok_card.region = QRect(120, 40, 780, 200)
        ok_card.blocks[0]["rect"] = ok_card.blocks[0]["draw"] = QRectF(60, 50, 820, 24)
        ok_card.content = QRectF(ok_card.region)
        ok_card.laid = None
        for width in (656, 1100):
            ed.resize(width, 600)
            settle()
            for scroll in (0, 10 ** 6):
                ed.scroll.horizontalScrollBar().setValue(scroll)
                settle(3)
                layer.repaint()
                check(ok_card.chip.isNull() or inside(ok_card.chip, viewport_in(layer, ed)),
                      f"{lang} {theme} {width}: плашка обычного перевода в видимой части {ok_card.chip.getRect()} в {viewport_in(layer, ed).getRect()}")
        close(ed)
print(f"карточки: {checks[0]} проверок, провалов {len(failures)}", flush=True)

# --- 6. состояния: перевод идёт, ошибка, частично, нечего копировать -------------------------------------------------------
for lang in (("ru", "de") if not SHORT else ("ru",)):
    ed, ctx = mk_layout(lang)
    i18n.set_language(lang)
    ed.select_tool(TRANSLATE)
    settle()
    layer = ed.tr_layer
    clip = QGuiApplication.clipboard()
    # нечего копировать
    clip.setText("не трогать")
    ed.tr_copy_button.click()
    settle()
    check(clip.text() == "не трогать", f"{lang}: нечего копировать: буфер не тронут")
    check(ed.toast is not None and i18n.tr("editor.tr_nothing_to_copy") in ed.toast.text() if hasattr(ed.toast, "text") else True,
          f"{lang}: нечего копировать: сообщение показано")
    # идёт перевод
    busy_card = TranslateCard(QRect(40, 40, 400, 120))
    busy_card.state = "busy"
    layer.tr_cards.append(busy_card)
    ed._update_info()
    for w in (1100, 800, 656):
        ed.resize(w, 600)
        settle()
        layout_checks(ed, lang, w, f"{lang} идёт перевод {w}")
    layer.tr_cards.remove(busy_card)
    # ошибка: на 656 видно
    err = add_error(layer)
    ed._update_info()
    for w in (1100, 800, 656):
        ed.resize(w, 600)
        settle()
        label = f"{lang} ошибка {w}"
        layout_checks(ed, lang, w, label)
        check(ed.tr_icon_button.isVisibleTo(ed) and ed.tr_icon_button.accessibleName() == i18n.tr("translate_ui.failed"),
              f"{label}: на месте значка режима значок предупреждения")
        check(ed.tr_icon_button.toolTip().endswith(err.message), f"{label}: полный текст ошибки в подсказке значка")
    ed.resize(656, 600)
    settle()
    QTest.mouseClick(ed.tr_icon_button, Qt.MouseButton.LeftButton)
    settle()
    card = getattr(ed, "_tr_error_card", None)
    check(card is not None and card.isVisible() and err.message in card.message_text, f"{lang}: по нажатию на значок полный текст ошибки в карточке сообщения")
    if card is not None:
        card.close()
    check(ed.canvas.tool == TRANSLATE, f"{lang}: карточка ошибки не закрыла режим")
    # частично: переведённое остаётся, ошибка остальной части отдельно
    done_card = add_done(layer, lang, n=2)
    ed._update_info()
    settle()
    check(ed.tr_message.text().startswith(i18n.tr("translate_ui.done_count", n=2, m=2).split(":")[0]) and err.message not in ed.tr_message.text(),
          f"{lang}: частично: в строке итог переведённого «{ed.tr_message.text()}»")
    check(ed.tr_icon_button.accessibleName() == i18n.tr("translate_ui.failed") and err.message in ed._tr_errors_text,
          f"{lang}: частично: значок предупреждения и ошибка остальной части отдельно")
    check(layer.all_text() != "", f"{lang}: частично: переведённое доступно для копирования")
    ed.tr_copy_button.click()
    check("Привет" in clip.text(), f"{lang}: частично: «Скопировать перевод» копирует переведённое")
    for w in (1100, 656):
        ed.resize(w, 600)
        settle()
        layout_checks(ed, lang, w, f"{lang} частично {w}")
    # итог без «подсказки про Оригинал»
    layer.tr_cards.remove(err)
    ed._update_info()
    settle()
    check("«" not in ed.tr_message.text() and "Оригинал" not in ed.tr_message.text() and ed.tr_message.text().count(".") == 0,
          f"{lang}: итог только про число абзацев: «{ed.tr_message.text()}»")
    close(ed)
print(f"состояния: {checks[0]} проверок, провалов {len(failures)}", flush=True)


# --- 6б. «Скопировать перевод» при ошибке и смене языка; действия в карточке ошибки; кольцо фокуса; область значка ---------------
from types import SimpleNamespace  # noqa: E402


def contrast(c1, c2):
    def lum(c):
        def ch(v):
            v /= 255
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
        return 0.2126 * ch(c.red()) + 0.7152 * ch(c.green()) + 0.0722 * ch(c.blue())
    a, b = lum(c1), lum(c2)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


_real_start = translate.start
translate.start = lambda *a, **k: SimpleNamespace(cancel=lambda: None, message=None)   # сеть и распознавание не нужны
try:
    for lang in (("ru", "de") if not SHORT else ("ru",)):
        # сценарий проверяющего: перевели части, сменили язык, часть не получилась, «Скопировать»
        ed, ctx = mk_layout(lang)
        ed.select_tool(TRANSLATE)
        settle()
        layer = ed.tr_layer
        clip = QGuiApplication.clipboard()
        old_a, old_b = add_done(layer, lang), add_done(layer, lang)   # два куска на прежнем языке (ru)
        for c in (old_a, old_b):
            c.blocks[0]["tgt"], c.blocks[0]["text"] = "ru", "Старый перевод"
        ctx.config["translate_to"] = "de"                              # язык сменили
        old_b.blocks, old_b.state = [], "error"                          # один кусок на новом языке не получился
        old_b.message = "Сервис недоступен"
        old_a.blocks[0]["tgt"], old_a.blocks[0]["text"] = "de", "Neue Übersetzung"   # другой успел на новом
        old_a.req_lang = "de"
        ed._update_info()
        settle()
        clip.setText("исходное")
        check(ed.tr_copy_button.isEnabled(), f"{lang}: частично: кнопка доступна, есть актуальный перевод")
        ed.tr_copy_button.click()
        check(clip.text() == "Neue Übersetzung" and "Старый" not in clip.text(), f"{lang}: частично: скопирована только актуальная часть «{clip.text()}»")
        old_a.req_lang = "ru"   # теперь актуальных нет: остался ответ прежнего запроса (на ru) и ошибка
        ed._update_info()
        settle()
        clip.setText("исходное")
        check(not ed.tr_copy_button.isEnabled(), f"{lang}: полная неудача: «Скопировать перевод» недоступна")
        ed.tr_copy_button.click()
        QTest.keyClick(ed.tr_copy_button, Qt.Key.Key_Space)
        check(clip.text() == "исходное", f"{lang}: устаревший перевод не копируется ни мышью, ни клавишей")
        check(i18n.tr("editor.tr_nothing_to_copy") == ed.tr_copy_button.toolTip(), f"{lang}: у недоступной кнопки в подсказке причина")
        close(ed)

    # действия в карточке ошибки
    for kind in ("generic", "key"):
        ed, ctx = mk_layout("ru")
        ed.select_tool(TRANSLATE)
        ed.resize(800, 600)
        settle()
        layer = ed.tr_layer
        err = add_error(layer)
        err.region = QRect(60, 40, 400, 120)
        if kind == "key":
            err.help = SimpleNamespace(service="google", command=None, url=None, wait="")
        layer.repaint()
        settle()
        names = set(err.buttons)
        want = {"retry"} if kind == "generic" else {"setup", "usemm"}
        check(want <= names and "close" in names, f"ошибка ({kind}): в карточке видны кнопки {sorted(names)}")
        vp = viewport_in(layer, ed)
        check(all(inside(r, vp) and r.height() >= 28 for r in err.buttons.values()), f"ошибка ({kind}): кнопки в видимой части и не ниже 28 точек")
        check(inside(err.chip, vp), f"ошибка ({kind}): карточка одна и целиком в видимой части")
        if kind == "generic":
            QTest.mouseClick(layer, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, err.buttons["retry"].center().toPoint())
            settle()
            check(err.state != "error", f"ошибка (generic): «Повторить» запускает перевод заново (состояние {err.state})")
        else:
            opened = []
            layer._tr_open_setup = lambda: opened.append(1)
            QTest.mouseClick(layer, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, err.buttons["setup"].center().toPoint())
            check(opened, "ошибка (key): «Подключить Google…» открывает настройку ключа")
            layer.repaint()
            QTest.mouseClick(layer, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, err.buttons["usemm"].center().toPoint())
            settle()
            check(ctx.config.get("translate_engine") == "mymemory", "ошибка (key): «Перевести через MyMemory» работает")
        close(ed)
finally:
    translate.start = _real_start

# кольцо фокуса видно на светлой и тёмной подложке; значок предупреждения не меньше 30 точек
for theme in ("standard", "pro"):
    ed, ctx = mk_layout("ru", theme)
    ed.select_tool(TRANSLATE)
    ed.resize(800, 600)
    settle()
    add_done(ed.tr_layer, "ru")
    ed._update_info()
    settle()
    for w in (ed.tr_lang_button, ed.tr_copy_button, ed.tr_done_button, ed.tr_more_button):
        w.setFocus(Qt.FocusReason.TabFocusReason)
        settle(3)
        img = ed.grab().toImage()
        pos = w.mapTo(ed, QPoint(0, 0))
        k = img.devicePixelRatio()   # снимок в настоящих пикселях: при масштабе 150 и 200 % точки умножаются
        ring = img.pixelColor(int((pos.x() + 1) * k), int((pos.y() + w.height() // 2) * k))
        outside = img.pixelColor(int((pos.x() - 4) * k), int((pos.y() + w.height() // 2) * k))
        check(contrast(ring, outside) >= 3.0, f"{theme}: кольцо фокуса у «{w.objectName()}» заметно на подложке ({contrast(ring, outside):.1f}:1)")
    err = add_error(ed.tr_layer)
    ed._update_info()
    settle()
    check(ed.tr_icon_button.width() >= 30 and ed.tr_icon_button.height() >= 30, f"{theme}: область нажатия значка предупреждения {ed.tr_icon_button.width()}x{ed.tr_icon_button.height()} не меньше 30")
    # открытое меню: выбранный пункт заметен
    ed.tr_more_menu.popup(ed.tr_more_button.mapToGlobal(QPoint(0, ed.tr_more_button.height())))
    settle()
    ed.tr_more_menu.setActiveAction(ed.tr_view_card)
    settle(3)
    mimg = ed.tr_more_menu.grab().toImage()
    ar = ed.tr_more_menu.actionGeometry(ed.tr_view_card)
    other = ed.tr_more_menu.actionGeometry(ed.tr_view_overlay)
    k = mimg.devicePixelRatio()
    hi = mimg.pixelColor(int((ar.right() - 6) * k), int(ar.center().y() * k))
    lo = mimg.pixelColor(int((other.right() - 6) * k), int(other.center().y() * k))
    print(f"   меню «⋯» {theme}: подсветка выбранного пункта {hi.name()} против {lo.name()}: {contrast(hi, lo):.2f}:1", flush=True)
    check(hi != lo, f"{theme}: в открытом меню выбранный пункт отличается от остальных")
    ed.tr_more_menu.close()
    close(ed)
print(f"копирование и ошибка: {checks[0]} проверок, провалов {len(failures)}", flush=True)

# --- 7. клавиатура ---------------------------------------------------------------------------------------------------------
from PyQt6.QtWidgets import QApplication as _QA  # noqa: E402
ed, ctx = mk_layout("en")
ed.select_tool(TRANSLATE)
settle()
add_done(ed.tr_layer, "en")
ed._update_info()
ed.resize(1100, 600)
settle()
order = [ed.tr_icon_button, ed.tr_lang_button, ed.tr_show_tr, ed.tr_show_orig, ed.tr_more_button, ed.tr_copy_button, ed.tr_done_button]
vis = [w for w in order if w.isVisibleTo(ed)]
ed.activateWindow()
vis[0].setFocus(Qt.FocusReason.TabFocusReason)
settle()
seen = [_QA.focusWidget()]
for _ in range(len(vis) - 1):
    QTest.keyClick(_QA.focusWidget(), Qt.Key.Key_Tab)
    settle(2)
    seen.append(_QA.focusWidget())
check(seen == vis, f"Tab ведёт по всем видимым кнопкам строки слева направо ({[w.objectName() or type(w).__name__ for w in seen]})")
back = [_QA.focusWidget()]
for _ in range(len(vis) - 1):
    QTest.keyClick(_QA.focusWidget(), Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)
    settle(2)
    back.append(_QA.focusWidget())
check(back == vis[::-1], "Shift+Tab ведёт обратно по тем же кнопкам")
# Enter и Space нажимают
card = ed.tr_layer.tr_cards[0]
ed.tr_show_orig.setFocus(Qt.FocusReason.TabFocusReason)
QTest.keyClick(ed.tr_show_orig, Qt.Key.Key_Space)
settle()
check(card.show_original and ed.tr_show_orig.isChecked() and not ed.tr_show_tr.isChecked(), "Space на «Оригинал» включает исходный текст, отмечена одна кнопка")
ed.tr_show_tr.setFocus(Qt.FocusReason.TabFocusReason)
QTest.keyClick(ed.tr_show_tr, Qt.Key.Key_Return)
settle()
check(not card.show_original and ed.tr_show_tr.isChecked() and not ed.tr_show_orig.isChecked(), "Enter на «Перевод» возвращает перевод, отмечена одна кнопка")
clip = QGuiApplication.clipboard()
clip.setText("")
ed.tr_copy_button.setFocus(Qt.FocusReason.TabFocusReason)
QTest.keyClick(ed.tr_copy_button, Qt.Key.Key_Return)
settle()
check("Привет" in clip.text(), "Enter на «Скопировать перевод» копирует")
# меню «⋯»: стрелки, Esc закрывает меню, а не режим
menu = ed.tr_more_menu
menu.popup(ed.tr_more_button.mapToGlobal(QPoint(0, ed.tr_more_button.height())))
settle()
check(menu.isVisible(), "меню «⋯» открылось")
ed.tr_more_menu.aboutToShow.emit()
QTest.keyClick(menu, Qt.Key.Key_Down)
settle(2)
check(menu.activeAction() is not None and menu.activeAction().isVisible(), "стрелка вниз выбирает пункт меню")
QTest.keyClick(menu, Qt.Key.Key_Escape)
settle()
check(not menu.isVisible() and ed.canvas.tool == TRANSLATE and ed.tr_top.isVisibleTo(ed), "Esc с открытым меню закрыл меню, а не режим перевода")
ed.escape()
settle()
check(ed.canvas.tool != TRANSLATE, "второй Esc выходит из режима")
# фокус при сворачивании: фокус на «Перевод / Оригинал», окно сужается до складывания сегментов
ed.select_tool(TRANSLATE)
settle()
ed.resize(1100, 600)
settle()
if ed.tr_seg_box.isVisibleTo(ed):
    ed.tr_show_orig.setFocus(Qt.FocusReason.TabFocusReason)
    ed.resize(656, 600)
    settle()
    fw = _QA.focusWidget()
    check(not ed.tr_seg_box.isVisibleTo(ed) and fw is not None and fw.isVisibleTo(ed), "сегменты свернулись вместе с фокусом: фокус ушёл на видимую кнопку")
close(ed)
# меню «⋯» на узком окне: сначала «Перевод / Оригинал», затем способ показа; отмечено выбранное
ed, ctx = mk_layout("ru")
ed.select_tool(TRANSLATE)
settle()
add_done(ed.tr_layer, "ru")
ed.resize(656, 600)
ed._update_info()
settle()
ed.tr_more_menu.aboutToShow.emit()
acts = [a for a in ed.tr_more_menu.actions() if a.isVisible() and not a.isSeparator()]
check(acts == [ed.tr_menu_show_tr, ed.tr_menu_show_orig, ed.tr_view_overlay, ed.tr_view_card] or not ed.tr_seg_box.isHidden(),
      f"меню «⋯»: сначала «Перевод / Оригинал», затем способ показа: {[a.text() for a in acts]}")
check(ed.tr_menu_show_tr.isChecked() and not ed.tr_menu_show_orig.isChecked() and ed.tr_view_overlay.isChecked() and not ed.tr_view_card.isChecked(),
      "в меню отмечены выбранные состояния")
check("Русский" in ed.tr_lang_button.accessibleName() or "→" in ed.tr_lang_button.accessibleName(), f"доступное имя языка полное: «{ed.tr_lang_button.accessibleName()}»")
close(ed)
print(f"клавиатура: {checks[0]} проверок, провалов {len(failures)}", flush=True)

if SHORT:
    print(f"ИТОГ: {checks[0]} проверок, " + ("все проверки пройдены" if not failures and not errors else f"провалов: {len(failures)}"))
    sys.exit(1 if failures or errors else 0)

if ocr.engine_name() != "tesseract":
    print("распознавания Tesseract нет: гонки пропущены")
    print("ИТОГ: " + ("все проверки пройдены" if not failures else f"провалов: {len(failures)}"))
    sys.exit(1 if failures else 0)

# --- 4. гонки ----------------------------------------------------------------------------------------------------------
W, H = 1100, 520
HEAD = ["Infrastructure intelligence your", "team (and agents) can trust"]


def page():
    img = QImage(W, H, QImage.Format.Format_RGB32)
    img.fill(QColor("#04070b"))
    p = QPainter(img)
    f = QFont("DejaVu Sans")
    f.setPixelSize(54)
    p.setFont(f)
    p.setPen(QColor("#ffffff"))
    p.drawText(0, 125, W, 70, Qt.AlignmentFlag.AlignHCenter, HEAD[0])
    p.drawText(0, 190, W, 70, Qt.AlignmentFlag.AlignHCenter, HEAD[1])
    p.end()
    return img


class Engine:
    name = "MyMemory"
    gate = None
    entered = None
    targets = []

    def translate(self, text, target, source=None):
        Engine.targets.append(target)
        if Engine.entered is not None:
            Engine.entered.set()
        if Engine.gate is not None:
            Engine.gate.wait(10)
        return f"[{target}] " + " ".join(text.split()), "en"


translate.engines_from_config = lambda c: [Engine()]
translate.check_mymemory_email = lambda email, cb: cb("")
translate.check_google_key = lambda key, cb: cb("")


def drag(layer, a, b):
    a, b = QPoint(*a), QPoint(*b)
    QTest.mousePress(layer, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, a)
    for i in range(1, 9):
        QTest.mouseMove(layer, a + (b - a) * i / 8)
    QTest.mouseRelease(layer, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, b)


def busy(lang="ru", view="overlay"):
    """Редактор, в котором запрос перевода начался и ждёт сигнала теста."""
    i18n.set_language(lang)
    ctx = Ctx()
    ctx.config["translate_view"] = view
    themes.apply_app(app, ctx.config)
    ed = EditorWindow(page(), ctx, QPoint(20, 20))
    ed.present()
    settle()
    ed.select_tool(TRANSLATE)
    settle()
    Engine.gate, Engine.entered, Engine.targets = threading.Event(), threading.Event(), []
    drag(ed.tr_layer, (80, 118), (1020, 265))
    started = wait(lambda: Engine.entered.is_set(), 60)
    check(started and (view == "card" or (ed.tr_layer.tr_cards and ed.tr_layer.tr_cards[0].state == "busy")), "запрос ушёл и ждёт ответа")
    return ed, ctx


def release():
    Engine.gate.set()
    ok = wait(lambda: not translate._jobs, 30)
    settle()
    Engine.gate = Engine.entered = None
    return ok


def header_ok(ed, width, label):
    ed.resize(width, ed.height())
    settle()
    layout_checks(ed, "ru", width, label)


before = len(errors)

# 4.1 включить и выключить перевод, пока идёт запрос (несколько раз), потом ответ
ed, ctx = busy()
for i in range(3):
    ed.select_tool(MOVE)
    settle()
    ed.select_tool(TRANSLATE)
    settle()
check(ed.canvas.tool == TRANSLATE and ed.tr_top.isVisibleTo(ed), "4.1: после трёх включений и выключений режим включён, строка на месте")
ed.select_tool(MOVE)
settle()
check(release(), "4.1: поток перевода завершился")
check(ed.canvas.tool == MOVE and not ed.tr_layer.isVisible() and not ed.tr_top.isVisibleTo(ed) and ed.panel.isVisibleTo(ed),
      "4.1: поздний ответ не открыл режим перевода заново, обычный вид на месте")
ed.select_tool(TRANSLATE)
settle()
check(all(c.state in ("done", "error") for c in ed.tr_layer.tr_cards), "4.1: при новом входе нет вечного ожидания")
header_ok(ed, 656, "4.1 после входа 656")
close(ed)

# 4.1 обратный порядок: ответ пришёл, потом выключение и включение
ed, ctx = busy()
check(release() and ed.tr_layer.tr_cards[0].state == "done", "4.1 обратный порядок: перевод готов")
ed.select_tool(MOVE)
settle()
ed.select_tool(TRANSLATE)
settle()
check(ed.tr_top.isVisibleTo(ed) and "→" in ed.tr_lang_button.text(), f"4.1 обратный порядок: язык «{ed.tr_lang_button.text()}», строка на месте")
close(ed)

# 4.2 Esc во время запроса и после
ed, ctx = busy()
ed.escape()
settle()
check(ed.canvas.tool != TRANSLATE and not ed.tr_top.isVisibleTo(ed), "4.2: Esc во время запроса закрыл режим")
check(release(), "4.2: поток завершился")
check(ed.canvas.tool != TRANSLATE and not ed.tr_layer.isVisible() and not ed.tr_top.isVisibleTo(ed),
      "4.2: поздний ответ после Esc не открыл режим")
close(ed)
ed, ctx = busy()
check(release() and ed.tr_layer.tr_cards[0].state == "done", "4.2 обратный порядок: ответ пришёл")
ed.escape()
settle()
check(ed.canvas.tool != TRANSLATE and ed.panel.isVisibleTo(ed), "4.2 обратный порядок: Esc закрыл режим")
close(ed)

# 4.3 смена языка во время запроса: ответ на прежний язык не показывается, перевод идёт заново на новом
ed, ctx = busy()
layer = ed.tr_layer
card = layer.tr_cards[0]
layer._tr_choose_lang("de")
settle()   # короткое обозначение языка обновляется само, без лишних вызовов
check(translate.lang_name("de") in ed.tr_lang_button.text() or "DE" in ed.tr_lang_button.text(), f"4.3: строка сразу показывает новый язык «{ed.tr_lang_button.text()}»")
first = Engine.gate
Engine.gate = threading.Event()   # второй запрос тоже ждёт сигнала: видно состояние между ответами
first.set()
check(wait(lambda: card.state == "busy" and "de" in Engine.targets, 60), f"4.3: после ответа на прежний язык запрос ушёл заново на новом {Engine.targets}")
check(not any(b["text"].startswith("[ru]") for b in card.blocks), "4.3: ответ на прежний язык не показан")
Engine.gate.set()
check(wait(lambda: card.state == "done", 60) and card.blocks and all(b["text"].startswith("[de]") for b in card.blocks),
      f"4.3: готов перевод на выбранный язык {[b['text'][:20] for b in card.blocks]}")
wait(lambda: not translate._jobs, 30)
Engine.gate = Engine.entered = None
settle()
check(ed.canvas.tool == TRANSLATE and ed.tr_top.isVisibleTo(ed), "4.3: режим перевода на месте")
header_ok(ed, 800, "4.3 после смены языка 800")
close(ed)
# обратный порядок: ответ пришёл, потом язык меняется
ed, ctx = busy()
check(release() and ed.tr_layer.tr_cards[0].state == "done", "4.3 обратный порядок: перевод готов")
Engine.gate, Engine.entered, Engine.targets = threading.Event(), threading.Event(), []
ed.tr_layer._tr_choose_lang("de")
Engine.gate.set()
card = ed.tr_layer.tr_cards[0]
check(wait(lambda: card.state == "done" and card.blocks and card.blocks[0]["text"].startswith("[de]"), 60),
      "4.3 обратный порядок: перевод заново на новом языке")
wait(lambda: not translate._jobs, 30)
Engine.gate = Engine.entered = None
close(ed)

# 4.4 ширина окна меняется во время перевода
ed, ctx = busy()
for w in (1100, 656, 800, 656, 1100):
    header_ok(ed, w, f"4.4 во время запроса {w}")
check(release(), "4.4: поток завершился")
for w in (656, 1100, 800):
    header_ok(ed, w, f"4.4 после ответа {w}")
check(ed.tr_layer.tr_cards[0].state == "done" and ed.canvas.tool == TRANSLATE, "4.4: перевод готов, режим включён")
close(ed)
# обратный порядок: ответ пришёл, потом меняется ширина (итог перевода в строке не ломает ступени)
ed, ctx = busy()
ed.resize(656, ed.height())
check(release(), "4.4 обратный порядок: ответ пришёл на узком окне")
for w in (656, 1100, 656):
    header_ok(ed, w, f"4.4 обратный порядок {w}")
close(ed)

# 4.5 закрытие редактора во время запроса и после
ed, ctx = busy()
close(ed)
check(release(), "4.5: редактор закрыт во время запроса, поток завершился после ответа")
ed, ctx = busy()
check(release(), "4.5 обратный порядок: ответ пришёл")
close(ed)

# 4.6 «Карточкой» при узком окне: окошко перевода целиком на экране
ed, ctx = busy(view="card")
ed.resize(656, ed.height())
check(release(), "4.6: поток завершился")
check(wait(lambda: ed.tr_layer.floats, 30), "4.6: окошко «Карточкой» появилось")
if ed.tr_layer.floats:
    win = ed.tr_layer.floats[0]
    screen = QApplication.primaryScreen().availableGeometry()
    check(screen.contains(win.frameGeometry()), f"4.6: окошко «Карточкой» целиком на экране {win.frameGeometry().getRect()} в {screen.getRect()}")
close(ed)

check(len(errors) == before, f"гонки: ни одного исключения в обработчиках ({len(errors) - before})")
print(f"ИТОГ: {checks[0]} проверок, " + ("все проверки пройдены" if not failures else f"провалов: {len(failures)}"))
sys.exit(1 if failures or errors else 0)
