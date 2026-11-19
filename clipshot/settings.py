# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
"""Окно настроек: горячие клавиши, выделение, трей, сохранение, автозапуск."""

import ast
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QKeySequence
from PyQt6.QtWidgets import (QApplication, QCheckBox, QColorDialog, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout,
                             QHBoxLayout, QLabel, QLineEdit, QKeySequenceEdit, QPushButton, QScrollArea, QStyle, QVBoxLayout,
                             QWidget)

from .i18n import tr
from .i18n import keys as i18n_keys

# Русская раскладка → латинская по месту клавиши: сочетание работает при любой раскладке.
_RU = "йцукенгшщзхъфывапролджэячсмитьбю"
_EN = "qwertyuiop[]asdfghjkl;'zxcvbnm,."
_RU_TO_EN = {ru: en for ru, en in zip(_RU, _EN)}
# Та же клавиша в русской раскладке — имя keysym X11 (GNOME различает сочетания по раскладкам).
_CYRILLIC_KEYSYM = dict(zip(
    "qwertyuiop[]asdfghjkl;'zxcvbnm,.",
    ["Cyrillic_shorti", "Cyrillic_tse", "Cyrillic_u", "Cyrillic_ka", "Cyrillic_ie", "Cyrillic_en", "Cyrillic_ghe",
     "Cyrillic_sha", "Cyrillic_shcha", "Cyrillic_ze", "Cyrillic_ha", "Cyrillic_hardsign", "Cyrillic_ef",
     "Cyrillic_yeru", "Cyrillic_ve", "Cyrillic_a", "Cyrillic_pe", "Cyrillic_er", "Cyrillic_o", "Cyrillic_el",
     "Cyrillic_de", "Cyrillic_zhe", "Cyrillic_e", "Cyrillic_ya", "Cyrillic_che", "Cyrillic_es", "Cyrillic_em",
     "Cyrillic_i", "Cyrillic_te", "Cyrillic_softsign", "Cyrillic_be", "Cyrillic_yu"]))
_CYRILLIC_KEYSYM["`"] = "Cyrillic_io"
_RU_TO_EN["ё"] = "`"

GNOME_KB = "org.gnome.settings-daemon.plugins.media-keys"
GNOME_KB_ROOT = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/"
GNOME_SHOT_UI = ("org.gnome.shell.keybindings", "show-screenshot-ui")


def normalize_hotkey(text: str) -> str:
    """Запись QKeySequenceEdit → формат настроек «Ctrl+Shift+Alt+Super+W» (латиница, одно сочетание)."""
    text = (text or "").split(",")[0].strip()
    if not text:
        return ""
    parts = text.split("+") if text != "+" else ["+"]
    *mods, key = parts
    names = {"ctrl": "Ctrl", "control": "Ctrl", "shift": "Shift", "alt": "Alt", "meta": "Super", "super": "Super",
             "win": "Super"}
    order = ["Ctrl", "Shift", "Alt", "Super"]
    mods = sorted({names.get(m.lower(), m) for m in mods}, key=lambda m: order.index(m) if m in order else 9)
    if len(key) == 1:
        key = _RU_TO_EN.get(key.lower(), key)
    from .keys import canonical
    return "+".join(mods + [canonical(key)])


def to_gnome(hotkey: str) -> str:
    """«Ctrl+Alt+W» → «<Primary><Alt>w» (формат сочетаний GNOME)."""
    if not hotkey:
        return ""
    *mods, key = hotkey.split("+")
    prefix = {"Ctrl": "<Primary>", "Shift": "<Shift>", "Alt": "<Alt>", "Super": "<Super>"}
    from .keys import x_keysym_name
    return "".join(prefix.get(m, "") for m in mods) + (x_keysym_name(key) or key)


def to_gnome_russian(hotkey: str) -> str:
    """То же сочетание для русской раскладки: «Alt+W» → «<Alt>Cyrillic_tse». Пусто, если клавиша не буква."""
    if not hotkey:
        return ""
    *mods, key = hotkey.split("+")
    keysym = _CYRILLIC_KEYSYM.get(key.lower()) if len(key) == 1 else None
    if keysym is None:
        return ""
    prefix = {"Ctrl": "<Primary>", "Shift": "<Shift>", "Alt": "<Alt>", "Super": "<Super>"}
    return "".join(prefix.get(m, "") for m in mods) + keysym


def _parse_gvariant_list(value: str):
    value = value.strip()
    if value.startswith("@as"):
        value = value[3:].strip()
    try:
        return list(ast.literal_eval(value))
    except (ValueError, SyntaxError):
        return []


EXT_UUID = "clipsd@clipsd.github.io"
EXT_SCHEMA = "org.gnome.shell.extensions.clipsd"


def legacy_ext_uuids(base: Path) -> list:
    """Прежние расширения ClipSD (1.29 и раньше, рабочая копия разработчика): другое имя, та же схема настроек.
    Узнаются по схеме в metadata.json, а не по имени."""
    found = []
    try:
        folders = sorted(p for p in base.iterdir() if p.is_dir() and p.name != EXT_UUID)
    except OSError:
        return found
    for folder in folders:
        try:
            meta = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(meta, dict) and meta.get("settings-schema") == EXT_SCHEMA:
            found.append(folder.name)
    return found


