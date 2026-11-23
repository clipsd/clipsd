# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""«Скрыть личные данные» (проверка выпуска 1.36.0, находки В2 и В3).

В2: после скрытия и «Сохранить» / «Сохранить в PDF» / «Копировать» / «Закрепить» автосохранённый файл в папке снимков
не содержит исходных пикселей на месте номера (обновляется сразу при применении скрытия).
В3: на месте скрытого сплошная заливка (дисперсия пикселей около нуля), а не пикселизация; режим «последние 4»
закрывает скрываемые цифры целиком. Обычное «Размытие» осталось пикселизацией. Все данные вымышленные.
"""
import faulthandler; faulthandler.dump_traceback_later(90, exit=True)
import tmpclean  # noqa: F401
import os
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.pop("CLIPSD_LANG", None)
TMP = tempfile.mkdtemp(prefix="clipsd-zakr-")
for _n in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[_n] = os.path.join(TMP, _n)
os.environ["HOME"] = TMP

from PyQt6.QtCore import QRect, QRectF, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)
from clipshot import app as appmod, i18n, ocr  # noqa: E402
from clipshot.shapes import BLUR, Shape  # noqa: E402

i18n.set_language("ru")
failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


def settle(n=6):
    for _ in range(n):
        app.processEvents()


a = appmod.Clipshot(app)
a.notify = lambda *_: None
SAVE_DIR = os.path.join(TMP, "Saved")
SNAP_DIR = os.path.join(TMP, "Snaps")
os.makedirs(SAVE_DIR, exist_ok=True)
os.makedirs(SNAP_DIR, exist_ok=True)
a.config.update(dict(tour_done=True, theme_chosen=True, tour_selector_done=True, auto_save=True,
                     save_dir=SAVE_DIR, snapshots_dir=SNAP_DIR, save_ask=False))
TEXT = "4111 1111 1111 1111"
CARD = QRect(18, 40, 200, 26)


def make_image():
    img = QImage(700, 200, QImage.Format.Format_RGB32)
    img.fill(QColor("#ffffff"))
    p = QPainter(img)
    f = QFont("DejaVu Sans")
    f.setPixelSize(18)
    p.setFont(f)
    p.setPen(QColor("#000000"))
    p.drawText(20, 60, TEXT)
    p.end()
    return img


def variance(img, rect):
    """Число разных цветов в области: у сплошной заливки он равен 1."""
    seen = set()
    for y in range(rect.top(), rect.bottom() + 1):
        for x in range(rect.left(), rect.right() + 1):
            seen.add(img.pixel(x, y))
    return len(seen)


def open_with_words(img, saved):
    ed = a.open_editor(QImage(img), None)
    ed.autosave_path = saved
    settle(30)
    words = [ocr.Word(t, QRectF(20 + i * 52, 44, 48, 20), 0) for i, t in enumerate(TEXT.split())]
    ed.canvas.set_words(words, 1.0)
    return ed


def same_as_original(out, orig, rect):
    return out.copy(rect) == orig.copy(rect)


orig = make_image()
INNER = CARD.adjusted(3, 3, -3, -3)   # без скруглённых углов заливки (радиус 2.5)

# --- В3: сплошная заливка вместо пикселизации
saved = a.autosave(QImage(orig))
ed = open_with_words(orig, saved)
ed._privacy_run(list(ed.canvas.words))
settle(10)
shapes = [s for s in ed.canvas.shapes if s.kind == BLUR]
check(len(shapes) >= 1 and all(s.solid for s in shapes), f"скрытие ставит сплошные фигуры: {len(shapes)}")
out = ed.render_image()
check(not same_as_original(out, orig, CARD), "на месте номера картинка изменилась")
check(variance(out, INNER) == 1, f"сплошная заливка: в области один цвет ({variance(out, INNER)})")
dark = QColor(out.pixel(INNER.center().x(), INNER.center().y()))
check(dark.lightness() < 110, f"заливка тёмно-серая ({dark.name()})")
# копия фигуры (отмена и повтор) остаётся сплошной
check(all(s.copy().solid for s in shapes), "копия фигуры сохраняет сплошную заливку")
# обычное «Размытие», выбранное человеком, осталось пикселизацией
c = ed.canvas
manual = Shape(BLUR, c.color, c.pen_size, c.shapes[0].points[0])
check(manual.solid is False, "обычное размытие не сплошное")
# В5 (проверка круг 2): номер под обычным «Размытием» не считается скрытым: пикселизацию можно подобрать
from clipshot import privacy_ui  # noqa: E402


class _Canvas:
    def __init__(self, shapes):
        self.shapes = shapes


box = QRectF(10, 10, 100, 20)
pix = Shape(BLUR, c.color, c.pen_size, box.topLeft())
pix.points.append(box.bottomRight())
check(pix.rect().contains(box) and not privacy_ui.already_hidden(_Canvas([pix]), [box]),
      "обычное размытие поверх номера: номер не считается скрытым")
pix.solid = True
check(privacy_ui.already_hidden(_Canvas([pix]), [box]), "сплошная заливка поверх номера: номер скрыт")

# --- В2: автосохранение сразу после скрытия, до любого вывода
auto = QImage(saved).convertToFormat(orig.format())
check(not same_as_original(auto, orig, CARD), "сразу после скрытия в автосохранении нет исходных пикселей номера")
check(variance(auto, INNER) == 1, "в автосохранении на месте номера сплошная заливка")

# --- В2: выводы
for action in ("save", "pdf", "copy", "pin", "last4"):
    saved = a.autosave(QImage(orig))
    check(same_as_original(QImage(saved).convertToFormat(orig.format()), orig, CARD), f"{action}: старт, автосохранение равно оригиналу")
    ed = open_with_words(orig, saved)
    ed._privacy_run(list(ed.canvas.words))
    settle(10)
    if action == "last4":
        s = ed.privacy_session
        s.set_mode(0, "last4")
        settle(10)
    elif action == "save":
        ed.save_and_close()
    elif action == "pdf":
        ed.save_pdf()
    elif action == "copy":
        ed.copy_to_clipboard()
    elif action == "pin":
        ed.pin_image()
    settle(20)
    auto = QImage(saved).convertToFormat(orig.format())
    if action == "last4":
        hidden = QRect(CARD.left(), CARD.top(), 150, CARD.height()).adjusted(3, 3, -3, -3)
        check(variance(auto, hidden) == 1, "последние 4: скрытые цифры закрыты сплошной заливкой, без просвечивания")
        shown = QRect(160, 44, 56, 20)
        check(variance(auto, shown) > 1, "последние 4: открытая часть не залита целиком")
    else:
        check(not same_as_original(auto, orig, CARD), f"{action}: в автосохранении нет исходных пикселей номера")
        check(variance(auto, INNER) == 1, f"{action}: в автосохранении на месте номера сплошная заливка")
    try:
        ed.exported = True
        ed.canvas.modified = False
        ed.close()
    except RuntimeError:
        pass
    settle(10)

print("ИТОГ:", "FAIL " + str(len(failures)) if failures else "все проверки пройдены")
sys.exit(1 if failures else 0)
