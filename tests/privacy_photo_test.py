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
from clipshot.shapes import BLUR  # noqa: E402

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
# 1.36.3 (владелец 24.11.2026): фото карты вставлено «С телефона» поверх экранного снимка: распознавание читает снимок
# вместе со вставленной картинкой, карта находится и закрывается поверх фото
from clipshot.shapes import IMAGE, Shape  # noqa: E402
from PyQt6.QtCore import QPointF  # noqa: E402
big = QImage(1300, 1000, QImage.Format.Format_RGB32)
big.fill(QColor("#ffffff"))
pp = QPainter(big)
pp.drawImage(0, 0, screen())
pp.end()
ed = EditorWindow(big, Ctx(), QPoint(0, 0))
ed.present()
check(ed._privacy_extra_passes() == [True], f"чистый экран: только проход с контрастом ({ed._privacy_extra_passes()})")
card_photo = photo(seed=2)
sh = Shape(IMAGE, "#ff0000", 2, QPointF(640, 60))
sh.points = [QPointF(640, 60), QPointF(640 + card_photo.width(), 60 + card_photo.height())]
sh.image = card_photo.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
ed.canvas.shapes.append(sh)
check(ed._privacy_extra_passes() == [True, (sh, ocr.PHOTO), (sh, ocr.PHOTO_LIGHT)],
      "экран со вставленным фото: оба чёрно-белых прохода по самой картинке (1.36.3)")
src = ed._privacy_source()
check(src.size() == ed.canvas.base.size() and src.pixelColor(640 + 300, 60 + 450) != ed.canvas.base.pixelColor(640 + 300, 60 + 450),
      "снимок для распознавания включает вставленную картинку, размер тот же")
for _ in range(4):
    qapp.processEvents()
ed.hide_personal()
for _ in range(600):
    QTest.qWait(100)
    if getattr(ed, "_ocr_job", None) is None and getattr(ed, "_privacy_pass2", None) is None and ed.privacy_panel.isVisible():
        break
s = ed.privacy_session
kinds = [f.kind for f in s.findings] if s else []
check(s is not None and privacy.CARD in kinds, f"вставленное фото карты: карта найдена ({kinds})")
if s is not None and privacy.CARD in kinds:
    i = kinds.index(privacy.CARD)
    r = s.rect_union(i)[0] if s.rect_union(i) else None
    check(r is not None and r.left() >= 640 and r.top() >= 60, f"закрытие легло на вставленное фото ({r})")
    cover = s.shapes.get(i)
    cover = cover if isinstance(cover, list) else [cover]
    pos = [ed.canvas.shapes.index(x) for x in cover if x in ed.canvas.shapes]
    check(bool(pos) and min(pos) > ed.canvas.shapes.index(sh), f"закрытие нарисовано поверх вставленной картинки ({pos})")
check(not any("8888" in w.text or "1881" in w.text for w in ed.canvas.words),
      "слова фото не попали в слова снимка для «Копировать текст» (находка 5 проверки 1.36.3)")
ed.canvas.modified = False
ed.exported = True
ed.close()


# --- 1.36.3, находки 4-8 проверки 1.36.3 -----------------------------------------------------------------------
def iban_de(bban: str) -> str:
    """Вымышленный IBAN Германии с верной контрольной суммой (mod 97)."""
    digits = "".join(str(int(ch, 36)) for ch in bban + "DE00")
    check_digits = 98 - int(digits) % 97
    raw = f"DE{check_digits:02d}{bban}"
    return " ".join(raw[i:i + 4] for i in range(0, len(raw), 4))


IBAN = iban_de("500105170648489890")


def iban_screen():
    out = QImage(1300, 1000, QImage.Format.Format_RGB32)
    out.fill(QColor("#ffffff"))
    q = QPainter(out)
    f = QFont("DejaVu Sans")
    f.setPixelSize(22)
    q.setFont(f)
    q.setPen(QColor("#111111"))
    q.drawText(20, 40, "Beneficiary account")
    q.drawText(20, 80, "IBAN: " + IBAN)
    for k in range(8):
        q.drawText(20, 140 + k * 36, f"Line of ordinary text number {k}")
    q.end()
    return out


def add_image(editor, image, x, y, w, h):
    shape = Shape(IMAGE, "#ff0000", 2, QPointF(x, y))
    shape.points = [QPointF(x, y), QPointF(x + w, y + h)]
    shape.image = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    editor.canvas.shapes.append(shape)
    return shape


def wait_privacy(editor, limit=900):
    for _ in range(limit):
        QTest.qWait(100)
        if getattr(editor, "_ocr_job", None) is None and getattr(editor, "_privacy_pass2", None) is None \
                and editor.privacy_panel.isVisible():
            break
    session = editor.privacy_session
    return session, ([f.kind for f in session.findings] if session else [])


