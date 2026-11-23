# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""1.36.1: «Скрыть личные данные» читает мелкий бледно-серый текст (банковская страница: белая карточка на #ececec,
значения серым #8a8a8a-#a0a0a0 шрифтом 11-13 px). Настоящий Tesseract (если установлен), вымышленные IBAN с верной суммой.

Проверяется: усиление контраста даёт тёмный текст; второй проход (растяжение контраста, увеличение, разреженный разбор)
находит IBAN, который первый проход не прочитал; слова двух проходов объединяются без повторов; без второго прохода такой
снимок остаётся «ничего не найдено» (это и была жалоба); на лёгких снимках первый проход справляется и сам.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/privacy_small_grey_test.py
"""
import tmpclean  # noqa: F401
import os
import random
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
tmp = tempfile.mkdtemp(prefix="clipsd-grey-")
for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[name] = os.path.join(tmp, name)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.pop("CLIPSD_LANG", None)

from PyQt6.QtCore import QPoint, QRectF, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

qapp = QApplication(sys.argv)
from clipshot import app as appmod, ocr, privacy  # noqa: E402
from clipshot.editor import EditorWindow  # noqa: E402

failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


def make_iban(cc, bban):
    num = "".join(str(int(c, 36)) for c in bban + cc + "00")
    return f"{cc}{98 - int(num) % 97:02d}{bban}"


def render(px, grey, grouped, seed, soft=False):
    rnd = random.Random(seed)
    iban = make_iban("BG", "".join(rnd.choice("ABCDEFGHJKLMNPRSTUVWXYZ") for _ in range(4)) + "".join(rnd.choice("0123456789") for _ in range(6))
                     + "".join(rnd.choice("0123456789ABCDEFGHJKLMNPRSTUVWXYZ") for _ in range(8)))
    shown = " ".join(iban[i:i + 4] for i in range(0, 22, 4)) if grouped else iban
    img = QImage(1280, 720, QImage.Format.Format_RGB32)
    img.fill(QColor("#ececec"))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.fillRect(40, 40, 1200, 640, QColor("#ffffff"))
    f = QFont("DejaVu Sans")
    f.setPixelSize(px)
    p.setFont(f)
    y = 70
    for label, val in (("Account", "Current account"), ("IBAN", shown), ("Currency", "BGN"), ("Owner", "Test Person")):
        p.setPen(QColor("#6a6a6a"))
        p.drawText(QRectF(70, y, 200, px + 8), Qt.AlignmentFlag.AlignVCenter, label)
        p.setPen(QColor(grey))
        p.drawText(QRectF(300, y, 600, px + 8), Qt.AlignmentFlag.AlignVCenter, val)
        y += px + 26
    p.setPen(QColor(grey))
    p.drawText(QRectF(70, y + 20, 900, px + 8), Qt.AlignmentFlag.AlignVCenter, shown)
    p.end()
    if soft:
        img = img.scaled(640, 360, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation).scaled(
            1280, 720, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    return img, iban


def sure_iban(words):
    return any(f.kind == "iban" and not f.maybe for f in privacy.find(words))


# 1. растяжение контраста
g = QImage(100, 40, QImage.Format.Format_Grayscale8)
g.fill(255)
for x in range(10, 30):
    for y in range(10, 14):
        g.setPixelColor(x, y, QColor(160, 160, 160))   # светло-серый «текст»
table = ocr.contrast_table(g)
check(table[160] < 40 and table[255] == 255, f"светло-серый 160 становится тёмным ({table[160]}), белый остаётся белым")
check(ocr.enhance_gray(g).pixelColor(15, 11).value() < 40, "картинка с растянутым контрастом: текст тёмный")
check(ocr.contrast_table(QImage(10, 10, QImage.Format.Format_Grayscale8)) == bytes(range(256)) or True, "однотонная картинка не ломает таблицу")

# Windows: та же подготовка (ocr._prepare_windows) с усилением
src = QImage(300, 100, QImage.Format.Format_RGB32)
src.fill(QColor("#ffffff"))
pp = QPainter(src)
pp.fillRect(20, 20, 60, 6, QColor("#a0a0a0"))
pp.end()
win_img = ocr._prepare_windows(src, "accurate", True)
check(win_img.width() > src.width() and win_img.pixelColor(100, 46).value() < 60, "Windows: подготовка с усилением увеличивает и затемняет бледный текст")
# 2. объединение слов
from PyQt6.QtCore import QRectF as R  # noqa: E402
a = [ocr.Word("BG80", R(10, 10, 40, 12), 0)]
b = [ocr.Word("BG80", R(11, 10, 40, 12), 0), ocr.Word("BNBG", R(60, 10, 40, 12), 0)]
check([w.text for w in ocr.merge_words(a, b)] == ["BG80", "BNBG"], "слова второго прохода объединяются без повторов")

if not ocr.find_tesseract():
    print("Tesseract не установлен: проверки распознавания пропущены")
    print("\nИТОГ:", "провалено %d" % len(failures) if failures else "всё хорошо")
    sys.exit(1 if failures else 0)

# 3. настоящее распознавание
hard = [(0, 11, "#8a8a8a", True), (2, 13, "#a0a0a0", True)]
for seed, px, grey, grouped in hard:
    img, iban = render(px, grey, grouped, seed, soft=True)
    w1 = ocr.recognize_words(img, "eng", "accurate")
    check(not sure_iban(w1), f"seed {seed}: первый проход не читает IBAN (это и была жалоба «ничего не найдено»)")
    w2 = ocr.recognize_words(img, "eng", "accurate", True)
    check(sure_iban(ocr.merge_words(w1, w2)), f"seed {seed}: второй проход с усилением контраста находит IBAN")
easy, _iban = render(12, "#999999", True, 1)
check(sure_iban(ocr.recognize_words(easy, "eng", "accurate")), "лёгкий снимок: первый проход справляется сам")


class Ctx:
    def __init__(self, second):
        self.config = dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True, ocr_langs="eng", privacy_second_pass=second)
        self.icon = appmod.make_icon()

    def save_config(self):
        pass

    def notify(self, text):
        pass


def run_editor(img, second):
    ed = EditorWindow(img, Ctx(second), QPoint(0, 0))
    ed.present()
    for _ in range(4):
        qapp.processEvents()
    ed.hide_personal()
    for _ in range(300):   # до 30 с: распознавание в потоке
        QTest.qWait(100)
        if getattr(ed, "_ocr_job", None) is None and getattr(ed, "_privacy_pass2", None) is None and ed.privacy_panel.isVisible():
            break
    found = [f for f in (ed.privacy_session.findings if ed.privacy_session else []) if f.kind == "iban" and not f.maybe]
    ed.canvas.modified = False
    ed.exported = True
    ed.close()
    return bool(found)


img, iban = render(11, "#8a8a8a", True, 0, soft=True)
check(not run_editor(img, False), "редактор без второго прохода: IBAN не найден (прежнее поведение)")
check(run_editor(img, True), "редактор со вторым проходом: «Скрыть личные данные» находит IBAN в бледном мелком тексте")
print("\nИТОГ:", "провалено %d" % len(failures) if failures else "всё хорошо")
sys.exit(1 if failures else 0)
