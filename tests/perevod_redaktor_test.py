# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Перевод в редакторе по снимкам владельца 20.11.2026 (1.32.3): тёмная страница, белый заголовок в две строки,
зелёный маркер по первой строке, красные линии и стрелка поверх; режим «Перевод» редактора.

Что было: рамку обвели от середины первой строки заголовка до верха подзаголовка. Распознавание шло по чистому снимку
(пометки в него не попадали), но по обрезку: полстроки букв давали мусор («SEs SEE = чи»), первая строка под маркером
не переводилась. Перевод слова «team» («команда») подбирался по высоте рамки без проверки ширины и рисовался
обрезанным: «команд». В строке режима было написано «Рисование скрыто», а пометки видны (скрыты инструменты).

Проверяется:
1. картинка распознавания: чистый снимок в обведённой области, без маркера и красных линий;
2. рамка, разрезавшая строку, дотягивается до её конца: первая строка под маркером распознана, строки заголовка
   переводятся одним абзацем, мусора нет; рамка, задевшая полоску чужой строки, полоску не распознаёт; рамка
   по пустому месту не меняется; слово, разрезанное краем рамки, дочитывается;
3. перевод помещается в свою рамку по ширине и высоте («команда» целиком), в том числе одно длинное слово;
4. пояснение строки режима говорит правду: скрыты инструменты рисования;
5. гонки: «Готово (Esc)», рисование и закрытие редактора, пока идёт перевод, и наоборот (результат раньше действия).

Распознавание настоящее (Tesseract), сеть подменена. Запуск: QT_QPA_PLATFORM=offscreen python3 tests/perevod_redaktor_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import json
import os
import sys
import tempfile
import threading
import time

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
_cfg = os.path.join(tempfile.mkdtemp(prefix="clipsd-perred-"), "screen.json")
with open(_cfg, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1600, "height": 1000,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _cfg

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv[:1])
from clipshot import app as appmod, ocr, themes, translate, translate_ui  # noqa: E402
from clipshot.editor import EditorWindow, TRANSLATE  # noqa: E402
from clipshot.shapes import FARROW, MARKER, PENCIL, Shape  # noqa: E402

failures, checks = [], [0]
errors = []
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
        QTest.qWait(15)


def wait(cond, seconds=60):
    end = time.time() + seconds
    while not cond() and time.time() < end:
        app.processEvents()
        QTest.qWait(30)
    return cond()


# --- 3. подбор шрифта без окон: ширина тоже проверяется ------------------------------------------------------------
def width_of(text, px):
    f = QFont()
    f.setPixelSize(px)
    return QFontMetrics(f).boundingRect(QRect(0, 0, 100000, 100000), 0, text).width()


px, draw = translate_ui.fit_font("команда", QRectF(0, 0, 146, 46), 42)
check(width_of("команда", px) <= draw.width(), f"«команда» в рамке слова «team» 146 точек: целиком ({px} px, "
      f"{width_of('команда', px)} из {draw.width():.0f})")
px, draw = translate_ui.fit_font("Datenschutzgrundverordnung", QRectF(0, 0, 40, 14), 12)
check(width_of("Datenschutzgrundverordnung", px) <= draw.width(),
      f"одно длинное слово в узкой рамке: рамка растёт вправо, слово не режется ({px} px, ширина {draw.width():.0f})")
px, draw = translate_ui.fit_font("Доставка бесплатно", QRectF(0, 0, 300, 24), 18)
check(px == 18 and draw == QRectF(0, 0, 300, 24), "текст, который и так помещается: размер и рамка как раньше")

if ocr.engine_name() != "tesseract":
    print("распознавания Tesseract нет: проверки по снимку пропущены")
    print("ИТОГ: " + ("все проверки пройдены" if not failures else f"провалов: {len(failures)}"))
    sys.exit(1 if failures else 0)

# --- сцена владельца -------------------------------------------------------------------------------------------------
W, H = 1100, 520
HEAD = ["Infrastructure intelligence your", "team (and agents) can trust"]
SUB = "Build, run, and scale networks and infrastructure at the speed of AI"
RU = {"Infrastructure intelligence your team (and agents) can trust":
      "Инфраструктурный интеллект, которому может доверять ваша команда (и агенты)",
      "team (and agents) can trust": "команда (и агенты) могут доверять",
      "team": "команда",
      SUB: "Создавайте, запускайте и масштабируйте сети и инфраструктуру со скоростью ИИ"}


