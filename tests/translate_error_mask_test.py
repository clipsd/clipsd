# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""П5 проверки 1.32.2: сообщение об ошибке перевода на маленьком куске видно целиком.

Окошко «Поверх текста» с 1.32.2 на Linux ловит мышь только на рамке перевода и плашке (маска окна). Карточка
сообщения об ошибке не меньше 220x56 точек и рисуется от угла области: на куске 196x34 она шире и выше самого куска,
и маска (рамка ±6) обрезала её справа и снизу, а окно ещё и своим краем. Теперь окно и маска вмещают карточку.

Перевод подменён: сразу ошибка сервиса. Проверки: карточка сообщения внутри окна и внутри маски (Linux) на маленьком
куске и на куске обычного размера.

Запуск: python3 tests/translate_error_mask_test.py
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QPointF, QRect, QRectF, Qt, QTimer  # noqa: E402
from PyQt6.QtGui import QColor, QFontMetrics, QImage  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)
from clipshot import app as appmod, translate, translate_ui  # noqa: E402
from clipshot.i18n import tr  # noqa: E402

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def settle(seconds=0.3):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


ERROR = tr("translate.err_unexpected", error="service unavailable")


class Job:
    def cancel(self):
        pass


def fake_start(image, cfg, on_done, confirm=None, full=False):
    QTimer.singleShot(0, lambda: on_done(translate.ResultList([]), ERROR, None))
    return Job()


translate.start = fake_start


def notice_box(win, card):
    """Где рисуется карточка сообщения (как _tr_notice): от угла области, не меньше 220x56, у правого края окна."""
    reg = QRectF(card.region)
    text = card.message
    if card.email_help():
        text += "\n\n" + tr("translate_ui.no_registration")
    elif card.key_help():
        text += "\n\n" + tr("translate_ui.setup_note")
    fm = QFontMetrics(win._chip_font(13, bold=False))
    width = int(max(220, min(reg.width() - 16, 560)))
    br = fm.boundingRect(QRect(0, 0, width - 64, 2000), Qt.TextFlag.TextWordWrap, text)
    box = QRectF(reg.left() + 8, reg.top() + 8, width, max(br.height() + 24, 56))
    box.moveLeft(max(4.0, min(box.left(), win.width() - box.width() - 4)))
    return box


def visible(win, box):
    """Сколько точек карточки (сетка через 4 точки) внутри окна и внутри маски окна (если маска есть)."""
    m = win.mask()
    pts = [QPointF(x, y) for x in range(int(box.left()) + 1, int(box.right()), 4)
           for y in range(int(box.top()) + 1, int(box.bottom()), 4)]
    inside = [p for p in pts if QRectF(0, 0, win.width(), win.height()).contains(p)
              and (m.isEmpty() or m.contains(p.toPoint()))]
    return len(inside), len(pts)


for label, rect in (("маленький кусок 196x34", QRect(300, 200, 196, 34)),
                    ("кусок обычного размера 600x90", QRect(100, 200, 600, 90))):
    crop = QImage(rect.size(), QImage.Format.Format_RGB32)
    crop.fill(QColor("white"))
    cfg = dict(appmod.DEFAULTS, translate_view="overlay")
    win = translate_ui.FloatingTranslation(crop, 1.0, rect, cfg, chip=True)
    win.start()
    settle()
    card = win.tr_cards[0] if win.tr_cards else None
    check(card is not None and card.state == "error", f"{label}: ошибка перевода показана")
    if card is not None:
        box = notice_box(win, card)
        seen, total = visible(win, box)
        check(seen == total, f"{label}: карточка сообщения видна целиком ({seen} из {total} точек, окно "
                             f"{win.width()}x{win.height()}, маска {'есть' if not win.mask().isEmpty() else 'нет'})")
    win.close()
    settle(0.1)

print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено {len(failures)}")
from clipshot.exitutil import quick_exit  # noqa: E402
quick_exit(1 if failures else 0)
