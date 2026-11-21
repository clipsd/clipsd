# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Иконки редактора, нарисованные кодом: не зависят от темы значков системы."""

import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

SIZE = 24      # логический размер значка
SCALE = 3      # запас пикселей для HiDPI


def _canvas():
    pix = QPixmap(SIZE * SCALE, SIZE * SCALE)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(SCALE, SCALE)
    return pix, p


def _pen(color, width=2.0):
    pen = QPen(QColor(color), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _arrow_head(p, tip: QPointF, angle: float, length: float, color):
    spread = math.pi / 6
    left = tip - QPointF(math.cos(angle - spread) * length, math.sin(angle - spread) * length)
    right = tip - QPointF(math.cos(angle + spread) * length, math.sin(angle + spread) * length)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawPolygon(QPolygonF([tip, left, right]))


def _draw(name: str, p: QPainter, c: str):
    if name == "move":
        p.setPen(_pen(c, 1.8))
        p.drawLine(QPointF(12, 4), QPointF(12, 20))
        p.drawLine(QPointF(4, 12), QPointF(20, 12))
        for tip, ang in ((QPointF(12, 2.5), -math.pi / 2), (QPointF(12, 21.5), math.pi / 2),
                         (QPointF(2.5, 12), math.pi), (QPointF(21.5, 12), 0.0)):
            _arrow_head(p, tip, ang, 5, c)
    elif name == "text":
        font = QFont("Sans")
        font.setPixelSize(20)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor(c))
        p.drawText(QRectF(0, 0, SIZE, SIZE), Qt.AlignmentFlag.AlignCenter, "T")
    elif name == "number":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#d60808"))
        p.drawEllipse(QPointF(12, 12), 9.5, 9.5)
        font = QFont("Sans")
        font.setPixelSize(13)
        font.setBold(True)
        p.setFont(font)
        p.setPen(Qt.GlobalColor.white)
        p.drawText(QRectF(0, 0, SIZE, SIZE), Qt.AlignmentFlag.AlignCenter, "1")
    elif name == "arrow":
        p.setPen(_pen(c, 2.4))
        p.drawLine(QPointF(4, 20), QPointF(16.5, 7.5))
        _arrow_head(p, QPointF(20.5, 3.5), -math.pi / 4, 9, c)
    elif name == "darrow":
        p.setPen(_pen(c, 2.4))
        p.drawLine(QPointF(7.5, 16.5), QPointF(16.5, 7.5))
        _arrow_head(p, QPointF(20.5, 3.5), -math.pi / 4, 8, c)
        _arrow_head(p, QPointF(3.5, 20.5), math.pi * 3 / 4, 8, c)
    elif name == "farrow":
        p.setPen(_pen(c, 2.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath(QPointF(3, 19))
        path.cubicTo(QPointF(6, 8), QPointF(12, 22), QPointF(15, 10))
        p.drawPath(path)
        _arrow_head(p, QPointF(18, 3), -math.pi * 0.38, 8, c)
    elif name == "fline":
        p.setPen(_pen(c, 2.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath(QPointF(3, 17))
        path.cubicTo(QPointF(7, 3), QPointF(12, 22), QPointF(16, 9))
        path.cubicTo(QPointF(18, 4), QPointF(20, 6), QPointF(21, 8))
        p.drawPath(path)
    elif name == "fshape":
        p.setPen(_pen(c, 2.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        pts = [QPointF(x, y) for x, y in ((3, 9), (9, 2.5), (13, 8), (21, 4), (20.5, 14), (13, 21), (9, 15),
                                           (3, 19))]
        mids = [(pts[i] + pts[(i + 1) % len(pts)]) / 2 for i in range(len(pts))]
        path = QPainterPath(mids[-1])
        for pt, mid in zip(pts, mids):
            path.quadTo(pt, mid)
        p.drawPath(path)
    elif name == "callout":
        p.setPen(_pen(c, 1.6))
        p.setBrush(QColor("#ffffff"))
        p.drawRoundedRect(QRectF(7, 2.5, 15, 11), 3, 3)
        p.drawLine(QPointF(9, 13.5), QPointF(3.5, 20.5))
        p.setBrush(QColor(c))
        p.drawEllipse(QPointF(3.5, 20.5), 1.8, 1.8)
        p.setPen(_pen(c, 1.4))
        p.drawLine(QPointF(10, 6.5), QPointF(19, 6.5))
        p.drawLine(QPointF(10, 9.5), QPointF(16, 9.5))
    elif name == "line":
        p.setPen(_pen(c, 2.4))
        p.drawLine(QPointF(4, 20), QPointF(20, 4))
    elif name == "rect":
        p.setPen(_pen(c, 2.2))
        p.drawRect(QRectF(3.5, 6, 17, 12))
    elif name == "ellipse":
        p.setPen(_pen(c, 2.2))
        p.drawEllipse(QRectF(3, 5.5, 18, 13))
    elif name == "marker":
        pen = QPen(QColor(245, 196, 0, 170), 7)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        p.setPen(pen)
        p.drawLine(QPointF(3, 17), QPointF(21, 17))
        p.save()
        p.translate(14, 10)
        p.rotate(45)
        p.setPen(_pen(c, 1.4))
        p.setBrush(QColor("#ffffff"))
        p.drawRect(QRectF(-2.5, -9, 5, 12))
        p.setBrush(QColor(c))
        p.drawPolygon(QPolygonF([QPointF(-2.5, 3), QPointF(2.5, 3), QPointF(1, 6), QPointF(-1, 6)]))
        p.restore()
    elif name == "pencil":
        p.save()
        p.translate(12, 12)
        p.rotate(45)
        p.setPen(_pen(c, 1.4))
        p.setBrush(QColor("#ffcf4d"))
        p.drawRect(QRectF(-3, -10, 6, 14))
        p.setBrush(QColor("#f3d9b1"))
        p.drawPolygon(QPolygonF([QPointF(-3, 4), QPointF(3, 4), QPointF(0, 10)]))
        p.restore()
    elif name == "blur":
        p.setPen(Qt.PenStyle.NoPen)
        shades = ["#5a5a5a", "#a0a0a0", "#7c7c7c", "#c4c4c4", "#6a6a6a", "#b0b0b0", "#8a8a8a", "#d2d2d2", "#707070"]
        for i in range(3):
            for j in range(3):
                p.setBrush(QColor(shades[i * 3 + j]))
                p.drawRect(QRectF(3 + j * 6, 3 + i * 6, 6, 6))
    elif name == "translate":
        # «A» и «Я» со стрелкой: перевод (QFont уже подключён в модуле: свой импорт сломал бы другие значки)
        f = QFont()
        f.setBold(True)
        f.setPixelSize(11)
        p.setFont(f)
        p.setPen(QColor(c))
        p.drawText(QRectF(0, 0, 13, 13), Qt.AlignmentFlag.AlignCenter, "A")
        p.drawText(QRectF(11, 11, 13, 13), Qt.AlignmentFlag.AlignCenter, "Я")
        p.setPen(_pen(c, 1.6))
        p.drawLine(QPointF(14, 5), QPointF(19, 5))
        p.drawLine(QPointF(19, 5), QPointF(19, 9))
        p.drawLine(QPointF(5, 15), QPointF(5, 19))
        p.drawLine(QPointF(5, 19), QPointF(10, 19))
    elif name == "translate_all":
        # «A» и «Я» со стрелкой в рамке-видоискателе по углам: перевод всего экрана
        p.setPen(_pen(c, 1.8))
        for x, y, dx, dy in ((2.5, 2.5, 1, 1), (21.5, 2.5, -1, 1), (2.5, 21.5, 1, -1), (21.5, 21.5, -1, -1)):
            p.drawPolyline(QPolygonF([QPointF(x, y + 5 * dy), QPointF(x, y), QPointF(x + 5 * dx, y)]))
        p.save()
        p.translate(5.5, 5.5)
        p.scale(0.58, 0.58)
        _draw("translate", p, c)
        p.restore()
    elif name == "translate_pick":
        # рамка-видоискатель с плюсом и буквами перевода: выделить другое место и перевести
        p.setPen(_pen(c, 1.8))
        for x, y, dx, dy in ((2, 2, 1, 1), (22, 2, -1, 1), (2, 22, 1, -1)):
            p.drawPolyline(QPolygonF([QPointF(x, y + 4 * dy), QPointF(x, y), QPointF(x + 4 * dx, y)]))
        p.save()
        p.translate(4.2, 4.2)
        p.scale(0.7, 0.7)
        _draw("translate", p, c)
        p.restore()
        p.setPen(_pen(c, 2.2))
        p.drawLine(QPointF(17, 21), QPointF(23, 21))
        p.drawLine(QPointF(20, 18), QPointF(20, 24))
    elif name == "ocr":
        # рамка-видоискатель по углам и буква «Т» внутри: текст с картинки
        p.setPen(_pen(c, 2.0))
        for x, y, dx, dy in ((3, 3, 1, 1), (21, 3, -1, 1), (3, 21, 1, -1), (21, 21, -1, -1)):
            p.drawPolyline(QPolygonF([QPointF(x, y + 5 * dy), QPointF(x, y), QPointF(x + 5 * dx, y)]))
        p.setPen(_pen(c, 2.4))
        p.drawLine(QPointF(8, 8), QPointF(16, 8))
        p.drawLine(QPointF(12, 8), QPointF(12, 17))
    elif name == "crop":
        p.setPen(_pen(c, 2.2))
        p.drawPolyline(QPolygonF([QPointF(7, 2), QPointF(7, 17), QPointF(22, 17)]))
        p.drawPolyline(QPolygonF([QPointF(2, 7), QPointF(17, 7), QPointF(17, 22)]))
    elif name in ("undo", "redo"):
        if name == "redo":
            p.translate(SIZE, 0)
            p.scale(-1, 1)
        p.setPen(_pen(c, 2.2))
        path = QPainterPath(QPointF(7, 9))
        path.cubicTo(QPointF(17, 9), QPointF(21, 13), QPointF(19, 18))
        p.drawPath(path)
        _arrow_head(p, QPointF(3, 9), math.pi, 7, c)
    elif name == "copy":
        p.setPen(_pen(c, 1.8))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(3, 3, 12, 14), 2, 2)
        p.setBrush(QColor(c).darker(110) if c != "#ffffff" else QColor("#1e78ff"))
        p.drawRoundedRect(QRectF(9, 7, 12, 14), 2, 2)
    elif name == "eraser":
        p.save()
        p.translate(12, 12)
        p.rotate(-40)
        p.setPen(_pen(c, 1.4))
        p.setBrush(QColor("#f28ba0"))
        p.drawRoundedRect(QRectF(-9, -5, 11, 10), 2, 2)
        p.setBrush(QColor("#ffffff"))
        p.drawRoundedRect(QRectF(2, -5, 7, 10), 2, 2)
        p.restore()
        p.setPen(_pen(c, 1.4))
        p.drawLine(QPointF(9, 21), QPointF(21, 21))
    elif name == "insert":
        p.setPen(_pen(c, 1.6))
        p.setBrush(QColor("#ffffff"))
        p.drawRoundedRect(QRectF(2.5, 5, 15, 12), 2, 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#2db400"))
        p.drawPolygon(QPolygonF([QPointF(4, 15.5), QPointF(9, 9.5), QPointF(13, 15.5)]))
        p.setBrush(QColor("#ffb300"))
        p.drawEllipse(QPointF(13.5, 8.5), 1.8, 1.8)
        p.setBrush(QColor("#1e78ff"))
        p.drawEllipse(QPointF(18, 17), 5.2, 5.2)
        p.setPen(_pen("#ffffff", 1.8))
        p.drawLine(QPointF(18, 14.2), QPointF(18, 19.8))
        p.drawLine(QPointF(15.2, 17), QPointF(20.8, 17))
    elif name == "help":
        p.setPen(_pen(c, 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(12, 12), 9.5, 9.5)
        font = QFont("Sans")
        font.setPixelSize(14)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor(c))
        p.drawText(QRectF(0, 0, SIZE, SIZE), Qt.AlignmentFlag.AlignCenter, "?")
    elif name == "update":   # обновления: круговая стрелка
        p.setPen(_pen(c, 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(4, 4, 16, 16), 40 * 16, 270 * 16)
        _arrow_head(p, QPointF(18.6, 6.2), math.radians(40), 5, c)
    elif name == "info":   # о программе: «i» в круге
        p.setPen(_pen(c, 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(12, 12), 9.5, 9.5)
        p.drawLine(QPointF(12, 11), QPointF(12, 17))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(c))
        p.drawEllipse(QPointF(12, 7.4), 1.3, 1.3)
    elif name == "globe":   # выбор языка (1.31): узнаётся без чтения подписи
        p.setPen(_pen(c, GLOBE_LINE))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(12, 12), 9.5, 9.5)
        p.drawEllipse(QRectF(7.6, 2.5, 8.8, 19))
        p.drawLine(QPointF(2.5, 12), QPointF(21.5, 12))
        p.drawLine(QPointF(12, 2.5), QPointF(12, 21.5))
        p.drawLine(QPointF(4.2, 7.2), QPointF(19.8, 7.2))
        p.drawLine(QPointF(4.2, 16.8), QPointF(19.8, 16.8))
    elif name == "record":
        p.setPen(_pen(c, 1.8))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(2.5, 6, 13, 12), 2.5, 2.5)
        p.setBrush(QColor(c))
        p.drawPolygon(QPolygonF([QPointF(16.5, 10), QPointF(21.5, 7), QPointF(21.5, 17), QPointF(16.5, 14)]))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#e01b24"))
        p.drawEllipse(QPointF(9, 12), 2.6, 2.6)
    elif name == "region":
        pen = _pen(c, 1.8)
        pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(3, 4, 14, 11))
        p.setPen(_pen(c, 1.8))
        p.drawLine(QPointF(18, 13), QPointF(18, 22))
        p.drawLine(QPointF(13.5, 17.5), QPointF(22.5, 17.5))
    elif name == "window":
        # Окно программы с полосой заголовка и уголками выделения вокруг: снимок одного окна (прототип dev/vybor-okna)
        p.setPen(_pen(c, 1.8))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(5, 6.5, 14, 11), 1.8, 1.8)
        p.drawLine(QPointF(5, 9.8), QPointF(19, 9.8))
        p.setPen(_pen(c, 1.6))
        for x, y, dx, dy in ((2, 3, 1, 1), (22, 3, -1, 1), (2, 21, 1, -1), (22, 21, -1, -1)):
            p.drawLine(QPointF(x, y), QPointF(x + 3.5 * dx, y))
            p.drawLine(QPointF(x, y), QPointF(x, y + 3.5 * dy))
    elif name == "fullscreen":
        # Монитор с уголками по краям: снимок всего экрана
        p.setPen(_pen(c, 1.8))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(2.5, 4, 19, 13), 1.5, 1.5)
        p.drawLine(QPointF(9, 21), QPointF(15, 21))
        p.drawLine(QPointF(12, 17), QPointF(12, 21))
        pen = _pen(c, 1.6)
        p.setPen(pen)
        for x, y, dx, dy in ((6, 7, 1, 1), (18, 7, -1, 1), (6, 14, 1, -1), (18, 14, -1, -1)):
            p.drawLine(QPointF(x, y), QPointF(x + 3 * dx, y))
            p.drawLine(QPointF(x, y), QPointF(x, y + 2.5 * dy))
    elif name == "settings":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(c))
        center = QPointF(12, 12)
        for k in range(8):   # зубцы шестерёнки
            p.save()
            p.translate(center)
            p.rotate(k * 45)
            p.drawRoundedRect(QRectF(-2.2, -10.5, 4.4, 5), 1, 1)
            p.restore()
        p.drawEllipse(center, 7.5, 7.5)
        p.setBrush(QColor("#ffffff") if c != "#ffffff" else QColor("#1e78ff"))
        p.drawEllipse(center, 3.2, 3.2)
    elif name == "more":   # «⋯ Все инструменты» (1.32): три точки
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(c))
        for x in (5, 12, 19):
            p.drawEllipse(QPointF(x, 12), 2.1, 2.1)
    elif name == "fit":   # «Вписать» значком (1.32, узкое окно): уголки рамки и стрелка по диагонали в обе стороны
        p.setPen(_pen(c, 1.8))
        for x, y, dx, dy in ((3, 3, 1, 1), (21, 3, -1, 1), (3, 21, 1, -1), (21, 21, -1, -1)):
            p.drawPolyline(QPolygonF([QPointF(x, y + 4.5 * dy), QPointF(x, y), QPointF(x + 4.5 * dx, y)]))
        p.drawLine(QPointF(9.5, 14.5), QPointF(14.5, 9.5))
        _arrow_head(p, QPointF(16.8, 7.2), -math.pi / 4, 5, c)
        _arrow_head(p, QPointF(7.2, 16.8), math.pi * 3 / 4, 5, c)
    elif name == "bell":   # колокольчик уведомлений (1.32)
        p.setPen(_pen(c, 1.8))
        p.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath(QPointF(5.5, 16.5))
        path.lineTo(5.5, 11)
        path.cubicTo(QPointF(5.5, 6.6), QPointF(8.4, 4), QPointF(12, 4))
        path.cubicTo(QPointF(15.6, 4), QPointF(18.5, 6.6), QPointF(18.5, 11))
        path.lineTo(18.5, 16.5)
        path.lineTo(20, 18.5)
        path.lineTo(4, 18.5)
        path.closeSubpath()
        p.drawPath(path)
        p.drawArc(QRectF(9.6, 18.6, 4.8, 4.2), 180 * 16, 180 * 16)
    elif name == "save":
        p.setPen(_pen(c, 1.8))
        p.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath(QPointF(4, 3))
        for x, y in ((17, 3), (21, 7), (21, 21), (4, 21)):
            path.lineTo(x, y)
        path.closeSubpath()
        p.drawPath(path)
        p.drawRect(QRectF(8, 3, 8, 5))
        p.drawRect(QRectF(7, 13, 11, 8))