class ShellExtension:
    """Расширение «ClipSD: горячие клавиши»: все варианты сочетания (Alt+W и Alt+Ц) одним сочетанием оболочки."""

    def __init__(self):
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "gnome-shell/extensions"
        self.uuid = EXT_UUID
        for uuid in (EXT_UUID, *legacy_ext_uuids(base)):   # новое имя, а если его нет, прежнее (по схеме)
            if (base / uuid / "schemas/gschemas.compiled").exists():
                self.uuid = uuid
                break
        self.dir = base / self.uuid

    def installed(self) -> bool:
        return (self.dir / "schemas/gschemas.compiled").exists()

    def active(self) -> bool:
        """Расширение загружено оболочкой (после установки нужен один перезаход в систему)."""
        try:
            out = subprocess.run(["gdbus", "call", "--session", "--dest", "org.gnome.Shell",
                                  "--object-path", "/org/gnome/Shell",
                                  "--method", "org.gnome.Shell.Extensions.GetExtensionInfo", self.uuid],
                                 capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            return False
        return "'state': <1.0>" in out or "'state': <1>" in out

    def set(self, key: str, values):
        subprocess.run(["gsettings", "--schemadir", str(self.dir / "schemas"), "set", EXT_SCHEMA, key, str(list(values))],
                       capture_output=True, timeout=5)


class GnomeHotkeys:
    """Сочетания ClipSD в GNOME. run и ext — для подмены в тестах.

    Если работает расширение ClipSD, сочетание с русским двойником пишется в него (один захват клавиши
    на обе раскладки), а обычное сочетание GNOME снимается. Иначе — обычное сочетание GNOME (одна раскладка)."""

    def __init__(self, run=None, ext="auto"):
        self.run = run or self._gsettings
        self.ext = ShellExtension() if ext == "auto" else ext

    @staticmethod
    def _gsettings(*args) -> str:
        out = subprocess.run(["gsettings", *args], capture_output=True, text=True, timeout=5)
        if out.returncode != 0:
            raise RuntimeError(out.stderr.strip() or tr("settings.gsettings_error"))
        return out.stdout.strip()

    @staticmethod
    def available() -> bool:
        return shutil.which("gsettings") is not None and "GNOME" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper()

    def _paths(self):
        return _parse_gvariant_list(self.run("get", GNOME_KB, "custom-keybindings"))

    def _get(self, path, key):
        return ast.literal_eval(self.run("get", f"{GNOME_KB}.custom-keybinding:{path}", key))

    def _set(self, path, key, value):
        self.run("set", f"{GNOME_KB}.custom-keybinding:{path}", key, value)

    def _find(self, flag):
        for path in self._paths():
            try:
                command = self._get(path, "command")
            except (ValueError, SyntaxError, RuntimeError):
                continue
            if "clip" in command and command.rstrip().endswith(flag) and not path.rstrip("/").endswith("-ru"):
                return path, command
        return None, None

    @staticmethod
    def variants(hotkey: str, both_layouts: bool):
        """Варианты сочетания: латинская клавиша и (по желанию) та же клавиша в русской раскладке.

        Для обеих раскладок буква или цифра задаётся кодом физической клавиши («<Alt>0x19»): GNOME
        пересчитывает буквы в коды при смене раскладки, а раскладку у Сергея переключает xkb (Alt+Shift)
        в обход GNOME, и пара «<Alt>w» + «<Alt>Cyrillic_tse» срабатывала только на одной раскладке."""
        if not hotkey:
            return []
        if both_layouts:
            from .keys import xkb_keycode
            *mods, key = hotkey.split("+")
            code = xkb_keycode(key)
            if code:
                prefix = {"Ctrl": "<Primary>", "Shift": "<Shift>", "Alt": "<Alt>", "Super": "<Super>"}
                return ["".join(prefix.get(m, "") for m in mods) + code]
        out = [to_gnome(hotkey)]
        russian = to_gnome_russian(hotkey) if both_layouts else ""
        if russian:
            out.append(russian)
        return out

    def apply(self, region: str, full: str, both_layouts: bool = True):
        ext = self.ext
        if ext is not None and ext.installed():
            ext.set("region-hotkey", self.variants(region, both_layouts))
            ext.set("full-hotkey", self.variants(full, both_layouts))
            if ext.active():
                # Расширение держит клавиши само; обычные сочетания GNOME с ним бы спорили — снимаем
                region, full = "", ""
        self._apply_custom(region, full)

    def _apply_custom(self, region: str, full: str):
        region_path, region_cmd = self._find("--region")
        binary = region_cmd.rsplit(" ", 1)[0] if region_cmd else str(Path.home() / ".local/bin/clipsd")
        paths = self._paths()
        for flag, hotkey, name, default_path in (
                ("--region", region, tr("settings.gnome_name_region"), GNOME_KB_ROOT + "clipsd/"),
                ("--full", full, tr("settings.gnome_name_full"), GNOME_KB_ROOT + "clipsd-full/")):
            existing = region_path if flag == "--region" else self._find(flag)[0]
            if not hotkey and existing is None:
                continue                      # выключенное сочетание, которого и не было
            path = existing or default_path
            if path not in paths:
                paths.append(path)
                self.run("set", GNOME_KB, "custom-keybindings", str(paths))
            self._set(path, "name", name)
            self._set(path, "command", f"{binary} {flag}")
            self._set(path, "binding", to_gnome(hotkey))
            if hotkey:
                self._free_from_screenshot_ui(to_gnome(hotkey))
            # Отдельный «русский двойник» (Alt+Ц) не нужен и вреден: GNOME привязывает сочетание к месту клавиши,
            # Alt+W работает при любой раскладке, а второе сочетание на ту же клавишу перехватывает её
            # и оставляет рабочей только русскую раскладку. Двойник от прежних версий убираем.
            twin = path.rstrip("/") + "-ru/"
            if twin in paths:
                paths.remove(twin)
                self.run("set", GNOME_KB, "custom-keybindings", str(paths))

    def _free_from_screenshot_ui(self, binding: str):
        """Если это сочетание было у встроенного скриншотера GNOME, забираем его (иначе не сработает)."""
        try:
            current = _parse_gvariant_list(self.run("get", *GNOME_SHOT_UI))
        except RuntimeError:
            return
        cleaned = [k for k in current if k.lower() != binding.lower()]
        if cleaned != current:
            self.run("set", *GNOME_SHOT_UI, str(cleaned))


# --- автозапуск ---------------------------------------------------------------

def _startup_lnk() -> Path:
    return Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup/ClipSD.lnk"


def _is_package_install() -> bool:
    """Запуск из папки пакета ~/.local/share/clipsd/versions/... (а не из исходников)."""
    versions = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "clipsd" / "versions"
    here = Path(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
    return versions in here.parents or versions.resolve() in here.resolve().parents


def _systemd_unit():
    """Пакет: только clipsd.service. clipshot.service (рабочая копия разработчика) считается только при
    запуске из исходников."""
    names = ("clipsd.service",) if _is_package_install() else ("clipsd.service", "clipshot.service")
    for name in names:
        if (Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "systemd/user" / name).exists():
            return name
    return None


def _xdg_autostart() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart/clipsd.desktop"


def autostart_enabled() -> bool:
    if sys.platform == "win32":
        return _startup_lnk().exists()
    unit = _systemd_unit()
    if unit:
        return subprocess.run(["systemctl", "--user", "is-enabled", "--quiet", unit]).returncode == 0
    return _xdg_autostart().exists()


def set_autostart(enabled: bool):
    if sys.platform == "win32":
        lnk = _startup_lnk()
        if not enabled:
            lnk.unlink(missing_ok=True)
            return
        if getattr(sys, "frozen", False):
            # Установлен из ClipSD-Setup.exe: ярлык на постоянный запускатель {app}\ClipSD.exe, путь не меняется
            # при обновлениях (сама программа живёт в {app}\app\ClipSD-app.exe)
            exe = Path(sys.executable)
            if exe.parent.name.lower() == "app" and (exe.parent.parent / "ClipSD.exe").exists():
                exe = exe.parent.parent / "ClipSD.exe"
            target, args, work_dir, icon = exe, "", exe.parent, exe
        else:
            code_dir = Path(__file__).resolve().parent.parent
            target, args, work_dir = Path(sys.executable).with_name("pythonw.exe"), "-m clipshot", code_dir
            icon = code_dir / "clipsd.ico"
        script = (f'$s=(New-Object -ComObject WScript.Shell).CreateShortcut("{lnk}");'
                  f'$s.TargetPath="{target}";$s.Arguments="{args}";$s.WorkingDirectory="{work_dir}";'
                  f'$s.IconLocation="{icon}";$s.Save()')
        subprocess.run(["powershell", "-NoProfile", "-Command", script], timeout=20,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return
    unit = _systemd_unit()
    if unit:
        subprocess.run(["systemctl", "--user", "enable" if enabled else "disable", unit], capture_output=True)
        return
    path = _xdg_autostart()
    if not enabled:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    # пакет: всегда постоянная команда ~/.local/bin/clipsd (переживает смену версий)
    launcher = Path.home() / ".local/bin/clipsd"
    binary = str(launcher) if _is_package_install() else (shutil.which("clipsd") or str(launcher))
    path.write_text("[Desktop Entry]\nType=Application\nName=ClipSD\nExec=" + binary +
                    "\nIcon=clipsd\nTerminal=false\nX-GNOME-Autostart-enabled=true\n", encoding="utf-8")


# --- выбор сочетания ------------------------------------------------------------

from .keys import canonical as _canonical, choices as _key_choices


class HotkeyEditor(QWidget):
    """Сочетание клавиш двумя способами: по шагам (Ctrl/Shift/Alt/Win + клавиша из списка) или нажатием."""

    MODS = (("Ctrl", "Ctrl"), ("Shift", "Shift"), ("Alt", "Alt"), ("Super", "Win"))

    def __init__(self, value=""):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self.mod_buttons = {}
        for mod, label in self.MODS:
            label = i18n_keys(label)   # de: «Strg»
            button = QPushButton(label)
            button.setCheckable(True)
            # Ширина по тексту: при крупном системном шрифте «Shift» не обрезается.
            f14 = QFont()
            f14.setPixelSize(14)   # в карточках буквы 14 px: ширина считается по ним, а не по шрифту до стиля
            button.setMinimumWidth(QFontMetrics(f14).horizontalAdvance(label) + 36)
            button.setToolTip(tr("settings.mod_tip", name=label))
            self.mod_buttons[mod] = button
            row.addWidget(button)
        plus = QLabel("+")
        row.addWidget(plus)
        self.key = QComboBox()
        self.key.addItem(tr("settings.key_none"), "")
        for key, label in _key_choices():
            self.key.addItem(label, key)
        self.key.setToolTip(tr("settings.key_tip"))
        row.addWidget(self.key, 1)
        record = QPushButton(tr("settings.record"))
        record.setToolTip(tr("settings.record_tip"))
        record.clicked.connect(self.record)
        row.addWidget(record)
        off = QPushButton(tr("settings.off"))
        off.clicked.connect(lambda: self.set_hotkey(""))
        row.addWidget(off)
        self.set_hotkey(value)

    def set_hotkey(self, value: str):
        *mods, key = (value or "").split("+") if value else [""]
        for mod, button in self.mod_buttons.items():
            button.setChecked(mod in mods)
        index = self.key.findData(_canonical(key))
        self.key.setCurrentIndex(max(0, index))

    def hotkey(self) -> str:
        key = self.key.currentData()
        if not key:
            return ""
        mods = [mod for mod, _label in self.MODS if self.mod_buttons[mod].isChecked()]
        return "+".join(mods + [key])

    def record(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("settings.press_title"))
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(tr("settings.press_text")))
        edit = QKeySequenceEdit()
        edit.setMaximumSequenceLength(1)
        line = edit.findChild(QLineEdit)
        if line is not None:
            line.setPlaceholderText(tr("settings.press_wait"))
        edit.editingFinished.connect(dialog.accept)
        layout.addWidget(edit)
        cancel = QPushButton(tr("settings.cancel"))
        cancel.clicked.connect(dialog.reject)
        layout.addWidget(cancel, 0, Qt.AlignmentFlag.AlignRight)
        edit.setFocus()
        if dialog.exec() == QDialog.DialogCode.Accepted:
            value = normalize_hotkey(edit.keySequence().toString(QKeySequence.SequenceFormat.PortableText))
            if value:
                self.set_hotkey(value)


# --- окно ---------------------------------------------------------------------

def settings_style(t) -> str:
    r = 10 if not t["dark"] else 3
    return f"""
QDialog {{ background: {t['dialog_bg']}; color: {t['text']}; }}
QLabel, QCheckBox {{ color: {t['text']}; font-size: 14px; }}
QLabel#section {{ font-size: 14px; font-weight: bold; color: {t['text']}; margin-top: 6px; }}
QScrollArea#settingsScroll, QWidget#settingsContent {{ background: transparent; }}
QLabel#hint, QLabel#footer {{ color: {t['text_dim']}; font-size: 14px; }}
QFrame#card {{ background: {t['card_bg']}; border: 1px solid {t['card_border']}; border-radius: {r}px; }}
QKeySequenceEdit, QLineEdit, QComboBox {{ min-height: 32px; font-size: 14px; }}
QLineEdit, QComboBox {{ background: {t['input_bg']}; color: {t['text']}; border: 1px solid {t['button_border']};
    border-radius: {min(r, 4)}px; padding: 0 6px; }}
HotkeyEditor QPushButton:checked {{ background: {t['ui_accent']}; color: white; border-color: {t['ui_accent']};
    font-weight: bold; }}
QPushButton {{ min-height: 32px; font-size: 14px; padding: 0 14px; border-radius: {min(r, 6)}px; border: 1px solid {t['button_border']};
    background: {t['button_bg']}; color: {t['button_text']}; }}
QPushButton:hover {{ background: {t['button_hover']}; border-color: {t['ui_accent']}; }}
QPushButton#primary {{ background: {t['ui_accent']}; color: white; border: 1px solid {t['ui_accent']}; font-weight: bold; }}
"""


class SettingsDialog(QDialog):
    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        from . import __author__, __version__
        self.config = config
        self.setWindowTitle(tr("settings.title"))
        from . import themes as _themes
        self.setStyleSheet(settings_style(_themes.tokens(config)))
        # Карточки прокручиваются: на низком экране окно не выше экрана, а «Отмена» и «Сохранить» всегда видны
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 14)
        outer.setSpacing(6)
        content = QWidget()
        content.setObjectName("settingsContent")
        root = QVBoxLayout(content)
        root.setContentsMargins(18, 14, 18, 4)
        root.setSpacing(6)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("settingsScroll")
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.viewport().setAutoFillBackground(False)
        outer.addWidget(self.scroll, 1)

        # Язык (1.31): первым разделом, с глобусом; языки на самих себе
        from . import icons, language
        grid = self._card(root, language.menu_title())
        globe = QLabel()
        globe.setPixmap(icons.icon("globe").pixmap(20, 20))
        grid.addWidget(globe, 0, 0)
        self.language = QComboBox()
        for code, label in language.entries():
            self.language.addItem(label, code)
        self.language.setCurrentIndex(max(0, self.language.findData(language.current_choice(self))))
        self.language.setAccessibleName(tr("settings.language"))
        grid.addWidget(self.language, 0, 1, 1, 2)

        # Горячие клавиши
        grid = self._card(root, tr("settings.sec_hotkeys"))
        self.key_region = self._hotkey_row(grid, 0, tr("settings.hotkey_region"), config.get("hotkey_region", ""))
        self.key_full = self._hotkey_row(grid, 1, tr("settings.hotkey_full"), config.get("hotkey_fullscreen", ""))
        self.both_layouts = QCheckBox(tr("settings.both_layouts"))
        self.both_layouts.setChecked(bool(config.get("hotkey_both_layouts", True)))
        grid.addWidget(self.both_layouts, 3, 0, 1, 3)
        hint = QLabel(tr("settings.hotkey_hint"))
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        grid.addWidget(hint, 2, 0, 1, 3)

        # Выделение
        grid = self._card(root, tr("settings.sec_select"))
        self.show_zoom = self._check(grid, 0, tr("settings.show_zoom"), config.get("show_zoom", True))
        self.show_size = self._check(grid, 1, tr("settings.show_size"), config.get("show_size", True))
        self.remember = self._check(grid, 2, tr("settings.remember"),
                                    config.get("remember_region", True))

        # Текст с картинки
        from . import ocr
        grid = self._card(root, tr("settings.sec_ocr"))
        self.ocr_enabled = self._check(grid, 0, tr("settings.ocr_enable"),
                                       config.get("ocr_enabled", True))
        grid.addWidget(QLabel(tr("settings.ocr_mode")), 1, 0)
        self.ocr_quality = QComboBox()
        self.ocr_quality.addItem(tr("settings.ocr_accurate"), "accurate")
        self.ocr_quality.addItem(tr("settings.ocr_fast"), "fast")
        self.ocr_quality.setCurrentIndex(1 if config.get("ocr_quality", "accurate") == "fast" else 0)
        grid.addWidget(self.ocr_quality, 1, 1, 1, 2)
        grid.addWidget(QLabel(tr("settings.ocr_langs")), 2, 0)
        self.ocr_langs = QComboBox()
        self.ocr_langs.addItem(tr("settings.ocr_auto", langs=ocr.langs_title(ocr.default_langs())), "auto")   # 1.31
        for key, code in (("settings.ocr_ru_en", "rus+eng"), ("settings.ocr_ru", "rus"), ("settings.ocr_en", "eng")):
            self.ocr_langs.addItem(tr(key), code)
        index = self.ocr_langs.findData(config.get("ocr_langs", "auto"))
        self.ocr_langs.setCurrentIndex(max(0, index))
        grid.addWidget(self.ocr_langs, 2, 1, 1, 2)
        status = QLabel(ocr.engine_status() + "\n" + tr("settings.ocr_idle"))
        status.setWordWrap(True)
        status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        grid.addWidget(status, 3, 0, 1, 3)
        help = ocr.engine_help(config.get("ocr_langs"))
        self.ocr_install = ocr.InstallBlock(help, tokens=_themes.tokens(config)) if help is not None else None
        if self.ocr_install is not None:
            grid.addWidget(self.ocr_install, 4, 0, 1, 3)
        # Языки распознавания (болгарский, немецкий и др.): это про распознавание, поэтому здесь, а не в «Переводе»
        from . import translate
        missing = translate.missing_ocr_langs()
        if missing and ocr.linux_family() == "debian":
            langs_help = ocr.InstallHelp(tr("settings.ocr_more_text"),
                                         translate.OCR_EXTRA_COMMAND, ocr.TESSERACT_GUIDE, tr("ocr.guide_title"))
            langs_help.title = tr("settings.ocr_more_title")
            grid.addWidget(ocr.InstallBlock(langs_help, tokens=_themes.tokens(config)), 5, 0, 1, 3)
        for widget in (self.ocr_quality, self.ocr_langs):
            widget.setEnabled(self.ocr_enabled.isChecked())
            self.ocr_enabled.toggled.connect(widget.setEnabled)

        # Перевод с картинки
        from . import translate
        grid = self._card(root, tr("settings.sec_translate"))
        self.tr_enabled = self._check(grid, 0, tr("settings.tr_enable"),
                                      config.get("translate_enabled", True))
        names = translate.LANG_NAMES
        grid.addWidget(QLabel(tr("settings.tr_to")), 1, 0)
        self.tr_to = QComboBox()
        grid.addWidget(QLabel(tr("settings.tr_alt")), 2, 0)
        self.tr_alt = QComboBox()
        self.tr_to.addItem(translate.auto_label(config), "auto")
        for code in translate.TARGETS:
            self.tr_to.addItem(names[code], code)
            self.tr_alt.addItem(names[code], code)
        self.tr_to.setCurrentIndex(max(0, self.tr_to.findData(config.get("translate_to", "auto") or "auto")))
        self.tr_alt.setCurrentIndex(max(0, self.tr_alt.findData(config.get("translate_alt", "en"))))
        grid.addWidget(self.tr_to, 1, 1, 1, 2)
        grid.addWidget(self.tr_alt, 2, 1, 1, 2)
        grid.addWidget(QLabel(tr("settings.tr_engine")), 3, 0)
        self.tr_engine = QComboBox()
        for code, title in translate.ENGINES:
            self.tr_engine.addItem(title, code)
        self.tr_engine.setCurrentIndex(max(0, self.tr_engine.findData(config.get("translate_engine", "mymemory"))))
        grid.addWidget(self.tr_engine, 3, 1, 1, 2)
        grid.addWidget(QLabel(tr("settings.tr_email")), 4, 0)
        self.tr_email = QLineEdit(config.get("translate_email", ""))
        self.tr_email.setPlaceholderText(tr("settings.tr_email_ph"))
        self.tr_email.setToolTip(tr("settings.tr_email_tip"))
        grid.addWidget(self.tr_email, 4, 1)
        self.tr_email_check = QPushButton(tr("settings.tr_email_check"))
        self.tr_email_check.setToolTip(tr("settings.tr_email_check_tip"))
        self.tr_email_check.clicked.connect(self._check_email)
        grid.addWidget(self.tr_email_check, 4, 2)
        grid.addWidget(QLabel("Google Cloud:"), 5, 0)
        self.tr_google = QLabel()
        self.tr_google.setWordWrap(True)
        grid.addWidget(self.tr_google, 5, 1)
        setup = QPushButton(tr("translate_ui.connect_google"))
        setup.setToolTip(tr("settings.google_tip"))
        setup.clicked.connect(self._open_google_setup)
        grid.addWidget(setup, 5, 2)
        self.tr_usage = QLabel()
        self.tr_usage.setWordWrap(True)
        grid.addWidget(self.tr_usage, 6, 0, 1, 3)
        self._refresh_translate_status()
        note = QLabel(tr("settings.tr_note"))
        note.setWordWrap(True)
        grid.addWidget(note, 7, 0, 1, 3)
        for widget in (self.tr_to, self.tr_alt, self.tr_engine, self.tr_email, self.tr_email_check):
            widget.setEnabled(self.tr_enabled.isChecked())
            self.tr_enabled.toggled.connect(widget.setEnabled)

        # Трей
        grid = self._card(root, tr("settings.sec_tray"))
        grid.addWidget(QLabel(tr("settings.tray_click")), 0, 0)
        self.tray_click = QComboBox()
        self.tray_click.addItem(tr("settings.tray_region"), "region")
        self.tray_click.addItem(tr("settings.tray_menu"), "menu")
        self.tray_click.setCurrentIndex(0 if config.get("tray_click", "region") == "region" else 1)
        grid.addWidget(self.tray_click, 0, 1, 1, 2)

        # Сохранение
        grid = self._card(root, tr("settings.sec_save"))
        grid.addWidget(QLabel(tr("settings.save_dir")), 0, 0)
        self.save_dir = QLineEdit(config.get("save_dir", ""))
        grid.addWidget(self.save_dir, 0, 1)
        browse = QPushButton(tr("settings.browse"))
        browse.clicked.connect(lambda: self._browse(self.save_dir, tr("settings.browse_save")))
        grid.addWidget(browse, 0, 2)
        grid.addWidget(QLabel(tr("settings.format")), 1, 0)
        self.save_format = QComboBox()
        self.save_format.addItem(tr("settings.fmt_png"), "png")
        self.save_format.addItem(tr("settings.fmt_jpg"), "jpg")
        self.save_format.setCurrentIndex(1 if config.get("save_format", "png") == "jpg" else 0)
        grid.addWidget(self.save_format, 1, 1, 1, 2)
        self.save_ask = self._check(grid, 2, tr("settings.save_ask"),
                                    not config.get("save_ask", True))
        self.auto_save = self._check(grid, 3, tr("settings.auto_save"), config.get("auto_save", True))
        grid.addWidget(QLabel(tr("settings.auto_save_dir")), 4, 0)
        self.auto_save_dir = QLineEdit(config.get("auto_save_dir", ""))
        grid.addWidget(self.auto_save_dir, 4, 1)
        browse_auto = QPushButton(tr("settings.browse"))
        browse_auto.clicked.connect(lambda: self._browse(self.auto_save_dir, tr("settings.browse_auto")))
        grid.addWidget(browse_auto, 4, 2)

        # Оформление
        from .editor import THEME_DEFAULTS, theme
        self.theme_defaults = THEME_DEFAULTS
        current = theme(config)
        grid = self._card(root, tr("settings.sec_theme"))
        grid.addWidget(QLabel(tr("settings.style")), 0, 0)
        self.ui_theme = QComboBox()
        for key, preset in _themes.THEMES.items():
            self.ui_theme.addItem(_themes.title(key), key)
        self.ui_theme.setCurrentIndex(max(0, self.ui_theme.findData(_themes.name(config))))
        self.ui_theme.currentIndexChanged.connect(self._theme_changed)
        grid.addWidget(self.ui_theme, 0, 1, 1, 2)
        self.colors = {}
        for row, (key, text) in enumerate((("ui_accent", "settings.color_accent"),
                                           ("ui_panel", "settings.color_panel"),
                                           ("ui_field", "settings.color_field")), start=1):
            grid.addWidget(QLabel(tr(text) + ":"), row, 0)
            button = QPushButton()
            button.setMinimumSize(button.fontMetrics().horizontalAdvance("#DDDDDD") + 36, 28)
            button.clicked.connect(lambda _c, k=key: self._pick_color(k))
            self.colors[key] = button
            self._show_color(key, current[key])
            grid.addWidget(button, row, 1, Qt.AlignmentFlag.AlignLeft)
        grid.addWidget(QLabel(tr("settings.frame")), 4, 0)
        self.frame = QComboBox()
        for px, text in ((4, "settings.frame_thin"), (8, "settings.frame_mid"), (12, "settings.frame_thick")):
            self.frame.addItem(tr(text), px)
        self.frame.setCurrentIndex(max(0, self.frame.findData(current["ui_frame"])))
        grid.addWidget(self.frame, 4, 1, 1, 2)
        grid.addWidget(QLabel(tr("settings.frame_style")), 5, 0)
        from .editor import FRAME_STYLES, frame_style
        self.frame_style = QComboBox()
        for key, text in FRAME_STYLES:
            self.frame_style.addItem(text, key)
        self.frame_style.setCurrentIndex(max(0, self.frame_style.findData(frame_style(config))))
        self.frame_style.currentIndexChanged.connect(self._frame_style_changed)
        grid.addWidget(self.frame_style, 5, 1, 1, 2)
        self.system_title = self._check(grid, 6, tr("settings.system_title"), config.get("editor_system_title", False))
        self.system_title.setToolTip(tr("settings.system_title_tip"))
        note = QLabel(tr("settings.next_shot"))
        note.setObjectName("hint")
        grid.addWidget(note, 7, 0, 1, 3)
        reset = QPushButton(tr("settings.reset_theme"))
        reset.clicked.connect(self._reset_theme)
        grid.addWidget(reset, 8, 0, 1, 3, Qt.AlignmentFlag.AlignLeft)
        self._frame_style_changed()

        # Запуск
        grid = self._card(root, tr("settings.sec_start"))
        self.autostart = self._check(grid, 0, tr("settings.autostart"), autostart_enabled())
        self.update_check = self._check(grid, 1, tr("settings.update_check"), bool(config.get("update_check", True)))
        self.update_check.setToolTip(tr("settings.update_check_tip"))
        self.want_tour = False
        tour = QPushButton(tr("settings.tour_again"))
        tour.clicked.connect(self._request_tour)
        grid.addWidget(tour, 2, 0, 1, 3, Qt.AlignmentFlag.AlignLeft)

        from . import build_info
        footer = QLabel(f"ClipSD {build_info.version_label(__version__)} · © 2026 {__author__} · GNU GPL v3")
        footer.setObjectName("footer")
        footer.setWordWrap(True)
        root.addSpacing(4)
        root.addWidget(footer)
        self.scroll.setWidget(content)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(18, 0, 18, 0)
        buttons.addStretch(1)
        cancel = QPushButton(tr("settings.cancel"))
        cancel.clicked.connect(self.reject)
        save = QPushButton(tr("settings.save"))
        save.setObjectName("primary")
        save.setDefault(True)
        save.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        outer.addLayout(buttons)
        self._fit_to_screen(content, parent)

    def _email_min_width(self):
        """Подсказка в поле почты видна целиком на любом языке и при любой ширине экрана (шрифт после стилей окна)."""
        self.tr_email.ensurePolished()
        text = self.tr_email.placeholderText()
        self.tr_email.setMinimumWidth(QFontMetrics(self.tr_email.font()).horizontalAdvance(text) + 40)

    def _fit_to_screen(self, content, parent):
        """Ширина не меньше самой широкой строки (ничего не режется), от 700 точек; высота по карточкам,
        но не выше экрана: дальше карточки прокручиваются, кнопки внизу остаются на месте."""
        content.ensurePolished()
        self._email_min_width()   # шрифт поля уже со стилями окна
        bar = self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent, None, self.scroll)
        self.scroll.setMinimumWidth(content.minimumSizeHint().width() + bar)
        width = max(700, self.minimumSizeHint().width())
        screen = (parent.screen() if parent is not None else None) or QApplication.primaryScreen()
        area = screen.availableGeometry() if screen is not None else None
        rest = self.sizeHint().height() - self.scroll.sizeHint().height()   # кнопки и поля
        need = content.heightForWidth(width) if content.hasHeightForWidth() else -1
        height = rest + (need if need > 0 else content.sizeHint().height())
        if area is not None:
            width = min(width, max(self.minimumSizeHint().width(), area.width() - 40))
            height = min(height, area.height() - 60)
        self.resize(width, height)

    # --- построение --------------------------------------------------------

    def _card(self, root, title) -> QGridLayout:
        label = QLabel(title)
        label.setObjectName("section")
        root.addWidget(label)
        card = QFrame()
        card.setObjectName("card")
        grid = QGridLayout(card)
        grid.setContentsMargins(16, 14, 16, 14)   # отступы как в окнах ClipDialog
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        root.addWidget(card)
        return grid

    def _check(self, grid, row, text, value) -> QCheckBox:
        box = QCheckBox(text)
        box.setChecked(bool(value))
        grid.addWidget(box, row, 0, 1, 3)
        return box

    def _hotkey_row(self, grid, row, text, value) -> HotkeyEditor:
        grid.addWidget(QLabel(text + ":"), row, 0)
        editor = HotkeyEditor(value)
        grid.addWidget(editor, row, 1, 1, 2)
        return editor

    def _request_tour(self):
        self.want_tour = True
        self.accept()

    def _show_color(self, key, color):
        color = QColor(color).name()
        self.colors[key].setProperty("color", color)
        fg = "#000000" if QColor(color).lightnessF() > 0.6 else "#ffffff"
        self.colors[key].setText(color.upper())
        self.colors[key].setStyleSheet(f"QPushButton {{ background: {color}; color: {fg}; border: 1px solid #777; }}")

    def _pick_color(self, key):
        color = QColorDialog.getColor(QColor(self.colors[key].property("color")), self, tr("settings.color_dialog"))
        if color.isValid():
            self._show_color(key, color.name())

    def _reset_theme(self):
        """Цвета и толщина рамки как у выбранного стиля."""
        from . import themes as _themes
        preset = _themes.THEMES[self.ui_theme.currentData()]
        for key in self.colors:
            self._show_color(key, preset[key])
        self.frame.setCurrentIndex(max(0, self.frame.findData(preset["ui_frame"])))

    def _frame_style_changed(self, _index=None):
        """Вид «Без цветной рамки»: цвет и толщина рамки на окно не влияют, пока он выбран."""
        plain = self.frame_style.currentData() == "plain"
        tip = tr("settings.frame_inactive_tip") if plain else ""
        self.frame.setEnabled(not plain)
        self.frame.setToolTip(tip)
        self.colors["ui_accent"].setToolTip(tr("settings.accent_tip") if not plain else
                                            tr("settings.accent_tip_plain"))
        self.frame_style.setToolTip(tr("settings.frame_style_tip"))

    def _theme_changed(self, _index):
        """Сменили стиль: цвета берутся из него, окно настроек сразу перекрашивается."""
        from . import themes as _themes
        self._reset_theme()
        self.setStyleSheet(settings_style(_themes.tokens({"ui_theme": self.ui_theme.currentData()})))

    def _browse(self, field=None, title=None):
        field = field or self.save_dir
        start = os.path.expanduser(field.text() or "~")
        if not os.path.isdir(start):
            start = os.path.dirname(start) or os.path.expanduser("~")
        folder = QFileDialog.getExistingDirectory(self, title or tr("settings.browse_default"), start)
        if folder:
            home = str(Path.home())
            field.setText("~" + folder[len(home):] if folder.startswith(home) else folder)

    # --- результат ---------------------------------------------------------

    def _refresh_translate_status(self):
        from . import translate
        self.tr_google.setText(tr("settings.google_on") if translate.load_google_key() else
                               tr("settings.google_off"))
        self.tr_usage.setText(translate.usage_line(self.config, "mymemory") + "\n" + translate.usage_line(self.config, "google"))

    def _check_email(self):
        from . import translate
        email = self.tr_email.text().strip()
        if not translate.looks_like_email(email):
            self.tr_usage.setText(tr("settings.email_bad"))
            return
        self.tr_email_check.setEnabled(False)
        self.tr_usage.setText(tr("settings.email_checking"))

        def done(error):
            try:
                self.tr_email_check.setEnabled(True)
                self.tr_usage.setText(tr("settings.email_failed", error=error) if error else
                                      tr("settings.email_ok"))
            except RuntimeError:   # окно настроек уже закрыто
                pass
        translate.check_mymemory_email(email, done)

    def _open_google_setup(self):
        """Окно подключения Google; после сохранения сервис Google выбирается в списке."""
        from .service_setup import open_google_setup
        cfg = dict(self.config)

        def saved():
            try:
                self.tr_engine.setCurrentIndex(max(0, self.tr_engine.findData("google")))
                self._refresh_translate_status()
            except RuntimeError:
                pass
        open_google_setup(self, cfg, None, saved)

    def values(self) -> dict:
        return {
            "hotkey_region": self.key_region.hotkey(),
            "hotkey_fullscreen": self.key_full.hotkey(),
            "hotkey_both_layouts": self.both_layouts.isChecked(),
            "show_zoom": self.show_zoom.isChecked(),
            "show_size": self.show_size.isChecked(),
            "remember_region": self.remember.isChecked(),
            "ocr_enabled": self.ocr_enabled.isChecked(),
            "translate_enabled": self.tr_enabled.isChecked(),
            "translate_to": self.tr_to.currentData(),
            "translate_alt": self.tr_alt.currentData(),
            "translate_engine": self.tr_engine.currentData(),
            "translate_email": self.tr_email.text().strip(),
            "ocr_quality": self.ocr_quality.currentData(),
            "ocr_langs": self.ocr_langs.currentData(),
            "tray_click": self.tray_click.currentData(),
            "save_dir": self.save_dir.text().strip() or self.config.get("save_dir", "~"),
            "save_format": self.save_format.currentData(),
            "save_ask": not self.save_ask.isChecked(),
            "auto_save": self.auto_save.isChecked(),
            "auto_save_dir": self.auto_save_dir.text().strip() or self.config.get("auto_save_dir", ""),
            "autostart": self.autostart.isChecked(),
            "update_check": self.update_check.isChecked(),
            "ui_accent": self.colors["ui_accent"].property("color"),
            "ui_panel": self.colors["ui_panel"].property("color"),
            "ui_field": self.colors["ui_field"].property("color"),
            "ui_frame": self.frame.currentData(),
            "editor_frame_style": self.frame_style.currentData(),
            "editor_system_title": self.system_title.isChecked(),
            "ui_theme": self.ui_theme.currentData(),
            "language": self.language.currentData(),
        }
