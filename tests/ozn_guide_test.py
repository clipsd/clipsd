# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""1.36.1: «Ознакомление»: правило владельца 23.11.2026 для списка, одна зелёная кнопка, шаги в настоящем окне выделения.

(1) В CATALOG нет вида "info" и нет пунктов оформления (forma, ten_ramka); у каждого пункта есть правая часть (не пустая).
(2) На каждом пункте и в каждой фазе зелёная кнопка (clipPrimary) не больше одной. (3) «Попробовать по-настоящему» для
«Закрепить»: окно выделения получает подсказку, подсвечена плитка «pin», шаг 2 наступает после выбора области, подсказки
нет в вырезанном снимке. У других настоящих действий (окно, другая область, область, весь экран) свои подсказки.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/ozn_guide_test.py
"""
import tmpclean  # noqa: F401
import os
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
tmp = tempfile.mkdtemp(prefix="clipsd-ozng-")
for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[name] = os.path.join(tmp, name)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.pop("CLIPSD_LANG", None)

from PyQt6.QtCore import QRect, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QImage, QPixmap  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QPushButton  # noqa: E402

qapp = QApplication(sys.argv)
from clipshot import app as appmod, i18n, novoe, oznakomlenie  # noqa: E402
from clipshot.selector import RegionSelector  # noqa: E402

failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


def settle(ms=80):
    for _ in range(4):
        qapp.processEvents()
        QTest.qWait(max(1, ms // 4))


i18n.set_language("ru")
# 1. правило владельца
kinds = {c[3] for c in oznakomlenie.CATALOG}
check("info" not in kinds, f"в списке нет вида «info» (виды: {sorted(kinds)})")
check({c[0] for c in oznakomlenie.CATALOG}.isdisjoint({"forma", "oznakomlenie", "color_swatch", "qr_big", "ocr_install", "otlozhit", "settings_apply", "phone_target"}),
      "форма снимка и внутренние доработки в список не входят; «Тень, рамка и поля» на месте")
check({"pdf", "qr_chtenie", "pechat", "stikery", "zakrepit"} <= set(oznakomlenie.BY_ID), "действующие функции на месте: PDF, QR, печать, стикеры, закрепить")
check("ten_ramka" in oznakomlenie.BY_ID and "→" in i18n.tr("ozn.ten_ramka_text") and "ten_ramka" in oznakomlenie.new_ids(dict(appmod.DEFAULTS), "1.36.0"), "«Тень, рамка и поля» в списке, путь через меню назван")

a = appmod.Clipshot(qapp)
a.notify = lambda *_x: None
a.save_config = lambda: None
a.config.update(dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True))
novoe.on_start(a.config)
novoe.window_done(a.config)
win = a.open_oznakomlenie()
settle(200)


def primaries():
    return [b.text() for b in win.findChildren(QPushButton) if b.objectName() == "clipPrimary" and b.isVisible()]


empty, many, no_demo = [], [], []
for ident in list(win.rows):
    win.select(ident)
    settle(120)
    if win.stack.currentIndex() == 3:
        empty.append(ident)
    if not win.show_button.isVisible():
        no_demo.append(ident)
    if len(primaries()) > 1:
        many.append((ident, "выбран", primaries()))
    for phase_done in (False, True):   # после «Получилось»
        win._update_next(phase_done)
        win.refresh_primary()
        if len(primaries()) > 1:
            many.append((ident, "готово" if phase_done else "обычно", primaries()))
check(not empty, f"нет пунктов с пустой правой частью: {empty}")
check(not many, f"на каждом пункте и в каждой фазе зелёная кнопка не больше одной: {many[:3]}")
check(not no_demo, f"у каждого пункта есть кнопка «Показать»: без неё {no_demo}")
win.select("arrows")
settle(100)
check(primaries() == [win.show_button.text()], "до показа зелёная только «Показать»")
win.close()
settle(100)

# 3. подсказка шагов в настоящем окне выделения
desk = QPixmap(1200, 700)
desk.fill(QColor("#e8eef5"))
sel = RegionSelector(desk, QRect(0, 0, 1200, 700))
sel.guide = "zakrepit"
sel.resize(1200, 700)
sel.show()
settle(100)
check(sel.guide_step() == 1 and any(cur for _t, cur in sel.guide_lines()[:1]), "до выбора области текущий шаг 1")
check(sel.guide_lines()[0][0] == i18n.tr("ozn.guide_select"), "шаг 1: «Обведите мышью…»")
sel.close()
sel = RegionSelector(desk, QRect(0, 0, 1200, 700), last_rect=QRect(300, 200, 400, 250))
sel.guide = "zakrepit"
sel.resize(1200, 700)
sel.show()
settle(100)
check(sel.guide_step() == 2 and sel.guide_lines()[1][1], "после выбора области текущий шаг 2")
print("кнопки панели:", [k for k, *_ in sel._bar_layout()[0]], "no_pin:", sel._no_pin, "step:", sel.guide_step(), flush=True)
target = sel.guide_target_rect()
check((target is not None and not target.isEmpty()) or sel._no_pin, "плитка «pin» подсвечивается (на узкой панели её нет: тогда названа клавиша F3)")
check("F3" in sel.guide_lines()[1][0], f"в шаге 2 названа клавиша F3: {sel.guide_lines()[1][0]}")
with_guide = sel.grab().toImage()
sel.guide = None
without = sel.grab().toImage()
check(with_guide != without, "подсказка рисуется на окне выделения")
crop = sel._crop(QRect(300, 200, 400, 250)).toImage()
ref = desk.copy(QRect(300, 200, 400, 250)).toImage()
check(crop.size() == ref.size() and crop == ref, "в вырезанном снимке подсказки нет (он берётся из замороженного кадра)")
for ident, key in (("other_area", "manual"), ("region", "edit"), ("full", "edit")):
    sel.guide = ident
    check(sel.GUIDE_TARGETS.get(ident) == key and sel.guide_lines()[1][1], f"у «{ident}» своя подсказка, кнопка «{key}»")
sel.close()
print("\nИТОГ:", "провалено %d" % len(failures) if failures else "всё хорошо")
sys.exit(1 if failures else 0)
