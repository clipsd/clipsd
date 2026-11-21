# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""1.34.1 (Б2 проверки 1.34.0): фото с телефона, пока снимок-получатель закрывается.

Кнопка «С телефона» в редакторе кладёт каждое фото в этот снимок. В 1.34.0 фото, пришедшее, пока над снимком
открыт вопрос «Снимок не сохранён», вставлялось за окном вопроса, телефону уходило «принято» (он удаляет свою
копию), а «Закрыть без сохранения» уносило фото вместе со снимком: файлов 0.

Порядок A→B: вопрос открыт, потом фото: фото не в закрывающемся снимке, а отдельным снимком, файл сохранён,
уведомление называет файл; после «Закрыть без сохранения» отдельный снимок с фото открыт. Порядок B→A: фото
вставлено, потом человек сам закрыл снимок без сохранения: файл фото всё равно сохранён (автосохранение и при
вставке). Без автосохранения (настройка выключена): отдельный снимок только в памяти, выйти без вопроса нельзя,
уведомление без имени файла. Обычный случай: фото в открытый снимок, файл сохранён, телефону «принято».

Запуск: python3 tests/telefon_zakrytie_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import glob
import json
import os
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
tmp = tempfile.mkdtemp(prefix="clipsd-tel-zakr-")
for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[name] = os.path.join(tmp, name)
_screen = os.path.join(tmp, "screen.json")
with open(_screen, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1600, "height": 1000,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _screen

from PyQt6.QtCore import QTimer  # noqa: E402
from PyQt6.QtGui import QColor, QImage  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

qapp = QApplication(sys.argv)
qapp.setQuitOnLastWindowClosed(False)
from clipshot import app as appmod, i18n, phone_ui  # noqa: E402
from clipshot.i18n import tr  # noqa: E402

i18n.set_language("ru")
failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


a = appmod.Clipshot(qapp)
a.save_config = lambda: None
notes = []
a.notify = lambda t, *_x: notes.append(t)


class Rx:
    def __init__(self):
        self.confirmed, self.rejected = [], []

    def confirm(self, pid):
        self.confirmed.append(pid)

    def reject(self, pid, n):
        self.rejected.append(pid)


class Session:
    def __init__(self, target):
        self.ctx, self.target, self.receiver, self.notified = a, target, Rx(), False

    def live_window(self):
        return None   # окно приёма спрятано после фото


def setup(name, auto_save=True):
    folder = os.path.join(tmp, name)
    os.makedirs(folder)
    a.config.update(theme_chosen=True, tour_done=True, novoe_enabled=False, auto_save=auto_save, auto_save_dir=folder)
    notes.clear()
    img = QImage(900, 500, QImage.Format.Format_RGB32)
    img.fill(QColor("#ffffff"))
    ed = a.open_editor(img, None)
    ed.autosave_path = None
    ed.canvas.push_undo()   # правка человека: при закрытии будет вопрос
    return folder, ed


def photo():
    img = QImage(1200, 900, QImage.Format.Format_RGB32)
    img.fill(QColor("#ff0000"))
    return img


def files(folder):
    return sorted(glob.glob(os.path.join(folder, "*.jpg")))   # фото с телефона сохраняется как JPEG


def run(ed, order, session, state):
    def deliver():
        before = len(ed.canvas.shapes)
        others = [e for e in a.editors if e is not ed]
        phone_ui.deliver_photo(session, {"image": photo(), "count": 1, "pid": "p1"})
        state["inserted"] = len(ed.canvas.shapes) - before
        state["new"] = [e for e in a.editors if e is not ed and e not in others]

    def discard():
        d = QApplication.activeModalWidget()
        state["dialog"] = type(d).__name__ if d is not None else None
        if d is not None:
            d.yes.click()   # «Закрыть без сохранения»: человек решал про свои прежние правки

    if order == "AB":
        QTimer.singleShot(50, ed.close)       # вопрос «Снимок не сохранён» открыт (вложенный цикл)
        QTimer.singleShot(300, deliver)       # фото приходит во время вопроса
    else:
        QTimer.singleShot(50, deliver)        # фото вставлено
        QTimer.singleShot(300, ed.close)      # потом человек закрыл снимок
    QTimer.singleShot(600, discard)
    QTest.qWait(1200)


def close_all():
    for e in list(a.editors):
        e.exported = True
        e.only_in_memory = False
        e.close()
    QTest.qWait(100)


# --- A→B: вопрос открыт, потом фото --------------------------------------------------------------------------------
folder, ed = setup("ab")
s, st = Session(ed), {}
run(ed, "AB", s, st)
saved = files(folder)
check(st.get("dialog") == "ConfirmDialog", f"A→B: вопрос «Снимок не сохранён» был открыт ({st.get('dialog')})")
check(st.get("inserted") == 0, f"A→B: фото не положено в закрывающийся снимок ({st.get('inserted')})")
check(len(st.get("new", [])) == 1 and st["new"][0] in a.editors, "A→B: фото открыто отдельным снимком, он открыт и после закрытия первого")
check(ed not in a.editors, "A→B: первый снимок закрыт, как просил человек")
check(len(saved) == 1, f"A→B: файл фото сохранён ({saved})")
check(s.receiver.confirmed == ["p1"], f"A→B: телефону «принято» ({s.receiver.confirmed})")
check(notes == [tr("phone.photo_apart_saved", path=saved[0] if saved else "?")],
      f"A→B: уведомление говорит, где фото ({notes})")
check(bool(st.get("new")) and st["new"][0].autosave_path == (saved[0] if saved else None),
      "A→B: отдельный снимок знает свой файл (повторно не сохраняется)")
close_all()

# --- B→A: фото вставлено, потом человек закрыл снимок без сохранения -------------------------------------------------
folder, ed = setup("ba")
s, st = Session(ed), {}
run(ed, "BA", s, st)
saved = files(folder)
check(st.get("inserted") == 1 and not st.get("new"), f"B→A: фото положено в открытый снимок ({st.get('inserted')})")
check(st.get("dialog") == "ConfirmDialog" and ed not in a.editors, "B→A: человек видел фото и закрыл снимок без сохранения")
check(len(saved) == 1, f"B→A: файл фото всё равно сохранён ({saved})")
check(notes == [tr("phone.photo_late")], f"B→A: уведомление правдивое: фото было открыто в редакторе ({notes})")
close_all()

# --- автосохранение выключено: отдельный снимок только в памяти ---------------------------------------------------
folder, ed = setup("off", auto_save=False)
s, st = Session(ed), {}
run(ed, "AB", s, st)
check(not files(folder) and len(st.get("new", [])) == 1, "без автосохранения: файла нет, фото открыто отдельным снимком")
check(bool(st.get("new")) and st["new"][0].only_in_memory and a.quit_blocker() == "unsaved",
      f"без автосохранения: снимок с фото только в памяти, выйти без вопроса нельзя ({a.quit_blocker()})")
check(notes == [tr("phone.photo_apart")], f"без автосохранения: уведомление без имени файла ({notes})")
close_all()

# --- обычный случай: снимок открыт, вопроса нет ---------------------------------------------------------------------
folder, ed = setup("plain")
s = Session(ed)
before = len(ed.canvas.shapes)
phone_ui.deliver_photo(s, {"image": photo(), "count": 1, "pid": "p2"})
QTest.qWait(100)
check(len(ed.canvas.shapes) == before + 1 and len(a.editors) == 1, "обычно: фото в открытом снимке, отдельного нет")
check(len(files(folder)) == 1 and s.receiver.confirmed == ["p2"], f"обычно: файл фото сохранён, телефону «принято» ({files(folder)})")
close_all()

print("ИТОГ:", "все проверки пройдены" if not failures else f"{len(failures)} не пройдено")
sys.exit(1 if failures else 0)
