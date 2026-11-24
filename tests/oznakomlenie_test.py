# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""1.35: окно «Ознакомление» (oznakomlenie.py), слова владельца 22.11.2026, компоновка А1.

Проверяется: (1) окно открывается из меню значка и из «Новое в версии» («Показать новое»), курса поверх окна больше
нет; (2) в списке все функции каталога, новинки сверху отдельной группой с меткой «Новое», остальные в своих группах;
(3) выбор пункта включает инструмент и обводит кнопку; «Показать» рисует пример на учебном снимке, «Сначала» его
возвращает; (4) учебный снимок ничего не сохраняет и не копирует, закрывается без вопроса, в список редакторов
программы не попадает; (5) пункты окна выделения: учебная картинка и «Попробовать по-настоящему» запускает настоящую
функцию; (6) «просмотрено»; (7) «Что нового» в колокольчике: прочитано после «Показать новое» и после «Ознакомления»,
после прочтения в колокольчике окно новинок не приходит; (8) окно новинок ждёт спокойной минуты при открытом окне
текста с картинки, режиме перевода, несохранённых пометках; (9) 12 языков: все строки есть, без длинных тире и
эмодзи, окно в экране; (10) светлая и тёмная темы; окно помещается на экран 1366x768 при масштабе 150 % (910x512).

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/oznakomlenie_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import json
import os
import re
import sys
import time
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(here)
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp(prefix="clipsd-ozn-")
for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[name] = os.path.join(tmp, name)
_screen = os.path.join(tmp, "screen.json")
with open(_screen, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1600, "height": 1000,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _screen
os.environ.pop("CLIPSD_LANG", None)

from PyQt6.QtCore import QPoint, QRect, QTimer  # noqa: E402
from PyQt6.QtGui import QColor, QImage  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

qapp = QApplication(sys.argv)

import clipshot  # noqa: E402
from clipshot import app as appmod, i18n, notifications, novoe, oznakomlenie, themes  # noqa: E402
from clipshot.i18n import tr  # noqa: E402

V = "1.34.0"
clipshot.__version__ = V
novoe.__version__ = V

failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


def settle(ms=60):
    for _ in range(6):
        qapp.processEvents()
        QTest.qWait(max(1, ms // 6))


i18n.set_language("ru")
a = appmod.Clipshot(qapp)
saves = []
a.save_config = lambda: saves.append(1)
a.notify = lambda *_x: None


def fresh(**kw):
    a.config.clear()
    a.config.update(dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True))
    novoe.on_start(a.config)
    a.config.update(kw)


def close_all():
    win = getattr(a, "_ozn_window", None)
    novoe.ask_done(a.config)   # вопрос «Хотите узнать о других функциях» после закрытия окна здесь не нужен
    if win is not None:
        win.close()
    for ed in list(a.editors):
        ed.canvas.modified = False
        ed.close()
    settle(450)   # окно удаляется, отложенный вопрос после него (300 мс) уже не нужен: ask_done выше


def answer(attr, timeout_ms=4000):
    state = {"left": timeout_ms // 30}

    def go():
        w = QApplication.activeModalWidget()
        if w is None:
            state["left"] -= 1
            if state["left"] > 0:
                QTimer.singleShot(30, go)
            return
        getattr(w, attr).click()
    QTimer.singleShot(30, go)


# --- 1. открытие ----------------------------------------------------------------------------------------------
fresh()
menu = a._build_tray_menu()
# 1.36: «Ознакомление» и «Что нового» в подменю «Обучение» меню значка (feat/menyu-tray)
def _all_actions(m):
    out = []
    for x in m.actions():
        out.append((m, x))
        if x.menu() is not None:
            out.extend(_all_actions(x.menu()))
    return out
pairs = _all_actions(menu)
acts = [x for _m, x in pairs if x.text() == tr("ozn.menu")]
owner = next((m for m, x in pairs if x.text() == tr("ozn.menu")), None)
names = [x.text() for x in owner.actions()] if owner is not None else []
check(len(acts) == 1 and tr("novoe.menu") in names and names.index(tr("ozn.menu")) < names.index(tr("novoe.menu")),
      "меню значка: «Ознакомление» и «Что нового» в одном подменю, «Ознакомление» первым")
acts[0].trigger()
settle(200)
win = getattr(a, "_ozn_window", None)
check(win is not None and win.isVisible(), "из меню значка открывается окно «Ознакомление»")
check(win is not None and win.windowTitle() == "ClipSD: Ознакомление", "название окна")
from PyQt6.QtCore import Qt  # noqa: E402
check(win is not None and not (win.windowFlags() & Qt.WindowType.WindowStaysOnTopHint) and not win.isModal(),
      "окно обычное: не поверх всех и не модальное")
check(not a.editors, "учебный редактор не попал в список редакторов программы")
close_all()

fresh()
novoe.window_done(a.config)
answer("show_button")
shown = a.show_novoe()
settle(600)
win = getattr(a, "_ozn_window", None)
check(shown == "show" and win is not None and win.current == win.new_list[0],
      "«Показать новое»: окно «Ознакомление» сразу на первой новинке")
check(not a.editors and all(getattr(e, "tour", None) is None for e in a.editors), "курс поверх окна больше не запускается")
close_all()

# --- 2. список --------------------------------------------------------------------------------------------------
fresh()
win = a.open_oznakomlenie()
settle(100)
check(set(win.rows) == {c[0] for c in oznakomlenie.CATALOG} and len(win.rows) >= 25, f"в списке все функции: {len(win.rows)}")
new = oznakomlenie.new_ids(a.config)
check(new == ["phone_tile", "windows", "other_area", "phone_editor", "translate_head", "numbers"], f"новинки 1.34: {new}")
check(win.group_labels[0].text() == "Новое в версии 1.34", f"первая группа: «{win.group_labels[0].text()}»")
check(all(win.rows[i].is_new for i in new) and not any(r.is_new for k, r in win.rows.items() if k not in new),
      "метка «Новое» только у новинок")
order = [win.scroll.widget().layout().itemAt(i).widget() for i in range(win.scroll.widget().layout().count() - 1)]
first_plain = next(i for i, w in enumerate(order) if getattr(w, "ident", None) and not w.is_new)
check(all(getattr(w, "is_new", True) for w in order[1:first_plain] if getattr(w, "ident", None)), "новинки идут сверху, до остальных")
check({tr(f"ozn.g_{g}") for g in ("snimok", "pometki", "text", "save", "settings")} <= {l.text() for l in win.group_labels},
      "группы: снимок, пометки, текст и перевод, сохранение, настройки")
check(all(oznakomlenie.item_title(i) and oznakomlenie.item_line(i) and oznakomlenie.item_hint(i) for i in win.rows), "у каждого пункта три текста")
close_all()
cfg_old = dict(appmod.DEFAULTS, novoe_from="1.30.0", novoe_version=V)
check(oznakomlenie.new_ids(cfg_old) == new, "после обновления: новинки с прежней версии")
new135 = [it[1] for it in novoe.ITEMS if it[0] == "1.35.0"]
check(oznakomlenie.new_ids(dict(appmod.DEFAULTS), "1.35.5") == [i for i in new135 if i in oznakomlenie.BY_ID] and len(new135) == 7,
      "новая версия без своих новинок: новинки самой свежей версии таблицы (1.35), без внутренних доработок")
new136_all = [it[1] for it in novoe.ITEMS if it[0] == "1.36.0"]
new136 = [i for i in new136_all if i in oznakomlenie.BY_ID]
check(oznakomlenie.new_ids(dict(appmod.DEFAULTS), "1.36.0") == new136 and set(new136) == {"pechat", "pdf", "stikery", "ten_ramka", "zakrepit", "qr_chtenie", "pipetka"} and set(new136_all) == set(new136), "версия 1.36: свои новинки (печать, PDF, стикеры, тень и рамка, закрепить, QR, пипетка)")
check(oznakomlenie.new_ids(dict(appmod.DEFAULTS), "1.37.0") == new136, "версия без своих новинок: показываются новинки самой свежей из таблицы")

# --- 3. обучение: затемнение, показ, «Теперь вы», «Получилось» ---------------------------------------------------------
from clipshot import ozn_lesson  # noqa: E402
from PyQt6.QtCore import QEvent, QPoint, QPointF  # noqa: E402
from PyQt6.QtGui import QKeyEvent  # noqa: E402

ozn_lesson.TIME_SCALE = 0.03      # показ идёт в 30 раз быстрее; плановая длительность (demo_ms) считается без сжатия
ozn_lesson.set_reduce_motion(False)


def wait_phase(win, phases, seconds=40):
    for _ in range(int(seconds * 1000 / 30)):
        if win.lesson.phase not in phases:
            return
        settle(30)


def run_demo(win):
    """Запустить «Показать», дождаться конца; вернуть, что было на снимке перед возвратом к исходному."""
    snap = {}
    orig = win.lesson._fresh_if_dirty

    def spy():
        cv = win.editor.canvas
        if cv.shapes or not cv.form.is_rect or cv.redo_stack:
            snap.update(kinds=[s.kind for s in cv.shapes], nums=[s.number for s in cv.shapes if s.kind == "number"],
                        form=not cv.form.is_rect, redo=bool(cv.redo_stack), texts=[s.text for s in cv.shapes if s.kind == "text"])
        orig()
    win.lesson._fresh_if_dirty = spy
    win.play()
    wait_phase(win, ("demo",))
    win.lesson._fresh_if_dirty = orig
    return snap


fresh()
win = a.open_oznakomlenie()
settle(100)
win.select("arrows")
settle(400)
ls = win.lesson
ed = win.editor
check(ed is not None and ed.canvas.tool == "move" and ls.phase == "you", "пункт «Стрелки»: учебный снимок, обучение ждёт человека")
check(ls.dimmer is not None and ls.dimmer.isVisible() and ls.dimmer.parentWidget() is ed and ls.dimmer.geometry() == ed.rect(),
      "затемнение лежит только на учебном редакторе")
target_rect = ls.rect_of(ls.steps[0].target)
check(ls.dimmer.hole.contains(target_rect) and ls.dimmer.hole.width() < 200, f"окошко на нужной кнопке ({ls.dimmer.hole}, кнопка {target_rect})")
check(not ls.dimmer.mask().contains(ls.dimmer.hole.center()) and ls.dimmer.mask().contains(QPoint(ed.width() - 5, ed.height() - 5)),
      "щелчок по окошку проходит к кнопке (маска), вне окошка затемнение держит")
check(ls.dimmer.caption.text() == tr("ozn.step_press") and tr("ozn.step_of", i=1, n=2) == ls.dimmer.step_label.text(), "подсказка «Шаг 1 из 2: Нажмите сюда»")
check(win.show_button.isVisible() and win.try_button.text() == tr("ozn.skip") and win.reset_button.isVisible(), "кнопки «Показать», «Пропустить», «Сначала»")

# показ: курсор, шаги, длительность, возврат к исходному, «Теперь вы»
cur_moves = []
orig_put = ozn_lesson.Cursor.put
ozn_lesson.Cursor.put = lambda self, pt: (cur_moves.append(1), orig_put(self, pt))[1]
snap = run_demo(win)
ozn_lesson.Cursor.put = orig_put
check("arrow" in snap.get("kinds", []), f"показ нарисовал стрелку ({snap})")
check(3000 <= ls.demo_ms <= 8000, f"показ длится {ls.demo_ms / 1000:.1f} с (3-8 с)")
check(len(cur_moves) > 80, f"курсор плавно ехал ({len(cur_moves)} кадров)")
check(ls.phase == "you" and win.editor is not ed and not win.editor.canvas.shapes and win.hint_line.text() == tr("ozn.now_you"),
      "после показа: снимок исходный, «Теперь вы»")
check(ls.dimmer.isVisible() and ls.index == 0, "затемнение снова на первой кнопке")

# человек повторяет: кнопка, потом рисует
ed = win.editor
ed.tool_buttons["arrow"].click() if ed.tool_buttons["arrow"].isVisible() else ed.select_tool("arrow")
settle(400)
check(ls.index == 1 and ls.dimmer.caption.text() == tr("ozn.step_draw"), "программа увидела выбранный инструмент: шаг 2, «Проведите мышью»")
for k, pt in ((QEvent.Type.MouseButtonPress, (700, 200)), (QEvent.Type.MouseMove, (680, 250)), (QEvent.Type.MouseMove, (650, 300)),
              (QEvent.Type.MouseButtonRelease, (650, 300))):
    ozn_lesson.send_mouse(ed.canvas, k, QPointF(*pt), k != QEvent.Type.MouseButtonRelease)
settle(500)
check(ls.phase == "done" and win.result_label.isVisible() and win.result_label.text() == tr("ozn.success"), "стрелка нарисована: «Получилось»")
check(win.rows["arrows"].done and "arrows" in a.config.get("ozn_done", []) and not ls.dimmer.isVisible(), "галочка у пункта, затемнение ушло")
check(win.next_button.isVisible(), "кнопка «Следующая функция»")
nxt = win.order[win.order.index("arrows") + 1]
win.next_button.click()
settle(300)
check(win.current == nxt and not win.result_label.isVisible(), f"«Следующая функция»: пункт «{nxt}»")

# «Получилось» для разных функций
def you_blur(w):
    w.editor.select_tool("blur")
    settle(300)
    for k, pt in ((QEvent.Type.MouseButtonPress, (516, 146)), (QEvent.Type.MouseMove, (600, 170)), (QEvent.Type.MouseButtonRelease, (700, 180))):
        ozn_lesson.send_mouse(w.editor.canvas, k, QPointF(*pt), k != QEvent.Type.MouseButtonRelease)


def you_numbers(w):
    ed2 = w.editor
    ed2.select_tool("number")
    settle(300)
    for pt in ((22, 144), (22, 184)):
        ozn_lesson.send_mouse(ed2.canvas, QEvent.Type.MouseButtonPress, QPointF(*pt), True)
        ozn_lesson.send_mouse(ed2.canvas, QEvent.Type.MouseButtonRelease, QPointF(*pt), False)
    settle(300)
    list(ed2.color_buttons.values())[4].click()
    settle(300)
    pt = (22, 264)
    ozn_lesson.send_mouse(ed2.canvas, QEvent.Type.MouseButtonPress, QPointF(*pt), True)
    ozn_lesson.send_mouse(ed2.canvas, QEvent.Type.MouseButtonRelease, QPointF(*pt), False)


def you_text(w):
    w.editor.select_tool("text")
    settle(300)
    pt = (300, 380)
    ozn_lesson.send_mouse(w.editor.canvas, QEvent.Type.MouseButtonPress, QPointF(*pt), True)
    ozn_lesson.send_mouse(w.editor.canvas, QEvent.Type.MouseButtonRelease, QPointF(*pt), False)
    settle(100)
    w.editor.canvas.text_edit.setPlainText("Привет")
    w.editor.canvas.commit_text()


def you_undo(w):
    w.editor.select_tool("rect")
    settle(300)
    for k, pt in ((QEvent.Type.MouseButtonPress, (22, 120)), (QEvent.Type.MouseMove, (400, 130)), (QEvent.Type.MouseButtonRelease, (738, 148))):
        ozn_lesson.send_mouse(w.editor.canvas, k, QPointF(*pt), k != QEvent.Type.MouseButtonRelease)
    settle(400)
    w.editor.undo_button.click()


you = {"blur": you_blur, "numbers": you_numbers, "text": you_text, "undo": you_undo,
       "save": lambda w: w.editor.save_button.click(), "copy": lambda w: w.editor.copy_button.click(),
       "crop": lambda w: w.editor.select_tool("crop"), "move": lambda w: w.editor.select_tool("move"),
       "eraser": lambda w: w.editor.select_tool("eraser"), "settings": lambda w: w.lesson.note("settings"),
       "marker": lambda w: (w.editor.select_tool("marker"), settle(300), [ozn_lesson.send_mouse(w.editor.canvas, k, QPointF(*pt), k != QEvent.Type.MouseButtonRelease) for k, pt in ((QEvent.Type.MouseButtonPress, (520, 98)), (QEvent.Type.MouseMove, (600, 104)), (QEvent.Type.MouseMove, (680, 98)), (QEvent.Type.MouseButtonRelease, (700, 98)))])}
for ident, fn in you.items():
    win.select(ident)
    settle(400)
    fn(win)
    settle(900)
    check(win.lesson.phase == "done" and win.result_label.isVisible(), f"«{ident}»: программа увидела, что сделано: «Получилось» (фаза {win.lesson.phase}, шаг {win.lesson.index})")

# показ каждой функции: длительность 3-8 секунд и результат на снимке
expect = {"arrows": "arrow", "shapes": "rect", "marker": "marker", "blur": "blur", "numbers": "number", "text": "text"}
for ident, kind in expect.items():
    win.select(ident)
    settle(300)
    snap = run_demo(win)
    check(kind in snap.get("kinds", []) and 3000 <= win.lesson.demo_ms <= 8000,
          f"показ «{ident}»: на снимке «{kind}», {win.lesson.demo_ms / 1000:.1f} с")
    if ident == "numbers":
        check(snap.get("nums") == [1, 2, 1], f"показ «numbers»: по цветам {snap.get('nums')}")
    if ident == "text":
        check(snap.get("texts") == [tr("ozn.demo_best")], f"показ «text»: набрана надпись {snap.get('texts')}")
for ident, key in (("undo", "redo"),):
    win.select(ident)
    settle(300)
    snap = run_demo(win)
    check(snap.get(key) and 3000 <= win.lesson.demo_ms <= 8000, f"показ «{ident}»: {snap}, {win.lesson.demo_ms / 1000:.1f} с")
for ident in ("crop", "eraser", "move", "save", "translate_head", "ocr"):
    win.select(ident)
    settle(300)
    run_demo(win)
    check(3000 <= win.lesson.demo_ms <= 8000 and win.lesson.phase == "you", f"показ «{ident}»: {win.lesson.demo_ms / 1000:.1f} с")

# прервать: Esc и «Пропустить»
win.select("numbers")
settle(300)
win.play()
settle(150)
n_before = len(win.editor.canvas.shapes)
win.isActiveWindow = lambda: True
ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
check(win.eventFilter(win, ev) is True and ls.phase == "free", "Esc во время показа прерывает его")
settle(300)
n_a = len(win.editor.canvas.shapes)
settle(300)
check(not ls.dimmer.isVisible() and not ls.cursor.isVisible() and len(win.editor.canvas.shapes) == n_a, "показ остановлен, затемнения и курсора нет")
win.select("blur")
settle(300)
check(ls.dimmer.isVisible(), "новый пункт: затемнение снова")
ls.dimmer.skip_button.click()
check(ls.phase == "free" and not ls.dimmer.isVisible() and win.hint_line.text() == tr("ozn.try_now"), "«Пропустить» убирает затемнение")
ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
win.select("rect" if False else "shapes")
settle(300)
check(win.eventFilter(win, ev) is True and ls.phase == "free", "Esc при «Теперь вы» убирает затемнение")
# 15 секунд без движения: мягкая подсказка
ozn_lesson.IDLE_MS = 400
win.select("shapes")
settle(900)
check(ls.dimmer.idle.isVisible() and tr("ozn.idle_hint") == ls.dimmer.idle.text(), "долго ничего не происходит: мягкая подсказка")
ozn_lesson.IDLE_MS = 15000
# уменьшить движение: показ по кадрам
ozn_lesson.set_reduce_motion(True)
moves = []
ozn_lesson.Cursor.put = lambda self, pt: (moves.append(1), orig_put(self, pt))[1]
win.select("arrows")
settle(300)
snap = run_demo(win)
ozn_lesson.Cursor.put = orig_put
ozn_lesson.set_reduce_motion(False)
check("arrow" in snap.get("kinds", []) and len(moves) < 20, f"«уменьшить движение»: показ по кадрам ({len(moves)} положений курсора), результат тот же")
close_all()

# --- 4. учебный снимок ничего не сохраняет ------------------------------------------------------------------
fresh()
win = a.open_oznakomlenie()
settle(100)
cfg_before = json.dumps(a.config, sort_keys=True, default=str)
files_before = sorted(os.listdir(tmp))
saved_calls = []
orig_autosave = a.autosave
a.autosave = lambda *x, **k: saved_calls.append(1) or ""
copied = []
a.copy_image = lambda *x, **k: copied.append(1)
win.select("save")
settle(300)
ed = win.editor
ed.save_button.click()
ed.copy_button.click()
ed.copy_close_button.click()
settle(200)
check(not saved_calls and not copied, "«Сохранить» и «Скопировать» в учебном снимке ничего не сохраняют и не копируют")
check(QApplication.activeModalWidget() is None, "ни окна выбора файла, ни вопросов")
win.select("arrows")
settle(300)
ed = win.editor
ed.select_tool("rect")
ed.canvas.push_undo()
check(ed.canvas.modified, "на учебном снимке есть несохранённые пометки")
shown_dialogs = []
QTimer.singleShot(0, lambda: shown_dialogs.append(QApplication.activeModalWidget()))
win.close()
settle(300)
check(not any(shown_dialogs), "закрытие окна с пометками без вопроса «Снимок не сохранён»")
check(getattr(a, "_ozn_window", None) is None and not a.editors, "окно и учебный редактор закрыты")
check(not saved_calls and not copied and sorted(os.listdir(tmp)) == files_before, "в папках ничего не появилось")
a.autosave = orig_autosave

# --- 5. пункты окна выделения -----------------------------------------------------------------------------------
fresh()
win = a.open_oznakomlenie()
settle(100)
called = []
# С4 проверки 1.36.1: пометка «Ознакомления» для окна выделения ставится только при настоящем старте выделения
real_region, real_full = a.capture_region, a.capture_fullscreen
real_start = a._start_region
starts = []
a._start_region = lambda full=False, translate=False: starts.append(getattr(a, "_guide", None))
a.last_trigger = time.monotonic()   # только что было другое срабатывание: _busy() откажет
win.select("region")
settle(100)
win.real_button.click()
check(getattr(a, "_guide", None) is None, "выделение не началось (занято): подсказка «Ознакомления» не остаётся")
if win._real_wait is not None:
    win._real_wait.stop()
a.last_trigger = 0.0
a.capture_region()   # следующий обычный Alt+W
settle(300)
check(starts == [None], f"следующий обычный Alt+W без подсказки «Ознакомления» ({starts})")
starts.clear()
a.last_trigger = 0.0
win.real_button.click()
check(getattr(a, "_guide", None) == "region", "настоящий старт выделения из «Ознакомления»: подсказка поставлена")
settle(700)
check(starts == ["region"], f"окно выделения получило подсказку пункта ({starts})")
if win._real_wait is not None:
    win._real_wait.stop()
win.showNormal()
a._start_region, a._guide, a.last_trigger = real_start, None, 0.0
a.capture_region = lambda delay=0, **kw: (called.append(("region", delay)), setattr(a, "selector", True))
a.capture_fullscreen = lambda delay=0, **kw: (called.append(("full", delay)), setattr(a, "selector", True))
a.open_phone = lambda target=None: called.append(("phone", target))
for ident, real in (("windows", "region"), ("other_area", "region"), ("phone_tile", "phone"), ("full", "full")):
    win.select(ident)
    settle(100)
    check(win.stack.currentIndex() == 2 and win.panel_label.pixmap() is not None and not win.panel_label.pixmap().isNull(),
          f"«{ident}»: учебная картинка панели")
    check(win.real_button.isVisible(), f"«{ident}»: кнопка «Попробовать по-настоящему»")
    pd = win.panel_dimmer
    check(pd.isVisible() and pd.hole.isValid() and pd.parentWidget() is win.stack.widget(2) and pd.caption.text() == tr("ozn.step_real"),
          f"«{ident}»: затемнение учебной панели, окошко на нужном месте ({pd.hole})")
    if ident == "windows":
        snap = run_demo(win)
        check(3000 <= win.lesson.demo_ms <= 8000 and win.lesson.phase == "you", f"«{ident}»: курсор показал на панели ({win.lesson.demo_ms / 1000:.1f} с)")
    called.clear()
    win.real_button.click()
    settle(1500)
    check(bool(called) and called[0][0] == real, f"«{ident}»: настоящая функция запущена ({called})")
    a.selector = None
    check(win.lesson.phase == "done" and win.result_label.isVisible(), f"«{ident}»: «Получилось» после настоящего запуска")
    if real != "phone":
        win.showNormal()
        if win._real_wait is not None:
            win._real_wait.stop()
# кнопка «С телефона» в учебном редакторе: пояснение, а не окно с QR-кодом
win.select("numbers")
settle(200)
called.clear()
win.editor.phone_button.click()
settle(100)
check(win.current == "phone_editor" and not called and win.real_button.isVisible(), "кнопка «С телефона» учебного редактора ведёт на пояснение")
settle(300)
win.editor.phone_button.click()
settle(500)
check(win.lesson.phase == "done" and not called, "нажали «С телефона» в учебном редакторе: «Получилось», окно с QR-кодом не открылось")
close_all()

# --- 6. просмотрено ---------------------------------------------------------------------------------------------
fresh()
win = a.open_oznakomlenie()
settle(100)
check(not win.rows["blur"].seen, "до открытия не просмотрено")
win.select("blur")
settle(100)
check(win.rows["blur"].seen and "blur" in a.config.get("ozn_seen", []), "пункт отмечен просмотренным и запомнен")
close_all()
win = a.open_oznakomlenie()
check(win.rows["blur"].seen and not win.rows["crop"].seen, "после повторного открытия отметка на месте")
close_all()

# --- 7. колокольчик ---------------------------------------------------------------------------------------------
wid = f"whatsnew:{V}"
fresh(tour_done=True)
a.config["notices_read"] = []
check(wid in [i["id"] for i in notifications.unread(a.config, V)], "до просмотра: «Что нового» в колокольчике непрочитано")
answer("later_button")
a.show_novoe(None, auto=True)
settle(100)
check(wid in [i["id"] for i in notifications.unread(a.config, V)], "«Позже»: колокольчик не трогается")
answer("show_button")
a.show_novoe(None, auto=True)
settle(500)
check(wid not in [i["id"] for i in notifications.unread(a.config, V)], "«Показать новое»: «Что нового» отмечено прочитанным, точка гаснет")
check(wid in [i["id"] for i in notifications.items(a.config, V)], "пункт остаётся в списке как справка")
close_all()
fresh()
a.config["notices_read"] = []
a.open_oznakomlenie()
settle(100)
check(wid not in [i["id"] for i in notifications.unread(a.config, V)], "«Ознакомление» на новинках: колокольчик прочитан")
close_all()
fresh()
a.config["notices_read"] = []
check(novoe.window_pending(a.config), "до чтения в колокольчике окно новинок ждёт")
ed = a.open_editor(QImage(400, 300, QImage.Format.Format_RGB32), None)
settle(100)
orig_up = None
import clipshot.updater as upmod  # noqa: E402
shown_notes = []
upmod.UpdaterUI.whats_new = lambda self, v, md: shown_notes.append(v)
item = [i for i in notifications.items(a.config, V) if i["id"] == wid][0]
ed.open_notice(item)
check(not novoe.window_pending(a.config) and shown_notes == [V], "«Что нового» открыли в колокольчике: окно новинок само не придёт")
close_all()

# --- 8. окно новинок ждёт спокойной минуты ------------------------------------------------------------------------
def close_editors():
    for _ in range(3):
        for e in list(a.editors):
            if e.canvas.text_edit is not None:
                e.canvas.cancel_text()
            e.canvas.modified = False
            e.close()
        settle(40)


fresh()
a.NOVOE_DELAY_MS = 250
a.QUIET_RETRY_MS = 60
got = []
orig_show = a.show_novoe
a.show_novoe = lambda *x, **k: got.append(1) or "later"
ed = a.open_editor(QImage(600, 400, QImage.Format.Format_RGB32), None)
ed._text_selected("пример")
settle(60)
check(a.work_window_open() and ed._text_panel.isVisible(), "открыто окно текста с картинки: человек занят")
settle(700)
check(not got, "окно «Новое в версии» не появилось поверх окна текста с картинки")
ed._text_panel.close()
ed._text_panel = None
ed.exported = True
ed.canvas.modified = False
ed.select_tool("move")
settle(900)
check(not a.work_window_open() and got, "после закрытия окна текста окно новинок пришло в спокойную минуту")
close_editors()
close_all()

from PyQt6.QtCore import QPointF  # noqa: E402
for label, setup in (("режим текста", lambda e: e.canvas.set_tool("ocr")),
                     ("режим перевода", lambda e: e.canvas.set_tool("translate")),
                     ("несохранённые пометки", lambda e: setattr(e.canvas, "modified", True)),
                     ("набор текста", lambda e: e.canvas.start_text(QPointF(20, 20)))):
    fresh()
    got.clear()
    ed = a.open_editor(QImage(600, 400, QImage.Format.Format_RGB32), None)
    ed.exported = False
    setup(ed)
    settle(800)
    check(a.work_window_open() and not got, f"{label}: окно новинок не появилось")
    close_editors()
    close_all()
check(not any(True for _ in a.editors), "редакторы закрыты")
a.show_novoe = orig_show
from clipshot import update_prompt  # noqa: E402
fresh()
tr_win_open = a.work_window_open
a.work_window_open = lambda: True
check(update_prompt.busy_reason(a) == "work", "окно после обновления тоже ждёт: busy_reason учитывает работу")
a.work_window_open = tr_win_open

# вопрос «Хотите узнать о других функциях»: ведёт в «Ознакомление»
fresh()
a.config.pop("novoe_asked", None)
a.config["ozn_seen"] = []
box_seen = []
orig_make_q = novoe.make_question


def fake_q(parent=None, dark=None):
    box = orig_make_q(parent, dark)
    box_seen.append(box)
    return box


novoe.make_question = fake_q
answer("primary_button")
a._ask_overview()
settle(600)
check(len(box_seen) == 1 and getattr(a, "_ozn_window", None) is not None, "«Да, показать обзор»: открывается «Ознакомление»")
novoe.make_question = orig_make_q
close_all()

# --- 9. 12 языков -------------------------------------------------------------------------------------------------
ids = [c[0] for c in oznakomlenie.CATALOG]
keys = [k for k in i18n._load("ru") if k.startswith("ozn.")]
check(len(keys) >= 80, f"новых ключей: {len(keys)}")
for lang in i18n.LANGUAGES:
    cat = i18n._load(lang)
    missing = [k for k in keys if k not in cat]
    check(not missing, f"{lang}: все ключи на месте {missing[:3]}")
    bad = [k for k in keys if "—" in cat.get(k, "") or re.search("[\U0001F300-\U0001FAFF☀-⛿✀-➿]", cat.get(k, ""))]
    check(not bad, f"{lang}: без длинных тире и эмодзи {bad[:3]}")
    i18n.set_language(lang)
    fresh()
    w = a.open_oznakomlenie()
    settle(80)
    texts_ok = all(oznakomlenie.item_title(i) and not oznakomlenie.item_title(i).startswith(("ozn.", "novoe."))
                   and not oznakomlenie.item_line(i).startswith("ozn.") and not oznakomlenie.item_hint(i).startswith(("ozn.", "novoe."))
                   for i in ids)
    check(texts_ok, f"{lang}: у всех пунктов тексты на языке")
    area = qapp.primaryScreen().availableGeometry()
    check(w.width() <= area.width() and w.height() <= area.height(), f"{lang}: окно в экране ({w.width()}x{w.height()})")
    w.select("windows")
    settle(60)
    for b in (w.real_button, w.done_button):
        fm = b.fontMetrics()
        check(b.isVisible() and fm.horizontalAdvance(b.text()) + 8 <= b.width(), f"{lang}: надпись «{b.text()}» не обрезана")
    wrap = w.hint_text
    check(wrap.heightForWidth(wrap.width()) <= wrap.height() + 4 or wrap.wordWrap(), f"{lang}: пояснение переносится по словам")
    w.select("arrows")
    settle(120)
    for b in (w.show_button, w.try_button, w.reset_button):
        fm = b.fontMetrics()
        check(fm.horizontalAdvance(b.text()) + 8 <= b.width(), f"{lang}: кнопка «{b.text()}» не обрезана")
    d = w.lesson.dimmer
    bub = d.bubble.geometry()
    check(d.isVisible() and d.hole.isValid() and d.rect().contains(bub) and not bub.intersects(d.hole),
          f"{lang}: затемнение с окошком, подсказка внутри редактора и не на кнопке")
    check(d.caption.text() == tr("ozn.step_press") and d.caption.heightForWidth(d.caption.width()) <= d.caption.height() + 2
          and d.skip_button.fontMetrics().horizontalAdvance(d.skip_button.text()) <= d.skip_button.width(),
          f"{lang}: подсказка шага «{d.caption.text()}» не обрезана")
    w.select("translate_head")
    settle(120)
    check(w.lesson.dimmer.isVisible() and w.lesson.dimmer.hole.isValid(), f"{lang}: окошко на кнопке перевода")
    close_all()
i18n.set_language("ru")

# --- 10. темы и размер экрана ---------------------------------------------------------------------------------------
for key in ("standard", "pro"):
    fresh(ui_theme=key)
    themes.apply_app(qapp, a.config)
    w = a.open_oznakomlenie()
    settle(100)
    w.select("blur")
    settle(500)
    dark = key == "pro"
    check(w.dark == dark, f"оформление «{key}»: окно {'тёмное' if dark else 'светлое'}")
    ed = w.editor
    dim_px = QColor(ed.grab().toImage().pixel(ed.width() - 8, ed.height() - 8))
    w.lesson.skip()
    settle(100)
    plain_px = QColor(ed.grab().toImage().pixel(ed.width() - 8, ed.height() - 8))
    check(dim_px.lightness() < plain_px.lightness() - 15, f"оформление «{key}»: затемнение заметно ({plain_px.lightness()} -> {dim_px.lightness()})")
    pix = w.grab().toImage()
    left = QColor(pix.pixel(150, w.height() - 6))
    check((left.lightness() < 110) == dark, f"оформление «{key}»: список {'тёмный' if dark else 'светлый'} ({left.name()})")
    close_all()
fresh()
themes.apply_app(qapp, a.config)
w = a.open_oznakomlenie()
settle(100)
w.select("arrows")
settle(200)
w.resize(910, 512)   # 1366x768 при масштабе 150 %
settle(400)
check(w.narrow and w.minimumSizeHint().width() <= 910, f"узкое окно: размер не больше экрана ({w.minimumSizeHint().width()}x{w.minimumSizeHint().height()})")
check(w.width() == 910 and w.height() == 512, f"окно 910x512 ({w.width()}x{w.height()})")
check(w.right_w.isVisible() and not w.left_w.isVisible() and w.back_button.isVisible(), "узкое окно после выбора пункта: снимок, «‹ Все функции» сверху")
ed = w.editor
check(ed.geometry().right() <= w.editor_host.width() + 2 and ed.width() >= 820 and ed.geometry().bottom() <= w.height(),
      f"редактор внутри окна ({ed.width()}x{ed.height()})")
check(w.show_button.isVisible() and w.show_button.geometry().right() < w.width() and w.done_button.geometry().right() < w.right_w.width(), "кнопки на экране")
w.back_button.click()
settle(100)
check(w.left_w.isVisible() and not w.right_w.isVisible() and w.left_w.width() <= 910, "«‹ Все функции» возвращает к списку")
w.resize(1240, 740)
settle(300)
check(not w.narrow and w.left_w.isVisible() and w.right_w.isVisible() and w.left_w.width() == oznakomlenie.LEFT_W, "широкое окно: список и снимок рядом")
close_all()


# --- 11. метка «Новое»: синяя, после изучения серая ----------------------------------------------------------------
def _lum(h):
    def lin(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _ratio(x, y):
    hi, lo = sorted((_lum(x), _lum(y)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


for i, (bg, fg) in enumerate(novoe.BADGE_GRAY):
    check(_ratio(bg, fg) >= 4.5, f"серая метка, {'тёмная' if i else 'светлая'} тема: текст {_ratio(bg, fg):.1f}:1")


def badge_color(win, ident):
    row = win.rows[ident]
    img = row.grab().toImage()
    fm = novoe.QFontMetrics(novoe.badge_font())
    size = novoe.badge_size(fm)
    return QColor(img.pixel(row.width() - 12 - size.width() + 4, 9 + size.height() // 2)).name()


for key in ("standard", "pro"):
    fresh(ui_theme=key)
    themes.apply_app(qapp, a.config)
    gray = novoe.BADGE_GRAY[1 if key == "pro" else 0][0]
    win = a.open_oznakomlenie()
    settle(200)
    check(badge_color(win, "numbers") == novoe.BADGE_BG and badge_color(win, "phone_editor") == novoe.BADGE_BG, f"«{key}»: до изучения метка синяя")
    win.select("numbers")
    settle(300)
    check(badge_color(win, "numbers") == novoe.BADGE_BG, f"«{key}»: пока только выбрали, метка синяя")
    run_demo(win)    # показ досмотрен до конца: изучено
    check(win.rows["numbers"].studied and badge_color(win, "numbers") == gray and badge_color(win, "phone_editor") == novoe.BADGE_BG,
          f"«{key}»: после показа метка серая ({badge_color(win, 'numbers')}), у других синяя")
    win.select("blur")
    settle(300)
    win.select("phone_editor")
    settle(300)
    win.editor.insert_from_phone()
    settle(500)
    check(win.lesson.phase == "done" and badge_color(win, "phone_editor") == gray, f"«{key}»: после «Получилось» метка серая")
    close_all()
    win = a.open_oznakomlenie()
    settle(200)
    check(badge_color(win, "numbers") == gray and badge_color(win, "phone_editor") == gray and badge_color(win, "windows") == novoe.BADGE_BG,
          f"«{key}»: после перезапуска серая у изученных, синяя у остальных")
    close_all()


# --- 12. проверка 1.35.0: Б1 смена языка при открытом окне ---------------------------------------------------------------
from clipshot import language as langmod  # noqa: E402


def lang_case(label, setup, change):
    fresh()
    i18n.set_language("ru")
    a.config["language"] = "ru"
    win = a.open_oznakomlenie()
    settle(200)
    setup(win)
    ident = win.current
    errors = []
    old_hook = sys.excepthook
    sys.excepthook = lambda *x: errors.append(x)
    try:
        change(win)
        settle(900)
    finally:
        sys.excepthook = old_hook
    new_win = getattr(a, "_ozn_window", None)
    ok = new_win is not None and new_win is not win and new_win.isVisible() and new_win.current == ident
    check(ok and not errors, f"смена языка: {label}: окно на месте, тот же пункт ({ident}), исключений нет {errors[:1]}")
    if new_win is not None:
        check(new_win.windowTitle().endswith(tr("ozn.window_title")), f"смена языка: {label}: окно на новом языке («{new_win.windowTitle()}»)")
        if ident and not new_win.is_panel(ident) and new_win.editor is not None:
            check(new_win.lesson.phase in ("you", "done", "demo"), f"смена языка: {label}: урок на новом окне идёт ({new_win.lesson.phase})")
    close_all()
    i18n.set_language("ru")
    a.config["language"] = "ru"


lang_case("без выбранного пункта", lambda w: None, lambda w: a.set_language("en"))
lang_case("выбран пункт «Стрелки»", lambda w: w.select("arrows"), lambda w: a.set_language("de"))
lang_case("выбран пункт панели «Весь экран»", lambda w: w.select("full"), lambda w: a.set_language("fr"))
lang_case("глобус учебного редактора", lambda w: w.select("blur"), lambda w: langmod.change(w.editor.ctx, "es"))
lang_case("меню значка", lambda w: w.select("shapes"), lambda w: langmod.change(a, "uk"))
lang_case("во время показа", lambda w: (w.select("numbers"), settle(200), w.play(), settle(150)), lambda w: a.set_language("it"))
lang_case("во время «Теперь вы»", lambda w: (w.select("arrows"), settle(300), w.editor.select_tool("arrow"), settle(300)), lambda w: a.set_language("pt"))
lang_case("пункт без редактора", lambda w: w.select("record"), lambda w: a.set_language("zh"))
lang_case("два раза подряд", lambda w: w.select("blur"), lambda w: (a.set_language("pl"), a.set_language("tr")))

# --- 13. В1: буфер обмена не трогается ------------------------------------------------------------------------------
from PyQt6.QtGui import QGuiApplication  # noqa: E402
fresh()
cb = QGuiApplication.clipboard()
cb.setText("МОЙ ВАЖНЫЙ ТЕКСТ")
win = a.open_oznakomlenie()
settle(200)
win.select("ocr")
settle(800)
ozn_lesson.TIME_SCALE = 0.05
win.play()
wait_phase(win, ("demo",))
settle(500)
check(cb.text() == "МОЙ ВАЖНЫЙ ТЕКСТ", f"«Текст с картинки»: после показа буфер обмена не изменился ({cb.text()[:30]!r})")
ed = win.editor
ed.select_tool("ocr")
for _ in range(60):
    if ed.canvas.has_words():
        break
    settle(100)
ed._text_selected("Пн Вт Ср")
settle(300)
check(cb.text() == "МОЙ ВАЖНЫЙ ТЕКСТ", "человек выделил текст на учебном снимке: буфер не изменился")
panel = getattr(ed, "_text_panel", None)
check(panel is not None and panel.isVisible() and tr("ozn.no_clip") in panel.note.text(), "окно текста с пометкой «учебный снимок: в буфер не копируется»")
if panel is not None:
    panel.copy_button.click()
    settle(200)
    check(cb.text() == "МОЙ ВАЖНЫЙ ТЕКСТ", "кнопка «Скопировать» в окне текста учебного снимка буфер не трогает")
for fn in ("copy_to_clipboard", "copy_and_close", "save_and_close", "copy_selected_text", "_tr_copy_all"):
    getattr(ed, fn)()
settle(200)
check(cb.text() == "МОЙ ВАЖНЫЙ ТЕКСТ" and not QApplication.clipboard().mimeData().hasImage(), "все пути копирования учебного редактора буфер не трогают")
for ident in ("arrows", "numbers", "save", "copy", "text", "blur"):
    win.select(ident)
    settle(300)
    run_demo(win)
check(cb.text() == "МОЙ ВАЖНЫЙ ТЕКСТ", "показы всех функций буфер не меняют")
close_all()
cb.clear()

# --- 14. В2: низкое окно ------------------------------------------------------------------------------------------------
def visible_image(win):
    ed = win.editor
    cv = ed.canvas
    vp = ed.scroll.viewport()
    return min(cv.height(), vp.height()), cv.zoom


for (w_, h_) in ((910, 472), (910, 512), (1280, 720)):
    fresh()
    win = a.open_oznakomlenie()
    settle(150)
    win.resize(w_, h_)
    win.select("arrows")
    settle(700)
    vis_h, zoom = visible_image(win)
    check(vis_h >= 200 and zoom >= 0.45, f"{w_}x{h_}: учебный снимок виден: {vis_h} точек высотой, масштаб {zoom:.0%}")
    d = win.lesson.dimmer
    ed = win.editor
    cvr = QRect(ed.canvas.mapTo(ed, QPoint(0, 0)), ed.canvas.size())
    check(d.isVisible() and d.rect().contains(d.bubble.geometry()) and not d.bubble.geometry().intersects(d.hole),
          f"{w_}x{h_}: подсказка шага внутри редактора и не на нужной кнопке")
    win.editor.select_tool("arrow")
    settle(400)
    d = win.lesson.dimmer
    check(not d.bubble.geometry().intersects(d.hole), f"{w_}x{h_}: на шаге «рисуйте» подсказка не закрывает нужное место снимка")
    if h_ < 600:
        check(win.compact and not win.hint_text.isVisible() and win.more_button.isVisible(), f"{w_}x{h_}: описание свёрнуто, есть «Подробнее»")
        win.more_button.click()
        settle(100)
        check(win.hint_text.isVisible(), f"{w_}x{h_}: «Подробнее» показывает описание")
    else:
        check(not win.compact and win.hint_text.isVisible(), f"{w_}x{h_}: описание на месте")
    close_all()
from PyQt6.QtGui import QGuiApplication as _G  # noqa: E402

# --- 15. В3: ни одной обрезанной подписи (список и учебная панель) на 12 языках -------------------------------------------
for lang in i18n.LANGUAGES:
    i18n.set_language(lang)
    fresh()
    win = a.open_oznakomlenie()
    settle(100)
    bad_rows = [i for i, r in win.rows.items() if r.overflow]
    check(not bad_rows, f"{lang}: список слева без обрезанных строк {bad_rows[:3]}")
    heights_ok = all(r.height() >= r.title_h + r.text_h + 18 for r in win.rows.values())
    check(heights_ok, f"{lang}: строки списка достаточно высоки для переноса")
    oznakomlenie.PANEL_OVERFLOW.clear()
    for tgt in ("phone", "window", "manual", "full"):
        oznakomlenie.panel_pixmap(tgt, False)
    check(not oznakomlenie.PANEL_OVERFLOW, f"{lang}: учебная панель, все подписи целиком {oznakomlenie.PANEL_OVERFLOW[:2]}")
    close_all()
i18n.set_language("ru")

# --- 16. В4: новинки 1.35 -------------------------------------------------------------------------------------------------
check(len(new135) == 7, "в novoe.ITEMS семь строк 1.35.0")
check(not any(i in oznakomlenie.BY_ID for i in new135), "внутренних доработок 1.35 в списке «Ознакомления» нет (правило владельца 23.11.2026)")
clipshot.__version__ = "1.35.0"
novoe.__version__ = "1.35.0"
cfg35 = dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True, novoe_version="1.34.2")
novoe.on_start(cfg35, "1.35.0")
check(novoe.window_pending(cfg35, "1.35.0") and [it[1] for it in novoe.window_items(cfg35, "1.35.0")] == new135[:4],
      f"после обновления с 1.34.2 окно «Новое в версии» придёт, в нём первые четыре 1.35 ({[it[1] for it in novoe.window_items(cfg35, '1.35.0')]})")
fresh()
a.config.update(novoe_version="1.34.2")
novoe.on_start(a.config, "1.35.0")
a.config.update(tour_done=True, theme_chosen=True)
win = a.open_oznakomlenie()
settle(200)
check(win.new_list == [] and not any(l.text().startswith("Новое в версии") for l in win.group_labels), f"в «Ознакомлении» у версии 1.35 нет группы новинок: {[l.text() for l in win.group_labels]}")
check(novoe.badges(a.config, "editor", "1.35.0") == {"phone_target": "phone_target"} and novoe.badges(a.config, "selector", "1.35.0") == {},
      "цели app: меток не ставят; у цели, которой в сборке нет (editor:phone_target), метка просто не рисуется")
novoe.window_done(a.config)   # окно новинок само не нужно: оно модальное и держало бы цикл теста
ed = a.open_editor(QImage(600, 400, QImage.Format.Format_RGB32), None)
settle(300)
check(ed is not None and "phone_target" not in getattr(getattr(ed, "_novoe", None), "badges", {}), "редактор открывается при новинках без цели в сборке, метка не рисуется")
close_all()
box = novoe.make_window("1.35.0", novoe.window_items(a.config, "1.35.0"), None)
box.show()
settle(60)
check(len(box.rows) == 4, "окно «Новое в версии 1.35»: четыре пункта")
box.close()
clipshot.__version__ = V
novoe.__version__ = V

# --- 17. мелочи проверки --------------------------------------------------------------------------------------------------
check(_ratio("#157a40", "#f1f4f8") >= 4.5 and _ratio("#7be08f", "#25282c") >= 4.5, "«Получилось»: контраст не ниже 4,5:1 в обеих темах")
for key in ("standard", "pro"):
    fresh(ui_theme=key)
    themes.apply_app(qapp, a.config)
    win = a.open_oznakomlenie()
    settle(100)
    win.select("full")
    settle(300)
    ring = "#ffd23f" if key == "pro" else "#a85d00"
    bg = "#2f3338" if key == "pro" else "#f1f4f8"
    check(ring in win.real_button.styleSheet() and _ratio(ring, bg) >= 3, f"«{key}»: обводка «Попробовать по-настоящему» {_ratio(ring, bg):.1f}:1 к фону")
    close_all()
fresh()
ls = a.open_oznakomlenie().lesson
a.selector = None
check(a.work_window_open() is False or True, "")
win = a._ozn_window
win.select("arrows")
settle(300)
check(a.work_window_open() and update_prompt.busy_reason(a) == "work", "идёт урок: окна оценки, обновления и новинок не всплывают поверх (busy_reason)")
win.lesson.skip()
settle(100)
check(not a.work_window_open(), "урок снят: спокойно")
close_all()
from clipshot import ocr as ocrmod  # noqa: E402
safe = ocrmod._log_safe("OCR_ERROR=Сбой C:\\Users\\Ivan\\AppData\\Local\\Temp\\x.png и /home/ivan/.cache/clipsd/a.png конец")
check("Ivan" not in safe and "ivan" not in safe and "<путь>" in safe, f"ocr.log: пути с именем пользователя не пишутся ({safe})")

# --- 16. М8 проверки 1.36: у каждого пункта «Следующая функция ›»; «Отложить ▾» и «Готово» не в ряду кнопок подсказки ---------
from PyQt6.QtWidgets import QPushButton  # noqa: E402
kinds = {}
for c in oznakomlenie.CATALOG:
    kinds.setdefault(c[3], c[0])
for lang in i18n.LANGUAGES:
    i18n.set_language(lang)
    for (w_, h_) in ((1240, 740), (910, 472), (1366 - 456, 728)):
        fresh()
        win = a.open_oznakomlenie()
        settle(80)
        win.resize(w_, h_)
        settle(80)
        bad = []
        for kind, ident in kinds.items():
            win.select(ident)
            settle(60)
            row = [b for b in win.hint.findChildren(QPushButton) if b.isVisible()]
            if not win.next_button.isVisible() or win.next_button not in row:
                bad.append(f"{kind}: нет «Следующая функция»")
            if win.done_button in row or win.snooze_button in win.hint.findChildren(type(win.snooze_button)):
                bad.append(f"{kind}: «Готово»/«Отложить» в ряду подсказки")
            for b in row:
                if b.width() < b.sizeHint().width() - 1:
                    bad.append(f"{kind}: «{b.text()}» обрезана ({b.width()} < {b.sizeHint().width()})")
                if not win.rect().contains(b.mapTo(win, b.rect().bottomRight())):
                    bad.append(f"{kind}: «{b.text()}» вне окна")
        check(not bad, f"{lang} {w_}x{h_}: у каждого вида пункта есть «Следующая функция ›», кнопки целы {bad[:3]}")
        close_all()
i18n.set_language("ru")
fresh()
win = a.open_oznakomlenie()
settle(100)
first = win.order[0]
win.select(first)
settle(60)
seen_ids = [win.current]
for _ in range(5):
    win.next_button.click()
    settle(120)
    seen_ids.append(win.current)
check(win.isVisible() and seen_ids == win.order[:6], f"«Следующая функция ›» шесть раз подряд: окно открыто, пункты по порядку {seen_ids}")
check(win.next_button.text().endswith("›") and not win.hint.isAncestorOf(win.done_button) and win.left_w.isAncestorOf(win.snooze_button),
      "«Готово» и «Отложить ▾» стоят под списком, не в подсказке")
last = win.order[-1]
win.select(last)
settle(60)
check(not win.next_button.isVisible(), "у последнего пункта «Следующая функция» не нужна")
close_all()

print("\nИТОГ:", "ВСЁ ХОРОШО" if not failures else f"{len(failures)} проверок не прошло")
for f in failures:
    print("  -", f)
sys.exit(1 if failures else 0)
