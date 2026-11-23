# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Вводный курс: окно редактора затемняется, по очереди подсвечиваются блоки с пояснением."""

from PyQt6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .i18n import tr

from .themes import BLUE_BUTTON, BLUE_BUTTON_BORDER, BLUE_BUTTON_HOVER, LINK   # 1.32: белый текст на синем 5,8:1

CARD_STYLE = """
#tourCard { background: #ffffff; border: 1px solid #c9ccd1; border-radius: 12px; }
QLabel { color: #1c1f24; background: transparent; }
QLabel#tourTitle { font-size: 16px; font-weight: bold; color: #1c1f24; }
QLabel#tourText { font-size: 13px; color: #33373d; }
QLabel#tourStep { font-size: 12px; color: #6b7079; }
QPushButton { min-height: 30px; padding: 0 14px; border-radius: 6px; border: 1px solid #c9ccd1; background: #ffffff;
    color: #1c1f24; }
QPushButton:hover { background: #eef3fb; border-color: #9fb6da; color: #1c1f24; }
QPushButton:disabled { background: #f4f5f7; border-color: #dfe2e6; color: #8a9099; }
QPushButton#tourNext { background: %(blue)s; color: white; border: 1px solid %(border)s; font-weight: bold; }
QPushButton#tourNext:hover { background: %(hover)s; color: white; }
QPushButton#tourSkip { border: none; background: transparent; color: #5b6068; }
QPushButton#tourSkip:hover { background: transparent; color: #1c1f24; text-decoration: underline; }
QPushButton#tourAction { border: none; background: transparent; color: %(link)s; font-weight: bold;
    text-decoration: underline; padding: 0; min-height: 22px; }
QPushButton#tourAction:hover { background: transparent; color: %(hover)s; }
""" % {"blue": BLUE_BUTTON, "border": BLUE_BUTTON_BORDER, "hover": BLUE_BUTTON_HOVER, "link": LINK}
# Карточка всегда белая, поэтому у каждой надписи и кнопки свой явный цвет: цвет из палитры приложения на Windows
# в тёмной теме светлый, и кнопки языков, «Назад», «Пропустить» были почти белыми на белом (19.11.2026).


LANGUAGE_STEP = "language"   # пометка шага выбора языка в таблице шагов


def steps(ed, language: bool = True):
    """(что подсветить, заголовок, текст[, (надпись кнопки, действие)]).

    Подсветка — виджет, список виджетов или None (карточка по центру). language=False: без первого шага выбора
    языка (1.32, слово владельца: при повторном знакомстве из «?», F1, меню значка и настроек он не нужен)."""
    all_steps = _steps(ed)
    return all_steps if language else all_steps[1:]


