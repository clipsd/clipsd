# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
"""1.31.1: панель окна выделения стоит вне рамки (под, над, справа, слева), внутри только если снаружи нигде нет места;
не выходит за монитор, не закрывает рамку и подпись размера, не дёргается у порогов; то же в режиме перевода.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/barplace_test.py
"""
import json
import os
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
_cfg = os.path.join(tempfile.mkdtemp(prefix="clipsd-barplace-"), "screen.json")
with open(_cfg, "w", encoding="utf-8") as _f:   # один экран 1600x1000: окно выделения 1280x720 целиком на нём
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1600, "height": 1000,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _cfg
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
from clipshot import app as appmod
from clipshot.selector import RegionSelector

failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


W, H = 1280, 720


def selector(kept, full=False):
    pm = QPixmap(W, H)
    pm.fill(QColor("#4a78b0"))
    sel = RegionSelector(pm, QRect(0, 0, W, H), last_rect=None if full else kept, full_screen=full)
    sel.tr_cfg, sel.tr_save = dict(appmod.DEFAULTS), lambda: None
    sel.show_zoom = False
    sel.resize(W, H)
    sel.show()
    for _ in range(3):
        app.processEvents()
        QTest.qWait(10)
    return sel


def where(sel):
    bar = sel._bar_layout()[1]
    return sel._bar_place if hasattr(sel, "_bar_place") else None, bar


def on_screen(bar):
    return bar.left() >= 0 and bar.top() >= 0 and bar.right() <= W - 1 and bar.bottom() <= H - 1


# 1. рамка вверху экрана: панель под ней
sel = selector(QRect(300, 60, 520, 200))
place, bar = where(sel)
check(place == "below" and bar.top() > 260 and not bar.intersects(sel.kept) and on_screen(bar), f"рамка вверху: панель под ней ({place}, {bar})")
sel.close()

# 2. рамка внизу экрана: панель сверху, подпись размера не закрыта
r = QRect(300, 480, 520, 220)
sel = selector(r)
place, bar = where(sel)
label_top = r.top() - 40
check(place == "above" and bar.bottom() < r.top() - 24 and not bar.intersects(r) and on_screen(bar),
      f"рамка внизу: панель над ней, подпись «ш/в» свободна ({place}, {bar})")
check(sel.bar_close_rect.right() < W and sel.bar_close_rect.top() >= 0, f"крестик панели в пределах экрана {sel.bar_close_rect}")
sel.close()

# 3. рамка от верхнего до нижнего края: панель сбоку (справа или слева), не закрывает рамку
for rect, expect in ((QRect(100, 10, 200, 700), "right"), (QRect(900, 10, 200, 700), "left")):
    sel = selector(rect)
    place, bar = where(sel)
    check(place == expect and not bar.intersects(rect) and on_screen(bar),
          f"рамка {rect.x()}..{rect.right()} на всю высоту: панель {expect}, вне рамки ({place}, {bar}, уровень {sel.bar_level['name']})")
    check(sel.bar_close_rect.right() < W, f"крестик панели у бокового места на экране {sel.bar_close_rect}")
    sel.close()

# 4. рамка во весь экран: внутри у нижнего края
sel = selector(QRect(0, 0, W, H))
place, bar = where(sel)
check(place == "inside" and sel.kept.contains(bar) and bar.bottom() > H * 0.6, f"рамка во весь экран: панель внутри у нижнего края ({place}, {bar})")
sel.close()

# 5. не дёргается у порога: панель над рамкой, рамку чуть подняли так, что снизу места ровно хватило бы
r = QRect(300, 400, 520, 200)
sel = selector(r)
check(where(sel)[0] == "above", "исходно панель над рамкой (снизу не помещается)")
bar_h = sel._bar_layout()[1].height()
fits_below = H - 4 - bar_h - 6 - 4   # самое нижнее положение верха рамки, при котором снизу помещается без запаса
sel.kept = QRect(300, fits_below - 200 + 1, 520, 200)   # снизу помещается впритык: места на запас нет
check(where(sel)[0] == "above", f"у порога (снизу впритык) панель остаётся над рамкой, не прыгает ({where(sel)[0]})")
sel.kept = QRect(300, fits_below - 200 - 60, 520, 200)   # снизу места с большим запасом
check(where(sel)[0] == "below", f"снизу места с запасом: панель переходит вниз ({where(sel)[0]})")
sel.close()

# 6. режим перевода: рамки нет (kept снят), панель внизу монитора, на экране, и тоже в ряд без перекрытия крестиком
sel = selector(QRect(300, 480, 520, 220))
sel.enter_translate()
bar = sel._bar_layout()[1]
check(sel.kept is None and on_screen(bar) and bar.bottom() > H * 0.7, f"режим перевода без рамки: панель внизу монитора {bar}")
sel.close()

print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено {len(failures)}")
sys.exit(1 if failures else 0)