ICON_COLOR = "#2e3436"   # цвет линий значков; оформление меняет его (светлый на тёмной теме)


GLOBE_COLOR = "#3a9be8"   # глобус выбора языка: один голубой во всех окнах и темах (themes.GLOBE)
GLOBE_LINE = 2.0          # 1.32: линии глобуса толще (было 1.7): лучше читается


def icon(name: str, color: str = None) -> QIcon:
    color = color or (GLOBE_COLOR if name == "globe" else ICON_COLOR)
    pix, p = _canvas()
    _draw(name, p, color)
    p.end()
    pix.setDevicePixelRatio(SCALE)
    return QIcon(pix)


def size_icon(level: int, color: str = None) -> QIcon:
    color = color or ICON_COLOR
    """Значок толщины: линия, толщина растёт с номером размера."""
    pix, p = _canvas()
    p.setPen(_pen(color, (1.5, 2.5, 4, 6, 8.5)[level - 1]))
    p.drawLine(QPointF(5, 12), QPointF(19, 12))
    p.end()
    pix.setDevicePixelRatio(SCALE)
    return QIcon(pix)


def _draw_logo(p: QPainter, size: int):
    """Логотип ClipSD: синий скруглённый квадрат, уголки рамки выделения, «SD» (и «Clip» на больших)."""
    from PyQt6.QtGui import QLinearGradient
    s = float(size)
    grad = QLinearGradient(0, 0, 0, s)
    grad.setColorAt(0, QColor("#3d8bff"))
    grad.setColorAt(1, QColor("#0a4fc4"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(grad)
    m = s * 0.04
    p.drawRoundedRect(QRectF(m, m, s - 2 * m, s - 2 * m), s * 0.22, s * 0.22)
    # Уголки рамки выделения (на мелких значках не рисуем: мешают буквам).
    pen = QPen(QColor("#ffffff"), max(1.5, s * 0.07))
    pen.setCapStyle(Qt.PenCapStyle.SquareCap)
    pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    p.setPen(pen)
    a, b, arm = s * 0.2, s * 0.8, s * 0.16
    for x, y, dx, dy in ((a, a, 1, 1), (b, a, -1, 1), (a, b, 1, -1), (b, b, -1, -1)) if size >= 28 else ():
        p.drawPolyline(QPolygonF([QPointF(x + arm * dx, y), QPointF(x, y), QPointF(x, y + arm * dy)]))
    font = QFont("Sans")
    font.setBold(True)
    p.setPen(QColor("#ffffff"))
    if size >= 40:
        font.setPixelSize(int(s * 0.17))
        p.setFont(font)
        p.drawText(QRectF(0, s * 0.27, s, s * 0.2), Qt.AlignmentFlag.AlignCenter, "Clip")
        font.setPixelSize(int(s * 0.33))
        p.setFont(font)
        p.drawText(QRectF(0, s * 0.42, s, s * 0.36), Qt.AlignmentFlag.AlignCenter, "SD")
    else:
        font.setPixelSize(int(s * 0.42))
        p.setFont(font)
        p.drawText(QRectF(0, 0, s, s), Qt.AlignmentFlag.AlignCenter, "SD")


def logo_pixmap(size: int) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    _draw_logo(p, size)
    p.end()
    return pix


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 22, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(logo_pixmap(size))
    return icon


# --- флаги языков (1.32): 24x16 со скруглением, как на сайте clipsd.github.io; рисуются кодом, без внешних файлов ---

FLAG_W, FLAG_H, FLAG_R = 24, 16, 3


def _star(cx, cy, r, rot=-90):
    pts = []
    for i in range(10):
        ang = math.radians(rot + i * 36)
        rr = r if i % 2 == 0 else r * 0.382
        pts.append(QPointF(cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
    return QPolygonF(pts)


def _flag_paint(p: QPainter, code: str):
    """Флаг в прямоугольнике 24x16 (координаты как в SVG сайта)."""
    def rect(x, y, w, h, color):
        p.fillRect(QRectF(x, y, w, h), QColor(color))

    def stripes_h(a, b, c):
        for i, color in enumerate((a, b, c)):
            rect(0, i * FLAG_H / 3, FLAG_W, FLAG_H / 3 + 0.01, color)

    def stripes_v(a, b, c):
        for i, color in enumerate((a, b, c)):
            rect(i * 8, 0, 8.01, FLAG_H, color)

    if code == "en":
        rect(0, 0, 24, 16, "#1d3f94")
        for color, width in (("#ffffff", 3.2), ("#c8102e", 1.1)):
            p.setPen(QPen(QColor(color), width))
            p.drawLine(QPointF(0, 0), QPointF(24, 16))
            p.drawLine(QPointF(24, 0), QPointF(0, 16))
        for color, width in (("#ffffff", 5), ("#c8102e", 3)):
            p.setPen(QPen(QColor(color), width))
            p.drawLine(QPointF(12, 0), QPointF(12, 16))
            p.drawLine(QPointF(0, 8), QPointF(24, 8))
    elif code == "ru":
        stripes_h("#ffffff", "#1c57a5", "#d52b1e")
    elif code == "uk":
        rect(0, 0, 24, 8, "#0057b8")
        rect(0, 8, 24, 8, "#ffd700")
    elif code == "bg":
        stripes_h("#ffffff", "#00966e", "#d62612")
    elif code == "de":
        stripes_h("#111111", "#dd0000", "#ffce00")
    elif code == "fr":
        stripes_v("#0055a4", "#ffffff", "#ef4135")
    elif code == "es":
        rect(0, 0, 24, 16, "#aa151b")
        rect(0, 4, 24, 8, "#f1bf00")
    elif code == "it":
        stripes_v("#009246", "#ffffff", "#ce2b37")
    elif code == "pt":
        rect(0, 0, 24, 16, "#ff0000")
        rect(0, 0, 9.6, 16, "#006600")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ffcc00"))
        p.drawEllipse(QPointF(9.6, 8), 3, 3)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QPointF(9.6, 8), 1.7, 1.7)
    elif code == "pl":
        rect(0, 0, 24, 8, "#ffffff")
        rect(0, 8, 24, 8, "#dc143c")
    elif code == "tr":
        rect(0, 0, 24, 16, "#e30a17")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QPointF(9, 8), 4, 4)
        p.setBrush(QColor("#e30a17"))
        p.drawEllipse(QPointF(10.2, 8), 3.2, 3.2)
        p.setBrush(QColor("#ffffff"))
        p.drawPolygon(_star(13.6, 8, 2.1))
    elif code == "zh":
        rect(0, 0, 24, 16, "#de2910")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ffde00"))
        for cx, cy, r, rot in ((5, 5, 3, -90), (10, 2.2, 1, -70), (12, 4.4, 1, -50), (12, 7.2, 1, -10), (10, 9.4, 1, -35)):
            p.drawPolygon(_star(cx, cy, r, rot))
    # 1.32: языки перевода, которых нет среди языков интерфейса (меню «На: … ▾», «Переводить на», «Запасной язык»)
    elif code == "el":   # Греция: 9 полос и крест в углу
        h = FLAG_H / 9
        for i in range(9):
            rect(0, i * h, FLAG_W, h + 0.01, "#0d5eaf" if i % 2 == 0 else "#ffffff")
        rect(0, 0, 5 * h, 5 * h, "#0d5eaf")
        rect(0, 2 * h, 5 * h, h, "#ffffff")
        rect(2 * h, 0, h, 5 * h, "#ffffff")
    elif code == "ro":
        stripes_v("#002b7f", "#fcd116", "#ce1126")
    elif code == "sr":   # Сербия: триколор без герба (на 24x16 он не читается)
        stripes_h("#c6363c", "#0c4076", "#ffffff")
    elif code == "nl":
        stripes_h("#ae1c28", "#ffffff", "#21468b")
    elif code == "cs":   # Чехия: белое и красное поле, синий клин до середины
        rect(0, 0, 24, 8, "#ffffff")
        rect(0, 8, 24, 8, "#d7141a")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#11457e"))
        p.drawPolygon(QPolygonF([QPointF(0, 0), QPointF(12, 8), QPointF(0, 16)]))
    elif code == "ja":
        rect(0, 0, 24, 16, "#ffffff")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#bc002d"))
        p.drawEllipse(QPointF(12, 8), 4.8, 4.8)
    elif code == "ko":   # Корея: тхэгык и четыре триграммы, упрощённо
        rect(0, 0, 24, 16, "#ffffff")
        p.setPen(Qt.PenStyle.NoPen)
        p.save()
        p.translate(12, 8)
        p.rotate(33.7)
        p.setBrush(QColor("#cd2e3a"))
        p.drawPie(QRectF(-4, -4, 8, 8), 0, 180 * 16)
        p.setBrush(QColor("#0047a0"))
        p.drawPie(QRectF(-4, -4, 8, 8), 180 * 16, 180 * 16)
        p.setBrush(QColor("#cd2e3a"))
        p.drawEllipse(QPointF(-2, 0), 2, 2)
        p.setBrush(QColor("#0047a0"))
        p.drawEllipse(QPointF(2, 0), 2, 2)
        p.restore()
        p.setPen(QPen(QColor("#000000"), 0.7))
        for cx, cy, ang in ((4, 3.2, 33.7), (20, 3.2, -33.7), (4, 12.8, -33.7), (20, 12.8, 33.7)):
            p.save()
            p.translate(cx, cy)
            p.rotate(ang + 90)
            for k in (-1.1, 0, 1.1):
                p.drawLine(QPointF(-1.6, k), QPointF(1.6, k))
            p.restore()


FLAG_CODES = ("en", "ru", "uk", "bg", "de", "fr", "es", "it", "pt", "pl", "tr", "zh",
              "el", "ro", "sr", "nl", "cs", "ja", "ko")   # арабский (ar): глобус, у языка нет флага одной страны
_flag_cache = {}


def flag_icon(code: str) -> QIcon:
    """Флаг языка 24x16 со скруглением и тонкой рамкой; «Как в системе» (auto) и неизвестный код: глобус."""
    if code not in FLAG_CODES:
        return icon("globe")
    if code in _flag_cache:
        return _flag_cache[code]
    k = 4
    pix = QPixmap(FLAG_W * k, FLAG_H * k)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(k, k)
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0, 0, FLAG_W, FLAG_H), FLAG_R, FLAG_R)
    p.setClipPath(clip)
    _flag_paint(p, code)
    p.setClipping(False)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(40, 30, 20, 46), 1))
    p.drawRoundedRect(QRectF(0.5, 0.5, FLAG_W - 1, FLAG_H - 1), FLAG_R - 0.5, FLAG_R - 0.5)
    p.end()
    pix.setDevicePixelRatio(k)
    _flag_cache[code] = QIcon(pix)
    return _flag_cache[code]


def flag_pixmap(code: str, scale: float = 1.0) -> QPixmap:
    return flag_icon(code).pixmap(round(FLAG_W * scale), round(FLAG_H * scale))
