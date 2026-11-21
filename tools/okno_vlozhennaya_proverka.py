# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Часть проверки tools/okno_vlozhennaya_proverka.sh: путь ClipSD к дополнению (QtDBus, асинхронно) внутри
безэкранной сессии GNOME Shell. Запускается только оттуда: шина сеанса здесь проверочная, не человека."""
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyQt6.QtCore import QTimer  # noqa: E402
from PyQt6.QtGui import QColor  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
from clipshot import windows  # noqa: E402

T = Path(sys.argv[1])
out = {}


def done_list(wl):
    out["list"] = wl
    out["list_ms"] = round((time.perf_counter() - out["t0"]) * 1000)
    app.quit()


out["t0"] = time.perf_counter()
lister = windows.WindowLister()
lister.ready.connect(done_list)
lister.start()
QTimer.singleShot(5000, app.quit)
app.exec()
wl = out.get("list")
if wl is None:
    print("СПИСОК: не пришёл за 5 с")
    sys.exit(1)
print(f"СПИСОК: источник {wl.source}, дополнение {wl.ext_state}, полный {wl.complete}, окон {len(wl.windows)}, "
      f"{out['list_ms']} мс")
for w in wl.windows:
    print(f"  z={w.z} {w.title!r} {w.rect.getRect()} свёрнуто={w.minimized}")
red = next((w for w in wl.windows if w.title == "okno-red"), None)
blue = next((w for w in wl.windows if w.title == "okno-blue"), None)
print("ЗАКРЫТО ДРУГИМ (красное под синим):", bool(red and windows.is_covered(red, wl.windows)))


def grab(win):
    res = {}
    job = windows.WindowGrab(win)
    t0 = time.perf_counter()

    def got(pm):
        res["pm"], res["ms"] = pm, round((time.perf_counter() - t0) * 1000)
        app.quit()
    job.done.connect(got)
    job.start()
    QTimer.singleShot(6000, app.quit)
    app.exec()
    return res.get("pm"), res.get("ms")


if red is not None and blue is not None:
    pm, ms = grab(red)
    if pm is None:
        print("СОДЕРЖИМОЕ красного: нет")
    else:
        img = pm.toImage()
        k = pm.devicePixelRatio()
        # точка внутри перекрытия: в замороженном кадре там синее окно, в содержимом красного должно быть красное
        ov = blue.rect.intersected(red.rect)
        x, y = round((ov.center().x() - red.rect.x()) * k), round((ov.center().y() - red.rect.y()) * k)
        c = img.pixelColor(x, y)
        print(f"СОДЕРЖИМОЕ красного: {img.width()}x{img.height()} (рамка {red.rect.width()}x{red.rect.height()}), "
              f"{ms} мс, цвет в месте перекрытия {c.name()}, красный: {c.red() > 180 and c.blue() < 90}")
    green = next((w for w in wl.windows if w.title == "okno-green"), None)
    if green is not None:
        pm, ms = grab(green)
        c = pm.toImage().pixelColor(pm.width() // 2, pm.height() // 2) if pm is not None else QColor()
        print(f"СОДЕРЖИМОЕ свёрнутого зелёного: {'есть' if pm is not None else 'нет'}, {ms} мс, цвет {c.name()}")
    gone = windows.WinInfo("999999", "нет такого", "", rect=red.rect, source="gnome-ext")
    pm, ms = grab(gone)
    print(f"СОДЕРЖИМОЕ несуществующего окна: {'есть' if pm is not None else 'нет'} ({ms} мс)")
