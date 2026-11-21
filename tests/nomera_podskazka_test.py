# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Подсказка о счёте номеров по цветам и читаемость подсказки у палитры (замечание владельца 21.11.2026: «при смене
цвета у номеров сообщение мало видно, кнопка мало видна»).

При инструменте «Номер» выбран другой цвет: у палитры карточка «Этот цвет: нумерация с N» и «У каждого цвета свой счёт
номеров» с образцом цвета, без кнопки; 4 секунды или до следующего действия; первые 3 раза (number_hint_count).
N считается по уже поставленным номерам этого цвета. Другие инструменты и тот же цвет подсказку не показывают.
Подсказка «Цвет изменён только у этого объекта»: текст 14 / 13 px цветом основного текста, кнопка мягкая синяя,
контраст по пикселям снимка не ниже 4,5:1 в светлой и тёмной теме, кнопка не обрезана, без QGraphicsEffect.
12 языков: строки на месте, с {n}, без длинных тире, карточка помещается в окне.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/nomera_podskazka_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import json
import os
import sys
import tempfile
from collections import Counter

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
os.environ.pop("CLIPSD_LANG", None)
_cfg = os.path.join(tempfile.mkdtemp(prefix="clipsd-nomhint-"), "screen.json")
with open(_cfg, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1280, "height": 720,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _cfg

from PyQt6.QtCore import QPoint, QRect, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QFontMetrics, QImage  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
from clipshot import app as appmod, i18n, themes  # noqa: E402
from clipshot import editor as em  # noqa: E402
from clipshot.dialogs import PALETTES  # noqa: E402
from clipshot.editor import ARROW, NUMBER, PALETTE, EditorWindow  # noqa: E402

LANGS = ("ru", "en", "es", "de", "fr", "it", "pt", "pl", "tr", "uk", "bg", "zh")
RED, BLUE, GREEN = PALETTE[0], PALETTE[4], PALETTE[3]
failures = []
checks = [0]


def check(cond, msg):
    checks[0] += 1
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def settle(ms=30):
    QTest.qWait(ms)


def lum(c):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c.red()) + 0.7152 * ch(c.green()) + 0.0722 * ch(c.blue())


def contrast(a, b):
    la, lb = sorted((lum(QColor(a)), lum(QColor(b))), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def text_contrast(widget, root):
    """Контраст текста виджета по пикселям снимка root: фон самый частый цвет, текст самый далёкий от него."""
    img = root.grab().toImage()
    dpr = img.devicePixelRatio()
    tl = widget.mapTo(root, QPoint(0, 0))
    r = QRect(int(tl.x() * dpr), int(tl.y() * dpr), int(widget.width() * dpr), int(widget.height() * dpr)).intersected(img.rect())
    counts = Counter(img.pixel(x, y) & 0xFFFFFF for y in range(r.top(), r.bottom() + 1) for x in range(r.left(), r.right() + 1))
    bg = QColor(counts.most_common(1)[0][0])
    return max([contrast(bg, QColor(v)) for v, n in counts.items() if n >= 2] or [1.0])


class Ctx:
    def __init__(self, **kw):
        self.config = dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True, color=RED, **kw)
        self.icon = appmod.make_icon()

    def save_config(self):
        pass

    def notify(self, text):
        pass

    def copy_image(self, image, config=None):
        pass


def mk(theme="standard", **kw):
    ctx = Ctx(ui_theme=theme, **kw)
    themes.apply_app(app, ctx.config)
    img = QImage(760, 420, QImage.Format.Format_RGB32)
    img.fill(QColor("#f4f6f9"))
    ed = EditorWindow(img, ctx, QPoint(0, 0))
    ed.present()
    settle(60)
    return ed, ctx


def click(ed, x, y):
    z = ed.canvas.zoom
    QTest.mouseClick(ed.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(x * z), int(y * z)))
    settle(40)


def hint(ed):
    h = ed._pen_hint
    return h if h is not None and h.isVisible() else None


def done(ed):
    ed.canvas.modified, ed.exported = False, True
    ed.close()
    settle(20)


# --- 1. подсказка номеров ----------------------------------------------------------------------------------------
i18n.set_language("ru")
ed, ctx = mk()
ed.select_tool(NUMBER)
click(ed, 150, 150)
click(ed, 250, 200)
check(sum(1 for s in ed.canvas.shapes if s.kind == NUMBER) == 2, "поставлены красные 1 и 2")
check(hint(ed) is None, "пока цвет не меняли, подсказки нет")
ed.select_color(BLUE)
h = hint(ed)
check(h is not None and h.kind == "number", "выбран синий при инструменте «Номер»: подсказка у палитры")
check(h is not None and h.title.text() == "Этот цвет: нумерация с 1" and h.sub.text() == "У каждого цвета свой счёт номеров",
      f"текст: {h.title.text() if h else None!r} / {h.sub.text() if h else None!r}")
check(h is not None and h.title_sample.isVisible() and QColor(BLUE).name() in h.title_sample.styleSheet()
      and not h.button.isVisible(), "образец синего у заголовка, кнопки нет")
