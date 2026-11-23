# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""«Отложить ▾» (слова владельца 22.11.2026): кнопка с меню времени в окнах-помощниках, которые приходят сами.

Проверяется на подставных часах (otlozhit.now): каждый пункт меню ставит верное время; окно возвращается после срока и
не раньше; время переживает перезапуск (настоящая запись и чтение настроек); окно не всплывает поверх рабочего окна;
«До завтра» через полночь; три откладывания подряд дают неделю; знакомство, «Ознакомление» и вопрос про другие функции
откладываются так же; на 12 языках подписи не обрезаются; меню не выходит за экран.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/otlozhit_test.py
"""
import tmpclean  # noqa: F401
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta

here = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(here)
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp(prefix="clipsd-otl-")
for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[name] = os.path.join(tmp, name)
_screen = os.path.join(tmp, "screen.json")
with open(_screen, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1600, "height": 1000,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _screen
os.environ.pop("CLIPSD_LANG", None)

from PyQt6.QtCore import QTimer  # noqa: E402
from PyQt6.QtGui import QColor, QFontMetrics, QGuiApplication, QImage  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

qapp = QApplication(sys.argv)
qapp.setQuitOnLastWindowClosed(False)

import clipshot  # noqa: E402
from clipshot import app as appmod, i18n, novoe, otlozhit, oznakomlenie  # noqa: E402

V = "1.34.0"
clipshot.__version__ = V
novoe.__version__ = V
i18n.set_language("ru")
failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


def settle(ms=30):
    for _ in range(3):
        qapp.processEvents()
        QTest.qWait(ms // 3 or 1)


# --- подставные часы ----------------------------------------------------------------------------------------------
T0 = datetime(2026, 11, 24, 14, 30).timestamp()   # вторник 14:30
clock = [T0]
otlozhit.now = lambda: clock[0]
MIN, HOUR, DAY = 60, 3600, 86400

# --- 1. каждый пункт меню ставит верное время ---------------------------------------------------------------------
tomorrow9 = datetime(2026, 11, 25, 9, 0).timestamp()
expect = {"15m": T0 + 15 * MIN, "1h": T0 + HOUR, "3h": T0 + 3 * HOUR, "tomorrow": tomorrow9, "week": T0 + 7 * DAY}
btn = otlozhit.SnoozeButton(False)
got = []
btn.chosen.connect(got.append)
check([c[0] for c in otlozhit.CHOICES] == ["15m", "1h", "3h", "tomorrow", "week"], "в меню пять пунктов по порядку владельца")
check([a.text() for a in btn.menu.actions()] == ["На 15 минут", "На 1 час", "На 3 часа", "До завтра", "На неделю"],
      f"подписи меню {[a.text() for a in btn.menu.actions()]}")
for key, want in expect.items():
    cfg = {}
    got.clear()
    btn.actions_by_key[key].trigger()
    check(got == [key], f"пункт «{key}» отдаёт свой код ({got})")
    until = otlozhit.snooze(cfg, "novoe", got[0])
    check(abs(until - want) < 1 and otlozhit.is_snoozed(cfg, "novoe"), f"«{key}»: время {datetime.fromtimestamp(until)}")
got.clear()
btn.click()
check(got == ["1h"], "основная часть кнопки: время по умолчанию, 1 час")
check(otlozhit.DEFAULT == "1h", "по умолчанию 1 час")

# долгое нажатие открывает меню и ничего не откладывает
got.clear()
QTest.mousePress(btn.main, __import__("PyQt6.QtCore", fromlist=["Qt"]).Qt.MouseButton.LeftButton)
QTest.qWait(otlozhit.LONG_PRESS_MS + 150)
opened = btn.menu.isVisible()
btn.menu.close()
QTest.mouseRelease(btn.main, __import__("PyQt6.QtCore", fromlist=["Qt"]).Qt.MouseButton.LeftButton)
settle(60)
check(opened and got == [], f"долгое нажатие: меню открылось ({opened}), время не выбрано ({got})")
btn.arrow.click()
check(btn.menu.isVisible(), "стрелка открывает меню")
btn.menu.close()

# --- 2. «До завтра» через полночь, три откладывания -------------------------------------------------------------
late = datetime(2026, 11, 24, 23, 50).timestamp()
check(abs(otlozhit.until_for("tomorrow", late) - datetime(2026, 11, 25, 9, 0).timestamp()) < 1, "23:50: до завтра = следующий день 9:00")
after = datetime(2026, 11, 25, 0, 10).timestamp()
check(abs(otlozhit.until_for("tomorrow", after) - datetime(2026, 11, 26, 9, 0).timestamp()) < 1, "00:10 после полуночи: до завтра = ещё через сутки, 9:00")
early = datetime(2026, 11, 24, 8, 0).timestamp()
check(abs(otlozhit.until_for("tomorrow", early) - datetime(2026, 11, 25, 9, 0).timestamp()) < 1, "08:00: до завтра = завтра 9:00")
month = datetime(2026, 11, 30, 22, 0).timestamp()
check(abs(otlozhit.until_for("tomorrow", month) - datetime(2026, 12, 1, 9, 0).timestamp()) < 1, "конец месяца: завтра 1 декабря 9:00")
cfg = {}
otlozhit.snooze(cfg, "novoe", "tomorrow", late)
clock[0] = datetime(2026, 11, 25, 8, 59).timestamp()
check(otlozhit.is_snoozed(cfg, "novoe") and not otlozhit.is_due(cfg, "novoe"), "08:59 следующего дня: ещё ждём")
clock[0] = datetime(2026, 11, 25, 9, 0, 1).timestamp()
check(otlozhit.is_due(cfg, "novoe") and not otlozhit.is_snoozed(cfg, "novoe"), "09:00 следующего дня: срок вышел")
clock[0] = T0

cfg = {}
u1 = otlozhit.snooze(cfg, "novoe", "15m")
u2 = otlozhit.snooze(cfg, "novoe", "15m")
check(abs(u1 - (T0 + 15 * MIN)) < 1 and abs(u2 - (T0 + 15 * MIN)) < 1, "первые два откладывания: как выбрано")
u3 = otlozhit.snooze(cfg, "novoe", "15m")
check(u3 >= T0 + 7 * DAY - 1, f"третье откладывание подряд: не раньше чем через неделю ({(u3 - T0) / DAY:.1f} суток)")
u4 = otlozhit.snooze(cfg, "novoe", "15m")
check(abs(u4 - (T0 + 15 * MIN)) < 1, "после недели счёт начинается заново")
otlozhit.clear(cfg, "novoe")
check(otlozhit.until(cfg, "novoe") is None and not otlozhit.is_snoozed(cfg, "novoe"), "«Показать новое» и подобное: откладывания забываются")
cfg = {}
otlozhit.snooze(cfg, "novoe", "week")
clock[0] = T0 - 30 * DAY   # часы переведены сильно назад: срок не держит окно
check(not otlozhit.is_snoozed(cfg, "novoe") and otlozhit.is_due(cfg, "novoe"), "часы переведены назад больше чем на неделю: окно не ждёт вечно")
clock[0] = T0

# --- 3. приложение ---------------------------------------------------------------------------------------------
appmod.is_wayland = lambda: False
a = appmod.Clipshot(qapp)
a.notify = lambda *_x: None


def fresh(**kw):
    a.config.clear()
    a.config.update(dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True, tour_selector_done=True))
    novoe.on_start(a.config)
    a.config.update(kw)


def image(w=900, h=500):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor("#ffffff"))
    return img


def close_all():
    ozn = getattr(a, "_ozn_window", None)
    if ozn is not None:
        novoe.ask_done(a.config)   # закрытие окна не должно породить вопрос про обзор (он бы встал модально)
        ozn.close()
        settle(450)
    for ed in list(a.editors):
        ed.canvas.modified = False
        ed.close()
    settle(60)


def answer_modal(fn, timeout_ms=4000):
    """Когда появится модальное окно, передать его fn (нажать кнопку или пункт меню)."""
    state = {"left": timeout_ms // 30, "w": None}

    def go():
        w = QApplication.activeModalWidget()
        if w is None:
            state["left"] -= 1
            if state["left"] > 0:
                QTimer.singleShot(30, go)
            return
        state["w"] = w
        fn(w)
    QTimer.singleShot(30, go)
    return state


# 3a. окно «Новое в версии»: пункт меню окна ставит верное время, окно открыто из меню значка тоже
for key, want_delta in (("15m", 15 * MIN), ("1h", HOUR), ("3h", 3 * HOUR), ("week", 7 * DAY)):
    fresh()
    clock[0] = T0
    st = answer_modal(lambda w, k=key: w.later_button.actions_by_key[k].trigger())
    choice = a.show_novoe(None, auto=False)   # из меню значка
    until = otlozhit.until(a.config, "novoe")
    check(choice == "snooze" and until is not None and abs(until - (T0 + want_delta)) < 1,
          f"окно «Новое» из меню значка, пункт «{key}»: срок {until and (until - T0) / MIN:.0f} мин")
fresh()
st = answer_modal(lambda w: w.later_button.actions_by_key["tomorrow"].trigger())
a.show_novoe(None, auto=True)
check(abs(otlozhit.until(a.config, "novoe") - tomorrow9) < 1, "«До завтра» в окне новинок: завтра 9:00")
fresh()
st = answer_modal(lambda w: w.later_button.click())
a.show_novoe(None, auto=True)
check(abs(otlozhit.until(a.config, "novoe") - (T0 + HOUR)) < 1, "основная часть кнопки в окне: 1 час")
fresh()
st = answer_modal(lambda w: w.close_b.click())
a.show_novoe(None, auto=True)
check(otlozhit.is_snoozed(a.config, "novoe"), "крестик у окна, пришедшего само: как «Отложить» на час")
check(not novoe.window_pending(a.config), "пока срок не вышел, окно новинок не ждёт первого редактора")

# 3b. возвращается после срока и не раньше
fresh()
calls = []
a.show_novoe = lambda *x, **k: calls.append((x, k)) or "show"
otlozhit.snooze(a.config, "novoe", "15m")
a.schedule_otlozhit()
check(a._otl_timer.isActive(), "таймер возврата запущен")
check(abs(a._otl_timer.interval() - 15 * MIN * 1000) < 2000, f"таймер на 15 минут ({a._otl_timer.interval() / 1000:.0f} с)")
clock[0] = T0 + 14 * MIN + 59
a._otlozhit_tick()
check(not calls, "за секунду до срока окно не приходит")
clock[0] = T0 + 15 * MIN + 1
a._otlozhit_tick()
check(len(calls) == 1 and calls[0][1].get("auto") is True, "после срока окно приходит само")
del a.show_novoe
clock[0] = T0

# 3c. не всплывает поверх рабочего окна
fresh()
calls.clear()
a.show_novoe = lambda *x, **k: calls.append(1) or "show"
otlozhit.snooze(a.config, "novoe", "15m")
clock[0] = T0 + 16 * MIN
ed = a.open_editor(image(), None)
settle(80)
ed.canvas.modified = True   # несохранённые пометки: человек работает
check(a.work_window_open(), "несохранённый снимок: рабочее окно открыто")
a._otlozhit_tick()
check(not calls and a._otl_timer.isActive(), "поверх несохранённого снимка окно не приходит, ждёт спокойной минуты")
ed.canvas.modified = False
ed.exported = True
a._otlozhit_tick()
check(len(calls) == 1, "снимок сохранён: окно пришло")
clock[0] = T0
for blocker, label in ((lambda: setattr(a, "selector", object()), "окно выделения"),):
    fresh()
    calls.clear()
    otlozhit.snooze(a.config, "novoe", "15m")
    clock[0] = T0 + 16 * MIN
    blocker()
    a._otlozhit_tick()
    check(not calls, f"поверх окна «{label}» окно не приходит")
    a.selector = None
    a._otlozhit_tick()
    check(len(calls) == 1, f"«{label}» закрыто: окно пришло")
clock[0] = T0
fresh()
calls.clear()
otlozhit.snooze(a.config, "novoe", "15m")
clock[0] = T0 + 16 * MIN
a.work_window_open = lambda: True   # окно текста с картинки, перевод
a._otlozhit_tick()
check(not calls, "окно текста или перевода открыто: окно не приходит")
del a.work_window_open
a._otlozhit_tick()
check(len(calls) == 1, "спокойная минута: окно пришло")
del a.show_novoe
clock[0] = T0
close_all()

# 3d. переживает перезапуск: настоящая запись и чтение настроек
fresh()
otlozhit.snooze(a.config, "novoe", "3h")
otlozhit.snooze(a.config, "ask", "tomorrow")
a.save_config()
loaded = appmod.load_config()
check(abs(otlozhit.until(loaded, "novoe") - (T0 + 3 * HOUR)) < 1 and abs(otlozhit.until(loaded, "ask") - tomorrow9) < 1,
      "после записи и чтения настроек сроки на месте")
clock[0] = T0 + HOUR
check(otlozhit.is_snoozed(loaded, "novoe") and not otlozhit.is_due(loaded, "novoe"), "перезапуск через час: «3 часа» ещё не вышли")
clock[0] = T0 + 4 * HOUR   # программу запустили после срока
a.config.clear()
a.config.update(loaded)
calls = []
a.show_novoe = lambda *x, **k: calls.append(1) or "show"
a.schedule_otlozhit()
check(a._otl_timer.isActive() and a._otl_timer.interval() <= 300, "запуск после срока: окно придёт сразу, как будет спокойно")
a._otlozhit_tick()
check(len(calls) == 1, "первый запуск после срока: окно пришло")
del a.show_novoe
clock[0] = T0

# 3e. три откладывания в окне подряд: неделя, а «Что нового» в меню значка открывает всегда
fresh()
for i in range(3):
    answer_modal(lambda w: w.later_button.actions_by_key["15m"].trigger())
    a.show_novoe(None, auto=(i > 0))
check(otlozhit.until(a.config, "novoe") >= T0 + 7 * DAY - 1, "три откладывания подряд: окно не раньше чем через неделю")
check(not novoe.window_pending(a.config), "в течение недели окно само не ждёт редактора")
shown_ = []
answer_modal(lambda w: (shown_.append(w.title.text()), w.show_button.click()))
close_after = a.show_novoe(None)
settle(80)
check(shown_ and close_after == "show", "пункт «Что нового» в меню значка открывает окно в любой момент")
settle(450)   # «Показать новое» открывает «Ознакомление» через 200 мс
close_all()
settle(450)

# 3f. «Хотите узнать о других функциях?»: Отложить
fresh()
novoe_seen = []
answer_modal(lambda w: (novoe_seen.append(w.snooze_button is not None), w.snooze_button.actions_by_key["1h"].trigger()))
a._ask_overview()
check(novoe_seen == [True], "в вопросе есть «Отложить ▾»")
check(abs(otlozhit.until(a.config, "ask") - (T0 + HOUR)) < 1 and a.config.get("novoe_asked") != V,
      "вопрос отложен на час, «до следующей версии не спрашивать» не записано")
calls = []
a._ask_overview = lambda *x, **k: calls.append(1)
clock[0] = T0 + HOUR + 5
a._otlozhit_tick()
check(len(calls) == 1, "через час вопрос возвращается")
del a._ask_overview
clock[0] = T0
fresh()
answer_modal(lambda w: w.secondary_button.click())
a._ask_overview()
check(a.config.get("novoe_asked") == V, "«Не сейчас» работает как раньше: до следующей версии")

# 3g. «Ознакомление»: Отложить останавливает показ, возвращается на той же функции, вопроса при этом нет
fresh()
win = a.open_oznakomlenie(focus_new=False)
settle(80)
win.select("arrows")
settle(150)
check(win.lesson is not None and win.current == "arrows", "в «Ознакомлении» идёт показ функции")
asked = []
real_ask = a._ask_overview
a._ask_overview = lambda *x, **k: asked.append(1)
win.snooze_button.actions_by_key["3h"].trigger()
settle(500)
check(getattr(a, "_ozn_window", None) is None, "«Отложить»: окно «Ознакомление» закрыто, показ остановлен")
check(otlozhit.is_snoozed(a.config, "ozn") and otlozhit.data(a.config, "ozn").get("id") == "arrows"
      and abs(otlozhit.until(a.config, "ozn") - (T0 + 3 * HOUR)) < 1, "срок и функция запомнены")
check(not asked, "отложенное «Ознакомление» не задаёт вопрос про другие функции")
clock[0] = T0 + 3 * HOUR + 1
a._otlozhit_tick()
settle(300)
win2 = getattr(a, "_ozn_window", None)
check(win2 is not None and win2.isVisible() and win2.current == "arrows", "после срока «Ознакомление» продолжается с той же функции")
check(otlozhit.until(a.config, "ozn") is None, "срок снят")
win2.close()
settle(500)
a._ask_overview = real_ask
a.config.pop("novoe_asked", None)
clock[0] = T0
close_all()

# 3h. первое знакомство в редакторе: Отложить, tour_done не ставится, возвращается с того же шага
fresh(tour_done=False)
a.config.pop("novoe_window", None)
ed = a.open_editor(image(), None)
settle(900)
tour = getattr(ed, "tour", None)
check(tour is not None and tour.snooze_button is not None, "первое знакомство: в карточке есть «Отложить ▾»")
tour.show_step(3)
settle(30)
tour.snooze_button.actions_by_key["3h"].trigger()
settle(50)
check(getattr(ed, "tour", None) is None and not a.config.get("tour_done"), "«Отложить»: знакомство закрыто, не считается пройденным")
check(otlozhit.data(a.config, "tour").get("step") == 3 and abs(otlozhit.until(a.config, "tour") - (T0 + 3 * HOUR)) < 1,
      "шаг и срок запомнены")
close_all()
ed = a.open_editor(image(), None)
settle(900)
check(getattr(ed, "tour", None) is None, "новый редактор до срока: знакомство не навязывается")
clock[0] = T0 + 3 * HOUR + 1
a._otlozhit_tick()
settle(80)
tour = getattr(ed, "tour", None)
check(tour is not None and tour.index == 3, f"после срока знакомство идёт с того же шага ({tour and tour.index})")
tour.finish()
settle(30)
check(a.config.get("tour_done") and otlozhit.until(a.config, "tour") is None, "знакомство пройдено: откладывания забыты")
clock[0] = T0
close_all()
fresh()
ed = a.open_editor(image(), None)
settle(100)
ed.start_tour()
check(ed.tour is not None and ed.tour.snooze_button is None, "повторное знакомство из меню (уже пройдено): «Отложить» не нужен")
ed.tour.finish()
close_all()

# 3i. знакомство с окном выделения: Отложить снимает отметку «показано», вернётся при выделении после срока
from clipshot.selector import RegionSelector  # noqa: E402


class FakeSel:
    pass


fs = FakeSel()
fs.tr_cfg = {"tour_selector_done": True}
saved = []
fs.tr_save = lambda: saved.append(1)
RegionSelector._tour_snoozed(fs, "tomorrow")
check(fs.tr_cfg["tour_selector_done"] is False and abs(otlozhit.until(fs.tr_cfg, "tour_selector") - tomorrow9) < 1 and saved,
      "окно выделения: «Отложить» до завтра, отметка «показано» снята")
check(otlozhit.is_snoozed(fs.tr_cfg, "tour_selector"), "до срока знакомство при выделении не придёт")

# 3j. предложение обновления не получило нового меню: у него своё «Позже» (3 дня или 20 снимков) и «Пропустить»
from clipshot import updater  # noqa: E402
src = open(os.path.join(ROOT, "clipshot", "updater.py"), encoding="utf-8").read()
check("SnoozeButton" not in src and "otlozhit" not in src, "окно обновления: «Позже»/«Пропустить эту версию» без изменений")

# --- 4. 12 языков: подписи не обрезаются -----------------------------------------------------------------------------
from clipshot.tour import Tour  # noqa: E402
fresh(tour_done=False)
ed = a.open_editor(image(), None)
settle(900)
for lang in i18n.LANGUAGES:
    i18n.set_language(lang)
    cat = i18n._load(lang)
    miss = [k for k in ("otl.button", "otl.more", "otl.tip", "otl.m15", "otl.h1", "otl.h3", "otl.tomorrow", "otl.week") if k not in cat]
    check(not miss, f"{lang}: строки на месте {miss}")
    for dark in (False, True):
        b = otlozhit.SnoozeButton(dark)
        b.show()
        settle(10)
        fm = QFontMetrics(b.main.font())
        need = fm.horizontalAdvance(b.main.text())
        check(need + 20 <= b.main.sizeHint().width() and b.width() >= b.main.sizeHint().width() + b.arrow.sizeHint().width() - 2,
              f"{lang} {'тёмная' if dark else 'светлая'}: кнопка «{b.main.text()}» не обрезана ({b.width()} px)")
        mfm = QFontMetrics(b.menu.font())
        widest = max(mfm.horizontalAdvance(x.text()) for x in b.menu.actions())
        check(b.menu.sizeHint().width() >= widest + 30, f"{lang}: пункты меню помещаются ({b.menu.sizeHint().width()} >= {widest})")
        b.close()
    # окно новинок и вопрос: ряд кнопок внутри карточки
    fresh()
    box = novoe.make_window(V, novoe.window_items(a.config), None, notes=True)
    box.show()
    settle(20)
    foot = box.footer_right.geometry()
    card_inner = box.card.rect().adjusted(24, 0, -20, 0)
    left_w = box.footer_left.sizeHint().width()
    row_need = box.later_button.sizeHint().width() + box.show_button.sizeHint().width() + 10 + left_w
    check(row_need <= card_inner.width() and box.later_button.width() >= box.later_button.sizeHint().width(),
          f"{lang}: окно «Новое»: ряд кнопок {row_need} <= {card_inner.width()}")
    box.close()
    q = novoe.make_question(None)
    q.show()
    settle(20)
    need = (q.snooze_button.sizeHint().width() + q.secondary_button.sizeHint().width()
            + q.primary_button.sizeHint().width() + 20)
    check(need <= q.card.width() - 44, f"{lang}: вопрос: ряд кнопок {need} <= {q.card.width() - 44}")
    q.close()
    # карточка знакомства: «Шаг i из n» и «Отложить» в одном ряду
    t = Tour(ed, language=False, snoozable=True)
    t.start()
    settle(10)
    t.show_step(1)
    head_need = t.step_label.sizeHint().width() + t.snooze_button.sizeHint().width() + 10
    btn_need = t.skip.sizeHint().width() + t.back.sizeHint().width() + t.next.sizeHint().width() + 20
    check(head_need <= t.card.width() - 36 and btn_need <= t.card.width() - 36,
          f"{lang}: карточка знакомства: шапка {head_need}, кнопки {btn_need} <= {t.card.width() - 36}")
    t.finish()
    settle(10)
    # окно «Ознакомление»: кнопки внизу
    if lang in ("ru", "de", "zh", "pt"):
        w = oznakomlenie.open_window(a)
        settle(40)
        bn = w.snooze_button.sizeHint().width() + w.done_button.sizeHint().width() + 8
        check(bn < w.right_w.width() // 2, f"{lang}: «Ознакомление»: нижние кнопки {bn} px")
        w.close()
        settle(30)
i18n.set_language("ru")
close_all()

# --- 5. меню не выходит за экран -----------------------------------------------------------------------------------
screen = QGuiApplication.primaryScreen().availableGeometry()
holder = otlozhit.SnoozeButton(False)
for label, pos in (("правый нижний угол", (screen.right() - 140, screen.bottom() - 40)), ("левый верх", (2, 2)),
                   ("низ по центру", (screen.center().x(), screen.bottom() - 30)), ("правый верх", (screen.right() - 130, 4))):
    holder.move(*pos)
    holder.show()
    settle(10)
    r = holder.menu_rect()
    check(screen.contains(r), f"меню у «{label}» внутри экрана {r.getRect()} в {screen.getRect()}")
    holder.open_menu()
    settle(20)
    mg = holder.menu.geometry()
    check(screen.contains(mg) or not holder.menu.isVisible(), f"меню открыто у «{label}»: {mg.getRect()}")
    holder.menu.close()
holder.close()

# --- 6. тема: светлая и тёмная ------------------------------------------------------------------------------------------
light, dark = otlozhit.button_style(False), otlozhit.button_style(True)
check(light != dark and "#25282c" in dark and "#ffffff" in light, "стили кнопки для светлой и тёмной темы разные")
check("#25282c" in otlozhit.menu_style(True) and "#ffffff" in otlozhit.menu_style(False), "меню окрашено под тему окна")
check(all("—" not in i18n._load(l).get(k, "") for l in i18n.LANGUAGES for k in i18n._load(l) if k.startswith("otl.")),
      "в новых строках нет длинных тире")

print("ИТОГ:", "все проверки пройдены" if not failures else f"{len(failures)} не пройдено")
sys.exit(1 if failures else 0)
