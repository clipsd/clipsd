# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Тень, рамка и поля снимка (1.36): размеры, пиксели, сочетание с формой снимка, PNG с прозрачностью и JPG с фоном,
буфер обмена, экран 200 %, панель, предпросмотр вокруг холста, отмена, запоминание, узкое окно, обе темы.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/ten_ramka_test.py
"""
import math
import os
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
sys.path.insert(0, here)
import tmpclean  # noqa: F401,E402  (временные папки этого теста убираются при его выходе)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
from clipshot import app as appmod, forma, hidpi, i18n, ten_ramka
from clipshot.editor import CROP, FRAME_WIDTH, EditorWindow
from clipshot.ten_ramka import Deco

failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


class Ctx:
    def __init__(self, **extra):
        self.config = dict(appmod.DEFAULTS)
        self.config.update(extra)
        self.icon = appmod.make_icon()
        self.copied = []

    def copy_image(self, image, config=None):
        self.copied.append(image)

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


def settle(n=4):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(15)


tmp = tempfile.mkdtemp(prefix="tenramka-", dir=os.environ.get("TMPDIR"))
RED = "#d60808"

# --- 1. Значения оформления ------------------------------------------------------------------------------------------
d = Deco()
check(not d.active and d.pad() == 0, "по умолчанию оформления нет, поля 0")
check(Deco(shadow_size=1000).shadow_size == ten_ramka.SHADOW_SIZE[1] and Deco(shadow_size=-5).shadow_size == ten_ramka.SHADOW_SIZE[0],
      "размер тени ограничен пределами")
check(Deco(frame_width=99).frame_width == ten_ramka.FRAME_WIDTH[1] and Deco(margin=0).margin == ten_ramka.MARGIN[0], "толщина и поля ограничены")
check(Deco(frame_color="не цвет").frame_color == "#000000" and Deco(frame_color="#D60808").frame_color == RED, "цвет рамки: мусор заменён, регистр приведён")
check(Deco(shadow_opacity="abc").shadow_opacity == ten_ramka.SHADOW_OPACITY[2], "число с мусором: значение по умолчанию")
check(Deco(frame=True, frame_width=4).pad() == 4, "рамка 4: добавляется 4")
check(Deco(margin_on=True, margin=10).pad() == 10, "поля 10: добавляется 10")
sh = Deco(shadow=True, shadow_size=20)
check(sh.pad() == int(math.ceil(20 + 20 * ten_ramka.SHADOW_DROP)) == 26, f"тень 20: место под неё 26 ({sh.pad()})")
check(Deco(True, 20, 40, True, 4, RED, True, 10).pad() == 26 + 4 + 10, "тень, рамка и поля складываются")
check(Deco(frame=False, frame_width=9).pad() == 0, "выключенная рамка не занимает места")
a, b = Deco(True, 10, 30), Deco(True, 10, 30)
check(a == b and a is not a.copy() and a.copy() == a and a != Deco(True, 11, 30) and hash(a) == hash(b), "сравнение и копия")
cfg = {}
Deco(True, 33, 55, True, 7, "#1e78ff", True, 40, True).remember(cfg)
back = Deco.from_config(cfg)
check((back.shadow_size, back.shadow_opacity, back.frame_width, back.frame_color, back.margin, back.margin_bg) == (33, 55, 7, "#1e78ff", 40, True),
      "размеры, цвет и вид полей запоминаются")
check(not back.shadow and not back.frame and not back.margin_on and not back.active, "включённость не запоминается: новый снимок без оформления")
check(Deco.from_config({"deco_shadow_size": "мусор"}).shadow_size == ten_ramka.SHADOW_SIZE[2], "мусор в настройках: значения по умолчанию")
check(Deco.from_config(None).shadow_size == ten_ramka.SHADOW_SIZE[2], "нет настроек: значения по умолчанию")

# --- 2. Рамка, поля, тень на картинке -----------------------------------------------------------------------------------
src = picture(300, 200)
check(ten_ramka.apply(src, forma.Form(), Deco()) is src, "без оформления: та же картинка")
fr = ten_ramka.apply(src, forma.Form(), Deco(frame=True, frame_width=4, frame_color=RED))
check((fr.width(), fr.height()) == (308, 208), f"рамка 4: 308 × 208 ({fr.width()} × {fr.height()})")
check(fr.pixelColor(0, 0).name() == RED and fr.pixelColor(3, 100).name() == RED and fr.pixelColor(150, 2).name() == RED, "рамка по периметру")
check(fr.pixelColor(4, 4).name() == "#3366cc" and fr.pixelColor(154, 104).name() == "#3366cc", "внутри рамки снимок на месте")
check(alpha(fr, 0, 0) == 255 and alpha(fr, 307, 207) == 255 and not forma.has_transparency(fr), "рамка без полей: картинка непрозрачна")
check(fr.pixelColor(303, 100).name() == RED and fr.pixelColor(304, 100).name() == "#3366cc" or fr.pixelColor(304, 100).name() == RED,
      "толщина рамки ровно 4 px")
mg = ten_ramka.apply(src, forma.Form(), Deco(margin_on=True, margin=10))
check((mg.width(), mg.height()) == (320, 220) and alpha(mg, 0, 0) == 0 and alpha(mg, 5, 110) == 0, "поля 10 прозрачные: 320 × 220, края прозрачны")
check(mg.pixelColor(10, 10).name() == "#3366cc" and alpha(mg, 10, 10) == 255 and alpha(mg, 9, 10) == 0, "снимок начинается ровно после полей")
bg = ten_ramka.apply(src, forma.Form(), Deco(margin_on=True, margin=10, margin_bg=True), QColor("#202020"))
check(bg.pixelColor(0, 0).name() == "#202020" and alpha(bg, 0, 0) == 255 and bg.pixelColor(5, 110).name() == "#202020", "поля цветом фона: залиты")
bg2 = ten_ramka.apply(src, forma.Form(), Deco(margin_on=True, margin=10, margin_bg=False), QColor("#202020"))
check(alpha(bg2, 0, 0) == 0, "поля «прозрачные»: цвет фона не применяется")
both = ten_ramka.apply(src, forma.Form(), Deco(frame=True, frame_width=4, frame_color=RED, margin_on=True, margin=10))
check((both.width(), both.height()) == (328, 228) and both.pixelColor(10, 10).name() == RED and both.pixelColor(14, 14).name() == "#3366cc"
      and alpha(both, 9, 9) == 0, "рамка внутри полей: сначала поля, потом рамка, потом снимок")
shd = ten_ramka.apply(src, forma.Form(), Deco(shadow=True, shadow_size=20, shadow_opacity=50))
pad = 26
check((shd.width(), shd.height()) == (352, 252), f"тень 20: 352 × 252 ({shd.width()} × {shd.height()})")
cx = pad + 150
below = [alpha(shd, cx, pad + 200 + k) for k in (1, 6, 12, 18, 24)]
above = [alpha(shd, cx, pad - 1 - k) for k in (0, 5, 11, 17, 23)]
check(all(x >= y for x, y in zip(below, below[1:])) and below[0] > below[-1], f"тень плавно слабеет вниз от снимка {below}")
check(below[0] > 40 and below[-1] < 12, f"у края снимка заметна, у границы поля почти нет {below}")
check(above[0] < below[0] and sum(below) > sum(above), f"тень сдвинута вниз: снизу плотнее, чем сверху ({below[0]} > {above[0]})")
check(alpha(shd, 0, 0) < 4 and alpha(shd, 351, 251) < 4, "в углах поля тени уже нет")
check(shd.pixelColor(pad + 5, pad + 5).name() == "#3366cc" and alpha(shd, pad + 5, pad + 5) == 255, "тень не заходит на снимок")
check(shd.pixelColor(cx, pad + 210).red() < 5, "тень чёрная")
dense = ten_ramka.apply(src, forma.Form(), Deco(shadow=True, shadow_size=20, shadow_opacity=80))
thin = ten_ramka.apply(src, forma.Form(), Deco(shadow=True, shadow_size=20, shadow_opacity=15))
check(alpha(dense, cx, pad + 203) > alpha(shd, cx, pad + 203) > alpha(thin, cx, pad + 203), "плотность тени меняет прозрачность")
soft = ten_ramka.apply(src, forma.Form(), Deco(shadow=True, shadow_size=50, shadow_opacity=50))
hard = ten_ramka.apply(src, forma.Form(), Deco(shadow=True, shadow_size=6, shadow_opacity=50))
check(soft.width() == 300 + 2 * math.ceil(50 + 15) and hard.width() == 300 + 2 * math.ceil(6 + 1.8), "размер картинки растёт вместе с размером тени")
full = ten_ramka.apply(src, forma.Form(), Deco(True, 20, 50, True, 4, RED, True, 10))
fp = 26 + 4 + 10
check((full.width(), full.height()) == (300 + 2 * fp, 200 + 2 * fp), f"тень, рамка и поля: {full.width()} × {full.height()}")
check(full.pixelColor(fp - 1, fp + 100).name() == RED and full.pixelColor(fp - 4, fp + 100).name() == RED
      and full.pixelColor(fp, fp + 100).name() == "#3366cc", "в сочетании рамка снаружи снимка, снимок на месте")
check(alpha(full, fp - 4 - 1, fp + 100) < 100 and alpha(full, fp, fp + 100) == 255, "рамка ложится поверх тени, тень лишь снаружи неё")

# --- 3. Сочетание с формой снимка --------------------------------------------------------------------------------------
shaped = forma.apply(picture(300, 200), forma.Form(forma.ROUND_L))
rd = ten_ramka.apply(shaped, forma.Form(forma.ROUND_L), Deco(frame=True, frame_width=8, frame_color=RED))
check((rd.width(), rd.height()) == (316, 216), f"скругления + рамка 8: 316 × 216 ({rd.width()} × {rd.height()})")
check(alpha(rd, 0, 0) == 0 and alpha(rd, 315, 0) == 0, "углы картинки прозрачны: рамка повторяет скругление")
check(rd.pixelColor(8 + 12, 8 + 12).name() == RED, "в вырезе угла снимка видна рамка (скругление радиуса 56 + 8)")
check(rd.pixelColor(8 + 150, 2).name() == RED and rd.pixelColor(8 + 150, 8 + 100).name() == "#3366cc", "рамка по прямому краю, снимок внутри")
check(alpha(rd, 8 + 4, 8 + 4) == 0 or alpha(rd, 8 + 4, 8 + 4) == 255, "угол снимка за контуром: рамка или пусто, не серый")
rd2 = ten_ramka.apply(shaped, forma.Form(forma.ROUND_L), Deco(shadow=True, shadow_size=16, shadow_opacity=60, margin_on=True, margin=6))
check(rd2.pixelColor(22 + 150, 22 + 100).name() == "#3366cc" and alpha(rd2, 22 + 2, 22 + 2) < 255, "скругления + тень + поля: размер и вырез угла")
check(rd2.width() == 300 + 2 * (6 + math.ceil(16 + 4.8)), f"размер при форме и тени: {rd2.width()}")
oval_src = forma.apply(picture(300, 200), forma.Form(forma.OVAL))
ov = ten_ramka.apply(oval_src, forma.Form(forma.OVAL), Deco(frame=True, frame_width=5, frame_color=RED))
check(ov.pixelColor(5 + 150, 2).name() == RED and alpha(ov, 0, 0) == 0 and ov.pixelColor(5 + 150, 5 + 100).name() == "#3366cc", "овал: рамка по эллипсу")
circ = forma.apply(picture(300, 200), forma.Form(forma.CIRCLE))
cc = ten_ramka.apply(circ, forma.Form(forma.CIRCLE, None), Deco(frame=True, frame_width=5, frame_color=RED, margin_on=True, margin=7))
check((cc.width(), cc.height()) == (200 + 24, 200 + 24), f"круг + рамка + поля: 224 × 224 ({cc.width()} × {cc.height()})")
check(cc.pixelColor(112, 7 + 2).name() == RED and alpha(cc, 0, 0) == 0 and cc.pixelColor(112, 112).name() == "#3366cc", "круг: рамка по окружности")

# экран 200 %
hi = forma.apply(picture(150, 100, ratio=2.0), forma.Form(forma.ROUND_M))
hd = ten_ramka.apply(hi, forma.Form(forma.ROUND_M), Deco(frame=True, frame_width=4, frame_color=RED, margin_on=True, margin=10))
check((hd.width(), hd.height(), hd.devicePixelRatio()) == (300 + 56, 200 + 56, 2.0), f"экран 200 %: физические пиксели ×2, масштаб сохранён ({hd.width()} × {hd.height()})")
check(hd.pixelColor(28 + 150, 20 + 3).name() == RED, "экран 200 %: рамка толщиной 4 точки = 8 пикселей")
check(hd.pixelColor(28 + 150, 20 - 1).alpha() == 0 and hd.pixelColor(28 + 150, 20 + 8).name() != RED, "экран 200 %: границы рамки в точных пикселях")

# --- 4. Файлы и буфер: PNG с прозрачностью, JPG с фоном ----------------------------------------------------------------
img = ten_ramka.apply(src, forma.Form(), Deco(True, 14, 50, True, 3, RED, True, 8))
png = os.path.join(tmp, "a.png")
check(hidpi.save_image(img, png, {}), "PNG сохранён")
back = QImage(png)
check(back.hasAlphaChannel() and alpha(back, 0, 0) == 0 and back.size() == img.size(), "PNG: поля прозрачные, размер тот же")
check(alpha(back, back.width() // 2, back.height() // 2) == 255 and back.pixelColor(back.width() // 2, back.height() // 2).name() == "#3366cc", "PNG: снимок в середине")
jpg = os.path.join(tmp, "a.jpg")
check(hidpi.save_image(img, jpg, {}), "JPG сохранён")
jb = QImage(jpg)
c = jb.pixelColor(1, 1)
check(not jb.hasAlphaChannel() and min(c.red(), c.green(), c.blue()) >= 245, f"JPG: прозрачные поля залиты белым по умолчанию ({c.name()})")
jpg2 = os.path.join(tmp, "b.jpg")
hidpi.save_image(img, jpg2, {"shape_background": "#202020"})
c = QImage(jpg2).pixelColor(1, 1)
check(max(c.red(), c.green(), c.blue()) < 50, f"JPG: цвет фона из настройки shape_background ({c.name()})")
check(QImage(jpg2).pixelColor(QImage(jpg2).width() // 2, QImage(jpg2).height() // 2).blue() > 150, "JPG: снимок в середине")
solid = ten_ramka.apply(src, forma.Form(), Deco(margin_on=True, margin=12, margin_bg=True), QColor("#10a010"))
jpg3 = os.path.join(tmp, "c.jpg")
hidpi.save_image(solid, jpg3, {"shape_background": "#202020"})
c = QImage(jpg3).pixelColor(2, 2)
check(c.green() > 120 and c.red() < 60, f"JPG: поля «цветом фона», заданные в оформлении, остаются как есть ({c.name()})")
webp = os.path.join(tmp, "a.webp")
hidpi.save_image(img, webp, {})
wb = QImage(webp)
check(not wb.isNull() and alpha(wb, 0, 0) == 0, "WebP: прозрачность полей сохранена")
mime = hidpi.clipboard_mime(img, {"clip_html": False})
pimg = QImage.fromData(bytes(mime.data("image/png")))
check(alpha(pimg, 0, 0) == 0 and pimg.size() == img.size(), "буфер: PNG с прозрачностью и тем же размером")
flat = QImage(mime.imageData())
check(not flat.hasAlphaChannel() and flat.pixelColor(1, 1).name() == "#ffffff", "буфер: запасная картинка на белом, без альфа-канала")
frame_only = ten_ramka.apply(src, forma.Form(), Deco(frame=True, frame_width=4, frame_color=RED))
mime2 = hidpi.clipboard_mime(frame_only, {"clip_html": False})
check(QImage(mime2.imageData()).size() == frame_only.size() and not forma.has_transparency(frame_only), "рамка без форм и полей: обычный непрозрачный снимок в буфере")
jpg4 = os.path.join(tmp, "d.jpg")
hidpi.save_image(frame_only, jpg4, {})
check(QImage(jpg4).pixelColor(1, 1).red() > 150 and QImage(jpg4).pixelColor(1, 1).green() < 70, "JPG: рамка без полей остаётся красной (не заливается фоном)")

# --- 5. Редактор: панель, предпросмотр, отмена, запоминание ----------------------------------------------------------------
ctx = Ctx()
ed = EditorWindow(picture(560, 340), ctx, QPoint(50, 50))
ed.present()
settle()
cv = ed.canvas
check(not cv.deco.active and cv.deco_pad() == 0, "новый снимок без оформления")
menu = ed.build_form_menu()
texts = [a.text() for a in menu.actions()]
check(i18n.tr("deco.menu") in texts, f"в меню «Форма снимка» есть «{i18n.tr('deco.menu')}»")
before = len(cv.undo_stack)
panel = ed.show_deco_panel()
settle(2)
check(panel.isVisible() and not panel.shadow_box.isChecked() and not panel.frame_box.isChecked(), "панель открыта, всё выключено")
check(not panel.shadow_size.isEnabled() and not panel.frame_width.isEnabled() and not panel.margin_size.isEnabled(), "ползунки выключенного недоступны")
panel.frame_box.setChecked(True)
check(cv.deco.frame and len(cv.undo_stack) == before + 1, "«Рамка» включена: один шаг отмены")
check(panel.frame_width.isEnabled() and not panel.shadow_size.isEnabled(), "доступны ползунки только включённого")
panel._pick_color("#1e78ff")
check(cv.deco.frame_color == "#1e78ff", "цвет рамки из палитры")
n = len(cv.undo_stack)
panel.frame_width.setSliderDown(True)
for v in (6, 9, 12):
    panel.frame_width.setValue(v)
panel.frame_width.setSliderDown(False)
check(cv.deco.frame_width == 12 and len(cv.undo_stack) == n + 1, "ползунок: значение 12, один шаг отмены на всё перетаскивание")
panel.frame_width.setValue(5)
check(cv.deco.frame_width == 5 and len(cv.undo_stack) == n + 2, "значение с клавиатуры: отдельный шаг")
panel.shadow_box.setChecked(True)
panel.shadow_size.setValue(20)
panel.shadow_opacity.setValue(50)
panel.margin_box.setChecked(True)
panel.margin_size.setValue(16)
panel.margin_bg.setChecked(True)
d = cv.deco
check((d.shadow, d.shadow_size, d.shadow_opacity, d.margin_on, d.margin, d.margin_bg) == (True, 20, 50, True, 16, True), "панель выставила тень, плотность, поля и «цвет фона»")
check(ctx.config["deco_shadow_size"] == 20 and ctx.config["deco_frame_width"] == 5 and ctx.config["deco_frame_color"] == "#1e78ff"
      and ctx.config["deco_margin"] == 16 and ctx.config["deco_margin_bg"] is True, "последний выбор записан в настройки")
pad = d.pad()
check(pad == 5 + 16 + 26, f"место вокруг: рамка 5 + поля 16 + тень 26 = {pad}")
layout_m = ed.frame_layout.contentsMargins()
check(layout_m.left() == FRAME_WIDTH + pad and layout_m.top() == FRAME_WIDTH + pad, f"вокруг холста место под оформление ({layout_m.left()})")
check(cv.lw() == 560 and cv.lh() == 340, "холст и координаты пометок не изменились")
settle(4)
view = ed.image_frame.grab().toImage()
cpos = cv.pos()
check(view.pixelColor(cpos.x() - 1, cpos.y() + 100).name() == "#1e78ff", "предпросмотр: рамка видна вокруг холста")
check(view.pixelColor(cpos.x() + 100, cpos.y() + 100).name() == "#3366cc", "предпросмотр: внутри рамки снимок")
check(ed.info.text().startswith(f"{560 + 2 * pad} × {340 + 2 * pad}"), f"внизу размер готовой картинки: {ed.info.text()}")
# готовая картинка при копировании
ed.copy_to_clipboard()
out = ctx.copied[-1]
check((out.width(), out.height()) == (560 + 2 * pad, 340 + 2 * pad), f"копирование: размер с оформлением ({out.width()} × {out.height()})")
check(out.pixelColor(pad - 5, pad + 100).name() == "#1e78ff", "копирование: рамка на месте")
check(out.pixelColor(2, 2).name() == "#202020" or out.pixelColor(2, 2).name() == "#ffffff", "копирование: поля цветом фона из настройки")
ctx.config["shape_background"] = "#202020"
out = ed.render_image()
check(out.pixelColor(2, 2).name() == "#202020" and alpha(out, 2, 2) == 255, "поля «цветом фона» берут shape_background")
# сохранение
path = os.path.join(tmp, "ed.png")
check(hidpi.save_image(ed.render_image(), path, ctx.config) and QImage(path).size() == out.size(), "сохранение PNG с оформлением")
jp = os.path.join(tmp, "ed.jpg")
check(hidpi.save_image(ed.render_image(), jp, ctx.config) and QImage(jp).pixelColor(2, 2).red() < 50, "сохранение JPG: поля цветом фона")
# масштаб вида
ed.set_zoom(0.5)
settle(2)
check(ed.frame_layout.contentsMargins().left() == FRAME_WIDTH + math.ceil(pad * 0.5), "масштаб вида 50 %: место вокруг холста уменьшилось")
ed.set_zoom(1.0)
# обрезка: оформление не мешает рамке обрезки
ed.select_tool(CROP, open_palette=False)
check(cv.deco_pad() == 0, "режим обрезки: место под оформление не занимается")
ed.select_tool("move", open_palette=False)
check(cv.deco_pad() == pad, "после обрезки место возвращается")
# отмена и повтор
for _ in range(4):
    cv.undo()
settle(2)
check(ed.frame_layout.contentsMargins().left() == FRAME_WIDTH + cv.deco.pad(), "отмена: поля вокруг холста следуют за оформлением")
while cv.undo_stack:
    cv.undo()
check(not cv.deco.active and ed.frame_layout.contentsMargins().left() == FRAME_WIDTH, "отмена всех шагов: оформления нет, место вокруг холста вернулось")
while cv.redo_stack:
    cv.redo()
check(cv.deco.shadow and cv.deco.frame and cv.deco.margin_on, "повтор возвращает оформление целиком")
check(cv.modified and not ed.exported, "оформление считается правкой (вопрос при закрытии)")
# с формой снимка
ed.set_form(forma.ROUND_L)
out = ed.render_image()
check(out.size() == ed.render_image().size() and alpha(out, pad + 2, pad + 2) in range(0, 256), "форма снимка вместе с оформлением")
check(alpha(out, 0, 0) == 255 and out.pixelColor(0, 0).name() == "#202020", "форма + поля цветом фона: углы залиты фоном")
view2 = ed.image_frame.grab().toImage()
check(not view2.isNull(), "предпросмотр с формой рисуется")
ed.exported = True
ed.close()

# новый снимок: размеры запомнены, включённости нет
ed2 = EditorWindow(picture(400, 300), ctx, QPoint(50, 50))
ed2.present()
settle()
d2 = ed2.canvas.deco
check(not d2.active and d2.shadow_size == 20 and d2.frame_width == 5 and d2.frame_color == "#1e78ff" and d2.margin == 16,
      "новый снимок: без оформления, но размеры и цвет прошлого раза")
p2 = ed2.show_deco_panel()
settle(2)
check(p2.shadow_size.value() == 20 and p2.frame_width.value() == 5 and p2.swatches["#1e78ff"].isChecked() and p2.margin_bg.isChecked(),
      "панель показывает запомненные значения")
p2.shadow_box.setChecked(True)
check(ed2.canvas.deco.shadow and ed2.canvas.deco.shadow_size == 20, "включение даёт тень прошлого размера одним щелчком")
# узкое окно: панель и меню формы
ed2.resize(420, 420)
settle(6)
all_menu = ed2.build_all_tools_menu()
subs = [a.menu() for a in all_menu.actions() if a.menu() is not None]
check(any(i18n.tr("deco.menu") in [x.text() for x in m.actions()] for m in subs), "«Все инструменты» (узкое окно): «Форма снимка» с пунктом «Тень, рамка и поля»")
p2.close()
ed2.exported = True
ed2.close()

# обе темы: панель рисуется
for theme in ("standard", "pro"):
    c3 = Ctx(ui_theme=theme)
    e3 = EditorWindow(picture(300, 200), c3, QPoint(50, 50))
    e3.present()
    settle()
    e3.canvas.set_deco(Deco(True, 18, 40, True, 4, RED, True, 12))
    pn = e3.show_deco_panel()
    settle(2)
    shot = pn.grab().toImage()
    bgc = shot.pixelColor(3, shot.height() // 2)
    check(not shot.isNull() and (bgc.lightness() < 110) == (theme == "pro"), f"тема «{theme}»: панель в цветах темы ({bgc.name()})")
    fr_img = e3.image_frame.grab().toImage()
    check(not fr_img.isNull() and e3.canvas.checker_dark == (theme == "pro"), f"тема «{theme}»: предпросмотр рисуется, шахматка по теме")
    pn.close()
    e3.exported = True
    e3.close()

# 12 языков: строки панели
for lang in i18n.LANGUAGES:
    miss = [k for k in ("deco.menu", "deco.title", "deco.shadow", "deco.size", "deco.opacity", "deco.frame", "deco.thickness", "deco.color",
                        "deco.margin", "deco.margin_size", "deco.margin_clear", "deco.margin_bg") if i18n.tr_in(lang, k) == k]
    if miss:
        failures.append(f"{lang}: нет строк {miss}")
check(not [f for f in failures if f.startswith(tuple(i18n.LANGUAGES))], "строки панели есть на всех 12 языках")

if failures:
    print(f"\nПРОВАЛ: {len(failures)}")
    for f in failures:
        print(" -", f)
    sys.exit(1)
print("\nИТОГ: все проверки пройдены")
