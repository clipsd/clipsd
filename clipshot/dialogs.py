# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Окна ClipSD в одном стиле: карточка со скруглёнными углами и тенью, шапка со значком, заголовком и крестиком,
одна главная кнопка. Окно открывается по центру экрана, где мышь, перетаскивается за шапку, Esc закрывает."""

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter, QPixmap
from PyQt6.QtWidgets import (QDialog, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QLineEdit,
                             QPushButton, QToolButton, QVBoxLayout, QWidget)

from .i18n import tr
from .frame_extents import track_frame_extents, refresh_frame_extents

from .themes import GREEN, GREEN_BORDER, GREEN_DISABLED, GREEN_HOVER, GREEN_PRESSED, LINK, LINK_DARK, TEAL   # 1.32: одни токены

ACCENT = "#1e78ff"
TEXT = "#16181c"
MUTED = "#5a6270"
# LINK (ссылка на белой карточке, #1660d0, 5,8:1) и GREEN теперь из themes: один источник для всей программы
ICON_COLORS = {"warning": "#f59e0b", "mail": TEAL, "google": "#1e78ff", "info": "#1e78ff", "star": "#f5a623",
               "error": "#c0392b", "ok": GREEN}   # 1.32: ошибка красным кругом, «готово» зелёным
ICON_GLYPHS = {"warning": "!", "mail": "@", "google": "G", "info": "i", "star": "★", "error": "!", "ok": "✓"}

PALETTES = {   # цвета карточки: светлая как раньше, тёмная по токенам тёмного оформления (win, s2, sep, t, t2)
    False: dict(card="#ffffff", edge="#d9dee6", text=TEXT, muted=MUTED, line="#c8d0db", field="#ffffff",
                soft="#f1f4f8", close_hover="#eef1f5", link=LINK, track="#e3e8ef", note_bg="#f5f6f8",
                warn_bg="#fff5d6", warn_edge="#efd27e", warn_text="#4a3a06", accent=ACCENT,
                handle="#b4bcc8", handle_hover="#8f99a8"),
    True: dict(card="#25282c", edge="#3a3f46", text="#f1f3f5", muted="#aab1ba", line="#4a5058", field="#1d2023",
               soft="#2f3338", close_hover="#2f3338", link=LINK_DARK, track="#3a3f46", note_bg="#2a2e33",
               warn_bg="#3a3016", warn_edge="#6b5619", warn_text="#f5e3b0", accent="#2d8ceb",
               handle="#5b626b", handle_hover="#7d8691"),
}


def style(dark: bool = False) -> str:
    """Таблица стилей окон-карточек. dark=True: тёмная карточка для оформления «Профессиональное» (1.32);
    старые окна ClipSD по-прежнему белые в обеих темах (STYLE)."""
    c = PALETTES[bool(dark)]
    return f"""
QFrame#clipCard {{ background: {c['card']}; border: 1px solid {c['edge']}; border-radius: 14px; }}
QLabel {{ color: {c['text']}; background: transparent; }}
QCheckBox, QRadioButton {{ color: {c['text']}; background: transparent; }}
QLabel#clipTitle {{ font-size: 17px; font-weight: bold; }}
QLabel#clipSubtitle {{ color: {c['muted']}; font-size: 13px; }}
QLabel#clipNote {{ color: {c['muted']}; font-size: 12px; }}
QLabel#clipFieldLabel {{ font-weight: bold; }}
QLineEdit {{ padding: 8px 10px; border: 1px solid {c['line']}; border-radius: 8px; font-size: 14px; background: {c['field']};
             color: {c['text']}; }}
QLineEdit:focus {{ border: 2px solid {c['accent']}; padding: 7px 9px; }}
QPushButton#clipPrimary {{ background: {GREEN}; color: white; font-weight: bold; font-size: 14px; padding: 9px 18px;
                           border: 1px solid {GREEN_BORDER}; border-radius: 8px; }}
