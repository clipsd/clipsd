# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Текст с картинки: подготовка картинки, настоящее распознавание (Tesseract или встроенное в Windows),
инструмент в редакторе, кнопка «Текст» в окне выделения.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/ocr_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import os
import sys
import time

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QImage, QKeyEvent, QPainter, QPixmap
from PyQt6.QtCore import QEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
from clipshot import app as appmod, ocr
from clipshot.editor import EditorWindow, MOVE, OCR
from clipshot.selector import RegionSelector
failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def sample(fg="#222222", bg="#ffffff", px=15, lines=None, w=760, h=150):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(bg))
    p = QPainter(img)
    f = QFont()
    f.setPixelSize(px)
    p.setFont(f)
    p.setPen(QColor(fg))
    for i, line in enumerate(lines or ["Посылка Swiftpost 220 г, доставка 150 км",
                                       "Заказ 4581 от 08.11.2026",
                                       "Email: info@example.com, тел. +7 (918) 123-45-67"]):
        p.drawText(12, 30 + i * 36, line)
    p.end()
    return img


def columns_sample():
    img = QImage(900, 260, QImage.Format.Format_RGB32)
    img.fill(QColor("#ffffff"))
    p = QPainter(img)
    f = QFont()
    f.setPixelSize(15)
    p.setFont(f)
    p.setPen(QColor("#222222"))
    p.drawText(20, 30, "Отслеживание посылок Swiftpost")
    for i, (l, r) in enumerate(zip(["Посылка в Порту", "вес 1,5 кг", "до двери", "срок 3 дня"],
                                   ["Письмо в Лиссабон", "вес 0,2 кг", "в отделение", "срок 5 дней"])):
        p.drawText(20, 80 + i * 28, l)
        p.drawText(470, 80 + i * 28, r)
    p.drawText(20, 230, "Страховка на всё 30 дней")
    p.end()
    return img


def wait(cond, seconds=90):
    end = time.time() + seconds
    while not cond() and time.time() < end:
        app.processEvents()
        QTest.qWait(50)
    return cond()


# 1. Подготовка
dark = ocr.prepare(sample("#e8e8e8", "#1e1f22"))
check(ocr._mean_brightness(dark) > 128, "тёмная тема переворачивается в светлую")
check(dark.width() == 760 * 3, "мелкая картинка увеличивается в 3 раза")
big = ocr.prepare(QImage(6000, 1440, QImage.Format.Format_RGB32))
check(big.width() * big.height() <= ocr.MAX_PIXELS, "большая картинка не раздувается сверх предела")
check(ocr.tidy("a  \n|\n\n\n\nb\f") == "a\n\nb", "чистка: пробелы, мусорные строки, лишние пустые строки")

# 1а. Раскладка по столбцам на заданных рамках (без движка: одинаково на Linux и Windows)
from PyQt6.QtCore import QRectF


def W(text, x, y, line, w=None, h=14):
    return ocr.Word(text, QRectF(x, y, w or len(text) * 8, h), line)


raw = [W("Заголовок", 20, 10, "h"), W("страницы", 110, 10, "h"),
       # Tesseract склеил строки двух столбцов в одну (строки r1..r3)
       W("левый", 20, 50, "r1"), W("один", 70, 50, "r1"), W("правый", 400, 50, "r1"), W("один", 460, 50, "r1"),
       W("левый", 20, 75, "r2"), W("два", 70, 75, "r2"), W("правый", 400, 75, "r2"), W("два", 460, 75, "r2"),
       W("левый", 20, 100, "r3"), W("три", 70, 100, "r3"), W("правый", 400, 100, "r3"), W("три", 460, 100, "r3"),
       W("Итог", 20, 150, "f"), W("внизу", 60, 150, "f")]
check(ocr.words_text(ocr.layout(raw)) ==
      "Заголовок страницы\nлевый один\nлевый два\nлевый три\nправый один\nправый два\nправый три\nИтог внизу",
      "два столбца: сначала левый целиком, потом правый; заголовок и итог на месте")
para = [W("Обычный", 20, 10, 1), W("текст", 90, 10, 1), W("в", 140, 10, 1), W("одну", 155, 10, 1), W("колонку", 195, 10, 1),
        W("вторая", 20, 32, 2), W("строка", 80, 32, 2)]
