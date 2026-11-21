# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Компоновка панели окна выделения (просьба владельца 21.11.2026; из двух эскизов владелец выбрал компоновку 1,
переключатель CLIPSD_PANEL_LAYOUT и компоновка 2 убраны).

Язык и шестерёнка в левом углу строки подсказки, крестик на углу панели, чип «Открытые окна ▾» справа в строке
подсказки, под «Скопировать и закрыть», «С телефона» плиткой в верхнем ряду. Переменная CLIPSD_PANEL_LAYOUT=2
больше ничего не меняет.
Для 12 языков на 1280 и 800: всё внутри панели, ничего не перекрывается, подсказка не заходит под чипы, подписи
чипов не обрезаны; щелчки по «Открытые окна ▾», языку, шестерёнке и «С телефона» работают; знакомство (8 шагов)
проходит на 1280 и 800, ru и de, подсветка на экране, карточка её не закрывает.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/kompanovka_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import json
import os
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
os.environ.pop("CLIPSD_LANG", None)
_cfg = os.path.join(tempfile.mkdtemp(prefix="clipsd-komp-"), "screen.json")
with open(_cfg, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1600, "height": 1000,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _cfg
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QColor, QFontMetrics, QPixmap
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
from clipshot import app as appmod, i18n
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
    def __init__(self):
        self.config = dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True)
        self.phone_calls = []

    def set_language(self, code):
        pass

    def open_phone(self, target=None):
        self.phone_calls.append(target)

    def open_settings(self):
        pass


