# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Г13 проверки гонок 1.32.2: смена языка интерфейса ровно в конце перевода.

Поток перевода клал в итог готовую фразу на языке момента («Текст в выделенной области не найден», «Отменено»),
а окно сравнивало её с фразой на текущем языке (error == translate.NO_TEXT, translate.CANCELLED). Если язык сменили
глобусом редактора между концом потока и показом итога, «Текст не найден» показывался карточкой ошибки на старом
языке, а «Отмена» ошибкой вместо того, чтобы убрать кусок.

Теперь поток передаёт код сообщения, текст на языке интерфейса берётся в главном потоке при показе. Момент задаёт
тест: главный поток ждёт конца потока перевода (QThread.wait), итог уже в очереди, язык меняется, и только потом
очередь обрабатывается. Обратный порядок: язык сменён до конца перевода.

Запуск: python3 tests/race_lang_switch_test.py
"""
import os
import sys
import threading
import time
from pathlib import Path

os.environ.pop("CLIPSD_LANG", None)            # язык меняет сам тест (CLIPSD_LANG в окружении важнее настроек)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PyQt6.QtGui import QColor, QImage  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)
from clipshot import i18n, ocr, translate  # noqa: E402

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def wait_for(cond, limit=10.0):
    end = time.monotonic() + limit
    while not cond() and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)
    return cond()


release = threading.Event()


def no_text(image, langs, quality="accurate"):
    release.wait(10)
    return []                                   # текста нет


ocr.recognize_words = no_text
img = QImage(200, 100, QImage.Format.Format_RGB32)
img.fill(QColor("white"))


def run(switch_before_end: bool, cancel: bool = False):
    i18n.set_language("ru")
    out = {}

    def done(results, error, help):
        out["error"] = error
        out["no_text"] = error == translate.NO_TEXT          # так сравнивают окна (translate_ui)
        out["cancelled"] = error == translate.CANCELLED

    job = translate.start(img, {"translate_engine": "mymemory"}, done, full=True)
    if cancel:
        job.cancel()                                          # Esc: перевод отменён
    if switch_before_end:
        i18n.set_language("en")
        release.set()
        wait_for(lambda: "error" in out)
    else:
        release.set()
        job.wait(10_000)                                      # поток закончил, итог лежит в очереди главного потока
        i18n.set_language("en")                               # человек сменил язык глобусом редактора
        wait_for(lambda: "error" in out)
    release.clear()
    wait_for(lambda: not translate._jobs, 5)
    return out


out = run(switch_before_end=False)
check(out.get("no_text") is True,
      f"язык сменён между концом перевода и показом: «Текст не найден» узнан ({out.get('error')!r})")
check(out.get("error") == i18n.tr("translate.no_text") and i18n.current() == "en",
      f"сообщение на новом языке ({i18n.current()})")
out = run(switch_before_end=False, cancel=True)
check(out.get("cancelled") is True, f"то же для «Отмены»: кусок убирается, а не показывается ошибкой ({out.get('error')!r})")
out = run(switch_before_end=True)
check(out.get("no_text") is True, "обратный порядок: язык сменён до конца перевода, «Текст не найден» узнан")
i18n.set_language("ru")

print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено {len(failures)}")
from clipshot.exitutil import quick_exit  # noqa: E402
quick_exit(1 if failures else 0)
