# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""«Не показывать» в меню «Отложить ▾» (слова владельца 23.11.2026).

Пункт есть в окне «Новое в версии», вопросе про другие функции, знакомстве (редактор и окно выделения), «Ознакомлении»
(только если открылось само), с верной подписью. После нажатия окно не приходит ни через сутки, ни после перезапуска
для этой версии, точка колокольчика гаснет, метки «Новое» скрыты, следующая версия показывает свои новинки, «Что нового»
из меню открывает окно. 12 языков: строки на месте, меню не обрезается.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/ne_pokazyvat_test.py
"""
import tmpclean  # noqa: F401
import json
import os
import sys
import tempfile
from datetime import datetime

here = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(here)
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp(prefix="clipsd-nep-")
for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[name] = os.path.join(tmp, name)
_screen = os.path.join(tmp, "screen.json")   # 910x472: 1366x768 при масштабе 150 %, самый низкий экран, который держим
with open(_screen, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "low", "x": 0, "y": 0, "width": 910, "height": 472,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _screen
os.environ.pop("CLIPSD_LANG", None)

from PyQt6.QtCore import QTimer  # noqa: E402
from PyQt6.QtGui import QFontMetrics  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel  # noqa: E402

qapp = QApplication(sys.argv)
qapp.setQuitOnLastWindowClosed(False)

import clipshot  # noqa: E402
from clipshot import app as appmod, i18n, notifications, novoe, otlozhit, oznakomlenie  # noqa: E402

V = "1.36.0"
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


T0 = datetime(2026, 11, 24, 14, 30).timestamp()
clock = [T0]
otlozhit.now = lambda: clock[0]
DAY = 86400

appmod.is_wayland = lambda: False
a = appmod.Clipshot(qapp)
a.notify = lambda *_x: None
a.save_config = lambda: None


def fresh():
    a.config.clear()
    a.config.update(dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True, tour_selector_done=True,
                         novoe_version="1.35.0"))
    novoe.on_start(a.config, V)
    a.config["novoe_from"] = "1.35.0"


def answer_modal(fn, timeout_ms=4000):
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


NEVER_LABELS = {"novoe": "Не показывать новинки этой версии", "ask": "Больше не спрашивать",
                "tour": "Не показывать знакомство", "ozn": "Не открывать само"}


def labels(btn):
    return [x.text() for x in btn.menu.actions() if not x.isSeparator()]


# --- 1. пункт есть, подпись верная, он последний после разделителя ------------------------------------------------
fresh()
box = novoe.make_window(V, novoe.window_items(a.config), None)
acts = box.later_button.menu.actions()
check(acts[-1].text() == NEVER_LABELS["novoe"] and acts[-2].isSeparator() and len(acts) == 7,
      f"«Новое в версии»: последний пункт «{acts[-1].text()}» после разделителя")
check([x.text() for x in acts[:5]] == ["На 15 минут", "На 1 час", "На 3 часа", "До завтра", "На неделю"],
      "«Новое в версии»: прежние пять пунктов на месте")
box.done(0)   # finished снимает слушатель смены языка
q = novoe.make_question(None)
check(labels(q.snooze_button)[-1] == NEVER_LABELS["ask"], f"вопрос про другие функции: «{labels(q.snooze_button)[-1]}»")
q.close()
from clipshot.tour import Tour  # noqa: E402
a.config["novoe_window"] = V   # редактор не должен сам открыть окно новинок модально
ed = a.open_editor(__import__("PyQt6.QtGui", fromlist=["QImage"]).QImage(900, 500, __import__("PyQt6.QtGui", fromlist=["QImage"]).QImage.Format.Format_RGB32), None)
settle(600)
t = Tour(ed, language=False, snoozable=True)
check(labels(t.snooze_button)[-1] == NEVER_LABELS["tour"], f"знакомство в редакторе: «{labels(t.snooze_button)[-1]}»")
t.snooze_button.close()
t.finish()
t2 = Tour(ed, language=False, snoozable=False)
check(t2.snooze_button is None, "знакомство по запросу: кнопки «Отложить» нет, пункта тоже")
t2.finish()
from clipshot.selector_tour import SelectorTour  # noqa: E402
win = oznakomlenie.open_window(a)
settle(40)
check(labels(win.snooze_button) == ["На 15 минут", "На 1 час", "На 3 часа", "До завтра", "На неделю"],
      "«Ознакомление» из меню значка: пункта «Не показывать» нет")
win.set_auto(True)
check(labels(win.snooze_button)[-1] == NEVER_LABELS["ozn"], f"«Ознакомление», открытое само: «{labels(win.snooze_button)[-1]}»")
win.set_auto(False)
check(len(labels(win.snooze_button)) == 5, "set_auto(False) убирает пункт")
win.close()
settle(450)
ed.canvas.modified = False
ed.close()
settle(60)

# --- 2. «Не показывать» в окне новинок -------------------------------------------------------------------------
fresh()
check(novoe.window_pending(a.config) and bool(novoe.badges(a.config, "editor")) and f"whatsnew:{V}" not in notifications.read_ids(a.config),
      "до нажатия: окно ждёт, метки есть, точка не погашена")
st = answer_modal(lambda w: w.later_button.actions_by_key["never"].trigger())
choice = a.show_novoe(None, auto=True)
check(choice == "never", f"выбор {choice}")
cfg = a.config
check(not novoe.window_pending(cfg), "окно этой версии больше не ждёт")
check(f"whatsnew:{V}" in notifications.read_ids(cfg), "точка колокольчика погасла (whatsnew прочитано)")
check(not novoe.badges(cfg, "editor") and not novoe.badges(cfg, "selector"), "метки «Новое» скрыты")
check(otlozhit.until(cfg, "novoe") is None and not otlozhit.due_topics(cfg), "отложенного срока нет")
check(not novoe.ask_pending(cfg), "вопрос про другие функции тоже не придёт")
clock[0] = T0 + DAY + 3600
check(not novoe.window_pending(cfg) and not otlozhit.due_topics(cfg), "через сутки окно не приходит")
a._otlozhit_tick()
check(getattr(a, "_novoe_window", None) is None, "через сутки таймер окно не открывает")
clock[0] = T0
cfg2 = json.loads(json.dumps(cfg))   # перезапуск: настройки записаны и прочитаны
novoe.on_start(cfg2, V)
check(not novoe.window_pending(cfg2) and not novoe.badges(cfg2, "editor") and not novoe.ask_pending(cfg2),
      "после перезапуска: окна, вопроса и меток нет")

# следующая версия показывает свои новинки
novoe.ITEMS = novoe.ITEMS + (("1.37.0", "next_thing", "editor:print_button", "print"),)
novoe.on_start(cfg2, "1.37.0")
check(novoe.window_pending(cfg2, "1.37.0") and novoe.badges(cfg2, "editor", "1.37.0") and novoe.ask_pending(cfg2, "1.37.0"),
      "версия 1.37: окно, метки и вопрос снова работают")
check("novoe_hidden" not in cfg2, "флаг «не показывать» относился к 1.36 и снят")

# «Что нового» из меню значка открывает окно, хотя «Не показывать» нажато
seen = []
st = answer_modal(lambda w: (seen.append(type(w).__name__), w.later_button.actions_by_key["1h"].trigger()))
choice = a.show_novoe(None, auto=False)
check(seen and choice == "snooze", f"«Что нового» из меню открыло окно после «Не показывать» ({seen}, {choice})")
a.config.clear()
fresh()
novoe.hide_version(a.config)
seen.clear()
st = answer_modal(lambda w: (seen.append(1), w.close()))
a.show_novoe(None, auto=False)
check(bool(seen), "пункт меню «Что нового» открывает окно и при скрытой версии")

# --- 3. вопрос про другие функции -----------------------------------------------------------------------------------
fresh()
a.config["novoe_asked"] = "1.35.0"
a.config["ozn_seen"] = []
st = answer_modal(lambda w: w.snooze_button.actions_by_key["never"].trigger())
a._ask_overview()
check(not novoe.ask_pending(a.config) and otlozhit.until(a.config, "ask") is None, "«Больше не спрашивать»: вопрос не придёт, срока нет")
a.config["novoe_version"] = V
a.config["novoe_asked"] = V
check(not novoe.ask_pending(a.config), "после перезапуска вопрос не приходит")

# --- 4. «Ознакомление», открытое само ---------------------------------------------------------------------------------
fresh()
otlozhit.snooze(a.config, "ozn", "1h", id=None)
win = a.open_oznakomlenie(ask_after=True)
settle(60)
check(win is not None and labels(win.snooze_button)[-1] == NEVER_LABELS["ozn"], "после «Показать новое» окно имеет «Не открывать само»")
win.snooze_button.actions_by_key["never"].trigger()
settle(450)
check(getattr(a, "_ozn_window", None) is None, "окно закрылось")
check(otlozhit.until(a.config, "ozn") is None and not novoe.window_pending(a.config) and not novoe.ask_pending(a.config)
      and f"whatsnew:{V}" in notifications.read_ids(a.config), "«Не открывать само»: срок снят, окно и вопрос не придут, точка погасла")
win = a.open_oznakomlenie()
settle(60)
check(win is not None and len(labels(win.snooze_button)) == 5, "«Ознакомление» из меню значка по-прежнему открывается, без пункта")
win.close()
settle(100)

# --- 5. знакомство ----------------------------------------------------------------------------------------------------
fresh()
a.config["novoe_window"] = V
a.config["tour_done"] = False
ed = a.open_editor(__import__("PyQt6.QtGui", fromlist=["QImage"]).QImage(900, 500, __import__("PyQt6.QtGui", fromlist=["QImage"]).QImage.Format.Format_RGB32), None)
settle(100)
if getattr(ed, "tour", None) is not None:
    ed.tour.finish()
ed.tour = None
a.config["tour_done"] = False
ed.start_tour()
settle(60)
check(ed.tour is not None and ed.tour.snooze_button is not None, "первое знакомство: кнопка «Отложить» есть")
ed.tour.snooze_button.actions_by_key["never"].trigger()
settle(60)
check(a.config.get("tour_done") is True and ed.tour is None and otlozhit.until(a.config, "tour") is None,
      "«Не показывать знакомство»: знакомство пройденным (tour_done), срока нет")
check(callable(getattr(ed, "start_tour", None)) and hasattr(a, "open_oznakomlenie"), "«Ознакомление» и знакомство из меню доступны")
ed.canvas.modified = False
ed.close()
settle(60)

from clipshot.selector import RegionSelector  # noqa: E402


class FakeSel:
    pass


fs = FakeSel()
fs.tr_cfg = {"tour_selector_done": False}
fs.tr_save = lambda: None
RegionSelector._tour_snoozed(fs, "never")
check(fs.tr_cfg["tour_selector_done"] is True and otlozhit.until(fs.tr_cfg, "tour_selector") is None,
      "окно выделения: «Не показывать знакомство» отмечает показанным")
sbtn = otlozhit.SnoozeButton(False, compact=True, never="otl.never_tour")
check(labels(sbtn)[-1] == NEVER_LABELS["tour"], "знакомство с окном выделения: подпись верная")

# --- 6. 12 языков, обе темы: строки на месте, меню не обрезается ----------------------------------------------------
for lang in i18n.LANGUAGES:
    i18n.set_language(lang)
    cat = i18n._load(lang)
    miss = [k for k in ("otl.never_novoe", "otl.never_ask", "otl.never_tour", "otl.never_ozn") if not cat.get(k)]
    check(not miss, f"{lang}: строки на месте {miss}")
    for dark in (False, True):
        for key in ("otl.never_novoe", "otl.never_ask", "otl.never_tour", "otl.never_ozn"):
            b = otlozhit.SnoozeButton(dark, never=key)
            b.show()
            settle(10)
            widest = max(QFontMetrics(b.menu.font()).horizontalAdvance(x.text()) for x in b.menu.actions())
            check(b.menu.sizeHint().width() >= widest + 30 and b.menu_rect().width() == b.menu.sizeHint().width(),
                  f"{lang} {'тёмная' if dark else 'светлая'} {key}: меню {b.menu.sizeHint().width()} >= {widest}")
            b.retranslate()
            b.close()

# --- 7. кнопки нижнего ряда не обрезаются (слова координатора 23.11.2026), экраны 1366x768 и 910x512 ----------------
from PyQt6.QtWidgets import QPushButton  # noqa: E402
fresh()
for lang in i18n.LANGUAGES:
    i18n.set_language(lang)
    for dark in (False, True):
        for kind in ("novoe", "ask"):
            win = (novoe.make_window(V, novoe.window_items(a.config), None, notes=True, dark=dark) if kind == "novoe"
                   else novoe.make_question(None, dark=dark))
            win.show()
            settle(40)
            tight, outside = [], []
            for b in win.findChildren(QPushButton):
                if not b.isVisible() or not b.text():
                    continue
                pad = 3 if b.objectName() == "clipLink" else 16
                if QFontMetrics(b.font()).horizontalAdvance(b.text()) + pad > b.width():
                    tight.append(b.text())
                if not win.card.rect().contains(b.mapTo(win.card, b.rect().bottomRight())):
                    outside.append(b.text())
            fits = (win.card.width() + 2 * 20 <= 910 and win.height() <= 472)
            check(not tight and not outside and fits,
                  f"{lang} {'тёмная' if dark else 'светлая'} {kind}: кнопки целы {tight}, в карточке {outside}, окно {win.width()}x{win.height()}")
            if kind == "novoe":
                # В4 проверки 1.36: на низком экране строки пунктов не наезжают друг на друга (каждая подпись получила высоту
                # по ширине), окно в экране, лишнее прокручивается, кнопки внизу видны
                cramped = []
                for r in win.rows:
                    for lab in r.findChildren(QLabel):
                        if lab.text() and lab.wordWrap() and lab.height() < lab.heightForWidth(lab.width()):
                            cramped.append(lab.text()[:20])
                rows_h = win.rows_height(win.scroll.viewport().width())
                scrolls = win.scroll.verticalScrollBar().maximum() > 0
                enough = win.scroll.viewport().height() >= rows_h or scrolls
                check(not cramped and enough and win.height() <= 472 and win.scroll.viewport().height() >= 200,
                      f"{lang} {'тёмная' if dark else 'светлая'} низкий экран 910x472: строки не наезжают {cramped[:2]}, "
                      f"видно {win.scroll.viewport().height()} из {rows_h}, прокрутка {scrolls}")
            win.done(0)

print("ИТОГ:", "ПРОВАЛЕНО " + str(len(failures)) if failures else "ВСЁ ХОРОШО", flush=True)
sys.exit(1 if failures else 0)
