# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
"""Всплывающие подсказки действий (владелец, 18.11.2026: «снизу сделал какую-то строчку, и я её даже прочитать
не могу, что нужно сделать»).

HintPlate: крупная тёмная плашка у верхнего края области снимка, когда программа ждёт действия человека
(«Нажмите на слово и тяните…»). Плавно появляется, держится 4 секунды, плавно гаснет, исчезает сразу при первом
нажатии мыши или клавиши. Мышь пропускает сквозь себя и фокус не берёт.
ChoicePopup: окно с вопросом и двумя кнопками (перевод большого текста при нехватке лимита).
floating_toast: уведомление без окна-родителя (окно, с которого оно ушло, уже закрыто).
Итоговые уведомления («Скопировано…») остаются внизу (ocr.Toast): подсказка сверху, уведомление снизу.
"""

from PyQt6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, QRect, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter
from PyQt6.QtWidgets import QApplication, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

PLATE_BG = QColor(32, 33, 36, 240)
MAIN_PX, SUB_PX = 17, 13   # крупный текст и вторая строка про выход


class HintPlate(QWidget):
    FADE_IN, SHOW, FADE_OUT = 220, 4000, 500

    def __init__(self, window):
        super().__init__(window)
        self.setObjectName("clipsdHint")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)   # нажатия идут к снимку сквозь плашку
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.text, self.sub = "", ""
        self.effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.effect)
        self.anim = QPropertyAnimation(self.effect, b"opacity", self)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._fade_out)
        self._filtering = False
        self.hide()

    # --- вид ----------------------------------------------------------------------------------

    @staticmethod
    def _fonts():
        main, sub = QFont(), QFont()
        main.setPixelSize(MAIN_PX)
        main.setBold(True)
        sub.setPixelSize(SUB_PX)
        return main, sub

    def _measure(self, limit: int):
        """Размер плашки и высоты строк: текст переносится, если окно узкое."""
        main, sub = self._fonts()
        fm, fs = QFontMetrics(main), QFontMetrics(sub)
        inner = max(120, limit - 2 * 22)
        flags = int(Qt.TextFlag.TextWordWrap)
        mb = fm.boundingRect(QRect(0, 0, inner, 2000), flags, self.text)
        sb = fs.boundingRect(QRect(0, 0, inner, 2000), flags, self.sub) if self.sub else QRect()
        w = max(mb.width(), sb.width()) + 2 * 22
        h = 12 + mb.height() + (6 + sb.height() if self.sub else 0) + 12
        return w, h, mb.height(), sb.height()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(PLATE_BG)
        p.drawRoundedRect(QRectF(self.rect()), 18, 18)
        _w, _h, mh, sh = self._measure(self.width())
        main, sub = self._fonts()
        flags = int(Qt.TextFlag.TextWordWrap) | int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        p.setFont(main)
        p.setPen(QColor("#ffffff"))
        p.drawText(QRect(22, 12, self.width() - 44, mh + 2), flags, self.text)
        if self.sub:
            p.setFont(sub)
            p.setPen(QColor(255, 255, 255, 190))
            p.drawText(QRect(22, 12 + mh + 6, self.width() - 44, sh + 2), flags, self.sub)
        p.end()

    # --- место ----------------------------------------------------------------------------------

    def _anchor(self) -> QRect:
        win = self.parentWidget()
        for name in ("hint_anchor", "toast_anchor"):
            if hasattr(win, name):
                a = getattr(win, name)()
                if a is not None and not a.isEmpty():
                    return a
        return win.rect()

    def _place(self):
        a = self._anchor()
        w, h, _mh, _sh = self._measure(max(160, a.width() - 40))
        self.resize(w, h)
        self.move(a.left() + max(0, (a.width() - w) // 2), a.top() + 18)   # у верхнего края: внизу уведомления итога

    # --- показ -----------------------------------------------------------------------------------

    def pop(self, text: str, sub: str = ""):
        self.text, self.sub = text, sub
        self._place()
        if not self.isVisible():
            self.effect.setOpacity(0.0)
        self.raise_()
        self.show()
        self.anim.stop()
        self.anim.setDuration(self.FADE_IN)
        self.anim.setStartValue(self.effect.opacity())
        self.anim.setEndValue(1.0)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        try:
            self.anim.finished.disconnect()
        except TypeError:
            pass
        self.anim.start()
        self.timer.start(self.FADE_IN + self.SHOW)
        self._listen(True)
        self._avoid_toast()

    def _avoid_toast(self):
        """Плашка и итоговое уведомление не накладываются: если места не хватило (низкое окно), побеждает уведомление."""
        from .ocr import Toast
        for toast in self.parentWidget().findChildren(Toast):
            if toast.isVisible() and toast.geometry().intersects(self.geometry()):
                self.dismiss()
                return

    def _fade_out(self):
        self.anim.stop()
        self.anim.setDuration(self.FADE_OUT)
        self.anim.setStartValue(self.effect.opacity())
        self.anim.setEndValue(0.0)
        try:
            self.anim.finished.disconnect()
        except TypeError:
            pass
        self.anim.finished.connect(self.dismiss)
        self.anim.start()

    def dismiss(self):
        """Убрать сразу (нажатие мыши, клавиша, окно закрывается)."""
        self.timer.stop()
        self.anim.stop()
        self._listen(False)
        self.hide()

    # --- «первое нажатие мыши или клавиши»: плашка уходит, чтобы не закрывать то, с чем работает человек ---------

    def _listen(self, on: bool):
        app = QApplication.instance()
        if app is None or on == self._filtering:
            return
        if on:
            app.installEventFilter(self)
        else:
            app.removeEventFilter(self)
        self._filtering = on

    def eventFilter(self, obj, event):
        if self.isVisible() and event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress):
            try:
                same = isinstance(obj, QWidget) and obj.window() is self.window()
            except RuntimeError:
                same = False
            if same:
                self.dismiss()
        return False   # событие не перехватываем: оно доходит до снимка как обычно


def hint(window, text: str, sub: str = ""):
    """Показать подсказку действия в окне, где находится window."""
    win = window.window()
    plate = win.findChild(HintPlate, "clipsdHint")
    if plate is None or plate.parentWidget() is not win:
        plate = HintPlate(win)
    plate.pop(text, sub)
    return plate


def hide_hint(window):
    plate = window.window().findChild(HintPlate, "clipsdHint")
    if plate is not None:
        plate.dismiss()


# --- вопрос с двумя кнопками -------------------------------------------------------------------------

class ChoicePopup(QFrame):
    """Всплывающее окно с вопросом и двумя кнопками. Не блокирует программу (модальный цикл не запускается);
    ответ приходит в done(True|False): True на первую кнопку, False на вторую, Esc или закрытие."""

    def __init__(self, parent, text: str, yes: str, no: str, done, sub: str = ""):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setObjectName("clipsdChoice")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._done, self._answered = done, False
        self.setStyleSheet("QFrame#clipsdChoice { background: #202124; border: 1px solid #5b5f66; border-radius: 14px; }"
                           " QLabel { color: #ffffff; background: transparent; }"
                           " QPushButton { font-size: 15px; font-weight: bold; padding: 8px 16px; border-radius: 8px; }")
        col = QVBoxLayout(self)
        col.setContentsMargins(22, 18, 22, 16)
        col.setSpacing(10)
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.label.setStyleSheet("font-size: 17px; font-weight: bold; color: #ffffff; background: transparent;")
        col.addWidget(self.label)
        if sub:
            self.sub = QLabel(sub)
            self.sub.setWordWrap(True)
            self.sub.setStyleSheet("font-size: 13px; color: #c5c8ce; background: transparent;")
            col.addWidget(self.sub)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.yes_button = QPushButton(yes)
        self.yes_button.setStyleSheet("QPushButton { background: #0d9488; color: white; border: 1px solid #0b766c; }"
                                      " QPushButton:hover { background: #14b8a6; }")
        self.no_button = QPushButton(no)
        self.no_button.setStyleSheet("QPushButton { background: #3c4043; color: white; border: 1px solid #5b5f66; }"
                                     " QPushButton:hover { background: #4a4e52; }")
        for b in (self.yes_button, self.no_button):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        self.yes_button.clicked.connect(lambda: self._answer(True))
        self.no_button.clicked.connect(lambda: self._answer(False))
        row.addWidget(self.yes_button)
        row.addWidget(self.no_button)
        col.addLayout(row)
        self.setFixedWidth(max(460, min(660, self.yes_button.sizeHint().width() + self.no_button.sizeHint().width() + 120)))
        self.adjustSize()

    def _answer(self, value: bool):
        if self._answered:
            return
        self._answered = True
        self.close()
        self._done(value)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._answer(False)
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        if not self._answered:   # закрыли иначе: это «Отмена»
            self._answered = True
            self._done(False)
        super().closeEvent(event)

    def dismiss(self):
        """Ожидание отменено снаружи (Esc в окне перевода): закрыть без повторного ответа."""
        self._answered = True
        self.close()

    def show_at(self, global_center: QPoint):
        self.adjustSize()
        self.move(global_center.x() - self.width() // 2, global_center.y() - self.height() // 2)
        self.show()
        self.raise_()
        self.activateWindow()


# --- уведомление без окна-родителя --------------------------------------------------------------------

_toast_windows = []


def floating_toast(text: str, global_center: QPoint = None):
    """Всплывающее сообщение посреди монитора, когда окна, из которого оно пришло, уже нет (окно выделения закрыто)."""
    from .ocr import Toast
    host = QWidget(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
    host.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    host.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    host.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    host.resize(640, 80)
    host.toast_anchor = lambda: QRect(0, 0, host.width(), host.height())
    bubble = Toast(host)
    if global_center is None:
        screen = QGuiApplication.screenAt(QGuiApplication.primaryScreen().geometry().center()) or QGuiApplication.primaryScreen()
        global_center = screen.geometry().center()
    host.move(global_center.x() - host.width() // 2, global_center.y() - host.height() // 2)
    host.show()
    bubble.pop(text, 2200)
    _toast_windows.append(host)

    def close():
        if host in _toast_windows:
            _toast_windows.remove(host)
        host.close()
        host.deleteLater()
    QTimer.singleShot(Toast.FADE_IN + 2200 + Toast.FADE_OUT + 300, close)
    host.toast = bubble
    return host
