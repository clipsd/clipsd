# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Окна 1.36: палитра стикеров (поиск, недавние, эмодзи, плашки, номера) и панель «Тень, рамка и поля».

Оба окна всплывающие (закрываются щелчком снаружи и Esc), цвета из общей палитры карточек dialogs.PALETTES,
размеры считаются по шрифту (12 языков, длинный немецкий), а не числами. Редактор их открывает и слушает сигналы.
"""
from PyQt6.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PyQt6.QtWidgets import (QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QRadioButton,
                             QScrollArea, QSlider, QToolButton, QVBoxLayout, QWidget)

from . import stickers, ten_ramka
from .dialogs import PALETTES
from .i18n import tr

CELL = 44            # кнопка эмодзи в палитре, px
ICON = 32            # значок эмодзи, px
COLUMNS = 8


def _style(dark: bool, name: str) -> str:
    c = PALETTES[bool(dark)]
    return f"""
QFrame#{name} {{ background: {c['card']}; border: 1px solid {c['edge']}; border-radius: 12px; }}
QLabel {{ color: {c['text']}; background: transparent; }}
QLabel#stHead {{ color: {c['muted']}; font-size: 12px; font-weight: bold; padding: 6px 2px 2px 2px; }}
QLabel#stNote {{ color: {c['muted']}; font-size: 12px; }}
QLineEdit {{ padding: 7px 10px; border: 1px solid {c['line']}; border-radius: 8px; font-size: 14px; background: {c['field']};
            color: {c['text']}; }}
QLineEdit:focus {{ border: 2px solid {c['accent']}; padding: 6px 9px; }}
QToolButton#stCell {{ background: transparent; border: 1px solid transparent; border-radius: 8px; }}
QToolButton#stCell:hover {{ background: {c['soft']}; border-color: {c['line']}; }}
QToolButton#stCell:focus {{ border: 2px solid {c['accent']}; }}
QToolButton#stCell:checked {{ background: {c['soft']}; border-color: {c['accent']}; }}
QCheckBox, QRadioButton {{ color: {c['text']}; background: transparent; font-size: 14px; spacing: 8px; }}
QCheckBox#decoHead {{ font-weight: bold; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {c['line']}; border-radius: 4px; background: {c['field']}; }}
QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; }}
QRadioButton::indicator {{ width: 16px; height: 16px; border: 1px solid {c['line']}; border-radius: 9px; background: {c['field']}; }}
QRadioButton::indicator:checked {{ background: {c['accent']}; border: 4px solid {c['field']}; outline: 1px solid {c['accent']}; }}
QCheckBox::indicator:focus, QRadioButton::indicator:focus {{ border: 2px solid {c['accent']}; }}
QSlider::groove:horizontal {{ height: 4px; background: {c['track']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; background: {c['accent']}; }}
QSlider::sub-page:horizontal {{ background: {c['accent']}; border-radius: 2px; }}
QSlider:disabled {{ opacity: 0.5; }}
QPushButton#decoSwatch {{ border: 1px solid {c['line']}; border-radius: 6px; min-width: 22px; max-width: 22px;
                          min-height: 22px; max-height: 22px; }}
QPushButton#decoSwatch:checked {{ border: 3px solid {c['accent']}; }}
QPushButton#decoSwatch:focus {{ border: 2px solid {c['accent']}; }}
QPushButton#decoReset {{ background: {c['card']}; color: {c['text']}; border: 1px solid {c['line']}; border-radius: 6px;
                         padding: 6px 12px; font-size: 13px; }}
