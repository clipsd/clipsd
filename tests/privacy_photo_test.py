# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""1.36.2: «Скрыть личные данные» на фото карты с телефона и кнопка «Копировать текст» при нажатой «Скрыть кусок»
(слова владельца 24.11.2026: «не скрывает нормально»; «копировать текст … получается наоборот, скрытие данных»).

Фото карты рисуется здесь же: неровный шумный фон, зелёная карта, тестовый номер 4111 1111 1111 1111 и вымышленное
имя. Проверяется: снимок узнаётся как фото, экранный снимок нет; чёрно-белый проход (ocr.PHOTO) читает номер; поиск
находит карту и имя под номером; редактор целиком закрывает и то и другое; выбор «Копировать текст» выключает обводку
«Скрыть кусок», и выделение мышью больше ничего не закрывает.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/privacy_photo_test.py
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QPoint, QRectF, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QLinearGradient  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

qapp = QApplication.instance() or QApplication(sys.argv)
from clipshot import app as appmod  # noqa: E402
from clipshot import ocr, privacy  # noqa: E402
from clipshot.editor import EditorWindow, OCR, merge_privacy_pass  # noqa: E402

failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


NUMBER = "4012 8888 8888 1881"   # тестовый номер Visa (разные цифры: сплошные единицы распознавание путает)
NAME = "IVAN PETROV"             # вымышленное имя


def noise(w, h, seed):
    rnd = random.Random(seed)
    img = QImage(rnd.randbytes(w * h), w, h, w, QImage.Format.Format_Grayscale8)
    return img.copy()


def photo(seed=3, card_col=("#7fae63", "#5e8a48"), ink="#262b22", under=(NAME,)):
    w, h = 620, 900
    img = QImage(w, h, QImage.Format.Format_RGB32)
    p = QPainter(img)
    g = QLinearGradient(0, 0, w, h)
    g.setColorAt(0, QColor("#d9d9d4"))
    g.setColorAt(1, QColor("#9c9c96"))
    p.fillRect(0, 0, w, h, g)
    card = QRectF(60, 330, 500, 300)
    cg = QLinearGradient(card.topLeft(), card.bottomRight())
    cg.setColorAt(0, QColor(card_col[0]))
    cg.setColorAt(1, QColor(card_col[1]))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(cg)
    p.drawRoundedRect(card, 18, 18)
    p.fillRect(QRectF(60, 365, 500, 50), QColor("#e8e4da"))   # полоса
    f = QFont("DejaVu Sans")
    f.setPixelSize(26)
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor(ink))
    p.drawText(QRectF(110, 450, 440, 40), Qt.AlignmentFlag.AlignVCenter, NUMBER)
    f.setPixelSize(22)
    p.setFont(f)
    for k, line in enumerate(under):
        p.drawText(QRectF(110, 505 + k * 40, 440, 34), Qt.AlignmentFlag.AlignVCenter, line)
    p.setBrush(QColor("#e0b8a0"))   # палец
    p.drawEllipse(QRectF(330, 600, 120, 260))
    p.setOpacity(0.10)   # шум матрицы телефона
    p.drawImage(0, 0, noise(w, h, seed))
    p.end()
    return img


def screen():
    img = QImage(900, 400, QImage.Format.Format_RGB32)
    img.fill(QColor("#ffffff"))
    p = QPainter(img)
    f = QFont("DejaVu Sans")
    f.setPixelSize(14)
    p.setFont(f)
    p.setPen(QColor("#222222"))
    for k in range(10):
        p.drawText(20, 30 + k * 30, f"Строка обычного экранного текста номер {k}")
    p.end()
    return img


# проверка 1.36.2, круг 2 (Р1): первый проход прочитал номер с ошибкой, дополнительный верно: верный номер не теряется
first = [ocr.Word(t, QRectF(100 + k * 80, 100, 70, 22), (0, 0)) for k, t in enumerate("9555 5555 5555 4444".split())]
extra = [ocr.Word(t, QRectF(101 + k * 80, 100, 70, 22), (0, 0)) for k, t in enumerate("5555 5555 5555 4444".split())]
merged = merge_privacy_pass(first, extra, "p1")
check([f.kind for f in privacy.find(merged)] == [privacy.CARD] and len(merged) == 4,
      f"слияние: верный номер дополнительного прохода главнее ошибочного ({[w.text for w in merged]})")
plain = [ocr.Word("Hello", QRectF(100, 200, 60, 20), (1, 0))]
merged = merge_privacy_pass(first + plain, [ocr.Word("Hel1o", QRectF(101, 200, 60, 20), (0, 0))], "p1")
check([w.text for w in merged].count("Hello") == 1 and "Hel1o" not in [w.text for w in merged],
      "слияние без находки: слова первого прохода главнее")

img = photo()
check(ocr.looks_like_photo(img), "фото карты узнаётся как фото")
check(not ocr.looks_like_photo(screen()), "экранный снимок не фото")
bw = ocr.binarize_local(img.convertToFormat(QImage.Format.Format_Grayscale8))
check(bw.size() == img.size() and {bw.pixelColor(x, y).value() for x in range(0, 600, 7) for y in range(0, 880, 11)} <= {0, 255},
      "чёрно-белая картинка того же размера, только чёрное и белое")

