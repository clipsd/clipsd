# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""1.34.1 (Б1 проверки 1.34.0): окно «Новое в версии» и окно выделения.

Окно новинок приходит по таймеру (0,7 с после первого редактора после обновления) и модальное для всей программы.
В 1.34.0 оно открывалось и тогда, когда человек уже нажал Alt+W: окно выделения получало WindowBlocked, мышь и
клавиши в нём не работали, на X11 экран застывал. Теперь окно ждёт спокойного момента у того же редактора.

Порядок A→B: редактор открыт, через 0,2 с Alt+W, таймер новинок срабатывает при открытом выделении: окна новинок нет,
выделение не заблокировано; после закрытия выделения окно приходит над редактором. Порядок B→A: окно новинок уже
открыто, потом Alt+W: окно новинок закрывается (clipsd_closable), выделение работает. То же для выбора оформления
при первом запуске и вопроса про обзор после короткого курса.

Запуск: python3 tests/novoe_gonka_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import json
import os
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(here)
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp(prefix="clipsd-novoe-gonka-")
for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[name] = os.path.join(tmp, name)
_screen = os.path.join(tmp, "screen.json")
with open(_screen, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1600, "height": 1000,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _screen
os.environ.pop("CLIPSD_LANG", None)

from PyQt6.QtCore import QEvent, QObject, QTimer  # noqa: E402
from PyQt6.QtGui import QColor, QImage  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

qapp = QApplication(sys.argv)
qapp.setQuitOnLastWindowClosed(False)

import clipshot  # noqa: E402
from clipshot import app as appmod, i18n, novoe  # noqa: E402

V = "1.34.0"
clipshot.__version__ = V
novoe.__version__ = V
i18n.set_language("ru")
failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


def modal_name():
    m = QApplication.activeModalWidget()
    return type(m).__name__ if m is not None and m.isVisible() else None


def image():
    img = QImage(900, 500, QImage.Format.Format_RGB32)
    img.fill(QColor("#ffffff"))
    return img


class Blocked(QObject):
    def __init__(self):
        super().__init__()
        self.events = []

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.WindowBlocked:
            self.events.append("WindowBlocked")
        return False


stuck = []   # модальные окна, которые никто не закрыл: на старом коде окно новинок над выделением


def unstick(state={"w": None, "n": 0}):
    """Окно, открытое дольше 3 с, закрывается и записывается: тест падает, а не висит во вложенном цикле."""
    m = QApplication.activeModalWidget()
    if m is not None and m is state["w"]:
        state["n"] += 1
        if state["n"] >= 6:
            stuck.append(type(m).__name__)
            m.reject()
            state["w"], state["n"] = None, 0
    else:
        state["w"], state["n"] = m, 0


_unstick = QTimer()
_unstick.timeout.connect(unstick)
_unstick.start(500)

appmod.is_wayland = lambda: False   # окно выделения сразу со снимком экрана (X11), без портала сеанса
a = appmod.Clipshot(qapp)
a.save_config = lambda: None
a.notify = lambda *_x: None


def updated_config(**kw):
    a.config.clear()
    a.config.update(dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True, tour_selector_done=True))
    novoe.on_start(a.config)
    a.config.update(kw)


def close_everything():
    for w in QApplication.topLevelWidgets():
        if w.isVisible() and w.isModal():
            w.reject()
    QTest.qWait(50)
    if a.selector is not None:
        a.selector._finish(None)
        QTest.qWait(50)
    for ed in list(a.editors):
        ed.canvas.modified = False
        ed.close()
    QTest.qWait(100)


def watch_selector(blocked):
    """Поставить фильтр на окно выделения, как только оно откроется."""
    def hook():
        if a.selector is not None and not getattr(a.selector, "_gonka_hooked", False):
            a.selector._gonka_hooked = True
            a.selector.installEventFilter(blocked)
        if not getattr(qapp, "_gonka_stop", False):
            QTimer.singleShot(20, hook)
    qapp._gonka_stop = False
    hook()


# --- A→B: редактор, через 0,2 с Alt+W, таймер новинок при открытом выделении ---------------------------------------
updated_config()
check(novoe.window_pending(a.config), "обновление: окно новинок ждёт первого редактора")
blocked = Blocked()
watch_selector(blocked)
ed = a.open_editor(image(), None)
a.last_trigger = 0
QTimer.singleShot(200, a.capture_region)
QTest.qWait(1200)   # таймер новинок (700 мс) уже сработал
check(a.selector is not None and a.selector.isVisible(), "A→B: окно выделения открыто")
check(modal_name() is None, f"A→B: окна новинок поверх выделения нет (модальное: {modal_name()})")
check(blocked.events == [], f"A→B: выделение не заблокировано ({blocked.events})")
QTest.qWait(1500)   # пока выделение открыто, окно так и не приходит
check(modal_name() is None and novoe.window_pending(a.config), "A→B: пока выделение открыто, окно ждёт")
qapp._gonka_stop = True
seen = {}


