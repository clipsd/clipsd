# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
"""Окна подключения сервисов перевода (в общем стиле ClipSD, dialogs.ClipDialog):
почта для MyMemory (50 000 знаков в день) и ключ Google Cloud (500 000 знаков в месяц)."""

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QGuiApplication
from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from .dialogs import ACCENT, ClipDialog
from .i18n import tr

_open = []


def _keep(dlg):
    _open.append(dlg)
    dlg.destroyed.connect(lambda *_: _open.remove(dlg) if dlg in _open else None)
    return dlg


class MyMemoryEmailDialog(ClipDialog):
    """Почта для MyMemory: лимит перевода 50 000 знаков в день вместо 5 000, без регистрации.
    reason="limit": открылось само, потому что бесплатный лимит на сегодня закончился; wait: когда обновится."""

    def __init__(self, parent=None, cfg: dict = None, save=None, on_saved=None, reason: str = "upgrade", wait: str = ""):
        from . import translate
        limit = reason == "limit"
        if limit:
            title = tr("service_setup.limit_title")
            subtitle = tr("service_setup.limit_sub_wait", wait=wait) if wait else tr("service_setup.limit_sub")
            icon = "warning"
        else:
            title = tr("service_setup.email_title")
            subtitle = tr("service_setup.email_sub")
            icon = "mail"
        super().__init__(parent, title, subtitle, icon, 660)
        self.translate = translate
        self.cfg, self.save, self.on_saved, self.reason = cfg if cfg is not None else {}, save, on_saved, reason
        self.text(tr("service_setup.email_text"))
        self.email = self.field(tr("service_setup.email_field"), self.cfg.get("translate_email", ""), tr("service_setup.email_placeholder"))
        self.email.returnPressed.connect(self.save_email)
        self.status = self.status_label()
        self.text(tr("service_setup.email_privacy"), "clipNote")
        self.text(translate.usage_line(self.cfg, "mymemory"), "clipNote")
        self.google_b = self.link(tr("service_setup.google_instead")) if limit else None
        if self.google_b is not None:
            self.google_b.clicked.connect(self._google)
        self.remove_b = self.link(tr("service_setup.remove_email"))
        self.remove_b.setVisible(bool(self.cfg.get("translate_email", "").strip()) and not limit)
        self.remove_b.clicked.connect(self.remove)
        self.secondary(tr("about.close")).clicked.connect(self.close)
        self.save_b = self.primary(tr("service_setup.save_translate") if limit else tr("settings.save"))
        self.save_b.setMinimumWidth(self.save_b.sizeHint().width())   # надпись главной кнопки всегда целиком
        self.save_b.clicked.connect(self.save_email)
        self.email.setFocus()

    def save_email(self):
        """Проверить почту пробным переводом (MyMemory сразу скажет, принял ли её), сохранить, закрыть."""
        email = self.email.text().strip()
        if not self.translate.looks_like_email(email):
            self.show_status(self.status, tr("service_setup.bad_email"), "error")
            return
        self.save_b.setEnabled(False)
        self.show_status(self.status, tr("service_setup.checking_email"), "info")

        def done(error):
            try:
                self.save_b.setEnabled(True)
                if error:
                    self.show_status(self.status, error, "error")
                    return
                self._apply(email)
                self.close()
            except RuntimeError:   # окно уже закрыто
                pass
        self.translate.check_mymemory_email(email, done)

    def _apply(self, email: str):
        self.cfg["translate_email"] = email
        if self.cfg.get("translate_engine") != "google":
            self.cfg["translate_engine"] = "mymemory"
        if callable(self.save):
            self.save()
        if callable(self.on_saved):
            self.on_saved()

    def remove(self):
        self.email.setText("")
        self._apply("")
        self.close()

    def _google(self):
        cfg, save, on_saved = self.cfg, self.save, self.on_saved
        self.close()
        open_google_setup(None, cfg, save, on_saved)


