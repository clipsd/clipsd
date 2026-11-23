# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Меню в одном стиле с окнами ClipSD: скруглённые углы, пункты с отступами 9 px, мягкая подсветка под курсором,
сочетания клавиш справа приглушённым цветом (после табуляции в тексте пункта), тонкие разделители.
Меню остаётся настоящим QMenu (клавиатура и поведение прежние): меняется только отрисовка."""

from PyQt6.QtCore import QRect, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import QProxyStyle, QStyle

FONT_PX = 14
PAD_V, PAD_H = 9, 14     # отступы пункта
MARGIN = 6               # поле внутри меню вокруг пунктов


class ClipMenuStyle(QProxyStyle):
    def __init__(self, tokens: dict):
        super().__init__("Fusion")
        from PyQt6.QtWidgets import QApplication
        self.setParent(QApplication.instance())   # живёт вместе с приложением, не удаляется раньше меню
        dark = bool(tokens.get("dark"))
        accent = QColor(tokens["ui_accent"])
        self.accent = accent
        self.bg = QColor(tokens["confirm_bg"]) if dark else QColor("#ffffff")
        self.border = QColor(tokens["confirm_line"]) if dark else QColor("#d9dee6")
        self.text = QColor(tokens["text"]) if dark else QColor("#16181c")
        self.muted = QColor(tokens["text_dim"]) if dark else QColor("#8a93a0")
        self.hover = QColor(accent.red(), accent.green(), accent.blue(), 70 if dark else 38)
        self.off = QColor("#6a6a6a") if dark else QColor("#b6bdc8")
        self.note = QColor("#aab1ba") if dark else QColor("#5a6270")   # пояснение в меню: 4,5:1 и выше в обеих темах

    @staticmethod
    def _font(base: QFont) -> QFont:
        f = QFont(base)
        f.setPixelSize(FONT_PX)
        return f

    @staticmethod
    def _split(text: str):
        label, _sep, shortcut = text.partition("\t")
        return label.replace("&&", "\0").replace("&", "").replace("\0", "&"), shortcut

    def pixelMetric(self, metric, option=None, widget=None):
        if metric in (QStyle.PixelMetric.PM_MenuHMargin, QStyle.PixelMetric.PM_MenuVMargin):
            return MARGIN
        if metric == QStyle.PixelMetric.PM_MenuPanelWidth:
            return 1
        return super().pixelMetric(metric, option, widget)

    def sizeFromContents(self, ctype, option, size, widget=None):
        if ctype == QStyle.ContentsType.CT_MenuItem:
            if option.menuItemType == option.MenuItemType.Separator:
                return QSize(size.width(), 11)
            font = self._font(option.font)
            fm = QFontMetrics(font)
            label, shortcut = self._split(option.text)
            w = 2 * PAD_H + 48 + 14 + fm.horizontalAdvance(label) + (28 + fm.horizontalAdvance(shortcut) if shortcut else 0)
            return QSize(w, fm.height() + 2 * PAD_V)
        return super().sizeFromContents(ctype, option, size, widget)

    def drawPrimitive(self, element, option, painter, widget=None):
        if element in (QStyle.PrimitiveElement.PE_PanelMenu, QStyle.PrimitiveElement.PE_FrameMenu):
            if element == QStyle.PrimitiveElement.PE_PanelMenu:
                painter.save()
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                painter.setPen(QPen(self.border, 1))
                painter.setBrush(self.bg)
                painter.drawRoundedRect(QRectF(option.rect).adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
                painter.restore()
            return
        super().drawPrimitive(element, option, painter, widget)

    def drawControl(self, element, option, painter, widget=None):
        if element != QStyle.ControlElement.CE_MenuItem:
            return super().drawControl(element, option, painter, widget)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = option.rect
        if option.menuItemType == option.MenuItemType.Separator:
            painter.setPen(QPen(self.border, 1))
            y = rect.center().y()
            painter.drawLine(rect.left() + 8, y, rect.right() - 8, y)
            painter.restore()
            return
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        act = widget.actionAt(rect.center()) if widget is not None and hasattr(widget, "actionAt") else None
        if act is not None and act.property("clipsd_note"):
            # строка-пояснение (не пункт): читаемый приглушённый цвет, без подсветки, клавиатура её пропускает
            painter.setFont(self._font(option.font))
            painter.setPen(self.note)
            label, _s = self._split(option.text)
            painter.drawText(rect.adjusted(PAD_H, 0, -PAD_H, 0), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                             label)
            painter.restore()
            return
        if act is not None and act.property("clipsd_section"):
            # 1.36: заголовок раздела меню значка («Снимок», «Инструменты»): мелко, приглушённо, не пункт
            f = self._font(option.font)
            f.setPixelSize(12)
            f.setBold(True)
            painter.setFont(f)
            painter.setPen(self.muted)
            label, _s = self._split(option.text)
            painter.drawText(rect.adjusted(PAD_H, 4, -PAD_H, 0), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), label)
            painter.restore()
            return
        if (option.state & QStyle.StateFlag.State_Selected) and enabled:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self.hover)
            painter.drawRoundedRect(QRectF(rect).adjusted(2, 0, -2, 0), 8, 8)
        elif option.font.bold() and enabled:   # 1.32: жирный пункт = текущий (меню группы инструментов): мягкая подложка
            soft = QColor(self.hover)
            soft.setAlpha(max(20, soft.alpha() * 2 // 3))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(soft)
            painter.drawRoundedRect(QRectF(rect).adjusted(2, 0, -2, 0), 8, 8)
        font = self._font(option.font)
        painter.setFont(font)
        label, shortcut = self._split(option.text)
        inner = rect.adjusted(PAD_H, 0, -PAD_H, 0)
        if option.checked:
            painter.setPen(self.text if enabled else self.off)
            painter.drawText(QRect(inner.left(), rect.top(), 18, rect.height()), Qt.AlignmentFlag.AlignVCenter, "✓")
        shift = 20
        if not option.icon.isNull():   # значок пункта (цвет, размер): правее места отметки, выбранный в рамке
            size = option.icon.actualSize(QSize(64, 64))
            wide = size.width() > size.height() * 1.2   # флаг языка 24x16 рисуется в своём размере
            bw, bh = (24, 16) if wide else (20, 20)
            box = QRect(inner.left() + 22, rect.top() + (rect.height() - bh) // 2, bw, bh)
            option.icon.paint(painter, box)
            if option.checked:
                painter.setPen(QPen(self.accent, 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(QRectF(box).adjusted(-3, -3, 3, 3), 5, 5)
            shift = 52 + (4 if wide else 0)
        # недоступный пункт, который всё же надо прочитать (свёрнутое окно в списке окон): читаемый приглушённый цвет
        soft = not enabled and act is not None and bool(act.property("clipsd_soft"))
        painter.setPen(self.text if enabled else (self.note if soft else self.off))
        # хвост пункта (имя программы в списке окон, « · Microsoft Word») приглушённым читаемым цветом
        tail = act.property("clipsd_tail") if act is not None else None
        head = label[:-len(tail)] if isinstance(tail, str) and tail and label.endswith(tail) else label
        box = QRect(inner.left() + shift, rect.top(), inner.width() - shift, rect.height())
        align = int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        painter.drawText(box, align, head)
        if head != label:
            painter.setPen(self.note if enabled or soft else self.off)
            painter.drawText(box.adjusted(QFontMetrics(font).horizontalAdvance(head), 0, 0, 0), align, label[len(head):])
        if option.menuItemType == option.MenuItemType.SubMenu:
            painter.setPen(self.muted)
            painter.drawText(inner, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight), "›")
        if shortcut:
            painter.setPen(self.muted if enabled else (self.note if soft else self.off))
            painter.drawText(inner, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight), shortcut)
        painter.restore()


_styles = {}   # стиль должен жить, пока живы меню: по одному на оформление


def style_menu(menu, cfg: dict):
    """Меню в стиле ClipSD: скруглённые углы, мягкая подсветка, сочетания справа."""
    from . import themes
    t = themes.tokens(cfg or {})
    key = (t["dark"], t["ui_accent"], t["text"])
    if key not in _styles:
        _styles[key] = ClipMenuStyle(t)
    menu.setStyle(_styles[key])
    menu.setWindowFlags(menu.windowFlags() | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
    menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    return menu
