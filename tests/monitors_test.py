"""Режим «весь экран»: выбор монитора (кнопки и клавиши 0..9). Мониторы подменяются."""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from clipshot.selector import RegionSelector

app = QApplication([])
fails = []
def check(ok, text):
    print(("OK   " if ok else "FAIL ") + text)
    if not ok:
        fails.append(text)

class Scr:
    def __init__(self, w, h): self._s = (w, h)
    def size(self):
        from PyQt6.QtCore import QSize
        return QSize(*self._s)
    def devicePixelRatio(self): return 1.0

geo = QRect(0, 0, 6000, 1440)
sel = RegionSelector(QPixmap(6000, 1440), geo, full_screen=True)
sel.resize(6000, 1440)
mons = [(Scr(2560, 1440), QRect(0, 0, 2560, 1440)), (Scr(3440, 1440), QRect(2560, 0, 3440, 1440))]
sel._mon_list = lambda: mons
sel.bar_anchor = QRect(0, 0, 2560, 1440)
sel.kept = QRect(sel.rect())
buttons, bar, _h = sel._bar_layout()
keys = [c[0] for c in sel.chip_rects]
check(keys == ["mon:all", "mon:0", "mon:1"], f"кнопки выбора: {keys}")
check(all(bar.contains(c[2]) for c in sel.chip_rects), "кнопки выбора внутри панели")
check(not any(c[2].intersects(b[3]) for c in sel.chip_rects for b in buttons), "кнопки выбора не наезжают на основные")
check(sel._selected_mon() is None, "по умолчанию выбраны все мониторы")
sel._do("mon:1")
check(sel.kept == QRect(2560, 0, 3440, 1440), "выбран монитор 2: область = его границы")
check(sel._full_title() == "Снимок монитора 2", "заголовок называет монитор")
check(sel._button_at(sel.chip_rects[1][2].center()) == "mon:0", "клик по кнопке находится")
sel._bar_layout()
check(sel.bar_title_rect.height() > 0 and sel.chip_rects[0][2].top() >= sel.bar_title_rect.bottom() - 6, "кнопки ниже заголовка")
sel.keyPressEvent(__import__("PyQt6.QtGui", fromlist=["QKeyEvent"]).QKeyEvent(
    __import__("PyQt6.QtCore", fromlist=["QEvent"]).QEvent.Type.KeyPress, Qt.Key.Key_1, Qt.KeyboardModifier.NoModifier))
check(sel.kept == QRect(0, 0, 2560, 1440), "клавиша 1: монитор 1")
sel.keyPressEvent(__import__("PyQt6.QtGui", fromlist=["QKeyEvent"]).QKeyEvent(
    __import__("PyQt6.QtCore", fromlist=["QEvent"]).QEvent.Type.KeyPress, Qt.Key.Key_0, Qt.KeyboardModifier.NoModifier))
check(sel.kept == QRect(sel.rect()), "клавиша 0: все мониторы")
img = sel.grab()
check(not img.isNull(), "отрисовка без ошибок")
img.save(os.environ.get("MON_PNG", "/tmp/monitors_test.png"))
print("ИТОГ:", "все проверки пройдены" if not fails else f"провалено: {len(fails)}")
from clipshot.exitutil import quick_exit
quick_exit(1 if fails else 0)
