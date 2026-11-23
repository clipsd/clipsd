# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""В5 проверки 1.35.0: окно «Ознакомление» с системным заголовком (Windows) целиком в доступной области экрана.
В offscreen рамки нет, поэтому заголовок 30 точек подставляется через frameGeometry.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/ozn_ramka_test.py"""
import tmpclean  # noqa: F401
import json
import os
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
tmp = tempfile.mkdtemp(prefix="clipsd-oznr-")
for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[name] = os.path.join(tmp, name)
_screen = os.path.join(tmp, "screen.json")
with open(_screen, "w", encoding="utf-8") as _f:   # 1366x768, панель задач 40 точек снизу не моделируется: берём 1366x728
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1366, "height": 728,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _screen
os.environ.pop("CLIPSD_LANG", None)

from PyQt6.QtCore import QRect  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

qapp = QApplication(sys.argv)
from clipshot import app as appmod, i18n, oznakomlenie  # noqa: E402

failures = []


def check(ok, what):
    print(("OK   " if ok else "FAIL ") + what)
    if not ok:
        failures.append(what)


TITLE = 30
cls = next(c for c in vars(oznakomlenie).values()
           if isinstance(c, type) and hasattr(c, "_keep_frame_on_screen"))
base_frame = cls.frameGeometry
cls.frameGeometry = lambda self: QRect(self.x(), self.y(), self.width(), self.height() + TITLE)

i18n.set_language("ru")
a = appmod.Clipshot(qapp)
a.save_config = lambda: None
a.notify = lambda *_x: None
win = oznakomlenie.open_window(a)
for _ in range(10):
    qapp.processEvents()
    QTest.qWait(10)
area = win.screen().availableGeometry()
fr = win.frameGeometry()
check(area.contains(fr), f"окно с заголовком {TITLE} точек целиком на экране: рамка {fr.getRect()}, область {area.getRect()}")
check(fr.bottom() <= area.bottom(), f"низ окна с «Готово» не под панелью задач ({fr.bottom()} <= {area.bottom()})")
cls.frameGeometry = base_frame
win.close()
print(f"\n{'ВСЁ ХОРОШО' if not failures else 'ОШИБКИ: ' + str(len(failures))}")
sys.exit(1 if failures else 0)
