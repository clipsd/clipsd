# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Меню правой кнопки по объекту (1.32, замечание владельца на Windows): меню не закрывает рамку и ручки объекта.

place_menu: справа от рамки, иначе слева, ниже, выше; меню целиком на экране того же монитора; объект почти во весь
экран: у курсора, но не на ближайшей ручке. Окно редактора: объект в разных местах снимка, масштаб вида 50-200 %,
второй монитор; пустое место снимка: меню у курсора. Второй проход того же теста с QT_SCALE_FACTOR=1.5 (HiDPI).

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/ctxmenu132_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import json
import os
import subprocess
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
os.environ.pop("CLIPSD_LANG", None)
SCALE = os.environ.get("CLIPSD_CTX_SCALE", "")
_cfg = os.path.join(tempfile.mkdtemp(prefix="clipsd-ctx132-"), "screen.json")
with open(_cfg, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "a", "x": 0, "y": 0, "width": 1600, "height": 1000, "logicalDpi": 96, "logicalBaseDpi": 96},
                           {"name": "b", "x": 1600, "y": 0, "width": 1920, "height": 1080, "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _cfg
if SCALE:
    os.environ["QT_SCALE_FACTOR"] = SCALE

from PyQt6.QtCore import QPoint, QPointF, QRect, QSize
from PyQt6.QtGui import QColor, QGuiApplication, QImage
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMenu

app = QApplication(sys.argv)
from clipshot import app as appmod
from clipshot.editor import MENU_GAP, RECT, EditorWindow, place_menu
from clipshot.shapes import ARROW, Shape

failures = []
checks = [0]
tag = f"[x{SCALE}] " if SCALE else ""


def check(cond, msg):
    checks[0] += 1
    print(("OK   " if cond else "FAIL ") + tag + msg)
    if not cond:
        failures.append(msg)


def settle(n=4):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(10)


def clear(menu_rect, frame):
    return not menu_rect.intersects(frame.adjusted(-MENU_GAP + 1, -MENU_GAP + 1, MENU_GAP - 1, MENU_GAP - 1))


# --- 1. place_menu без окна ---------------------------------------------------------------------------------
area = QRect(0, 0, 1600, 1000)
size = QSize(260, 430)
bad = []
for fx in range(0, 1600, 120):
    for fy in range(0, 1000, 110):
        for fw, fh in ((40, 30), (300, 200), (700, 500)):
            frame = QRect(fx, fy, fw, fh).intersected(area)
            if frame.isEmpty():
                continue
            cursor = frame.center()
            pos = place_menu(frame, size, cursor, area)
            r = QRect(pos, size)
            if not area.contains(r) or not clear(r, frame):
                bad.append((frame, r))
check(not bad, f"меню целиком на экране и не на рамке объекта: {len(bad)} неудач, например {bad[:2]}")
frame = QRect(500, 300, 200, 150)
check(place_menu(frame, size, frame.center(), area).x() == frame.right() + MENU_GAP, "место есть справа: меню справа от рамки")
frame = QRect(1300, 300, 250, 150)
check(QRect(place_menu(frame, size, frame.center(), area), size).right() < frame.left(), "у правого края экрана: слева от рамки")
frame = QRect(100, 80, 1450, 300)
pos = place_menu(frame, size, frame.center(), area)
check(pos.y() > frame.bottom(), "широкий объект сверху: меню ниже рамки")
frame = QRect(100, 560, 1450, 400)
pos = place_menu(frame, size, frame.center(), area)
check(QRect(pos, size).bottom() < frame.top(), "широкий объект снизу: меню выше рамки")
# почти во весь экран: у курсора, ближайшая ручка свободна
frame = QRect(5, 5, 1590, 990)
handles = [frame.topLeft(), frame.topRight(), frame.bottomRight(), frame.bottomLeft()]
for cursor in (QPoint(30, 30), QPoint(1570, 30), QPoint(1570, 970), QPoint(30, 970), QPoint(800, 500)):
    pos = place_menu(frame, size, cursor, area, handles)
    r = QRect(pos, size)
    near = min(handles, key=lambda p: (p - cursor).manhattanLength())
    check(area.contains(r) and not r.contains(near) and (r.topLeft() - cursor).manhattanLength() < 900,
          f"объект во весь экран, курсор {cursor.x()},{cursor.y()}: меню у курсора, ручка {near.x()},{near.y()} открыта")
# второй монитор
area2 = QRect(1600, 0, 1920, 1080)
frame = QRect(3300, 400, 180, 120)
r = QRect(place_menu(frame, size, frame.center(), area2), size)
check(area2.contains(r) and clear(r, frame), "второй монитор: меню на нём же, не на рамке")

# --- 2. окно редактора ---------------------------------------------------------------------------------------


class Ctx:
    def __init__(self):
        self.config = dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True)
        self.icon = appmod.make_icon()

    def save_config(self):
        pass

    def notify(self, text):
        pass


