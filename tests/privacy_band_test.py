# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""1.36.1: «Открыть кусок» / «Скрыть кусок» работают при любом инструменте и масштабе (слова владельца 23.11.2026:
«не реагирует»). Обводка главнее пипетки и набираемого текста (раньше нажатие возвращалось раньше, чем доходило до
обводки). Проверяется реальными событиями мыши на холсте: инструменты MOVE, PIPETTE, TEXT с набираемым текстом, STICKER,
OCR; масштаб холста 0,75 и 1,5 (снимок больше окна); открытый кусок показывает исходные пиксели, остальное остаётся
закрытым; плашка «Открыто/Закрыто» и подсказка под кнопками; масштаб экрана задаёт CLIPSD_TEST_SCALE (1, 1.25, 1.5).

Запуск: QT_QPA_PLATFORM=offscreen [CLIPSD_TEST_SCALE=1.5] python3 tests/privacy_band_test.py
"""
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
if os.environ.get("CLIPSD_TEST_SCALE"):
    os.environ["QT_SCALE_FACTOR"] = os.environ["CLIPSD_TEST_SCALE"]
_src = open(os.path.join(_here, "skryt_dannye_test.py"), encoding="utf-8").read().split("def test_button_and_blur")[0]
exec(compile(_src, "skryt_dannye_head", "exec"))   # те же снимок, Ctx и make, что в тесте «Скрыть личные данные»

from clipshot.editor import PIPETTE, STICKER, OCR, TEXT as TOOL_TEXT  # noqa: E402


def run(tool, zoom, mode="open"):
    ed, img, words = make(TEXT)
    ed.hide_personal()
    settle()
    c, panel, s = ed.canvas, ed.privacy_panel, ed.privacy_session
    toasts = []
    ed.show_toast = lambda t, *_a, **_k: toasts.append(t)
    if tool != MOVE:
        ed.select_tool(tool)
        settle()
    if tool == TOOL_TEXT:
        c.start_text(QPointF(20, img.height() - 40))
        settle()
        check(c.text_edit is not None, "перед обводкой набирается текст")
    c.set_zoom(zoom)
    settle()
    panel.tool_buttons[mode].click()
    settle()
    check(panel.tool == mode and c.band_mode == mode, f"[{tool}, масштаб {zoom}] кнопка «{mode}» включена")
    check(panel.band_hint.isVisible() and panel.band_hint.text() != "", "под кнопками видна подсказка")
    i = [f.kind for f in s.findings].index("card")
    wr = words[s.findings[i].chars[0][0]].rect
    z = c.zoom
    a = QPoint(int((wr.left() + wr.width() * 0.5) * z), int((wr.top() - 2) * z))
    b = QPoint(int((wr.right() + 20) * z), int((wr.bottom() + 2) * z))
    QTest.mousePress(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, a)
    QTest.mouseMove(c, QPoint((a.x() + b.x()) // 2, (a.y() + b.y()) // 2))
    QTest.mouseMove(c, b)
    check(c.band is not None, f"[{tool}, масштаб {zoom}] обводка видна, пока мышь зажата")
    QTest.mouseRelease(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, b)
    settle()
    out = c.render()
    opened = QRectF(wr.left() + wr.width() * 0.5 + 2, wr.top() + 3, wr.width() * 0.5 - 4, wr.height() - 6)
    check(region_changed(img, out, opened) == 0, f"[{tool}, масштаб {zoom}] обведённая часть открыта: пиксели как в исходном")
    left = QRectF(wr.left(), wr.top(), wr.width() * 0.4, wr.height())
    check(region_changed(img, out, left) > 4, f"[{tool}, масштаб {zoom}] остальное закрыто")
    check(toasts and toasts[-1] == tr("privacy.band_opened"), f"[{tool}, масштаб {zoom}] плашка «Открыто»")
    finish(ed)


for t in (MOVE, PIPETTE, TOOL_TEXT, STICKER, OCR):
    for zm in (0.75, 1.0, 1.5):
        run(t, zm)

# «Скрыть кусок» при пипетке: поверх нераспознанного слова
ed, img, words = make(TEXT)
ed.hide_personal()
settle()
ed.select_tool(PIPETTE)
ed.privacy_panel.tool_buttons["hide"].click()
settle()
plain = next(w for w in words if w.text == "обычного")
c = ed.canvas
n = len(blur_shapes(ed))
a = QPoint(int(plain.rect.left() * c.zoom) + 1, int(plain.rect.top() * c.zoom) + 1)
b = QPoint(int(plain.rect.right() * c.zoom) - 1, int(plain.rect.bottom() * c.zoom) - 1)
QTest.mousePress(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, a)
QTest.mouseMove(c, b)
QTest.mouseRelease(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, b)
settle()
check(len(blur_shapes(ed)) == n + 1, "«Скрыть кусок» при активной пипетке добавляет закрытие")
finish(ed)
# режим «последние 4»: закрыт сплошной заливкой, открытый кусок показывает оригинал, остаток остаётся закрытым
ed, img, words = make(TEXT)
ed.hide_personal()
settle()
s, c = ed.privacy_session, ed.canvas
i = [f.kind for f in s.findings].index("card")
s.set_mode(i, "last4")
settle()
wr = words[s.findings[i].chars[0][0]].rect
check(all(getattr(sh, "solid", True) for sh in blur_shapes(ed)), "в режиме «последние 4» закрытие сплошное")
s.cut(QRectF(wr.left() + wr.width() * 0.5, wr.top() - 2, wr.width() * 0.5 + 10, wr.height() + 4), "open")
out = c.render()
check(region_changed(img, out, QRectF(wr.left() + wr.width() * 0.5 + 2, wr.top() + 3, wr.width() * 0.5 - 4, wr.height() - 6)) == 0, "«последние 4»: открытая часть показывает оригинал")
check(region_changed(img, out, QRectF(wr.left(), wr.top(), wr.width() * 0.4, wr.height())) > 4, "«последние 4»: остаток закрыт")
check(all(getattr(sh, "solid", True) for sh in blur_shapes(ed)), "после открытия куска остаток по-прежнему сплошной")
finish(ed)
print(f"\nИТОГ: {'проверок ' + str(checks[0]) + ', провалов ' + str(len(failures))}")
sys.exit(1 if failures else 0)
