# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""«Скрыть личные данные» (1.36): закрытие найденного размытием и панель «Найдено: N».

Сеанс (PrivacySession) держит найденное и размытия на холсте: одно действие «Отменить» убирает всё. У каждого
значения свой режим (закрыто целиком, последние 4, начало и конец, только домен и т. д., открыто целиком);
«Открыть кусок» и «Скрыть кусок» режут и добавляют размытие по прямоугольнику, нарисованному мышью. Панель
(PrivacyPanel) показывает значения только замаскированными. Ничего не отправляется и не пишется в журналы.
"""
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea, QSizePolicy, QToolButton,
                             QVBoxLayout, QWidget)

from . import privacy
from .i18n import tr
from .shapes import BLUR, Shape

PANEL_W = 360
ROW_BUTTON_W = 150
KIND_KEYS = {privacy.CARD: "privacy.kind_card", privacy.IBAN: "privacy.kind_iban", privacy.PHONE: "privacy.kind_phone",
             privacy.EMAIL: "privacy.kind_email", privacy.LINK: "privacy.kind_link"}


MODE_KEYS = {"full": "privacy.mode_full", "last4": "privacy.mode_last4", "first_last": "privacy.mode_first_last",
             "open": "privacy.mode_open", "domain": "privacy.mode_domain", "name": "privacy.mode_name",
             "country_last4": "privacy.mode_country_last4", "host": "privacy.mode_host"}
SHORT_KEYS = {"full": "privacy.short_full", "last4": "privacy.short_last4", "first_last": "privacy.short_first_last",
              "open": "privacy.short_open", "domain": "privacy.short_domain", "name": "privacy.short_name",
              "country_last4": "privacy.short_country_last4", "host": "privacy.short_host", "custom": "privacy.short_custom"}
TOOL_KEYS = {"open": ("privacy.tool_open", "privacy.tool_open_tip"), "hide": ("privacy.tool_hide", "privacy.tool_hide_tip")}   # ключи каталога, tr() при показе


def mode_title(kind: str, mode: str) -> str:
    """Название режима в меню строки («Показать последние 4»)."""
    if mode == "first_last" and kind == privacy.PHONE:
        return tr("privacy.mode_first_last_phone")
    return tr(MODE_KEYS[mode])


def mode_short(kind: str, mode: str) -> str:
    """Короткое название режима для кнопки в строке."""
    return tr(SHORT_KEYS[mode])


class PrivacySession:
    """Найденное на одном снимке и его размытия на холсте. Слова и рамки в точках холста (canvas.words)."""

    def __init__(self, canvas, words, findings):
        self.canvas = canvas
        self.words = list(words)
        self.findings = list(findings)
        # «Похоже на IBAN» без подписи счёта рядом: не закрыто само; рядом с подписью (IBAN, Сметка, Account): закрыто (В3)
        self.modes = ["full" if getattr(f, "hide_by_default", not getattr(f, "maybe", False)) else "open" for f in self.findings]
        self.custom = [False] * len(self.findings)   # размытие этого значения правили мышью («Открыть кусок»)
        self.shapes = {}    # номер находки -> её размытия на холсте
        self.extra = []     # размытия, добавленные «Скрыть кусок»
        self._boxes = {}
        self.on_change = None   # вызывается после каждого изменения закрытого (редактор обновляет автосохранение)

    def _changed(self):
        if self.on_change is not None:
            self.on_change()

    # --- рамки -------------------------------------------------------------------------------------

    def _bounds(self) -> QRectF:
        ratio = self.canvas.base.devicePixelRatio() or 1.0
        return QRectF(0, 0, self.canvas.base.width() / ratio, self.canvas.base.height() / ratio)

    def boxes(self, wi: int):
        """Границы символов слова, измеренные по картинке (или None: тогда доли ширины с запасом)."""
        if wi not in self._boxes:
            w = self.words[wi]
            try:
                self._boxes[wi] = privacy.char_boxes(self.canvas.base, w.rect, w.text)
            except Exception:   # noqa: BLE001 — измерение только уточняет границы, без него работают доли ширины
                self._boxes[wi] = None
        return self._boxes[wi]

    def rects_for(self, i: int, mode: str = None) -> list:
        bounds = self._bounds()
        mode = mode or self.modes[i]
        return [r.intersected(bounds) for r in self.findings[i].rects(self.words, mode, self.boxes)
                if r.intersected(bounds).width() >= 2]

    def _make(self, rect: QRectF, like: Shape = None) -> Shape:
        color = like.color if like is not None else self.canvas.color
        size = like.size if like is not None else self.canvas.pen_size
        shape = Shape(BLUR, color, size, rect.topLeft())
        shape.points = [QPointF(rect.topLeft()), QPointF(rect.bottomRight())]
        shape.solid = True   # сплошная заливка: пикселизацию подбором можно прочитать
        return shape

    # --- действия ----------------------------------------------------------------------------------

    def apply(self):
        """Закрыть всё найденное одним шагом «Отменить»."""
        self.canvas.commit_text()
        self.canvas.push_undo()
        for i in range(len(self.findings)):
            self._show(i)
        self.canvas.select(None)
        self.canvas.update()
        self._changed()

    def _show(self, i: int):
        self._hide(i)
        shapes = [self._make(r) for r in self.rects_for(i)]
        self.canvas.shapes.extend(shapes)
        self.shapes[i] = shapes
        self.custom[i] = False

    def _hide(self, i: int):
        for s in self.shapes.pop(i, []):
            if s in self.canvas.shapes:
                self.canvas.shapes.remove(s)

    def alive(self) -> bool:
        """Размытия сеанса ещё на холсте (отмена и повтор пересоздают объекты: сеанс тогда закончен)."""
        mine = [s for v in self.shapes.values() for s in v] + self.extra
        return bool(mine) and any(s in self.canvas.shapes for s in mine)

    def set_mode(self, i: int, mode: str):
        if mode not in self.findings[i].modes():
            return
        self.modes[i] = mode
        self._show(i)
        self._touch()

    def set_all(self, mode: str):
        """«Скрыть всё» (full) и «Открыть всё» (open): и найденное, и добавленные вручную куски."""
        for i in range(len(self.findings)):
            self.modes[i] = mode
            self._show(i)
        for s in self.extra:
            if s in self.canvas.shapes:
                self.canvas.shapes.remove(s)
        if mode == "full":
            self.canvas.shapes.extend(self.extra)
        self._touch()

    def mode_label(self, i: int) -> str:
        return "custom" if self.custom[i] else self.modes[i]

    def rect_union(self, i: int) -> list:
        return [QRectF(s.rect()) for s in self.shapes.get(i, [])]

    def finding_at(self, pt: QPointF) -> int:
        """Номер значения, чьё размытие под точкой (или -1)."""
        for i, shapes in self.shapes.items():
            if any(s.rect().contains(pt) for s in shapes):
                return i
        return -1

    # --- куски -------------------------------------------------------------------------------------

    def cut(self, rect: QRectF, mode: str) -> bool:
        """«Открыть кусок»: размытие разрезается, внутри рамки открыто, остальное осталось; «Скрыть кусок»: поверх
        рамки добавляется размытие (и по нераспознанному месту: это обычное размытие). Одним шагом «Отменить»."""
        rect = rect.normalized().intersected(self._bounds())
        if rect.width() < 3 or rect.height() < 3:
            return False
        if mode == "hide":
            self.canvas.commit_text()
            self.canvas.push_undo()
            shape = self._make(rect)
            self.canvas.shapes.append(shape)
            self.extra.append(shape)
            self._touch(push=False)
            return True
        hit = [s for s in self.canvas.shapes if s.kind == BLUR and s.rect().intersects(rect)]
        if not hit:
            return False
        self.canvas.commit_text()
        self.canvas.push_undo()
        for s in hit:
            pieces = [self._make(r, s) for r in _minus(QRectF(s.rect()), rect)]
            at = self.canvas.shapes.index(s)
            self.canvas.shapes[at:at + 1] = pieces
            for i, lst in self.shapes.items():
                if s in lst:
                    lst[lst.index(s):lst.index(s) + 1] = pieces
                    self.custom[i] = True
            if s in self.extra:
                self.extra[self.extra.index(s):self.extra.index(s) + 1] = pieces
        self._touch(push=False)
        return True

    def _touch(self, push=False):
        self.canvas.select(None)
        self.canvas.modified = True
        self.canvas.update()
        self.canvas.changed.emit()
        self._changed()


def _minus(r: QRectF, cut: QRectF) -> list:
    """Прямоугольник без вырезанной части: до четырёх остатков (сверху, снизу, слева, справа)."""
    c = r.intersected(cut)
    if c.isEmpty():
        return [r]
    out = []
    if c.top() > r.top():
        out.append(QRectF(r.left(), r.top(), r.width(), c.top() - r.top()))
    if c.bottom() < r.bottom():
        out.append(QRectF(r.left(), c.bottom(), r.width(), r.bottom() - c.bottom()))
    if c.left() > r.left():
        out.append(QRectF(r.left(), c.top(), c.left() - r.left(), c.height()))
    if c.right() < r.right():
        out.append(QRectF(c.right(), c.top(), r.right() - c.right(), c.height()))
    return [x for x in out if x.width() >= 1 and x.height() >= 1]


def already_hidden(canvas, rects) -> bool:
    """Все рамки уже закрыты сплошной заливкой «Скрыть личные данные» (повторное нажатие не накладывает её второй раз).
    Обычное «Размытие» человека не считается: пикселизацию можно подобрать, такой номер закрашивается заново."""
    blurs = [s.rect() for s in canvas.shapes if s.kind == BLUR and getattr(s, "solid", False)]
    return bool(rects) and all(any(b.contains(r) for b in blurs) for r in rects)


class PrivacyRow(QFrame):
    """Строка списка: замаскированное значение и выбор «что оставить открытым» (меню ▾ в строке)."""

    hovered = pyqtSignal(int, bool)
    chosen = pyqtSignal(int, str)

    def __init__(self, index: int, finding, mode: str, custom: bool, cfg=None):
        super().__init__()
        self.index, self.finding = index, finding
        self.setObjectName("privacyRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setProperty("sel", False)
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 3, 4, 3)
        row.setSpacing(6)
        self.label = QLabel()
        self.label.setObjectName("privacyValue")
        self.label.setMinimumWidth(40)
        self.label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        row.addWidget(self.label, 1)
        self.button = QToolButton()
        self.button.setObjectName("privacyMode")
        self.button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.button.setFixedWidth(ROW_BUTTON_W)
        self.button.setToolTip(tr("privacy.item_tip"))
        self.button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.menu = QMenu(self.button)
        if cfg is not None:
            from .menus import style_menu
            style_menu(self.menu, cfg)   # меню в оформлении программы (светлом или тёмном)
        self.menu.aboutToShow.connect(self._fill_menu)
        self.button.setMenu(self.menu)
        row.addWidget(self.button)
        self.set_state(mode, custom)

    def set_state(self, mode: str, custom: bool = False):
        self.mode, self.custom = mode, custom
        text = self.finding.preview("full" if custom else mode)
        self._full_text = text
        self.label.setText(self.label.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, 150))
        self.label.setToolTip(text)
        if getattr(self.finding, "maybe", False):   # сумма IBAN не сошлась: подсказка вместо тишины, закрыть можно в меню
            self.label.setText(self.label.fontMetrics().elidedText(tr("privacy.maybe_short") + " " + text, Qt.TextElideMode.ElideRight, 150))
            hint = "privacy.maybe_iban_label" if getattr(self.finding, "near_label", False) else "privacy.maybe_iban"
            self.label.setToolTip(tr(hint) + "\n" + text)
        name = "custom" if custom else mode
        short = tr(SHORT_KEYS[name])
        self.button.setText(self.button.fontMetrics().elidedText(short + "  ▾", Qt.TextElideMode.ElideRight,
                                                                 ROW_BUTTON_W - 18))
        self.button.setAccessibleName(tr(KIND_KEYS[self.finding.kind]) + ": " + text + ": " + short)

    def _fill_menu(self):
        self.menu.clear()
        for mode in self.finding.modes():
            act = self.menu.addAction(mode_title(self.finding.kind, mode))
            act.setCheckable(True)
            act.setChecked(mode == self.mode and not self.custom)
            act.triggered.connect(lambda _c=False, m=mode: self.chosen.emit(self.index, m))

    def enterEvent(self, event):
        self.hovered.emit(self.index, True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hovered.emit(self.index, False)
        super().leaveEvent(event)

    def set_selected(self, on: bool):
        self.setProperty("sel", bool(on))
        self.style().unpolish(self)
        self.style().polish(self)


class PrivacyPanel(QFrame):
    """Панель справа от снимка: «Найдено: N», значения по типам (замаскированные) с выбором режима, кнопки."""

    closed = pyqtSignal()
    manual_requested = pyqtSignal()
    hovered = pyqtSignal(int, bool)      # наведение на строку: подсветить место на снимке
    tool_changed = pyqtSignal(str)       # "", "open" или "hide": «Открыть кусок» / «Скрыть кусок»
    visibility_changed = pyqtSignal(bool)   # 1.36.1: панель показана или убрана: окно редактора растёт вбок, снимок не сжимается

    def showEvent(self, event):
        super().showEvent(event)
        self.visibility_changed.emit(True)

    def hideEvent(self, event):
        super().hideEvent(event)
        self.visibility_changed.emit(False)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("privacyPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setFixedWidth(PANEL_W)
        self.session = None
        self.rows = []
        self.tool_buttons = {}
        self.setAccessibleName(tr("privacy.title"))
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 10, 12)
        root.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(6)
        self.title = QLabel()
        self.title.setObjectName("privacyTitle")
        self.title.setWordWrap(True)
        head.addWidget(self.title, 1)
        self.close_button = QToolButton()
        self.close_button.setObjectName("privacyClose")
        self.close_button.setText("✕")
        self.close_button.setToolTip(tr("privacy.close_tip"))
        self.close_button.setAccessibleName(tr("privacy.close_tip"))
        self.close_button.setAutoRaise(True)
        self.close_button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.close_button.clicked.connect(self.close_panel)
        head.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(head)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(2)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.body)
        self.scroll.viewport().setAutoFillBackground(False)
        self.body.setAutoFillBackground(False)
        root.addWidget(self.scroll, 1)
        self.buttons = QVBoxLayout()
        self.buttons.setSpacing(6)
        root.addLayout(self.buttons)
        self.note = QLabel(tr("privacy.note"))
        self.note.setObjectName("privacyNote")
        self.note.setWordWrap(True)
        root.addWidget(self.note)
        self.setVisible(False)

    # --- содержимое -----------------------------------------------------------------------------------

    def _clear(self):
        for lay in (self.body_layout, self.buttons):
            while lay.count():
                item = lay.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.setParent(None)
                    w.deleteLater()
                elif item.layout() is not None:
                    inner = item.layout()
                    while inner.count():
                        sub = inner.takeAt(0)
                        if sub.widget() is not None:
                            sub.widget().setParent(None)
                            sub.widget().deleteLater()
        self.rows = []
        self.tool_buttons = {}
        self.set_tool("")

    def show_empty(self, text: str = None):
        """Ничего не найдено: короткая подсказка и совет выделить вручную."""
        self.session = None
        self._clear()
        self.title.setText(text or tr("privacy.none"))
        hint = QLabel(tr("privacy.none_hint"))
        hint.setObjectName("privacyHint")
        hint.setWordWrap(True)
        self.body_layout.addWidget(hint)
        self.body_layout.addStretch(1)
        manual = QPushButton(tr("privacy.manual"))
        manual.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        manual.clicked.connect(self.manual_requested.emit)
        self.buttons.addWidget(manual)
        self.manual_button = manual
        self.note.setVisible(True)
        self.setVisible(True)

    def show_session(self, session: PrivacySession):
        self.session = session
        self._clear()
        self.title.setText(tr("privacy.found", n=len(session.findings)))
        for kind in privacy.KINDS:
            idx = [i for i, f in enumerate(session.findings) if f.kind == kind]
            if not idx:
                continue
            head = QLabel(tr(KIND_KEYS[kind]) + " · " + str(len(idx)))
            head.setObjectName("privacyKind")
            head.setWordWrap(True)
            self.body_layout.addWidget(head)
            for i in idx:
                row = PrivacyRow(i, session.findings[i], session.modes[i], session.custom[i], self.cfg)
                row.chosen.connect(self._chosen)
                row.hovered.connect(self.hovered.emit)
                self.body_layout.addWidget(row)
                self.rows.append(row)
        self.body_layout.addStretch(1)
        tools = QHBoxLayout()
        tools.setSpacing(6)
        for key, (name_key, tip) in TOOL_KEYS.items():
            b = QPushButton(tr(name_key))
            b.setCheckable(True)
            b.setObjectName("privacyTool")
            b.setToolTip(tr(tip))
            b.setAccessibleName(tr(name_key))
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            b.clicked.connect(lambda _c=False, k=key: self.set_tool("" if self.tool == k else k, emit=True))
            tools.addWidget(b, 1)
            self.tool_buttons[key] = b
        self.buttons.addLayout(tools)
        self.band_hint = QLabel()   # 1.36.1: что делать, пока выбран «Открыть/Скрыть кусок»
        self.band_hint.setObjectName("privacyHint")
        self.band_hint.setWordWrap(True)
        self.band_hint.hide()
        self.buttons.addWidget(self.band_hint)
        row = QHBoxLayout()
        row.setSpacing(6)
        open_all = QPushButton(tr("privacy.open_all"))
        hide_all = QPushButton(tr("privacy.hide_all"))
        open_all.clicked.connect(lambda: self._set_all("open"))
        hide_all.clicked.connect(lambda: self._set_all("full"))
        self.open_all_button, self.hide_all_button = open_all, hide_all
        for b in (open_all, hide_all):
            b.setMinimumWidth(0)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            row.addWidget(b, 1)
        self.buttons.addLayout(row)
        self.note.setVisible(True)
        self.setVisible(True)

    # --- действия -------------------------------------------------------------------------------------

    tool = ""
    cfg = None   # настройки редактора: оформление меню строк

    def set_tool(self, tool: str, emit: bool = False):
        self.tool = tool
        for k, b in self.tool_buttons.items():
            b.setChecked(k == tool)
        hint = getattr(self, "band_hint", None)
        if hint is not None:
            hint.setText({"open": tr("privacy.band_hint_open"), "hide": tr("privacy.band_hint_hide")}.get(tool, ""))
            hint.setVisible(tool in TOOL_KEYS)
        if emit:
            self.tool_changed.emit(tool)

    def _chosen(self, i: int, mode: str):
        if self.session is None:
            return
        self.session.set_mode(i, mode)
        self.refresh_rows()

    def _set_all(self, mode: str):
        if self.session is None:
            return
        self.session.set_all(mode)
        self.refresh_rows()

    def refresh_rows(self):
        """Строки показывают текущие режимы сеанса (после выбора, «Открыть всё» или куска)."""
        if self.session is None:
            return
        for row in self.rows:
            row.set_state(self.session.modes[row.index], self.session.custom[row.index])

    def select_row(self, i: int):
        """Щелчок по размытому месту на снимке: строка выделена и прокручена в видимую часть списка."""
        for row in self.rows:
            row.set_selected(row.index == i)
            if row.index == i:
                self.scroll.ensureWidgetVisible(row, 0, 24)

    def selected_index(self) -> int:
        return next((r.index for r in self.rows if r.property("sel")), -1)

    def close_panel(self):
        self.session = None
        self.set_tool("")
        self.setVisible(False)
        self.tool_changed.emit("")
        self.closed.emit()

    def restyle(self, P: dict):
        """Цвета из палитры редактора (светлая и тёмная тема)."""
        self.setStyleSheet(f"""
