# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Окно редактирования снимка: открывается в размер скриншота на месте снятой области."""

import datetime
import os
import sys

from PyQt6.QtCore import QEvent, QKeyCombination, QMimeData, QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (QColor, QContextMenuEvent, QDrag, QFont, QFontMetrics, QFontMetricsF, QPolygonF, QGuiApplication, QIcon, QImage, QKeySequence, QPainter, QPainterPath, QPen,
                         QPixmap, QShortcut)
from PyQt6.QtWidgets import (QAbstractButton, QAbstractSpinBox, QKeySequenceEdit, QLineEdit, QTextEdit,
                             QApplication, QButtonGroup, QColorDialog, QDialog, QFileDialog, QFrame, QGraphicsDropShadowEffect,
                             QGridLayout, QHBoxLayout, QLabel, QMainWindow, QMenu, QWidgetAction,
                             QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QToolButton,
                             QVBoxLayout,
                             QWidget)

from . import hidpi, icons
from .dialogs import PALETTES as CARD_PALETTES, ClipDialog
from .frame_extents import track_frame_extents
from .i18n import dynamic, tr
from .menus import style_menu
from .selector import force_foreground, span_rect
from .shapes import (ARROW, BLUR, CALLOUT, CALLOUT_PAD, DARROW, ELLIPSE, FARROW, FLINE, FREEHAND_KINDS, FSHAPE, IMAGE,
                     LINE,
                     MARKER, NUMBER, PENCIL, RECT, SMOOTHED_KINDS, TEXT, Shape, constrain, simplify, text_color_on,
                     text_font)

MOVE, CROP, ERASER = "move", "crop", "eraser"
OCR = "ocr"   # текст с картинки: выделить область, текст в буфер обмена
TRANSLATE = "translate"   # перевод: выделить кусок снимка, перевод ложится поверх (в снимок не попадает)
ERASER_SIZES = {1: 8, 2: 14, 3: 22, 4: 34, 5: 50}   # диаметр кисти ластика по кнопкам толщины

# (инструмент, значок, подсказка, клавиша)
TOOLS = [   # порядок по умолчанию (1.31.1): перемещение, стрелки, фигуры, остальное; свой порядок владельца хранится в tool_order
    (MOVE, "", "editor.tip_move", "V"),
    (ARROW, "", "editor.tip_arrow", "A"),
    (DARROW, "", "editor.tip_darrow", "D"),
    (FARROW, "", "editor.tip_farrow", "F"),
    (FLINE, "", "editor.tip_fline", "G"),
    (LINE, "", "editor.tip_line", "L"),
    (RECT, "", "editor.tip_rect", "R"),
    (ELLIPSE, "", "editor.tip_ellipse", "E"),
    (FSHAPE, "", "editor.tip_fshape", "O"),
    (CALLOUT, "", "editor.tip_callout", "K"),
    (TEXT, "", "editor.tip_text", "T"),
    (NUMBER, "", "editor.tip_number", "N"),
    (MARKER, "", "editor.tip_marker", "M"),
    (PENCIL, "", "editor.tip_pencil", "P"),
    (BLUR, "", "editor.tip_blur", "B"),
    (ERASER, "", "editor.tip_eraser", "X"),
    (OCR, "", "editor.tip_ocr", "I"),
    (TRANSLATE, "", "editor.tip_translate", "Y"),
    (CROP, "", "editor.tip_crop", "C"),
]

PALETTE = ["#d60808", "#ff8c00", "#ffd800", "#2db400", "#1e78ff", "#8b3dff", "#000000", "#808080", "#ffffff"]
DRAW_TOOLS = {ARROW, DARROW, FARROW, FLINE, FSHAPE, LINE, RECT, ELLIPSE, MARKER, PENCIL, NUMBER, BLUR}
STROKE_TOOLS = {MARKER, PENCIL}   # линии ведут вплотную друг к другу: только что проведённая не перехватывает нажатие
OWN_COLORS_MAX = 3                # своих цветов из «+» в палитре, новый вытесняет самый старый
HANDLE = 9   # размер ручки правки, px


IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")


def _is_image_file(path: str) -> bool:
    return bool(path) and path.lower().endswith(IMAGE_EXTENSIONS) and os.path.isfile(path)


def logical_size(image: QImage) -> QSize:
    """Размер картинки в точках экрана: при масштабе Windows 125–150 % снимок не раздувается."""
    return image.deviceIndependentSize().toSize()


def physical_rect(rect: QRect, ratio: float) -> QRect:
    return QRect(round(rect.x() * ratio), round(rect.y() * ratio),
                 max(1, round(rect.width() * ratio)), max(1, round(rect.height() * ratio)))


