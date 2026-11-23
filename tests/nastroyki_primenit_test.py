# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Окно настроек: кнопки «ОК», «Отмена», «Применить» (как в Windows).

Проверяется:
- «Применить» неактивна, пока в окне нет изменений; применяет всё изменённое, окно остаётся открытым, после применения
  снова неактивна, рядом серое «Применено»;
- «Отмена» после «Применить» не откатывает применённое; «Отмена» без «Применить» ничего не применяет и возвращает
  язык и вид (предпросмотр); крестик, как «Отмена»;
- «ОК» применяет и закрывает;
- каждая настройка действительно действует после «Применить», без перезапуска (по возможности смотрим эффект:
  сочетание, трей, путь и формат снимка, расписание обновлений, оформление открытого редактора, язык);
- ошибка сочетания (занято): понятное сообщение в окне, остальные изменения применены, «ОК» не закрывает окно;
- на 12 языках кнопки помещаются в окно 813x420 (1280x720 при 150%), есть строки «ОК», «Применить», «Применено».

Запуск: python3 tests/nastroyki_primenit_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
tmp = tempfile.mkdtemp(prefix="clipsd-prim-")
os.environ["XDG_CONFIG_HOME"] = os.path.join(tmp, "config")
os.environ.pop("CLIPSD_LANG", None)   # язык меняется в самом тесте (предпросмотр в настройках)
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QPoint, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QImage  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QDialog, QSystemTrayIcon  # noqa: E402

app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)

from clipshot import app as appmod  # noqa: E402
from clipshot import hidpi, i18n, novoe, settings as st, themes, translate, updater  # noqa: E402
from clipshot.editor import EditorWindow, frame_style  # noqa: E402
from clipshot.i18n import tr  # noqa: E402

failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def settle():
    for _ in range(4):
        app.processEvents()


# --- подмены: GNOME и автозапуск не трогают систему ----------------------------------------------------
class FakeGnome:
    available = staticmethod(lambda: True)
    calls = []
    fail = None

    def apply(self, region, full, both_layouts=True):
        if FakeGnome.fail:
            raise RuntimeError(FakeGnome.fail)
        FakeGnome.calls.append((region, full, both_layouts))


autostart_state = {"on": False, "calls": []}
st.GnomeHotkeys = FakeGnome
st.autostart_enabled = lambda: autostart_state["on"]


def fake_set_autostart(value):
    autostart_state["calls"].append(value)
    autostart_state["on"] = value


st.set_autostart = fake_set_autostart

i18n.set_language("ru")
ctx = appmod.Clipshot(app)
ctx.config["language"] = "ru"
ctx.config["auto_save_dir"] = os.path.join(tmp, "auto0")
ctx.save_config()


def open_dialog():
    """Окно, как его открывает open_settings, но без exec(): тест сам нажимает кнопки."""
    dlg = st.SettingsDialog(ctx.config)
    dlg.update_ctx = ctx
    dlg.apply_handler = ctx.apply_settings
    ctx._settings = dlg
    dlg.show()
    settle()
    return dlg


def close_dialog(dlg):
    ctx._settings = None
    dlg.close()
    settle()


def disk():
    return appmod.load_config()


# --- 1. кнопки и состояние ---------------------------------------------------------------------------
dlg = open_dialog()
check(dlg.ok_button.text() == tr("settings.ok") and dlg.cancel_button.text() == tr("settings.cancel")
      and dlg.apply_button.text() == tr("settings.apply") == "Применить", "кнопки: «ОК», «Отмена», «Применить»")
xs = [dlg.ok_button.x(), dlg.cancel_button.x(), dlg.apply_button.x()]
check(xs == sorted(xs), f"порядок как в Windows: ОК, Отмена, Применить ({xs})")
check(not dlg.apply_button.isEnabled(), "«Применить» неактивна, пока нет изменений")
dlg.show_zoom.setChecked(not dlg.show_zoom.isChecked())
check(dlg.apply_button.isEnabled(), "правка включила «Применить»")
dlg.show_zoom.setChecked(not dlg.show_zoom.isChecked())
check(not dlg.apply_button.isEnabled(), "правка возвращена: «Применить» снова неактивна")
dlg.show_section("editor")
check(not dlg.apply_button.isEnabled(), "смена раздела не считается правкой")

# --- 2. «Применить»: действует, окно открыто, снова неактивна --------------------------------------------
before = ctx.config["show_zoom"]
dlg.show_zoom.setChecked(not before)
dlg.apply_button.click()
settle()
check(ctx.config["show_zoom"] is (not before) and disk()["show_zoom"] is (not before), "«Применить»: настройка в приложении и в файле")
check(dlg.isVisible() and dlg.result() != QDialog.DialogCode.Accepted, "окно осталось открытым")
check(not dlg.apply_button.isEnabled() and dlg.apply_note.text() == tr("settings.applied"),
      "после применения «Применить» неактивна, рядом «Применено»")
