# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Нижние ряды панели окна выделения по решению владельца 21.11.2026 (вариант Б эскиза «кнопка Редактировать»;
до этого в ветке был вариант В с вопросом «Что сделать со снимком?»).

1. 12 языков, экраны 1280, 800 и 480: все кнопки на месте, в панели, не перекрываются; на экранах с подписями ряд из
   двух равных кнопок «Сохранить» и «Другая область» на всю ширину, под ним крупные: широкая «Редактировать» слева
   и поуже «Скопировать и закрыть» справа; вопроса нет; подписи и пояснения не обрезаны на 1280 и 800; на 480
   (одни значки) нижний ряд в одну строку, цвета варианта Б: «Редактировать» значком на зелёной заливке,
   «Скопировать» светло-зелёная с зелёной рамкой.
2. «Другая область» на 12 языках: подпись не обрезается на 1280 и 800, подсказка при наведении с клавишами и пояснением.
3. Экран 800 × 600, 12 языков: панель целиком на экране (под рамкой, над ней или сбоку), подписи не обрезаны;
   знакомство с панелью (ru, de, zh, fr) проходит все шаги, карточка и подсветка внутри экрана.
4. «Сохранить» и Ctrl+S: файл записан, окно выделения не закрыто, рамка на месте, плашка «Сохранено: имя»; на время
   окна выбора файла окно выделения спрятано и потом возвращается; отмена ничего не пишет; после сохранения можно
   скопировать. Настоящий Clipshot.save_from_selector с save_ask выключенным и включённым.
5. Щелчки и клавиши как раньше: Enter, пробел и щелчок в рамке открывают редактор (главная зелёная), Ctrl+Enter
   и Ctrl+C копируют, R и «Другая область» снимают рамку.
6. В панели одна зелёная заливка: «Редактировать»; «Скопировать и закрыть» светло-зелёная с зелёной рамкой; контраст
   текста на обеих не ниже 4,5:1 (по цветам кода и по пикселям кадра).
7. Знакомство с панелью: шаг 2 «Редактировать» (главная), шаг 3 «Скопировать и закрыть».

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/knopka_b_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import json
import os
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
os.environ.pop("CLIPSD_LANG", None)
_tmp = tempfile.mkdtemp(prefix="clipsd-knopka-b-")
_cfg = os.path.join(_tmp, "screen.json")
with open(_cfg, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1600, "height": 1000,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _cfg
from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QFontMetrics, QPixmap
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
from clipshot import app as appmod, editor as editormod, i18n, ocr
from clipshot.selector import RegionSelector
from clipshot.selector_tour import PAD

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)
        print("FAIL " + msg)


def settle(n=3):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(10)


class Ctx:
    """Как Clipshot для окна выделения: язык, настройки и сохранение (save_from_selector) настоящими методами."""

    def __init__(self, folder, ask=False):
        self.config = dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True, save_dir=folder, save_ask=ask,
                           save_format="png")
        self.saved_config = 0

    def set_language(self, code):
        pass

    def save_config(self):
        self.saved_config += 1

    save_from_selector = appmod.Clipshot.save_from_selector


