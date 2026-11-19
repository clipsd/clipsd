# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
"""Ширина надписей на 12 языках (1.31): панель окна выделения (подписи и пояснения кнопок не обрезаются, слово плитки
помещается в плитку, на экране 1280 панель не уходит в «только значки»), редактор (кнопки не сжаты меньше текста,
окно редактора для маленького снимка не шире 1280), окно настроек (помещается на 1280x720 по ширине),
выбор языка (смена из меню у часов, глобуса редактора, знакомства и настроек; config language записан;
названия языков на самих себе не переводятся).

Шрифт настоящий (системный); CLIPSD_WIDTH_FONT="Segoe UI,9" проверяет с другим шрифтом.
Запуск: QT_QPA_PLATFORM=offscreen python3 tests/i18n_width_test.py
"""
import json
import os
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
os.environ.pop("CLIPSD_LANG", None)   # тест сам перебирает языки
_cfg = os.path.join(tempfile.mkdtemp(prefix="clipsd-i18nw-"), "screen.json")
with open(_cfg, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1600, "height": 1000,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _cfg

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QImage, QPixmap
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QAbstractButton, QApplication, QPushButton, QToolButton

app = QApplication(sys.argv)
if os.environ.get("CLIPSD_WIDTH_FONT"):
    fam, _sep, pt = os.environ["CLIPSD_WIDTH_FONT"].partition(",")
    app.setFont(QFont(fam, int(pt or 9)))
from clipshot import app as appmod, i18n, language
from clipshot.editor import EditorWindow
from clipshot.selector import RegionSelector
from clipshot.settings import SettingsDialog

failures = []
checks = [0]


def check(cond, msg):
    checks[0] += 1
    if not cond:
        failures.append(msg)
        print("FAIL " + msg)


def settle(n=3):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(10)


class Ctx:
    def __init__(self):
        self.config = dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True)
        self.icon = appmod.make_icon()
        self.saved = 0

    def save_config(self):
        self.saved += 1

    def notify(self, text):
        pass


TOP5 = ["record", "full", "ocr", "translate", "translate_pick"]
BOTTOM4 = ["save", "edit", "manual", "copy"]
levels = {}


