# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
"""Автотест настроек ClipSD. Системные настройки не трогает: GNOME подменяется словарём.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/settings_test.py [проект] [временная_папка]
"""

import os
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
project = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(here)
tmp = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="clipsd-test-")
os.makedirs(tmp, exist_ok=True)
os.environ["XDG_CONFIG_HOME"] = os.path.join(tmp, "config")   # настройки теста — во временной папке
sys.path.insert(0, project)

from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QColor, QImage, QKeySequence
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)

from clipshot import app as appmod
from clipshot import settings as st
from clipshot.editor import EditorWindow

failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


# --- сочетания --------------------------------------------------------------
for raw, exp in (("Alt+W", "Alt+W"), ("Alt+Ц", "Alt+W"), ("Meta+Shift+S", "Shift+Super+S"),
                 ("Ctrl+Alt+Print", "Ctrl+Alt+Print"), ("", ""), ("Alt+W, Alt+Q", "Alt+W")):
    check(st.normalize_hotkey(raw) == exp, f"сочетание «{raw}» → «{st.normalize_hotkey(raw)}»")
for hk, exp in (("Alt+W", "<Alt>Cyrillic_tse"), ("Ctrl+Shift+S", "<Primary><Shift>Cyrillic_yeru"),
                ("Alt+F1", ""), ("Alt+5", "")):
    check(st.to_gnome_russian(hk) == exp, f"русская раскладка: «{hk}» → «{st.to_gnome_russian(hk)}»")
for raw, exp in (("Ctrl+PgUp", "Ctrl+PageUp"), ("Alt+Ins", "Alt+Insert"), ("Ctrl+Alt+Х", "Ctrl+Alt+["), ("Alt+ё", "Alt+`")):
    check(st.normalize_hotkey(raw) == exp, f"сочетание «{raw}» → «{st.normalize_hotkey(raw)}»")
for hk, exp in (("Ctrl+Alt+[", "<Primary><Alt>bracketleft"), ("Alt+PageUp", "<Alt>Page_Up"), ("Super+Space", "<Super>space")):
    check(st.to_gnome(hk) == exp, f"GNOME: «{hk}» → «{st.to_gnome(hk)}»")
check(st.to_gnome_russian("Ctrl+Alt+[") == "<Primary><Alt>Cyrillic_ha", "русская раскладка для знака [ → Х")
check(appmod.WinHotkeys.parse("Ctrl+Alt+PageDown") == (0x4000 | 0x2 | 0x1, 0x22), "Windows: Ctrl+Alt+Page Down")
three = st.HotkeyEditor("Ctrl+Alt+W")
check(three.hotkey() == "Ctrl+Alt+W", "сочетание из трёх клавиш в настройках")
three.set_hotkey("Ctrl+Shift+Alt+F5")
check(three.hotkey() == "Ctrl+Shift+Alt+F5", "сочетание из четырёх клавиш с F5")
for hk, exp in (("Alt+W", "<Alt>w"), ("Ctrl+Shift+S", "<Primary><Shift>s"), ("Super+Print", "<Super>Print"), ("", "")):
    check(st.to_gnome(hk) == exp, f"GNOME: «{hk}» → «{st.to_gnome(hk)}»")
check(appmod.WinHotkeys.parse("Shift+Super+S") == (0x4000 | 0x4 | 0x8, 0x53), "Windows понимает Super")


# --- GNOME на подменённом хранилище -----------------------------------------
class FakeGsettings:
    def __init__(self):
        root = st.GNOME_KB_ROOT
        self.data = {
            (st.GNOME_KB, "custom-keybindings"): f"['{root}custom0/', '{root}clipshot/']",
            (f"{st.GNOME_KB}.custom-keybinding:{root}custom0/", "command"): "'gnome-terminal'",
            (f"{st.GNOME_KB}.custom-keybinding:{root}clipshot/", "command"): "'/home/u/.local/bin/clipsd --region'",
            (f"{st.GNOME_KB}.custom-keybinding:{root}clipshot/", "binding"): "'<Alt>w'",
            st.GNOME_SHOT_UI: "['Print', '<Super><Shift>s']",
        }

    def __call__(self, op, schema, key, value=None):
        if op == "get":
            return self.data.get((schema, key), "''")
        self.data[(schema, key)] = value if value.startswith(("[", "@")) else repr(value)
        return ""


