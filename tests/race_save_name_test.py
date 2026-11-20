# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Г9 проверки гонок 1.32.2: два сохранения в одну секунду.

Сохранение без вопроса («Спрашивать, куда сохранить» выключено) брало имя Screenshot_ГГГГ-ММ-ДД_ЧЧ-ММ-СС.png по
секунде и писало поверх: два редактора, Ctrl+S подряд, первый снимок молча терялся, «Сохранено» показано оба раза.
Автосохранение проверяло имя, но проверка и запись были разнесены: две копии программы в одну секунду получали одно
имя. Теперь имя занимается сразу (пустой файл, O_CREAT | O_EXCL), следующее сохранение получает _2.

Секунда задаётся тестом (часы подменены), оба порядка: имя и запись подряд; два имени, потом две записи.

Запуск: python3 tests/race_save_name_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import datetime as real_datetime
import os
import shutil
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PyQt6.QtGui import QColor, QImage  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
from clipshot import app as appmod, editor as editormod, hidpi  # noqa: E402

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


class FixedNow(real_datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 11, 20, 12, 0, 0)


fixed = types.SimpleNamespace(datetime=FixedNow)
editormod.datetime = fixed                     # ask_save_path: одна и та же секунда


def shot(color):
    img = QImage(40, 40, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    return img


def color_of(path):
    return QImage(path).pixelColor(1, 1).name()


tmp = Path(tempfile.mkdtemp(prefix="clipsd-race-save-"))
try:
    # --- 1. сохранение без вопроса: имя и запись подряд, дважды в одну секунду ----------------------------
    folder = tmp / "a"
    folder.mkdir()
    cfg = dict(appmod.DEFAULTS, save_ask=False, save_dir=str(folder), auto_save_dir=str(folder))
    p1 = editormod.ask_save_path(None, cfg)
    hidpi.save_image(shot("red"), p1, cfg)
    p2 = editormod.ask_save_path(None, cfg)
    hidpi.save_image(shot("blue"), p2, cfg)
    files = sorted(f.name for f in folder.iterdir())
    check(p1 != p2 and len(files) == 2, f"Ctrl+S в двух редакторах в одну секунду: два файла {files}")
    check(os.path.isfile(p1) and color_of(p1) == "#ff0000" and color_of(p2) == "#0000ff",
          "первый снимок не затёрт вторым")
    check(os.path.basename(p2) == "Screenshot_2026-11-20_12-00-00_2.png", f"второе имя с _2: {os.path.basename(p2)}")

    # --- 2. обратный порядок: два имени, потом две записи (две копии программы) ---------------------------
    folder = tmp / "b"
    folder.mkdir()
    cfg = dict(cfg, save_dir=str(folder), auto_save_dir=str(folder))
    q1 = editormod.ask_save_path(None, cfg)
    q2 = editormod.ask_save_path(None, cfg)
    hidpi.save_image(shot("red"), q1, cfg)
    hidpi.save_image(shot("blue"), q2, cfg)
    check(q1 != q2 and color_of(q1) == "#ff0000" and color_of(q2) == "#0000ff",
          "два имени до записи: два разных файла, оба снимка целы")

    # --- 3. автосохранение двух копий программы в одну секунду ---------------------------------------------
    folder = tmp / "c"
    folder.mkdir()
    ctx = types.SimpleNamespace(config=dict(cfg, auto_save_dir=str(folder)))
    saved_mod = sys.modules["datetime"]
    sys.modules["datetime"] = fixed            # snapshot_path импортирует datetime внутри себя
    try:
        a = appmod.Clipshot.snapshot_path(ctx)
        b = appmod.Clipshot.snapshot_path(ctx)   # вторая копия, первая ещё не записала файл
    finally:
        sys.modules["datetime"] = saved_mod
    check(a != b, f"автосохранение двух копий в одну секунду: разные имена ({os.path.basename(a)}, {os.path.basename(b)})")

    # --- 4. запись не удалась: занятое пустое имя не остаётся ---------------------------------------------------
    folder = tmp / "d"
    folder.mkdir()
    ctx = types.SimpleNamespace(config=dict(cfg, auto_save_dir=str(folder), auto_save=True))
    ctx.snapshot_path = lambda: appmod.Clipshot.snapshot_path(ctx)
    real_png = hidpi.png_bytes
    hidpi.png_bytes = lambda *a, **k: b""
    try:
        res = appmod.Clipshot.autosave(ctx, shot("red"))
    finally:
        hidpi.png_bytes = real_png
    check(res is None and not list(folder.iterdir()), f"автосохранение не удалось: пустого файла нет {list(folder.iterdir())}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено {len(failures)}")
sys.exit(1 if failures else 0)