check(ocr.words_text(ocr.layout(para)) == "Обычный текст в одну колонку\nвторая строка", "одна колонка не рвётся")
three = []
for row in range(3):
    for col, x in enumerate((20, 260, 500)):
        three.append(W(f"к{col + 1}с{row + 1}", x, 20 + row * 24, f"r{row}"))
check(ocr.words_text(ocr.layout(three)) == "к1с1\nк1с2\nк1с3\nк2с1\nк2с2\nк2с3\nк3с1\nк3с2\nк3с3", "три столбца по порядку")

engine = ocr.engine_name()
# Tesseract 4 (Ubuntu 22.04) reads a line in one script: a Latin word inside a Cyrillic line comes out garbled
# ("Swiftpost" -> "$\\/Йроз{"). Mixed lines are checked from Tesseract 5 on; the word tests then use a Russian word.
TESS_MAJOR = 0
if engine == "tesseract":
    import re as _re
    import subprocess as _sp
    try:
        _out = _sp.run([ocr.find_tesseract(), "--version"], capture_output=True, text=True, timeout=30)
        _m = _re.search(r"tesseract\s+v?(\d+)", (_out.stdout or "") + (_out.stderr or ""))
        TESS_MAJOR = int(_m.group(1)) if _m else 0
    except (OSError, _sp.SubprocessError, TypeError):
        TESS_MAJOR = 0
    print("Tesseract major:", TESS_MAJOR)
MIXED = engine != "tesseract" or TESS_MAJOR >= 5
WORD = "Swiftpost" if MIXED else "Посылка"   # a word of the first line the engine reads reliably
print("движок:", engine or "нет")

# 2. Настоящее распознавание
def windows_sample(path):
    """Картинку рисует сама Windows (System.Drawing, настоящие шрифты): Qt без экрана на Windows буквы может не нарисовать."""
    import subprocess
    ps = ("Add-Type -AssemblyName System.Drawing; $b = New-Object System.Drawing.Bitmap 760,150; "
          "$g = [System.Drawing.Graphics]::FromImage($b); $g.Clear([System.Drawing.Color]::White); "
          "$f = New-Object System.Drawing.Font 'Segoe UI',20; "
          "$g.DrawString('Hello ClipSD 2026', $f, [System.Drawing.Brushes]::Black, 12, 20); "
          "$g.DrawString('Screenshot text recognition', $f, [System.Drawing.Brushes]::Black, 12, 70); "
          f"$b.Save('{path}', [System.Drawing.Imaging.ImageFormat]::Png)")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, timeout=60)
    return QImage(path)


def dark_pixels(img):
    return sum(1 for y in range(0, img.height(), 3) for x in range(0, img.width(), 3) if img.pixelColor(x, y).value() < 100)


qt_sample = sample(lines=["Hello ClipSD 2026"], px=22)
print("тёмных точек на картинке Qt:", dark_pixels(qt_sample))
if sys.platform == "win32" and engine == "windows":
    import tempfile
    img = windows_sample(os.path.join(tempfile.mkdtemp(), "win.png"))
    check(not img.isNull() and dark_pixels(img) > 50, f"картинка с текстом нарисована: тёмных точек {dark_pixels(img)}")
    try:
        text = ocr.recognize(img)
        print("Windows OCR:", repr(text), ocr.last_info)
        check("ClipSD" in text and "2026" in text, "встроенное распознавание Windows читает английский текст")
        ws = ocr.recognize_words(img)
        hello = next((w for w in ws if w.text == "Hello"), None)
        print("Windows слова:", [(w.text, round(w.rect.x()), round(w.rect.y())) for w in ws])
        check(hello is not None and 0 <= hello.rect.x() < 60 and 10 <= hello.rect.y() < 60,
              "Windows: у слов правильные рамки (для выделения маркером)")
    except ocr.OcrError as exc:
        print("Windows OCR недоступно:", exc)
        check("язык" in str(exc), "без языкового пакета понятное сообщение")
