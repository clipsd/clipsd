# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
"""Вводный курс: окно редактора затемняется, по очереди подсвечиваются блоки с пояснением."""

from PyQt6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .i18n import tr

CARD_STYLE = """
#tourCard { background: #ffffff; border: 1px solid #c9ccd1; border-radius: 12px; }
QLabel#tourTitle { font-size: 16px; font-weight: bold; color: #1c1f24; }
QLabel#tourText { font-size: 13px; color: #33373d; }
QLabel#tourStep { font-size: 12px; color: #7a7f87; }
QPushButton { min-height: 30px; padding: 0 14px; border-radius: 6px; border: 1px solid #b9b9b9; background: #fff; }
QPushButton:hover { background: #eef3fb; border-color: #9fb6da; }
QPushButton#tourNext { background: #1e78ff; color: white; border: 1px solid #1660d0; font-weight: bold; }
QPushButton#tourNext:hover { background: #3a8bff; }
QPushButton#tourSkip { border: none; background: transparent; color: #5b6068; }
QPushButton#tourAction { border: none; background: transparent; color: #1660d0; font-weight: bold;
    text-decoration: underline; padding: 0; min-height: 22px; }
QPushButton#tourAction:hover { color: #1e78ff; }
"""


LANGUAGE_STEP = "language"   # пометка шага выбора языка в таблице шагов


def steps(ed):
    """(что подсветить, заголовок, текст[, (надпись кнопки, действие)]).

    Подсветка — виджет, список виджетов или None (карточка по центру)."""
    colors = list(ed.color_buttons.values()) + [ed.custom_color]
    sizes = ed.size_group.buttons()
    hotkey = ed.ctx.config.get("hotkey_region") or "Alt+W"
    from .language import menu_title
    return [
        (None, menu_title(), tr("tour.lang_text"), LANGUAGE_STEP),   # 1.31: первый экран: выбор языка
        (None, tr("tour.intro_title"), tr("tour.intro_text")),
        (ed.tool_strip, tr("tour.tools_title"), tr("tour.tools_text")),
        ([ed.undo_button, ed.insert_button], tr("tour.undo_title"), tr("tour.undo_text")),
        ([ed.help_button, ed.settings_button], tr("tour.help_title"), tr("tour.help_text")),
        (colors, tr("tour.color_title"), tr("tour.color_text")),
        (ed.text_color_button, tr("tour.text_color_title"), tr("tour.text_color_text")),
        (sizes, tr("tour.sizes_title"), tr("tour.sizes_text")),
        (ed.scroll, tr("tour.canvas_title"), tr("tour.canvas_text")),
        ([ed.save_button, ed.copy_close_button, ed.copy_button], tr("tour.done_title"), tr("tour.done_text")),
        (None, tr("tour.capture_title"), tr("tour.capture_text", hotkey=hotkey),
         (tr("tour.change_hotkey"), ed.open_settings)),
    ]


