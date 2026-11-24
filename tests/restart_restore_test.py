# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""1.36.1, находки Б2, С3, С5 независимой проверки: снимки, спасённые перед перезапуском для обновления. 1.36.3: открытые
снимки без пометок (свежий снимок уже в папке снимков, скопированный) тоже возвращаются, но не помечаются несохранёнными.

Выход проверяется настоящим путём: вопрос quit-for-update по каналу команд (сокет, Clipshot._on_connection), ответ, выход
через 200 мс (quit_for_update_now; выход программы здесь закрывает окна, как QApplication.quit в Qt 6).

Б2: масштаб снимка (devicePixelRatio при экране 125-200 %) сохраняется: после перезапуска логический размер холста и
положение пометки те же, что до него (масштабы 1, 1.5, 2; запасной путь картинкой; масштаб только в самой PNG).
С5: два снимка, записанные в одну секунду, дают разные файлы. С3: смена версии сорвалась (deferred_lost): записи этого
запуска и их файлы убраны, редакторы снова держат выход. Запись, которую не удалось прочитать, убирается вместе с файлами.

1.36.3, находки проверки 1.36.3:
1. свежий снимок без пометок возвращается после обновления и без «Обновить», и через 30 минут после него (отложенное
   обновление прошло само); quit-for-uninstall (удаление программы) ничего не записывает и не отпускает несохранённое;
2. окно, дорисованное после «Обновить», записывается с новыми пометками; записанное и изменённое пишется по тому же пути;
3. отпущенное на перезапуск окно выход не держит, но закрытие его человеком спрашивает; закрытое человеком записанное
   окно убирается из записей вместе с файлами;
10. испорченная запись (autosave не строка, пометки не читаются) не обрывает остальные; непрочитанные пометки дают
   несохранённое окно.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/restart_restore_test.py
