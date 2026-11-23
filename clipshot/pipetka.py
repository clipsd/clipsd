# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Пипетка цвета (1.36): наведение показывает увеличенные пиксели и цвет, щелчок копирует код цвета.

Здесь только то, что не зависит от окна редактора: какой цвет у точки, как он записывается (HEX и RGB) и как рисуется
лупа. Инструмент в холсте (Canvas) и подсказка «Рисовать этим цветом» (PenHint) в editor.py. Цвет берётся с того, что
видно на холсте: снимок вместе с пометками (flat), а не с одного снимка под ними."""

from PyQt6.QtCore import QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen

GRID = 11             # клеток в лупе по стороне (нечётное: в середине та точка, на которую навели)
CELL = 11             # px одной клетки на экране
LOUPE = GRID * CELL
INFO_H = 40


def hex_of(color) -> str:
    return QColor(color).name().upper()


def rgb_of(color) -> str:
    c = QColor(color)
    return f"rgb({c.red()}, {c.green()}, {c.blue()})"


def pixel_at(image: QImage, x: float, y: float):
    """Цвет точки по координатам в точках снимка (с учётом масштаба экрана у картинки) или None за краем."""
    if image is None or image.isNull():
        return None
    dpr = image.devicePixelRatio() or 1.0
    ix, iy = int(x * dpr), int(y * dpr)
    if not (0 <= ix < image.width() and 0 <= iy < image.height()):
        return None
    c = image.pixelColor(ix, iy)
    if c.alpha() < 255:   # прозрачное место (форма снимка): цвет как на белом поле
        bg = QColor("#ffffff")
        a = c.alphaF()
        c = QColor(round(c.red() * a + bg.red() * (1 - a)), round(c.green() * a + bg.green() * (1 - a)),
                   round(c.blue() * a + bg.blue() * (1 - a)))
    return c


def grid_colors(image: QImage, x: float, y: float, n: int = GRID) -> list:
    """Цвета клеток n x n вокруг точки (x, y): [[QColor или None]], середина это сама точка."""
    dpr = image.devicePixelRatio() or 1.0 if image is not None and not image.isNull() else 1.0
    half = n // 2
    out = []
    for j in range(-half, half + 1):
        row = []
        for i in range(-half, half + 1):
            row.append(pixel_at(image, x + i / dpr, y + j / dpr))
        out.append(row)
    return out


def paint_loupe(p: QPainter, image: QImage, x: float, y: float, widget_pos: QPointF, bounds: QRect, dark: bool = False):
    """Лупа у курсора: увеличенные точки, рамка у средней, под ней HEX и RGB. widget_pos: куда навели (точки окна),
    bounds: где лупа может лежать (видимая часть холста). Рисуется в окне без масштаба вида."""
    color = pixel_at(image, x, y)
    if color is None:
        return
    box_w, box_h = LOUPE + 2, LOUPE + INFO_H + 2
    left = int(widget_pos.x()) + 22
    top = int(widget_pos.y()) + 22
    if left + box_w > bounds.right():
        left = int(widget_pos.x()) - 22 - box_w
    if top + box_h > bounds.bottom():
        top = int(widget_pos.y()) - 22 - box_h
    left = max(bounds.left(), min(left, bounds.right() - box_w))
    top = max(bounds.top(), min(top, bounds.bottom() - box_h))
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#1d2023" if dark else "#ffffff"))
    p.drawRect(QRect(left, top, box_w, box_h))
    cells = grid_colors(image, x, y)
    for j, row in enumerate(cells):
        for i, c in enumerate(row):
            r = QRect(left + 1 + i * CELL, top + 1 + j * CELL, CELL, CELL)
            if c is None:
                p.fillRect(r, QColor("#8a8f98" if (i + j) % 2 else "#b4bcc8"))
            else:
                p.fillRect(r, c)
    mid = GRID // 2
    p.setBrush(Qt.BrushStyle.NoBrush)
    mr = QRect(left + 1 + mid * CELL, top + 1 + mid * CELL, CELL, CELL)
    p.setPen(QPen(QColor("#000000"), 1))
    p.drawRect(mr.adjusted(-1, -1, 0, 0))
    p.setPen(QPen(QColor("#ffffff"), 1))
    p.drawRect(mr.adjusted(0, 0, -1, -1))
    p.setPen(QPen(QColor("#6b7178" if dark else "#8a8f98"), 1))
    p.drawRect(QRect(left, top, box_w - 1, box_h - 1))
    # строка цвета: образец, HEX и RGB
    info = QRect(left + 1, top + 1 + LOUPE, LOUPE, INFO_H)
    sw = QRect(info.left() + 6, info.top() + 9, 22, 22)
    p.setPen(QPen(QColor("#6b7178" if dark else "#8a8f98"), 1))
    p.setBrush(color)
    p.drawRect(sw)
    font = QFont()
    font.setPixelSize(13)
    font.setBold(True)
    p.setFont(font)
    p.setPen(QColor("#f1f3f5" if dark else "#16181c"))
    p.drawText(QRect(sw.right() + 8, info.top() + 3, info.width() - 40, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
               hex_of(color))
    font.setBold(False)
    font.setPixelSize(11)
    p.setFont(font)
    p.setPen(QColor("#aab1ba" if dark else "#4b5563"))
    p.drawText(QRect(sw.right() + 8, info.top() + 21, info.width() - 40, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
               rgb_of(color))
    p.restore()
