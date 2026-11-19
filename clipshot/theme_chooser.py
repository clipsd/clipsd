# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Выбор оформления при первом запуске: карточки-превью, клик сразу перекрашивает программу."""

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout

from . import themes
from .dialogs import PALETTES, ClipDialog, style
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
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        box = QVBoxLayout(self)
        box.setContentsMargins(12, 12, 12, 12)
        box.setSpacing(6)
        image = QLabel()
        image.setPixmap(pixmap)
        box.addWidget(image, 0, Qt.AlignmentFlag.AlignHCenter)   # превью по центру карточки
        self.setFixedWidth(round(pixmap.width() / pixmap.devicePixelRatio()) + 30)   # обе карточки точно одной ширины
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


class ThemeChooser(ClipDialog):
    """Клик по карточке: оформление применяется сразу (окно редактора за диалогом перекрашивается).
    1.32: окно-карточка в общем стиле ClipSD, зелёная «Продолжить», карточка сама темнеет вместе с оформлением."""

    def __init__(self, ctx, parent=None, on_change=None):
        t = themes.tokens(ctx.config)
        super().__init__(parent, tr("theme_chooser.head"), tr("theme_chooser.sub"), "info", 700, dark=t["dark"], logo=True)
        self.ctx = ctx
        self.on_change = on_change
        self.setWindowTitle(tr("theme_chooser.window_title"))
        if parent is not None:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        self.setModal(True)
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addStretch(1)
        self.cards = {}
        for key in themes.THEMES:
            card = Card(key, preview(ctx, key))
            card.clicked.connect(self.choose)
            self.cards[key] = card
            row.addWidget(card)   # карточки точно одной ширины, по центру окна
        row.addStretch(1)
        self.body.addLayout(row)
        self.ok = self.primary(tr("theme_chooser.ok"))
        self.ok.clicked.connect(self.accept)
        self._restyle()

    def showEvent(self, event):
        super().showEvent(event)
        if self.parentWidget() is not None:
            frame = self.frameGeometry()
            frame.moveCenter(self.parentWidget().frameGeometry().center())
            self.move(frame.topLeft())

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
        self.dark = bool(t["dark"])
        c = PALETTES[self.dark]
        self.setStyleSheet(style(self.dark) + f"""
QLabel#cardTitle {{ font-size: 16px; font-weight: bold; }}
QLabel#cardNote {{ font-size: 14px; color: {c['muted']}; }}
QFrame#themeCard {{ background: {c['note_bg']}; border: 2px solid {c['edge']}; border-radius: 10px; }}
QFrame#themeCard:hover {{ border-color: {c['accent']}; }}
""")
        for key, card in self.cards.items():
            card.setStyleSheet(f"QFrame#themeCard {{ border: 3px solid {c['accent']}; }}" if key == current else "")
