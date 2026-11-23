# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Объекты аннотаций редактора: стрелка, линия, фигуры, маркер, карандаш, текст, номер, размытие."""

import math

from PyQt6.QtCore import QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen, QPolygonF

ARROW, LINE, RECT, ELLIPSE, MARKER, PENCIL, TEXT, NUMBER, BLUR, CALLOUT = (
    "arrow", "line", "rect", "ellipse", "marker", "pencil", "text", "number", "blur", "callout")
DARROW, FARROW = "darrow", "farrow"   # стрелка в обе стороны; свободная (рисуется рукой) стрелка
FLINE, FSHAPE = "fline", "fshape"     # плавная линия от руки; свободная замкнутая фигура
IMAGE = "image"                       # вставленная картинка (из буфера, файла или нового снимка)
STICKER = "sticker"                   # 1.36: эмодзи, плашка с текстом или номер в кружке (clipshot/stickers.py)

FREEHAND_KINDS = {MARKER, PENCIL, FARROW, FLINE, FSHAPE}
SMOOTHED_KINDS = {FARROW, FLINE, FSHAPE}   # после отпускания мыши спрямляется дрожание руки
LINE_KINDS = {ARROW, DARROW, LINE}    # ручки на концах
BOX_KINDS = {RECT, ELLIPSE, BLUR, IMAGE}   # ручки по углам
CALLOUT_PAD = 8                       # поля текста внутри выносного блока
ROTATE_GAP = 26                       # ручка поворота стикера: на столько выше верхней стороны

PEN_WIDTHS = {1: 2, 2: 3, 3: 5, 4: 8, 5: 12}
FONT_SIZES = {1: 14, 2: 18, 3: 24, 4: 32, 5: 44}
NUMBER_RADII = {1: 11, 2: 14, 3: 18, 4: 23, 5: 30}
NUMBER_HANDLE_GAP = 8   # ручка нетянутого номера стоит на столько дальше края кружка, чтобы не касаться цифры
SOLID_COVER = "#45494f"   # 1.36: нейтральный тёмно-серый: виден и на светлом, и на тёмном фоне
PIXELATE_BLOCK = 10


def constrain(origin: QPointF, point: QPointF, mode: str) -> QPointF:
    """Shift: 'angle' — шаг 45°, 'square' — квадрат/круг."""
    d = point - origin
    if mode == "angle":
        length = math.hypot(d.x(), d.y())
        step = math.pi / 4
        angle = round(math.atan2(d.y(), d.x()) / step) * step
        return origin + QPointF(math.cos(angle) * length, math.sin(angle) * length)
    if mode == "square":
        side = max(abs(d.x()), abs(d.y()))
        return origin + QPointF(math.copysign(side, d.x() or 1), math.copysign(side, d.y() or 1))
    return point


def _segment_distance(p: QPointF, a: QPointF, b: QPointF) -> float:
    d = b - a
    length2 = d.x() ** 2 + d.y() ** 2
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, QPointF.dotProduct(p - a, d) / length2))
    nearest = a + d * t
    return math.hypot(p.x() - nearest.x(), p.y() - nearest.y())


def simplify(points, epsilon=3.5):
    """Спрямить дрожание руки (алгоритм Дугласа — Пекера): лишние точки убираются, изгибы остаются."""
    if len(points) < 3:
        return list(points)
    first, last = points[0], points[-1]
    index, worst = 0, 0.0
    for i in range(1, len(points) - 1):
        d = _segment_distance(points[i], first, last)
        if d > worst:
            index, worst = i, d
    if worst <= epsilon:
        return [first, last]
    return simplify(points[:index + 1], epsilon)[:-1] + simplify(points[index:], epsilon)


def smooth_path(points) -> QPainterPath:
    """Плавная кривая через точки: отрезки скругляются квадратичными сплайнами по серединам."""
    path = QPainterPath(points[0])
    if len(points) < 3:
        for pt in points[1:]:
            path.lineTo(pt)
        return path
    for a, b in zip(points[1:-1], points[2:]):
        path.quadTo(a, (a + b) / 2)
    path.lineTo(points[-1])
    return path


def smooth_closed_path(points) -> QPainterPath:
    """Плавный замкнутый контур через точки (последняя соединяется с первой)."""
    if len(points) < 3:
        path = smooth_path(points)
        path.closeSubpath()
        return path
    n = len(points)
    mids = [(points[i] + points[(i + 1) % n]) / 2 for i in range(n)]
    path = QPainterPath(mids[-1])
    for i in range(n):
        path.quadTo(points[i], mids[i])
    path.closeSubpath()
    return path


