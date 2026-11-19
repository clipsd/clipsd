# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
"""Потоки заданий (проверка почты MyMemory, «Копировать текст»): 30 запусков подряд, поток удаляется только после выхода
из run(); при ошибке процесс падал бы с «QThread: Destroyed while thread is still running» (код 134).
Сеть подменена. Запуск: QT_QPA_PLATFORM=offscreen python3 tests/threads_test.py"""
import os
import sys
import time

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
from clipshot import ocr, translate
failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def wait(cond, seconds=300):
    end = time.time() + seconds
    while not cond() and time.time() < end:
        app.processEvents()
        QTest.qWait(10)
    return cond()


translate._http = lambda *a, **k: {"responseStatus": 200, "responseData": {"translatedText": "ok"}}
img = QImage(300, 80, QImage.Format.Format_RGB32)
img.fill(QColor("#ffffff"))
p = QPainter(img)
f = p.font()
f.setPixelSize(20)
p.setFont(f)
p.drawText(10, 40, "Hello world")
p.end()
mails, texts = [], []
held = []   # the job is still held in _jobs when its answer arrives: it is dropped only on QThread.finished
for _ in range(30):
    translate.check_mymemory_email("name@gmail.com", lambda e: (mails.append(e), held.append(bool(translate._jobs))))
check(wait(lambda: len(mails) == 30 and not translate._jobs), f"проверка почты: 30 ответов из 30 ({len(mails)})")
check(all(held), "задание держится в _jobs до сигнала finished (не по ответу из run())")
for _ in range(30):
    ocr.start(img.copy(), lambda t, e, h=None: texts.append(e))
check(wait(lambda: len(texts) == 30 and not ocr._jobs), f"«Копировать текст»: 30 ответов из 30 ({len(texts)})")
for _ in range(40):
    app.processEvents()
    QTest.qWait(10)
check(not translate._jobs and not ocr._jobs, "все потоки завершены, процесс жив")
print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено: {len(failures)}")
from clipshot.exitutil import quick_exit
quick_exit(1 if failures else 0)
