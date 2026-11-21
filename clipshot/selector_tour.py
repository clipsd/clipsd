# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""1.32: знакомство с окном выделения. Поверх окна затемнение с вырезами вокруг кнопок панели и карточка с пояснением
(тот же вид, что у знакомства в редакторе). Захват не ломается: пока идёт знакомство, окно выделения ничего не снимает."""

from PyQt6.QtCore import QRect, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .i18n import tr
from .tour import CARD_STYLE

PAD = 6   # запас выреза вокруг кнопок


def steps(sel):
    """[(ключ, [прямоугольники для подсветки], заголовок, текст)] по текущей раскладке панели; шаги без кнопок пропускаются."""
    buttons, _bar, _hint = sel._bar_layout()
    by = {b[0]: b[3] for b in buttons}

    def rects(*keys):
        return [by[k] for k in keys if k in by]

    kept = [sel.kept] if sel.kept is not None else []
    lang = [r for r in (sel.lang_rect, sel.gear_rect) if not r.isEmpty()]
    close = [] if sel.bar_close_rect.isEmpty() else [sel.bar_close_rect.adjusted(-2, -2, 2, 2)]
    table = [
        ("area", kept, 1),
        # 21.11.2026 (вариант Б): главная зелёная теперь «Редактировать», она и рассказывается первой после рамки
        ("edit", rects("edit") + kept, 3),
        ("copy", rects("copy"), 2),
        ("manual", rects("manual"), 4),
        ("top", rects("record", "full", "ocr", "phone"), 5),
        ("translate", rects("translate", "translate_pick"), 6),
        ("lang", lang, 7),
        ("close", close, 8),
    ]
    return [(key, holes, tr(f"seltour.s{n}_title"), tr(f"seltour.s{n}_text")) for key, holes, n in table if holes]


class SelectorTour(QWidget):
    finished = pyqtSignal()

    def __init__(self, selector):
        super().__init__(selector)
        self.sel = selector
        self.steps = []
        self.keys = []
        self.index = 0
        self.holes = []
        self.setGeometry(selector.rect())
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.card = QFrame(self)
        self.card.setObjectName("tourCard")
        self.card.setStyleSheet(CARD_STYLE)
        self.card.setFixedWidth(350)
        box = QVBoxLayout(self.card)
        box.setContentsMargins(18, 14, 18, 14)
        box.setSpacing(8)
        self.step_label = QLabel()
        self.step_label.setObjectName("tourStep")
        self.title = QLabel()
        self.title.setObjectName("tourTitle")
        self.text = QLabel()
        self.text.setObjectName("tourText")
        self.text.setWordWrap(True)
        for w in (self.step_label, self.title, self.text):
            box.addWidget(w)
        buttons = QHBoxLayout()
        self.skip = QPushButton(tr("tour.skip"))
        self.skip.setObjectName("tourSkip")
        self.skip.clicked.connect(self.finish)
        self.back = QPushButton(tr("tour.back"))
        self.back.clicked.connect(self.prev)
        self.next = QPushButton(tr("tour.next"))
        self.next.setObjectName("tourNext")
        self.next.clicked.connect(self.forward)
        for b in (self.skip, self.back, self.next):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        buttons.addWidget(self.skip)
        buttons.addStretch(1)
        buttons.addWidget(self.back)
        buttons.addWidget(self.next)
        box.addLayout(buttons)
        self.active = False

    # --- ход ---------------------------------------------------------------

    def start(self):
        self.active = True
        self.setGeometry(self.sel.rect())
        self.refresh_steps()
        self.show()
        self.raise_()
        self.show_step(0)

    def refresh_steps(self):
        self.steps = steps(self.sel)
        self.keys = [s[0] for s in self.steps]

    def show_step(self, index):
        if not self.steps:
            self.finish()
            return
        self.index = max(0, min(index, len(self.steps) - 1))
        _key, holes, title, text = self.steps[self.index]
        self.holes = [QRect(h).adjusted(-PAD, -PAD, PAD, PAD) for h in holes]
        last = self.index == len(self.steps) - 1
        self.step_label.setText(tr("tour.step", i=self.index + 1, total=len(self.steps)))
        self.title.setText(title)
        self.text.setText(text)
        self.back.setEnabled(self.index > 0)
        self.next.setText(tr("tour.finish") if last else tr("tour.next"))
        self.text.ensurePolished()
        width = self.card.width() - 36
        text_h = QFontMetrics(self.text.font()).boundingRect(
            QRect(0, 0, width, 10000), int(Qt.TextFlag.TextWordWrap), text).height() + 4
        self.text.setFixedHeight(text_h)
        box = self.card.layout()
        m = box.contentsMargins()
        self.card.setFixedHeight(m.top() + m.bottom() + 3 * box.spacing() + self.step_label.sizeHint().height()
                                 + self.title.sizeHint().height() + text_h + self.next.sizeHint().height())
        self._place_card()
        self.update()

    def forward(self):
        if self.index >= len(self.steps) - 1:
            self.finish()
        else:
            self.show_step(self.index + 1)

    def prev(self):
        self.show_step(self.index - 1)

    def finish(self):
        if not self.active:
            return
        self.active = False
        self.hide()
        self.finished.emit()
        self.deleteLater()

    # --- геометрия ---------------------------------------------------------

    def _place_card(self):
        """Карточка не закрывает подсвеченное; из остальных мест берётся то, что меньше всего закрывает панель и рамку
        и ближе всего к подсветке."""
        area = self.sel.hint_anchor().intersected(self.rect()).adjusted(12, 12, -12, -12)
        w, h = self.card.width(), self.card.height()
        holes = [QRect(r) for r in self.holes]
        union = QRect()
        for r in holes:
            union = union.united(r)
        soft = [self.sel._bar_layout()[1]] + ([self.sel.kept] if self.sel.kept is not None else [])
        if self.sel.kept is not None:   # подпись размера над левым углом рамки
            soft.append(QRect(self.sel.kept.left(), self.sel.kept.top() - 34, 150, 34))
        soft = [r for r in soft if r is not None and not r.isEmpty()]

        def overlap(a, b):
            c = a.intersected(b)
            return max(0, c.width()) * max(0, c.height()) if c.isValid() else 0

        xs = list(range(area.left(), area.right() - w + 1, 40)) + [area.right() - w]
        ys = list(range(area.top(), area.bottom() - h + 1, 40)) + [area.bottom() - h]
        best = None
        for y in ys:
            for x in xs:
                rect = QRect(x, y, w, h)
                if any(rect.intersects(r) for r in holes):
                    continue
                dist = (abs(rect.center().x() - union.center().x()) + abs(rect.center().y() - union.center().y())
                        if union.isValid() else abs(rect.center().x() - area.center().x())
                        + abs(rect.center().y() - area.center().y()))
                score = 6 * sum(overlap(rect, r) for r in soft) + dist * 8
                if best is None or score < best[0]:
                    best = (score, x, y)
        if best is None:   # некуда: по центру области
            best = (0, area.center().x() - w // 2, area.center().y() - h // 2)
        self.card.move(best[1], best[2])
        self.card.raise_()

    def relayout(self):
        """Окно выделения изменилось (размер, перенос панели): вырезы и карточка пересчитываются."""
        self.setGeometry(self.sel.rect())
        self.refresh_steps()
        self.show_step(self.index)

    # --- отрисовка и ввод --------------------------------------------------

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        shade = QPainterPath()
        shade.addRect(QRectF(self.rect()))
        for r in self.holes:
            cut = QPainterPath()
            cut.addRoundedRect(QRectF(r), 8, 8)
            shade = shade.subtracted(cut)
        p.fillPath(shade, QColor(0, 0, 0, 165))
        p.setPen(QPen(QColor("#ffd23f"), 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for r in self.holes:
            p.drawRoundedRect(QRectF(r), 8, 8)

    def mousePressEvent(self, event):
        event.accept()   # щелчки мимо карточки не доходят до окна выделения: рамка не рисуется, снимок не делается

    def mouseMoveEvent(self, event):
        event.accept()

    def mouseReleaseEvent(self, event):
        event.accept()

    def key(self, event):
        """Клавиши окна выделения при идущем знакомстве: листать и закрывать; остальное (Enter, Ctrl+C) снимка не делает."""
        k = event.key()
        if k in (Qt.Key.Key_Right, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.forward()
        elif k == Qt.Key.Key_Left:
            self.prev()
        elif k == Qt.Key.Key_Escape:
            self.finish()
        event.accept()
