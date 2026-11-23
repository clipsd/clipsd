# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Окна чтения QR-кода (1.36): «Код на снимке» (текст кода целиком, «Открыть ссылку», «Скопировать текст кода») и
подтверждение «Открыть ссылку?» с адресом целиком. Сеть не используется, пока человек не подтвердил: адрес открывается
через sysenv.open_url только после «Открыть» и только если это адрес http или https (qr_read.web_url)."""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextOption
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget

from . import qr_read
from .dialogs import PALETTES, ClipDialog
from .i18n import tr


def _url_field(text: str, dark: bool) -> QPlainTextEdit:
    """Адрес или текст кода целиком: переносится в любом месте, выделяется и копируется, не обрезается."""
    box = QPlainTextEdit(text)
    box.setObjectName("clipReport")
    box.setReadOnly(True)
    box.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
    box.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    box.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    lines = max(1, min(6, text.count("\n") + 1 + len(text) // 46))
    box.setFixedHeight(box.fontMetrics().lineSpacing() * lines + 20)
    return box


class OpenLinkConfirm(ClipDialog):
    """«Открыть ссылку?»: адрес показан целиком; главная кнопка «Не открывать» (Enter и Esc), «Открыть» спокойная."""

    def __init__(self, parent, url: str):
        super().__init__(parent, tr("qr_chtenie.confirm_title"), "", "warning", 520)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        self.setModal(True)
        self.url = url
        self.opened = False
        self.text(tr("qr_chtenie.confirm_text"), "clipBody")
        self.address = _url_field(url, self.dark)
        self.body.addWidget(self.address)
        self.text(tr("qr_chtenie.confirm_note"), "clipHint")
        self.yes = self.secondary(tr("qr_chtenie.confirm_yes"))
        self.no = self.primary(tr("qr_chtenie.confirm_no"))
        self.yes.clicked.connect(self._open)
        self.no.clicked.connect(self.reject)
        self.no.setFocus()

    def _open(self):
        from . import sysenv
        self.opened = bool(qr_read.web_url(self.url)) and bool(sysenv.open_url(self.url) is not False)
        self.accept()


class QrDialog(ClipDialog):
    """«Код на снимке»: у каждого найденного кода его текст целиком и кнопки «Открыть ссылку» (только http и https) и
    «Скопировать текст кода»."""

    def __init__(self, parent, codes: list):
        n = len(codes)
        title = tr("qr_chtenie.title_one") if n == 1 else tr("qr_chtenie.title_many", n=n)
        super().__init__(parent, title, "", "info", 520)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        self.setModal(False)
        self.codes = list(codes)
        self.rows = []          # [(код, поле текста, кнопка «Открыть ссылку» или None, кнопка «Скопировать»)]
        self.confirm = None
        self.status = self.status_label()
        holder = QWidget()
        col = QVBoxLayout(holder)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(12)
        c = PALETTES[self.dark]
        for code in self.codes:
            card = QFrame()
            card.setObjectName("qrCode")
            card.setStyleSheet(f"QFrame#qrCode {{ background: {c['soft']}; border: 1px solid {c['edge']}; border-radius: 8px; }}")
            inner = QVBoxLayout(card)
            inner.setContentsMargins(10, 8, 10, 10)
            inner.setSpacing(8)
            kind = QLabel(code.kind)
            kind.setObjectName("clipHint")
            inner.addWidget(kind)
            field = _url_field(code.text, self.dark)
            inner.addWidget(field)
            buttons = QHBoxLayout()
            buttons.setSpacing(8)
            open_b = None
            if code.link:
                open_b = QPushButton(tr("qr_chtenie.open"))
                open_b.setObjectName("clipPrimary")
                open_b.setCursor(Qt.CursorShape.PointingHandCursor)
                open_b.clicked.connect(lambda _c=False, u=code.link: self.ask_open(u))
                buttons.addWidget(open_b)
            copy_b = QPushButton(tr("qr_chtenie.copy"))
            copy_b.setObjectName("clipSecondary")
            copy_b.setCursor(Qt.CursorShape.PointingHandCursor)
            copy_b.clicked.connect(lambda _c=False, t=code.text: self.copy_text(t))
            buttons.addWidget(copy_b)
            buttons.addStretch(1)
            inner.addLayout(buttons)
            if not code.link:
                note = QLabel(tr("qr_chtenie.not_link"))
                note.setObjectName("clipHint")
                note.setWordWrap(True)
                inner.addWidget(note)
            col.addWidget(card)
            self.rows.append((code, field, open_b, copy_b))
        if n > 2:   # много кодов: список прокручивается, окно не растёт выше экрана
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.Shape.NoFrame)
            area.setStyleSheet("QScrollArea { background: transparent; } QScrollArea > QWidget > QWidget { background: transparent; }")
            area.setWidget(holder)
            area.setMinimumHeight(300)
            self.body.addWidget(area)
        else:
            self.body.addWidget(holder)
        self.close_button = self.secondary(tr("qr_chtenie.close"))
        self.close_button.clicked.connect(self.close)
        self.close_button.setFocus()

    def copy_text(self, text: str):
        from . import ocr
        ocr.copy_text(text, self.parentWidget())
        self.show_status(self.status, tr("qr_chtenie.copied"), "ok")

    def ask_open(self, url: str):
        """«Открыть ссылку»: сначала подтверждение с адресом целиком, сеть только после «Открыть»."""
        if not qr_read.web_url(url):
            return False
        self.confirm = OpenLinkConfirm(self, url)
        self.confirm.exec()
        return self.confirm.opened
