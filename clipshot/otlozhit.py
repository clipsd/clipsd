# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""«Отложить ▾» в окнах-помощниках, которые приходят сами (слова владельца 22.11.2026: «когда помощник или ещё что-то
идёт, а человеку сейчас некогда это проходить, он хочет быстро что-то сделать, а потом дальше пройти»).

Кнопка из двух частей: основная часть откладывает на время по умолчанию (1 час), стрелка или долгое нажатие открывает
меню: 15 минут, 1 час, 3 часа, до завтра (9:00), неделя. Окно возвращается само, когда время вышло и в программе
спокойная минута (Clipshot.schedule_otlozhit); время хранится в настройках и переживает перезапуск.

Состояние в config["otlozhit"] = {тема: {"until": секунды Unix, "count": подряд откладываний, "data": {...}}}.
Темы: "novoe" (окно «Новое в версии»), "ask" (вопрос про другие функции), "ozn" (окно «Ознакомление», data["id"]:
с какой функции продолжить), "tour" (первое знакомство в редакторе, data["step"]), "tour_selector" (знакомство с
окном выделения: вернётся при следующем выделении, сам по себе окно выделения не открывается).

После MAX_SNOOZES откладываний подряд окно приходит не раньше чем через неделю (меню значка открывает его всегда).
Время берётся из now(): тесты подставляют свои часы."""

import time
from datetime import datetime, time as dtime, timedelta

from PyQt6.QtCore import QRect, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QCursor, QGuiApplication
from PyQt6.QtWidgets import QHBoxLayout, QMenu, QPushButton, QWidget

from .i18n import tr

DEFAULT = "1h"
NEVER = "never"          # последний пункт меню «Не показывать» (подпись по смыслу окна), chosen("never")
MAX_SNOOZES = 3          # после трёх откладываний подряд: не раньше чем через неделю
WEEK = 7 * 86400
TOMORROW_HOUR = 9        # «До завтра»: завтра в 9:00
LONG_PRESS_MS = 450
# (код, секунды или None, ключ подписи); «До завтра» считается по календарю, «неделя» ровно 7 суток
CHOICES = (("15m", 15 * 60, "otl.m15"), ("1h", 3600, "otl.h1"), ("3h", 3 * 3600, "otl.h3"),
           ("tomorrow", None, "otl.tomorrow"), ("week", WEEK, "otl.week"))
TOPICS = ("novoe", "ask", "ozn", "tour", "tour_selector")


def now() -> float:
    """Текущее время, секунды Unix. Тесты подменяют otlozhit.now."""
    return time.time()


def until_for(key: str, at: float = None) -> float:
    """Момент, когда окно должно вернуться, если отложили с кодом key в момент at."""
    at = now() if at is None else at
    if key == "tomorrow":
        day = datetime.fromtimestamp(at).date() + timedelta(days=1)
        return datetime.combine(day, dtime(TOMORROW_HOUR, 0)).timestamp()
    for code, seconds, _label in CHOICES:
        if code == key:
            return at + seconds
    return at + 3600   # неизвестный код: как по умолчанию


# --- состояние -----------------------------------------------------------------------------------------

def _all(cfg, create=False):
    if not isinstance(cfg, dict):
        return {}
    box = cfg.get("otlozhit")
    if not isinstance(box, dict):
        if not create:
            return {}
        box = cfg["otlozhit"] = {}
    return box


def _entry(cfg, topic, create=False):
    box = _all(cfg, create)
    e = box.get(topic)
    if not isinstance(e, dict):
        if not create:
            return {}
        e = box[topic] = {}
    return e


def snooze(cfg, topic: str, key: str = DEFAULT, at: float = None, **data) -> float:
    """Отложить тему. Возвращает момент возврата. Третье откладывание подряд: не раньше чем через неделю."""
    at = now() if at is None else at
    e = _entry(cfg, topic, True)
    count = int(e.get("count") or 0) + 1
    until = until_for(key, at)
    if count >= MAX_SNOOZES:
        until = max(until, at + WEEK)
        count = 0
    e["until"] = until
    e["count"] = count
    if data:
        e["data"] = dict(data)
    return until


def until(cfg, topic: str):
    v = _entry(cfg, topic).get("until")
    return float(v) if isinstance(v, (int, float)) else None


def is_snoozed(cfg, topic: str, at: float = None) -> bool:
    """Тема отложена и срок ещё не вышел. Часы переведены назад больше чем на неделю: срок не ждём."""
    u = until(cfg, topic)
    if u is None:
        return False
    at = now() if at is None else at
    return 0 < u - at <= WEEK + 3600


def is_due(cfg, topic: str, at: float = None) -> bool:
    """Тема была отложена, и время вышло: пора вернуть окно."""
    u = until(cfg, topic)
    if u is None:
        return False
    return not is_snoozed(cfg, topic, at)


def due_topics(cfg, at: float = None) -> list:
    return [t for t in TOPICS if is_due(cfg, t, at)]


def next_until(cfg):
    """Ближайший момент возврата среди всех отложенных тем, None: ничего не отложено."""
    found = [u for u in (until(cfg, t) for t in TOPICS) if u is not None]
    return min(found) if found else None


def data(cfg, topic: str) -> dict:
    d = _entry(cfg, topic).get("data")
    return d if isinstance(d, dict) else {}


def shown(cfg, topic: str):
    """Окно вернулось: срок снимается, счёт откладываний остаётся (человек может отложить снова)."""
    _entry(cfg, topic).pop("until", None)


def clear(cfg, topic: str):
    """Человек сделал своё («Показать новое», «Пропустить», «Да»): откладывания забываются."""
    _all(cfg).pop(topic, None)


# --- кнопка «Отложить ▾» ----------------------------------------------------------------------------------

def _palette(dark: bool) -> dict:
    from .dialogs import PALETTES
    return PALETTES[bool(dark)]


def button_style(dark: bool = False, compact: bool = False) -> str:
    c = _palette(dark)
    pad_v, pad_h, size = (0, 12, 13) if compact else (9, 14, 14)
    arrow_h = 8 if not compact else 7
    height = "min-height: 30px;" if compact else ""
    return f"""
