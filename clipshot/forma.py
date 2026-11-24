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
1.36.3: у скруглённых углов, овала и круга есть рамка формы (box) внутри снимка: маркеры по углам и серединам сторон
меняют размер формы, перенос двигает её. Готовая картинка обрезается до рамки, как круг до своего квадрата.
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
MIN_BOX = 16.0                  # 1.36.3: самая маленькая рамка формы, точки снимка (меньше форму не разглядеть)
HANDLES = ("tl", "t", "tr", "r", "br", "b", "bl", "l")   # маркеры рамки формы: углы и середины сторон


def valid(code) -> str:
    return code if code in ALL_CODES else RECT


class Form:
    """Форма снимка: код, центр круга в точках снимка (None: по центру снимка), свой радиус углов (код ROUND)
    и рамка формы box (1.36.3) в точках снимка: None значит весь снимок (круг: квадрат по меньшей стороне с центром)."""

    __slots__ = ("code", "center", "r", "box")

    def __init__(self, code=RECT, center=None, radius=None, box=None):
        self.code = valid(code)
        self.center = QPointF(center) if center is not None else None
        self.r = max(0.0, float(radius)) if self.code == ROUND and radius is not None else (
            RADII[ROUND_M] if self.code == ROUND else None)
        self.box = QRectF(box).normalized() if box is not None and self.code != RECT else None   # прямоугольнику: «Обрезка»

    def copy(self) -> "Form":
        return Form(self.code, self.center, self.r, self.box)

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
                and self.r == other.r and self.box == other.box)

    def __repr__(self):
        return f"Form({self.code!r}, {self.center!r}, {self.r!r}, {self.box!r})"


def rounded(radius: float, box=None) -> Form:
    """Скруглённые углы с радиусом: готовый размер (малые, средние, большие), если радиус совпал, иначе свой.
    box: рамка формы (1.36.3), остаётся прежней при смене радиуса."""
    radius = max(0.0, float(radius))
    for code, value in RADII.items():
        if abs(value - radius) < 1e-6:
            return Form(code, box=box)
    return Form(ROUND, radius=radius, box=box)


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
    """Где на холсте маркер радиуса: середина дуги левого верхнего угла рамки формы (1.36.3: не снимка)."""
    box = frame(form, w, h)
    r = min(form.radius, max_radius(box.width(), box.height()))
    return QPointF(box.x() + r * HANDLE_K, box.y() + r * HANDLE_K)


def radius_from_point(pos: QPointF, w: float, h: float, form: Form = None) -> float:
    """Радиус по точке, куда тянут маркер: по диагонали от угла рамки формы, в пределах 0 … половины её меньшей стороны."""
    box = frame(form, w, h) if form is not None else QRectF(0, 0, w, h)
    d = max(0.0, (pos.x() - box.x() + pos.y() - box.y()) / 2.0)
    return min(d / HANDLE_K, max_radius(box.width(), box.height()))


def circle_rect(form: Form, w: float, h: float) -> QRectF:
    """Квадрат круга: сторона равна меньшей стороне снимка (1.36.3: или рамки формы), центр по умолчанию в середине,
    круг не выходит за снимок."""
    full = QRectF(0, 0, w, h)
    box = form.box.intersected(full) if form.box is not None else QRectF()
    if box.width() > 0 and box.height() > 0:
        d = float(min(box.width(), box.height()))
        c = box.center()
    else:
        d = float(min(w, h))
        c = form.center if form.center is not None else QPointF(w / 2, h / 2)
    x = min(max(c.x() - d / 2, 0.0), w - d)
    y = min(max(c.y() - d / 2, 0.0), h - d)
    return QRectF(x, y, d, d)


def frame(form: Form, w: float, h: float) -> QRectF:
    """1.36.3: рамка формы в точках снимка, какой она получится: круг в своём квадрате, остальные в box или по всему
    снимку; за снимок рамка не выходит."""
    full = QRectF(0, 0, w, h)
    if form is None or form.is_rect:
        return full
    if form.code == CIRCLE:
        return circle_rect(form, w, h)
    if form.box is None:
        return full
    box = form.box.intersected(full)
    return box if box.width() > 0 and box.height() > 0 else full


