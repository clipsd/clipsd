# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Окна обновления в стиле окон ClipSD (1.32): карточка со значком программы, понятный заголовок, одна зелёная главная
кнопка, спокойные второстепенные, светлая и тёмная карточка по оформлению. Только вид: когда и какое окно показывать,
решает updater.py и update_prompt.py, они не менялись. Здесь окно предложения («Доступна версия N»), загрузка и установка,
«Что нового», «не установилась», отчёт об ошибке. Имена кнопок и полей те же, что были у прежних окон."""

import html
import re

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar, QPushButton, QTextBrowser, QVBoxLayout

from . import i18n, sysenv, themes
from .dialogs import ClipDialog, MessageCard, icon_pixmap
from .i18n import tr

NOTE_ITEMS = 3            # сколько изменений показывать в окне сразу
NOTE_CHARS = 120          # длиннее одной строки не делаем: обрезаем по слову


def _dark() -> bool:
    return themes.is_dark()


def notes_browser(markdown: str) -> QTextBrowser:
    """Полные заметки о версии: ссылки открываются через sysenv.open_url (чистое окружение)."""
    view = QTextBrowser()
    view.setObjectName("clipNotes")
    view.setOpenLinks(False)
    view.anchorClicked.connect(sysenv.open_url)
    view.setMarkdown(markdown or tr("updater.notes.none"))
    view.setMinimumSize(460, 200)
    return view


def note_headlines(markdown: str, limit: int = NOTE_ITEMS, chars: int = NOTE_CHARS) -> list:
    """Первые изменения из заметок короткими строками: первое предложение пункта списка, длинное обрезается по слову."""
    out = []
    for line in (markdown or "").splitlines():
        m = re.match(r"\s*[-*+]\s+(.*\S)", line)
        if not m:
            continue
        item = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", m.group(1))
        item = re.sub(r"[*_`]", "", item).strip()
        parts = re.split(r"(?<=[.!?])\s+|(?<=。)\s*", item, maxsplit=1)
        sentence = parts[0].strip()
        # «С телефона. QR-код стал крупнее…»: короткое первое «предложение» это тема, а не смысл (владелец 23.11.2026:
        # «там просто «С телефона», вообще ни о чём не говорит»). Тогда «Тема: следующее предложение».
        topic = sentence.rstrip(".。")
        if len(parts) > 1 and parts[1].strip() and len(topic) <= 26 and len(topic.split()) <= 4:
            rest = re.split(r"(?<=[.!?。])\s", parts[1].strip(), maxsplit=1)[0].strip()
            if (rest[:1].isupper() and not rest[1:2].isupper() and i18n.current() not in ("de", "tr")
                    and not rest.startswith(("Windows", "Linux", "Microsoft", "ClipSD", "GNOME", "Tesseract"))):
                rest = rest[0].lower() + rest[1:]
            sentence = topic + ("：" if sentence.endswith("。") else ": ") + rest
        if len(sentence) > chars:
            sentence = sentence[:chars].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
        if sentence:
            out.append(sentence)
        if len(out) >= limit:
            break
    return out


class OfferDialog(ClipDialog):
    """«Доступна версия N»: значок программы, что нового, «Обновить» / «Позже» / «Пропустить эту версию»."""

    def __init__(self, manifest, installed: str, parent=None, critical=None):
        self.critical = manifest.critical if critical is None else bool(critical)
        super().__init__(parent, tr("updater.offer.heading", version=manifest.version), tr("updater.offer.installed", current=installed),
                         "info", 540, dark=_dark(), logo=not self.critical)
        if self.critical:
            self.icon.setPixmap(icon_pixmap("warning"))
        self.choice = "later"
        self.setWindowTitle(tr("updater.offer.title_security" if self.critical else "updater.offer.title"))
        notes = manifest.notes_for(i18n.current())
        if self.critical:
            bar = QFrame()
            bar.setObjectName("clipWarn")
            box = QVBoxLayout(bar)
            box.setContentsMargins(14, 10, 14, 12)
            box.setSpacing(4)
            head = QLabel("<b>" + html.escape(tr("updater.offer.security_head")) + "</b>")
            head.setObjectName("security")
            box.addWidget(head)
            for key in ("updater.offer.security", "updater.offer.security_later"):
                label = QLabel(tr(key))
                label.setWordWrap(True)
                box.addWidget(label)
            self.body.addWidget(bar)
        else:
            self.text(tr("updater.offer.lead"))
        self.headlines = note_headlines(notes)   # решение владельца 19.11.2026: три главных изменения в окне
        if self.headlines:
            heading = QLabel(tr("updater.offer.whatsnew"))
            heading.setObjectName("clipFieldLabel")
            self.body.addWidget(heading)
            for line in self.headlines:
                bullet = QLabel("•  " + line)
                bullet.setObjectName("clipBullet")
                bullet.setWordWrap(True)
                bullet.setTextFormat(Qt.TextFormat.PlainText)
                self.body.addWidget(bullet)
        self.notes_view = notes_browser(notes)
        self.notes_view.setVisible(False)
        self.notes_link = QPushButton()
        self.notes_link.setObjectName("clipLink")
        self.notes_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self._link_texts = ((tr("updater.offer.show_notes") if self.headlines else tr("updater.offer.whatsnew") + " ›"),
                            tr("updater.offer.hide_notes"))   # без списка (заметки не в виде пунктов) ссылка «Что нового ›»
        self.notes_link.setText(self._link_texts[0])
        self.notes_link.clicked.connect(self._toggle_notes)
        link_row = QHBoxLayout()
        link_row.addWidget(self.notes_link)
        link_row.addStretch(1)
        self.body.addLayout(link_row)
        self.body.addWidget(self.notes_view)
        self.skip_button = self.link(tr("updater.button.skip"))
        self.later_button = self.secondary(tr("updater.button.later"))
        self.update_button = self.primary(tr("updater.button.update"))
        self.skip_button.setVisible(not self.critical)   # a security fix can be postponed, not skipped
        self.skip_button.clicked.connect(lambda: self._done("skip"))
        self.later_button.clicked.connect(lambda: self._done("later"))
        self.update_button.clicked.connect(lambda: self._done("update"))

    def _toggle_notes(self):
        show = not self.notes_view.isVisible()
        self.notes_view.setVisible(show)
        self.notes_link.setText(self._link_texts[1 if show else 0])
        self.adjustSize()

    def _done(self, choice):
        self.choice = choice
        self.accept()


class ProgressDialog(ClipDialog):
    """Загрузка версии N: тонкая полоса, «23,0 из 59,0 МБ · 38%», «Можно продолжать работу», «Отмена»."""

    def __init__(self, version: str, on_cancel, parent=None):
        super().__init__(parent, tr("updater.download.title", version=version), tr("updater.progress.sub"), "info", 460,
                         dark=_dark(), logo=True)
        self.setWindowTitle(tr("updater.offer.title"))
        self.heading = self.title
        self.bar = QProgressBar()
        self.bar.setObjectName("clipBar")
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.body.addWidget(self.bar)
        self.status = QLabel("")
        self.status.setObjectName("clipNote")
        self.body.addWidget(self.status)
        self.cancel_button = self.secondary(tr("updater.button.cancel"))
        self.cancel_button.clicked.connect(on_cancel)
        # 1.32.3 (Г2 проверки гонок): Esc и крестик только убирают окно, загрузка идёт дальше («Можно продолжать
        # работу»); отменяет кнопка «Отмена». Раньше Esc закрывал и удалял окно, а загрузка продолжала слать в него
        # прогресс: программа падала на следующем шаге.
        self.close_b.clicked.disconnect()
        self.close_b.clicked.connect(self.hide)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)

    def set_progress(self, done: int, total: int):
        percent = int(done * 100 / total) if total else 0
        self.bar.setValue(percent)
        mb = 1024 * 1024
        self.status.setText(tr("updater.download.progress_pct", done=f"{done / mb:.1f}", total=f"{total / mb:.1f}",
                               percent=percent))

    def set_stage(self, text: str):
        """After the download: the same window says what happens now (installing, ClipSD restarts by itself);
        the bar runs without a percentage and there is nothing to cancel any more."""
        self.heading.setText(text)
        self.subtitle.hide()
        self.bar.setRange(0, 0)
        self.status.setText("")
        self.status.hide()
        self.cancel_button.hide()


class WhatsNewDialog(ClipDialog):
    """После обновления: «ClipSD обновлён до версии N», заметки, «Готово»."""

    def __init__(self, version: str, markdown: str, parent=None):
        super().__init__(parent, tr("updater.whatsnew.head", version=version), tr("updater.whatsnew.title", version=version),
                         "ok", 560, dark=_dark(), logo=True)
        self.setWindowTitle(tr("updater.whatsnew.title", version=version))
        self.notes_view = notes_browser(markdown)
        self.notes_view.setMinimumSize(480, 240)
        self.body.addWidget(self.notes_view)
        self.ok = self.primary(tr("updater.button.done"))
        self.ok.clicked.connect(self.accept)


class ReportDialog(ClipDialog):
    """Отчёт об ошибке обновления: точный текст, «Скопировать», страница сообщения об ошибке, письмо; «Отправить»
    только когда задан приёмник (REPORT_ENDPOINT, 1.32)."""

    def __init__(self, report: str, title: str, parent=None, open_url=None, endpoint=None, sender=None):
        from . import updater
        super().__init__(parent, tr("updater.report.title"), "", "info", 740, dark=_dark())
        self.report, self.title_text = report, title
        self.endpoint = updater.REPORT_ENDPOINT if endpoint is None else endpoint
        self._open_url = open_url or sysenv.open_url
        self._sender = sender or updater.send_report
        self.text(tr("updater.report.hint"), "clipNote")
        self.text_view = QPlainTextEdit(report)
        self.text_view.setObjectName("clipReport")
        self.text_view.setReadOnly(True)
        self.text_view.setMinimumSize(540, 240)
        self.body.addWidget(self.text_view)
        self.status = self.status_label()
        self.issue_button = self.link(tr("updater.button.open_issue"))
        self.mail_button = self.link(tr("updater.button.email"))
        self.close_button = self.secondary(tr("updater.button.close"))
        send_main = bool(self.endpoint)   # с приёмником главная «Отправить», без него «Скопировать»
        self.copy_button = self.secondary(tr("updater.button.copy")) if send_main else self.primary(tr("updater.button.copy"))
        self.send_button = self.primary(tr("updater.button.send")) if send_main else self.secondary(tr("updater.button.send"))
        self.send_button.setVisible(send_main)
        self.copy_button.clicked.connect(self.copy)
        self.issue_button.clicked.connect(lambda: self._open_url(self.issue_url()))
        self.mail_button.clicked.connect(lambda: self._open_url(self.mail_url()))
        self.send_button.clicked.connect(self.send)
        self.close_button.clicked.connect(self.accept)

    def issue_url(self) -> str:
        from . import updater
        return updater.issue_url(self.title_text, self.report)

    def mail_url(self) -> str:
        from . import updater
        return updater.mail_url("ClipSD: " + self.title_text, self.report)

    def copy(self):
        QGuiApplication.clipboard().setText(self.report)
        self.show_status(self.status, tr("updater.report.copied"), "ok")

    def send(self) -> bool:
        ok = self._sender(self.report, self.title_text, self.endpoint)
        self.show_status(self.status, tr("updater.report.sent" if ok else "updater.report.send_failed"),
                         "ok" if ok else "error")
        if ok:
            self.send_button.setEnabled(False)
        return ok


class FailedDialog(ClipDialog):
    """Обновление не встало: красный значок, что случилось, что продолжает работать, «Повторить» / «Закрыть» и ссылка
    «Отчёт об ошибке…» (закрыто = «Закрыть»)."""

    def __init__(self, version: str, report: str, title: str, parent=None, open_url=None, hint: str = ""):
        super().__init__(parent, tr("updater.failed.title", version=version), "", "error", 520, dark=_dark())
        self.setWindowTitle(tr("updater.offer.title"))
        self.choice = "close"
        self.report, self.title_text, self._open_url = report, title, open_url
        self.report_dialog = None
        self.text(tr("updater.failed.text"), "text")
        if hint:   # what to do for this reason (FAILURE_HINTS), e.g. install by hand when systemd-run is missing
            bar = QFrame()
            bar.setObjectName("clipWarn")
            box = QVBoxLayout(bar)
            box.setContentsMargins(14, 10, 14, 12)
            note = QLabel(hint)
            note.setObjectName("hint")
            note.setWordWrap(True)
            box.addWidget(note)
            self.body.addWidget(bar)
        self.report_button = self.link(tr("updater.button.report"))
        self.close_button = self.secondary(tr("updater.button.close"))
        self.retry_button = self.primary(tr("updater.button.retry"))
        self.retry_button.clicked.connect(lambda: self._done("retry"))
        self.close_button.clicked.connect(lambda: self._done("close"))
        self.report_button.clicked.connect(self.show_report)

    def _done(self, choice):
        self.choice = choice
        self.accept()

    def show_report(self):
        from .updater import closable
        self.report_dialog = closable(ReportDialog(self.report, self.title_text, self, open_url=self._open_url))
        self.report_dialog.place_centered()
        self.report_dialog.exec()


def waiting_card(text: str, on_restart_clicked=None) -> MessageCard:
    """Обновление скачано и ждёт, пока закроется редактор: окно не блокирует работу, «Перезапустить сейчас»."""
    card = MessageCard(None, tr("updater.wait.title"), text, "ok", primary=tr("updater.button.restart_now"),
                       secondary=tr("updater.button.close"), modal=False, logo=False)
    card.restart_button = card.primary_button
    if on_restart_clicked is not None:
        card.primary_button.clicked.connect(on_restart_clicked)
    return card
