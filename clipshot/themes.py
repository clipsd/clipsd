# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
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
        "ui_accent": "#1e78ff", "ui_panel": "#d9dbdf", "ui_field": "#3a3d42", "ui_frame": 8,
        "text": "#1c1f24", "text_dim": "#3d4046", "stage": "#4a4d52", "image_frame": "#1b1d21",
        "button_bg": "#ffffff", "button_border": "#b9b9b9", "button_hover": "#eef3fb", "button_text": "#1c1f24",
        "icon": "#2e3436", "swatch_check": "#111111", "radius": 6, "font": 14, "flat_frame": False,
        "dialog_bg": "#e4e6e9", "card_bg": "#f6f7f8", "card_border": "#c9ccd1", "input_bg": "#ffffff",
        "confirm_bg": "#fafafa", "confirm_text": "#222222", "confirm_dim": "#555555", "confirm_line": "#dcdcdc",
        "confirm_hover": "#ececec", "dark": False,
    }),
    "pro": _Preset({
        "title": "themes.pro",
        "ui_accent": "#2d8ceb", "ui_panel": "#232323", "ui_field": "#121212", "ui_frame": 4,
        "text": "#c8c8c8", "text_dim": "#9a9a9a", "stage": "#1a1a1a", "image_frame": "#000000",
        "button_bg": "#2e2e2e", "button_border": "#3c3c3c", "button_hover": "#383838", "button_text": "#d6d6d6",
        "icon": "#c8c8c8", "swatch_check": "#ffffff", "radius": 2, "font": 13, "flat_frame": True,
        "dialog_bg": "#1e1e1e", "card_bg": "#262626", "card_border": "#3a3a3a", "input_bg": "#1a1a1a",
        "confirm_bg": "#2a2a2a", "confirm_text": "#e0e0e0", "confirm_dim": "#a8a8a8", "confirm_line": "#3c3c3c",
        "confirm_hover": "#343434", "dark": True,
    }),
}


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


def apply_app(qapp, cfg):
    """Меню, подсказки и стандартные окна Qt в цветах оформления. Палитра задаётся всегда явно: тема системы
    (тёмная Windows, GNOME) не просачивается в окна программы."""
    from PyQt6.QtGui import QColor, QPalette
    t = tokens(cfg)
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
        QPalette.ColorRole.Link: t["ui_accent"],
    }
    for role, color in roles.items():
        pal.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor("#6a6a6a"))
    qapp.setPalette(pal)
    qapp.setStyleSheet(f"""
QToolTip {{ background: #2b2b2b; color: #e6e6e6; border: 1px solid #454545; padding: 4px; }}
""")
