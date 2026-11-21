# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Выделение области: замороженный экран, затемнение, перекрестие, лупа и размер.

Под Wayland снимок стола приходит с задержкой (см. grab.py), поэтому оверлей умеет работать
«вживую»: прозрачное окно с затемнением поверх настоящего экрана. Когда снимок готов
(set_desktop), под затемнение подкладывается замороженный кадр и включается лупа.
Если выделение закончено раньше, чем пришёл снимок, вырезка делается сразу по его приходу."""

import sys

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QLinearGradient, QCursor, QFont, QFontMetrics, QGuiApplication, QImage, QPainter, QPen, QPixmap, QRegion
from PyQt6.QtWidgets import QWidget

from . import i18n, language, translate_ui
from .grab import native_region
from .i18n import dynamic, tr
from .i18n import keys as i18n_keys
from .translate_ui import TranslateMixin

DIM = QColor(0, 0, 0, 110)
ACCENT = QColor(0, 174, 255)
ZOOM_COLS = 61    # ширина участка экрана в лупе, пикселей (нечётное: курсор ровно в центре)
ZOOM_ROWS = 41    # высота участка
ZOOM_PIXELS = ZOOM_ROWS   # для совместимости с тестами
ZOOM_SCALE = 4    # увеличение: в 4 раза, слова под курсором читаются, пиксели остаются чёткими
ZOOM_OFFSET = 26   # отступ лупы от курсора


def _fullscreen_all_monitors(widget):
    """X11/XWayland: растянуть полноэкранное окно на все мониторы (_NET_WM_FULLSCREEN_MONITORS)."""
    try:
        from Xlib import X, display, protocol
        from Xlib.ext import xinerama
    except ImportError:
        widget.showFullScreen()
        return
    disp = display.Display()
    try:
        screens = xinerama.query_screens(disp).screens
        if not screens:
            widget.showFullScreen()
            return
        idx = range(len(screens))
        top = min(idx, key=lambda i: screens[i].y)
        bottom = max(idx, key=lambda i: screens[i].y + screens[i].height)
        left = min(idx, key=lambda i: screens[i].x)
        right = max(idx, key=lambda i: screens[i].x + screens[i].width)
        root = disp.screen().root
        win = disp.create_resource_object("window", int(widget.winId()))
        mask = X.SubstructureRedirectMask | X.SubstructureNotifyMask

        def send(name, data):
            event = protocol.event.ClientMessage(window=win, client_type=disp.intern_atom(name),
                                                 data=(32, data))
            root.send_event(event, event_mask=mask)

        send("_NET_WM_FULLSCREEN_MONITORS", [top, bottom, left, right, 1])
        send("_NET_WM_STATE", [1, disp.intern_atom("_NET_WM_STATE_FULLSCREEN"), 0, 1, 0])
        send("_NET_ACTIVE_WINDOW", [2, X.CurrentTime, 0, 0, 0])
        disp.flush()
    finally:
        disp.close()


def force_foreground(widget):
    """Windows: вывести окно на передний план с фокусом клавиатуры.

    ClipSD работает в фоне, и Windows не даёт фоновому процессу забирать фокус: окно появляется,
    но клавиши (Esc, Enter, V, A, Ctrl+C…) продолжают уходить в прежнее окно. Временно
    подключаемся к очереди ввода активного окна — тогда SetForegroundWindow разрешён."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
        for name in ("BringWindowToTop", "SetForegroundWindow", "SetFocus"):
            getattr(user32, name).argtypes = [wintypes.HWND]
        hwnd = int(widget.winId())
        foreground = user32.GetForegroundWindow() or 0
        if foreground == hwnd:
            return
        fg_thread = user32.GetWindowThreadProcessId(foreground, None)
        own_thread = kernel32.GetCurrentThreadId()
        attached = fg_thread and fg_thread != own_thread and user32.AttachThreadInput(fg_thread, own_thread, True)
        try:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SetFocus(hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(fg_thread, own_thread, False)
    except Exception:   # noqa: BLE001 — активация «по возможности», без неё программа тоже работает
        pass


def span_rect(a: QPoint, b: QPoint) -> QRect:
    """Прямоугольник между двумя точками без «лишнего» пикселя (QRect(a, b) включает обе границы)."""
    return QRect(min(a.x(), b.x()), min(a.y(), b.y()), abs(b.x() - a.x()), abs(b.y() - a.y()))


class RegionSelector(TranslateMixin, QWidget):
    """Полноэкранный оверлей. finished(pixmap | None, глобальный прямоугольник)."""

    tr_floating = True   # перевод: отдельное окошко, экран после выделения сразу живой
    tr_floating_chip = False    # пока окно выделения в режиме перевода, у окошек нет плашки: кнопки в строке панели
    tr_banner_enabled = False   # 1.29: вместо полосы внизу панель окна выделения с плиткой перевода и бирюзовой строкой

    finished = pyqtSignal(object, QRect)

    def __init__(self, desktop, geometry: QRect, show_zoom=True, show_size=True, last_rect: QRect = None,
                 full_screen=False):
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.desktop = None        # QPixmap всего стола; None — снимок ещё не готов
        self.image = QImage()
        self.ratio = max(screen.devicePixelRatio() for screen in QGuiApplication.screens())
        self.pending = None        # выделение, завершённое до прихода снимка
        self.origin = geometry.topLeft()
        self.show_zoom = show_zoom
        self.show_size = show_size
        self.start = None
        self.cursor_pos = QPoint()
        self._done = False
        # Прошлая область: Enter или клик внутри — снять её же; тянуть внутри — сдвинуть; снаружи — новая.
        self.kept = None
        if last_rect is not None and last_rect.width() >= 3 and last_rect.height() >= 3:
            local = last_rect.translated(-geometry.topLeft())
            if QRect(QPoint(0, 0), geometry.size()).contains(local):
                self.kept = local
        # Снимок всего экрана: экран притемнён, по краю каждого монитора толстая рамка, в центре надпись и кнопки.
        # Так случайно нажатое сочетание сразу видно; мышью можно выделить и обычную область.
        self.full_mode = bool(full_screen)
        if self.full_mode:
            self.kept = QRect(QPoint(0, 0), geometry.size())
        self.bar_title_rect = QRect()
        self.bar_close_rect = QRect()
        # Панель можно перетащить мышью за свободное место (разово: пока окно открыто, в настройки не пишется)
        self.bar_pos = None        # левый верхний угол перетащенной панели; None: панель на обычном месте
        self.bar_drag = None       # идущий перенос: (где нажали, угол панели в момент нажатия)
        self.bar_dragging = False  # протянули дальше порога: это перенос, а не щелчок
        self._tr_init()   # режим перевода (translate_ui)
        self.tr_current = None     # окошко, к которому относятся кнопки строки перевода (последнее или выбранное щелчком)
        self.tr_ctl_rects = []     # кнопки строки перевода: (ключ, подпись, прямоугольник, включена, нажата)
        self.bar_user = False      # панель перетащена владельцем: сама не двигается
        self.tr_pieces = 0         # сколько кусков уже переведено в этом режиме (подсказка «следующий кусок»)
        self.chip_rects = []       # кнопки выбора монитора в режиме «весь экран»: (ключ, подпись, прямоугольник, выбрана)
        self.bar_anchor = None     # монитор (глобальный прямоугольник), на котором стоит панель «весь экран»
        self.move_from = None
        self.moved = False
        self.resize_edge = None   # тянем сторону или угол прошлой области: "l", "r", "t", "b", "tl", "tr", "bl", "br"
        self.action = "edit"      # что сделать со снимком: edit (редактор), copy (в буфер и закрыть), save (в файл)
        self.hover_button = None
        self.bar_level = None
        self.bar_hint_text = ""
        # Выбор языка в нижней строке панели (1.31.1): приложение (ctx с set_language и config); None: чипа нет
        self.lang_ctx = None
        self.lang_rect = QRect()   # чип языка в строке подсказки; пустой: чипа нет
        self.gear_rect = QRect()   # шестерёнка «Настройки» правее чипа языка
        self.bar_hint_reserve = 0  # сколько справа в строке подсказки занято чипом языка и размером
        self.tour = None           # 1.32: идущее знакомство с окном выделения (SelectorTour)
        self.tour_force = False    # знакомство по запросу (пункт меню): показывать, даже если уже видели
        self._tour_demo = False    # рамка у знакомства показана для примера (своей области ещё нет)
        # «Снимок окна» (утверждено владельцем 21.11.2026): чип «Окна ▾» в нижней строке панели и клавиша W.
        # Список окон просится в момент Alt+W, вместе с кадром стола, и приходит сюда set_windows.
        self.windows_state = None    # None: на этой системе списка нет (чипа нет); "loading"; "ready"
        self.windows = []            # [windows.WinInfo] сверху вниз, глобальные точки
        self.windows_complete = True  # False: видны только окна XWayland (дополнение GNOME старое или не стоит)
        self.windows_ext = ""        # GNOME: ok, old (нет ListWindows), missing (дополнения нет), slow (не ответило вовремя)
        self.windows_failed = False  # список не получен из-за ошибки (Windows): в меню понятная строка
        self.window_ext_relogin = False   # дополнение уже обновлено кнопкой, ждёт выхода из сеанса и входа
        self.window_grab = None      # фабрика(WinInfo) -> объект с сигналом done(QPixmap|None) и start(); None: не умеет
        self.win_rect = QRect()      # чип «Окна ▾» левее чипа языка; пустой: чипа нет
        self.win_menu = None         # открытый список окон
        self.preview_win = None      # окно, чья рамка показана (строка списка под курсором)
        self.picked_win = None       # выбранное окно: рамка стоит на нём
        self._desktop_orig = None    # кадр стола до того, как в него вписано выбранное окно
        self._lift = None            # идущий запрос содержимого выбранного окна
        self._lift_pixmap = None     # содержимое пришло раньше кадра стола: впишется, когда кадр придёт
        self._win_open_pending = False   # список попросили (W, чип), пока он ещё не пришёл

        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setGeometry(geometry)
        if desktop is not None:
            self.set_desktop(desktop)

    # --- знакомство с окном выделения (1.32) ---------------------------------

    def maybe_start_tour(self):
        """Первый показ окна выделения (флаг tour_selector_done в настройках) или знакомство по запросу."""
        cfg = self.tr_cfg if isinstance(getattr(self, "tr_cfg", None), dict) else None
        if self.tour is not None or self.translate_mode or self._done:
            return False
        if not self.tour_force and (cfg is None or cfg.get("tour_selector_done")):
            return False
        self.tour_force = False
        if cfg is not None:
            cfg["tour_selector_done"] = True   # отмечается при показе: даже закрытое сразу знакомство повторно не навязывается
            save = getattr(self, "tr_save", None)
            if callable(save):
                save()
        self.start_tour()
        return True

    def start_tour(self):
        """Затемнение с вырезами вокруг кнопок панели. Своей рамки ещё нет: для примера ставится рамка посередине."""
        from .selector_tour import SelectorTour
        if self.tour is not None:
            return
        self._tour_demo = self.kept is None
        if self._tour_demo:
            area = self.hint_anchor()
            w, h = int(area.width() * 0.38), int(area.height() * 0.30)
            self.kept = QRect(area.center().x() - w // 2, area.center().y() - h // 2 - area.height() // 12, w, h)
            self._bar_forget()
        self.hover_button = None
        self.tour = SelectorTour(self)
        self.tour.finished.connect(self._tour_done)
        self.tour.start()
        self.update()

    def _tour_done(self):
        self.tour = None
        if self._tour_demo:
            self._tour_demo = False
            self.kept = None
            self._bar_forget()
        self.hover_button = None
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.tour is not None:
            self.tour.relayout()

    def set_desktop(self, desktop: QPixmap):
        self.desktop = desktop
        self._desktop_orig = None
        self.ratio = desktop.devicePixelRatio()
        if self._lift_pixmap is not None and self.picked_win is not None:
            self._paint_lifted(self.picked_win, self._lift_pixmap)   # содержимое окна пришло раньше кадра
        self.image = self.desktop.toImage()
        if self.pending is not None:
            if self._lift is None:
                self._emit(self.pending)
        else:
            self._tr_pending()   # куски для перевода, выделенные до готовности снимка
            self.update()

    def fail(self):
        """Снимок не получен — закрыть оверлей без результата."""
        self.pending = None
        self._finish(None)

    def start_selection(self):
        if sys.platform == "win32":
            self.setGeometry(self.geometry())   # Windows: окно без рамки на все мониторы сразу
            self.show()
        elif len(QGuiApplication.screens()) == 1:
            self.showFullScreen()
        else:
            # Обычное окно (не Tool): иначе GNOME не даёт фокус и сдвигает его под верхнюю панель.
            self.setWindowFlag(Qt.WindowType.Tool, False)
            self.show()
            _fullscreen_all_monitors(self)
        self.raise_()
        self.activateWindow()
        force_foreground(self)
        self.grabKeyboard()
        self.cursor_pos = self.mapFromGlobal(QCursor.pos())
        self.update()

    # --- геометрия ---------------------------------------------------------

    EDGE_CURSORS = {"l": Qt.CursorShape.SizeHorCursor, "r": Qt.CursorShape.SizeHorCursor,
                    "t": Qt.CursorShape.SizeVerCursor, "b": Qt.CursorShape.SizeVerCursor,
                    "tl": Qt.CursorShape.SizeFDiagCursor, "br": Qt.CursorShape.SizeFDiagCursor,
                    "tr": Qt.CursorShape.SizeBDiagCursor, "bl": Qt.CursorShape.SizeBDiagCursor}
    GRIP = 7   # насколько близко к стороне рамки нужно навести курсор, px
    # Круглые ручки изменения размера: видны всегда, чтобы было понятно, что за них можно тянуть.
    # Радиус угловой 8 (диаметр 16), боковой 6 (диаметр 12); мышью ручка берётся на радиус плюс HANDLE_PAD.
    HANDLE_R_CORNER, HANDLE_R_SIDE, HANDLE_PAD = 8, 6, 3
    FRAME_W = 3   # толщина пунктирной рамки выделенной области

    def _handles(self, r: QRect):
        """Ручки области: [(имя стороны или угла, центр QPoint, радиус)]. У маленькой области кружки меньше,
        а боковые пропадают (остаются угловые), чтобы ручки не слипались и область можно было перенести."""
        m = min(r.width(), r.height())
        rc = max(4, min(self.HANDLE_R_CORNER, m // 4))
        rs = max(3, min(self.HANDLE_R_SIDE, rc * 3 // 4))
        x0, y0, x1, y1 = r.left(), r.top(), r.left() + r.width(), r.top() + r.height()
        xm, ym = (x0 + x1) // 2, (y0 + y1) // 2
        out = [("tl", QPoint(x0, y0), rc), ("tr", QPoint(x1, y0), rc), ("br", QPoint(x1, y1), rc), ("bl", QPoint(x0, y1), rc)]
        room = 4 * rc + 2 * rs + 8   # сторона короче: боковая ручка уткнулась бы в угловые
        if r.width() >= room:
            out += [("t", QPoint(xm, y0), rs), ("b", QPoint(xm, y1), rs)]
        if r.height() >= room:
            out += [("l", QPoint(x0, ym), rs), ("r", QPoint(x1, ym), rs)]
        return out

    def _edge_at(self, pos: QPoint):
        """Какая сторона или угол прошлой области под курсором (None — нет)."""
        r = self.kept
        if r is None or self.full_mode:
            return None
        for name, c, rad in self._handles(r):   # видимый кружок берётся целиком
            if (pos.x() - c.x()) ** 2 + (pos.y() - c.y()) ** 2 <= (rad + self.HANDLE_PAD) ** 2:
                return name
        g = self.GRIP
        if not r.adjusted(-g, -g, g, g).contains(pos):
            return None
        near_l, near_r = abs(pos.x() - r.left()) <= g, abs(pos.x() - (r.left() + r.width())) <= g
        near_t, near_b = abs(pos.y() - r.top()) <= g, abs(pos.y() - (r.top() + r.height())) <= g
        vert = "t" if near_t else "b" if near_b else ""
        horiz = "l" if near_l else "r" if near_r else ""
        return (vert + horiz) or None

    def _resized(self, pos: QPoint) -> QRect:
        r = QRect(self.kept)
        left, top, right, bottom = r.left(), r.top(), r.left() + r.width(), r.top() + r.height()
        x = max(0, min(pos.x(), self.width()))
        y = max(0, min(pos.y(), self.height()))
        if "l" in self.resize_edge:
            left = min(x, right - 8)
        if "r" in self.resize_edge:
            right = max(x, left + 8)
        if "t" in self.resize_edge:
            top = min(y, bottom - 8)
        if "b" in self.resize_edge:
            bottom = max(y, top + 8)
        return QRect(left, top, right - left, bottom - top)

    def _cursor_for(self, pos: QPoint):
        edge = self._edge_at(pos)
        if edge:
            return self.EDGE_CURSORS[edge]
        if self.kept is not None and not self.full_mode and self.kept.contains(pos):
            return Qt.CursorShape.SizeAllCursor
        return Qt.CursorShape.CrossCursor

    def selection(self):
        if self.start is None:
            return self.kept
        return span_rect(self.start, self.cursor_pos)

    def to_physical(self, rect: QRect) -> QRect:
        r = self.ratio
        return QRect(round(rect.x() * r), round(rect.y() * r),
                     max(1, round(rect.width() * r)), max(1, round(rect.height() * r)))

    # --- отрисовка ---------------------------------------------------------

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        if self.desktop is not None:
            p.drawPixmap(self.rect(), self.desktop)
        else:
            p.fillRect(self.rect(), Qt.GlobalColor.transparent)  # живой экран под оверлеем
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        if self.translate_mode:
            self._tr_paint(p)
            self._draw_action_bar(p)
            return
        sel = self.pending if self.pending is not None else self.selection()

        if self.preview_win is not None and self.pending is None and self.start is None:
            self._draw_window_preview(p)
            return
        if self.full_mode and self.pending is None and self.start is None:
            self._draw_full_screen(p)
            return
        if sel is not None and sel.width() > 0 and sel.height() > 0:
            p.setClipRegion(QRegion(self.rect()).subtracted(QRegion(sel)))
            p.fillRect(self.rect(), DIM)
            p.setClipping(False)
            p.setPen(QPen(ACCENT, 1))
            p.drawRect(sel.adjusted(0, 0, -1, -1))
            if self.show_size:
                phys = self.to_physical(sel)
                # у выделенной области подпись отодвинута от угловой ручки
                shift = (14, 10) if sel is self.kept and self.start is None and self.pending is None else (0, 0)
                self._draw_label(p, tr("selector.size_label", w=phys.width(), h=phys.height()), sel.topLeft(), above=True,
                                 dx=shift[0], dy=shift[1])
            if sel is self.kept and self.start is None and self.pending is None:
                fw = self.FRAME_W
                p.setPen(QPen(ACCENT, fw, Qt.PenStyle.DashLine))
                p.drawRect(QRectF(sel).adjusted(fw / 2, fw / 2, -fw / 2, -fw / 2))
                self._draw_handles(p, sel)
                p.setBrush(Qt.BrushStyle.NoBrush)
                self._draw_action_bar(p)
        else:
            p.fillRect(self.rect(), DIM)
            pen = QPen(QColor(255, 255, 255, 160), 1, Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.drawLine(0, self.cursor_pos.y(), self.width(), self.cursor_pos.y())
            p.drawLine(self.cursor_pos.x(), 0, self.cursor_pos.x(), self.height())

        if self.pending is not None:
            self._draw_label(p, tr("selector.preparing"), sel.topLeft(), above=False)
        elif self.show_zoom and self.desktop is not None:
            self._draw_magnifier(p)
        self._draw_corner_close(p)

    def _draw_handles(self, p: QPainter, sel: QRect):
        """Круглые ручки: белые, обводка цветом рамки, снаружи тёмная полупрозрачная кайма (видно на любом фоне).
        Под курсором (или пока тянут) ручка чуть крупнее и залита цветом рамки."""
        hot = self.resize_edge or self._edge_at(self.cursor_pos)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for name, c, rad in self._handles(sel):
            rr = rad + (1.5 if name == hot else 0)
            centre = QPointF(c)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 100))
            p.drawEllipse(centre, rr + 1.5, rr + 1.5)
            p.setPen(QPen(ACCENT, 2.75))
            p.setBrush(QColor(ACCENT) if name == hot else QColor(255, 255, 255))
            p.drawEllipse(centre, rr - 1.4, rr - 1.4)
        p.restore()

    # Второй крестик «Закрыть без снимка» в правом верхнем углу: у выделенной области он внутри неё у правого
    # верхнего угла и ездит вместе с ней; без области и в режиме «весь экран» в углу монитора.
    CORNER_SIZE, CORNER_MARGIN = 40, 22
    KEPT_CROSS, KEPT_INSET = 32, 12   # отступ от сторон больше GRIP: за стороны по-прежнему можно тянуть

    def _corner_rects(self):
        size, m = self.CORNER_SIZE, self.CORNER_MARGIN
        if self.kept is not None and not self.full_mode:
            r, cs, inset = self.kept, self.KEPT_CROSS, self.KEPT_INSET
            right = r.left() + r.width()
            if r.width() >= cs + 2 * inset + 20 and r.height() >= cs + 2 * inset + 20:
                return [QRect(right - inset - cs, r.top() + inset, cs, cs)]
            # Область слишком мала: крестик над её правым верхним углом (или под ним у края экрана)
            top = r.top() - 14 - cs   # зазор больше радиуса угловой ручки
            if top < 2:
                top = r.top() + r.height() + 14
            x = min(right, self.width() - 2) - cs
            if self.show_size:
                # подпись размера стоит над левым углом: крестик не должен её закрывать, уходит правее неё
                x = max(x, r.left() + 14 + self._size_label_width() + 8)
            return [QRect(min(x, self.width() - 2 - cs), top, cs, cs)]
        rects = []
        for screen in QGuiApplication.screens():
            area = screen.geometry().translated(-self.origin).intersected(self.rect())
            if area.width() > 3 * size and area.height() > 3 * size:
                rects.append(QRect(area.left() + area.width() - m - size, area.top() + m, size, size))
        return rects or [QRect(self.width() - m - size, m, size, size)]

    def _corner_at(self, pos: QPoint) -> bool:
        if self.start is not None or self.pending is not None:
            return False
        pad = 0 if (self.kept is not None and not self.full_mode) else 4   # у области не задевать её стороны
        return any(r.adjusted(-pad, -pad, pad, pad).contains(pos) for r in self._corner_rects())

    def _draw_corner_close(self, p: QPainter):
        if self.start is not None or self.pending is not None:
            return
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for rect in self._corner_rects():
            self._draw_cross(p, QRectF(rect), self.hover_button == "corner")
        p.restore()

    FULL_FRAME = 10   # толщина рамки по краю монитора в режиме «весь экран», px

    def _draw_full_screen(self, p: QPainter):
        p.fillRect(self.rect(), QColor(0, 0, 0, 120))
        half = self.FULL_FRAME // 2
        p.setPen(QPen(ACCENT, self.FULL_FRAME))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for screen in QGuiApplication.screens():
            area = screen.geometry().translated(-self.origin).intersected(self.kept)
            if not area.isEmpty():
                p.drawRect(area.adjusted(half, half, -half - 1, -half - 1))
        self._draw_action_bar(p)
        self._draw_corner_close(p)

    def _size_label_text(self, sel: QRect) -> str:
        phys = self.to_physical(sel)
        return tr("selector.size_label", w=phys.width(), h=phys.height())

    def _size_label_width(self) -> int:
        font = QFont()
        font.setPixelSize(12)
        return QFontMetrics(font).horizontalAdvance(self._size_label_text(self.kept)) + 10

    def _draw_label(self, p: QPainter, text: str, anchor: QPoint, above: bool, dx: int = 0, dy: int = 0):
        font = QFont()
        font.setPixelSize(12)
        p.setFont(font)
        fm = p.fontMetrics()
        w, h = fm.horizontalAdvance(text) + 10, fm.height() + 4
        y = anchor.y() - h - 2 - dy if above and anchor.y() - h - 2 - dy >= 0 else anchor.y() + 2 + dy
        box = QRect(anchor.x() + dx, y, w, h)
        p.fillRect(box, QColor(0, 0, 0, 190))
        p.setPen(Qt.GlobalColor.white)
        p.drawText(box.adjusted(5, 2, 0, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, text)

    def _draw_magnifier(self, p: QPainter):
        """Лупа рядом с курсором: участок экрана в 4 раза крупнее (читаются слова), точный пиксель, цвет."""
        nw, nh, cell = ZOOM_COLS, ZOOM_ROWS, ZOOM_SCALE
        w, h = nw * cell, nh * cell
        info_h = 50
        cur = self.cursor_pos
        # Лупа не выходит за монитор, на котором курсор: при нехватке места — по другую сторону курсора.
        screen = QGuiApplication.screenAt(self.mapToGlobal(cur))
        area = screen.geometry().translated(-self.origin) if screen else self.rect()
        x, y = cur.x() + ZOOM_OFFSET, cur.y() + ZOOM_OFFSET
        if x + w + 2 > area.right():
            x = cur.x() - ZOOM_OFFSET - w
        if y + h + info_h + 2 > area.bottom():
            y = cur.y() - ZOOM_OFFSET - h - info_h
        x = max(area.left() + 2, x)
        y = max(area.top() + 2, y)
        box = QRect(x, y, w, h)
        whole = QRect(x, y, w, h + info_h)

        # Участок снимка в физических пикселях (масштаб экрана 125–150 % учтён)
        px = min(max(0, int(cur.x() * self.ratio)), max(0, self.image.width() - 1))
        py = min(max(0, int(cur.y() * self.ratio)), max(0, self.image.height() - 1))
        hx, hy = nw // 2, nh // 2
        patch = self.image.copy(QRect(px - hx, py - hy, nw, nh))
        patch.setDevicePixelRatio(1.0)

        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        for i, alpha in ((7, 26), (4, 40), (2, 60)):   # мягкая тень, чтобы лупа читалась на любом фоне
            p.setBrush(QColor(0, 0, 0, alpha))
            p.drawRoundedRect(QRectF(whole.adjusted(-i, -i + 2, i, i + 2)), 8 + i, 8 + i)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)   # чёткие пиксели без размытия
        p.fillRect(box, QColor(40, 40, 40))
        p.drawImage(QRectF(box), patch)

        # Перекрестие: тонкие линии по краям строки и столбца курсора, рамка вокруг точного пикселя
        cx, cy = x + hx * cell, y + hy * cell
        guide = QColor(ACCENT)
        guide.setAlpha(150)
        p.setPen(QPen(guide, 1))
        for gx in (cx, cx + cell):
            p.drawLine(gx, y, gx, cy - 2)
            p.drawLine(gx, cy + cell + 2, gx, y + h - 1)
        for gy in (cy, cy + cell):
            p.drawLine(x, gy, cx - 2, gy)
            p.drawLine(cx + cell + 2, gy, x + w - 1, gy)
        center = QRect(cx, cy, cell, cell)
        p.setPen(QPen(Qt.GlobalColor.black, 1))
        p.drawRect(center.adjusted(-2, -2, 1, 1))
        p.setPen(QPen(Qt.GlobalColor.white, 1))
        p.drawRect(center.adjusted(-1, -1, 0, 0))

        # Подпись: координаты и цвет
        color = self.image.pixelColor(px, py)
        info = QRect(x, y + h, w, info_h)
        p.fillRect(info, QColor(24, 26, 30, 240))
        font = QFont()
        font.setPixelSize(14)
        p.setFont(font)
        p.setPen(QColor(235, 235, 235))
        p.drawText(info.adjusted(8, 4, -6, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                   f"x: {px}   y: {py}")
        swatch = QRect(x + 8, y + h + 27, 15, 15)
        p.fillRect(swatch, color)
        p.setPen(QPen(QColor(255, 255, 255, 180), 1))
        p.drawRect(swatch.adjusted(0, 0, -1, -1))
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor(255, 255, 255))
        p.drawText(info.adjusted(30, 26, -6, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                   color.name().upper())
        font.setBold(False)
        font.setPixelSize(13)
        p.setFont(font)
        p.setPen(QColor(190, 190, 190))
        p.drawText(info.adjusted(0, 27, -8, 0), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
                   f"{color.red()}, {color.green()}, {color.blue()}")

        # Внешняя рамка
        p.setPen(QPen(QColor(0, 0, 0, 160), 1))
        p.drawRect(whole.adjusted(-1, -1, 0, 0))
        p.setPen(QPen(ACCENT, 2))
        p.drawRect(whole.adjusted(0, 0, -1, -1))
        p.restore()

    # --- мышь и клавиатура -------------------------------------------------

    # --- панель действий под прошлой областью ------------------------------

    # 1.29: два ряда. Верх: шесть одинаковых плиток «значок сверху, подпись снизу» по частоте нажатий снизу вверх
    # (видео, снимок экрана, сохранить, текст, два перевода); низ: три главные кнопки, чем правее, тем шире:
    # «Редактировать», «Выделить заново», «Скопировать и закрыть». Клавиши на кнопках не пишутся: они в подсказке.
    BAR_BUTTONS = (("record", "selector.btn_record", "Ctrl+R"),
                   ("full", "selector.btn_full_shot", "Ctrl+A"),
                   ("ocr", "selector.btn_ocr", "Ctrl+T"),
                   ("translate", "selector.btn_translate", "Ctrl+L"),
                   ("translate_pick", "selector.btn_translate_pick", "Ctrl+P"),
                   ("save", "selector.btn_save", "Ctrl+S"),
                   ("edit", "selector.btn_edit", "Enter"),
                   ("manual", "selector.btn_retake", "selector.keys_retake"),
                   ("copy", "selector.btn_copy", "Ctrl+Enter"))
    # 1.29.1: сверху пять плиток, снизу четыре кнопки справа налево по частоте: «Скопировать и закрыть», «Выделить заново»,
    # «Редактировать», «Сохранить»; ширина по тексту, чем правее, тем шире; слева значок в цветном квадрате.
    BAR_TOP = ("record", "full", "ocr", "translate", "translate_pick")
    BAR_BOTTOM = ("save", "edit", "manual", "copy")
    BAR_WEIGHTS = {"save": 1.0, "edit": 1.2, "manual": 1.4, "copy": 1.65}

    @dynamic
    def BAR_SHORT(self):   # подписи узкого режима
        return {"manual": tr("selector.short_retake"), "copy": tr("selector.short_copy")}

    @dynamic
    def BAR_SUB(self):
        return {"save": tr("selector.sub_save_file"), "edit": tr("selector.sub_edit_frame"),
                "manual": tr("selector.sub_retake_empty"), "copy": tr("selector.sub_copy_clipboard"),
                "translate": tr("selector.sub_translate"), "translate_pick": tr("selector.sub_translate_pick")}
    BAR_ICONS = {"full": "fullscreen", "edit": "pencil", "copy": "copy", "save": "save", "record": "record",
                 "manual": "region", "ocr": "ocr", "translate": "translate", "translate_pick": "translate_pick"}
    # цвет у главных кнопок фоном, у плиток только значком
    BAR_ICON_COLORS = {"record": "#d92d20", "full": "#2a6df4", "save": "#5a6270", "ocr": "#7c3aed",
                       "translate": "#0d9488", "translate_pick": "#0d9488", "edit": "#0b6fd6", "manual": "#0b4fb3",
                       "copy": "#f4fff8"}
    BAR_SQUARE = {"save": ("#e3e6eb", "#5a6270"), "edit": ("#d6e7fc", "#0b6fd6"),   # цвет квадрата и значка нижних кнопок
                  "manual": ("#1e6fe0", "#ffffff"), "copy": ("#4fc487", "#ffffff")}

    def _bar_buttons(self):
        """Кнопки панели: верхний ряд, затем нижний. В режиме «весь экран» кнопки «Снимок всего экрана» нет."""
        out = []
        for b in self.BAR_BUTTONS:
            key = b[0]
            if self.full_mode and key == "full":
                continue
            if key == "ocr" and not getattr(self, "ocr_enabled", True):
                continue
            if key in ("translate", "translate_pick") and not self.translate_enabled():
                continue
            out.append((key, tr(b[1]), tr(b[2]) if b[2].startswith("selector.") else i18n_keys(b[2])))
        return out

    def _mon_list(self):
        """Мониторы слева направо: [(экран, прямоугольник в координатах окна)]."""
        screens = sorted(QGuiApplication.screens(), key=lambda s: (s.geometry().x(), s.geometry().y()))
        out = []
        for s in screens:
            g = s.geometry().translated(-self.origin).intersected(self.rect())
            if not g.isEmpty():
                out.append((s, g))
        return out

    def _selected_mon(self):
        """None: сняты все мониторы; число: номер монитора (с нуля) в _mon_list."""
        for i, (_s, g) in enumerate(self._mon_list()):
            if self.kept == g and g != self.rect():
                return i
        return None

    def select_monitor(self, sel):
        """Режим «весь экран»: все мониторы (None) или один из них. Вписанное выбранное окно убирается: в снимке
        экрана только то, что было на экране (проверка 1.33, В5)."""
        self._unpick()
        mons = self._mon_list()
        if sel is None:
            self.kept = QRect(self.rect())
        elif 0 <= sel < len(mons):
            self.kept = QRect(mons[sel][1])
        self._bar_forget()
        self.hover_button = None
        self.update()

    def _full_title(self):
        sel = self._selected_mon()
        return self.BAR_TITLE_FULL if sel is None else tr("selector.title_monitor", n=sel + 1)

    @dynamic
    def BAR_HINT(self):
        return tr("selector.hint_wide")

    @dynamic
    def BAR_HINT_SHORT(self):
        return tr("selector.hint_short")

    @dynamic
    def BAR_HINT_ICONS(self):
        return tr("selector.hint_icons")

    @dynamic
    def BAR_HINT_FULL(self):
        return tr("selector.hint_full")

    @dynamic
    def BAR_TITLE_FULL(self):
        return tr("selector.title_full")

    @dynamic
    def TR_HINTS(self):
        return (tr("selector.tr_hint_next_long"), tr("selector.tr_hint_next"), tr("selector.tr_hint_next_short"))

    @dynamic
    def TR_HINTS_FIRST(self):
        return (tr("selector.tr_hint_first_long"), tr("selector.tr_hint_first"), tr("selector.tr_hint_first_short"))
    BAR_PAD = 10       # поля панели (1.31.1: компактнее на 15%)
    BAR_GAP = 6        # промежутки между кнопками
    BAR_CROSS = 26     # крестик «Закрыть (Esc)» на правом верхнем углу панели

    # Размеры панели: подбираются по ширине экрана, не по рамке. «Широкая» и «средняя» с подписями, «узкая» значками.
    BAR_LEVELS = (
        {"name": "wide", "label": 12, "small": 10, "tile_h": 74, "btn_h": 52, "icon": 20, "tile_min": 114, "text": True,
         "bl": 15, "bs": 11, "sq": 32, "pl": 10, "gp": 9, "rm": 10},
        {"name": "mid", "label": 11, "small": 10, "tile_h": 70, "btn_h": 48, "icon": 18, "tile_min": 102, "text": True,
         "bl": 12, "bs": 10, "sq": 28, "pl": 7, "gp": 6, "rm": 5},
        {"name": "narrow", "label": 12, "small": 10, "tile_h": 34, "btn_h": 46, "icon": 18, "tile_min": 48, "text": False,
         "bl": 12, "bs": 10, "sq": 0, "pl": 12, "gp": 6},
    )

    def _bar_fonts(self, level=None):
        lv = level or self.BAR_LEVELS[0]
        label, small = QFont(), QFont()
        label.setPixelSize(lv["label"])
        label.setBold(True)
        small.setPixelSize(lv["small"])
        return label, small

    def _bar_bfonts(self, level):
        """Шрифты нижних кнопок: название жирное, пояснение мельче."""
        label, small = QFont(), QFont()
        label.setPixelSize(level["bl"])
        label.setBold(True)
        small.setPixelSize(int(level["bs"] + 0.5))   # 12,5 точек округляются до 13
        return label, small

    @staticmethod
    def _wrap(fm: QFontMetrics, text: str, width: float):
        """Слова в строки не шире width (жадно); слово длиннее строки остаётся целым."""
        lines, cur = [], ""
        for word in text.split():
            trial = (cur + " " + word).strip()
            if cur and fm.horizontalAdvance(trial) > width:
                lines.append(cur)
                cur = word
            else:
                cur = trial
        if cur:
            lines.append(cur)
        return lines

    def _bar_label(self, key, text, lv):
        return self.BAR_SHORT.get(key, text) if not lv["text"] or lv["name"] == "narrow" else text

    def _bar_hint_variants(self, lv):
        if self.full_mode:
            return (self.BAR_HINT_FULL,)
        if self.translate_mode:
            return self.TR_HINTS if self.tr_pieces else self.TR_HINTS_FIRST
        return {"wide": (self.BAR_HINT,), "mid": (self.BAR_HINT_SHORT,), "narrow": (self.BAR_HINT_ICONS,)}[lv["name"]]

    def _bar_sizes(self, lv):
        """Ширина содержимого рядов (без полей панели) и минимумы нижних кнопок на этом размере."""
        label_font, small_font = self._bar_fonts(lv)
        fm_l, fm_s = QFontMetrics(label_font), QFontMetrics(small_font)
        bl_font, bs_font = self._bar_bfonts(lv)
        fm_bl, fm_bs = QFontMetrics(bl_font), QFontMetrics(bs_font)
        keys = [b[0] for b in self._bar_buttons()]
        top = [k for k in self.BAR_TOP if k in keys]
        gap, pad = self.BAR_GAP, 14
        texts = {b[0]: b[1] for b in self._bar_buttons()}
        if lv["text"]:
            words = max([fm_l.horizontalAdvance(w) for k in top for w in texts[k].split()] or [0]) + 16
            sub = max(fm_s.horizontalAdvance(self.BAR_SUB[k]) for k in ("translate", "translate_pick") if k in top) + 14 \
                if "translate" in top else 0
            tile_min = max(lv["tile_min"], words, sub)
            mins = {}
            for k in self.BAR_BOTTOM:
                label = self._bar_label(k, texts[k], lv)
                widest = max(fm_bl.horizontalAdvance(label), fm_bs.horizontalAdvance(self.BAR_SUB[k]))
                # rm: right margin after the text; the middle size keeps it and the left padding pl small, so that on a 800 px screen the
                # labels still fit with a wider interface font (DejaVu Sans: XFCE, KDE, Ubuntu 22.04 without Ubuntu Sans)
                mins[k] = lv["pl"] + lv["sq"] + lv["gp"] + widest + lv.get("rm", 12)
        else:
            tile_min = lv["tile_min"]
            mins = {"save": 56, "edit": 56}
            for k in ("manual", "copy"):
                mins[k] = 2 * pad + lv["icon"] + 8 + fm_l.horizontalAdvance(self._bar_label(k, texts[k], lv))
        top_w = len(top) * tile_min + gap * max(0, len(top) - 1)
        bottom_w = sum(mins.values()) + (len(mins) - 1) * gap
        return max(top_w, bottom_w), mins, top

    def _bar_area(self):
        """Монитор, на котором стоит панель (в координатах окна)."""
        r = self.kept
        if self.full_mode or r is None:
            if self.bar_anchor is None:   # панель не прыгает, пока выбираешь монитор
                s0 = QGuiApplication.screenAt(QCursor.pos())
                self.bar_anchor = QRect(s0.geometry()) if s0 else QRect(self.origin, self.size())
            area = self.bar_anchor.translated(-self.origin)
        else:
            screen = QGuiApplication.screenAt(self.mapToGlobal(r.center()))
            area = screen.geometry().translated(-self.origin) if screen else self.rect()
        return area.intersected(self.rect()) if area.intersects(self.rect()) else self.rect()

    BAR_PLACES = ("below", "above", "right", "left")   # куда ставить панель вне рамки, по порядку (1.31.1)
    BAR_CHIP_H = 24        # высота чипа языка и шестерёнки в нижней строке
    BAR_SIDE_GAP = 12      # зазор между рамкой и панелью сбоку (ручки сторон выступают за рамку)
    BAR_HYSTERESIS = 20    # запас у порога: уйти с прежнего места на более выгодное можно, только если там с запасом

    def _bar_layout(self):
        """Где панель и её кнопки: [(ключ, подпись, клавиша, прямоугольник)], прямоугольник панели, строка подсказки.
        Панель стоит вне рамки, чтобы не закрывать выделенное: под ней, над ней, справа, слева; только если снаружи
        нигде не помещается (рамка почти во весь экран), внутри у нижнего края."""
        if (self.kept is None and not self.translate_mode) or self.kept is None or self.full_mode or self.bar_pos is not None:
            return self._bar_layout_for("below")
        prev = getattr(self, "_bar_place", None)
        order = list(self.BAR_PLACES)
        for i, place in enumerate(order):
            # на более «старшее» место, чем нынешнее, переходим только с запасом: панель не дёргается у порога
            slack = self.BAR_HYSTERESIS if prev in order and i < order.index(prev) else 0
            res = self._bar_layout_for(place, slack)
            if self._bar_ok:
                self._bar_place = place
                return res
        self._bar_place = "inside"
        return self._bar_layout_for("inside")

    def _bar_layout_for(self, place, slack=0):
        """Раскладка панели при заданном месте (below, above, right, left, inside); self._bar_ok: место подошло."""
        self._bar_ok = True
        if self.kept is None and not self.translate_mode:
            self.lang_rect = self.gear_rect = self.win_rect = QRect()
            return [], QRect(), QRect()
        r = self.kept
        full = self.full_mode
        area = self._bar_area()
        gap, bp = self.BAR_GAP, self.BAR_PAD
        room = area.width() - 8 - self.BAR_CROSS // 2   # запас справа под крестик, выступающий за угол
        side_room = None
        if place in ("right", "left") and r is not None:
            gapx = self.BAR_SIDE_GAP + slack
            if place == "right":
                side_room = area.right() - (r.right() + gapx) - self.BAR_CROSS // 2 - 4
            else:
                side_room = (r.left() - gapx) - (area.left() + 8)
            room = side_room
        for lv in self.BAR_LEVELS:
            inner, mins, top_keys = self._bar_sizes(lv)
            if inner + 2 * bp <= room:
                break
        self.bar_level = lv
        label_font, small_font = self._bar_fonts(lv)
        fm_s = QFontMetrics(small_font)
        title_h, base_h, chips = 0, 0, []
        chip_h, chip_gap = 30, 8
        bar_w = inner + 2 * bp
        if full:
            title_font = QFont()
            title_font.setPixelSize(26)
            title_font.setBold(True)
            title_h = base_h = QFontMetrics(title_font).height() + fm_s.height() + 18
            bar_w = max(bar_w, QFontMetrics(title_font).horizontalAdvance(self.BAR_TITLE_FULL + " 0") + 40)
            mons = self._mon_list()
            if len(mons) > 1:
                sel = self._selected_mon()
                chip_font = QFont()
                chip_font.setPixelSize(14)
                chip_font.setBold(True)
                fm_c = QFontMetrics(chip_font)
                chips.append(("mon:all", tr("selector.all_monitors"), sel is None))
                for i, (scr, _g) in enumerate(mons):
                    ph = scr.size() * scr.devicePixelRatio()
                    chips.append((f"mon:{i}", tr("selector.monitor_size", n=i + 1, w=round(ph.width()), h=round(ph.height())), sel == i))
                chip_ws = [fm_c.horizontalAdvance(t) + 24 for _k, t, _s in chips]
                chips_total = sum(chip_ws) + chip_gap * (len(chips) - 1)
                title_h += chip_h + 10
                bar_w = max(bar_w, chips_total + 40)
        if side_room is not None:
            if bar_w > side_room:
                self._bar_ok = False
        else:
            bar_w = min(bar_w, max(200, area.width() - 8 - self.BAR_CROSS // 2))
        inner = bar_w - 2 * bp
        # строка подсказки: самый полный вариант, который помещается в одну строку; иначе последний в две
        variants = self._bar_hint_variants(lv)
        bold_small = QFont(small_font)
        bold_small.setBold(True)
        fm_h = QFontMetrics(bold_small) if self.translate_mode else fm_s   # строка режима перевода жирная
        # чип языка справа в строке подсказки, левее размера «1040 × 600»; не помещается с названием: один глобус
        lang_w, gear_w, dims_w, reserve, win_w = 0, 0, 0, 0, 0
        if self.lang_ctx is not None:
            name = i18n.LANGUAGE_NAMES.get(i18n.current(), "")
            long_w = 8 + 14 + 5 + 21 + 5 + fm_s.horizontalAdvance(name + " ▾") + 8   # глобус, флаг, название
            if self.kept is not None and not full and lv["text"] and not self.translate_mode:
                dims_w = fm_s.horizontalAdvance("0000 × 0000") + 8
            # чип «Окна ▾» (21.11.2026): значок окна и подпись; места мало: один значок
            win_long = 0
            if self.windows_state is not None and not self.translate_mode and not full:
                win_long = 8 + 14 + 5 + fm_s.horizontalAdvance(tr("selector.win_chip") + " ▾") + 8
            win_short = 28 if win_long else 0
            lang_w, gear_w = long_w, 28
            for cand, wcand in ((long_w, win_long), (long_w, win_short), (28, win_short)):
                lang_w, win_w = cand, wcand
                reserve = cand + gear_w + 4 + dims_w + 6 + (wcand + 4 if wcand else 0)
                if any(fm_h.horizontalAdvance(t) + 24 <= inner - reserve for t in variants):
                    break
        text_room = inner - reserve
        hint_text = next((t for t in variants if fm_h.horizontalAdvance(t) + 24 <= text_room), variants[-1])
        hint_lines = 1 if fm_h.horizontalAdvance(hint_text) + 24 <= text_room else 2
        hint_h = hint_lines * fm_s.height() + (12 if self.translate_mode else 6)
        if lang_w and hint_lines == 1:
            hint_h = max(hint_h, self.BAR_CHIP_H + 4)   # чип языка и шестерёнка 24 px: удобно попадать мышью
        # строка перевода: кнопки языка, «Перевод/Оригинал», «Поверх текста/Карточкой», «Скопировать», «Ещё» (для окошка,
        # которое переведено последним или выбрано щелчком); не помещаются в ряд: переносятся
        ctl_units, ctl_rows, ctl_h = [], 0, 0
        if self.translate_mode and not full:
            ctl_units = self._tr_ctl_units(fm_h)
            row_w, ctl_rows = 0, 1
            for unit in ctl_units:
                uw = sum(w for _k, _t, w in unit)
                if row_w and row_w + 6 + uw > inner - 16:
                    ctl_rows += 1
                    row_w = 0
                row_w += (6 if row_w else 0) + uw
            ctl_h = ctl_rows * 26 + (ctl_rows - 1) * 6 + 8
            hint_h += ctl_h
        bh_tile, bh_btn = lv["tile_h"], lv["btn_h"]
        bar_h = bp + title_h + bh_tile + gap + bh_btn + gap + hint_h + 8
        if r is None:   # режим перевода без рамки: панель внизу монитора
            x = area.left() + (area.width() - bar_w) // 2
            y = area.bottom() - bar_h - 56
        else:
            x = max(area.left() + 8, min(r.center().x() - bar_w // 2, area.right() - bar_w - self.BAR_CROSS // 2 - 4))
            top_lim = area.top() + self.BAR_CROSS // 2 + 4
            if place == "below":
                y = r.top() + r.height() + 6                       # вплотную под рамкой
                self._bar_ok = y + bar_h <= area.bottom() - 4 - slack
            elif place == "above":
                # над рамкой; подпись размера «ш/в» стоит над левым углом, панель её не закрывает
                y = r.top() - bar_h - (36 if self.show_size else 6)
                self._bar_ok = y >= top_lim + slack
            elif place in ("right", "left"):
                gapx = self.BAR_SIDE_GAP
                x = r.left() + r.width() + gapx if place == "right" else r.left() - gapx - bar_w
                y = max(top_lim, min(r.center().y() - bar_h // 2, area.bottom() - bar_h - 4))
                self._bar_ok = self._bar_ok and bar_h <= area.height() - self.BAR_CROSS // 2 - 8 - slack
            else:
                # Снаружи нигде нет места: внутри рамки у нижнего края, с отступом от сторон (их можно тянуть)
                y = r.top() + r.height() - bar_h - 2 * self.GRIP - 4
                x = max(x, r.left() + 2 * self.GRIP + 4)
        if full:
            x = area.left() + (area.width() - bar_w) // 2
            y = area.top() + (area.height() - bar_h) // 2
        if self.bar_pos is not None:
            # Панель, перетащенная владельцем: остаётся там, где её оставили, в пределах монитора
            x = max(area.left(), min(self.bar_pos.x(), area.right() - bar_w - self.BAR_CROSS // 2))
            y = max(area.top() + self.BAR_CROSS // 2, min(self.bar_pos.y(), area.bottom() - bar_h + 1))
        bar = QRect(x, y, bar_w, bar_h)
        self.bar_title_rect = QRect(x + 12, y + 12, bar_w - 24, base_h - 6) if full else QRect()
        self.chip_rects = []
        if chips:
            shrink = min(1.0, (bar_w - 24) / chips_total)
            cx0 = x + (bar_w - int(chips_total * shrink)) // 2
            for (key, text, on), w in zip(chips, chip_ws):
                w = int(w * shrink)
                self.chip_rects.append((key, text, QRect(cx0, y + base_h + 10, w, chip_h), on))
                cx0 += w + int(chip_gap * shrink)
        buttons = []
        texts = {b[0]: (b[1], b[2]) for b in self._bar_buttons()}
        n = len(top_keys)
        tw = (inner - gap * (n - 1)) / n if n else 0
        ty = y + bp + title_h
        for i, key in enumerate(top_keys):
            tx = x + bp + round(i * (tw + gap))
            tx2 = x + bp + round((i + 1) * tw + i * gap)
            buttons.append((key, texts[key][0], texts[key][1], QRect(tx, ty, tx2 - tx, bh_tile)))
        by = ty + bh_tile + gap
        weights = [self.BAR_WEIGHTS[k] for k in self.BAR_BOTTOM]
        avail = inner - (len(self.BAR_BOTTOM) - 1) * gap
        widths = [avail * w / sum(weights) for w in weights]
        if any(w < mins[k] for w, k in zip(widths, self.BAR_BOTTOM)):
            extra = avail - sum(mins[k] for k in self.BAR_BOTTOM)
            widths = [mins[k] + extra * w / sum(weights) for k, w in zip(self.BAR_BOTTOM, weights)]
        bx = float(x + bp)
        for key, w in zip(self.BAR_BOTTOM, widths):
            left, right = round(bx), round(bx + w)
            buttons.append((key, texts[key][0], texts[key][1], QRect(left, by, right - left, bh_btn)))
            bx += w + gap
        hint = QRect(x + bp, by + bh_btn + gap, inner, hint_h - 2)
        self.bar_hint_text = hint_text
        self.bar_hint_reserve = reserve
        self.lang_rect = self.gear_rect = self.win_rect = QRect()
        if lang_w:
            ch = self.BAR_CHIP_H
            if hint_lines > 1:
                cy = hint.top() + 3
            elif self.translate_mode:
                cy = hint.top() + (fm_h.height() + 8 - ch) // 2   # по центру первой строки (бирюзовой)
            else:
                cy = hint.top() + (hint.height() - ch) // 2
            right = hint.right() - dims_w - (8 if self.translate_mode else 0)
            self.gear_rect = QRect(right - gear_w, cy, gear_w, ch)
            self.lang_rect = QRect(right - gear_w - 4 - lang_w, cy, lang_w, ch)
            if win_w:
                self.win_rect = QRect(self.lang_rect.left() - 4 - win_w, cy, win_w, ch)
        self.tr_ctl_rects = []
        if ctl_units:
            cur_x, cur_y = hint.left() + 8, hint.top() + hint_lines * fm_s.height() + 10
            for unit in ctl_units:
                uw = sum(w for _k, _t, w in unit)
                if cur_x > hint.left() + 8 and cur_x + uw > hint.right() - 8:
                    cur_x, cur_y = hint.left() + 8, cur_y + 32
                for key, text, w in unit:
                    self.tr_ctl_rects.append((key, text, QRect(cur_x, cur_y, w, 26)))
                    cur_x += w
                cur_x += 6
        # Крестик «Закрыть (Esc)» на правом верхнем углу панели, вне рядов
        size = self.BAR_CROSS
        self.bar_close_rect = QRect(bar.right() - size // 2 + 4, bar.top() - size // 2 + 3, size, size)
        return buttons, bar, hint

    BAR_DISABLED_IN_TR = ("copy", "edit", "save", "ocr", "record", "full")   # в режиме перевода не работают

    @dynamic
    def BAR_TR_BLOCKED(self):
        return tr("selector.tr_blocked")

    def _tr_ctl_state(self):
        """Состояние кнопок строки перевода по окошку, к которому они относятся: (окошко, карточка, готово, оригинал, вид)."""
        w = self._tr_current_win()
        card = w.tr_cards[0] if w is not None else None
        done = card is not None and card.state == "done"
        view = w._tr_view(card) if card is not None else "overlay"
        return w, card, done, bool(card is not None and card.show_original), view

    def _tr_ctl_units(self, fm):
        """Кнопки строки перевода группами (в группе кнопки вплотную): [[(ключ, подпись, ширина)]]."""
        from .translate import lang_name, target_lang
        w, card, done, _orig, _view = self._tr_ctl_state()
        tgt = lang_name(target_lang(self.tr_cfg))
        src = ""
        if card is not None and card.blocks and card.blocks[0]["src"]:
            src = lang_name(card.blocks[0]["src"])
        lang = f"{src} → {tgt} ▾" if src else tr("selector.tr_lang_to", lang=tgt)
        pad = 22
        spec = [[("trc:lang", lang)], [("trc:tr", tr("selector.trc_translation")), ("trc:orig", tr("selector.trc_original"))],
                [("trc:overlay", tr("selector.trc_overlay")), ("trc:card", tr("selector.trc_card"))],
                [("trc:copy", tr("selector.short_copy"))], [("trc:all", tr("selector.trc_all"))],
                [("trc:more", tr("selector.trc_more"))]]
        return [[(k, t, fm.horizontalAdvance(t) + pad) for k, t in group] for group in spec]

    def _tr_ctl_enabled(self, key) -> bool:
        w, card, done, _o, _v = self._tr_ctl_state()
        return bool(key in ("trc:more", "trc:all") or (w is not None and done))

    def _tr_ctl(self, key):
        """Нажата кнопка строки перевода: действие над выбранным окошком."""
        w, card, done, orig, view = self._tr_ctl_state()
        rect = next((r for k, _t, r in self.tr_ctl_rects if k == key), QRect())
        gpos = self.mapToGlobal(rect.bottomLeft())
        if key == "trc:all":
            self.start_translate_all()   # «Весь экран»: из верхнего ряда убран, живёт здесь и на Ctrl+Shift+L
            return
        if key == "trc:more":
            if w is not None:
                w._tr_more_menu_at(gpos, parent=self)
            return
        if w is None or not done:
            return
        if key == "trc:lang":
            w._tr_lang_menu_at(gpos, card, parent=self)
        elif key in ("trc:tr", "trc:orig"):
            card.show_original = key == "trc:orig"
            w.update()
        elif key in ("trc:overlay", "trc:card"):
            if view != key[4:]:
                w._tr_toggle_view(card)
        elif key == "trc:copy":
            w._tr_copy(card.text(), card.box().toAlignedRect())
        self.update()

    BAR_DRAG_THRESHOLD = 5   # протянули меньше: это щелчок по панели, а не перенос

    def _bar_free_at(self, pos: QPoint) -> bool:
        """Свободное место панели (фон, строка подсказки, промежутки), не кнопки: за него панель переносится.
        Ручка или сторона рамки под курсором (в том числе под панелью) всегда начинает изменение размера."""
        if (self.kept is None and not self.translate_mode) or self.start is not None or self.pending is not None \
                or self.resize_edge is not None:
            return False
        if self._edge_at(pos) is not None:
            return False   # ручки и стороны рамки важнее панели: нижние ручки заходят под панель
        buttons, bar, _hint = self._bar_layout()
        if not buttons or not bar.contains(pos):
            return False
        return self._button_at(pos) is None

    def _bar_forget(self):
        """Новая область, другой режим, другой монитор: панель встаёт на обычное место."""
        self.bar_pos = None
        self.bar_drag = None
        self.bar_dragging = False

    def _bar_check_after_frame_change(self):
        """Рамку изменили или перенесли: перетащенная панель остаётся, если не закрывает рамку, иначе на место."""
        if self.bar_pos is None or self.kept is None:
            return
        bar = self._bar_layout()[1]
        if bar.intersects(self.kept) and not self.full_mode:
            self.bar_pos = None

    def _button_at(self, pos: QPoint):
        if (self.kept is None and not self.translate_mode) or self.start is not None or self.pending is not None:
            return None
        buttons = self._bar_layout()[0]
        if buttons and self.bar_close_rect.adjusted(-3, -3, 3, 3).contains(pos):
            return "cancel"
        if buttons and not self.lang_rect.isEmpty() and self.lang_rect.contains(pos):
            return "lang"
        if buttons and not self.gear_rect.isEmpty() and self.gear_rect.contains(pos):
            return "settings"
        if buttons and not self.win_rect.isEmpty() and self.win_rect.contains(pos):
            return "window"
        for key, _text, _short, rect in buttons:
            if rect.contains(pos):
                return key
        for key, _text, rect, _on in self.chip_rects:
            if rect.contains(pos):
                return key
        for key, _text, rect in self.tr_ctl_rects:
            if rect.contains(pos):
                return key
        return None

    def _draw_action_bar(self, p: QPainter):
        """Светлая панель под рамкой: на затемнённом экране хорошо видна и читается как часть рамки."""
        from . import icons
        buttons, bar, hint = self._bar_layout()
        if not buttons:
            return
        lv = self.bar_level
        label_font, small_font = self._bar_fonts(lv)
        fm_l, fm_s = QFontMetrics(label_font), QFontMetrics(small_font)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        for i, alpha in ((8, 30), (5, 45), (2, 70)):   # тень
            p.setBrush(QColor(0, 0, 0, alpha))
            p.drawRoundedRect(QRectF(bar.adjusted(-i, -i + 3, i, i + 3)), 12 + i, 12 + i)
        p.setBrush(QColor(255, 255, 255))
        p.setPen(QPen(ACCENT, 2))
        p.drawRoundedRect(QRectF(bar).adjusted(1, 1, -1, -1), 11, 11)
        if self.full_mode and not self.bar_title_rect.isEmpty():
            title_font = QFont()
            title_font.setPixelSize(26)
            title_font.setBold(True)
            t = self.bar_title_rect
            line = QFontMetrics(title_font).height()
            p.setFont(title_font)
            p.setPen(QColor("#16181c"))
            p.drawText(QRect(t.left(), t.top(), t.width(), line), Qt.AlignmentFlag.AlignCenter, self._full_title())
            phys = self.to_physical(self.kept)
            screens = len(QGuiApplication.screens())
            sub = f"{phys.width()} × {phys.height()} px" + (tr("selector.monitors", n=screens) if screens > 1 and self._selected_mon() is None else "")
            p.setFont(small_font)
            p.setPen(QColor("#5a6270"))
            p.drawText(QRect(t.left(), t.top() + line + 2, t.width(), t.height() - line - 2),
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, sub)
        if self.chip_rects:
            chip_font = QFont()
            chip_font.setPixelSize(14)
            chip_font.setBold(True)
            p.setFont(chip_font)
            for key, text, rect, on in self.chip_rects:
                hover = key == self.hover_button
                if on:
                    p.setBrush(QColor(ACCENT))
                    p.setPen(QPen(QColor(ACCENT).darker(120), 1))
                    fg = QColor("#ffffff")
                else:
                    p.setBrush(QColor("#dbe6f7") if hover else QColor("#eceef2"))
                    p.setPen(QPen(QColor(ACCENT) if hover else QColor("#b8c0cc"), 1))
                    fg = QColor("#16181c")
                p.drawRoundedRect(QRectF(rect), 7, 7)
                p.setPen(fg)
                p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        hovered_text = None
        for key, text, short, rect in buttons:
            hover = key == self.hover_button
            blocked = self.translate_mode and key in self.BAR_DISABLED_IN_TR
            p.setOpacity(0.38 if blocked else 1.0)   # режим перевода: эти кнопки не работают, рисуются бледными
            if hover:
                hovered_text = self.BAR_TR_BLOCKED if blocked else f"{text} ({short})"
            tile = key in self.BAR_TOP
            active = key == "translate" and self.translate_mode   # режим перевода включён: плитка подсвечена
            if key == "copy":
                from .themes import GREEN, GREEN_BORDER, GREEN_GRADIENT, GREEN_GRADIENT_HOVER, GREEN_HOVER, GREEN_SHADOW, GREEN_SUB
                fill = QColor(GREEN_HOVER) if hover else QColor(GREEN)   # 1.32: зелёный темнее, белый текст читается
                if lv["text"]:   # зелёная: лёгкий градиент сверху вниз и тень
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(*GREEN_SHADOW))
                    p.drawRoundedRect(QRectF(rect).adjusted(1, 3, -1, 3), 9, 9)
                    top, bottom = GREEN_GRADIENT_HOVER if hover else GREEN_GRADIENT
                    grad = QLinearGradient(0, rect.top(), 0, rect.bottom())
                    grad.setColorAt(0, QColor(top))
                    grad.setColorAt(1, QColor(bottom))
                    fill = QBrush(grad)
                border, fg, sub = QColor(GREEN_BORDER), QColor("#ffffff"), QColor(*GREEN_SUB)
            elif key == "manual":
                fill = QColor("#d6e7fc") if hover else QColor("#e6f0fd")
                from .themes import BLUE_SUB
                border, fg, sub = QColor(ACCENT), QColor("#0f3a7d"), QColor(BLUE_SUB)   # 1.32: 5,2:1 и под курсором
            elif key == "edit":
                fill = QColor("#f1f6fd") if hover else QColor("#ffffff")
                border, fg, sub = QColor("#9ec1ee") if not hover else QColor(ACCENT), QColor("#16181c"), QColor("#5a6270")
            else:
                fill = QColor("#e4effb") if hover else QColor("#f5f6f8")
                from .themes import TILE_SUB
                border, fg, sub = QColor(ACCENT) if hover else QColor("#d9dde4"), QColor("#16181c"), QColor(TILE_SUB)   # 1.32: 5,2:1
                if active:
                    fill, border = QColor("#d6f1ec"), QColor("#0b8f84")
            p.setBrush(fill)
            p.setPen(QPen(border, 2 if (active or key == "manual") else 1))
            p.drawRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
            isize = lv["icon"]
            ic = icons.icon(self.BAR_ICONS[key], self.BAR_SQUARE[key][1] if (lv["text"] and not tile) else self.BAR_ICON_COLORS[key])
            if tile and not lv["text"]:
                ic.paint(p, QRect(rect.center().x() - isize // 2, rect.center().y() - isize // 2, isize, isize))
                continue
            if tile:
                # значок сверху, подпись снизу; вторая мелкая строка только у плитки «Перевести выделенное»
                lines = self._wrap(fm_l, text, rect.width() - 12)
                sub_text = self.BAR_SUB.get(key, "")
                total = isize + 4 + len(lines) * fm_l.height() + (fm_s.height() + 1 if sub_text else 0)
                top = rect.top() + (rect.height() - total) // 2
                ic.paint(p, QRect(rect.center().x() - isize // 2, top, isize, isize))
                p.setFont(label_font)
                p.setPen(fg)
                ty = top + isize + 4
                for ln in lines:
                    p.drawText(QRect(rect.left(), ty, rect.width(), fm_l.height()), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, ln)
                    ty += fm_l.height()
                if sub_text:
                    p.setFont(small_font)
                    p.setPen(QColor("#0b766c") if active else sub)
                    p.drawText(QRect(rect.left(), ty + 1, rect.width(), fm_s.height()), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, sub_text)
                continue
            # нижние кнопки: значок слева, справа подпись и (на широких размерах) вторая мелкая строка
            if not lv["text"] and key in ("save", "edit"):
                ic.paint(p, QRect(rect.center().x() - isize // 2, rect.center().y() - isize // 2, isize, isize))
                continue
            bl_font, bs_font = self._bar_bfonts(lv)   # свои имена: fm_l, fm_s, small_font нужны ниже строке режима перевода
            fm_bl, fm_bs = QFontMetrics(bl_font), QFontMetrics(bs_font)
            if lv["text"]:
                sq = lv["sq"]
                box = QRect(rect.left() + lv["pl"], rect.center().y() - sq // 2, sq, sq)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(self.BAR_SQUARE[key][0]) if key != "copy" else QColor(255, 255, 255, 70))
                p.drawRoundedRect(QRectF(box), 9, 9)
                ic.paint(p, QRect(box.center().x() - isize // 2, box.center().y() - isize // 2, isize, isize))
                tx = box.right() + 1 + lv["gp"]
            else:
                ic.paint(p, QRect(rect.left() + 14, rect.center().y() - isize // 2, isize, isize))
                tx = rect.left() + 14 + isize + 8
            label = self._bar_label(key, text, lv)
            sub_text = self.BAR_SUB[key] if lv["text"] else ""
            block = fm_bl.height() + (fm_bs.height() if sub_text else 0)
            ty = rect.top() + (rect.height() - block) // 2
            p.setFont(bl_font)
            p.setPen(fg)
            p.drawText(QRect(tx, ty, rect.right() - tx, fm_bl.height()), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
            if sub_text:
                p.setFont(bs_font)
                p.setPen(sub)
                p.drawText(QRect(tx, ty + fm_bl.height(), rect.right() - tx, fm_bs.height()), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, sub_text)
        p.setOpacity(1.0)
        p.setFont(small_font)
        flags = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap
        if self.translate_mode and not self.full_mode:
            # бирюзовая строка режима перевода
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#d6f1ec"))
            p.drawRoundedRect(QRectF(hint), 6, 6)
            bold = QFont(small_font)
            bold.setBold(True)
            p.setFont(bold)
            p.setPen(QColor("#0b5f57"))
            fm_b = QFontMetrics(bold)
            lines = 1 if fm_b.horizontalAdvance(self.bar_hint_text) + 24 <= hint.width() else 2
            text_h = lines * fm_b.height() + 8
            shown = self.BAR_TR_BLOCKED if self.hover_button in self.BAR_DISABLED_IN_TR else self.bar_hint_text
            if self.hover_button in ("lang", "settings", "window"):
                shown = self._chip_tip(self.hover_button)
            p.drawText(QRect(hint.left() + 8, hint.top(), hint.width() - 16 - self.bar_hint_reserve, text_h), flags, shown)
            w_cur, card_cur, _d, orig_cur, view_cur = self._tr_ctl_state()
            for key, text, rect in self.tr_ctl_rects:
                on = self._tr_ctl_enabled(key)
                hover = key == self.hover_button and on
                active = (key == "trc:orig" and orig_cur) or (key == "trc:tr" and not orig_cur and on) \
                    or (key == "trc:overlay" and view_cur == "overlay" and on) or (key == "trc:card" and view_cur == "card")
                p.setOpacity(1.0 if on else 0.4)
                p.setPen(QPen(QColor("#0b8f84"), 1))
                from .themes import TEAL_BUTTON
                p.setBrush(QColor(TEAL_BUTTON) if active else QColor("#ccefe9") if hover else QColor("#ffffff"))   # белый текст 5,5:1
                p.drawRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
                p.setPen(QColor("#ffffff") if active else QColor("#0b5f57"))
                p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
            p.setOpacity(1.0)
        else:
            p.setPen(QColor("#3c4350"))
            text = self.bar_hint_text
            if self.hover_button in ("cancel", "corner"):
                text = tr("selector.close_hint")
            elif self.hover_button in ("lang", "settings", "window"):
                text = self._chip_tip(self.hover_button)
            elif hovered_text:
                text = hovered_text   # название и клавиши кнопки под курсором
            elif self.kept is not None and not self.full_mode and lv["text"]:
                phys = self.to_physical(self.kept)
                dims = f"{phys.width()} × {phys.height()}"
                if fm_s.horizontalAdvance(text) + fm_s.horizontalAdvance(dims) + 24 + self.lang_rect.width() + self.gear_rect.width() \
                        + self.win_rect.width() + 4 <= hint.width():
                    p.drawText(hint, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, dims)
            p.drawText(hint.adjusted(0, 0, -self.bar_hint_reserve, 0), flags, text)
        self._draw_lang_chip(p, small_font)
        self._draw_close(p)
        p.restore()

    def _draw_lang_chip(self, p: QPainter, font):
        """Чип языка: глобус, название языка на нём самом и «▾»; места мало: один глобус."""
        from . import icons
        if self.lang_rect.isEmpty():
            return
        self._draw_gear(p)
        self._draw_win_chip(p, font)
        rect = self.lang_rect
        hover = self.hover_button == "lang"
        p.save()
        p.setOpacity(1.0)
        p.setBrush(QColor("#dbe6f7") if hover else QColor("#eceef2"))
        p.setPen(QPen(QColor(ACCENT) if hover else QColor("#b8c0cc"), 1))
        p.drawRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), 7, 7)
        long_form = rect.width() > 30
        ic_rect = QRect(rect.left() + (8 if long_form else (rect.width() - 14) // 2), rect.center().y() - 7, 14, 14)
        icons.icon("globe").paint(p, ic_rect)
        if long_form:
            fl = QRect(ic_rect.right() + 6, rect.center().y() - 7, 21, 14)   # флаг текущего языка (1.32), 24x16 в масштабе 7:8
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawPixmap(fl, icons.flag_icon(i18n.current()).pixmap(21 * 4, 14 * 4))
            p.setFont(font)
            p.setPen(QColor("#16181c"))
            name = i18n.LANGUAGE_NAMES.get(i18n.current(), "") + " ▾"
            p.drawText(QRect(fl.right() + 6, rect.top(), rect.right() - fl.right() - 8, rect.height()),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)
        p.restore()

    @staticmethod
    def _chip_tip(key):
        if key == "window":
            return f"{tr('selector.btn_window')} (W)"
        return language.menu_title() if key == "lang" else tr("app.menu_settings").rstrip("…")

    def _draw_win_chip(self, p: QPainter, font):
        """Чип «Окна ▾»: тот же вид, что у чипа языка; значок окна цветом плитки «Снимок всего экрана»."""
        from . import icons
        rect = self.win_rect
        if rect.isEmpty():
            return
        hover = self.hover_button == "window"
        p.save()
        p.setOpacity(1.0)
        p.setBrush(QColor("#dbe6f7") if hover else QColor("#eceef2"))
        p.setPen(QPen(QColor(ACCENT) if hover else QColor("#b8c0cc"), 1))
        p.drawRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), 7, 7)
        long_form = rect.width() > 30
        ic = QRect(rect.left() + (8 if long_form else (rect.width() - 14) // 2), rect.center().y() - 7, 14, 14)
        icons.icon("window", self.BAR_ICON_COLORS["full"]).paint(p, ic)
        if long_form:
            p.setFont(font)
            p.setPen(QColor("#16181c"))
            p.drawText(QRect(ic.right() + 6, rect.top(), rect.right() - ic.right() - 8, rect.height()),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, tr("selector.win_chip") + " ▾")
        p.restore()

    def _draw_gear(self, p: QPainter):
        """Шестерёнка «Настройки» рядом с чипом языка: тот же вид, один значок."""
        from . import icons
        rect = self.gear_rect
        hover = self.hover_button == "settings"
        p.save()
        p.setOpacity(1.0)
        p.setBrush(QColor("#dbe6f7") if hover else QColor("#eceef2"))
        p.setPen(QPen(QColor(ACCENT) if hover else QColor("#b8c0cc"), 1))
        p.drawRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), 7, 7)
        icons.icon("settings", "#3c4350").paint(p, QRect(rect.center().x() - 7, rect.center().y() - 7, 14, 14))
        p.restore()

    def _open_settings(self):
        """Шестерёнка: окно выделения закрывается без снимка (как Esc), настройки открываются, как из меню значка."""
        ctx = self.lang_ctx
        self._finish(None)
        if ctx is not None and hasattr(ctx, "open_settings"):
            QTimer.singleShot(0, ctx.open_settings)

    def _lang_menu(self):
        """Щелчок по чипу языка: то же меню, что у глобуса в редакторе; под чипом, а у нижнего края экрана над ним."""
        if self.lang_ctx is None or self.lang_rect.isEmpty():
            return
        menu = language.make_menu(self.lang_ctx, self)
        menu.ensurePolished()
        below = self.mapToGlobal(self.lang_rect.bottomLeft())
        above = self.mapToGlobal(self.lang_rect.topLeft())
        screen = QGuiApplication.screenAt(below) or QGuiApplication.primaryScreen()
        h = menu.sizeHint().height()
        pos = below if below.y() + h <= screen.availableGeometry().bottom() else QPoint(above.x(), above.y() - h)
        menu.exec(pos)
        menu.deleteLater()
        self.hover_button = None
        self.update()

    def _draw_close(self, p: QPainter):
        self._draw_cross(p, QRectF(self.bar_close_rect), self.hover_button == "cancel")

    @staticmethod
    def _draw_cross(p: QPainter, r: QRectF, hover: bool):
        """Крестик закрытия: светлый кружок, при наведении красный."""
        p.setPen(QPen(QColor("#b3261e") if hover else QColor("#9aa3b2"), 1.5))
        p.setBrush(QColor("#e5484d") if hover else QColor("#ffffff"))
        p.drawEllipse(r)
        m = r.width() * 0.32
        p.setPen(QPen(QColor("#ffffff") if hover else QColor("#3c4350"), max(2.4, r.width() / 13), Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(r.left() + m, r.top() + m), QPointF(r.right() - m, r.bottom() - m))
        p.drawLine(QPointF(r.right() - m, r.top() + m), QPointF(r.left() + m, r.bottom() - m))

    # --- «Снимок окна» (утверждено владельцем 21.11.2026) ---------------------------

    def _win_local(self, win) -> QRect:
        """Рамка окна в координатах окна выделения, обрезанная его краями."""
        return win.rect.translated(-self.origin).intersected(self.rect())

    def set_windows(self, wl):
        """Список окон пришёл (windows.WindowList). Окно выделения само в списке не нужно: на случай, если Shell
        успел его увидеть, выбрасывается окно этой же программы, накрывающее почти весь стол."""
        import os
        if self._done:
            return
        own, area = os.getpid(), QRect(self.origin, self.size())
        whole = area.width() * area.height() * 0.9

        def ours(w):
            r = w.rect.intersected(area)
            return w.pid == own and r.width() * r.height() >= whole
        self.windows = [w for w in wl.windows if not ours(w)]
        self.windows_complete = wl.complete
        self.windows_ext = wl.ext_state
        self.windows_failed = wl.failed
        self.windows_state = "ready"   # чип уже стоит с начала («loading»): панель не двигается, перетащенная остаётся
        if self._win_open_pending:
            busy = self.start is not None or self.translate_mode or self.pending is not None or self.tour is not None \
                or self.bar_drag is not None or self.resize_edge is not None or self.move_from is not None
            self._cancel_win_pending()
            if not busy:   # человек тем временем начал другое действие: меню посреди него не открывается
                self.open_window_list(keyboard=True)
        self.update()

    def _cancel_win_pending(self):
        if self._win_open_pending:
            self._win_open_pending = False
            from . import hints
            hints.hide_hint(self)

    def _menu_note(self, menu, text):
        """Строка-пояснение в меню: читаемая, но не пункт (клавиатура её пропускает)."""
        act = menu.addAction(text)
        act.setEnabled(False)
        act.setProperty("clipsd_note", True)
        return act

    def _window_menu(self):
        """Список окон: сверху вниз по наложению, по мониторам; свёрнутые в конце. Справа приглушённо: монитор (если
        их несколько) или «свёрнуто». Наведение на строку показывает рамку окна на экране. Дополнение GNOME старое
        или не стоит: сверху пояснение и пункт «Обновить» («Установить»), ниже неполный список окон XWayland."""
        from PyQt6.QtGui import QIcon
        from PyQt6.QtWidgets import QMenu
        from . import icons
        from .menus import style_menu
        from .windows import EXT_MISSING, EXT_OLD, EXT_SLOW
        menu = QMenu(self)
        cfg = self.tr_cfg if isinstance(getattr(self, "tr_cfg", None), dict) else {}
        style_menu(menu, cfg)
        menu.setObjectName("clipsdWindowList")
        if self.windows_ext in (EXT_OLD, EXT_MISSING):
            if self.window_ext_relogin:
                self._menu_note(menu, tr("selector.win_relogin"))
            else:
                old = self.windows_ext == EXT_OLD
                self._menu_note(menu, tr("selector.win_need_update" if old else "selector.win_need_install"))
                act = menu.addAction(QIcon(icons.icon("update", "#1e78ff")),
                                     tr("selector.win_do_update" if old else "selector.win_do_install"))
                act.setObjectName("clipsdUpdateExtension")
                act.triggered.connect(self._update_extension)
            menu.addSeparator()
        elif self.windows_ext == EXT_SLOW:
            self._menu_note(menu, tr("selector.win_slow"))   # Shell занят: список полный придёт позже
            menu.addSeparator()
        if self.windows_failed:
            self._menu_note(menu, tr("selector.win_failed"))
        wins = [w for w in self.windows if w.minimized or not self._win_local(w).isEmpty()]
        shown = [w for w in wins if not w.minimized]
        many = len({w.monitor for w in shown}) > 1
        groups = [[w for w in shown if w.monitor == m] for m in sorted({w.monitor for w in shown})] if many else [shown]
        groups.append([w for w in wins if w.minimized])
        groups = [g for g in groups if g]
        if not groups and not self.windows_failed:
            self._menu_note(menu, tr("selector.win_empty"))
        for gi, group in enumerate(groups):
            if gi:
                menu.addSeparator()
            for w in group:
                title = " ".join((w.title or tr("selector.win_untitled")).split())
                if len(title) > 64:
                    title = title[:63].rstrip() + "…"
                right = tr("selector.win_minimized") if w.minimized else (
                    tr("selector.win_monitor", n=w.monitor + 1) if many else "")
                act = menu.addAction(QIcon(self._app_badge(w)), title.replace("&", "&&") + (f"\t{right}" if right else ""))
                act.setData(w.id)
                act.hovered.connect(lambda w=w: self._preview(w))
                act.triggered.connect(lambda _c=False, w=w: self.pick_window(w))
                # свёрнутое окно в списке видно с пометкой, но не выбирается: его содержимого нет ни у GNOME (скрытое
                # окно рисуется чёрным), ни у Windows (PrintWindow), ни у X11; его надо сначала развернуть
                act.setEnabled(not w.minimized)
                act.setProperty("clipsd_soft", w.minimized)
        menu.aboutToHide.connect(self._window_menu_closed)
        return menu

    def _window_menu_closed(self):
        self.preview_win = None
        menu, self.win_menu = self.win_menu, None
        if menu is not None:
            menu.deleteLater()
        self.update()

    @staticmethod
    def _app_badge(win):
        """Значок программы: значок темы (GNOME) или первая буква на сером квадрате (цвета чипа панели)."""
        import os
        from PyQt6.QtGui import QIcon
        size = 40
        if win.icon and win.source == "gnome-ext":   # имя значка темы или путь к файлу значка
            themed = QIcon(win.icon) if os.path.isabs(win.icon) else QIcon.fromTheme(win.icon)
            if not themed.isNull():
                return themed.pixmap(size, size)
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(QColor("#b8c0cc"), 1.5))
        p.setBrush(QColor("#eceef2"))
        p.drawRoundedRect(QRectF(1, 1, size - 2, size - 2), 9, 9)
        f = QFont()
        f.setPixelSize(20)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#3c4350"))
        letter = (win.app or win.title or "?").strip()[:1].upper()
        p.drawText(QRect(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, letter)
        p.end()
        return pm

    def _preview(self, win):
        self.preview_win = win if (win is not None and not win.minimized) else None
        self.update()

    def _window_menu_pos(self, menu) -> QPoint:
        """Под чипом «Окна ▾» (у нижнего края экрана над ним), если панель видна; иначе вверху по центру монитора
        под мышью."""
        h, w = menu.sizeHint().height(), menu.sizeHint().width()
        if not self.win_rect.isEmpty() and self.kept is not None:
            below = self.mapToGlobal(self.win_rect.bottomLeft() + QPoint(0, 4))
            screen = QGuiApplication.screenAt(below) or QGuiApplication.primaryScreen()
            if below.y() + h <= screen.availableGeometry().bottom():
                return below
            above = self.mapToGlobal(self.win_rect.topLeft())
            return QPoint(above.x(), above.y() - h - 4)
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        g = screen.availableGeometry()
        return QPoint(g.center().x() - w // 2, g.top() + 60)

    def open_window_list(self, keyboard=False):
        """Чип «Окна ▾» или клавиша W. Список ещё не пришёл: подсказка «готовится», меню откроется, когда придёт.
        С клавиатуры сразу выделена первая строка (верхнее окно), стрелки и Enter, Esc закрывает только список."""
        if self.windows_state is None or self.pending is not None or self.tour is not None or self._done:
            return
        if self.win_menu is not None:
            return
        if self.windows_state == "loading":
            self._win_open_pending = True
            from . import hints
            hints.hint(self, tr("selector.win_loading"))
            return
        menu = self._window_menu()
        menu.ensurePolished()
        self.win_menu = menu
        menu.popup(self._window_menu_pos(menu))
        if keyboard:
            first = next((a for a in menu.actions() if a.isEnabled() and not a.isSeparator() and a.data() is not None),
                         None)
            if first is not None:
                menu.setActiveAction(first)
        self.hover_button = None
        self.update()

    def _close_window_menu(self):
        if self.win_menu is not None:
            self.win_menu.close()

    def _update_extension(self):
        """«Обновить» («Установить») в списке окон: окно выделения закрывается без снимка (как шестерёнка),
        программа ставит дополнение и объясняет, что дальше."""
        ctx = self.lang_ctx
        self._finish(None)
        if ctx is not None and hasattr(ctx, "update_gnome_extension"):
            QTimer.singleShot(0, ctx.update_gnome_extension)

    def pick_window(self, win):
        """Рамка встаёт ровно на выбранное окно; панель как обычно (Enter, Ctrl+Enter, кнопки). При выходе рамка
        запоминается как прошлая область: следующий снимок начнётся с того же места. Окно закрыто другими: его
        собственное содержимое просится у источника и вписывается в замороженный кадр, настоящие окна не трогаются.
        Свёрнутое окно не выбирается (содержимого нет): подсказка «разверните»."""
        from . import hints
        from .windows import is_covered
        if self._done or self.pending is not None:
            return
        rect = self._win_local(win)
        if win.minimized or rect.width() < 3 or rect.height() < 3:
            hints.hint(self, tr("selector.win_min_failed" if win.minimized else "selector.win_offscreen"),
                       tr("selector.win_min_failed_sub") if win.minimized else "")
            return
        self._unpick()
        self.preview_win = None
        self.picked_win = win
        self.full_mode = False
        self.bar_anchor = None
        self.kept = rect
        self._bar_forget()
        self.hover_button = None
        if is_covered(win, self.windows):
            if self.window_grab is not None:
                self._lift_start(win)
            else:   # X11 и GNOME без нового дополнения: содержимое окна под другими взять неоткуда
                hints.hint(self, tr("selector.win_visible_only"))
        self.update()

    def _unpick(self):
        """Снять выбор окна: кадр без вписанного окна, поздний ответ с содержимым окна не нужен."""
        self._lift = None
        self._lift_pixmap = None
        self.picked_win = None
        if self._desktop_orig is not None:
            self.desktop, self._desktop_orig = self._desktop_orig, None
            self.image = self.desktop.toImage()

    def _lift_start(self, win):
        try:
            job = self.window_grab(win)
        except Exception:   # noqa: BLE001 — источник не смог даже начать: остаётся кадр как есть
            job = None
        if job is None:
            self._lift_done(None, win, None)
            return
        self._lift = job
        job.done.connect(lambda pm, job=job, win=win: self._lift_done(job, win, pm))
        job.start()

    def _lift_done(self, job, win, pixmap):
        """Содержимое выбранного окна пришло (или нет). Ответ на прежний выбор отбрасывается."""
        from . import hints
        if self._done or (job is not None and job is not self._lift) or self.picked_win is not win:
            return
        self._lift = None
        if pixmap is not None and not pixmap.isNull():
            if self.desktop is None:
                self._lift_pixmap = pixmap   # кадр стола ещё не пришёл: впишется в set_desktop
            else:
                self._paint_lifted(win, pixmap)
                self.image = self.desktop.toImage()
        else:
            hints.hint(self, tr("selector.win_closed"))   # окно закрылось после Alt+W: снимается то, что было видно
        if self.pending is not None and self.desktop is not None:
            self._emit(self.pending)
            return
        self.update()

    def _paint_lifted(self, win, pixmap):
        """Вписать содержимое окна в замороженный кадр на место окна (как будто его подняли наверх)."""
        base = self._desktop_orig if self._desktop_orig is not None else self.desktop
        self._desktop_orig = base
        out = QPixmap(base)
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.drawPixmap(QRectF(win.rect.translated(-self.origin)), pixmap, QRectF(pixmap.rect()))
        p.end()
        self.desktop = out
        self._lift_pixmap = None

    def _draw_window_preview(self, p: QPainter):
        """Рамка окна под курсором списка: вокруг затемнено, само окно светлое, размер в пикселях."""
        r = self._win_local(self.preview_win)
        p.setClipRegion(QRegion(self.rect()).subtracted(QRegion(r)))
        p.fillRect(self.rect(), DIM)
        p.setClipping(False)
        p.setPen(QPen(ACCENT, self.FRAME_W))
        p.setBrush(Qt.BrushStyle.NoBrush)
        fw = self.FRAME_W
        p.drawRect(QRectF(r).adjusted(fw / 2, fw / 2, -fw / 2, -fw / 2))
        if self.show_size:
            phys = self.to_physical(r)
            self._draw_label(p, tr("selector.size_label", w=phys.width(), h=phys.height()), r.topLeft(), above=True)
        if self.kept is not None:
            self._draw_action_bar(p)   # список открыт с панели: панель остаётся на месте

    def clear_kept(self):
        """«Выделить вручную»: прошлая рамка и панель исчезают, область выделяется мышью с нуля."""
        self.kept = None
        self._unpick()
        self.full_mode = False
        self.bar_anchor = None
        self._bar_forget()
        self.hover_button = None
        self.move_from = None
        self.resize_edge = None
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.update()

    def show_full_screen(self):
        """Кнопка «Весь экран»: весь стол с рамкой по краю, надпись и кнопки в центре. Вписанное выбранное окно
        убирается: в снимке экрана только то, что было на экране (проверка 1.33, В5)."""
        self._unpick()
        self.kept = QRect(self.rect())
        self.full_mode = True
        self.bar_anchor = None
        self._bar_forget()
        self.start = None
        self.hover_button = None
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.update()

    def enter_translate(self, hint=True):
        """Режим перевода: панель остаётся (плитка перевода подсвечена), внизу бирюзовая строка. Рамки нет."""
        self._cancel_win_pending()   # список окон, попрошенный раньше, в режиме перевода не открывается
        if not self.translate_mode:
            self.tr_pieces = 0
            self.bar_anchor = None
            self._bar_forget()
        super().enter_translate(hint=False)   # подсказка теперь в строке панели

    def start_translate(self):
        """Кнопка «Перевести выделенное» и Ctrl+L: стоящая рамка (не «весь экран») переводится сразу, без повторного
        выделения; окно НЕ закрывается: любая следующая обведённая область тоже переводится."""
        region = QRect(self.kept) if self.kept is not None and not self.full_mode else None
        ready = region is not None and region.width() >= 8 and region.height() >= 8
        self.enter_translate()
        if ready:
            self._tr_spawn_floating(region)

    def start_translate_pick(self):
        """Кнопка «Выделить и перевести» и Ctrl+P: режим перевода без перевода стоящей рамки; обведённое место переводится.
        Вписанное выбранное окно убирается: новое место переводится таким, каким было на экране."""
        self._unpick()
        self.enter_translate()

    def _tr_after_spawn(self, spawned=True, full=False, win=None):
        if full:
            self._finish(None)   # весь экран: окно выделения закрывается, как в 1.28 (Esc окошка ожидания отменяет перевод)
            return
        if spawned:
            self.tr_pieces += 1
            if win is not None:
                self.tr_current = win
                win.select_hook = self._tr_select
                win.more_hook = self._tr_more_piece
                win.tr_state_hook = self._tr_float_changed
                self._tr_avoid_windows()
        self.update()

    def _tr_backdrop(self):
        if self.image is None or self.image.isNull():
            return None
        return (self.image, QPoint(self.origin), self.ratio)

    def _tr_select(self, win):
        """Щелчок по окошку: кнопки панели относятся к нему."""
        from PyQt6 import sip
        if sip.isdeleted(self):
            return
        if win is not self.tr_current:
            self.tr_current = win
            self.update()

    def _tr_float_changed(self):
        from PyQt6 import sip
        if sip.isdeleted(self) or self._done:
            return
        self._tr_avoid_windows()
        self.update()

    def _tr_current_win(self):
        """Окошко для кнопок строки перевода: выбранное или последнее живое."""
        from PyQt6 import sip
        alive = [w for w in getattr(self, "spawned", []) if not sip.isdeleted(w) and not w._done and w.tr_cards]
        if self.tr_current in alive:
            return self.tr_current
        return alive[-1] if alive else None

    def _tr_more_piece(self):
        """«Перевести ещё кусок» из меню «Ещё» окошка: окно выделения открыто, режим перевода включается в нём."""
        from PyQt6 import sip
        if sip.isdeleted(self) or self._done:
            if callable(translate_ui.FloatingTranslation.request_more):
                translate_ui.FloatingTranslation.request_more()
            return
        if not self.translate_mode:
            self.enter_translate()
        self.update()

    def _tr_avoid_windows(self):
        """Окошки перевода не ложатся на панель окна выделения: панель переезжает на свободное место (если её не
        перетащил сам владелец)."""
        if not self.translate_mode or self.bar_user or self.full_mode:
            return
        from PyQt6 import sip
        wins = [w.frameGeometry() for w in getattr(self, "spawned", []) if not sip.isdeleted(w) and not w._done]
        if not wins:
            return
        self.bar_pos = None
        bar0 = self._bar_layout()[1]
        bar = bar0.united(self.bar_close_rect)   # крестик на углу панели тоже не под окошками

        def local(g):
            return QRect(self.mapFromGlobal(g.topLeft()), g.size())
        rects = [local(g) for g in wins]

        def hit(r):
            return sum(max(0, r.intersected(w).width()) * max(0, r.intersected(w).height()) for w in rects)
        if not hit(bar):
            return
        area = self._bar_area()
        cands = []
        for y in (area.top() + 14, area.bottom() - bar.height() - 56, area.top() + (area.height() - bar.height()) // 2):
            for x in (bar.left(), area.left() + 8, area.right() - bar.width() - 20):
                cands.append(QPoint(max(area.left(), min(x, area.right() - bar.width() - 14)), max(area.top() + 14, y)))
        best = min(cands, key=lambda pt: hit(QRect(pt, bar.size())))
        if hit(QRect(best, bar.size())) < hit(bar):
            self.bar_pos = best + (bar0.topLeft() - bar.topLeft())

    def _tr_close_mode(self):
        """Esc в режиме перевода: режим завершается, окошки перевода остаются, окно выделения ждёт новую область.
        Второй Esc закрывает окно выделения."""
        if self.translate_mode:
            self.translate_mode = False
            for w in list(getattr(self, "spawned", [])):   # режим завершён: окошкам возвращаются плашки (снаружи области)
                try:
                    w.enable_chip()
                except RuntimeError:
                    pass
            self.tr_start = self.tr_cur = None
            self.tr_pieces = 0
            self.kept = None
            self.start = None
            self.hover_button = None
            self.bar_anchor = None
            self._bar_forget()
            self.setCursor(Qt.CursorShape.CrossCursor)
            self.update()
        else:
            self._finish(None)

    def _tr_all_text(self) -> str:
        """Ctrl+C в режиме перевода: переводы всех окошек этого окна выделения."""
        from PyQt6 import sip
        return "\n\n".join(w.tr_cards[0].text() for w in getattr(self, "spawned", [])
                            if not sip.isdeleted(w) and not w._done and w.tr_cards and w.tr_cards[0].state == "done"
                            and w.tr_cards[0].text())

    def _tr_leave_for_browser(self):
        self._finish(None)   # сайт открывается в браузере: окно выделения поверх всего закрывается совсем

    def _tr_bar_do(self, key):
        """Кнопка панели в режиме перевода: «Перевести весь экран» (окно закрывается, как в 1.28), «Закрыть», «Выделить заново»
        (выход из режима), кнопки строки перевода; остальные в режиме перевода не работают (нарисованы бледными)."""
        if key.startswith("trc:"):
            self._tr_ctl(key)
        elif key == "lang":
            self._lang_menu()
        elif key == "settings":
            self._open_settings()
        elif key == "cancel":
            self._finish(None)
        elif key == "manual" or key.startswith("mon:"):
            self._tr_close_mode()

    def _tr_full_rect(self) -> QRect:
        """Монитор для «Перевести весь экран»: тот, на котором рамка (или выбранный монитор), иначе под курсором."""
        screen = None
        if self.kept is not None and not self.full_mode:
            screen = QGuiApplication.screenAt(self.mapToGlobal(self.kept.center()))
        elif self.full_mode:
            sel = self._selected_mon()
            mons = self._mon_list()
            if sel is not None and sel < len(mons):
                screen = mons[sel][0]
            elif self.bar_anchor is not None:
                screen = QGuiApplication.screenAt(self.bar_anchor.center())
        if screen is None:
            screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        geo = screen.geometry().translated(-self.origin) if screen else self.rect()
        return geo.intersected(self.rect())

    def start_translate_all(self):
        """Кнопка «Перевести весь экран» и Ctrl+Shift+L: монитор переводится сразу, без выделения мышью."""
        self._unpick()
        rect = self._tr_full_rect()
        self.enter_translate(hint=False)
        self.tr_translate_all(rect)

    def hint_anchor(self) -> QRect:
        """Где стоят подсказки действий: монитор, на котором курсор (окно выделения закрывает все мониторы)."""
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        area = screen.geometry().translated(-self.origin) if screen else self.rect()
        return area.intersected(self.rect())

    def _do(self, action):
        if action == "cancel":
            self._finish(None)
            return
        if action == "lang":
            self._lang_menu()
            return
        if action.startswith("mon:"):
            v = action[4:]
            self.select_monitor(None if v == "all" else int(v))
            return
        if action == "manual":
            self.clear_kept()
            return
        if action == "full":
            self.show_full_screen()
            return
        if action == "window":
            self.open_window_list()
            return
        if action == "translate":
            self.start_translate()
            return
        if action == "translate_pick":
            self.start_translate_pick()
            return
        if action == "settings":
            self._open_settings()
            return
        self.action = action
        # Запись видео ведёт встроенная запись системы: наш снимок не нужен, окно выделения просто закрываем
        self._finish(None if action == "record" else self.kept)

    def _tr_bar_press(self, event) -> bool:
        """Режим перевода: нажатие на кнопку панели или на её свободное место (перенос панели)."""
        if event.button() != Qt.MouseButton.LeftButton or self.tr_start is not None or self.tr_drag is not None:
            return False
        pos = event.position().toPoint()
        button = self._button_at(pos)
        if button:
            self._tr_bar_do(button)
            return True
        if self._bar_free_at(pos):
            self.bar_drag = (pos, self._bar_layout()[1].topLeft())
            self.bar_dragging = False
            self.bar_user = True   # дальше панель сама не переезжает от окошек
            return True
        return False

    def _tr_bar_move(self, event) -> bool:
        pos = event.position().toPoint()
        if self.bar_drag is not None:
            start, origin = self.bar_drag
            delta = pos - start
            if self.bar_dragging or abs(delta.x()) + abs(delta.y()) > self.BAR_DRAG_THRESHOLD - 1:
                self.bar_dragging = True
                self.bar_pos = origin + delta
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            self.update()
            return True
        if self.tr_start is not None or self.tr_drag is not None:
            return False
        hover = self._button_at(pos)
        if hover != self.hover_button:
            self.hover_button = hover
            self.update()
        if hover:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            return True
        if self._bar_free_at(pos):
            self.setCursor(Qt.CursorShape.SizeAllCursor)
            return True
        return False

    def mousePressEvent(self, event):
        if self.translate_mode and self._tr_bar_press(event):
            return
        if self._tr_press(event):
            return
        if self.pending is not None:
            return
        pos = event.position().toPoint()
        if event.button() == Qt.MouseButton.LeftButton and self._corner_at(pos):
            self._finish(None)   # крестик в углу экрана
            return
        if event.button() == Qt.MouseButton.LeftButton and self._bar_free_at(pos):
            self.bar_drag = (pos, self._bar_layout()[1].topLeft())   # свободное место панели: схватить и тащить
            self.bar_dragging = False
            return
        on_edge = self._edge_at(pos) is not None   # стороны и углы рамки важнее кнопок
        button = self._button_at(pos) if event.button() == Qt.MouseButton.LeftButton and not on_edge else None
        if button:
            self._do(button)
            return
        if event.button() == Qt.MouseButton.RightButton:
            self._finish(None)
        elif event.button() == Qt.MouseButton.LeftButton and self._edge_at(event.position().toPoint()):
            self.resize_edge = self._edge_at(event.position().toPoint())
            self.moved = False
        elif event.button() == Qt.MouseButton.LeftButton and self.full_mode:
            # Весь экран, но нажали мимо кнопок: выделяется обычная область
            self._unpick()
            self._cancel_win_pending()
            self.full_mode = False
            self.bar_anchor = None
            self._bar_forget()
            self.kept = None
            self.start = event.position().toPoint()
            self.cursor_pos = self.start
            self.update()
        elif event.button() == Qt.MouseButton.LeftButton and self.kept is not None \
                and self.kept.contains(event.position().toPoint()):
            self.move_from = event.position().toPoint()
            self.moved = False
        elif event.button() == Qt.MouseButton.LeftButton:
            self.kept = None
            self._unpick()
            self._cancel_win_pending()   # начато выделение мышью: попрошенный раньше список окон уже не нужен
            self._bar_forget()
            self.start = event.position().toPoint()
            self.cursor_pos = self.start
            self.update()

    def mouseMoveEvent(self, event):
        if self.translate_mode and self._tr_bar_move(event):
            return
        if self._tr_move(event):
            return
        if self.pending is not None:
            return
        pos = event.position().toPoint()
        if self.bar_drag is not None:
            start, origin = self.bar_drag
            delta = pos - start
            if self.bar_dragging or abs(delta.x()) + abs(delta.y()) > self.BAR_DRAG_THRESHOLD - 1:
                self.bar_dragging = True
                self.bar_pos = origin + delta
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            self.cursor_pos = pos
            self.update()
            return
        if self.resize_edge is not None:
            self.kept = self._resized(pos)
            self.moved = True
        elif self.move_from is not None:
            delta = pos - self.move_from
            if self.moved or abs(delta.x()) + abs(delta.y()) > 3:
                moved = self.kept.translated(delta)
                moved.moveLeft(max(0, min(moved.left(), self.width() - moved.width())))
                moved.moveTop(max(0, min(moved.top(), self.height() - moved.height())))
                self.kept, self.move_from, self.moved = moved, pos, True
        elif self._corner_at(pos):
            self.hover_button = "corner"
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        elif self.kept is not None and self.start is None:
            free = self._bar_free_at(pos)
            hover = None if (free or self._edge_at(pos)) else self._button_at(pos)
            if hover != self.hover_button:
                self.hover_button = hover
            if free:
                self.setCursor(Qt.CursorShape.SizeAllCursor)   # панель можно перетащить
            else:
                self.setCursor(Qt.CursorShape.PointingHandCursor if hover else self._cursor_for(pos))
        elif self.hover_button == "corner":
            self.hover_button = None
            self.setCursor(Qt.CursorShape.CrossCursor)
        self.cursor_pos = pos
        self.update()

    def mouseReleaseEvent(self, event):
        if self.translate_mode and event.button() == Qt.MouseButton.LeftButton and self.bar_drag is not None:
            self.bar_drag = None
            self.bar_dragging = False
            self.update()
            return
        if self._tr_release(event):
            return
        if event.button() == Qt.MouseButton.LeftButton and self.bar_drag is not None:
            self.bar_drag = None
            self.bar_dragging = False
            self.update()
            return
        if event.button() == Qt.MouseButton.LeftButton and self.resize_edge is not None:
            self.resize_edge = None   # размер изменён; снять: Enter или клик внутри
            self._bar_check_after_frame_change()
            self.update()
            return
        if event.button() == Qt.MouseButton.LeftButton and self.move_from is not None:
            self.move_from = None
            if not self.moved:
                self._finish(self.kept)   # клик внутри прошлой области — снять её
            else:
                self._bar_check_after_frame_change()
            return
        if event.button() != Qt.MouseButton.LeftButton or self.start is None or self.pending is not None:
            return
        self.cursor_pos = event.position().toPoint()
        sel = self.selection()
        if sel.width() < 3 or sel.height() < 3:
            # Простой клик без протягивания — монитор под курсором, но не сразу: сначала рамка по краю,
            # надпись «Снимок всего экрана» и кнопки в центре, иначе случайный клик незаметно снимал экран.
            screen = QGuiApplication.screenAt(self.mapToGlobal(self.cursor_pos))
            geo = screen.geometry() if screen else QGuiApplication.primaryScreen().geometry()
            self.start = None
            self.kept = geo.translated(-self.origin).intersected(self.rect())
            self.full_mode = True
            self.bar_anchor = None
            self._bar_forget()
            self.update()
            return
        self._finish(sel)

    @staticmethod
    def _is_r_key(event) -> bool:
        """Клавиша R без Ctrl и других модификаторов на любой раскладке: по символу (r или «к»), по физической клавише
        (X11: код 27; Windows: виртуальный код 0x52)."""
        if event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
                                | Qt.KeyboardModifier.MetaModifier):
            return False
        if event.key() == Qt.Key.Key_R or event.text().lower() in ("r", "к"):
            return True
        try:
            if sys.platform == "win32":
                return event.nativeVirtualKey() == 0x52
            return event.nativeScanCode() == 27
        except (AttributeError, TypeError):
            return False

    @staticmethod
    def _is_w_key(event) -> bool:
        """Клавиша W без модификаторов на любой раскладке: по символу (w или «ц») и по физической клавише
        (X11: код 25; Windows: виртуальный код 0x57)."""
        if event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
                                | Qt.KeyboardModifier.MetaModifier):
            return False
        if event.key() == Qt.Key.Key_W or event.text().lower() in ("w", "ц"):
            return True
        try:
            if sys.platform == "win32":
                return event.nativeVirtualKey() == 0x57
            return event.nativeScanCode() == 25
        except (AttributeError, TypeError):
            return False

    def keyPressEvent(self, event):
        if self.tour is not None:
            self.tour.key(event)   # пока идёт знакомство, горячие клавиши окна выделения ничего не снимают
            return
        if event.key() == Qt.Key.Key_P and event.modifiers() == Qt.KeyboardModifier.ControlModifier \
                and self.translate_enabled() and self.pending is None and (self.kept is not None or self.translate_mode):
            self.start_translate_pick()   # Ctrl+P: выделить другое место и перевести
            return
        if self.translate_mode and event.key() == Qt.Key.Key_L and self.translate_enabled() and self.pending is None \
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier \
                and event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.start_translate_all()   # Ctrl+Shift+L и в режиме «выделите кусок»: переход на весь экран
            return
        if self._tr_key(event):
            return
        if event.key() == Qt.Key.Key_L and event.modifiers() & Qt.KeyboardModifier.ControlModifier \
                and self.translate_enabled() and self.pending is None:
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.start_translate_all()   # Ctrl+Shift+L: весь экран
            else:
                self.start_translate()       # Ctrl+L: выделенное
            return
        if self._is_w_key(event) and self.windows_state is not None and self.pending is None and self.start is None \
                and not self.translate_mode:
            self.open_window_list(keyboard=True)   # W, как в окне снимков GNOME: список окон
            return
        if event.key() == Qt.Key.Key_Escape:
            self._finish(None)
        elif (event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) or self._is_r_key(event)) and self.kept is not None \
                and self.start is None and self.pending is None:
            self.clear_kept()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space) and self.kept is not None \
                and self.start is None and self.pending is None:
            # Ctrl+Enter: скопировать и закрыть, как в редакторе; просто Enter: редактировать
            ctrl = event.modifiers() & Qt.KeyboardModifier.ControlModifier
            self._do("copy" if ctrl and event.key() != Qt.Key.Key_Space else "edit")
        elif event.modifiers() & Qt.KeyboardModifier.ControlModifier and self.kept is not None \
                and self.start is None and self.pending is None \
                and event.key() in (Qt.Key.Key_C, Qt.Key.Key_S, Qt.Key.Key_R, Qt.Key.Key_T):
            action = {Qt.Key.Key_C: "copy", Qt.Key.Key_S: "save", Qt.Key.Key_R: "record", Qt.Key.Key_T: "ocr"}[event.key()]
            if action != "ocr" or getattr(self, "ocr_enabled", True):   # распознавание выключено: Ctrl+T ничего не делает
                self._do(action)
        elif self.full_mode and self.start is None and self.pending is None and len(self._mon_list()) > 1 \
                and not event.modifiers() and Qt.Key.Key_0 <= event.key() <= Qt.Key.Key_9:
            n = event.key() - Qt.Key.Key_0   # 0: все мониторы, 1..9: монитор по номеру
            self.select_monitor(None if n == 0 else n - 1)
        elif event.modifiers() & Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_A \
                and self.start is None and self.pending is None:
            self.show_full_screen()

    def _finish(self, sel):
        if self._done:
            return
        if sel is not None and (self.desktop is None or self._lift is not None):
            # дождаться снимка (set_desktop) или содержимого выбранного окна (_lift_done) и тогда вырезать
            self.pending = sel
            self.update()
            return
        self._emit(sel)

    def _emit(self, sel):
        if self._done:
            return
        self._done = True
        self._lift = None   # поздний ответ с содержимым окна больше не нужен
        self._close_window_menu()
        for w in list(getattr(self, "spawned", [])):   # окно выделения закрыто: окошкам возвращаются плашки
            try:
                w.enable_chip()
                # связи с окном выделения обрываются: оно сейчас удалится, а окошки живут дальше
                w.select_hook = w.more_hook = w.tr_state_hook = None
            except RuntimeError:
                pass
        self.spawned = []
        self.tr_current = None
        self._tr_shutdown()   # ждущие карточки перевода отменяются: результат окну уже не нужен
        self.pending = None
        self.releaseKeyboard()
        self.hide()
        if sel is None:
            self.finished.emit(None, QRect())
        else:
            pixmap = self.desktop.copy(self.to_physical(sel))
            # Масштаб экрана сохраняем: редактор покажет снимок ровно в размер выделенной области.
            pixmap.setDevicePixelRatio(self.ratio)
            # Мониторы с разным масштабом: снимок в масштабе того монитора, где область (плотность PNG по нему)
            pixmap = native_region(pixmap, sel.translated(self.origin))
            self.finished.emit(pixmap, sel.translated(self.origin))
        self.close()