def fresh_editor(image):
    editor = EditorWindow(image, Ctx(), QPoint(0, 0))
    editor.present()
    for _ in range(4):
        qapp.processEvents()
    return editor


def close_editor(editor):
    editor.canvas.modified = False
    editor.exported = True
    editor.close()


# находка 4: IBAN на экране и фото карты поверх: первый проход находит IBAN, проходы по фото всё равно идут
ed = fresh_editor(iban_screen())
sh = add_image(ed, photo(seed=2), 640, 60, 620, 900)
ed.hide_personal()
s, kinds = wait_privacy(ed)
check(privacy.IBAN in kinds and privacy.CARD in kinds, f"IBAN на экране и вставленное фото карты: найдены оба ({kinds})")
if s is not None and privacy.CARD in kinds:
    r = s.rect_union(kinds.index(privacy.CARD))[0]
    check(sh.rect().contains(r), f"закрытие карты на вставленном фото ({r})")
check(kinds.count(privacy.CARD) == 1 and kinds.count(privacy.IBAN) == 1, f"без повторов ({kinds})")
close_editor(ed)

# находка 5: слова снимка со вставленной картинкой не уходят в «Копировать текст» (картинку потом сдвинут или уберут)
ed = fresh_editor(iban_screen())
words_pic = QImage(600, 160, QImage.Format.Format_RGB32)
words_pic.fill(QColor("#fffbe0"))
q = QPainter(words_pic)
f = QFont("DejaVu Sans")
f.setPixelSize(34)
q.setFont(f)
q.setPen(QColor("#000000"))
q.drawText(20, 60, "ALPHA BRAVO CHARLIE")
q.drawText(20, 120, "DELTA ECHO FOXTROT")
q.end()
sh = add_image(ed, words_pic, 10, 130, 600, 160)
ed.hide_personal()
s, kinds = wait_privacy(ed)
check(privacy.IBAN in kinds, f"IBAN под строками картинки найден ({kinds})")
check(not any(w.text in ("ALPHA", "BRAVO", "DELTA") for w in ed.canvas.words),
      f"слова вставленной картинки не в словах снимка ({[w.text for w in ed.canvas.words][:6]})")
close_editor(ed)

# находка 6: фото уменьшено на снимке до 45 %: читается в собственном разрешении
ed = fresh_editor(iban_screen())
sh = add_image(ed, photo(seed=2), 640, 60, 279, 405)
ed.hide_personal()
s, kinds = wait_privacy(ed)
check(privacy.CARD in kinds and privacy.HOLDER in kinds, f"фото карты, уменьшенное до 45 %: карта и имя найдены ({kinds})")
if s is not None and privacy.CARD in kinds:
    r = s.rect_union(kinds.index(privacy.CARD))[0]
    check(sh.rect().contains(r) and r.width() < 279, f"закрытие на уменьшенной картинке, в её масштабе ({r})")
close_editor(ed)

# синяя карта со светлыми цифрами вставлена поверх экрана: на ней доходит до второго чёрно-белого прохода
ed = fresh_editor(iban_screen())
sh = add_image(ed, blue, 640, 60, 620, 900)
ed.hide_personal()
s, kinds = wait_privacy(ed)
check(privacy.CARD in kinds and privacy.IBAN in kinds, f"вставленная синяя карта и IBAN на экране: найдены ({kinds})")
close_editor(ed)

# находка 7: картинку сдвинули, пока шло распознавание: итог не ложится на старое место
ed = fresh_editor(iban_screen())
sh = add_image(ed, photo(seed=2), 640, 60, 620, 900)
ed.hide_personal()
sh.translate(QPointF(-300, 0))
ed.canvas.update()
for _ in range(300):
    QTest.qWait(100)
    if getattr(ed, "_ocr_job", None) is None and getattr(ed, "_privacy_pass2", None) is None:
        break
QTest.qWait(300)
s = ed.privacy_session
kinds = [f.kind for f in s.findings] if s else []
check(s is None and not any(x.kind == BLUR for x in ed.canvas.shapes),
      f"картинку сдвинули во время распознавания: старый итог не применён ({kinds})")
close_editor(ed)

# находка 8: следы ластика на вставленной картинке видны и распознаванию
ed = fresh_editor(iban_screen())
sh = add_image(ed, photo(seed=2), 640, 60, 620, 900)
sh.erasures = [(40, [QPointF(700, 120), QPointF(900, 120)])]
src = ed._privacy_source()
check(src.pixelColor(800, 120) == ed.canvas.base.pixelColor(800, 120) and src.pixelColor(800, 400) != ed.canvas.base.pixelColor(800, 400),
      "стёртое ластиком на картинке распознавание видит как снимок под ней")
close_editor(ed)

print("\nИТОГ:", "провалено %d" % len(failures) if failures else "всё хорошо")
sys.exit(1 if failures else 0)