#privacyPanel {{ background: {P['panel']}; border-left: 1px solid {P['sep']}; }}
#privacyPanel QLabel {{ color: {P['t']}; background: transparent; }}
#privacyPanel QLabel#privacyTitle {{ font-size: 15px; font-weight: 600; }}
#privacyPanel QLabel#privacyKind {{ color: {P['t2']}; font-size: 12px; font-weight: 600; padding: 8px 0 2px 0; }}
#privacyPanel QLabel#privacyHint, #privacyPanel QLabel#privacyNote {{ color: {P['t2']}; font-size: 12px; }}
#privacyPanel QLabel#privacyValue {{ font-size: 13px; }}
#privacyPanel QFrame#privacyRow {{ background: transparent; border-radius: 6px; }}
#privacyPanel QFrame#privacyRow[sel="true"] {{ background: {P['accs']}; }}
#privacyPanel QToolButton#privacyMode {{ color: {P['t']}; background: {P['s2']}; border: 1px solid {P['sep']};
    border-radius: 6px; padding: 3px 8px; font-size: 12px; text-align: left; }}
#privacyPanel QToolButton#privacyMode:hover {{ background: {P['s3']}; }}
#privacyPanel QToolButton#privacyMode::menu-indicator {{ image: none; width: 0px; }}
#privacyPanel QToolButton#privacyClose {{ color: {P['t2']}; border: none; border-radius: 6px; padding: 4px 6px;
    background: transparent; }}
#privacyPanel QToolButton#privacyClose:hover {{ background: {P['hover']}; }}
#privacyPanel QScrollArea, #privacyPanel QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
#privacyPanel QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
#privacyPanel QScrollBar::handle:vertical {{ background: {P['s3']}; border-radius: 4px; min-height: 28px; }}
#privacyPanel QScrollBar::add-line:vertical, #privacyPanel QScrollBar::sub-line:vertical {{ height: 0; }}
#privacyPanel QScrollBar::add-page:vertical, #privacyPanel QScrollBar::sub-page:vertical {{ background: transparent; }}
#privacyPanel QPushButton {{ padding: 0 8px; }}
#privacyPanel QPushButton:checked {{ background: {P['accs']}; border-color: {P['sep']}; }}
""")
