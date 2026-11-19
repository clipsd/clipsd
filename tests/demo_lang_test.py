# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later
"""The example picture of the tour is in the language of the interface and follows a change of language (1.31.2).

19.11.2026, Windows: ClipSD started in Russian, the owner chose Bulgarian on the first step of the tour; the panels
and the tour switched, the example picture behind them («Пример снимка», «Здесь можно потренироваться…», «Кнопка»)
stayed in Russian: it was drawn once when the editor opened.

Checks: the texts drawn in the example are those of the chosen language (ru, bg, de, zh: no Cyrillic in de and zh,
Chinese characters in zh); the pictures differ per language; in an open tour, picking another language redraws the
example in that language and keeps the marks on it; a cropped example and an ordinary snapshot are not touched.

Run: QT_QPA_PLATFORM=offscreen python3 tests/demo_lang_test.py [folder for snapshots]
"""
import os
import re
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
tmp = tempfile.mkdtemp(prefix="clipsd-demo-lang-")
for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[name] = os.path.join(tmp, name)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.pop("CLIPSD_LANG", None)
SNAP = sys.argv[1] if len(sys.argv) > 1 else ""

from PyQt6.QtCore import QPoint, QPointF, QRect  # noqa: E402
from PyQt6.QtGui import QColor, QImage  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
from clipshot import app as appmod, fonts, i18n  # noqa: E402
from clipshot.editor import EditorWindow  # noqa: E402
from clipshot.shapes import RECT, Shape  # noqa: E402

failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


CYR = re.compile(r"[Ѐ-ӿ]")
CJK = re.compile(r"[一-鿿]")


def same(a: QImage, b: QImage) -> bool:
    fmt = QImage.Format.Format_ARGB32
    return a.convertToFormat(fmt) == b.convertToFormat(fmt)


def settle(n=4):
    for _ in range(n):
        app.processEvents()


pictures = {}
for lang in ("ru", "bg", "de", "zh"):
    i18n.set_language(lang)
    fonts.add_cjk(app)
    texts = appmod.demo_texts()
    check(texts == {k: i18n.tr_in(lang, k) for k in appmod.DEMO_KEYS} and all(texts.values()),
          f"{lang}: the example uses the texts of {lang}")
    joined = " ".join(texts.values())
    if lang in ("de", "zh"):
        check(not CYR.search(joined), f"{lang}: no Cyrillic in the example ({joined[:60]}…)")
    else:
        check(bool(CYR.search(joined)), f"{lang}: Cyrillic language, Cyrillic text")
    if lang == "zh":
        check(bool(CJK.search(joined)), "zh: Chinese characters in the example")
    pictures[lang] = appmod.demo_image()
    if SNAP and lang in ("bg", "de"):
        pictures[lang].save(os.path.join(SNAP, f"demo-{lang}.png"))
check(not same(pictures["ru"], pictures["bg"]) and not same(pictures["bg"], pictures["de"])
      and not same(pictures["de"], pictures["zh"]), "the pictures differ per language")


class Ctx:
    def __init__(self):
        self.config = dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True)
        self.icon = appmod.make_icon()

    def save_config(self):
        pass

    def notify(self, text):
        pass


# the tour over the example: ru -> bg on the first step
i18n.set_language("ru")
fonts.add_cjk(app)
ed = EditorWindow(appmod.demo_image(), Ctx(), QPoint(0, 0))
ed.demo_maker = appmod.demo_image
ed.present()
settle()
check(same(ed.canvas.base, pictures["ru"]), "the example opens in Russian")
mark = Shape(RECT, "#ff0000", 3, QPointF(100, 100))
mark.points[1] = QPointF(300, 200)
ed.canvas.shapes.append(mark)   # a mark the person drew: it must stay
ed.start_tour()
settle()
ed.tour.lang_buttons["bg"].click()
settle()
check(i18n.current() == "bg" and same(ed.canvas.base, pictures["bg"]),
      "Bulgarian picked in the tour: the example is redrawn in Bulgarian")
check(ed.canvas.shapes == [mark], "marks on the example stay")
if SNAP:
    img = ed.grab().toImage()
    img.save(os.path.join(SNAP, "znakomstvo-primer-ru-bg.png"))
ed.tour.lang_buttons["de"].click()
settle()
check(same(ed.canvas.base, pictures["de"]), "then German: the example in German")
ed.canvas.shapes.clear()
ed.tour.finish()
# a cropped example keeps its picture (another size), an ordinary snapshot is never redrawn
ed.canvas.base = ed.canvas.base.copy(QRect(0, 0, 400, 300))
cropped = QImage(ed.canvas.base)
ed.retranslate()
check(same(ed.canvas.base, cropped), "a cropped example is not replaced")
settle()
ed.canvas.modified, ed.exported = False, True
ed.close()
settle()
shot = QImage(900, 520, QImage.Format.Format_RGB32)
shot.fill(QColor("#336699"))
ed2 = EditorWindow(shot, Ctx(), QPoint(0, 0))
ed2.present()
settle()
i18n.set_language("zh")
ed2.retranslate()
check(same(ed2.canvas.base, shot), "an ordinary snapshot is not redrawn on a change of language")
settle()
ed2.canvas.modified, ed2.exported = False, True
ed2.close()
settle()

print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено {len(failures)}")
sys.exit(1 if failures else 0)
