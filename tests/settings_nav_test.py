# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""1.32: окно настроек по разделам: меню слева, страницы справа, поиск, запоминание раздела, размер не больше 860x620,
светлое и тёмное оформление, все прежние настройки на месте.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/settings_nav_test.py
"""
import os
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
os.environ.pop("CLIPSD_LANG", None)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QPushButton

app = QApplication(sys.argv)
from clipshot import app as appmod, i18n
from clipshot.settings import SettingsDialog

failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def settle(n=4):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(10)


i18n.set_language("ru")
dlg = SettingsDialog(dict(appmod.DEFAULTS))
dlg.show()
settle()
check(list(dlg.pages) == ["general", "shot", "editor", "text", "updates", "about"], "шесть разделов")
check(dlg.width() <= 860 and dlg.height() <= 620, f"окно не больше 860x620 ({dlg.width()}x{dlg.height()})")
check(all(b.isVisible() for b in dlg.nav_buttons.values()), "все разделы в меню слева")
old_keys = {"hotkey_region", "hotkey_fullscreen", "hotkey_both_layouts", "show_zoom", "show_size", "remember_region",
            "ocr_enabled", "translate_enabled", "translate_to", "translate_alt", "translate_engine", "translate_email",
            "ocr_quality", "ocr_langs", "tray_click", "save_dir", "save_format", "save_ask", "auto_save", "auto_save_dir",
            "autostart", "update_check", "ui_accent", "ui_panel", "ui_field", "ui_frame", "editor_frame_style",
            "editor_system_title", "ui_theme", "language"}
check(old_keys <= set(dlg.values()), "все прежние настройки в values()")
where = {}
for key, (scroll, _l) in dlg.pages.items():
    for name in ("key_region", "show_zoom", "ocr_enabled", "tr_engine", "tray_click", "save_dir", "ui_theme", "update_check", "language"):
        w = getattr(dlg, name)
        if scroll.widget().isAncestorOf(w):
            where[name] = key
check(where == {"key_region": "general", "language": "general", "tray_click": "general", "show_zoom": "shot", "save_dir": "shot",
                "ui_theme": "editor", "ocr_enabled": "text", "tr_engine": "text", "update_check": "updates"}, f"настройки по разделам: {where}")


def hits(q):
    dlg.search.setText(q)
    settle(6)
    return {k for k, b in dlg.nav_buttons.items() if b.isVisible()}


check({"general", "text"} <= hits("язык"), "поиск «язык»: основное и текст")
check("general" in hits("Alt+W"), "поиск «Alt+W»: основное (горячие клавиши)")
check(dlg.current_section() == "general" and any(w.property("found") for w in dlg._found_widgets), "найденное подсвечено")
check("text" in hits("перевод"), "поиск «перевод»: текст и перевод")
check(dlg.current_section() == "text", "поиск переключил на раздел с совпадением")
check("updates" in hits("обнов"), "поиск «обнов»: обновления")
check("updates" in hits("update") and "text" in hits("ocr"), "поиск по английским словам на русском интерфейсе")
check(hits("zzzzqq") == set() and dlg.search_none.isVisible(), "ничего не найдено: сообщение")
check(hits("") == set(dlg.pages) and not dlg.search_none.isVisible() and not dlg._found_widgets, "пустой запрос: всё как было")
# раздел запоминается
dlg.show_section("editor")
check(dlg.values()["settings_page"] == "editor", "values(): последний раздел")
dlg2 = SettingsDialog(dict(appmod.DEFAULTS, settings_page="text"))
dlg2.show()
settle()
check(dlg2.current_section() == "text" and dlg2.nav_buttons["text"].isChecked(), "новое окно открывается на прошлом разделе")
dlg2.close()
# знакомство из «О программе»
dlg.show_section("about")
dlg.tour_selector_button.click()
check(dlg.want_selector_tour and not dlg.want_tour and dlg.result() == dlg.DialogCode.Accepted, "кнопка знакомства с окном выделения")
# тёмное оформление и узкое окно
dark = SettingsDialog(dict(appmod.DEFAULTS, ui_theme="pro"))
dark.show()
settle()
check("#" in dark.styleSheet() and "QFrame#nav" in dark.styleSheet() and "rgba" in dark.styleSheet(), "явные цвета меню в стиле окна")
check(dark.nav.palette().window().color().name() is not None and dark.width() <= 860, "тёмное окно строится")
dark.resize(640, 420)
settle()
buttons = [b for b in dark.findChildren(QPushButton) if b.text() in ("ОК", "Отмена", "Применить")]
check(len(buttons) == 3 and all(b.isVisible() and dark.rect().contains(b.geometry()) for b in buttons), "узкое окно: кнопки на виду")
for code in i18n.LANGUAGES:
    i18n.set_language(code)
    d = SettingsDialog(dict(appmod.DEFAULTS, language=code))
    d.show()
    settle(2)
    labels = [b.text() for b in d.nav_buttons.values()]
    check(all(t and not t.startswith("settings.") for t in labels) and d.search.placeholderText() != "settings.search",
          f"{code}: названия разделов и поиск переведены")
    d.close()
# 1280x720 при 150%: окно ~813 px, «Основное» без горизонтальной прокрутки на всех языках
for code in i18n.LANGUAGES:
    i18n.set_language(code)
    d = SettingsDialog(dict(appmod.DEFAULTS, language=code))
    d.resize(813, 420)
    d.show()
    settle(6)
    bad = [k for k, (sc, _l) in d.pages.items() if not d.show_section(k) and (settle(3) or sc.horizontalScrollBar().isVisible())]
    check(not bad, f"{code}: узкое окно 813 px без горизонтальной прокрутки (разделы с полосой: {bad})")
    d.close()
i18n.set_language("ru")
print("FAILURES:", len(failures))
sys.exit(1 if failures else 0)