dlg.tray_click.setCurrentIndex(1)
check(dlg.apply_note.text() == "" and dlg.apply_button.isEnabled(), "новая правка: «Применено» убрано, кнопка активна")

# --- 3. «Отмена» после «Применить» не откатывает ---------------------------------------------------------
dlg.apply_button.click()
settle()
dlg.remember.setChecked(not dlg.remember.isChecked())    # ещё не применено
unapplied = dlg.remember.isChecked()
dlg.cancel_button.click()
settle()
ctx._settings = None
check(ctx.config["tray_click"] == "menu" and disk()["tray_click"] == "menu", "«Отмена» после «Применить»: применённое осталось")
check(ctx.config["remember_region"] is not unapplied and disk()["remember_region"] is not unapplied,
      "«Отмена»: неприменённая правка не применена")
check(not dlg.isVisible(), "«Отмена» закрыла окно, ничего не спрашивая")
ctx.config["tray_click"] = "region"

# --- 4. предпросмотр вида и языка, «Отмена» возвращает -----------------------------------------------------
dlg = open_dialog()
light_style = dlg.styleSheet()
dlg.ui_theme.setCurrentIndex(dlg.ui_theme.findData("pro"))
settle()
dark_style = st.settings_style(themes.tokens({"ui_theme": "pro"}))
check(dlg.styleSheet() == dark_style and dlg.styleSheet() != light_style, "вид: тёмный показан сразу, как предпросмотр")
check(ctx.config.get("ui_theme") != "pro" and disk().get("ui_theme") != "pro", "вид: пока не применён, в настройках прежний")
dlg.language.setCurrentIndex(dlg.language.findData("en"))
settle()
check(i18n.current() == "en" and dlg.apply_button.text() == "Apply", "язык: английский показан сразу, окно перестроено")
dlg.cancel_button.click()
settle()
ctx._settings = None
check(i18n.current() == "ru" and ctx.config["language"] == "ru" and disk()["language"] == "ru",
      "«Отмена» без «Применить»: язык вернулся на русский")
check(dlg.styleSheet() == light_style and ctx.config.get("ui_theme") != "pro", "«Отмена»: вид вернулся светлый")
settle()

# крестик = «Отмена»
dlg = open_dialog()
dlg.language.setCurrentIndex(dlg.language.findData("de"))
settle()
check(i18n.current() == "de", "язык: немецкий показан сразу")
dlg.close()
settle()
ctx._settings = None
check(i18n.current() == "ru" and ctx.config["language"] == "ru", "крестик вернул язык, как «Отмена»")

# язык применён: «Отмена» не возвращает
dlg = open_dialog()
dlg.language.setCurrentIndex(dlg.language.findData("en"))
settle()
dlg.apply_button.click()
settle()
dlg.cancel_button.click()
settle()
ctx._settings = None
check(i18n.current() == "en" and ctx.config["language"] == "en" and disk()["language"] == "en",
      "язык применён кнопкой: «Отмена» его не откатывает")
ctx.set_language("ru")
settle()

# вид применён
dlg = open_dialog()
dlg.ui_theme.setCurrentIndex(dlg.ui_theme.findData("pro"))
dlg.apply_button.click()
settle()
check(ctx.config["ui_theme"] == "pro" and themes.name(ctx.config) == "pro", "вид: после «Применить» тёмный в настройках приложения")
dark_applied = dlg.styleSheet()
dlg.cancel_button.click()
settle()
ctx._settings = None
check(ctx.config["ui_theme"] == "pro" and dlg.styleSheet() == dark_applied, "вид: «Отмена» после «Применить» тёмный оставила")
ctx.config["ui_theme"] = "standard"
ctx.config["ui_accent"] = ctx.config["ui_panel"] = ctx.config["ui_field"] = None

# --- 5. «ОК» -------------------------------------------------------------------------------------------
dlg = open_dialog()
dlg.show_size.setChecked(not dlg.show_size.isChecked())
want = dlg.show_size.isChecked()
dlg.ok_button.click()
settle()
ctx._settings = None
check(dlg.result() == QDialog.DialogCode.Accepted and not dlg.isVisible(), "«ОК» закрывает окно")
check(ctx.config["show_size"] is want and disk()["show_size"] is want, "«ОК» применил")
dlg = open_dialog()    # без правок «ОК» просто закрывает
dlg.ok_button.click()
settle()
ctx._settings = None
check(dlg.result() == QDialog.DialogCode.Accepted, "«ОК» без правок закрывает")