elif engine == "tesseract":
    text = ocr.recognize(sample())
    print("Tesseract:", repr(text))
    if MIXED:
        check("Посылка" in text and "Swiftpost" in text, "русский и английский в одной строке")
    else:
        print("skip: Tesseract", TESS_MAJOR, "не читает латинское слово в русской строке (ограничение версии)")
        check("Посылка" in text and "доставка" in text, "русская строка читается (Tesseract 4)")
    check("info@example.com" in text and "123-45-67" in text, "почта и телефон")
    text2 = ocr.recognize(sample("#e8e8e8", "#1e1f22", px=13))
    check("Заказ 4581" in text2 and "08.11.2026" in text2, f"мелкий светлый текст на тёмном фоне: {text2!r}")
    check(ocr.recognize(QImage(300, 100, QImage.Format.Format_RGB32).copy()) == "" or True, "пустая картинка не падает")
else:
    try:
        ocr.recognize(sample())
        check(False, "без движка должна быть понятная ошибка")
    except ocr.OcrError as exc:
        check("apt install" in str(exc), "без Tesseract: подсказка, как установить")


class Ctx:
    config = dict(appmod.DEFAULTS)
    icon = appmod.make_icon()
    def copy_image(self, image): pass
    def notify(self, text): pass
    def save_config(self): pass


# 3. Режим «Копировать текст»: маркер
ctx = Ctx()
ctx.config = dict(appmod.DEFAULTS)
ed = EditorWindow(sample(), ctx, QPoint(50, 50))
ed.present()
for _ in range(6):
    app.processEvents(); QTest.qWait(20)
ed.set_zoom(1.0)
ed.resize(1500, ed.height())   # 1.32: в узком окне группы свёрнуты и больших кнопок нет; здесь окно широкое
app.processEvents(); QTest.qWait(30); app.processEvents()
c = ed.canvas
check(OCR in ed.tool_buttons and ed.tool_buttons[OCR].isVisible(), "кнопка инструмента есть")
check(ed.ocr_button.isVisible() and "Копировать текст" in ed.ocr_button.text(), "фиолетовая кнопка «Копировать текст»")
check(ed.ocr_button.objectName() == "ocrButton" and "#5b21b6" in ed.styleSheet() and "#7c3aed" in ed.styleSheet(),
      "кнопка фиолетовая (1.32: мягкая заливка, фиолетовый текст)")


def line_of(word):
    w0 = next(w for w in c.words if w.text.startswith(word))
    ws = [w for w in c.words if w.line == w0.line]
    return ws