fake = FakeGsettings()
st.GnomeHotkeys(run=fake, ext=None).apply("Ctrl+Shift+A", "Print")
root = st.GNOME_KB_ROOT
kb = lambda path, key: fake.data.get((f"{st.GNOME_KB}.custom-keybinding:{root}{path}", key))
check(kb("clipshot/", "binding") == "'<Primary><Shift>a'", "GNOME: сочетание области сменено на месте")
check(kb("clipsd-full/", "command") == "'/home/u/.local/bin/clipsd --full'" and kb("clipsd-full/", "binding") == "'Print'",
      "GNOME: создано сочетание для всего экрана")
check(f"{root}clipsd-full/" in fake.data[(st.GNOME_KB, "custom-keybindings")] and
      f"{root}custom0/" in fake.data[(st.GNOME_KB, "custom-keybindings")], "GNOME: чужие сочетания не тронуты")
check(fake.data[st.GNOME_SHOT_UI] == "['<Super><Shift>s']", "GNOME: Print забран у встроенного скриншотера")
check("-ru/" not in fake.data[(st.GNOME_KB, "custom-keybindings")],
      "GNOME: второго сочетания на ту же клавишу (Ctrl+Shift+Ф) нет, оно перебивало латинское")
fake.data[(st.GNOME_KB, "custom-keybindings")] = fake.data[(st.GNOME_KB, "custom-keybindings")][:-1] + f", '{root}clipshot-ru/']"
st.GnomeHotkeys(run=fake, ext=None).apply("Ctrl+Shift+A", "Print")
check("clipshot-ru/" not in fake.data[(st.GNOME_KB, "custom-keybindings")], "GNOME: двойник от прежней версии убирается")
fake2 = FakeGsettings()
st.GnomeHotkeys(run=fake2, ext=None).apply("Alt+W", "")
check((f"{st.GNOME_KB}.custom-keybinding:{root}clipsd-full/", "binding") not in fake2.data,
      "GNOME: выключенное сочетание всего экрана не создаётся")

# --- Расширение «ClipSD: горячие клавиши» (подменено: настоящие настройки не трогаем) ----
class FakeExt:
    def __init__(self, active):
        self._active, self.keys = active, {}

    def installed(self):
        return True

    def active(self):
        return self._active

    def set(self, key, values):
        self.keys[key] = list(values)


fake3, ext3 = FakeGsettings(), FakeExt(active=True)
st.GnomeHotkeys(run=fake3, ext=ext3).apply("Alt+W", "", True)
check(ext3.keys["region-hotkey"] == ["<Alt>0x19"], f"расширение: Alt+W кодом физической клавиши, не зависит от раскладки {ext3.keys}")
check(kb3 := fake3.data.get((f"{st.GNOME_KB}.custom-keybinding:{st.GNOME_KB_ROOT}clipshot/", "binding")) == "''",
      "при работающем расширении обычное сочетание GNOME снято (не спорит)")
fake4, ext4 = FakeGsettings(), FakeExt(active=False)
st.GnomeHotkeys(run=fake4, ext=ext4).apply("Alt+W", "", True)
check(fake4.data.get((f"{st.GNOME_KB}.custom-keybinding:{st.GNOME_KB_ROOT}clipshot/", "binding")) == "'<Alt>w'"
      and ext4.keys["region-hotkey"] == ["<Alt>0x19"],
      "до перезахода (расширение ещё не загружено) работает обычное сочетание, расширение уже настроено")
