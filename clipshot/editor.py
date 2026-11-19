# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
"""Окно редактирования снимка: открывается в размер скриншота на месте снятой области."""

import datetime
import os
import sys

from PyQt6.QtCore import QEvent, QKeyCombination, QMimeData, QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (QColor, QContextMenuEvent, QDrag, QFontMetricsF, QPolygonF, QGuiApplication, QIcon, QImage, QKeySequence, QPainter, QPainterPath, QPen,
                         QPixmap, QShortcut)
from PyQt6.QtWidgets import (QAbstractSpinBox, QKeySequenceEdit, QLineEdit, QTextEdit,
                             QApplication, QButtonGroup, QColorDialog, QDialog, QFileDialog, QFrame, QGraphicsDropShadowEffect,
                             QGridLayout, QHBoxLayout, QLabel, QMainWindow, QMenu, QWidgetAction,
                             QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QToolButton,
                             QVBoxLayout,
                             QWidget)

from . import icons
from .dialogs import ClipDialog
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
TOOLS = [
    (MOVE, "", "editor.tip_move", "V"),
    (CALLOUT, "", "editor.tip_callout", "K"),
    (TEXT, "", "editor.tip_text", "T"),
    (NUMBER, "", "editor.tip_number", "N"),
    (ARROW, "", "editor.tip_arrow", "A"),
    (DARROW, "", "editor.tip_darrow", "D"),
    (FARROW, "", "editor.tip_farrow", "F"),
    (FLINE, "", "editor.tip_fline", "G"),
    (LINE, "", "editor.tip_line", "L"),
    (RECT, "", "editor.tip_rect", "R"),
    (ELLIPSE, "", "editor.tip_ellipse", "E"),
    (FSHAPE, "", "editor.tip_fshape", "O"),
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
        """Выделен объект: кнопки цвета и толщины меняют только его, общие настройки не трогаются."""
        return self.selected is not None and self.selected in self.shapes and self.tool != ERASER

    def set_color(self, color):
        if self.editing_object():
            if self.selected.color != QColor(color):
                self.push_undo()
                self.selected.color = QColor(color)
                self.update()
            return
        self.color = QColor(color)
        if self.text_edit is not None:
            self._style_text_edit()

    def set_text_color(self, color):
        """color — QColor или None (авто). Выделен номер/сноска — меняется только он, иначе общий выбор."""
        new = QColor(color) if color is not None else None
        if self.editing_object():
            shape = self.selected
            if shape.kind in (NUMBER, CALLOUT) and shape.text_color != new:
                self.push_undo()
                shape.text_color = new
                self.update()
            return
        self.text_color = new
        if self.text_edit is not None:
            self._style_text_edit()
            self.update()

    def set_size(self, size):
        if self.tool == ERASER:          # при ластике кнопки толщины задают размер кисти
            self.eraser_size = size
            self.update()
            return
        if self.editing_object():
            if self.selected.size != size:
                self.push_undo()
                self.selected.size = size
                self.update()
            return
        self.pen_size = size
        if self.text_edit is not None:
            self.text_edit.setFont(self._edit_font(size))
            self._fit_text_edit()

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
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self.zoom != 1.0)
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
        if self.tool != MOVE and self.selected is not None and self.selected.hit(pos):
            # Только что нарисованный (выделенный) объект можно двигать любым инструментом.
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
            self.select(None)
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
        if self.current is not None:
            shape, self.current = self.current, None
            if shape.kind == CALLOUT:
                self._start_callout(shape)
            elif not shape.is_empty():
                if shape.kind in SMOOTHED_KINDS:
                    shape.points = simplify(shape.points, max(6.0, shape.pen_width * 1.2))   # дрожание руки до ~6 px
                self.push_undo()
                self.shapes.append(shape)
                self.select(shape)   # сразу можно поправить толщину, цвет, тянуть за ручки
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
        if shape is not None:
            if original is None:
                self.push_undo()
            self.shapes.append(shape)
            self.select(shape)
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
TITLE_H = 38      # своя шапка окна
GRAB = 8          # ширина зоны захвата края окна для изменения размера, px
FRAME_STYLE_KEYS = (("glow", "editor.frame_glow"), ("thick", "editor.frame_thick"), ("plain", "editor.frame_plain"))