# --- 6. каждая настройка действует после «Применить» -------------------------------------------------------
FakeGnome.calls.clear()
img = QImage(120, 80, QImage.Format.Format_RGB32)
img.fill(QColor("#336699"))
ed = EditorWindow(img, ctx, QPoint(0, 0))
ed.present()
ctx.editors.append(ed)
settle()
tray_calls = []
ctx.capture_region = lambda **kw: tray_calls.append(kw)

dlg = open_dialog()
dlg.key_region.set_hotkey("Ctrl+Shift+X")
dlg.key_full.set_hotkey("Alt+F")
dlg.both_layouts.setChecked(False)
dlg.show_zoom.setChecked(False)
dlg.show_size.setChecked(False)
dlg.remember.setChecked(False)
ctx.config["last_region"] = [1, 2, 30, 40]
dlg.ocr_enabled.setChecked(False)
dlg.ocr_quality.setCurrentIndex(dlg.ocr_quality.findData("fast"))
dlg.ocr_langs.setCurrentIndex(dlg.ocr_langs.findData("eng"))
dlg.tr_enabled.setChecked(False)
dlg.tr_to.setCurrentIndex(dlg.tr_to.findData("de"))
dlg.tr_alt.setCurrentIndex(dlg.tr_alt.findData("fr"))
dlg.tr_engine.setCurrentIndex(dlg.tr_engine.findData("google"))
dlg.tr_email.setText("prim@example.org")
dlg.tray_click.setCurrentIndex(dlg.tray_click.findData("menu"))
shots = os.path.join(tmp, "shots1")
dlg.save_dir.setText(shots)
dlg.save_format.setCurrentIndex(dlg.save_format.findData("jpg"))
dlg.save_ask.setChecked(True)
dlg.auto_save.setChecked(True)
auto = os.path.join(tmp, "auto1")
dlg.auto_save_dir.setText(auto)
dlg.snapshot_size.setCurrentIndex(dlg.snapshot_size.findData(hidpi.SIZE_SCREEN))
dlg.clip_html.setChecked(not dlg.clip_html.isChecked())
dlg.autostart.setChecked(True)
dlg.update_check.setChecked(False)
dlg.novoe_enabled.setChecked(False)
dlg._show_color("ui_accent", "#8b3dff")
dlg._show_color("ui_panel", "#b0b4ba")
dlg.frame.setCurrentIndex(dlg.frame.findData(12))
dlg.frame_style.setCurrentIndex(dlg.frame_style.findData("thick"))
dlg.system_title.setChecked(True)
dlg.apply_button.click()
settle()
c = ctx.config
check(FakeGnome.calls == [("Ctrl+Shift+X", "Alt+F", False)], f"сочетания: переданы системе сразу ({FakeGnome.calls})")
check(c["hotkey_region"] == "Ctrl+Shift+X" and c["hotkey_fullscreen"] == "Alt+F" and c["hotkey_both_layouts"] is False,
      "сочетания: в настройках")
check(ctx._tray_tip().count("Ctrl+Shift+X") == 1, "сочетание: подсказка у значка обновилась")
check(c["show_zoom"] is False and c["show_size"] is False, "выделение: лупа и размер выключены в настройках")
check(ctx._last_region() is None, "выделение: прошлая область не предлагается (эффект)")
check(c["ocr_enabled"] is False and c["ocr_quality"] == "fast" and c["ocr_langs"] == "eng", "распознавание: в настройках")
check(c["translate_enabled"] is False and translate.target_lang(c) == "de"
      and translate.alt_lang(c, "de") == "fr" and c["translate_engine"] == "google"
      and c["translate_email"] == "prim@example.org", "перевод: язык, запасной язык, сервис, почта (эффект)")
ctx._on_tray_activated(QSystemTrayIcon.ActivationReason.Trigger)
check(tray_calls == [], "трей: щелчок по значку больше не делает снимок (эффект)")
dlg.tray_click.setCurrentIndex(dlg.tray_click.findData("region"))
dlg.apply_button.click()
ctx._on_tray_activated(QSystemTrayIcon.ActivationReason.Trigger)
check(len(tray_calls) == 1, "трей: «снимок области» возвращён, щелчок снова делает снимок (эффект)")
path = ctx.snapshot_path()
check(os.path.dirname(path) == auto and path.endswith(".jpg") and os.path.isdir(auto),
      f"сохранение: папка и формат следующего снимка новые (эффект): {path}")
check(c["save_dir"] == shots and c["save_ask"] is False and c["auto_save"] is True, "сохранение: папка, вопрос, автосохранение")
check(hidpi.size_mode(c) == hidpi.SIZE_SCREEN and c["clip_html"] is (not hidpi.html_default()),
      "размер снимка и HTML в буфер: действуют")