class Canvas(QWidget):
    resized = pyqtSignal()
    changed = pyqtSignal()                   # снимок изменился (рисование, правка, отмена)
    selection_changed = pyqtSignal(object)   # выделенная фигура или None
    context_requested = pyqtSignal(object, QPoint)   # правый клик: фигура (или None), где показать меню
    text_selected = pyqtSignal(str)                  # режим «Копировать текст»: выделили кусок текста
    text_edit_started = pyqtSignal()                 # открыто поле ввода текста или сноски
    crop_confirmed = pyqtSignal()                    # рамка обрезки применена (кнопка, Enter или двойной щелчок)
    crop_state_changed = pyqtSignal()                # рамка обрезки появилась, подтверждена или отменена
    zoom_requested = pyqtSignal(float, object)       # Ctrl+колесо: во сколько раз изменить масштаб, глобальная точка
    pressed = pyqtSignal()                           # нажатие мыши по снимку (подсказка про цвет объекта уходит)
    size_wheeled = pyqtSignal(int)                   # колесо над выделенным объектом поменяло его толщину
    ZOOM_MIN, ZOOM_MAX = 0.1, 8.0

    def __init__(self, image: QImage, tool, color, size):
        super().__init__()
        # base хранит физические пиксели и масштаб экрана (devicePixelRatio); холст и фигуры — в точках.
        self.base = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        self.base.setDevicePixelRatio(image.devicePixelRatio())
        self._rpress = None        # правая кнопка зажата: {hit, wpos, gpos, moved}; тянуть = переносить, клик = меню
        self._click_candidate = None   # текст/сноска под левой кнопкой: щелчок без сдвига открывает правку
        self._press_wpos = QPoint()
        self.zoom = 1.0            # масштаб вида: только показ, фигуры и итоговый снимок остаются в своих координатах
        self.shapes = []
        self.undo_stack, self.redo_stack = [], []
        self.tool, self.color, self.pen_size = tool, QColor(color), size
        self.text_color = None     # цвет текста в номере и сноске; None — авто
        self.eraser_mode = "object"   # object — объект целиком, part — частично
        self.eraser_size = 2          # размер кисти ластика (кнопки толщины 1–5 при ластике)
        self.eraser_pos = None        # где нарисовать кружок кисти
        self.erasing = None           # проход ластиком: {"changed": bool, "stroke": [...], "targets": {...}}
        self.erase_hover = None       # объект, который сотрётся целиком (подсветка)
        self.modified = False

        self.current = None        # фигура, которая рисуется сейчас
        self.selected = None       # выделенная фигура: её можно двигать, тянуть за ручки, менять цвет/толщину
        # Только что нарисованная фигура (выделена сразу после рисования, пока выделение не сменили). Маркер и
        # карандаш: нажатие на неё начинает новую линию, перенос только за ручку или после щелчка по ней.
        self.fresh = None
        self._grab_on_click = None   # маркер начат поверх только что нарисованной линии: щелчок без сдвига выделит её
        self._pen_saved = None     # правка готового текста: цвет, размер и цвет текста до неё (вернуть после)
        self.drag_from = None
        self.move_pending = False
        self.handle_index = None   # какую ручку выделенной фигуры тянут
        self.crop_start = None
        self.crop_rect = None
        self.words = []            # распознанные слова (ocr.Word, рамки в точках снимка), порядок чтения
        self.words_key = None      # для какого снимка распознано (cacheKey): после обрезки или отмены распознаём заново
        self.text_sel = set()      # выделенные маркером слова (номера в порядке чтения)
        self._text_drag = False
        self._hl_points = []       # мазок маркера, который ведут сейчас
        self.text_mode = "range"   # range: подряд от слова до слова (как на телефоне); marker: только задетые маркером
        self._range_anchor = None
        self.crop_pending = False  # рамка выделена, но ещё не применена: её можно поправить, потом «Обрезать» (Enter)
        self.crop_edge = None      # какую сторону/угол рамки тянут: l, r, t, b, tl, tr, bl, br
        self.crop_move = None      # рамку переносят: точка, с которой начали
        self._crop_orig = QRect()
        self.text_edit = None
        self.text_pos = None
        self.text_kind = TEXT      # TEXT или CALLOUT
        self.text_anchor = None    # для сноски — точка, на которую она указывает
        self._editing_original = None

        self._apply_size()
        self.setMouseTracking(True)
        self.setAcceptDrops(True)        # картинку можно перетащить из папки прямо на снимок
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.update_cursor()

    # --- масштаб вида --------------------------------------------------------

    def lw(self) -> int:
        """Ширина снимка в точках (не зависит от масштаба вида)."""
        return logical_size(self.base).width()

    def lh(self) -> int:
        return logical_size(self.base).height()

    def _ep(self, event) -> QPointF:
        """Позиция мыши в координатах снимка: масштаб вида убран."""
        return QPointF(event.position()) / self.zoom

    def _apply_size(self):
        self.setFixedSize(max(1, round(self.lw() * self.zoom)), max(1, round(self.lh() * self.zoom)))

    def set_zoom(self, zoom: float):
        zoom = max(self.ZOOM_MIN, min(self.ZOOM_MAX, zoom))
        if abs(zoom - self.zoom) < 1e-6:
            return
        self.commit_text()          # открытое поле текста живёт в старом масштабе
        self.zoom = zoom
        self._apply_size()
        self.update()

    def _edit_font(self, size):
        """Шрифт поля ввода текста с учётом масштаба вида."""
        font = text_font(size)
        if font.pixelSize() > 0:
            font.setPixelSize(max(1, round(font.pixelSize() * self.zoom)))
        else:
            font.setPointSizeF(font.pointSizeF() * self.zoom)
        return font

    # --- состояние и отмена ------------------------------------------------

    def push_undo(self):
        self.undo_stack.append((self.base, [s.copy() for s in self.shapes]))
        self.redo_stack.clear()
        self.modified = True
        self.changed.emit()

    def _restore(self, snapshot):
        self.base, shapes = snapshot
        self.shapes = [s.copy() for s in shapes]
        self.select(None)
        self.cancel_crop()
        self._apply_size()
        self.resized.emit()
        self.update()

    def undo(self):
        self.commit_text()
        if self.undo_stack:
            self.redo_stack.append((self.base, [s.copy() for s in self.shapes]))
            self._restore(self.undo_stack.pop())
            self.changed.emit()

    def redo(self):
        self.commit_text()
        if self.redo_stack:
            self.undo_stack.append((self.base, [s.copy() for s in self.shapes]))
            self._restore(self.redo_stack.pop())
            self.changed.emit()

    def select(self, shape):
        if shape is not self.fresh:
            self.fresh = None      # выделили другое или сняли выделение: только что нарисованного больше нет
        if shape is not self.selected:
            self.selected = shape
            self.selection_changed.emit(shape)
        self.update()

    def set_tool(self, tool):
        self.commit_text()
        if tool != CROP:
            self.cancel_crop()
        self.text_sel = set()
        self._text_drag = False
        self._hl_points = []
        self.tool = tool
        if tool != ERASER:
            self.select(None)      # выделение остаётся для ластика: стирать части только выделенного
        self.eraser_pos = None
        self.erase_hover = None
        self.update_cursor()
        self.update()

    def editing_object(self) -> bool:
        """Выделен объект: кнопки цвета и толщины меняют только его; цвет и толщина следующих линий остаются
        прежними, пока человек не нажмёт «Рисовать дальше…» в подсказке (EditorWindow._object_restyled)."""
        return self.selected is not None and self.selected in self.shapes and self.tool != ERASER

    def pen_values(self):
        """Цвет, толщина и цвет текста следующих линий. Во время правки готового текста поле берёт его цвет,
        а настоящие значения лежат в _pen_saved."""
        if self._pen_saved is not None:
            return self._pen_saved
        return self.color, self.pen_size, self.text_color

    _KEEP = object()

    def adopt_pen(self, color=None, size=None, text_color=_KEEP):
        """«Рисовать дальше…»: цвет, толщина или цвет текста становятся значениями следующих линий."""
        cur = list(self.pen_values())
        if color is not None:
            cur[0] = QColor(color)
        if size is not None:
            cur[1] = size
        if text_color is not Canvas._KEEP:
            cur[2] = QColor(text_color) if text_color is not None else None
        if self._pen_saved is not None:
            self._pen_saved = tuple(cur)   # поле правки текста оставляет свой цвет, после правки вернутся эти
        else:
            self.color, self.pen_size, self.text_color = cur

    def set_color(self, color) -> bool:
        """Вернёт True, если поменялся цвет следующих линий (его запоминают настройки). Выделен объект или
        правится готовый текст: меняется только он, вернёт False."""
        if self.editing_object():
            if self.selected.color != QColor(color):
                self.push_undo()
                self.selected.color = QColor(color)
                self.update()
            return False
        self.color = QColor(color)
        if self.text_edit is not None:
            self._style_text_edit()
            if self._pen_saved is not None:
                return False       # правка готового текста: цвет только у него, после правки вернётся прежний
        return True

    def set_text_color(self, color) -> bool:
        """color — QColor или None (авто). Выделен объект — меняется только он (номер, сноска); иначе общий
        выбор. Вернёт True, если поменялся общий выбор."""
        new = QColor(color) if color is not None else None
        if self.editing_object():
            shape = self.selected
            if shape.kind in (NUMBER, CALLOUT) and shape.text_color != new:
                self.push_undo()
                shape.text_color = new
                self.update()
            return False
        self.text_color = new
        if self.text_edit is not None:
            self._style_text_edit()
            self.update()
            if self._pen_saved is not None:
                return False
        return True

    def set_size(self, size) -> bool:
        if self.tool == ERASER:          # при ластике кнопки толщины задают размер кисти
            self.eraser_size = size
            self.update()
            return False
        if self.editing_object():
            if self.selected.size != size:
                self.push_undo()
                self.selected.size = size
                self.update()
            return False
        self.pen_size = size
        if self.text_edit is not None:
            self.text_edit.setFont(self._edit_font(size))
            self._fit_text_edit()
            if self._pen_saved is not None:
                return False       # правка готового текста: размер только у него
        return True

    def delete_selected(self):
        if self.selected in self.shapes:
            self.push_undo()
            self.shapes.remove(self.selected)
            self.renumber()
            self.select(None)

    def renumber(self):
        """Номера идут 1, 2, 3… без пропусков, в прежнем порядке."""
        numbers = sorted((s for s in self.shapes if s.kind == NUMBER), key=lambda s: s.number)
        for i, shape in enumerate(numbers, 1):
            shape.number = i
        self.update()

    def insert_image(self, image: QImage, at: QPointF = None):
        """Вставить картинку поверх снимка: по центру (или в точке at), уменьшив, если не помещается."""
        if image is None or image.isNull():
            return None
        w, h = image.deviceIndependentSize().width(), image.deviceIndependentSize().height()
        scale = min(1.0, self.lw() * 0.9 / w, self.lh() * 0.9 / h)
        w, h = max(8.0, w * scale), max(8.0, h * scale)
        center = at if at is not None else QPointF(self.lw() / 2, self.lh() / 2)
        top_left = QPointF(min(max(0.0, center.x() - w / 2), max(0.0, self.lw() - w)),
                           min(max(0.0, center.y() - h / 2), max(0.0, self.lh() - h)))
        shape = Shape(IMAGE, self.color, self.pen_size, top_left)
        shape.points = [top_left, top_left + QPointF(w, h)]
        shape.image = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        self.commit_text()
        self.push_undo()
        self.shapes.append(shape)
        self.select(shape)
        return shape

    def dragEnterEvent(self, event):
        mime = event.mimeData()
        if mime.hasImage() or any(_is_image_file(u.toLocalFile()) for u in mime.urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        mime = event.mimeData()
        pos = self._ep(event)
        if mime.hasImage():
            self.insert_image(QImage(mime.imageData()), pos)
        else:
            for url in mime.urls():
                if _is_image_file(url.toLocalFile()):
                    self.insert_image(QImage(url.toLocalFile()), pos)
        event.acceptProposedAction()

    def duplicate_selected(self):
        shape = self.selected
        if shape is None or shape not in self.shapes:
            return
        self.push_undo()
        dup = shape.copy()
        dup.translate(QPointF(15, 15))
        if dup.kind == NUMBER:
            dup.number = self.next_number()
        self.shapes.append(dup)
        self.select(dup)

    def restack_selected(self, to_front: bool):
        shape = self.selected
        if shape is None or shape not in self.shapes:
            return
        self.push_undo()
        self.shapes.remove(shape)
        if to_front:
            self.shapes.append(shape)
        else:
            self.shapes.insert(0, shape)
        self.update()

    def toggle_fill_selected(self):
        shape = self.selected
        if shape is not None and shape.kind in (RECT, ELLIPSE, FSHAPE):
            self.push_undo()
            shape.filled = not shape.filled
            self.update()

    def restore_erased_selected(self):
        shape = self.selected
        if shape is not None and shape.erasures:
            self.push_undo()
            shape.erasures = []
            self.update()

    def contextMenuEvent(self, event):
        if self.text_edit is not None:
            return
        if event.reason() == QContextMenuEvent.Reason.Mouse:
            return   # мышью меню открывается при отпускании правой кнопки без сдвига (см. mouseReleaseEvent)
        hit = self.shape_at(QPointF(event.pos()) / self.zoom)   # у QContextMenuEvent нет position(), только pos()
        if hit is not None:
            self.select(hit)
        self.context_requested.emit(hit, event.globalPos())

    def next_number(self):
        return 1 + max((s.number for s in self.shapes if s.kind == NUMBER), default=0)

    def render(self) -> QImage:
        self.commit_text()
        image = self.base.copy()
        image.setDevicePixelRatio(self.base.devicePixelRatio())   # фигуры ложатся в полном разрешении
        p = QPainter(image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for shape in self.shapes:
            shape.paint(p, self.base)
        p.end()
        return image

    # --- отрисовка ---------------------------------------------------------

    def paintEvent(self, _event):
        p = QPainter(self)
        p.scale(self.zoom, self.zoom)
        # 100% на мониторе масштаба снимка: пиксель в пиксель, без сглаживания (резко). Снимок с монитора 150 %
        # в окне на мониторе 100 % уменьшается: со сглаживанием, иначе мелкий текст рвётся.
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform,
                        self.zoom != 1.0 or self.devicePixelRatioF() < self.base.devicePixelRatio() - 0.01)
        p.drawImage(0, 0, self.base)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for shape in self.shapes:
            shape.paint(p, self.base)
        if self.current is not None:
            if self.current.kind == FSHAPE:
                self._paint_open_shape(p, self.current)
            else:
                self.current.paint(p, self.base)
        if self.text_edit is not None and self.text_kind == CALLOUT:
            # Пока печатается текст сноски, блок и указатель видны под полем ввода.
            preview = Shape(CALLOUT, self.color, self.pen_size, self.text_anchor)
            preview.points[-1] = QPointF(self.text_pos)
            preview.text = self.text_edit.toPlainText() or " "
            preview.text_color = self.text_color
            preview.paint(p, self.base)
        if self.selected is not None:
            self._paint_selection(p, self.selected)
        if self.crop_rect is not None:
            self._paint_crop(p, self.crop_rect)
        if self.tool == OCR and self.words and self.words_key == self.base.cacheKey():
            self._paint_words(p)
        if self.tool == ERASER:
            self._paint_eraser(p)

    def eraser_width(self):
        return ERASER_SIZES.get(self.eraser_size, 14)

    def _paint_eraser(self, p):
        if self.erase_hover is not None:
            p.setPen(QPen(QColor(220, 30, 30), 2, Qt.PenStyle.DashLine))
            p.setBrush(QColor(220, 30, 30, 40))
            p.drawRect(self.erase_hover.bounding_rect())
        if self.eraser_pos is not None:
            r = self.eraser_width() / 2 if self.eraser_mode == "part" else 5
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(255, 255, 255), 3))
            p.drawEllipse(self.eraser_pos, r, r)
            p.setPen(QPen(QColor(30, 30, 30), 1.2))
            p.drawEllipse(self.eraser_pos, r, r)

    def _erase_at(self, pos):
        """Шаг ластика до точки pos. Путь от прошлой точки проверяется целиком: быстрый взмах не перепрыгнет линию."""
        state = self.erasing
        prev = state.get("last", pos)
        state["last"] = QPointF(pos)
        step = max(2.0, self.eraser_width() / 4)
        d = pos - prev
        count = max(1, int((abs(d.x()) + abs(d.y())) / step))
        samples = [prev + d * (k / count) for k in range(1, count + 1)] if d != QPointF() else [QPointF(pos)]
        if self.eraser_mode == "object":
            for pt in samples:
                hit = self.shape_at_exact(pt)
                if hit is None:
                    continue
                if not state["changed"]:
                    self.push_undo()
                    state["changed"] = True
                self.shapes.remove(hit)
                if hit is self.selected:
                    self.select(None)
                if hit.kind == NUMBER:
                    self.renumber()
            return
        state["stroke"].append(QPointF(pos))
        half = self.eraser_width() / 2
        targets = [self.selected] if self.selected in self.shapes else self.shapes
        for shape in targets:
            if id(shape) in state["targets"]:
                continue
            area = shape.bounding_rect().adjusted(-half, -half, half, half)
            if any(area.contains(pt) for pt in samples):
                if not state["changed"]:
                    self.push_undo()
                    state["changed"] = True
                shape.erasures.append((self.eraser_width(), state["stroke"]))   # общий список точек прохода
                state["targets"][id(shape)] = shape

    def shape_at_exact(self, pos):
        """Объект, по линии которого (а не по пустому месту внутри рамки) прошёл ластик."""
        return next((s for s in reversed(self.shapes) if s.hit(pos)), None)

    def _paint_open_shape(self, p, shape):
        """Свободная фигура в процессе рисования: контур ещё открыт, замыкание показано тонким пунктиром."""
        pts = shape.points
        pen = QPen(shape.color, shape.pen_width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolyline(QPolygonF(pts))
        if len(pts) > 2:
            p.setPen(QPen(QColor(255, 255, 255, 170), 3))      # светлая подложка: пунктир виден на любом фоне
            p.drawLine(pts[-1], pts[0])
            p.setPen(QPen(shape.color, 1.5, Qt.PenStyle.DashLine))
            p.drawLine(pts[-1], pts[0])

    def _paint_selection(self, p, shape):
        p.setPen(QPen(QColor(0, 174, 255), 1, Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(shape.bounding_rect())
        p.setPen(QPen(QColor(0, 120, 255), 1.5))
        p.setBrush(Qt.GlobalColor.white)
        for pt in shape.handles():
            p.drawRect(QRectF(pt.x() - HANDLE / 2, pt.y() - HANDLE / 2, HANDLE, HANDLE))

    def _paint_crop(self, p, r):
        outside = QColor(0, 0, 0, 140)
        full = QRect(0, 0, self.lw(), self.lh())
        for part in (QRect(0, 0, full.width(), r.top()),
                     QRect(0, r.bottom() + 1, full.width(), full.height()),
                     QRect(0, r.top(), r.left(), r.height()),
                     QRect(r.right() + 1, r.top(), full.width(), r.height())):
            p.fillRect(part, outside)
        p.setPen(QPen(QColor(255, 255, 255), 1, Qt.PenStyle.DashLine))
        p.drawRect(r.adjusted(0, 0, -1, -1))
        if self.crop_pending:
            hs = 9 / self.zoom   # ручки одного размера на экране при любом масштабе
            p.setPen(QPen(QColor(0, 120, 255), 1.5 / self.zoom))
            p.setBrush(Qt.GlobalColor.white)
            for pt in self._crop_handles(r):
                p.drawRect(QRectF(pt.x() - hs / 2, pt.y() - hs / 2, hs, hs))
        label = f"{r.width()} × {r.height()}"
        font = p.font()
        font.setPixelSize(12)
        p.setFont(font)
        box = QRectF(r.left(), max(0, r.top() - 20), QFontMetricsF(font).horizontalAdvance(label) + 10, 18)
        p.fillRect(box, QColor(0, 0, 0, 190))
        p.setPen(Qt.GlobalColor.white)
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, label)

    # --- режим «Копировать текст» -----------------------------------

    def set_words(self, words, ratio: float):
        """Слова от распознавания (рамки в пикселях снимка) переводятся в точки холста."""
        from .ocr import Word
        self.words = [Word(w.text, QRectF(w.rect.x() / ratio, w.rect.y() / ratio,
                                          w.rect.width() / ratio, w.rect.height() / ratio), w.line) for w in words]
        self.words_key = self.base.cacheKey()
        self.text_sel = set()
        self.update()

    def has_words(self) -> bool:
        return bool(self.words) and self.words_key == self.base.cacheKey()

    def _word_index_at(self, pos, exact=False):
        """Слово под курсором; если мимо слов, то ближайшее по строке (как выделение текста в документе)."""
        if not self.has_words():
            return None
        pad = 3
        for i, w in enumerate(self.words):
            if w.rect.adjusted(-pad, -pad, pad, pad).contains(pos):
                return i
        if exact:
            return None
        lines = {}
        for i, w in enumerate(self.words):
            lines.setdefault(w.line, []).append(i)
        def line_box(ids):
            r = QRectF(self.words[ids[0]].rect)
            for i in ids[1:]:
                r = r.united(self.words[i].rect)
            return r
        boxes = {key: line_box(ids) for key, ids in lines.items()}
        inside = [k for k, b in boxes.items() if b.top() - 4 <= pos.y() <= b.bottom() + 4]
        cands = inside or list(boxes)
        key = min(cands, key=lambda k: (abs(boxes[k].center().y() - pos.y()) if not inside else
                                         max(0.0, boxes[k].left() - pos.x(), pos.x() - boxes[k].right())))
        ids = sorted(lines[key], key=lambda i: self.words[i].rect.left())
        best = ids[0]
        for i in ids:
            if self.words[i].rect.left() <= pos.x():
                best = i
        return best

    def selected_text(self) -> str:
        from .ocr import words_text
        if not self.text_sel or not self.has_words():
            return ""
        return words_text([self.words[i] for i in sorted(self.text_sel) if i < len(self.words)])

    def select_all_text(self):
        if self.has_words():
            self.text_sel = set(range(len(self.words)))
            self.update()
            self.text_selected.emit(self.selected_text())

    def marker_width(self) -> float:
        """Толщина маркера: примерно высота строки текста на снимке."""
        if not self.has_words():
            return 14.0
        heights = sorted(w.rect.height() for w in self.words)
        return max(8.0, heights[len(heights) // 2] * 1.3)

    def _mark_segment(self, a, b):
        """Слова, которые задел мазок маркера от точки a до точки b, добавляются к выделению."""
        half = self.marker_width() / 2
        dist = max(abs(b.x() - a.x()), abs(b.y() - a.y()))
        steps = max(1, int(dist / 3))
        points = [a + (b - a) * (k / steps) for k in range(steps + 1)]
        for i, w in enumerate(self.words):
            if i in self.text_sel:
                continue
            area = w.rect.adjusted(-half * 0.5, -half, half * 0.5, half)
            if any(area.contains(pt) for pt in points):
                self.text_sel.add(i)

    def _paint_words(self, p):
        """Найденные слова слегка голубые; выделенные маркером жёлтые, как текстовым выделителем."""
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        for i, w in enumerate(self.words):
            chosen = i in self.text_sel
            p.setBrush(QColor(255, 222, 0, 140) if chosen else QColor(30, 120, 255, 32))
            p.drawRect(w.rect.adjusted(-2, -2, 2, 2))
        if len(self._hl_points) > 1:
            pen = QPen(QColor(255, 222, 0, 90), self.marker_width())
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolyline(QPolygonF(self._hl_points))
        p.restore()

    CROP_MIN = 8   # меньше рамку не сделать, px снимка

    @staticmethod
    def _crop_handles(r):
        x1, y1, x2, y2 = r.x(), r.y(), r.x() + r.width(), r.y() + r.height()
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        return [QPointF(x1, y1), QPointF(mx, y1), QPointF(x2, y1), QPointF(x2, my),
                QPointF(x2, y2), QPointF(mx, y2), QPointF(x1, y2), QPointF(x1, my)]

    def _crop_edge_at(self, pos):
        """Какая сторона или угол рамки обрезки под курсором (None — не на рамке)."""
        r = self.crop_rect
        if r is None:
            return None
        tol = max(3.0, min(10 / self.zoom, min(r.width(), r.height()) / 3))
        x1, y1, x2, y2 = r.x(), r.y(), r.x() + r.width(), r.y() + r.height()
        in_x, in_y = x1 - tol <= pos.x() <= x2 + tol, y1 - tol <= pos.y() <= y2 + tol
        h = "l" if in_y and abs(pos.x() - x1) <= tol else "r" if in_y and abs(pos.x() - x2) <= tol else ""
        v = "t" if in_x and abs(pos.y() - y1) <= tol else "b" if in_x and abs(pos.y() - y2) <= tol else ""
        return (v + h) or None

    def _resize_crop(self, pos):
        o, name = self._crop_orig, self.crop_edge
        x1, y1, x2, y2 = o.x(), o.y(), o.x() + o.width(), o.y() + o.height()
        px = round(max(0, min(self.lw(), pos.x())))
        py = round(max(0, min(self.lh(), pos.y())))
        if "l" in name:
            x1 = min(px, x2 - self.CROP_MIN)
        if "r" in name:
            x2 = max(px, x1 + self.CROP_MIN)
        if "t" in name:
            y1 = min(py, y2 - self.CROP_MIN)
        if "b" in name:
            y2 = max(py, y1 + self.CROP_MIN)
        self.crop_rect = QRect(x1, y1, x2 - x1, y2 - y1)

    def _move_crop(self, pos):
        o = self._crop_orig
        d = pos - self.crop_move
        x = round(max(0, min(self.lw() - o.width(), o.x() + d.x())))
        y = round(max(0, min(self.lh() - o.height(), o.y() + d.y())))
        self.crop_rect = QRect(x, y, o.width(), o.height())

    def confirm_crop(self):
        rect = self.crop_rect
        self.cancel_crop(silent=True)
        if rect is not None and rect.width() > 2 and rect.height() > 2:
            self.apply_crop(rect)
            self.crop_confirmed.emit()
        self.crop_state_changed.emit()

    def cancel_crop(self, silent=False):
        was = self.crop_pending or self.crop_rect is not None
        self.crop_pending, self.crop_rect, self.crop_start = False, None, None
        self.crop_edge = self.crop_move = None
        self.update()
        if was and not silent:
            self.crop_state_changed.emit()

    # --- мышь ----------------------------------------------------------------

    def shape_at(self, pos):
        """Объект под курсором: сначала точное попадание по линиям, затем внутренность рамок."""
        hit = next((s for s in reversed(self.shapes) if s.hit(pos)), None)
        if hit is None:
            hit = next((s for s in reversed(self.shapes) if s.bounding_rect().contains(pos)), None)
        return hit

    def _handle_at(self, pos):
        if self.selected is None:
            return None
        for i, pt in enumerate(self.selected.handles()):
            if abs(pt.x() - pos.x()) <= HANDLE and abs(pt.y() - pos.y()) <= HANDLE:
                return i
        return None

    EDGE_CURSORS = {"l": Qt.CursorShape.SizeHorCursor, "r": Qt.CursorShape.SizeHorCursor,
                    "t": Qt.CursorShape.SizeVerCursor, "b": Qt.CursorShape.SizeVerCursor,
                    "tl": Qt.CursorShape.SizeFDiagCursor, "br": Qt.CursorShape.SizeFDiagCursor,
                    "tr": Qt.CursorShape.SizeBDiagCursor, "bl": Qt.CursorShape.SizeBDiagCursor}

    def update_cursor(self, pos=None):
        if self.tool == ERASER:
            self.setCursor(Qt.CursorShape.BlankCursor if self.eraser_mode == "part" else Qt.CursorShape.CrossCursor)
        elif pos is not None and self._handle_at(pos) is not None:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        elif pos is not None and self.selected is not None and self.selected.hit(pos):
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        elif self.tool == OCR:
            self.setCursor(Qt.CursorShape.IBeamCursor)
        elif self.tool == CROP and self.crop_pending and pos is not None:
            name = self.crop_edge or self._crop_edge_at(pos)
            if name:
                self.setCursor(self.EDGE_CURSORS[name])
            elif self.crop_rect.contains(pos.toPoint()):
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            else:
                self.setCursor(Qt.CursorShape.CrossCursor)
        elif self.tool == MOVE:
            over = pos is not None and self.shape_at(pos) is not None
            self.setCursor(Qt.CursorShape.SizeAllCursor if over else Qt.CursorShape.ArrowCursor)
        elif self.tool == TEXT:
            self.setCursor(Qt.CursorShape.IBeamCursor)
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)

    def mousePressEvent(self, event):
        self.pressed.emit()
        if event.button() == Qt.MouseButton.RightButton:
            self._press_right(event)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = self._ep(event)
        ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if self.text_edit is not None:
            self.commit_text()
            return

        if self.tool == ERASER:
            self.erasing = {"changed": False, "stroke": [], "targets": {}}
            self._erase_at(pos)
            self.update()
            return

        if self.tool == CROP and self.crop_pending:
            edge = self._crop_edge_at(pos)
            if edge:
                self.crop_edge, self._crop_orig = edge, QRect(self.crop_rect)
                return
            if self.crop_rect.contains(pos.toPoint()):
                self.crop_move, self._crop_orig = pos, QRect(self.crop_rect)
                return
            self.crop_pending, self.crop_rect = False, None   # клик снаружи: рамка выделяется заново
            self.crop_state_changed.emit()

        handle = self._handle_at(pos)
        if handle is not None:
            self.handle_index = handle
            self.move_pending = True
            return
        if self.tool != MOVE and self.selected is not None and self.selected.hit(pos) and not (
                self.selected is self.fresh and self.tool in STROKE_TOOLS):
            # Выделенный объект можно двигать любым инструментом. Только что проведённый маркер или карандаш нет:
            # следующую линию часто начинают вплотную к прошлой (её переносят за ручку или после щелчка по ней).
            self.drag_from = pos
            self.move_pending = True
            self._arm_click_edit(self.selected, event)
            return
        if self.tool == TEXT:
            # Щелчок по готовому тексту или сноске: правка (протянуть — перенести), а не новый текст поверх
            hit = self.shape_at(pos)
            if hit is not None and hit.kind in (TEXT, CALLOUT):
                self.select(hit)
                self.drag_from = pos
                self.move_pending = True
                self._arm_click_edit(hit, event)
                self.update()
                return

        if self.tool == MOVE:
            hit = self.shape_at(pos)
            self.select(hit)
            if hit is not None:
                if ctrl:
                    self.push_undo()
                    dup = hit.copy()
                    if dup.kind == NUMBER:
                        dup.number = self.next_number()
                    self.shapes.append(dup)
                    self.select(dup)
                    self.move_pending = False
                else:
                    self.move_pending = True
                    self._arm_click_edit(hit, event)
                self.drag_from = pos
        elif self.tool in (TEXT, CALLOUT):
            self.select(None)
            self.text_anchor = pos
            if self.tool == TEXT:
                self.start_text(pos, TEXT)
            else:
                self.current = Shape(CALLOUT, self.color, self.pen_size, pos)  # пока тянем — только линия
        elif self.tool == OCR and self.text_mode == "range":
            self.select(None)
            idx = self._word_index_at(pos)
            if idx is not None:
                self._range_anchor = idx   # подряд: от этого слова до слова под курсором
                self.text_sel = {idx}
                self._text_drag = True
        elif self.tool == OCR:
            self.select(None)
            if self.has_words():
                if not ctrl:
                    self.text_sel = set()   # новый мазок маркера; с Ctrl добавляется к уже выделенному
                self._text_drag = True
                self._hl_points = [pos]
                self._mark_segment(pos, pos)
        elif self.tool == CROP:
            self.select(None)
            self.crop_start = pos
            self.crop_rect = None
        elif self.tool in DRAW_TOOLS:
            fresh = self.fresh if self.fresh is not None and self.fresh.hit(pos) else None
            self.select(None)
            self._grab_on_click = fresh   # щелчок без сдвига по только что проведённой линии выделит её для переноса
            filled = ctrl and self.tool in (RECT, ELLIPSE, FSHAPE)
            self.current = Shape(self.tool, self.color, self.pen_size, pos, filled)
            if self.tool == NUMBER:
                self.current.number = self.next_number()
                self.current.text_color = QColor(self.text_color) if self.text_color is not None else None
        self.update()

    def _arm_click_edit(self, shape, event):
        """Текст и сноска: щелчок без сдвига откроет правку, сдвиг больше 4 px превратит нажатие в перенос."""
        if shape is not None and shape.kind in (TEXT, CALLOUT):
            self._click_candidate = shape
            self._press_wpos = event.position().toPoint()

    def _press_right(self, event):
        """Правая кнопка: протянуть — перенести объект под курсором (любым инструментом); щелчок — меню действий."""
        if self.text_edit is not None:
            self.commit_text()
            return
        if self.crop_pending:
            self.cancel_crop()   # правая кнопка при рамке обрезки: отмена рамки
            return
        if self.current is not None or self.crop_start is not None or self.erasing is not None:
            return
        pos = self._ep(event)
        hit = self.shape_at(pos)
        self._rpress = {"hit": hit, "wpos": event.position().toPoint(), "gpos": event.globalPosition().toPoint(), "moved": False}
        if hit is not None:
            self.select(hit)
            self.drag_from = pos
            self.move_pending = True
        self._click_candidate = None

    def mouseDoubleClickEvent(self, event):
        if self.tool == OCR:
            idx = self._word_index_at(self._ep(event), exact=True)
            if idx is not None:
                self.text_sel = {idx}   # двойной щелчок: одно слово
                self.update()
                self.text_selected.emit(self.selected_text())
            return
        if self.tool == CROP and self.crop_pending and self.crop_rect.contains(self._ep(event).toPoint()):
            self.confirm_crop()   # двойной щелчок внутри рамки = «Обрезать»
            return
        hit = self.shape_at(self._ep(event))
        if hit is not None and hit.kind in (TEXT, CALLOUT):
            self.edit_text(hit)
        else:
            super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event):
        pos = self._ep(event)
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)

        if self._rpress is not None:
            # Правая кнопка зажата: до 5 px это ещё щелчок (меню), дальше перенос выбранного под курсором объекта
            if not self._rpress["moved"]:
                if (event.position().toPoint() - self._rpress["wpos"]).manhattanLength() < 5:
                    return
                self._rpress["moved"] = True
            if self._rpress["hit"] is None:
                return
        elif self._click_candidate is not None and self.drag_from is not None:
            if (event.position().toPoint() - self._press_wpos).manhattanLength() < 4:
                return
            self._click_candidate = None   # сдвинули: это перенос, а не щелчок
        if self.tool == ERASER and self._rpress is None:
            self.eraser_pos = pos
            if self.erasing is not None:
                self._erase_at(pos)
                self.erase_hover = None
            elif self.eraser_mode == "object":
                self.erase_hover = self.shape_at_exact(pos)
            self.update()
            return
        if self.handle_index is not None and self.selected is not None:
            if self.move_pending:
                self.push_undo()
                self.move_pending = False
            self.selected.drag_handle(self.handle_index, pos, shift)
        elif self.drag_from is not None and self.selected is not None:
            if self.move_pending:
                self.push_undo()
                self.move_pending = False
            delta = pos - self.drag_from
            shape = self.selected
            if shape.kind == NUMBER and not shift:
                shape.points[0] = shape.points[0] + delta      # кружок едет, конец указателя стоит
            elif shape.kind == CALLOUT and not shift:
                shape.points[-1] = shape.points[-1] + delta    # блок едет, точка-цель стоит
            else:
                shape.translate(delta)
            self.drag_from = pos
        elif self.current is not None:
            shape = self.current
            if shape.kind in FREEHAND_KINDS:
                if shift:
                    shape.points = [shape.points[0], pos]
                else:
                    shape.points.append(pos)
            elif shift and shape.kind in (ARROW, DARROW, LINE):
                shape.points[-1] = constrain(shape.points[0], pos, "angle")
            elif shift and shape.kind in (RECT, ELLIPSE):
                shape.points[-1] = constrain(shape.points[0], pos, "square")
            else:
                shape.points[-1] = pos
        elif self._text_drag and self.text_mode == "range":
            idx = self._word_index_at(pos)
            if idx is not None and self._range_anchor is not None:
                a, b = sorted((self._range_anchor, idx))
                self.text_sel = set(range(a, b + 1))
        elif self._text_drag:
            self._mark_segment(self._hl_points[-1], pos)
            self._hl_points.append(pos)
        elif self.crop_edge is not None:
            self._resize_crop(pos)
        elif self.crop_move is not None:
            self._move_crop(pos)
        elif self.crop_start is not None:
            end = constrain(self.crop_start, pos, "square") if shift else pos
            self.crop_rect = span_rect(self.crop_start.toPoint(), end.toPoint()).intersected(
                QRect(0, 0, self.lw(), self.lh()))
        else:
            self.update_cursor(pos)
            return
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton and self._rpress is not None:
            press, self._rpress = self._rpress, None
            self.drag_from = None
            self.move_pending = False
            if not press["moved"] and self.text_edit is None:
                if press["hit"] is not None:
                    self.select(press["hit"])
                self.context_requested.emit(press["hit"], press["gpos"])
            self.update()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        candidate, self._click_candidate = self._click_candidate, None
        was_dragging = self.drag_from is not None
        self.drag_from = None
        self.handle_index = None
        if candidate is not None and was_dragging and candidate in self.shapes:
            self.move_pending = False
            self.edit_text(candidate)   # щелчок по тексту или сноске: сразу правка
            return
        if self.erasing is not None:
            self.erasing = None
            self.update()
            return
        if self.crop_edge is not None or self.crop_move is not None:
            self.crop_edge = self.crop_move = None   # рамку поправили: ждёт «Обрезать»
            self.update_cursor(self._ep(event))
            self.update()
            return
        grab, self._grab_on_click = self._grab_on_click, None
        if self.current is not None:
            shape, self.current = self.current, None
            if shape.kind == CALLOUT:
                self._start_callout(shape)
            elif shape.is_empty() and grab is not None and grab in self.shapes:
                self.select(grab)    # щелчок по только что проведённой линии: теперь её можно тянуть
                self.update_cursor(self._ep(event))
            elif not shape.is_empty():
                if shape.kind in SMOOTHED_KINDS:
                    shape.points = simplify(shape.points, max(6.0, shape.pen_width * 1.2))   # дрожание руки до ~6 px
                self.push_undo()
                self.shapes.append(shape)
                self.select(shape)   # сразу можно поправить толщину, цвет, тянуть за ручки
                self.fresh = shape   # новый цвет для неё станет и цветом следующих линий
        elif self._text_drag:
            self._text_drag = False
            self._hl_points = []
            self._range_anchor = None
            if self.text_sel:
                self.text_selected.emit(self.selected_text())   # отпустили маркер: выделенное в буфер и в окно копирования
        elif self.crop_start is not None:
            self.crop_start = None
            rect = self.crop_rect
            if rect is not None and rect.width() > 2 and rect.height() > 2:
                self.crop_pending = True    # не режем сразу: рамку можно поправить, затем Enter или «Обрезать»
            else:
                self.crop_rect = None
            self.crop_state_changed.emit()
        self.update()

    def apply_crop(self, rect: QRect):
        self.push_undo()
        ratio = self.base.devicePixelRatio()
        self.base = self.base.copy(physical_rect(rect, ratio))
        self.base.setDevicePixelRatio(ratio)
        offset = QPointF(-rect.x(), -rect.y())
        for shape in self.shapes:
            shape.translate(offset)
        self._apply_size()
        self.resized.emit()

    def wheelEvent(self, event):
        """Ctrl+колесо: масштаб вида. Колесо над выделенным объектом меняет его толщину/размер."""
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self.zoom_requested.emit(1.2 ** (delta / 120), event.globalPosition())
            event.accept()
            return
        shape = self.selected
        if shape is not None and shape.bounding_rect().contains(self._ep(event)) and self.text_edit is None:
            step = 1 if event.angleDelta().y() > 0 else -1
            size = max(1, min(5, shape.size + step))
            if size != shape.size:
                self.push_undo()
                shape.size = size
                self.selection_changed.emit(shape)
                self.size_wheeled.emit(size)
                self.update()
            event.accept()
        else:
            super().wheelEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete and self.selected is not None:
            self.delete_selected()
        else:
            super().keyPressEvent(event)

    # --- текст и сноска ----------------------------------------------------

    def _start_callout(self, shape):
        target, end = shape.points[0], shape.points[-1]
        d = end - target
        if abs(d.x()) < 8 and abs(d.y()) < 8:
            end = target + QPointF(30, -50)   # просто клик — блок чуть выше и правее точки
        self.text_anchor = target
        self.start_text(end, CALLOUT)

    def edit_text(self, shape):
        """Двойной клик по тексту/сноске: открыть на правку."""
        self.commit_text()
        self.push_undo()
        self.shapes.remove(shape)
        self.select(None)
        # Поле правки берёт цвет и размер текста; цвет следующих линий после правки возвращается прежний.
        self._pen_saved = (QColor(self.color), self.pen_size,
                           QColor(self.text_color) if self.text_color is not None else None)
        self.color, self.pen_size = QColor(shape.color), shape.size
        self.text_color = QColor(shape.text_color) if shape.text_color is not None else None
        self.text_anchor = shape.points[0]
        self._editing_original = shape   # снимок для Ctrl+Z уже сделан выше
        self.start_text(shape.points[-1] if shape.kind == CALLOUT else shape.points[0], shape.kind, shape.text)

    def start_text(self, pos: QPointF, kind=TEXT, text=""):
        edit = QPlainTextEdit(self)
        edit.setFont(self._edit_font(self.pen_size))
        edit.setFrameShape(QFrame.Shape.NoFrame)
        edit.document().setDocumentMargin(0)
        edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text_edit, self.text_pos, self.text_kind = edit, pos, kind
        self._style_text_edit()
        pad = CALLOUT_PAD if kind == CALLOUT else 0
        edit.move((pos * self.zoom).toPoint() + QPoint(round(pad * self.zoom), round(pad * self.zoom)))
        edit.setPlainText(text)
        edit.textChanged.connect(self._fit_text_edit)
        edit.textChanged.connect(self.update)
        edit.installEventFilter(self)
        self._fit_text_edit()
        edit.show()
        edit.setFocus()
        edit.moveCursor(edit.textCursor().MoveOperation.End)
        self.update()
        self.text_edit_started.emit()

    def _style_text_edit(self):
        c = self.color.name()
        if self.text_kind == CALLOUT:
            fg = (self.text_color or text_color_on(self.color)).name()
            css = f"background: transparent; color: {fg}; border: none;"   # фон даёт блок под полем
        else:
            css = f"background: rgba(255,255,255,60); color: {c}; border: 1px dashed {c};"
        self.text_edit.setStyleSheet(f"QPlainTextEdit {{ {css} }}")

    def _fit_text_edit(self):
        edit = self.text_edit
        fm = QFontMetricsF(edit.font())
        lines = edit.toPlainText().split("\n")
        width = max(fm.horizontalAdvance(line) for line in lines) + fm.horizontalAdvance("MM")
        edit.resize(int(max(width, 60)) + 4, int(fm.lineSpacing() * len(lines)) + 6)

    def eventFilter(self, obj, event):
        if obj is self.text_edit:
            if event.type() == QEvent.Type.ShortcutOverride:
                # Пока вводится текст, все клавиши (Enter, Esc, буквы) достаются полю ввода.
                event.accept()
                return True
            if event.type() == QEvent.Type.KeyPress:
                if event.key() == Qt.Key.Key_Escape:
                    self.cancel_text()
                    return True
                if (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                        and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                    self.commit_text()
                    return True
            elif event.type() == QEvent.Type.FocusOut:
                QTimer.singleShot(0, self.commit_text)
        return super().eventFilter(obj, event)

    def commit_text(self, cancelled=False):
        edit = self.text_edit
        if edit is None:
            return
        self.text_edit = None
        text = edit.toPlainText().rstrip()
        edit.removeEventFilter(self)
        edit.hide()          # спрятать сразу: удаление произойдёт позже, а текст уже рисует фигура
        edit.deleteLater()
        original = getattr(self, "_editing_original", None)
        self._editing_original = None
        if cancelled and original is not None:
            shape = original                # Esc при правке — вернуть как было
            self.undo_stack.pop()
        elif text.strip():
            shape = Shape(self.text_kind, self.color, self.pen_size, self.text_anchor or self.text_pos)
            shape.text = text
            shape.text_color = QColor(self.text_color) if self.text_color is not None else None
            if self.text_kind == CALLOUT:
                shape.points[-1] = QPointF(self.text_pos)
                # Блок сноски целиком внутри снимка, иначе текст обрежется при копировании.
                box = shape.callout_box()
                dx = max(-box.left(), min(0.0, self.lw() - box.right()))
                dy = max(-box.top(), min(0.0, self.lh() - box.bottom()))
                shape.points[-1] = shape.points[-1] + QPointF(dx, dy)
        else:
            shape = None
        if self._pen_saved is not None:
            self.color, self.pen_size, self.text_color = self._pen_saved
            self._pen_saved = None
        if shape is not None:
            if original is None:
                self.push_undo()
            self.shapes.append(shape)
            self.select(shape)
            if original is None:
                self.fresh = shape   # новый текст или сноска: как только что нарисованная линия
        self.setFocus()
        self.update()

    def cancel_text(self):
        if self.text_edit is not None:
            self.text_edit.setPlainText("")
            self.commit_text(cancelled=True)


ACCENT = "#1e78ff"
FRAME_WIDTH = 1   # тонкая линия вокруг самого снимка
BORDER = 8        # толщина рамки окна по умолчанию (настройка «Толщина рамки»: 4, 8, 12)
SHADOW = 16       # поле вокруг скруглённой карточки окна: тень и ореол (только своё оформление окна)
RADIUS = 12       # скругление углов окна
RADIUS_THIN = 8   # 1.32, вид «Тонкая линия»: скругление окна как в эскизе А
TITLE_H = 38      # своя шапка окна
GRAB = 8          # ширина зоны захвата края окна для изменения размера, px
FRAME_STYLE_KEYS = (("thin", "editor.frame_thin"), ("glow", "editor.frame_glow"), ("thick", "editor.frame_thick"),
                    ("plain", "editor.frame_plain"))


def __getattr__(name):
    """FRAME_STYLES: пары (код, надпись) на текущем языке; считаются при обращении, не при импорте."""
    if name == "FRAME_STYLES":
        return tuple((code, tr(key)) for code, key in FRAME_STYLE_KEYS)
    raise AttributeError(name)

# Оформление по умолчанию; меняется в настройках (раздел «Оформление»).
THEME_DEFAULTS = {"ui_accent": ACCENT, "ui_panel": "#f5f6f8", "ui_field": "#34383e", "ui_frame": BORDER}
# Цвета панелей и поля из оформлений до 1.32: считаются «не своими» и заменяются спокойной палитрой 1.32 (вид А).
# Настройки сохраняют цвета целиком, поэтому прежние значения встречаются у всех, кто хоть раз нажимал «Сохранить».
PRESET_PANELS = {"#d9dbdf", "#232323", "#f5f6f8", "#202327"}
PRESET_FIELDS = {"#3a3d42", "#121212", "#34383e", "#111315"}


def theme(cfg) -> dict:
    from . import themes
    return themes.tokens(cfg)


def frame_style(cfg) -> str:
    """Вид рамки окна: thin (тонкая линия и мягкая тень, с 1.32 по умолчанию), glow (тонкая линия со свечением),
    thick (толстая скруглённая), plain (без цветной рамки). «Свечение» было видом по умолчанию до 1.32 и записано в
    настройки у всех: пока вид не выбран в окне настроек 1.32 (frame_style_132), оно читается как «Тонкая линия»."""
    cfg = cfg or {}
    value = cfg.get("editor_frame_style", "thin")
    if value == "glow" and not cfg.get("frame_style_132"):
        value = "thin"
    return value if value in dict(FRAME_STYLE_KEYS) else "thin"


def palette(cfg) -> dict:
    """Цвета редактора 1.32 (вид А, «спокойный»): поверхности, текст, разделители, поле вокруг снимка, акцент.
    Свои цвета панелей и поля из настроек сохраняются; прежние цвета оформлений заменяются новой палитрой."""
    t = theme(cfg)
    accent = QColor(t["ui_accent"])
    panel_c = QColor(t["ui_panel"])
    dark = panel_c.lightnessF() < 0.45
    if str(t["ui_panel"]).lower() in PRESET_PANELS:
        if dark:
            p = {"win": "#25282c", "panel": "#202327", "s2": "#2f3338", "s3": "#383d43", "sep": "#3a3f46",
                 "t": "#f1f3f5", "t2": "#aab1ba"}
        else:
            p = {"win": "#ffffff", "panel": "#f5f6f8", "s2": "#eceff3", "s3": "#e1e5eb", "sep": "#d8dde5",
                 "t": "#1f2328", "t2": "#5f6875"}
    else:   # свой цвет панелей: оттенки из него (подложка окна чуть светлее выбранного цвета, как до 1.32)
        p = {"win": panel_c.lighter(118 if dark else 104).name(), "panel": panel_c.lighter(104 if dark else 106).name(),
             "s2": panel_c.lighter(130).name() if dark else panel_c.darker(106).name(),
             "s3": panel_c.lighter(150).name() if dark else panel_c.darker(112).name(),
             "sep": panel_c.lighter(160).name() if dark else panel_c.darker(118).name(),
             "t": t["text"] if dark else "#1f2328", "t2": t["text_dim"] if dark else "#5f6875"}
    field = str(t["ui_field"]).lower()
    p["stage"] = ("#111315" if dark else "#34383e") if field in PRESET_FIELDS else QColor(t["ui_field"]).lighter(125).name()
    r, g, b = accent.red(), accent.green(), accent.blue()
    from . import themes as _t
    p.update({"dark": dark, "acc": accent.name(), "accs": f"rgba({r}, {g}, {b}, {66 if dark else 36})", "link": _t.link_color(dark),
              "hover": "rgba(255, 255, 255, 18)" if dark else "rgba(0, 0, 0, 14)",
              "quick": "rgba(255, 255, 255, 18)" if dark else "rgba(0, 0, 0, 15)"})
    return p


def chrome_params(cfg) -> dict:
    """Всё, что нужно для рисования рамки окна редактора: вид, цвета, толщина линии и ореола."""
    t = theme(cfg)
    accent = QColor(t["ui_accent"])
    pal = palette(cfg)
    dark = pal["dark"]
    fill = QColor(pal["panel"])
    style = frame_style(cfg)
    px = int(t["ui_frame"])
    if style == "glow":
        line = 2 if px <= 4 else (3 if px <= 8 else 4)   # тонкая линия: 2-4 px по настройке «Толщина рамки»
        halo = line + 4
        color = QColor(accent)
    elif style == "thick":
        line, halo, color = px, 0, QColor(accent)
    elif style == "thin":   # 1.32: тонкая линия цвета акцента без свечения и одна мягкая тень
        line, halo = 1, 0
        color = QColor(accent)
        color.setAlpha(170 if dark else 150)
    else:
        line, halo = 1, 0
        color = QColor(255, 255, 255, 70) if dark else QColor(0, 0, 0, 46)   # нейтральная тонкая обводка
    return {"style": style, "dark": dark, "fill": fill, "line": line, "halo": halo, "color": color,
            "accent": accent, "system": bool(cfg.get("editor_system_title", False))}


SOFT = {   # 1.32: «Копировать текст» и «Перевести» мягкой заливкой: (фон, текст, наведение, отмеченная) светлое / тёмное
    "ocr": (("#efe7fe", "#5b21b6", "#e4d6fd", "#7c3aed"), ("#2e2547", "#d9c8ff", "#3a2f5a", "#7c3aed")),
    "tr": (("#e0f4f1", "#0b5f57", "#cdeee9", "#0b766c"), ("#13302d", "#a7ece4", "#1a3f3b", "#0b766c")),   # отмеченная: themes.TEAL_BUTTON
}


def soft_colors(kind: str, dark: bool) -> tuple:
    return SOFT[kind][1 if dark else 0]


def make_style(cfg) -> str:
    """Стиль окна редактора 1.32 (вид А): светлые спокойные поверхности, выбранный инструмент мягкой подложкой,
    «Сохранить» и «Скопировать» лёгкие, одна яркая зелёная «Скопировать и закрыть». Из оформления и своих цветов."""
    t = theme(cfg)
    P = palette(cfg)
    dark = P["dark"]
    accent = QColor(t["ui_accent"])
    a = accent.name()
    info = P["t2"]
    font = t["font"]
    from . import themes as G   # 1.32: зелёный главной кнопки из одного места
    ocr_bg, ocr_fg, ocr_hover, ocr_on = soft_colors("ocr", dark)
    tr_bg, tr_fg, tr_hover, tr_on = soft_colors("tr", dark)
    return f"""
QMainWindow {{ background: transparent; }}
#panel, #bottom, #titlebar, #modeHint {{ background: transparent; color: {P['t']}; }}
#panel {{ border-bottom: 1px solid {P['sep']}; }}
#bottom {{ border-top: 1px solid {P['sep']}; }}
QToolButton {{ color: {P['t']}; }}
QToolButton#tool, QToolButton#group, QToolButton#action, QToolButton#more, QToolButton#bell {{
    border: none; border-radius: 6px; padding: 3px; background: transparent; }}
QToolButton#group {{ padding-right: {GROUP_ARROW_W + 3}px; }}
QToolButton#more {{ padding: 0px 10px 0px 7px; background: {P['s2']}; font-size: {font - 1}px; }}
QToolButton#tool:hover, QToolButton#group:hover, QToolButton#action:hover, QToolButton#bell:hover {{ background: {P['hover']}; }}
QToolButton#more:hover {{ background: {P['s3']}; }}
QToolButton#tool:checked, QToolButton#group:checked {{ background: {P['accs']}; }}
QToolButton#action::menu-indicator, QToolButton#bell::menu-indicator {{ image: none; width: 0px; }}
QToolButton#size {{ border: none; border-radius: 4px; padding: 0px 6px; background: transparent; }}
QToolButton#size:hover {{ background: {P['hover']}; }}
QToolButton#size:checked {{ background: {P['win'] if not dark else P['s3']}; border: 1px solid {P['sep']}; }}
QFrame#sizeSeg {{ background: {P['s2']}; border-radius: 6px; }}
QFrame#sep {{ background: {P['sep']}; }}
QFrame#quickGroup {{ background: {P['quick']}; border: 1px solid {P['sep']}; border-radius: 9px; }}
QScrollArea, #stage {{ background: {P['stage']}; border: none; }}
#imageFrame {{ background: {t['image_frame']}; }}
QPushButton {{ min-height: 30px; padding: 0 14px; border-radius: 6px; font-size: {font}px;
    border: 1px solid {P['sep']}; background: {P['win']}; color: {P['t']}; }}
QPushButton:hover {{ background: {P['s2']}; }}
QPushButton#light {{ min-height: 34px; padding: 0 13px 0 10px; border: none; background: {P['s2']}; }}
QPushButton#light:hover {{ background: {P['s3']}; }}
QFrame#zoomGroup {{ border: 1px solid {P['sep']}; border-radius: 6px; background: {P['win']}; }}
QPushButton#zoomSeg {{ min-height: 30px; padding: 0px; border: none; border-left: 1px solid {P['sep']};
    border-radius: 0px; background: transparent; }}
QPushButton#zoomSeg[first="true"] {{ border-left: none; border-top-left-radius: 5px; border-bottom-left-radius: 5px; }}
QPushButton#zoomSeg[last="true"] {{ border-top-right-radius: 5px; border-bottom-right-radius: 5px; }}
QPushButton#zoomSeg[big="true"] {{ font-size: 18px; }}
QPushButton#zoomSeg:hover {{ background: {P['s2']}; }}
QPushButton#primary {{ background: {G.blue_button(a)[0]}; color: white; border: 1px solid {G.blue_button(a)[2]};
    font-weight: bold; }}
QPushButton#primary:hover {{ background: {G.blue_button(a)[1]}; }}
QPushButton#finish {{ min-height: 38px; padding: 0 18px 0 14px; font-size: {font + 1}px; font-weight: bold; color: white;
    background: {G.GREEN}; border: 1px solid {G.GREEN_BORDER}; border-radius: 6px; }}
QPushButton#finish:hover {{ background: {G.GREEN_HOVER}; }}
QPushButton#finish:pressed {{ background: {G.GREEN_PRESSED}; }}
QPushButton#ocrButton {{ min-height: 32px; padding: 0 12px 0 9px; border: none; border-radius: 6px; font-weight: 600;
    background: {ocr_bg}; color: {ocr_fg}; }}
QPushButton#ocrButton:hover {{ background: {ocr_hover}; }}
QPushButton#ocrButton:checked {{ background: {ocr_on}; color: white; }}
QPushButton#trAllButton, QPushButton#trButton {{ min-height: 32px; border: none; font-weight: 600; background: {tr_bg};
    color: {tr_fg}; }}
QPushButton#trAllButton {{ padding: 0 11px 0 9px; border-top-left-radius: 6px; border-bottom-left-radius: 6px;
    border-top-right-radius: 0px; border-bottom-right-radius: 0px; }}
QPushButton#trButton {{ padding: 0 11px; border-left: 1px solid rgba(11, 143, 132, 90); border-top-right-radius: 6px;
    border-bottom-right-radius: 6px; border-top-left-radius: 0px; border-bottom-left-radius: 0px; }}
QPushButton#trAllButton:hover, QPushButton#trButton:hover {{ background: {tr_hover}; }}
QPushButton#trButton:checked {{ background: {tr_on}; color: white; }}
QLabel#info {{ color: {info}; font-size: {font - 1}px; background: transparent; }}
QLabel#winTitle {{ color: {P['t']}; font-weight: 600; font-size: {font}px; background: transparent; }}
QLabel#modeHint {{ color: {P['t']}; font-size: {max(15, font + 1)}px; padding: 10px 12px;
    border-top: 1px solid {P['sep']}; }}
#trTop {{ background: {'#12302d' if dark else '#eaf7f5'}; color: {P['t']}; border-bottom: 2px solid #0b8f84; }}
#trTop[mode="text"] {{ background: {'#2a1d4a' if dark else '#f3edff'}; border-bottom: 2px solid #7c3aed; }}
#trTop[mode="crop"] {{ background: {'#16301f' if dark else '#eaf7ee'}; border-bottom: 2px solid #1f9d55; }}
QLabel#trTitle {{ color: {P['t']}; font-weight: bold; font-size: {font + 5}px; background: transparent; }}
QLabel#trSub {{ color: {info}; font-size: {font - 1}px; background: transparent; }}
QPushButton#modeDone, QPushButton#modeMain {{ min-height: 38px; min-width: 130px; padding: 0 18px; font-size: {font + 2}px;
    font-weight: bold; color: white; background: {G.TEAL_BUTTON}; border: 1px solid {G.TEAL_BUTTON_BORDER}; border-radius: 6px; }}
QPushButton#modeDone:hover, QPushButton#modeMain:hover {{ background: {G.TEAL_BUTTON_HOVER}; }}
QPushButton#modeDone[mode="text"], QPushButton#modeMain[mode="text"] {{ background: #7c3aed; border: 1px solid #5b21b6; }}
QPushButton#modeDone[mode="text"]:hover {{ background: {G.VIOLET_HOVER}; }}
QPushButton#modeDone[mode="crop"] {{ background: {P['win']}; color: {P['t']}; border: 1px solid {P['sep']}; }}
QPushButton#modeMain[mode="crop"] {{ background: {G.GREEN}; border: 1px solid {G.GREEN_BORDER}; }}
QPushButton#modeMain[mode="crop"]:hover {{ background: {G.GREEN_HOVER}; }}
QPushButton#modeMain:disabled {{ background: {P['s2']}; color: {info}; border: 1px solid {P['sep']}; }}
#textBottom {{ background: {'#2a1d4a' if dark else '#f3edff'}; border-top: 2px solid #7c3aed; }}
QLabel#textMessage {{ color: {'#d9c8ff' if dark else '#3b1a7a'}; font-size: {max(15, font + 1)}px; background: transparent; }}
QPushButton#textCopySel {{ min-height: 30px; padding: 0 14px; font-weight: bold; color: {'#d9c8ff' if dark else '#3b1a7a'};
    background: {P['win']}; border: 1px solid #7c3aed; }}
QPushButton#textCopyAll {{ min-height: 30px; padding: 0 14px; font-weight: bold; color: white; background: #7c3aed; border: 1px solid #5b21b6; }}
QPushButton#textCopyAll:hover {{ background: {G.VIOLET_HOVER}; }}
#trBottom {{ background: {'#12302d' if dark else '#eaf7f5'}; border-top: 2px solid #0b8f84; }}
QLabel#trMessage {{ color: {'#a7ece4' if dark else '#0b5f57'}; font-size: {font}px; background: transparent; }}
QPushButton#trLang, QPushButton#trSegL, QPushButton#trSegR {{ min-height: 30px; padding: 0 12px; font-weight: bold;
    color: {'#a7ece4' if dark else '#0b5f57'}; background: {P['win']}; border: 1px solid #0b8f84; }}
QPushButton#trSegL {{ border-top-right-radius: 0px; border-bottom-right-radius: 0px; }}
QPushButton#trSegR {{ border-top-left-radius: 0px; border-bottom-left-radius: 0px; border-left: none; }}
QPushButton#trSegL:checked, QPushButton#trSegR:checked {{ background: {G.TEAL_BUTTON}; color: white; }}
QPushButton#trCopy {{ min-height: 30px; padding: 0 14px; font-weight: bold; color: white; background: {G.TEAL_BUTTON};
    border: 1px solid {G.TEAL_BUTTON_BORDER}; }}
QPushButton#trCopy:hover {{ background: {G.TEAL_BUTTON_HOVER}; }}
"""


class WinButton(QToolButton):
    """Круглая кнопка своей шапки окна: свернуть, развернуть (восстановить), закрыть. Значок рисуется сам."""

    def __init__(self, kind: str, tip: str):
        super().__init__()
        self.kind = kind   # min | max | restore | close
        self.setObjectName("winButton")
        self.setToolTip(tip)
        self.setFixedSize(28, 28)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.ArrowCursor)   # над кнопкой шапки обычная стрелка, «перемещение» только на свободном месте

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        danger = self.kind == "close"
        if self.underMouse() or self.isDown():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(220, 53, 69, 215 if self.isDown() else 190) if danger else QColor(128, 128, 128, 70))
            p.drawEllipse(QRectF(self.rect()).adjusted(1, 1, -1, -1))
        color = QColor("#ffffff") if danger and self.underMouse() else QColor(icons.ICON_COLOR)
        p.setPen(QPen(color, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        c = QPointF(self.rect().center()) + QPointF(0.0, 0.0)
        k = 4.5
        if self.kind == "min":
            p.drawLine(QPointF(c.x() - k, c.y() + 3), QPointF(c.x() + k, c.y() + 3))
        elif self.kind == "max":
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(c.x() - k, c.y() - k, 2 * k, 2 * k), 1.5, 1.5)
        elif self.kind == "restore":
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(c.x() - k, c.y() - k + 2.5, 2 * k - 2.5, 2 * k - 2.5), 1.5, 1.5)
            p.drawPolyline(QPolygonF([QPointF(c.x() - k + 2.5, c.y() - k + 2.5 - 0.0), QPointF(c.x() - k + 2.5, c.y() - k),
                                      QPointF(c.x() + k, c.y() - k), QPointF(c.x() + k, c.y() + k - 2.5),
                                      QPointF(c.x() + k - 2.5, c.y() + k - 2.5)]))
        else:
            p.drawLine(QPointF(c.x() - k + 0.5, c.y() - k + 0.5), QPointF(c.x() + k - 0.5, c.y() + k - 0.5))
            p.drawLine(QPointF(c.x() + k - 0.5, c.y() - k + 0.5), QPointF(c.x() - k + 0.5, c.y() + k - 0.5))