def __getattr__(name):
    """FRAME_STYLES: пары (код, надпись) на текущем языке; считаются при обращении, не при импорте."""
    if name == "FRAME_STYLES":
        return tuple((code, tr(key)) for code, key in FRAME_STYLE_KEYS)
    raise AttributeError(name)

# Оформление по умолчанию; меняется в настройках (раздел «Оформление»).
THEME_DEFAULTS = {"ui_accent": ACCENT, "ui_panel": "#d9dbdf", "ui_field": "#3a3d42", "ui_frame": BORDER}


def theme(cfg) -> dict:
    from . import themes
    return themes.tokens(cfg)


def frame_style(cfg) -> str:
    """Вид рамки окна: glow (тонкая линия со свечением), thick (толстая скруглённая), plain (без цветной рамки)."""
    value = (cfg or {}).get("editor_frame_style", "glow")
    return value if value in dict(FRAME_STYLE_KEYS) else "glow"


def chrome_params(cfg) -> dict:
    """Всё, что нужно для рисования рамки окна редактора: вид, цвета, толщина линии и ореола."""
    t = theme(cfg)
    accent, panel = QColor(t["ui_accent"]), QColor(t["ui_panel"])
    dark = panel.lightnessF() < 0.45
    fill = panel.lighter(104 if dark else 106)
    style = frame_style(cfg)
    px = int(t["ui_frame"])
    if style == "glow":
        line = 2 if px <= 4 else (3 if px <= 8 else 4)   # тонкая линия: 2-4 px по настройке «Толщина рамки»
        halo = line + 4
        color = QColor(accent)
    elif style == "thick":
        line, halo, color = px, 0, QColor(accent)
    else:
        line, halo = 1, 0
        color = QColor(255, 255, 255, 70) if dark else QColor(0, 0, 0, 46)   # нейтральная тонкая обводка
    return {"style": style, "dark": dark, "fill": fill, "line": line, "halo": halo, "color": color,
            "accent": accent, "system": bool(cfg.get("editor_system_title", False))}