def page():
    img = QImage(W, H, QImage.Format.Format_RGB32)
    img.fill(QColor("#04070b"))
    p = QPainter(img)
    f = QFont("DejaVu Sans")
    f.setPixelSize(15)
    p.setFont(f)
    p.setPen(QColor("#c9ced6"))
    for i, word in enumerate(["Platform", "Solutions", "Resources", "Company", "Pricing", "Docs"]):
        p.drawText(230 + i * 105, 18, 100, 24, Qt.AlignmentFlag.AlignLeft, word)
    f.setPixelSize(54)
    p.setFont(f)
    p.setPen(QColor("#ffffff"))
    p.drawText(0, 125, W, 70, Qt.AlignmentFlag.AlignHCenter, HEAD[0])
    p.drawText(0, 190, W, 70, Qt.AlignmentFlag.AlignHCenter, HEAD[1])
    f.setPixelSize(18)
    p.setFont(f)
    p.setPen(QColor("#a7adb7"))
    p.drawText(0, 272, W, 30, Qt.AlignmentFlag.AlignHCenter, SUB)
    p.fillRect(370, 335, 130, 38, QColor("#ffffff"))
    p.fillRect(525, 335, 125, 38, QColor("#1b1f25"))
    f.setPixelSize(16)
    p.setFont(f)
    p.setPen(QColor("#000000"))
    p.drawText(370, 335, 130, 38, Qt.AlignmentFlag.AlignCenter, "Start for free")
    p.setPen(QColor("#ffffff"))
    p.drawText(525, 335, 125, 38, Qt.AlignmentFlag.AlignCenter, "Get a demo")
    p.end()
    return img


def stroke(kind, color, size, pts):
    s = Shape(kind, color, size, QPointF(*pts[0]))
    s.points = [QPointF(x, y) for x, y in pts]
    return s


def marks():
    """Как на снимке владельца: зелёный маркер по первой строке заголовка, красная кривая стрелка и линия."""
    return [stroke(MARKER, "#2db400", 5, [(95, 160), (300, 158), (520, 162), (760, 158), (900, 161)]),
            stroke(FARROW, "#d60808", 3, [(250, 40), (300, 90), (420, 112), (600, 108), (680, 90), (690, 45)]),
            stroke(PENCIL, "#d60808", 3, [(100, 420), (110, 360), (190, 330), (330, 340), (480, 380), (500, 390),
                                          (600, 330), (650, 270), (710, 240), (760, 260), (780, 330), (780, 420),
                                          (760, 500)])]


def norm(text):
    return " ".join(text.split()).replace("of Al", "of AI")   # Tesseract читает «AI» в конце строки как «Al»


class Engine:
    name = "MyMemory"
    seen = []
    gate = None        # threading.Event: перевод ждёт его (гонки), None: сразу
    entered = None     # threading.Event: перевод начался

    def translate(self, text, target, source=None):
        Engine.seen.append(norm(text))
        if Engine.entered is not None:
            Engine.entered.set()
        if Engine.gate is not None:
            Engine.gate.wait(10)
        return RU.get(norm(text), "RU: " + text), "en"


translate.engines_from_config = lambda c: [Engine()]
inputs = []
_real_start = translate.start


def spy_start(image, cfg, on_done, confirm=None, full=False):
    inputs.append(QImage(image))
    return _real_start(image, cfg, on_done, confirm=confirm, full=full)


translate.start = spy_start


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


def mk():
    ctx = Ctx()
    themes.apply_app(app, ctx.config)
    ed = EditorWindow(page(), ctx, QPoint(40, 30))
    ed.present()
    settle()
    ed.canvas.shapes.extend(marks())
    ed.canvas.update()
    ed.select_tool(TRANSLATE)
    settle()
    return ed


def done(ed):
    try:
        ed.canvas.modified, ed.exported = False, True
        ed.close()
    except RuntimeError:
        pass
    settle()


def drag(layer, a, b):
    a, b = QPoint(*a), QPoint(*b)
    QTest.mousePress(layer, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, a)
    for i in range(1, 9):
        QTest.mouseMove(layer, a + (b - a) * i / 8)
    QTest.mouseRelease(layer, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, b)


def translated(ed, a, b):
    """Обвести кусок, дождаться перевода; (карточка, тексты, ушедшие в перевод)."""
    Engine.seen = []
    del inputs[:]
    layer = ed.tr_layer
    n = len(layer.tr_cards)
    drag(layer, a, b)
    ok = wait(lambda: len(layer.tr_cards) > n and layer.tr_cards[-1].state in ("done", "error"), 90)
    settle()
    return (layer.tr_cards[-1] if ok else None), list(Engine.seen)


def red_pixels(img):
    return sum(1 for y in range(0, img.height(), 2) for x in range(0, img.width(), 2)
               if img.pixelColor(x, y).red() > 150 and img.pixelColor(x, y).green() < 70)


def green_marker_pixels(img):
    return sum(1 for y in range(0, img.height(), 2) for x in range(0, img.width(), 2)
               if (lambda c: c.green() > 60 and c.red() < 40 and c.blue() < 40)(img.pixelColor(x, y)))


KNOWN = set(RU) | {norm(HEAD[0])}

