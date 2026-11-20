# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Редактор 1.32.1: сочетания клавиш без двойных привязок и «Копировать текст» при любой ширине окна.

1. Повтор работает по Ctrl+Y и по Ctrl+Shift+Z. В 1.32.0 повтор был привязан как ["Ctrl+Y", StandardKey.Redo]:
   в Windows StandardKey.Redo тоже Ctrl+Y, два QShortcut на одном сочетании Qt считает неоднозначными и не выполняет
   ни один (Ctrl+Y не работал), а Ctrl+Shift+Z не был привязан вовсе. Платформа offscreen отдаёт привязки Windows
   (схема клавиатуры по умолчанию), поэтому тест проверяет именно этот случай. Ни одно сочетание редактора не
   привязано дважды, нажатые сочетания не срабатывают неоднозначно; запасной путь для русской раскладки
   (_key_slots) знает оба сочетания повтора.
2. «Копировать текст» (распознавание текста) доступна при любой ширине окна: большая фиолетовая кнопка во втором
   ряду, а в узком окне (снимок уже примерно 1100 px) кнопка группы «Текст с картинки» в верхнем ряду, пункт
   «Копировать текст» в «⋯ Все инструменты» и клавиша I.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/editor1321_test.py
"""
import json
import os
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
os.environ.setdefault("CLIPSD_LANG", "ru")
_cfg = os.path.join(tempfile.mkdtemp(prefix="clipsd-ed1321-"), "screen.json")
with open(_cfg, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1920, "height": 1080,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _cfg

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QColor, QImage, QKeySequence, QShortcut
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
from clipshot import app as appmod  # noqa: E402
from clipshot import editor as em  # noqa: E402
from clipshot.editor import OCR, EditorWindow, tool_title  # noqa: E402

failures = []
checks = [0]
CTRL, SHIFT = Qt.KeyboardModifier.ControlModifier, Qt.KeyboardModifier.ShiftModifier
PORTABLE = QKeySequence.SequenceFormat.PortableText


def check(cond, msg):
    checks[0] += 1
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def settle(n=5):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(10)


class Ctx:
    def __init__(self, **kw):
        self.config = dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True, **kw)
        self.icon = appmod.make_icon()

    def save_config(self):
        pass

    def notify(self, text):
        pass


def make(width, height=300):
    img = QImage(width, height, QImage.Format.Format_RGB32)
    img.fill(QColor("#ffffff"))
    ed = EditorWindow(img, Ctx(), QPoint(0, 0))
    ed.present()
    settle()
    return ed


# ---------------------------------------------------------------- 1. сочетания клавиш

calls = []
_undo, _redo = em.Canvas.undo, em.Canvas.redo
em.Canvas.undo = lambda self: (calls.append("undo"), _undo(self))[1]
em.Canvas.redo = lambda self: (calls.append("redo"), _redo(self))[1]


def test_shortcuts():
    redo_std = [s.toString(PORTABLE) for s in QKeySequence.keyBindings(QKeySequence.StandardKey.Redo)]
    print(f"     StandardKey.Redo на этой платформе: {redo_std}")
    check(redo_std[:1] == ["Ctrl+Y"], "offscreen отдаёт привязки Windows: StandardKey.Redo начинается с Ctrl+Y")

    ed = make(900)
    shortcuts = ed.findChildren(QShortcut)
    keys = [s.key().toString(PORTABLE) for s in shortcuts]
    dups = sorted({k for k in keys if keys.count(k) > 1})
    check(not dups, f"ни одно сочетание редактора не привязано дважды {dups or ''}")
    check("Ctrl+Y" in keys and "Ctrl+Shift+Z" in keys and "Ctrl+Z" in keys, "повтор: Ctrl+Y и Ctrl+Shift+Z, отмена: Ctrl+Z")
    ambiguous = []
    for s in shortcuts:
        s.activatedAmbiguously.connect(lambda k=s.key().toString(PORTABLE): ambiguous.append(k))

    ed.raise_()
    ed.activateWindow()
    settle()
    check(QApplication.activeWindow() is ed, "окно редактора активно")
    c = ed.canvas
    for press, mods, want in ((Qt.Key.Key_Y, CTRL, "redo"), (Qt.Key.Key_Z, CTRL | SHIFT, "redo"),
                              (Qt.Key.Key_Z, CTRL, "undo")):
        calls.clear()
        QTest.keyClick(c, press, mods)
        settle(2)
        name = QKeySequence(mods.value | press.value).toString(PORTABLE)
        check(calls == [want], f"{name}: {want} ({calls})")
    check(not ambiguous, f"ни одно нажатое сочетание не сработало неоднозначно {ambiguous or ''}")

    # действие по-настоящему: нарисовать, отменить, повторить по Ctrl+Y и по Ctrl+Shift+Z
    c.undo_stack.append((c.base, [s.copy() for s in c.shapes]))
    c.redo_stack.clear()
    QTest.keyClick(c, Qt.Key.Key_Z, CTRL)
    check(len(c.redo_stack) == 1, "Ctrl+Z: шаг ушёл в повтор")
    QTest.keyClick(c, Qt.Key.Key_Y, CTRL)
    check(not c.redo_stack and len(c.undo_stack) == 1, "Ctrl+Y: шаг повторён")
    QTest.keyClick(c, Qt.Key.Key_Z, CTRL)
    QTest.keyClick(c, Qt.Key.Key_Z, CTRL | SHIFT)
    check(not c.redo_stack and len(c.undo_stack) == 1, "Ctrl+Shift+Z: шаг повторён")

    # русская раскладка (Windows): запасной путь по физической клавише знает оба сочетания повтора
    for seq in ("Ctrl+Y", "Ctrl+Shift+Z"):
        combined = QKeySequence(seq)[0].toCombined()
        slot = ed._key_slots.get(combined)
        calls.clear()
        if slot is not None:
            slot()
        check(calls == ["redo"], f"русская раскладка: {seq} = повтор")
    ed.close()
    settle()


# ---------------------------------------------------------------- 2. «Копировать текст» при любой ширине

def test_copy_text_everywhere():
    title = tool_title(OCR)
    check(title == "Копировать текст", f"название инструмента: {title!r}")
    hidden = []
    for width in (300, 500, 700, 900, 1000, 1100, 1300, 1600):
        ed = make(width)
        big = ed.ocr_button.isVisible()
        if not big:
            hidden.append(width)
        group = ed.tool_strip.visible_widget(OCR)
        in_row = group is not None and group.isVisible()
        ed.build_all_tools_menu()
        row = ed.all_tools_rows.get(OCR)
        in_all = row is not None and ed.more_button.isVisible()
        hotkey = ed._key_slots.get(QKeySequence("I")[0].toCombined()) is not None
        check(big or (in_row and in_all), f"снимок {width} px (окно {ed.width()}): "
              + ("большая кнопка" if big else "кнопка группы «Текст с картинки» и «Все инструменты»"))
        check(in_all and hotkey, f"снимок {width} px: «Копировать текст» в «Все инструменты» и на клавише I")
        ed._all_tools_menu.deleteLater()
        ed.close()
        settle(2)
    print(f"     большая кнопка скрыта у снимков шириной: {hidden}")


for fn in (test_shortcuts, test_copy_text_everywhere):
    try:
        fn()
    except Exception as exc:     # noqa: BLE001
        import traceback
        traceback.print_exc()
        check(False, f"{fn.__name__}: исключение {exc!r}")

print(f"ИТОГ: проверок {checks[0]}, провалено: {len(failures)}")
sys.exit(1 if failures else 0)