def make_style(cfg) -> str:
    """Стиль окна редактора из выбранного оформления и своих цветов (акцент, панели, поле вокруг снимка)."""
    t = theme(cfg)
    accent, panel, field = QColor(t["ui_accent"]), QColor(t["ui_panel"]), QColor(t["ui_field"])
    a, a_light, a_dark = accent.name(), accent.lighter(130).name(), accent.darker(135).name()
    dark = panel.lightnessF() < 0.45
    fill = chrome_params(cfg)["fill"]
    if dark:
        a_hover = t["button_hover"]
        line, sep = fill.lighter(140).name(), fill.lighter(150).name()
    else:
        a_hover = QColor.fromHsl(accent.hslHue(), max(0, accent.hslSaturation() // 3), 215).name()
        line, sep = fill.darker(112).name(), fill.darker(122).name()
    a_soft = f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, {70 if dark else 55})"   # полупрозрачная заливка выбранного
    p = fill.name()
    info = t["text_dim"] if dark else "#3d4046"
    stage = field.lighter(125).name()
    return f"""
QMainWindow {{ background: transparent; }}
#panel, #bottom, #titlebar, #modeHint {{ background: transparent; color: {t['text']}; }}
#panel {{ border-bottom: 1px solid {line}; }}
#bottom {{ border-top: 1px solid {line}; }}
QToolButton {{ color: {t['button_text']}; }}
QToolButton#tool, QToolButton#size, QToolButton#action {{
    border: 1px solid transparent; border-radius: 8px; padding: 3px; background: transparent; }}
QToolButton#tool:hover, QToolButton#size:hover, QToolButton#action:hover {{
    background: {a_hover}; border-color: {line}; }}
QToolButton#tool:checked, QToolButton#size:checked {{
    background: {a_soft}; border: 1px solid {a}; }}
QToolButton#swatch {{ border: 1px solid #8a8a8a; border-radius: 6px; }}
QToolButton#swatch:checked {{ border: 3px solid {t['swatch_check']}; }}
QFrame#sep {{ background: {sep}; }}
QScrollArea, #stage {{ background: {stage}; border: none; }}
#imageFrame {{ background: {t['image_frame']}; }}
QPushButton {{ min-height: 30px; padding: 0 14px; border-radius: 8px; font-size: {t['font']}px;
    border: 1px solid {t['button_border']}; background: {t['button_bg']}; color: {t['button_text']}; }}
QPushButton:hover {{ background: {t['button_hover']}; border-color: {a if dark else '#9fb6da'}; }}
QPushButton#primary {{ background: {a}; color: white; border: 1px solid {a_dark}; font-weight: bold; }}
QPushButton#primary:hover {{ background: {a_light}; }}
QPushButton#finish {{ min-height: 38px; padding: 0 20px; font-size: {t['font'] + 1}px; font-weight: bold; color: white;
    background: #1f9d55; border: 1px solid #157a40; }}
QPushButton#finish:hover {{ background: #26b864; border-color: #1f9d55; }}
QPushButton#finish:pressed {{ background: #157a40; }}
QLabel#info {{ color: {info}; font-size: {t['font'] - 1}px; background: transparent; }}
QLabel#winTitle {{ color: {t['text']}; font-weight: bold; font-size: {t['font']}px; background: transparent; }}
QLabel#modeHint {{ color: {t['text']}; font-size: {max(15, t['font'] + 1)}px; padding: 10px 12px;
    border-top: 1px solid {line}; }}
#trTop {{ background: {'#12302d' if dark else '#eaf7f5'}; color: {t['text']}; border-bottom: 2px solid #0b8f84; }}
#trTop[mode="text"] {{ background: {'#2a1d4a' if dark else '#f3edff'}; border-bottom: 2px solid #7c3aed; }}
#trTop[mode="crop"] {{ background: {'#16301f' if dark else '#eaf7ee'}; border-bottom: 2px solid #1f9d55; }}
QLabel#trTitle {{ color: {t['text']}; font-weight: bold; font-size: {t['font'] + 5}px; background: transparent; }}
QLabel#trSub {{ color: {info}; font-size: {t['font'] - 1}px; background: transparent; }}
QPushButton#modeDone, QPushButton#modeMain {{ min-height: 38px; min-width: 130px; padding: 0 18px; font-size: {t['font'] + 2}px;
    font-weight: bold; color: white; background: #0d9488; border: 1px solid #0b766c; border-radius: 8px; }}
QPushButton#modeDone:hover, QPushButton#modeMain:hover {{ background: #14b8a6; }}
QPushButton#modeDone[mode="text"], QPushButton#modeMain[mode="text"] {{ background: #7c3aed; border: 1px solid #5b21b6; }}
QPushButton#modeDone[mode="text"]:hover {{ background: #8f55f5; }}
QPushButton#modeDone[mode="crop"] {{ background: {t['button_bg']}; color: {t['button_text']}; border: 1px solid {t['button_border']}; }}
QPushButton#modeMain[mode="crop"] {{ background: #1f9d55; border: 1px solid #157a40; }}
QPushButton#modeMain[mode="crop"]:hover {{ background: #26b864; }}
QPushButton#modeMain:disabled {{ background: {t['button_bg']}; color: {info}; border: 1px solid {t['button_border']}; }}
#textBottom {{ background: {'#2a1d4a' if dark else '#f3edff'}; border-top: 2px solid #7c3aed; }}
QLabel#textMessage {{ color: {'#d9c8ff' if dark else '#3b1a7a'}; font-size: {max(15, t['font'] + 1)}px; background: transparent; }}
QPushButton#textCopySel {{ min-height: 30px; padding: 0 14px; font-weight: bold; color: {'#d9c8ff' if dark else '#3b1a7a'};
    background: {t['button_bg'] if dark else '#ffffff'}; border: 1px solid #7c3aed; }}
QPushButton#textCopyAll {{ min-height: 30px; padding: 0 14px; font-weight: bold; color: white; background: #7c3aed; border: 1px solid #5b21b6; }}
QPushButton#textCopyAll:hover {{ background: #8f55f5; }}
#trBottom {{ background: {'#12302d' if dark else '#eaf7f5'}; border-top: 2px solid #0b8f84; }}
QLabel#trMessage {{ color: {'#a7ece4' if dark else '#0b5f57'}; font-size: {t['font']}px; background: transparent; }}
QPushButton#trLang, QPushButton#trSegL, QPushButton#trSegR {{ min-height: 30px; padding: 0 12px; font-weight: bold;
    color: {'#a7ece4' if dark else '#0b5f57'}; background: {t['button_bg'] if dark else '#ffffff'}; border: 1px solid #0b8f84; }}
QPushButton#trSegL {{ border-top-right-radius: 0px; border-bottom-right-radius: 0px; }}
QPushButton#trSegR {{ border-top-left-radius: 0px; border-bottom-left-radius: 0px; border-left: none; }}
QPushButton#trSegL:checked, QPushButton#trSegR:checked {{ background: #0d9488; color: white; }}
QPushButton#trCopy {{ min-height: 30px; padding: 0 14px; font-weight: bold; color: white; background: #0d9488;
    border: 1px solid #0b766c; }}
QPushButton#trCopy:hover {{ background: #14b8a6; }}
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
        self.min_button = WinButton("min", tr("editor.minimize"))
        self.max_button = WinButton("max", tr("editor.maximize"))
        self.close_button = WinButton("close", tr("editor.close"))
        self.min_button.clicked.connect(window.minimize_window)
        self.max_button.clicked.connect(window.toggle_maximized)
        self.close_button.clicked.connect(window.close)   # тот же путь, что у прежнего закрытия: вопрос «Снимок не сохранён»
        for b in (self.min_button, self.max_button, self.close_button):
            row.addWidget(b)

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
        return RADIUS if self.outer() else 0

    def inner(self) -> int:
        """Отступ содержимого внутри карточки: рамка и (в системном окне) внутренний ореол."""
        p = self.params
        if self.custom() and self.maximized():
            return 0
        extra = p["halo"] if not self.custom() else 0
        return p["line"] + extra + (1 if p["style"] != "plain" else 0)

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
        near = max(2, int(self.params["line"]))   # внутрь карточки только сама линия рамки: шапка целиком отдана переносу
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


class DraggableToolButton(QToolButton):
    """Кнопка инструмента: клик выбирает, перетаскивание переставляет её в строке."""

    def __init__(self, tool):
        super().__init__()
        self.tool = tool
        self._press = None
        self.default_mark = False   # зелёная галочка: это инструмент по умолчанию

    def set_default_mark(self, on: bool):
        if on != self.default_mark:
            self.default_mark = on
            self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.default_mark:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        d = 13
        r = QRectF(self.width() - d - 2, self.height() - d - 2, d, d)
        p.setPen(QPen(QColor("#ffffff"), 1.5))
        p.setBrush(QColor("#1f9d55"))
        p.drawEllipse(r)
        p.setPen(QPen(QColor("#ffffff"), 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPolyline(QPolygonF([QPointF(r.left() + d * 0.27, r.top() + d * 0.53), QPointF(r.left() + d * 0.43, r.top() + d * 0.69),
                                  QPointF(r.left() + d * 0.75, r.top() + d * 0.32)]))
        p.end()

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
            mime.setData(TOOL_MIME, self.tool.encode())
            drag.setMimeData(mime)
            drag.setPixmap(self.grab())
            drag.setHotSpot(QPoint(self.width() // 2, self.height() // 2))
            drag.exec(Qt.DropAction.MoveAction)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._press = None
        super().mouseReleaseEvent(event)


class ToolStrip(QWidget):
    """Строка инструментов, порядок которой меняется перетаскиванием. order_changed(список инструментов)."""

    order_changed = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(2)
        self.drop_x = None
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def buttons(self):
        return [self.row.itemAt(i).widget() for i in range(self.row.count())]

    def order(self):
        return [b.tool for b in self.buttons()]

    def index_at(self, x: int) -> int:
        """Куда встанет кнопка, если отпустить её в точке x."""
        for i, button in enumerate(self.buttons()):
            if x < button.geometry().center().x():
                return i
        return len(self.buttons())

    def move_tool(self, tool, index):
        button = next(b for b in self.buttons() if b.tool == tool)
        old = self.buttons().index(button)
        if index > old:
            index -= 1
        if index == old:
            return
        self.row.removeWidget(button)
        self.row.insertWidget(index, button)
        self.order_changed.emit(self.order())

    def set_order(self, order):
        buttons = {b.tool: b for b in self.buttons()}
        for button in buttons.values():
            self.row.removeWidget(button)
        for tool in order:
            self.row.addWidget(buttons[tool])
        self.order_changed.emit(self.order())

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(TOOL_MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(TOOL_MIME):
            index = self.index_at(int(event.position().x()))
            buttons = self.buttons()
            self.drop_x = (buttons[index].geometry().left() - 2 if index < len(buttons)
                           else buttons[-1].geometry().right() + 2)
            self.update()
            event.acceptProposedAction()

    def dragLeaveEvent(self, _event):
        self.drop_x = None
        self.update()

    def dropEvent(self, event):
        tool = bytes(event.mimeData().data(TOOL_MIME)).decode()
        self.drop_x = None
        self.update()
        if tool in self.order():
            self.move_tool(tool, self.index_at(int(event.position().x())))
            event.acceptProposedAction()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.drop_x is not None:
            p = QPainter(self)
            p.fillRect(QRect(self.drop_x - 1, 2, 3, self.height() - 4), QColor(ACCENT))
            p.end()


def tool_order(cfg) -> list:
    """Порядок инструментов из настроек: неизвестные отбрасываются, новые добавляются в конец."""
    standard = [t for t, _g, _tip, _k in TOOLS]
    saved = [t for t in (cfg.get("tool_order") or []) if t in standard]
    return saved + [t for t in standard if t not in saved]


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
            self._drag_filter = DragFilter(self)
            for w in self._chrome_widgets():
                w.installEventFilter(self._drag_filter)
            self._set_drag_cursors()
        self.shell.layout_.addWidget(content, 1)
        self.setCentralWidget(self.shell)

        self._build_shortcuts()
        self._sync_ocr()
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
        self.tool_group = QButtonGroup(self)
        self.tool_buttons = {}
        self.tool_strip = ToolStrip()
        tips = {tool: tip for tool, _glyph, tip, _key in TOOLS}
        for tool in tool_order(self.ctx.config):
            button = DraggableToolButton(tool)
            self._style_tool_button(button, icons.icon(tool), self._tool_tip(tool))
            button.setChecked(tool == self.canvas.tool)
            button.clicked.connect(lambda _c, t=tool: self.select_tool(t))
            self.tool_group.addButton(button)
            self.tool_buttons[tool] = button
            self.tool_strip.row.addWidget(button)
        self.tool_strip.order_changed.connect(self._save_tool_order)
        self.tool_strip.customContextMenuRequested.connect(self._tool_strip_menu)
        self._sync_default_tool()
        row1.addWidget(self.tool_strip)
        row1.addSpacing(6)
        row1.addWidget(_separator())
        row1.addSpacing(6)
        undo = self._tool_button(icons.icon("undo"), tr("editor.undo_tip"), "action", False)
        self.undo_button = undo
        undo.clicked.connect(self.canvas.undo)
        redo = self._tool_button(icons.icon("redo"), tr("editor.redo_tip"), "action", False)
        self.redo_button = redo
        redo.clicked.connect(self.canvas.redo)
        row1.addWidget(undo)
        row1.addWidget(redo)
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
        row1.addStretch(1)
        help_button = self._tool_button(icons.icon("help"), tr("editor.help_tip"),
                                        "action", False)
        help_button.clicked.connect(self.start_tour)
        self.help_button = help_button
        row1.addWidget(help_button)
        settings = self._tool_button(icons.icon("settings"), tr("editor.settings_tip"), "action", False)
        self.settings_button = settings
        settings.clicked.connect(self.open_settings)
        row1.addWidget(settings)
        from . import language   # 1.31: глобус рядом с «?» и шестерёнкой, подменю языков на самих себе
        globe = self._tool_button(icons.icon("globe"), language.menu_title(), "action", False)
        globe.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        globe.setMenu(language.make_menu(self.ctx, globe))
        self.language_button = globe
        row1.addWidget(globe)
        rows.addLayout(row1)

        # Ряд 2: цвета | толщина
        row2 = QHBoxLayout()
        row2.setSpacing(4)
        self.color_group = QButtonGroup(self)
        self.color_buttons = {}
        current = self.canvas.color.name().lower()
        for color in PALETTE:
            swatch = QToolButton()
            swatch.setObjectName("swatch")
            swatch.setCheckable(True)
            swatch.setFixedSize(26, 26)
            swatch.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            swatch.setToolTip(color.upper())
            swatch.setStyleSheet(f"QToolButton#swatch {{ background: {color}; }}")
            swatch.setChecked(color == current)
            swatch.clicked.connect(lambda _c, col=color: self.select_color(col))
            self.color_group.addButton(swatch)
            self.color_buttons[color] = swatch
            row2.addWidget(swatch)
        self.custom_color = QToolButton()
        self.custom_color.setObjectName("swatch")
        self.custom_color.setCheckable(True)
        self.custom_color.setFixedSize(26, 26)
        self.custom_color.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.custom_color.setText("+")
        self.custom_color.setToolTip(tr("editor.other_color"))
        self.custom_color.clicked.connect(self.pick_custom_color)
        self.color_group.addButton(self.custom_color)
        row2.addWidget(self.custom_color)
        if current not in self.color_buttons:
            self._show_custom(current)
        row2.addSpacing(6)
        row2.addWidget(_separator())
        row2.addSpacing(6)
        row2.addWidget(self._build_text_color_button())
        row2.addSpacing(6)
        row2.addWidget(_separator())
        row2.addSpacing(6)
        self.size_group = QButtonGroup(self)
        for level in range(1, 6):
            button = self._tool_button(icons.size_icon(level), tr("editor.size_tip", level=level),
                                       "size")
            button.setFixedSize(34, 30)
            button.setChecked(level == self.canvas.pen_size)
            button.clicked.connect(lambda _c, lv=level: self.select_size(lv))
            self.size_group.addButton(button, level)
            row2.addWidget(button)
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
        for button, width in ((zoom_out, 34), (self.zoom_label, 60), (zoom_in, 34),
                               (zoom_fit, max(84, zoom_fit.fontMetrics().horizontalAdvance(zoom_fit.text()) + 24))):   # ширина по тексту: на другом языке надпись длиннее
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setFixedWidth(width)
            button.setStyleSheet("QPushButton { padding: 0px; font-size: 18px; }" if width < 40 else "QPushButton { padding: 0px; }")   # общий стиль кнопок даёт большие отступы и режет подпись
            row.addWidget(button)
        zoom_out.clicked.connect(lambda: self.zoom_step(-1))
        zoom_in.clicked.connect(lambda: self.zoom_step(1))
        self.zoom_label.clicked.connect(lambda: self.set_zoom(1.0))
        zoom_fit.clicked.connect(self.zoom_fit)
        row.addSpacing(10)
        save = QPushButton(icons.icon("save"), "  " + tr("editor.save"))
        save.setIconSize(QSize(18, 18))
        save.setToolTip(tr("editor.save_tip"))
        save.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        save.clicked.connect(self.save_and_close)
        copy = QPushButton(icons.icon("copy"), "  " + tr("editor.copy"))
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
        ocr_button = QPushButton(icons.icon("ocr", "#ffffff"), "  " + self.OCR_LABEL_ON)
        ocr_button.setCheckable(True)
        ocr_button.setObjectName("ocrButton")
        ocr_button.setIconSize(QSize(18, 18))
        ocr_button.setToolTip(tr("editor.ocr_button_tip"))
        ocr_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        ocr_button.setCursor(Qt.CursorShape.PointingHandCursor)
        ocr_button.setStyleSheet("QPushButton#ocrButton { background: #7c3aed; color: white; font-weight: bold;"
                                 " border: 1px solid #5b21b6; border-radius: 8px; padding: 3px 10px; }"
                                 " QPushButton#ocrButton:hover { background: #8f55f5; }"
                                 " QPushButton#ocrButton:checked { background: #5b21b6; border: 2px solid #ffffff; }")
        ocr_button.clicked.connect(lambda: self.exit_text_mode() if self.canvas.tool == OCR else self.select_tool(OCR))
        # одинаковая ширина при обеих надписях: кнопка не прыгает при входе и выходе из режима текста
        fm = ocr_button.fontMetrics()
        ocr_button.setMinimumWidth(max(fm.horizontalAdvance("  " + t) for t in (self.OCR_LABEL_ON, self.OCR_LABEL_OFF)) + 52)
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
        all_button = QPushButton(self.TR_ALL_LABEL)
        all_button.setObjectName("trAllButton")
        all_button.setToolTip(self.TR_ALL_TIP)
        tr_button = QPushButton(self.TR_SEL_LABEL)
        tr_button.setObjectName("trButton")
        tr_button.setCheckable(True)
        tr_button.setToolTip(self.TR_SEL_TIP)
        for b in (all_button, tr_button):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        all_button.setStyleSheet("QPushButton#trAllButton { background: #0d9488; color: white; font-weight: bold;"
                                 " border: 1px solid #0b766c; border-top-left-radius: 8px; border-bottom-left-radius: 8px;"
                                 " border-top-right-radius: 0px; border-bottom-right-radius: 0px; padding: 3px 6px; }"
                                 " QPushButton#trAllButton:hover { background: #14b8a6; }")
        tr_button.setStyleSheet("QPushButton#trButton { background: #0d9488; color: white; font-weight: bold;"
                                " border: 1px solid #0b766c; border-left: 1px solid #7fd8cf; border-top-right-radius: 8px;"
                                " border-bottom-right-radius: 8px; border-top-left-radius: 0px; border-bottom-left-radius: 0px;"
                                " padding: 3px 6px; }"
                                " QPushButton#trButton:hover { background: #14b8a6; }"
                                " QPushButton#trButton:checked { background: #0b5f57; border: 2px solid #ffffff; }")
        fm_tr = tr_button.fontMetrics()
        fm_all = all_button.fontMetrics()
        tr_button.setMinimumWidth(max(fm_tr.horizontalAdvance(t) for t in (self.TR_SEL_LABEL, self.TR_DONE_LABEL)) + 16)
        all_button.setMinimumWidth(fm_all.horizontalAdvance(self.TR_ALL_LABEL) + 16)
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

        def bind(keys, slot):
            for key in keys:
                QShortcut(QKeySequence(key), self, activated=slot)
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
        bind(["Ctrl+Y", QKeySequence.StandardKey.Redo], self.canvas.redo)
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
                self._widen_for_bottom()   # «Подряд / Маркер» появился: окно чуть шире, только если не помещается
        if tool == OCR:
            self.set_text_mode(self.ctx.config.get("ocr_select_mode", "range"))
        if tool == OCR:
            QTimer.singleShot(0, self.start_text_mode)
        if hasattr(self, "eraser_box"):
            self.eraser_box.setVisible(tool == ERASER)
            if tool == ERASER:
                self._widen_for_panel()   # «Целиком / Частично» появились: окно шире, если ряд не помещается
        if hasattr(self, "text_color_button"):
            self._sync_controls()
        self.tool_buttons[tool].setChecked(True)
        if tool not in MODE_TOOLS:   # режимы (текст, перевод, обрезка) не запоминаются: следующий снимок открывается обычным видом
            self.ctx.config["tool"] = tool
            self.ctx.save_config()   # выбор сразу запоминается для следующего снимка

    def select_color(self, color):
        color = QColor(color).name().lower()
        editing = self.canvas.editing_object()
        self.canvas.set_color(color)
        if not editing:
            self.ctx.config["color"] = color   # общий выбор запоминается; правка объекта — нет
            self.ctx.save_config()
        self._sync_controls()

    def _show_custom(self, color):
        self.custom_color.setChecked(True)
        self.custom_color.setText("")
        self.custom_color.setStyleSheet(f"QToolButton#swatch {{ background: {color}; }}")

    def pick_custom_color(self):
        color = QColorDialog.getColor(QColor(self._shown_values()[0]), self, tr("editor.color"))
        if color.isValid():
            self.select_color(color.name())
        else:
            self._sync_controls()

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
        editing = self.canvas.editing_object()
        self.canvas.set_text_color(QColor(color) if color is not None else None)
        if not editing:
            self.ctx.config["text_color"] = QColor(color).name() if color is not None else ""
            self.ctx.save_config()
        self._sync_controls()

    def pick_text_color(self):
        color = QColorDialog.getColor(self.canvas.text_color or QColor("#ffffff"), self, tr("editor.text_color"))
        if color.isValid():
            self.select_text_color(color.name())

    def select_size(self, size):
        editing = self.canvas.editing_object()
        self.canvas.set_size(size)
        if self.canvas.tool == ERASER:
            self.ctx.config["eraser_size"] = size
            self.ctx.save_config()
        elif not editing:
            self.ctx.config["size"] = size
            self.ctx.save_config()
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
        name = QColor(color).name().lower()
        if name in self.color_buttons:
            self.color_buttons[name].setChecked(True)
        else:
            self._show_custom(name)
        self.size_group.button(size).setChecked(True)
        self._update_text_color_button()
        self._update_info()

    def _selection_changed(self, _shape):
        """Выделили объект — кнопки показывают его свойства и меняют только его; сняли — общий выбор."""
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
        menu = self.build_tool_menu(button.tool if button is not None else None)
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

    def start_tour(self):
        """Вводный курс поверх окна (первый запуск или по кнопке «Показать знакомство»)."""
        from .tour import Tour
        if getattr(self, "tour", None) is not None:
            return
        self.tour = Tour(self)
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

    def _widen_for_panel(self):
        """Ряд палитры с кнопками режима ластика шире окна (маленький снимок, длинные подписи): окно расширяется
        до ширины панели, но не шире экрана; иначе подписи «Целиком / Частично» и кнопок справа обрезались."""
        self.panel.layout().activate()
        need = self.panel.sizeHint().width() + self._rim()[0]
        area = self._screen_area()
        if self.width() < need:
            self.resize(min(need, area.width() - 20), self.height())

    def _widen_for_bottom(self):
        need = self.bottom.sizeHint().width() + self._rim()[0]
        area = self._screen_area()
        if self.width() < need:
            self.resize(min(need, area.width() - 20), self.height())

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
        menu = self.build_context_menu(shape)
        menu.exec(global_pos)

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
        self.setStyleSheet(make_style(cfg))
        self.frame_px = theme(cfg)["ui_frame"]
        # Вид рамки меняется сразу; «системный заголовок» действует только на новые окна: у открытого окна
        # он всегда такой, с каким окно создано (иначе пропадут скругления или появится поле тени)
        self.shell.apply(dict(chrome_params(cfg), system=self.system_title))
        # Значки перерисовать в цвете нового оформления
        for tool, button in self.tool_buttons.items():
            button.setIcon(icons.icon(tool))
        for button, name in ((self.undo_button, "undo"), (self.redo_button, "redo"),
                             (self.insert_button, "insert"), (self.help_button, "help"),
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
        if OCR in getattr(self, "tool_buttons", {}):
            self.tool_buttons[OCR].setVisible(enabled)
        if getattr(self, "ocr_button", None) is not None:
            self.ocr_button.setVisible(enabled)
        tr_on = self.ctx.config.get("translate_enabled", True)
        if TRANSLATE in getattr(self, "tool_buttons", {}):
            self.tool_buttons[TRANSLATE].setVisible(tr_on)
        if getattr(self, "tr_block", None) is not None:
            self.tr_block.setVisible(tr_on)
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
        """Окно = снимок в рамке + панели; не уже панели инструментов и не больше экрана."""
        area = self._screen_area()
        rim_w, rim_h = self._rim()
        panel_w = self.panel.sizeHint().width() + rim_w
        bottom_w = self.bottom.sizeHint().width() + rim_w

        image_w = self.canvas.lw() + 2 * FRAME_WIDTH + rim_w      # размер окна считается по снимку 100%, масштаб вида его не меняет
        image_h = self.canvas.lh() + 2 * FRAME_WIDTH + rim_h
        bars_h = self.panel.sizeHint().height() + self.bottom.sizeHint().height()
        want_w = max(image_w, panel_w, bottom_w)
        want_h = image_h + bars_h
        self.setMinimumWidth(min(max(panel_w, bottom_w), area.width() - 20))
        self.resize(min(want_w, area.width() - 20), min(want_h, area.height() - 40))

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
            image.save(path)

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
        if not image.save(path):
            QMessageBox.warning(self, tr("editor.error"), tr("editor.save_error", path=path))
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