def text_color_on(color: QColor) -> QColor:
    """Белый или чёрный текст — что читается лучше на фоне color."""
    return QColor("#000000") if color.lightnessF() > 0.62 else QColor("#ffffff")


def crisp(font: QFont) -> QFont:
    """Без цветной каймы у букв: она сохранялась бы и в картинку снимка."""
    font.setStyleStrategy(QFont.StyleStrategy.NoSubpixelAntialias | QFont.StyleStrategy.PreferAntialias)
    font.setHintingPreference(QFont.HintingPreference.PreferVerticalHinting)
    return font


def text_font(size: int) -> QFont:
    font = crisp(QFont())
    font.setPixelSize(FONT_SIZES[size])
    font.setBold(True)
    return font


class Shape:
    def __init__(self, kind, color, size, start: QPointF, filled=False):
        self.kind = kind
        self.color = QColor(color)
        self.size = size
        self.filled = filled
        self.points = [QPointF(start), QPointF(start)]
        self.text = ""
        self.number = 0
        self.text_color = None   # цвет цифры/текста сноски; None — авто (контраст к заливке)
        self.erasures = []       # стёртые ластиком куски: [(ширина кисти, [точки])]
        self.image = None        # QImage для вставленной картинки
        self.sticker = ""        # 1.36: код стикера (stickers.ALL); текст плашки лежит в text
        self.solid = False       # 1.36: «Скрыть личные данные»: сплошная заливка вместо пикселизации (подбором не вернуть)
        self.angle = 0.0         # 1.36: поворот стикера, градусы по часовой стрелке вокруг центра

    def copy(self):
        clone = Shape(self.kind, self.color, self.size, self.points[0], self.filled)
        clone.points = [QPointF(pt) for pt in self.points]
        clone.text = self.text
        clone.number = self.number
        clone.text_color = QColor(self.text_color) if self.text_color is not None else None
        clone.erasures = [(w, [QPointF(pt) for pt in pts]) for w, pts in self.erasures]
        clone.image = self.image   # картинка не меняется, можно делить между копиями
        clone.sticker = self.sticker
        clone.angle = self.angle
        clone.solid = self.solid
        return clone

    # --- геометрия ---------------------------------------------------------

    @property
    def pen_width(self):
        return PEN_WIDTHS[self.size]

    def rect(self) -> QRectF:
        return QRectF(self.points[0], self.points[-1]).normalized()

    def translate(self, delta: QPointF):
        self.points = [pt + delta for pt in self.points]
        self.erasures = [(w, [pt + delta for pt in pts]) for w, pts in self.erasures]

    def is_empty(self) -> bool:
        if self.kind == TEXT:
            return not self.text.strip()
        if self.kind in (NUMBER, IMAGE, STICKER):
            return False
        r = QPolygonF(self.points).boundingRect()
        return r.width() < 3 and r.height() < 3

    # --- стикер: прямоугольник points[0]..points[-1] без поворота, поворот вокруг его центра ---------------------

    def _to_world(self, local: QPointF) -> QPointF:
        """Точка стикера (в его неповёрнутой раме, от центра) -> точка снимка."""
        a = math.radians(self.angle)
        c = self.rect().center()
        return c + QPointF(local.x() * math.cos(a) - local.y() * math.sin(a),
                           local.x() * math.sin(a) + local.y() * math.cos(a))

    def _to_local(self, point: QPointF) -> QPointF:
        a = math.radians(-self.angle)
        d = point - self.rect().center()
        return QPointF(d.x() * math.cos(a) - d.y() * math.sin(a), d.x() * math.sin(a) + d.y() * math.cos(a))

    def sticker_corners(self) -> list:
        """Углы повёрнутого стикера на снимке: левый верхний, правый верхний, правый нижний, левый нижний."""
        r = self.rect()
        hw, hh = r.width() / 2, r.height() / 2
        return [self._to_world(QPointF(x, y)) for x, y in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh))]

    def rotate_handle(self) -> QPointF:
        return self._to_world(QPointF(0, -self.rect().height() / 2 - ROTATE_GAP))

    def set_size(self, size: int):
        """Кнопка толщины/размера 1-5: у стикера задаёт длинную сторону (пропорции и центр остаются)."""
        self.size = size
        if self.kind == STICKER:
            from . import stickers
            r = self.rect()
            side = float(stickers.SIZES.get(size, stickers.SIZES[3]))
            k = side / max(r.width(), r.height(), 1.0)
            c = r.center()
            hw, hh = r.width() * k / 2, r.height() * k / 2
            self.points = [QPointF(c.x() - hw, c.y() - hh), QPointF(c.x() + hw, c.y() + hh)]

    def bounding_rect(self) -> QRectF:
        if self.kind == IMAGE:
            return self.rect()
        if self.kind == STICKER:
            return QPolygonF(self.sticker_corners()).boundingRect().adjusted(-2, -2, 2, 2)
        if self.kind == TEXT:
            fm = QFontMetricsF(text_font(self.size))
            lines = self.text.split("\n")
            width = max(fm.horizontalAdvance(line) for line in lines)
            return QRectF(self.points[0], QRectF(0, 0, width, fm.lineSpacing() * len(lines)).size())
        if self.kind == CALLOUT:
            return self.callout_box().united(QRectF(self.points[0], self.points[0])).adjusted(-4, -4, 4, 4)
        if self.kind == NUMBER:
            r = NUMBER_RADII[self.size]
            circle = QRectF(self.points[0] - QPointF(r, r), QRectF(0, 0, 2 * r, 2 * r).size())
            return circle.united(QRectF(self.points[-1], self.points[-1]))
        margin = self.pen_width * (4 if self.kind == MARKER else 1) + (self.pen_width * 4 if self.kind == ARROW else 0)
        return QPolygonF(self.points).boundingRect().adjusted(-margin, -margin, margin, margin)

    def hit(self, point: QPointF) -> bool:
        tolerance = self.pen_width / 2 + 6
        if self.kind in LINE_KINDS:
            return _segment_distance(point, self.points[0], self.points[-1]) <= tolerance
        if self.kind in FREEHAND_KINDS:
            tolerance = self.pen_width * (2 if self.kind == MARKER else 0.5) + 6
            pts = self.points + ([self.points[0]] if self.kind == FSHAPE else [])
            if self.kind == FSHAPE and self.filled and smooth_closed_path(self.points).contains(point):
                return True
            return any(_segment_distance(point, a, b) <= tolerance for a, b in zip(pts, pts[1:]))
        if self.kind == IMAGE:
            return self.rect().contains(point)
        if self.kind == STICKER:
            return self.rect().translated(-self.rect().center()).adjusted(-3, -3, 3, 3).contains(self._to_local(point))
        if self.kind in (RECT, ELLIPSE) and not self.filled:
            r = self.rect()
            inner = r.adjusted(tolerance, tolerance, -tolerance, -tolerance)
            return r.adjusted(-tolerance, -tolerance, tolerance, tolerance).contains(point) and not (
                inner.isValid() and inner.contains(point))
        if self.kind == NUMBER:
            r = NUMBER_RADII[self.size]
            d = point - self.points[0]
            return (math.hypot(d.x(), d.y()) <= r + 4
                    or _segment_distance(point, self.points[0], self.points[-1]) <= tolerance)
        if self.kind == CALLOUT:
            return (self.callout_box().adjusted(-4, -4, 4, 4).contains(point)
                    or _segment_distance(point, self.points[0], self.callout_box().center()) <= tolerance)
        return self.bounding_rect().adjusted(-4, -4, 4, 4).contains(point)

    # --- ручки для правки выделенного объекта -----------------------------

    def handles(self):
        if self.kind in LINE_KINDS:
            return [self.points[0], self.points[-1]]
        if self.kind in BOX_KINDS:
            r = self.rect()
            return [r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft()]
        if self.kind == STICKER:
            return self.sticker_corners() + [self.rotate_handle()]   # четыре угла и ручка поворота над верхней стороной
        if self.kind == NUMBER:
            return [self.number_handle()]   # конец выносной линии
        if self.kind == CALLOUT:
            return [self.points[0]]    # точка, на которую указывает сноска
        return []

    def number_handle(self) -> QPointF:
        """Ручка номера. Пока указатель не вытянут (конец внутри кружка или у его края), ручка стоит снаружи
        кружка справа внизу, а не на центре: иначе квадратик закрывает цифру. Потянули указатель: ручка на его конце."""
        r = NUMBER_RADII[self.size]
        tail = self.points[-1]
        d = tail - self.points[0]
        if math.hypot(d.x(), d.y()) > r + NUMBER_HANDLE_GAP:
            return tail
        k = (r + NUMBER_HANDLE_GAP) * 0.7071
        return self.points[0] + QPointF(k, k)

    def drag_handle(self, index: int, pos: QPointF, shift=False):
        if self.kind in LINE_KINDS:
            fixed = self.points[-1] if index == 0 else self.points[0]
            pos = constrain(fixed, pos, "angle") if shift else pos
            self.points = [pos, fixed] if index == 0 else [fixed, pos]
        elif self.kind == IMAGE:
            corners = self.handles()
            fixed = corners[(index + 2) % 4]
            if not shift and self.image is not None and self.image.height() > 0:
                # Пропорции картинки сохраняются; Shift — растянуть свободно.
                ratio = self.image.width() / self.image.height()
                d = pos - fixed
                w = max(abs(d.x()), abs(d.y()) * ratio, 8.0)
                h = w / ratio
                pos = fixed + QPointF(math.copysign(w, d.x() or 1), math.copysign(h, d.y() or 1))
            self.points = [fixed, pos]
        elif self.kind == STICKER:
            self._drag_sticker(index, pos, shift)
        elif self.kind in BOX_KINDS:
            corners = self.handles()
            fixed = corners[(index + 2) % 4]
            self.points = [fixed, constrain(fixed, pos, "square") if shift else pos]
        elif self.kind == NUMBER:
            self.points[-1] = pos
        elif self.kind == CALLOUT:
            self.points[0] = pos

    def _drag_sticker(self, index: int, pos: QPointF, shift=False):
        r = self.rect()
        if index == 4:   # ручка поворота: стикер смотрит верхом на курсор; Shift: шаг 15 градусов
            d = pos - r.center()
            if math.hypot(d.x(), d.y()) < 1:
                return
            angle = math.degrees(math.atan2(d.y(), d.x())) + 90.0
            if shift:
                angle = round(angle / 15.0) * 15.0
            self.angle = ((angle + 180.0) % 360.0) - 180.0
            return
        # угол: масштаб с сохранением пропорций вокруг противоположного угла (считается в раме стикера)
        sx, sy = ((-1, -1), (1, -1), (1, 1), (-1, 1))[index]
        fixed_local = QPointF(-sx * r.width() / 2, -sy * r.height() / 2)
        d = self._to_local(pos) - fixed_local
        a = r.width() / max(r.height(), 1e-6)
        w = max(abs(d.x()), abs(d.y()) * a, 12.0 * max(1.0, a))
        h = w / a
        center_local = fixed_local + QPointF(sx * w / 2, sy * h / 2)
        center = self._to_world(center_local)
        self.points = [QPointF(center.x() - w / 2, center.y() - h / 2), QPointF(center.x() + w / 2, center.y() + h / 2)]

    # --- выносной текстовый блок --------------------------------------------

    def callout_box(self) -> QRectF:
        fm = QFontMetricsF(text_font(self.size))
        lines = (self.text or " ").split("\n")
        width = max(fm.horizontalAdvance(line) for line in lines)
        return QRectF(self.points[-1], QRectF(0, 0, width + 2 * CALLOUT_PAD,
                                              fm.lineSpacing() * len(lines) + 2 * CALLOUT_PAD).size())

    def _leader_start(self) -> QPointF:
        """Точка на краю блока, ближайшая к цели сноски."""
        box, target = self.callout_box(), self.points[0]
        return QPointF(min(max(target.x(), box.left()), box.right()), min(max(target.y(), box.top()), box.bottom()))

    # --- отрисовка ---------------------------------------------------------

    def paint(self, p: QPainter, base: QImage):
        if not self.erasures:
            p.save()
            getattr(self, "_paint_" + self.kind)(p, base)
            p.restore()
            return
        # Есть стёртые куски: рисуем объект на отдельном слое и вырезаем из него следы ластика.
        area = self.bounding_rect().adjusted(-8, -8, 8, 8).toAlignedRect()
        if area.isEmpty():
            return
        ratio = base.devicePixelRatio()
        layer = QImage(area.size() * ratio, QImage.Format.Format_ARGB32_Premultiplied)
        layer.setDevicePixelRatio(ratio)
        layer.fill(Qt.GlobalColor.transparent)
        lp = QPainter(layer)
        lp.setRenderHint(QPainter.RenderHint.Antialiasing)
        lp.translate(-QPointF(area.topLeft()))
        lp.save()
        getattr(self, "_paint_" + self.kind)(lp, base)
        lp.restore()
        lp.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        for width, pts in self.erasures:
            pen = QPen(Qt.GlobalColor.black, width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            lp.setPen(pen)
            if len(pts) == 1:
                lp.drawPoint(pts[0])
            else:
                lp.drawPolyline(QPolygonF(pts))
        lp.end()
        p.drawImage(area.topLeft(), layer)

    def _pen(self, width=None, color=None):
        pen = QPen(color or self.color, width or self.pen_width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return pen

    def _paint_line(self, p, _base):
        p.setPen(self._pen())
        p.drawLine(self.points[0], self.points[-1])

    def _head(self, p, tip: QPointF, angle: float, limit: float) -> QPointF:
        """Наконечник стрелки в точке tip; возвращает, где заканчивать древко."""
        head = min(max(14.0, self.pen_width * 4.0), limit)
        spread = math.pi / 7
        left = tip - QPointF(math.cos(angle - spread) * head, math.sin(angle - spread) * head)
        right = tip - QPointF(math.cos(angle + spread) * head, math.sin(angle + spread) * head)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.color)
        p.drawPolygon(QPolygonF([tip, left, right]))
        return tip - QPointF(math.cos(angle) * head * 0.7, math.sin(angle) * head * 0.7)

    def _paint_arrow(self, p, _base, both=False):
        start, tip = self.points[0], self.points[-1]
        d = tip - start
        length = math.hypot(d.x(), d.y())
        if length < 1:
            return
        angle = math.atan2(d.y(), d.x())
        shaft_end = self._head(p, tip, angle, length / (2 if both else 1))
        shaft_start = self._head(p, start, angle + math.pi, length / 2) if both else start
        p.setPen(self._pen())
        p.drawLine(shaft_start, shaft_end)

    def _paint_darrow(self, p, base):
        self._paint_arrow(p, base, both=True)

    def _paint_farrow(self, p, _base):
        pts = self.points
        if len(pts) < 2:
            return
        tip = pts[-1]
        # Направление наконечника — по последнему заметному участку пути.
        back = next((pt for pt in reversed(pts[:-1])
                     if math.hypot(tip.x() - pt.x(), tip.y() - pt.y()) >= 12), pts[0])
        d = tip - back
        if math.hypot(d.x(), d.y()) < 1:
            return
        self._head(p, tip, math.atan2(d.y(), d.x()), 1e9)
        p.setPen(self._pen())
        p.setBrush(Qt.BrushStyle.NoBrush)
        head = max(14.0, self.pen_width * 4.0) * 0.7
        trimmed = [pt for pt in pts[:-1] if math.hypot(tip.x() - pt.x(), tip.y() - pt.y()) > head] or [pts[0]]
        u = d / math.hypot(d.x(), d.y())
        p.drawPath(smooth_path(trimmed + [tip - u * head]))

    def _paint_rect(self, p, _base):
        pen = self._pen()
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        p.setPen(pen)
        p.setBrush(QBrush(self.color) if self.filled else Qt.BrushStyle.NoBrush)
        p.drawRect(self.rect())

    def _paint_ellipse(self, p, _base):
        p.setPen(self._pen())
        p.setBrush(QBrush(self.color) if self.filled else Qt.BrushStyle.NoBrush)
        p.drawEllipse(self.rect())

    def _paint_marker(self, p, _base):
        color = QColor(self.color)
        color.setAlpha(110)
        pen = self._pen(self.pen_width * 3 + 6, color)
        pen.setCapStyle(Qt.PenCapStyle.SquareCap)
        p.setPen(pen)
        p.drawPolyline(QPolygonF(self.points))

    def _paint_image(self, p, _base):
        if self.image is None:
            return
        r = self.rect()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(r, self.image)
        p.setPen(QPen(QColor(0, 0, 0, 90), 1))   # тонкая граница: вставка видна на снимке
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(r.adjusted(0.5, 0.5, -0.5, -0.5))

    def _paint_sticker(self, p, _base):
        from . import stickers
        r = self.rect()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.translate(r.center())
        p.rotate(self.angle)
        stickers.draw(p, self.sticker, QRectF(-r.width() / 2, -r.height() / 2, r.width(), r.height()),
                      self.color, self.text)

    def _paint_fline(self, p, _base):
        p.setPen(self._pen())
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(smooth_path(self.points))

    def _paint_fshape(self, p, _base):
        p.setPen(self._pen())
        p.setBrush(QBrush(self.color) if self.filled else Qt.BrushStyle.NoBrush)
        p.drawPath(smooth_closed_path(self.points))

    def _paint_pencil(self, p, _base):
        p.setPen(self._pen())
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(smooth_path(self.points))

    def _paint_blur(self, p, base):
        # target — в точках экрана, base — в физических пикселях (масштаб Windows 125–150 %).
        ratio = base.devicePixelRatio()
        bounds = QRect(0, 0, round(base.width() / ratio), round(base.height() / ratio))
        target = self.rect().toRect().intersected(bounds)
        if target.width() < 2 or target.height() < 2:
            return
        if self.solid:
            p.save()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(SOLID_COVER))
            # Прямоугольник ровно по рамке, без сглаживания и скругления: скруглённые углы открывали бы
            # пиксели скрытого текста, а расширение рамки задевало бы соседние открытые символы («последние 4»).
            p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            p.drawRect(target)
            p.restore()
            return
        phys = QRect(round(target.x() * ratio), round(target.y() * ratio),
                     round(target.width() * ratio), round(target.height() * ratio)).intersected(base.rect())
        region = base.copy(phys)
        small = region.scaled(max(1, phys.width() // PIXELATE_BLOCK), max(1, phys.height() // PIXELATE_BLOCK),
                              Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        pixelated = small.scaled(phys.size(), Qt.AspectRatioMode.IgnoreAspectRatio,
                                 Qt.TransformationMode.FastTransformation)
        pixelated.setDevicePixelRatio(ratio)
        p.drawImage(target.topLeft(), pixelated)

    def _paint_text(self, p, _base):
        font = text_font(self.size)
        fm = QFontMetricsF(font)
        path = QPainterPath()
        for i, line in enumerate(self.text.split("\n")):
            baseline = self.points[0] + QPointF(0, fm.ascent() + i * fm.lineSpacing())
            path.addText(baseline, font, line)
        outline = QPen(QColor(255, 255, 255, 220), 3)
        outline.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.strokePath(path, outline)
        p.fillPath(path, self.color)

    def label_color(self) -> QColor:
        """Цвет цифры в номере и текста в сноске: выбранный или авто."""
        if self.text_color is not None:
            return QColor(self.text_color)
        return QColor("#ffffff") if self.kind == NUMBER else text_color_on(self.color)

    def _paint_wedge(self, p, base: QPointF, tip: QPointF, half_width: float):
        """Указатель-клин как в Clip2net: широкий у основания, сходится в точку на цели."""
        d = tip - base
        dist = math.hypot(d.x(), d.y())
        if dist < 1:
            return
        perp = QPointF(-d.y() / dist, d.x() / dist) * half_width
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.color)
        p.drawPolygon(QPolygonF([base + perp, tip, base - perp]))

    def _paint_number(self, p, _base):
        center, tail = self.points[0], self.points[-1]
        r = NUMBER_RADII[self.size]
        d = tail - center
        if math.hypot(d.x(), d.y()) > r:
            self._paint_wedge(p, center, tail, r * 0.6)
        p.setBrush(self.color)
        p.setPen(QPen(Qt.GlobalColor.white, 2))
        p.drawEllipse(center, r, r)

        font = crisp(QFont())
        font.setPixelSize(int(r * 1.1))
        font.setBold(True)
        fm = QFontMetricsF(font)
        label = str(self.number)
        p.setFont(font)
        p.setPen(self.label_color())
        p.drawText(center + QPointF(-fm.horizontalAdvance(label) / 2, (fm.ascent() - fm.descent()) / 2), label)

    def _paint_callout(self, p, _base):
        box = self.callout_box()
        target = self.points[0]
        if not box.adjusted(-2, -2, 2, 2).contains(target):
            # Клин от середины блока к цели; блок рисуется поверх и закрывает основание.
            half = min(box.height() / 2 - 2, max(8.0, NUMBER_RADII[self.size] * 0.6))
            self._paint_wedge(p, box.center(), target, half)
        p.setPen(QPen(self.color.darker(130), 1))
        p.setBrush(self.color)
        p.drawRoundedRect(box, 6, 6)
        font = text_font(self.size)
        fm = QFontMetricsF(font)
        p.setFont(font)
        p.setPen(self.label_color())
        for i, line in enumerate(self.text.split("\n")):
            p.drawText(box.topLeft() + QPointF(CALLOUT_PAD, CALLOUT_PAD + fm.ascent() + i * fm.lineSpacing()), line)
