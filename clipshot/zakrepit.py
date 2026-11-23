# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""«Закрепить поверх окон» (1.36): снимок висит отдельным окошком без рамки поверх всех окон, как стикер.

Окошко тянется мышью, размер меняется за края и углы (пропорции снимка сохраняются, 1.36.1) и колесом, Ctrl+колесо
прозрачность, крестик в углу, двойной щелчок или Esc открепляют, правая кнопка открывает меню (копировать, сохранить,
открыть в редакторе, прозрачность, открепить). Закреплённых окон можно
держать сколько угодно: их список здесь же (OPEN), у каждого своя картинка, размер и прозрачность.

Поверх всех окон: Qt.WindowStaysOnTopHint. Программа на Linux под Wayland по умолчанию работает через XWayland
(app.py), и там подсказка выполняется (оконный менеджер получает _NET_WM_STATE_ABOVE), на Windows тоже. Если ClipSD
запущен на «родном» Wayland (QT_QPA_PLATFORM=wayland), протокол окон такой подсказки не знает, и GNOME её не выполнит:
в окошке на несколько секунд появляется честная подсказка, как закрепить его средствами системы (Alt+Пробел, «Поверх
всех окон»). Окошко при этом остаётся обычным, программа не падает.

Прозрачность рисуется самим окошком (фон прозрачный, картинка рисуется с прозрачностью), а не setWindowOpacity:
так работает и там, где система прозрачность окон не знает."""

import os

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QImage, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QMenu, QWidget

from .i18n import tr

SCALE_MIN, SCALE_MAX = 0.1, 8.0
SCALE_STEP = 1.1          # одно «щёлк» колеса: на 10 %
OPACITY_MIN = 0.2
OPACITY_STEP = 0.1
OPACITY_CHOICES = (1.0, 0.75, 0.5, 0.25)
MIN_SIDE = 40             # меньше этого по короткой стороне окошко не сжимается
CROSS = 28                # крестик в углу, виден, пока мышь над окошком (1.36.1: крупнее и контрастнее)
EDGE = 8                  # px (логические, Qt сам умножает на масштаб экрана): полоса у края и угла, за которую тянется размер
HINT_MS = 7000
DRAG_START = 3            # px: до этого щелчок, не перенос

LEFT, RIGHT, TOP, BOTTOM = 1, 2, 4, 8   # какие края схвачены при изменении размера
CURSORS = {LEFT: Qt.CursorShape.SizeHorCursor, RIGHT: Qt.CursorShape.SizeHorCursor,
           TOP: Qt.CursorShape.SizeVerCursor, BOTTOM: Qt.CursorShape.SizeVerCursor,
           LEFT | TOP: Qt.CursorShape.SizeFDiagCursor, RIGHT | BOTTOM: Qt.CursorShape.SizeFDiagCursor,
           RIGHT | TOP: Qt.CursorShape.SizeBDiagCursor, LEFT | BOTTOM: Qt.CursorShape.SizeBDiagCursor}

OPEN: list = []           # закреплённые окошки (держат себя от сборщика мусора)


def native_wayland() -> bool:
    """Qt работает на «родном» Wayland: подсказка «поверх всех» там не выполняется (XWayland и Windows выполняют)."""
    return QGuiApplication.platformName().lower().startswith("wayland")


def logical_size(image: QImage) -> QSize:
    dpr = image.devicePixelRatio() or 1.0
    return QSize(max(1, round(image.width() / dpr)), max(1, round(image.height() / dpr)))


class PinnedWindow(QWidget):
    closed = pyqtSignal(object)

    def __init__(self, ctx, image: QImage, scale: float = 1.0, opacity: float = 1.0, dark: bool = None):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.ctx = ctx
        self.image = image
        self.scale = 1.0
        self.opacity = 1.0
        self.hint_text = ""
        self.flash_text = ""
        self._resize = None           # (края, геометрия окна, позиция мыши) при изменении размера за край
        self._drag = None             # (позиция мыши на экране, позиция окна) при переносе вручную
        self._press = None
        self._hover = False
        self.menu = None
        self.setObjectName("pinned")
        self.setWindowTitle(tr("zakrepit.window_name"))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)   # закрепление не отнимает ввод у другой программы
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.dark = bool(dark) if dark is not None else False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._clear_notes)
        self.set_scale(scale)
        self.set_opacity(opacity)

    # --- размер, прозрачность ------------------------------------------------------------

    def _limits(self):
        base = logical_size(self.image)
        low = max(SCALE_MIN, MIN_SIDE / max(1, min(base.width(), base.height())))
        return base, min(low, 1.0), SCALE_MAX

    def set_scale(self, scale: float, anchor: QPointF = None):
        """Размер в долях от исходного. anchor: точка окна, которая остаётся под курсором (колесо)."""
        base, low, high = self._limits()
        scale = max(low, min(high, float(scale)))
        old = self.size()
        self.scale = scale
        size = QSize(max(1, round(base.width() * scale)), max(1, round(base.height() * scale)))
        if anchor is not None and old.width() > 0 and old.height() > 0 and self.isVisible():
            rx, ry = anchor.x() / old.width(), anchor.y() / old.height()
            pos = self.pos() + QPoint(round(anchor.x() - rx * size.width()), round(anchor.y() - ry * size.height()))
            self.setGeometry(QRect(pos, size))
        else:
            self.resize(size)
        self.update()

    def set_opacity(self, value: float):
        self.opacity = max(OPACITY_MIN, min(1.0, round(float(value), 2)))
        self.update()

    # --- подсказки поверх картинки ---------------------------------------------------------

    def show_hint(self, text: str, ms: int = HINT_MS):
        self.hint_text = text
        self._timer.start(ms)
        self.update()

    def flash(self, text: str, ms: int = 1600):
        self.flash_text = text
        self._timer.start(ms)
        self.update()

    def _clear_notes(self):
        self.hint_text = self.flash_text = ""
        self.update()

    # --- рисование -------------------------------------------------------------------------

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self.scale != 1.0)
        p.setOpacity(self.opacity)
        p.drawImage(QRectF(self.rect()), self.image)
        p.setOpacity(1.0)
        p.setPen(QPen(QColor(0, 0, 0, 110), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        if self._hover:
            r = self.cross_rect()
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QPen(QColor("#ffffff"), 2))   # белое кольцо: крестик виден и на тёмном, и на светлом снимке
            p.setBrush(QColor(196, 43, 28, 245))
            p.drawEllipse(r.adjusted(1, 1, -1, -1))
            p.setPen(QPen(QColor("#ffffff"), 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            c = r.center()
            d = 5.5
            p.drawLine(QPointF(c.x() - d, c.y() - d), QPointF(c.x() + d, c.y() + d))
            p.drawLine(QPointF(c.x() - d, c.y() + d), QPointF(c.x() + d, c.y() - d))
        text = self.flash_text or self.hint_text
        if text:
            self._paint_note(p, text)
        p.end()

    def _paint_note(self, p: QPainter, text: str):
        font = QFont()
        font.setPixelSize(13)
        p.setFont(font)
        margin = 8
        width = max(60, self.width() - 2 * margin)
        flags = Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignCenter
        need = p.fontMetrics().boundingRect(QRect(0, 0, width - 20, 10000), int(flags), text)
        box = QRect(0, 0, min(width, need.width() + 20), need.height() + 16)
        box.moveCenter(QPoint(self.width() // 2, 0))
        box.moveBottom(self.height() - margin)
        if box.top() < margin:
            box.moveTop(margin)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 22, 26, 235))
        p.drawRoundedRect(QRectF(box), 8, 8)
        p.setPen(QColor("#ffffff"))
        p.drawText(box.adjusted(10, 8, -10, -8), int(flags), text)

    def cross_rect(self) -> QRectF:
        return QRectF(self.width() - CROSS - 5, 5, CROSS, CROSS)

    # --- мышь и клавиши -----------------------------------------------------------------------

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        if self._resize is None:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.update()
        super().leaveEvent(event)

    def edges_at(self, pos) -> int:
        """Какие края под точкой (логические точки окна): полоса EDGE у края, в углу два края. Под крестиком краёв нет."""
        x, y = pos.x(), pos.y()
        if self._hover and self.cross_rect().contains(QPointF(x, y)):
            return 0
        edges = 0
        if x < EDGE:
            edges |= LEFT
        elif x >= self.width() - EDGE:
            edges |= RIGHT
        if y < EDGE:
            edges |= TOP
        elif y >= self.height() - EDGE:
            edges |= BOTTOM
        return edges

    def _update_cursor(self, pos):
        shape = CURSORS.get(self.edges_at(pos), Qt.CursorShape.SizeAllCursor)
        if self.cursor().shape() != shape:
            self.setCursor(shape)

    def resize_by_edges(self, edges: int, start: QRect, delta: QPoint):
        """Размер за край или угол с сохранением пропорций снимка: окно растёт от противоположного края (угла)."""
        base, low, high = self._limits()
        w0, h0 = max(1, start.width()), max(1, start.height())
        dx = delta.x() * (1 if edges & RIGHT else -1 if edges & LEFT else 0)
        dy = delta.y() * (1 if edges & BOTTOM else -1 if edges & TOP else 0)
        kx = (w0 + dx) / w0 if (edges & (LEFT | RIGHT)) else None
        ky = (h0 + dy) / h0 if (edges & (TOP | BOTTOM)) else None
        k = max(v for v in (kx, ky) if v is not None)   # в углу побеждает та сторона, которую потянули дальше
        scale = max(low, min(high, self.scale_of(start) * k))
        size = QSize(max(1, round(base.width() * scale)), max(1, round(base.height() * scale)))
        x = start.right() + 1 - size.width() if edges & LEFT else start.x()
        y = start.bottom() + 1 - size.height() if edges & TOP else start.y()
        self.scale = scale
        self.setGeometry(QRect(QPoint(x, y), size))
        self.update()

    def scale_of(self, rect: QRect) -> float:
        base = logical_size(self.image)
        return rect.width() / max(1, base.width())

    def mousePressEvent(self, event):
        self.setFocus()
        if event.button() == Qt.MouseButton.RightButton:
            self.show_menu(event.globalPosition().toPoint())
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._press = event.globalPosition().toPoint()
        self._drag = None
        self._resize = None
        if self._hover and self.cross_rect().contains(event.position()):
            self._press = "close"
            return
        edges = self.edges_at(event.position())
        if edges:
            self._resize = (edges, QRect(self.geometry()), event.globalPosition().toPoint())
            self._press = "resize"
            return
        self._drag = (event.globalPosition().toPoint(), self.pos())

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            self._update_cursor(event.position())
            return
        if self._resize is not None:
            edges, start, origin = self._resize
            self.resize_by_edges(edges, start, event.globalPosition().toPoint() - origin)
            return
        if self._drag is None:
            return
        start, origin = self._drag
        delta = event.globalPosition().toPoint() - start
        if delta.manhattanLength() < DRAG_START and self._press != "moved":
            return
        if self._press != "moved":
            handle = self.windowHandle()
            if handle is not None and handle.startSystemMove():   # X11, Wayland, Windows: систему переносит сама
                self._drag = None
                self._press = None
                return
            self._press = "moved"
        self.move(origin + delta)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._press == "close" \
                and self.cross_rect().contains(event.position()):
            self.close()
            return
        self._drag = None
        self._resize = None
        self._press = None
        self._update_cursor(event.position())

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.close()

    def wheelEvent(self, event):
        dy = event.angleDelta().y()
        if not dy:
            return
        steps = dy / 120.0
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.set_opacity(self.opacity + OPACITY_STEP * steps)
        else:
            self.set_scale(self.scale * (SCALE_STEP ** steps), event.position())
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    # --- меню правой кнопки ------------------------------------------------------------------------

    def build_menu(self) -> QMenu:
        from .menus import style_menu
        menu = QMenu(self)
        style_menu(menu, getattr(self.ctx, "config", None) or {})
        menu.addAction(tr("zakrepit.menu_copy")).triggered.connect(self.copy_image)
        menu.addAction(tr("zakrepit.menu_save")).triggered.connect(self.save_image)
        menu.addAction(tr("zakrepit.menu_editor")).triggered.connect(self.open_in_editor)
        menu.addSeparator()
        sub = menu.addMenu(tr("zakrepit.menu_opacity"))
        style_menu(sub, getattr(self.ctx, "config", None) or {})
        for value in OPACITY_CHOICES:
            act = sub.addAction(f"{round(value * 100)} %")
            act.setCheckable(True)
            act.setChecked(abs(self.opacity - value) < 0.02)
            act.triggered.connect(lambda _c=False, v=value: self.set_opacity(v))
        menu.addSeparator()
        close = menu.addAction(tr("zakrepit.menu_close") + "\tEsc")
        close.triggered.connect(self.close)
        if len(OPEN) > 1:
            menu.addAction(tr("zakrepit.menu_close_all")).triggered.connect(close_all)
        return menu

    def show_menu(self, global_pos: QPoint):
        self.menu = self.build_menu()
        self.menu.exec(global_pos)

    # --- действия --------------------------------------------------------------------------------

    def copy_image(self):
        copy = getattr(self.ctx, "copy_image", None)
        if callable(copy):
            copy(self.image)
        else:
            QGuiApplication.clipboard().setImage(self.image)
        self.flash(tr("zakrepit.copied"))

    def save_image(self):
        from . import hidpi
        from .editor import ask_save_path
        cfg = getattr(self.ctx, "config", None) or {}
        path = ask_save_path(self, cfg)
        if not path:
            return None
        if not hidpi.save_image(self.image, path, cfg):
            hidpi.discard_reserved(path)
            self.flash(tr("zakrepit.save_failed"), 3000)
            return False
        cfg["save_dir"] = os.path.dirname(path)
        save = getattr(self.ctx, "save_config", None)
        if callable(save):
            save()
        self.flash(tr("zakrepit.saved", name=os.path.basename(path)), 2600)
        return path

    def open_in_editor(self):
        from . import otdelno
        return otdelno.open_apart(self.ctx, self.image)

    # --- закрытие ---------------------------------------------------------------------------------

    def closeEvent(self, event):
        if self in OPEN:
            OPEN.remove(self)
        self.closed.emit(self)
        super().closeEvent(event)


def close_all():
    for w in list(OPEN):
        w.close()


def _place(win: PinnedWindow, top_left):
    """Куда поставить окошко: на место снимка (top_left, глобальные точки), иначе по центру экрана с курсором, каждое
    следующее со сдвигом, чтобы закреплённые не ложились в точности друг на друга."""
    shift = 28 * (len(OPEN) - 1)
    if top_left is not None:
        pos = QPoint(top_left)
        while any(w is not win and w.pos() == pos for w in OPEN):   # на этом месте уже висит закреплённый
            pos += QPoint(28, 28)
    else:
        from PyQt6.QtGui import QCursor
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry() if screen is not None else QRect(0, 0, 1280, 720)
        pos = QPoint(area.center().x() - win.width() // 2 + shift, area.center().y() - win.height() // 2 + shift)
    win.move(pos)


def pin(ctx, image: QImage, top_left=None, scale: float = 1.0, opacity: float = 1.0):
    """Закрепить картинку поверх окон. top_left: где стоял снимок на экране (глобальные точки) или None.
    Возвращает окошко или None, если картинки нет."""
    if image is None or image.isNull():
        return None
    from . import themes
    try:
        dark = themes.is_dark()
    except Exception:   # noqa: BLE001 — оформление не должно мешать закреплению
        dark = False
    win = PinnedWindow(ctx, QImage(image), scale, opacity, dark)
    OPEN.append(win)
    _place(win, top_left)
    win.show()
    win.raise_()
    howto = not _howto_enough(ctx)
    wayland = native_wayland() and not _hint_enough(ctx)
    if howto or wayland:
        win.show_hint("\n".join(([tr("zakrepit.howto")] if howto else []) + ([tr("zakrepit.wayland_hint")] if wayland else [])),
                      HINT_MS + (3000 if howto else 0))
    if howto:
        _note_howto(ctx)
    if wayland:
        _note_hint(ctx)
    return win


HINT_TIMES = 3   # столько закреплений подсказка про Wayland показывается, потом считается, что человек её видел


def _hint_enough(ctx) -> bool:
    cfg = getattr(ctx, "config", None)
    try:
        return isinstance(cfg, dict) and int(cfg.get("zakrepit_hint_shown", 0) or 0) >= HINT_TIMES
    except (TypeError, ValueError):
        return False


def _note_hint(ctx):
    cfg = getattr(ctx, "config", None)
    if not isinstance(cfg, dict):
        return
    try:
        cfg["zakrepit_hint_shown"] = int(cfg.get("zakrepit_hint_shown", 0) or 0) + 1
    except (TypeError, ValueError):
        cfg["zakrepit_hint_shown"] = 1
    save = getattr(ctx, "save_config", None)
    if callable(save):
        save()


def _howto_enough(ctx) -> bool:
    """Как менять размер и как открепить: показывается при первых закреплениях (HINT_TIMES), потом человек знает."""
    cfg = getattr(ctx, "config", None)
    if not isinstance(cfg, dict):
        return True   # учебный или пробный ctx без настроек: ничего не запоминаем и не показываем
    try:
        return int(cfg.get("zakrepit_howto_shown", 0) or 0) >= HINT_TIMES
    except (TypeError, ValueError):
        return False


def _note_howto(ctx):
    cfg = getattr(ctx, "config", None)
    try:
        cfg["zakrepit_howto_shown"] = int(cfg.get("zakrepit_howto_shown", 0) or 0) + 1
    except (TypeError, ValueError):
        cfg["zakrepit_howto_shown"] = 1
    save = getattr(ctx, "save_config", None)
    if callable(save):
        save()
