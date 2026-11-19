# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Оформление: «Стандартное» (светлое) и «Профессиональное» (тёмное, как в программах видеомонтажа)."""

class _Preset(dict):
    """Набор настроек оформления; preset["title"] переводится в момент обращения (совместимость со старым кодом)."""

    def __getitem__(self, k):
        v = dict.__getitem__(self, k)
        if k == "title":
            from .i18n import tr
            return tr(v)
        return v


THEMES = {
    "standard": _Preset({
        "title": "themes.standard",
        "ui_accent": "#1e78ff", "ui_panel": "#f5f6f8", "ui_field": "#34383e", "ui_frame": 8,   # 1.32: спокойная палитра (вид А)
        "text": "#1c1f24", "text_dim": "#3d4046", "stage": "#4a4d52", "image_frame": "#1b1d21",
        "button_bg": "#ffffff", "button_border": "#b9b9b9", "button_hover": "#eef3fb", "button_text": "#1c1f24",
        "icon": "#2e3436", "swatch_check": "#111111", "radius": 6, "font": 14, "flat_frame": False,
        "dialog_bg": "#e4e6e9", "card_bg": "#f6f7f8", "card_border": "#c9ccd1", "input_bg": "#ffffff",
        "confirm_bg": "#fafafa", "confirm_text": "#222222", "confirm_dim": "#555555", "confirm_line": "#dcdcdc",
        "confirm_hover": "#ececec", "dark": False,
    }),
    "pro": _Preset({
        "title": "themes.pro",
        "ui_accent": "#2d8ceb", "ui_panel": "#202327", "ui_field": "#111315", "ui_frame": 4,   # 1.32: без чистого чёрного
        "text": "#c8c8c8", "text_dim": "#9a9a9a", "stage": "#1a1a1a", "image_frame": "#000000",
        "button_bg": "#2e2e2e", "button_border": "#3c3c3c", "button_hover": "#383838", "button_text": "#d6d6d6",
        "icon": "#c8c8c8", "swatch_check": "#ffffff", "radius": 2, "font": 13, "flat_frame": True,
        "dialog_bg": "#1e1e1e", "card_bg": "#262626", "card_border": "#3a3a3a", "input_bg": "#1a1a1a",
        "confirm_bg": "#2a2a2a", "confirm_text": "#e0e0e0", "confirm_dim": "#a8a8a8", "confirm_line": "#3c3c3c",
        "confirm_hover": "#343434", "dark": True,
    }),
}


# Главная зелёная кнопка («Скопировать и закрыть» в редакторе и в панели окна выделения, «Обновить», главная кнопка
# окон ClipSD). 1.32, решение владельца 19.11.2026: темнее прежнего #1f9d55 (белый текст 3,5:1), по правилу контраста
# 4,5:1: основной #157a40 (5,4:1), наведение темнее #126b38 (6,6:1), рамка и нажатие #0f5c30 (8,1:1); наведение
# только темнее, иначе текст теряет контраст.
# Один источник для editor.py, selector.py, dialogs.py, ocr.py и окон обновления.
GREEN = "#157a40"
GREEN_HOVER = "#126b38"
GREEN_BORDER = "#0f5c30"
GREEN_PRESSED = "#0f5c30"
GREEN_DISABLED = "#9fd3b4"
GREEN_GRADIENT = ("#157a40", "#126b38")         # плитка «Скопировать» плавающей панели: сверху вниз
GREEN_GRADIENT_HOVER = ("#126b38", "#0f5c30")   # она же под курсором
GREEN_SHADOW = (15, 92, 48, 70)                 # тень плитки, сдвиг 3 px
GREEN_SUB = (255, 255, 255, 235)                # мелкая вторая строка на зелёной кнопке: белый 92 %


# Контраст текста (решение владельца 19.11.2026):
# все пары «текст на фоне» не ниже 4,5:1. Один источник для editor, selector, dialogs, hints, окон обновления, настроек.
LINK = "#1660d0"                 # ссылки, светлое: 5,8:1 на белом (акцент #1e78ff давал 4,05:1)
LINK_DARK = "#58a4f2"            # ссылки, тёмное: 5,6:1 на #25282c (акцент #2d8ceb давал 4,27:1)
TILE_SUB = "#5f6875"             # вторая строка на плитке панели окна выделения: 5,2:1 (было #6b7380, 4,4:1)
BLUE_SUB = "#3f5f8a"             # вторая строка на «Выделить заново»: 5,2:1 под курсором (было #4a6d9c, 4,2:1)
TEAL = "#0d9488"                 # бирюзовый перевода: значки и линии
TEAL_BUTTON = "#0b766c"          # бирюзовая кнопка с белым текстом: 5,5:1 (#0d9488 давал 3,7:1)
TEAL_BUTTON_HOVER = "#095f57"    # её наведение: темнее
TEAL_BUTTON_BORDER = "#08544d"
VIOLET = "#7c3aed"               # фиолетовый текста с картинки: фон кнопки не меняется
VIOLET_HOVER = "#6d28d9"         # наведение темнее: белый текст 7,1:1 (#8f55f5 давал 4,4:1)
VIOLET_BORDER = "#5b21b6"
GLOBE = "#3a9be8"                # глобус языка, один голубой везде
GLOBE_LINE = 2.0                 # толщина линий глобуса (было 1.7): лучше читается