class Tour(QWidget):
    finished = pyqtSignal()

    def __init__(self, editor):
        host = getattr(editor, "content", None) or editor.centralWidget()   # карточка окна без полей тени
        super().__init__(host)
        self.editor = editor
        self.steps = steps(editor)
        self.index = 0
        self.hole = QRect()
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        host.installEventFilter(self)

        self.card = QFrame(self)
        self.card.setObjectName("tourCard")
        self.card.setStyleSheet(CARD_STYLE)
        self.card.setFixedWidth(400)
        box = QVBoxLayout(self.card)
        box.setContentsMargins(18, 14, 18, 14)
        box.setSpacing(8)
        self.step_label = QLabel()
        self.step_label.setObjectName("tourStep")
        self.title = QLabel()
        self.title.setObjectName("tourTitle")
        self.text = QLabel()
        self.text.setObjectName("tourText")
        self.text.setWordWrap(True)
        box.addWidget(self.step_label)
        box.addWidget(self.title)
        box.addWidget(self.text)
        self._build_language_row(box)
        self.action = QPushButton()
        self.action.setObjectName("tourAction")
        self.action.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.action.clicked.connect(self._run_action)
        self.action_slot = None
        box.addWidget(self.action, 0, Qt.AlignmentFlag.AlignLeft)
        buttons = QHBoxLayout()
        self.skip = QPushButton(tr("tour.skip"))
        self.skip.setObjectName("tourSkip")
        self.skip.clicked.connect(self.finish)
        self.back = QPushButton(tr("tour.back"))
        self.back.clicked.connect(self.prev)
        self.next = QPushButton(tr("tour.next"))
        self.next.setObjectName("tourNext")
        self.next.clicked.connect(self.forward)
        for b in (self.skip, self.back, self.next):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        buttons.addWidget(self.skip)
        buttons.addStretch(1)
        buttons.addWidget(self.back)
        buttons.addWidget(self.next)
        box.addLayout(buttons)

    def _build_language_row(self, box):
        """1.31: первый экран знакомства: выбор языка. Крупный глобус, «Язык · Language», 13 кнопок с языками на
        самих себе: человек, который не понимает текущий язык, сразу его меняет; курс и окно тут же переходят на него."""
        from PyQt6.QtWidgets import QGridLayout
        from . import icons
        self.lang_row = QWidget()
        grid = QGridLayout(self.lang_row)
        grid.setContentsMargins(0, 4, 0, 4)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        globe = QLabel()
        globe.setPixmap(icons.icon("globe").pixmap(34, 34))
        globe.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(globe, 0, 0)
        self.lang_buttons = {}
        from . import i18n, language
        codes = [language.AUTO] + list(i18n.LANGUAGES)
        for i, code in enumerate(codes):
            button = QPushButton()
            button.setObjectName("tourLang")
            button.setCheckable(True)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(lambda _c=False, c=code: self._language_picked(c))
            self.lang_buttons[code] = button
            if i == 0:
                grid.addWidget(button, 0, 1, 1, 3)   # «Как в системе (…)» рядом с крупным глобусом
            else:
                grid.addWidget(button, 1 + (i - 1) // 4, (i - 1) % 4)
        self.lang_row.setStyleSheet("QPushButton#tourLang { min-height: 30px; font-size: 13px; padding: 0 4px; }"
                                    " QPushButton#tourLang:checked { background: #1e78ff; color: white;"
                                    " border: 1px solid #1660d0; font-weight: bold; }")
        self._fill_languages()
        box.addWidget(self.lang_row)

    def _fill_languages(self):
        from . import language
        chosen = language.current_choice(self.editor.ctx)
        for code, label in language.entries():
            button = self.lang_buttons[code]
            button.setText(label)
            button.setChecked(code == chosen)

    def _language_picked(self, code):
        from . import language
        ctx = self.editor.ctx
        language.change(ctx, code)
        if not hasattr(ctx, "set_language") and hasattr(self.editor, "retranslate"):
            self.editor.retranslate()   # без приложения (демо, тесты) окно перерисовывается здесь
        self.retranslate()

    def retranslate(self):
        """Язык сменён: шаги собираются заново (у редактора новые панели), подписи кнопок на новом языке."""
        from . import language
        self.steps = steps(self.editor)
        self.skip.setText(tr("tour.skip"))
        self.back.setText(tr("tour.back"))
        self._fill_languages()
        self.raise_()
        self.show_step(self.index)

    # --- ход курса -----------------------------------------------------------

    def start(self):
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self.setFocus()
        self.show_step(0)

    def show_step(self, index):
        self.index = max(0, min(index, len(self.steps) - 1))
        target, title, text, *extra = self.steps[self.index]
        is_language = bool(extra) and extra[0] == LANGUAGE_STEP
        if is_language:
            extra = []
        self.action_slot = extra[0][1] if extra else None
        self.action.setVisible(bool(extra))
        if extra:
            self.action.setText(extra[0][0])
        self.step_label.setText(tr("tour.step", i=self.index + 1, total=len(self.steps)))
        self.title.setText(title)
        self.text.setText(text)
        self.lang_row.setVisible(is_language)
        self.back.setEnabled(self.index > 0)
        self.next.setText(tr("tour.finish") if self.index == len(self.steps) - 1 else tr("tour.next"))
        # Высота карточки по переносам строк (у QLabel с переносом сам adjustSize её не угадывает).
        self.text.ensurePolished()
        width = self.card.width() - 36
        text_h = QFontMetrics(self.text.font()).boundingRect(
            QRect(0, 0, width, 10000), int(Qt.TextFlag.TextWordWrap), text).height() + 4
        self.text.setFixedHeight(text_h)
        box = self.card.layout()
        margins = box.contentsMargins()
        height = (margins.top() + margins.bottom() + 3 * box.spacing() + self.step_label.sizeHint().height()
                  + self.title.sizeHint().height() + text_h + self.next.sizeHint().height())
        if self.action_slot is not None:
            height += self.action.sizeHint().height() + box.spacing()
        if is_language:
            height += self.lang_row.sizeHint().height() + box.spacing()
        self.card.setFixedHeight(height)
        host = self.parentWidget()
        if host is not None and height + 24 > host.height() and not self.editor.isMaximized():
            # маленький снимок: окно редактора подрастает, чтобы карточка (выбор языка) поместилась целиком
            self.editor.resize(self.editor.width(), self.editor.height() + height + 24 - host.height())
        self.hole = self._target_rect(target)
        self._place_card()
        self.update()

    def _run_action(self):
        """Кнопка-переход из карточки (например, в настройки): курс закрывается, действие выполняется."""
        slot = self.action_slot
        self.finish()
        if slot is not None:
            slot()

    def forward(self):
        if self.index == len(self.steps) - 1:
            self.finish()
        else:
            self.show_step(self.index + 1)

    def prev(self):
        self.show_step(self.index - 1)

    def finish(self):
        self.parentWidget().removeEventFilter(self)
        self.hide()
        self.finished.emit()
        self.close()

    # --- геометрия -----------------------------------------------------------

    def _target_rect(self, target) -> QRect:
        if target is None:
            return QRect()
        widgets = target if isinstance(target, list) else [target]
        rect = QRect()
        for w in widgets:
            if w is None or not w.isVisible():
                continue
            top_left = w.mapTo(self.parentWidget(), QPoint(0, 0))
            rect = rect.united(QRect(top_left, w.size()))
        return rect.adjusted(-6, -6, 6, 6) if rect.isValid() else QRect()

    def _place_card(self):
        area = self.rect().adjusted(12, 12, -12, -12)
        size = self.card.size()
        if not self.hole.isValid():
            pos = area.center() - QPoint(size.width() // 2, size.height() // 2)
        elif self.hole.bottom() + 12 + size.height() <= area.bottom():
            pos = QPoint(self.hole.left(), self.hole.bottom() + 12)          # под подсветкой
        elif self.hole.top() - 12 - size.height() >= area.top():
            pos = QPoint(self.hole.left(), self.hole.top() - 12 - size.height())   # над подсветкой
        else:
            pos = QPoint(self.hole.right() + 12, self.hole.top())           # сбоку
        pos.setX(max(area.left(), min(pos.x(), area.right() - size.width())))
        pos.setY(max(area.top(), min(pos.y(), area.bottom() - size.height())))
        self.card.move(pos)
        self.card.raise_()

    def eventFilter(self, obj, event):
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self.setGeometry(obj.rect())
            self.show_step(self.index)
        return super().eventFilter(obj, event)

    # --- отрисовка и ввод ----------------------------------------------------

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        shade = QPainterPath()
        shade.addRect(QRectF(self.rect()))
        if self.hole.isValid():
            cut = QPainterPath()
            cut.addRoundedRect(QRectF(self.hole), 8, 8)
            shade = shade.subtracted(cut)
        p.fillPath(shade, QColor(0, 0, 0, 165))
        if self.hole.isValid():
            p.setPen(QPen(QColor("#ffd23f"), 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(self.hole), 8, 8)

    def mousePressEvent(self, event):
        event.accept()   # клики мимо карточки не доходят до редактора, пока идёт курс

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Right, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.forward()
        elif key == Qt.Key.Key_Left:
            self.prev()
        elif key == Qt.Key.Key_Escape:
            self.finish()
        event.accept()

    def event(self, event):
        # Пока идёт курс, клавиши (Esc, Enter, буквы) не должны срабатывать как команды редактора.
        if event.type() == QEvent.Type.ShortcutOverride:
            event.accept()
            return True
        return super().event(event)
