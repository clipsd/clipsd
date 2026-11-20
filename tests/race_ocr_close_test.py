# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Г1 проверки гонок 1.32.2: распознавание текста заканчивается после закрытия редактора.

Кнопка «Текст» открывает редактор сразу в режиме текста, распознавание идёт 1,5-3 с. Человек закрывает редактор (Esc,
«Скопировать и закрыть») раньше. В 1.32.2 обработчик конца распознавания трогал кружок ожидания удалённого окна:
RuntimeError в обработчике сигнала, PyQt вызывает qFatal, вся программа падает (SIGABRT, код 134).

Момент конца распознавания задаёт тест: подменённое распознавание ждёт сигнала (threading.Event, предел 10 с).
Оба порядка: окно закрыто, потом распознавание кончилось (Esc и «Скопировать и закрыть»); распознавание кончилось,
потом окно закрыто (обычный путь: слова подсвечены). Каждый сценарий в своём процессе: падение не роняет сам тест.

Запуск: python3 tests/race_ocr_close_test.py
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def child(mode: str) -> int:
    import threading
    import time

    from PyQt6 import sip
    from PyQt6.QtCore import QEvent, QPoint
    from PyQt6.QtGui import QColor, QImage
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)   # как в ClipSD
    from clipshot import app as appmod, ocr
    from clipshot.editor import EditorWindow, OCR
    from clipshot.ocr import Word
    from PyQt6.QtCore import QRectF

    release = threading.Event()
    entered = threading.Event()

    def slow_words(image, langs, quality="accurate"):
        entered.set()
        release.wait(10)                    # конец распознавания задаёт тест
        return [Word("Hello", QRectF(10, 10, 60, 20), ("1", "1"))]

    ocr.recognize_words = slow_words
    ocr.missing_rus_help = lambda langs=None: None

    class Ctx:
        config = dict(appmod.DEFAULTS, auto_save=False)
        icon = appmod.make_icon()
        editors = []
        copied = []

        def copy_image(self, image):
            self.copied.append(image)

        def notify(self, text):
            pass

        def save_config(self):
            pass

    def wait_for(cond, limit=10.0):
        end = time.monotonic() + limit
        while not cond() and time.monotonic() < end:
            app.processEvents()
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
            time.sleep(0.01)
        return cond()

    img = QImage(600, 300, QImage.Format.Format_RGB32)
    img.fill(QColor("#ffffff"))
    ed = EditorWindow(img, Ctx(), QPoint(10, 10))
    ed.present()
    app.processEvents()
    ed.select_tool(OCR)                     # «Текст» под областью: редактор сразу в режиме текста
    job = ed._ocr_job
    print("job started:", job is not None, flush=True)
    if not wait_for(entered.is_set, 5):
        print("recognition did not start", flush=True)
        return 2
    if mode in ("esc", "copy_close"):
        ed.exported = True                  # снимок уже скопирован: закрытие без вопроса
        if mode == "esc":
            ed.close()
        else:
            ed.copy_and_close()
        if not wait_for(lambda: sip.isdeleted(ed), 5):
            print("editor was not deleted", flush=True)
            return 2
        print("editor deleted before the end of recognition", flush=True)
        release.set()
        wait_for(lambda: not ocr._jobs, 10)  # поток распознавания закончил, его сигнал done обработан
        wait_for(lambda: False, 0.5)
        print("ALIVE", flush=True)
        return 0
    # обратный порядок: распознавание кончилось при открытом окне, потом окно закрыто
    release.set()
    if not wait_for(lambda: ed._ocr_job is None and not ocr._jobs, 10):
        print("recognition result did not arrive", flush=True)
        return 2
    print("words:", ed.canvas.has_words(), flush=True)
    ed.exported = True
    ed.close()
    wait_for(lambda: sip.isdeleted(ed), 5)
    print("ALIVE", flush=True)
    return 0


def run(mode: str):
    env = dict(os.environ, QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", "offscreen"))
    res = subprocess.run([sys.executable, __file__, "child", mode], capture_output=True, text=True, timeout=120,
                         env=env, cwd=str(ROOT))
    return res.returncode, res.stdout + res.stderr


if __name__ == "__main__":
    if sys.argv[1:2] == ["child"]:
        from clipshot.exitutil import quick_exit
        quick_exit(child(sys.argv[2]))
    rc, out = run("esc")
    check(rc == 0 and "ALIVE" in out and "editor deleted before the end of recognition" in out,
          f"Esc до конца распознавания: программа жива (код {rc})" + ("" if rc == 0 else "\n" + out[-1500:]))
    rc, out = run("copy_close")
    check(rc == 0 and "ALIVE" in out,
          f"«Скопировать и закрыть» до конца распознавания: программа жива (код {rc})" + ("" if rc == 0 else "\n" + out[-1500:]))
    rc, out = run("done_first")
    check(rc == 0 and "words: True" in out and "ALIVE" in out,
          f"распознавание кончилось при открытом окне: слова подсвечены, закрытие без ошибок (код {rc})"
          + ("" if rc == 0 else "\n" + out[-1500:]))
    print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено {len(failures)}")
    sys.exit(1 if failures else 0)
