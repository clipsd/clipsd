# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Интерфейс 1.28: два действия перевода («выделенное» и «весь экран / весь снимок»), вопрос про лимит, отмена по Esc,
всплывающие подсказки действий вместо мелкой строки. Сеть подменяется (лимит не тратится); распознавание настоящее
(нужен Tesseract).

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/ui128_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import json
import os
import sys
import tempfile
import time

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
# два монитора по 1600x700 точек рядом: проверяется, что «весь экран» берёт тот монитор, где рамка
_cfg = os.path.join(tempfile.mkdtemp(prefix="clipsd-ui128-"), "screen.json")
with open(_cfg, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "A", "x": 0, "y": 0, "width": 1600, "height": 700, "logicalDpi": 96, "logicalBaseDpi": 96},
                           {"name": "B", "x": 1600, "y": 0, "width": 1600, "height": 700, "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _cfg

from PyQt6.QtCore import QEvent, QPoint, QRect, Qt
from PyQt6.QtGui import QColor, QFont, QFontInfo, QFontMetrics, QGuiApplication, QImage, QPainter, QPixmap
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QPushButton

app = QApplication(sys.argv)
from clipshot import app as appmod, hints, ocr, themes, translate, translate_ui
from clipshot.editor import CROP, OCR, RECT, TRANSLATE, EditorWindow
from clipshot.selector import RegionSelector
failures = []
checks = [0]


def check(cond, msg):
    checks[0] += 1
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def settle(n=6):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(15)


def gone(w):
    """Окно закрыто (объект мог быть уже удалён: WA_DeleteOnClose)."""
    try:
        return not w.isVisible()
    except RuntimeError:
        return True


def wait(cond, seconds=60):
    end = time.time() + seconds
    while not cond() and time.time() < end:
        app.processEvents()
        QTest.qWait(50)
    return cond()


# Ширина окна редактора на снимке 300x160 в main (1.27.1), замеренная до правок
MAIN_WIDTH_300x160 = 981

translate.check_mymemory_email = lambda email, cb: cb("")
translate.check_google_key = lambda key, cb: cb("")
tmp = tempfile.mkdtemp(prefix="clipsd-ui128-data-")
translate.usage_path = lambda: __import__("pathlib").Path(tmp) / "usage.json"    # не трогать настоящий расход
translate.load_google_key = lambda: ""                                            # второй сервис не подключён
spent = []
translate.add_mymemory_chars = lambda n: spent.append(n)


class FakeEngine:
    name = "MyMemory"
    calls = 0   # сколько раз сервис перевода вызывали

    def translate(self, text, target, source=None):
        FakeEngine.calls += 1
        return "Перевод: " + text, "en"


translate.engines_from_config = lambda c: [FakeEngine()]
translate_ui.FloatingTranslation.request_more = lambda: None


def desktop(texts_a, texts_b, blank=False):
    """Стол из двух мониторов 1600x700: на левом одни надписи, на правом другие."""
    img = QImage(3200, 700, QImage.Format.Format_RGB32)
    img.fill(QColor("#ffffff"))
    if blank:
        return img
    p = QPainter(img)
    f = QFont()
    f.setPixelSize(20)
    p.setFont(f)
    p.setPen(QColor("#1d2330"))
    for x0, lines in ((0, texts_a), (1600, texts_b)):
        y = 90
        for line in lines:
            p.drawText(x0 + 60, y, line)
            y += 44
    p.end()
    return img


A_TEXT = ["Swiftpost parcel tracking guide", "Keep the label away from water."]
B_TEXT = ["Free delivery across Bulgaria.", "Installation guide included."]
LONG_B = ["Dear Ms. Taylor, thank you for your order number 4581.", "We confirm that your parcel is with Swiftpost now.",
          "The shipment will leave our warehouse on Monday morning.", "It should arrive in Porto within four working days.",
          "If you need the delivery earlier, please let us know.", "We can arrange express transport for a small fee.",
          "Please keep this letter until the goods are received."]
cfg = dict(appmod.DEFAULTS, translate_view="card", translate_engine="mymemory", translate_email="", tour_done=True, theme_chosen=True)
saves = []


def new_selector(img=None, kept=None):
    sel = RegionSelector(QPixmap.fromImage(img if img is not None else desktop(A_TEXT, B_TEXT)), QRect(0, 0, 3200, 700),
                         last_rect=kept)
    sel.resize(3200, 700)
    sel.tr_cfg, sel.tr_save = cfg, lambda: saves.append(1)
    sel.show()
    settle(4)
    return sel


def click_at(w, r):
    QTest.mouseClick(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, r.center())
    app.processEvents()


def button_rect(sel, key):
    return next(r for k, _t, _s, r in sel._bar_layout()[0] if k == key)


MON_A, MON_B = QRect(0, 0, 1600, 700), QRect(1600, 0, 1600, 700)
KEPT_B = QRect(1700, 100, 500, 200)   # рамка на правом мониторе
real_start = translate.start
started = []


def spy_start(image, cfg_, on_done, confirm=None, full=False):
    started.append((image.size(), confirm is not None))
    return real_start(image, cfg_, on_done, confirm=confirm, full=full)


translate.start = spy_start

# 1. Окно выделения: обе кнопки на панели, обе нажимаются
sel = new_selector(kept=KEPT_B)
keys = [k for k, *_ in sel._bar_buttons()]
check("translate" in keys and "translate_pick" in keys and "translate_all" not in keys and keys.count("translate") == 1,
      "в панели окна выделения есть «Перевести выделенное» и «Выделить и перевести», кнопки «весь экран» в верхнем ряду нет (1.31.1)")
labels = {k: t for k, t, *_ in sel._bar_buttons()}
check(labels["translate"] == "Перевести выделенное" and labels["translate_pick"] == "Выделить и перевести",
      f"подписи кнопок: {labels['translate']!r}, {labels['translate_pick']!r}")
sel.repaint()
spawned = []
sel._tr_spawn_floating = lambda r: spawned.append((QRect(r), False))
sel._tr_spawn_full = lambda r: spawned.append((QRect(r), True))
click_at(sel, button_rect(sel, "translate"))
check(spawned == [(KEPT_B, False)] and sel.translate_mode, f"«Перевести выделенное» переводит рамку: {spawned}")
sel.close()

sel = new_selector(kept=KEPT_B)
sel.repaint()
spawned = []
sel._tr_spawn_floating = lambda r: spawned.append((QRect(r), False))
sel._tr_spawn_full = lambda r: spawned.append((QRect(r), True))
click_at(sel, button_rect(sel, "translate_pick"))
check(spawned == [] and sel.translate_mode, f"«Выделить и перевести»: режим перевода, рамка не переводится: {spawned}")
sel.close()

# «Весь экран» живёт в строке управления режима перевода (trc:all)
sel = new_selector(kept=KEPT_B)
sel.repaint()
spawned = []
sel._tr_spawn_floating = lambda r: spawned.append((QRect(r), False))
sel._tr_spawn_full = lambda r: spawned.append((QRect(r), True))
sel.start_translate_pick()
sel.repaint()
rect_all = next((r for k, _t, r in sel.tr_ctl_rects if k == "trc:all"), None)
check(rect_all is not None, "в строке управления режима перевода есть «Весь экран»")
if rect_all is not None:
    click_at(sel, rect_all)
check(len(spawned) == 1 and spawned[0][1] and spawned[0][0] in (MON_A, MON_B), f"«Весь экран» из строки режима перевода: монитор под курсором, без выделения мышью: {spawned}")
check(sel.tr_start is None and not sel.tr_cards, "выделение мышью не начиналось")
sel.close()

sel = new_selector(kept=QRect(100, 100, 400, 200))   # рамка на левом мониторе
sel._tr_spawn_floating = lambda r: spawned.append((QRect(r), False))
sel._tr_spawn_full = lambda r: spawned.append((QRect(r), True))
spawned = []
sel.start_translate_all()
check(spawned == [(MON_A, True)], f"рамка на левом мониторе: переводится левый монитор: {spawned}")
sel.close()

sel = new_selector(kept=KEPT_B)
sel.show_full_screen()
sel.select_monitor(0)
spawned = []
sel._tr_spawn_floating = lambda r: spawned.append((QRect(r), False))
sel._tr_spawn_full = lambda r: spawned.append((QRect(r), True))
sel.start_translate_all()
check(spawned == [(MON_A, True)], f"режим «весь экран», выбран монитор 1: переводится он: {spawned}")
sel.close()

# «выделенное» без рамки: нынешнее поведение, кусок выбирается мышью
sel = new_selector()
spawned = []
sel._tr_spawn_floating = lambda r: spawned.append((QRect(r), False))
sel._tr_spawn_full = lambda r: spawned.append((QRect(r), True))
sel.start_translate()
check(sel.translate_mode and not spawned, "«Перевести выделенное» без рамки: включается выбор куска мышью")
sel.close()

# 2. Клавиши
sel = new_selector(kept=KEPT_B)
spawned = []
sel._tr_spawn_floating = lambda r: spawned.append((QRect(r), False))
sel._tr_spawn_full = lambda r: spawned.append((QRect(r), True))
QTest.keyClick(sel, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier)
check(spawned == [(KEPT_B, False)], f"Ctrl+L: выделенное: {spawned}")
sel.close()
sel = new_selector(kept=KEPT_B)
spawned = []
sel._tr_spawn_floating = lambda r: spawned.append((QRect(r), False))
sel._tr_spawn_full = lambda r: spawned.append((QRect(r), True))
QTest.keyClick(sel, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
check(spawned == [(MON_B, True)], f"Ctrl+Shift+L: весь экран: {spawned}")
sel.close()
sel = new_selector(kept=KEPT_B)
spawned = []
sel._tr_spawn_floating = lambda r: spawned.append((QRect(r), False))
QTest.keyClick(sel, Qt.Key.Key_P, Qt.KeyboardModifier.ControlModifier)
check(spawned == [] and sel.translate_mode, f"Ctrl+P: выделить другое место и перевести, рамка не переводится: {spawned}")
sel.close()

# перевод выключен в настройках: кнопок нет, клавиши не срабатывают
cfg["translate_enabled"] = False
sel = new_selector(kept=KEPT_B)
sel.repaint()
keys = [k for k, *_ in sel._bar_buttons()]
check("translate" not in keys and "translate_all" not in keys, "перевод выключен: обеих кнопок нет")
spawned = []
sel._tr_spawn_floating = lambda r: spawned.append((QRect(r), False))
sel._tr_spawn_full = lambda r: spawned.append((QRect(r), True))
QTest.keyClick(sel, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier)
QTest.keyClick(sel, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
check(not spawned and not sel.translate_mode, "перевод выключен: Ctrl+L и Ctrl+Shift+L не срабатывают")
sel.close()
cfg["translate_enabled"] = True

# 3. Раскладка панели на рамках 300, 600, 1200
for width in (300, 600, 1200):
    sel = new_selector(kept=QRect(1700, 100, width, 200) if width < 800 else QRect(300, 100, width, 200))
    buttons, bar, _hint = sel._bar_layout()
    rects = {k: r for k, _t, _s, r in buttons}
    inside = all(bar.contains(r) for r in rects.values())
    flat = list(rects.values()) + [sel.bar_close_rect]
    overlap = [(a, b) for i, a in enumerate(flat) for b in flat[i + 1:] if a.intersects(b)]
    copy, close = rects["copy"], sel.bar_close_rect
    last = copy.right() >= max(r.right() for r in rects.values()) and copy.bottom() >= max(r.bottom() for r in rects.values())
    if close.top() < copy.bottom() and close.bottom() > copy.top():   # один ряд значков: крестик «Закрыть» в том же ряду справа
        corner = last and close.left() - copy.right() <= 12 and bar.right() - close.right() <= 12
    else:
        corner = last and bar.right() - copy.right() <= 12
    mon = MON_B if width < 800 else MON_A
    check("translate" in rects and "translate_pick" in rects, f"рамка {width}: обе кнопки перевода на панели (размер {sel.bar_level['name']}, "
                                                              f"значки: {not sel.bar_level['text']})")
    check(inside and not overlap, f"рамка {width}: кнопки внутри панели и не пересекаются {overlap[:1]}")
    check(corner, f"рамка {width}: «Скопировать и закрыть» в правом нижнем углу панели")
    check(bar.width() <= mon.width() - 8,
          f"рамка {width}: панель помещается в монитор ({bar.width()} из {mon.width()}); ширина по содержимому, не по рамке (1.29)")
    sel.close()
# узкая рамка: одни значки, полное название и клавиша кнопки в строке подсказки
sel.close()
sel = RegionSelector(QPixmap(480, 700), QRect(1700, 0, 480, 700), last_rect=QRect(1760, 100, 200, 200))   # узкий экран (480 точек)
sel.resize(480, 700)
sel.tr_cfg, sel.tr_save = cfg, lambda: None
sel.show()
settle(4)
sel.repaint()
check(not sel.bar_level["text"], "узкая панель (экран 480 точек): верхний ряд сокращён до значков")
sel.hover_button = "translate_pick"
sel.repaint()
sel.hover_button = None
hovered = next(f"{t} ({s})" for k, t, s, _r in sel._bar_layout()[0] if k == "translate_pick")
check(hovered == "Выделить и перевести (Ctrl+P)", f"полное название и клавиша для подсказки: {hovered}")
sel.close()

# 4. Перевод всего экрана по-настоящему (распознавание Tesseract, подменённый движок)
real_words = ocr.recognize_words
slow_calls = []


def slow_words(image, langs, quality="accurate"):
    slow_calls.append(1)
    for _ in range(40):
        time.sleep(0.05)
    return real_words(image, langs, quality)


if ocr.engine_name() != "tesseract":
    print("распознавания Tesseract нет: проверки перевода с настоящим распознаванием пропущены")
    print(f"ИТОГ: проверок {checks[0]}, ", "все пройдены" if not failures else f"провалено: {len(failures)}")
    from clipshot.exitutil import quick_exit
    quick_exit(1 if failures else 0)
if True:
    popups = lambda: [w for w in QApplication.topLevelWidgets() if isinstance(w, hints.ChoicePopup) and w.isVisible()]
    waitboxes = lambda: [w for w in QApplication.topLevelWidgets() if w.objectName() == "clipsdWaitBox" and w.isVisible()]

    def fresh(before):
        return [w for w in translate_ui._floating if w not in before and not gone(w)]

    FakeEngine.calls = 0
    started.clear()
    before = list(translate_ui._floating)
    sel = new_selector(kept=KEPT_B)
    fin = []
    sel.finished.connect(lambda *a: fin.append(a))
    sel.start_translate_all()
    check(bool(fin), "«Перевести весь экран»: окно выделения закрылось, как в 1.28")
    from PyQt6.QtWidgets import QWidget
    check(QWidget.keyboardGrabber() is not sel and gone(sel),
          "окно выделения закрыто и клавиатуру не держит (иначе Esc не дошёл бы до окошка ожидания)")
    settle(3)
    # 6. Пока идёт перевод: только маленькое окошко ожидания, без окна на весь монитор
    boxes = waitboxes()
    check(len(boxes) == 1 and boxes[0].width() * boxes[0].height() < MON_B.width() * MON_B.height() / 4
          and not fresh(before), f"ожидание: одно маленькое окошко {boxes[0].size() if boxes else None} (меньше четверти монитора), окна на весь монитор нет")
    check(boxes[0].cross.isValid() and "Перевожу весь экран…" in boxes[0].text, "в окошке ожидания «Перевожу весь экран…» и крестик")
    boxes[0].repaint()
    check(wait(lambda: fresh(before), 90), "перевод готов: появилось окошко перевода")
    win = fresh(before)[0]
    check(started and started[-1][0].width() == 1600 and started[-1][0].height() == 700 and started[-1][1],
          f"в распознавание ушёл весь монитор 1600x700: {started[-1][0] if started else None}")
    card = win.tr_cards[0]
    check(card.full and card.state == "done" and not waitboxes(), "кусок помечен как «весь экран», окошко ожидания убрано")
    win.repaint()
    texts = " ".join(b["orig"] for b in card.blocks)
    check("delivery" in texts and "Swiftpost" not in texts, f"переведён текст именно правого монитора: {texts[:70]!r}")
    check(FakeEngine.calls >= 1, f"подменённый движок вызван ({FakeEngine.calls})")
    check(translate_ui.TranslateMixin.tr_full_wait == "Перевожу весь экран…", "подпись кружка ожидания «Перевожу весь экран…»")
    # окно на весь монитор тащится только за шапку-плашку
    was = win.pos()
    QTest.mousePress(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, card.region.center() + QPoint(300, 150))
    QTest.mouseMove(win, card.region.center() + QPoint(350, 200))
    QTest.mouseRelease(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, card.region.center() + QPoint(350, 200))
    check(not win._user_moved and win.pos() == was, "нажатие в произвольном месте окна на весь монитор окно не тащит")
    # 5. Повтор: уже переведено, второй перевод не запускается
    calls_before = FakeEngine.calls
    hints._toast_windows.clear()
    sel = new_selector(kept=KEPT_B)
    sel.start_translate_all()
    settle(6)
    check(not waitboxes() and FakeEngine.calls == calls_before and hints._toast_windows
          and hints._toast_windows[-1].toast.text() == "Весь экран уже переведён",
          f"повторное «Перевести весь экран»: «{hints._toast_windows[-1].toast.text() if hints._toast_windows else None}», лимит не тронут")
    win.close()

    # 4. Повторное нажатие во время работы (другое окно выделения): второй перевод не стартует
    ocr.recognize_words = slow_words
    FakeEngine.calls = 0
    started.clear()
    before = list(translate_ui._floating)
    sel = new_selector(kept=KEPT_B)
    sel.start_translate_all()
    sel2 = new_selector(kept=KEPT_B)
    hints._toast_windows.clear()
    sel2.start_translate_all()
    settle(4)
    check(len(waitboxes()) == 1 and len(started) == 1 and hints._toast_windows
          and hints._toast_windows[-1].toast.text() == "Перевод уже идёт",
          f"повтор во время работы: ожидание одно, запусков {len(started)}")
    # 7. Esc в окошке ожидания: отмена без падения и без запросов
    QTest.keyClick(waitboxes()[0], Qt.Key.Key_Escape)
    settle(4)
    check(not waitboxes() and not translate_ui._runs, "Esc: окошко ожидания закрыто")
    check(wait(lambda: not translate._jobs, 15), "поток перевода завершился без падения")
    settle(6)
    check(FakeEngine.calls == 0 and not fresh(before), f"после Esc запросов в сервис нет ({FakeEngine.calls}), окна перевода нет")
    # крестик тоже отменяет
    sel = new_selector(kept=KEPT_B)
    sel.start_translate_all()
    settle(3)
    box = waitboxes()[0]
    QTest.mouseClick(box, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, box.cross.center())
    check(not waitboxes() and not translate_ui._runs, "крестик в окошке ожидания отменяет перевод")
    wait(lambda: not translate._jobs, 15)
    ocr.recognize_words = real_words

    # 5а. Большой текст и лимит
    translate.mymemory_usage = lambda email="": (4900, 5000)   # осталось 100 знаков
    big = desktop(A_TEXT, LONG_B)
    for label, choose_partial in (("Отмена", False), ("Перевести, сколько хватит", True)):
        FakeEngine.calls = 0
        spent.clear()
        before = list(translate_ui._floating)
        sel = new_selector(big, kept=KEPT_B)
        sel.start_translate_all()
        check(wait(lambda: popups(), 60), f"текста больше остатка: всплывает сообщение с двумя кнопками ({label})")
        pop = popups()[0]
        import re
        nums = [int(x.replace(" ", "").replace(" ", "")) for x in re.findall(r"\d[\d ]*\d|\d", pop.label.text())]
        check(pop.label.text().split()[3].rstrip(",") == translate.znak_word(nums[0]) and "на сегодня осталось 100" in pop.label.text()
              and nums[0] > 100, f"в сообщении «{pop.label.text()}»")
        box = waitboxes()[0]
        check(not pop.geometry().intersects(box.geometry()), "окно вопроса не закрывает окошко ожидания")
        check({pop.yes_button.text(), pop.no_button.text()} == {"Перевести, сколько хватит", "Отмена"}, "две кнопки: «Перевести, сколько хватит» и «Отмена»")
        check(FakeEngine.calls == 0, "до ответа ничего не отправлено в сервис перевода")
        (pop.yes_button if choose_partial else pop.no_button).click()
        settle()
        if choose_partial:
            check(wait(lambda: fresh(before)), "«Перевести, сколько хватит»: окошко перевода появилось")
            win = fresh(before)[0]
            check(wait(lambda: win.tr_cards[0].state == "done"), "перевод готов")
            sent = sum(len(b["orig"]) for b in win.tr_cards[0].blocks)
            check(FakeEngine.calls >= 1 and 0 < sent <= 100, f"переведено в пределах остатка: {sent} знаков из 100, вызовов {FakeEngine.calls}")
            win.close()
        else:
            check(wait(lambda: not waitboxes() and not translate_ui._runs, 20), "«Отмена»: окошко ожидания закрылось")
            settle(10)
            check(FakeEngine.calls == 0 and not spent and not fresh(before),
                  f"«Отмена» не тратит лимит: вызовов движка {FakeEngine.calls}, списано {spent}")
    # 3. Остаток 0: вопроса нет, сразу окно про почту; ничего не отправлено
    translate.mymemory_usage = lambda email="": (5000, 5000)
    FakeEngine.calls = 0
    before = list(translate_ui._floating)
    from clipshot import service_setup
    n_open = len(service_setup._open)
    sel = new_selector(big, kept=KEPT_B)
    sel.start_translate_all()
    check(wait(lambda: fresh(before), 60) and not popups(), "остаток 0: вопроса про «сколько хватит» нет")
    win = fresh(before)[0]
    check(win.tr_cards[0].state == "error" and win.tr_cards[0].email_help() and FakeEngine.calls == 0,
          f"остаток 0: ошибка про лимит и почту, в сервис ничего не ушло ({FakeEngine.calls})")
    check(win.width() < MON_B.width() / 2, f"окно с ошибкой маленькое, не на весь монитор ({win.width()} px)")
    check(wait(lambda: len(service_setup._open) > n_open, 10), "окно про почту и лимит открылось само")
    for d in list(service_setup._open):
        d.close()
    win.close()
    # 3а. Остаток меньше самого короткого абзаца
    translate.mymemory_usage = lambda email="": (4990, 5000)   # осталось 10
    FakeEngine.calls = 0
    before = list(translate_ui._floating)
    sel = new_selector(big, kept=KEPT_B)
    sel.start_translate_all()
    check(wait(lambda: popups(), 60), "остаток 10: вопрос задан")
    popups()[0].yes_button.click()
    check(wait(lambda: fresh(before), 30), "остаток меньше любого абзаца: окошко с сообщением")
    win = fresh(before)[0]
    check(win.tr_cards[0].state == "error" and win.tr_cards[0].message == translate.EXHAUSTED_SMALL and FakeEngine.calls == 0,
          f"«сколько хватит» при остатке 10: ничего не отправлено ({FakeEngine.calls}), «{win.tr_cards[0].message}»")
    win.close()
    # текст помещается в остаток: вопроса нет
    translate.mymemory_usage = lambda email="": (0, 5000)
    FakeEngine.calls = 0
    before = list(translate_ui._floating)
    sel = new_selector(big, kept=KEPT_B)
    sel.start_translate_all()
    check(wait(lambda: fresh(before), 60) and not popups(), "хватает лимита: вопроса нет, перевод идёт сразу")
    win = fresh(before)[0]
    check(wait(lambda: win.tr_cards[0].state == "done") and FakeEngine.calls >= 1, "перевод готов")
    win.close()
    # Google подключён: второй сервис подхватит, вопроса нет
    translate.mymemory_usage = lambda email="": (4900, 5000)
    translate.load_google_key = lambda: "AIza" + "SyD-test_key_0123456789abcdefghijkl"
    FakeEngine.calls = 0
    before = list(translate_ui._floating)
    sel = new_selector(big, kept=KEPT_B)
    sel.start_translate_all()
    check(wait(lambda: fresh(before), 60) and not popups(), "второй сервис подключён: вопроса про лимит нет")
    fresh(before)[0].close()
    translate.load_google_key = lambda: ""
    translate.mymemory_usage = lambda email="": (0, 5000)

    # 4б. Русский текст при переводе на русский не отправляется и не считается
    class CountingEngine:
        name = "MyMemory"
        sent = 0
        calls = 0

        def translate(self, text, target, source=None):
            CountingEngine.sent += len(text)
            CountingEngine.calls += 1
            return "Перевод: " + text, "en"
    translate.engines_from_config = lambda c: [CountingEngine()]
    cfg["translate_to"] = "ru"
    RU = ["Уважаемый господин Тейлор, благодарим вас за заказ.", "Отгрузка уйдёт с нашего склада в понедельник утром."]
    hints._toast_windows.clear()
    before = list(translate_ui._floating)
    sel = new_selector(desktop(A_TEXT, RU), kept=KEPT_B)
    sel.start_translate_all()
    check(wait(lambda: hints._toast_windows, 60), "русский экран при переводе на русский: сообщение вместо перевода")
    check(hints._toast_windows[-1].toast.text() == "Перевод не нужен: текст уже на русском" and CountingEngine.sent == 0
          and not fresh(before), f"ничего не отправлено ({CountingEngine.sent} знаков), окна перевода нет")
    # смешанный экран: на правом мониторе русские строки и английская; расход = только английское, вопроса нет
    translate.mymemory_usage = lambda email="": (4900, 5000)   # осталось 100: английской строки меньше
    EN = "Free delivery to Porto."
    CountingEngine.sent = CountingEngine.calls = 0
    before = list(translate_ui._floating)
    sel = new_selector(desktop(A_TEXT, RU[:1] + RU[1:] + [EN]), kept=KEPT_B)
    sel.start_translate_all()
    check(wait(lambda: fresh(before), 60) and not popups(), "смешанный экран: русские строки в расход не входят, вопроса нет")
    win = fresh(before)[0]
    check(wait(lambda: win.tr_cards[0].state == "done"), "смешанный экран: перевод готов")
    origs = [b["orig"] for b in win.tr_cards[0].blocks]
    check(CountingEngine.sent == sum(len(o) for o in origs) and all(not translate.already_in_target(o, "ru") for o in origs)
          and any("delivery" in o for o in origs) and CountingEngine.sent < 100,
          f"отправлено {CountingEngine.sent} знаков = только нерусское: {origs}")
    win.close()
    translate.engines_from_config = lambda c: [FakeEngine()]
    translate.mymemory_usage = lambda email="": (0, 5000)
    cfg.pop("translate_to", None)

    # 6а. Текст не найден
    hints._toast_windows.clear()
    before = list(translate_ui._floating)
    sel = new_selector(desktop([], [], blank=True), kept=KEPT_B)
    sel.start_translate_all()
    check(wait(lambda: hints._toast_windows, 30), "пустой экран: всплывает сообщение")
    check(hints._toast_windows[-1].toast.text() == "Текст на экране не найден", f"текст сообщения: {hints._toast_windows[-1].toast.text()!r}")
    check(not fresh(before) and not waitboxes(), "окна перевода нет, ожидание убрано")

    # 9. Таймаут распознавания всего экрана
    def timeout_words(image, langs, quality="accurate"):
        raise ocr.OcrError("Распознавание заняло слишком долго. Выделите область поменьше.")
    ocr.recognize_words = timeout_words
    before = list(translate_ui._floating)
    sel = new_selector(kept=KEPT_B)
    sel.start_translate_all()
    check(wait(lambda: fresh(before), 30), "таймаут распознавания: окошко с сообщением")
    win = fresh(before)[0]
    check(win.tr_cards[0].message == translate.TOO_BIG_FULL and "Ctrl+L" in win.tr_cards[0].message,
          f"таймаут «весь экран»: «{win.tr_cards[0].message}»")
    win.close()
    ocr.recognize_words = real_words

    # 11. Ctrl+Shift+L в режиме «выделите кусок»
    sel = new_selector(kept=KEPT_B)
    sel.start_translate()
    sel.kept = None
    sel.enter_translate()
    spawned = []
    sel._tr_spawn_full = lambda r: spawned.append(QRect(r))
    QTest.keyClick(sel, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    check(sel.translate_mode and spawned == [MON_A],
          f"режим выбора куска: Ctrl+Shift+L переходит на весь экран (монитор под курсором): {spawned}")
    sel.close()



# 8. Редактор
def letter(w=900, h=440, lines=None):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor("#ffffff"))
    p = QPainter(img)
    f = p.font()
    f.setPixelSize(20)
    p.setFont(f)
    p.setPen(QColor("#1d2330"))
    y = 70
    for line in (lines if lines is not None else ["Free delivery across Bulgaria.", "Installation guide included.", "Order now and get a gift"]):
        p.drawText(60, y, line)
        y += 40
    p.end()
    return img


class Ctx:
    def __init__(self, **kw):
        self.config = dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True, translate_view="overlay")
        self.config.update(kw)
        self.icon = appmod.make_icon()
        self.saved = 0

    def copy_image(self, image):
        pass

    def notify(self, text):
        pass

    def save_config(self):
        self.saved += 1


def mk(img=None, **kw):
    ctx = Ctx(**kw)
    themes.apply_app(app, ctx.config)
    ed = EditorWindow(img if img is not None else letter(), ctx, QPoint(60, 40))
    ed.present()
    settle()
    ed.set_zoom(1.0)
    settle()
    return ed, ctx


def done(ed):
    ed.canvas.modified, ed.exported = False, True
    ed.close()
    themes.apply_app(app, {"ui_theme": "standard"})


small = QImage(300, 160, QImage.Format.Format_RGB32)
small.fill(QColor("#ffffff"))
ed, ctx = mk(small)
# 981 was measured with Noto Sans (the default sans-serif there): with a wider interface font (DejaVu Sans on the
# Ubuntu 22.04 runner) every label is wider too, so the reference width is scaled by the width of the same sample text
_f = QFont()
_f.setPixelSize(14)
_adv = QFontMetrics(_f).horizontalAdvance("Копировать текст · Перевести всё · Сохранить · Скопировать и закрыть · 100% · Вписать")
base_w = round(MAIN_WIDTH_300x160 * _adv / 604)   # 604: the sample in Noto Sans 14 px
growth = ed.width() - base_w
check(growth <= 90, f"окно редактора на снимке 300x160: {ed.width()} против {base_w} в main (981 при Noto Sans, "
                    f"шрифт {QFontInfo(_f).family()}; +{growth}, допустимо до +90)")
# 1.32: узкое окно по самому узкому виду панелей (группы свёрнуты, без больших кнопок, внизу значки), а не 981
check(ed.width() == ed.min_content_width() + ed._rim()[0] and ed.width() < 800 and ed.isVisible(),
      f"ширина измерена по настоящему показанному окну ({ed.width()}): узкое окно")
ed.resize(1500, ed.height())   # сдвоенная кнопка перевода видна в широком окне
settle()
check(ed.tr_all_button.text() == "Перевести всё" and ed.tr_button.text() == "Выделенное", "сдвоенная кнопка: «Перевести всё» и «Выделенное»")
check(ed.tr_all_button.toolTip() == "Перевести весь снимок (Shift+Y)" and ed.tr_button.toolTip() == "Перевести выделенное: выделите мышью текст (Y)",
      "всплывающие подсказки половин полные")
check(ed.tr_all_button.parentWidget() is ed.tr_button.parentWidget() and ed.tr_all_button.geometry().right() + 1 == ed.tr_button.geometry().left(),
      "обе половины в одном блоке, вплотную")
done(ed)

ed, ctx = mk()
c = ed.canvas
ed.select_tool(RECT)
layer = None
QTest.mouseClick(ed.tr_button, Qt.MouseButton.LeftButton)
layer = ed.tr_layer
check(c.tool == TRANSLATE and layer.isVisible() and ed.tr_button.text() == "Готово (Esc)" and not layer.tr_cards,
      "правая половина «выделенное»: режим выбора куска мышью, «Готово (Esc)», перевода всего нет")
QTest.mouseClick(ed.tr_button, Qt.MouseButton.LeftButton)
check(c.tool == RECT and ed.tr_button.text() == "Выделенное", "«Готово (Esc)» выходит из режима")
FakeEngine.calls = 0
started.clear()
QTest.mouseClick(ed.tr_all_button, Qt.MouseButton.LeftButton)
check(c.tool == TRANSLATE and layer.isVisible(), "левая половина «Перевести всё»: режим перевода включён сразу")
card = layer.tr_cards[0] if layer.tr_cards else None
check(card is not None and card.full and card.region == layer.rect(), f"переводится весь снимок целиком: {card.region if card else None}")
check(started and started[-1][0] == c.base.size(), f"в распознавание ушёл весь снимок {c.base.size()}: {started[-1][0] if started else None}")
check(wait(lambda: card.state == "done"), "перевод всего снимка готов")
check(any("delivery" in b["orig"] for b in card.blocks) and FakeEngine.calls >= 1, "переведён текст снимка, движок вызван")
layer.clear()
c.set_tool(RECT)
ed.select_tool(RECT)
# клавиши
FakeEngine.calls = 0
QTest.keyClick(ed, Qt.Key.Key_Y, Qt.KeyboardModifier.ShiftModifier)
check(c.tool == TRANSLATE and wait(lambda: layer.tr_cards and layer.tr_cards[0].state == "done") and layer.tr_cards[0].full,
      "Shift+Y: весь снимок переведён сразу")
layer.clear()
ed.select_tool(RECT)
QTest.keyClick(ed, Qt.Key.Key_Y)
settle()
check(c.tool == TRANSLATE and not layer.tr_cards, "Y: режим «выделенное» (ничего не переводится само)")
ed.select_tool(RECT)
# меню правой кнопки над пустым местом
menu = ed.build_context_menu(None)
items = {a.text(): a for a in menu.actions()}
check("Перевести весь снимок\tShift+Y" in items and "Перевести выделенное\tY" in items and "Копировать текст\tI" in items,
      f"в меню над пустым местом есть оба пункта: {[t for t in items if 'Перевести' in t]}")
order = [a.text() for a in menu.actions()]
check(abs(order.index("Перевести весь снимок\tShift+Y") - order.index("Копировать текст\tI")) <= 3, "пункты стоят рядом с «Копировать текст»")
items["Перевести выделенное\tY"].trigger()
check(c.tool == TRANSLATE, "пункт «Перевести выделенное» включает режим")
ed.select_tool(RECT)
layer.clear()
items["Перевести весь снимок\tShift+Y"].trigger()
check(c.tool == TRANSLATE and wait(lambda: layer.tr_cards and layer.tr_cards[0].state == "done"), "пункт «Перевести весь снимок» переводит снимок")
layer.clear()
ed.select_tool(RECT)
# перевод выключен
ed.ctx.config["translate_enabled"] = False
ed._sync_ocr()
check(not ed.tr_block.isVisible(), "перевод выключен: сдвоенная кнопка скрыта")
QTest.keyClick(ed, Qt.Key.Key_Y, Qt.KeyboardModifier.ShiftModifier)
QTest.keyClick(ed, Qt.Key.Key_Y)
check(c.tool == RECT, "перевод выключен: Y и Shift+Y не срабатывают")
check(not any("Перевести" in a.text() for a in ed.build_context_menu(None).actions()), "перевод выключен: в меню пунктов перевода нет")
done(ed)

# 9. Редактор: лимит, «Отмена», «Текст на снимке не найден», Esc
translate.mymemory_usage = lambda email="": (4900, 5000)
ed, ctx = mk(letter(lines=LONG_B))
c = ed.canvas
FakeEngine.calls = 0
spent.clear()
ed.translate_all()
check(wait(lambda: popups(), 60), "редактор: текста больше остатка: сообщение с двумя кнопками")
pop = popups()[0]
import re
ne = int(re.search(r"На снимке (\d+) ", pop.label.text()).group(1))
we = pop.label.text().split()[3].rstrip(",")
want = translate.znak_word(ne)
check(pop.label.text().startswith("На снимке") and "осталось 100" in pop.label.text() and we == want,
      f"редактор: «{pop.label.text()}» (склонение «{want}» верное для {ne})")
pop.no_button.click()
settle(8)
check(wait(lambda: not ed.tr_layer.tr_cards, 20) and FakeEngine.calls == 0 and not spent,
      f"редактор, «Отмена»: перевода нет, вызовов движка {FakeEngine.calls}, лимит не списан")
ed.exit_translate_mode()
translate.mymemory_usage = lambda email="": (0, 5000)
done(ed)

ed, ctx = mk(letter(lines=[]))
ed.translate_all()
tst = lambda: ed.findChild(ocr.Toast, "clipsdToast")
check(wait(lambda: tst() is not None and tst().isVisible(), 30), "редактор, пустой снимок: сообщение")
check(tst().text().endswith("Текст на снимке не найден"), f"текст: {tst().text()!r}")
done(ed)

ocr.recognize_words = slow_words
ed, ctx = mk()
FakeEngine.calls = 0
ed.translate_all()
settle(4)
check(ed.tr_layer.tr_cards and ed.tr_layer.tr_cards[0].state == "busy", "редактор: долгий перевод всего снимка идёт")
ed.tr_layer.repaint()
QTest.keyClick(ed, Qt.Key.Key_Escape)
settle(4)
check(not ed.tr_layer.tr_cards and ed.canvas.tool != TRANSLATE and not ed.tr_layer.isVisible(),
      "редактор: Esc отменяет ожидание и возвращает к обычному состоянию")
wait(lambda: not translate._jobs, 15)
settle(6)
check(FakeEngine.calls == 0, f"редактор: после Esc запросов в сервис нет ({FakeEngine.calls})")
ocr.recognize_words = real_words
done(ed)

# 10. Всплывающие подсказки действий
ed, ctx = mk()
c = ed.canvas
ed.select_tool(OCR)
check(wait(lambda: c.has_words()), "режим текста: слова распознаны")
settle(4)
plate = ed.findChild(hints.HintPlate, "clipsdHint")
check(plate is not None and plate.isVisible() and plate.text == "Нажмите на слово и тяните: выделится текст подряд",
      f"вход в режим текста: всплывающая подсказка «{plate.text if plate else None}»")
area = ed.toast_anchor()
check(plate.geometry().top() - area.top() <= 40 and plate.geometry().bottom() < area.top() + area.height() // 2
      and abs(plate.geometry().center().x() - area.center().x()) <= 2,
      f"плашка у верхнего края области снимка по центру: {plate.geometry()} в {area}")
check(hints.MAIN_PX >= 16 and plate._fonts()[0].pixelSize() == hints.MAIN_PX and plate._fonts()[1].pixelSize() < hints.MAIN_PX,
      f"крупный текст {plate._fonts()[0].pixelSize()} px, вторая строка {plate._fonts()[1].pixelSize()} px мельче")
check("Esc" in plate.sub and "Готово" in plate.sub, f"вторая строка про выход: «{plate.sub}»")
check(plate.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents) and plate.focusPolicy() == Qt.FocusPolicy.NoFocus,
      "плашка не перехватывает мышь и не берёт фокус")
check(wait(lambda: plate.effect.opacity() > 0.95, 3), "плашка появилась плавно (прозрачность выросла)")
under = ed.childAt(plate.geometry().center())
check(under is not None and under is not plate and (under is c or c.isAncestorOf(under) or under is ed.scroll.viewport()
                                                     or ed.scroll.viewport().isAncestorOf(under)),
      f"под плашкой снимок: нажатие сквозь неё доходит до {type(under).__name__}")
# нажатие мыши на снимке: плашка исчезает сразу, нажатие доходит до снимка
presses = []
orig_press = c.mousePressEvent
def counting_press(e):
    presses.append(1)
    orig_press(e)


c.mousePressEvent = counting_press
QTest.mouseClick(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(100, 100))
check(not plate.isVisible() and presses, "первое нажатие мыши на снимке: плашка исчезла сразу, нажатие дошло до снимка")
c.mousePressEvent = orig_press
# режим «Маркер» и клавиша
ed.set_text_mode("marker")
settle(2)
check(plate.isVisible() and plate.text == "Проведите маркером по нужному тексту", f"режим «Маркер»: «{plate.text}»")
QTest.keyClick(ed, Qt.Key.Key_Down)
check(not plate.isVisible(), "нажатие клавиши: плашка исчезла")
# 4 секунды и плавное гашение
ed.set_text_mode("range")
t0 = time.time()
check(plate.isVisible() and plate.SHOW == 4000 and plate.timer.interval() == plate.FADE_IN + 4000 and plate.timer.remainingTime() > 3500,
      f"плашка держится 4 секунды (таймер {plate.timer.remainingTime()} мс)")
check(wait(lambda: plate.anim.endValue() == 0.0 and plate.anim.state() != 0 or not plate.isVisible(), 8), "через 4 секунды плашка начинает гаснуть")
check(wait(lambda: not plate.isVisible(), 5) and 3.5 <= time.time() - t0 <= 6.5, f"и скрывается ({time.time() - t0:.1f} с после показа)")
# перевод и обрезка
ed.exit_text_mode()
ed.select_tool(TRANSLATE)
check(plate.isVisible() and plate.text == "Выделите мышью текст для перевода", f"режим перевода: «{plate.text}»")
ed.exit_translate_mode()
ed.select_tool(CROP)
check(plate.isVisible() and plate.text.startswith("Выделите область"), f"обрезка: «{plate.text}»")
ed.select_tool(RECT)
check(not plate.isVisible(), "другой инструмент: подсказка прежнего режима убрана")
# подсказка и итоговое уведомление: сверху и снизу, не накладываются
ed.select_tool(TRANSLATE)
ed.show_toast("Скопировано в буфер обмена")
settle(4)
tb = ed.toast
check(plate.isVisible() and tb.isVisible() and not plate.geometry().intersects(tb.geometry()) and plate.geometry().bottom() < tb.geometry().top(),
      f"подсказка сверху ({plate.geometry().y()}), уведомление снизу ({tb.geometry().y()}), не накладываются")
done(ed)
# низкое окно: даже если места мало, подсказка и уведомление не лежат друг на друге
ed, ctx = mk(small)
ed.select_tool(TRANSLATE)
ed.show_toast("Скопировано в буфер обмена")
settle(4)
plate = ed.findChild(hints.HintPlate, "clipsdHint")
tb = ed.toast
check(not (plate.isVisible() and tb.isVisible() and plate.geometry().intersects(tb.geometry())), "маленький снимок: плашки не накладываются")
done(ed)

# окно выделения: режим перевода (1.29): плитка подсвечена, внизу панели бирюзовая строка, всплывающей подсказки нет
sel = new_selector()
sel.enter_translate()
settle(4)
sel.repaint()
check(sel.findChild(hints.HintPlate, "clipsdHint") is None and sel.bar_hint_text.startswith("Режим перевода: обведите кусок"),
      f"окно выделения, режим перевода: строка панели «{sel.bar_hint_text}»")
QTest.mouseClick(sel, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(300, 300))
check(sel.translate_mode, "окно выделения: щелчок без протягивания режим перевода не отменяет")
sel.close()

# 11. Строка подсказки над нижней панелью: крупная и контрастная в обоих оформлениях
def lum(c):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c.red()) + 0.7152 * ch(c.green()) + 0.0722 * ch(c.blue())


