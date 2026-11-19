# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""1.32: язык в настройках применяется сразу (окно настроек перестраивается на новом языке, открытый редактор тоже,
несохранённые правки остаются, «Отмена» язык не откатывает); флаги у всех 12 языков в меню языка, списке настроек,
кнопках знакомства и чипе окна выделения.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/langflags_test.py
"""
import json
import os
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
os.environ.pop("CLIPSD_LANG", None)
_cfg = os.path.join(tempfile.mkdtemp(prefix="clipsd-flags-"), "screen.json")
with open(_cfg, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1600, "height": 1000,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _cfg
from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
from clipshot import app as appmod, i18n, icons, language
from clipshot.editor import EditorWindow
from clipshot.selector import RegionSelector
from clipshot.settings import SettingsDialog

failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def settle(n=6):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(15)


class Ctx:
    def __init__(self):
        self.config = dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True, language="ru")
        self.icon = appmod.make_icon()
        self.editors = []

    def set_language(self, choice):
        self.config["language"] = choice
        i18n.set_language(choice)
        for e in self.editors:
            e.retranslate()

    def save_config(self):
        pass

    def open_settings(self):
        pass


i18n.set_language("ru")
# --- флаги: у всех 12 языков свой рисунок, у «Как в системе» глобус
images = {}
for code in icons.FLAG_CODES:
    img = icons.flag_icon(code).pixmap(24, 16).toImage()
    images[code] = img
    check(not img.isNull() and img.width() >= 24, f"флаг {code} нарисован")
check(set(i18n.LANGUAGES) <= set(icons.FLAG_CODES), "флаги есть у всех языков программы")
from clipshot import translate
no_flag = [c for c in translate.TARGETS if c not in icons.FLAG_CODES]
check(no_flag == ["ar"], f"флаги есть у всех языков перевода, кроме арабского (глобус): {no_flag}")
check(len({bytes(i.constBits().asarray(i.sizeInBytes())) for i in images.values()}) == len(icons.FLAG_CODES),
      f"все {len(icons.FLAG_CODES)} флагов разные")
corner = images["ru"].pixelColor(0, 0)
check(corner.alpha() < 128, "углы флага скруглены (прозрачны)")
check(images["ru"].pixelColor(12, 8).name() == "#1c57a5", "ru: синяя полоса посередине")

ctx = Ctx()
# --- меню языка
menu = language.make_menu(ctx)
acts = [a for a in menu.actions() if not a.isSeparator()]
check(len(acts) == 13 and all(not a.icon().isNull() for a in acts), f"меню: 13 пунктов, у всех значок ({len(acts)})")
check(sum(1 for a in acts if a.data() in icons.FLAG_CODES) == 12, "меню: флаг у каждого из 12 языков")
# --- окно настроек
dlg = SettingsDialog(ctx.config)
dlg.update_ctx = ctx
dlg.show()
settle()
check(dlg.language.count() == 13 and all(not dlg.language.itemIcon(i).isNull() for i in range(13)),
      "список языков в настройках: 13 пунктов со значками")
check(dlg.language.iconSize().width() == 24 and dlg.language.iconSize().height() == 16, "размер значка списка 24x16")
# --- открытый редактор и несохранённые правки
from clipshot.app import demo_image
ed = EditorWindow(demo_image(), ctx, QPoint(0, 0))
ctx.editors.append(ed)
ed.present()
settle()
before_ed = ed.save_button.text()
before_title = dlg.windowTitle()
dlg.show_zoom.setChecked(not dlg.show_zoom.isChecked())
unsaved = dlg.show_zoom.isChecked()
dlg.language.setCurrentIndex(dlg.language.findData("de"))
settle(8)
check(ctx.config["language"] == "de" and i18n.current() == "de", "язык применён сразу, без «Сохранить»")
check(dlg.windowTitle() == i18n.tr_in("de", "settings.title") != before_title, f"окно настроек на новом языке: {dlg.windowTitle()}")
check(ed.save_button.text() != before_ed, f"открытый редактор перешёл на язык: {before_ed} -> {ed.save_button.text()}")
check(dlg.show_zoom.isChecked() == unsaved, "несохранённая правка в настройках сохранилась после перестройки")
check(dlg.language.currentData() == "de" and dlg.isVisible(), "в списке выбран новый язык, окно не закрылось")
check(dlg.language.count() == 13 and not dlg.language.itemIcon(5).isNull(), "после перестройки флаги на месте")
dlg.language.setCurrentIndex(dlg.language.findData("zh"))
settle(8)
check(dlg.windowTitle() == i18n.tr_in("zh", "settings.title"), "второй раз подряд тоже работает")
dlg.reject()
settle()
check(ctx.config["language"] == "zh", "«Отмена» язык не откатывает: остаётся выбранный")
check(dlg.values()["language"] == "zh", "values() даёт выбранный язык")
ed.close()

# --- знакомство и окно выделения
i18n.set_language("ru")
W, H = 1280, 720
pm = QPixmap(W, H)
pm.fill(QColor("#4a78b0"))
sel = RegionSelector(pm, QRect(0, 0, W, H), last_rect=QRect(300, 120, 520, 300))
sel.tr_cfg, sel.tr_save = dict(appmod.DEFAULTS), lambda: None
sel.lang_ctx = Ctx()
sel.show_zoom = False
sel.resize(W, H)
sel.show()
settle()
sel._bar_layout()
check(sel.lang_rect.width() > 60, f"чип языка в окне выделения длинный (с флагом): {sel.lang_rect.width()}")
img = sel.grab().toImage().copy(sel.lang_rect)
flag_x = sel.lang_rect.left() + 8 + 14 + 6 + 10
red = sum(1 for y in range(img.height()) for x in range(flag_x - sel.lang_rect.left(), flag_x - sel.lang_rect.left() + 14)
          if img.pixelColor(x, y).red() > 180 and img.pixelColor(x, y).blue() < 80)
check(red > 5, f"в чипе виден красный цвет флага ru ({red} точек)")
sel._done = True
sel.close()

from clipshot.tour import Tour
ed2 = EditorWindow(demo_image(), Ctx(), QPoint(0, 0))
ed2.resize(1000, 760)
ed2.present()
settle()
ed2.start_tour(language=True)   # шаг выбора языка: как при самом первом знакомстве
settle()
tb = ed2.tour.lang_buttons
check(len(tb) == 13 and all(not b.icon().isNull() for b in tb.values()), "кнопки языков знакомства: 13, у всех значок")
ed2.tour.finish()
ed2.close()

# --- 1.32, слово владельца: флаги во всех местах выбора языка ------------------------------------------------
from PyQt6.QtWidgets import QMenu
globe_key = icons.icon("globe").pixmap(16, 16).toImage()


def flag_or_globe(code, ic):
    """У языка с флагом: его флаг; «Как в системе» (auto) и арабский: глобус."""
    if ic.isNull():
        return False
    if code in icons.FLAG_CODES:
        return ic.cacheKey() == icons.flag_icon(code).cacheKey()
    return code in ("auto", "ar")


i18n.set_language("ru")
ed3 = EditorWindow(demo_image(), Ctx(), QPoint(0, 0))
ed3.present()
settle()
globe_menu = ed3.language_button.menu()
acts = [a for a in globe_menu.actions() if not a.isSeparator()]
check(len(acts) == 13 and all(flag_or_globe(a.data(), a.icon()) for a in acts), "редактор, глобус: флаг у каждого языка")
# меню языка перевода «На: … ▾» (редактор и окно выделения, общий код translate_ui)
shown = []
real_exec = QMenu.exec
QMenu.exec = lambda m, *a, **k: shown.append(m) or None
try:
    sel2 = RegionSelector(pm, QRect(0, 0, W, H), last_rect=QRect(300, 120, 520, 300))
    sel2.tr_cfg, sel2.tr_save = dict(appmod.DEFAULTS), lambda: None
    sel2._tr_lang_menu_at(QPoint(10, 10), None)
finally:
    QMenu.exec = real_exec
tacts = [a for a in shown[-1].actions() if not a.isSeparator()] if shown else []
check(len(tacts) == 1 + len(translate.TARGETS) and all(flag_or_globe(a.data(), a.icon()) for a in tacts),
      f"меню языка перевода: {len(tacts)} пунктов, флаг у каждого (арабский и «Как в системе»: глобус)")
sel2._done = True
sel2.close()
# настройки: «Переводить на» и «Запасной язык»
dlg2 = SettingsDialog(Ctx().config)
for box, extra in ((dlg2.tr_to, 1), (dlg2.tr_alt, 0)):
    items = [(box.itemData(i), box.itemIcon(i)) for i in range(box.count())]
    check(len(items) == extra + len(translate.TARGETS) and all(flag_or_globe(c, ic) for c, ic in items)
          and box.iconSize().width() == 24, f"настройки, {box is dlg2.tr_to and 'Переводить на' or 'Запасной язык'}: флаг у каждого языка")
dlg2.close()


# меню значка у часов: подменю языка
class TrayApp(Ctx):
    def __init__(self):
        super().__init__()
        self.tray, self.qapp = None, app

    def capture_region(self, **_k):
        pass
    capture_fullscreen = open_screen_recording = open_file = open_folder = open_settings = capture_region
    demo_tour = demo_selector_tour = show_about = show_rating = capture_region
    _build_tray_menu = appmod.Clipshot._build_tray_menu


tray_menu = TrayApp()._build_tray_menu()
sub = next((a.menu() for a in tray_menu.actions() if a.menu() is not None and a.text() == language.menu_title()), None)
sacts = [a for a in sub.actions() if not a.isSeparator()] if sub is not None else []
check(len(sacts) == 13 and all(flag_or_globe(a.data(), a.icon()) for a in sacts), "меню значка у часов: флаг у каждого языка")
ed3.close()

print("FAILURES:", len(failures))
sys.exit(1 if failures else 0)