def stroke(a, b, mods=Qt.KeyboardModifier.NoModifier, steps=10):
    QTest.mousePress(c, Qt.MouseButton.LeftButton, mods, a)
    for i in range(1, steps + 1):
        QTest.mouseMove(c, QPoint(a.x() + (b.x() - a.x()) * i // steps, a.y() + (b.y() - a.y()) * i // steps))
    QTest.mouseRelease(c, Qt.MouseButton.LeftButton, mods, b)
    app.processEvents()


if engine == "tesseract":
    QTest.mouseClick(ed.ocr_button, Qt.MouseButton.LeftButton)
    check(c.tool == OCR and ed.ocr_button.isChecked(), "кнопка включает режим текста")
    app.processEvents()
    sp = getattr(ed, "_ocr_spinner", None)
    check(sp is not None and sp.isVisible() and sp.timer.isActive(), "пока распознаётся: кружок «думаю» по центру и крутится")
    check(wait(lambda: c.has_words()), "снимок распознан, слова найдены")
    check(getattr(ed, "_ocr_spinner", None) is None, "распознано: кружок исчез")
    check(len(c.words) >= 8, f"слов найдено: {len(c.words)}")
    # «Подряд» (по умолчанию): от слова вниз через строки, весь текст подряд
    check(c.text_mode == "range" and ed.text_mode_box.isVisible() and ed.text_mode_buttons["range"].isChecked(),
          "по умолчанию «Подряд», переключатель виден")
    z = next(w for w in c.words if w.text == "Заказ")
    em = next(w for w in c.words if w.text.startswith("Email"))
    stroke(z.rect.center().toPoint(), em.rect.center().toPoint())
    clip = QGuiApplication.clipboard().text()
    check(clip == "Заказ 4581 от 08.11.2026\nEmail:", f"«Подряд»: от «Заказ» вниз до «Email:»: {clip!r}")
    w4 = next(w for w in c.words if w.text == "4581")
    wp = next(w for w in c.words if w.text == WORD)
    stroke(w4.rect.center().toPoint(), wp.rect.center().toPoint())
    clip = QGuiApplication.clipboard().text()
    check(clip.startswith(WORD) and clip.endswith("Заказ 4581"), f"«Подряд» в обратную сторону, вверх: {clip!r}")
    last = c.words[-1]
    stroke(z.rect.center().toPoint(), QPoint(c.width() - 5, c.height() - 5))
    clip = QGuiApplication.clipboard().text()
    check(clip.startswith("Заказ") and clip.endswith(last.text), "«Подряд» за край текста: до последнего слова")
    # «Подряд» на снимке с двумя столбцами: тянем вниз по левому, правый не попадает
    ed2 = EditorWindow(columns_sample(), ctx, QPoint(60, 60))
    ed2.present()
    for _ in range(6):
        app.processEvents(); QTest.qWait(20)
    ed2.set_zoom(1.0)
    ed2.select_tool(OCR)
    check(wait(lambda: ed2.canvas.has_words()), "два столбца: распознано")
    c2 = ed2.canvas
    ed2.set_text_mode("range")
    first = next(w for w in c2.words if w.text.startswith("Посылка"))
    lastw = next(w for w in c2.words if w.text == "дня" and w.rect.left() < 300)
    QTest.mousePress(c2, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, first.rect.center().toPoint())
    QTest.mouseMove(c2, QPoint(100, 150)); QTest.mouseMove(c2, lastw.rect.center().toPoint())
    QTest.mouseRelease(c2, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, lastw.rect.center().toPoint())
    app.processEvents()
    clip = QGuiApplication.clipboard().text()
    check(clip == "Посылка в Порту\nвес 1,5 кг\nдо двери\nсрок 3 дня",
          f"два столбца, «Подряд» вниз по левому: только левый столбец: {clip!r}")
    ed2.select_tool(MOVE)
    if getattr(ed2, "_text_panel", None) is not None:
        ed2._text_panel.close()
    ed2.close()
    ed.activateWindow()   # клавиши дальше в первое окно
    ed.canvas.setFocus()
    for _ in range(4):
        app.processEvents(); QTest.qWait(20)
    # переключение на «Маркер», выбор запоминается
    QTest.mouseClick(ed.text_mode_buttons["marker"], Qt.MouseButton.LeftButton)
    check(c.text_mode == "marker" and ctx.config.get("ocr_select_mode") == "marker", "переключатель: «Маркер», запомнилось")
    ws = line_of("Заказ")
    y = round(ws[0].rect.center().y())
    stroke(QPoint(round(ws[0].rect.left()) - 2, y), QPoint(round(ws[-1].rect.right()) + 2, y))
    clip = QGuiApplication.clipboard().text()
    check(clip == "Заказ 4581 от 08.11.2026", f"маркер по строке: в буфере {clip!r}")
    panel = getattr(ed, "_text_panel", None)
    check(panel is not None and panel.isVisible() and panel.edit.toPlainText() == clip, "выделенное открылось в окне для копирования")
    bubble = ed.findChild(ocr.Toast, "clipsdToast")
    check(bubble is not None and bubble.isVisible() and "скопирован в буфер обмена" in bubble.text(),
          "всплывает «Текст скопирован в буфер обмена»")
    check("Скопировано" in panel.copy_button.text(), "кнопка в окне сразу «✓ Скопировано»")
    panel.edit.setPlainText(clip + " исправлено")
    check(panel.copy_button.text() == "Скопировать", "после правки текста кнопка снова «Скопировать»")
    QTest.mouseClick(panel.copy_button, Qt.MouseButton.LeftButton)
    check(QGuiApplication.clipboard().text() == clip + " исправлено", "кнопка кладёт в буфер исправленный текст")
    check("Скопировано" in panel.copy_button.text(), "после нажатия снова «✓ Скопировано»")
    pb = panel.findChild(ocr.Toast, "clipsdToast")
    check(pb is not None and pb.isVisible(), "в окне с текстом тоже всплывает сообщение")
    end = time.time() + 4
    while bubble.isVisible() and time.time() < end:
        app.processEvents(); QTest.qWait(50)
    check(not bubble.isVisible(), "сообщение само исчезает через пару секунд")
    panel.edit.setPlainText(clip)
    # только одно слово маркером
    w = next(w for w in c.words if w.text == WORD)
    stroke(QPoint(round(w.rect.left()) + 2, round(w.rect.center().y())), QPoint(round(w.rect.right()) - 2, round(w.rect.center().y())))
    clip = QGuiApplication.clipboard().text()
    check(clip == WORD, f"маркер по одному слову: {clip!r}")
    check(ed._text_panel is panel and panel.edit.toPlainText() == WORD, "окно одно, текст в нём обновился")
    # Ctrl + мазок добавляет кусок с другой строки
    em = next(w for w in c.words if "example" in w.text)
    stroke(QPoint(round(em.rect.left()) + 2, round(em.rect.center().y())), QPoint(round(em.rect.right()) - 2, round(em.rect.center().y())),
           Qt.KeyboardModifier.ControlModifier)
    clip = QGuiApplication.clipboard().text()
    check(clip.startswith(WORD + "\ninfo@example.com"), f"Ctrl + мазок добавляет: {clip!r}")
    # двойной щелчок: одно слово
    n = next(w for w in c.words if w.text == "4581")
    QTest.mouseDClick(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, n.rect.center().toPoint())
    check(QGuiApplication.clipboard().text() == "4581", "двойной щелчок: одно слово")
    # Ctrl+A и Ctrl+C
    QTest.keyClick(ed, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    clip = QGuiApplication.clipboard().text()
    check(("Посылка Swiftpost" if MIXED else "Посылка") in clip and "info@example.com" in clip, "Ctrl+A: весь текст")
    QGuiApplication.clipboard().setText("")
    QTest.keyClick(ed, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    check("Заказ 4581" in QGuiApplication.clipboard().text(), "Ctrl+C в режиме текста копирует выделенный текст, не снимок")
    check(len(c.shapes) == 0 and (c.base.width(), c.base.height()) == (760, 150), "снимок и рисунки не меняются")
    # маркер мимо текста ничего не выделяет
    QGuiApplication.clipboard().setText("прежнее")
    stroke(QPoint(600, 140), QPoint(740, 140))
    check(QGuiApplication.clipboard().text() == "прежнее" and not c.text_sel, "мазок по пустому месту ничего не копирует")
    # Esc выходит
    QTest.keyClick(ed, Qt.Key.Key_Escape)
    check(c.tool != OCR and not ed.ocr_button.isChecked(), "Esc: выход из режима текста")
    check(not ed.text_mode_box.isVisible(), "вне режима текста переключатель скрыт")
    # выход «Готово» возвращает прежний инструмент, дальше снимок обрабатывается как обычно
    from clipshot.editor import RECT
    ed.select_tool(RECT)
    ed.select_tool(OCR)
    app.processEvents()
    check("Готово" in ed.ocr_button.text(), f"в режиме текста кнопка «Готово»: {ed.ocr_button.text().strip()!r}")
    QTest.mouseClick(ed.ocr_button, Qt.MouseButton.LeftButton)
    check(c.tool == RECT and "Копировать текст" in ed.ocr_button.text(), "«Готово»: вернулся прежний инструмент (прямоугольник)")
    before = len(c.shapes)
    QTest.mousePress(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(300, 20))
    QTest.mouseMove(c, QPoint(360, 60)); QTest.mouseMove(c, QPoint(420, 100))
    QTest.mouseRelease(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(420, 100))
    check(len(c.shapes) == before + 1, "после выхода рисование работает")
    c.undo()
    ed.select_tool(OCR)
    QTest.keyClick(ed, Qt.Key.Key_Escape)
    check(c.tool == RECT, "Esc тоже возвращает прежний инструмент")
    ed.select_tool(OCR)
    ed.select_tool(RECT)
    check(c.tool == RECT and not ed.text_mode_box.isVisible() and "Копировать текст" in ed.ocr_button.text(),
          "выбор другого инструмента на панели тоже выходит из режима текста")
    # повторный вход не распознаёт заново
    ed.select_tool(OCR)
    app.processEvents()
    check(c.has_words() and ed._ocr_job is None, "повторный вход: распознанное уже готово, без ожидания")
    check(c.text_mode == "marker" and ed.text_mode_buttons["marker"].isChecked(), "повторный вход: способ «Маркер» сохранился")
    ed.set_text_mode("range")
    ed.select_tool(MOVE)
    panel.close()

# 3а. Выключено в настройках: кнопок нет, клавиша и вызовы ничего не делают
ctx.config["ocr_enabled"] = False
ed.refresh_theme()
check(not ed.tool_strip.visible_widget(OCR).isVisible() and not ed.ocr_button.isVisible(), "выключено: кнопки скрыты")
ed.select_tool(OCR)
check(c.tool != OCR, "выключено: режим не включается")
check(not any("текст" in a.text().lower() for a in ed.build_context_menu(None).actions()), "выключено: нет пункта в меню")
ctx.config["ocr_enabled"] = True
ed.refresh_theme()
check(ed.ocr_button.isVisible() or ed.tool_strip.visible_widget(OCR).isVisible(), "включено снова: кнопка вернулась")

# 3б. Программы распознавания нет: подсказка, команда и ссылка с кнопками «Скопировать»
if sys.platform != "win32":
    real_find = ocr.find_tesseract
    ocr.find_tesseract = lambda: None
    c.words, c.words_key = [], None   # забыть прежнее распознавание
    try:
        ocr.recognize(sample())
        check(False, "без программы должна быть ошибка")
    except ocr.OcrError as exc:
        h = exc.help
        check(h is not None and h.command and "tesseract-ocr-rus" in h.command and h.url == ocr.TESSERACT_GUIDE,
              f"подсказка: команда {h.command if h else None!r} и ссылка")
    ed._ocr_dialog = None
    ed.select_tool(MOVE)
    ed.select_tool(OCR)
    check(wait(lambda: ed._ocr_job is None and getattr(ed, "_ocr_dialog", None) is not None, 15), "окно с подсказкой открылось")
    dlg = ed._ocr_dialog
    block = dlg.install
    check(block is not None and block.command_field.text().startswith("sudo "), "в окне поле с командой")
    QTest.mouseClick(block.command_field.copy_button, Qt.MouseButton.LeftButton)
    check(QGuiApplication.clipboard().text() == block.command_field.text(), "кнопка «Скопировать команду» копирует")
    tb = dlg.findChild(ocr.Toast, "clipsdToast")
    check(tb is not None and tb.isVisible() and "Команда скопирована" in tb.text(), "всплывает «Команда скопирована»")
    QTest.mouseClick(block.url_field.copy_button, Qt.MouseButton.LeftButton)
    check(QGuiApplication.clipboard().text() == ocr.TESSERACT_GUIDE, "кнопка «Скопировать ссылку» копирует")
    check(c.tool != OCR, "без программы режим текста выключается сам")
    dlg.close()
    ocr.find_tesseract = real_find
    real_langs = ocr.tesseract_langs
    ocr.tesseract_langs = lambda exe: {"eng", "osd"}
    h = ocr.missing_rus_help()
    check(engine != "tesseract" or (h is not None and "rus" in (h.command or "")), "нет русского: подсказка доставить русский")
    ocr.tesseract_langs = real_langs
h = ocr.install_help("windows_lang")
check(h.settings_url == "ms-settings:regionlanguage" and h.url.startswith("https://support.microsoft.com"), "Windows: ссылка Microsoft и кнопка параметров языка")

# 4. Окно выделения: кнопка «Текст» и Ctrl+T
sel = RegionSelector(QPixmap.fromImage(sample()), QRect(0, 0, 760, 150), last_rect=QRect(10, 10, 300, 100))
keys = [b[0] for b in sel._bar_buttons()]
check("ocr" in keys, "в окне выделения есть кнопка «Копировать текст»")
sel.ocr_enabled = False
check("ocr" not in [b[0] for b in sel._bar_buttons()], "выключено: в окне выделения кнопки нет")
sel.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_T, Qt.KeyboardModifier.ControlModifier))
check(not sel._done, "выключено: Ctrl+T ничего не делает")
sel.ocr_enabled = True
got = []
sel.finished.connect(lambda pix, rect: got.append(sel.action))
sel.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_T, Qt.KeyboardModifier.ControlModifier))
check(got == ["ocr"], f"Ctrl+T снимает область для распознавания: {got}")
print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено: {len(failures)}")
from clipshot.exitutil import quick_exit
quick_exit(1 if failures else 0)
