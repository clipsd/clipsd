# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""22.11.2026 (просьба владельца): картинка с телефона, из файла или из буфера кладётся в открытый снимок или
открывается отдельным снимком. Меню у кнопки «С телефона» (стрелка ▾) и в «Вставить» с отметкой у выбора, выбор
запоминается; фото с телефона читает выбор в момент прихода; после вставки 6 секунд карточка «Вставлено в снимок ·
Открыть отдельно»; у выделенной вставленной картинки постоянная кнопка «Открыть отдельно» (у других объектов её нет).
Гонки: смена выбора при приходе фото, снимок закрывается, два фото подряд.

Запуск: python3 tests/otdelnym_snimkom_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import glob
import json
import os
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
tmp = tempfile.mkdtemp(prefix="clipsd-otdel-")
for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[name] = os.path.join(tmp, name)
_screen = os.path.join(tmp, "screen.json")
with open(_screen, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1600, "height": 1000,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _screen

from PyQt6.QtCore import QPoint, QPointF, QTimer, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QGuiApplication, QImage  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

qapp = QApplication(sys.argv)
qapp.setQuitOnLastWindowClosed(False)
from clipshot import app as appmod, i18n, otdelno, phone_ui  # noqa: E402
from clipshot.editor import EditorWindow, GROUP_ARROW_W, PHONE_ICON_W  # noqa: E402
from clipshot.shapes import IMAGE, RECT, Shape  # noqa: E402

failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


a = appmod.Clipshot(qapp)
saves = []
a.save_config = lambda: saves.append(a.config.get(otdelno.CONFIG_KEY))
notes = []
a.notify = lambda t, *_x: notes.append(t)
folder = os.path.join(tmp, "shots")
os.makedirs(folder)
a.config.update(theme_chosen=True, tour_done=True, novoe_enabled=False, auto_save=True, auto_save_dir=folder,
                save_dir=folder)
i18n.set_language("ru")


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
        return None


def pic(w=1200, h=900, color="#ff0000"):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    return img


def mk(w=900, h=500):
    ed = a.open_editor(pic(w, h, "#ffffff"), None)
    ed.autosave_path = None
    QTest.qWait(80)
    return ed


def others(ed):
    return [e for e in a.editors if e is not ed]


def close_all():
    for e in list(a.editors):
        e.exported = True
        e.only_in_memory = False
        e.canvas.modified = False
        e.close()
    QTest.qWait(80)


def images(ed):
    return [s for s in ed.canvas.shapes if s.kind == IMAGE]


def deliver(ed, session=None, color="#ff0000"):
    s = session or Session(ed)
    phone_ui.deliver_photo(s, {"image": pic(1200, 900, color), "count": 1, "pid": "p1"})
    return s


def jpgs():
    return sorted(glob.glob(os.path.join(folder, "*.jpg")))


# --- 1. меню: два пункта, отметка у выбора, выбор запоминается ---------------------------------------------------
ed = mk()
check(otdelno.get_mode(a.config) == "here", "по умолчанию «в этот снимок»")
menu = ed.build_target_menu()
acts = menu.actions()
check([x.text() for x in acts] == ["Вставить в этот снимок", "Открыть отдельным снимком"], "меню: два пункта по-русски")
check(acts[0].isChecked() and not acts[1].isChecked(), "отметка у «в этот снимок»")
acts[1].trigger()
check(a.config["insert_target_mode"] == "apart" and saves[-1] == "apart", "выбор «отдельным снимком» запомнен и сохранён")
check(ed.build_target_menu().actions()[1].isChecked(), "новое меню: отметка у выбранного")
ed.set_insert_mode("bogus")
check(otdelno.get_mode(a.config) == "apart", "неизвестное значение выбор не меняет")
a.config["insert_target_mode"] = "мусор"
check(otdelno.get_mode(a.config) == "here", "испорченная настройка читается как «в этот снимок»")
ed.set_insert_mode("here")

# меню «Вставить»: те же пункты в конце и отметка обновляется при открытии
im = ed.insert_button.menu()
texts = [x.text() for x in im.actions() if not x.isSeparator()]
check(texts[-2:] == ["Вставить в этот снимок", "Открыть отдельным снимком"], f"меню «Вставить»: пункты выбора в конце {texts}")
ed.set_insert_mode("apart")
im.aboutToShow.emit()
check([x.isChecked() for x in im.actions() if x.isCheckable()] == [False, True], "меню «Вставить»: отметка обновилась")
ed.set_insert_mode("here")

# стрелка ▾ у «С телефона»: открывает меню выбора; щелчок по самой кнопке выбор не меняет
b = ed.phone_button
opened = []


def pick_apart():
    m = ed._target_menu
    opened.append([x.text() for x in m.actions()] if m is not None else None)
    if m is not None:
        m.actions()[1].trigger()
        m.close()


QTimer.singleShot(150, pick_apart)
QTest.mouseClick(b, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(b.width() - 5, b.height() // 2))
QTest.qWait(100)
check(opened and opened[0] == ["Вставить в этот снимок", "Открыть отдельным снимком"], "щелчок по стрелке открывает меню выбора")
check(otdelno.get_mode(a.config) == "apart", "выбор в меню у кнопки действует")
check(b.width() >= PHONE_ICON_W and b.width() - 20 >= GROUP_ARROW_W, "кнопка со стрелкой не уже значка")
calls = []
a.open_phone = lambda target=None: calls.append(target)
QTest.mouseClick(b, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(10, b.height() // 2))
check(calls == [ed] and otdelno.get_mode(a.config) == "apart", "щелчок по кнопке открывает приём, выбор остался")
del a.open_phone
ed.set_insert_mode("here")
close_all()

# --- 2. телефон: в снимок и отдельно ----------------------------------------------------------------------------
ed = mk()
before = len(jpgs())
s = deliver(ed)
check(len(images(ed)) == 1 and not others(ed), "телефон, «в этот снимок»: картинка в снимке, нового окна нет")
check(len(jpgs()) == before + 1 and s.receiver.confirmed == ["p1"], "файл фото сохранён, телефону «принято»")
check(ed._insert_hint is not None and ed._insert_hint.isVisible()
      and ed._insert_hint.title.text() == "Вставлено в снимок" and ed._insert_hint.button.text() == "Открыть отдельно",
      "после вставки карточка «Вставлено в снимок» с кнопкой «Открыть отдельно»")
check(ed._apart_button is None or not ed._apart_button.isVisible(), "пока карточка видна, второй кнопки нет")
ed.set_insert_mode("apart")
before = len(jpgs())
s = deliver(ed, color="#00aa00")
new = others(ed)
check(len(images(ed)) == 1 and len(new) == 1, "телефон, «отдельным»: в снимке не прибавилось, открыт новый редактор")
check(len(jpgs()) == before + 1 and new[0].autosave_path in jpgs() and new[0].phone_photo, "новый снимок с автосохранением")
check(new[0].canvas.base.width() > 0 and s.receiver.confirmed == ["p1"], "телефону «принято»")
close_all()

# --- 3. файл и буфер ---------------------------------------------------------------------------------------------
ed = mk()
ed.set_insert_mode("here")
path = os.path.join(tmp, "f.png")
pic(400, 300, "#0000ff").save(path)
ed.place_image(QImage(path))
check(len(images(ed)) == 1 and not others(ed), "файл, «в этот снимок»: картинка в снимке")
ed.set_insert_mode("apart")
ed.place_image(QImage(path))
new = others(ed)
check(len(images(ed)) == 1 and len(new) == 1 and new[0].canvas.base.size().width() == 400, "файл, «отдельным»: новый снимок 400 точек")
check(new[0].autosave_path and os.path.exists(new[0].autosave_path), "файл отдельным: автосохранён")
QGuiApplication.clipboard().setImage(pic(300, 200, "#aa00aa"))
ed.paste_image()
check(len(others(ed)) == 2 and len(images(ed)) == 1, "буфер через меню, «отдельным»: ещё один снимок")
ed.paste_image(True)
check(len(images(ed)) == 2, "Ctrl+V всегда в этот снимок")
close_all()

# --- 4. карточка: «Открыть отдельно» убирает ровно эту вставку ---------------------------------------------------
ed = mk()
ed.set_insert_mode("here")
rect = Shape(RECT, QColor("#ff0000"), 2, QPointF(20, 20))
rect.points = [QPointF(20, 20), QPointF(120, 90)]
ed.canvas.push_undo()
ed.canvas.shapes.append(rect)
ed.place_image(pic(500, 400, "#12ab34"))
check(len(images(ed)) == 1 and len(ed.canvas.shapes) == 2, "до: рамка и картинка")
ed._insert_hint.button.click()
QTest.qWait(60)
check(not images(ed) and len(ed.canvas.shapes) == 1 and ed.canvas.shapes[0].kind == RECT, "кнопка карточки: убрана ровно картинка, рамка на месте")
new = others(ed)
check(len(new) == 1 and new[0].canvas.base.width() == 500 and new[0].canvas.base.pixelColor(5, 5) == QColor("#12ab34"),
      "новый редактор с той же картинкой в исходном качестве")
check(not ed._insert_hint.isVisible(), "карточка ушла")
ed.canvas.undo()
check(len(images(ed)) == 1 and len(ed.canvas.shapes) == 2, "«Отменить» возвращает картинку одним шагом")
ed.canvas.undo()
ed.canvas.undo()
check(not images(ed) and not ed.canvas.shapes, "дальше отменяются прежние шаги по порядку (вставка, потом рамка)")
close_all()

# карточка уходит при следующем действии и сама через 6 секунд; не мешает рисовать
ed = mk()
ed.place_image(pic(300, 200))
check(ed._insert_hint.SHOW_MS == 6000 and ed._insert_hint.isVisible(), "карточка на 6 секунд")
ed.canvas.pressed.emit()
check(not ed._insert_hint.isVisible(), "нажатие на снимок убирает карточку")
ed.place_image(pic(300, 200))
check(ed._insert_hint.isVisible(), "новая вставка показывает её снова")
ed.canvas.push_undo()
check(not ed._insert_hint.isVisible(), "любая правка убирает карточку")
close_all()

# --- 5. постоянная кнопка у выделенной вставленной картинки ------------------------------------------------------
ed = mk()
ed.place_image(pic(300, 200, "#336699"))
ed._insert_hint.dismiss()
btn = ed._apart_button
check(btn is not None and btn.isVisible() and btn.text() == "Открыть отдельно" and not btn.icon().isNull(),
      "выделена картинка: кнопка «Открыть отдельно» со значком окна")
ed.canvas.select(None)
check(not btn.isVisible(), "ничего не выделено: кнопки нет")
for kind in (RECT,):
    sh = Shape(kind, QColor("#ff0000"), 2, QPointF(10, 10))
    sh.points = [QPointF(10, 10), QPointF(60, 50)]
    ed.canvas.push_undo()
    ed.canvas.shapes.append(sh)
    ed.canvas.select(sh)
    check(not btn.isVisible(), "выделена рамка: кнопки нет")
img_shape = images(ed)[0]
ed.canvas.select(img_shape)
check(btn.isVisible(), "снова выделили картинку: кнопка есть")
r = btn.geometry()
check(ed.rect().contains(r), "кнопка внутри окна редактора")
# пометка поверх картинки не попадает в новый снимок
ed.canvas.shapes.append(sh)
btn.click()
QTest.qWait(60)
new = others(ed)
check(len(new) == 1 and new[0].canvas.base.size().width() == 300 and not new[0].canvas.shapes, "новый снимок: исходная картинка без пометок")
check(not images(ed) and not btn.isVisible(), "картинка ушла из снимка, кнопка скрыта")
ed.canvas.undo()
check(len(images(ed)) == 1, "«Отменить» возвращает картинку")
# тёмная тема
ed.place_image(pic(200, 100))
a.config["ui_theme"] = "pro"
ed.refresh_theme()
check(ed._apart_button.dark and ed._insert_hint.dark and "#8cc4ff" in ed._apart_button.styleSheet().lower(),
      "тёмная тема: карточка и кнопка в тёмных цветах")
a.config["ui_theme"] = "standard"
ed.refresh_theme()
check(not ed._apart_button.dark and not ed._insert_hint.dark, "светлая тема: возврат")
close_all()

# --- 6. сочетания: снимок закрывается, не сохранён --------------------------------------------------------------
ed = mk()
ed.set_insert_mode("here")
ed.canvas.push_undo()
ed.closing = True
notes.clear()
s = deliver(ed)
check(not images(ed) and len(others(ed)) == 1 and s.receiver.confirmed == ["p1"], "снимок закрывается: фото отдельным снимком, ничего не теряется")
check(any("сохран" in n.lower() or "отдельн" in n.lower() for n in notes), "уведомление о том, где фото")
ed.closing = False
close_all()

# --- 7. гонки ---------------------------------------------------------------------------------------------------
# 7a. фото приходит, пока открыто меню выбора: это фото по прежнему выбору, меняется следующее
ed = mk()
ed.set_insert_mode("here")
st = {}


def race():
    deliver(ed)                       # приходит при открытом меню (выбор ещё «в этот снимок»)
    st["after_first"] = (len(images(ed)), len(others(ed)))
    ed._target_menu.actions()[1].trigger()   # человек выбрал «отдельным»
    ed._target_menu.close()


QTimer.singleShot(100, race)
ed.show_phone_menu()
deliver(ed, color="#00ff00")
check(st["after_first"] == (1, 0), "фото при открытом меню ушло по прежнему выбору (в снимок)")
check(len(images(ed)) == 1 and len(others(ed)) == 1, "следующее фото после смены выбора открыто отдельно")
close_all()

# 7b. два фото подряд: оба по выбору; карточка относится к последнему
ed = mk()
ed.set_insert_mode("here")
deliver(ed, color="#111111")
first = images(ed)[0]
deliver(ed, color="#222222")
check(len(images(ed)) == 2 and ed._insert_hint.shape is images(ed)[1], "два фото подряд: обе в снимке, карточка про последнее")
ed._insert_hint.button.click()
QTest.qWait(60)
check(len(images(ed)) == 1 and images(ed)[0] is first and len(others(ed)) == 1, "«Открыть отдельно» унесло только последнее")
ed.set_insert_mode("apart")
deliver(ed)
deliver(ed)
check(len(others(ed)) == 3 and len(images(ed)) == 1, "два фото подряд в режиме «отдельно»: два новых снимка")
close_all()

# 7c. редактор закрыт, пока приходит фото: связь с ним потеряна, фото не теряется
ed = mk()
ed.set_insert_mode("apart")
s = Session(ed)
ed.exported = True
ed.canvas.modified = False
ed.close()
QTest.qWait(60)
before = len(a.editors)
deliver(ed, session=s)
check(len(a.editors) == before + 1 and s.receiver.confirmed == ["p1"], "редактор закрыт: фото открыто новым снимком")
close_all()

# 7d. открытие картинки отдельно после закрытия окна, из которого она вставлена, не падает
ed = mk()
ed.set_insert_mode("here")
ed.place_image(pic(200, 100))
shape = images(ed)[0]
ed.canvas.shapes.clear()
check(ed.open_shape_apart(shape) is False, "картинки в снимке уже нет: ничего не открывается и не падает")
close_all()

# --- 8. 12 языков и узкое окно -----------------------------------------------------------------------------------
for lang in ("ru", "en", "es", "de", "fr", "it", "pt", "pl", "tr", "uk", "bg", "zh"):
    i18n.set_language(lang)
    ed = mk(300)
    keys = ("otdelno.here", "otdelno.apart", "otdelno.arrow_tip", "otdelno.hint_title", "otdelno.hint_button",
            "otdelno.hint_tip")
    check(all(i18n.tr(k) != k and i18n.tr(k) for k in keys), f"{lang}: строки переведены")
    pb = ed.phone_button
    fits = ed.titlebar.layout().minimumSize().width() <= ed.titlebar.width() if ed.titlebar is not None else True
    check(fits and ed.panel.layout().minimumSize().width() <= ed.panel.width(), f"{lang}: узкое окно, шапка и первый ряд помещаются")
    ed.place_image(pic(200, 100))
    ed._insert_hint.dismiss()
    check(ed._apart_button.isVisible() and ed._apart_button.width() >= ed._apart_button.sizeHint().width() - 1,
          f"{lang}: кнопка «Открыть отдельно» не обрезана")
    close_all()
i18n.set_language("ru")

print(f"\nИТОГ: {'ВСЁ ХОРОШО' if not failures else str(len(failures)) + ' ошибок'}")
sys.exit(1 if failures else 0)
