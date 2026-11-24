# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""1.36.1: обновление по решению человека не требует закрывать окна вручную (слова владельца 23.11.2026).

Проверяется: (1) без решения человека обновление по-прежнему осторожное: редактор с пометками, текст, окно настроек
отвечают «busy»; (2) после restart_requested (нажато «Обновить» или «Перезапустить сейчас») ответ «ok»: вводимый
текст зафиксирован, несохранённый редактор записан в recovery и после перезапуска открывается заново, настройки
применены и окно закрыто, «О программе» закрыто, окно выделения отменено; (3) окно, которое закрыть не удалось, остаётся
причиной и называется (blocker_widget); (4) спасённый снимок не остаётся в папке после открытия.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/update_restart_test.py
"""
import tmpclean  # noqa: F401
import os
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
tmp = tempfile.mkdtemp(prefix="clipsd-updrs-")
for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[name] = os.path.join(tmp, name)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.pop("CLIPSD_LANG", None)

from PyQt6.QtCore import QPoint, QTimer  # noqa: E402
from PyQt6.QtGui import QImage  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

qapp = QApplication(sys.argv)
from clipshot import app as appmod, i18n  # noqa: E402

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
saves = []
a.save_config = lambda: saves.append(1)


def editor(modified=True):
    img = QImage(300, 200, QImage.Format.Format_RGB32)
    img.fill(0xFFFFFF)
    ed = a.open_editor(img, QPoint(40, 40))
    settle(120)
    ed.canvas.modified = modified
    ed.exported = False
    return ed


def drop_editors():
    for ed in list(a.editors):
        ed.canvas.modified = False
        ed.exported = True
        ed.close()
    settle(100)


# 1. без решения человека: осторожно
ed = editor()
check(a.quit_blocker() == "unsaved" and a.answer_quit_for_update().startswith("busy"), "без решения человека: несохранённый редактор держит обновление")
check(not a.explicit_restart(), "решения человека нет")

# 2. несохранённый редактор и вводимый текст при решении человека
from clipshot.shapes import RECT, TEXT, Shape  # noqa: E402
from PyQt6.QtCore import QPointF  # noqa: E402
sh = Shape(TEXT, "#d92d20", 3, QPointF(20, 30))
sh.text = "метка"
rc = Shape(RECT, "#1e78ff", 2, QPointF(60, 60))
rc.points = [QPointF(60, 60), QPointF(160, 120)]
ed.canvas.shapes = [sh, rc]
marked_shapes = list(ed.canvas.shapes)
base_size = ed.canvas.base.size()
a.restart_requested()
check(a.explicit_restart(), "«Обновить»/«Перезапустить сейчас» запомнено")
ed.select_tool("text")
steps = a.release_for_restart()
check(a.quit_blocker() == "", f"после освобождения ничто не держит выход: {steps}")
files = list(a.recovery_dir().glob("*.png")) if a.recovery_dir().exists() else []
check(len(files) == 1 and a.config.get(a.RECOVERY_KEY) == [str(files[0])], "несохранённый снимок записан в recovery и перечислен в настройках")
check(a.answer_quit_for_update() == "ok", "ответ помощнику смены версии: ok")
drop_editors()
n = a.restore_after_restart()
settle(120)
check(n == 1 and len(a.editors) == 1 and a.editors[0].canvas.modified, "после перезапуска снимок открыт заново и считается несохранённым")
check(len(a.editors[0].canvas.shapes) == len(marked_shapes) and [s.kind for s in a.editors[0].canvas.shapes] == [s.kind for s in marked_shapes]
      and a.editors[0].canvas.shapes[0].text == "метка", "пометки вернулись правимыми объектами, а не картинкой")
check(a.editors[0].canvas.base.size() == base_size, "исходная картинка без пометок вплавленных")
check(not list(a.recovery_dir().glob("*.png")) and not a.config.get(a.RECOVERY_KEY), "спасённый файл и запись о нём убраны после открытия")
drop_editors()

# 3. окно настроек: изменения применены, окно закрыто
from clipshot.settings import SettingsDialog  # noqa: E402
info = {}


def inside_settings():
    """Выполняется, пока окно настроек открыто (exec внутри таймера держит цикл): проверки и решение человека."""
    dlg = getattr(a, "_settings", None)
    info["open"] = dlg is not None and dlg.isVisible()
    info["blocker"] = a.quit_blocker()
    dlg.save_dir.setText(os.path.join(tmp, "snimki"))
    a.restart_requested()
    info["steps"] = a.release_for_restart()
    info["visible_after"] = dlg.isVisible()
    info["blocker_after"] = a.quit_blocker()


QTimer.singleShot(50, lambda: a.open_settings(None))
QTimer.singleShot(500, inside_settings)
settle(1500)
check(info.get("open") and info.get("blocker") == "dialog", "открытые настройки держат обновление (автоматический путь)")
check(not info.get("visible_after") and info.get("blocker_after") == "", f"настройки закрыты сами, выход свободен: {info.get('steps')}")
check(a.config.get("save_dir") == os.path.join(tmp, "snimki"), "изменения настроек применены, а не потеряны")

# 4. «О программе» и окно выделения
a.show_about()
settle(150)
check(a.quit_blocker() == "dialog", "«О программе» держит выход в автоматическом пути")
a.release_for_restart()
settle(150)
check(a.quit_blocker() == "", "«О программе» закрыто само")


class FakeSelector:
    cancelled = False

    def _finish(self, sel):
        FakeSelector.cancelled = True
        a.selector = None


a.selector = FakeSelector()
check(a.quit_blocker() == "selector", "окно выделения держит выход")
a.release_for_restart()
check(FakeSelector.cancelled and a.quit_blocker() == "", "окно выделения отменено при решении человека")

# 5. то, что закрыть нельзя, называется
check(a.blocker_widget("selector") is None and a.blocker_widget("unsaved") is None, "нет окон: назвать нечего")
ed = editor()
check(a.blocker_widget("unsaved") is ed, "несохранённый редактор называется причиной")
drop_editors()

print("\nИТОГ:", "провалено %d" % len(failures) if failures else "всё хорошо")
sys.exit(1 if failures else 0)