# --- 1, 2. рамка владельца: от середины первой строки до верха подзаголовка -----------------------------------------------
ed = mk()
layer = ed.tr_layer
card, seen = translated(ed, (110, 165), (870, 280))
check(card is not None and card.state == "done", "рамка владельца: перевод готов")
check(len(inputs) == 1, f"распознавание запускалось один раз ({len(inputs)})")
if inputs:
    img = inputs[0]
    clean = page().copy(layer._tr_phys(QRectF(card.region))) if card is not None else QImage()
    check(img.convertToFormat(QImage.Format.Format_RGB32) == clean.convertToFormat(QImage.Format.Format_RGB32),
          "распознавание получило чистый снимок в обведённой области (без пометок)")
    check(red_pixels(img) == 0 and green_marker_pixels(img) == 0,
          f"на картинке распознавания нет красных линий и зелёного маркера ({red_pixels(img)}, {green_marker_pixels(img)})")
check(any("Infrastructure intelligence your" in t for t in seen),
      f"первая строка под маркером распознана: {seen}")
check(norm(" ".join(HEAD)) in seen, "строки заголовка ушли в перевод одним абзацем")
check(all(t in KNOWN for t in seen), f"в перевод не ушло ни одного мусорного куска: {seen}")
if card is not None:
    head = [b for b in card.blocks if b["orig"] and "Infrastructure" in b["orig"]]
    check(bool(head) and head[0]["text"] == RU[norm(" ".join(HEAD))], "на месте заголовка его перевод целиком")
    check(card.region.top() <= 135 and card.region.right() >= 968,
          f"рамка дотянута до верха первой строки и конца слова «your»: {card.region}")
check(ed.canvas.shapes and len(ed.canvas.shapes) == 3, "пометки владельца на месте (их три)")
done(ed)

# --- 3. слово «team»: перевод «команда» помещается целиком ------------------------------------------------------------
ed = mk()
card, seen = translated(ed, (150, 195), (320, 262))
check(seen == ["team"], f"обведено слово «team»: {seen}")
if card is not None and card.blocks:
    b = card.blocks[0]
    w = width_of(b["text"], b["px"])
    check(b["text"] == "команда" and w <= b["draw"].width() + 0.5,
          f"«команда» помещается в рамку: {w} из {b['draw'].width():.0f} точек ({b['px']} px)")
done(ed)

# --- 2. разрезанное слово, полоска чужой строки, пустое место ----------------------------------------------------------
ed = mk()
layer = ed.tr_layer
card, seen = translated(ed, (150, 195), (230, 262))   # правый край режет «te|am»
check(seen == ["team"], f"край рамки разрезал слово «team»: дочитано целиком {seen}")
card, seen = translated(ed, (100, 240), (1000, 300))  # верх рамки задел низ второй строки заголовка
check(seen == [norm(SUB)], f"рамка задела полоску строки заголовка: полоска не распознаётся, мусора нет {seen}")
drag_rect = QRect(QPoint(80, 118), QPoint(1020, 265))
card, seen = translated(ed, (80, 118), (1020, 265))   # края по пустому месту
check(card is not None and card.region == drag_rect, f"рамка по пустому месту не меняется: {card.region if card else None}")
check(seen == [norm(" ".join(HEAD))], f"весь заголовок одним абзацем {seen}")
done(ed)

# --- то же при масштабе вида 50 % (точка окна = два пикселя снимка) -------------------------------------------------------
ed = mk()
ed.canvas.set_zoom(0.5)
settle()
card, seen = translated(ed, (55, 83), (435, 140))
check(norm(" ".join(HEAD)) in seen and all(t in KNOWN for t in seen),
      f"масштаб 50 %: рамка владельца дотянута, заголовок одним абзацем, мусора нет {seen}")
done(ed)

# --- 4. пояснение строки режима ---------------------------------------------------------------------------------------
ed = mk()
title = ed.tr_top.findChild(type(ed.tr_top.layout().itemAt(1).widget()), "trTitle")
check(title.toolTip().split("\n")[0] == "Инструменты рисования скрыты на время перевода",
      f"1.32.4: «Инструменты рисования скрыты на время перевода» стоит подсказкой у названия: «{title.toolTip()}»")
check(ed.tr_message.text() == ed.MODE_HINTS[TRANSLATE], "1.32.4: в строке режима вместо пояснения итог перевода (до перевода подсказка «обведите кусок»)")
old = {"Рисование скрыто", "Drawing is hidden", "Zeichnen ist beim Übersetzen aus"}
for lang in ("ru", "en", "de", "bg", "uk", "fr", "es", "it", "pt", "pl", "tr", "zh"):
    data = json.load(open(os.path.join(os.path.dirname(here), "clipshot", "i18n", lang, "editor.json"), encoding="utf-8"))
    text = data.get("editor.tr_sub", "")
    check(text and not any(o in text for o in old) and "—" not in text, f"{lang}: «{text}»")
