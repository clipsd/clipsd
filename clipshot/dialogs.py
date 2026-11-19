# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
"""Окна ClipSD в одном стиле: карточка со скруглёнными углами и тенью, шапка со значком, заголовком и крестиком,
одна главная кнопка. Окно открывается по центру экрана, где мышь, перетаскивается за шапку, Esc закрывает."""

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter, QPixmap
from PyQt6.QtWidgets import (QDialog, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QLineEdit,
                             QPushButton, QToolButton, QVBoxLayout, QWidget)

from .i18n import tr
from .frame_extents import track_frame_extents, refresh_frame_extents

ACCENT = "#1e78ff"
LINK = "#1660d0"          # link text on the white card
GREEN = "#1f9d55"
TEXT = "#16181c"
MUTED = "#5a6270"
ICON_COLORS = {"warning": "#f59e0b", "mail": "#0d9488", "google": "#1e78ff", "info": "#1e78ff"}
ICON_GLYPHS = {"warning": "!", "mail": "@", "google": "G", "info": "i"}

STYLE = f"""
QFrame#clipCard {{ background: #ffffff; border: 1px solid #d9dee6; border-radius: 14px; }}
QLabel {{ color: {TEXT}; background: transparent; }}
QCheckBox, QRadioButton {{ color: {TEXT}; background: transparent; }}
QLabel#clipTitle {{ font-size: 17px; font-weight: bold; }}
QLabel#clipSubtitle {{ color: {MUTED}; font-size: 13px; }}
QLabel#clipNote {{ color: {MUTED}; font-size: 12px; }}
QLabel#clipFieldLabel {{ font-weight: bold; }}
QLineEdit {{ padding: 8px 10px; border: 1px solid #c8d0db; border-radius: 8px; font-size: 14px; background: #ffffff;
             color: {TEXT}; }}
QLineEdit:focus {{ border: 2px solid {ACCENT}; padding: 7px 9px; }}
QPushButton#clipPrimary {{ background: {GREEN}; color: white; font-weight: bold; font-size: 14px; padding: 9px 18px;
                           border: 1px solid #157a40; border-radius: 8px; }}
QPushButton#clipPrimary:hover {{ background: #26b864; }}
QPushButton#clipPrimary:disabled {{ background: #9fd3b4; border-color: #9fd3b4; }}
QPushButton#clipSecondary {{ background: #ffffff; color: {TEXT}; font-size: 14px; padding: 9px 16px;
                             border: 1px solid #c8d0db; border-radius: 8px; }}
QPushButton#clipSecondary:hover {{ background: #f1f4f8; }}
QPushButton#clipLink {{ background: transparent; color: {ACCENT}; border: none; font-size: 13px; padding: 4px 2px;
                        text-align: left; }}
QPushButton#clipLink:hover {{ text-decoration: underline; }}
QToolButton#clipClose {{ background: transparent; border: none; border-radius: 15px; color: {MUTED}; font-size: 16px; }}
QToolButton#clipClose:hover {{ background: #eef1f5; color: {TEXT}; }}
"""


def link_colored(text: str) -> str:
    """Rich text for the white card: links get the colour LINK. Without it a link takes the palette colour, which in the
    Professional theme or a dark system is a light blue (3.5:1 on white); LINK reads well (5.8:1)."""
    if "<a " in text and "style=" not in text:
        text = text.replace("<a ", f'<a style="color: {LINK};" ')
    return text


def icon_pixmap(kind: str, size: int = 44) -> QPixmap:
    """Круглый значок шапки: «!» предупреждение, «@» почта, «G» Google."""
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


class ClipDialog(QDialog):
    """Основа окон ClipSD. Наполнение: self.body (QVBoxLayout), кнопки: self.footer_left / self.footer_right."""

    SHADOW_MARGINS = (20, 16, 20, 24)   # поля под тень: слева, сверху, справа, снизу

    def __init__(self, parent=None, title: str = "", subtitle: str = "", icon: str = "info", width: int = 560):
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("ClipSD: " + title)
        self.setStyleSheet(STYLE)
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
        self.icon.setPixmap(icon_pixmap(icon))
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
        label = QLabel(link_colored(text))
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

    @staticmethod
    def show_status(label: QLabel, text: str, kind: str = "info"):
        color = {"ok": "#157a40", "error": "#b42318", "info": MUTED}.get(kind, MUTED)
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

    def open_centered(self):
        """Показать по центру экрана, где сейчас мышь, поверх всех окон."""
        self.adjustSize()
        track_frame_extents(self, self.frame_extents_margins)   # свойство ставится до показа окна
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        self.move(area.center().x() - self.width() // 2, area.center().y() - self.height() // 2)
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