def selector_case(lang):
    for width in (1280, 800, 480):
        pm = QPixmap(width, 720)
        pm.fill(QColor("#4a78b0"))
        sel = RegionSelector(pm, QRect(0, 0, width, 720), last_rect=QRect(width // 2 - 150, 90, 300, 200))
        sel.tr_cfg, sel.tr_save = dict(appmod.DEFAULTS), lambda: None
        sel.show_zoom = False
        sel.resize(width, 720)
        sel.show()
        settle()
        sel.repaint()
        buttons, bar, _hint = sel._bar_layout()
        lv = sel.bar_level
        levels[(lang, width)] = lv["name"]
        check(bar.width() <= width, f"{lang} {width}: панель шире экрана ({bar.width()})")
        rects = {k: r for k, _t, _s, r in buttons}
        texts = {k: t for k, t, _s, _r in buttons}
        if lv["text"]:
            bl, bs = sel._bar_bfonts(lv)
            fb, fs = QFontMetrics(bl), QFontMetrics(bs)
            for k in BOTTOM4:
                room = rects[k].width() - lv["pl"] - lv["sq"] - lv["gp"] - 4
                check(fb.horizontalAdvance(texts[k]) <= room, f"{lang} {width}: подпись «{texts[k]}» обрезана")
                check(fs.horizontalAdvance(sel.BAR_SUB[k]) <= room, f"{lang} {width}: пояснение «{sel.BAR_SUB[k]}» обрезано")
            label_font, _small = sel._bar_fonts(lv)
            fl = QFontMetrics(label_font)
            for k in TOP5:
                longest = max(texts[k].split(), key=fl.horizontalAdvance)
                check(fl.horizontalAdvance(longest) <= rects[k].width() - 8,
                      f"{lang} {width}: слово «{longest}» шире плитки {rects[k].width()}")
        sel.close()
    check(levels[(lang, 1280)] != "narrow", f"{lang}: на экране 1280 панель без подписей")


def editor_case(lang):
    image = QImage(300, 200, QImage.Format.Format_RGB32)
    image.fill(QColor("#ffffff"))
    ed = EditorWindow(image, Ctx(), QPoint(0, 0))
    ed.present()
    settle()
    check(ed.width() <= 1280, f"{lang}: редактор для снимка 300x200 шире 1280 ({ed.width()})")
    for host in (ed.panel, ed.bottom):
        for w in host.findChildren(QAbstractButton):
            if w.isVisible() and w.text().strip():
                fm = w.fontMetrics()
                need = fm.horizontalAdvance(w.text().replace("&", ""))
                check(w.width() >= need, f"{lang}: кнопка «{w.text().strip()}» уже текста ({w.width()} < {need})")
    # ластик и режим текста на маленьком снимке: подписи кнопок не обрезаются (раньше ряд палитры сжимал их)
    from clipshot.editor import ERASER, MOVE, OCR
    for tool in (ERASER, OCR):
        ed.select_tool(tool) if tool != OCR else ed.set_text_mode("marker")
        if tool == OCR:
            ed._set_mode_ui(OCR)
            ed.text_mode_box.setVisible(True)
        settle()
        hosts = (ed.panel,) if tool == ERASER else (ed.text_bottom,)
        for host in hosts:
            for w in host.findChildren(QAbstractButton):
                if w.isVisible() and w.text().strip():
                    need = w.fontMetrics().horizontalAdvance(w.text().replace("&", ""))
                    check(w.width() >= need, f"{lang} {tool}: кнопка «{w.text().strip()}» уже текста ({w.width()} < {need})")
        ed.select_tool(MOVE)
        settle()
    ed.close()


def settings_case(lang):
    dlg = SettingsDialog(dict(appmod.DEFAULTS))
    dlg.show()
    settle()
    check(dlg.width() <= 1280, f"{lang}: настройки шире 1280 ({dlg.width()})")
    dlg.close()


for lang in i18n.LANGUAGES:
    i18n.set_language(lang)
    selector_case(lang)
    editor_case(lang)
    settings_case(lang)

# --- выбор языка из разных окон (раздел 7 плана) ---------------------------------------
names = set(i18n.LANGUAGE_NAMES.values())
i18n.set_language("ru")
ctx = Ctx()
image = QImage(300, 200, QImage.Format.Format_RGB32)
image.fill(QColor("#ffffff"))
ed = EditorWindow(image, ctx, QPoint(0, 0))
ed.present()
settle()
menu = ed.language_button.menu()
labels = [a.text() for a in menu.actions() if not a.isSeparator()]
check(names <= set(labels), f"глобус редактора: языки на самих себе {labels}")
check(ed.language_button.toolTip() == "Язык · Language", f"подпись глобуса {ed.language_button.toolTip()}")
de = next(a for a in menu.actions() if a.data() == "de")
de.trigger()
ed.retranslate()
settle()
check(i18n.current() == "de" and ctx.config["language"] == "de", "глобус редактора: язык de выбран и записан в config")
check(ed.save_button.text().strip() == i18n.tr_in("de", "editor.save"), f"редактор перестроен на de: {ed.save_button.text()}")
check(ed.language_button.toolTip() == "Sprache · Language", f"подпись глобуса на de {ed.language_button.toolTip()}")
check(ed.titlebar is None or (ed.titlebar.min_button.toolTip() == i18n.tr_in("de", "editor.minimize")
      and ed.titlebar.close_button.toolTip() == i18n.tr_in("de", "editor.close")
      and ed.titlebar.max_button.toolTip() == i18n.tr_in("de", "editor.maximize")), "шапка редактора на de")
labels_de = [a.text() for a in ed.language_button.menu().actions() if not a.isSeparator()]
check(names <= set(labels_de), "названия языков не переводятся при смене языка")
# знакомство: первый шаг с выбором языка
ed.start_tour()
settle()
tour = ed.tour
check(tour.index == 0 and tour.lang_row.isVisible() and not tour.hole.isValid(), "знакомство: первый экран: выбор языка")
check({b.text() for b in tour.lang_buttons.values()} >= names, "знакомство: языки на самих себе")
check(all(b.width() >= b.fontMetrics().horizontalAdvance(b.text()) for b in tour.lang_buttons.values()),
      "знакомство: названия языков помещаются в кнопки")
check(tour.card.geometry().bottom() <= tour.rect().bottom(), "знакомство: карточка выбора языка помещается в окно")
tour.lang_buttons["bg"].click()
settle()
check(i18n.current() == "bg" and ctx.config["language"] == "bg", "знакомство: язык bg выбран и записан")
check(tour.lang_buttons["bg"].isChecked() and tour.next.text() == i18n.tr_in("bg", "tour.next")
      and tour.title.text() == "Език · Language", "знакомство перешло на bg")
tour.forward()
settle()
check(tour.title.text() == i18n.tr_in("bg", "tour.intro_title") and not tour.lang_row.isVisible(), "второй экран: знакомство на bg")
tour.show_step(2)
settle()
check(tour.hole.isValid(), "третий шаг: подсветка на новой панели")
tour.finish()
ed.close()
# настройки
dlg = SettingsDialog(ctx.config)
dlg.language.setCurrentIndex(dlg.language.findData("en"))
check(dlg.values()["language"] == "en", "настройки: язык в values()")
check(names <= {dlg.language.itemText(i) for i in range(dlg.language.count())}, "настройки: языки на самих себе")


# меню у часов: приложение без трея и окон, только меню
class FakeApp(Ctx):
    def __init__(self):
        super().__init__()
        self.editors, self.tray, self.qapp = [], None, app

    set_language = appmod.Clipshot.set_language
    _build_tray_menu = appmod.Clipshot._build_tray_menu

    def capture_region(self, **_k): pass
    capture_fullscreen = open_screen_recording = open_file = open_folder = open_settings = capture_region
    demo_tour = show_about = capture_region


appmod.CONFIG_PATH = __import__("pathlib").Path(tempfile.mkdtemp(prefix="clipsd-i18nw-cfg-")) / "config.json"
fake = FakeApp()
fake.save_config = appmod.Clipshot.save_config.__get__(fake)
tray_menu = fake._build_tray_menu()
sub = next(a.menu() for a in tray_menu.actions() if a.menu() is not None)
check(sub.title() == "Език · Language", f"меню у часов: «{sub.title()}»")
uk = next(a for a in sub.actions() if a.data() == "uk")
uk.trigger()
saved = json.loads(appmod.CONFIG_PATH.read_text(encoding="utf-8"))
check(i18n.current() == "uk" and saved["language"] == "uk", "меню у часов: язык uk выбран и записан в файл настроек")
i18n.set_language("en")
check(language.menu_title() == "Language · Язык", f"на английском: {language.menu_title()}")
# старые установки: файл без поля language остаётся на русском, новой установки нет файла: язык системы
check(language.config_choice({"tool": "arrow"}, True) == "ru", "файл 1.x без language: русский")
check(language.config_choice(None, False) == "auto", "новая установка: язык системы")
check(language.config_choice({"language": "de"}, True) == "de", "выбранный язык из файла")
# язык установщика Windows (ClipSD.iss пишет installer-language при новой установке)
import tempfile as _tf  # noqa: E402
from pathlib import Path as _P  # noqa: E402
_d = _P(_tf.mkdtemp(dir=os.environ.get("TMPDIR")))
check(language.config_choice(None, False, _d) == "auto", "нет файла установщика: язык системы")
_other = "de" if i18n.system_language() != "de" else "fr"
(_d / "installer-language").write_text(_other + "\r\n", encoding="utf-8")
check(language.config_choice(None, False, _d) == _other, f"новая установка: язык установщика ({_other})")
check(language.config_choice({"tool": "arrow"}, True, _d) == "ru", "файл настроек есть: установщик не в счёт")
check(language.config_choice({"language": "it"}, True, _d) == "it", "выбор в настройках важнее установщика")
(_d / "installer-language").write_text(i18n.system_language(), encoding="utf-8")
check(language.config_choice(None, False, _d) == "auto", "язык установщика совпал с системой: auto")
(_d / "installer-language").write_text("xx", encoding="utf-8")
check(language.config_choice(None, False, _d) == "auto", "мусор в файле установщика: auto")
check(language.early_choice(_d / "config.json") == "auto", "early_choice без config.json читает файл установщика")

print("Уровни панели (язык, ширина экрана):", {f"{k[0]}:{k[1]}": v for k, v in levels.items() if k[1] != 480})
print(f"ИТОГ: проверок {checks[0]}, провалено: {len(failures)}")
sys.exit(1 if failures else 0)
