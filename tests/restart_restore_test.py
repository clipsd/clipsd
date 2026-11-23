# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""1.36.1, находки Б2, С3, С5 независимой проверки: снимки, спасённые перед перезапуском для обновления.

Б2: масштаб снимка (devicePixelRatio при экране 125-200 %) сохраняется: после перезапуска логический размер холста и
положение пометки те же, что до него (масштабы 1, 1.5, 2; запасной путь картинкой; масштаб только в самой PNG).
С5: два спасения в одну секунду дают разные файлы. С3: смена версии сорвалась после освобождения окон (deferred_lost):
записи этого запуска и их файлы убраны, редакторы снова несохранённые. Запись, которую не удалось прочитать, убирается
вместе с файлами.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/restart_restore_test.py
"""
import tmpclean  # noqa: F401
import json
import os
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
tmp = tempfile.mkdtemp(prefix="clipsd-rsrs-")
for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[name] = os.path.join(tmp, name)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.pop("CLIPSD_LANG", None)

from PyQt6.QtCore import QPoint, QPointF  # noqa: E402
from PyQt6.QtGui import QImage  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

qapp = QApplication(sys.argv)
qapp.setQuitOnLastWindowClosed(False)
from clipshot import app as appmod, i18n, shapes as shapes_mod, updater as up  # noqa: E402
from clipshot.shapes import RECT, Shape  # noqa: E402

failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


def settle(ms=80):
    for _ in range(4):
        qapp.processEvents()
        QTest.qWait(max(1, ms // 4))


i18n.set_language("ru")
a = appmod.Clipshot(qapp)
a.notify = lambda *_x: None
a.config.update(dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True))
a.save_config = lambda: None


def editor(dpr):
    img = QImage(int(600 * dpr / 2) * 2, int(400 * dpr / 2) * 2, QImage.Format.Format_RGB32)
    img.fill(0xFFFFFF)
    img.setDevicePixelRatio(dpr)
    ed = a.open_editor(img, QPoint(40, 40))
    settle(120)
    r = Shape(RECT, "#ff0000", 2, QPointF(150, 90))
    r.points = [QPointF(150, 90), QPointF(190, 130)]
    ed.canvas.shapes = [r]
    ed.canvas.modified = True
    ed.exported = False
    return ed


def drop_editors():
    for ed in list(a.editors):
        ed.canvas.modified = False
        ed.exported = True
        ed.close()
    settle(100)


def red_box(im):
    xs, ys = [], []
    for y in range(0, im.height(), 2):
        for x in range(0, im.width(), 2):
            c = im.pixelColor(x, y)
            if c.red() > 200 and c.green() < 80 and c.blue() < 80:
                xs.append(x)
                ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def recovery_files():
    folder = a.recovery_dir()
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


# --- Б2: масштабы 1, 1.5, 2 ---------------------------------------------------------------------------------
for dpr in (1.0, 1.5, 2.0):
    ed = editor(dpr)
    before = ed.render_image()
    logical = ed.canvas.base.deviceIndependentSize()
    box = red_box(before)
    a.restart_requested()
    a.release_for_restart()
    drop_editors()
    n = a.restore_after_restart()
    settle(150)
    e2 = a.editors[0] if a.editors else None
    after = e2.render_image() if e2 is not None else QImage()
    check(n == 1 and e2 is not None and abs(e2.canvas.base.devicePixelRatio() - dpr) < 1e-6,
          f"масштаб {dpr}: снимок открыт с тем же масштабом ({e2.canvas.base.devicePixelRatio() if e2 else None})")
    check(e2 is not None and e2.canvas.base.deviceIndependentSize() == logical,
          f"масштаб {dpr}: логический размер холста тот же ({logical} -> {e2.canvas.base.deviceIndependentSize() if e2 else None})")
    check(box is not None and red_box(after) == box, f"масштаб {dpr}: пометка на том же месте ({box} -> {red_box(after)})")
    check(recovery_files() == [], f"масштаб {dpr}: файлы восстановления убраны после открытия")
    drop_editors()

# --- Б2: запасной путь картинкой (пометки не записались) ------------------------------------------------------
real_to_dict = shapes_mod.shape_to_dict


def broken(_s):
    raise ValueError("проба: пометки не записываются")


ed = editor(2.0)
flat = ed.render_image()
shapes_mod.shape_to_dict = broken
a.restart_requested()
a.release_for_restart()
shapes_mod.shape_to_dict = real_to_dict
drop_editors()
n = a.restore_after_restart()
settle(150)
e2 = a.editors[0] if a.editors else None
check(n == 1 and e2 is not None and e2.canvas.base.devicePixelRatio() == 2.0
      and e2.canvas.base.deviceIndependentSize() == flat.deviceIndependentSize(),
      "запасной путь картинкой: масштаб 2 сохранён, логический размер тот же")
drop_editors()

# --- Б2: JSON потерян, масштаб берётся из самой PNG ----------------------------------------------------------
ed = editor(1.5)
logical = ed.canvas.base.deviceIndependentSize()
a.restart_requested()
a.release_for_restart()
for p in a.recovery_dir().glob("*.json"):
    p.unlink()
drop_editors()
a.restore_after_restart()
settle(150)
e2 = a.editors[0] if a.editors else None
check(e2 is not None and e2.canvas.base.devicePixelRatio() == 1.5 and e2.canvas.base.deviceIndependentSize() == logical,
      "без JSON масштаб 1.5 берётся из текста PNG")
drop_editors()

# --- С5: два спасения в одну секунду --------------------------------------------------------------------------
real_time = appmod.time.time
appmod.time.time = lambda: 1700000000.0
try:
    editor(1.0)
    a.restart_requested()
    a.release_for_restart()
    editor(1.0)
    a.release_for_restart()
finally:
    appmod.time.time = real_time
listed = list(a.config.get(a.RECOVERY_KEY) or [])
pngs = [p for p in recovery_files() if p.endswith(".png")]
check(len(listed) == 2 and len(set(listed)) == 2 and len(pngs) == 2, f"два спасения в одну секунду: два разных файла ({pngs})")

# --- С3: смена версии сорвалась (deferred_lost): записи этого запуска убраны ---------------------------------
a.config[a.RECOVERY_KEY] = listed + [os.path.join(tmp, "earlier-run.png")]   # запись прошлого запуска не трогается


class UI:
    def __getattr__(self, name):
        return lambda *x, **k: None


u = up.Updater(a, kind="linux", installed="1.36.0", ui=UI())
rec = up.write_attempt(up.attempt_path(), "1.36.0", "1.36.1", up.utcnow())
rec["deferred"] = True
check(u.retry_switch(rec) is False, "помощника смены версии нет: попытка сорвалась (deferred_lost)")
check(a.config.get(a.RECOVERY_KEY) == [os.path.join(tmp, "earlier-run.png")],
      f"записи восстановления этого запуска убраны, прошлого остались ({a.config.get(a.RECOVERY_KEY)})")
check(recovery_files() == [], f"файлы восстановления этого запуска убраны ({recovery_files()})")
check(len(a.editors) == 2 and all(not e.exported for e in a.editors) and a.quit_blocker() == "unsaved",
      "редакторы снова несохранённые: закрытие спросит, выход держат")
check(a.drop_restart_restore() == 0, "повторный вызов ничего не трогает")
a.config.pop(a.RECOVERY_KEY, None)
drop_editors()

# --- запись, которую не удалось прочитать, убирается вместе с файлами ----------------------------------------
folder = a.recovery_dir()
folder.mkdir(parents=True, exist_ok=True)
bad = folder / "1700000000-broken.png"
bad.write_bytes(b"not a png")
(folder / "1700000000-broken.json").write_text(json.dumps({"dpr": 2.0, "shapes": []}), encoding="utf-8")
a.config[a.RECOVERY_KEY] = [str(bad)]
check(a.restore_after_restart() == 0 and recovery_files() == [] and not a.config.get(a.RECOVERY_KEY),
      "испорченная запись восстановления: файлы и запись убраны")

print("\nИТОГ:", "провалено %d" % len(failures) if failures else "всё хорошо")
sys.exit(1 if failures else 0)