check(h is not None and h.timer.isActive() and h.timer.interval() == em.PenHint.NUMBER_MS == 4000, "держится 4 секунды")
check(h is not None and h.accessibleName().startswith("Этот цвет: нумерация с 1"), "имя для экранного диктора")
check(ctx.config.get("number_hint_count") == 1, "счётчик показов: 1")
r = h.geometry() if h else QRect()
canvas_area = QRect(ed.scroll.viewport().mapTo(ed, QPoint(0, 0)), ed.scroll.viewport().size())
check(h is not None and canvas_area.contains(r), "подсказка внутри области снимка, у палитры")
for w, name in ((h.title, "заголовок"), (h.sub, "пояснение")) if h else ():
    k = text_contrast(w, ed)
    check(k >= 4.5, f"светлая: {name} {k:.1f}:1 (норма 4,5)")
click(ed, 400, 250)
check(hint(ed) is None, "следующее действие (поставлен номер) убирает подсказку")
blue = [s for s in ed.canvas.shapes if s.kind == NUMBER and s.color.name() == QColor(BLUE).name()]
check(len(blue) == 1 and blue[0].number == 1, "синий номер начался с 1")
ed.select_color(RED)
h = hint(ed)
check(h is not None and h.title.text() == "Этот цвет: нумерация с 3", "назад к красному: «нумерация с 3» (красные 1, 2 уже есть)")
h.timer.timeout.emit()
check(hint(ed) is None, "через 4 секунды уходит сама")
ed.select_color(RED)
check(hint(ed) is None, "тот же цвет ещё раз: подсказки нет")
ed.select_color(GREEN)
check(hint(ed) is not None and ctx.config.get("number_hint_count") == 3, "третий показ")
click(ed, 500, 300)
ed.select_color(BLUE)
check(hint(ed) is None and ctx.config.get("number_hint_count") == 3, "после трёх показов больше не показывается")
done(ed)

ed, ctx = mk()
ed.select_tool(ARROW)
ed.select_color(BLUE)
check(hint(ed) is None and not ctx.config.get("number_hint_count"), "другой инструмент: смена цвета без подсказки номеров")
done(ed)

# --- 2. читаемость подсказок в светлой и тёмной теме ---------------------------------------------------------------
for theme in ("standard", "pro"):
    dark = theme == "pro"
    tag = "тёмная" if dark else "светлая"
    ed, ctx = mk(theme)
    ed.select_tool(NUMBER)
    click(ed, 150, 150)
    ed.select_color(BLUE)
    h = hint(ed)
    for w, name in ((h.title, "заголовок номеров"), (h.sub, "пояснение номеров")) if h else ():
        k = text_contrast(w, ed)
        check(k >= 4.5, f"{tag}: {name} {k:.1f}:1")
    click(ed, 300, 220)
    first = next(s for s in ed.canvas.shapes if s.kind == NUMBER)
    ed.canvas.select(first)   # выделен старый номер: перекрашивается он, подсказка с кнопкой
    settle(30)
    ed.select_color(GREEN)
    h = hint(ed)
    check(h is not None and h.kind == "color" and h.button.isVisible(), f"{tag}: выделенный номер перекрашен, подсказка с кнопкой")
    if h is not None:
        c = PALETTES[dark]
        check(h.title.font().pixelSize() >= 14 and h.sub.font().pixelSize() >= 13, f"{tag}: текст 14 / 13 px")
        for w, name in ((h.title, "заголовок"), (h.sub, "пояснение"), (h.button, "кнопка")):
            k = text_contrast(w, ed)
            check(k >= 4.5, f"{tag}: {name} {k:.1f}:1")
        bg, fg, edge, _hov = em.HINT_BUTTON[dark]
        check(contrast(fg, bg) >= 4.5 and contrast(edge, c["card"]) >= 1.6, f"{tag}: кнопка мягкая синяя, текст {contrast(fg, bg):.1f}:1")
        fm = QFontMetrics(h.button.font())
        check(h.button.width() >= fm.horizontalAdvance(h.button.text()) + 20, f"{tag}: подпись кнопки целиком")
        check(h.graphicsEffect() is None, f"{tag}: без QGraphicsEffect")
    done(ed)

# --- 3. 12 языков ------------------------------------------------------------------------------------------------
for lang in LANGS:
    i18n.set_language(lang)
    t, sub = i18n.tr("editor.number_hint_title", n=7), i18n.tr("editor.number_hint_sub")
    check("7" in t and "{" not in t and sub and "—" not in t + sub, f"{lang}: «{t}» / «{sub}»")
    ed, ctx = mk()
    ed.select_tool(NUMBER)
    click(ed, 150, 150)
    ed.select_color(BLUE)
    h = hint(ed)
    ok = h is not None and h.width() <= ed.scroll.viewport().width() and \
        h.title.width() >= QFontMetrics(h.title.font()).horizontalAdvance(h.title.text())
    check(ok, f"{lang}: карточка помещается, заголовок целиком")
    done(ed)

i18n.set_language("ru")
print(f"ИТОГ: проверок {checks[0]}, провалено: {len(failures)}")
sys.exit(1 if failures else 0)
