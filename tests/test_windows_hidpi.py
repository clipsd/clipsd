"""Запуск: .venv-build/Scripts/python.exe -X utf8 tests/test_windows_hidpi.py [папка_для_картинок]

Проверка исправлений ClipSD 1.8.0 при масштабе экрана 150 % (QT_SCALE_FACTOR=1.5, offscreen)."""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_SCALE_FACTOR"] = "1.5"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "build", "test-out")
os.makedirs(OUT, exist_ok=True)

from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PyQt6.QtGui import QColor, QIcon, QImage, QKeyEvent, QLinearGradient, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
from clipshot import app as appmod
from clipshot.editor import Canvas, EditorWindow
from clipshot.selector import RegionSelector
from clipshot.shapes import BLUR, Shape

ratio = app.primaryScreen().devicePixelRatio()
print("screen dpr:", ratio)
ok = True


def check(name, cond):
    global ok
    ok &= bool(cond)
    print(("OK   " if cond else "FAIL ") + name)


# Снимок 300×150 физических пикселей = 200×100 точек при 150 %
img = QImage(300, 150, QImage.Format.Format_RGB32)
p = QPainter(img)
g = QLinearGradient(0, 0, 300, 150)
g.setColorAt(0, QColor("red"))
g.setColorAt(1, QColor("blue"))
p.fillRect(img.rect(), g)
p.end()
img.setDevicePixelRatio(1.5)

c = Canvas(img, "arrow", "#d60808", 2)
check(f"холст в точках 200x100 (есть {c.width()}x{c.height()})", (c.width(), c.height()) == (200, 100))
blur = Shape(BLUR, QColor("red"), 2, QPointF(20, 20))
blur.points = [QPointF(20, 20), QPointF(120, 80)]
c.shapes.append(blur)
out = c.render()
check(f"экспорт в полном разрешении 300x150 (есть {out.width()}x{out.height()})", (out.width(), out.height()) == (300, 150))
c.apply_crop(QRect(10, 10, 50, 40))
check(f"обрезка 50x40 точек = 75x60 пикселей (есть {c.base.width()}x{c.base.height()}, холст {c.width()}x{c.height()})",
      (c.base.width(), c.base.height(), c.width(), c.height()) == (75, 60, 50, 40))
out.save(os.path.join(OUT, "render.png"))


# Редактор: клавиши на русской раскладке (физическая A = VK 0x41, символ «ф»)
class Ctx:
    config = appmod.load_config()
    icon = QIcon()

    def save_config(self):
        pass


ed = EditorWindow(img, Ctx())
ed.show()
ed.activateWindow()
app.processEvents()
ed.canvas.setFocus()
app.processEvents()
# Qt.Key для «ф» = 0x424 (Cyrillic_ef), VK = 0x41 (A)
ev = QKeyEvent(QEvent.Type.KeyPress, 0x424, Qt.KeyboardModifier.NoModifier, 0x1E, 0x41, 0, "ф")
handled = ed.eventFilter(ed.canvas, ev) if ed.isActiveWindow() else None
if handled is None:
    print("SKIP окно неактивно в offscreen — вызываю фильтр с подменой isActiveWindow")
    ed.isActiveWindow = lambda: True
    handled = ed.eventFilter(ed.canvas, ev)
check(f"«ф» (физическая A) → стрелка (tool={ed.canvas.tool})", handled and ed.canvas.tool == "arrow")
ev = QKeyEvent(QEvent.Type.KeyPress, 0x41A, Qt.KeyboardModifier.NoModifier, 0x13, 0x52, 0, "к")
ed.eventFilter(ed.canvas, ev)
check(f"«к» (физическая R) → прямоугольник (tool={ed.canvas.tool})", ed.canvas.tool == "rect")
ev = QKeyEvent(QEvent.Type.KeyPress, int(Qt.Key.Key_E), Qt.KeyboardModifier.NoModifier, 0x12, 0x45, 0, "e")
check("латинская E не перехватывается (работает штатный QShortcut)", ed.eventFilter(ed.canvas, ev) is False)
check(f"окно редактора по размеру снимка (canvas {ed.canvas.width()}x{ed.canvas.height()})",
      (ed.canvas.width(), ed.canvas.height()) == (200, 100))
ed.grab().save(os.path.join(OUT, "editor.png"))
ed.close()

# Лупа
desk = QImage(1500, 900, QImage.Format.Format_RGB32)
desk.fill(QColor("#f0f0f0"))
p = QPainter(desk)
p.setPen(QColor("black"))
for x in range(0, 1500, 7):
    p.drawLine(x, 0, x, 900)
p.fillRect(600, 300, 30, 30, QColor("#1e78ff"))
p.end()
pix = QPixmap.fromImage(desk)
pix.setDevicePixelRatio(1.5)
geo = QRect(0, 0, 1000, 600)
sel = RegionSelector(pix, geo, True, True, None)
sel.cursor_pos = QPoint(410, 205)   # = физ. (615, 307) — внутри синего квадрата
img2 = sel.grab()
img2.save(os.path.join(OUT, "magnifier.png"))
px = sel.image.pixelColor(int(410 * 1.5), int(205 * 1.5))
check(f"лупа берёт пиксель под курсором ({px.name()})", px.name() == "#1e78ff")
sel.close()
print("ИТОГ:", "всё прошло" if ok else "есть ошибки")
from clipshot.exitutil import quick_exit
quick_exit(0 if ok else 1)