def is_full(form: Form, w: float, h: float) -> bool:
    """Форма во весь снимок: готовую картинку обрезать не нужно."""
    box = frame(form, w, h)
    return abs(box.x()) < 1e-6 and abs(box.y()) < 1e-6 and abs(box.width() - w) < 1e-6 and abs(box.height() - h) < 1e-6


def inscribed_square(box: QRectF) -> QRectF:
    """Вписанный квадрат по центру рамки (переход на круг из рамки овала или скруглённых углов)."""
    d = min(box.width(), box.height())
    c = box.center()
    return QRectF(c.x() - d / 2, c.y() - d / 2, d, d)


def handle_points(box: QRectF) -> dict:
    """Маркеры рамки формы: углы и середины сторон (имена как у рамки обрезки: tl, t, tr, r, br, b, bl, l)."""
    l, t, r, b = box.left(), box.top(), box.right(), box.bottom()
    cx, cy = box.center().x(), box.center().y()
    return {"tl": QPointF(l, t), "t": QPointF(cx, t), "tr": QPointF(r, t), "r": QPointF(r, cy),
            "br": QPointF(r, b), "b": QPointF(cx, b), "bl": QPointF(l, b), "l": QPointF(l, cy)}


def _minimum(w: float, h: float) -> float:
    return min(MIN_BOX, float(w), float(h))


def resize_box(start: QRectF, handle: str, pos: QPointF, w: float, h: float, keep: bool = False) -> QRectF:
    """1.36.3: новая рамка формы, когда маркер handle тянут в точку pos (точки снимка). Рамка не выходит за снимок и не
    меньше MIN_BOX. keep: пропорционально (круг всегда, овал и скруглённые углы с Shift): противоположный угол
    или сторона стоят на месте, у маркера на стороне рамка растёт в обе стороны поперёк от середины."""
    m = _minimum(w, h)
    l, t, r, b = start.left(), start.top(), start.right(), start.bottom()
    if not keep:
        if "l" in handle:
            l = min(max(pos.x(), 0.0), r - m)
        if "r" in handle:
            r = max(min(pos.x(), float(w)), l + m)
        if "t" in handle:
            t = min(max(pos.y(), 0.0), b - m)
        if "b" in handle:
            b = max(min(pos.y(), float(h)), t + m)
        return QRectF(QPointF(l, t), QPointF(r, b))
    bw, bh = max(start.width(), 1e-6), max(start.height(), 1e-6)
    cx, cy = start.center().x(), start.center().y()
    scales, limits = [], []
    # по горизонтали
    if "l" in handle:
        scales.append((r - pos.x()) / bw)
        limits.append(r / bw)
    elif "r" in handle:
        scales.append((pos.x() - l) / bw)
        limits.append((w - l) / bw)
    else:
        limits.append(2 * min(cx, w - cx) / bw)   # маркер на верхней или нижней стороне: ширина растёт от середины
    # по вертикали
    if "t" in handle:
        scales.append((b - pos.y()) / bh)
        limits.append(b / bh)
    elif "b" in handle:
        scales.append((pos.y() - t) / bh)
        limits.append((h - t) / bh)
    else:
        limits.append(2 * min(cy, h - cy) / bh)
    k = max(scales) if scales else 1.0
    k = max(min(k, min(limits)), max(m / bw, m / bh))
    nw, nh = bw * k, bh * k
    nl = r - nw if "l" in handle else (l if "r" in handle else cx - nw / 2)
    nt = b - nh if "t" in handle else (t if "b" in handle else cy - nh / 2)
    return QRectF(nl, nt, nw, nh)


def move_box(start: QRectF, delta: QPointF, w: float, h: float) -> QRectF:
    """Рамка формы, сдвинутая на delta: прижимается к краям снимка, размер прежний."""
    x = min(max(start.x() + delta.x(), 0.0), max(0.0, w - start.width()))
    y = min(max(start.y() + delta.y(), 0.0), max(0.0, h - start.height()))
    return QRectF(x, y, start.width(), start.height())


