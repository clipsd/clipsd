# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
"""Выбор оформления при первом запуске: карточки-превью, клик сразу перекрашивает программу."""

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout

from . import themes
from .i18n import tr


def preview(ctx, key: str, width: int = 360) -> QPixmap:
    """Уменьшенная картинка окна редактора в оформлении key."""
    from . import icons
    from .app import demo_image
    from .editor import EditorWindow

    config = dict(ctx.config, ui_theme=key)
    for k in themes.COLOR_KEYS:
        config.pop(k, None)

    class _Ctx:
        icon = ctx.icon

        def copy_image(self, _i):
            pass

        def notify(self, _t):
            pass

        def save_config(self):
            pass

    preview_ctx = _Ctx()
    preview_ctx.config = config
    ed = EditorWindow(demo_image(), preview_ctx, QPoint(0, 0))
    w = max(1100, ed.minimumWidth())   # панель инструментов шире 1000: окно не должно быть уже неё (width: ширина превью)
    ed.resize(w, round(w * 0.68))
    ed.ensurePolished()
    pix = ed.grab()
    ed.deleteLater()
    icons.ICON_COLOR = themes.tokens(ctx.config)["icon"]   # вернуть цвет значков текущего оформления
    return pix.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)


class Card(QFrame):
    clicked = pyqtSignal(str)

    def __init__(self, key, pixmap):
        super().__init__()
        self.key = key
        self.setObjectName("themeCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        box = QVBoxLayout(self)
        box.setContentsMargins(12, 12, 12, 12)
        box.setSpacing(6)
        image = QLabel()
        image.setPixmap(pixmap)
        box.addWidget(image, 0, Qt.AlignmentFlag.AlignHCenter)   # превью по центру карточки
        # название крупно, пояснение в скобках мелкой строкой: подписи одинаковой высоты у обеих карточек
        full = themes.title(key)
        name, _sep, note = full.partition(" (")
        title = QLabel(name)
        title.setObjectName("cardTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(title)
        sub = QLabel(note.rstrip(")"))
        sub.setObjectName("cardNote")
        sub.setWordWrap(True)
        sub.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        sub.setMinimumHeight(2 * sub.fontMetrics().lineSpacing() + 2)
        box.addWidget(sub)

    def mousePressEvent(self, _event):
        self.clicked.emit(self.key)


class ThemeChooser(QDialog):
    """Клик по карточке: оформление применяется сразу (окно редактора за диалогом перекрашивается)."""

    def __init__(self, ctx, parent=None, on_change=None):
        super().__init__(parent)
        self.ctx = ctx
        self.on_change = on_change
        self.setWindowTitle(tr("theme_chooser.window_title"))
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)
        head = QLabel(tr("theme_chooser.head"))
        head.setObjectName("head")
        sub = QLabel(tr("theme_chooser.sub"))
        sub.setWordWrap(True)
        root.addWidget(head)
        root.addWidget(sub)
        row = QHBoxLayout()
        row.setSpacing(16)
        self.cards = {}
        for key in themes.THEMES:
            card = Card(key, preview(ctx, key))
            card.clicked.connect(self.choose)
            self.cards[key] = card
            row.addWidget(card, 1)   # карточки одинаковой ширины
        root.addLayout(row)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.ok = QPushButton(tr("theme_chooser.ok"))
        self.ok.setObjectName("primary")
        self.ok.setDefault(True)
        self.ok.clicked.connect(self.accept)
        buttons.addWidget(self.ok)
        root.addLayout(buttons)
        self._restyle()

    def choose(self, key):
        self.ctx.config["ui_theme"] = key
        for k in themes.COLOR_KEYS:          # свои цвета сбрасываются к цветам выбранного стиля
            self.ctx.config.pop(k, None)
        self.ctx.save_config()
        if self.on_change is not None:
            self.on_change()
        self._restyle()

    def _restyle(self):
        t = themes.tokens(self.ctx.config)
        current = themes.name(self.ctx.config)
        self.setStyleSheet(f"""
QDialog {{ background: {t['dialog_bg']}; }}
QLabel {{ color: {t['text']}; }}
QLabel#head {{ font-size: 20px; font-weight: bold; }}
QLabel#cardTitle {{ font-size: 16px; font-weight: bold; }}
QLabel#cardNote {{ font-size: 14px; color: {t['text_dim']}; }}
QFrame#themeCard {{ background: {t['card_bg']}; border: 3px solid {t['card_border']}; border-radius: 14px; }}
QFrame#themeCard:hover {{ border-color: {t['ui_accent']}; }}
QPushButton#primary {{ background: {t['ui_accent']}; color: white; border: none; border-radius: 8px;
    font-weight: bold; font-size: 14px; min-height: 36px; padding: 0 24px; }}
""")
        for key, card in self.cards.items():
            card.setStyleSheet(f"QFrame#themeCard {{ border: 3px solid {t['ui_accent']}; }}" if key == current else "")
