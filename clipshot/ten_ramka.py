# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Тень, рамка и поля вокруг снимка (1.36).

Три независимых переключателя, как «Форма снимка» повторяют контур формы (скруглённые углы, овал, круг):
- Рамка: линия заданной толщины и цвета из палитры снаружи контура формы (картинка становится больше на толщину);
- Тень: мягкая тень от внешнего контура, сдвинута вниз; размер (мягкость) и прозрачность задаются;
- Поля: свободное место вокруг, прозрачное или цвета фона (настройка shape_background, как за формой в JPG).
Размеры в точках снимка (как радиус углов и толщина линий). Применяется после формы снимка при копировании и
сохранении; PNG и WebP остаются с прозрачностью, JPG заливается цветом фона (hidpi/forma.flatten). Во время правки
тот же рисунок показан вокруг холста (Canvas._paint_deco, DecoFrame): холст и координаты пометок не меняются.
Включённость при новом снимке сбрасывается (как форма), размеры и цвет запоминаются в настройках (deco_*).
"""
import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPainterPath

from . import forma

SHADOW_SIZE = (4, 60, 18)        # мягкость тени, точки: от, до, по умолчанию
SHADOW_OPACITY = (10, 80, 40)    # прозрачность тени, проценты
FRAME_WIDTH = (1, 24, 4)         # толщина рамки, точки
MARGIN = (4, 120, 24)            # поля, точки
DEFAULT_FRAME_COLOR = "#000000"
SHADOW_DROP = 0.3                # тень сдвинута вниз на такую долю её размера

_KEYS = ("shadow", "shadow_size", "shadow_opacity", "frame", "frame_width", "frame_color",
         "margin_on", "margin", "margin_bg")


def _clamp(value, spec, default=None):
    lo, hi, dflt = spec
    try:
        v = int(round(float(value)))
    except (TypeError, ValueError):
        v = dflt if default is None else default
    return max(lo, min(hi, v))


class Deco:
    """Оформление снимка: что включено и с какими размерами."""

    __slots__ = _KEYS

    def __init__(self, shadow=False, shadow_size=SHADOW_SIZE[2], shadow_opacity=SHADOW_OPACITY[2], frame=False,
                 frame_width=FRAME_WIDTH[2], frame_color=DEFAULT_FRAME_COLOR, margin_on=False, margin=MARGIN[2],
                 margin_bg=False):
        self.shadow = bool(shadow)
        self.shadow_size = _clamp(shadow_size, SHADOW_SIZE)
        self.shadow_opacity = _clamp(shadow_opacity, SHADOW_OPACITY)
        self.frame = bool(frame)
        self.frame_width = _clamp(frame_width, FRAME_WIDTH)
        color = QColor(frame_color) if isinstance(frame_color, str) else QColor(DEFAULT_FRAME_COLOR)
        self.frame_color = (color if color.isValid() else QColor(DEFAULT_FRAME_COLOR)).name().lower()
        self.margin_on = bool(margin_on)
        self.margin = _clamp(margin, MARGIN)
        self.margin_bg = bool(margin_bg)

    @classmethod
    def from_config(cls, config) -> "Deco":
        """Размеры и цвет из настроек; тень, рамка и поля при новом снимке выключены."""
        c = config or {}
        return cls(False, c.get("deco_shadow_size", SHADOW_SIZE[2]), c.get("deco_shadow_opacity", SHADOW_OPACITY[2]),
                   False, c.get("deco_frame_width", FRAME_WIDTH[2]), c.get("deco_frame_color", DEFAULT_FRAME_COLOR),
                   False, c.get("deco_margin", MARGIN[2]), bool(c.get("deco_margin_bg", False)))

    def remember(self, config):
        """Размеры, цвет и вид полей в настройки (включённость не запоминается: новый снимок без оформления)."""
        config["deco_shadow_size"] = self.shadow_size
        config["deco_shadow_opacity"] = self.shadow_opacity
        config["deco_frame_width"] = self.frame_width
        config["deco_frame_color"] = self.frame_color
        config["deco_margin"] = self.margin
        config["deco_margin_bg"] = self.margin_bg

    def copy(self) -> "Deco":
        return Deco(*(getattr(self, k) for k in _KEYS))

    def __eq__(self, other):
        return isinstance(other, Deco) and all(getattr(self, k) == getattr(other, k) for k in _KEYS)

    def __hash__(self):
        return hash(tuple(getattr(self, k) for k in _KEYS))

    def __repr__(self):
        return "Deco(" + ", ".join(f"{k}={getattr(self, k)!r}" for k in _KEYS) + ")"

    # --- размеры --------------------------------------------------------------------------------------------

    @property
    def active(self) -> bool:
        return self.shadow or self.frame or self.margin_on

    def frame_px(self) -> int:
        return self.frame_width if self.frame else 0

    def drop(self) -> float:
        return self.shadow_size * SHADOW_DROP

    def pad(self) -> int:
        """Сколько добавляется с каждой стороны снимка, точки: рамка + поля + место под тень (целое число)."""
        if not self.active:
            return 0
        room = int(math.ceil(self.shadow_size + self.drop())) if self.shadow else 0
        return self.frame_px() + (self.margin if self.margin_on else 0) + room


def outer_form(form):
    """Форма готовой картинки: круг уже обрезан до своего квадрата и стоит по центру."""
    if form is not None and form.code == forma.CIRCLE:
        return forma.Form(forma.CIRCLE)
    return form if form is not None else forma.Form()


def outset_path(form, w: float, h: float, t: float) -> QPainterPath:
    """Контур формы, раздвинутый наружу на t (рамка и тень идут по нему)."""
    out = QPainterPath()
    rect = QRectF(0, 0, w, h)
    if form.is_round:
        r = min(form.radius, forma.max_radius(w, h))
        out.addRoundedRect(rect.adjusted(-t, -t, t, t), r + t, r + t)
    elif form.code == forma.OVAL:
        out.addEllipse(rect.adjusted(-t, -t, t, t))
    elif form.code == forma.CIRCLE:
        out.addEllipse(forma.circle_rect(form, w, h).adjusted(-t, -t, t, t))
    else:
        out.addRect(rect.adjusted(-t, -t, t, t))
    return out


# --- мягкая тень -------------------------------------------------------------------------------------------

_cache = {"key": None, "image": None}


def shadow_layer(form, w: float, h: float, deco: Deco, scale: float) -> QImage:
    """Слой тени для прямоугольника (-pad, -pad, w + 2 pad, h + 2 pad): scale пикселей на точку снимка, devicePixelRatio
    равен scale, поэтому слой кладётся в точках снимка (p.drawImage(-pad, -pad, слой)). Мягкость даёт рисование в уменьшенном
    виде и плавное увеличение: без чтения пикселей по одному, на любой платформе одинаково."""
    pad = deco.pad()
    key = (form.code, form.center.x() if form.center is not None else None, form.center.y() if form.center is not None else None,
           form.r, round(w, 3), round(h, 3), deco.shadow_size, deco.shadow_opacity, deco.frame_px(), pad, round(scale, 4))
    if _cache["key"] == key:
        return _cache["image"]
    full_w, full_h = max(1, math.ceil((w + 2 * pad) * scale)), max(1, math.ceil((h + 2 * pad) * scale))
    blur = deco.shadow_size * scale
    f = max(1.0, blur / 4.0)                       # во сколько раз рисуем мельче: мягкость растёт вместе с размером
    small_w, small_h = max(1, math.ceil(full_w / f)), max(1, math.ceil(full_h / f))
    small = QImage(small_w, small_h, QImage.Format.Format_ARGB32_Premultiplied)
    small.fill(Qt.GlobalColor.transparent)
    p = QPainter(small)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(scale / f, scale / f)
    p.translate(pad, pad + deco.drop())
    p.fillPath(outset_path(form, w, h, deco.frame_px()), QColor(0, 0, 0, round(255 * deco.shadow_opacity / 100)))
    p.end()
    # второй проход смягчения: вдвое мельче и обратно (расплывает ступеньки)
    half = small.scaled(max(1, small_w // 2), max(1, small_h // 2), Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)
    small = half.scaled(small_w, small_h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    layer = small.scaled(full_w, full_h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    layer = layer.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    layer.setDevicePixelRatio(scale)
    _cache["key"], _cache["image"] = key, layer
    return layer


def paint_backdrop(p: QPainter, form, w: float, h: float, deco: Deco, scale: float, background=None, checker=None):
    """Всё, что вокруг контура формы: поля (цвет фона или шахматка), тень, рамка. p в точках снимка, начало в левом
    верхнем углу снимка. background: QColor полей или None (прозрачные: рисуется checker(p, path) или ничего)."""
    if deco is None or not deco.active:
        return
    pad = deco.pad()
    t = deco.frame_px()
    contour = forma.path(form, w, h)
    whole = QPainterPath()
    whole.addRect(QRectF(-pad, -pad, w + 2 * pad, h + 2 * pad))
    outside = whole.subtracted(contour)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if deco.margin_on and deco.margin_bg and background is not None:
        p.fillPath(outside, QColor(background))
    elif checker is not None:
        checker(p, outside)
    if deco.shadow:
        p.save()
        p.setClipPath(whole.subtracted(outset_path(form, w, h, t)))
        p.drawImage(QPointF(-pad, -pad), shadow_layer(form, w, h, deco, scale))
        p.restore()
    if t:
        p.fillPath(outset_path(form, w, h, t).subtracted(contour), QColor(deco.frame_color))
    p.restore()


def apply(image: QImage, form, deco: Deco, background=None) -> QImage:
    """Готовая картинка (после forma.apply) с рамкой, тенью и полями. Без оформления: та же картинка."""
    if deco is None or not deco.active or image.isNull():
        return image
    ratio = image.devicePixelRatio() or 1.0
    w, h = forma.logical(image)
    pad = deco.pad()
    pad_px = round(pad * ratio)
    out = QImage(image.width() + 2 * pad_px, image.height() + 2 * pad_px, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(Qt.GlobalColor.transparent)
    out.setDevicePixelRatio(ratio)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.translate(pad_px / ratio, pad_px / ratio)
    shape = outer_form(form)
    paint_backdrop(p, shape, w, h, deco, ratio, background)
    # картинка пиксель в пиксель поверх (за формой у неё прозрачно: видна рамка, тень, поля)
    src = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    src.setDevicePixelRatio(ratio)
    p.drawImage(QPointF(0, 0), src)
    p.end()
    out.setDotsPerMeterX(image.dotsPerMeterX())
    out.setDotsPerMeterY(image.dotsPerMeterY())
    return out
