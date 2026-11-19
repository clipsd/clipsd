# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""1.32: знакомство с окном выделения: первый показ включает, второй нет; пункт меню включает снова; Esc пропускает;
шаги проходят до конца; подсветка попадает в нужные кнопки при ширинах 1280 и 800; снимок во время знакомства не делается.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/seltour_test.py
"""
import json
import os
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
os.environ.pop("CLIPSD_LANG", None)
_cfg = os.path.join(tempfile.mkdtemp(prefix="clipsd-seltour-"), "screen.json")
with open(_cfg, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1600, "height": 1000,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _cfg
from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
from clipshot import app as appmod, i18n
from clipshot.selector import RegionSelector
from clipshot.selector_tour import PAD

failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def settle(n=3):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(10)


class Ctx:
    def __init__(self):
        self.config = dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True)
        self.icon = appmod.make_icon()
        self.settings_opened = 0

    def set_language(self, code):
        pass

    def open_settings(self):
        self.settings_opened += 1


def selector(w, cfg, h=720, last=None):
    pm = QPixmap(w, h)
    pm.fill(QColor("#4a78b0"))
    sel = RegionSelector(pm, QRect(0, 0, w, h), last_rect=last)
    sel.tr_cfg, sel.tr_save = cfg, lambda: cfg.__setitem__("_saved", cfg.get("_saved", 0) + 1)
    sel.lang_ctx = Ctx()
    sel.show_zoom = False
    sel.resize(w, h)
    sel.show()
    settle()
    return sel


def key(sel, k, mods=Qt.KeyboardModifier.NoModifier):
    QTest.keyClick(sel, k, mods)
    settle(2)


i18n.set_language("ru")

for W in (1280, 800):
    print(f"--- ширина {W}")
    cfg = dict(appmod.DEFAULTS)
    check(cfg.get("tour_selector_done") is False, "по умолчанию знакомство с окном выделения не показано")
    sel = selector(W, cfg)
    done = []
    sel.finished.connect(lambda *_a: done.append(1))
    check(sel.maybe_start_tour() and sel.tour is not None and sel.tour.isVisible(), "первый показ: знакомство запущено")
    check(cfg["tour_selector_done"] is True and cfg.get("_saved"), "флаг tour_selector_done записан сразу")
    check(sel.kept is not None, "для примера показана рамка")
    tour = sel.tour
    n = len(tour.steps)
    check(n == 8, f"шагов 8 (панель полная): {n}")
    check("1 " in tour.step_label.text() or "1" in tour.step_label.text(), f"надпись шага: {tour.step_label.text()}")
    # подсветка: каждый шаг попадает в свои кнопки
    buttons = {b[0]: b[3] for b in sel._bar_layout()[0]}
    expect = {"area": [sel.kept], "copy": [buttons["copy"]], "edit": [buttons["edit"], sel.kept],
              "manual": [buttons["manual"]], "top": [buttons[k] for k in ("record", "full", "ocr") if k in buttons],
              "translate": [buttons[k] for k in ("translate", "translate_pick") if k in buttons],
              "lang": [sel.lang_rect, sel.gear_rect], "close": [sel.bar_close_rect]}
    area = sel.rect()
    for i, key_name in enumerate(tour.keys):
        tour.show_step(i)
        holes = [h.adjusted(PAD, PAD, -PAD, -PAD) for h in tour.holes]
        want = expect[key_name]
        ok = len(holes) == len(want) and all(h.contains(w.adjusted(2, 2, -2, -2)) and h.width() <= w.width() + 4
                                             and h.height() <= w.height() + 4 for h, w in zip(holes, want))
        check(ok, f"шаг {i + 1} ({key_name}): подсветка совпадает с кнопками {holes} / {want}")
        card = QRect(tour.card.pos(), tour.card.size())
        check(area.contains(card), f"шаг {i + 1}: карточка внутри окна {card}")
        check(not any(card.intersects(h) for h in tour.holes), f"шаг {i + 1}: карточка не закрывает подсвеченное")
        check(tour.step_label.text() == i18n.tr("tour.step", i=i + 1, total=n), f"шаг {i + 1}: «Шаг N из M»")
    # Enter и Ctrl+C во время знакомства снимка не делают; щелчок по кнопке панели тоже
    tour.show_step(0)
    key(sel, Qt.Key.Key_Return)
    check(tour.index == 1 and not done, "Enter листает дальше, снимок не делается")
    key(sel, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    check(not done and sel.tour is tour and tour.index == 1, "Ctrl+C не снимает и не листает")
    QTest.mouseClick(tour, Qt.MouseButton.LeftButton, pos=buttons["copy"].center())
    settle()
    check(not done and sel.tour is tour, "щелчок по кнопке панели под знакомством ничего не делает")
    QTest.mouseClick(tour, Qt.MouseButton.RightButton, pos=QPoint(5, 5))
    settle()
    check(not done and sel.tour is tour, "правый щелчок окно не закрывает")
    key(sel, Qt.Key.Key_Left)
    check(tour.index == 0 and not tour.back.isEnabled(), "Назад на первом шаге недоступен")
    # до конца кнопками
    for i in range(n - 1):
        tour.next.click()
    check(tour.index == n - 1 and tour.next.text() == i18n.tr("tour.finish"), "последний шаг: кнопка «Готово»")
    tour.next.click()
    settle()
    check(sel.tour is None and sel.kept is None and not done and sel.isVisible(),
          "после последнего шага: знакомство закрыто, пример рамки убран, окно выделения живо")
    # после знакомства окно работает как раньше
    sel.kept = QRect(100, 100, 300, 200)
    sel._do("edit")
    check(len(done) == 1, "после знакомства «Редактировать» снимает как обычно")

    # второй показ не включает
    sel2 = selector(W, cfg)
    check(not sel2.maybe_start_tour() and sel2.tour is None and sel2.kept is None, "второй показ: знакомства нет")
    # по запросу из меню
    sel2.tour_force = True
    check(sel2.maybe_start_tour() and sel2.tour is not None, "по запросу из меню знакомство включается снова")
    # Esc пропускает, окно остаётся
    done2 = []
    sel2.finished.connect(lambda *_a: done2.append(1))
    key(sel2, Qt.Key.Key_Escape)
    check(sel2.tour is None and not done2 and sel2.isVisible() and sel2.kept is None, "Esc пропускает знакомство, окно остаётся")
    key(sel2, Qt.Key.Key_Escape)
    check(len(done2) == 1, "второй Esc закрывает окно выделения как обычно")
    # кнопка «Пропустить»
    sel3 = selector(W, cfg)
    sel3.tour_force = True
    sel3.maybe_start_tour()
    sel3.tour.skip.click()
    settle()
    check(sel3.tour is None and sel3.kept is None, "кнопка «Пропустить» закрывает знакомство")
    # прошлая область сохраняется, своя рамка не стирается
    last = QRect(150, 120, 320, 200)
    sel4 = selector(W, cfg, last=last)
    sel4.tour_force = True
    sel4.maybe_start_tour()
    check(sel4.kept == last and not sel4._tour_demo, "своя прошлая область остаётся рамкой знакомства")
    sel4.tour.skip.click()
    settle()
    check(sel4.kept == last, "после знакомства прошлая область на месте")
    for s in (sel, sel2, sel3, sel4):
        try:
            s._done = True
            s.close()
        except RuntimeError:
            pass

# пункт меню значка
class Stub:
    selector = None
    _force_selector_tour = False
    calls = []

    def capture_region(self, delay=0):
        self.calls.append(delay)


stub = Stub()
appmod.Clipshot.demo_selector_tour(stub)
check(stub._force_selector_tour is True and stub.calls == [250], "пункт меню просит знакомство и запускает выделение")
import inspect
check("demo_selector_tour" in inspect.getsource(appmod.Clipshot._build_tray_menu), "пункт есть в меню значка")
for code in i18n.LANGUAGES:
    for k in [f"seltour.s{n}_{part}" for n in range(1, 9) for part in ("title", "text")] + ["app.menu_tour_selector"]:
        check(bool(i18n.tr_in(code, k)) and i18n.tr_in(code, k) != k, f"{code}: есть строка {k}") if False else None

# 12 языков: строки есть, шаги проходят, карточка помещается и не закрывает подсвеченное
for code in i18n.LANGUAGES:
    i18n.set_language(code)
    for W in (1280, 800):
        cfg = dict(appmod.DEFAULTS)
        sel = selector(W, cfg)
        sel.tour_force = True
        sel.maybe_start_tour()
        t = sel.tour
        keys_ok = all(i18n.tr(f"seltour.s{n}_{part}") != f"seltour.s{n}_{part}" for n in range(1, 9) for part in ("title", "text"))
        check(keys_ok and i18n.tr("app.menu_tour_selector") != "app.menu_tour_selector", f"{code}: строки знакомства есть")
        bad = []
        for i in range(len(t.steps)):
            t.show_step(i)
            card = QRect(t.card.pos(), t.card.size())
            if not sel.rect().contains(card) or any(card.intersects(h) for h in t.holes) \
                    or t.text.height() < 10 or t.card.height() > sel.height() * 0.6:
                bad.append(i + 1)
        check(len(t.steps) == 8 and not bad, f"{code} {W}: 8 шагов, карточка на месте (проблемные шаги: {bad})")
        t.finish()
        sel._done = True
        sel.close()
i18n.set_language("ru")

print("FAILURES:", len(failures))
sys.exit(1 if failures else 0)
