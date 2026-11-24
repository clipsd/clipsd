# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Интерактивное обучение в окне «Ознакомление» (слова владельца 22.11.2026: «где-то что-то затемнять, что-то
показывать, и дальше предлагать повторить действие»).

Как идёт функция:
1. Выбрали пункт: учебный редактор затемняется, светлое окошко с рамкой только на нужной кнопке (потом на нужном
   месте снимка), рядом подсказка «Шаг 1 из 2: Нажмите сюда». Щелчок по окошку проходит к кнопке (маска затемнения).
2. «Показать»: видимый курсор плавно едет к кнопке, «нажимает» (кружок), едет к снимку и рисует пометку скоростью руки;
   у функций из нескольких действий шаги по очереди с подписью. 3-8 секунд. Esc или «Пропустить» прерывают.
3. «Теперь вы»: снимок возвращается к исходному, окошко на той же кнопке, человек повторяет. Программа сама видит, что
   действие сделано (инструмент выбран, пометка появилась), и пишет «Получилось». 15 секунд без движения: мягкая подсказка.
«Уменьшить движение» (настройка системы или CLIPSD_REDUCE_MOTION=1): курсор не едет, показ по кадрам."""

import math
import os
import sys
import time

from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPen, QPolygonF, QRegion
from PyQt6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from . import novoe
from .i18n import tr
from .later import later

TIME_SCALE = 1.0          # тесты ставят меньше: задержки сжимаются, плановая длительность считается без сжатия
IDLE_MS = 15000           # столько ничего не происходит: мягкая подсказка
HAND_PX_S = 430           # скорость руки при рисовании, px/с
DIM = QColor(0, 0, 0, 150)
RING = QColor("#ffd23f")
_REDUCE = {}


def _gsettings_reduce():
    try:
        import subprocess
        from . import sysenv
        out = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "enable-animations"],
                             capture_output=True, text=True, timeout=1, env=sysenv.child_env()).stdout
        _REDUCE["v"] = out.strip() == "false"
    except Exception:   # нет gsettings или ответа: движение оставляем
        _REDUCE["v"] = False


def reduce_motion() -> bool:
    """Системная просьба «уменьшить движение» или CLIPSD_REDUCE_MOTION=1. Узнаётся один раз за запуск; на Linux gsettings
    спрашивается в отдельном потоке (окно не ждёт), до ответа движение включено."""
    if "v" in _REDUCE:
        return _REDUCE["v"]
    env = os.environ.get("CLIPSD_REDUCE_MOTION")
    if env in ("0", "1"):
        _REDUCE["v"] = env == "1"
        return _REDUCE["v"]
    if sys.platform == "win32":
        value = False
        try:
            import ctypes
            flag = ctypes.c_int(1)
            # SPI_GETCLIENTAREAANIMATION = 0x1042: анимации в окнах включены?
            if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(flag), 0):
                value = not bool(flag.value)
        except Exception:
            value = False
        _REDUCE["v"] = value
        return value
    if sys.platform.startswith("linux") and not os.environ.get("QT_QPA_PLATFORM", "").startswith("offscreen"):
        warm_reduce_motion()
        return _REDUCE.get("v", False)
    _REDUCE["v"] = False
    return False


def warm_reduce_motion():
    """Заранее, при открытии окна: ответ gsettings в фоновом потоке."""
    if "v" in _REDUCE or "thread" in _REDUCE:
        return
    if sys.platform.startswith("linux") and not os.environ.get("QT_QPA_PLATFORM", "").startswith("offscreen") \
            and os.environ.get("CLIPSD_REDUCE_MOTION") not in ("0", "1"):
        import threading
        _REDUCE["thread"] = True
        threading.Thread(target=_gsettings_reduce, daemon=True).start()


def set_reduce_motion(value):
    """Для тестов: принудительно включить или выключить (None: узнать заново)."""
    if value is None:
        _REDUCE.pop("v", None)
    else:
        _REDUCE["v"] = bool(value)


# --- слои поверх учебного редактора ---------------------------------------------------------------------------

class Dimmer(QWidget):
    """Полупрозрачное затемнение с «окошком»: в окошке всё светлое, щелчок проходит к кнопке (маска окна), вокруг жёлтая
    рамка. Рядом карточка-подсказка шага. Лежит только поверх своего родителя (учебного редактора)."""

    def __init__(self, parent, dark: bool, on_skip):
        super().__init__(parent)
        self.dark = dark
        self.getter = None
        self.hole = QRect()
        self.setObjectName("oznDimmer")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.bubble = QFrame(self)
        self.bubble.setObjectName("oznBubble")
        bg, fg, muted, edge = ("#25282c", "#f1f3f5", "#aab1ba", "#4a5058") if dark else ("#ffffff", "#16181c", "#5a6270", "#c8d0db")
        self.bubble.setStyleSheet(
            f"QFrame#oznBubble {{ background: {bg}; border: 1px solid {edge}; border-radius: 10px; }}"
            f"QLabel {{ background: transparent; color: {fg}; font-size: 13px; }}"
            f"QLabel#oznBubbleStep {{ color: {muted}; font-size: 12px; }}"
            f"QLabel#oznBubbleCaption {{ font-size: 15px; font-weight: bold; }}"
            f"QLabel#oznBubbleIdle {{ color: {muted}; }}"
            f"QPushButton {{ border: none; background: transparent; color: {muted}; font-size: 12px; text-decoration: underline; padding: 2px 0; }}"
            f"QPushButton:hover {{ color: {fg}; }}")
        lay = QVBoxLayout(self.bubble)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(3)
        self.step_label = QLabel()
        self.step_label.setObjectName("oznBubbleStep")
        self.caption = QLabel()
        self.caption.setObjectName("oznBubbleCaption")
        self.caption.setWordWrap(True)
        self.idle = QLabel()
        self.idle.setObjectName("oznBubbleIdle")
        self.idle.setWordWrap(True)
        self.skip_button = QPushButton(tr("ozn.skip"))
        self.skip_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.skip_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.skip_button.clicked.connect(on_skip)
        row = QHBoxLayout()
        row.addWidget(self.skip_button)
        row.addStretch(1)
        for w in (self.step_label, self.caption, self.idle):
            lay.addWidget(w)
        lay.addLayout(row)
        self.bubble.setFixedWidth(270)
        self._step_text, self._caption, self._is_compact = "", "", False
        self.hide()

    def show_step(self, index: int, total: int, caption: str, getter, idle: str = ""):
        self.getter = getter
        self._step_text = tr("ozn.step_of", i=index + 1, n=total) if total > 1 else ""
        self._caption = caption
        self.step_label.setText(self._step_text)
        self.step_label.setVisible(total > 1)
        self.caption.setText(caption)
        self.idle.setText(idle)
        self.idle.setVisible(bool(idle))
        self.skip_button.setText(tr("ozn.skip"))
        self.refresh(force=True)

    def set_idle(self, text: str):
        self.idle.setText(text)
        self.idle.setVisible(bool(text))
        self.refresh(force=True)

    def refresh(self, force=False):
        parent = self.parentWidget()
        if parent is None or self.getter is None:
            return
        try:
            rect = self.getter()
        except RuntimeError:
            return
        self.setGeometry(parent.rect())
        self._apply_compact()
        hole = QRect() if rect is None else QRect(rect).adjusted(-3, -3, 3, 3).intersected(self.rect())
        if hole != self.hole or force:
            self.hole = hole
            region = QRegion(self.rect())
            if hole.isValid():
                region = region.subtracted(QRegion(hole))
            self.setMask(region)
            self._place_bubble()
            self.update()
        self.show()
        self.raise_()
        self.bubble.raise_()

    def _apply_compact(self):
        """Низкий редактор (910x472): подсказка в одну строку «Шаг 1 из 2: Нажмите сюда», чтобы не закрывать снимок."""
        compact = self.height() < 480 and bool(getattr(self, "_caption", ""))
        if compact == getattr(self, "_is_compact", False):
            return
        self._is_compact = compact
        if compact:
            self.step_label.hide()
            self.caption.setText((self._step_text + ": " if self._step_text else "") + self._caption)
        else:
            self.step_label.setVisible(bool(self._step_text))
            self.caption.setText(self._caption)
        self.bubble.setFixedWidth(250 if compact else 270)
        self._place_bubble()

    def _place_bubble(self):
        self.bubble.adjustSize()
        w, h = self.bubble.width(), self.bubble.sizeHint().height()
        self.bubble.setFixedHeight(h)
        room = self.rect().adjusted(8, 8, -8, -8)
        hole = self.hole
        if not hole.isValid():
            pos = QPoint(room.center().x() - w // 2, room.top() + 8)
        else:
            options = (QPoint(hole.left(), hole.bottom() + 12), QPoint(hole.left(), hole.top() - 12 - h),
                       QPoint(hole.right() + 12, hole.top()), QPoint(hole.left() - 12 - w, hole.top()))
            pos = options[0]
            for p in options:
                r = QRect(p, self.bubble.size())
                if room.contains(r) and not r.intersects(hole):
                    pos = p
                    break
            else:
                pos = QPoint(room.right() - w, room.top() + 8)
        pos.setX(max(room.left(), min(pos.x(), room.right() - w)))
        pos.setY(max(room.top(), min(pos.y(), room.bottom() - h)))
        self.bubble.move(pos)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRect(QRectF(self.rect()))
        if self.hole.isValid():
            cut = QPainterPath()
            cut.addRoundedRect(QRectF(self.hole), 6, 6)
            path = path.subtracted(cut)
        p.fillPath(path, DIM)
        if self.hole.isValid():
            p.setPen(QPen(RING, 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(self.hole).adjusted(-1.5, -1.5, 1.5, 1.5), 8, 8)
        p.end()


class Cursor(QWidget):
    """Нарисованная стрелка мыши и кружок нажатия. Горячая точка в центре виджета. Мышь проходит насквозь."""
    HOT = 32

    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedSize(2 * self.HOT, 2 * self.HOT)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setObjectName("oznCursor")
        self.ring = 0.0
        self.hide()

    def put(self, pt: QPointF):
        self.move(round(pt.x()) - self.HOT, round(pt.y()) - self.HOT)
        self.raise_()
        self.show()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = self.HOT
        if self.ring > 0:
            col = QColor("#ffd23f")
            col.setAlphaF(max(0.0, 1.0 - self.ring))
            p.setPen(QPen(col, 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            r = 6 + 22 * self.ring
            p.drawEllipse(QPointF(c, c), r, r)
        arrow = QPolygonF([QPointF(c, c), QPointF(c, c + 25), QPointF(c + 6, c + 19), QPointF(c + 11, c + 30),
                           QPointF(c + 15, c + 28), QPointF(c + 10, c + 18), QPointF(c + 18, c + 18)])
        p.setPen(QPen(QColor("#16181c"), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(QColor("#ffffff"))
        p.drawPolygon(arrow)
        p.end()


# --- события мыши по снимку ------------------------------------------------------------------------------------------

def send_mouse(canvas, kind, p: QPointF, down: bool):
    """Мышиное событие на холст в точке p (координаты снимка)."""
    pos = QPointF(p.x() * canvas.zoom, p.y() * canvas.zoom)
    left = Qt.MouseButton.LeftButton
    btn = left if kind != QEvent.Type.MouseMove else Qt.MouseButton.NoButton
    ev = QMouseEvent(kind, pos, canvas.mapToGlobal(pos.toPoint()).toPointF(), btn,
                     left if down else Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(canvas, ev)


def line(a, b, n=2):
    return [(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(n + 1)]


# --- шаги ----------------------------------------------------------------------------------------------------------------

class Step:
    """kind: press (нажать кнопку), draw (провести по снимку), click (щёлкнуть по снимку, text: набрать в нём).
    target: "tool:код", имя поля редактора, функция, дающая виджет, или ("img", QRectF в точках снимка).
    do: что делает показ при «нажатии»; path: точки снимка; wait: ждать, пока станет True (распознавание текста);
    done: сделано ли это человеком."""

    def __init__(self, kind, target, done, do=None, path=None, text="", wait=None, caption_key=None):
        self.kind, self.target, self.done, self.do = kind, target, done, do
        self.path, self.text, self.wait = path or [], text, wait
        self.caption_key = caption_key or {"press": "ozn.step_press", "draw": "ozn.step_draw", "click": "ozn.step_click"}[kind]

    @property
    def caption(self):
        return tr(self.caption_key)


def start_tool(ident_tool: str) -> str:
    return "rect" if ident_tool == "move" else "move"


def plan(ed, win, ident: str) -> list:
    """Шаги функции ident на учебном редакторе ed. win.noted: что сделал человек кнопками, которые ничего не меняют."""
    from . import forma
    from .oznakomlenie import BY_ID, row_y
    cv = ed.canvas
    _i, _g, _icon, kind, target, demo, _real = BY_ID[ident]
    best = row_y(5)
    noted = win.lesson.noted

    def tool_step(code, where=None):
        return Step("press", where or "tool:" + code, lambda: cv.tool == code, do=lambda: ed.select_tool(code))

    def shaped(k):
        return any(s.kind == k for s in cv.shapes)

    def img(a, b, pad=30):
        return ("img", QRectF(min(a[0], b[0]) - pad, min(a[1], b[1]) - pad, abs(a[0] - b[0]) + 2 * pad, abs(a[1] - b[1]) + 2 * pad))

    def drawn(tool, k, a, b, n=2):
        return [tool_step(tool), Step("draw", img(a, b), lambda: shaped(k), path=line(a, b, n))]

    if demo == "arrows":
        return drawn("arrow", "arrow", (735, 240), (672, best - 10))
    if demo == "shapes":
        return drawn("rect", "rect", (22, best - 19), (738, best + 19))
    if demo == "marker":
        wave = [(520 + i * 12, 100 + (3 if i % 2 else -3)) for i in range(16)]
        return [tool_step("marker"), Step("draw", img((520, 100), (700, 100), 24), lambda: shaped("marker"), path=wave)]
    if demo == "blur":
        return drawn("blur", "blur", (516, 146), (722, 182))
    if demo == "numbers":
        blue = lambda: list(ed.color_buttons.values())[4]
        return [tool_step("number"),
                Step("click", img((22, row_y(0)), (22, row_y(1)), 36), lambda: sum(1 for s in cv.shapes if s.kind == "number") >= 2,
                     path=[(22, row_y(0)), (22, row_y(1))]),
                Step("press", lambda: blue(), lambda: cv.color.name().lower() == "#1e78ff", do=lambda: blue().click()),
                Step("click", img((22, row_y(3)), (22, row_y(3)), 36),
                     lambda: len({s.color.rgba() for s in cv.shapes if s.kind == "number"}) >= 2, path=[(22, row_y(3))])]
    if demo == "text":
        return [tool_step("text"),
                Step("click", img((300, 380), (300, 380), 60), lambda: any(s.kind == "text" and s.text for s in cv.shapes),
                     path=[(300, 380)], text=tr("ozn.demo_best"))]
    if demo == "undo":
        return drawn("rect", "rect", (22, row_y(0) - 19), (738, row_y(0) + 19)) + [
            Step("press", "undo_button", lambda: not cv.shapes and bool(cv.redo_stack), do=lambda: ed.undo_button.click())]
    if demo == "forma":
        return [Step("press", target, lambda: not cv.form.is_rect, do=lambda: ed.set_form(forma.ROUND))]
    if demo == "stikery":
        return [tool_step("sticker"),
                Step("click", img((640, 300), (640, 300), 50), lambda: shaped("sticker"), path=[(640, 300)])]
    if demo == "ten_ramka":
        # 1.36.1 (слова владельца: «её надо открыть ещё изначально»): путь целиком: «Форма снимка ▾» → меню → «Тень, рамка и
        # поля…» → панель → тень, рамка и поля применены к снимку. Меню показывается без блокировки (popup), пункт подсвечен.
        from PyQt6.QtWidgets import QApplication, QMenu
        from . import ten_ramka

        def open_menu():
            menu = ed.build_form_menu()
            ed._ozn_menu = menu
            anchor = form_target()
            menu.popup(anchor.mapToGlobal(QPoint(0, anchor.height() + 2)))

        def active_menu():
            m = QApplication.activePopupWidget()
            return m if isinstance(m, QMenu) else getattr(ed, "_ozn_menu", None)

        def choose_item():
            menu = active_menu()
            if menu is None:
                return
            act = next((a for a in menu.actions() if a.text() == tr("deco.menu")), None)
            if act is not None:
                menu.setActiveAction(act)   # подсветка пункта самим меню
                later(act, 700, act.trigger)

        def panel():
            p = getattr(ed, "_deco_panel", None)
            try:
                return p if p is not None and p.isVisible() else None
            except RuntimeError:
                return None
        def form_target():   # узкое окно: «Форма снимка» живёт в «⋯ Все инструменты»
            return ed.form_button if ed.form_button.isVisible() else ed.more_button
        return [Step("press", form_target, lambda: active_menu() is not None and active_menu().isVisible() or panel() is not None
                     or cv.deco.active, do=open_menu),
                Step("press", active_menu, lambda: panel() is not None or cv.deco.active, do=choose_item),
                Step("press", lambda: panel() or form_target(), lambda: cv.deco.active,
                     do=lambda: cv.set_deco(ten_ramka.Deco(True, 18, 40, True, 4, "#1e78ff", False)))]
    if ident == "ocr":
        return [tool_step("ocr"),
                Step("draw", img((40, row_y(0)), (330, row_y(0)), 20), lambda: bool(cv.text_sel) or "ocr" in noted,
                     path=line((40, row_y(0)), (330, row_y(0))), wait=cv.has_words)]
    if kind == "tool":
        return [tool_step(target)]
    if ident == "translate_head":
        return [tool_step("translate", target)]
    if ident in ("save", "copy"):
        return [Step("press", target, lambda: ident in noted, do=getattr(ed, target).click)]
    if ident == "pechat":   # показ: окно предпросмотра само не открывается (оно модальное), только плашка; настоящее нажатие человека откроет его
        return [Step("press", target, lambda: ident in noted, do=lambda: (win.lesson.note("pechat"), ed.show_toast(tr("ozn.pechat_demo"))))]
    if ident == "pdf":   # PDF: кнопка «Печать ▾» (стрелка: «Сохранить в PDF…») и окно «Сохранить»; показ только плашка
        return [Step("press", target, lambda: "pdf" in noted,
                     do=lambda: (noted.add("pdf"), ed.show_toast(tr("ozn.pdf_demo"))))]
    if ident == "qr_chtenie":   # на учебном снимке нарисован код: кнопка «QR» появляется в шапке, когда он прочитан
        return [Step("press", target, lambda: getattr(ed, "qr_dialog", None) is not None, do=ed.show_qr,
                     wait=lambda: ed.qr_button.isVisible())]
    if ident in ("settings", "help"):
        return [Step("press", target, lambda: ident in noted)]
    if ident == "phone_editor":
        return [Step("press", target, lambda: "phone_editor" in noted)]
    return [Step("press", target, lambda: False)]


# --- ход обучения ------------------------------------------------------------------------------------------------------

class Lesson:
    """Состояние обучения одного пункта: слои на редакторе, показ, «Теперь вы», распознавание «Получилось»."""

    def __init__(self, win):
        self.win = win
        self.phase = "off"       # off, demo, you, done, free
        self.ident = None
        self.steps = []
        self.index = 0
        self.noted = set()
        self.gen = 0
        self.demo_ms = 0         # плановая длительность последнего показа (без сжатия TIME_SCALE)
        self.demo_runs = 0
        self.dimmer = None
        self.cursor = None
        self.panel_dimmer = None
        self._since = time.monotonic()
        self._idle_shown = False
        self.poll = QTimer(win)
        self.poll.setInterval(120)
        self.poll.timeout.connect(self._tick)

    @property
    def active(self) -> bool:
        return self.phase in ("demo", "you")

    # --- слои ---

    def attach(self, ed):
        self.dimmer = Dimmer(ed, self.win.dark, self.skip)
        self.cursor = Cursor(ed)
        ed.canvas.pressed.connect(self._touched)
        for name, key in (("settings_button", "settings"), ("help_button", "help")):
            w = getattr(ed, name, None)
            if w is not None:
                (w.pressed if name == "help_button" else w.clicked).connect(lambda *_a, k=key: self.note(k))

    def detach(self):
        self.stop_all()
        self.dimmer = self.cursor = None

    def _touched(self):
        self._since = time.monotonic()

    # --- геометрия ---

    def rect_of(self, target):
        ed = self.win.editor
        if ed is None:
            return None
        if isinstance(target, tuple):   # ("img", QRectF в точках снимка)
            cv = ed.canvas
            r = target[1]
            tl = cv.mapTo(ed, QPoint(round(r.left() * cv.zoom), round(r.top() * cv.zoom)))
            br = cv.mapTo(ed, QPoint(round(r.right() * cv.zoom), round(r.bottom() * cv.zoom)))
            rect = QRect(tl, br).normalized()
            vp = ed.scroll.viewport()
            view = QRect(vp.mapTo(ed, QPoint(0, 0)), vp.size())
            return rect.intersected(view)
        w = target() if callable(target) else novoe.editor_widget(ed, target)
        if w is None:
            w = getattr(ed, "more_button", None)
        if w is None or not w.isVisible():
            return None
        return QRect(ed.mapFromGlobal(w.mapToGlobal(QPoint(0, 0))), w.size())   # через экран: работает и для всплывающих окон

    def point_img(self, p):
        ed = self.win.editor
        cv = ed.canvas
        q = cv.mapTo(ed, QPoint(round(p[0] * cv.zoom), round(p[1] * cv.zoom)))
        return QPointF(q)

    # --- запуск «Теперь вы» ---

    def start(self, ident):
        """Пункт выбран: окошко на первом шаге, человек может делать сам или нажать «Показать»."""
        self.stop_all()
        self.ident = ident
        if self.win.is_panel(ident):
            self._start_panel(ident)
            return
        ed = self.win.editor
        if ed is None:
            return
        self._fresh_if_dirty()
        ed = self.win.editor
        from .oznakomlenie import BY_ID
        kind, target = BY_ID[ident][3], BY_ID[ident][4]
        ed.select_tool(start_tool(target if kind == "tool" else "x"))
        if BY_ID[ident][5] == "numbers":
            list(ed.color_buttons.values())[0].click()
        self.noted = set()
        self.steps = plan(ed, self.win, ident)
        self.index = 0
        self.phase = "you"
        self._since = time.monotonic()
        self._idle_shown = False
        self._show_step()
        self.poll.start()

    def _fresh_if_dirty(self):
        ed = self.win.editor
        cv = ed.canvas
        if cv.shapes or cv.undo_stack or cv.redo_stack or not cv.form.is_rect or cv.text_sel or cv.text_edit is not None:
            self.win.rebuild_editor()

    def _show_step(self):
        if self.dimmer is None or not self.steps:
            return
        st = self.steps[self.index]
        n = len(self.steps)
        self.dimmer.show_step(self.index, n, st.caption, lambda t=st.target: self.rect_of(t))
        self.win.set_result("")

    def _start_panel(self, ident):
        from .oznakomlenie import BY_ID
        self.phase = "you"
        self.noted = set()
        self.steps = []
        self.win.show_panel_dim(True)
        self._since = time.monotonic()
        self.poll.start()

    # --- обратная связь ---

    def note(self, key):
        """Редактор сообщает: человек нажал кнопку, которая ничего не рисует (сохранить, настройки, телефон)."""
        self.noted.add(key)

    def _tick(self):
        if self.dimmer is not None and self.win.editor is not None:
            try:
                self.dimmer.refresh()
            except RuntimeError:
                pass
        self.win.refresh_panel_dim()
        self.win.refresh_primary()
        if self.phase != "you":
            return
        if self.win.is_panel(self.ident):
            if "real" in self.noted:
                self.finish()
            return
        st = self.steps[self.index]
        try:
            ok = bool(st.done())
        except RuntimeError:
            return
        if ok:
            self._since = time.monotonic()
            self._idle_shown = False
            self.index += 1
            if self.index >= len(self.steps):
                self.finish()
            else:
                self._show_step()
            return
        limit = IDLE_MS / 1000.0
        if not self._idle_shown and time.monotonic() - self._since > limit:
            self._idle_shown = True
            hint = tr("ozn.idle_hint")
            if self.dimmer is not None:
                self.dimmer.set_idle(hint)

    def finish(self):
        self.phase = "done"
        self.poll.stop()
        self._hide_layers()
        self.win.lesson_done(self.ident)

    def skip(self, *_a):
        """«Пропустить» и Esc: затемнения нет, человек делает как хочет."""
        if self.phase in ("off", "free", "done"):
            return
        self.gen += 1
        self.phase = "free"
        self.poll.stop()
        self._hide_layers()
        self.win.lesson_skipped()

    def escape(self):
        self.skip()

    def stop_all(self):
        self.gen += 1
        self.phase = "off"
        self.poll.stop()
        self._hide_layers()

    def _hide_layers(self):
        for w in (self.dimmer, self.cursor):
            if w is not None:
                try:
                    w.hide()
                except RuntimeError:
                    pass
        self.win.show_panel_dim(False)

    # --- показ ---

    def demo(self):
        """«Показать»: живой показ по шагам, потом «Теперь вы»."""
        ident = self.ident
        if ident is None:
            return
        self.gen += 1
        gen = self.gen
        self.poll.stop()
        self._hide_layers()
        self.phase = "demo"
        self.demo_runs += 1
        self.demo_ms = 0
        self.win.set_result("")
        if self.win.is_panel(ident):
            gen_obj = self._demo_panel(gen)
        else:
            self._fresh_if_dirty()
            from .oznakomlenie import BY_ID
            ed = self.win.editor
            kind, target = BY_ID[ident][3], BY_ID[ident][4]
            ed.select_tool(start_tool(target if kind == "tool" else "x"))
            if BY_ID[ident][5] == "numbers":
                list(ed.color_buttons.values())[0].click()
            self.noted = set()
            self.steps = plan(ed, self.win, ident)
            gen_obj = self._demo_editor(gen)
        self._drive(gen_obj, gen)

    def _drive(self, gen_obj, gen):
        def step():
            if gen != self.gen:
                return
            try:
                ms = next(gen_obj)
            except StopIteration:
                if gen == self.gen:
                    self.win.mark_studied(self.ident)   # показ досмотрен до конца
                    self.start(self.ident)   # «Теперь вы»
                    self.win.hint_line.setText(tr("ozn.now_you"))
                return
            except RuntimeError:
                return
            later(self.win, max(1, int(ms * TIME_SCALE)), step)   # окно закрыли во время показа: шаг не вызывается
        step()

    def _wait(self, ms):
        self.demo_ms += ms
        yield ms

    def _glide(self, cur, a: QPointF, b: QPointF, ms: float, on_frame=None):
        """Курсор плавно едет от a к b за ms (плавный разгон и торможение)."""
        if reduce_motion():
            cur.put(b)
            if on_frame:
                on_frame(1.0)
            yield from self._wait(250)
            return
        frames = max(1, int(ms / 16))
        for k in range(1, frames + 1):
            t = k / frames
            e = t * t * (3 - 2 * t)
            cur.put(QPointF(a.x() + (b.x() - a.x()) * e, a.y() + (b.y() - a.y()) * e))
            if on_frame:
                on_frame(t)
            yield from self._wait(ms / frames)

    @staticmethod
    def _travel_ms(a: QPointF, b: QPointF) -> float:
        d = math.hypot(b.x() - a.x(), b.y() - a.y())
        return max(450.0, min(1000.0, 400 + d * 0.9))

    def _click_ring(self, cur):
        if reduce_motion():
            cur.ring = 0.5
            cur.update()
            yield from self._wait(450)
            cur.ring = 0
            cur.update()
            return
        for k in range(1, 9):
            cur.ring = k / 8
            cur.update()
            yield from self._wait(30)
        cur.ring = 0
        cur.update()

    def _demo_editor(self, gen):
        ed = self.win.editor
        cv = ed.canvas
        cur = self.cursor
        steps = self.steps
        n = len(steps)
        pos = QPointF(ed.width() * 0.55, ed.height() * 0.45)
        cur.put(pos)
        self.win.hint_line.setText(tr("ozn.playing"))
        yield from self._wait(500)
        for i, st in enumerate(steps):
            if gen != self.gen:
                return
            self.dimmer.show_step(i, n, st.caption, lambda t=st.target: self.rect_of(t))
            yield from self._wait(250)
            if st.kind == "press":
                r = self.rect_of(st.target)
                if r is None:
                    continue
                goal = QPointF(r.center())
                yield from self._glide(cur, pos, goal, self._travel_ms(pos, goal))
                pos = goal
                yield from self._click_ring(cur)
                if st.do is not None:
                    st.do()
                yield from self._wait(450)
                continue
            a = self.point_img(st.path[0])
            yield from self._glide(cur, pos, a, self._travel_ms(pos, a))
            pos = a
            if st.wait is not None:   # распознавание текста ещё идёт
                for _ in range(40):
                    if st.wait():
                        break
                    yield 100
            if st.kind == "click":
                for j, q in enumerate(st.path):
                    if j:
                        b = self.point_img(q)
                        yield from self._glide(cur, pos, b, self._travel_ms(pos, b) * 0.6)
                        pos = b
                    yield from self._click_ring(cur)
                    send_mouse(cv, QEvent.Type.MouseButtonPress, QPointF(*q), True)
                    send_mouse(cv, QEvent.Type.MouseButtonRelease, QPointF(*q), False)
                if st.text and cv.text_edit is not None:
                    for ch in st.text:
                        if cv.text_edit is None:
                            break
                        cv.text_edit.insertPlainText(ch)
                        yield from self._wait(70)
                    yield from self._wait(300)
                    cv.commit_text()
                yield from self._wait(400)
                continue
            # draw: рука ведёт по точкам со своей скоростью
            pts = st.path
            length = sum(math.hypot(pts[j + 1][0] - pts[j][0], pts[j + 1][1] - pts[j][1]) for j in range(len(pts) - 1))
            ms = max(500.0, min(1400.0, length / HAND_PX_S * 1000.0))
            send_mouse(cv, QEvent.Type.MouseButtonPress, QPointF(*pts[0]), True)
            yield from self._wait(150)
            if reduce_motion():
                for p in pts[1:]:
                    send_mouse(cv, QEvent.Type.MouseMove, QPointF(*p), True)
                cur.put(self.point_img(pts[-1]))
                yield from self._wait(500)
            else:
                frames = max(2, int(ms / 16))
                seg = [0.0]
                for j in range(len(pts) - 1):
                    seg.append(seg[-1] + math.hypot(pts[j + 1][0] - pts[j][0], pts[j + 1][1] - pts[j][1]))
                total = seg[-1] or 1.0
                for k in range(1, frames + 1):
                    d = total * k / frames
                    j = max(1, next((q for q in range(1, len(seg)) if seg[q] >= d), len(seg) - 1))
                    span = (seg[j] - seg[j - 1]) or 1.0
                    t = (d - seg[j - 1]) / span
                    p = (pts[j - 1][0] + (pts[j][0] - pts[j - 1][0]) * t, pts[j - 1][1] + (pts[j][1] - pts[j - 1][1]) * t)
                    send_mouse(cv, QEvent.Type.MouseMove, QPointF(*p), True)
                    cur.put(self.point_img(p))
                    yield from self._wait(ms / frames)
            send_mouse(cv, QEvent.Type.MouseButtonRelease, QPointF(*pts[-1]), False)
            pos = self.point_img(pts[-1])
            yield from self._wait(500)
        if self.demo_ms < 3000:   # короткий показ держится до трёх секунд, чтобы успеть рассмотреть
            yield from self._wait(3000 - self.demo_ms)

    def _demo_panel(self, gen):
        win = self.win
        win.show_panel_dim(True)
        cur = win.panel_cursor
        r = win.panel_hole()
        pos = QPointF(r.center().x() + 160, r.center().y() + 90) if r else QPointF(20, 20)
        cur.put(pos)
        win.hint_line.setText(tr("ozn.playing"))
        yield from self._wait(700)
        if r is not None:
            goal = QPointF(r.center())
            yield from self._glide(cur, pos, goal, self._travel_ms(pos, goal))
            yield from self._click_ring(cur)
        yield from self._wait(1200)
        yield from self._wait(max(0, 3000 - self.demo_ms))