class TitleBar(QWidget):
    """Своя тонкая шапка окна: слева значок и «ClipSD», справа свернуть, развернуть, закрыть."""

    def __init__(self, window, icon: QIcon):
        super().__init__()
        self.setObjectName("titlebar")
        self.setFixedHeight(TITLE_H)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 0, 8, 0)
        row.setSpacing(8)
        self.icon_label = QLabel()
        self.icon_label.setPixmap(icon.pixmap(20, 20))
        self.icon_label.setFixedSize(20, 20)
        row.addWidget(self.icon_label)
        self.label = QLabel("ClipSD")
        self.label.setObjectName("winTitle")
        row.addWidget(self.label)
        row.addStretch(1)
        self.icons_widget = None   # 1.32: колокольчик, «?», шестерёнка и глобус справа в шапке (set_icons)
        self.min_button = WinButton("min", tr("editor.minimize"))
        self.max_button = WinButton("max", tr("editor.maximize"))
        self.close_button = WinButton("close", tr("editor.close"))
        self.min_button.clicked.connect(window.minimize_window)
        self.max_button.clicked.connect(window.toggle_maximized)
        self.close_button.clicked.connect(window.close)   # тот же путь, что у прежнего закрытия: вопрос «Снимок не сохранён»
        for b in (self.min_button, self.max_button, self.close_button):
            row.addWidget(b)

    def set_icons(self, widget):
        """Колокольчик, «?», шестерёнка, глобус (1.32): в своей шапке перед кнопками окна, с промежутком 10 px."""
        row = self.layout()
        if self.icons_widget is not None:
            row.removeWidget(self.icons_widget)
            self.icons_widget.hide()
            self.icons_widget.deleteLater()
            spacer = row.itemAt(row.indexOf(self.min_button) - 1)
            if spacer is not None and spacer.spacerItem() is not None:
                row.removeItem(spacer)
        self.icons_widget = widget
        i = row.indexOf(self.min_button)
        row.insertWidget(i, widget)
        row.insertSpacing(i + 1, 10)
        widget.show()

    def set_maximized(self, on: bool):
        self.max_button.kind = "restore" if on else "max"
        self.max_button.setToolTip(tr("editor.restore") if on else tr("editor.maximize"))
        self.max_button.update()


