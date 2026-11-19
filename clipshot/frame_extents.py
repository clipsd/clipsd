# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Сообщить оконному менеджеру X11 (Mutter через XWayland), где видимая часть безрамочного окна.

У окон ClipSD с прозрачным полем под тень оконный менеджер считал границей окна внешний край поля, и
рамка активного окна (расширения оболочки, привязка к краям экрана, снимки окна) отстояла от видимой карточки.
Свойство _GTK_FRAME_EXTENTS (CARDINAL, 32 бита: левое, правое, верхнее, нижнее поле в пикселях устройства)
говорит менеджеру, сколько из окна занимает невидимое поле. Размер и позиция окна в Qt от этого не меняются."""

from PyQt6.QtGui import QGuiApplication

PROPERTY = "_GTK_FRAME_EXTENTS"


def frame_margins(left: int, right: int, top: int, bottom: int, ratio: float = 1.0, active: bool = True):
    """Поля в пикселях устройства: логические точки умножаются на масштаб; active=False (развёрнутое окно,
    системный заголовок) даёт нули."""
    if not active:
        return (0, 0, 0, 0)
    k = ratio if ratio and ratio > 0 else 1.0
    return tuple(int(round(v * k)) for v in (left, right, top, bottom))


_state = {"disp": None, "atom": None, "atom_disp": None}   # одно соединение и атом на процесс


def _display():
    """Общее соединение python-xlib; None, если дисплей не открылся (при следующем вызове откроется заново)."""
    if _state["disp"] is None:
        from Xlib import display
        _state["disp"] = display.Display()
    return _state["disp"]


def _reset():
    """Соединение оборвалось: закрыть и забыть, при следующем вызове откроется заново."""
    disp, _state["disp"], _state["atom"], _state["atom_disp"] = _state["disp"], None, None, None
    try:
        if disp is not None:
            disp.close()
    except Exception:
        pass


def _write(disp, win_id: int, values):
    """Записать свойство через объект дисплея python-xlib (вынесено для проверки на поддельном дисплее)."""
    if _state["atom"] is None or _state["atom_disp"] is not disp:
        _state["atom"], _state["atom_disp"] = disp.intern_atom(PROPERTY), disp
    win = disp.create_resource_object("window", win_id)
    win.change_property(_state["atom"], 6, 32, [int(v) for v in values])   # 6 = XA_CARDINAL
    disp.flush()


def set_frame_extents(widget, left: int, right: int, top: int, bottom: int, active: bool = True) -> bool:
    """Выставить _GTK_FRAME_EXTENTS окну виджета (поля в логических точках). Молча ничего не делает не под xcb,
    без python-xlib или если дисплей не открылся. Возвращает True, если свойство записано."""
    try:
        if QGuiApplication.platformName() != "xcb":
            return False
        win_id = int(widget.winId())   # создаёт окно, если его ещё нет: свойство ставится до первого показа
        values = frame_margins(left, right, top, bottom, widget.devicePixelRatioF(), active)
    except Exception:
        return False
    for _attempt in (0, 1):   # при ошибке соединения: открыть заново и повторить один раз
        try:
            _write(_display(), win_id, values)
            return True
        except Exception:
            _reset()
    return False


def track_frame_extents(widget, getter) -> bool:
    """Выставить поля сейчас и каждый раз, когда окно перешло на другой экран (другой масштаб).
    getter() возвращает (слева, справа, сверху, снизу) в логических точках по фактической геометрии окна."""
    widget._frame_extents_getter = getter
    handle = widget.windowHandle()
    if handle is not None and getattr(widget, "_frame_extents_handle", None) is not handle:
        widget._frame_extents_handle = handle
        handle.screenChanged.connect(lambda *_: refresh_frame_extents(widget))
    return refresh_frame_extents(widget)


def refresh_frame_extents(widget) -> bool:
    getter = getattr(widget, "_frame_extents_getter", None)
    if getter is None:
        return False
    left, right, top, bottom = getter()
    return set_frame_extents(widget, left, right, top, bottom)
