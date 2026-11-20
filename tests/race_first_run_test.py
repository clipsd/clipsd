# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Г7 проверки гонок 1.32.2: самый первый снимок, редактор закрыт раньше 0,4 с.

При первом запуске open_editor через 400 мс открывает выбор оформления над редактором. В 1.32.2 таймер не был
привязан к окну: если человек сразу нажал Esc, выбор оформления строился с удалённым родителем, RuntimeError в
обработчике таймера, программа падала в первую минуту знакомства (SIGABRT).

Оба порядка: редактор закрыт до срабатывания таймера (программа жива, выбор оформления предложит следующий снимок);
редактор открыт дольше (выбор оформления открывается над ним, как раньше). Момент закрытия задаёт тест: окно
закрывается сразу после открытия, до первого прохода цикла событий с таймером. Каждый порядок в своём процессе.

Запуск: python3 tests/race_first_run_test.py
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
    import time

    from PyQt6 import sip
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QColor, QImage
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    from clipshot import app as appmod

    def wait_for(cond, limit=5.0):
        end = time.monotonic() + limit
        while not cond() and time.monotonic() < end:
            app.processEvents()
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
            time.sleep(0.01)
        return cond()

    ctx = appmod.Clipshot(app)
    ctx.config.update(theme_chosen=False, tour_done=False, auto_save=False)   # самый первый снимок после установки
    img = QImage(300, 200, QImage.Format.Format_RGB32)
    img.fill(QColor("white"))
    ed = ctx.open_editor(img, None)
    if mode == "close_first":
        ed.close()                                     # Esc сразу, до 400 мс
        wait_for(lambda: sip.isdeleted(ed), 5)
        print("editor deleted:", sip.isdeleted(ed), flush=True)
        wait_for(lambda: False, 1.0)                   # таймер выбора оформления успел бы сработать
        print("theme_chosen:", ctx.config.get("theme_chosen"), flush=True)
        print("ALIVE", flush=True)
        return 0
    seen = {}

    def chooser_open():
        modal = QApplication.activeModalWidget()
        if modal is not None:
            seen["modal"] = type(modal).__name__
            modal.close()                              # человек выбрал оформление и закрыл окно
            return True
        return False

    from PyQt6.QtCore import QTimer
    timer = QTimer()
    timer.timeout.connect(chooser_open)
    timer.start(50)
    wait_for(lambda: "modal" in seen, 5)
    timer.stop()
    wait_for(lambda: False, 0.3)
    print("chooser:", seen.get("modal"), "| theme_chosen:", ctx.config.get("theme_chosen"), flush=True)
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
    rc, out = run("close_first")
    check(rc == 0 and "ALIVE" in out and "editor deleted: True" in out,
          f"первый редактор закрыт раньше 0,4 с: программа жива (код {rc})" + ("" if rc == 0 else "\n" + out[-1500:]))
    check("theme_chosen: False" in out, "оформление не выбрано: окно выбора предложит следующий снимок")
    rc, out = run("keep_open")
    check(rc == 0 and "chooser: ThemeChooser | theme_chosen: True" in out and "ALIVE" in out,
          f"редактор открыт: выбор оформления над ним, как раньше (код {rc})" + ("" if rc == 0 else "\n" + out[-1500:]))
    print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено {len(failures)}")
    sys.exit(1 if failures else 0)