def clamp_center(form: Form, w: float, h: float) -> QPointF:
    """Центр круга, который реально получится (круг прижат к краям снимка)."""
    return circle_rect(form, w, h).center()


def path(form: Form, w: float, h: float) -> QPainterPath:
    """Контур формы в точках снимка (w × h)."""
    out = QPainterPath()
    rect = frame(form, w, h)
    if form.is_round:
        r = min(form.radius, max_radius(rect.width(), rect.height()))
        out.addRoundedRect(rect, r, r)
    elif form.code in (OVAL, CIRCLE):
        out.addEllipse(rect)
    else:
        out.addRect(rect)
    return out


def logical(image: QImage) -> tuple:
    size = image.deviceIndependentSize()
    return size.width(), size.height()


def apply(image: QImage, form: Form) -> QImage:
    """Картинка с прозрачностью за формой (сглаженный край). Прямоугольник: та же картинка без изменений.
    Круг обрезается до своего квадрата, 1.36.3: любая форма до своей рамки: прозрачные поля вокруг в файл не попадают."""
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
    if not is_full(form, w, h):
        box = frame(form, w, h)
        phys = QRectF(box.x() * ratio, box.y() * ratio, box.width() * ratio, box.height() * ratio).toAlignedRect()
        phys = phys.intersected(out.rect())
        out = out.copy(phys)
        out.setDevicePixelRatio(ratio)
    out.setDotsPerMeterX(image.dotsPerMeterX())
    out.setDotsPerMeterY(image.dotsPerMeterY())
    return out


# --- общее для редактора и окна выделения (1.36.3: форма выбирается и в окне выделения) ---------------------------

def last_code(config) -> str:
    """Последняя выбранная форма (не прямоугольник): её включает щелчок по кнопке «Форма снимка»."""
    code = (config or {}).get("form_last")
    return code if code in ALL_CODES and code != RECT else DEFAULT_LAST


def last_form(config) -> Form:
    """Последняя форма целиком: у скруглённых углов со своим радиусом и радиус (form_radius)."""
    code = last_code(config)
    if code == ROUND:
        return rounded(float((config or {}).get("form_radius") or RADII[ROUND_M]))
    return Form(code)


def remember(config, form):
    """Запомнить форму для следующего щелчка (прямоугольник не запоминается)."""
    if config is None or form is None or form.is_rect:
        return
    config["form_last"] = form.code
    if form.code == ROUND:
        config["form_radius"] = round(form.radius, 2)


def title(form, ratio: float = 1.0) -> str:
    """Название формы, как в меню; свой радиус в пикселях снимка."""
    from .i18n import tr
    if form.code == ROUND:
        return tr("forma.round_custom", r=int(round(form.radius * (ratio or 1.0))))
    return tr(TITLE_KEYS[form.code])


def jpg_note(config) -> str:
    """Строка про JPG: прозрачности нет, за формой будет фон (белый по умолчанию). Пусто для PNG."""
    from .i18n import tr
    if (config or {}).get("save_format", "png") != "jpg":
        return ""
    color = background(config)
    if color == QColor(DEFAULT_BACKGROUND):
        return tr("forma.jpg_note")
    return tr("forma.jpg_note_color", color=color.name().upper())


def fill_menu(menu, current: str, pick):
    """Пункты форм в меню (значок, название, отметка текущей): одно меню у редактора и окна выделения.
    pick(code) вызывается при выборе."""
    from PyQt6.QtGui import QActionGroup
    from . import icons
    from .i18n import tr
    group = QActionGroup(menu)
    group.setExclusive(True)
    for code in FORMS:
        if code == OVAL:
            menu.addSeparator()
        action = menu.addAction(icons.icon("form_" + code), tr(TITLE_KEYS[code]))
        action.setCheckable(True)
        action.setChecked(code == current)
        action.setData(code)
        group.addAction(action)
        action.triggered.connect(lambda _c=False, c=code: pick(c))
        if code == RECT:
            menu.addSeparator()
    return group


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