QPushButton#clipPrimary:hover {{ background: {GREEN_HOVER}; }}
QPushButton#clipPrimary:pressed {{ background: {GREEN_PRESSED}; }}
QPushButton#clipPrimary:disabled {{ background: {GREEN_DISABLED}; border-color: {GREEN_DISABLED}; }}
QPushButton#clipSecondary {{ background: {c['card']}; color: {c['text']}; font-size: 14px; padding: 9px 16px;
                             border: 1px solid {c['line']}; border-radius: 8px; }}
QPushButton#clipSecondary:hover {{ background: {c['soft']}; }}
QPushButton#clipLink {{ background: transparent; color: {c['link']}; border: none; font-size: 13px; padding: 4px 2px;
                        text-align: left; }}
QPushButton#clipLink:hover {{ text-decoration: underline; }}
QToolButton#clipClose {{ background: transparent; border: none; border-radius: 15px; color: {c['muted']}; font-size: 16px; }}
QToolButton#clipClose:hover {{ background: {c['close_hover']}; color: {c['text']}; }}
QProgressBar#clipBar {{ border: none; border-radius: 3px; background: {c['track']}; max-height: 6px; min-height: 6px;
                        text-align: center; color: transparent; }}
QProgressBar#clipBar::chunk {{ background: {c['accent']}; border-radius: 3px; }}
QFrame#clipWarn {{ background: {c['warn_bg']}; border: 1px solid {c['warn_edge']}; border-radius: 8px; }}
QFrame#clipWarn QLabel {{ color: {c['warn_text']}; }}
QTextBrowser#clipNotes, QPlainTextEdit#clipReport {{ background: {c['note_bg']}; color: {c['text']};
                        border: 1px solid {c['edge']}; border-radius: 8px; padding: 6px 8px; font-size: 13px; }}
