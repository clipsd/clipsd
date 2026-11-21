# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Форма снимка (1.34): прямоугольник, скруглённые углы, овал, круг.

Форма не меняет пиксели снимка в редакторе: холст рисует шахматку за её пределами, а готовая картинка
(копирование, сохранение, автосохранение) получает прозрачность за формой вместе с пометками.
- PNG и WebP: прозрачный фон за формой;
- JPG прозрачности не знает: фон за формой заливается цветом из настройки shape_background (белый по умолчанию);
- буфер обмена: PNG с прозрачностью и запасная картинка на белом фоне (hidpi.clipboard_mime).
Каждый новый снимок прямоугольный; последняя выбранная форма запоминается (form_last) и включается одним щелчком.
"""

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QImage, QPainter, QPainterPath, QTransform

RECT, ROUND_S, ROUND_M, ROUND_L, OVAL, CIRCLE = "rect", "round1", "round2", "round3", "oval", "circle"
ROUND = "round"                 # скруглённые углы со своим радиусом (ползунок, поле, маркер у угла)
FORMS = (RECT, ROUND_S, ROUND_M, ROUND_L, OVAL, CIRCLE)   # порядок пунктов меню
ROUNDED = (ROUND_S, ROUND_M, ROUND_L)   # готовые размеры: быстрые пункты меню
ALL_CODES = FORMS + (ROUND,)
RADII = {ROUND_S: 12.0, ROUND_M: 28.0, ROUND_L: 56.0}   # радиус углов в точках снимка (не больше половины меньшей стороны)
DEFAULT_LAST = ROUND_M          # одним щелчком, пока форму ни разу не выбирали
DEFAULT_BACKGROUND = "#ffffff"  # фон за формой там, где прозрачности нет (JPG, запасная картинка буфера)
TITLE_KEYS = {RECT: "forma.rect", ROUND_S: "forma.round_s", ROUND_M: "forma.round_m", ROUND_L: "forma.round_l",
              OVAL: "forma.oval", CIRCLE: "forma.circle"}
NO_ALPHA_EXT = (".jpg", ".jpeg", ".jfif", ".bmp")   # форматы без прозрачности: фон за формой заливается
CHECKER = 8                     # клетка шахматки, точки экрана
CHECKER_COLORS = {False: ("#ffffff", "#d9dde3"), True: ("#4a4f56", "#3a3f46")}


def valid(code) -> str:
    return code if code in ALL_CODES else RECT


class Form:
    """Форма снимка: код, центр круга в точках снимка (None: по центру снимка) и свой радиус углов (код ROUND)."""

    __slots__ = ("code", "center", "r")

    def __init__(self, code=RECT, center=None, radius=None):
        self.code = valid(code)
        self.center = QPointF(center) if center is not None else None
        self.r = max(0.0, float(radius)) if self.code == ROUND and radius is not None else (
            RADII[ROUND_M] if self.code == ROUND else None)

    def copy(self) -> "Form":
        return Form(self.code, self.center, self.r)

    @property
    def is_rect(self) -> bool:
        return self.code == RECT

    @property
    def is_round(self) -> bool:
        return self.code in ROUNDED or self.code == ROUND

    @property
    def radius(self) -> float:
        """Радиус углов в точках снимка (0 у остальных форм)."""
        return RADII.get(self.code, self.r or 0.0)

    def __eq__(self, other):
        return (isinstance(other, Form) and self.code == other.code and self.center == other.center
                and self.r == other.r)

    def __repr__(self):
        return f"Form({self.code!r}, {self.center!r}, {self.r!r})"


def rounded(radius: float) -> Form:
    """Скруглённые углы с радиусом: готовый размер (малые, средние, большие), если радиус совпал, иначе свой."""
    radius = max(0.0, float(radius))
    for code, value in RADII.items():
        if abs(value - radius) < 1e-6:
            return Form(code)
    return Form(ROUND, radius=radius)


def max_radius(w: float, h: float) -> float:
    """Самый большой радиус углов: половина меньшей стороны снимка (дальше углы не скругляются)."""
    return min(w, h) / 2.0


def icon_code(form: Form) -> str:
    """Значок формы: для своего радиуса ближайший готовый размер."""
    if form.code != ROUND:
        return form.code
    return min(ROUNDED, key=lambda c: abs(RADII[c] - form.radius))


HANDLE_K = 0.2929   # 1 - cos 45°: маркер радиуса на середине дуги левого верхнего угла


def radius_handle(form: Form, w: float, h: float) -> QPointF:
    """Где на холсте маркер радиуса: середина дуги левого верхнего угла."""
    r = min(form.radius, max_radius(w, h))
    return QPointF(r * HANDLE_K, r * HANDLE_K)


def radius_from_point(pos: QPointF, w: float, h: float) -> float:
    """Радиус по точке, куда тянут маркер: по диагонали от угла, в пределах 0 … половины меньшей стороны."""
    d = max(0.0, (pos.x() + pos.y()) / 2.0)
    return min(d / HANDLE_K, max_radius(w, h))


def circle_rect(form: Form, w: float, h: float) -> QRectF:
    """Квадрат круга: сторона равна меньшей стороне снимка, центр по умолчанию в середине, круг не выходит за снимок."""
    d = float(min(w, h))
    c = form.center if form.center is not None else QPointF(w / 2, h / 2)
    x = min(max(c.x() - d / 2, 0.0), w - d)
    y = min(max(c.y() - d / 2, 0.0), h - d)
    return QRectF(x, y, d, d)


def clamp_center(form: Form, w: float, h: float) -> QPointF:
    """Центр круга, который реально получится (круг прижат к краям снимка)."""
    return circle_rect(form, w, h).center()


def path(form: Form, w: float, h: float) -> QPainterPath:
    """Контур формы в точках снимка (w × h)."""
    out = QPainterPath()
    rect = QRectF(0, 0, w, h)
    if form.is_round:
        r = min(form.radius, max_radius(w, h))
        out.addRoundedRect(rect, r, r)
    elif form.code == OVAL:
        out.addEllipse(rect)
    elif form.code == CIRCLE:
        out.addEllipse(circle_rect(form, w, h))
    else:
        out.addRect(rect)
    return out


def logical(image: QImage) -> tuple:
    size = image.deviceIndependentSize()
    return size.width(), size.height()


def apply(image: QImage, form: Form) -> QImage:
    """Картинка с прозрачностью за формой (сглаженный край). Прямоугольник: та же картинка без изменений.
    Круг обрезается до своего квадрата: прозрачные поля слева и справа в файл не попадают."""
    if form is None or form.is_rect or image.isNull():
        return image
    ratio = image.devicePixelRatio() or 1.0
    w, h = logical(image)
    contour = path(form, w, h)
    src = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    out = QImage(src.size(), QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(Qt.GlobalColor.transparent)
    out.setDevicePixelRatio(ratio)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255))
    p.drawPath(contour)          # маска: сглаженный край формы
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    src.setDevicePixelRatio(ratio)
    p.drawImage(0, 0, src)       # снимок с пометками только внутри маски
    p.end()
    if form.code == CIRCLE:
        box = circle_rect(form, w, h)
        phys = QRectF(box.x() * ratio, box.y() * ratio, box.width() * ratio, box.height() * ratio).toAlignedRect()
        phys = phys.intersected(out.rect())
        out = out.copy(phys)
        out.setDevicePixelRatio(ratio)
    out.setDotsPerMeterX(image.dotsPerMeterX())
    out.setDotsPerMeterY(image.dotsPerMeterY())
    return out


def background(config=None) -> QColor:
    color = QColor((config or {}).get("shape_background") or DEFAULT_BACKGROUND)
    return color if color.isValid() else QColor(DEFAULT_BACKGROUND)


def flatten(image: QImage, color=None) -> QImage:
    """Картинка без прозрачности: прозрачное залито цветом (JPG, запасная картинка буфера обмена)."""
    color = QColor(color) if color is not None else QColor(DEFAULT_BACKGROUND)
    out = QImage(image.size(), QImage.Format.Format_RGB32)
    out.fill(color)
    p = QPainter(out)
    p.drawImage(0, 0, image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied))   # пиксель в пиксель
    p.end()
    out.setDevicePixelRatio(image.devicePixelRatio())
    out.setDotsPerMeterX(image.dotsPerMeterX())
    out.setDotsPerMeterY(image.dotsPerMeterY())
    return out


def has_transparency(image: QImage) -> bool:
    """Есть ли прозрачность за формой: у всех форм, кроме прямоугольника, прозрачны углы картинки.
    Обычный снимок непрозрачен: для него буфер обмена и файлы работают как раньше."""
    if image is None or image.isNull() or not image.hasAlphaChannel():
        return False
    w, h = image.width() - 1, image.height() - 1
    return any(image.pixelColor(x, y).alpha() < 255 for x, y in ((0, 0), (w, 0), (0, h), (w, h)))


def outside(form: Form, w: float, h: float) -> QPainterPath:
    """Область снимка за формой (там холст рисует шахматку)."""
    whole = QPainterPath()
    whole.addRect(QRectF(0, 0, w, h))
    return whole.subtracted(path(form, w, h))


def checker_brush(zoom: float, dark: bool) -> QBrush:
    """Кисть шахматки (так программы показывают прозрачность): клетка CHECKER точек экрана при любом масштабе вида."""
    a, b = (QColor(c) for c in CHECKER_COLORS[bool(dark)])
    tile = QImage(CHECKER * 2, CHECKER * 2, QImage.Format.Format_RGB32)
    tile.fill(a)
    p = QPainter(tile)
    p.fillRect(CHECKER, 0, CHECKER, CHECKER, b)
    p.fillRect(0, CHECKER, CHECKER, CHECKER, b)
    p.end()
    brush = QBrush(tile)
    k = 1.0 / max(zoom, 0.01)
    brush.setTransform(QTransform.fromScale(k, k))   # холст рисуется в точках снимка, умноженных на масштаб вида
    return brush


def paint_checker(p: QPainter, area: QPainterPath, zoom: float, dark: bool):
    """Шахматка в области area (координаты снимка; у художника уже стоит масштаб вида zoom)."""
    if area.isEmpty():
        return
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.fillPath(area, checker_brush(zoom, dark))
    p.restore()