ext5 = FakeExt(active=True)
st.GnomeHotkeys(run=FakeGsettings(), ext=ext5).apply("Ctrl+Alt+F5", "", True)
check(ext5.keys["region-hotkey"] == ["<Primary><Alt>F5"], "для F5 русского двойника нет")
ext6 = FakeExt(active=True)
st.GnomeHotkeys(run=FakeGsettings(), ext=ext6).apply("Alt+W", "", False)
check(ext6.keys["region-hotkey"] == ["<Alt>w"], "галочка «обе раскладки» снята: только латинский вариант")

# --- окно настроек ----------------------------------------------------------
cfg = dict(appmod.DEFAULTS)
dlg = st.SettingsDialog(cfg)
for mod in ("Ctrl", "Shift"):            # по шагам: модификаторы кнопками, клавиша из списка
    dlg.key_region.mod_buttons[mod].setChecked(True)
dlg.key_region.mod_buttons["Alt"].setChecked(False)
dlg.key_region.key.setCurrentIndex(dlg.key_region.key.findData("X"))
dlg.key_full.set_hotkey("")
dlg.show_zoom.setChecked(False)
dlg.remember.setChecked(False)
dlg.tray_click.setCurrentIndex(1)
dlg.save_dir.setText(os.path.join(tmp, "shots"))
dlg.save_format.setCurrentIndex(1)
dlg.save_ask.setChecked(True)
dlg._show_color("ui_accent", "#2db400")
dlg._show_color("ui_panel", "#b0b4ba")
dlg.frame.setCurrentIndex(dlg.frame.findData(12))
v = dlg.values()
check(v["hotkey_region"] == "Ctrl+Shift+X" and v["hotkey_fullscreen"] == "" and v["hotkey_both_layouts"] is True,
      f"окно: клавиши {v['hotkey_region']!r}, обе раскладки по умолчанию")
check(v["show_zoom"] is False and v["remember_region"] is False and v["tray_click"] == "menu"
      and v["save_format"] == "jpg" and v["save_ask"] is False, "окно: флажки, трей, формат")
check(v["ui_accent"] == "#2db400" and v["ui_panel"] == "#b0b4ba" and v["ui_frame"] == 12, "окно: цвета и толщина рамки")
dlg.show()
app.processEvents()
dlg.grab().save(os.path.join(tmp, "settings.png"))
ed_hk = st.HotkeyEditor("Alt+W")
check(ed_hk.hotkey() == "Alt+W" and ed_hk.mod_buttons["Alt"].isChecked(), "поле сочетания показывает Alt+W")
ed_hk.set_hotkey("")
check(ed_hk.hotkey() == "", "«Выключить» убирает сочетание")
dlg._reset_theme()
check(dlg.values()["ui_accent"] == "#1e78ff" and dlg.values()["ui_frame"] == 8, "окно: сброс оформления")
appmod.install_translations(app)
check(len(app._translators) > 0, "русский перевод стандартных окон Qt подключён")

# --- применение в приложении (GNOME подменён) --------------------------------
qapp_ctx = appmod.Clipshot(app)
applied = {}


class FakeGnome:
    @staticmethod
    def available():
        return True

    def apply(self, region, full, both_layouts=True):
        applied.update(region=region, full=full)


st_gnome = st.GnomeHotkeys
st.GnomeHotkeys = FakeGnome
v.pop("autostart")
qapp_ctx.config["last_region"] = [1, 2, 30, 40]
qapp_ctx.apply_settings(v)
st.GnomeHotkeys = st_gnome
check(applied == {"region": "Ctrl+Shift+X", "full": ""}, "приложение: новые клавиши применены сразу")
check(qapp_ctx._last_region() is None, "приложение: прошлая область не предлагается, если выключено")
check(appmod.load_config()["save_format"] == "jpg", "приложение: настройки записаны в файл")

# --- редактор: оформление, настройки из окна, сохранение без вопроса ----------
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest

img = QImage(120, 80, QImage.Format.Format_RGB32)
img.fill(QColor("#336699"))
ed = EditorWindow(img, qapp_ctx, QPoint(0, 0))
ed.present()
app.processEvents()
ed.grab().save(os.path.join(tmp, "editor_theme.png"))
from clipshot.editor import chrome_params
check("#2db400" in ed.styleSheet() and ed.shell.params["fill"].name() == chrome_params(qapp_ctx.config)["fill"].name()
      and QColor("#b0b4ba").lightness() < ed.shell.params["fill"].lightness() and ed.frame_px == 12,
      "редактор открылся с выбранными цветами и толщиной рамки")
opened = []
real_open = qapp_ctx.open_settings
qapp_ctx.open_settings = lambda parent=None: opened.append(parent)
ed.activateWindow()
QTest.keyClick(ed.canvas, Qt.Key.Key_Comma, Qt.KeyboardModifier.ControlModifier)
check(opened == [ed], "Ctrl+, в редакторе открывает настройки")
qapp_ctx.open_settings = real_open
qapp_ctx.editors.append(ed)
qapp_ctx.apply_settings(dict(qapp_ctx.config, ui_accent="#8b3dff", ui_frame=4))
check("#8b3dff" in ed.styleSheet() and ed.frame_px == 4, "оформление меняется в уже открытом окне")
ed.grab().save(os.path.join(tmp, "editor_settings_button.png"))
ed.save_and_close()
files = os.listdir(os.path.join(tmp, "shots"))
check(len(files) == 1 and files[0].endswith(".jpg"), f"Ctrl+S без окна: файл {files}")

# --- Выбор оформления при первом запуске ---------------------------------------
from PyQt6.QtWidgets import QLabel
from clipshot.theme_chooser import ThemeChooser
changed = []
qapp_ctx.config["ui_theme"] = "standard"
ch = ThemeChooser(qapp_ctx, None, on_change=lambda: changed.append(qapp_ctx.config["ui_theme"]))
check(set(ch.cards) == {"standard", "pro"} and not ch.cards["pro"].findChildren(QLabel)[0].pixmap().isNull(),
      "окно выбора: две карточки с превью")
ch.show()
app.processEvents()
ch.grab().save(os.path.join(tmp, "theme_chooser_standard.png"))
ch.cards["pro"].mousePressEvent(None)
check(qapp_ctx.config["ui_theme"] == "pro" and changed == ["pro"], "клик по карточке сразу включает тёмный стиль")
app.processEvents()
ch.grab().save(os.path.join(tmp, "theme_chooser_pro.png"))
ch.cards["standard"].mousePressEvent(None)
check(qapp_ctx.config["ui_theme"] == "standard", "можно переключить обратно")

# прежнее расширение ClipSD узнаётся по схеме настроек, а не по имени
from pathlib import Path  # noqa: E402
_ext = Path(tempfile.mkdtemp(dir=os.environ.get("TMPDIR"))) / "extensions"
for _uuid, _meta in (("clipsd@clipsd.github.io", '{"settings-schema": "org.gnome.shell.extensions.clipsd"}'),
                     ("clipsd@old-copy", '{"settings-schema": "org.gnome.shell.extensions.clipsd"}'),
                     ("other@x", '{"settings-schema": "org.gnome.shell.extensions.other"}'),
                     ("broken@x", "not json")):
    (_ext / _uuid).mkdir(parents=True)
    (_ext / _uuid / "metadata.json").write_text(_meta)
check(st.legacy_ext_uuids(_ext) == ["clipsd@old-copy"], f"прежнее расширение по схеме: {st.legacy_ext_uuids(_ext)}")
check(st.legacy_ext_uuids(_ext / "nope") == [], "нет папки расширений: пусто")

print()
print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено {len(failures)}")
from clipshot.exitutil import quick_exit
quick_exit(1 if failures else 0)