class GoogleSetupDialog(ClipDialog):
    """Подключение Google Cloud: шаги с кнопками на нужные страницы, поле для ключа, проверка и сохранение."""

    def __init__(self, parent=None, cfg: dict = None, save=None, on_saved=None):
        from . import translate
        super().__init__(parent, tr("service_setup.google_title"), tr("service_setup.google_sub"), "google", 820)
        self.translate = translate
        self.cfg, self.save, self.on_saved = cfg if cfg is not None else {}, save, on_saved
        self.text(tr("service_setup.google_text"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        self.step_buttons = []
        for i, (text, caption, url) in enumerate(translate.GOOGLE_STEPS):
            num = QLabel(str(i + 1))
            num.setFixedSize(28, 28)
            num.setAlignment(Qt.AlignmentFlag.AlignCenter)
            num.setStyleSheet(f"QLabel {{ background: {ACCENT}; color: white; border-radius: 14px; font-weight: bold; }}")
            label = QLabel(tr(text))
            label.setWordWrap(True)
            label.setFixedWidth(400)   # постоянная ширина: высота строк с переносом считается правильно, текст не режется
            label.setMinimumHeight(label.heightForWidth(400))
            open_b = QPushButton(tr(caption))
            open_b.setObjectName("clipSecondary")
            open_b.setCursor(Qt.CursorShape.PointingHandCursor)
            open_b.clicked.connect(lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u)))
            copy_b = QPushButton(tr("service_setup.copy_link"))
            copy_b.setObjectName("clipSmall")
            copy_b.setStyleSheet("QPushButton#clipSmall { font-size: 14px; padding: 4px 12px; min-height: 26px;"
                                 " border-radius: 8px; background: #ffffff; border: 1px solid #c8d0db; }"
                                 " QPushButton#clipSmall:hover { background: #f1f4f8; }")   # маленькая светлая кнопка, не текст-ссылка
            copy_b.setCursor(Qt.CursorShape.PointingHandCursor)
            open_b.setFixedHeight(36)
            copy_b.setFixedHeight(36)   # обе кнопки шага одной высоты, на одной линии
            copy_b.clicked.connect(lambda _=False, u=url, b=copy_b: self._copy(u, b))
            grid.addWidget(num, i, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(label, i, 1)
            grid.addWidget(open_b, i, 2, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(copy_b, i, 3, Qt.AlignmentFlag.AlignTop)
            self.step_buttons.append((open_b, copy_b, url))
        # шаг 5: тот же кружок, что у шагов 1-4, подпись и поле ключа с кнопкой «Вставить»
        n = len(translate.GOOGLE_STEPS)
        num = QLabel(str(n + 1))
        num.setFixedSize(28, 28)
        num.setAlignment(Qt.AlignmentFlag.AlignCenter)
        num.setStyleSheet(f"QLabel {{ background: {ACCENT}; color: white; border-radius: 14px; font-weight: bold; }}")
        grid.addWidget(num, n, 0, Qt.AlignmentFlag.AlignTop)
        box = QVBoxLayout()
        box.setSpacing(6)
        cap = QLabel(tr("service_setup.key_caption"))
        cap.setObjectName("clipFieldLabel")
        box.addWidget(cap)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.key = QLineEdit(translate.load_google_key())
        self.key.setPlaceholderText(tr("service_setup.key_placeholder"))
        paste = QPushButton(tr("service_setup.paste"))
        paste.setObjectName("clipSecondary")
        paste.setToolTip(tr("service_setup.paste_tip"))
        paste.clicked.connect(lambda: self.key.setText(QGuiApplication.clipboard().text().strip()))
        row.addWidget(self.key, 1)
        row.addWidget(paste)
        box.addLayout(row)
        self.key.paste_button = paste
        grid.addLayout(box, n, 1, 1, 3)
        self.body.addLayout(grid)
        self.key.returnPressed.connect(self.save_and_use)
        self.status = self.status_label()
        self.secondary(tr("about.close")).clicked.connect(self.close)
        self.save_b = self.primary(tr("service_setup.check_save"))
        self.save_b.clicked.connect(self.save_and_use)

    def _copy(self, url, button):
        from . import ocr
        ocr.copy_text(url)
        button.setText(tr("service_setup.copied"))
        ocr.toast(self, tr("service_setup.link_copied"))

    def save_and_use(self):
        key = self.key.text().strip()
        if not key:
            self.show_status(self.status, tr("service_setup.key_empty"), "error")
            return
        if not self.translate.looks_like_google_key(key):
            self.show_status(self.status, tr("service_setup.key_bad_form"),
                             "error")
            return
        self.save_b.setEnabled(False)
        self.show_status(self.status, tr("service_setup.checking_key"), "info")

        def done(error):
            try:
                self.save_b.setEnabled(True)
                if error:
                    self.show_status(self.status, tr("service_setup.key_failed", error=error), "error")
                    return
                self.translate.save_google_key(key)
                self.cfg["translate_engine"] = "google"
                if callable(self.save):
                    self.save()
                if callable(self.on_saved):
                    self.on_saved()
                self.close()
            except RuntimeError:
                pass
        self.translate.check_google_key(key, done)


def open_mymemory_email(parent=None, cfg=None, save=None, on_saved=None, reason="upgrade", wait=""):
    """Окно почты по центру экрана; если уже открыто, поднимается то же."""
    for dlg in _open:
        if isinstance(dlg, MyMemoryEmailDialog) and dlg.isVisible():   # закрытое окно удаляется не сразу: не брать его
            dlg.raise_()
            dlg.activateWindow()
            return dlg
    dlg = _keep(MyMemoryEmailDialog(parent, cfg, save, on_saved, reason, wait))
    dlg.open_centered()
    return dlg


def open_google_setup(parent=None, cfg=None, save=None, on_saved=None):
    for dlg in _open:
        if isinstance(dlg, GoogleSetupDialog) and dlg.isVisible():   # закрытое окно удаляется не сразу: не брать его
            dlg.raise_()
            dlg.activateWindow()
            return dlg
    dlg = _keep(GoogleSetupDialog(parent, cfg, save, on_saved))
    dlg.open_centered()
    return dlg
