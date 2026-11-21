# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Ширина чипа «Окна ▾» («Снимок окна», 1.33.0) в окне выделения на 12 языках.

i18n_width_test меряет панель окна выделения без списка окон, поэтому чип туда не попадает. Здесь окно выделения
с готовящимся списком окон на экранах шириной 1280, 800 и 480; область небольшая (панель под ней, в строке ещё размер)
и почти во весь экран (панель внутри рамки). Без области панели нет, чипа тоже:
- панель не шире экрана, чип есть (с подписью или одним значком) и лежит внутри панели;
- чип не наезжает на чип языка и шестерёнку, подсказка строки до чипа не доходит (место под чип отведено);
- у чипа с подписью «Окна ▾» помещается целиком в отведённое ей место;
- на экране 1280 чип с подписью на всех 12 языках.

Шрифт настоящий (системный); CLIPSD_WIDTH_FONT="Segoe UI,9" проверяет с другим шрифтом.
Запуск: QT_QPA_PLATFORM=offscreen python3 tests/vybor_okna_width_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import json
import os
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
os.environ.pop("CLIPSD_LANG", None)   # тест сам перебирает языки
os.environ.pop("DBUS_SESSION_BUS_ADDRESS", None)   # никакой настоящей шины сеанса
_cfg = os.path.join(tempfile.mkdtemp(prefix="clipsd-oknow-"), "screen.json")
with open(_cfg, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1600, "height": 1000,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _cfg

from PyQt6.QtCore import QRect  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPixmap  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
if os.environ.get("CLIPSD_WIDTH_FONT"):
    fam, _sep, pt = os.environ["CLIPSD_WIDTH_FONT"].partition(",")
    app.setFont(QFont(fam, int(pt or 9)))
from clipshot import app as appmod, i18n  # noqa: E402
from clipshot.selector import RegionSelector  # noqa: E402

failures = []
checks = [0]


def check(cond, msg):
    checks[0] += 1
    if not cond:
        failures.append(msg)
        print("FAIL " + msg)


def settle(n=3):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(10)


forms = {}


def chip_case(lang, width, big):
    pm = QPixmap(width, 720)
    pm.fill(QColor("#4a78b0"))
    last = QRect(10, 10, width - 20, 700) if big else QRect(width // 2 - 150, 90, 300, 200)
    sel = RegionSelector(pm, QRect(0, 0, width, 720), last_rect=last)
    cfg = dict(appmod.DEFAULTS)
    sel.tr_cfg, sel.tr_save = cfg, (lambda: None)
    sel.lang_ctx = type("C", (), {"config": cfg, "set_language": lambda *a: None})()
    sel.windows_state = "loading"   # список окон просится (как после Alt+W): чип уже в строке
    sel.show_zoom = False
    sel.resize(width, 720)
    sel.show()
    settle()
    sel.repaint()
    _buttons, bar, hint = sel._bar_layout()
    win, lang_r, gear = sel.win_rect, sel.lang_rect, sel.gear_rect
    label = f"{lang} {width}{' область во весь экран' if big else ''}"
    check(bar.width() <= width, f"{label}: панель шире экрана ({bar.width()})")
    check(not win.isEmpty(), f"{label}: нет чипа «Окна ▾»")
    if not win.isEmpty():
        check(bar.contains(win), f"{label}: чип {win} вне панели {bar}")
        check(not win.intersects(lang_r) and not win.intersects(gear), f"{label}: чип наезжает на чип языка или шестерёнку")
        check(win.left() >= hint.right() - sel.bar_hint_reserve - 1,
              f"{label}: подсказка строки заходит под чип (резерв {sel.bar_hint_reserve}, чип с {win.left()})")
        long_form = win.width() > 30
        if long_form:
            _label_font, small_font = sel._bar_fonts(sel.bar_level)
            # как в _draw_win_chip: значок 14 точек с отступом 8, текст через 6 от значка, справа поле 8
            room = win.right() - (win.left() + 8 + 14 - 1) - 8
            text = i18n.tr("selector.win_chip") + " ▾"
            need = QFontMetrics(small_font).horizontalAdvance(text)
            check(need <= room, f"{label}: подпись «{text}» шире места в чипе ({need} > {room})")
        forms[(lang, width, big)] = "подпись" if long_form else "значок"
    sel.close()
    sel.deleteLater()


for lang in i18n.LANGUAGES:
    i18n.set_language(lang)
    for width in (1280, 800, 480):
        for big in (False, True):
            chip_case(lang, width, big)
    check(forms.get((lang, 1280, False)) == "подпись" and forms.get((lang, 1280, True)) == "подпись",
          f"{lang}: на экране 1280 чип «Окна ▾» без подписи")

check(len(i18n.LANGUAGES) == 12, f"12 языков: {i18n.LANGUAGES}")
print("Вид чипа (язык: 1280/800/480, небольшая область):",
      {lang: "/".join(forms.get((lang, w, False), "-") for w in (1280, 800, 480)) for lang in i18n.LANGUAGES})
print(f"ИТОГ: проверок {checks[0]}, провалено: {len(failures)}")
sys.exit(1 if failures else 0)