def _steps(ed):
    colors = list(ed.color_buttons.values()) + [ed.custom_color]
    sizes = ed.size_group.buttons()
    hotkey = ed.ctx.config.get("hotkey_region") or "Alt+W"
    from .language import menu_title
    more = getattr(ed, "more_button", None)   # 1.32: «⋯ Все инструменты» и колокольчик
    bell = getattr(ed, "bell_button", None)
    return [
        (None, menu_title(), tr("tour.lang_text"), LANGUAGE_STEP),   # 1.31: первый экран: выбор языка
        (None, tr("tour.intro_title"), tr("tour.intro_text")),
        (ed.tool_strip, tr("tour.tools_title"), tr("tour.tools_text")),
        (more, tr("tour.alltools_title"), tr("tour.alltools_text")),
        ([ed.undo_button, ed.insert_button], tr("tour.undo_title"), tr("tour.undo_text")),
        (bell, tr("tour.bell_title"), tr("tour.bell_text")),
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
    snoozed = pyqtSignal(str)   # «Отложить ▾»: код времени (otlozhit.CHOICES), курс закрыт без отметки «пройдено»

    def __init__(self, editor, language: bool = True, steps_fn=None, snoozable: bool = False, start_index: int = 0):
        # steps_fn(editor, language) -> шаги в том же виде, что steps(): свой короткий курс (1.34, «Показать новое»)
        # 1.32: со своей шапкой окна знакомство затемняет всю карточку окна (колокольчик, «?» и глобус в шапке),
        # поля тени вокруг неё остаются прозрачными; с системным заголовком: содержимое окна
        host = getattr(editor, "shell", None) if getattr(editor, "titlebar", None) is not None else None
        host = host or getattr(editor, "content", None) or editor.centralWidget()
        super().__init__(host)
        self.editor = editor
        self.with_language = language   # первый шаг: выбор языка (только самое первое знакомство)
        self.steps_fn = steps_fn or steps
        self.steps = self.steps_fn(editor, language)
        self.index = 0
        self.start_index = max(0, int(start_index or 0))   # после «Отложить»: с того же шага
        self.snoozable = bool(snoozable)
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
        head = QHBoxLayout()   # «Шаг 3 из 12» слева, «Отложить ▾» справа: ряд кнопок внизу остаётся прежней ширины
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(self.step_label)
        head.addStretch(1)
        self.snooze_button = None
        if self.snoozable:
            from . import otlozhit
            self.snooze_button = otlozhit.SnoozeButton(False, compact=True, never="otl.never_tour")   # карточка курса всегда белая
            self.snooze_button.chosen.connect(self.snooze)
            head.addWidget(self.snooze_button)
        box.addLayout(head)
        self.head_h = head
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
            button.setIcon(icons.flag_icon(code))   # 1.32: флаг языка; «Как в системе»: глобус
            button.setIconSize(QSize(24, 16))
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(lambda _c=False, c=code: self._language_picked(c))
            self.lang_buttons[code] = button
            if i == 0:
                grid.addWidget(button, 0, 1, 1, 3)   # «Как в системе (…)» рядом с крупным глобусом
            else:
                grid.addWidget(button, 1 + (i - 1) // 4, (i - 1) % 4)
        self.lang_row.setStyleSheet("QPushButton#tourLang { min-height: 30px; font-size: 13px; padding: 0 4px;"
                                    " background: #ffffff; color: #1c1f24; border: 1px solid #c9ccd1; }"
                                    " QPushButton#tourLang:hover { background: #eef3fb; border-color: #9fb6da; }"
                                    f" QPushButton#tourLang:checked {{ background: {BLUE_BUTTON}; color: white;"
                                    f" border: 1px solid {BLUE_BUTTON_BORDER}; font-weight: bold; }}")
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
        self.steps = self.steps_fn(self.editor, self.with_language)
        self.skip.setText(tr("tour.skip"))
        self.back.setText(tr("tour.back"))
        if self.snooze_button is not None:
            self.snooze_button.retranslate()
        self._fill_languages()
        self.raise_()
        self.show_step(self.index)

    # --- ход курса -----------------------------------------------------------

    def start(self):
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self.setFocus()
        self.show_step(self.start_index)

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
        self.back.setVisible(self.index > 0)   # на первом шаге «Назад» нет, а не бледная отключённая кнопка
        self.next.setText(tr("tour.finish") if self.index == len(self.steps) - 1 else tr("tour.next"))
        # Высота карточки по переносам строк (у QLabel с переносом сам adjustSize её не угадывает).
        self.text.ensurePolished()
        width = self.card.width() - 36
        text_h = QFontMetrics(self.text.font()).boundingRect(
            QRect(0, 0, width, 10000), int(Qt.TextFlag.TextWordWrap), text).height() + 4
        self.text.setFixedHeight(text_h)
        box = self.card.layout()
        margins = box.contentsMargins()
        height = (margins.top() + margins.bottom() + 3 * box.spacing() + self.head_height()
                  + self.title.sizeHint().height() + text_h + self.next.sizeHint().height())
        if self.action_slot is not None:
            height += self.action.sizeHint().height() + box.spacing()
        if is_language:
            height += self.lang_row.sizeHint().height() + box.spacing()
        self.card.setFixedHeight(height)
        host = self.parentWidget()
        room = self._card_rect().height() if host is not None else 0
        if host is not None and height + 24 > room and not self.editor.isMaximized():
            # маленький снимок: окно редактора подрастает, чтобы карточка (выбор языка) поместилась целиком
            self.editor.resize(self.editor.width(), self.editor.height() + height + 24 - room)
        self.hole = self._target_rect(target)
        self._place_card()
        self.update()

    def head_height(self) -> int:
        h = self.step_label.sizeHint().height()
        return max(h, self.snooze_button.sizeHint().height()) if self.snooze_button is not None else h

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

    def snooze(self, key):
        """«Отложить ▾»: курс закрывается, знакомство не считается пройденным и вернётся, когда срок выйдет."""
        self.parentWidget().removeEventFilter(self)
        self.hide()
        self.snoozed.emit(key)
        self.close()

    # --- геометрия -----------------------------------------------------------

    def _card_rect(self) -> QRect:
        """Видимая карточка окна (без полей тени): её затемняем, в ней ставим карточку шага."""
        host = self.parentWidget()
        if host is not None and hasattr(host, "card"):
            return host.card().toRect()
        return self.rect()

    def _target_rect(self, target) -> QRect:
        if target is None:
            return QRect()
        widgets = target if isinstance(target, list) else [target]
        rect = QRect()
        for w in widgets:
            if w is None or not w.isVisible():
                continue
            top_left = self.parentWidget().mapFromGlobal(w.mapToGlobal(QPoint(0, 0)))   # и из шапки окна
            rect = rect.united(QRect(top_left, w.size()))
        if not rect.isValid():
            return QRect()
        return rect.adjusted(-6, -6, 6, 6).intersected(self._card_rect().adjusted(2, 2, -2, -2))

    def _place_card(self):
        area = self._card_rect().adjusted(12, 12, -12, -12)
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
        host = self.parentWidget()
        if host is not None and hasattr(host, "card"):   # карточка окна со скруглёнными углами, без полей тени
            radius = host.radius() if hasattr(host, "radius") else 0
            shade.addRoundedRect(QRectF(self._card_rect()), radius, radius)
        else:
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