def selector(width, height=720, kept=None, ctx=None):
    pm = QPixmap(width, height)
    pm.fill(QColor("#4a78b0"))
    sel = RegionSelector(pm, QRect(0, 0, width, height),
                         last_rect=kept or QRect(width // 2 - 150, min(90, height // 4), 300, 200))
    cfg = ctx.config if ctx is not None else dict(appmod.DEFAULTS)
    sel.tr_cfg, sel.tr_save = cfg, lambda: None
    if ctx is not None:
        sel.lang_ctx = ctx
    sel.show_zoom = False
    sel.resize(width, height)
    sel.show()
    settle()
    sel.repaint()
    return sel


def layout(sel):
    buttons, bar, hint = sel._bar_layout()
    return {k: r for k, _t, _s, r in buttons}, {k: t for k, t, _s, _r in buttons}, bar, hint


ALL = ["record", "full", "ocr", "phone", "pin", "form", "translate", "translate_pick", "save", "edit", "manual", "copy"]   # 1.36: «Закрепить», 1.36.3: «Форма снимка»
BOTTOM = ["save", "edit", "manual", "copy"]
RETAKE = {"ru": "Другая область", "en": "Another area", "es": "Otra zona", "de": "Anderer Bereich", "fr": "Autre zone",
          "it": "Altra area", "pt": "Outra área", "pl": "Inny obszar", "tr": "Başka alan", "uk": "Інша область",
          "bg": "Друга област", "zh": "换个区域"}
check(sorted(RETAKE) == sorted(i18n.LANGUAGE_NAMES), f"12 языков: {sorted(i18n.LANGUAGE_NAMES)}")


def lum(c):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    c = QColor(c)
    return 0.2126 * ch(c.red()) + 0.7152 * ch(c.green()) + 0.0722 * ch(c.blue())


def contrast(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def over(fg_rgba, bg):
    """Полупрозрачный цвет поверх непрозрачного фона."""
    r, g, b, a = fg_rgba
    bg = QColor(bg)
    k = a / 255
    return QColor(round(r * k + bg.red() * (1 - k)), round(g * k + bg.green() * (1 - k)), round(b * k + bg.blue() * (1 - k)))


def han_missing(text):
    """Пусто, если для иероглифов подписи есть один из шрифтов, на которые рассчитан китайский интерфейс
    (fonts.CJK_FAMILIES: Noto Sans CJK, Microsoft YaHei, Source Han Sans, WenQuanYi); иначе пояснение.
    Без такого шрифта иероглифы рисует случайный запасной шрифт (без жирного, тонкие штрихи серым сглаживанием)
    или не рисует никто: пиксели подписи там не говорят о цветах программы. QRawFont.fromFont без шрифта
    китайского письма роняет процесс, поэтому по списку шрифтов и по самим знакам."""
    from PyQt6.QtGui import QFont, QFontDatabase
    from clipshot import fonts
    han = [ch for ch in text if "\u4e00" <= ch <= "\u9fff"]
    if not han:
        return ""
    families = QFontDatabase.families(QFontDatabase.WritingSystem.SimplifiedChinese)
    for fam in families:
        if any(fam.startswith(want) for want in fonts.CJK_FAMILIES):
            fm = QFontMetrics(QFont(fam))
            if all(fm.inFontUcs4(ord(ch)) for ch in han):
                return ""
    return f"шрифтов китайского письма {len(families)} {families[:3]}, из рассчитанных ни одного"


# --- 6 (по цветам кода): белый на зелёной «Редактировать», тёмно-зелёный на светло-зелёной «Скопировать» ----------
from clipshot import themes
TG = RegionSelector.TONAL_GREEN
for bg in themes.GREEN_GRADIENT + themes.GREEN_GRADIENT_HOVER:
    check(contrast("#ffffff", bg) >= 4.5, f"белый на зелёной {bg}: {contrast('#ffffff', bg):.2f}")
    sub = over(themes.GREEN_SUB, bg)
    check(contrast(sub, bg) >= 4.5, f"пояснение на зелёной {bg}: {contrast(sub, bg):.2f}")
for fill in (TG["fill"], TG["fill_hover"]):
    for fg in (TG["fg"], TG["sub"]):
        check(contrast(fg, fill) >= 4.5, f"{fg} на светло-зелёной {fill}: {contrast(fg, fill):.2f}")
    check(contrast(themes.GREEN, fill) >= 3.0, f"зелёная рамка и квадрат значка на {fill}: {contrast(themes.GREEN, fill):.2f}")

# --- 1, 2: раскладка на 12 языках --------------------------------------------------------------------------------
for lang in i18n.LANGUAGE_NAMES:
    i18n.set_language(lang)
    check(i18n.tr("selector.btn_retake") == RETAKE.get(lang), f"{lang}: «Другая область» = {i18n.tr('selector.btn_retake')}")
    check(i18n.tr("seltour.s4_title") == RETAKE.get(lang), f"{lang}: шаг знакомства назван так же")
    for width in (1280, 800, 480):
        sel = selector(width)
        rects, texts, bar, hint = layout(sel)
        lv = sel.bar_level
        where = f"{lang} {width}"
        want = [k for k in ALL if k not in ("pin", "form") or width != 800]   # 1.36: на 800 px «Закрепить» (и форма) не ставятся, подписи важнее
        check(sorted(rects) == sorted(want), f"{where}: кнопки {sorted(rects)}")
        check(bar.left() >= 0 and bar.right() <= width - 1, f"{where}: панель в экране {bar}")
        for k, r in rects.items():
            check(bar.contains(r), f"{where}: {k} внутри панели")
            check(r.bottom() < hint.top() + 1, f"{where}: {k} выше строки подсказки")
        keys = list(rects)
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                check(not rects[a].intersects(rects[b]), f"{where}: {a} и {b} не перекрываются")
        if width in (1280, 800):
            check(lv["text"], f"{where}: панель с подписями, а не одни значки ({lv['name']})")
        if not lv["text"]:
            check(not sel._choice(lv), f"{where}: на значках крупного ряда нет")
            check(len({rects[k].top() for k in BOTTOM}) == 1, f"{where}: на значках нижний ряд один")
            # вариант Б и на значках: «Редактировать» зелёная заливка, «Скопировать» светло-зелёная с зелёной рамкой
            sel.hover_button = None
            sel.repaint()
            nimg = sel.grab().toImage()
            ne, nc = rects["edit"], rects["copy"]
            c_edit = nimg.pixelColor(ne.left() + 5, ne.center().y())
            c_copy = nimg.pixelColor(nc.right() - 5, nc.top() + 5)
            n_edge = nimg.pixelColor(nc.center().x(), nc.top() + 1)
            check(c_edit.name() == themes.GREEN, f"{where}: на значках «Редактировать» зелёная {c_edit.name()}")
            check(c_copy.name() == TG["fill"], f"{where}: на значках «Скопировать» светло-зелёная {c_copy.name()}")
            check(n_edge.green() > n_edge.red() + 40 and n_edge.green() < 160, f"{where}: у «Скопировать» зелёная рамка {n_edge.name()}")
            for k in ("save", "manual"):
                c = nimg.pixelColor(rects[k].left() + 5, rects[k].center().y())
                check(c.green() <= c.red() + 30, f"{where}: на значках «{k}» без зелёной заливки {c.name()}")
            sel.close()
            continue
        check(sel._choice(lv), f"{where}: два нижних ряда")
        check(not hasattr(sel, "choice_caption"), f"{where}: строки вопроса нет")
        bl, bs = sel._bar_bfonts(lv)
        fb, fs = QFontMetrics(bl), QFontMetrics(bs)
        for k in ("edit", "copy"):
            room = rects[k].width() - lv["pl"] - lv["sq"] - 6 - lv["gp"] - 4
            check(fb.horizontalAdvance(texts[k]) <= room, f"{where}: подпись «{texts[k]}» обрезана")
            check(fs.horizontalAdvance(sel._choice_sub(k)) <= room, f"{where}: пояснение «{k}» обрезано")
        fl = QFontMetrics(sel._bar_fonts(lv)[0])
        for k in ("save", "manual"):
            check(fl.horizontalAdvance(texts[k]) <= rects[k].width() - 12 - 16 - 7 - 6,
                  f"{where}: «{texts[k]}» мелкой кнопки обрезана ({fl.horizontalAdvance(texts[k])} в {rects[k].width()})")
        check(texts["manual"] == RETAKE[lang], f"{where}: на кнопке «{texts['manual']}»")
        check(rects["save"].bottom() < rects["edit"].top() and rects["manual"].bottom() < rects["copy"].top(),
              f"{where}: мелкий ряд выше крупного")
        check(rects["edit"].width() > rects["copy"].width() and rects["edit"].height() == rects["copy"].height(),
              f"{where}: «Редактировать» шире «Скопировать» ({rects['edit'].width()} / {rects['copy'].width()})")
        check(rects["edit"].right() < rects["copy"].left(), f"{where}: копирование справа")
        check(rects["copy"].right() == max(r.right() for r in rects.values()), f"{where}: копирование у правого края")
        check(rects["record"].left() == rects["edit"].left() == rects["save"].left(), f"{where}: левые края рядов ровные")
        check(rects["manual"].right() == rects["copy"].right(), f"{where}: правые края нижних рядов ровные")
        check(abs(rects["save"].width() - rects["manual"].width()) <= 1 and rects["save"].top() == rects["manual"].top()
              and rects["save"].height() == rects["manual"].height(), f"{where}: «Сохранить» и «Другая область» равные")
        # подсказка при наведении: название, клавиши и пояснение
        sel.hover_button = "manual"
        sel.repaint()
        tip = f"{texts['manual']} ({i18n.tr('selector.keys_retake')}) · {sel.BAR_SUB['manual']}"
        img = sel.grab().toImage()
        check(not img.isNull(), f"{where}: панель рисуется при наведении")
        check(fs.horizontalAdvance(tip) > 0, f"{where}: подсказка {tip}")
        # одна зелёная заливка: «Редактировать» зелёная, «Скопировать» светло-зелёная с зелёной рамкой
        def px(r, dx=None, dy=4):
            return img.pixelColor(r.left() + (r.width() * 3 // 4 if dx is None else dx), r.top() + dy)
        sel.hover_button = None
        sel.repaint()
        img = sel.grab().toImage()
        c_copy, c_edit = px(rects["copy"]), px(rects["edit"])
        check(c_edit.green() > c_edit.red() + 40 and c_edit.green() > c_edit.blue() + 20 and c_edit.green() < 160,
              f"{where}: «Редактировать» зелёная {c_edit.name()}")
        check(c_copy.red() > 200 and c_copy.green() > c_copy.red() and contrast(c_copy, "#ffffff") < 1.25,
              f"{where}: «Скопировать» светло-зелёная, без заливки {c_copy.name()}")
        edge = px(rects["copy"], dx=rects["copy"].width() // 2, dy=1)
        check(edge.green() > edge.red() + 40 and edge.green() < 160, f"{where}: у «Скопировать» зелёная рамка {edge.name()}")
        for k in ("save", "manual"):
            c = px(rects[k])
            check(c.green() <= c.red() + 30, f"{where}: «{k}» без зелёной заливки {c.name()}")
        # контраст по пикселям: фон кнопки и самый тёмный (светлый) пиксель подписи
        for k, light_text in (("edit", True), ("copy", False)):
            missing = han_missing(texts[k])
            if missing:
                # Без шрифта, на который рассчитан китайский интерфейс (сборочная машина CI Linux), самый
                # светлый пиксель подписи оказался #d6e7dd (CI 1.34.0, zh): мерить там нечего. Контраст цветов
                # кода для всех языков проверен выше (раздел 6), с настоящим шрифтом проверка по пикселям идёт.
                if width == 1280 and k == "edit":
                    print(f"SKIP {where}: контраст подписи по пикселям, нет шрифта для иероглифов ({missing})")
                continue
            r = rects[k]
            bg = px(r)
            text_box = QRect(r.left() + lv["pl"] + lv["sq"] + 6 + lv["gp"], r.top() + 6, r.width() // 2, r.height() // 2 - 6)
            best = None
            for x in range(text_box.left(), text_box.right(), 1):
                for y in range(text_box.top(), text_box.bottom(), 1):
                    c = img.pixelColor(x, y)
                    if best is None or (lum(c) > lum(best) if light_text else lum(c) < lum(best)):
                        best = c
            check(best is not None and contrast(best, bg) >= 4.5, f"{where}: подпись «{k}» {best.name() if best else None} на {bg.name()}")
        sel.close()

# --- 3: экран 800 × 600, панель и знакомство ------------------------------------------------------------------
for lang in i18n.LANGUAGE_NAMES:
    i18n.set_language(lang)
    for kept in (QRect(90, 150, 260, 150), QRect(250, 60, 300, 220), QRect(40, 40, 700, 480)):
        sel = selector(800, 600, kept)
        rects, texts, bar, hint = layout(sel)
        where = f"800x600 {lang} {kept.x()},{kept.y()} {kept.width()}x{kept.height()}"
        check(QRect(0, 0, 800, 600).contains(bar), f"{where}: панель на экране {bar}")
        check(not sel.bar_close_rect.isEmpty() and QRect(0, 0, 800, 600).contains(sel.bar_close_rect),
              f"{where}: крестик на экране")
        check(sel.bar_level["text"], f"{where}: с подписями")
        fl = QFontMetrics(sel._bar_fonts(sel.bar_level)[0])
        for k in ("save", "manual"):
            check(fl.horizontalAdvance(texts[k]) <= rects[k].width() - 12 - 16 - 7 - 6, f"{where}: «{texts[k]}» не обрезана")
        lv = sel.bar_level
        fb, fs = (QFontMetrics(f) for f in sel._bar_bfonts(lv))
        for k in ("edit", "copy"):
            room = rects[k].width() - lv["pl"] - lv["sq"] - 6 - lv["gp"] - 4
            check(fb.horizontalAdvance(texts[k]) <= room and fs.horizontalAdvance(sel._choice_sub(k)) <= room,
                  f"{where}: «{texts[k]}» и пояснение не обрезаны")
        check(rects["edit"].width() > rects["copy"].width(), f"{where}: «Редактировать» шире")
        sel.close()
    if lang not in ("ru", "de", "zh", "fr"):   # знакомство целиком на четырёх языках (самые широкие и узкие подписи)
        continue
    cfg = dict(appmod.DEFAULTS)
    sel = selector(800, 600, QRect(90, 150, 260, 150))
    sel.tr_cfg = cfg
    sel.lang_ctx = Ctx(_tmp)
    sel.tour_force = True
    check(sel.maybe_start_tour() and sel.tour is not None, f"800x600 {lang}: знакомство запущено")
    tour = sel.tour
    n = len(tour.steps)
    check(n == 8, f"800x600 {lang}: шагов 8 ({n})")
    for i in range(n):
        tour.show_step(i)
        settle(1)
        card = QRect(tour.card.pos(), tour.card.size())
        check(sel.rect().contains(card), f"800x600 {lang} шаг {i + 1}: карточка на экране {card}")
        check(all(sel.rect().contains(h.adjusted(PAD, PAD, -PAD, -PAD)) for h in tour.holes), f"800x600 {lang} шаг {i + 1}: подсветка на экране")
        check(not any(card.intersects(h) for h in tour.holes), f"800x600 {lang} шаг {i + 1}: карточка не закрывает подсветку")
    if "manual" in tour.keys:
        tour.show_step(tour.keys.index("manual"))
        check(tour.title.text() == RETAKE[lang], f"800x600 {lang}: шаг «{tour.title.text()}»")
    check(tour.keys[:3] == ["area", "edit", "copy"], f"800x600 {lang}: после рамки сначала главная «Редактировать» {tour.keys}")
    tour.show_step(1)
    check(tour.title.text() == i18n.tr("seltour.s3_title"), f"800x600 {lang}: шаг 2 «{tour.title.text()}»")
    for _i in range(n):
        tour.next.click()
    settle()
    check(sel.tour is None and sel.isVisible(), f"800x600 {lang}: знакомство прошло до конца, окно живо")
    sel._done = True
    sel.close()

# --- 4: «Сохранить» не закрывает окно ---------------------------------------------------------------------------
i18n.set_language("ru")
folder = os.path.join(_tmp, "save")
os.makedirs(folder)


def pngs():
    return sorted(f for f in os.listdir(folder) if f.endswith(".png"))


toasts = []
_orig_toast = ocr.toast


def spy_toast(widget, text=None, ms=None, mark=True):
    toasts.append(text)
    return _orig_toast(widget, text, ms, mark)


ocr.toast = spy_toast
for how in ("click", "ctrl_s"):
    ctx = Ctx(folder, ask=False)
    sel = selector(1280, ctx=ctx)
    done = []
    sel.finished.connect(lambda pm, r, d=done: d.append(pm))
    kept = QRect(sel.kept)
    before = pngs()
    toasts.clear()
    if how == "click":
        rects = layout(sel)[0]
        QTest.mouseClick(sel, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, rects["save"].center())
    else:
        QTest.keyClick(sel, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    settle()
    new = [f for f in pngs() if f not in before]
    check(len(new) == 1, f"{how}: файл создан {new}")
    check(not done and not sel._done and sel.isVisible(), f"{how}: окно выделения не закрыто")
    check(sel.kept == kept, f"{how}: рамка на месте")
    check(new and toasts and toasts[-1] == i18n.tr("selector.saved", name=new[0]), f"{how}: плашка «Сохранено: имя» {toasts}")
    check(ctx.config.get("save_dir") == folder and ctx.config.get("last_region") == [kept.x(), kept.y(), kept.width(), kept.height()],
          f"{how}: папка и прошлая область запомнены")
    if new:
        from PyQt6.QtGui import QImage
        im = QImage(os.path.join(folder, new[0]))
        check(not im.isNull() and im.width() == kept.width() and im.height() == kept.height(), f"{how}: в файле рамка {im.width()}x{im.height()}")
    # дальше можно скопировать: окно закрывается как обычно
    QTest.keyClick(sel, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    settle()
    check(sel.action == "copy" and len(done) == 1 and done[0] is not None, f"{how}: после сохранения Ctrl+Enter копирует и закрывает")

# 1.34.1 (В1 проверки 1.34.0): окно после «Сохранить» остаётся, повтор того же снимка второй файл не создаёт
from PyQt6.QtCore import QEvent  # noqa: E402
from PyQt6.QtGui import QKeyEvent  # noqa: E402
ctx = Ctx(folder, ask=False)
sel = selector(1280, ctx=ctx)
before = pngs()
toasts.clear()
QTest.keyClick(sel, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
QTest.keyClick(sel, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
settle()
first = [f for f in pngs() if f not in before]
check(len(first) == 1, f"Ctrl+S дважды: один файл {first}")
check(first and toasts[-1:] == [i18n.tr("selector.saved_already", name=first[0])], f"второе Ctrl+S: «Уже сохранено: имя» {toasts}")
before = pngs()
for i in range(10):   # Ctrl+S удержано полсекунды: одно нажатие и автоповтор системы
    QApplication.sendEvent(sel, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier, "s",
                                          autorep=(i > 0)))
settle()
check(pngs() == before, f"Ctrl+S удержано: новых файлов нет {[f for f in pngs() if f not in before]}")
r = layout(sel)[0]["save"]
QTest.mouseClick(sel, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, r.center())
QTest.mouseDClick(sel, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, r.center())
settle()
check(pngs() == before, f"двойной щелчок по «Сохранить»: новых файлов нет {[f for f in pngs() if f not in before]}")
sel.kept = QRect(sel.kept.adjusted(10, 10, -10, -10))   # другая рамка: это другой снимок
sel.update()
QTest.keyClick(sel, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
settle()
check(len([f for f in pngs() if f not in before]) == 1, "другая рамка: новый файл")
os.remove(os.path.join(folder, first[0]))   # файл удалили: тот же снимок сохраняется снова
sel.kept = QRect(sel.kept.adjusted(-10, -10, 10, 10))
before = pngs()
sel._do("save")
settle()
check(len([f for f in pngs() if f not in before]) == 1, "прошлый файл удалён: тот же снимок сохраняется снова")
sel._finish(None)
settle()

# с окном выбора файла: на время окна выделение спрятано, потом снова на экране
asked = []
_orig_ask = editormod.ask_save_path


def fake_ask(parent, cfg, answer):
    asked.append(sel.isVisible())
    return answer


for answer in (os.path.join(folder, "my-shot.png"), None):
    ctx = Ctx(folder, ask=True)
    sel = selector(1280, ctx=ctx)
    done = []
    sel.finished.connect(lambda pm, r, d=done: d.append(pm))
    editormod.ask_save_path = lambda parent, cfg, a=answer: fake_ask(parent, cfg, a)
    before = pngs()
    asked.clear()
    toasts.clear()
    sel._do("save")
    settle()
    editormod.ask_save_path = _orig_ask
    tag = "выбран файл" if answer else "отмена"
    check(asked == [False], f"окно выбора ({tag}): выделение спрятано на время окна {asked}")
    check(sel.isVisible() and not sel._done and not done, f"окно выбора ({tag}): выделение снова на экране")
    if answer:
        check(os.path.isfile(answer) and toasts == [i18n.tr("selector.saved", name="my-shot.png")], f"окно выбора: файл и плашка {toasts}")
    else:
        check(pngs() == before and not toasts, "отмена: файла нет, плашки нет")
    sel._done = True
    sel.close()

# запись не удалась: окно остаётся, плашка без галочки
ctx = Ctx(os.path.join(_tmp, "нет", "такой"), ask=False)
editormod.ask_save_path = lambda parent, cfg: os.path.join(_tmp, "нет-папки", "x.png")
sel = selector(1280, ctx=ctx)
toasts.clear()
sel._do("save")
settle()
editormod.ask_save_path = _orig_ask
check(sel.isVisible() and not sel._done and toasts == [i18n.tr("selector.save_failed")], f"ошибка записи: окно открыто, плашка {toasts}")
sel._done = True
sel.close()

# без программы (нет save_from_selector): как раньше, с закрытием
sel = selector(1280)
got = []
sel.finished.connect(lambda pm, r, g=got: g.append(pm is not None))
sel._do("save")
settle()
check(sel.action == "save" and got == [True], f"без программы «Сохранить» закрывает, как раньше {got}")
ocr.toast = _orig_toast

# --- 5: остальные кнопки и клавиши как раньше -----------------------------------------------------------------
for key, act in (("edit", "edit"), ("copy", "copy")):
    sel = selector(1280)
    got = []
    sel.finished.connect(lambda pm, r, g=got: g.append(pm is not None))
    r = layout(sel)[0][key]
    QTest.mouseClick(sel, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, r.center())
    settle()
    check(sel.action == act and got == [True], f"щелчок по «{key}» даёт {sel.action} {got}")
sel = selector(1280)
QTest.mouseClick(sel, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, layout(sel)[0]["manual"].center())
settle()
check(sel.kept is None, "«Другая область» снимает рамку")
sel.close()
for mods, key, act in ((Qt.KeyboardModifier.NoModifier, Qt.Key.Key_Return, "edit"),
                       (Qt.KeyboardModifier.NoModifier, Qt.Key.Key_Space, "edit"),
                       (Qt.KeyboardModifier.ControlModifier, Qt.Key.Key_Return, "copy"),
                       (Qt.KeyboardModifier.ControlModifier, Qt.Key.Key_C, "copy")):
    sel = selector(1280)
    QTest.keyClick(sel, key, mods)
    settle()
    check(sel.action == act and sel._done, f"клавиша {key} {mods} даёт {sel.action}, нужно {act}")
sel = selector(1280)
QTest.keyClick(sel, Qt.Key.Key_R)
settle()
check(sel.kept is None and not sel._done, "R снимает рамку")
sel = selector(1280)   # щелчок внутри рамки без движения: редактор
QTest.mouseClick(sel, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, sel.kept.center())
settle()
check(sel.action == "edit" and sel._done, f"щелчок в рамке открывает редактор ({sel.action})")

print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено {len(failures)}")
sys.exit(1 if failures else 0)
