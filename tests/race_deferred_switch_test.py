# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Г4 проверки гонок 1.32.2: ждущее обновление и «Скопировать и закрыть».

Обновление скачано и ждёт, потому что открыты редакторы с пометками. Человек жмёт «Скопировать и закрыть» в двух
редакторах подряд, чтобы вставить снимки в чат. В 1.32.2 каждое закрытие ставило свой таймер на 1 с: два помощника
смены версии на одну попытку (каждый съедает попытку из пяти), и через 1 с программа уходила на обновление, унося с
собой снимок из буфера обмена (Windows, X11 без менеджера буфера).

Теперь: один общий таймер на закрытия редакторов; второй помощник на ту же попытку не запускается, пока первый не
ответил (замок update.lock или 30 с с запуска); пока программа держит только что скопированное (буфер её, меньше
2 минут), отложенное обновление ждёт. Запуск помощника подменён записью, моменты закрытий задаёт тест. Буфер «наш»
подменой _owns_clipboard (у Qt offscreen своего буфера нет), как на Windows и X11.

Запуск: python3 tests/race_deferred_switch_test.py
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QTimer  # noqa: E402
from PyQt6.QtGui import QColor, QImage  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)
from clipshot import app as appmod, updater as up  # noqa: E402

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def wait(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


launches = []


def fake_launch(version_dir, from_version, to_version, attempt_id, **kw):
    launches.append((time.monotonic(), attempt_id))
    return "systemd-run"


up.launch_linux_switch = fake_launch


class UI:
    def __getattr__(self, name):
        return lambda *a, **k: None


owns = [True]
ctx = appmod.Clipshot(app)
ctx._owns_clipboard = lambda: owns[0]   # буфер остаётся за программой, как на Windows и X11 без менеджера буфера
ctx.config.update(theme_chosen=True, tour_done=True, auto_save=False)
u = up.Updater(ctx, kind="linux", installed="1.32.2", ui=UI())
ctx._updater = u
folder = up.versions_dir() / "1.32.3"
folder.mkdir(parents=True, exist_ok=True)
(folder / "clipsd-switch").write_text("#!/bin/bash\n")


def clipboard_busy():
    return bool(getattr(ctx, "clipboard_busy", lambda: False)())


def tries():
    return int((up.read_attempt(up.attempt_path()) or {}).get("tries", 0) or 0)


def setup(n_editors=2):
    up.write_attempt(up.attempt_path(), "1.32.2", "1.32.3", up.utcnow())
    img = QImage(300, 200, QImage.Format.Format_RGB32)
    img.fill(QColor("white"))
    eds = [ctx.open_editor(img, None) for _ in range(n_editors)]
    for ed in eds:
        ed.canvas.modified = True              # пометки не сохранены
    app.processEvents()
    u.note_deferred(ctx.quit_blocker())        # ответ «busy» помощнику: обновление ждёт
    app.processEvents()
    return eds


# --- 1. «Скопировать и закрыть» в двух редакторах, снимок в буфере программы ----------------------------------
eds = setup()
check(up.read_attempt(up.attempt_path()).get("deferred") is True, "обновление ждёт закрытия редакторов")
launches.clear()
QTimer.singleShot(0, eds[0].copy_and_close)
QTimer.singleShot(400, eds[1].copy_and_close)
wait(3.0)
check(clipboard_busy(), "после «Скопировать и закрыть» буфер занят снимком программы")
check(not launches, f"пока скопированный снимок в буфере программы, выход для обновления не начинается ({len(launches)})")
# прошло 2 минуты (или буфер забрала другая программа): обновление идёт, помощник один
if getattr(ctx, "_clipboard_at", None) is not None:
    ctx._clipboard_at -= appmod.Clipshot.CLIPBOARD_HOLD_S + 1
check(not clipboard_busy(), "через 2 минуты буфер больше не держит обновление")
first = u.deferred_tick()
second = u.deferred_tick()                     # ещё одно закрытие или тик таймера ожидания сразу после
check(first is True and second is False and len(launches) == 1,
      f"помощник смены версии запущен один раз на попытку ({len(launches)})")
check(tries() == 1, f"попытка засчитана одна ({tries()} из {up.MAX_SWITCH_TRIES})")
# помощник спросил программу, а она снова занята («busy»): он ответил и вышел, следующий может начать позже
u.note_deferred("unsaved")
check(u.deferred_tick() is True and len(launches) == 2 and tries() == 2,
      "после ответа «занята» следующий помощник запускается, когда редакторы закрыты")

# --- 2. Два закрытия подряд без снимка в буфере: один общий таймер, один помощник ---------------------------
up._unlink(up.attempt_path())
owns[0] = False
eds = setup()
u._switch_started = None
launches.clear()
t0 = time.monotonic()
QTimer.singleShot(0, eds[0].copy_and_close)
QTimer.singleShot(400, eds[1].copy_and_close)
wait(3.0)
check(len(launches) == 1, f"два закрытия за 0,4 с: один помощник ({len(launches)})")
if launches:
    check(launches[0][0] - t0 >= 1.3, f"помощник через 1 с после последнего закрытия ({launches[0][0] - t0:.2f} с)")

# --- 3. «Перезапустить сейчас» и окно «С телефона» (22.11.2026: окно ожидания мигало и возвращалось) ----------
import json  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from clipshot import i18n, phone_ui  # noqa: E402

up._unlink(up.attempt_path())
owns[0] = False
for ed in list(ctx.editors):
    ed.canvas.modified = False
    ed.exported = True
shown = []
u.ui = type("UI2", (), {"deferred_notice": lambda self, text, cb: shown.append(text),
                        "__getattr__": lambda self, n: (lambda *a, **k: None)})()
up.write_attempt(up.attempt_path(), "1.32.2", "1.32.3", up.utcnow())
u._switch_started = None
visible = [False]
fake = SimpleNamespace(closing=False, hidden_for_photo=True, isVisible=lambda: visible[0])
phone_ui._window = fake
u.note_deferred("phone")
app.processEvents()
check(ctx.quit_blocker() == "phone", "спрятанное окно «С телефона» без нажатия держит обновление")
launches.clear()
check(u.restart_now() is True and len(launches) == 1, "«Перезапустить сейчас»: спрятанное окно телефона не мешает, переключение запущено")
check(ctx.quit_blocker() == "", "после нажатия помощник, спросив программу снова, получает «можно» (нет петли)")
check(ctx.answer_quit_for_update() == "ok", "quit-for-update после нажатия отвечает ok")
ctx._restart_asked_at -= appmod.Clipshot.RESTART_ASK_S + 1
check(ctx.quit_blocker() == "phone", "пометка нажатия действует ограниченно по времени")
# видимое окно держит и после нажатия
visible[0] = True
fake.hidden_for_photo = False
ctx.restart_requested()
check(ctx.quit_blocker() == "phone", "видимое окно «С телефона» держит обновление и после нажатия")
u._switch_started = None
shown.clear()
launches.clear()
check(u.restart_now() is False and not launches, "видимое окно: переключение не запущено")
app.processEvents()
check(bool(shown) and shown[-1] == up.wait_text("phone", "1.32.3") and "С телефона" in shown[-1],
      f"окно ожидания называет причину про окно «С телефона»: {shown[-1:]!r}")
# фото в обработке держит и спрятанное окно
visible[0] = False
fake.hidden_for_photo = True
rx = SimpleNamespace(running=True, _busy=1)
phone_ui._RECEIVERS.append(rx)
ctx.restart_requested()
check(ctx.quit_blocker() == "phone", "фото в обработке держит обновление даже после нажатия")
rx._busy = 0
check(ctx.quit_blocker() == "", "фото обработано, окно спрятано: после нажатия не держит")
phone_ui._RECEIVERS.remove(rx)
phone_ui._window = None
langs = sorted(p.name for p in (ROOT / "clipshot" / "i18n").iterdir() if p.is_dir() and p.name != "__pycache__")
check(len(langs) == 12, f"языков 12 ({len(langs)})")
for lang in langs:
    data = json.loads((ROOT / "clipshot" / "i18n" / lang / "updater.json").read_text(encoding="utf-8"))
    check("{version}" in data.get("updater.wait.phone", ""), f"updater.wait.phone есть на языке {lang}")
check(up.WAIT_KEYS.get("phone") == "updater.wait.phone", "WAIT_KEYS знает причину phone")

print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено {len(failures)}")
from clipshot.exitutil import quick_exit  # noqa: E402
quick_exit(1 if failures else 0)