def catch():
    m = QApplication.activeModalWidget()
    if m is not None and m.isVisible():
        seen["name"] = type(m).__name__
        seen["parent"] = m.parentWidget()
        m.reject()
        return
    QTimer.singleShot(30, catch)


a.selector._finish(None)   # человек нажал Esc в окне выделения
catch()
QTest.qWait(2500)
check(seen.get("name") == "NovoeDialog" and seen.get("parent") is ed,
      f"A→B: после выделения окно новинок пришло над тем же редактором ({seen.get('name')})")
close_everything()

# --- B→A: окно новинок открыто, потом Alt+W ------------------------------------------------------------------------
updated_config()
blocked = Blocked()
watch_selector(blocked)
ed = a.open_editor(image(), None)
before = {}


def alt_w():
    """Alt+W, пока открыто окно новинок (вызывается из его вложенного цикла: окно модальное)."""
    before["modal"] = modal_name()
    a.last_trigger = 0
    a.capture_region()


QTimer.singleShot(1000, alt_w)
QTest.qWait(1800)
check(before.get("modal") == "NovoeDialog", f"B→A: окно новинок было открыто над редактором ({before.get('modal')})")
check(a.selector is not None and a.selector.isVisible() and modal_name() is None,
      f"B→A: Alt+W закрыл окно новинок, выделение открыто (модальное: {modal_name()})")
check(blocked.events == [], f"B→A: выделение не заблокировано ({blocked.events})")
qapp._gonka_stop = True
close_everything()

# --- новый редактор из выделения: окно над ним, а не над старым ------------------------------------------------------
updated_config()
ed1 = a.open_editor(image(), None)
a.last_trigger = 0
QTimer.singleShot(200, a.capture_region)
QTest.qWait(1100)
check(a.selector is not None and modal_name() is None, "второй редактор: при выделении окна нет")
a.selector._finish(None)
seen.clear()
ed2 = a.open_editor(image(), None)   # снимок из выделения открылся новым редактором
catch()
QTest.qWait(2500)
check(seen.get("name") == "NovoeDialog" and seen.get("parent") is ed2,
      f"окно новинок над новым редактором, а не над прежним ({seen.get('name')}, "
      f"{'новый' if seen.get('parent') is ed2 else 'прежний' if seen.get('parent') is ed1 else None})")
close_everything()

# --- выбор оформления при первом запуске: тоже не поверх выделения -------------------------------------------------
a.config.clear()
a.config.update(dict(appmod.DEFAULTS))
novoe.on_start(a.config)
a.config.update(theme_chosen=False, tour_done=False)
blocked = Blocked()
watch_selector(blocked)
ed = a.open_editor(image(), None)
a.last_trigger = 0
QTimer.singleShot(100, a.capture_region)
QTest.qWait(900)   # таймер выбора оформления (400 мс) сработал
check(a.selector is not None and modal_name() is None and blocked.events == [],
      f"первый запуск: выбор оформления не поверх выделения (модальное: {modal_name()}, {blocked.events})")
qapp._gonka_stop = True
seen.clear()
a.selector._finish(None)
catch()
QTest.qWait(2500)
check(seen.get("name") == "ThemeChooser", f"первый запуск: выбор оформления после выделения ({seen.get('name')})")
for ed in list(a.editors):
    if getattr(ed, "tour", None) is not None:
        ed.tour.finish()
close_everything()

# --- вопрос про обзор: не поверх выделения ------------------------------------------------------------------------
updated_config()
ed = a.open_editor(image(), None)
novoe.window_done(a.config)   # окно новинок уже было, курс прошёл, сейчас придёт вопрос
check(novoe.ask_pending(a.config), "вопрос про обзор ждёт")
blocked = Blocked()
watch_selector(blocked)
a.last_trigger = 0
a.capture_region()
QTest.qWait(400)
a._ask_overview(ed)
QTest.qWait(300)
check(a.selector is not None and modal_name() is None and blocked.events == [] and novoe.ask_pending(a.config),
      f"вопрос про обзор не поверх выделения (модальное: {modal_name()})")
qapp._gonka_stop = True
seen.clear()
a.selector._finish(None)
catch()
QTest.qWait(2500)
check(seen.get("name") is not None and not novoe.ask_pending(a.config),
      f"вопрос про обзор пришёл после выделения ({seen.get('name')})")
close_everything()

check(not stuck, f"ни одно окно не осталось висеть без ответа ({stuck})")
print("ИТОГ:", "все проверки пройдены" if not failures else f"{len(failures)} не пройдено")
sys.exit(1 if failures else 0)
