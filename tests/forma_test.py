# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Форма снимка (1.34): скруглённые углы, овал, круг; прозрачность в PNG и WebP, фон в JPG, буфер обмена,
пометки обрезаются по форме, круг по меньшей стороне и сдвигается мышью, отмена, 12 языков.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/forma_test.py
"""
import json
import os
import shutil
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
sys.path.insert(0, here)
import tmpclean  # noqa: F401,E402  (временные папки этого теста убираются при его выходе)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QColor, QGuiApplication, QImage
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
from clipshot import app as appmod, forma, hidpi, i18n
from clipshot.editor import RECT, EditorWindow
from clipshot.shapes import Shape

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


tmp = tempfile.mkdtemp(prefix="forma-", dir=os.environ.get("TMPDIR"))

# --- 1. Контур и круг по меньшей стороне ---------------------------------------------------------
r = forma.circle_rect(forma.Form(forma.CIRCLE), 600, 400)
check((r.width(), r.height(), r.x(), r.y()) == (400, 400, 100, 0), f"круг: сторона = меньшая сторона, по центру ({r})")
r = forma.circle_rect(forma.Form(forma.CIRCLE, QPointF(10, 200)), 600, 400)
check(r.x() == 0, "круг не выходит за левый край снимка")
r = forma.circle_rect(forma.Form(forma.CIRCLE, QPointF(590, 200)), 600, 400)
check(r.right() == 600, "круг не выходит за правый край снимка")
out = forma.apply(picture(600, 400), forma.Form(forma.CIRCLE))
check((out.width(), out.height()) == (400, 400), f"готовый круг обрезан до квадрата 400 × 400 ({out.width()} × {out.height()})")
check(alpha(out, 0, 0) == 0 and alpha(out, 200, 200) == 255, "круг: углы прозрачные, середина непрозрачная")
check(alpha(out, 200, 2) == 255 and alpha(out, 2, 200) == 255, "круг касается краёв квадрата (диаметр 400)")
hi = forma.apply(picture(300, 200, ratio=2.0), forma.Form(forma.CIRCLE))
check((hi.width(), hi.height(), hi.devicePixelRatio()) == (400, 400, 2.0), "экран 200 %: круг в физических пикселях, масштаб сохранён")
rect_img = picture(300, 200)
check(forma.apply(rect_img, forma.Form(forma.RECT)) is rect_img, "прямоугольник: картинка не меняется")
check(not forma.has_transparency(rect_img), "обычный снимок непрозрачен")
for code in (forma.ROUND_S, forma.ROUND_M, forma.ROUND_L, forma.OVAL):
    o = forma.apply(picture(300, 200), forma.Form(code))
    check(o.size() == rect_img.size() and alpha(o, 0, 0) == 0 and alpha(o, 150, 100) == 255
          and forma.has_transparency(o), f"{code}: размер прежний, угол прозрачный, середина на месте")
small, big = (forma.apply(picture(300, 200), forma.Form(c)) for c in (forma.ROUND_S, forma.ROUND_L))
check(alpha(small, 20, 4) == 255 and alpha(big, 20, 4) == 0, "большие скругления срезают угол сильнее малых")
tiny = forma.apply(picture(40, 30), forma.Form(forma.ROUND_L))
check(alpha(tiny, 20, 15) == 255, "радиус не больше половины меньшей стороны (маленький снимок не пропадает)")

# --- 2. Файлы: PNG и WebP с прозрачностью, JPG с фоном -------------------------------------------
shaped = forma.apply(picture(300, 200), forma.Form(forma.OVAL))
png_path = os.path.join(tmp, "a.png")
check(hidpi.save_image(shaped, png_path, {}), "PNG сохранён")
back = QImage(png_path)
check(back.hasAlphaChannel() and alpha(back, 0, 0) == 0 and alpha(back, 150, 100) == 255,
      "PNG: за формой прозрачно (альфа 0), внутри непрозрачно")
webp_path = os.path.join(tmp, "a.webp")
check(hidpi.save_image(shaped, webp_path, {}), "WebP сохранён")
back = QImage(webp_path)
check(not back.isNull() and alpha(back, 0, 0) == 0 and alpha(back, 150, 100) == 255, "WebP: за формой прозрачно")
jpg_path = os.path.join(tmp, "a.jpg")
check(hidpi.save_image(shaped, jpg_path, {}), "JPG сохранён")
back = QImage(jpg_path)
c = back.pixelColor(1, 1)
check(min(c.red(), c.green(), c.blue()) >= 245, f"JPG: за формой белый фон, не чёрный ({c.name()})")
m = back.pixelColor(150, 100)
check(abs(m.blue() - 0xcc) < 12 and abs(m.red() - 0x33) < 12, f"JPG: внутри формы снимок ({m.name()})")
jpg2 = os.path.join(tmp, "b.jpg")
hidpi.save_image(shaped, jpg2, {"shape_background": "#202020"})
c = QImage(jpg2).pixelColor(1, 1)
check(max(c.red(), c.green(), c.blue()) < 50, f"JPG: цвет фона из настройки shape_background ({c.name()})")
plain_jpg = os.path.join(tmp, "c.jpg")
hidpi.save_image(picture(300, 200, "#ff0000"), plain_jpg, {})
c = QImage(plain_jpg).pixelColor(1, 1)
check(c.red() > 240 and c.green() < 20, "JPG без формы: как раньше, угол не залит")

# --- 3. Буфер обмена: PNG с прозрачностью + запасная картинка на белом ---------------------------
mime = hidpi.clipboard_mime(shaped, {"clip_html": False})
png = bytes(mime.data("image/png"))
check(png.startswith(b"\x89PNG"), "Linux: в буфере image/png")
img = QImage.fromData(png)
check(alpha(img, 0, 0) == 0 and alpha(img, 150, 100) == 255, "PNG в буфере с прозрачностью за формой")
flat = QImage(mime.imageData())
check(not flat.hasAlphaChannel() and flat.pixelColor(1, 1).name() == "#ffffff",
      "запасная картинка (BMP, JPEG, в Windows CF_DIB) на белом фоне, без альфа-канала")
check(not mime.hasFormat(hidpi.WINDOWS_PNG), "Linux: формата Windows «PNG» нет")
plain = hidpi.clipboard_mime(picture(300, 200), {"clip_html": False})
check(QImage(plain.imageData()).hasAlphaChannel() and plain.hasFormat("image/png"),
      "обычный снимок в буфер как раньше (та же картинка и image/png)")
real_platform = sys.platform
try:
    sys.platform = "win32"
    win = hidpi.clipboard_mime(shaped, {"clip_html": False})
    win_plain = hidpi.clipboard_mime(picture(300, 200), {"clip_html": False})
finally:
    sys.platform = real_platform
check(win.hasFormat(hidpi.WINDOWS_PNG) and not win.hasFormat("image/png"),
      "Windows: прозрачный PNG под именем формата «PNG», как кладут браузеры")
wimg = QImage.fromData(bytes(win.data(hidpi.WINDOWS_PNG)))
check(alpha(wimg, 0, 0) == 0 and alpha(wimg, 150, 100) == 255, "Windows: PNG с прозрачностью")
wflat = QImage(win.imageData())
check(not wflat.hasAlphaChannel() and wflat.pixelColor(1, 1).name() == "#ffffff",
      "Windows: CF_DIB из картинки без альфы на белом фоне (углы не чёрные)")
check(not win_plain.hasFormat(hidpi.WINDOWS_PNG) and not win_plain.hasFormat("image/png"),
      "Windows: обычный снимок кладётся как раньше (только картинка)")
scaled = forma.apply(picture(300, 200, ratio=1.5), forma.Form(forma.ROUND_M))
html_mime = hidpi.clipboard_mime(scaled, {"clip_html": True})
check(html_mime.hasHtml() and 'width="300"' in html_mime.html(), "экран 150 %: HTML с размером в точках остаётся")

# --- 4. Редактор: кнопка, меню, пометки обрезаются, отмена ---------------------------------------
ctx = Ctx()
ed = EditorWindow(picture(560, 340, "#3366cc"), ctx, QPoint(50, 50))
ed.present()
for _ in range(4):
    app.processEvents()
    QTest.qWait(20)
cv = ed.canvas
check(cv.form.is_rect and not ed.form_button.isChecked(), "новый снимок прямоугольный")
check(ed.form_button.accessibleName() == i18n.tr("forma.title"), "у кнопки есть имя для экранного диктора")
check(ed.form_button.width() <= 48 and ed.form_button.height() == 36, "кнопка размером с кнопку группы (48 × 36)")
menu = ed.build_form_menu()
acts = [a for a in menu.actions() if a.isCheckable()]
check([a.data() for a in acts] == list(forma.FORMS), "в меню шесть форм по порядку")
check(sum(a.isChecked() for a in acts) == 1 and acts[0].isChecked(), "в меню отмечен прямоугольник")
check(all(not a.icon().isNull() for a in acts), "у каждой формы свой значок")
from PyQt6.QtWidgets import QLabel as _QL
check(not menu.findChildren(_QL, "formNote"), "PNG: строки про JPG в меню нет")
# Пометка в левом верхнем углу: после формы срезается вместе со снимком
mark = Shape(RECT, QColor("#ff0000"), 3, QPointF(2, 2), True)
mark.points[-1] = QPointF(60, 60)
cv.shapes.append(mark)
before = cv.render()
check(before.pixelColor(4, 4).name() == "#ff0000", "без формы пометка видна в углу")
ed.toggle_form()
check(cv.form.code == forma.ROUND_M and ed.form_button.isChecked(), "щелчок по кнопке: средние скругления (по умолчанию)")
out = cv.render()
check(alpha(out, 1, 1) == 0, "пометка в углу срезана по форме вместе со снимком")
check(out.pixelColor(40, 40).name() == "#ff0000", "пометка внутри формы осталась")
check(ed.ctx.config["form_last"] == forma.ROUND_M, "последняя форма запомнилась")
ed.set_form(forma.OVAL)
check(cv.form.code == forma.OVAL and ed.ctx.config["form_last"] == forma.OVAL, "меню: овал, запомнен как последний")
ed.toggle_form()
check(cv.form.is_rect, "щелчок по включённой форме возвращает прямоугольник")
ed.toggle_form()
check(cv.form.code == forma.OVAL, "щелчок снова включает последнюю форму (овал)")
cv.undo()
check(cv.form.is_rect, "отмена возвращает прошлую форму")
cv.redo()
check(cv.form.code == forma.OVAL and ed.form_button.isChecked(), "повтор возвращает овал, кнопка включена")
check(cv.modified and not ed.exported, "смена формы считается правкой (вопрос при закрытии, автосохранение)")
# Шахматка за формой на холсте
shot = cv.grab().toImage()
c0 = shot.pixelColor(1, 1).name()
check(c0 in forma.CHECKER_COLORS[False], f"за формой шахматка светлой темы ({c0})")
check(shot.pixelColor(280, 170).name() == "#3366cc", "внутри формы снимок")

# JPG: строка-подсказка
ctx.config["save_format"] = "jpg"
ed._sync_form()
check(i18n.tr("forma.jpg_note") in ed.info.text(), "JPG и форма: строка про белый фон внизу окна")
check(i18n.tr("forma.jpg_note") in ed.form_button.toolTip(), "JPG и форма: та же строка в подсказке кнопки")
menu = ed.build_form_menu()
from PyQt6.QtWidgets import QLabel
notes = [lb.text() for lb in menu.findChildren(QLabel, "formNote")]
check(notes == [i18n.tr("forma.jpg_note")], f"JPG: строка в меню формы ({notes})")
ctx.config["shape_background"] = "#202020"
check("#202020" in ed.form_note(), "JPG: цвет фона из настроек назван в строке")
ctx.config["shape_background"] = "#ffffff"
ed.set_form(forma.RECT)
check(i18n.tr("forma.jpg_note") not in ed.info.text(), "прямоугольник: строки про JPG нет")
ctx.config["save_format"] = "png"

# Узкое окно: кнопка уходит из ряда вместе с подписью «Все инструменты», формы остаются в этом меню
ed._measure_rows()
ed._adapt_rows(ed.min_content_width())
check(not ed.form_button.isVisibleTo(ed), "узкое окно: кнопки формы в ряду нет")
check(ed.min_content_width() <= ed._need_row1[-1] and ed._need_row1[-1] < ed._need_row1[0],
      "узкое окно не шире, чем без кнопки формы")
ed._adapt_rows(2000)
check(ed.form_button.isVisibleTo(ed), "широкое окно: кнопка формы снова в ряду")
allm = ed.build_all_tools_menu()
subs = [a.menu() for a in allm.actions() if a.menu() is not None]
check(len(subs) == 1 and subs[0].title() == i18n.tr("forma.title")
      and [a.data() for a in subs[0].actions() if a.isCheckable()] == list(forma.FORMS),
      "«Все инструменты»: подменю «Форма снимка» со всеми формами")

# --- 4а. Свой радиус: ползунок, поле, маркер у угла, предел, отмена ------------------------------
L, NOMOD = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
ed.set_form(forma.ROUND_M)
check(ed.radius_box.isVisibleTo(ed), "скруглённые углы: во втором ряду «Радиус» с ползунком и полем")
check(ed.radius_slider.value() == 28 and ed.radius_spin.value() == 28, "ползунок и поле стоят на 28 (средние)")
check(ed.radius_spin.maximum() == 170 and ed.radius_slider.maximum() == 170, "предел: половина меньшей стороны (340 / 2)")
n = len(cv.undo_stack)
ed.radius_spin.setValue(40)
check(cv.form.code == forma.ROUND and abs(cv.form.radius - 40) < 1e-6, "поле: радиус 40")
check(len(cv.undo_stack) == n + 1, "поле: один шаг отмены")
check(ed.ctx.config["form_last"] == forma.ROUND and ed.ctx.config["form_radius"] == 40, "свой радиус запомнен вместе с формой")
check("40" in ed.form_button.toolTip(), "подсказка кнопки называет радиус")
o = cv.render()
check(alpha(o, 5, 5) == 0 and alpha(o, 40, 40) == 255, "радиус 40 виден в готовой картинке")
ed.radius_spin.setValue(10000)
check(ed.radius_spin.value() == 170 and abs(cv.form.radius - 170) < 1e-6, "поле не даёт больше предела")
o = cv.render()
check(alpha(o, 2, 170) == 255 and alpha(o, 60, 2) == 0 and alpha(o, 280, 2) == 255,
      "радиус на пределе: короткие стороны полукругом, длинные прямые")
n = len(cv.undo_stack)
ed.radius_slider.setSliderDown(True)
for v in (150, 120, 90, 64):
    ed.radius_slider.setValue(v)
ed.radius_slider.setSliderDown(False)
app.processEvents()
check(abs(cv.form.radius - 64) < 1e-6 and ed.radius_spin.value() == 64, "ползунок: радиус 64, поле следом")
check(len(cv.undo_stack) == n + 1, "перетаскивание ползунка: один шаг отмены")
cv.undo()
check(abs(cv.form.radius - 170) < 1e-6 and ed.radius_slider.value() == 170, "Ctrl+Z: радиус до ползунка, ползунок следом")
cv.redo()
ed.radius_slider.setValue(12)
check(cv.form.code == forma.ROUND_S, "радиус 12 = готовые малые скругления (пункт меню отмечен)")
check([a.data() for a in ed.build_form_menu().actions() if a.isCheckable() and a.isChecked()] == [forma.ROUND_S],
      "меню: отмечены малые")
ed.set_form(forma.ROUND_L)
check(ed.radius_slider.value() == 56, "пункт «большие» ставит ползунок на 56")
# маркер радиуса на холсте
z = cv.zoom
h = forma.radius_handle(cv.form, cv.lw(), cv.lh())
hp = QPoint(round(h.x() * z), round(h.y() * z))
QTest.mouseMove(cv, hp)
check(cv.cursor().shape() == Qt.CursorShape.SizeFDiagCursor, "над маркером радиуса курсор по диагонали")
n = len(cv.undo_stack)
QTest.mousePress(cv, L, NOMOD, hp)
for i in range(1, 6):
    QTest.mouseMove(cv, hp + QPoint(round(3 * i * z), round(3 * i * z)))
QTest.mouseRelease(cv, L, NOMOD, hp + QPoint(round(15 * z), round(15 * z)))
app.processEvents()
check(cv.form.radius > 56 + 30 and ed.radius_spin.value() == round(cv.form.radius), f"маркер: радиус вырос ({cv.form.radius:.0f}), поле следом")
check(len(cv.undo_stack) == n + 1, "маркер: один шаг отмены")
ed.set_form(forma.OVAL)
check(not ed.radius_box.isVisibleTo(ed), "овал: ползунка радиуса нет")
ed.set_form(forma.RECT)

# --- 5. Круг сдвигается мышью за поле вокруг него ------------------------------------------------
ed.set_form(forma.CIRCLE)
check(abs(forma.clamp_center(cv.form, cv.lw(), cv.lh()).x() - 280) < 0.01, "круг сначала по центру")
undo_before = len(cv.undo_stack)
shapes_before = len(cv.shapes)
z = cv.zoom


def at(x, y):
    return QPoint(round(x * z), round(y * z))


QTest.mouseMove(cv, at(30, 170))
check(cv.cursor().shape() == Qt.CursorShape.OpenHandCursor, "над полем вокруг круга курсор-рука")
QTest.mousePress(cv, L, NOMOD, at(30, 170))
for i in range(1, 6):
    QTest.mouseMove(cv, at(30 - 10 * i, 170))
QTest.mouseRelease(cv, L, NOMOD, at(-20, 170))
app.processEvents()
cx = forma.clamp_center(cv.form, cv.lw(), cv.lh()).x()
check(abs(cx - 230) < 1.5, f"круг сдвинулся влево на 50 точек ({cx:.1f})")
check(len(cv.undo_stack) == undo_before + 1, "перенос круга: один шаг отмены")
check(len(cv.shapes) == shapes_before, "перенос круга ничего не нарисовал")
QTest.mousePress(cv, L, NOMOD, at(20, 170))
for i in range(1, 8):
    QTest.mouseMove(cv, at(20 - 40 * i, 170))
QTest.mouseRelease(cv, L, NOMOD, at(-260, 170))
app.processEvents()
r = forma.circle_rect(cv.form, cv.lw(), cv.lh())
check(r.x() == 0, "круг упирается в край снимка и дальше не уходит")
out = cv.render()
check((out.width(), out.height()) == (340, 340), "готовый круг 340 × 340 (меньшая сторона снимка)")
cv.undo()
check(abs(forma.clamp_center(cv.form, cv.lw(), cv.lh()).x() - 230) < 1.5, "отмена возвращает прошлое место круга")
n = len(cv.undo_stack)
QTest.mousePress(cv, L, NOMOD, at(20, 170))
QTest.mouseRelease(cv, L, NOMOD, at(20, 170))
check(len(cv.undo_stack) == n, "щелчок по полю без сдвига не пишет шаг отмены")
QTest.mouseMove(cv, at(280, 170))
check(cv.cursor().shape() != Qt.CursorShape.OpenHandCursor, "внутри круга обычный курсор инструмента")

# --- 6. Обрезка при форме: рамка по всему снимку, круг остаётся над тем же местом ----------------
cv.set_form(forma.CIRCLE, QPointF(300, 170))
from clipshot.editor import CROP, MOVE
cv.tool = CROP
check(not cv.form_active(), "в режиме обрезки шахматки нет: видно весь снимок")
cv.tool = MOVE
from PyQt6.QtCore import QRect
cv.apply_crop(QRect(100, 0, 460, 340))
check(abs(cv.form.center.x() - 200) < 0.01, "после обрезки центр круга сдвинут вместе со снимком")

# --- 7. Вставка из буфера: углы остаются прозрачными ---------------------------------------------
QGuiApplication.clipboard().setMimeData(hidpi.clipboard_mime(forma.apply(picture(200, 120, "#00aa00"), forma.Form(forma.OVAL)),
                                                             {"clip_html": False}))
count = len(cv.shapes)
ed.paste_image()
ins = cv.shapes[-1] if len(cv.shapes) > count else None
check(ins is not None and forma.has_transparency(ins.image), "вставка снимка с формой: прозрачные углы, не белые")
# М7 проверки 1.34.0: обычный снимок (PNG без альфы) при вставке заново не раскодируется, решает заголовок PNG
from PyQt6.QtCore import QBuffer, QByteArray, QIODevice  # noqa: E402
from clipshot.editor import _png_may_have_alpha  # noqa: E402


def png_bytes(image):
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buf, "PNG")
    return bytes(ba)


rgb = QImage(64, 40, QImage.Format.Format_RGB32)
rgb.fill(QColor("#123456"))
argb = forma.apply(picture(64, 40, "#00aa00"), forma.Form(forma.OVAL))
check(not _png_may_have_alpha(png_bytes(rgb), 64, 40), "PNG обычного снимка (RGB): раскодировать не нужно")
check(_png_may_have_alpha(png_bytes(argb), argb.width(), argb.height()), "PNG снимка с формой (RGBA): раскодируется")
check(not _png_may_have_alpha(png_bytes(argb), 65, 40), "PNG другого размера: не тот снимок, не раскодируется")
check(_png_may_have_alpha(b"not a png at all, just bytes for the check", 64, 40), "не PNG: решает раскодирование, как раньше")

# --- 8. Тёмная тема, новый снимок, языки ---------------------------------------------------------
ctx2 = Ctx()
ctx2.config["ui_theme"] = "pro"
ctx2.config["form_last"] = forma.CIRCLE
ed2 = EditorWindow(picture(400, 300, "#3366cc"), ctx2, QPoint(50, 50))
ed2.present()
app.processEvents()
check(ed2.canvas.form.is_rect, "следующий снимок снова прямоугольный, хотя последняя форма круг")
check(ed2.last_form() == forma.CIRCLE, "последняя форма доступна одним щелчком")
ed2.toggle_form()
check(ed2.canvas.form.code == forma.CIRCLE, "щелчок включает круг")
ctx3 = Ctx()
ctx3.config.update(form_last=forma.ROUND, form_radius=40.0)
ed3 = EditorWindow(picture(400, 300), ctx3, QPoint(50, 50))
ed3.toggle_form()
check(ed3.canvas.form.code == forma.ROUND and abs(ed3.canvas.form.radius - 40) < 1e-6,
      "новый снимок: щелчок включает скругление со своим радиусом 40")
ed3.exported = True
ed3.close()
shot = ed2.canvas.grab().toImage()
c0 = shot.pixelColor(1, 1).name()
check(c0 in forma.CHECKER_COLORS[True], f"тёмная тема: тёмная шахматка ({c0})")
os.environ.pop("CLIPSD_LANG", None)
i18n.set_language("de", notify=False)
ed2.retranslate()
check(ed2.form_button.isChecked() and ed2.canvas.form.code == forma.CIRCLE, "смена языка: форма и кнопка на месте")
check("Kreis" in ed2.form_button.toolTip(), f"подсказка на немецком ({ed2.form_button.toolTip()[:40]}…)")

ref = json.load(open(os.path.join(os.path.dirname(here), "clipshot", "i18n", "ru", "forma.json"), encoding="utf-8"))
for lang in i18n.LANGUAGES:
    cat = json.load(open(os.path.join(os.path.dirname(here), "clipshot", "i18n", lang, "forma.json"), encoding="utf-8"))
    check(set(cat) == set(ref), f"{lang}: все строки формы")
    bad = [k for k, v in cat.items() if "—" in v or any(ord(ch) > 0x1F000 for ch in v)]
    check(not bad, f"{lang}: без длинных тире и эмодзи {bad}")

for e in (ed, ed2):
    e.exported = True   # без вопроса «Сохранить изменения?»
    e.close()
shutil.rmtree(tmp, ignore_errors=True)
print("ИТОГ:", "ВСЁ ХОРОШО" if not failures else f"{len(failures)} ошибок")
sys.exit(1 if failures else 0)
