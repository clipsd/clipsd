# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Экраны с масштабом (1.32): плотность pHYs в PNG файла и буфера обмена (96 dpi × масштаб) при 100, 125, 150, 200 %;
HTML с размером в точках в буфере только при масштабе ≠ 100 % (и выключается настройкой, и не кладётся больше 8 МБ);
режим «Как на экране, 100%» уменьшает снимок до размера в точках со сглаживанием; JPG с плотностью JFIF;
мониторы с разным масштабом: снимок в масштабе монитора области; редактор при QT_SCALE_FACTOR=1.5 показывает снимок
пиксель в пиксель, выделение и лупа берут нужные физические пиксели.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/hidpi_test.py (сам запускает дочерние проверки с масштабом 1.5
и с двумя мониторами разного масштаба).
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import base64
import json
import os
import re
import subprocess
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(here)
sys.path.insert(0, ROOT)
MODE = sys.argv[1] if len(sys.argv) > 1 else "main"
if MODE == "mixed":
    _cfg = os.path.join(tempfile.mkdtemp(prefix="clipsd-hidpi-"), "screens.json")
    with open(_cfg, "w", encoding="utf-8") as _f:   # монитор 100 % слева, монитор 150 % справа
        json.dump({"screens": [
            {"name": "a", "x": 0, "y": 0, "width": 1000, "height": 600, "logicalDpi": 96, "logicalBaseDpi": 96},
            {"name": "b", "x": 1000, "y": 0, "width": 1200, "height": 900, "logicalDpi": 144, "logicalBaseDpi": 96}]}, _f)
    os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _cfg
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPixmap
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
from clipshot import app as appmod, editor as editormod, grab, hidpi
from clipshot.editor import EditorWindow
from clipshot.selector import RegionSelector

failures = []
TMP = tempfile.mkdtemp(prefix="clipsd-hidpi-out-")


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def settle(n=6):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(15)


def noise(w, h, ratio=1.0, seed=7):
    """Картинка с разными соседними пикселями: любое растяжение или сглаживание меняет пиксели."""
    data = bytearray()
    state = seed
    for _ in range(w * h):
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        data += bytes((state & 255, (state >> 8) & 255, (state >> 16) & 255, 255))
    img = QImage(bytes(data), w, h, w * 4, QImage.Format.Format_RGB32).copy()
    img.setDevicePixelRatio(ratio)
    return img


def stripes(w, h, ratio):
    """Чёрно-белые полосы в 1 пиксель: при уменьшении со сглаживанием выходит серый, без него остаются чёрный и белый."""
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setPen(QColor("black"))
    for x in range(0, w, 2):
        p.drawLine(x, 0, x, h)
    p.end()
    img.setDevicePixelRatio(ratio)
    return img


def same_pixels(a: QImage, b: QImage) -> int:
    """Сколько пикселей различается (размеры обязаны совпадать)."""
    a = a.convertToFormat(QImage.Format.Format_RGB32)
    b = b.convertToFormat(QImage.Format.Format_RGB32)
    if a.size() != b.size():
        return -1
    return sum(1 for y in range(a.height()) for x in range(a.width()) if a.pixel(x, y) != b.pixel(x, y))


def grays(img: QImage) -> float:
    """Доля пикселей не чисто чёрных и не чисто белых."""
    img = img.convertToFormat(QImage.Format.Format_RGB32)
    total = mid = 0
    for y in range(0, img.height(), 3):
        for x in range(img.width()):
            v = QColor(img.pixel(x, y)).red()
            total += 1
            mid += 20 < v < 235
    return mid / max(1, total)


class FakeApp:
    """Настоящие методы Clipshot (автосохранение, «Сохранить», копирование) без трея и клавиш."""
    autosave = appmod.Clipshot.autosave
    snapshot_path = appmod.Clipshot.snapshot_path
    copy_image = appmod.Clipshot.copy_image
    icon = appmod.make_icon()

    def __init__(self, **cfg):
        self.config = dict(appmod.DEFAULTS, auto_save_dir=TMP, save_dir=TMP, tour_done=True, theme_chosen=True, **cfg)

    def notify(self, text):
        pass

    def save_config(self):
        pass