QPushButton#otlMain, QPushButton#otlArrow {{ background: {c['card']}; color: {c['text']}; font-size: {size}px;
    padding: {pad_v}px {pad_h}px; border: 1px solid {c['line']}; {height} }}
QPushButton#otlMain {{ border-top-left-radius: 8px; border-bottom-left-radius: 8px; border-right: none;
    border-top-right-radius: 0; border-bottom-right-radius: 0; padding-left: {pad_h + 2}px; }}
QPushButton#otlArrow {{ border-top-right-radius: 8px; border-bottom-right-radius: 8px; border-top-left-radius: 0;
    border-bottom-left-radius: 0; padding-left: {arrow_h}px; padding-right: {arrow_h}px; }}
QPushButton#otlMain:hover, QPushButton#otlArrow:hover, QPushButton#otlArrow:pressed {{ background: {c['soft']}; }}
QPushButton#otlMain:focus, QPushButton#otlArrow:focus {{ border: 2px solid {c['accent']}; }}
"""


def menu_style(dark: bool = False) -> str:
    c = _palette(dark)
    return (f"QMenu {{ background: {c['card']}; color: {c['text']}; border: 1px solid {c['line']}; border-radius: 8px;"
            f" padding: 4px; font-size: 14px; }}"
            f" QMenu::item {{ padding: 7px 22px; border-radius: 6px; background: transparent; }}"
            f" QMenu::item:selected {{ background: {c['soft']}; color: {c['text']}; }}")


class SnoozeButton(QWidget):
    """«Отложить ▾»: основная часть = время по умолчанию, стрелка и долгое нажатие = меню. chosen(код)."""

    chosen = pyqtSignal(str)

    def __init__(self, dark: bool = False, compact: bool = False, parent=None, never: str = None):
        super().__init__(parent)
        self.dark, self.compact = bool(dark), bool(compact)
        self.setObjectName("otlButton")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.main = QPushButton(tr("otl.button"))
        self.main.setObjectName("otlMain")
        self.arrow = QPushButton("▾")
        self.arrow.setObjectName("otlArrow")
        for b in (self.main, self.arrow):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        self.main.setToolTip(tr("otl.tip"))
        self.arrow.setToolTip(tr("otl.more"))
        self.main.setAccessibleName(tr("otl.button"))
        self.arrow.setAccessibleName(tr("otl.more"))
        lay.addWidget(self.main)
        lay.addWidget(self.arrow)
        self.setStyleSheet(button_style(self.dark, self.compact))
        self.menu = QMenu(self)
        self.menu.setStyleSheet(menu_style(self.dark))
        self.actions_by_key = {}
        for code, _sec, label in CHOICES:
            act = QAction(tr(label), self.menu)
            act.triggered.connect(lambda _c=False, k=code: self.chosen.emit(k))
            self.menu.addAction(act)
            self.actions_by_key[code] = act
        self.never_key = None
        self.never_action = None
        self._never_sep = None
        self.set_never(never)
        self._long = False
        self._press = QTimer(self)
        self._press.setSingleShot(True)
        self._press.setInterval(LONG_PRESS_MS)
        self._press.timeout.connect(self._long_press)
        self.main.pressed.connect(self._pressed)
        self.main.released.connect(self._press.stop)
        self.main.clicked.connect(self._main_clicked)
        self.arrow.clicked.connect(self.open_menu)

    def set_never(self, label_key):
        """Последний пункт меню «Не показывать» после разделителя; подпись по смыслу окна (ключ i18n). None: пункта нет."""
        if self.never_action is not None:
            self.menu.removeAction(self.never_action)
            if self._never_sep is not None:
                self.menu.removeAction(self._never_sep)
            self.never_action = self._never_sep = None
        self.never_key = label_key
        if not label_key:
            return
        self._never_sep = self.menu.addSeparator()
        act = QAction(tr(label_key), self.menu)
        act.triggered.connect(lambda _c=False: self.chosen.emit(NEVER))
        self.menu.addAction(act)
        self.never_action = act
        self.actions_by_key[NEVER] = act

    # основная часть
    def _pressed(self):
        self._long = False
        self._press.start()

    def _long_press(self):
        self._long = True
        self.open_menu()

    def _main_clicked(self):
        if self._long:   # меню уже открылось долгим нажатием: отпускание кнопки ничего не откладывает
            self._long = False
            return
        self.chosen.emit(DEFAULT)

    def click(self):
        """Как нажатие на основную часть (старые проверки и клавиатура)."""
        self.main.click()

    def setFocus(self, *a):
        self.main.setFocus(*a)

    # меню
    def menu_rect(self) -> QRect:
        """Где откроется меню: под кнопкой, а если внизу нет места, над ней; не выходит за экран."""
        size = self.menu.sizeHint()
        below = self.mapToGlobal(self.rect().bottomLeft())
        top = self.mapToGlobal(self.rect().topLeft())
        screen = QGuiApplication.screenAt(below) or QGuiApplication.screenAt(top) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x = max(area.left(), min(below.x(), area.right() - size.width() + 1))
        y = below.y() + 2
        if y + size.height() > area.bottom() + 1:
            y = top.y() - size.height() - 2
        y = max(area.top(), min(y, area.bottom() - size.height() + 1))
        return QRect(x, y, size.width(), size.height())

    def open_menu(self):
        if self.menu.isVisible():
            return
        r = self.menu_rect()
        self.menu.popup(r.topLeft())

    def retranslate(self):
        self.main.setText(tr("otl.button"))
        self.main.setToolTip(tr("otl.tip"))
        self.arrow.setToolTip(tr("otl.more"))
        for code, _sec, label in CHOICES:
            self.actions_by_key[code].setText(tr(label))
        if self.never_action is not None:
            self.never_action.setText(tr(self.never_key))
