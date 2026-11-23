# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""1.34.3: каким движком и языком распознан снимок (русский Windows, а текст латиницей и без подсказки, 22.11.2026).

Проверяется: журнал ocr.log (движок, OCR_AVAIL, OCR_WANT, OCR_LANG, языки Tesseract); подсказка при пустом или без
русского OCR_AVAIL и OCR_LANG=en-US, и когда OCR_WANT не пришёл; Tesseract найден без русского: берётся встроенное
распознавание Windows, если оно читает русский (иначе остаётся Tesseract и подсказка); строка «Распознано: …» в окне.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/ocr_dvizhok_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import base64
import os
import subprocess
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["CLIPSD_LANG"] = "ru"
tmp = tempfile.mkdtemp(prefix="clipsd-ocrd-")
for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[name] = os.path.join(tmp, name)

from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
from clipshot import ocr, sysenv, translate  # noqa: F401  (translate: до подмены sys.platform, он тянет модули Windows)
from clipshot.i18n import tr
failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def row(text):
    b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
    return "\t".join(["U", "0", "10", "20", "50", "20", b64]) + "\r\n"


TSV = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n" \
      "5\t1\t1\t1\t1\t1\t10\t10\t40\t20\t90\tHello\n"
calls = []


def fake_factory(tess_langs, win_stderr):
    def fake_run(cmd, **kw):
        if "-EncodedCommand" in cmd:
            calls.append("powershell")
            return subprocess.CompletedProcess(cmd, 0, row("Рекомендовано").encode("utf-8"), win_stderr.encode("utf-8"))
        if "--list-langs" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "List of available languages (%d):\n" % len(tess_langs)
                                               + "\n".join(tess_langs) + "\n", "")
        calls.append("tesseract")
        return subprocess.CompletedProcess(cmd, 0, TSV.encode(), b"")
    return fake_run


real = (ocr.subprocess.run, sys.platform, ocr.find_tesseract, sysenv._system_dir)
SYSDIR = os.path.join(os.path.abspath(os.sep), "Windows", "System32")


def recognize(tess, tess_langs, win_stderr):
    """OcrJob.run() как на Windows: tess None = Tesseract не найден."""
    calls.clear()
    ocr.subprocess.run = fake_factory(tess_langs, win_stderr)
    ocr.find_tesseract = lambda: tess
    sysenv._system_dir = lambda: SYSDIR
    sys.platform = "win32"
    try:
        img = QImage(300, 80, QImage.Format.Format_RGB32)
        img.fill(QColor("white"))
        job = ocr.OcrJob(img, "rus+eng")
        got = {}
        job.done.connect(lambda t, e: got.update(text=t, error=e))
        job.run()
    finally:
        ocr.subprocess.run, sys.platform, ocr.find_tesseract, sysenv._system_dir = real
    return job, got


def log_text():
    try:
        return ocr.log_path().read_text(encoding="utf-8")
    except OSError:
        return ""


# 1. Windows без Tesseract взял английский: подсказка, строка «Распознано», журнал
job, got = recognize(None, [], "OCR_AVAIL=en-US\r\nOCR_WANT=ru OCR_LANG=en-US OCR_LINES=1\r\n")
check(job.help is not None, "русский просили, Windows взял en-US: подсказка есть")
check("Windows" in job.used and "Распознано" in job.used, f"строка «Распознано: …» называет движок ({job.used!r})")
log = log_text()
check("engine=windows" in log and "OCR_AVAIL=en-US" in log and "OCR_WANT=ru" in log and "OCR_LANG=en-US" in log,
      "журнал: движок, OCR_AVAIL, OCR_WANT, OCR_LANG")

# 2. Подсказка при пустом OCR_AVAIL и без русского, и когда OCR_WANT не пришёл
check(ocr.windows_fallback_help("OCR_AVAIL= OCR_LANG=en-US", "ru") is not None, "OCR_AVAIL пустой, OCR_LANG=en-US: подсказка")
check(ocr.windows_fallback_help("OCR_AVAIL=en-US,de-DE OCR_LANG=en-US", "ru") is not None, "в OCR_AVAIL нет ru: подсказка")
check(ocr.windows_fallback_help("OCR_AVAIL=en-US OCR_LANG=en-US") is None, "ничего не просили (нет want): без подсказки")
check(ocr.windows_fallback_help("OCR_AVAIL=ru-RU,en-US OCR_LANG=ru-RU", "ru") is None, "ru в списке и взят: без подсказки")
job, got = recognize(None, [], "OCR_AVAIL=en-US\r\nOCR_LANG=en-US OCR_LINES=1\r\n")   # сценарий не сообщил OCR_WANT
check(job.help is not None, "OCR_WANT не пришёл, взят en-US: подсказка есть (язык известен из запроса)")
job, got = recognize(None, [], "OCR_AVAIL=\r\nOCR_WANT=ru OCR_LANG=en-US\r\n")
check(job.help is not None, "OCR_AVAIL пустой: подсказка есть")
job, got = recognize(None, [], "OCR_AVAIL=ru-RU,en-US\r\nOCR_WANT=ru OCR_LANG=ru-RU\r\n")
check(job.help is None and job.used == "", "русский взят: подсказки и строки «Распознано» нет")

# 3. Tesseract без русского, встроенное Windows читает русский: берётся встроенное
job, got = recognize("C:/Tesseract/tesseract.exe", ["eng", "osd"], "OCR_AVAIL=ru-RU,en-US\r\nOCR_WANT=ru OCR_LANG=ru-RU\r\n")
check(calls == ["powershell"] and got.get("text") == "Рекомендовано", f"Tesseract без rus, Windows читает русский: взято встроенное {calls}")
check(job.help is None and job.used == "", "русский распознан: подсказки нет")
log = log_text()
check("engine=tesseract" in log and "have=eng,osd" in log and "взято встроенное" in log, "журнал: языки Tesseract и выбор встроенного")

# 4. Tesseract без русского и в Windows русского нет: остаётся Tesseract, подсказка с кнопкой Windows
job, got = recognize("C:/Tesseract/tesseract.exe", ["eng"], "OCR_AVAIL=en-US\r\nOCR_WANT=ru OCR_LANG=en-US\r\n")
check(calls == ["powershell", "tesseract"], f"Windows русского не знает: затем Tesseract {calls}")
check(job.help is not None and "Tesseract" in job.used, f"подсказка и строка про Tesseract ({job.used!r})")

# 5. Tesseract с русским: встроенное не зовётся
job, got = recognize("C:/Tesseract/tesseract.exe", ["eng", "rus"], "")
check(calls == ["tesseract"] and job.help is None and job.used == "", f"Tesseract с rus: только он {calls}")

# 6. Окно: строка под текстом
d = ocr.TextResultDialog("PeKOMeHAOBaHO", "", None, None, "Распознано: Английский (Tesseract)")
check(d.used_label.isVisibleTo(d) and "Tesseract" in d.used_label.text(), "в окне строка «Распознано: …»")
d.set_used("")
check(not d.used_label.isVisibleTo(d), "set_used('') прячет строку")
d2 = ocr.TextResultDialog("Привет", "", None)
check(not d2.used_label.isVisibleTo(d2), "язык совпал: строки нет")

print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено {len(failures)}")
sys.exit(1 if failures else 0)
