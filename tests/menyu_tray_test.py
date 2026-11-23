# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""1.36: меню значка у часов: значки у всех пунктов, разделы, подменю «Обучение» и «Справка», действия те же,
сочетание из настроек, 12 языков без обрезки, обе темы.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/menyu_tray_test.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.pop("CLIPSD_LANG", None)   # язык задаёт сам тест

from PyQt6.QtCore import QObject  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
from clipshot import app as appmod, i18n  # noqa: E402
from clipshot.i18n import tr  # noqa: E402

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


class Fake(QObject):
    """Минимум от Clipshot для _build_tray_menu: обработчики подменены и пишут вызов в журнал."""

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.qapp = app
        self.calls = []
        for name in ("capture_region", "capture_fullscreen", "open_screen_recording", "open_phone", "open_file",
                     "open_folder", "open_settings", "open_oznakomlenie", "show_novoe", "demo_tour",
                     "demo_selector_tour", "show_rating", "show_about"):
            setattr(self, name, (lambda n: lambda *a, **k: self.calls.append(n))(name))
        self.qapp = type("Q", (), {"quit": staticmethod(lambda: self.calls.append("quit"))})()

    def set_language(self, choice):
        self.calls.append("lang:" + choice)


def build(cfg):
    fake = Fake(cfg)
    return fake, appmod.Clipshot._build_tray_menu(fake)


def flat(menu):
    return [a for a in menu.actions()]


for dark in (False, True):
    for lang in i18n.LANGUAGES:
        i18n.set_language(lang)
        cfg = dict(appmod.DEFAULTS)
        cfg["hotkey_region"] = "Ctrl+Shift+S"
        cfg["hotkey_fullscreen"] = "Alt+F"
        cfg["ui_theme"] = "pro" if dark else "standard"
        cfg["language"] = lang
        fake, menu = build(cfg)
        tag = f"{lang}/{'тёмная' if dark else 'светлая'}"
        acts = flat(menu)
        items = [a for a in acts if not a.isSeparator() and not a.property("clipsd_section")]
        check(all(not a.icon().isNull() for a in items), f"{tag}: у всех пунктов верхнего уровня есть значок")
        subs = [a for a in items if a.menu() is not None]
        for sa in subs:
            check(all(not x.icon().isNull() for x in sa.menu().actions() if not x.isSeparator() and x.menu() is None),
                  f"{tag}: значки в подменю «{sa.text()}»")
        if lang == "ru" and not dark:
            order = [("sep" if a.isSeparator() else ("sec:" + a.text() if a.property("clipsd_section") else a.text()))
                     for a in acts]
            check(order[0] == "sec:Снимок" and order[1].startswith("Область экрана\tCtrl+Shift+S"), "ru: раздел «Снимок», первым «Область экрана» с клавишей из настроек")
            check(acts[1].font().bold() and not acts[2].font().bold(), "жирный только «Область экрана»")
            check(acts[2].text() == "Весь экран\tAlt+F", "«Весь экран» с сочетанием из настроек")
            check([a.text() for a in acts[3:6]] == ["Запись видео", "Скриншот/фото с телефона", "Открыть изображение…"], "порядок группы «Снимок»")
            check("sec:Инструменты" in order and order.index("sec:Инструменты") > order.index("Открыть изображение…"), "раздел «Инструменты» после снимков")
            check(order.index("Папка со снимками") < order.index("Настройки…") < order.index("Обучение"), "папка, настройки, затем подменю")
            check(order.index("Обучение") < order.index("Справка") < order.index("Язык · Language") < order.index("Выход"), "Обучение, Справка, Язык, Выход")
            check(order[-1] == "Выход", "«Выход» последний")
            learn = next(a for a in acts if a.text() == "Обучение").menu()
            check([a.text() for a in learn.actions()] == ["Ознакомление", "Что нового", "Знакомство с программой",
                                                          "Знакомство с окном выделения"], "подменю «Обучение»")
            helpm = next(a for a in acts if a.text() == "Справка").menu()
            check([a.text() for a in helpm.actions()] == ["Проверить обновления", "Оценить ClipSD", "О программе"], "подменю «Справка»")
            # действия вызывают прежние обработчики
            want = {"Область экрана\tCtrl+Shift+S": "capture_region", "Весь экран\tAlt+F": "capture_fullscreen",
                    "Запись видео": "open_screen_recording", "Скриншот/фото с телефона": "open_phone",
                    "Открыть изображение…": "open_file", "Папка со снимками": "open_folder", "Настройки…": "open_settings",
                    "Ознакомление": "open_oznakomlenie", "Что нового": "show_novoe", "Знакомство с программой": "demo_tour",
                    "Знакомство с окном выделения": "demo_selector_tour", "Оценить ClipSD": "show_rating",
                    "О программе": "show_about", "Выход": "quit"}
            everything = acts + learn.actions() + helpm.actions()
            for text, handler in want.items():
                a = next(x for x in everything if x.text() == text)
                fake.calls.clear()
                a.trigger()
                check(fake.calls == [handler], f"«{text.split(chr(9))[0]}» вызывает {handler} (получено {fake.calls})")
            # без сочетания подписи без табуляции
            cfg2 = dict(cfg, hotkey_region="", hotkey_fullscreen="")
            _f, m2 = build(cfg2)
            check(all("\t" not in a.text() for a in m2.actions()), "без сочетаний табуляции в подписях нет")
        # без обрезки: ширина меню вмещает самый длинный пункт
        menu.ensurePolished()
        menu.adjustSize()
        fm = menu.fontMetrics()
        longest = max(fm.horizontalAdvance(a.text().split("\t")[0]) for a in items)
        check(menu.sizeHint().width() >= longest + 40, f"{tag}: ширина меню {menu.sizeHint().width()} вмещает самый длинный пункт ({longest})")
        for sa in subs:
            sm = sa.menu()
            sm.adjustSize()
            lg = max(fm.horizontalAdvance(a.text().split("\t")[0]) for a in sm.actions() if not a.isSeparator())
            check(sm.sizeHint().width() >= lg + 40, f"{tag}: подменю «{sa.text()}» без обрезки")
        # ключи переведены: тексты разделов не равны ключам
        for key in ("app.menu_sec_capture", "app.menu_sec_tools", "app.menu_learn", "app.menu_help"):
            check(tr(key) != key, f"{tag}: перевод {key}")

print("ИТОГ:", "ВСЁ ХОРОШО" if not failures else f"{len(failures)} провалов")
sys.exit(1 if failures else 0)