"""
import tmpclean  # noqa: F401
import json
import os
import sys
import tempfile
import threading
import time

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
tmp = tempfile.mkdtemp(prefix="clipsd-rsrs-")
for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[name] = os.path.join(tmp, name)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.pop("CLIPSD_LANG", None)

from PyQt6.QtCore import QPoint, QPointF  # noqa: E402
from PyQt6.QtGui import QImage  # noqa: E402
from PyQt6.QtNetwork import QLocalServer  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

qapp = QApplication(sys.argv)
qapp.setQuitOnLastWindowClosed(False)
from clipshot import app as appmod, editor as editor_mod, i18n, ipc, shapes as shapes_mod, updater as up  # noqa: E402
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
deferred = []
up.get_updater(a).note_deferred = lambda reason="busy": deferred.append(reason)


class QuitApp:
    """Выход программы: как QApplication.quit в Qt 6, сначала закрываются все окна."""
    calls = 0

    def quit(self):
        QuitApp.calls += 1
        qapp.closeAllWindows()

    def __getattr__(self, name):
        return getattr(qapp, name)


a.qapp = QuitApp()
sock_path = os.path.join(tmp, "cmd.sock")
a.server = QLocalServer(a)
a.server.newConnection.connect(a._on_connection)
check(a.server.listen(sock_path), "канал команд открыт")


def ask(command=ipc.QUIT_FOR_UPDATE):
    """Вопрос по сокету, как у clipsd-switch; после «ok» ждём выхода (таймер 200 мс)."""
    got = []
    t = threading.Thread(target=lambda: got.append(ipc.request(command, 5.0, sock_path)))
    t.start()
    while t.is_alive():
        qapp.processEvents()
        time.sleep(0.01)
    reply = got[0] if got else None
    settle(400)
    return reply


def new_run():
    """Программа запущена заново (после перезапуска): состояние выхода этого запуска сброшено."""
    a._update_quitting = False
    a._recovery_saved = []
    a._explicit_at = None
    a._restart_asked_at = None


def editor(dpr=1.0, marks=True):
    img = QImage(int(600 * dpr / 2) * 2, int(400 * dpr / 2) * 2, QImage.Format.Format_RGB32)
    img.fill(0xFFFFFF)
    img.setDevicePixelRatio(dpr)
    ed = a.open_editor(img, QPoint(40, 40))
    settle(120)
    if marks:
        r = Shape(RECT, "#ff0000", 2, QPointF(150, 90))
        r.points = [QPointF(150, 90), QPointF(190, 130)]
        ed.canvas.shapes = [r]
        ed.canvas.modified = True
    ed.exported = False
    ed.only_in_memory = False
    return ed


def draw(ed, x=100):
    """Человек дорисовал: новая пометка через сигнал холста (как настоящее рисование)."""
    r = Shape(RECT, "#00ff00", 2, QPointF(x, x))
    r.points = [QPointF(x, x), QPointF(x + 40, x + 40)]
    ed.canvas.shapes.append(r)
    ed.canvas.modified = True
    ed.canvas.changed.emit()


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


def listed():
    return list(a.config.get(a.RECOVERY_KEY) or [])


# --- Б2: масштабы 1, 1.5, 2 ---------------------------------------------------------------------------------
for dpr in (1.0, 1.5, 2.0):
    ed = editor(dpr)
    before = ed.render_image()
    logical = ed.canvas.base.deviceIndependentSize()
    box = red_box(before)
    a.restart_requested()
    reply = ask()
    check(reply == "ok" and not a.editors, f"масштаб {dpr}: ответ ok, программа вышла, окна закрыты без вопроса ({reply})")
    new_run()
    n = a.restore_after_restart()
    settle(150)
    e2 = a.editors[0] if a.editors else None
    after = e2.render_image() if e2 is not None else QImage()
    check(n == 1 and e2 is not None and abs(e2.canvas.base.devicePixelRatio() - dpr) < 1e-6,
          f"масштаб {dpr}: снимок открыт с тем же масштабом ({e2.canvas.base.devicePixelRatio() if e2 else None})")
    check(e2 is not None and e2.canvas.base.deviceIndependentSize() == logical,
          f"масштаб {dpr}: логический размер холста тот же ({logical} -> {e2.canvas.base.deviceIndependentSize() if e2 else None})")
    check(box is not None and red_box(after) == box, f"масштаб {dpr}: пометка на том же месте ({box} -> {red_box(after)})")
    check(e2 is not None and e2.canvas.modified and not e2.exported, f"масштаб {dpr}: открытый снова несохранённый")
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
try:
    ask()
finally:
    shapes_mod.shape_to_dict = real_to_dict
new_run()
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
ask()
for p in a.recovery_dir().glob("*.json"):
    p.unlink()
new_run()
a.restore_after_restart()
settle(150)
e2 = a.editors[0] if a.editors else None
check(e2 is not None and e2.canvas.base.devicePixelRatio() == 1.5 and e2.canvas.base.deviceIndependentSize() == logical,
      "без JSON масштаб 1.5 берётся из текста PNG")
check(e2 is not None and e2.canvas.modified, "без JSON окно несохранённое (закрытие спросит)")
drop_editors()

# --- С5: два снимка в одну секунду ----------------------------------------------------------------------------
real_time = appmod.time.time
appmod.time.time = lambda: 1700000000.0
try:
    editor(1.0)
    editor(1.0)
    a.restart_requested()
    ask()
finally:
    appmod.time.time = real_time
saved_names = listed()
pngs = [p for p in recovery_files() if p.endswith(".png")]
check(len(saved_names) == 2 and len(set(saved_names)) == 2 and len(pngs) == 2, f"два снимка в одну секунду: два разных файла ({pngs})")
new_run()
a.restore_after_restart()
settle(150)
drop_editors()

# --- С3: смена версии сорвалась (deferred_lost): записи этого запуска убраны ---------------------------------
e1, e2 = editor(1.0), editor(1.0)
a.restart_requested()
a.release_for_restart()   # «Обновить»: окна отпущены (updater._release_blockers)
check(a.quit_blocker() == "" and getattr(e1, "restart_keep", None) and getattr(e2, "restart_keep", None) and not e1.exported,
      "отпущенные окна выход не держат, exported не тронут")
a._save_editors_for_restart()   # записаны (как в quit_for_update_now перед самым выходом)
a.config[a.RECOVERY_KEY] = listed() + [os.path.join(tmp, "earlier-run.png")]   # запись прошлого запуска не трогается


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
check(len(a.editors) == 2 and all(not e.exported and not getattr(e, "restart_keep", None) for e in a.editors) and a.quit_blocker() == "unsaved",
      "редакторы снова несохранённые: закрытие спросит, выход держат")
check(a.drop_restart_restore() == 0, "повторный вызов ничего не трогает")
a.config.pop(a.RECOVERY_KEY, None)
new_run()
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

# --- 1.36.3, находка 1 (владелец 24.11.2026): открытый снимок без пометок возвращается после обновления ----------
shot = os.path.join(tmp, "Screenshot_fresh.png")
fresh = QImage(400, 300, QImage.Format.Format_RGB32)
fresh.fill(0x3366AA)
fresh.save(shot, "PNG")


def fresh_editor(exported=False, at=40):
    ed = a.open_editor(QImage(fresh), QPoint(at, at))
    settle(120)
    ed.canvas.modified = False
    ed.exported = exported
    ed.autosave_path = shot
    ed.only_in_memory = False
    return ed


e1 = fresh_editor()
e2 = fresh_editor(exported=True, at=60)   # уже скопирован или сохранён
check(a.quit_blocker() == "", "свежий снимок без пометок выход не держит (как раньше)")
a.restart_requested()
reply = ask()
check(reply == "ok" and QuitApp.calls and not a.editors, f"«Обновить»: ответ ok, программа вышла ({reply})")
check(len(listed()) == 2, f"оба открытых снимка записаны ({len(listed())})")
new_run()
n = a.restore_after_restart()
settle(150)
check(n == 2 and len(a.editors) == 2, f"после перезапуска оба снимка снова открыты ({n})")
check(all(not e.canvas.modified for e in a.editors), "открытые заново снимки не помечены несохранёнными: закрытие не спросит")
check(a.quit_blocker() == "", "и выход они не держат")
check(any(getattr(e, "autosave_path", None) == shot for e in a.editors), "у снимка из папки снимков прежний файл автосохранения")
check(any(getattr(e, "exported", False) for e in a.editors), "скопированный снимок остался скопированным")
check(os.path.exists(shot) and recovery_files() == [], "файл в папке снимков цел, файлы восстановления убраны")
drop_editors()

# без «Обновить»: помощник смены версии спрашивает сам (отложенное обновление, автоматическая смена версии)
fresh_editor()
reply = ask()
check(reply == "ok" and len(listed()) == 1, f"без решения человека свежий снимок тоже записан ({reply}, {len(listed())})")
new_run()
check(a.restore_after_restart() == 1, "и после перезапуска открыт")
drop_editors()

# «Обновить», окно с пометками отпущено, через 30 минут смена версии пошла сама: возвращаются оба окна
e1 = editor(1.0)
e2 = fresh_editor(at=60)
a.restart_requested()
a.release_for_restart()
a._explicit_at -= appmod.Clipshot.EXPLICIT_S + 1
a._restart_asked_at = None
check(not a.explicit_restart() and a.quit_blocker() == "", "30 минут прошло, отпущенное окно выход не держит")
reply = ask()
check(reply == "ok" and len(listed()) == 2, f"автоматическая смена версии: записаны оба окна ({reply}, {len(listed())})")
new_run()
check(a.restore_after_restart() == 2 and sorted(e.canvas.modified for e in a.editors) == [False, True],
      "после перезапуска: окно с пометками несохранённое, свежий снимок нет")
drop_editors()

# quit-for-uninstall (uninstall.sh): ничего не записывается, несохранённое держит выход и после «Обновить»
deferred.clear()
QuitApp.calls = 0
e1 = editor(1.0)
e2 = fresh_editor(at=60)
a.restart_requested()
a.release_for_restart()
reply = ask(getattr(ipc, "QUIT_FOR_UNINSTALL", "quit-for-uninstall"))
check(reply == "busy:unsaved" and not QuitApp.calls and len(a.editors) == 2,
      f"удаление программы: окно с несохранёнными пометками держит выход и после «Обновить» ({reply})")
e1.exported = True
reply = ask(getattr(ipc, "QUIT_FOR_UNINSTALL", "quit-for-uninstall"))
check(reply == "ok" and QuitApp.calls == 1 and not a.editors, f"удаление программы: ответ ok, программа вышла ({reply})")
check(not listed() and recovery_files() == [], f"удаление программы: снимки не записаны ({listed()}, {recovery_files()})")
new_run()

# --- проверка 1.36.3, круг 2 (Р1): окно с формой снимка возвращается с той же формой и рамкой ------------------
from PyQt6.QtCore import QRectF as _QRectF  # noqa: E402
from clipshot import forma as _forma  # noqa: E402
e1 = fresh_editor()
e1.canvas.form = _forma.Form(_forma.OVAL, box=_QRectF(40, 30, 200, 150))
e2 = fresh_editor(at=60)
e2.canvas.form = _forma.Form(_forma.ROUND, radius=33.0)
a.restart_requested()
reply = ask()
check(reply == "ok" and len(listed()) == 2, f"окна с формой записаны ({reply}, {len(listed())})")
new_run()
a.restore_after_restart()
settle(150)
forms = sorted((e.canvas.form.code, e.canvas.form.box, e.canvas.form.r) for e in a.editors)
check(("oval", _QRectF(40, 30, 200, 150), None) in forms and any(f[0] == "round" and abs((f[2] or 0) - 33.0) < 1e-6 for f in forms),
      f"после перезапуска овал с рамкой и скругление 33 на месте ({forms})")
check(all(not e.canvas.modified for e in a.editors) and not a.editors[0].canvas.undo_stack,
      "форма поставлена без отметки «изменено» и без шага отмены")
drop_editors()
check(a._form_from_dict({"code": "oval", "box": ["x"]}) is None and a._form_from_dict("мусор") is None,
      "испорченная запись формы: окно откроется прямоугольным, без ошибки")

# --- находки 2 и 3: окно дорисовали после «Обновить»; отпущенное окно закрывает человек ------------------------
asked = []
real_exec = editor_mod.ConfirmDialog.exec
editor_mod.ConfirmDialog.exec = lambda self: (asked.append(1), 0)[1]   # вопрос задан, человек вернулся к правке
try:
    e1 = fresh_editor()
    e2 = editor(1.0)
    a.restart_requested()
    a.release_for_restart()
    check(getattr(e2, "restart_keep", None) and not e2.exported and a.quit_blocker() == "", "окно с пометками отпущено, exported не тронут")
    e2.close()
    settle(50)
    check(asked == [1] and e2 in a.editors, "закрытие отпущенного окна с несохранёнными пометками спрашивает (находка 3)")
    draw(e1)   # свежий снимок дорисовали после «Обновить»
    check(a.quit_blocker() == "unsaved", "дорисованное окно снова держит выход, пока человек не решит")
    a._explicit_at = None
    reply = ask()
    check(reply == "busy:unsaved" and a.editors, f"без нового решения человека: обновление ждёт ({reply})")
    a.restart_requested()   # «Перезапустить сейчас»
    reply = ask()
    check(reply == "ok" and not a.editors and not asked[1:], f"после нового решения: ok, окна закрыты без вопроса ({reply})")
    path1 = next((item[0] for item in a._recovery_saved if item[1] is e1), None)
    data = json.loads(open(path1[:-4] + ".json", encoding="utf-8").read()) if path1 else {}
    check(len(listed()) == 2 and len(data.get("shapes", [])) == 1 and data.get("modified") is True,
          f"дорисованное окно записано с новой пометкой, как несохранённое (находка 2): {data.get('shapes')}")
finally:
    editor_mod.ConfirmDialog.exec = real_exec
new_run()
a.restore_after_restart()
settle(100)
drop_editors()

# записанное окно изменили: перезапись по тому же пути; записанное окно закрыл человек: запись и файлы убраны
e1 = fresh_editor()
e2 = fresh_editor(at=60)
a._save_editors_for_restart()
first = listed()
check(len(first) == 2 and all(getattr(e, "restart_written", None) for e in (e1, e2)), "оба окна записаны")
draw(e1)
check(not getattr(e1, "restart_written", None), "правка снимает признак записанного")
a._save_editors_for_restart()
data = [json.loads(open(n[:-4] + ".json", encoding="utf-8").read()) for n in listed()]
check(listed() == first and sorted(len(d["shapes"]) for d in data) == [0, 1],
      f"изменённое окно перезаписано по тому же пути, повторов нет ({len(listed())})")
e2.close()
settle(50)
check(len(listed()) == 1 and len([p for p in recovery_files() if p.endswith(".png")]) == 1,
      f"закрытое человеком записанное окно убрано из записей вместе с файлами (находка 3): {recovery_files()}")
e1.canvas.modified = False
e1.exported = True
e1.close()
settle(50)
check(not listed() and recovery_files() == [], "и второе: записей и файлов не осталось")
new_run()

# --- находка 10: испорченная запись не обрывает остальные; непрочитанные пометки дают несохранённое окно -----------
folder.mkdir(parents=True, exist_ok=True)
names = []
for k, extra in enumerate(({"autosave": 5, "modified": False, "shapes": []},          # autosave не строка
                           {"autosave": "", "modified": False, "shapes": [123]},       # пометки не читаются
                           {"autosave": "", "modified": False, "shapes": []})):        # исправная
    png = folder / f"1700000001-rec{k}.png"
    fresh.save(str(png), "PNG")
    (folder / f"1700000001-rec{k}.json").write_text(json.dumps({"dpr": 1.0, **extra}), encoding="utf-8")
    names.append(str(png))
a.config[a.RECOVERY_KEY] = names + [12345]   # и запись не путь
n = a.restore_after_restart()
settle(150)
check(n == 3 and len(a.editors) == 3, f"все исправные записи открыты, испорченная не оборвала остальные ({n})")
mods = [e.canvas.modified for e in a.editors]
check(mods == [False, True, False], f"окно с непрочитанными пометками несохранённое (закрытие спросит): {mods}")
check(recovery_files() == [] and not a.config.get(a.RECOVERY_KEY), "файлы и записи убраны")
drop_editors()

a.server.close()
print("\nИТОГ:", "провалено %d" % len(failures) if failures else "всё хорошо")
sys.exit(1 if failures else 0)
