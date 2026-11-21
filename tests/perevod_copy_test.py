# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""«Скопировать перевод» копирует всё, что видно как перевод текущего запроса (пробы проверяющего 1.33.0, блокер Б3).

1. Текст уже на языке перевода, сервис переводит его на запасной язык: перевод виден и копируется.
2. Смешанный снимок (абзац по-английски, абзац по-русски): копируются оба абзаца.
3. Ответ прежнего запроса (язык перевода сменён, кусок не переведён заново) не копируется.
4. «Повторить» дважды до перерисовки: один запрос, не два (П-М1).
5. Выбор того же языка во время запроса: нового запроса нет (П-М2).
6. Язык сменён, затем Esc до ответа: после ответа новый запрос не уходит (П-М3).

Распознавание настоящее (Tesseract), сеть подменена. Запуск: QT_QPA_PLATFORM=offscreen python3 tests/perevod_copy_test.py
"""
import tmpclean  # noqa: F401
import json
import os
import sys
import tempfile
import threading
import time

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
os.environ.pop("CLIPSD_LANG", None)
_cfg = os.path.join(tempfile.mkdtemp(prefix="clipsd-pcopy-"), "screen.json")
with open(_cfg, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1600, "height": 1000,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _cfg

from types import SimpleNamespace  # noqa: E402
from PyQt6.QtCore import QPoint, QRect, QRectF, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv[:1])
from clipshot import app as appmod, i18n, ocr, themes, translate  # noqa: E402
from clipshot.editor import EditorWindow, TRANSLATE  # noqa: E402
from clipshot.translate_ui import TranslateCard  # noqa: E402

failures, checks, errors = [], [0], []
_hook = sys.excepthook


def _catch(*exc):
    errors.append(exc)
    _hook(*exc)


sys.excepthook = _catch


def check(cond, msg):
    checks[0] += 1
    print(("OK   " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


def settle(n=6):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(12)


def wait(cond, seconds=60):
    end = time.time() + seconds
    while not cond() and time.time() < end:
        app.processEvents()
        QTest.qWait(30)
    return cond()


if ocr.engine_name() != "tesseract":
    print("распознавания Tesseract нет: тест пропущен")
    sys.exit(0)

W, H = 1100, 520


class Ctx:
    def __init__(self):
        self.config = dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True, translate_view="overlay")
        self.icon = appmod.make_icon()

    def copy_image(self, image):
        pass

    def notify(self, text):
        pass

    def save_config(self):
        pass


def page(lines):
    img = QImage(W, H, QImage.Format.Format_RGB32)
    img.fill(QColor("#ffffff"))
    p = QPainter(img)
    f = QFont("DejaVu Sans")
    f.setPixelSize(44)
    p.setFont(f)
    p.setPen(QColor("#000000"))
    for i, t in enumerate(lines):
        p.drawText(60, 60 + 150 * i, 1000, 70, Qt.AlignmentFlag.AlignLeft, t)
    p.end()
    return img


class Engine:
    name = "MyMemory"
    gate = None
    entered = None
    targets = []

    def translate(self, text, target, source=None):
        Engine.targets.append(target)
        if Engine.entered is not None:
            Engine.entered.set()
        if Engine.gate is not None:
            Engine.gate.wait(10)
        cyr = any("а" <= ch <= "я" for ch in text.lower())
        return f"[{target}] " + " ".join(text.split()), source or ("ru" if cyr else "en")


translate.engines_from_config = lambda c: [Engine()]
translate.check_mymemory_email = lambda email, cb: cb("")
translate.check_google_key = lambda key, cb: cb("")


def editor(lines):
    i18n.set_language("ru")
    ctx = Ctx()
    themes.apply_app(app, ctx.config)
    ed = EditorWindow(page(lines), ctx, QPoint(20, 20))
    ed.present()
    settle()
    ed.select_tool(TRANSLATE)
    settle()
    return ed, ctx


def drag(layer, a, b):
    a, b = QPoint(*a), QPoint(*b)
    QTest.mousePress(layer, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, a)
    for i in range(1, 9):
        QTest.mouseMove(layer, a + (b - a) * i / 8)
    QTest.mouseRelease(layer, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, b)


def close(ed):
    try:
        ed.canvas.modified, ed.exported = False, True
        ed.close()
    except RuntimeError:
        pass
    settle()


clip = QGuiApplication.clipboard()
before = len(errors)

# 1. текст уже на языке перевода: переводится на запасной язык, перевод виден и копируется
ed, ctx = editor(["Откройте окно настроек"])
Engine.targets = []
drag(ed.tr_layer, (40, 40), (700, 150))
card = None
if wait(lambda: ed.tr_layer.tr_cards and ed.tr_layer.tr_cards[0].state == "done", 90):
    card = ed.tr_layer.tr_cards[0]
settle()
check(card is not None and card.blocks, f"1: перевод на запасной язык готов {[ (b['src'], b['tgt']) for b in (card.blocks if card else [])]}")
check(ed.tr_copy_button.isEnabled(), "1: кнопка доступна")
clip.setText("SENTINEL")
ed.tr_copy_button.click()
settle()
check(card is not None and clip.text() == card.text() and clip.text() != "SENTINEL", f"1: скопирован видимый перевод «{clip.text()[:50]}»")
close(ed)

# 2. смешанный снимок: оба абзаца
ed, ctx = editor(["Open the settings window", "Откройте окно настроек"])
drag(ed.tr_layer, (40, 40), (1060, 400))
ok = wait(lambda: ed.tr_layer.tr_cards and ed.tr_layer.tr_cards[0].state == "done", 90)
settle()
card = ed.tr_layer.tr_cards[0]
clip.setText("SENTINEL")
ed.tr_copy_button.click()
settle()
texts = [b["text"] for b in card.blocks]
check(ok and len(texts) >= 2 and all(t in clip.text() for t in texts), f"2: скопированы все абзацы {len(texts)}: «{clip.text()[:70]}»")
# 3. ответ прежнего запроса не копируется: язык сменили, кусок не переведён заново
ctx.config["translate_to"] = "de"
card.req_lang = "ru"
ed._update_info()
clip.setText("SENTINEL")
ed.tr_copy_button.click()
settle()
check(clip.text() == "SENTINEL", "3: перевод прежнего запроса (другой язык) не копируется")
close(ed)

# 3б. язык сменён в другом редакторе (настройка общая): выбор этого же языка в списке обновляет устаревший кусок (Р2-П1)
Engine.targets = []
n_before = len(Engine.targets)
ed, ctx = editor(["Open the settings window"])
drag(ed.tr_layer, (40, 40), (700, 150))
wait(lambda: ed.tr_layer.tr_cards and ed.tr_layer.tr_cards[0].state == "done", 90)
settle()
card = ed.tr_layer.tr_cards[0]
ctx.config["translate_to"] = "de"     # сменили в другом окне
n_before = len(Engine.targets)
ed.tr_layer._tr_choose_lang("de")     # на кнопке уже «de»: выбор того же языка
wait(lambda: card.state == "done" and card.req_lang == "de", 60)
check(card.req_lang == "de" and len(Engine.targets) == n_before + 1 and card.blocks and card.blocks[0]["tgt"] == "de",
      f"3б: выбор уже показанного языка переводит устаревший кусок заново (запросов +{len(Engine.targets) - n_before})")
n_before = len(Engine.targets)
ed.tr_layer._tr_choose_lang("de")
settle()
check(len(Engine.targets) == n_before, "3б: и повторный выбор того же языка уже ничего не запрашивает")
# Р2-П2: кусок вернули из «Карточкой» на снимок: язык запроса сохраняется, прежний перевод не копируется
src_card = TranslateCard(QRect(40, 40, 600, 120))
src_card.state, src_card.req_lang = "done", "ru"
src_card.blocks = [{"rect": ed.tr_layer.rect().adjusted(0, 0, -900, -400), "draw": ed.tr_layer.rect().adjusted(0, 0, -900, -400), "text": "x", "orig": "o", "src": "en", "tgt": "ru",
                    "bg": QColor("#fff"), "fg": QColor("#000"), "px": 14, "engine": "M"}]
ed.tr_layer.adopt(SimpleNamespace(source=QRect(40, 40, 600, 120)), src_card)
check(ed.tr_layer.tr_cards[-1].req_lang == "ru", "Р2-П2: кусок, вернувшийся из «Карточкой», помнит язык запроса")
close(ed)

# 4. «Повторить» дважды до перерисовки: один запрос
ed, ctx = editor(["Open the settings window"])
layer = ed.tr_layer
err = TranslateCard(QRect(40, 40, 600, 120))
err.state, err.message, err.view = "error", "Сервис недоступен", "overlay"
layer.tr_cards.append(err)
layer.repaint()
settle()
n0 = len(Engine.targets)
btn = err.buttons.get("retry")
check(btn is not None, "4: кнопка «Повторить» есть")
if btn is not None:
    pt = btn.center().toPoint()
    Engine.gate, Engine.entered = threading.Event(), threading.Event()
    QTest.mouseClick(layer, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pt)
    QTest.mouseClick(layer, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pt)   # без перерисовки между нажатиями
    wait(lambda: Engine.entered.is_set(), 30)
    Engine.gate.set()
    wait(lambda: not translate._jobs, 30)
    settle()
    check(len(Engine.targets) - n0 == 1, f"4: два нажатия «Повторить» дали {len(Engine.targets) - n0} запрос")
    Engine.gate = Engine.entered = None
close(ed)


def busy():
    ed, ctx = editor(["Open the settings window"])
    Engine.gate, Engine.entered, Engine.targets = threading.Event(), threading.Event(), []
    drag(ed.tr_layer, (40, 40), (700, 150))
    wait(lambda: Engine.entered.is_set(), 60)
    return ed, ctx


def release():
    Engine.gate.set()
    wait(lambda: not translate._jobs, 30)
    settle()
    Engine.gate = Engine.entered = None


# 5. тот же язык во время запроса: нового запроса нет
ed, ctx = busy()
ed.tr_layer._tr_choose_lang("auto")
release()
check(len(Engine.targets) == 1, f"5: выбор того же языка во время запроса: запросов {len(Engine.targets)}")
close(ed)

# 6. язык сменён, потом Esc, потом ответ: нового запроса нет
ed, ctx = busy()
ed.tr_layer._tr_choose_lang("de")
ed.escape()
settle()
release()
check(len(Engine.targets) == 1 and not ed.tr_layer.isVisible(), f"6: после Esc новый запрос не ушёл (запросов {len(Engine.targets)})")
close(ed)

check(len(errors) == before, f"ни одного исключения ({len(errors) - before})")
print(f"ИТОГ: {checks[0]} проверок, " + ("все проверки пройдены" if not failures else f"провалов: {len(failures)}"))
sys.exit(1 if failures or errors else 0)