check(autostart_state["calls"] == [True] and autostart_state["on"], "автозапуск: включён сразу (эффект)")
now = datetime.now(timezone.utc)
check(updater.should_check(c, now) is False and c["update_check"] is False,
      "обновления: автопроверка выключена, расписание её не запускает (эффект)")
check(novoe.enabled(c) is False, "новинки: выключены (эффект)")
check("#8b3dff" in ed.styleSheet() and ed.frame_px == 12, "оформление: цвета и рамка в уже открытом редакторе (эффект)")
check(frame_style(c) == "thick", "вид рамки: толстая (читает редактор)")
check(c["editor_system_title"] is True, "системный заголовок: включён (для новых окон, как сказано в подсказке)")
check(disk()["translate_to"] == "de" and disk()["update_check"] is False, "всё записано в файл")
check(not dlg.apply_button.isEnabled(), "после применения всех правок «Применить» неактивна")
dlg.ui_theme.setCurrentIndex(dlg.ui_theme.findData("pro"))
dlg.apply_button.click()
settle()
check(themes.name(c) == "pro" and themes.tokens(c)["dark"], "тёмный вид применён к приложению")
close_dialog(dlg)
ed.close()
ctx.editors.clear()

# --- 7. ошибка сочетания --------------------------------------------------------------------------------
dlg = open_dialog()
FakeGnome.calls.clear()
FakeGnome.fail = "сочетание занято другой программой"
old_region = ctx.config["hotkey_region"]
dlg.key_region.set_hotkey("Super+Q")
dlg.show_zoom.setChecked(True)
dlg.apply_button.click()
settle()
msg = dlg.apply_error.text()
check(dlg.apply_error.isVisible() and "сочетание занято другой программой" in msg
      and msg.startswith(tr("app.gnome_hotkey_failed", error="").strip(" :")), f"ошибка сочетания: сообщение в окне ({msg!r})")
check(ctx.config["show_zoom"] is True and disk()["show_zoom"] is True, "ошибка сочетания: остальное применено")
check(ctx.config["hotkey_region"] == old_region, "ошибка сочетания: в настройках осталось прежнее")
check(dlg.apply_button.isEnabled(), "ошибка сочетания: «Применить» остаётся для повтора")
dlg.ok_button.click()
settle()
check(dlg.isVisible() and dlg.result() != QDialog.DialogCode.Accepted, "«ОК» при ошибке окно не закрывает")
FakeGnome.fail = None
dlg.apply_button.click()
settle()
check(not dlg.apply_error.isVisible() and ctx.config["hotkey_region"] == "Super+Q"
      and FakeGnome.calls and FakeGnome.calls[-1][0] == "Super+Q", "повтор «Применить» без ошибки: сочетание назначено, сообщение ушло")
# «занято» из потока клавиш (Windows, X11): приходит в окно
ctx._show_hotkey_error("Сочетание \"Alt+W\" занято другой программой")
check(dlg.apply_error.isVisible() and "занято" in dlg.apply_error.text(), "«занято» из потока клавиш показано в окне настроек")
close_dialog(dlg)

# --- 8. 12 языков: строки и размеры ----------------------------------------------------------------------
for lang in i18n.LANGUAGES:
    ok, ap, done = (i18n.tr_in(lang, k) for k in ("settings.ok", "settings.apply", "settings.applied"))
    check(all(v and not v.startswith("settings.") for v in (ok, ap, done)) and len({ok, ap, done}) == 3,
          f"{lang}: «{ok}», «{ap}», «{done}»")
    i18n.set_language(lang)
    d = st.SettingsDialog(dict(appmod.DEFAULTS, language=lang))
    d.resize(813, 420)
    d.show()
    settle()
    row_w = sum(b.sizeHint().width() for b in (d.ok_button, d.cancel_button, d.apply_button))
    fits = all(b.width() >= b.fontMetrics().horizontalAdvance(b.text()) for b in (d.ok_button, d.cancel_button, d.apply_button))
    check(fits and d.apply_button.geometry().right() <= d.width() and row_w < 600,
          f"{lang}: три кнопки помещаются в окно 813x420 (ряд {row_w})")
    d.apply_note.setText(done)
    check(d.ok_button.y() + d.ok_button.height() <= d.height(), f"{lang}: кнопки внутри окна по высоте")
    d.close()
i18n.set_language("ru")
ctx.config.pop("language", None)

print()
print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено {len(failures)}")
from clipshot.exitutil import quick_exit  # noqa: E402
quick_exit(1 if failures else 0)