class DragFilter(QObject):
    """Перетаскивание окна за шапку и за свободные места панелей; двойной щелчок по шапке разворачивает."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.drag = None

    def eventFilter(self, obj, event):
        t, w = event.type(), self.window
        if t == QEvent.Type.MouseButtonDblClick and obj is getattr(w, "titlebar", None) \
                and event.button() == Qt.MouseButton.LeftButton:
            self.drag = None
            w.toggle_maximized()
            return True
        if t == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            if w.isMaximized():
                return True
            handle = w.windowHandle()
            if handle is not None and handle.startSystemMove():
                return True
            self.drag = event.globalPosition().toPoint() - w.frameGeometry().topLeft()   # запасной ручной перенос
            return True
        if t == QEvent.Type.MouseMove and self.drag is not None:
            if event.buttons() & Qt.MouseButton.LeftButton:
                w.move(event.globalPosition().toPoint() - self.drag)
            else:
                self.drag = None
            return True
        if t == QEvent.Type.MouseButtonRelease:
            self.drag = None
        return False


class ChromeShell(QWidget):
    """Подложка окна: рисует скруглённую карточку с тенью и рамкой выбранного вида, ловит края для изменения размера.
    Дети лежат внутри карточки с отступом, поэтому рамка их не перекрывается."""

    def __init__(self, window):
        super().__init__()
        self.setObjectName("shell")
        self.win = window
        self.params = chrome_params(window.ctx.config)
        self.setMouseTracking(True)
        self.layout_ = QVBoxLayout(self)
        self.layout_.setSpacing(0)
        self.apply()

    def custom(self) -> bool:
        return not self.params["system"]

    def maximized(self) -> bool:
        return self.win.isMaximized() or self.win.isFullScreen()

    def outer(self) -> int:
        """Поле тени вокруг карточки; без своей рамки окна и в развёрнутом виде его нет."""
        return SHADOW if self.custom() and not self.maximized() else 0

    def radius(self) -> int:
        if not self.outer():
            return 0
        return RADIUS_THIN if self.params["style"] == "thin" else RADIUS

    def inner(self) -> int:
        """Отступ содержимого внутри карточки: рамка и (в системном окне) внутренний ореол."""
        p = self.params
        if self.custom() and self.maximized():
            return 0
        extra = p["halo"] if not self.custom() else 0
        return p["line"] + extra + (1 if p["style"] in ("glow", "thick") else 0)

    def apply(self, params=None):
        if params is not None:
            self.params = params
        m = self.outer() + self.inner()
        self.layout_.setContentsMargins(m, m, m, m)
        self.update()

    def card(self) -> QRectF:
        o = self.outer()
        return QRectF(self.rect()).adjusted(o, o, -o, -o)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pr = self.params
        r, card = self.radius(), self.card()
        dark = pr["dark"]
        if self.outer():
            p.setPen(Qt.PenStyle.NoPen)
            if pr["style"] == "thin":   # 1.32: одна мягкая широкая тень (как 0 12px 36px) и тонкая близкая
                for i in range(15, 0, -1):
                    p.setBrush(QColor(0, 0, 0, 4 if not dark else 7))
                    p.drawRoundedRect(card.adjusted(-i, -i + 6, i, i + 6), r + i, r + i)
                p.setBrush(QColor(0, 0, 0, 22 if not dark else 40))
                p.drawRoundedRect(card.adjusted(-1, 0, 1, 2), r + 1, r + 1)
            else:
                deep = 1.5 if pr["style"] == "plain" else 1.0   # вид «без цветной рамки»: тень глубже
                for i in range(14, 0, -2):
                    alpha = int((6 if not dark else 9) * deep)
                    p.setBrush(QColor(0, 0, 0, alpha))
                    p.drawRoundedRect(card.adjusted(-i, -i + 7, i, i + 7), r + i, r + i)
            if pr["halo"] and pr["style"] == "glow":
                halo = QColor(pr["color"])
                halo.setAlpha(70)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(halo, 2 * pr["halo"]))
                p.drawRoundedRect(card, r, r)
        path = QPainterPath()
        path.addRoundedRect(card, r, r)
        p.fillPath(path, pr["fill"])
        if self.custom() and self.maximized():
            return
        lw = pr["line"]
        p.setBrush(Qt.BrushStyle.NoBrush)
        if not self.custom() and pr["style"] == "glow":   # системное окно: ореол внутри линии
            halo = QColor(pr["color"])
            halo.setAlpha(70)
            p.setPen(QPen(halo, pr["halo"]))
            p.drawRect(card.adjusted(lw + pr["halo"] / 2, lw + pr["halo"] / 2, -lw - pr["halo"] / 2, -lw - pr["halo"] / 2))
        p.setPen(QPen(pr["color"], lw))
        p.drawRoundedRect(card.adjusted(lw / 2, lw / 2, -lw / 2, -lw / 2), max(0, r - lw / 2), max(0, r - lw / 2))

    # --- края окна: изменение размера -------------------------------------------

    def edge_at(self, pos) -> Qt.Edge:
        """Какие края окна под точкой (зона захвата GRAB px у края карточки и крупнее у углов)."""
        none = Qt.Edge(0)
        if not self.custom() or self.maximized() or self.win.isFullScreen():
            return none
        c = self.card()
        x, y = pos.x(), pos.y()
        if not c.adjusted(-GRAB, -GRAB, GRAB, GRAB).contains(QPointF(x, y)):
            return none
        e = none
        near = max(3, int(self.params["line"]))   # внутрь карточки только линия рамки (3 px у тонкой): шапка отдана переносу
        corner = 2 * GRAB + 4
        left, right = x < c.left() + near, x > c.right() - near
        top, bottom = y < c.top() + near, y > c.bottom() - near
        if x < c.left() + corner and y < c.top() + near or (left and y < c.top() + corner):
            left, top = True, True
        if x > c.right() - corner and y < c.top() + near or (right and y < c.top() + corner):
            right, top = True, True
        if x < c.left() + corner and y > c.bottom() - near or (left and y > c.bottom() - corner):
            left, bottom = True, True
        if x > c.right() - corner and y > c.bottom() - near or (right and y > c.bottom() - corner):
            right, bottom = True, True
        for flag, edge in ((left, Qt.Edge.LeftEdge), (right, Qt.Edge.RightEdge),
                           (top, Qt.Edge.TopEdge), (bottom, Qt.Edge.BottomEdge)):
            if flag:
                e |= edge
        return e

    CURSORS = {Qt.Edge.LeftEdge: Qt.CursorShape.SizeHorCursor, Qt.Edge.RightEdge: Qt.CursorShape.SizeHorCursor,
               Qt.Edge.TopEdge: Qt.CursorShape.SizeVerCursor, Qt.Edge.BottomEdge: Qt.CursorShape.SizeVerCursor,
               Qt.Edge.LeftEdge | Qt.Edge.TopEdge: Qt.CursorShape.SizeFDiagCursor,
               Qt.Edge.RightEdge | Qt.Edge.BottomEdge: Qt.CursorShape.SizeFDiagCursor,
               Qt.Edge.RightEdge | Qt.Edge.TopEdge: Qt.CursorShape.SizeBDiagCursor,
               Qt.Edge.LeftEdge | Qt.Edge.BottomEdge: Qt.CursorShape.SizeBDiagCursor}

    def mouseMoveEvent(self, event):
        e = self.edge_at(event.position())
        if e:
            self.setCursor(self.CURSORS.get(e, Qt.CursorShape.ArrowCursor))
        else:
            self.unsetCursor()

    def leaveEvent(self, event):
        # Курсор изменения размера не должен «прилипать»: дети наследуют курсор подложки, пока он выставлен
        self.unsetCursor()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        e = self.edge_at(event.position())
        if e and event.button() == Qt.MouseButton.LeftButton:
            handle = self.win.windowHandle()
            if handle is not None:
                handle.startSystemResize(e)


class ConfirmDialog(ClipDialog):
    """Вопрос в стиле окон ClipSD: значок-предупреждение, заголовок, текст, две кнопки справа.

    Левая кнопка: результат YES, правая: NO, Esc: отмена (CANCEL). Enter: кнопка по умолчанию (она главная, залитая)."""

    CANCEL, YES, NO = 0, 1, 2

    def __init__(self, parent, title: str, text: str, yes_text=None, no_text=None, default_yes=True):
        yes_text = tr("editor.yes") if yes_text is None else yes_text
        no_text = tr("editor.no") if no_text is None else no_text
        super().__init__(parent, title, "", "warning", 520)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        self.setModal(True)
        self.title.setText(title)
        self.text(text)
        self.yes = self._button(yes_text, "clipPrimary" if default_yes else "clipSecondary", "right")
        self.no = self._button(no_text, "clipSecondary" if default_yes else "clipPrimary", "right")
        self.yes.clicked.connect(lambda: self.done(self.YES))
        self.no.clicked.connect(lambda: self.done(self.NO))
        self.default = self.YES if default_yes else self.NO
        (self.yes if default_yes else self.no).setFocus()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.done(self.default)
        elif event.key() == Qt.Key.Key_Escape:
            self.done(self.CANCEL)
        else:
            super().keyPressEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if self.parentWidget() is not None:
            frame = self.frameGeometry()
            frame.moveCenter(self.parentWidget().frameGeometry().center())
            self.move(frame.topLeft())


def _separator() -> QFrame:
    line = QFrame()
    line.setObjectName("sep")
    line.setFixedSize(1, 26)
    return line


TOOL_MIME = "application/x-clipsd-tool"
GROUP_PREFIX = "group:"   # в перетаскивании: «group:<код>» тащит всю группу

# 1.32: группы инструментов, как в Office. Щелчок по значку группы включает её последний выбранный инструмент,
# стрелка ▾ справа открывает меню группы (значок, название, клавиша, зелёная галочка у инструмента по умолчанию).
# По ширине окна группы сворачиваются в одну кнопку от менее нужных к более нужным (COLLAPSE_ORDER);
# выделение, номер и обрезка всегда отдельными кнопками. Горячие клавиши работают всегда.
GROUPS = (   # (код, ключ названия, инструменты в стандартном порядке)
    ("arrows", "editor.group_arrows", (ARROW, DARROW, FARROW, FLINE, LINE)),
    ("shapes", "editor.group_shapes", (RECT, ELLIPSE, FSHAPE)),
    ("labels", "editor.group_labels", (CALLOUT, TEXT)),
    ("draw", "editor.group_draw", (MARKER, PENCIL)),
    ("hide", "editor.group_hide", (BLUR, ERASER)),
    ("ocr", "editor.group_ocr", (OCR, TRANSLATE)),
)
GROUP_TOOLS = {code: tools for code, _key, tools in GROUPS}
GROUP_TITLE = {code: key for code, key, _tools in GROUPS}
TOOL_GROUP = {tool: code for code, _key, tools in GROUPS for tool in tools}
GROUP_MAIN = {"arrows": ARROW, "shapes": RECT, "labels": TEXT, "draw": MARKER, "hide": BLUR, "ocr": OCR}   # на значке, пока ничего не выбирали
COLLAPSE_ORDER = ("draw", "ocr", "hide", "shapes", "arrows", "labels")   # первыми сворачиваются менее нужные
COLLAPSE_SLACK = 15   # px: свернувшаяся группа разворачивается на 15 px позже, кнопки не прыгают у порога
TOOL_W, GROUP_W, GROUP_ARROW_W = 36, 48, 13   # ширина кнопки инструмента, кнопки группы и её зоны ▾


def normalize_order(order) -> list:
    """Порядок инструментов в модели групп (1.32): неизвестные отбрасываются, повторы убираются; новый
    инструмент встаёт в свою группу (или в конец); каждая группа идёт подряд на месте своего первого инструмента.
    Так сохранённый в 1.31 порядок переносится аккуратно: порядок групп берётся по первому инструменту каждой группы,
    порядок внутри группы сохраняется."""
    standard = [t for t, _g, _tip, _k in TOOLS]
    seen = [t for t in dict.fromkeys(order or []) if t in standard]
    for t in standard:
        if t in seen:
            continue
        g = TOOL_GROUP.get(t)
        mates = [i for i, x in enumerate(seen) if g is not None and TOOL_GROUP.get(x) == g]
        if mates:
            seen.insert(mates[-1] + 1, t)
        else:
            seen.append(t)
    out, placed = [], set()
    for t in seen:
        g = TOOL_GROUP.get(t)
        if g is None:
            out.append(t)
        elif g not in placed:
            placed.add(g)
            out.extend(x for x in seen if TOOL_GROUP.get(x) == g)
    return out


def order_entries(order) -> list:
    """Плоский порядок -> элементы ряда: [("tool", MOVE, [MOVE]), ("group", "arrows", [ARROW, ...]), ...]."""
    entries = []
    for t in normalize_order(order):
        g = TOOL_GROUP.get(t)
        if g is None:
            entries.append(("tool", t, [t]))
        elif entries and entries[-1][0] == "group" and entries[-1][1] == g:
            entries[-1][2].append(t)
        else:
            entries.append(("group", g, [t]))
    return entries


def move_in_order(order, tool, index, whole=False) -> list:
    """Перестановка перетаскиванием. index: куда в плоском порядке (перед каким по счёту) отпустили.
    Инструмент группы, отпущенный внутри своей группы, переставляется в ней; отпущенный вне её (или whole=True,
    тащили кнопку свёрнутой группы) переносит всю группу. Отдельная кнопка и группа встают только между
    элементами ряда: внутрь чужой группы не попадают (к её ближнему краю)."""
    order = normalize_order(order)
    g = TOOL_GROUP.get(tool)
    block = [t for t in order if TOOL_GROUP.get(t) == g] if g is not None else [tool]
    start = order.index(block[0])
    end = start + len(block)
    if g is not None and not whole and start <= index <= end:
        old = order.index(tool)
        order.pop(old)
        order.insert(index - (1 if index > old else 0), tool)
        return order
    rest = [t for t in order if t not in block]
    idx = sum(1 for t in order[:max(0, index)] if t not in block)
    if 0 < idx < len(rest):
        g2 = TOOL_GROUP.get(rest[idx])
        if g2 is not None and TOOL_GROUP.get(rest[idx - 1]) == g2:
            s = next(i for i, t in enumerate(rest) if TOOL_GROUP.get(t) == g2)
            e = s + sum(1 for t in rest if TOOL_GROUP.get(t) == g2)
            idx = s if idx - s <= e - idx else e
    return rest[:idx] + block + rest[idx:]


def drop_plan(order, tool, index, whole=False) -> tuple:
    """(новый порядок, что переносится): весь блок группы или один инструмент (для красной черты «сюда встанет»)."""
    order = normalize_order(order)
    g = TOOL_GROUP.get(tool)
    block = [t for t in order if TOOL_GROUP.get(t) == g] if g is not None else [tool]
    start = order.index(block[0])
    inside = g is not None and not whole and start <= index <= start + len(block)
    return move_in_order(order, tool, index, whole), ([tool] if inside else block)


SELECTED_BAR_COLOR = [ACCENT]   # цвет полоски выбранного инструмента (акцент оформления; ставит окно редактора)


def _paint_selected_bar(button, center=None):
    """1.32: выбранный инструмент: мягкая подложка (таблица стилей) и короткая полоска акцента снизу."""
    p = QPainter(button)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    c = button.width() / 2 if center is None else center
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(SELECTED_BAR_COLOR[0]))
    p.drawRoundedRect(QRectF(c - 7, button.height() - 5, 14, 3), 1.5, 1.5)
    p.end()


def _paint_default_mark(button, right=2):
    """Зелёная галочка (инструмент по умолчанию) в правом нижнем углу значка."""
    p = QPainter(button)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    d = 13
    r = QRectF(button.width() - d - right, button.height() - d - 2, d, d)
    from .themes import GREEN   # 1.32: галочка того же зелёного, что главная кнопка
    p.setPen(QPen(QColor("#ffffff"), 1.5))
    p.setBrush(QColor(GREEN))
    p.drawEllipse(r)
    p.setPen(QPen(QColor("#ffffff"), 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.drawPolyline(QPolygonF([QPointF(r.left() + d * 0.27, r.top() + d * 0.53), QPointF(r.left() + d * 0.43, r.top() + d * 0.69),
                              QPointF(r.left() + d * 0.75, r.top() + d * 0.32)]))
    p.end()


class DraggableToolButton(QToolButton):
    """Кнопка инструмента: клик выбирает, перетаскивание переставляет её в строке."""

    def __init__(self, tool):
        super().__init__()
        self.tool = tool
        self._press = None
        self.default_mark = False   # зелёная галочка: это инструмент по умолчанию

    def drag_payload(self) -> str:
        return self.tool

    def set_default_mark(self, on: bool):
        if on != self.default_mark:
            self.default_mark = on
            self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.isChecked():
            _paint_selected_bar(self, center=self.width() / 2 - (4 if self.default_mark else 0))
        if self.default_mark:
            _paint_default_mark(self)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press is not None and (event.position().toPoint() - self._press).manhattanLength() \
                >= QApplication.startDragDistance():
            self._press = None
            self.setDown(False)
            drag = QDrag(self)
            mime = QMimeData()
            mime.setData(TOOL_MIME, self.drag_payload().encode())
            drag.setMimeData(mime)
            drag.setPixmap(self.grab())
            drag.setHotSpot(QPoint(self.width() // 2, self.height() // 2))
            drag.exec(Qt.DropAction.MoveAction)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._press = None
        super().mouseReleaseEvent(event)


class GroupButton(DraggableToolButton):
    """Кнопка свёрнутой группы (1.32): значок последнего выбранного инструмента группы и стрелка ▾ справа.
    Щелчок по значку включает этот инструмент, по стрелке открывает меню группы (menu_requested);
    перетаскивание переносит группу целиком."""

    menu_requested = pyqtSignal(str)

    def __init__(self, code):
        super().__init__(code)
        self.code = code
        self.current = GROUP_MAIN[code]
        self.menu_open = False
        self._arrow_hover = False
        self.setMouseTracking(True)

    def drag_payload(self) -> str:
        return GROUP_PREFIX + self.code

    def in_arrow(self, pos) -> bool:
        return pos.x() >= self.width() - GROUP_ARROW_W - 2

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.in_arrow(event.position()):
            event.accept()
            self.menu_requested.emit(self.code)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        hover = self.in_arrow(event.position())
        if hover != self._arrow_hover:
            self._arrow_hover = hover
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._arrow_hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        QToolButton.paintEvent(self, event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        zone = QRectF(self.width() - GROUP_ARROW_W - 2, 3, GROUP_ARROW_W, self.height() - 6)
        if self.menu_open or self._arrow_hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(128, 128, 128, 60 if self._arrow_hover and not self.menu_open else 90))
            p.drawRoundedRect(zone, 4, 4)
        c = zone.center()
        color = QColor(icons.ICON_COLOR)
        color.setAlpha(200)
        p.setPen(QPen(color, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolyline(QPolygonF([QPointF(c.x() - 3.5, c.y() - 1.6), QPointF(c.x(), c.y() + 1.9),
                                  QPointF(c.x() + 3.5, c.y() - 1.6)]))
        p.end()
        if self.isChecked():
            _paint_selected_bar(self, center=(self.width() - GROUP_ARROW_W - 2) / 2 + 1)
        if self.default_mark:
            _paint_default_mark(self, right=GROUP_ARROW_W + 1)


class ToolStrip(QWidget):
    """Ряд инструментов (1.32): отдельные кнопки и группы. Свёрнутая группа показывает одну кнопку GroupButton,
    развёрнутая: кнопки всех своих инструментов. Порядок меняется перетаскиванием (группы целиком, инструмент
    внутри своей группы); order_changed(плоский список инструментов) пишется в tool_order."""

    order_changed = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(2)
        self.drop_x = None
        self.tool_buttons = {}
        self.group_buttons = {}
        self._order = []
        self.collapsed = set()
        self.available = lambda tool: True   # распознавание или перевод выключены в настройках: их кнопок нет
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def setup(self, order, tool_buttons, group_buttons, available=None):
        self.tool_buttons, self.group_buttons = tool_buttons, group_buttons
        if available is not None:
            self.available = available
        self._order = normalize_order(order)
        self._relayout()

    # --- порядок -----------------------------------------------------------------------------
    def order(self):
        return list(self._order)

    def buttons(self):
        """Видимые кнопки ряда по порядку: инструменты и кнопки свёрнутых групп."""
        out = []
        for t in self._order:
            w = self.visible_widget(t)
            if w.isVisibleTo(self) and w not in out:
                out.append(w)
        return out

    def set_order(self, order):
        self._order = normalize_order(order)
        self._relayout()
        self.order_changed.emit(self.order())

    def move_tool(self, tool, index, whole=False):
        new = move_in_order(self._order, tool, index, whole)
        if new == self._order:
            return
        self._order = new
        self._relayout()
        self.order_changed.emit(self.order())

    # --- что видно ---------------------------------------------------------------------------
    def members(self, code) -> list:
        """Инструменты группы в порядке ряда, которые сейчас доступны."""
        return [t for t in self._order if TOOL_GROUP.get(t) == code and self.available(t)]

    def folded(self, code, collapsed=None) -> bool:
        """Группа показана одной кнопкой: свёрнута и в ней больше одного доступного инструмента."""
        collapsed = self.collapsed if collapsed is None else collapsed
        return code in collapsed and len(self.members(code)) > 1

    def set_collapsed(self, codes):
        codes = set(codes)
        if codes != self.collapsed:
            self.collapsed = codes
            self._sync_visibility()

    def _relayout(self):
        while self.row.count():
            self.row.takeAt(0)
        for kind, key, tools in order_entries(self._order):
            if kind == "group" and key in self.group_buttons:
                self.row.addWidget(self.group_buttons[key])
            for t in tools:
                self.row.addWidget(self.tool_buttons[t])
        self._sync_visibility()

    def _sync_visibility(self):
        for code, gb in self.group_buttons.items():
            folded = self.folded(code)
            gb.setVisible(folded)
            for t in GROUP_TOOLS[code]:
                if t in self.tool_buttons:
                    self.tool_buttons[t].setVisible(not folded and self.available(t))
        for t, b in self.tool_buttons.items():
            if t not in TOOL_GROUP:
                b.setVisible(self.available(t))
        self.updateGeometry()

    def width_for(self, collapsed) -> int:
        """Ширина ряда при этих свёрнутых группах (по настоящим размерам кнопок)."""
        widths = []
        for kind, key, tools in order_entries(self._order):
            if kind == "tool":
                widths += [TOOL_W] if self.available(key) else []
            elif self.folded(key, collapsed):
                widths.append(GROUP_W)
            else:
                widths += [TOOL_W] * len(self.members(key))
        return sum(widths) + self.row.spacing() * max(0, len(widths) - 1)

    def visible_widget(self, tool):
        g = TOOL_GROUP.get(tool)
        if g is not None and self.folded(g):
            return self.group_buttons[g]
        return self.tool_buttons[tool]

    # --- перетаскивание ----------------------------------------------------------------------
    def index_at(self, x: int) -> int:
        """Куда (перед каким по счёту инструментом плоского порядка) встанет кнопка, если отпустить её в точке x."""
        for i, tool in enumerate(self._order):
            w = self.visible_widget(tool)
            if w.isVisible() and x < w.geometry().center().x():
                return i
        return len(self._order)

    def _payload(self, event):
        text = bytes(event.mimeData().data(TOOL_MIME)).decode()
        if text.startswith(GROUP_PREFIX):
            code = text[len(GROUP_PREFIX):]
            tools = [t for t in self._order if TOOL_GROUP.get(t) == code]
            return (tools[0], True) if tools else (None, False)
        return (text, False) if text in self._order else (None, False)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(TOOL_MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if not event.mimeData().hasFormat(TOOL_MIME):
            return
        tool, whole = self._payload(event)
        if tool is None:
            return
        new, block = drop_plan(self._order, tool, self.index_at(int(event.position().x())), whole)
        after = new.index(block[-1]) + 1
        nxt = next((t for t in new[after:] if t not in block), None)
        shown = [self.visible_widget(t) for t in self._order if self.visible_widget(t).isVisible()]
        if nxt is not None and self.visible_widget(nxt).isVisible():
            self.drop_x = self.visible_widget(nxt).geometry().left() - 2   # красная черта: сюда встанет
        elif shown:
            self.drop_x = shown[-1].geometry().right() + 2
        self.update()
        event.acceptProposedAction()

    def dragLeaveEvent(self, _event):
        self.drop_x = None
        self.update()

    def dropEvent(self, event):
        tool, whole = self._payload(event)
        self.drop_x = None
        self.update()
        if tool is not None:
            self.move_tool(tool, self.index_at(int(event.position().x())), whole)
            event.acceptProposedAction()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.drop_x is not None:
            p = QPainter(self)
            p.fillRect(QRect(self.drop_x - 1, 2, 3, self.height() - 4), QColor(ACCENT))
            p.end()


def tool_order(cfg) -> list:
    """Порядок инструментов из настроек в модели групп (1.32, см. normalize_order): неизвестные отбрасываются,
    новые встают в свою группу или в конец."""
    return normalize_order(cfg.get("tool_order") or [])


MODE_TOOLS = {OCR, TRANSLATE, CROP}   # режимы со своей строкой сверху (1.29.1): по умолчанию не включаются и не запоминаются
NO_DEFAULT_TOOLS = MODE_TOOLS
TOOL_ACCUSATIVE = {
    MOVE: "editor.acc_move",
    CALLOUT: "editor.acc_callout",
    TEXT: "editor.acc_text",
    NUMBER: "editor.acc_number",
    ARROW: "editor.acc_arrow",
    DARROW: "editor.acc_darrow",
    FARROW: "editor.acc_farrow",
    FLINE: "editor.acc_fline",
    LINE: "editor.acc_line",
    RECT: "editor.acc_rect",
    ELLIPSE: "editor.acc_ellipse",
    FSHAPE: "editor.acc_fshape",
    MARKER: "editor.acc_marker",
    PENCIL: "editor.acc_pencil",
    BLUR: "editor.acc_blur",
    ERASER: "editor.acc_eraser",
    CROP: "editor.acc_crop",
}   # ключи каталога (винительный падеж для «Сделать … инструментом по умолчанию»), tr() при показе


def tool_title(tool) -> str:
    """Название инструмента для меню: первая строка подсказки без клавиши («Стрелка»)."""
    for t, _g, tip, _k in TOOLS:
        if t == tool:
            return tr(tip).split("\n")[0].rsplit(" (", 1)[0]
    return str(tool)


def default_tool(cfg) -> str:
    """Инструмент по умолчанию из настроек (default_tool); пусто или неизвестный: нет, открываем с последним."""
    tool = cfg.get("default_tool") or ""
    return tool if tool in {t for t, _g, _tip, _k in TOOLS} and tool not in NO_DEFAULT_TOOLS else ""


SHAPE_NAMES = {
    ARROW: "editor.shape_arrow",
    DARROW: "editor.shape_darrow",
    FARROW: "editor.shape_farrow",
    FLINE: "editor.shape_fline",
    LINE: "editor.shape_line",
    RECT: "editor.shape_rect",
    ELLIPSE: "editor.shape_ellipse",
    FSHAPE: "editor.shape_fshape",
    MARKER: "editor.shape_marker",
    PENCIL: "editor.shape_pencil",
    TEXT: "editor.shape_text",
    CALLOUT: "editor.shape_callout",
    NUMBER: "editor.shape_number",
    BLUR: "editor.shape_blur",
    IMAGE: "editor.shape_image",
}   # ключи каталога; название показывают через tr(SHAPE_NAMES[...])


def _capital(text: str) -> str:
    """Первая буква заглавная, остальное как есть (str.capitalize() портит немецкие существительные и аббревиатуры)."""
    return text[:1].upper() + text[1:]


def _color_icon(color) -> QIcon:
    pix = QPixmap(16, 16)
    pix.fill(QColor(color))
    p = QPainter(pix)
    p.setPen(QColor(90, 90, 90))
    p.drawRect(0, 0, 15, 15)
    p.end()
    return QIcon(pix)


def ask_save_path(parent, cfg):
    """Куда сохранить снимок по кнопке «Сохранить»: окно выбора места (начинает с папки save_dir,
    по умолчанию «Загрузки»). Без вопроса (save_ask выключен): сразу в save_dir. None: отмена."""
    folder = os.path.expanduser(cfg.get("save_dir") or "~")
    os.makedirs(folder, exist_ok=True)
    ext = "jpg" if cfg.get("save_format", "png") == "jpg" else "png"
    name = datetime.datetime.now().strftime(f"Screenshot_%Y-%m-%d_%H-%M-%S.{ext}")
    if cfg.get("save_ask", True):
        filters = ["PNG (*.png)", "JPEG (*.jpg *.jpeg)"]
        if ext == "jpg":
            filters.reverse()
        path, _ = QFileDialog.getSaveFileName(parent, tr("editor.save_dialog"), os.path.join(folder, name),
                                              ";;".join(filters))
        if not path:
            return None
    else:
        path = os.path.join(folder, name)
    if not os.path.splitext(path)[1]:
        path += "." + ext
    return path


MENU_GAP = 8   # px: меню объекта не ближе к рамке с ручками


def place_menu(frame: QRect, size: QSize, cursor: QPoint, area: QRect, handles=(), gap=MENU_GAP) -> QPoint:
    """Левый верхний угол меню, которое не закрывает рамку объекта с ручками (frame) и целиком на экране area:
    справа от рамки, иначе слева, ниже, выше (по высоте или ширине ближе к курсору). Объект почти во весь экран:
    у курсора, но так, чтобы меню не закрыло ближайшую ручку."""
    w, h = size.width(), size.height()

    def clamp(v, lo, hi):
        return max(lo, min(v, hi))

    def fits(x, y):
        r = QRect(x, y, w, h)
        return area.contains(r) and not r.intersects(frame.adjusted(-gap + 1, -gap + 1, gap - 1, gap - 1))

    y_side = clamp(cursor.y() - 10, area.top(), area.bottom() - h + 1)
    x_side = clamp(cursor.x() - 10, area.left(), area.right() - w + 1)
    for x, y in ((frame.right() + gap, y_side), (frame.left() - gap - w, y_side),
                 (x_side, frame.bottom() + gap), (x_side, frame.top() - gap - h)):
        if fits(x, y):
            return QPoint(x, y)
    # объект почти во весь экран: у курсора, со сдвигом от ближайшей ручки
    near = min(handles, key=lambda p: (p - cursor).manhattanLength()) if handles else cursor
    keep = QRect(near.x() - HANDLE - gap, near.y() - HANDLE - gap, 2 * (HANDLE + gap), 2 * (HANDLE + gap))
    off = 14
    for dx, dy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
        x = cursor.x() + off if dx > 0 else cursor.x() - off - w
        y = cursor.y() + off if dy > 0 else cursor.y() - off - h
        x, y = clamp(x, area.left(), area.right() - w + 1), clamp(y, area.top(), area.bottom() - h + 1)
        if not QRect(x, y, w, h).intersects(keep):
            return QPoint(x, y)
    return QPoint(clamp(cursor.x() + off, area.left(), area.right() - w + 1),
                  clamp(cursor.y() + off, area.top(), area.bottom() - h + 1))


def split_columns(sections, n=3) -> list:
    """Разделы подряд в n столбцов так, чтобы самый высокий столбец был как можно ниже (строка заголовка + строки)."""
    import itertools
    heights = [len(tools) + 1 for _t, tools in sections]
    k = min(n, len(sections))
    if k <= 1:
        return [list(sections)] if sections else []
    best = None
    for cuts in itertools.combinations(range(1, len(sections)), k - 1):
        bounds = (0,) + cuts + (len(sections),)
        tallest = max(sum(heights[a:b]) for a, b in zip(bounds, bounds[1:]))
        if best is None or tallest < best[0]:
            best = (tallest, bounds)
    bounds = best[1]
    return [list(sections[a:b]) for a, b in zip(bounds, bounds[1:])]


class ToolRow(QAbstractButton):
    """Строка панели «Все инструменты» (1.32): значок, название, клавиша справа; текущий на мягкой подложке.
    Правая кнопка: context(инструмент, где показать меню «инструмент по умолчанию»)."""

    context = pyqtSignal(str, QPoint)

    def __init__(self, tool, text, key, icon, current=False, tokens=None):
        super().__init__()
        self.tool, self.key, self.current = tool, key, current
        self.setText(text)
        self.setIcon(icon)
        self.setObjectName("toolRow")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"{text} ({key})" if key else text)
        t = tokens or {}
        dark = bool(t.get("dark"))
        accent = QColor(t.get("ui_accent", ACCENT))
        self.c_text = QColor(t["text"]) if dark and "text" in t else QColor("#16181c")
        self.c_dim = QColor(t["text_dim"]) if dark and "text_dim" in t else QColor("#6b7280")
        self.c_hover = QColor(accent.red(), accent.green(), accent.blue(), 70 if dark else 38)
        self.c_cur = QColor(accent.red(), accent.green(), accent.blue(), 95 if dark else 60)
        self.c_line = QColor("#4a4f57") if dark else QColor("#d9dee6")
        self.setMouseTracking(True)
        f = self.font()
        f.setPixelSize(14)
        self.setFont(f)

    def _key_font(self):
        f = QFont(self.font())
        f.setPixelSize(12)
        return f

    def sizeHint(self):
        fm = self.fontMetrics()
        key_w = QFontMetrics(self._key_font()).horizontalAdvance(self.key) + 12 if self.key else 0
        return QSize(10 + 22 + 10 + fm.horizontalAdvance(self.text()) + 18 + key_w + 8, 34)

    def minimumSizeHint(self):
        return self.sizeHint()

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def contextMenuEvent(self, event):
        self.context.emit(self.tool, event.globalPos())

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self.current or self.underMouse():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self.c_cur if self.current else self.c_hover)
            p.drawRoundedRect(r, 7, 7)
        self.icon().paint(p, QRect(10, (self.height() - 22) // 2, 22, 22))
        x = 10 + 22 + 10
        key_w = 0
        if self.key:
            kf = self._key_font()
            key_w = QFontMetrics(kf).horizontalAdvance(self.key) + 12
            chip = QRectF(self.width() - 8 - key_w, (self.height() - 20) / 2, key_w, 20)
            p.setPen(QPen(self.c_line, 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(chip, 4, 4)
            p.setFont(kf)
            p.setPen(self.c_dim)
            p.drawText(chip, int(Qt.AlignmentFlag.AlignCenter), self.key)
        f = QFont(self.font())
        f.setBold(self.current)
        p.setFont(f)
        p.setPen(self.c_text)
        p.drawText(QRectF(x, 0, self.width() - x - key_w - 14, self.height()),
                   int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), self.text())
        p.end()


class SwatchButton(QToolButton):
    """Цвет палитры (1.32): квадрат 20 px с тонкой обводкой (белый и чёрный различимы на любой панели), выбранный
    обведён кольцом цвета текста с промежутком. Без цвета (color None) рисуется «+» (другой цвет)."""

    def __init__(self, color=None):
        super().__init__()
        self.setObjectName("swatch")
        self.setCheckable(True)
        self.setFixedSize(28, 28)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.color = color
        self.ring = QColor("#1f2328")
        self.dark = False

    def set_color(self, color):
        self.color = color
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        sq = QRectF(4, 4, self.width() - 8, self.height() - 8)
        if self.isChecked():
            p.setPen(QPen(self.ring, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2), 7, 7)
        elif self.underMouse():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(128, 128, 128, 50))
            p.drawRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2), 7, 7)
        if self.color is None:
            line = QColor(self.ring)
            line.setAlpha(150)
            p.setPen(QPen(line, 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(sq.adjusted(0.5, 0.5, -0.5, -0.5), 5, 5)
            p.setPen(QPen(line, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            c = sq.center()
            p.drawLine(QPointF(c.x() - 4.5, c.y()), QPointF(c.x() + 4.5, c.y()))
            p.drawLine(QPointF(c.x(), c.y() - 4.5), QPointF(c.x(), c.y() + 4.5))
        else:
            p.setPen(QPen(QColor(255, 255, 255, 64) if self.dark else QColor(0, 0, 0, 52), 1))
            p.setBrush(QColor(self.color))
            p.drawRoundedRect(sq.adjusted(0.5, 0.5, -0.5, -0.5), 5, 5)
        p.end()

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)


class PenHint(QFrame):
    """Подсказка у палитры (1.32.1, решение владельца 20.11.2026). Цвет или толщина поменялись только у выделенного
    объекта, новые линии рисуются как раньше; кнопка «Рисовать дальше…» делает новое значение текущим. Не окно:
    карточка поверх снимка, рисовать не мешает, уходит сама через несколько секунд или при следующем действии;
    повторная смена обновляет ту же карточку. Цвета карточки из общей палитры окон (dialogs.PALETTES)."""
    SHOW_MS = 6000       # сколько держится без наведения мыши
    LINGER_MS = 2500     # после того как мышь ушла с карточки
    adopt = pyqtSignal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("penHint")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.target = None       # чей цвет поменяли: фигура или "text" (правка готового текста)
        self.pending = {}        # что можно сделать текущим: color, size, text_color
        self.kind = "color"
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 9, 10, 9)
        row.setSpacing(14)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        self.title = QLabel()
        self.title.setObjectName("penHintTitle")
        sub_row = QHBoxLayout()
        sub_row.setSpacing(6)
        self.sample = QLabel()   # прежний цвет: им рисуются новые линии
        self.sample.setFixedSize(12, 12)
        self.sub = QLabel()
        self.sub.setObjectName("penHintSub")
        sub_row.addWidget(self.sample, 0, Qt.AlignmentFlag.AlignVCenter)
        sub_row.addWidget(self.sub, 1)
        texts.addWidget(self.title)
        texts.addLayout(sub_row)
        row.addLayout(texts, 1)
        self.button = QPushButton()
        self.button.setObjectName("penHintButton")
        self.button.setFocusPolicy(Qt.FocusPolicy.NoFocus)   # как кнопки палитры: фокус остаётся у снимка и поля текста
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.clicked.connect(self.adopt)
        row.addWidget(self.button, 0, Qt.AlignmentFlag.AlignVCenter)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 60))
        self.setGraphicsEffect(shadow)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.dismiss)
        self.dark = False
        self.apply_theme(False)
        self.hide()

    def apply_theme(self, dark: bool):
        self.dark = bool(dark)
        c = CARD_PALETTES[self.dark]
        self.setStyleSheet(f"""
QFrame#penHint {{ background: {c['card']}; border: 1px solid {c['edge']}; border-radius: 8px; }}
QLabel#penHintTitle {{ color: {c['text']}; font-size: 13px; font-weight: bold; background: transparent; }}
QLabel#penHintSub {{ color: {c['muted']}; font-size: 12px; background: transparent; }}
QPushButton#penHintButton {{ color: {c['text']}; background: {c['card']}; border: 1px solid {c['line']};
    border-radius: 6px; padding: 5px 12px; font-size: 13px; min-height: 18px; }}