QPlainTextEdit#clipReport {{ font-family: "DejaVu Sans Mono", "Consolas", monospace; font-size: 12px; }}
QLabel#clipBullet {{ font-size: 14px; }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 3px 2px 3px 0; border: none; }}
QScrollBar::handle:vertical {{ background: {c['handle']}; border-radius: 4px; min-height: 36px; }}
QScrollBar::handle:vertical:hover {{ background: {c['handle_hover']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; border: none; background: none; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
"""


STYLE = style(False)


def link_colored(text: str, dark: bool = False) -> str:
    """Rich text for the white card: links get the colour LINK. Without it a link takes the palette colour, which in the
    Professional theme or a dark system is a light blue (3.5:1 on white); LINK reads well (5.8:1)."""
    if "<a " in text and "style=" not in text:
        text = text.replace("<a ", f'<a style="color: {LINK_DARK if dark else LINK};" ')
    return text


def icon_pixmap(kind: str, size: int = 44) -> QPixmap:
    """Круглый значок шапки: «!» предупреждение, «@» почта, «G» Google, «★» оценка."""
    ratio = 2
    pix = QPixmap(size * ratio, size * ratio)
    pix.setDevicePixelRatio(ratio)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = QColor(ICON_COLORS.get(kind, ACCENT))
    soft = QColor(color)
    soft.setAlpha(40)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(soft)
    p.drawEllipse(QRectF(0, 0, size, size))
    p.setBrush(color)
    p.drawEllipse(QRectF(6, 6, size - 12, size - 12))
    f = QFont()
    f.setBold(True)
    f.setPixelSize(int(size * 0.42))
    p.setFont(f)
    p.setPen(QColor("#ffffff"))
    p.drawText(QRectF(6, 6, size - 12, size - 12), Qt.AlignmentFlag.AlignCenter, ICON_GLYPHS.get(kind, "i"))
    p.end()
    return pix


def logo_pixmap(size: int = 44) -> QPixmap:
    """Значок программы для шапки окна, чётко на экранах с масштабом (рисуется с запасом ×2)."""
    from .icons import logo_pixmap as draw_logo
    ratio = 2
    pix = draw_logo(size * ratio)
    pix.setDevicePixelRatio(ratio)
    return pix


class ClipDialog(QDialog):
    """Основа окон ClipSD. Наполнение: self.body (QVBoxLayout), кнопки: self.footer_left / self.footer_right."""

    SHADOW_MARGINS = (20, 16, 20, 24)   # поля под тень: слева, сверху, справа, снизу

    def __init__(self, parent=None, title: str = "", subtitle: str = "", icon: str = "info", width: int = 560,
                 dark: bool = None, logo: bool = False):
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("ClipSD: " + title)
        if dark is None:   # 1.32: все окна-карточки следуют оформлению (тёмная карточка в «Профессиональном»)
            from . import themes
            dark = themes.is_dark()
        self.dark = bool(dark)
        self.setStyleSheet(style(self.dark))
        self._drag = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(*self.SHADOW_MARGINS)   # место под тень
        self.card = QFrame()
        self.card.setObjectName("clipCard")
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(32)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 90))
        self.card.setGraphicsEffect(shadow)
        self.card.setMinimumWidth(width)
        outer.addWidget(self.card)
        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(24, 20, 20, 22)
        lay.setSpacing(14)

        self.header = QWidget()
        head = QHBoxLayout(self.header)
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(14)
        self.icon = QLabel()
        self.icon.setPixmap(logo_pixmap(44) if logo else icon_pixmap(icon))
        self.icon.setFixedSize(44, 44)
        head.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title = QLabel(title)
        self.title.setObjectName("clipTitle")
        self.title.setWordWrap(True)
        self.subtitle = QLabel(subtitle)
        self.subtitle.setObjectName("clipSubtitle")
        self.subtitle.setWordWrap(True)
        self.subtitle.setVisible(bool(subtitle))
        titles.addWidget(self.title)
        titles.addWidget(self.subtitle)
        head.addLayout(titles, 1)
        self.close_b = QToolButton()
        self.close_b.setObjectName("clipClose")
        self.close_b.setText("✕")
        self.close_b.setFixedSize(30, 30)
        self.close_b.setToolTip(tr("dialogs.close_tip"))
        self.close_b.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_b.clicked.connect(self.close)
        head.addWidget(self.close_b, 0, Qt.AlignmentFlag.AlignTop)
        self.header.setCursor(Qt.CursorShape.OpenHandCursor)
        self.header.installEventFilter(self)
        lay.addWidget(self.header)

        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        lay.addLayout(self.body)
        footer = QHBoxLayout()
        footer.setSpacing(10)
        self.footer_left = QHBoxLayout()
        self.footer_right = QHBoxLayout()
        self.footer_right.setSpacing(10)
        footer.addLayout(self.footer_left)
        footer.addStretch(1)
        footer.addLayout(self.footer_right)
        lay.addSpacing(4)
        lay.addLayout(footer)

    # --- наполнение -------------------------------------------------------------

    def text(self, text: str, name: str = None) -> QLabel:
        label = QLabel(link_colored(text, self.dark))
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.RichText if "<" in text else Qt.TextFormat.PlainText)
        if name:
            label.setObjectName(name)
        self.body.addWidget(label)
        return label

    def field(self, label: str, value: str = "", placeholder: str = "") -> QLineEdit:
        """Подпись и поле ввода с кнопкой «Вставить» справа."""
        cap = QLabel(label)
        cap.setObjectName("clipFieldLabel")
        self.body.addWidget(cap)
        row = QHBoxLayout()
        row.setSpacing(8)
        edit = QLineEdit(value)
        edit.setPlaceholderText(placeholder)
        paste = QPushButton(tr("dialogs.paste"))
        paste.setObjectName("clipSecondary")
        paste.setToolTip(tr("dialogs.paste_tip"))
        paste.clicked.connect(lambda: edit.setText(QGuiApplication.clipboard().text().strip()))
        row.addWidget(edit, 1)
        row.addWidget(paste)
        self.body.addLayout(row)
        edit.paste_button = paste
        return edit

    def status_label(self) -> QLabel:
        label = QLabel("")
        label.setWordWrap(True)
        label.setVisible(False)
        self.body.addWidget(label)
        return label

    def show_status(self, label: QLabel, text: str, kind: str = "info"):
        palette = PALETTES[self.dark]
        ok, error = ("#5fd08a", "#ff8a80") if self.dark else ("#157a40", "#b42318")
        color = {"ok": ok, "error": error, "info": palette["muted"]}.get(kind, palette["muted"])
        label.setStyleSheet(f"QLabel {{ color: {color}; font-weight: {'bold' if kind != 'info' else 'normal'}; }}")
        label.setText(text)
        label.setVisible(bool(text))

    def _button(self, text: str, name: str, side: str) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName(name)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        (self.footer_left if side == "left" else self.footer_right).addWidget(b)
        return b

    def primary(self, text: str) -> QPushButton:
        b = self._button(text, "clipPrimary", "right")
        b.setDefault(True)
        return b

    def secondary(self, text: str) -> QPushButton:
        return self._button(text, "clipSecondary", "right")

    def link(self, text: str) -> QPushButton:
        return self._button(text, "clipLink", "left")

    # --- поведение --------------------------------------------------------------

    def place_centered(self):
        """Поставить по центру экрана, где сейчас мышь (без показа: окно потом показывает exec() или show())."""
        self.adjustSize()
        track_frame_extents(self, self.frame_extents_margins)   # свойство ставится до показа окна
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        self.move(area.center().x() - self.width() // 2, area.center().y() - self.height() // 2)

    def open_centered(self):
        """Показать по центру экрана, где сейчас мышь, поверх всех окон."""
        self.place_centered()
        self.show()
        self.raise_()
        self.activateWindow()

    def showEvent(self, event):
        super().showEvent(event)
        track_frame_extents(self, self.frame_extents_margins)   # менеджеру окон: видимая часть без поля тени

    def frame_extents_margins(self):
        """Поля под тень по фактическим отступам карточки от края окна: (слева, справа, сверху, снизу)."""
        m = self.layout().contentsMargins()
        return (m.left(), m.right(), m.top(), m.bottom())

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        if obj is self.header:
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                handle = self.windowHandle()
                if handle is not None and handle.startSystemMove():
                    return True
                self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                return True
            if event.type() == QEvent.Type.MouseMove and self._drag is not None:
                self.move(event.globalPosition().toPoint() - self._drag)
                return True
            if event.type() == QEvent.Type.MouseButtonRelease:
                self._drag = None
        return False

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)


class MessageCard(ClipDialog):
    """Короткое сообщение в стиле окон ClipSD вместо стандартного окошка Qt с «OK» и жёлтым треугольником (1.32).

    Значок, заголовок, понятный текст, одна главная кнопка (по умолчанию «Понятно»), при желании вторая спокойная.
    После закрытия choice: "primary", "secondary" или "close" (крестик, Esc). Тёмная карточка при тёмном оформлении."""

    def __init__(self, parent, title: str, text: str, icon: str = "info", primary: str = None, secondary: str = None,
                 subtitle: str = "", modal: bool = True, width: int = 480, logo: bool = False, dark: bool = None):
        from . import themes
        super().__init__(parent, title, subtitle, icon, width, dark=themes.is_dark() if dark is None else dark, logo=logo)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, parent is None)
        self.setModal(modal)
        self.choice = "close"
        self.message_text = text
        self.message = self.text(text)
        self.secondary_button = self.secondary(secondary) if secondary else None
        self.primary_button = self.primary(primary or tr("dialogs.ok"))
        self.primary_button.clicked.connect(lambda: self._pick("primary"))
        if self.secondary_button is not None:
            self.secondary_button.clicked.connect(lambda: self._pick("secondary"))
        self.primary_button.setFocus()

    def _pick(self, choice: str):
        self.choice = choice
        self.accept()

    def showEvent(self, event):
        super().showEvent(event)
        if self.parentWidget() is not None:   # над окном, из которого открыто
            frame = self.frameGeometry()
            frame.moveCenter(self.parentWidget().frameGeometry().center())
            self.move(frame.topLeft())