def selector(width, height=720, windows=True):
    pm = QPixmap(width, height)
    pm.fill(QColor("#4a78b0"))
    sel = RegionSelector(pm, QRect(0, 0, width, height), last_rect=QRect(width // 2 - 150, min(90, height // 4), 300, 200))
    sel.tr_cfg, sel.tr_save = dict(appmod.DEFAULTS), lambda: None
    sel.lang_ctx = Ctx()
    if windows:
        sel.windows_state = "loading"   # список окон просится: чип «Открытые окна ▾» есть
    sel.show_zoom = False
    sel.resize(width, height)
    sel.show()
    settle()
    sel.repaint()
    return sel


for variant in ("", "2"):   # без переменной и со старой переменной компоновки 2: панель одна и та же
    os.environ["CLIPSD_PANEL_LAYOUT"] = variant
    for lang in i18n.LANGUAGE_NAMES:
        i18n.set_language(lang)
        for width in (1280, 800):
            sel = selector(width)
            buttons, bar, hint = sel._bar_layout()
            rects = {k: r for k, _t, _s, r in buttons}
            where = f"переменная «{variant}» {lang} {width}"
            lv = sel.bar_level
            check(lv["text"], f"{where}: панель с подписями ({lv['name']})")
            win, lang_r, gear = sel.win_rect, sel.lang_rect, sel.gear_rect
            check(not win.isEmpty() and not lang_r.isEmpty() and not gear.isEmpty(), f"{where}: чипы на месте")
            # язык и шестерёнка в левом углу строки подсказки
            check(lang_r.left() == hint.left() and gear.left() > lang_r.right() and gear.top() == lang_r.top()
                  and lang_r.top() >= hint.top() - 4, f"{where}: язык {lang_r} и шестерёнка {gear} слева в строке подсказки {hint}")
            check(not hasattr(sel, "group_rect") and not hasattr(sel, "_group2"), f"{where}: кода компоновки 2 нет")
            check(abs(win.right() - rects["copy"].right()) <= 1 and win.top() >= rects["copy"].bottom(),
                  f"{where}: «Открытые окна ▾» справа под «Скопировать и закрыть» {win} / {rects['copy']}")
            check(rects["phone"].top() == rects["record"].top() and rects["phone"].height() == rects["record"].height(),
                  f"{where}: «С телефона» плиткой в верхнем ряду")
            fm_s0 = QFontMetrics(sel._bar_fonts(lv)[1])
            if width == 1280:   # на 1280 чип с подписью, не один значок
                check(win.width() >= fm_s0.horizontalAdvance(i18n.tr("selector.win_chip") + " ▾") + 8 + 14 + 5,
                      f"{where}: «Открытые окна ▾» с подписью ({win.width()})")
            flat = [("win", win), ("lang", lang_r), ("gear", gear)] + list(rects.items())
            for i, (a, ra) in enumerate(flat):
                check(bar.contains(ra), f"{where}: {a} внутри панели")
                for b, rb in flat[i + 1:]:
                    check(not ra.intersects(rb), f"{where}: {a} и {b} не перекрываются")
            check(not sel.bar_close_rect.intersects(bar.adjusted(14, 14, -14, -14)) and abs(sel.bar_close_rect.center().x() - bar.right()) <= 14,
                  f"{where}: крестик на углу панели")
            # подсказка строки не заходит под чипы
            t = sel.hint_text_rect
            check(not t.isEmpty() and t.left() > gear.right() and (win.top() < hint.top() or t.right() < win.left())
                  and (sel.dims_rect.isEmpty() or t.right() < sel.dims_rect.left()), f"{where}: текст подсказки {t} между чипами")
            fm_s = QFontMetrics(sel._bar_fonts(lv)[1])
            check(fm_s.horizontalAdvance(sel.bar_hint_text) <= t.width() or sel.bar_hint_text == sel.BAR_HINT_ICONS,
                  f"{where}: подсказка «{sel.bar_hint_text}» помещается ({t.width()})")
            # щелчки
            check(sel._button_at(win.center()) == "window" and sel._button_at(lang_r.center()) == "lang"
                  and sel._button_at(gear.center()) == "settings" and sel._button_at(rects["phone"].center()) == "phone",
                  f"{where}: щелчки попадают в «Открытые окна ▾», язык, шестерёнку, «С телефона»")
            if width == 800 and lang in ("ru", "de"):
                ctx = sel.lang_ctx
                sel._do("phone")
                settle(4)
                check(ctx.phone_calls == [None], f"{where}: «С телефона» открывает приём с телефона")
                continue   # окно выделения закрыто и удалено
            sel._done = True
            sel.close()
    # знакомство с панелью
    for lang in ("ru", "de"):
        i18n.set_language(lang)
        for width, height in ((1280, 720), (800, 720), (800, 600)):
            sel = selector(width, height)
            sel.tr_cfg = dict(appmod.DEFAULTS)
            sel.tour_force = True
            sel.maybe_start_tour()
            tour = sel.tour
            where = f"переменная «{variant}» {lang} {width}x{height} знакомство"
            check(tour is not None and len(tour.steps) == 8, f"{where}: 8 шагов")
            for i in range(len(tour.steps)):
                tour.show_step(i)
                settle(1)
                card = QRect(tour.card.pos(), tour.card.size())
                check(sel.rect().contains(card), f"{where} шаг {i + 1}: карточка на экране")
                # запас 3: вырез вокруг крестика на 2 точки шире самого крестика, крестик у края экрана
                check(all(sel.rect().adjusted(-3, -3, 3, 3).contains(h.adjusted(PAD, PAD, -PAD, -PAD)) for h in tour.holes),
                      f"{where} шаг {i + 1}: подсветка на экране")
                check(not any(card.intersects(h) for h in tour.holes), f"{where} шаг {i + 1}: карточка не закрывает подсветку")
            k = tour.keys.index("lang")
            tour.show_step(k)
            check(len(tour.holes) == 2, f"{where}: шаг «язык и настройки» подсвечивает чип языка и шестерёнку")
            for _i in range(len(tour.steps)):
                tour.next.click()
            settle()
            check(sel.tour is None and sel.isVisible(), f"{where}: прошло до конца")
            sel._done = True
            sel.close()
os.environ.pop("CLIPSD_PANEL_LAYOUT", None)

print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено {len(failures)}")
sys.exit(1 if failures else 0)
