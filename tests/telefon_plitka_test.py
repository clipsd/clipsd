# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Плитка «С телефона» в верхнем ряду панели окна выделения (просьба владельца 21.11.2026).

1. 12 языков, экраны 1280 и 800 (и 800 × 600): шесть плиток в одном ряду, внутри панели, не перекрываются, панель
   с подписями (не одни значки), подпись плитки не шире её (слово целиком, не больше двух строк), пояснения
   переводов не обрезаны; на 1280 плитки равные.
2. Значок телефона нарисован (не пустой) и цветной, как у других плиток.
3. Плитка заметнее серых: мягкий малиновый тон, значок крупнее, вторая строка «камера или картинка»; подсказка при
   наведении «С телефона · Снять камерой или отправить картинку с телефона» на 12 языках. Ключи общие с кнопкой
   в редакторе: phone.tile_title, phone.tile_sub, phone.tile_tip, значок icons.icon("phone").
4. Нажатие: окно выделения закрывается без снимка, открывается окно приёма (ctx.open_phone, то же, что пункт меню);
   если выделение открыто из редактора, фото вставляется в этот редактор (target).
5. В режиме перевода плитка не работает (бледная, как запись и весь экран).
6. Знакомство: шаг «верхний ряд» подсвечивает и «С телефона», текст шага упоминает плитку.
7. Страница телефона: есть оба пути, «Сфотографировать» (камера) и «Выбрать скриншот или фото» (файл без capture).

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/telefon_plitka_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import json
import os
import re
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
os.environ.pop("CLIPSD_LANG", None)
_cfg = os.path.join(tempfile.mkdtemp(prefix="clipsd-tel-"), "screen.json")
with open(_cfg, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1600, "height": 1000,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _cfg
from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtGui import QColor, QFontMetrics, QPixmap
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
from clipshot import app as appmod, i18n, icons
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
    def __init__(self, target=None):
        self.config = dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True)
        self.phone_calls = []
        self.insert_target = target

    def set_language(self, code):
        pass

    def open_phone(self, target=None):
        self.phone_calls.append(target)