QPushButton#penHintButton:hover {{ background: {c['soft']}; }}
QPushButton#penHintButton:pressed {{ background: {c['edge']}; }}
""")

    TEXTS = {"color": ("editor.pen_hint_color_title", "editor.pen_hint_color_sub", "editor.pen_hint_color_button"),
             "size": ("editor.pen_hint_size_title", "editor.pen_hint_size_sub", "editor.pen_hint_size_button"),
             "both": ("editor.pen_hint_both_title", "editor.pen_hint_both_sub", "editor.pen_hint_both_button")}

    def show_kind(self, kind: str, pen_color):
        """kind: color, size или both; pen_color: прежний цвет (образец рядом с пояснением) или None."""
        self.kind = kind
        title, sub, button = (tr(k) for k in self.TEXTS[kind])
        self.title.setText(title)
        self.sub.setText(sub)
        self.button.setText(button)
        self.button.setAccessibleName(button)
        self.setAccessibleName(f"{title}. {sub}")
        if pen_color is not None:
            edge = "#6b7178" if self.dark else "#8a8f98"
            self.sample.setStyleSheet(f"background: {QColor(pen_color).name()}; border: 1px solid {edge}; border-radius: 3px;")
            self.sample.setToolTip(QColor(pen_color).name().upper())
        self.sample.setVisible(pen_color is not None)
        self.adjustSize()
        self.show()
        self.raise_()
        self.timer.start(self.SHOW_MS)

    def dismiss(self):
        self.timer.stop()
        self.hide()
        self.pending = {}
        self.target = None

    def mousePressEvent(self, event):
        """Щелчок по самой карточке мимо кнопки закрывает её, как щелчок по снимку (раньше пропадал впустую)."""
        self.dismiss()
        event.accept()

    def enterEvent(self, event):
        self.timer.stop()        # пока мышь на карточке, она не уходит
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self.isVisible():
            self.timer.start(self.LINGER_MS)
        super().leaveEvent(event)


class BellButton(QToolButton):
    """Колокольчик уведомлений (1.32): красная точка в углу, когда есть непрочитанное."""

    def __init__(self):
        super().__init__()
        self.setObjectName("bell")
        self.unread = 0
        self.ring = QColor("#f5f6f8")

    def set_unread(self, n: int):
        if n != self.unread:
            self.unread = n
            self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.unread:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(self.ring, 2))
        p.setBrush(QColor("#e5484d"))
        p.drawEllipse(QRectF(self.width() - 15.5, 4.5, 10, 10))
        p.end()


class NoticeRow(QAbstractButton):
    """Пункт колокольчика (1.32): кружок со значком, заголовок, пояснение; непрочитанный на мягкой подложке;
    у «Доступна версия» справа зелёная «Обновить»."""

    ICONS = {"update": "update", "whatsnew": "spark", "message": "info"}

    def __init__(self, item, unread, pal):
        super().__init__()
        self.item, self.unread, self.pal = item, unread, pal
        self.setText(item["title"])
        self.setToolTip(item["sub"])
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)
        self.action_button = None
        if item["kind"] == "update":
            b = QPushButton(tr("notifications.update_button"), self)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            from . import themes
            b.setStyleSheet(themes.green_button_qss(radius=6, extra="min-height: 28px; padding: 0 12px; font-weight: bold;"))
            b.ensurePolished()   # ширина по жирному шрифту и отступам из таблицы стилей
            bold = QFont(b.font())
            bold.setBold(True)
            b.setFixedSize(max(b.sizeHint().width(), QFontMetrics(bold).horizontalAdvance(b.text()) + 40), 30)
            self.action_button = b
        self._title_font = QFont(self.font())
        self._title_font.setPixelSize(14)
        self._title_font.setBold(True)
        self._sub_font = QFont(self.font())
        self._sub_font.setPixelSize(12)

    def _text_width(self):
        return 332 - 10 - 30 - 10 - 10 - ((self.action_button.width() + 10) if self.action_button else 0)

    def _title_height(self):
        """Заголовок переносится на вторую строку, а не обрезается (немецкий и французский длиннее)."""
        fm = QFontMetrics(self._title_font)
        return fm.boundingRect(QRect(0, 0, self._text_width(), 400), int(Qt.TextFlag.TextWordWrap), self.text()).height()

    def sizeHint(self):
        fm = QFontMetrics(self._sub_font)
        sub_h = fm.boundingRect(QRect(0, 0, self._text_width(), 400), int(Qt.TextFlag.TextWordWrap), self.item["sub"]).height()
        return QSize(332, max(50, 10 + self._title_height() + 2 + sub_h + 10))

    def resizeEvent(self, event):
        if self.action_button is not None:
            b = self.action_button
            b.move(self.width() - b.width() - 10, (self.height() - b.height()) // 2)
        super().resizeEvent(event)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event):
        P = self.pal
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self.unread or self.underMouse():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(P["accs"]) if self.unread else QColor(128, 128, 128, 30))
            if self.unread:
                acc = QColor(P["acc"])
                acc.setAlpha(60 if P["dark"] else 34)
                p.setBrush(acc)
            p.drawRoundedRect(r, 8, 8)
        circle = QRectF(10, 10, 30, 30)
        accent = self.item["kind"] == "update"
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(P["acc"]) if accent else QColor(P["s2"]))
        p.drawEllipse(circle)
        _draw_notice_icon(p, self.ICONS[self.item["kind"]], circle.center(), QColor("#ffffff") if accent else QColor(P["t2"]))
        x = 50
        w = self._text_width()
        p.setFont(self._title_font)
        p.setPen(QColor(P["t"]))
        th = self._title_height()
        p.drawText(QRectF(x, 9, w, th), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap),
                   self.text())
        p.setFont(self._sub_font)
        p.setPen(QColor(P["t2"]))
        p.drawText(QRectF(x, 9 + th + 2, w, self.height() - th - 12),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap), self.item["sub"])
        p.end()


def _draw_notice_icon(p, kind, c, color):
    """Значки пунктов колокольчика: стрелка загрузки (обновление), звёздочка (что нового), «i» (сообщение)."""
    pen = QPen(color, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    x, y = c.x(), c.y()
    if kind == "update":
        p.drawLine(QPointF(x, y - 6), QPointF(x, y + 3))
        p.drawPolyline(QPolygonF([QPointF(x - 4, y - 0.5), QPointF(x, y + 3.5), QPointF(x + 4, y - 0.5)]))
        p.drawLine(QPointF(x - 6, y + 6.5), QPointF(x + 6, y + 6.5))
    elif kind == "spark":
        path = QPainterPath(QPointF(x, y - 7))
        for px, py in ((x + 1.8, y - 1.8), (x + 7, y), (x + 1.8, y + 1.8), (x, y + 7), (x - 1.8, y + 1.8), (x - 7, y),
                       (x - 1.8, y - 1.8)):
            path.lineTo(px, py)
        path.closeSubpath()
        p.drawPath(path)
    else:
        p.drawEllipse(QPointF(x, y), 7, 7)
        p.drawLine(QPointF(x, y - 0.5), QPointF(x, y + 3.5))
        p.drawPoint(QPointF(x, y - 3.5))


class EditorWindow(QMainWindow):
    closed = pyqtSignal(object)

    def __init__(self, image: QImage, ctx, origin: QPoint = None):
        super().__init__()
        self.ctx = ctx
        self.origin = origin
        self.exported = False
        cfg = ctx.config

        self.setWindowTitle(tr("editor.window_title"))
        self.setWindowIcon(ctx.icon)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        # Своя рамка окна (скруглённые углы, тень, своя шапка) или, по настройке, системный заголовок
        self.system_title = bool(cfg.get("editor_system_title", False))
        if not self.system_title:
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        icons.ICON_COLOR = theme(cfg)["icon"]
        SELECTED_BAR_COLOR[0] = theme(cfg)["ui_accent"]
        self.setStyleSheet(make_style(cfg))
        self.frame_px = theme(cfg)["ui_frame"]

        start_tool = default_tool(cfg) or cfg["tool"]
        self.canvas = Canvas(image, MOVE if start_tool in MODE_TOOLS else start_tool, cfg["color"], cfg["size"])   # 1.29: инструмент по умолчанию
        self.canvas.eraser_mode = cfg.get("eraser_mode", "object")
        self.canvas.eraser_size = int(cfg.get("eraser_size", 2))
        if cfg.get("text_color"):
            self.canvas.text_color = QColor(cfg["text_color"])
        self.canvas.resized.connect(self._canvas_resized)
        self.canvas.selection_changed.connect(self._selection_changed)
        self.canvas.changed.connect(self._canvas_changed)
        self.canvas.context_requested.connect(self.show_context_menu)
        self.canvas.zoom_requested.connect(self.zoom_by)
        self.canvas.pressed.connect(self._dismiss_pen_hint)        # следующее действие на снимке убирает подсказку
        self.canvas.size_wheeled.connect(lambda size: self._object_restyled(size=size))
        self._pen_hint = None
        self.canvas.crop_state_changed.connect(self._update_info)
        self.canvas.crop_confirmed.connect(self.exit_crop_mode)   # обрезали любым способом: режим завершён
        self.canvas.text_selected.connect(self._text_selected)
        self.canvas.text_edit_started.connect(self._text_edit_started)
        self._ocr_job = None
        self._zoom_fit_mode = False

        # Снимок в синей рамке на тёмном поле.
        self.image_frame = QFrame()
        self.image_frame.setObjectName("imageFrame")
        frame_layout = QVBoxLayout(self.image_frame)
        frame_layout.setContentsMargins(FRAME_WIDTH, FRAME_WIDTH, FRAME_WIDTH, FRAME_WIDTH)
        frame_layout.addWidget(self.canvas)
        stage = QWidget()
        stage.setObjectName("stage")
        stage_layout = QVBoxLayout(stage)
        stage_layout.setContentsMargins(0, 0, 0, 0)
        stage_layout.addWidget(self.image_frame, 0, Qt.AlignmentFlag.AlignCenter)   # узкий снимок по центру, поле вокруг ровное
        self.scroll = QScrollArea()
        self.scroll.setWidget(stage)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)

        # Подложка со скруглённой карточкой и рамкой; в карточке своя шапка (если нет системной), панели и снимок
        self.shell = ChromeShell(self)
        content = QWidget()
        content.setObjectName("content")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.panel = self._build_panel()
        layout.addWidget(self.panel)
        layout.addWidget(self.scroll, 1)
        # Подсказка режима текста и перевода: отдельная строка над нижней панелью, место под неё не берётся у снимка,
        # пока режима нет; уведомления («Текст скопирован…») тоже ложатся сюда, а не на текст снимка
        self.mode_hint = QLabel()
        self.mode_hint.setObjectName("modeHint")
        self.mode_hint.setWordWrap(True)
        self.mode_hint.setVisible(False)
        layout.addWidget(self.mode_hint)
        self.tr_top = self._build_tr_top()
        layout.insertWidget(1, self.tr_top)
        layout.addWidget(self._build_bottom())
        self.tr_bottom = self._build_tr_bottom()
        layout.addWidget(self.tr_bottom)
        self.text_top, self.text_bottom = self._build_text_top(), self._build_text_bottom()
        layout.insertWidget(1, self.text_top)
        layout.addWidget(self.text_bottom)
        self.crop_top = self._build_crop_top()
        layout.insertWidget(1, self.crop_top)
        self.content = content
        self.titlebar = None
        self._drag_filter = None
        if not self.system_title:
            self.titlebar = TitleBar(self, ctx.icon)
            self.shell.layout_.addWidget(self.titlebar)
            title_line = QFrame()
            title_line.setObjectName("sep")
            title_line.setFixedHeight(1)
            self.title_line = title_line
            self.shell.layout_.addWidget(title_line)
            title_line.hide()   # 1.32 (вид А): шапка и первый ряд на одной подложке, без линии между ними
            self.titlebar.set_icons(self.top_icons)
            self._drag_filter = DragFilter(self)
            for w in self._chrome_widgets():
                w.installEventFilter(self._drag_filter)
            self._set_drag_cursors()
        self.shell.layout_.addWidget(content, 1)
        self.setCentralWidget(self.shell)

        self._build_shortcuts()
        self._sync_ocr()
        from . import notifications   # 1.32: колокольчик
        notifications.register(ctx)
        notifications.first_run_seen(cfg)
        notifications.listen(self._sync_bell)
        self._sync_bell()
        self.scroll.viewport().installEventFilter(self)   # Ctrl+колесо над полем вокруг снимка
        self._update_info()
        self.fit_size()
        self._sync_frame_extents()   # окно создано: свойство для менеджера ставится до первого показа

    def _chrome_widgets(self):
        """Шапка и панели, за которые окно переносится (включая строки режимов)."""
        return (self.titlebar, self.panel, self.bottom, self.info, self.mode_hint, self.tr_top, self.tr_bottom,
                self.text_top, self.text_bottom, self.crop_top)

    def _set_drag_containers(self):
        """Шапка и панели: «перемещение» только пока окно можно переносить (развёрнутое не переносится)."""
        if getattr(self, "titlebar", None) is None:
            return
        for w in self._chrome_widgets():
            if self.isMaximized() or self.isFullScreen():
                w.unsetCursor()
            else:
                w.setCursor(Qt.CursorShape.SizeAllCursor)

    def _set_drag_cursors(self):
        """Курсор «перемещение» (четыре стрелки) над шапкой и свободными местами панелей, за которые окно переносится;
        над кнопками и полями ввода обычная стрелка (или текстовый курсор). Остальное содержимое окна (снимок, поле
        вокруг него) не наследует курсор изменения размера от подложки."""
        from PyQt6.QtWidgets import QAbstractButton, QAbstractSlider, QComboBox
        self.content.setCursor(Qt.CursorShape.ArrowCursor)
        self._set_drag_containers()
        for w in self._chrome_widgets():
            for child in w.findChildren(QWidget):
                if child.testAttribute(Qt.WidgetAttribute.WA_SetCursor):
                    continue
                if isinstance(child, (QAbstractButton, QAbstractSlider, QComboBox, QAbstractSpinBox)):
                    child.setCursor(Qt.CursorShape.ArrowCursor)
                elif isinstance(child, (QLineEdit, QTextEdit)):
                    child.setCursor(Qt.CursorShape.IBeamCursor)

    # --- верхняя панель: инструменты, цвета, толщины -------------------------

    def _tool_button(self, icon, tip, name="tool", checkable=True) -> QToolButton:
        return self._style_tool_button(QToolButton(), icon, tip, name, checkable)

    def _style_tool_button(self, button, icon, tip, name="tool", checkable=True) -> QToolButton:
        button.setObjectName(name)
        button.setIcon(icon)
        button.setIconSize(QSize(24, 24))
        button.setToolTip(tip)
        button.setCheckable(checkable)
        button.setFixedSize(36, 36)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return button

    def _build_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("panel")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        rows = QVBoxLayout(panel)
        rows.setContentsMargins(8, 6, 8, 6)
        rows.setSpacing(4)

        # Ряд 1: инструменты (порядок меняется перетаскиванием) | отменить, повторить, настройки
        row1 = QHBoxLayout()
        row1.setSpacing(2)
        # Быстрый доступ (1.31.1): «Отменить», «Повторить» в начале ряда на своей подложке, как в Excel
        quick = QFrame()
        quick.setObjectName("quickGroup")
        quick_row = QHBoxLayout(quick)
        quick_row.setContentsMargins(3, 2, 3, 2)
        quick_row.setSpacing(2)
        undo = self._tool_button(icons.icon("undo"), tr("editor.undo_tip"), "action", False)
        self.undo_button = undo
        undo.clicked.connect(self.canvas.undo)
        redo = self._tool_button(icons.icon("redo"), tr("editor.redo_tip"), "action", False)
        self.redo_button = redo
        redo.clicked.connect(self.canvas.redo)
        quick_row.addWidget(undo)
        quick_row.addWidget(redo)
        self.quick_group = quick
        row1.addWidget(quick)
        row1.addSpacing(6)
        row1.addWidget(_separator())
        row1.addSpacing(6)
        self.tool_group = QButtonGroup(self)
        self.tool_buttons = {}
        self.group_buttons = {}
        self.tool_strip = ToolStrip()
        for tool, _glyph, _tip, _key in TOOLS:
            button = DraggableToolButton(tool)
            self._style_tool_button(button, icons.icon(tool), self._tool_tip(tool))
            button.setChecked(tool == self.canvas.tool)
            button.clicked.connect(lambda _c, t=tool: self.select_tool(t))
            self.tool_group.addButton(button)
            self.tool_buttons[tool] = button
        # 1.32: группы (как в Office): значок = последний выбранный инструмент группы, ▾ = меню группы
        self.group_current = self._initial_group_tools()
        for code, _key, _tools in GROUPS:
            gb = GroupButton(code)
            self._style_tool_button(gb, icons.icon(self.group_current[code]), "", "group")
            gb.setFixedSize(GROUP_W, 36)
            gb.clicked.connect(lambda _c, c=code: self.select_tool(self.group_current[c]))
            gb.menu_requested.connect(self.show_group_menu)
            self.group_buttons[code] = gb
        self.tool_strip.setup(tool_order(self.ctx.config), self.tool_buttons, self.group_buttons, self._tool_available)
        self.tool_strip.order_changed.connect(self._save_tool_order)
        self.tool_strip.customContextMenuRequested.connect(self._tool_strip_menu)
        self._sync_default_tool()
        row1.addWidget(self.tool_strip)
        row1.addSpacing(6)
        row1.addWidget(_separator())
        row1.addSpacing(6)
        insert = self._tool_button(icons.icon("insert"), tr("editor.insert_tip"), "action", False)
        insert.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(insert)
        style_menu(menu, self.ctx.config)
        menu.addAction(tr("editor.insert_clipboard")).triggered.connect(self.paste_image)
        menu.addAction(tr("editor.insert_file")).triggered.connect(self.insert_from_file)
        menu.addAction(tr("editor.insert_capture")).triggered.connect(self.insert_screenshot)
        insert.setMenu(menu)
        self.insert_button = insert
        row1.addWidget(insert)
        # «⋯ Все инструменты» (1.32): видна всегда; панель со всеми инструментами по группам и их клавишами.
        # В узком окне только значок «⋯»
        more = QToolButton()
        more.setObjectName("more")
        more.setIcon(icons.icon("more"))
        more.setIconSize(QSize(20, 20))
        more.setFixedHeight(36)
        more.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        more.clicked.connect(self.show_all_tools)
        self.more_button = more
        self._set_more_label(True)
        row1.addSpacing(4)
        row1.addWidget(more)
        self.panel_row1 = row1
        row1.addStretch(1)
        # 1.32: колокольчик, «?», шестерёнка, глобус одной группой справа сверху: в своей шапке окна (перед кнопками
        # окна) или, при системном заголовке, справа в первом ряду. Нативную шапку окна ClipSD не трогает.
        top = QWidget()
        top.setObjectName("topIcons")
        top_row = QHBoxLayout(top)
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(2)
        bell = BellButton()
        self._style_tool_button(bell, icons.icon("bell"), tr("editor.bell_tip"), "bell", False)
        bell.clicked.connect(self.show_notifications)
        self.bell_button = bell
        top_row.addWidget(bell)
        help_button = self._tool_button(icons.icon("help"), tr("editor.help_tip"),
                                        "action", False)
        help_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        help_menu = QMenu(help_button)   # 1.31.1: «?» открывает меню: обучение, обновления, о программе
        style_menu(help_menu, self.ctx.config)
        help_menu.addAction(tr("app.menu_tour")).triggered.connect(self.start_tour)
        help_menu.addAction(tr("updater.menu.check")).triggered.connect(self._check_updates)
        help_menu.addAction(tr("feedback.rate_title")).triggered.connect(self._rate)   # 1.32: «Оценить ClipSD»
        help_menu.addAction(tr("app.menu_about")).triggered.connect(self._show_about)
        from . import links   # 1.32: «Новости в Telegram» (канал программы, открывается через sysenv.open_url)
        telegram = help_menu.addAction(tr("links.telegram_menu"))
        telegram.setToolTip(tr("links.telegram_tip"))
        telegram.triggered.connect(links.open_telegram)
        self.telegram_action = telegram
        help_button.setMenu(help_menu)
        self.help_menu = help_menu
        self.help_button = help_button
        top_row.addWidget(help_button)
        settings = self._tool_button(icons.icon("settings"), tr("editor.settings_tip"), "action", False)
        self.settings_button = settings
        settings.clicked.connect(self.open_settings)
        top_row.addWidget(settings)
        from . import language   # 1.31: глобус рядом с «?» и шестерёнкой, подменю языков на самих себе
        globe = self._tool_button(icons.icon("globe"), language.menu_title(), "action", False)
        globe.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        globe.setMenu(language.make_menu(self.ctx, globe))
        self.language_button = globe
        top_row.addWidget(globe)
        self.top_icons = top
        if self.system_title:
            row1.addWidget(top)        # системный заголовок: справа в первом ряду
        rows.addLayout(row1)

        # Ряд 2: цвета | толщина
        row2 = QHBoxLayout()
        row2.setSpacing(4)
        self.color_group = QButtonGroup(self)
        self.color_buttons = {}
        current = self.canvas.color.name().lower()
        pal = palette(self.ctx.config)
        for color in PALETTE:
            swatch = SwatchButton(color)
            swatch.ring, swatch.dark = QColor(pal["t"]), pal["dark"]
            swatch.setToolTip(color.upper())
            swatch.setChecked(color == current)
            swatch.clicked.connect(lambda _c, col=color: self.select_color(col))
            self.color_group.addButton(swatch)
            self.color_buttons[color] = swatch
            row2.addWidget(swatch)
        # 1.32.1: свои цвета из «+» стоят образцами перед «+» (до трёх), щелчок сразу выбирает цвет
        self.own_buttons = {}
        self._own_row = row2
        self.custom_color = SwatchButton(None)
        self.custom_color.ring, self.custom_color.dark = QColor(pal["t"]), pal["dark"]
        self.custom_color.setText("+")
        self.custom_color.setToolTip(tr("editor.other_color"))
        self.custom_color.setAccessibleName(tr("editor.other_color"))
        self.custom_color.clicked.connect(self.pick_custom_color)
        self.color_group.addButton(self.custom_color)
        row2.addWidget(self.custom_color)
        own = self._own_colors()
        if not self.ctx.config.get("custom_colors_seen"):
            # один раз: свой цвет 1.32.0 (был текущим) встаёт в палитру. Убранный потом образец насовсем не возвращается,
            # даже если им ещё рисуют (цвет пера при этом остаётся прежним)
            if current not in self.color_buttons and current not in own:
                own = (own + [current])[-OWN_COLORS_MAX:]
                self.ctx.config["custom_colors"] = own
            self.ctx.config["custom_colors_seen"] = True
            self.ctx.save_config()
        for name in own:
            self._add_own_button(name)
        self._check_swatch(current)
        row2.addSpacing(6)
        row2.addWidget(_separator())
        row2.addSpacing(6)
        row2.addWidget(self._build_text_color_button())
        row2.addSpacing(6)
        row2.addWidget(_separator())
        row2.addSpacing(6)
        self.size_group = QButtonGroup(self)
        seg = QFrame()   # 1.32: толщины одной полосой, выбранная приподнята
        seg.setObjectName("sizeSeg")
        seg_row = QHBoxLayout(seg)
        seg_row.setContentsMargins(2, 2, 2, 2)
        seg_row.setSpacing(1)
        for level in range(1, 6):
            button = self._tool_button(icons.size_icon(level), tr("editor.size_tip", level=level),
                                       "size")
            button.setFixedSize(32, 26)
            button.setChecked(level == self.canvas.pen_size)
            button.clicked.connect(lambda _c, lv=level: self.select_size(lv))
            self.size_group.addButton(button, level)
            seg_row.addWidget(button)
        self.size_seg = seg
        row2.addWidget(seg)
        # Режим ластика: видно, только когда выбран ластик.
        self.eraser_box = QWidget()
        box = QHBoxLayout(self.eraser_box)
        box.setContentsMargins(6, 0, 0, 0)
        box.setSpacing(2)
        box.addWidget(_separator())
        box.addSpacing(4)
        self.eraser_group = QButtonGroup(self)
        for mode, text, tip in (("object", tr("editor.eraser_object"), tr("editor.eraser_object_tip")),
                                ("part", tr("editor.eraser_part"), tr("editor.eraser_part_tip"))):
            button = QToolButton()
            button.setObjectName("size")
            button.setProperty("eraser_mode", mode)
            button.setText(text)
            button.setToolTip(tip)
            button.setCheckable(True)
            button.setFixedHeight(30)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setChecked(mode == self.canvas.eraser_mode)
            button.clicked.connect(lambda _c, m=mode: self.select_eraser_mode(m))
            self.eraser_group.addButton(button)
            box.addWidget(button)
        self.eraser_box.setVisible(self.canvas.tool == ERASER)
        row2.addWidget(self.eraser_box)
        row2.addStretch(1)
        self.panel_row2 = row2   # справа сюда встают «Копировать текст» и «Перевести» (см. _build_bottom)
        rows.addLayout(row2)
        return panel

    # --- режим перевода (1.29): сверху «Перевод» и «Готово (Esc)», внизу бирюзовая полоса ---------------

    # Единый образец строки режима (1.29.1): значок, название крупно, пояснение, справа крупная кнопка выхода,
    # всегда в одном месте и того же размера; цвет задаёт режим (свойство "mode" в таблице стилей).
    def _build_mode_top(self, mode: str, icon_name: str, color: str, title: str, sub: str, buttons) -> tuple:
        """buttons: [(ключ, подпись, подсказка, слот, главная)]; возвращает (строка, {ключ: кнопка})."""
        top = QWidget()
        top.setObjectName("trTop")
        top.setProperty("mode", mode)
        top.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        row = QHBoxLayout(top)
        row.setContentsMargins(12, 6, 8, 6)
        row.setSpacing(8)
        icon = QLabel()
        icon.setPixmap(icons.icon(icon_name, color).pixmap(QSize(24, 24)))
        title_label = QLabel(title)
        title_label.setObjectName("trTitle")
        sub_label = QLabel(sub)
        sub_label.setObjectName("trSub")
        sub_label.setProperty("mode", mode)
        sub_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)   # длинное пояснение обрезается, кнопки остаются
        sub_label.setMinimumWidth(10)
        row.addWidget(icon)
        row.addWidget(title_label)
        row.addWidget(sub_label, 1)
        made = {}
        for key, label, tip, slot, main in buttons:
            button = QPushButton(label)
            button.setObjectName("modeMain" if main else "modeDone")
            button.setProperty("mode", mode)
            button.setToolTip(tip)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(slot)
            row.addWidget(button)
            made[key] = button
        top.setVisible(False)
        return top, made

    def _build_tr_top(self) -> QWidget:
        """Верхняя строка режима перевода: вместо инструментов рисования, палитры и толщины."""
        top, made = self._build_mode_top("translate", "translate", "#0d9488", tr("editor.tr_title"),
                                         tr("editor.tr_sub"),
                                         [("done", self.TR_DONE_LABEL, tr("editor.tr_back_tip"), self.exit_translate_mode, False)])
        self.tr_done_button = made["done"]
        return top

    def _build_text_top(self) -> QWidget:
        top, made = self._build_mode_top("text", "ocr", "#7c3aed", tr("editor.mode_text_title"),
                                         tr("editor.mode_text_sub"),
                                         [("done", self.OCR_LABEL_OFF, tr("editor.tr_back_tip"), self.exit_text_mode, False)])
        self.text_done_button = made["done"]
        self.text_sub = top.findChild(QLabel, "trSub")
        return top

    def _build_crop_top(self) -> QWidget:
        top, made = self._build_mode_top("crop", "crop", "#1f9d55", tr("editor.crop_info"), tr("editor.hint_crop"),
                                         [("ok", self.CROP_OK_LABEL, tr("editor.crop_ok_tip"), self.crop_confirm_button, True),
                                          ("cancel", self.CROP_CANCEL_LABEL, tr("editor.crop_cancel_tip"),
                                           self.exit_crop_mode, False)])
        self.crop_ok_button, self.crop_cancel_button = made["ok"], made["cancel"]
        self.crop_ok_button.setEnabled(False)   # пока рамки нет, обрезать нечего
        return top

    def _build_text_bottom(self) -> QWidget:
        """Нижняя фиолетовая полоса режима текста: сообщение, «Подряд / Маркер», «Скопировать выделенное», «Скопировать весь текст»."""
        bar = QWidget()
        bar.setObjectName("textBottom")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        col = QVBoxLayout(bar)
        col.setContentsMargins(12, 8, 12, 10)
        col.setSpacing(6)
        self.text_message = QLabel()
        self.text_message.setObjectName("textMessage")
        self.text_message.setWordWrap(True)
        col.addWidget(self.text_message)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(self.text_mode_box)
        row.addStretch(1)
        sel = QPushButton(icons.icon("copy", "#d9c8ff" if theme(self.ctx.config).get("dark") else "#5b21b6"), "  " + tr("editor.copy_selected"))
        sel.setObjectName("textCopySel")
        sel.setToolTip(tr("editor.copy_selected_tip"))
        whole = QPushButton(icons.icon("copy", "#ffffff"), "  " + tr("editor.copy_all_text"))
        whole.setObjectName("textCopyAll")
        whole.setToolTip(tr("editor.copy_all_text_tip"))
        for b in (sel, whole):
            b.setIconSize(QSize(18, 18))
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        sel.clicked.connect(self.copy_selected_text)
        whole.clicked.connect(self.copy_all_text)
        row.addWidget(sel)
        row.addWidget(whole)
        self.text_copy_sel_button, self.text_copy_all_button = sel, whole
        col.addLayout(row)
        bar.setVisible(False)
        return bar

    def _build_tr_bottom(self) -> QWidget:
        """Нижняя бирюзовая полоса: сообщение, язык, «Перевод / Оригинал», «Поверх текста / Карточкой», «Скопировать перевод»."""
        bar = QWidget()
        bar.setObjectName("trBottom")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        col = QVBoxLayout(bar)
        col.setContentsMargins(12, 8, 12, 10)
        col.setSpacing(6)
        self.tr_message = QLabel()
        self.tr_message.setObjectName("trMessage")
        self.tr_message.setWordWrap(True)
        col.addWidget(self.tr_message)
        row = QHBoxLayout()
        row.setSpacing(10)
        lang = QPushButton()   # надпись «На: язык ▾» ставит _sync_tr_controls при входе в режим перевода (translate не грузим заранее)
        lang.setObjectName("trLang")
        lang.setToolTip(tr("editor.tr_lang_tip"))
        lang.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lang.setCursor(Qt.CursorShape.PointingHandCursor)
        lang.clicked.connect(self._tr_lang_menu)
        row.addWidget(lang)

        def segmented(first, second, on_first, tip1, tip2):
            box = QWidget()
            lay = QHBoxLayout(box)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(0)
            group = QButtonGroup(box)
            a, b = QPushButton(first), QPushButton(second)
            a.setObjectName("trSegL")
            b.setObjectName("trSegR")
            for btn, tip in ((a, tip1), (b, tip2)):
                btn.setCheckable(True)
                btn.setToolTip(tip)
                btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                group.addButton(btn)
                lay.addWidget(btn)
            a.setChecked(on_first)
            b.setChecked(not on_first)
            return box, a, b
        box1, self.tr_show_tr, self.tr_show_orig = segmented(tr("editor.tr_seg_translation"), tr("editor.tr_seg_original"), True, tr("editor.tr_seg_translation_tip"), tr("editor.tr_seg_original_tip"))
        box2, self.tr_view_overlay, self.tr_view_card = segmented(
            tr("editor.tr_view_overlay"), tr("editor.tr_view_card"), True, tr("editor.tr_view_overlay_tip"), tr("editor.tr_view_card_tip"))
        self.tr_show_tr.clicked.connect(lambda: self._tr_set_original(False))
        self.tr_show_orig.clicked.connect(lambda: self._tr_set_original(True))
        self.tr_view_overlay.clicked.connect(lambda: self._tr_set_view("overlay"))
        self.tr_view_card.clicked.connect(lambda: self._tr_set_view("card"))
        row.addWidget(box1)
        row.addWidget(box2)
        row.addStretch(1)
        copy = QPushButton(icons.icon("copy", "#ffffff"), "  " + tr("editor.tr_copy"))
        copy.setObjectName("trCopy")
        copy.setIconSize(QSize(18, 18))
        copy.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        copy.setCursor(Qt.CursorShape.PointingHandCursor)
        copy.clicked.connect(self._tr_copy_all)
        row.addWidget(copy)
        self.tr_lang_button, self.tr_copy_button = lang, copy
        col.addLayout(row)
        bar.setVisible(False)
        return bar

    def _tr_lang_menu(self):
        layer = getattr(self, "tr_layer", None)
        if layer is None:
            return
        btn = self.tr_lang_button
        pos = layer.mapFromGlobal(btn.mapToGlobal(QPoint(0, 0)))   # координаты слоя, а не окна
        layer._tr_lang_menu(QRectF(pos.x(), pos.y(), btn.width(), btn.height()), None)

    def _tr_set_original(self, on: bool):
        layer = getattr(self, "tr_layer", None)
        if layer is not None:
            layer.set_original(on)
        self._update_info()

    def _tr_set_view(self, new: str):
        layer = getattr(self, "tr_layer", None)
        if layer is not None:
            layer.set_view_all(new)
        self._update_info()

    def _tr_copy_all(self):
        layer = getattr(self, "tr_layer", None)
        text = layer.all_text() if layer is not None else ""
        if not text:
            self.show_toast(tr("editor.tr_nothing_to_copy"))
            return
        from . import ocr
        ocr.copy_text(text)
        self.show_toast(tr("editor.tr_copied"))

    def _set_mode_ui(self, tool):
        """Режимы редактора (перевод, копирование текста, обрезка): пока режим включён, инструменты рисования, палитра и
        толщина скрыты, на их месте строка режима с крупной кнопкой выхода. Перевод и текст убирают ещё масштаб и
        «Сохранить»/«Скопировать», их место занимает цветная полоса режима."""
        translate, text, crop = tool == TRANSLATE, tool == OCR, tool == CROP
        self.panel.setVisible(not (translate or text or crop))
        self.bottom.setVisible(not (translate or text))
        self.tr_top.setVisible(translate)
        self.tr_bottom.setVisible(translate)
        self.text_top.setVisible(text)
        self.text_bottom.setVisible(text)
        self.crop_top.setVisible(crop)
        for b in (self.save_button, self.copy_button, self.copy_close_button):
            b.setVisible(not crop)   # обрезка: «Скопировать и закрыть», «Скопировать», «Сохранить» не путать с «Обрезать»
        if translate or text:
            self.mode_hint.setVisible(False)

    # --- нижняя панель: размер снимка, Сохранить, Скопировать ----------------

    def _build_bottom(self) -> QWidget:
        bottom = QWidget()
        bottom.setObjectName("bottom")
        bottom.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        row = QHBoxLayout(bottom)
        row.setContentsMargins(10, 6, 6, 6)
        row.setSpacing(8)
        self.info = QLabel()
        self.info.setObjectName("info")
        self.info.setMinimumWidth(10)
        self.info.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)   # длинная подсказка обрезается
        row.addWidget(self.info, 1)   # подпись занимает всё свободное место слева от кнопок
        zoom_out = QPushButton("−")
        zoom_out.setToolTip(tr("editor.zoom_out_tip"))
        self.zoom_label = QPushButton("100%")
        self.zoom_label.setToolTip(tr("editor.zoom_reset_tip"))
        zoom_in = QPushButton("+")
        zoom_in.setToolTip(tr("editor.zoom_in_tip"))
        zoom_fit = QPushButton(tr("editor.zoom_fit"))
        zoom_fit.setToolTip(tr("editor.zoom_fit_tip"))
        # 1.32: масштаб одной группой: «− | 100% | + | Вписать» в общей рамке
        zoom_box = QFrame()
        zoom_box.setObjectName("zoomGroup")
        zoom_row = QHBoxLayout(zoom_box)
        zoom_row.setContentsMargins(0, 0, 0, 0)
        zoom_row.setSpacing(0)
        for i, (button, width) in enumerate(((zoom_out, 32), (self.zoom_label, 56), (zoom_in, 32),
                                             (zoom_fit, max(76, zoom_fit.fontMetrics().horizontalAdvance(zoom_fit.text()) + 22)))):   # ширина по тексту: на другом языке надпись длиннее
            button.setObjectName("zoomSeg")
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setFixedWidth(width)
            button.setProperty("first", i == 0)
            button.setProperty("last", i == 3)
            button.setProperty("big", width < 40)
            zoom_row.addWidget(button)
        self.zoom_group = zoom_box
        row.addWidget(zoom_box)
        zoom_out.clicked.connect(lambda: self.zoom_step(-1))
        zoom_in.clicked.connect(lambda: self.zoom_step(1))
        self.zoom_label.clicked.connect(lambda: self.set_zoom(1.0))
        zoom_fit.clicked.connect(self.zoom_fit)
        self.zoom_fit_button = zoom_fit
        row.addSpacing(10)
        save = QPushButton(icons.icon("save"), "  " + tr("editor.save"))
        save.setObjectName("light")   # 1.32: «Сохранить» и «Скопировать» лёгкие, без рамки
        save.setIconSize(QSize(18, 18))
        save.setToolTip(tr("editor.save_tip"))
        save.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        save.clicked.connect(self.save_and_close)
        copy = QPushButton(icons.icon("copy"), "  " + tr("editor.copy"))
        copy.setObjectName("light")
        copy.setIconSize(QSize(18, 18))
        copy.setToolTip(tr("editor.copy_tip"))
        copy.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        copy.clicked.connect(self.copy_to_clipboard)
        # Главная кнопка: ей пользуются чаще всего, поэтому она зелёная, крупнее и стоит в правом нижнем углу
        copy_close = QPushButton(icons.icon("copy", "#f4fff8"), "  " + tr("editor.copy_close"))   # светлый значок без синей заливки
        copy_close.setObjectName("finish")
        copy_close.setIconSize(QSize(20, 20))
        copy_close.setToolTip(tr("editor.copy_close_tip"))
        copy_close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        copy_close.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_close.clicked.connect(self.copy_and_close)
        self.save_button, self.copy_button, self.copy_close_button = save, copy, copy_close
        # Заметная фиолетовая кнопка: текст со всего снимка в буфер обмена (область: инструмент «Текст с картинки»)
        dark = palette(self.ctx.config)["dark"]
        ocr_button = QPushButton(icons.icon("ocr", soft_colors("ocr", dark)[1]), "  " + self.OCR_LABEL_ON)
        ocr_button.setCheckable(True)
        ocr_button.setObjectName("ocrButton")   # 1.32: мягкая фиолетовая (цвета в make_style, SOFT)
        ocr_button.setIconSize(QSize(18, 18))
        ocr_button.setToolTip(tr("editor.ocr_button_tip"))
        ocr_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        ocr_button.setCursor(Qt.CursorShape.PointingHandCursor)
        ocr_button.clicked.connect(lambda: self.exit_text_mode() if self.canvas.tool == OCR else self.select_tool(OCR))
        # одинаковая ширина при обеих надписях: кнопка не прыгает при входе и выходе из режима текста
        bold_o = QFont(ocr_button.font())
        bold_o.setBold(True)
        fm = QFontMetrics(bold_o)
        ocr_button.setMinimumWidth(max(fm.horizontalAdvance("  " + t) for t in (self.OCR_LABEL_ON, self.OCR_LABEL_OFF)) + 44)
        self.ocr_button = ocr_button
        # Способ выделения текста: «Подряд» (как на телефоне) или «Маркер»; виден только в режиме текста
        mode_box = QWidget()
        mode_row = QHBoxLayout(mode_box)
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.setSpacing(0)
        self.text_mode_group = QButtonGroup(self)
        self.text_mode_buttons = {}
        for key, caption, tip, radius in (
                ("range", tr("editor.mode_range"), tr("editor.mode_range_tip"), "border-top-left-radius: 6px; border-bottom-left-radius: 6px;"),
                ("marker", tr("editor.mode_marker"), tr("editor.mode_marker_tip"), "border-top-right-radius: 6px; border-bottom-right-radius: 6px;")):
            b = QPushButton(caption)
            b.setCheckable(True)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setStyleSheet("QPushButton { padding: 5px 12px; border: 1px solid #7c3aed; background: #f3edff; color: #3b1a7a;"
                            f" border-radius: 0px; {radius} }}"
                            " QPushButton:checked { background: #7c3aed; color: white; font-weight: bold; }")
            b.clicked.connect(lambda _=False, k=key: self.set_text_mode(k))
            self.text_mode_group.addButton(b)
            self.text_mode_buttons[key] = b
            mode_row.addWidget(b)
        self.text_mode_box = mode_box   # живёт в фиолетовой полосе режима текста (_build_text_bottom)
        mode_box.setVisible(False)
        # «Копировать текст» и «Перевести» во втором ряду верхней панели справа: там есть место,
        # а в нижней панели они делали окно шире 1400 пикселей даже для маленького снимка
        self.panel_row2.addWidget(ocr_button)
        # «Перевести»: сдвоенная бирюзовая кнопка, как полоса и окошки перевода. Левая половина «Перевести всё»
        # переводит весь снимок сразу (без значка: ради ширины окна на маленьком снимке), правая «выделенное» включает выбор куска мышью; в режиме перевода правая
        # половина показывает «Готово (Esc)»
        block = QWidget()
        block.setObjectName("trBlock")
        block_row = QHBoxLayout(block)
        block_row.setContentsMargins(0, 0, 0, 0)
        block_row.setSpacing(0)
        all_button = QPushButton(icons.icon("translate_all", soft_colors("tr", dark)[1]), self.TR_ALL_LABEL)
        all_button.setIconSize(QSize(18, 18))
        all_button.setObjectName("trAllButton")
        all_button.setToolTip(self.TR_ALL_TIP)
        tr_button = QPushButton(self.TR_SEL_LABEL)
        tr_button.setObjectName("trButton")
        tr_button.setCheckable(True)
        tr_button.setToolTip(self.TR_SEL_TIP)
        for b in (all_button, tr_button):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        bold = QFont(tr_button.font())
        bold.setBold(True)
        fm_b = QFontMetrics(bold)   # подписи полужирные: ширина по полужирному шрифту
        tr_button.setMinimumWidth(max(fm_b.horizontalAdvance(t) for t in (self.TR_SEL_LABEL, self.TR_DONE_LABEL)) + 24)
        all_button.setMinimumWidth(fm_b.horizontalAdvance(self.TR_ALL_LABEL) + 18 + 7 + 22)
        all_button.clicked.connect(self.translate_all)
        tr_button.clicked.connect(lambda: self.exit_translate_mode() if self.canvas.tool == TRANSLATE else self.select_tool(TRANSLATE))
        block_row.addWidget(all_button)
        block_row.addWidget(tr_button)
        self.tr_all_button, self.tr_button, self.tr_block = all_button, tr_button, block
        self.panel_row2.addSpacing(6)
        self.panel_row2.addWidget(block)
        row.addSpacing(6)
        row.addWidget(save)
        row.addWidget(copy)
        row.addSpacing(10)
        row.addWidget(copy_close)
        self.bottom = bottom
        return bottom

    def _build_shortcuts(self):
        # Сочетание (QKeyCombination.toCombined) → действие: запасной путь для русской раскладки, см. eventFilter.
        self._key_slots = {}
        # Сочетание, на котором уже есть QShortcut. Второй QShortcut на тех же клавишах Qt считает неоднозначным
        # и не выполняет ни один (1.32.0: в Windows StandardKey.Redo тоже Ctrl+Y, и Ctrl+Y не работал).
        bound = set()

        def bind(keys, slot):
            for key in keys:
                seq = QKeySequence(key)
                name = seq.toString(QKeySequence.SequenceFormat.PortableText)
                if name and name not in bound:
                    bound.add(name)
                    QShortcut(seq, self, activated=slot)
                sequences = (QKeySequence.keyBindings(key) if isinstance(key, QKeySequence.StandardKey)
                             else [QKeySequence(key)])
                for seq in sequences:
                    if seq.count() == 1:
                        self._key_slots.setdefault(seq[0].toCombined(), slot)

        for tool, _glyph, _tip, key in TOOLS:
            bind([key], lambda t=tool: self.select_tool(t))
        for level in range(1, 6):
            bind([str(level)], lambda lv=level: self.select_size(lv))
        bind([QKeySequence.StandardKey.Undo], self.canvas.undo)
        bind(["Ctrl+Y", "Ctrl+Shift+Z"], self.canvas.redo)   # повтор одинаково в Windows и Linux, без StandardKey
        bind([QKeySequence.StandardKey.Save], self.save_and_close)
        bind([QKeySequence.StandardKey.Copy], self.copy_shortcut)
        bind([QKeySequence.StandardKey.SelectAll], self.select_all_shortcut)
        bind(["Return", "Enter"], self.enter_pressed)
        bind(["Ctrl+Return", "Ctrl+Enter"], self.copy_and_close)
        bind(["Shift+Y"], self.translate_all)
        bind(["Escape"], self.escape)
        bind(["Ctrl+D"], self.canvas.duplicate_selected)
        bind(["Ctrl+,"], self.open_settings)
        bind(["Ctrl++", "Ctrl+="], lambda: self.zoom_step(1))
        bind(["Ctrl+-"], lambda: self.zoom_step(-1))
        bind(["Ctrl+0"], lambda: self.set_zoom(1.0))
        bind(["Ctrl+9"], self.zoom_fit)
        bind(["F1"], self.start_tour)
        bind([QKeySequence.StandardKey.Paste], self.paste_image)
        bind(["Shift+Delete"], self.canvas.delete_selected)
        if sys.platform == "win32":
            QApplication.instance().installEventFilter(self)

    _TEXT_INPUTS = (QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox, QKeySequenceEdit)
    _MOD_MASK = (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
                 | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier)

    def eventFilter(self, obj, event):
        """Windows, русская (и любая не латинская) раскладка: клавиши V, A, R, Ctrl+C, Ctrl+Z…

        Qt сравнивает сочетания по введённому символу: на русской раскладке вместо «A» приходит «Ф»,
        и инструменты не переключаются. Здесь берём физическую клавишу (код VK Windows) и запускаем
        то же действие. Если сочетание уже сработало штатно, KeyPress сюда не доходит."""
        if isinstance(obj, QMenu) and obj is getattr(self, "_group_menu", None) \
                and event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.RightButton:
            return self._menu_right_click(obj, event)
        if event.type() == QEvent.Type.Wheel and obj is self.scroll.viewport() \
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.angleDelta().y():
                self.zoom_by(1.2 ** (event.angleDelta().y() / 120), event.globalPosition())
            return True
        if event.type() != QEvent.Type.KeyPress or not self.isActiveWindow():
            return False
        try:
            vk = event.nativeVirtualKey()
        except AttributeError:
            return False
        if not (0x41 <= vk <= 0x5A or 0x30 <= vk <= 0x39) or event.key() == Qt.Key(vk):
            return False    # не буква/цифра или раскладка латинская — пусть работает штатно
        focus = QApplication.focusWidget()
        if isinstance(focus, self._TEXT_INPUTS) or (focus is not None and focus.window() is not self):
            return False    # идёт ввод текста — буквы нужны самому полю
        mods = event.modifiers() & self._MOD_MASK
        slot = self._key_slots.get(QKeyCombination(mods, Qt.Key(vk)).toCombined())
        if slot is None:
            return False
        slot()
        return True

    def _remove_key_filter(self):
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)

    # --- выбор инструмента, цвета, толщины -----------------------------------

    def select_eraser_mode(self, mode):
        self.canvas.eraser_mode = mode
        self.canvas.erase_hover = None
        self.canvas.update_cursor()
        self.canvas.update()
        for button in self.eraser_group.buttons():
            button.setChecked(button.property("eraser_mode") == mode)
        self.ctx.config["eraser_mode"] = mode
        self.ctx.save_config()

    _BACK_ATTR = {OCR: "_tool_before_text", TRANSLATE: "_tool_before_translate", CROP: "_tool_before_crop",
                  ERASER: "_tool_before_eraser"}

    def _real_tool_before(self, prev):
        """Инструмент, к которому вернёт выход: если вошли из другого режима, то тот, что был до него (по цепочке),
        а если и там круг или режим, то MOVE. Так Esc не гоняет по кругу между режимами."""
        seen = set()
        while prev in self._BACK_ATTR:
            if prev in seen:
                return MOVE
            seen.add(prev)
            prev = getattr(self, self._BACK_ATTR[prev], None)
        return prev or MOVE

    def select_tool(self, tool):
        if tool == OCR and not self.ctx.config.get("ocr_enabled", True):
            return   # распознавание выключено в настройках
        if tool == TRANSLATE and not self.ctx.config.get("translate_enabled", True):
            return   # перевод выключен в настройках
        if tool in self._BACK_ATTR and self.canvas.tool != tool:
            setattr(self, self._BACK_ATTR[tool], self._real_tool_before(self.canvas.tool))   # к нему вернёт «Готово» / Esc
        self.canvas.set_tool(tool)
        self._sync_translate_layer(tool)
        if tool != OCR:
            self._action_hint()   # текст: подсказка после распознавания; остальное: показать свою или убрать прежнюю
        if getattr(self, "ocr_button", None) is not None:
            self.ocr_button.setChecked(tool == OCR)
            self.ocr_button.setText("  " + (self.OCR_LABEL_OFF if tool == OCR else self.OCR_LABEL_ON))
            self.text_mode_box.setVisible(tool == OCR)
        if tool == OCR:
            self.set_text_mode(self.ctx.config.get("ocr_select_mode", "range"))
        if tool == OCR:
            QTimer.singleShot(0, self.start_text_mode)
        if hasattr(self, "eraser_box") and self.eraser_box.isVisibleTo(self.panel) != (tool == ERASER):
            self.eraser_box.setVisible(tool == ERASER)
            self._refit_width()   # «Целиком / Частично» появились или ушли: второму ряду нужна другая ширина
        if hasattr(self, "text_color_button"):
            self._sync_controls()
        self.tool_buttons[tool].setChecked(True)
        if tool in TOOL_GROUP and getattr(self, "group_buttons", None):   # 1.32: инструмент встаёт на значок своей группы
            self.group_current[TOOL_GROUP[tool]] = tool
            last = dict(self.ctx.config.get("tool_group_last") or {})
            last[TOOL_GROUP[tool]] = tool
            self.ctx.config["tool_group_last"] = last
        self._sync_groups()
        if tool not in MODE_TOOLS:   # режимы (текст, перевод, обрезка) не запоминаются: следующий снимок открывается обычным видом
            self.ctx.config["tool"] = tool
            self.ctx.save_config()   # выбор сразу запоминается для следующего снимка

    def select_color(self, color):
        """Ничего не выделено: цвет следующих линий (запоминается). Выделен объект: перекрашивается только он,
        у палитры подсказка с кнопкой «Рисовать дальше этим цветом» (решение владельца 20.11.2026)."""
        color = QColor(color).name().lower()
        if self.canvas.set_color(color):
            self.ctx.config["color"] = color
            self.ctx.save_config()
            self._dismiss_pen_hint()
        else:
            self._object_restyled(color=color)
        self._sync_controls()

    # --- свои цвета из «+» --------------------------------------------------

    def _own_colors(self) -> list:
        """Свои цвета из настроек: не больше OWN_COLORS_MAX, без повторов и без цветов основной палитры."""
        out = []
        raw = self.ctx.config.get("custom_colors")
        for c in (raw if isinstance(raw, list) else []):   # не список (число, true, строка, словарь): пустой список
            if isinstance(c, str) and QColor(c).isValid():
                name = QColor(c).name().lower()
                if name not in PALETTE and name not in out:
                    out.append(name)
        return out[-OWN_COLORS_MAX:]

    def _add_own_button(self, name):
        pal = palette(self.ctx.config)
        swatch = SwatchButton(name)
        swatch.ring, swatch.dark = QColor(pal["t"]), pal["dark"]
        swatch.setToolTip(tr("editor.own_color_tip", color=name.upper()))
        swatch.setAccessibleName(name.upper())
        swatch.clicked.connect(lambda _c, col=name: self.select_color(col))
        swatch.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        swatch.customContextMenuRequested.connect(lambda pos, col=name, b=swatch: self._own_color_menu(col, b, pos))
        self.color_group.addButton(swatch)
        self._own_row.insertWidget(self._own_row.indexOf(self.custom_color), swatch)
        self.own_buttons[name] = swatch
        return swatch

    def _remove_own_button(self, name):
        swatch = self.own_buttons.pop(name, None)
        if swatch is not None:
            self.color_group.removeButton(swatch)
            self._own_row.removeWidget(swatch)
            swatch.hide()
            swatch.deleteLater()

    def remember_own_color(self, color):
        """Цвет из окна «Другой цвет…» встаёт в палитру образцом; новый вытесняет самый старый."""
        name = QColor(color).name().lower()
        own = self._own_colors()
        if name in PALETTE or name in own:
            return
        own.append(name)
        while len(own) > OWN_COLORS_MAX:
            self._remove_own_button(own.pop(0))
        self.ctx.config["custom_colors"] = list(own)
        self.ctx.save_config()
        self._add_own_button(name)
        self._refit_width()

    def forget_own_color(self, color):
        name = QColor(color).name().lower()
        self.ctx.config["custom_colors"] = [c for c in self._own_colors() if c != name]
        self.ctx.save_config()
        self._remove_own_button(name)
        self._sync_controls()
        self._refit_width()

    def _own_color_menu(self, name, swatch, pos):
        menu = QMenu(self)
        style_menu(menu, self.ctx.config)
        menu.addAction(tr("editor.remove_own_color")).triggered.connect(lambda: self.forget_own_color(name))
        menu.exec(swatch.mapToGlobal(pos))

    def _check_swatch(self, name):
        """Отметить в палитре образец этого цвета; если такого нет, ни один не отмечен."""
        button = self.color_buttons.get(name) or self.own_buttons.get(name)
        if button is not None:
            button.setChecked(True)
            return
        self.color_group.setExclusive(False)
        for b in self.color_group.buttons():
            b.setChecked(False)
        self.color_group.setExclusive(True)

    def pick_custom_color(self):
        color = QColorDialog.getColor(QColor(self._shown_values()[0]), self, tr("editor.color"))
        if color.isValid():
            self.remember_own_color(color.name())
            self.select_color(color.name())
        else:
            self._sync_controls()

    # --- подсказка «изменён только этот объект» -----------------------------

    def _object_restyled(self, color=None, size=None, text_color=Canvas._KEEP):
        """Цвет, толщина или цвет текста поменялись только у выделенного объекта (или у правящегося текста):
        показать или обновить подсказку у палитры. Если значение совпало с текущим для новых линий, предлагать
        нечего."""
        c = self.canvas
        target = c.selected if c.editing_object() else ("text" if c.text_edit is not None else None)
        if target is None:
            return
        hint = self._pen_hint
        if hint is None:
            hint = self._pen_hint = PenHint(self)
            hint.apply_theme(palette(self.ctx.config)["dark"])
            hint.adopt.connect(self._adopt_pending)
        if hint.target is not target or not hint.isVisible():
            hint.pending = {}
            hint.target = target
        pen_color, pen_size, pen_text = c.pen_values()
        if color is not None:
            if QColor(color) != QColor(pen_color):
                hint.pending["color"] = QColor(color).name().lower()
            else:
                hint.pending.pop("color", None)
        if size is not None:
            if size != pen_size:
                hint.pending["size"] = size
            else:
                hint.pending.pop("size", None)
        if text_color is not Canvas._KEEP:
            new = QColor(text_color).name().lower() if text_color is not None else None
            old = QColor(pen_text).name().lower() if pen_text is not None else None
            if new != old:
                hint.pending["text_color"] = new
            else:
                hint.pending.pop("text_color", None)
        if not hint.pending:
            hint.dismiss()
            return
        keys = set(hint.pending)
        kind = "size" if keys == {"size"} else ("both" if "size" in keys else "color")
        hint.show_kind(kind, pen_color if "color" in keys else None)
        self._place_pen_hint()

    def _place_pen_hint(self):
        """Под палитрой у левого края снимка; если там выделенный объект, справа, иначе внизу: подсказка не
        закрывает то, с чем работают."""
        hint = getattr(self, "_pen_hint", None)
        if hint is None or not hint.isVisible():
            return
        view = self.scroll.viewport()
        area = QRect(view.mapTo(self, QPoint(0, 0)), view.size())
        first = self.color_buttons[PALETTE[0]]
        x = max(area.left() + 8, first.mapTo(self, QPoint(0, 0)).x())
        spots = [QPoint(x, area.top() + 8), QPoint(area.right() - hint.width() - 8, area.top() + 8),
                 QPoint(x, area.bottom() - hint.height() - 8)]
        busy = QRect()
        sel = self.canvas.selected if self.canvas.editing_object() else None
        if sel is not None:
            z = self.canvas.zoom
            r = sel.bounding_rect()
            busy = QRect(self.canvas.mapTo(self, QPoint(int(r.left() * z), int(r.top() * z))),
                          QSize(int(r.width() * z) + 1, int(r.height() * z) + 1)).adjusted(-6, -6, 6, 6)
        spot = next((p for p in spots if not QRect(p, hint.size()).intersects(busy)), spots[0])
        hint.move(spot)
        hint.raise_()

    def _adopt_pending(self):
        """«Рисовать дальше…»: новое значение объекта становится текущим для следующих линий и запоминается."""
        hint = self._pen_hint
        pending = dict(hint.pending) if hint is not None else {}
        if hint is not None:
            hint.dismiss()
        if not pending:
            return
        kw = {k: pending[k] for k in ("color", "size") if k in pending}
        if "text_color" in pending:
            kw["text_color"] = pending["text_color"]
        self.canvas.adopt_pen(**kw)
        cfg = self.ctx.config
        if "color" in pending:
            cfg["color"] = pending["color"]
        if "size" in pending:
            cfg["size"] = pending["size"]
        if "text_color" in pending:
            cfg["text_color"] = pending["text_color"] or ""
        self.ctx.save_config()
        self._sync_controls()

    def _dismiss_pen_hint(self):
        if self._pen_hint is not None and self._pen_hint.isVisible():
            self._pen_hint.dismiss()

    def _build_text_color_button(self) -> QToolButton:
        """Кнопка «Цвет текста» (цифра в номере, текст в сноске): клик — палитра."""
        button = QToolButton()
        button.setObjectName("action")
        button.setFixedSize(46, 30)
        button.setIconSize(QSize(36, 22))
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setToolTip(tr("editor.text_color_tip"))
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(button)
        style_menu(menu, self.ctx.config)
        grid_holder = QWidget()
        grid = QGridLayout(grid_holder)
        grid.setContentsMargins(10, 10, 10, 10)
        grid.setSpacing(6)
        title = QLabel(tr("editor.text_color_tip"))
        title.setStyleSheet("font-weight: bold; color: #333;")
        grid.addWidget(title, 0, 0, 1, 5)
        auto = QPushButton(tr("editor.auto"))
        auto.setToolTip(tr("editor.auto_tip"))
        auto.clicked.connect(lambda: (menu.close(), self.select_text_color(None)))
        grid.addWidget(auto, 1, 0, 1, 5)
        for i, color in enumerate(PALETTE):
            swatch = QToolButton()
            swatch.setFixedSize(30, 30)
            swatch.setToolTip(color.upper())
            swatch.setStyleSheet(f"QToolButton {{ background: {color}; border: 1px solid #8a8a8a; border-radius: 4px; }}"
                                 f"QToolButton:hover {{ border: 2px solid #111; }}")
            swatch.clicked.connect(lambda _c, col=color: (menu.close(), self.select_text_color(col)))
            grid.addWidget(swatch, 2 + i // 5, i % 5)
        other = QToolButton()
        other.setFixedSize(30, 30)
        other.setText("+")
        other.setToolTip(tr("editor.other_color"))
        other.clicked.connect(lambda: (menu.close(), self.pick_text_color()))
        grid.addWidget(other, 3, 4)
        action = QWidgetAction(menu)
        action.setDefaultWidget(grid_holder)
        menu.addAction(action)
        button.setMenu(menu)
        self.text_color_button = button
        self._update_text_color_button()
        return button

    def _update_text_color_button(self):
        color, _size, text_color, shape = self._shown_values() if hasattr(self, "size_group") else (
            self.canvas.color, 0, self.canvas.text_color, None)
        fill = QColor(color)
        kind = shape.kind if shape is not None else self.canvas.tool
        fg = text_color or (text_color_on(fill) if kind == CALLOUT else QColor("#ffffff"))
        pix = QPixmap(36 * 3, 22 * 3)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(3, 3)
        p.setPen(QPen(QColor("#6b6f76"), 1))
        p.setBrush(fill)
        p.drawRoundedRect(QRectF(0.5, 0.5, 35, 21), 4, 4)
        font = p.font()
        font.setPixelSize(15)
        font.setBold(True)
        p.setFont(font)
        p.setPen(fg)
        p.drawText(QRectF(0, 0, 36, 22), Qt.AlignmentFlag.AlignCenter, "A")
        p.end()
        pix.setDevicePixelRatio(3)
        self.text_color_button.setIcon(QIcon(pix))

    def select_text_color(self, color):
        if self.canvas.set_text_color(QColor(color) if color is not None else None):
            self.ctx.config["text_color"] = QColor(color).name() if color is not None else ""
            self.ctx.save_config()
            self._dismiss_pen_hint()
        else:
            self._object_restyled(text_color=color)
        self._sync_controls()

    def pick_text_color(self):
        color = QColorDialog.getColor(self.canvas.text_color or QColor("#ffffff"), self, tr("editor.text_color"))
        if color.isValid():
            self.select_text_color(color.name())

    def select_size(self, size):
        changed = self.canvas.set_size(size)
        if self.canvas.tool == ERASER:
            self.ctx.config["eraser_size"] = size
            self.ctx.save_config()
        elif changed:
            self.ctx.config["size"] = size
            self.ctx.save_config()
            self._dismiss_pen_hint()
        else:
            self._object_restyled(size=size)
        self._sync_controls()

    def _shown_values(self):
        """Что показывают кнопки: свойства выделенного объекта или общий выбор (при ластике — кисть)."""
        c = self.canvas
        if c.tool == ERASER:
            return c.color, c.eraser_size, c.text_color, None
        if c.editing_object():
            sh = c.selected
            return sh.color, sh.size, sh.text_color, sh
        return c.color, c.pen_size, c.text_color, None

    def _sync_controls(self):
        color, size, text_color, shape = self._shown_values()
        self._check_swatch(QColor(color).name().lower())
        self.size_group.button(size).setChecked(True)
        self._update_text_color_button()
        self._update_info()

    def _selection_changed(self, shape):
        """Выделили объект — кнопки показывают его свойства и меняют только его; сняли — общий выбор."""
        hint = self._pen_hint
        if hint is not None and hint.isVisible() and hint.target is not shape:
            hint.dismiss()       # выделили другое или сняли выделение: подсказка была про прежний объект
        self._sync_controls()

    def paste_image(self):
        mime = QGuiApplication.clipboard().mimeData()
        image = QImage()
        if mime is not None and mime.hasImage():
            image = QImage(mime.imageData())
        elif mime is not None:
            for url in mime.urls():
                if _is_image_file(url.toLocalFile()):
                    image = QImage(url.toLocalFile())
                    break
        if image.isNull():
            self.ctx.notify(tr("editor.no_image"))
            return
        self.canvas.insert_image(image)

    def insert_from_file(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("editor.insert_title"), os.path.expanduser(self.ctx.config["save_dir"]),
                                              tr("editor.images_filter"))
        if path:
            self.canvas.insert_image(QImage(path))

    def insert_screenshot(self):
        """Снять ещё одну область экрана и положить её поверх этого снимка."""
        if hasattr(self.ctx, "capture_into"):
            self.ctx.capture_into(self)

    DEFAULT_TIP_ON = dynamic(lambda self: tr("editor.default_tip_on"))   # надписи читаются при показе: язык меняется на ходу
    DEFAULT_TIP_OFF = dynamic(lambda self: tr("editor.default_tip_off"))

    def _tool_tip(self, tool) -> str:
        """Подсказка кнопки инструмента; последней строкой: он по умолчанию или как им стать."""
        tip = {t: tr(tp) for t, _g, tp, _k in TOOLS}[tool] + "\n" + tr("editor.drag_tip")
        if tool in NO_DEFAULT_TOOLS:
            return tip
        return tip + "\n" + (self.DEFAULT_TIP_ON if tool == default_tool(self.ctx.config) else self.DEFAULT_TIP_OFF)

    def _sync_default_tool(self):
        """Галочка на кнопке инструмента по умолчанию (одна на все) и подсказки кнопок."""
        current = default_tool(self.ctx.config)
        for tool, button in self.tool_buttons.items():
            button.set_default_mark(bool(current) and tool == current)
            button.setToolTip(self._tool_tip(tool))
        self._sync_groups()

    def set_default_tool(self, tool):
        """Правая кнопка по инструменту: сделать его инструментом по умолчанию (пусто: без него, открывать с последним)."""
        self.ctx.config["default_tool"] = tool if tool and tool not in NO_DEFAULT_TOOLS else ""
        self.ctx.save_config()
        self._sync_default_tool()

    def _save_tool_order(self, order):
        self.ctx.config["tool_order"] = order
        self.ctx.save_config()

    def _tool_strip_menu(self, pos):
        button = self.tool_strip.childAt(pos)
        while button is not None and not isinstance(button, DraggableToolButton):
            button = button.parentWidget() if button.parentWidget() is not self.tool_strip else None
        tool = button.current if isinstance(button, GroupButton) else (button.tool if button is not None else None)
        menu = self.build_tool_menu(tool)
        menu.exec(self.tool_strip.mapToGlobal(pos))

    def build_tool_menu(self, tool=None) -> QMenu:
        """Меню правой кнопки по инструменту: сделать его инструментом по умолчанию, снять выбор, вернуть порядок."""
        menu = QMenu(self)
        style_menu(menu, self.ctx.config)
        if tool is not None and tool not in NO_DEFAULT_TOOLS:
            if tool == default_tool(self.ctx.config):
                menu.addAction(tr("editor.default_is", name=tool_title(tool)))
            else:
                menu.addAction(_capital(tr("editor.default_make", name=tr(TOOL_ACCUSATIVE[tool]) if tool in TOOL_ACCUSATIVE else tool_title(tool).lower()))).triggered.connect(
                    lambda _c=False, t=tool: self.set_default_tool(t))
        menu.addAction(tr("editor.default_none")).triggered.connect(
            lambda _c=False: self.set_default_tool(""))
        menu.addSeparator()
        menu.addAction(tr("editor.reset_order")).triggered.connect(
            lambda: self.tool_strip.set_order([t for t, _g, _tip, _k in TOOLS]))
        return menu

    # --- 1.32: группы инструментов, «Все инструменты» -------------------------------------------

    def _tool_available(self, tool) -> bool:
        """Распознавание или перевод выключены в настройках: их кнопок и пунктов нет."""
        if tool == OCR:
            return bool(self.ctx.config.get("ocr_enabled", True))
        if tool == TRANSLATE:
            return bool(self.ctx.config.get("translate_enabled", True))
        return True

    def _initial_group_tools(self) -> dict:
        """Что стоит на значке каждой группы при открытии: текущий инструмент, если он в группе; иначе инструмент
        по умолчанию из этой группы; иначе последний выбранный в группе (config tool_group_last); иначе главный."""
        cfg = self.ctx.config
        last = cfg.get("tool_group_last") if isinstance(cfg.get("tool_group_last"), dict) else {}
        default = default_tool(cfg)
        current = {}
        for code, _key, tools in GROUPS:
            pick = GROUP_MAIN[code]
            if last.get(code) in tools:
                pick = last[code]
            if default in tools:
                pick = default
            if self.canvas.tool in tools:
                pick = self.canvas.tool
            current[code] = pick
        return current

    def _group_tool(self, code):
        """Инструмент на значке группы с учётом выключенных в настройках."""
        tool = self.group_current.get(code, GROUP_MAIN[code])
        if self._tool_available(tool):
            return tool
        avail = [t for t in GROUP_TOOLS[code] if self._tool_available(t)]
        return avail[0] if avail else tool

    def _group_tip(self, code) -> str:
        tool = self._group_tool(code)
        first = {t: tr(tp) for t, _g, tp, _k in TOOLS}[tool].split("\n")[0]
        tip = tr("editor.group_tip", group=tr(GROUP_TITLE[code]), tool=first) + "\n" + tr("editor.group_menu_tip") \
            + "\n" + tr("editor.group_drag_tip")
        if tool in NO_DEFAULT_TOOLS:
            return tip
        return tip + "\n" + (self.DEFAULT_TIP_ON if tool == default_tool(self.ctx.config) else self.DEFAULT_TIP_OFF)

    def _sync_groups(self):
        """Значки, подсказки, отметка и галочка кнопок групп по текущему инструменту и инструменту по умолчанию."""
        if not getattr(self, "group_buttons", None):
            return
        default = default_tool(self.ctx.config)
        for code, gb in self.group_buttons.items():
            tool = self._group_tool(code)
            gb.current = tool
            gb.setIcon(icons.icon(tool))
            gb.setToolTip(self._group_tip(code))
            gb.setChecked(self.canvas.tool in GROUP_TOOLS[code])
            gb.set_default_mark(bool(default) and tool == default)

    def _badged_icon(self, tool) -> QIcon:
        """Значок инструмента с зелёной галочкой (инструмент по умолчанию) для меню."""
        pix = icons.icon(tool).pixmap(QSize(24, 24), 3.0)
        pix.setDevicePixelRatio(3.0)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(12.5, 12.5, 11, 11)
        from .themes import GREEN
        p.setPen(QPen(QColor("#ffffff"), 1.3))
        p.setBrush(QColor(GREEN))
        p.drawEllipse(r)
        p.setPen(QPen(QColor("#ffffff"), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPolyline(QPolygonF([QPointF(r.left() + 3, r.top() + 5.8), QPointF(r.left() + 4.8, r.top() + 7.6),
                                  QPointF(r.left() + 8.2, r.top() + 3.6)]))
        p.end()
        return QIcon(pix)

    def build_group_menu(self, code) -> QMenu:
        """Меню группы (стрелка ▾): значок, название и клавиша каждого инструмента; текущий на подложке,
        у инструмента по умолчанию зелёная галочка. Правая кнопка по строке: «Сделать … по умолчанию»."""
        menu = QMenu(self)
        style_menu(menu, self.ctx.config)
        head = menu.addAction(tr(GROUP_TITLE[code]))
        head.setEnabled(False)
        default = default_tool(self.ctx.config)
        current = self._group_tool(code)
        keys = {t: k for t, _g, _tip, k in TOOLS}
        for tool in self.tool_strip.members(code):
            act = menu.addAction(self._badged_icon(tool) if tool == default else icons.icon(tool),
                                 tool_title(tool) + "\t" + keys[tool])
            act.setData(tool)
            if tool == current:
                f = act.font()
                f.setBold(True)
                act.setFont(f)
            act.triggered.connect(lambda _c=False, t=tool: self.select_tool(t))
        if code == "ocr" and self._tool_available(TRANSLATE):
            act = menu.addAction(icons.icon("translate_all"), tr("editor.menu_translate_all") + "\tShift+Y")
            act.triggered.connect(self.translate_all)
        menu.installEventFilter(self)
        self._group_menu = menu
        return menu

    def show_group_menu(self, code):
        gb = self.group_buttons[code]
        menu = self.build_group_menu(code)
        gb.menu_open = True
        gb.update()
        try:
            menu.exec(gb.mapToGlobal(QPoint(0, gb.height() + 2)))
        finally:
            gb.menu_open = False
            gb.update()

    def _menu_right_click(self, menu, event) -> bool:
        """Правая кнопка по строке меню группы: то же меню «инструмент по умолчанию», что и на кнопке."""
        act = menu.actionAt(event.position().toPoint())
        tool = act.data() if act is not None else None
        if tool not in {t for t, _g, _tip, _k in TOOLS}:
            return False
        menu.close()
        self.build_tool_menu(tool).exec(event.globalPosition().toPoint())
        return True

    def _set_more_label(self, on: bool):
        """«⋯ Все инструменты» с подписью или (узкое окно) только значок «⋯»."""
        b = self.more_button
        label = tr("editor.all_tools")
        b.setAccessibleName(label)
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon if on else Qt.ToolButtonStyle.ToolButtonIconOnly)
        b.setText(label if on else "")   # значком: название только в подсказке («Все инструменты: …»)
        b.setToolTip(tr("editor.all_tools_tip") if on else label + "\n" + tr("editor.all_tools_tip"))
        if on:
            b.ensurePolished()   # шрифт и отступы из таблицы стилей уже применены: ширина по ним
            b.setMinimumWidth(0)
            b.setMaximumWidth(16777215)
            b.setFixedWidth(max(b.sizeHint().width(), b.fontMetrics().horizontalAdvance(label) + 20 + 26))
        else:
            b.setFixedWidth(TOOL_W)
        self._more_label = on

    def all_tools_sections(self) -> list:
        """Разделы панели «Все инструменты»: [(заголовок, [инструменты])]: отдельные кнопки, потом группы в порядке ряда."""
        singles, groups = [], []
        for kind, key, tools in order_entries(self.tool_strip.order()):
            if kind == "tool":
                if self._tool_available(key):
                    singles.append(key)
            else:
                avail = [t for t in tools if self._tool_available(t)]
                if avail:
                    groups.append((tr(GROUP_TITLE[key]), avail))
        return [(tr("editor.group_main"), singles)] + groups

    def build_all_tools_menu(self) -> QMenu:
        """Панель «Все инструменты»: все инструменты по группам в три столбца, с горячими клавишами."""
        from PyQt6.QtWidgets import QWidgetAction
        menu = QMenu(self)
        style_menu(menu, self.ctx.config)
        t = theme(self.ctx.config)
        holder = QWidget()
        holder.setObjectName("allTools")
        grid = QHBoxLayout(holder)
        grid.setContentsMargins(8, 6, 8, 6)
        grid.setSpacing(14)
        keys = {tl: k for tl, _g, _tip, k in TOOLS}
        keys["translate_all"] = "Shift+Y"
        default = default_tool(self.ctx.config)
        sections = self.all_tools_sections()
        if self._tool_available(TRANSLATE):
            sections = [(title, tools + (["translate_all"] if TRANSLATE in tools else [])) for title, tools in sections]
        columns = split_columns(sections, 3)
        self.all_tools_rows = {}
        dark = t.get("dark")
        dim = t["text_dim"] if dark else "#6b7280"
        for col in columns:
            box = QVBoxLayout()
            box.setSpacing(1)
            for title, tools in col:
                head = QLabel(title)
                head.setObjectName("allToolsHead")
                head.setStyleSheet(f"QLabel#allToolsHead {{ color: {dim}; font-size: 12px; font-weight: bold; padding: 8px 6px 3px 6px; }}")
                box.addWidget(head)
                for tool in tools:
                    name = tr("editor.menu_translate_all") if tool == "translate_all" else tool_title(tool)
                    row = ToolRow(tool, name, keys.get(tool, ""), self._badged_icon(tool) if tool == default
                                  else icons.icon(tool), current=tool == self.canvas.tool, tokens=t)
                    row.clicked.connect(lambda _c=False, tl=tool: (menu.close(), self.translate_all() if tl == "translate_all"
                                                                   else self.select_tool(tl)))
                    if tool != "translate_all":
                        row.context.connect(lambda tl, pos: (menu.close(), self.build_tool_menu(tl).exec(pos)))
                    self.all_tools_rows[tool] = row
                    box.addWidget(row)
            box.addStretch(1)
            grid.addLayout(box)
        action = QWidgetAction(menu)
        action.setDefaultWidget(holder)
        menu.addAction(action)
        self._all_tools_menu = menu
        return menu

    def show_all_tools(self):
        menu = self.build_all_tools_menu()
        b = self.more_button
        b.setDown(True)
        try:
            menu.exec(b.mapToGlobal(QPoint(0, b.height() + 2)))
        finally:
            b.setDown(False)

    # --- 1.32: ширина окна и ступени сворачивания ---------------------------------------------------

    def _stages(self) -> list:
        """Ступени верхнего ряда по сужению окна: (свёрнутые группы, подпись у «Все инструменты»). Сначала
        сворачиваются «Рисование», «Текст с картинки», «Скрыть и стереть», «Фигуры»; затем «Все инструменты»
        остаётся значком; последними «Стрелки и линии» и «Надписи»."""
        out = [(frozenset(COLLAPSE_ORDER[:k]), True) for k in range(0, 5)]
        out += [(frozenset(COLLAPSE_ORDER[:k]), False) for k in range(4, len(COLLAPSE_ORDER) + 1)]
        return out

    def _measure_rows(self):
        """Сколько ширины нужно каждому ряду в каждом виде, по настоящим размерам кнопок на текущем языке.
        Считается при сборке панелей, смене языка, оформления и настроек, а не при каждом изменении размера окна."""
        if getattr(self, "panel_row1", None) is None or getattr(self, "zoom_fit_button", None) is None:
            return
        self.panel.ensurePolished()
        for w in self.panel.findChildren(QWidget):
            w.ensurePolished()   # размеры по таблице стилей (шрифт, отступы), даже пока окно не показано
        margins = self.panel.layout().contentsMargins()
        side = margins.left() + margins.right()
        row1 = self.panel_row1
        label_was = getattr(self, "_more_label", True)
        self._set_more_label(True)
        more_full = self.more_button.maximumWidth()
        self.tool_strip.row.invalidate()
        self.tool_strip.updateGeometry()
        row1.invalidate()
        rest = row1.sizeHint().width() - self.tool_strip.sizeHint().width() - more_full
        self._set_more_label(label_was)
        self._need_row1 = [side + rest + self.tool_strip.width_for(c) + (more_full if label else TOOL_W)
                           for c, label in self._stages()]
        # ряд 2: три вида: обе большие кнопки, только «Копировать текст», ни одной (1.32.2: «Перевести» уходит первой)
        row2 = self.panel_row2
        bigs = [w for w in (self.ocr_button, self.tr_block) if w is not None]
        shown = [w.isVisibleTo(self.panel) for w in bigs]
        wanted = [self.ctx.config.get("ocr_enabled", True), self.ctx.config.get("translate_enabled", True)]
        for w, want in zip(bigs, wanted):
            w.setVisible(want)
        row2.invalidate()
        full = row2.sizeHint().width()
        if getattr(self, "tr_block", None) is not None:
            self.tr_block.setVisible(False)
        row2.invalidate()
        only_ocr = row2.sizeHint().width()
        for w in bigs:
            w.setVisible(False)
        row2.invalidate()
        compact = row2.sizeHint().width()
        for w, was in zip(bigs, shown):
            w.setVisible(was)
        row2.invalidate()
        self._need_row2 = (side + full, side + only_ocr, side + compact)
        # нижняя строка: подписи «Вписать», «Сохранить», «Скопировать» или значки
        bl = self.bottom.layout()
        was = getattr(self, "_bottom_compact", False)
        self._set_bottom_compact(False)
        bl.invalidate()
        full = bl.minimumSize().width()
        self._set_bottom_compact(True)
        bl.invalidate()
        compact = bl.minimumSize().width()
        self._set_bottom_compact(was)
        bl.invalidate()
        self._need_bottom = (full, compact)
        self._stage = self._row2_state = self._bottom_state = None   # вид выбирается заново при следующей подгонке

    def min_content_width(self) -> int:
        """Самое узкое содержимое окна: всё свёрнуто, второй ряд без больших кнопок, внизу значки."""
        if not hasattr(self, "_need_row1"):
            self._measure_rows()
        return max(self._need_row1[-1], self._need_row2[-1], self._need_bottom[1])

    @staticmethod
    def _pick(needs, width, current):
        """Первый вид (от самого полного), который помещается; к более полному виду, чем текущий, только с запасом
        COLLAPSE_SLACK, чтобы кнопки не прыгали туда-обратно, когда окно тянут мышью около порога."""
        fit = next((i for i, n in enumerate(needs) if n <= width), len(needs) - 1)
        if current is None or fit >= current:
            return fit
        roomy = next((i for i, n in enumerate(needs) if n + COLLAPSE_SLACK <= width), current)
        return min(current, roomy)

    def _adapt_rows(self, width=None):
        """Свернуть или развернуть группы, спрятать или показать большие кнопки второго ряда и подписи нижних кнопок
        по ширине окна."""
        if getattr(self, "panel_row1", None) is None or getattr(self, "zoom_fit_button", None) is None:
            return
        if not hasattr(self, "_need_row1"):
            self._measure_rows()
        if width is None:
            width = self.width() - self._rim()[0]
        stages = self._stages()
        stage = self._pick(self._need_row1, width, getattr(self, "_stage", None))
        self._stage = stage
        collapsed, label = stages[stage]
        self.tool_strip.set_collapsed(collapsed)
        if label != getattr(self, "_more_label", None):
            self._set_more_label(label)
        big = self._pick(list(self._need_row2), width, getattr(self, "_row2_state", None))
        self._row2_state = big
        self._set_row2_compact(big)
        low = self._pick(list(self._need_bottom), width, getattr(self, "_bottom_state", None))
        self._bottom_state = low
        if (low == 1) != getattr(self, "_bottom_compact", False):
            self._set_bottom_compact(low == 1)

    def _set_row2_compact(self, level):
        """Узкое окно, второй ряд: 0 обе большие кнопки, 1 только «Копировать текст» («Перевести» ушла первой),
        2 ни одной (обе функции есть в группе «Текст с картинки», во «Все инструменты» и на клавише I)."""
        level = int(level)
        self._row2_compact = level
        if getattr(self, "ocr_button", None) is not None:
            self.ocr_button.setVisible(level < 2 and self.ctx.config.get("ocr_enabled", True))
        if getattr(self, "tr_block", None) is not None:
            self.tr_block.setVisible(level < 1 and self.ctx.config.get("translate_enabled", True))

    def _set_bottom_compact(self, on: bool):
        """Узкое окно: «Вписать», «Сохранить», «Скопировать» значками с подсказкой; «Скопировать и закрыть» с подписью."""
        self._bottom_compact = on
        fit = self.zoom_fit_button
        if on:
            fit.setText("")
            fit.setIcon(icons.icon("fit"))
            fit.setIconSize(QSize(20, 20))
            fit.setFixedWidth(34)
        else:
            fit.setIcon(QIcon())
            fit.setText(tr("editor.zoom_fit"))
            fit.setFixedWidth(max(76, fit.fontMetrics().horizontalAdvance(fit.text()) + 22))
        for b, key in ((self.save_button, "editor.save"), (self.copy_button, "editor.copy")):
            if on:
                b.setText("")
                b.setFixedWidth(36)
                b.setStyleSheet("QPushButton { padding: 0px; }")
            else:
                b.setText("  " + tr(key))
                b.setMinimumWidth(0)
                b.setMaximumWidth(16777215)
                b.setStyleSheet("")
        group = getattr(self, "zoom_group", None)
        if group is not None:   # «Вписать» стала шире или уже: размер группы масштаба пересчитать сразу (иначе старый)
            group.layout().invalidate()
            group.updateGeometry()

    # --- 1.32: колокольчик уведомлений ------------------------------------------------------------

    def _sync_bell(self):
        """Точка на колокольчике: есть непрочитанное; подсказка со счётом."""
        bell = getattr(self, "bell_button", None)
        if bell is None:
            return
        try:
            from . import notifications
            n = len(notifications.unread(self.ctx.config))
        except RuntimeError:
            return
        bell.ring = QColor(palette(self.ctx.config)["panel"])
        bell.set_unread(n)
        bell.setToolTip(tr("editor.bell_tip") + ("\n" + tr("notifications.unread", n=n) if n else ""))

    def build_notifications_menu(self) -> QMenu:
        """Список уведомлений: заголовок и «Прочитать все», пункты (непрочитанные на подложке), внизу
        «Проверить обновления»."""
        from PyQt6.QtWidgets import QWidgetAction
        from . import notifications
        menu = QMenu(self)
        style_menu(menu, self.ctx.config)
        cfg = self.ctx.config
        pal = palette(cfg)
        holder = QWidget()
        holder.setObjectName("bellList")
        holder.setFixedWidth(340)
        col = QVBoxLayout(holder)
        col.setContentsMargins(4, 2, 4, 2)
        col.setSpacing(2)
        head = QHBoxLayout()
        title = QLabel(tr("notifications.title"))
        title.setStyleSheet(f"font-weight: bold; font-size: 15px; color: {pal['t']}; padding: 6px 8px 4px 8px;")
        head.addWidget(title)
        head.addStretch(1)
        items = notifications.items(cfg)
        done = notifications.read_ids(cfg)
        read_all = QPushButton(tr("notifications.read_all"))
        read_all.setObjectName("bellLink")
        read_all.setFlat(True)
        read_all.setCursor(Qt.CursorShape.PointingHandCursor)
        read_all.setStyleSheet(f"QPushButton#bellLink {{ border: none; background: transparent; color: {pal['link']};"
                               f" font-size: 13px; padding: 0 8px; min-height: 24px; }}"
                               f" QPushButton#bellLink:disabled {{ color: {pal['t2']}; }}")
        read_all.setEnabled(any(it["id"] not in done and not it.get("history") for it in items))
        read_all.clicked.connect(lambda: (notifications.mark_read(cfg, [it["id"] for it in items], self.ctx.save_config),
                                          menu.close()))
        head.addWidget(read_all)
        col.addLayout(head)
        self.notice_rows = {}
        if not items:
            empty = QLabel(tr("notifications.empty"))
            empty.setStyleSheet(f"color: {pal['t2']}; padding: 14px 10px 16px 10px; font-size: 13px;")
            col.addWidget(empty)
        for it in items:
            row = NoticeRow(it, it["id"] not in done and not it.get("history"), pal)
            row.clicked.connect(lambda _c=False, item=it: (menu.close(), self.open_notice(item)))
            if row.action_button is not None:
                row.action_button.clicked.connect(lambda _c=False, item=it: (menu.close(), self.open_notice(item)))
            self.notice_rows[it["id"]] = row
            col.addWidget(row)
        check = QPushButton(tr("updater.menu.check"))
        check.setObjectName("bellLink")
        check.setFlat(True)
        check.setCursor(Qt.CursorShape.PointingHandCursor)
        check.setStyleSheet(read_all.styleSheet() + " QPushButton#bellLink { padding: 6px 8px 6px 8px; text-align: left; }")
        check.clicked.connect(lambda: (menu.close(), self._check_updates()))
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {pal['sep']};")
        col.addWidget(line)
        col.addWidget(check, 0, Qt.AlignmentFlag.AlignLeft)
        action = QWidgetAction(menu)
        action.setDefaultWidget(holder)
        menu.addAction(action)
        self._notices_menu = menu
        return menu

    def show_notifications(self):
        menu = self.build_notifications_menu()
        b = self.bell_button
        b.setDown(True)
        try:
            pos = b.mapToGlobal(QPoint(b.width(), b.height() + 2))
            menu.exec(QPoint(pos.x() - menu.sizeHint().width(), pos.y()))
        finally:
            b.setDown(False)

    def open_notice(self, item):
        """Пункт колокольчика: «Обновить» (проверка и окно предложения), «Что нового» (заметки версии), сообщение
        просто отмечается прочитанным."""
        from . import notifications
        notifications.mark_read(self.ctx.config, [item["id"]], self.ctx.save_config)
        if item["kind"] == "update":
            self._check_updates()
        elif item["kind"] == "whatsnew":
            notes = notifications.whats_new_notes(self.ctx.config, item["version"])
            from . import updater
            updater.UpdaterUI().whats_new(item["version"], notes)

    def _check_updates(self):
        from . import updater
        updater.get_updater(self.ctx).check_now(manual=True)

    def _show_about(self):
        if hasattr(self.ctx, "show_about"):
            self.ctx.show_about()

    def _rate(self):
        if hasattr(self.ctx, "show_rating"):
            self.ctx.show_rating()

    def start_tour(self, *_args, language=None):
        """Вводный курс поверх окна (первый запуск или по кнопке «Показать знакомство»).

        language: шаг выбора языка первым. По умолчанию только при самом первом знакомстве (tour_done ещё нет);
        повторное знакомство из «?», F1, меню значка и настроек начинается сразу с «Знакомство с ClipSD» (1.32)."""
        from .tour import Tour
        if getattr(self, "tour", None) is not None:
            return
        if language is None:
            language = not self.ctx.config.get("tour_done")
        self.tour = Tour(self, language=bool(language))
        self.tour.finished.connect(self._tour_finished)
        self.tour.start()

    def _tour_finished(self):
        self.tour = None
        self.ctx.config["tour_done"] = True
        self.ctx.save_config()

    def start_text_mode(self):
        """Режим «Копировать текст»: распознать снимок (один раз на снимок), подсветить слова."""
        from . import ocr
        if not self.ctx.config.get("ocr_enabled", True):
            return
        if self.canvas.has_words():
            self._text_mode_hint()
            return
        if self._ocr_job is not None:
            return
        from .busy import BusySpinner
        spinner = BusySpinner(self.scroll.viewport(), tr("editor.ocr_busy"))   # кружок «думаю» по центру снимка
        spinner.start()
        self._ocr_spinner = spinner
        key = self.canvas.base.cacheKey()

        def done(text, error, help=None):
            self._ocr_job = None
            if getattr(self, "_ocr_spinner", None) is not None:
                self._ocr_spinner.stop()
                self._ocr_spinner = None
            job_words = getattr(job, "words", [])
            if error:
                self._ocr_dialog = ocr.show_result("", error, self, help)
                self.select_tool(MOVE)
                return
            if self.canvas.base.cacheKey() != key:
                return   # снимок успели обрезать или отменить: распознаём заново при следующем входе
            self.canvas.set_words(job_words, self.canvas.base.devicePixelRatio())
            if help is not None:
                self._ocr_dialog = ocr.show_result("", tr("editor.ocr_no_ru"), self, help)
            self._text_mode_hint()
            self._update_info()
        job = ocr.start(self.canvas.base.copy(), done, ocr.resolve_langs(self.ctx.config.get("ocr_langs")),
                        self.ctx.config.get("ocr_quality", "accurate"))
        self._ocr_job = job

    def _sync_translate_layer(self, tool):
        """Слой перевода поверх снимка включён только в режиме перевода (создаётся при первом входе)."""
        on = tool == TRANSLATE
        if getattr(self, "tr_button", None) is not None:
            self.tr_button.setChecked(on)
            self.tr_button.setText(self.TR_DONE_LABEL if on else self.TR_SEL_LABEL)
        self._set_mode_ui(self.canvas.tool)
        layer = getattr(self, "tr_layer", None)
        if on and layer is None:
            from .translate_ui import TranslateLayer
            layer = TranslateLayer(self.canvas, self.exit_translate_mode)
            layer.tr_state_hook = self._update_info
            self.tr_layer = layer
        if layer is not None:
            layer.tr_cfg, layer.tr_save = self.ctx.config, self.ctx.save_config
            layer.activate(on)
        self._update_info()

    def _refit_width(self):
        """Ряд изменился (кнопки режима ластика, язык, настройки): ступени считаются заново; если самое узкое
        содержимое теперь шире окна, окно расширяется до него (не шире экрана). Вместо прежних _widen_for_panel и
        _widen_for_bottom (1.32)."""
        self._measure_rows()
        need = self.min_content_width() + self._rim()[0]
        area = self._screen_area()
        self.setMinimumWidth(min(need, area.width() - 20))
        if self.width() < need:
            self.resize(min(need, area.width() - 20), self.height())
        self._adapt_rows()

    def exit_translate_mode(self):
        if self.canvas.tool == TRANSLATE:
            back = getattr(self, "_tool_before_translate", None)
            self.select_tool(back if back not in (None, TRANSLATE) else MOVE)

    CROP_OK_LABEL = dynamic(lambda self: tr("editor.crop_ok_label"))
    CROP_CANCEL_LABEL = dynamic(lambda self: tr("editor.crop_cancel_label"))

    def crop_confirm_button(self):
        """Кнопка «Обрезать (Enter)» в строке режима обрезки: то же, что Enter."""
        if self.canvas.crop_pending:
            self.canvas.confirm_crop()
            self.exit_crop_mode()

    def exit_crop_mode(self):
        """Выйти из режима обрезки (рамка отменяется) к инструменту, что был до него."""
        if self.canvas.tool == CROP:
            self.canvas.cancel_crop()
            back = getattr(self, "_tool_before_crop", None)
            self.select_tool(back if back not in (None, CROP) else MOVE)

    def exit_eraser_mode(self):
        if self.canvas.tool == ERASER:
            back = getattr(self, "_tool_before_eraser", None)
            self.select_tool(back if back not in (None, ERASER) else MOVE)

    def copy_all_text(self):
        """«Скопировать весь текст»: выделить все слова и скопировать (то же, что Ctrl+A)."""
        if self.canvas.has_words():
            self.canvas.select_all_text()
        else:
            self.show_toast(tr("editor.ocr_no_text"))

    OCR_LABEL_ON = dynamic(lambda self: tr("editor.ocr_label_on"))
    OCR_LABEL_OFF = dynamic(lambda self: tr("editor.done_esc"))
    TR_ALL_LABEL = dynamic(lambda self: tr("editor.tr_all_label"))
    TR_SEL_LABEL = dynamic(lambda self: tr("editor.tr_sel_label"))
    TR_DONE_LABEL = dynamic(lambda self: tr("editor.done_esc"))
    TR_ALL_TIP = dynamic(lambda self: tr("editor.tr_all_tip"))
    TR_SEL_TIP = dynamic(lambda self: tr("editor.tr_sel_tip"))

    def translate_all(self):
        """«Перевести всё» и Shift+Y: весь снимок переводится сразу, без выделения мышью; перевод ложится поверх."""
        if not self.ctx.config.get("translate_enabled", True):
            return
        if self.canvas.tool != TRANSLATE:
            self.select_tool(TRANSLATE)
        from . import hints
        hints.hide_hint(self)   # выделять мышью ничего не нужно: подсказка «Выделите мышью…» тут не к месту
        layer = getattr(self, "tr_layer", None)
        if layer is not None:
            layer.tr_translate_all(layer.rect())

    def exit_text_mode(self):
        """Выйти из режима текста к тому инструменту, что был до него, и дальше работать со снимком."""
        if self.canvas.tool == OCR:
            back = getattr(self, "_tool_before_text", None)
            self.select_tool(back if back not in (None, OCR) else MOVE)

    def set_text_mode(self, mode: str):
        """«Подряд» или «Маркер»; выбор запоминается."""
        mode = "marker" if mode == "marker" else "range"
        self.canvas.text_mode = mode
        self.canvas.text_sel = set()
        self.canvas.update()
        if hasattr(self, "text_mode_buttons"):
            self.text_mode_buttons[mode].setChecked(True)
        if self.canvas.tool == OCR and self.canvas.has_words():
            self._action_hint()   # переключили «Подряд» / «Маркер»: подсказка про новый способ
        if self.ctx.config.get("ocr_select_mode") != mode:
            self.ctx.config["ocr_select_mode"] = mode
            self.ctx.save_config()
        self._update_info()

    def _text_mode_hint(self):
        if self.canvas.tool != OCR:
            return
        if self.canvas.has_words():
            self._update_info()   # постоянное напоминание: строка над нижней панелью
            self._action_hint()   # и крупная всплывающая подсказка у верхнего края снимка
        else:
            self.show_toast(tr("editor.ocr_no_text"))

    def _action_hint(self):
        """Всплывающая подсказка действия (крупно, у верхнего края снимка, 4 секунды): программа ждёт от человека
        выделения. Постоянное напоминание остаётся в строке над нижней панелью (mode_hint)."""
        from . import hints
        tool = self.canvas.tool
        if tool == OCR:
            if self.canvas.text_mode == "marker":
                hints.hint(self, tr("editor.hint_marker"), tr("editor.hint_marker_sub"))
            else:
                hints.hint(self, tr("editor.hint_range"), tr("editor.hint_exit_done"))
        elif tool == TRANSLATE:
            hints.hint(self, tr("editor.hint_translate"), tr("editor.hint_exit_done"))
        elif tool == CROP:
            hints.hint(self, tr("editor.hint_crop"), tr("editor.hint_crop_sub"))
        elif tool == ERASER:
            hints.hint(self, tr("editor.hint_eraser"), tr("editor.hint_eraser_exit"))
        else:
            hints.hide_hint(self)

    def _text_edit_started(self):
        """Ввод текста (инструмент T или сноска): крупная подсказка, как закончить и как отменить."""
        from . import hints
        hints.hint(self, tr("editor.hint_typing"), tr("editor.hint_typing_keys"))

    def _text_selected(self, text):
        """Выделили маркером: текст в буфер и в окно для копирования (одно окно, текст в нём обновляется)."""
        from . import ocr
        if not text:
            return
        ocr.copy_text(text)
        panel = getattr(self, "_text_panel", None)
        if panel is None or not panel.isVisible():
            panel = ocr.TextResultDialog(text, "", self)
            panel.destroyed.connect(lambda *_: setattr(self, "_text_panel", None))
            self._text_panel = panel
            # окно у правого края редактора, чтобы не закрывало снимок
            frame = self.frameGeometry()
            panel.move(max(0, frame.right() - panel.width() - 30), max(0, frame.bottom() - panel.height() - 90))
            panel.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)   # клавиши (Ctrl+A, Ctrl+C, Esc) остаются у редактора
            panel.show()
            self.activateWindow()
            self.canvas.setFocus()
        else:
            panel.set_text(text)
        ocr.toast(self)   # «Текст скопирован в буфер обмена», как на телефоне

    def copy_selected_text(self):
        text = self.canvas.selected_text()
        if text:
            self._text_selected(text)
        else:
            self.show_toast(tr("editor.select_text_first"))

    def enter_pressed(self):
        """Enter: если выделена рамка обрезки, применить её; иначе скопировать снимок."""
        if self.canvas.crop_pending:
            self.canvas.confirm_crop()
            self.exit_crop_mode()   # обрезали: режим обрезки завершён, вид и прежний инструмент возвращаются
        elif self.canvas.tool == CROP:
            return                  # режим обрезки без рамки: Enter не копирует снимок втихую
        else:
            self.copy_to_clipboard()

    def escape(self):
        """Esc: сначала отменить рамку обрезки, потом снять выделение, потом закрыть окно."""
        if self.canvas.tool == CROP:
            self.exit_crop_mode()   # Esc: рамка отменена и режим обрезки завершён
        elif self.canvas.crop_pending:
            self.canvas.cancel_crop()
        elif self.canvas.tool == ERASER:
            self.exit_eraser_mode()
        elif self.canvas.tool == OCR:
            self.exit_text_mode()   # выйти из режима текста к прежнему инструменту
        elif self.canvas.tool == TRANSLATE:
            self.exit_translate_mode()
        elif self.canvas.selected is not None and self.canvas.tool != ERASER:
            self.canvas.select(None)
        else:
            self.close()

    def show_context_menu(self, shape, global_pos):
        """Меню правой кнопки. У объекта (1.32): за рамкой выделения с ручками, чтобы меню не закрывало контур и
        ручки, за которые объект тянут; на пустом месте снимка у курсора, как обычно."""
        menu = self.build_context_menu(shape)
        menu.ensurePolished()
        pos = self.context_menu_pos(shape, QPoint(global_pos), menu.sizeHint())
        menu.exec(pos)

    def selection_frame_global(self, shape) -> QRect:
        """Рамка выделенного объекта вместе с ручками в экранных координатах (логические точки Qt: при масштабе
        Windows 125-200 % и на нескольких мониторах те же единицы, что у положения меню)."""
        r = QRectF(shape.bounding_rect())
        for pt in shape.handles():
            r = r.united(QRectF(pt.x() - HANDLE / 2, pt.y() - HANDLE / 2, HANDLE, HANDLE))
        z = self.canvas.zoom
        a = self.canvas.mapToGlobal(QPointF(r.left() * z, r.top() * z))
        b = self.canvas.mapToGlobal(QPointF(r.right() * z, r.bottom() * z))
        return QRect(QPoint(int(a.x()) - 2, int(a.y()) - 2), QPoint(int(b.x()) + 2, int(b.y()) + 2))

    def context_menu_pos(self, shape, cursor: QPoint, size: QSize) -> QPoint:
        """Где открыть меню размером size: у объекта за его рамкой (place_menu), на пустом месте у курсора."""
        screen = QGuiApplication.screenAt(cursor) or self.screen() or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        if shape is None:
            return cursor
        handles = []
        z = self.canvas.zoom
        for pt in shape.handles():
            g = self.canvas.mapToGlobal(QPointF(pt.x() * z, pt.y() * z))
            handles.append(QPoint(int(g.x()), int(g.y())))
        return place_menu(self.selection_frame_global(shape), size, cursor, area, handles)

    def build_context_menu(self, shape) -> QMenu:
        """Меню правой кнопки: действия с объектом под курсором или со снимком целиком."""
        c = self.canvas
        menu = QMenu(self)
        style_menu(menu, self.ctx.config)
        if shape is None:
            menu.addAction(tr("editor.ctx_paste")).triggered.connect(self.paste_image)
            menu.addAction(tr("editor.ctx_paste_file")).triggered.connect(self.insert_from_file)
            menu.addAction(tr("editor.ctx_paste_capture")).triggered.connect(self.insert_screenshot)
            if self.ctx.config.get("ocr_enabled", True):
                menu.addSeparator()
                menu.addAction(tr("editor.ctx_ocr")).triggered.connect(lambda: self.select_tool(OCR))
            if self.ctx.config.get("translate_enabled", True):
                if not self.ctx.config.get("ocr_enabled", True):
                    menu.addSeparator()
                menu.addAction(tr("editor.ctx_translate_all")).triggered.connect(self.translate_all)
                menu.addAction(tr("editor.ctx_translate_sel")).triggered.connect(lambda: self.select_tool(TRANSLATE))
            menu.addSeparator()
            undo = menu.addAction(tr("editor.ctx_undo"))
            undo.setEnabled(bool(c.undo_stack))
            undo.triggered.connect(c.undo)
            redo = menu.addAction(tr("editor.ctx_redo"))
            redo.setEnabled(bool(c.redo_stack))
            redo.triggered.connect(c.redo)
            menu.addSeparator()
            menu.addAction(tr("editor.ctx_copy")).triggered.connect(self.copy_to_clipboard)
            menu.addAction(tr("editor.ctx_copy_close")).triggered.connect(self.copy_and_close)
            menu.addAction(tr("editor.ctx_save")).triggered.connect(self.save_and_close)
            menu.addSeparator()
            menu.addAction(tr("editor.ctx_settings")).triggered.connect(self.open_settings)
            return menu

        title = menu.addAction(_capital(tr(SHAPE_NAMES.get(shape.kind, "editor.shape_object"))))
        title.setEnabled(False)
        menu.addSeparator()
        colors = menu.addMenu(tr("editor.color"))
        style_menu(colors, self.ctx.config)
        for color in PALETTE:
            act = colors.addAction(_color_icon(color), color.upper())
            act.setCheckable(True)
            act.setChecked(shape.color.name().lower() == color)
            act.triggered.connect(lambda _c, col=color: self.select_color(col))
        for color in self.own_buttons:   # 1.32.1: свои цвета из «+»
            act = colors.addAction(_color_icon(color), color.upper())
            act.setCheckable(True)
            act.setChecked(shape.color.name().lower() == color)
            act.triggered.connect(lambda _c, col=color: self.select_color(col))
        colors.addSeparator()
        colors.addAction(tr("editor.ctx_other")).triggered.connect(self.pick_custom_color)
        if shape.kind != IMAGE:
            sizes = menu.addMenu(tr("editor.ctx_size") if shape.kind in (TEXT, CALLOUT, NUMBER) else tr("editor.ctx_thickness"))
            style_menu(sizes, self.ctx.config)
            for level in range(1, 6):
                act = sizes.addAction(icons.size_icon(level), f"{level}")
                act.setCheckable(True)
                act.setChecked(shape.size == level)
                act.triggered.connect(lambda _c, lv=level: self.select_size(lv))
        if shape.kind in (NUMBER, CALLOUT):
            text_colors = menu.addMenu(tr("editor.text_color"))
            style_menu(text_colors, self.ctx.config)
            auto = text_colors.addAction(tr("editor.ctx_auto"))
            auto.setCheckable(True)
            auto.setChecked(shape.text_color is None)
            auto.triggered.connect(lambda: self.select_text_color(None))
            for color in PALETTE:
                act = text_colors.addAction(_color_icon(color), color.upper())
                act.setCheckable(True)
                act.setChecked(shape.text_color is not None and shape.text_color.name().lower() == color)
                act.triggered.connect(lambda _c, col=color: self.select_text_color(col))
        if shape.kind in (RECT, ELLIPSE, FSHAPE):
            menu.addAction(tr("editor.ctx_unfill") if shape.filled else tr("editor.ctx_fill")).triggered.connect(c.toggle_fill_selected)
        if shape.kind in (TEXT, CALLOUT):
            menu.addAction(tr("editor.ctx_edit_text")).triggered.connect(lambda: c.edit_text(shape))
        if shape.erasures:
            menu.addAction(tr("editor.ctx_restore")).triggered.connect(c.restore_erased_selected)
        menu.addSeparator()
        menu.addAction(tr("editor.ctx_duplicate")).triggered.connect(c.duplicate_selected)
        menu.addAction(tr("editor.ctx_front")).triggered.connect(lambda: c.restack_selected(True))
        menu.addAction(tr("editor.ctx_back")).triggered.connect(lambda: c.restack_selected(False))
        menu.addSeparator()
        menu.addAction(tr("editor.ctx_delete")).triggered.connect(c.delete_selected)
        return menu

    def open_settings(self):
        if hasattr(self.ctx, "open_settings"):
            self.ctx.open_settings(self)

    def _redraw_demo(self):
        """Пример снимка знакомства (demo_maker задаёт app.demo_tour) рисует программа: при смене языка его подписи
        перерисовываются на новом языке. Пометки поверх остаются; обрезанный пример не трогается (другой размер)."""
        maker = getattr(self, "demo_maker", None)
        canvas = getattr(self, "canvas", None)
        if maker is None or canvas is None:
            return
        image = maker()
        if image.isNull() or logical_size(canvas.base) != logical_size(image):
            return
        canvas.base = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        canvas.base.setDevicePixelRatio(image.devicePixelRatio())
        canvas.update()

    def retranslate(self):
        """Язык сменён (1.31): панели и строки режимов строятся заново на новом языке в том же порядке, что в
        __init__; снимок, рисунки, отмена, инструмент и режим остаются (они живут в холсте)."""
        layout = self.content.layout()
        order = (("panel", self._build_panel), ("tr_top", self._build_tr_top), ("bottom", self._build_bottom),
                 ("tr_bottom", self._build_tr_bottom), ("text_top", getattr(self, "_build_text_top", None)),
                 ("text_bottom", getattr(self, "_build_text_bottom", None)),
                 ("crop_top", getattr(self, "_build_crop_top", None)))
        for attr, build in order:
            old = getattr(self, attr, None)
            if old is None or build is None:
                continue
            new = build()          # _build_bottom сам ставит self.bottom
            setattr(self, attr, new)
            i = layout.indexOf(old)
            layout.removeWidget(old)
            old.hide()
            old.deleteLater()
            layout.insertWidget(i, new)
        self.setWindowTitle(tr("editor.window_title"))
        self._redraw_demo()
        if self.titlebar is not None:
            self.titlebar.set_icons(self.top_icons)   # новая группа колокольчика, «?», шестерёнки и глобуса
        self._sync_bell()
        if self.titlebar is not None:   # подсказки шапки: Свернуть, Развернуть/Восстановить, Закрыть
            self.titlebar.min_button.setToolTip(tr("editor.minimize"))
            self.titlebar.close_button.setToolTip(tr("editor.close"))
            self.titlebar.set_maximized(self.isMaximized())
        if self._drag_filter is not None:
            for w in self._chrome_widgets():
                if w is not None:
                    w.installEventFilter(self._drag_filter)
            self._set_drag_cursors()
        tool = self.canvas.tool
        self._set_mode_ui(tool)
        if getattr(self, "tr_button", None) is not None:
            self.tr_button.setChecked(tool == TRANSLATE)
            self.tr_button.setText(self.TR_DONE_LABEL if tool == TRANSLATE else self.TR_SEL_LABEL)
        if getattr(self, "ocr_button", None) is not None:
            self.ocr_button.setChecked(tool == OCR)
            self.ocr_button.setText("  " + (self.OCR_LABEL_OFF if tool == OCR else self.OCR_LABEL_ON))
            self.text_mode_box.setVisible(tool == OCR)
        if tool == OCR:
            self.set_text_mode(self.ctx.config.get("ocr_select_mode", "range"))
        if hasattr(self, "eraser_box"):
            self.eraser_box.setVisible(tool == ERASER)
        if tool in self.tool_buttons:
            self.tool_buttons[tool].setChecked(True)
        self._sync_ocr()
        self._sync_controls()
        self._update_info()
        self.fit_size()

    def refresh_theme(self):
        """Применить оформление из настроек к уже открытому окну."""
        cfg = self.ctx.config
        icons.ICON_COLOR = theme(cfg)["icon"]
        SELECTED_BAR_COLOR[0] = theme(cfg)["ui_accent"]
        self.setStyleSheet(make_style(cfg))
        self.frame_px = theme(cfg)["ui_frame"]
        pal = palette(cfg)
        for sw in list(self.color_buttons.values()) + list(self.own_buttons.values()) + [self.custom_color]:
            sw.ring, sw.dark = QColor(pal["t"]), pal["dark"]
            sw.update()
        if self._pen_hint is not None:
            self._pen_hint.apply_theme(pal["dark"])
        self.bell_button.ring = QColor(pal["panel"])
        self.ocr_button.setIcon(icons.icon("ocr", soft_colors("ocr", pal["dark"])[1]))
        self.tr_all_button.setIcon(icons.icon("translate_all", soft_colors("tr", pal["dark"])[1]))
        # Вид рамки меняется сразу; «системный заголовок» действует только на новые окна: у открытого окна
        # он всегда такой, с каким окно создано (иначе пропадут скругления или появится поле тени)
        self.shell.apply(dict(chrome_params(cfg), system=self.system_title))
        # Значки перерисовать в цвете нового оформления
        for tool, button in self.tool_buttons.items():
            button.setIcon(icons.icon(tool))
        self._sync_groups()
        self.more_button.setIcon(icons.icon("more"))
        if getattr(self, "_bottom_compact", False):
            self.zoom_fit_button.setIcon(icons.icon("fit"))
        for button, name in ((self.undo_button, "undo"), (self.redo_button, "redo"),
                             (self.insert_button, "insert"), (self.help_button, "help"), (self.bell_button, "bell"),
                             (self.settings_button, "settings"), (self.language_button, "globe"),
                             (self.save_button, "save"),
                             (self.copy_button, "copy")):
            button.setIcon(icons.icon(name))
        for level in range(1, 6):
            self.size_group.button(level).setIcon(icons.size_icon(level))
        self._sync_ocr()
        self.fit_size()

    def _sync_ocr(self):
        """Распознавание выключено в настройках: кнопки инструмента нет, был выбран он — переходим на «Перемещение»."""
        enabled = self.ctx.config.get("ocr_enabled", True)
        tr_on = self.ctx.config.get("translate_enabled", True)
        if getattr(self, "tool_strip", None) is not None:
            self.tool_strip._sync_visibility()   # кнопки инструментов и группа «Текст с картинки» по настройкам
            self._sync_groups()
        compact = getattr(self, "_row2_compact", 0)
        if getattr(self, "ocr_button", None) is not None:
            self.ocr_button.setVisible(enabled and compact < 2)
        if getattr(self, "tr_block", None) is not None:
            self.tr_block.setVisible(tr_on and compact < 1)
        if hasattr(self, "_need_row1"):
            self._measure_rows()   # без распознавания или перевода ряды уже: ступени считаются заново
        if not tr_on and self.canvas.tool == TRANSLATE:
            self.select_tool(MOVE)
        if not enabled and self.canvas.tool == OCR:
            self.select_tool(MOVE)

    def toast_anchor(self):
        """Где лежат всплывающие плашки: область снимка; плашка стоит у её нижнего края, над строкой подсказки
        и нижней панелью, не закрывая «Подряд / Маркер» и кнопки."""
        return QRect(self.scroll.mapTo(self, QPoint(0, 0)), self.scroll.size())

    MODE_HINTS = dynamic(lambda self: {   # тексты читаются при обращении: язык меняется на ходу
        "range": tr("editor.mode_hint_range"),
        "marker": tr("editor.mode_hint_marker"),
        TRANSLATE: tr("editor.mode_hint_translate"),
    })

    TR_ALL_HINTS = dynamic(lambda self: {"busy": tr("editor.tr_all_busy"), "done": tr("editor.tr_all_done")})

    def _tr_message_text(self) -> str:
        """Сообщение бирюзовой полосы: что идёт, что переведено, сколько оставлено как есть (уже на русском)."""
        layer = getattr(self, "tr_layer", None)
        state = layer._tr_full_exists() if layer is not None else None
        if state == "busy":
            return self.TR_ALL_HINTS["busy"]
        errors = [c for c in layer.all_cards() if c.state == "error"] if layer is not None else []
        if errors:
            return tr("editor.tr_failed", error=errors[-1].message or tr("editor.tr_failed_fallback"))
        m, n, k, partial = layer.stats() if layer is not None else (0, 0, 0, False)
        if not (m or n or partial):
            return self.TR_ALL_HINTS["done"] if state == "done" else self.MODE_HINTS[TRANSLATE]
        from types import SimpleNamespace
        from .translate_ui import TranslateMixin
        text = TranslateMixin._tr_partial_text(SimpleNamespace(blocks=[0] * m, skipped=n, total=k, partial=partial))
        if not (n or partial):
            text = self.TR_ALL_HINTS["done"] if state == "done" else tr("editor.tr_partial_orig", text=text)
        return text

    def _sync_tr_controls(self):
        """Переключатели нижней полосы показывают то, что включено сейчас."""
        layer = getattr(self, "tr_layer", None)
        if layer is None:
            return
        from .translate import lang_name, target_lang
        cards = [c for c in layer.all_cards() if c.state == "done" and c.blocks]
        src = ""
        if cards:
            src = lang_name(cards[-1].blocks[0]["src"]) if cards[-1].blocks[0]["src"] else ""
        tgt = lang_name(target_lang(self.ctx.config))
        self.tr_lang_button.setText(tr("editor.tr_lang_from_to", src=src, lang=tgt) if src else tr("editor.tr_lang_to", lang=tgt))
        orig = layer.showing_original()
        self.tr_show_orig.setChecked(orig)
        self.tr_show_tr.setChecked(not orig)
        card_view = layer._tr_view_default() == "card"
        self.tr_view_card.setChecked(card_view)
        self.tr_view_overlay.setChecked(not card_view)

    def _update_info(self):
        size = f"{self.canvas.base.width()} × {self.canvas.base.height()} px"
        if getattr(self, "crop_ok_button", None) is not None:
            self.crop_ok_button.setEnabled(self.canvas.crop_pending)   # «Обрезать» доступно, когда есть рамка
            self.crop_top.findChild(QLabel, "trSub").setText(
                tr("editor.hint_crop_pending") if self.canvas.crop_pending else tr("editor.hint_crop"))
        self.mode_hint.setVisible(False)   # 1.29.1: сообщения режимов живут в цветных полосах внизу (text_bottom, tr_bottom)
        if self.canvas.tool == TRANSLATE:
            self.info.setText(size)
            text = self._tr_message_text()
            self.mode_hint.setText(text)
            self.tr_message.setText(text)
            self._sync_tr_controls()
            try:
                from . import translate
                usage = translate.usage_line(self.ctx.config)
            except Exception:   # noqa: BLE001
                usage = ""
            self.tr_message.setToolTip(tr("editor.tr_message_tip") + "\n" + usage)
            self.info.setToolTip("")
            return
        if self.canvas.tool == OCR:
            self.info.setText("")   # внизу тесно из-за «Подряд / Маркер»: размер снимка не нужен, подсказка над панелью
            self.mode_hint.setText(self.MODE_HINTS["marker" if self.canvas.text_mode == "marker" else "range"])
            self.text_message.setText(self.mode_hint.text())
            self.mode_hint.setToolTip(tr("editor.mode_hint_tip"))
            self.info.setToolTip("")
            return
        if self.canvas.crop_pending:
            self.info.setText(tr("editor.crop_info"))   # подробности в строке режима сверху и во всплывающей подсказке: нижняя строка узкая
            self.info.setToolTip(tr("editor.crop_tip", size=size))
            return
        shape = self.canvas.selected if self.canvas.editing_object() else None
        if shape is None:
            self.info.setText(size)
            self.info.setToolTip("")
            return
        name = tr(SHAPE_NAMES.get(shape.kind, "editor.shape_object"))
        self.info.setText(tr("editor.selected_info", name=name))
        self.info.setToolTip(tr("editor.selected_tip", size=size, name=name))

    # --- масштаб вида --------------------------------------------------------

    ZOOM_STEPS = (0.1, 0.15, 0.2, 0.25, 0.33, 0.5, 0.67, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0)

    def set_zoom(self, zoom: float, anchor=None, fit=False):
        """Масштаб вида. anchor: глобальная точка (QPointF), которая остаётся на месте; без неё центр окна."""
        canvas = self.canvas
        zoom = max(canvas.ZOOM_MIN, min(canvas.ZOOM_MAX, zoom))
        self._zoom_fit_mode = fit
        viewport = self.scroll.viewport()
        if anchor is not None:
            view_pt = viewport.mapFromGlobal(anchor.toPoint())
        else:
            view_pt = QPoint(viewport.width() // 2, viewport.height() // 2)
        old = canvas.zoom
        logical = QPointF(canvas.mapFrom(viewport, view_pt)) / old
        canvas.set_zoom(zoom)
        self.zoom_label.setText(f"{round(canvas.zoom * 100)}%")
        if abs(canvas.zoom - old) < 1e-6:
            return
        self.image_frame.adjustSize()

        def keep_point():
            top_left = canvas.mapTo(self.scroll.widget(), QPoint(0, 0))
            self.scroll.horizontalScrollBar().setValue(round(top_left.x() + logical.x() * canvas.zoom - view_pt.x()))
            self.scroll.verticalScrollBar().setValue(round(top_left.y() + logical.y() * canvas.zoom - view_pt.y()))
        QTimer.singleShot(0, keep_point)   # после пересчёта полос прокрутки

    def zoom_by(self, factor: float, anchor=None):
        self.set_zoom(self.canvas.zoom * factor, anchor)

    def zoom_step(self, direction: int):
        """Кнопки и клавиши: ближайший шаг из ряда 10%…800%."""
        cur = self.canvas.zoom
        if direction > 0:
            nxt = next((z for z in self.ZOOM_STEPS if z > cur + 1e-6), self.ZOOM_STEPS[-1])
        else:
            nxt = next((z for z in reversed(self.ZOOM_STEPS) if z < cur - 1e-6), self.ZOOM_STEPS[0])
        self.set_zoom(nxt)

    def zoom_fit(self):
        """Весь снимок в окне, но не крупнее 100%."""
        vp = self.scroll.viewport().size()
        w, h = self.canvas.lw() + 2 * FRAME_WIDTH + 6, self.canvas.lh() + 2 * FRAME_WIDTH + 6
        self.set_zoom(min(1.0, vp.width() / w, vp.height() / h), fit=True)

    def _auto_fit(self):
        """Снимок больше окна (например, два монитора сразу): сразу показываем целиком."""
        vp = self.scroll.viewport().size()
        if self.canvas.lw() + 2 * FRAME_WIDTH > vp.width() or self.canvas.lh() + 2 * FRAME_WIDTH > vp.height():
            self.zoom_fit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._adapt_rows()   # 1.32: группы, большие кнопки второго ряда и подписи внизу по ширине окна
        self._place_pen_hint()
        if getattr(self, "_zoom_fit_mode", False):
            QTimer.singleShot(0, self.zoom_fit)

    def _canvas_resized(self):
        if getattr(self, "tr_layer", None) is not None:
            self.tr_layer.clear()   # снимок изменился (обрезка, отмена): старые переводы уже не на своём месте
        if self.canvas.tool == OCR and not self.canvas.has_words():
            QTimer.singleShot(0, self.start_text_mode)   # снимок изменился (отмена, вставка): распознать заново
        self.image_frame.adjustSize()
        self._update_info()
        self.fit_size()

    # --- размер и положение окна -------------------------------------------

    def _screen_area(self) -> QRect:
        point = self.origin if self.origin is not None else self.geometry().center()
        screen = QGuiApplication.screenAt(point) or QGuiApplication.primaryScreen()
        return screen.availableGeometry()

    def fit_size(self):
        """Окно = снимок в рамке + панели (1.32): по ширине снимка, но не уже самого узкого вида панелей
        (группы свёрнуты, второй ряд без больших кнопок, внизу значки) и не больше экрана."""
        area = self._screen_area()
        rim_w, rim_h = self._rim()
        self._measure_rows()
        min_w = self.min_content_width() + rim_w
        image_w = self.canvas.lw() + 2 * FRAME_WIDTH + rim_w      # размер окна считается по снимку 100%, масштаб вида его не меняет
        image_h = self.canvas.lh() + 2 * FRAME_WIDTH + rim_h
        want_w = min(max(image_w, min_w), area.width() - 20)
        self._adapt_rows(want_w - rim_w)
        self.panel.layout().activate()
        bars_h = self.panel.sizeHint().height() + self.bottom.sizeHint().height()
        want_h = image_h + bars_h
        self.setMinimumWidth(min(min_w, area.width() - 20))
        self.resize(want_w, min(want_h, area.height() - 40))

    def _rim(self):
        """Сколько окно занимает сверх панелей и снимка: (по ширине, по высоте): поля тени, рамка, своя шапка."""
        m = self.shell.outer() + self.shell.inner()
        title = (TITLE_H + 1) if self.titlebar is not None else 0
        return 2 * m, 2 * m + title

    def minimize_window(self):
        self.showMinimized()

    def toggle_maximized(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and getattr(self, "shell", None) is not None:
            layer = getattr(self, "tr_layer", None)
            if layer is not None:
                layer.set_floats_visible(not self.isMinimized())   # окошки перевода уходят вместе с редактором
            self.shell.apply()   # развёрнутое окно: без скруглений, тени и полей
            self._sync_frame_extents()
            self._set_drag_containers()
            if self.titlebar is not None:
                self.titlebar.set_maximized(self.isMaximized())

    def frame_extents_margins(self):
        """Поля под тень в логических точках (слева, справа, сверху, снизу); нули: развёрнутое окно или системный заголовок."""
        o = self.shell.outer()
        return (o, o, o, o)

    def _sync_frame_extents(self):
        """Менеджеру окон (X11): видимая часть окна без прозрачного поля тени, чтобы рамка активного окна,
        привязка к краям и снимки окна шли по карточке, а не по невидимому полю."""
        if getattr(self, "shell", None) is None:
            return
        track_frame_extents(self, self.frame_extents_margins)   # заодно пересчёт при переходе на другой экран

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_frame_extents()

    def present(self):
        self.show()
        self.raise_()
        self.activateWindow()
        force_foreground(self)   # Windows: иначе клавиши редактора уходят в прежнее окно
        self.canvas.setFocus()
        QTimer.singleShot(0, self._auto_fit)
        QTimer.singleShot(60, self._align_to_origin)

    def _align_to_origin(self):
        """Ставим окно так, чтобы картинка легла ровно на снятую область, но не вылезла за экран."""
        area = self._screen_area()
        frame = self.frameGeometry()
        if self.origin is not None:
            delta = self.origin - self.canvas.mapToGlobal(QPoint(0, 0))
            frame.translate(delta)
        else:
            frame.moveCenter(area.center())
        frame.moveLeft(max(area.left(), min(frame.left(), area.right() - frame.width())))
        frame.moveTop(max(area.top(), min(frame.top(), area.bottom() - frame.height())))
        self.move(frame.topLeft())

    # --- действия ------------------------------------------------------------

    def _update_autosave(self, image: QImage):
        """Снимок уже сохранён автоматически: после правок файл обновляется готовой картинкой."""
        path = getattr(self, "autosave_path", None)
        if path and self.canvas.modified:
            hidpi.save_image(image, path, self.ctx.config)

    def copy_shortcut(self):
        """Ctrl+C: в режиме текста копирует выделенный текст, иначе снимок."""
        if self.canvas.tool == OCR:
            self.copy_selected_text()
        else:
            self.copy_to_clipboard()

    def select_all_shortcut(self):
        if self.canvas.tool == OCR:
            self.canvas.select_all_text()

    def copy_to_clipboard(self):
        """Скопировать снимок с пометками; окно остаётся открытым, всплывает сообщение."""
        image = self.canvas.render()
        self.ctx.copy_image(image)
        self._update_autosave(image)
        self.exported = True          # без новых правок окно закроется без вопроса
        self.show_toast(tr("editor.copied_toast"))

    def copy_and_close(self):
        image = self.canvas.render()
        self.ctx.copy_image(image)
        self._update_autosave(image)
        self.exported = True
        self.close()

    def show_toast(self, text: str, ms: int = None):
        """Всплывающая плашка (появляется и гаснет) у нижнего края области снимка."""
        from . import ocr
        self.toast = ocr.toast(self, text, ms)

    def _canvas_changed(self):
        self.exported = False

    def save_and_close(self):
        image = self.canvas.render()
        path = ask_save_path(self, self.ctx.config)
        if not path:
            return
        if not hidpi.save_image(image, path, self.ctx.config):
            from .dialogs import MessageCard
            card = MessageCard(self, tr("editor.error"), tr("editor.save_error", path=path), "error")
            card.exec()
            return
        self.ctx.config["save_dir"] = os.path.dirname(path)
        self.ctx.notify(tr("editor.saved", path=path))
        self.exported = True
        self.close()

    def closeEvent(self, event):
        if self.canvas.text_edit is not None:
            self.canvas.cancel_text()
            event.ignore()
            return
        if self.canvas.modified and not self.exported:
            dialog = ConfirmDialog(self, tr("editor.unsaved_title"), tr("editor.unsaved_text"),
                                   tr("editor.unsaved_discard"), tr("editor.save"), default_yes=False)
            answer = dialog.exec()
            if answer == ConfirmDialog.NO:
                event.ignore()
                QTimer.singleShot(0, self.save_and_close)   # если в окне сохранения нажать «Отмена» — редактор останется
                return
            if answer != ConfirmDialog.YES:
                event.ignore()
                return
        self.ctx.save_config()
        self._remove_key_filter()
        layer = getattr(self, "tr_layer", None)
        if layer is not None:
            layer.shutdown()   # перевод и вопрос про лимит отменяются, окошки закрываются вместе с редактором
        self.closed.emit(self)
        event.accept()