img = QImage(900, 600, QImage.Format.Format_RGB32)
img.fill(QColor("#ffffff"))
ed = EditorWindow(img, Ctx(), QPoint(80, 60))
ed.present()
settle()
c = ed.canvas
shown = []
real_exec = QMenu.exec


def fake_exec(menu, *a, **k):
    shown.append((QPoint(a[0]) if a else None, menu.sizeHint()))


QMenu.exec = fake_exec
for zoom in (1.0, 0.5, 2.0):
    ed.set_zoom(zoom)
    settle()
    for kind, (x1, y1, x2, y2) in ((RECT, (20, 20, 120, 90)), (RECT, (380, 250, 520, 350)), (RECT, (760, 20, 880, 140)),
                                   (RECT, (30, 480, 300, 590)), (ARROW, (700, 560, 860, 420)), (RECT, (10, 10, 890, 590))):
        sh = Shape(kind, "#d60808", 2, QPointF(x1, y1))
        sh.points[-1] = QPointF(x2, y2)
        c.shapes.append(sh)
        c.select(sh)
        settle(1)
        frame = ed.selection_frame_global(sh)
        cursor = c.mapToGlobal(QPoint(int((x1 + x2) / 2 * c.zoom), int((y1 + y2) / 2 * c.zoom)))
        shown.clear()
        ed.show_context_menu(sh, cursor)
        pos, msize = shown[-1]
        r = QRect(pos, msize)
        scr = (QGuiApplication.screenAt(cursor) or QGuiApplication.primaryScreen()).availableGeometry()
        # места нет ни с одной стороны рамки (не только объект во весь экран: и широкий шрифт меню на маленьком
        # экране, как в облачной сборке Ubuntu 22.04 при 150 %): меню у курсора, ближайшая ручка открыта
        big = (frame.left() - scr.left() - MENU_GAP < msize.width() and scr.right() - frame.right() - MENU_GAP < msize.width()
               and frame.top() - scr.top() - MENU_GAP < msize.height() and scr.bottom() - frame.bottom() - MENU_GAP < msize.height())
        ok = scr.contains(r) and (clear(r, frame) or big)
        if big:
            near = min((c.mapToGlobal(QPoint(int(p.x() * c.zoom), int(p.y() * c.zoom))) for p in sh.handles()),
                       key=lambda p: (p - cursor).manhattanLength())
            ok = ok and not r.contains(near)
        check(ok, f"масштаб {zoom}: {kind} {x1},{y1}-{x2},{y2}: меню {r.x()},{r.y()} {r.width()}x{r.height()} "
                  f"не закрывает рамку {frame.x()},{frame.y()} {frame.width()}x{frame.height()}")
        c.shapes.remove(sh)
        c.select(None)
# пустое место снимка: у курсора
cursor = c.mapToGlobal(QPoint(50, 50))
shown.clear()
ed.show_context_menu(None, cursor)
check(shown and shown[-1][0] == cursor, "пустое место: меню у курсора, как обычно")
# окно на втором мониторе
ed.move(1700, 80)
settle()
ed.set_zoom(1.0)
sh = Shape(RECT, "#d60808", 2, QPointF(600, 200))
sh.points[-1] = QPointF(860, 400)
c.shapes.append(sh)
c.select(sh)
cursor = c.mapToGlobal(QPoint(700, 300))
shown.clear()
ed.show_context_menu(sh, cursor)
r = QRect(shown[-1][0], shown[-1][1])
scr2 = QGuiApplication.screenAt(cursor).availableGeometry()
check(scr2.x() >= 1500 and scr2.contains(r) and clear(r, ed.selection_frame_global(sh)), f"второй монитор: меню {r} на нём, рамка открыта")
QMenu.exec = real_exec
ed.canvas.modified, ed.exported = False, True
ed.close()

if not SCALE:   # HiDPI: тот же тест при масштабе 150 %
    env = dict(os.environ, CLIPSD_CTX_SCALE="1.5")
    env.pop("QT_QPA_PLATFORM", None)
    res = subprocess.run([sys.executable, os.path.abspath(__file__)], env=env, capture_output=True, text=True, timeout=300)
    print(res.stdout)
    check(res.returncode == 0, "проход с QT_SCALE_FACTOR=1.5: " + (res.stderr.strip().splitlines()[-1] if res.returncode and res.stderr.strip() else "ok"))
print(f"{tag}ИТОГ: проверок {checks[0]}, провалено: {len(failures)}")
sys.exit(1 if failures else 0)