def selector(width, height=720, kept=None, ctx=None):
    pm = QPixmap(width, height)
    pm.fill(QColor("#4a78b0"))
    sel = RegionSelector(pm, QRect(0, 0, width, height),
                         last_rect=kept or QRect(width // 2 - 150, min(90, height // 4), 300, 200))
    sel.tr_cfg, sel.tr_save = dict(appmod.DEFAULTS), lambda: None
    sel.lang_ctx = ctx or Ctx()
    sel.show_zoom = False
    sel.resize(width, height)
    sel.show()
    settle()
    return sel


TOP = ["record", "full", "ocr", "phone", "translate", "translate_pick"]
LABEL = {"ru": "С телефона", "en": "From phone", "es": "Del teléfono", "de": "Vom Smartphone", "fr": "Du téléphone",
         "it": "Dal telefono", "pt": "Do celular", "pl": "Z telefonu", "tr": "Telefondan", "uk": "З телефону",
         "bg": "От телефона", "zh": "从手机"}

# --- 1, 3: 12 языков ---------------------------------------------------------------------------------------------
for lang in i18n.LANGUAGE_NAMES:
    i18n.set_language(lang)
    check(i18n.tr("phone.tile_title") == LABEL.get(lang), f"{lang}: подпись {i18n.tr('phone.tile_title')}")
    tip = i18n.tr("phone.tile_tip")
    check(tip and tip != "phone.tile_tip" and "—" not in tip and len(tip) <= 70, f"{lang}: подсказка «{tip}»")
    check(i18n.tr("seltour.s5_text").count(LABEL[lang]) >= 1, f"{lang}: знакомство упоминает «{LABEL[lang]}»")
    for width, height in ((1280, 720), (800, 720), (800, 600)):
        sel = selector(width, height)
        buttons, bar, hint = sel._bar_layout()
        rects = {k: r for k, _t, _s, r in buttons}
        texts = {k: t for k, t, _s, _r in buttons}
        where = f"{lang} {width}x{height}"
        lv = sel.bar_level
        check([k for k in rects if k in TOP] == TOP, f"{where}: плитки {list(rects)}")
        check(lv["text"], f"{where}: панель с подписями, не одни значки ({lv['name']})")
        check(QRect(0, 0, width, height).contains(bar), f"{where}: панель на экране {bar}")
        check(all(bar.contains(rects[k]) for k in TOP), f"{where}: плитки внутри панели")
        check(len({rects[k].top() for k in TOP}) == 1, f"{where}: плитки в одном ряду")
        check(all(rects[a].right() < rects[b].left() for a, b in zip(TOP, TOP[1:])), f"{where}: плитки не перекрываются")
        check(abs(rects["translate_pick"].right() - rects["copy"].right()) <= 1, f"{where}: ряд не шире панели")
        if width == 1280:
            ws = [rects[k].width() for k in TOP]
            check(max(ws) - min(ws) <= 1, f"{where}: на 1280 плитки равные {ws}")
        fl = QFontMetrics(sel._bar_fonts(lv)[0])
        fs = QFontMetrics(sel._bar_fonts(lv)[1])
        for k in TOP:
            lines = sel._wrap(fl, texts[k], rects[k].width() - 12)
            check(len(lines) <= 2 and all(fl.horizontalAdvance(x) <= rects[k].width() - 4 for x in lines),
                  f"{where}: подпись «{texts[k]}» помещается в плитку {rects[k].width()}")
        for k in ("translate", "translate_pick", "phone"):
            check(fs.horizontalAdvance(sel.BAR_SUB[k]) <= rects[k].width() - 6, f"{where}: пояснение «{sel.BAR_SUB[k]}» не обрезано")
        # плитка заметнее остальных: свой мягкий тон, не серый и не зелёный
        sel.repaint()
        im = sel.grab().toImage()
        c_ph = im.pixelColor(rects["phone"].left() + 4, rects["phone"].center().y())
        c_rec = im.pixelColor(rects["record"].left() + 4, rects["record"].center().y())
        check(c_ph != c_rec and c_ph.red() > c_ph.green() + 8 and c_ph.green() < 245, f"{where}: плитка «С телефона» выделена {c_ph.name()} / {c_rec.name()}")
        # подсказка при наведении
        drawn = []
        from clipshot import selector as selmod
        real = selmod.QPainter

        class Spy(real):
            def drawText(self, *a):
                drawn.extend(x for x in a if isinstance(x, str))
                return super().drawText(*a)
        sel.hover_button = "phone"
        selmod.QPainter = Spy
        sel.repaint()
        selmod.QPainter = real
        want = f"{LABEL[lang]} · {tip}"
        check(want in drawn, f"{where}: подсказка «{want}» в строке подсказки")
        sel.hover_button = None
        sel._done = True
        sel.close()

# --- 2: значок -----------------------------------------------------------------------------------------------------
img = icons.icon("phone", "#b4236e").pixmap(QSize(48, 48)).toImage()
colored = sum(1 for x in range(img.width()) for y in range(img.height()) if img.pixelColor(x, y).alpha() > 128)
check(60 < colored < 48 * 48 // 2, f"значок телефона нарисован ({colored} точек)")
i18n.set_language("ru")
check(RegionSelector.BAR_ICON_COLORS["phone"] not in ("#157a40", "#1f9d55") and RegionSelector.BAR_ICONS["phone"] == "phone",
      "цвет значка не зелёный (зелёный только у главной)")

# --- 4: нажатие --------------------------------------------------------------------------------------------------
for target in (None, "editor"):
    ctx = Ctx(target)
    sel = selector(1280, ctx=ctx)
    got = []
    sel.finished.connect(lambda pm, r, g=got: g.append(pm))
    r = {k: rr for k, _t, _s, rr in sel._bar_layout()[0]}["phone"]
    QTest.mouseClick(sel, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, r.center())
    settle(5)
    check(got == [None] and sel._done, f"нажатие: окно выделения закрыто без снимка {got}")
    check(ctx.phone_calls == [target], f"нажатие: открыто окно приёма с телефона (target={target}) {ctx.phone_calls}")
check("phone_ui.open_phone" in open(os.path.join(os.path.dirname(here), "clipshot", "app.py"), encoding="utf-8").read(),
      "Clipshot.open_phone открывает phone_ui.open_phone, как пункт меню")

# --- 5: режим перевода -------------------------------------------------------------------------------------------
ctx = Ctx()
sel = selector(1280, ctx=ctx)
sel.translate_mode = True
check("phone" in sel.BAR_DISABLED_IN_TR, "в режиме перевода плитка бледная и не работает")
sel.translate_mode = False
sel._done = True
sel.close()

# --- 6: знакомство -----------------------------------------------------------------------------------------------
for width in (1280, 800):
    sel = selector(width, ctx=Ctx())
    sel.tr_cfg = dict(appmod.DEFAULTS)
    sel.tour_force = True
    sel.maybe_start_tour()
    tour = sel.tour
    phone = {k: rr for k, _t, _s, rr in sel._bar_layout()[0]}["phone"]
    i = tour.keys.index("top")
    tour.show_step(i)
    check(any(h.adjusted(PAD, PAD, -PAD, -PAD).contains(phone.adjusted(2, 2, -2, -2)) for h in tour.holes),
          f"{width}: шаг «верхний ряд» подсвечивает «С телефона»")
    card = QRect(tour.card.pos(), tour.card.size())
    check(not any(card.intersects(h) for h in tour.holes) and sel.rect().contains(card), f"{width}: карточка не закрывает подсветку")
    tour.skip.click()
    settle()
    sel._done = True
    sel.close()

# --- 7: страница телефона: снять камерой и выбрать готовую картинку ---------------------------------------------
src = open(os.path.join(os.path.dirname(here), "clipshot", "phone_page.py"), encoding="utf-8").read()
check(re.search(r'<input id="cam"[^>]*capture="environment"', src) is not None, "страница: «Сфотографировать» открывает камеру")
pick = re.search(r'<input id="pick"[^>]*>', src)
check(pick is not None and "capture" not in pick.group(0) and 'accept="image/*"' in pick.group(0),
      "страница: «Выбрать скриншот или фото» без capture (галерея и файлы)")
check("pick.click()" in src and 'id="gal"' in src, "страница: кнопка «Выбрать» открывает выбор файла")

print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено {len(failures)}")
sys.exit(1 if failures else 0)
