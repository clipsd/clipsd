# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Размер формы снимка (1.36.3): рамка формы у скруглённых углов, овала и круга. Маркеры по углам и сторонам,
Shift и круг пропорционально, пределы снимка и минимум, перенос, один шаг отмены, готовая картинка обрезана до рамки,
экран 200 %, сброс при обрезке, радиус в пределах рамки, смена вида формы, тень и рамка вокруг обрезанной формы.
Слова владельца 24.11.2026: «эту форму ещё иметь возможность по размеру сужать или увеличивать, если есть куда».

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/forma_razmer_test.py
"""
import os
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
sys.path.insert(0, here)
import tmpclean  # noqa: F401,E402
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QImage  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
from clipshot import app as appmod, forma, hidpi, i18n, ten_ramka  # noqa: E402
from clipshot.editor import CROP, ERASER, MOVE, EditorWindow  # noqa: E402

failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


class Ctx:
    def __init__(self):
        self.config = dict(appmod.DEFAULTS)
        self.icon = appmod.make_icon()

    def copy_image(self, image, config=None):
        hidpi.copy_image(image, config or self.config)

    def notify(self, text):
        pass

    def save_config(self):
        pass


def picture(w, h, color="#3366cc", ratio=1.0):
    img = QImage(round(w * ratio), round(h * ratio), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(color))
    img.setDevicePixelRatio(ratio)
    return img


def alpha(img, x, y):
    return img.pixelColor(x, y).alpha()


def near(a: QRectF, x, y, w, h, eps=0.51):
    return abs(a.x() - x) < eps and abs(a.y() - y) < eps and abs(a.width() - w) < eps and abs(a.height() - h) < eps


W, H = 600, 400
# --- 1. Рамка по маркерам: углы, стороны, Shift --------------------------------------------------
B = QRectF(100, 100, 200, 100)
r = forma.resize_box(B, "br", QPointF(350, 260), W, H)
check(near(r, 100, 100, 250, 160), f"угол br: правый нижний угол идёт за мышью, левый верхний на месте ({r})")
r = forma.resize_box(B, "tl", QPointF(50, 40), W, H)
check(near(r, 50, 40, 250, 160), f"угол tl: левый верхний за мышью ({r})")
r = forma.resize_box(B, "r", QPointF(420, 999), W, H)
check(near(r, 100, 100, 320, 100), f"сторона r: меняется только ширина, вертикаль мыши не важна ({r})")
r = forma.resize_box(B, "t", QPointF(-50, 60), W, H)
check(near(r, 100, 60, 200, 140), f"сторона t: меняется только верх ({r})")
r = forma.resize_box(B, "br", QPointF(400, 160), W, H, keep=True)
check(near(r, 100, 100, 300, 150), f"Shift, угол: пропорции 2:1 сохраняются ({r})")
r = forma.resize_box(B, "r", QPointF(400, 0), W, H, keep=True)
check(near(r, 100, 75, 300, 150), f"Shift, сторона: высота растёт от середины поровну вверх и вниз ({r})")
sq = QRectF(200, 100, 200, 200)
r = forma.resize_box(sq, "tr", QPointF(500, 60), W, H, keep=True)
check(abs(r.width() - r.height()) < 1e-6 and r.width() > 200, f"квадрат остаётся квадратом ({r})")

# --- 2. Пределы снимка и минимум ----------------------------------------------------------------
r = forma.resize_box(B, "br", QPointF(9000, 9000), W, H)
check(near(r, 100, 100, 500, 300), f"рамка не выходит за снимок справа и снизу ({r})")
r = forma.resize_box(B, "tl", QPointF(-500, -500), W, H)
check(near(r, 0, 0, 300, 200), f"рамка не выходит за снимок слева и сверху ({r})")
r = forma.resize_box(B, "br", QPointF(-500, -500), W, H)
check(near(r, 100, 100, forma.MIN_BOX, forma.MIN_BOX), f"меньше {forma.MIN_BOX:.0f} точек рамка не становится ({r})")
r = forma.resize_box(B, "br", QPointF(9000, 9000), W, H, keep=True)
check(r.right() <= W + 1e-6 and r.bottom() <= H + 1e-6 and abs(r.width() / r.height() - 2) < 1e-6,
      f"Shift у края: упирается в снимок, пропорции те же ({r})")
r = forma.resize_box(B, "b", QPointF(0, 9000), W, H, keep=True)
check(r.left() >= -1e-6 and r.right() <= W + 1e-6 and r.bottom() <= H + 1e-6, f"Shift, сторона у края: внутри снимка ({r})")
r = forma.resize_box(B, "tl", QPointF(9000, 9000), W, H, keep=True)
check(r.width() >= forma.MIN_BOX - 1e-6 and r.height() >= forma.MIN_BOX - 1e-6, f"Shift: минимум по меньшей стороне ({r})")
r = forma.resize_box(QRectF(0, 0, 10, 8), "br", QPointF(0, 0), 10, 8)
check(r.width() >= 8 - 1e-6 and r.height() >= 8 - 1e-6, f"снимок меньше минимума: рамка не больше снимка ({r})")

# --- 3. Сдвиг -----------------------------------------------------------------------------------
r = forma.move_box(B, QPointF(50, -20), W, H)
check(near(r, 150, 80, 200, 100), f"сдвиг на (50, -20) ({r})")
r = forma.move_box(B, QPointF(9000, 9000), W, H)
check(near(r, 400, 300, 200, 100), f"сдвиг упирается в край снимка, размер прежний ({r})")

# --- 4. Готовая картинка: обрезка до рамки, прозрачность за формой внутри рамки ------------------
img = picture(W, H)
for code in (forma.OVAL, forma.ROUND_M, forma.CIRCLE):
    box = QRectF(50, 40, 300, 200) if code != forma.CIRCLE else QRectF(50, 40, 200, 200)
    out = forma.apply(img, forma.Form(code, box=box))
    check((out.width(), out.height()) == (round(box.width()), round(box.height())),
          f"{code}: картинка обрезана до рамки {box.width():.0f} × {box.height():.0f} ({out.width()} × {out.height()})")
    check(alpha(out, 0, 0) == 0 and alpha(out, out.width() // 2, out.height() // 2) == 255 and forma.has_transparency(out),
          f"{code}: внутри рамки за формой прозрачно, середина на месте")
out = forma.apply(img, forma.Form(forma.OVAL))
check(out.size() == img.size(), "овал без рамки: во весь снимок, как раньше")
out = forma.apply(img, forma.Form(forma.OVAL, box=QRectF(-100, -100, 2000, 2000)))
check(out.size() == img.size(), "рамка больше снимка не выходит за снимок")
# экран 200 %
hi = forma.apply(picture(300, 200, ratio=2.0), forma.Form(forma.OVAL, box=QRectF(20, 10, 150, 100)))
check((hi.width(), hi.height(), hi.devicePixelRatio()) == (300, 200, 2.0),
      f"экран 200 %: рамка 150 × 100 точек = 300 × 200 пикселей, масштаб сохранён ({hi.width()} × {hi.height()})")
check(alpha(hi, 1, 1) == 0 and alpha(hi, 150, 100) == 255, "экран 200 %: углы прозрачны, середина на месте")
# тень, рамка и поля идут вокруг обрезанной формы
deco = ten_ramka.Deco(frame=True, margin_on=True)
shaped = forma.apply(img, forma.Form(forma.ROUND_L, box=QRectF(50, 40, 300, 200)))
dec = ten_ramka.apply(shaped, forma.Form(forma.ROUND_L, box=QRectF(50, 40, 300, 200)), deco)
pad = deco.pad()
check((dec.width(), dec.height()) == (300 + 2 * pad, 200 + 2 * pad), f"тень, рамка, поля: вокруг рамки формы ({dec.width()} × {dec.height()})")
check(alpha(dec, pad + 150, pad + 100) == 255, "оформление: снимок внутри на месте")
check(deco.frame_px() > 0 and alpha(dec, pad - 1, pad + 100) == 255 and alpha(dec, 0, 0) < 255,
      "оформление: рамка прилегает к форме слева, угол картинки за ней не залит")
o = ten_ramka.outer_form(forma.Form(forma.ROUND, radius=40, box=QRectF(1, 2, 3, 4)))
check(o.box is None and abs(o.radius - 40) < 1e-6, "форма готовой картинки: рамка во всю картинку, радиус прежний")
p1 = ten_ramka.outset_path(forma.Form(forma.OVAL, box=QRectF(50, 40, 300, 200)), W, H, 4).boundingRect()
check(near(p1, 46, 36, 308, 208), f"контур рамки в редакторе идёт по рамке формы ({p1})")

# --- 5. Радиус в пределах рамки -------------------------------------------------------------------
small = forma.Form(forma.ROUND, radius=150, box=QRectF(100, 100, 120, 80))
pth = forma.path(small, W, H)
check(pth.contains(QPointF(160, 102)) and not pth.contains(QPointF(102, 102)), "радиус не больше половины меньшей стороны рамки")
hp = forma.radius_handle(small, W, H)
check(abs(hp.x() - (100 + 40 * forma.HANDLE_K)) < 1e-6 and abs(hp.y() - (100 + 40 * forma.HANDLE_K)) < 1e-6,
      f"маркер радиуса на дуге угла рамки, а не снимка ({hp})")
check(abs(forma.radius_from_point(QPointF(400, 400), W, H, small) - 40) < 1e-6, "радиус по маркеру: предел по рамке (40)")
check(abs(forma.radius_from_point(hp, W, H, small) - 40) < 1e-6, "радиус по точке маркера считается от угла рамки")

# --- 6. Редактор: маркеры мышью, курсоры, отмена, перенос ----------------------------------------
L, NOMOD, SHIFT = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ShiftModifier
ctx = Ctx()
ed = EditorWindow(picture(W, H, "#3366cc"), ctx, QPoint(50, 50))
ed.present()
for _ in range(4):
    app.processEvents()
    QTest.qWait(20)
cv = ed.canvas
cv.set_tool(MOVE)
z = cv.zoom


def at(x, y):
    return QPoint(round(x * z), round(y * z))


def drag(a, b, mod=NOMOD, steps=5):
    QTest.mousePress(cv, L, mod, at(*a))
    for i in range(1, steps + 1):
        QTest.mouseMove(cv, at(a[0] + (b[0] - a[0]) * i / steps, a[1] + (b[1] - a[1]) * i / steps))
    QTest.mouseRelease(cv, L, mod, at(*b))
    app.processEvents()


ed.set_form(forma.OVAL)
check(cv.form.box is None and cv.form_editable(), "овал из меню: во весь снимок, рамку можно менять")
check(ctx.config["form_last"] == forma.OVAL, "овал запомнен")
check(i18n.tr("forma.size_tip") in ed.form_button.toolTip(), "подсказка кнопки формы рассказывает про размер")
QTest.mouseMove(cv, at(W - 1, H - 1))
check(cv.cursor().shape() == Qt.CursorShape.SizeFDiagCursor, "над угловым маркером курсор по диагонали")
QTest.mouseMove(cv, at(W - 1, H / 2))
check(cv.cursor().shape() == Qt.CursorShape.SizeHorCursor, "над маркером на стороне курсор по горизонтали")
QTest.mouseMove(cv, at(W / 2, 1))
check(cv.cursor().shape() == Qt.CursorShape.SizeVerCursor, "над верхним маркером курсор по вертикали")
QTest.mouseMove(cv, at(W - 1, 1))
check(cv.cursor().shape() == Qt.CursorShape.SizeBDiagCursor, "над правым верхним маркером курсор по другой диагонали")
n = len(cv.undo_stack)
drag((W, H), (500, 300))
check(cv.form.box is not None and near(cv.form.box, 0, 0, 500, 300), f"угол мышью: овал 500 × 300 ({cv.form.box})")
check(len(cv.undo_stack) == n + 1, "изменение рамки: один шаг отмены")
drag((0, 150), (100, 150))
check(near(cv.form.box, 100, 0, 400, 300), f"левый маркер мышью: овал уже слева ({cv.form.box})")
drag((500, 300), (600, 300), SHIFT)
check(abs(cv.form.box.width() / cv.form.box.height() - 4 / 3) < 0.02 and cv.form.box.bottom() <= H + 1e-6,
      f"Shift: овал тянется пропорционально ({cv.form.box})")
cv.undo()
check(near(cv.form.box, 100, 0, 400, 300), "Ctrl+Z: прежний размер рамки")
cv.undo()
check(near(cv.form.box, 0, 0, 500, 300), "Ctrl+Z ещё раз: прежний левый край")
cv.redo()
check(near(cv.form.box, 100, 0, 400, 300), "повтор: рамка снова уже")
# перенос за поле вокруг формы и внутри с «Выделение и перемещение»
n = len(cv.undo_stack)
QTest.mouseMove(cv, at(110, 10))
check(cv.cursor().shape() == Qt.CursorShape.OpenHandCursor, "над полем за овалом курсор-рука")
drag((110, 10), (160, 60))
check(near(cv.form.box, 150, 50, 400, 300), f"перенос за поле вокруг овала ({cv.form.box})")
drag((350, 200), (300, 150))
check(near(cv.form.box, 100, 0, 400, 300), f"«Выделение и перемещение»: перенос изнутри формы ({cv.form.box})")
check(len(cv.undo_stack) == n + 2 and not cv.shapes, "два переноса: два шага отмены, ничего не нарисовано")
drag((300, 150), (9000, 9000))
check(near(cv.form.box, 200, 100, 400, 300), f"перенос упирается в край снимка ({cv.form.box})")
n = len(cv.undo_stack)
QTest.mousePress(cv, L, NOMOD, at(300, 250))
QTest.mouseRelease(cv, L, NOMOD, at(300, 250))
check(len(cv.undo_stack) == n, "щелчок без сдвига не пишет шаг отмены")
# инструменты рисования внутри формы рисуют, а не двигают
from clipshot.editor import RECT as T_RECT  # noqa: E402
cv.set_tool(T_RECT)
box_before = QRectF(cv.form.box)
drag((300, 200), (380, 260))
check(cv.form.box == box_before and len(cv.shapes) == 1, "прямоугольник внутри формы рисуется, форма на месте")
cv.set_tool(ERASER)
check(not cv.form_editable() and cv._form_handle_at(QPointF(200, 100)) is None, "ластик: маркеров рамки нет")
cv.set_tool(MOVE)
# готовая картинка из редактора обрезана до рамки, пометки вместе со снимком
out = cv.render()
check((out.width(), out.height()) == (400, 300), f"готовая картинка обрезана до рамки 400 × 300 ({out.width()} × {out.height()})")
check(alpha(out, 0, 0) == 0 and alpha(out, 200, 150) == 255, "за овалом внутри рамки прозрачно")
check(out.pixelColor(140, 100).alpha() == 255, "пометка внутри формы осталась в готовой картинке")

# --- 7. Смена вида формы: рамка сохраняется, круг вписан ------------------------------------------
ed.set_form(forma.ROUND_M)
check(cv.form.code == forma.ROUND_M and near(cv.form.box, 200, 100, 400, 300), "скруглённые углы берут прежнюю рамку")
check(ed.radius_spin.maximum() == 150, f"предел радиуса: половина меньшей стороны рамки (150, {ed.radius_spin.maximum()})")
ed.radius_spin.setValue(500)
check(abs(cv.form.radius - 150) < 1e-6 and near(cv.form.box, 200, 100, 400, 300), "радиус не больше 150, рамка прежняя")
h = forma.radius_handle(cv.form, cv.lw(), cv.lh())
check(abs(h.x() - (200 + 150 * forma.HANDLE_K)) < 1e-6, "маркер радиуса на дуге угла рамки")
QTest.mouseMove(cv, at(h.x(), h.y()))
check(cv.cursor().shape() == Qt.CursorShape.SizeFDiagCursor, "маркер радиуса доступен")
ed.set_form(forma.CIRCLE)
check(cv.form.code == forma.CIRCLE and near(forma.frame(cv.form, W, H), 250, 100, 300, 300),
      f"круг: вписанный квадрат рамки по центру ({forma.frame(cv.form, W, H)})")
drag((550, 250), (450, 250))
fr = forma.frame(cv.form, W, H)
check(near(fr, 250, 150, 200, 200),
      f"круг тянется пропорционально, остаётся кругом ({fr})")
out = cv.render()
check(out.width() == out.height() == round(fr.width()), f"готовый круг по своей рамке ({out.width()} × {out.height()})")
ed.set_form(forma.RECT)
check(cv.form.is_rect and cv.form.box is None and not cv.form_editable(), "прямоугольник: рамки формы нет (есть «Обрезка»)")
ed.set_form(forma.OVAL)
check(cv.form.box is None, "новая форма после прямоугольника начинается со всего снимка")

# --- 8. Обрезка снимка сбрасывает рамку формы ---------------------------------------------------
cv.form.box = QRectF(300, 200, 200, 150)
cv.tool = CROP
check(not cv.form_editable(), "в режиме обрезки маркеров формы нет")
cv.tool = MOVE
cv.apply_crop(QRect(0, 0, 350, 250))
check(cv.form.box is None and forma.is_full(cv.form, cv.lw(), cv.lh()), "после обрезки рамка формы во весь новый снимок")
cv.undo()
check(cv.form.box is not None and near(cv.form.box, 300, 200, 200, 150), "отмена обрезки возвращает рамку формы")
cv.set_form(forma.CIRCLE, box=QRectF(400, 100, 150, 150))
cv.apply_crop(QRect(100, 0, 500, 400))
check(cv.form.box is None and cv.form.center is not None and abs(cv.form.center.x() - 375) < 0.01,
      f"круг после обрезки: рамка сброшена, центр над тем же местом ({cv.form.center})")

# --- 9. Масштаб 2: маркеры мышью на снимке экрана 200 % -----------------------------------------
ctx2 = Ctx()
ed2 = EditorWindow(picture(300, 200, "#22aa55", ratio=2.0), ctx2, QPoint(50, 50))
ed2.present()
app.processEvents()
cv2 = ed2.canvas
cv2.set_tool(MOVE)
ed2.set_form(forma.OVAL)
z = cv2.zoom


def at2(x, y):
    return QPoint(round(x * z), round(y * z))


QTest.mousePress(cv2, L, NOMOD, at2(300, 200))
for i in range(1, 6):
    QTest.mouseMove(cv2, at2(300 - 20 * i, 200 - 10 * i))
QTest.mouseRelease(cv2, L, NOMOD, at2(200, 150))
app.processEvents()
check(cv2.form.box is not None and near(cv2.form.box, 0, 0, 200, 150, 1.0), f"200 %: рамка в точках снимка ({cv2.form.box})")
out = cv2.render()
check((out.width(), out.height(), out.devicePixelRatio()) == (400, 300, 2.0),
      f"200 %: готовая картинка 400 × 300 пикселей ({out.width()} × {out.height()})")
ed2.set_form(forma.ROUND_S)
check(ed2.radius_spin.maximum() == 150, f"200 %: предел радиуса в пикселях снимка по рамке ({ed2.radius_spin.maximum()})")

# --- 10. Подсказка на 12 языках, без длинных тире --------------------------------------------------
for lang in i18n.LANGUAGES:
    i18n.set_language(lang, notify=False)
    text = i18n.tr("forma.size_tip")
    check(text and text != "forma.size_tip" and "—" not in text, f"{lang}: подсказка про размер формы")
i18n.set_language("ru", notify=False)

for e in (ed, ed2):
    e.exported = True
    e.close()
print("ИТОГ:", "ВСЁ ХОРОШО" if not failures else f"{len(failures)} ошибок")
sys.exit(1 if failures else 0)
