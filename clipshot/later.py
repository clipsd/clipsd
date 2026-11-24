# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Отложенный вызов, который живёт не дольше своего окна (1.36.1).

QTimer.singleShot(ms, функция) в PyQt6 не знает, к какому окну относится функция: если окно закрыли и удалили раньше,
функция всё равно вызывается, обращается к удалённому виджету (RuntimeError: wrapped C/C++ object ... has been deleted),
а необработанное исключение в обработчике Qt в PyQt6 роняет программу (Aborted, core dumped: Linux CI, прогон
45288065564, keep_point редактора). later(owner, ms, fn): таймер дочерний для owner и удаляется вместе с ним; перед
вызовом owner проверяется ещё раз.
"""
from PyQt6.QtCore import QObject, QTimer


def alive(obj) -> bool:
    """Объект Qt ещё существует (обёртка не указывает на удалённый объект C++)."""
    if obj is None:
        return False
    try:
        from PyQt6 import sip
        return not sip.isdeleted(obj)
    except (ImportError, TypeError):
        return True


def later(owner: QObject, ms: int, fn):
    """Вызвать fn через ms мс, если owner ещё жив. Таймер принадлежит owner: удалённое окно ничего не вызовет."""
    if not alive(owner):
        return None
    timer = QTimer(owner)
    timer.setSingleShot(True)

    def run():
        timer.deleteLater()
        if alive(owner):
            fn()
    timer.timeout.connect(run)
    timer.start(max(0, int(ms)))
    return timer