QPushButton#decoReset:hover {{ background: {c['soft']}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
"""


class StickerPalette(QFrame):
    """Палитра стикеров: поиск по названию на языке интерфейса, недавние сверху, эмодзи, плашки, номера."""
    chosen = pyqtSignal(str)

    def __init__(self, parent, config, dark=False, current=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("stickerPalette")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.config, self.dark, self.current = config, bool(dark), current
        self.color = QColor("#d60808")      # цвет плашек и номеров в образцах (цвет из палитры редактора)
        self.buttons = {}
        self.setStyleSheet(_style(self.dark, "stickerPalette"))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(6)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("stiker.search"))
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName(tr("stiker.search"))
        self.search.textChanged.connect(self._rebuild)
        self.search.returnPressed.connect(self._pick_first)
        outer.addWidget(self.search)
        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        self.area.setFrameShape(QFrame.Shape.NoFrame)
        self.area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.holder = QWidget()
        self.body = QVBoxLayout(self.holder)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(2)
        self.area.setWidget(self.holder)
        outer.addWidget(self.area, 1)
        width = COLUMNS * (CELL + 2) + 28
        self.setFixedWidth(width)
        self.area.setFixedHeight(CELL * 6 + 24)
        self._rebuild()

    # --- содержимое -------------------------------------------------------------------------------------------

    def _clear(self):
        while self.body.count():
            item = self.body.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.deleteLater()
        self.buttons = {}

    def _head(self, text: str):
        label = QLabel(text)
        label.setObjectName("stHead")
        self.body.addWidget(label)

    def _cell(self, sid: str, wide: bool = False) -> QToolButton:
        b = QToolButton()
        b.setObjectName("stCell")
        b.setCheckable(True)
        b.setChecked(sid == self.current)
        b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        text = stickers.plate_text(sid) if stickers.kind(sid) == "plate" else ""
        ratio = self.devicePixelRatioF() or 1.0
        if wide:
            w, h = 108, 34
            image = QImage(round(w * ratio), round(h * ratio), QImage.Format.Format_ARGB32_Premultiplied)
            image.setDevicePixelRatio(ratio)
            image.fill(Qt.GlobalColor.transparent)
            p = QPainter(image)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            stickers.draw(p, sid, QRectF(2, 3, w - 4, h - 6), stickers.default_color(sid, self.color), text)
            p.end()
            b.setIconSize(QSize(w, h))
            b.setFixedSize(w + 8, h + 8)
        else:
            image = stickers.render_icon(sid, ICON, self.color, text, ratio)
            b.setIconSize(QSize(ICON, ICON))
            b.setFixedSize(CELL, CELL)
        b.setIcon(QIcon(QPixmap.fromImage(image)))
        name = stickers.title(sid) if stickers.kind(sid) == "emoji" else (text or sid)
        b.setToolTip(name)
        b.setAccessibleName(name)
        b.clicked.connect(lambda _c=False, s=sid: self._choose(s))
        self.buttons[sid] = b
        return b

    def _grid(self, ids, wide=False):
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(2)
        cols = 2 if wide else COLUMNS
        for i, sid in enumerate(ids):
            grid.addWidget(self._cell(sid, wide), i // cols, i % cols, Qt.AlignmentFlag.AlignLeft)
        box = QWidget()
        box.setLayout(grid)
        self.body.addWidget(box)

    def _rebuild(self, *_):
        self._clear()
        query = self.search.text().strip()
        if query:
            found = stickers.search(query)
            if not found:
                note = QLabel(tr("stiker.none"))
                note.setObjectName("stNote")
                note.setWordWrap(True)
                self.body.addWidget(note)
            else:
                self._head(tr("stiker.found"))
                self._grid([s for s in found if stickers.kind(s) != "plate"])
                plates = [s for s in found if stickers.kind(s) == "plate"]
                if plates:
                    self._head(tr("stiker.plates"))
                    self._grid(plates, wide=True)
            self.body.addStretch(1)
            return
        recent = stickers.recent(self.config)
        if recent:
            self._head(tr("stiker.recent"))
            self._grid([s for s in recent if stickers.kind(s) != "plate"] or [])
            plates = [s for s in recent if stickers.kind(s) == "plate"]
            if plates:
                self._grid(plates, wide=True)
        self._head(tr("stiker.emoji"))
        self._grid(list(stickers.EMOJI))
        self._head(tr("stiker.plates"))
        self._grid(list(stickers.PLATES), wide=True)
        self._head(tr("stiker.numbers"))
        self._grid(list(stickers.NUMBERS))
        self.body.addStretch(1)

    # --- выбор ---------------------------------------------------------------------------------------------------

    def visible_ids(self) -> list:
        return list(self.buttons)

    def _pick_first(self):
        if self.buttons:
            self._choose(next(iter(self.buttons)))

    def _choose(self, sid: str):
        self.chosen.emit(sid)
        self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def popup_at(self, global_pos):
        self.adjustSize()
        self.move(global_pos)
        self.show()
        self.search.setFocus()


class DecoPanel(QFrame):
    """Тень, рамка и поля вокруг снимка: переключатели, ползунки, цвет рамки из палитры. Сигнал changed(Deco, record):
    record=False у промежуточных значений ползунка (один шаг отмены на всё перетаскивание)."""
    changed = pyqtSignal(object, bool)

    def __init__(self, parent, deco, colors, dark=False, jpg_note=""):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("decoPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.deco = deco.copy()
        self.dark = bool(dark)
        self._record = True
        self._loading = True
        self.setStyleSheet(_style(self.dark, "decoPanel"))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(6)
        title = QLabel(tr("deco.title"))
        title.setStyleSheet("font-size: 15px; font-weight: bold;")
        outer.addWidget(title)

        self.shadow_box = QCheckBox(tr("deco.shadow"))
        self.shadow_box.setObjectName("decoHead")
        outer.addWidget(self.shadow_box)
        self.shadow_size = self._slider(outer, tr("deco.size"), ten_ramka.SHADOW_SIZE, "px")
        self.shadow_opacity = self._slider(outer, tr("deco.opacity"), ten_ramka.SHADOW_OPACITY, "%")

        self.frame_box = QCheckBox(tr("deco.frame"))
        self.frame_box.setObjectName("decoHead")
        outer.addSpacing(4)
        outer.addWidget(self.frame_box)
        self.frame_width = self._slider(outer, tr("deco.thickness"), ten_ramka.FRAME_WIDTH, "px")
        row = QHBoxLayout()
        row.setSpacing(5)
        label = QLabel(tr("deco.color"))
        label.setMinimumWidth(86)
        row.addWidget(label)
        self.swatches = {}
        for color in colors:
            b = QPushButton()
            b.setObjectName("decoSwatch")
            b.setCheckable(True)
            b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            b.setAccessibleName(color.upper())
            b.setToolTip(color.upper())
            border = "#8a8f98" if QColor(color).lightnessF() > 0.9 or QColor(color).lightnessF() < 0.1 else color
            b.setStyleSheet(f"QPushButton#decoSwatch {{ background: {color}; border-color: {border}; border-radius: 6px; "
                            "min-width: 22px; max-width: 22px; min-height: 22px; max-height: 22px; }")
            b.clicked.connect(lambda _c=False, col=color: self._pick_color(col))
            self.swatches[color] = b
            row.addWidget(b)
        row.addStretch(1)
        outer.addLayout(row)

        self.margin_box = QCheckBox(tr("deco.margin"))
        self.margin_box.setObjectName("decoHead")
        outer.addSpacing(4)
        outer.addWidget(self.margin_box)
        self.margin_size = self._slider(outer, tr("deco.margin_size"), ten_ramka.MARGIN, "px")
        fill = QHBoxLayout()
        fill.setSpacing(12)
        self.margin_clear = QRadioButton(tr("deco.margin_clear"))
        self.margin_bg = QRadioButton(tr("deco.margin_bg"))
        fill.addWidget(self.margin_clear)
        fill.addWidget(self.margin_bg)
        fill.addStretch(1)
        outer.addLayout(fill)
        if jpg_note:
            note = QLabel(jpg_note)
            note.setObjectName("stNote")
            note.setWordWrap(True)
            note.setMaximumWidth(360)
            outer.addWidget(note)
        self.setMinimumWidth(380)

        self.shadow_box.toggled.connect(lambda v: self._set("shadow", v))
        self.frame_box.toggled.connect(lambda v: self._set("frame", v))
        self.margin_box.toggled.connect(lambda v: self._set("margin_on", v))
        self.margin_bg.toggled.connect(lambda v: self._set("margin_bg", v))
        self._wire(self.shadow_size, "shadow_size")
        self._wire(self.shadow_opacity, "shadow_opacity")
        self._wire(self.frame_width, "frame_width")
        self._wire(self.margin_size, "margin")
        self._loading = False
        self.load(self.deco)

    def _slider(self, outer, text, spec, suffix):
        lo, hi, _d = spec
        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel(text)
        label.setMinimumWidth(86)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(lo, hi)
        slider.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        slider.setAccessibleName(text)
        value = QLabel()
        value.setMinimumWidth(48)
        value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        slider.valueChanged.connect(lambda v, lab=value, suf=suffix: lab.setText(f"{v} {suf}"))
        row.addWidget(label)
        row.addWidget(slider, 1)
        row.addWidget(value)
        outer.addLayout(row)
        slider.label_widget, slider.value_label = label, value
        return slider

    def _wire(self, slider, field):
        slider.sliderPressed.connect(lambda: setattr(self, "_record", True))
        slider.valueChanged.connect(lambda v, f=field, s=slider: self._slider_moved(f, v, s))

    def _slider_moved(self, field, value, slider):
        if self._loading:
            return
        if slider.isSliderDown():
            record, self._record = self._record, False   # первый шаг перетаскивания записывается, остальные нет
        else:
            record = True                                 # клавиши, колесо, щелчок по дорожке: каждый шаг отдельно
        self._set(field, value, record)

    def load(self, deco):
        """Показать значения оформления (без сигналов)."""
        self._loading = True
        self.deco = deco.copy()
        d = self.deco
        self.shadow_box.setChecked(d.shadow)
        self.frame_box.setChecked(d.frame)
        self.margin_box.setChecked(d.margin_on)
        self.shadow_size.setValue(d.shadow_size)
        self.shadow_opacity.setValue(d.shadow_opacity)
        self.frame_width.setValue(d.frame_width)
        self.margin_size.setValue(d.margin)
        self.margin_bg.setChecked(d.margin_bg)
        self.margin_clear.setChecked(not d.margin_bg)
        for color, b in self.swatches.items():
            b.setChecked(color == d.frame_color)
        self._enable()
        self._loading = False

    def _enable(self):
        d = self.deco
        for w in (self.shadow_size, self.shadow_opacity):
            w.setEnabled(d.shadow)
        for w in (self.frame_width, *self.swatches.values()):
            w.setEnabled(d.frame)
        for w in (self.margin_size, self.margin_clear, self.margin_bg):
            w.setEnabled(d.margin_on)

    def _set(self, field, value, record=True):
        if self._loading:
            return
        setattr(self.deco, field, value)
        self._enable()
        self.changed.emit(self.deco.copy(), record)

    def _pick_color(self, color):
        for c, b in self.swatches.items():
            b.setChecked(c == color)
        self._set("frame_color", color)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def popup_at(self, global_pos):
        self.adjustSize()
        self.move(global_pos)
        self.show()
