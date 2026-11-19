# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Китайский интерфейс: иероглифы и полноширинная пунктуация 、。，：（） берутся из китайского шрифта
(fonts.CJK_FAMILIES), а не из случайного шрифта системы (узкие знаки с пустотой). Смена языка любым путём
(i18n.set_language) сразу меняет запасные шрифты; на остальных языках шрифт прежний, без китайских семейств.
Если на машине нет ни одного из CJK_FAMILIES, проверка шрифта пропускается (порядок семейств проверяется всегда).
Запуск: QT_QPA_PLATFORM=offscreen python3 tests/cjk_punct_test.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.pop("CLIPSD_LANG", None)
from PyQt6.QtGui import QFontDatabase, QTextLayout  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
from clipshot import fonts, i18n  # noqa: E402

failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def run_fonts(text):
    lay = QTextLayout(text, app.font())
    lay.beginLayout()
    line = lay.createLine()
    lay.endLayout()
    out = []
    for run in line.glyphRuns():
        out.append((run.rawFont().familyName(), len(run.glyphIndexes())))
    return out


i18n.set_language("ru")
fonts.install(app)
base = list(app.font().families())
check(not any(f in base for f in fonts.CJK_FAMILIES), f"ru: без китайских семейств ({base})")
i18n.set_language("zh")   # без явного fonts.add_cjk: шрифты идут за языком сами (i18n.on_change)
fam = list(app.font().families())
check(fam[:len(base)] == base and any(f in fam for f in fonts.CJK_FAMILIES),
      f"zh: прежние семейства первыми, китайские добавлены ({fam})")
have = [f for f in fonts.CJK_FAMILIES if f in QFontDatabase.families()]
if have:
    for ch in "、。，：（）语":
        got = run_fonts(ch)
        check(bool(got) and all(name in fonts.CJK_FAMILIES for name, _n in got), f"zh: «{ch}» из {got}")
else:
    print("skip: на машине нет китайского шрифта из CJK_FAMILIES")
i18n.set_language("de")
check(list(app.font().families()) == base, f"de: снова прежние семейства ({list(app.font().families())})")
i18n.set_language("ru")
check(list(app.font().families()) == base, "ru: шрифт как был")
print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено: {len(failures)}")
from clipshot.exitutil import quick_exit  # noqa: E402
quick_exit(1 if failures else 0)