if not ocr.find_tesseract():
    print("Tesseract не установлен: проверки распознавания пропущены")
    print("\nИТОГ:", "провалено %d" % len(failures) if failures else "всё хорошо")
    sys.exit(1 if failures else 0)

words = ocr.recognize_words(img, "eng", "accurate", ocr.PHOTO)
got = privacy.find(words)
kinds = [f.kind for f in got]
check(privacy.CARD in kinds, f"чёрно-белый проход: номер карты найден ({kinds})")
check(privacy.HOLDER in kinds, f"имя под номером карты найдено ({kinds})")
holder = next((f for f in got if f.kind == privacy.HOLDER), None)
check(holder is not None and holder.masked() == "I*** P***" and holder.hide_by_default and holder.modes() == ("full", "open"),
      "имя: маска «I*** P***», закрыто сразу, режимы «скрыть» и «открыть»")


# синяя карта, белые цифры, под номером строка срока: светлые знаки читает второй чёрно-белый проход, имя ищется под
# строкой «VALID THRU» (проверка 1.36.2, находки 4 и 5)
blue = photo(card_col=("#2457b0", "#1a3f86"), ink="#f2f2f2", under=("VALID THRU 12/28", NAME))
got = privacy.find(ocr.recognize_words(blue, "eng", "accurate", ocr.PHOTO_LIGHT))
kinds = [f.kind for f in got]
check(privacy.CARD in kinds and privacy.HOLDER in kinds, f"синяя карта, светлые цифры: проход PHOTO_LIGHT находит карту и имя ({kinds})")
check(all(f.value != "VALID THRU" for f in got), "«VALID THRU» не принято за имя")


class Ctx:
    def __init__(self):
        self.config = dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True, ocr_langs="eng", privacy_second_pass=True)
        self.icon = appmod.make_icon()

    def save_config(self):
        pass

    def notify(self, text):
        pass


ed = EditorWindow(img, Ctx(), QPoint(0, 0))
ed.present()
for _ in range(4):
    qapp.processEvents()
ed.hide_personal()
for _ in range(400):   # до 40 с: распознавание в потоке
    QTest.qWait(100)
    if getattr(ed, "_ocr_job", None) is None and getattr(ed, "_privacy_pass2", None) is None and ed.privacy_panel.isVisible():
        break
s = ed.privacy_session
kinds = [f.kind for f in s.findings] if s else []
check(s is not None and privacy.CARD in kinds and privacy.HOLDER in kinds, f"редактор: на фото найдены карта и имя ({kinds})")
if s is not None:
    check(all(s.modes[i] == "full" and s.shapes.get(i) for i, f in enumerate(s.findings) if f.kind in (privacy.CARD, privacy.HOLDER)),
          "карта и имя закрыты сразу")
    # «Скрыть кусок» нажата, затем «Копировать текст»: обводка выключена, выделение мышью ничего не закрывает
    panel = ed.privacy_panel
    panel.set_tool("hide", emit=True)
    check(ed.canvas.band_mode == "hide", "«Скрыть кусок» включает обводку")
    shapes_before = len(ed.canvas.shapes)
    ed.ocr_button.click()
    for _ in range(10):
        qapp.processEvents()
    check(ed.canvas.tool == OCR, "«Копировать текст» включает режим текста")
    check(not ed.canvas.band_mode and panel.tool == "" and not any(b.isChecked() for b in panel.tool_buttons.values()),
          "обводка «Скрыть кусок» выключена, кнопка отжата")
    c = ed.canvas
    QTest.mousePress(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(40, 40))
    QTest.mouseMove(c, QPoint(200, 120))
    QTest.mouseRelease(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(200, 120))
    check(len(ed.canvas.shapes) == shapes_before, "выделение мышью в режиме текста ничего не закрывает")
ed.canvas.modified = False
ed.exported = True
ed.close()

# редактор на синей карте: цепочка проходов доходит до светлых знаков
ed = EditorWindow(blue, Ctx(), QPoint(0, 0))
ed.present()
check(ed._privacy_extra_passes() == [ocr.PHOTO, ocr.PHOTO_LIGHT], f"фото: два чёрно-белых прохода ({ed._privacy_extra_passes()})")
for _ in range(4):
    qapp.processEvents()
ed.hide_personal()
for _ in range(600):
    QTest.qWait(100)
    if getattr(ed, "_ocr_job", None) is None and getattr(ed, "_privacy_pass2", None) is None and ed.privacy_panel.isVisible():
        break
s = ed.privacy_session
kinds = [f.kind for f in s.findings] if s else []
check(s is not None and privacy.CARD in kinds and privacy.HOLDER in kinds, f"редактор: синяя карта, карта и имя найдены ({kinds})")
ed.canvas.modified = False
ed.exported = True
ed.close()
ed = EditorWindow(screen(), Ctx(), QPoint(0, 0))
check(ed._privacy_extra_passes() == [True], f"чистый экран: только проход с контрастом ({ed._privacy_extra_passes()})")
ed.canvas.modified = False
ed.exported = True
ed.close()

print("\nИТОГ:", "провалено %d" % len(failures) if failures else "всё хорошо")
sys.exit(1 if failures else 0)
