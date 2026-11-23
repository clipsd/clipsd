# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Эмодзи и стикеры (1.36): инструмент «Стикер».

Цветные эмодзи рисуются не системным шрифтом (в Windows и Linux он разный, а где-то его нет совсем), а встроенными
картинками Twemoji (SVG, лицензия CC BY 4.0, clipshot/assets/twemoji, лицензия в packaging/licenses): значок на снимке
выглядит одинаково везде, а при увеличении и повороте остаётся чётким. Встроено 71 знак, отобранный под снимки экрана.
Плюс стикеры, нарисованные программой: плашки с текстом («Нажмите сюда», «Важно»…) и номера в кружках.
Поиск идёт по названиям на языке интерфейса (i18n stiker.n.<код>: несколько слов через запятую).
"""
from pathlib import Path

from PyQt6.QtCore import QByteArray, QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PyQt6.QtSvg import QSvgRenderer

ASSETS = Path(__file__).resolve().parent / "assets" / "twemoji"
RECENT_MAX = 12
SIZES = {1: 32, 2: 48, 3: 64, 4: 96, 5: 144}   # длинная сторона стикера по кнопкам размера 1-5
MIN_SIDE = 12.0                                  # меньше стикер не делается, точки снимка

# Эмодзи в порядке палитры: сначала самое нужное на снимках (отметки, предупреждения, указатели), потом остальное.
EMOJI = (
    "check", "cross", "warn", "question", "excl", "stop", "ban", "check2",
    "point_r", "point_l", "point_u", "point_d", "arrow_right", "arrow_left", "arrow_up", "arrow_down",
    "star", "star2", "fire", "heart", "new", "ok_btn", "bulb", "pin",
    "lock", "unlock", "key", "eye", "eyes", "alarm", "hourglass", "search",
    "smile", "joy", "love", "cool", "wink", "think", "surprised", "sad", "cry", "angry",
    "thumbs_up", "thumbs_down", "ok_hand", "clap", "pray", "party", "rocket", "hundred",
    "red", "yellow", "green", "flag", "finish", "refresh", "bell", "megaphone",
    "speech", "memo", "pencil", "clip", "camera", "mail", "link", "folder",
    "floppy", "gear", "tools", "bug", "money",
)

# Плашки: код -> (ключ текста в каталоге, цвет из палитры по умолчанию)
PLATES = {
    "plate_click": ("stiker.plate_click", "#1e78ff"),
    "plate_important": ("stiker.plate_important", "#d60808"),
    "plate_new": ("stiker.plate_new", "#2db400"),
    "plate_error": ("stiker.plate_error", "#d60808"),
    "plate_done": ("stiker.plate_done", "#2db400"),
    "plate_attention": ("stiker.plate_attention", "#ff8c00"),
    "plate_tip": ("stiker.plate_tip", "#8b3dff"),
    "plate_here": ("stiker.plate_here", "#1e78ff"),
}
NUMBERS = tuple(f"num{i}" for i in range(1, 10))   # номера в кружках 1-9
ALL = EMOJI + tuple(PLATES) + NUMBERS
PLATE_H = 32.0   # опорная высота плашки при расчёте пропорций

_renderers: dict = {}


def kind(sid: str) -> str:
    """emoji / plate / number"""
    if sid in PLATES:
        return "plate"
    if sid in NUMBERS:
        return "number"
    return "emoji"


def valid(sid) -> bool:
    return sid in ALL


def emoji_path(sid: str) -> Path:
    return ASSETS / f"{sid}.svg"


def renderer(sid: str):
    """Рисовальщик SVG эмодзи (из встроенного файла, системные шрифты не нужны); None, если файла нет."""
    if sid not in _renderers:
        r = None
        try:
            r = QSvgRenderer(QByteArray(emoji_path(sid).read_bytes()))
            if not r.isValid():
                r = None
        except OSError:
            r = None
        _renderers[sid] = r
    return _renderers[sid]


def plate_text(sid: str, lang: str = None) -> str:
    """Текст плашки на языке интерфейса (запоминается в стикере при постановке: смена языка его не меняет)."""
    from .i18n import tr, tr_in
    entry = PLATES.get(sid)
    if not entry:
        return ""
    return tr_in(lang, entry[0]) if lang else tr(entry[0])


def default_color(sid: str, fallback) -> QColor:
    entry = PLATES.get(sid)
    return QColor(entry[1]) if entry else QColor(fallback)


def text_on(color) -> QColor:
    """Цвет текста на заливке: белый, если он даёт контраст не меньше 3,5:1 (крупный жирный текст), иначе чёрный.
    Свой расчёт по яркости: общий shapes.text_color_on считает жёлтый и зелёный «тёмными» и даёт белый текст."""
    c = QColor(color)

    def lin(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    lum = 0.2126 * lin(c.red()) + 0.7152 * lin(c.green()) + 0.0722 * lin(c.blue())
    return QColor("#ffffff") if 1.05 / (lum + 0.05) >= 3.5 else QColor("#000000")


def _plate_font(px: float) -> QFont:
    font = QFont()
    font.setPixelSize(max(1, round(px)))
    font.setBold(True)
    font.setStyleStrategy(QFont.StyleStrategy.NoSubpixelAntialias | QFont.StyleStrategy.PreferAntialias)
    return font


def aspect(sid: str, text: str = "") -> float:
    """Ширина / высота стикера по умолчанию: эмодзи и номера квадратные, плашка по длине текста."""
    if kind(sid) != "plate":
        return 1.0
    fm = QFontMetricsF(_plate_font(PLATE_H * 0.56))
    lines = (text or " ").split("\n")
    width = max(fm.horizontalAdvance(line) for line in lines) + PLATE_H * 0.9
    return max(1.6, width / (PLATE_H * (1 + 0.5 * (len(lines) - 1))))


def default_box(sid: str, text: str, level: int) -> tuple:
    """Размер новой плашки (ширина, высота) по кнопке размера 1-5: длинная сторона = SIZES[level]."""
    side = float(SIZES.get(level, SIZES[3]))
    a = aspect(sid, text)
    return (side, side / a) if a >= 1 else (side * a, side)


def draw(p: QPainter, sid: str, rect: QRectF, color=None, text: str = ""):
    """Нарисовать стикер в прямоугольнике rect (у художника уже стоят сдвиг и поворот)."""
    k = kind(sid)
    if k == "emoji":
        r = renderer(sid)
        if r is None:
            _draw_missing(p, rect)
        else:
            r.render(p, rect)
        return
    color = QColor(color) if color is not None else QColor("#d60808")
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if k == "number":
        side = min(rect.width(), rect.height())
        c = rect.center()
        circle = QRectF(c.x() - side / 2, c.y() - side / 2, side, side)
        p.setPen(QPen(QColor("#ffffff"), max(1.0, side * 0.06)))
        p.setBrush(color)
        inner = circle.adjusted(side * 0.03, side * 0.03, -side * 0.03, -side * 0.03)
        p.drawEllipse(inner)
        label = sid[3:]
        font = _plate_font(side * 0.62)
        fm = QFontMetricsF(font)
        p.setFont(font)
        p.setPen(text_on(color))
        p.drawText(QPointF(c.x() - fm.horizontalAdvance(label) / 2, c.y() + (fm.ascent() - fm.descent()) / 2), label)
    else:
        radius = rect.height() * 0.28
        p.setPen(QPen(color.darker(130), max(1.0, rect.height() * 0.03)))
        p.setBrush(color)
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        lines = (text or " ").split("\n")
        px = rect.height() * 0.56 / (1 + 0.5 * (len(lines) - 1))
        font = _plate_font(px)
        fm = QFontMetricsF(font)
        widest = max(fm.horizontalAdvance(line) for line in lines)
        room = rect.width() * 0.88
        if widest > room > 0:
            font = _plate_font(px * room / widest)   # длинный текст сжимается, а не вылезает за плашку
            fm = QFontMetricsF(font)
        p.setFont(font)
        p.setPen(text_on(color))
        total = fm.lineSpacing() * len(lines)
        top = rect.center().y() - total / 2
        for i, line in enumerate(lines):
            x = rect.center().x() - fm.horizontalAdvance(line) / 2
            p.drawText(QPointF(x, top + fm.ascent() + i * fm.lineSpacing()), line)
    p.restore()


def _draw_missing(p: QPainter, rect: QRectF):
    """Файла эмодзи нет в сборке: пустая рамка (снимок не ломается)."""
    p.save()
    p.setPen(QPen(QColor(128, 128, 128), 1, Qt.PenStyle.DashLine))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(rect)
    p.restore()


def render_icon(sid: str, side: int, color=None, text: str = "", ratio: float = 1.0):
    """Картинка для кнопки палитры: стикер по центру квадрата side x side."""
    from PyQt6.QtGui import QImage
    img = QImage(round(side * ratio), round(side * ratio), QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(ratio)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    a = aspect(sid, text)
    w, h = (side, side / a) if a >= 1 else (side * a, side)
    draw(p, sid, QRectF((side - w) / 2, (side - h) / 2, w, h), color, text)
    p.end()
    return img


# --- названия и поиск ---------------------------------------------------------------------------------------

def names(sid: str, lang: str = None) -> list:
    """Названия для поиска на языке (по умолчанию интерфейса): список слов и фраз, свёрнутых в нижний регистр."""
    from . import i18n
    if kind(sid) != "emoji":
        return []   # у плашек ищется их текст, у номеров названия нет
    key = f"stiker.n.{sid}"
    raw = i18n.tr_in(lang, key) if lang else i18n.tr(key)
    if raw == key:
        return []
    return [fold(part, lang) for part in raw.split(",") if part.strip()]


def fold(text: str, lang: str = None) -> str:
    """Для сравнения: без лишних пробелов, регистр не важен (турецкие I/İ и ı/i разные буквы, не как у casefold)."""
    from . import i18n
    text = (text or "").strip()
    if (lang or i18n.current()) == "tr":
        text = text.replace("I", "ı").replace("İ", "i")
    return text.casefold()


def title(sid: str) -> str:
    """Первое (главное) название стикера на языке интерфейса: подсказка кнопки."""
    n = names(sid)
    from .i18n import tr
    return n[0][:1].upper() + n[0][1:] if n else tr("stiker.unnamed")


def search(query: str, lang: str = None) -> list:
    """Коды стикеров, у которых любое название содержит запрос (регистр не важен). Пустой запрос: все."""
    q = fold(query, lang)
    if not q:
        return list(ALL)
    out = []
    for sid in ALL:
        if any(q in n for n in names(sid, lang)):
            out.append(sid)
            continue
        if kind(sid) == "plate" and q in fold(plate_text(sid, lang), lang):
            out.append(sid)
    return out


# --- недавние -------------------------------------------------------------------------------------------------

def recent(config) -> list:
    raw = (config or {}).get("sticker_recent")
    out = []
    for sid in (raw if isinstance(raw, list) else []):
        if isinstance(sid, str) and valid(sid) and sid not in out:
            out.append(sid)
    return out[:RECENT_MAX]


def remember(config, sid: str) -> list:
    """Поставленный стикер встаёт первым в «недавних»; повтор поднимается, лишние вытесняются."""
    if not valid(sid):
        return recent(config)
    out = [sid] + [s for s in recent(config) if s != sid]
    config["sticker_recent"] = out[:RECENT_MAX]
    return config["sticker_recent"]


def selfcheck() -> list:
    """Проблемы встроенного набора: нет файла эмодзи или он не читается (для теста и сборки)."""
    problems = []
    for sid in EMOJI:
        if renderer(sid) is None:
            problems.append(f"нет или не читается: {emoji_path(sid)}")
    return problems
