# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
"""Кружок «думаю»: точки бегут по кругу, пока идёт распознавание или перевод.
Лёгкий модуль: таймер работает только пока кружок на экране."""

import math

from PyQt6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PyQt6.QtWidgets import QWidget

DOTS = 10
TICK_MS = 80


def draw_spinner(p: QPainter, center: QPointF, radius: float, phase: int, color: QColor, dots: int = DOTS):
    """Точки по кругу: ведущая яркая и крупная, за ней затухающий хвост; phase растёт: точки бегут по часовой."""
    dot = max(2.2, radius * 0.17)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    for i in range(dots):
        angle = 2 * math.pi * i / dots - math.pi / 2
        behind = (phase - i) % dots          # 0: ведущая точка
        k = behind / dots
        c = QColor(color)
        c.setAlpha(int(255 * (1 - 0.85 * k)))
        p.setBrush(c)
        r = dot * (1 - 0.5 * k)
        p.drawEllipse(QPointF(center.x() + radius * math.cos(angle), center.y() + radius * math.sin(angle)), r, r)
    p.restore()


class BusySpinner(QWidget):
    """Кружок с подписью по центру родителя (например, поля со снимком); сам следит за размером родителя."""

    def __init__(self, parent: QWidget, text: str = "", color: str = "#7c3aed"):
        super().__init__(parent)
        self.text = text
        self.color = QColor(color)
        self.phase = 0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        parent.installEventFilter(self)
        self._place()

    def start(self):
        self._place()
        self.show()
        self.raise_()
        self.timer.start(TICK_MS)

    def stop(self):
        self.timer.stop()
        self.hide()
        self.deleteLater()

    def _tick(self):
        self.phase += 1
        self.update()

    def _place(self):
        font = QFont()
        font.setPixelSize(14)
        font.setBold(True)
        w = max(150, QFontMetrics(font).horizontalAdvance(self.text) + 40)
        h = 120 if self.text else 90
        par = self.parentWidget()
        self.setGeometry((par.width() - w) // 2, (par.height() - h) // 2, w, h)

    def eventFilter(self, obj, event):
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self._place()
        return False

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 225))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 16, 16)
        draw_spinner(p, QPointF(self.width() / 2, 44), 22, self.phase, self.color)
        if self.text:
            font = QFont()
            font.setPixelSize(14)
            font.setBold(True)
            p.setFont(font)
            p.setPen(QColor("#1d2330"))
            p.drawText(QRectF(0, 80, self.width(), 26), Qt.AlignmentFlag.AlignCenter, self.text)