def clip():
    mime = QGuiApplication.clipboard().mimeData()
    png = bytes(mime.data("image/png"))
    return mime, png


def html_img(html):
    m = re.search(r'<img src="data:image/png;base64,([A-Za-z0-9+/=]+)" width="(\d+)" height="(\d+)" alt="">', html or "")
    return (base64.b64decode(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def main_checks():
    print("--- плотность и HTML при масштабах 100, 125, 150, 200 %")
    check(hidpi.dots_per_meter(1.0) == 3780 and hidpi.dots_per_meter(1.5) == 5669 and hidpi.dots_per_meter(2) == 7559,
          "плотность: 96 dpi = 3780, 144 dpi = 5669, 192 dpi = 7559 точек на метр")
    check(appmod.DEFAULTS["snapshot_size"] == "full", "по умолчанию «Полное разрешение»")
    check(appmod.DEFAULTS["clip_html"] is (sys.platform != "win32"), "HTML в буфере по умолчанию: Linux да, Windows нет")
    for ratio, (pw, ph), (lw, lh) in ((1.0, (300, 200), (300, 200)), (1.25, (375, 250), (300, 200)),
                                      (1.5, (450, 300), (300, 200)), (2.0, (600, 400), (300, 200))):
        name = f"{round(ratio * 100)} %"
        dpm = hidpi.dots_per_meter(ratio)
        img = noise(pw, ph, ratio)
        fake = FakeApp()
        path = fake.autosave(img)
        data = open(path, "rb").read() if path else b""
        check(hidpi.read_phys(data) == (dpm, dpm, 1), f"{name}: автосохранение PNG с pHYs {round(96 * ratio)} dpi "
              f"({hidpi.read_phys(data)})")
        back = QImage(path)
        check((back.width(), back.height()) == (pw, ph) and same_pixels(back, img) == 0,
              f"{name}: в файле все {pw}x{ph} пикселей без изменений")
        jpg = os.path.join(TMP, f"shot-{ratio}.jpg")
        check(hidpi.save_image(img, jpg, fake.config), f"{name}: JPG сохраняется")
        dpi = QImage(jpg).dotsPerMeterX() * 0.0254
        check(abs(dpi - 96 * ratio) < 1, f"{name}: в JPG плотность JFIF {dpi:.0f} dpi")
        fake.copy_image(img)
        mime, png = clip()
        check(hidpi.read_phys(png) == (dpm, dpm, 1), f"{name}: image/png в буфере с pHYs {round(96 * ratio)} dpi")
        check(QImage.fromData(png).size() == img.size(), f"{name}: в буфере полное разрешение {pw}x{ph}")
        cimg = mime.imageData()
        check(cimg is not None and QImage(cimg).dotsPerMeterX() == dpm,
              f"{name}: картинка буфера (из неё Qt делает BMP, а в Windows CF_DIB) с той же плотностью")
        got = html_img(mime.html()) if mime.hasHtml() else None
        if ratio == 1.0:
            check(not mime.hasHtml(), f"{name}: HTML в буфере нет (на экране 100% ничего не меняется)")
        else:
            check(got is not None and got[1:] == (lw, lh),
                  f"{name}: HTML <img width={lw} height={lh}> в точках ({got[1:] if got else mime.html()[:80]})")
            check(got is not None and got[0] == png, f"{name}: в HTML тот же PNG, что в image/png")

    print("--- настройка «Вставлять в исходном размере» выключена, большой снимок")
    img = noise(450, 300, 1.5)
    FakeApp(clip_html=False).copy_image(img)
    mime, png = clip()
    check(not mime.hasHtml() and hidpi.read_phys(png) == (5669, 5669, 1),
          "выключено: в буфере только картинка (с pHYs 144 dpi), без HTML")
    old = hidpi.HTML_LIMIT
    hidpi.HTML_LIMIT = 1000
    FakeApp().copy_image(img)
    mime, png = clip()
    check(not mime.hasHtml() and len(png) > 1000, "PNG больше предела base64 (8 МБ, в тесте 1000 байт): без HTML")
    hidpi.HTML_LIMIT = old
    check(hidpi.HTML_LIMIT == 8 * 1024 * 1024, "предел HTML в буфере 8 МБ")

    print("--- pHYs дописывается сам, если PNG пришёл без него")
    plain = noise(20, 10)
    raw = hidpi.ensure_phys(b"", 5669)
    check(raw == b"", "не PNG не трогаем")
    from PyQt6.QtCore import QBuffer, QIODevice
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    plain.save(buf, "PNG")
    data = bytes(buf.data())
    idx = data.find(b"pHYs") - 4
    stripped = data[:idx] + data[idx + 21:] if idx > 0 else data
    check(hidpi.read_phys(stripped) is None, "без чанка: read_phys = None")
    fixed = hidpi.ensure_phys(stripped, 5669)
    check(hidpi.read_phys(fixed) == (5669, 5669, 1) and fixed.index(b"pHYs") < fixed.index(b"IDAT")
          and same_pixels(QImage.fromData(fixed), plain) == 0, "чанк вставлен до IDAT, картинка читается")
    check(hidpi.read_phys(hidpi.ensure_phys(fixed, 3780)) == (3780, 3780, 1), "чужая плотность заменяется")

    print("--- «Как на экране, 100%»: уменьшение до размера в точках")
    img = stripes(600, 300, 2.0)
    fake = FakeApp(snapshot_size="screen")
    path = fake.autosave(img)
    back = QImage(path)
    check((back.width(), back.height()) == (300, 150), f"200 %: файл 300x150 вместо 600x300 ({back.width()}x{back.height()})")
    check(hidpi.read_phys(open(path, "rb").read()) == (3780, 3780, 1), "плотность 96 dpi")
    check(grays(back) > 0.9, f"сглаживание: полосы в 1 px стали серыми ({grays(back):.2f}), а не рябью")
    fake.copy_image(img)
    mime, png = clip()
    check(QImage.fromData(png).size().width() == 300 and not mime.hasHtml(), "в буфер тоже 300x150, без HTML")
    img = noise(450, 300, 1.5)
    out = hidpi.prepare(img, "screen")
    check((out.width(), out.height(), out.devicePixelRatio()) == (300, 200, 1.0), "150 %: 450x300 → 300x200")
    img1 = noise(300, 200, 1.0)
    check(same_pixels(hidpi.prepare(img1, "screen"), img1) == 0, "на экране 100% «как на экране» снимок не меняет")
    check(img.width() == 450 and img.devicePixelRatio() == 1.5, "исходный снимок не испорчен")

    print("--- редактор: сохранение, обновление автосохранения, копирование")
    fake = FakeApp()
    img = noise(450, 300, 1.5)
    ed = EditorWindow(img, fake, QPoint(40, 40))
    ed.present()
    settle()
    path = os.path.join(TMP, "editor-save.png")
    editormod.ask_save_path = lambda *_a, **_k: path
    ed.canvas.modified = True
    ed.save_and_close()
    data = open(path, "rb").read() if os.path.exists(path) else b""
    check(hidpi.read_phys(data) == (5669, 5669, 1) and QImage(path).width() == 450,
          "«Сохранить» в редакторе: 450x300 с pHYs 144 dpi")
    auto = os.path.join(TMP, "editor-auto.png")
    ed = EditorWindow(img, fake, QPoint(40, 40))
    ed.autosave_path = auto
    ed.canvas.modified = True
    ed.copy_to_clipboard()
    mime, png = clip()
    check(hidpi.read_phys(open(auto, "rb").read()) == (5669, 5669, 1), "файл автосохранения после правок с pHYs 144 dpi")
    check(hidpi.read_phys(png) == (5669, 5669, 1) and html_img(mime.html())[1:] == (300, 200),
          "«Копировать» в редакторе: pHYs 144 dpi и HTML 300x200")
    ed.exported = True
    ed.close()

    print("--- окно 100 %, снимок с монитора 150 %: уменьшение со сглаживанием")
    ed = EditorWindow(stripes(450, 300, 1.5), fake, QPoint(40, 40))
    ed.present()
    settle()
    shown = ed.canvas.grab().toImage()
    check((shown.width(), shown.height()) == (300, 200), f"холст в точках 300x200 ({shown.width()}x{shown.height()})")
    check(grays(shown) > 0.5, f"полосы 1 px показаны сглаженно ({grays(shown):.2f}), без рваной ряби")
    ed.exported = True
    ed.close()


def scaled_checks():
    """Дочерний процесс: QT_SCALE_FACTOR=1.5, как ноутбук владельца с масштабом 150 %."""
    ratio = app.primaryScreen().devicePixelRatio()
    check(abs(ratio - 1.5) < 0.01, f"экран с масштабом 1.5 (devicePixelRatio {ratio})")
    fake = FakeApp()
    img = noise(450, 300, 1.5)
    ed = EditorWindow(img, fake, QPoint(40, 40))
    ed.present()
    settle()
    c = ed.canvas
    check(c.zoom == 1.0 and ed.zoom_label.text() == "100%", "редактор открылся в 100%")
    check((c.width(), c.height()) == (300, 200), f"холст 300x200 точек ({c.width()}x{c.height()})")
    shot = c.grab()
    shown = shot.toImage()
    check((shown.width(), shown.height()) == (450, 300) and abs(shot.devicePixelRatio() - 1.5) < 0.01,
          f"на экране 450x300 физических пикселей ({shown.width()}x{shown.height()}): без растяжения")
    diff = same_pixels(shown, img)
    check(diff == 0, f"100%: пиксель в пиксель, без сглаживания (различий: {diff})")
    ed.set_zoom(2.0)
    settle()
    check(c.zoom > 1.0 and c.grab().toImage().width() > 450, "увеличение работает (крупнее 1:1)")
    ed.exported = True
    ed.close()

    print("--- выделение и лупа при 150 %")
    desk = QImage(1500, 900, QImage.Format.Format_RGB32)
    desk.fill(QColor("#808080"))
    desk.setPixelColor(615, 307, QColor("#ff0000"))
    pix = QPixmap.fromImage(desk)
    pix.setDevicePixelRatio(1.5)
    sel = RegionSelector(pix, QRect(0, 0, 1000, 600), True, True, None)
    got = {}

    class Spy(QImage):
        def copy(self, *args):
            got["patch"] = args[0] if args else None
            return QImage.copy(self, *args)

        def pixelColor(self, *args):
            got["pixel"] = (args[0], args[1]) if len(args) == 2 else (args[0].x(), args[0].y())
            return QImage.pixelColor(self, *args)

    sel.image = Spy(sel.image)
    sel.show()
    sel.cursor_pos = QPoint(410, 205)
    sel.repaint()
    settle(2)
    patch = got.get("patch")
    check(got.get("pixel") == (615, 307), f"лупа: курсор (410, 205) точек = пиксель (615, 307) ({got.get('pixel')})")
    check(patch is not None and (patch.x() + patch.width() // 2, patch.y() + patch.height() // 2) == (615, 307),
          f"лупа: участок с этим пикселем в центре ({patch})")
    out = {}
    sel.finished.connect(lambda pm, r: out.update(pm=pm, r=r))
    sel._emit(QRect(400, 200, 20, 10))
    pm = out.get("pm")
    check(pm is not None and (pm.width(), pm.height()) == (30, 15) and abs(pm.devicePixelRatio() - 1.5) < 0.01,
          f"выделение 20x10 точек = 30x15 пикселей, масштаб 1.5 ({pm.size() if pm else None})")
    check(pm is not None and pm.toImage().pixelColor(15, 7).name() == "#ff0000",
          "в снимок попали нужные физические пиксели (красная точка на месте)")


def mixed_checks():
    """Дочерний процесс: монитор a 100 % (0..1000 точек), монитор b 150 % (1000..1800 точек)."""
    screens = app.screens()
    check(len(screens) == 2 and screens[1].devicePixelRatio() == 1.5, "два монитора: 100 % и 150 %")
    desk = grab.grab_qt()
    check(abs(desk.devicePixelRatio() - 1.5) < 0.01 and desk.width() == 2700, "весь стол собран в масштабе 1.5")
    check(len(grab._native_shots) == 1 and grab._native_shots[0][1].devicePixelRatio() == 1.0,
          "родной снимок монитора 100 % сохранён")
    # Подменяем снимки известными картинками: монитор a — шум 1000x600, весь стол — его растянутая копия
    native_a = QPixmap.fromImage(noise(1000, 600, 1.0))
    grab._native_shots[:] = [(QRect(0, 0, 1000, 600), native_a)]
    rect = QRect(100, 50, 200, 100)
    crop = desk.copy(QRect(150, 75, 300, 150))
    crop.setDevicePixelRatio(1.5)
    out = grab.native_region(crop, rect)
    check((out.width(), out.height(), out.devicePixelRatio()) == (200, 100, 1.0),
          f"область на мониторе 100 %: снимок 200x100, масштаб 1 ({out.width()}x{out.height()}, {out.devicePixelRatio()})")
    check(same_pixels(out.toImage(), native_a.toImage().copy(rect)) == 0, "пиксели родные, без растяжения и сглаживания")
    check(hidpi.read_phys(hidpi.png_bytes(hidpi.prepare(out.toImage()))) == (3780, 3780, 1),
          "плотность по монитору снимка: 96 dpi")
    grab._native_shots.clear()   # Wayland-путь: родных снимков нет, растянутое уменьшается до родного масштаба
    out = grab.native_region(crop, rect)
    check((out.width(), out.height(), out.devicePixelRatio()) == (200, 100, 1.0), "без родного снимка: уменьшено до 200x100")
    rect_b = QRect(1100, 100, 200, 100)
    crop_b = desk.copy(QRect(1650, 150, 300, 150))
    crop_b.setDevicePixelRatio(1.5)
    out = grab.native_region(crop_b, rect_b)
    check(out is crop_b, "область на мониторе 150 %: снимок без изменений (300x150, масштаб 1.5)")
    across = QRect(900, 100, 200, 100)
    crop_x = desk.copy(QRect(1350, 150, 300, 150))
    crop_x.setDevicePixelRatio(1.5)
    check(grab.native_region(crop_x, across) is crop_x, "область на двух мониторах: полный масштаб 1.5")


def child(mode, extra_env):
    env = dict(os.environ, **extra_env)
    res = subprocess.run([sys.executable, os.path.abspath(__file__), mode], env=env, capture_output=True, text=True,
                         timeout=300)
    print(res.stdout.rstrip())
    if res.returncode != 0:
        print(res.stderr[-2000:])
    check(res.returncode == 0, f"дочерняя проверка «{mode}» прошла")


if MODE == "scaled":
    scaled_checks()
elif MODE == "mixed":
    mixed_checks()
else:
    main_checks()
    print("=== масштаб экрана 1.5 (QT_SCALE_FACTOR=1.5)")
    child("scaled", {"QT_SCALE_FACTOR": "1.5", "QT_QPA_PLATFORM": "offscreen"})
    print("=== два монитора: 100 % и 150 %")
    child("mixed", {})

print(f"ИТОГ ({MODE}):", "все проверки пройдены" if not failures else f"провалено {len(failures)}")
from clipshot.exitutil import quick_exit
quick_exit(1 if failures else 0)