BLUE_BUTTON = "#1660d0"          # синяя кнопка с белым текстом (знакомство «Далее», выбранный язык): 5,8:1
BLUE_BUTTON_HOVER = "#124fae"    # наведение темнее, 7,5:1 (прежнее #3a8bff светлее давало 3,5:1)
BLUE_BUTTON_BORDER = "#0f4596"


def link_color(dark: bool) -> str:
    return LINK_DARK if dark else LINK


STANDARD_ACCENTS = ("#1e78ff", "#2d8ceb")   # акценты оформлений «Стандартное» и «Профессиональное»


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")

    def lin(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def white_contrast(hex_color: str) -> float:
    """Контраст белого текста на этом фоне (WCAG)."""
    return 1.05 / (_luminance(hex_color) + 0.05)


def _darker(hex_color: str, factor: float) -> str:
    h = hex_color.lstrip("#")
    return "#%02x%02x%02x" % tuple(max(0, round(int(h[i:i + 2], 16) * factor)) for i in (0, 2, 4))


def blue_button(accent: str = None) -> tuple:
    """(фон, под курсором, рамка) кнопки с белым текстом цвета акцента: «Сохранить» настроек, «Готово» выбора
    оформления, выбранный модификатор горячей клавиши, номера шагов (1.32, решение владельца
    19.11.2026: белый текст не ниже 4,5:1, наведение только темнее). Стандартные акценты дают синий
    BLUE_BUTTON, как у знакомства; свой цвет акцента затемняется до 4,5:1, его оттенок остаётся."""
    accent = (accent or STANDARD_ACCENTS[0]).lower()
    if accent in STANDARD_ACCENTS or not accent.startswith("#") or len(accent) != 7:
        return BLUE_BUTTON, BLUE_BUTTON_HOVER, BLUE_BUTTON_BORDER
    base = accent
    while white_contrast(base) < 4.5:
        base = _darker(base, 0.92)
    hover = _darker(base, 0.85)
    return base, hover, _darker(base, 0.72)


def green_button_qss(selector: str = "QPushButton", radius: int = 6, extra: str = "") -> str:
    """Таблица стилей главной зелёной кнопки: обычная, под курсором, нажатая, неактивная."""
    return (f"{selector} {{ background: {GREEN}; color: #ffffff; border: 1px solid {GREEN_BORDER}; "
            f"border-radius: {radius}px; {extra} }}"
            f" {selector}:hover {{ background: {GREEN_HOVER}; }}"
            f" {selector}:pressed {{ background: {GREEN_PRESSED}; }}"
            f" {selector}:disabled {{ background: {GREEN_DISABLED}; border-color: {GREEN_DISABLED}; }}")


def title(key) -> str:
    """Название оформления на языке интерфейса."""
    from .i18n import tr
    return tr(f"themes.{key}")

COLOR_KEYS = ("ui_accent", "ui_panel", "ui_field", "ui_frame")


def name(cfg) -> str:
    return cfg.get("ui_theme") if cfg.get("ui_theme") in THEMES else "standard"


def tokens(cfg) -> dict:
    """Набор цветов выбранного оформления; свои цвета из настроек (ui_*) перекрывают его."""
    t = dict(THEMES[name(cfg)])
    t.pop("title", None)
    for key in COLOR_KEYS:
        if cfg.get(key):
            t[key] = cfg[key]
    t["ui_frame"] = int(t["ui_frame"])
    return t


def light_palette():
    """Светлая палитра «Стандартного» оформления, одинаковая при любой теме системы.

    Раньше бралась qapp.style().standardPalette(), но Fusion в Qt 6.5+ отдаёт там палитру по теме системы
    (qt_fusionPalette: при тёмной теме Windows или GNOME текст 240,240,240 на 50,50,50). Наши окна рисуют белые
    карточки и кнопки, а цвет текста многих надписей берут из палитры: на Windows в тёмной теме кнопки языков
    знакомства, «Назад», «Пропустить» были почти белыми на белом (19.11.2026). Здесь те же значения, что у
    светлой Fusion, но всегда светлые."""
    from PyQt6.QtGui import QColor, QPalette
    role, group = QPalette.ColorRole, QPalette.ColorGroup
    black, white = QColor(0, 0, 0), QColor(255, 255, 255)
    window = QColor(239, 239, 239)
    light, mid, dark = window.lighter(150), window.darker(130), window.darker(150)
    shadow = dark.darker(135)
    highlight = QColor(48, 140, 198)
    # (windowText, button, light, dark, mid, text, brightText, base, window), как QPalette(windowText, window, ...) в Qt
    pal = QPalette(black, window, light, dark, mid, black, light, white, window)
    placeholder = QColor(black)
    placeholder.setAlpha(128)
    for r, color in ((role.Midlight, mid.lighter(110)), (role.Shadow, shadow), (role.Highlight, highlight),
                     (role.HighlightedText, white), (role.AlternateBase, QColor(246, 247, 248)),
                     (role.ToolTipBase, QColor(255, 255, 220)), (role.ToolTipText, black),
                     (role.PlaceholderText, placeholder), (role.Link, QColor(22, 96, 208)),
                     (role.LinkVisited, QColor(107, 63, 160))):
        pal.setColor(r, color)
    if hasattr(role, "Accent"):
        pal.setColor(role.Accent, highlight)
    disabled_text = QColor(150, 154, 160)   # спокойно-серый, но читаемый (у Fusion 190,190,190 почти не виден)
    for r in (role.Text, role.WindowText, role.ButtonText):
        pal.setColor(group.Disabled, r, disabled_text)
    pal.setColor(group.Disabled, role.Base, window)
    pal.setColor(group.Disabled, role.Dark, QColor(209, 209, 209).darker(110))
    pal.setColor(group.Disabled, role.Shadow, shadow.lighter(150))
    pal.setColor(group.Disabled, role.Highlight, QColor(145, 145, 145))
    return pal


def _color_scheme(qapp, dark: bool) -> None:
    """Qt 6.8+: попросить у системы светлую или тёмную схему для этой программы (заголовки окон, системные
    диалоги на Windows); в старых Qt и на платформах без поддержки ничего не делает."""
    from PyQt6.QtCore import Qt
    hints = qapp.styleHints() if hasattr(qapp, "styleHints") else None
    scheme = getattr(Qt, "ColorScheme", None)
    if hints is not None and scheme is not None and hasattr(hints, "setColorScheme"):
        try:
            hints.setColorScheme(scheme.Dark if dark else scheme.Light)
        except (AttributeError, TypeError, RuntimeError):
            pass


_STATE = {"dark": False}


def is_dark() -> bool:
    """Включено тёмное оформление («Профессиональное»): окна-карточки обновления и сообщений берут тёмную карточку."""
    return bool(_STATE["dark"])


def apply_app(qapp, cfg):
    """Меню, подсказки и стандартные окна Qt в цветах оформления. Палитра задаётся всегда явно: тема системы
    (тёмная Windows, GNOME) не просачивается в окна программы."""
    from PyQt6.QtGui import QColor, QPalette
    t = tokens(cfg)
    _STATE["dark"] = bool(t["dark"])
    qapp.setStyle("Fusion")
    _color_scheme(qapp, t["dark"])
    if not t["dark"]:
        qapp.setPalette(light_palette())
        qapp.setStyleSheet("")
        return
    pal = light_palette()   # все роли заданы (у QPalette() по умолчанию палитра приложения, она может быть системной)
    roles = {
        QPalette.ColorRole.Window: t["dialog_bg"], QPalette.ColorRole.WindowText: t["text"],
        QPalette.ColorRole.Base: t["input_bg"], QPalette.ColorRole.AlternateBase: t["ui_panel"],
        QPalette.ColorRole.Text: t["text"], QPalette.ColorRole.Button: t["button_bg"],
        QPalette.ColorRole.ButtonText: t["button_text"], QPalette.ColorRole.ToolTipBase: "#2b2b2b",
        QPalette.ColorRole.ToolTipText: "#e6e6e6", QPalette.ColorRole.Highlight: t["ui_accent"],
        QPalette.ColorRole.HighlightedText: "#ffffff", QPalette.ColorRole.PlaceholderText: "#7a7a7a",
        QPalette.ColorRole.Link: LINK_DARK,   # 1.32: ссылки светлее акцента, 5,6:1 на тёмном
    }
    for role, color in roles.items():
        pal.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor("#6a6a6a"))
    qapp.setPalette(pal)
    qapp.setStyleSheet(f"""
QToolTip {{ background: #2b2b2b; color: #e6e6e6; border: 1px solid #454545; padding: 4px; }}
""")