def contrast(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


for theme_key in ("standard", "pro"):
    ed, ctx = mk(ui_theme=theme_key)
    ed.select_tool(OCR)
    wait(lambda: ed.canvas.has_words())
    settle(4)
    hint = ed.text_message
    hint.ensurePolished()
    px = hint.font().pixelSize()
    check(hint.isVisible() and px >= 15, f"оформление {theme_key}: строка подсказки {px} px (не меньше 15)")
    img = ed.grab().toImage()
    pos = hint.mapTo(ed, QPoint(hint.width() - 4, hint.height() // 2))   # справа: слева начинается текст
    bg = QColor(img.pixelColor(pos.x(), pos.y()))
    fg = hint.palette().windowText().color()
    ratio = contrast(fg, bg)
    check(ratio >= 4.5, f"оформление {theme_key}: контраст текста {fg.name()} к фону {bg.name()} = {ratio:.1f} (нужно 4,5 и выше)")
    done(ed)

# 1. Закрытие окон при вопросе и во время перевода: программа не падает
excs = []
old_hook = sys.excepthook
def hook(*a):
    excs.append(a)
    import traceback
    traceback.print_exception(*a)   # исключение не теряется: и в списке, и в выводе

sys.excepthook = hook
translate.TranslateJob.ASK_WAIT = 2
translate.mymemory_usage = lambda email="": (4900, 5000)
for view in ("overlay", "card"):
    FakeEngine.calls = 0
    ed, ctx = mk(letter(lines=LONG_B), translate_view=view)
    ed.translate_all()
    check(wait(lambda: popups(), 60), f"закрытие редактора ({view}): вопрос про лимит открыт")
    done(ed)
    settle(8)
    check(not popups(), f"закрытие редактора ({view}): окно вопроса закрылось вместе с ним")
    check(wait(lambda: not translate._jobs, 15), f"закрытие редактора ({view}): поток перевода завершился")
    settle(10)
    check(FakeEngine.calls == 0 and not excs, f"закрытие редактора ({view}): процесс жив, исключений нет, лимит не тронут")
# закрыть редактор во время самого перевода (без вопроса)
translate.mymemory_usage = lambda email="": (0, 5000)
ocr.recognize_words = slow_words
for view in ("overlay", "card"):
    ed, ctx = mk(letter(), translate_view=view)
    ed.translate_all()
    settle(4)
    done(ed)
    check(wait(lambda: not translate._jobs, 15), f"закрытие редактора ({view}) во время перевода: поток завершился")
    settle(10)
    check(not excs, f"закрытие редактора ({view}) во время перевода: процесс жив, исключений нет")
# окно выделения закрыто Esc, пока ждёт снимок
FakeEngine.calls = 0
n_started = len(started)
sel = new_selector(kept=KEPT_B)
sel.desktop = None   # снимок ещё «готовится»
sel.start_translate_all()
waiting = [c for c in sel.tr_cards if c.full and c.state == "wait"]
sel._finish(None)
settle(6)
check(len(waiting) == 1 and sel._done, "окно выделения без снимка: ждущая карточка «весь экран» была, окно закрыто")
check(not waitboxes() and not translate_ui._runs and not translate._jobs and len(started) == n_started and FakeEngine.calls == 0,
      f"после закрытия: окошка ожидания нет, перевода нет, потоков нет, запросов в сервис {FakeEngine.calls}, запусков {len(started) - n_started}")
ocr.recognize_words = real_words
translate.TranslateJob.ASK_WAIT = 600
translate.mymemory_usage = lambda email="": (0, 5000)
sys.excepthook = old_hook

# 4а. Окошко ожидания не «сирота»: отмена до показа
sel = new_selector(kept=KEPT_B)
n_started = len(started)
sel.start_translate_all()
runs = list(translate_ui._runs)
check(len(runs) == 1 and not waitboxes(), "сразу после нажатия окошко ожидания ещё не показано")
runs[0].cancel()
settle(8)
check(not waitboxes() and not [w for w in QApplication.allWidgets() if w.objectName() == "clipsdWaitBox" and w.isVisible()],
      "отмена до показа: окошко-сирота не появилось")
wait(lambda: not translate._jobs, 15)
FakeEngine.calls = 0

# 1. Правило «уже на русском»: образцы
sample_no = {   # уходят в сервис (не русские)
    "BG: доставка": "Безплатна доставка в цяла България при поръчка над 100 лв.",
    "BG: Количка": "Количка", "BG: Добави в количката": "Добави в количката", "BG: Вход в профила": "Вход в профила",
    "BG: със": "Със защитен достъп", "BG: път": "Един път",
    "UK": "Безкоштовна доставка по всій Україні", "SR": "Бесплатна достава широм Србије.",
    "RU короткое без ы, э, ё": "Корзина", "EN": "Free delivery across Bulgaria.", "цифры": "100 500 2026",
}
sample_yes = {  # русские, не отправляются
    "RU письмо": "Уважаемый покупатель, ваш заказ отправлен, это письмо создано автоматически.",
    "RU объём": "Объём памяти: 16 ГБ, поддержка быстрой зарядки",
    "RU съезд": "Съезд участников состоится сегодня, это важно",
    "RU с англ. названиями": "Установите приложение Samsung Galaxy Store и выберите тариф Premium для этой подписки",
}
wrong_no = [k for k, t in sample_no.items() if translate.already_in_target(t, "ru")]
wrong_yes = [k for k, t in sample_yes.items() if not translate.already_in_target(t, "ru")]
check(not wrong_no, f"болгарский, украинский, сербский и короткие подписи уходят в сервис (ошиблось: {wrong_no})")
check(not wrong_yes, f"русские абзацы пропускаются (ошиблось: {wrong_yes})")
check(not translate.already_in_target(sample_yes["RU письмо"], "en") and not translate.already_in_target(sample_yes["RU письмо"], "bg"),
      "правило только для перевода на русский")

# 1б. Сквозная проверка: редактор, два болгарских абзаца, «Перевести всё»
class CountEngine:
    name = "MyMemory"
    sent = 0

    def translate(self, text, target, source=None):
        CountEngine.sent += len(text)
        return "Перевод: " + text, "bg"
translate.engines_from_config = lambda c: [CountEngine()]
BG = ["Безплатна доставка в цяла България при поръчка над 100 лв.", "Добави в количката и влез във профила"]
ed, ctx = mk(letter(lines=BG), translate_to="ru")
hints._toast_windows.clear()
ed.translate_all()
check(wait(lambda: ed.tr_layer.tr_cards and ed.tr_layer.tr_cards[0].state in ("done", "error"), 90) and ed.tr_layer.tr_cards[0].state == "done",
      "болгарский снимок: перевод готов")
tst = lambda: ed.findChild(ocr.Toast, "clipsdToast")
check(CountEngine.sent > 0 and not (tst() is not None and tst().isVisible() and "не нужен" in tst().text()) and ed.tr_layer.tr_cards[0].skipped == 0,
      f"болгарский снимок: в сервис ушло {CountEngine.sent} знаков, сообщения «Перевод не нужен» нет, пропущено 0")
check(ed.mode_hint.text().startswith("Весь снимок переведён."), "пропущено 0: строка «Весь снимок переведён…» верна")
done(ed)

# 2. Пропущенные абзацы: честное сообщение в обоих видах
RU2 = ["Уважаемый господин Тейлор, благодарим вас за заказ.", "Отгрузка уйдёт с нашего склада в понедельник утром."]
for view in ("overlay", "card"):
    CountEngine.sent = 0
    before = list(translate_ui._floating)
    ed, ctx = mk(letter(lines=RU2 + ["Free delivery to Porto."]), translate_to="ru", translate_view=view)
    ed.translate_all()
    if view == "overlay":
        check(wait(lambda: ed.tr_layer.tr_cards and ed.tr_layer.tr_cards[0].state == "done", 90), "пропуск (поверх текста): перевод готов")
        cardx = ed.tr_layer.tr_cards[0]
        check(wait(lambda: tst() is not None and tst().isVisible(), 5) and tst().text() == "Переведено: 1 абзац. Уже на русском, оставлено как есть: 2",
              f"поверх текста: сообщение «{tst().text() if tst() else None}» без галочки")
    else:
        check(wait(lambda: fresh(before), 90) and wait(lambda: fresh(before)[0].tr_cards[0].state == "done", 30), "пропуск (карточкой): перевод готов")
        cardx = fresh(before)[0].tr_cards[0]
        w_ = fresh(before)[0]
        w_.repaint()
        check(cardx.note and cardx.note[0] == ["Уже на русском, оставлено как есть: 2"], f"карточкой: строка в карточке {cardx.note[0] if cardx.note else None}")
    check(cardx.skipped == 2 and len(cardx.blocks) == 1 and CountEngine.sent == len("Free delivery to Porto."),
          f"({view}) пропущено 2, переведён 1, отправлено {CountEngine.sent} знаков (только английская строка)")
    settle(3)
    check("Весь снимок переведён" not in ed.mode_hint.text() and "Уже на русском, оставлено как есть: 2" in ed.mode_hint.text() and ed.tr_message.text() == ed.mode_hint.text(),
          f"({view}) строка над панелью не врёт: «{ed.mode_hint.text()}»")
    done(ed)

# 2а. Весь текст уже на русском: сообщение без галочки
CountEngine.sent = 0
ed, ctx = mk(letter(lines=RU2), translate_to="ru")
ed.translate_all()
check(wait(lambda: tst() is not None and tst().isVisible(), 60), "весь текст русский: сообщение")
check(tst().text() == "Перевод не нужен: текст уже на русском" and CountEngine.sent == 0 and "✓" not in tst().text(),
      f"информационное сообщение без галочки: «{tst().text()}», отправлено {CountEngine.sent}")
done(ed)
translate.engines_from_config = lambda c: [FakeEngine()]

# 3. RuntimeError: удалённый объект тихо, настоящая доходит до excepthook
from PyQt6 import sip
caught = []
old_hook2 = sys.excepthook
sys.excepthook = lambda *a: caught.append(a)
ed, ctx = mk(letter())
ed.select_tool(TRANSLATE)
layer = ed.tr_layer
card0 = translate_ui.TranslateCard(QRect(0, 0, 50, 50))
layer.tr_cards.append(card0)


def boom(*a, **k):
    raise RuntimeError("настоящая ошибка из тела")
layer._tr_done_inner = boom
layer._tr_done(card0, [], "", None)
check(len(caught) == 1 and isinstance(caught[0][1], RuntimeError) and "настоящая ошибка" in str(caught[0][1]),
      f"настоящая RuntimeError из тела дошла до excepthook ({len(caught)})")
del layer._tr_done_inner
caught.clear()
win = translate_ui.FloatingTranslation(letter(200, 100), 1.0, QRect(100, 100, 200, 100), dict(cfg), None)
sip.delete(win)
win._tr_done(win.tr_cards[0], [], "", None)
check(not caught, "удалённое окно: _tr_done молча возвращается, в журнал ничего не попало")
done(ed)
sys.excepthook = old_hook2

# 12. Склонение «знак»: все три формы
table = {1: "знак", 2: "знака", 3: "знака", 4: "знака", 5: "знаков", 10: "знаков", 11: "знаков", 12: "знаков", 13: "знаков",
         14: "знаков", 15: "знаков", 21: "знак", 22: "знака", 25: "знаков", 101: "знак", 111: "знаков", 112: "знаков", 331: "знак", 366: "знаков"}
bad = {n: translate.znak_word(n) for n, w in table.items() if translate.znak_word(n) != w}
check(not bad, f"склонение «знак»: 1, 2-4, 5-20, 11-14, 21, 101, 111 верны {bad}")

# 13. Окно выбора оформления: не больше 900x600, превью 360 px
from clipshot import theme_chooser
class TCtx:
    config = dict(appmod.DEFAULTS)
    icon = appmod.make_icon()

    def save_config(self):
        pass
pv = theme_chooser.preview(TCtx(), "standard")
check(pv.width() == 360, f"превью оформления 360 px по ширине ({pv.width()})")
ch = theme_chooser.ThemeChooser(TCtx())
ch.show()
settle()
check(ch.width() <= 900 and ch.height() <= 600, f"окно выбора оформления {ch.width()}x{ch.height()} (не больше 900x600)")
ch.close()

# 14. Редактор: повторное «Перевести всё», строка подсказки над панелью по состоянию
ocr.recognize_words = slow_words
FakeEngine.calls = 0
started.clear()
ed, ctx = mk()
c = ed.canvas
ed.translate_all()
settle(3)
check(ed.mode_hint.text() == "Перевожу весь снимок… Esc: отменить", f"строка над панелью во время работы: «{ed.mode_hint.text()}»")
ed.translate_all()
QTest.keyClick(ed, Qt.Key.Key_Y, Qt.KeyboardModifier.ShiftModifier)
settle(3)
check(len(started) == 1, f"повторные «Перевести всё» и Shift+Y во время работы второй перевод не запускают (запусков {len(started)})")
ocr.recognize_words = real_words
check(wait(lambda: ed.tr_layer.tr_cards and ed.tr_layer.tr_cards[0].state == "done", 90), "перевод всего снимка готов")
settle(3)
check(ed.tr_message.text().startswith("Весь снимок переведён.") and "«Оригинал»" in ed.tr_message.text() and ed.tr_message.isVisibleTo(ed),
      f"бирюзовая полоса внизу после готового перевода: «{ed.mode_hint.text()}»")
calls_before = FakeEngine.calls
ed.translate_all()
settle(4)
tst = lambda: ed.findChild(ocr.Toast, "clipsdToast")
check(FakeEngine.calls == calls_before and len(started) == 1 and tst() is not None and tst().isVisible()
      and tst().text().endswith("Весь снимок уже переведён") and len(ed.tr_layer.tr_cards) == 1,
      "готовый перевод: повторный вызов не тратит лимит, один перевод на снимке, сообщение «Весь снимок уже переведён»")
ed.tr_layer.clear()
settle(2)
check(ed.mode_hint.text() == ed.MODE_HINTS[TRANSLATE], f"после очистки прежняя подсказка: «{ed.mode_hint.text()}»")
done(ed)

# 15. Редактор, вид «Карточкой»: ожидание маленьким окошком, окошко перевода с готовым результатом, повтор
FakeEngine.calls = 0
started.clear()
ed, ctx = mk(translate_view="card")
before = list(translate_ui._floating)
ed.translate_all()
settle(3)
check(len(waitboxes()) == 1 and not fresh(before), "вид «Карточкой»: ожидание маленьким окошком, окошка на весь снимок пока нет")
check(ed.mode_hint.text() == "Перевожу весь снимок… Esc: отменить", f"строка над панелью (карточкой): «{ed.mode_hint.text()}»")
ed.translate_all()
check(len(started) == 1, "повторный вызов во время работы (карточкой): запуск один")
check(wait(lambda: fresh(before), 90) and not waitboxes(), "вид «Карточкой»: окошко перевода появилось с результатом")
win = fresh(before)[0]
check(wait(lambda: win.tr_cards[0].state == "done") and win.tr_cards[0].full, "окошко перевода всего снимка готово")
settle(3)
check(ed.mode_hint.text().startswith("Весь снимок переведён."), "строка над панелью: «Весь снимок переведён…» (карточкой)")
calls_before = FakeEngine.calls
ed.translate_all()
settle(4)
check(FakeEngine.calls == calls_before and len(started) == 1, "готовый перевод (карточкой): повтор лимит не тратит")
done(ed)

# 16. Лимит и пропуск вместе: одно сообщение, строка над панелью, карточка
BGL = ["Безплатна доставка в цяла България", "Добави в количката и влез във профила", "Вход в профила и количката днес"]
MIX = [RU2[0], BGL[0], RU2[1], BGL[1], BGL[2]]
translate.mymemory_usage = lambda email="": (4940, 5000)   # осталось 60 знаков
toasts = lambda w: [t for t in w.findChildren(ocr.Toast) if t.isVisible()]
MSG_BOTH = "Переведено, сколько хватило лимита: 1 абзац. Уже на русском, оставлено как есть: 2"
HINT_BOTH = "Переведено, сколько хватило лимита: 1 абзац. Уже на русском, оставлено как есть: 2"
for label, lines, msg, hint_start in (
        ("лимит и пропуск", MIX, MSG_BOTH, HINT_BOTH),
        ("только лимит", BGL, "Переведено, сколько хватило лимита: 1 из 3 абзацев", "Переведено, сколько хватило лимита: 1 из 3 абзацев")):
    FakeEngine.calls = 0
    ed, ctx = mk(letter(lines=lines), translate_to="ru")
    ed.translate_all()
    check(wait(lambda: popups(), 60), f"{label} (поверх текста): вопрос про лимит")
    popups()[0].yes_button.click()
    check(wait(lambda: ed.tr_layer.tr_cards and ed.tr_layer.tr_cards[0].state == "done", 60), f"{label}: перевод готов")
    settle(4)
    tt = toasts(ed)
    check(len(tt) == 1 and tt[0].text() == msg, f"{label} (поверх текста): одно сообщение «{tt[0].text() if tt else None}»")
    check(ed.mode_hint.text().startswith(hint_start) and "Весь снимок переведён" not in ed.mode_hint.text(),
          f"{label}: строка над панелью «{ed.mode_hint.text()}»")
    done(ed)
    ed, ctx = mk(letter(lines=lines), translate_to="ru", translate_view="card")
    before = list(translate_ui._floating)
    ed.translate_all()
    check(wait(lambda: popups(), 60), f"{label} (карточкой): вопрос про лимит")
    popups()[0].yes_button.click()
    check(wait(lambda: fresh(before) and fresh(before)[0].tr_cards[0].state == "done", 60), f"{label} (карточкой): перевод готов")
    w_ = fresh(before)[0]
    w_.repaint()
    lines_note = w_.tr_cards[0].note[0] if w_.tr_cards[0].note else []
    want = ["Переведено, сколько хватило лимита: 1 из 3 абзацев"] + (["Уже на русском, оставлено как есть: 2"] if lines is MIX else [])
    check(lines_note == want, f"{label} (карточкой): строки в карточке {lines_note}")
    settle(3)
    check(ed.mode_hint.text().startswith(hint_start), f"{label} (карточкой): строка над панелью «{ed.mode_hint.text()}»")
    done(ed)
# окно выделения: одно сообщение, а не два друг на друге
FakeEngine.calls = 0
cfg["translate_view"] = "overlay"
cfg["translate_to"] = "ru"
hints._toast_windows.clear()
before = list(translate_ui._floating)
sel = new_selector(desktop(A_TEXT, MIX), kept=KEPT_B)
sel.start_translate_all()
check(wait(lambda: popups(), 60), "окно выделения, лимит и пропуск: вопрос про лимит")
popups()[0].yes_button.click()
check(wait(lambda: fresh(before) and fresh(before)[0].tr_cards[0].state == "done", 60), "окно выделения: перевод готов")
settle(4)
check(len(hints._toast_windows) == 1 and hints._toast_windows[0].toast.text() == MSG_BOTH,
      f"окно выделения: одно сообщение «{hints._toast_windows[0].toast.text() if hints._toast_windows else None}», окон сообщений {len(hints._toast_windows)}")
for w_ in fresh(before):
    w_.close()
cfg["translate_view"] = "card"
cfg.pop("translate_to", None)
translate.mymemory_usage = lambda email="": (0, 5000)

# 17. Выход из программы убирает значок из области уведомлений
from PyQt6.QtWidgets import QSystemTrayIcon
hidden = []


class SpyTray(QSystemTrayIcon):
    def hide(self):
        hidden.append(1)
        super().hide()


shut = appmod.Clipshot(app)
shut.tray = SpyTray(shut.icon, shut)
shut.tray.show()
shut.shutdown()
check(hidden == [1] and not shut.tray.isVisible(), f"shutdown(): значок убран из области уведомлений (вызовов hide: {len(hidden)}, виден: {shut.tray.isVisible()})")
shut.tray = None
shut.shutdown()   # без значка тоже не падает
check(shut.tray is None and hidden == [1], "shutdown() без значка и повторный вызов проходят, hide второй раз не вызывался")

# 18. Неожиданная RuntimeError: карточка не остаётся с вечным кружком
caught2 = []
old_hook3 = sys.excepthook
sys.excepthook = lambda *a: caught2.append(a)
ed, ctx = mk(letter())
ed.select_tool(TRANSLATE)
layer = ed.tr_layer
cardw = translate_ui.TranslateCard(QRect(0, 0, 60, 60))
cardw.state = "busy"
layer.tr_cards.append(cardw)
layer._tr_done_inner = boom
layer._tr_done(cardw, [], "", None)
check(cardw.state == "error" and cardw.message == "Неожиданная ошибка перевода" and len(caught2) == 1,
      f"неожиданная ошибка: карточка в состоянии ошибки «{cardw.message}», в excepthook {len(caught2)}")
del layer._tr_done_inner
done(ed)
caught2.clear()
ed, ctx = mk(letter(), translate_view="card")
ed.select_tool(TRANSLATE)
ed.tr_layer._tr_new_float = boom
ed.translate_all()
check(wait(lambda: not translate_ui._runs and not waitboxes(), 60) and len(caught2) >= 1,
      f"ошибка в окошке результата: окошко ожидания закрыто, в excepthook {len(caught2)}")
done(ed)
sys.excepthook = old_hook3

# 19. Окошко перевода всего снимка при первом показе в поле снимка, не на панелях
ed, ctx = mk(letter(), translate_view="card")
before = list(translate_ui._floating)
ed.translate_all()
check(wait(lambda: fresh(before) and fresh(before)[0].tr_cards[0].state == "done", 60), "карточка всего снимка готова")
settle(4)
w_ = fresh(before)[0]
lm, rm, tm, bm = w_.frame_extents_margins()
vis = QRect(w_.x() + lm, w_.y() + tm, w_.width() - lm - rm, w_.height() - tm - bm)
panel = QRect(ed.tr_top.mapToGlobal(QPoint(0, 0)), ed.tr_top.size())   # 1.29: в режиме перевода сверху строка «Перевод»
vp = ed.scroll.viewport()
field = QRect(vp.mapToGlobal(QPoint(0, 0)), vp.size())
side = vis.left() >= ed.frameGeometry().right() or vis.right() <= ed.frameGeometry().left()
check(side or (not vis.intersects(panel) and vis.top() >= field.top() - 1 and vis.bottom() <= field.bottom() + 1),
      f"карточка при первом показе: {vis} вне панели {panel}, в поле {field} (или сбоку от редактора)")
check(not side, "в этом окружении сбоку места нет: проверено именно положение на снимке")
done(ed)

print(f"ИТОГ: проверок {checks[0]}, ", "все пройдены" if not failures else f"провалено: {len(failures)}")
from clipshot.exitutil import quick_exit
quick_exit(1 if failures else 0)