done(ed)

# --- 5. гонки: перевод идёт, а человек жмёт «Готово (Esc)», рисует, закрывает редактор ------------------------------------


def busy_editor():
    """Редактор, в котором перевод заголовка начался и ждёт сигнала (ответ сервиса придёт, когда скажет тест)."""
    ed = mk()
    Engine.gate, Engine.entered = threading.Event(), threading.Event()
    Engine.seen = []
    drag(ed.tr_layer, (80, 118), (1020, 265))
    started = wait(lambda: Engine.entered.is_set(), 60)
    return ed, started


def finish(ed):
    """Ответ сервиса пришёл; дождаться конца потока перевода."""
    Engine.gate.set()
    ok = wait(lambda: not translate._jobs, 30)
    settle()
    Engine.gate = Engine.entered = None
    return ok


before = len(errors)
# «Готово (Esc)» раньше ответа
ed, started = busy_editor()
base_key = ed.canvas.base.cacheKey()
check(started and ed.tr_layer.tr_cards and ed.tr_layer.tr_cards[0].state == "busy", "гонка 1: перевод идёт")
QTest.mouseClick(ed.tr_done_button, Qt.MouseButton.LeftButton)
settle()
check(ed.canvas.tool != TRANSLATE and not ed.tr_layer.isVisible(), "гонка 1: «Готово (Esc)» во время перевода: режим закрыт")
check(finish(ed), "гонка 1: поток перевода завершился после ответа")
check(not ed.tr_layer.isVisible() and ed.canvas.tool != TRANSLATE and ed.panel.isVisible(),
      "гонка 1: поздний ответ не открыл режим и не показал слой поверх снимка")
check(ed.canvas.base.cacheKey() == base_key and len(ed.canvas.shapes) == 3, "гонка 1: снимок и пометки не изменились")
ed.select_tool(TRANSLATE)
settle()
check(all(c.state in ("done", "error") for c in ed.tr_layer.tr_cards), "гонка 1: при новом входе нет вечного кружка ожидания")
done(ed)
# ответ раньше «Готово (Esc)»
ed, started = busy_editor()
check(finish(ed) and ed.tr_layer.tr_cards and ed.tr_layer.tr_cards[0].state == "done", "гонка 1, обратный порядок: перевод готов")
ed.escape()
settle()
check(ed.canvas.tool != TRANSLATE and ed.panel.isVisible(), "гонка 1, обратный порядок: Esc закрыл режим")
done(ed)

# рисование во время перевода: маркер (клавиша M) и линия, потом ответ
ed, started = busy_editor()
base_key = ed.canvas.base.cacheKey()
QTest.keyClick(ed, Qt.Key.Key_M)
settle()
check(ed.canvas.tool == MARKER, f"гонка 2: клавиша M во время перевода включила маркер ({ed.canvas.tool})")
n0 = len(ed.canvas.shapes)
QTest.mousePress(ed.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(150, 300))
for x in range(160, 400, 20):
    QTest.mouseMove(ed.canvas, QPoint(x, 302))
QTest.mouseRelease(ed.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(400, 302))
settle()
check(len(ed.canvas.shapes) == n0 + 1, "гонка 2: штрих маркера нарисован, пока перевод идёт")
check(finish(ed), "гонка 2: поток перевода завершился")
check(len(ed.canvas.shapes) == n0 + 1 and ed.canvas.base.cacheKey() == base_key and ed.canvas.tool == MARKER,
      "гонка 2: ответ после рисования не тронул пометки, снимок и выбранный инструмент")
check(not ed.tr_layer.isVisible(), "гонка 2: слой перевода не всплыл поверх рисования")
done(ed)
# ответ раньше рисования
ed, started = busy_editor()
check(finish(ed), "гонка 2, обратный порядок: перевод готов")
QTest.keyClick(ed, Qt.Key.Key_M)
settle()
n0 = len(ed.canvas.shapes)
QTest.mousePress(ed.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(150, 300))
QTest.mouseMove(ed.canvas, QPoint(300, 302))
QTest.mouseRelease(ed.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(300, 302))
settle()
check(ed.canvas.tool == MARKER and len(ed.canvas.shapes) == n0 + 1, "гонка 2, обратный порядок: рисуется как обычно")
done(ed)

# закрытие редактора во время перевода
ed, started = busy_editor()
done(ed)
check(finish(None), "гонка 3: редактор закрыт во время перевода, поток завершился после ответа")
check(len(errors) == before, f"гонки: ни одного исключения в обработчиках ({len(errors) - before})")

print(f"ИТОГ: {checks[0]} проверок, " + ("все проверки пройдены" if not failures else f"провалов: {len(failures)}"))
sys.exit(1 if failures or errors else 0)
