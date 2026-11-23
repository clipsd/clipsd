# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Окно настроек: горячие клавиши, выделение, трей, сохранение, автозапуск."""

import ast
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import QPoint, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QKeySequence
from PyQt6.QtWidgets import (QApplication, QButtonGroup, QSizePolicy, QStackedWidget, QCheckBox, QColorDialog, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout,
                             QHBoxLayout, QLabel, QLineEdit, QKeySequenceEdit, QPushButton, QScrollArea, QStyle, QVBoxLayout,
                             QWidget)

from .i18n import tr
from .i18n import keys as i18n_keys
from .sysenv import child_env, open_url

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
                                 capture_output=True, text=True, timeout=5, env=child_env()).stdout
        except (OSError, subprocess.SubprocessError):
            return False
        return "'state': <1.0>" in out or "'state': <1>" in out

    def set(self, key: str, values):
        subprocess.run(["gsettings", "--schemadir", str(self.dir / "schemas"), "set", EXT_SCHEMA, key, str(list(values))],
                       capture_output=True, timeout=5, env=child_env())


class GnomeHotkeys:
    """Сочетания ClipSD в GNOME. run и ext — для подмены в тестах.

    Если работает расширение ClipSD, сочетание с русским двойником пишется в него (один захват клавиши
    на обе раскладки), а обычное сочетание GNOME снимается. Иначе — обычное сочетание GNOME (одна раскладка)."""

    def __init__(self, run=None, ext="auto"):
        self.run = run or self._gsettings
        self.ext = ShellExtension() if ext == "auto" else ext

    @staticmethod
    def _gsettings(*args) -> str:
        out = subprocess.run(["gsettings", *args], capture_output=True, text=True, timeout=5, env=child_env())
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
        return subprocess.run(["systemctl", "--user", "is-enabled", "--quiet", unit], env=child_env()).returncode == 0
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
        subprocess.run(["systemctl", "--user", "enable" if enabled else "disable", unit], capture_output=True,
                       env=child_env())
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
        self.row = QGridLayout(self)
        row = self.row
        row.setContentsMargins(0, 0, 0, 0)
        row.setHorizontalSpacing(4)
        row.setVerticalSpacing(6)
        self.mod_buttons = {}
        self._parts = []
        for mod, label in self.MODS:
            label = i18n_keys(label)   # de: «Strg»
            button = QPushButton(label)
            button.setCheckable(True)
            # Ширина по тексту: при крупном системном шрифте «Shift» не обрезается.
            f14 = QFont()
            f14.setPixelSize(14)   # в карточках буквы 14 px: ширина считается по ним, а не по шрифту до стиля
            button.setMinimumWidth(QFontMetrics(f14).horizontalAdvance(label) + 22)
            button.setToolTip(tr("settings.mod_tip", name=label))
            self.mod_buttons[mod] = button
            self._parts.append(button)
        self._parts.append(QLabel("+"))
        self.key = QComboBox()
        self.key.addItem(tr("settings.key_none"), "")
        for key, label in _key_choices():
            self.key.addItem(label, key)
        self.key.setToolTip(tr("settings.key_tip"))
        self._parts.append(self.key)
        self.record_button = QPushButton(tr("settings.record"))
        self.record_button.setToolTip(tr("settings.record_tip"))
        self.record_button.clicked.connect(self.record)
        self.off_button = QPushButton(tr("settings.off"))
        self.off_button.clicked.connect(lambda: self.set_hotkey(""))
        self._tail = [self.record_button, self.off_button]
        self._narrow = None
        self._arrange(False)
        self.set_hotkey(value)

    def _arrange(self, narrow: bool):
        """Широко: всё в одну строку. Узко (150% на 1280x720): «Записать…» и «Выключить» переходят во вторую строку,
        ряд не даёт горизонтальной прокрутки."""
        if narrow == self._narrow:
            return
        self._narrow = narrow
        for w in self._parts + self._tail:
            self.row.removeWidget(w)
        for i, w in enumerate(self._parts):
            self.row.addWidget(w, 0, i)
        keycol = len(self._parts) - 1
        self.row.setColumnStretch(keycol, 1)
        if narrow:
            self.row.addWidget(self._tail[0], 1, 0, 1, 3)
            self.row.addWidget(self._tail[1], 1, 3, 1, keycol - 2)
        else:
            self.row.addWidget(self._tail[0], 0, len(self._parts))
            self.row.addWidget(self._tail[1], 0, len(self._parts) + 1)
        self.updateGeometry()

    def _wide_width(self) -> int:
        widgets = self._parts + self._tail
        return sum(max(w.minimumSizeHint().width(), w.sizeHint().width() if w is not self.key else 110) for w in widgets) + 4 * len(widgets)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._arrange(event.size().width() < self._wide_width())

    def minimumSizeHint(self):
        return QSize(sum(w.minimumSizeHint().width() for w in self._parts) + 4 * len(self._parts), 36)

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


class WrapCheck(QCheckBox):
    """Флажок с подписью, которая переносится по строкам (длинные подписи на 12 языках не раздвигают окно)."""

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._text = text
        box = QHBoxLayout(self)
        box.setContentsMargins(26, 0, 0, 0)
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)   # щелчок по подписи ставит флажок
        box.addWidget(self.label)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

    def text(self):
        return self._text

    def setText(self, text):
        self._text = text
        self.label.setText(text)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return max(22, self.layout().heightForWidth(w))

    def sizeHint(self):
        s = self.layout().sizeHint()
        return QSize(s.width(), max(22, s.height()))

    def minimumSizeHint(self):
        return QSize(120, max(22, self.layout().minimumSize().height()))


# --- окно ---------------------------------------------------------------------

def _luminance(c) -> float:
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c.red()) + 0.7152 * ch(c.green()) + 0.0722 * ch(c.blue())


def _readable(fg, bg, need: float = 4.5):
    """Цвет fg, затемнённый (на светлом фоне) или осветлённый (на тёмном), пока контраст к bg не станет не ниже need."""
    from PyQt6.QtGui import QColor
    lb = _luminance(bg)
    dark_bg = lb < 0.18
    c = QColor(fg)
    for _ in range(40):
        lf = _luminance(c)
        hi, lo = max(lf, lb), min(lf, lb)
        if (hi + 0.05) / (lo + 0.05) >= need:
            break
        c = c.lighter(108) if dark_bg else c.darker(108)
    return c


def _themes_tokens(cfg) -> dict:
    from . import themes as _themes
    return _themes.tokens(cfg)


def settings_style(t) -> str:
    r = 10 if not t["dark"] else 3
    from PyQt6.QtGui import QColor as _C
    base, accent = _C(t["dialog_bg"]), _C(t["ui_accent"])
    t = dict(t)
    t["nav_bg"] = (base.lighter(112) if t["dark"] else base.darker(104)).name()
    t["nav_hover"] = f"rgba(128,128,128,{0.18 if t['dark'] else 0.12})"
    alpha = 0.28 if t["dark"] else 0.15
    t["nav_sel"] = f"rgba({accent.red()},{accent.green()},{accent.blue()},{alpha})"
    # Подпись выбранного раздела цветом акцента, но не бледнее 4,5:1 к своему фону (акцент поверх меню): на светлом
    # акцент темнеет, на тёмном светлеет (контраст текста 1.32; акцент #1e78ff на этом фоне давал 2,6:1)
    nav = _C(t["nav_bg"])
    sel_bg = _C(*(round(a * alpha + b * (1 - alpha)) for a, b in ((accent.red(), nav.red()), (accent.green(), nav.green()),
                                                                 (accent.blue(), nav.blue()))))
    t["nav_sel_text"] = _readable(accent, sel_bg).name()
    # кнопки с белым текстом (выбранный модификатор, «Сохранить»): синий по правилу контраста 4,5:1, не акцент
    from . import themes as _themes
    t["blue_bg"], t["blue_hover"], t["blue_border"] = _themes.blue_button(t["ui_accent"])
    t["error_text"] = _readable(_C("#d32f2f"), _C(t["dialog_bg"])).name()   # сообщение «не удалось применить»
    t["found_bg"] = "rgba(255,210,63,0.45)" if not t["dark"] else "rgba(255,210,63,0.30)"
    return f"""
QDialog {{ background: {t['dialog_bg']}; color: {t['text']}; }}
QLabel, QCheckBox {{ color: {t['text']}; font-size: 14px; }}
QLabel#section {{ font-size: 14px; font-weight: bold; color: {t['text']}; margin-top: 6px; }}
QScrollArea#settingsScroll, QWidget#settingsContent {{ background: transparent; }}
QLabel#hint, QLabel#footer {{ color: {t['text_dim']}; font-size: 14px; }}
QLabel#applyError {{ color: {t['error_text']}; font-size: 14px; }}
QFrame#card {{ background: {t['card_bg']}; border: 1px solid {t['card_border']}; border-radius: {r}px; }}
QKeySequenceEdit, QLineEdit, QComboBox {{ min-height: 32px; font-size: 14px; }}
QLineEdit, QComboBox {{ background: {t['input_bg']}; color: {t['text']}; border: 1px solid {t['button_border']};
    border-radius: {min(r, 4)}px; padding: 0 6px; }}
HotkeyEditor QPushButton {{ padding: 0 8px; }}
HotkeyEditor QPushButton:checked {{ background: {t['blue_bg']}; color: white; border-color: {t['blue_border']};
    font-weight: bold; }}
HotkeyEditor QPushButton:checked:hover {{ background: {t['blue_hover']}; border-color: {t['blue_border']}; }}
QPushButton {{ min-height: 32px; font-size: 14px; padding: 0 14px; border-radius: {min(r, 6)}px; border: 1px solid {t['button_border']};
    background: {t['button_bg']}; color: {t['button_text']}; }}
QPushButton:hover {{ background: {t['button_hover']}; border-color: {t['ui_accent']}; }}
QPushButton:disabled {{ background: transparent; color: {t['text_dim']}; border-color: {t['card_border']}; }}
QFrame#nav {{ background: {t['nav_bg']}; border-right: 1px solid {t['card_border']}; }}
QLineEdit#search {{ min-height: 30px; border-radius: 15px; padding: 0 12px; }}
QPushButton#navItem {{ text-align: left; min-height: 36px; padding: 0 10px; border: none; border-radius: 8px;
    background: transparent; color: {t['text']}; }}
QPushButton#navItem:hover {{ background: {t['nav_hover']}; border: none; }}
QPushButton#navItem:checked {{ background: {t['nav_sel']}; color: {t['nav_sel_text']}; font-weight: bold; border: none; }}
QLabel[found="true"], QCheckBox[found="true"], QPushButton[found="true"] {{ background: {t['found_bg']}; border-radius: 4px; }}
QFrame#card[found="true"] {{ border: 2px solid {t['ui_accent']}; }}
QPushButton#primary {{ background: {t['blue_bg']}; color: white; border: 1px solid {t['blue_border']}; font-weight: bold; }}
QPushButton#primary:hover {{ background: {t['blue_hover']}; border-color: {t['blue_border']}; }}
"""


class SettingsDialog(QDialog):
    language_rebuilt = pyqtSignal()   # окно перестроено на новом языке (после смены в списке)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = config
        self._parent = parent
        self.update_ctx = None   # приложение (ставит open_settings): без него кнопка ничего не запускает
        self.apply_handler = None   # values -> [(поля, текст ошибки)]: «Применить» и «ОК» применяют в приложении
        self._found_widgets = []
        self._building = False
        self._build(config)
        # что уже применено: «Применить» неактивна, пока окно совпадает с этим; «Отмена» возвращает язык и вид
        self._baseline = self._snapshot()
        self._applied = dict(self._baseline, settings_page=None)
        self._applied_style = self._style_cfg(self._baseline)
        self._refresh_apply()

    def _build(self, config: dict):
        """Строит содержимое окна; при смене языка окно строится заново на новом языке (_language_chosen)."""
        from . import __author__, __version__
        self._building = True
        self.config = config
        self.setWindowTitle(tr("settings.title"))
        from . import themes as _themes
        self.setStyleSheet(settings_style(_themes.tokens(config)))
        # 1.32: слева меню разделов с поиском, справа страница выбранного раздела; страницы прокручиваются,
        # «Отмена» и «Сохранить» всегда видны
        from . import icons
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 14)
        outer.setSpacing(10)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        outer.addLayout(body, 1)
        self.nav = QFrame()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(224)
        nav_box = QVBoxLayout(self.nav)
        nav_box.setContentsMargins(10, 12, 10, 10)
        nav_box.setSpacing(4)
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText(tr("settings.search"))
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName(tr("settings.search"))
        nav_box.addWidget(self.search)
        nav_box.addSpacing(6)
        self.nav_group = QButtonGroup(self)
        self.nav_buttons = {}
        self.pages = {}       # ключ раздела -> (область прокрутки, раскладка страницы)
        self._cards = []      # (ключ раздела, заголовок карточки, ключ синонимов, рамка карточки)
        self.stack = QStackedWidget()
        self.stack.setObjectName("pages")
        # значки разделов: светлое: TILE_SUB (5,2:1, прежний серый был бледнее), тёмное: приглушённый текст
        nav_icon = _themes.TILE_SUB if not _themes.tokens(config)["dark"] else _themes.tokens(config)["text_dim"]
        for key, title_key, icon_name in self.SECTIONS:
            button = QPushButton(tr(title_key))
            button.setObjectName("navItem")
            button.setCheckable(True)
            button.setIcon(icons.icon(icon_name, nav_icon))
            button.setIconSize(QSize(20, 20))
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.nav_group.addButton(button)
            self.nav_buttons[key] = button
            nav_box.addWidget(button)
            button.clicked.connect(lambda _c=False, k=key: self.show_section(k))
            scroll = QScrollArea()
            scroll.setObjectName("settingsScroll")
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            scroll.viewport().setAutoFillBackground(False)
            content = QWidget()
            content.setObjectName("settingsContent")
            page = QVBoxLayout(content)
            page.setContentsMargins(18, 14, 18, 8)
            page.setSpacing(6)
            scroll.setWidget(content)
            self.stack.addWidget(scroll)
            self.pages[key] = (scroll, page)
        self.search_none = QLabel(tr("settings.search_none"))
        self.search_none.setObjectName("hint")
        self.search_none.setWordWrap(True)
        self.search_none.hide()
        nav_box.addWidget(self.search_none)
        nav_box.addStretch(1)
        body.addWidget(self.nav)
        body.addWidget(self.stack, 1)
        pg = {key: layout for key, (_scroll, layout) in self.pages.items()}
        self._root_key = {id(layout): key for key, layout in pg.items()}

        # Язык (1.31): первым разделом, с глобусом; языки на самих себе
        from . import icons, language
        grid = self._card(pg["general"], language.menu_title(), "language")
        globe = QLabel()
        globe.setPixmap(icons.icon("globe").pixmap(20, 20))
        grid.addWidget(globe, 0, 0)
        self.language = QComboBox()
        self.language.setIconSize(QSize(24, 16))
        for code, label in language.entries():
            self.language.addItem(icons.flag_icon(code), label, code)
        self.language.setCurrentIndex(max(0, self.language.findData(language.current_choice(self))))
        self.language.setAccessibleName(tr("settings.language"))
        self.language.currentIndexChanged.connect(self._language_chosen)   # 1.32: язык меняется сразу
        grid.addWidget(self.language, 0, 1, 1, 2)

        # Обновления (1.31.1): отдельный заметный блок: версия, «Проверить обновления», автопроверка
        from . import build_info
        grid = self._card(pg["updates"], tr("settings.sec_updates"), "updates")
        self.version_label = QLabel(tr("settings.version_line", version=build_info.version_label(__version__)))
        self.version_label.setObjectName("versionLine")
        grid.addWidget(self.version_label, 0, 0, 1, 2)
        self.check_updates = QPushButton(tr("updater.menu.check"))
        self.check_updates.clicked.connect(self._check_updates_now)
        grid.addWidget(self.check_updates, 0, 2, Qt.AlignmentFlag.AlignRight)
        self.update_check = self._check(grid, 1, tr("settings.update_check"), bool(config.get("update_check", True)))
        self.update_check.setToolTip(tr("settings.update_check_tip"))
        # 1.34: окно «Новое в версии» и метки «Новое» после обновления (novoe.py)
        self.novoe_enabled = self._check(grid, 2, tr("settings.novoe_enabled"), bool(config.get("novoe_enabled", True)))
        self.novoe_enabled.setToolTip(tr("settings.novoe_enabled_tip"))

        # Горячие клавиши
        grid = self._card(pg["general"], tr("settings.sec_hotkeys"), "hotkeys")
        self.key_region = self._hotkey_row(grid, 0, tr("settings.hotkey_region"), config.get("hotkey_region", ""))
        self.key_full = self._hotkey_row(grid, 1, tr("settings.hotkey_full"), config.get("hotkey_fullscreen", ""))
        self.both_layouts = WrapCheck(tr("settings.both_layouts"))
        self.both_layouts.setChecked(bool(config.get("hotkey_both_layouts", True)))
        grid.addWidget(self.both_layouts, 5, 0, 1, 3)
        hint = QLabel(tr("settings.hotkey_hint"))
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        grid.addWidget(hint, 4, 0, 1, 3)

        # Выделение
        grid = self._card(pg["shot"], tr("settings.sec_select"), "select")
        self.show_zoom = self._check(grid, 0, tr("settings.show_zoom"), config.get("show_zoom", True))
        self.show_size = self._check(grid, 1, tr("settings.show_size"), config.get("show_size", True))
        self.remember = self._check(grid, 2, tr("settings.remember"),
                                    config.get("remember_region", True))

        # Текст с картинки
        from . import ocr
        grid = self._card(pg["text"], tr("settings.sec_ocr"), "ocr")
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
        # 1.36: «Распознавание: русский, английский [Установить ещё язык]»; нет программы: блок с кнопкой установки
        self.ocr_status = ocr.OcrStatusRow(tokens=_themes.tokens(config))
        grid.addWidget(self.ocr_status, 3, 0, 1, 3)
        idle = QLabel(tr("settings.ocr_idle"))
        idle.setWordWrap(True)
        grid.addWidget(idle, 4, 0, 1, 3)
        help = ocr.engine_help(config.get("ocr_langs"))
        self.ocr_install = ocr.InstallBlock(help, tokens=_themes.tokens(config)) if help is not None else None
        if self.ocr_install is not None:
            self.ocr_install.installed.connect(lambda: self.ocr_status.set_codes(ocr.installed_codes()))
            grid.addWidget(self.ocr_install, 5, 0, 1, 3)
        for widget in (self.ocr_quality, self.ocr_langs):
            widget.setEnabled(self.ocr_enabled.isChecked())
            self.ocr_enabled.toggled.connect(widget.setEnabled)

        # Перевод с картинки
        from . import translate
        grid = self._card(pg["text"], tr("settings.sec_translate"), "translate")
        self.tr_enabled = self._check(grid, 0, tr("settings.tr_enable"),
                                      config.get("translate_enabled", True))
        names = translate.LANG_NAMES
        grid.addWidget(QLabel(tr("settings.tr_to")), 1, 0)
        self.tr_to = QComboBox()
        grid.addWidget(QLabel(tr("settings.tr_alt")), 2, 0)
        self.tr_alt = QComboBox()
        from . import icons
        self.tr_to.addItem(icons.flag_icon("auto"), translate.auto_label(config), "auto")
        for code in translate.TARGETS:   # 1.32: флаги языков, как в списке языка интерфейса
            self.tr_to.addItem(icons.flag_icon(code), names[code], code)
            self.tr_alt.addItem(icons.flag_icon(code), names[code], code)
        for box in (self.tr_to, self.tr_alt):
            box.setIconSize(QSize(24, 16))
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
        grid = self._card(pg["general"], tr("settings.sec_tray"), "tray")
        grid.addWidget(QLabel(tr("settings.tray_click")), 0, 0)
        self.tray_click = QComboBox()
        self.tray_click.addItem(tr("settings.tray_region"), "region")
        self.tray_click.addItem(tr("settings.tray_menu"), "menu")
        self.tray_click.setCurrentIndex(0 if config.get("tray_click", "region") == "region" else 1)
        grid.addWidget(self.tray_click, 0, 1, 1, 2)

        # Сохранение
        grid = self._card(pg["shot"], tr("settings.sec_save"), "save")
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
        # Экраны с масштабом (125–200 %): размер снимка и вставка в исходном размере
        from . import hidpi
        # 1.32: в списке короткие пункты, пояснение выбранного строкой под списком с переносом по словам: длинные
        # пункты обрезались в окне по разделам на экране 1280x720 при 150% (и шире шрифт, например DejaVu Sans)
        grid.addWidget(QLabel(tr("settings.snapshot_size")), 5, 0)
        self.snapshot_size = QComboBox()
        self.snapshot_size.addItem(tr("settings.size_full"), hidpi.SIZE_FULL)
        self.snapshot_size.addItem(tr("settings.size_screen"), hidpi.SIZE_SCREEN)
        self.snapshot_size_hint = QLabel()
        self.snapshot_size_hint.setObjectName("hint")
        self.snapshot_size_hint.setWordWrap(True)
        hints = {hidpi.SIZE_FULL: tr("settings.size_full_hint"), hidpi.SIZE_SCREEN: tr("settings.size_screen_hint")}

        def size_hint(_index=None):
            text = hints.get(self.snapshot_size.currentData(), "")
            self.snapshot_size_hint.setText(text)
            self.snapshot_size.setToolTip(f"{self.snapshot_size.currentText()}: {text}" if text else "")
        self.snapshot_size.currentIndexChanged.connect(size_hint)
        self.snapshot_size.setCurrentIndex(max(0, self.snapshot_size.findData(hidpi.size_mode(config))))
        size_hint()
        grid.addWidget(self.snapshot_size, 5, 1, 1, 2)
        grid.addWidget(self.snapshot_size_hint, 6, 1, 1, 2)
        self.clip_html = self._check(grid, 7, tr("settings.clip_html"), hidpi.html_enabled(config))
        self.clip_html.setToolTip(tr("settings.clip_html_tip"))
        # 1.36: PDF только вручную («Сохранить» с форматом PDF, «Сохранить в PDF»); автосохранение остаётся PNG/JPEG
        grid.addWidget(QLabel(tr("settings.pdf_page")), 8, 0)
        self.pdf_page = QComboBox()
        self.pdf_page.addItem(tr("settings.pdf_page_image"), "image")
        self.pdf_page.addItem(tr("settings.pdf_page_a4"), "a4")
        self.pdf_page.setCurrentIndex(1 if config.get("pdf_page", "image") == "a4" else 0)
        self.pdf_page.setToolTip(tr("settings.pdf_page_tip"))
        grid.addWidget(self.pdf_page, 8, 1, 1, 2)

        # Оформление
        from .editor import THEME_DEFAULTS, theme
        self.theme_defaults = THEME_DEFAULTS
        current = theme(config)
        grid = self._card(pg["editor"], tr("settings.sec_theme"), "theme")
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
        grid = self._card(pg["general"], tr("settings.sec_start"), "start")
        self.autostart = self._check(grid, 0, tr("settings.autostart"), autostart_enabled())
        # О программе: версия, лицензия, ссылка, оба знакомства
        grid = self._card(pg["about"], tr("settings.nav_about"), "about")
        self.want_tour = False
        self.want_selector_tour = False
        about = QLabel(f"ClipSD {build_info.version_label(__version__)}\n© 2026 {__author__}\n" + tr("app.about_license"))
        about.setWordWrap(True)
        about.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        grid.addWidget(about, 0, 0, 1, 3)
        site = QLabel('<a href="https://clipsd.github.io">clipsd.github.io</a>')
        site.linkActivated.connect(open_url)   # not Qt's own opener: see sysenv.open_url
        grid.addWidget(site, 1, 0, 1, 3)
        # Название и значок (TRADEMARKS.md, раздел 7 GPLv3): та же ссылка, что в окне «О программе»
        from html import escape
        from .i18n import current
        page = f"https://clipsd.github.io/{'ru' if current() == 'ru' else 'en'}/trademarks.html"
        terms = QLabel(f'<a href="{page}">{escape(tr("app.about_trademark"))}</a>')
        terms.setWordWrap(True)
        terms.linkActivated.connect(open_url)
        grid.addWidget(terms, 2, 0, 1, 3)
        from . import links   # канал Telegram с новостями (1.32), как в окне «О программе»
        telegram = QLabel(f'<a href="{links.TELEGRAM_URL}">{escape(tr("links.telegram_about", url=links.TELEGRAM_SHORT))}</a>')
        telegram.setWordWrap(True)
        telegram.setToolTip(tr("links.telegram_tip"))
        telegram.linkActivated.connect(open_url)
        grid.addWidget(telegram, 3, 0, 1, 3)
        tour = QPushButton(tr("settings.tour_again"))
        tour.clicked.connect(self._request_tour)
        grid.addWidget(tour, 4, 0, 1, 3, Qt.AlignmentFlag.AlignLeft)
        tour_sel = QPushButton(tr("app.menu_tour_selector"))
        tour_sel.clicked.connect(self._request_selector_tour)
        grid.addWidget(tour_sel, 5, 0, 1, 3, Qt.AlignmentFlag.AlignLeft)
        self.tour_button, self.tour_selector_button = tour, tour_sel

        for box in self.findChildren(QComboBox):   # ширина по полю, а не по самому длинному пункту
            box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            box.setMinimumContentsLength(10)
        for label in self.stack.findChildren(QLabel):   # подписи переносятся, длинная подпись не раздвигает окно
            if label.pixmap().isNull() and label.textFormat() != Qt.TextFormat.RichText:
                label.setWordWrap(True)
        for layout in pg.values():
            layout.addStretch(1)
        self.apply_error = QLabel()   # «Не удалось применить»: сообщение в окне, остальное уже применено
        self.apply_error.setObjectName("applyError")
        self.apply_error.setWordWrap(True)
        self.apply_error.setAccessibleName(tr("settings.apply"))
        self.apply_error.hide()
        err_row = QHBoxLayout()
        err_row.setContentsMargins(18, 0, 18, 0)
        err_row.addWidget(self.apply_error)
        outer.addLayout(err_row)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(18, 0, 18, 0)
        # Как в Windows: «ОК», «Отмена», «Применить»; порядок не зависит от языка
        self.apply_note = QLabel("")   # серое «Применено» после «Применить», пока нет новых правок
        self.apply_note.setObjectName("hint")
        buttons.addWidget(self.apply_note)
        buttons.addStretch(1)
        save = QPushButton(tr("settings.ok"))
        save.setObjectName("primary")
        save.setDefault(True)
        save.clicked.connect(self.accept)
        cancel = QPushButton(tr("settings.cancel"))
        cancel.clicked.connect(self.reject)
        self.apply_button = QPushButton(tr("settings.apply"))
        self.apply_button.clicked.connect(self.apply_now)
        self.ok_button, self.cancel_button = save, cancel
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        buttons.addWidget(self.apply_button)
        outer.addLayout(buttons)
        self._watch_changes()
        self.search.textChanged.connect(self._search_changed)
        first = config.get("settings_page")
        self.show_section(first if first in self.pages else "general")
        self._fit_to_screen(self._parent)
        self._building = False
        self._refresh_apply()

    # --- «Применить» ---------------------------------------------------------

    def _watch_changes(self):
        """Любая правка в окне пересчитывает, активна ли «Применить»."""
        for box in self.findChildren(QCheckBox):
            box.toggled.connect(self._refresh_apply)
        for box in self.findChildren(QComboBox):
            box.currentIndexChanged.connect(self._refresh_apply)
        for edit in self.findChildren(QLineEdit):
            if edit is not self.search and edit.objectName() != "search":
                edit.textChanged.connect(self._refresh_apply)
        for button in self.findChildren(QPushButton):
            if button.isCheckable() and button.objectName() != "navItem":
                button.toggled.connect(self._refresh_apply)   # Ctrl/Shift/Alt/Win в сочетаниях

    def _snapshot(self) -> dict:
        values = self.values()
        values.pop("settings_page", None)   # раздел окна настройкой не считается
        return values

    @staticmethod
    def _style_cfg(values: dict) -> dict:
        return {k: values.get(k) for k in ("ui_theme", "ui_accent", "ui_panel", "ui_field", "ui_frame")}

    def has_changes(self) -> bool:
        """В окне есть то, что ещё не применено."""
        return not self._building and self._snapshot() != self._baseline

    def _refresh_apply(self, *_args):
        if self._building or not hasattr(self, "_baseline") or getattr(self, "apply_button", None) is None:
            return
        dirty = self.has_changes()
        self.apply_button.setEnabled(dirty)
        if dirty:
            self.apply_note.setText("")
            self.apply_error.hide()

    def show_apply_errors(self, texts):
        self.apply_error.setText("\n".join(texts))
        self.apply_error.setVisible(bool(texts))
        if texts:
            self.apply_note.setText("")

    def apply_now(self) -> bool:
        """«Применить»: сохранить и применить всё изменённое сейчас, окно остаётся открытым. True: без ошибок.
        Что не вышло (сочетание занято, автозапуск), показано в окне; остальное применено."""
        values = self.values()
        errors = []
        if self.apply_handler is not None:
            errors = self.apply_handler(dict(values)) or []
        failed = {key for keys, _text in errors for key in keys}
        shot = dict(values)
        shot.pop("settings_page", None)
        for key in failed:   # не применённое остаётся «изменённым»: «Применить» повторит попытку
            shot[key] = self._baseline.get(key)
        self._baseline = shot
        self._applied = dict(shot)
        for key, value in values.items():
            if key not in failed and key not in ("autostart", "settings_page"):
                self.config[key] = value
        self._applied_style = self._style_cfg(shot)
        self.setStyleSheet(settings_style(_themes_tokens(self._applied_style)))
        self._refresh_apply()
        self.show_apply_errors([text for _keys, text in errors])   # после пересчёта: он прячет прежнее сообщение
        self.apply_note.setText("" if errors else tr("settings.applied"))
        return not errors

    def accept(self):
        """«ОК»: применить и закрыть. Не вышло применить (занято сочетание): окно остаётся, сообщение в нём."""
        if self.apply_handler is not None and self.has_changes():
            if not self.apply_now() and not (self.want_tour or self.want_selector_tour):
                return
        super().accept()

    def reject(self):
        """«Отмена» и крестик: то, что не применено, не применяется; язык и вид, показанные как предпросмотр,
        возвращаются прежними. Уже применённое остаётся."""
        self._revert_preview()
        super().reject()

    def _revert_preview(self):
        from . import language
        ctx = self.update_ctx if self.update_ctx is not None else self
        wanted = self._applied.get("language")
        if wanted is not None and language.current_choice(ctx) != wanted:
            language.change(ctx, wanted)
        self.setStyleSheet(settings_style(_themes_tokens(self._applied_style)))

    # --- разделы и поиск (1.32) --------------------------------------------

    SECTIONS = (("general", "settings.nav_general", "settings"), ("shot", "settings.nav_shot", "region"),
                ("editor", "settings.nav_editor", "pipette"), ("text", "settings.nav_text", "translate"),
                ("updates", "settings.nav_updates", "update"), ("about", "settings.nav_about", "info"))
    # английские слова для поиска: находят раздел и карточку и на русском интерфейсе
    SYNONYMS = {
        "language": "language lang locale", "updates": "update upgrade version check release new whats news features highlight",
        "hotkeys": "hotkey shortcut keyboard key combination alt ctrl shift win", "tray": "tray icon click notification area",
        "start": "startup autostart launch login boot", "select": "selection area zoom magnifier size remember region capture",
        "save": "save folder directory format png jpg jpeg pdf page a4 print file autosave size scale scaling resolution dpi hidpi clipboard", "theme": "theme style appearance color dark light frame border editor",
        "ocr": "ocr text recognition tesseract languages", "translate": "translate translation engine google mymemory email key limit",
        "about": "about license version tour intro help gpl site telegram news channel trademark name icon terms",
    }
    SECTION_WORDS = {"general": "main general language hotkeys tray startup", "shot": "screenshot capture save folder format",
                     "editor": "editor theme style appearance look design color colors dark light", "text": "text ocr translate translation recognition",
                     "updates": "updates update version", "about": "about license tour"}

    @property
    def scroll(self):
        """Область прокрутки открытой страницы."""
        return self.pages[self.current_section()][0]

    def current_section(self) -> str:
        return next((k for k, (sc, _l) in self.pages.items() if sc is self.stack.currentWidget()), "general")

    def show_section(self, key: str):
        if key not in self.pages:
            return
        self.stack.setCurrentWidget(self.pages[key][0])
        self.nav_buttons[key].setChecked(True)
        self.config["settings_page"] = key   # окно помнит последний раздел

    def _search_changed(self, _text=None):
        """Поиск по названиям и подсказкам на языке интерфейса и по английским словам: меню показывает разделы с
        совпадениями, найденное подсвечивается."""
        query = self.search.text().strip().casefold()
        hits = self.search_hits(query)
        for w in self._found_widgets:
            w.setProperty("found", False)
            w.style().unpolish(w)
            w.style().polish(w)
        self._found_widgets = []
        for key, button in self.nav_buttons.items():
            button.setVisible(not query or key in hits)
        self.search_none.setVisible(bool(query) and not hits)
        if not query or not hits:
            return
        for widgets in hits.values():
            for w in widgets:
                w.setProperty("found", True)
                w.style().unpolish(w)
                w.style().polish(w)
                self._found_widgets.append(w)
        if self.current_section() not in hits:
            self.show_section(next(k for k, _l, _i in self.SECTIONS if k in hits))
        shown = hits[self.current_section()]
        if shown:
            QTimer.singleShot(0, lambda: self._reveal(shown[0]))

    def _reveal(self, widget):
        try:
            bar = self.scroll.verticalScrollBar()
            bar.setValue(max(0, widget.mapTo(self.scroll.widget(), QPoint(0, 0)).y() - 36))
        except RuntimeError:
            pass

    def search_hits(self, query: str) -> dict:
        """{раздел: [найденные виджеты]} для запроса (регистр не важен); пустой запрос: пусто."""
        out = {}
        if not query:
            return out
        for key, title_key, _icon in self.SECTIONS:
            words = (tr(title_key) + " " + self.SECTION_WORDS.get(key, "")).casefold()
            if query in words:
                out.setdefault(key, [])
        for section, title, syn, card in self._cards:
            matched = []
            if query in (title + " " + self.SYNONYMS.get(syn, "")).casefold():
                matched.append(card)
            for w in card.findChildren(QWidget):
                if isinstance(w, HotkeyEditor):
                    if query in w.hotkey().casefold() and getattr(w, "label", None) is not None:
                        matched.append(w.label)
                    continue
                if isinstance(w, (QLabel, QCheckBox, QPushButton)) and w.objectName() != "navItem":
                    text = (w.text() if not isinstance(w, QLabel) or w.textFormat() != Qt.TextFormat.RichText else "")
                    if query in (text + " " + w.toolTip()).casefold().replace("&", ""):
                        matched.append(w)
            if matched:
                out.setdefault(section, []).extend(matched)
        for widgets in out.values():   # сначала карточки (совпал заголовок), потом отдельные строки
            widgets.sort(key=lambda w: 0 if isinstance(w, QFrame) else 1)
        return out

    def _request_selector_tour(self):
        self.want_selector_tour = True
        self.accept()

    def _fit_to_screen(self, parent):
        """Окно не больше 860x620 и не больше экрана (150% на 1280x720: меньше, страницы прокручиваются)."""
        screen = (parent.screen() if parent is not None else None) or QApplication.primaryScreen()
        area = screen.availableGeometry() if screen is not None else None
        width, height = 860, 620
        if area is not None:
            width, height = min(width, area.width() - 40), min(height, area.height() - 60)
        self.setMinimumSize(0, 0)
        self.resize(width, height)

    def _language_chosen(self, _index=None):
        """Язык выбран в списке: применяется сразу (как глобус в редакторе), окно настроек перестраивается на новом
        языке без закрытия, несохранённые правки остаются. Это предпросмотр: «Отмена» без «Применить» возвращает прежний язык."""
        from . import language
        code = self.language.currentData()
        if code == language.current_choice(self):
            return
        pending = self.values()
        language.change(self.update_ctx if self.update_ctx is not None else self, code)
        cfg = dict(self.config)
        cfg.update(pending)
        cfg["language"] = code
        QTimer.singleShot(0, lambda: self._rebuild(cfg, pending))   # список, из которого пришёл сигнал, удаляется позже

    def _rebuild(self, cfg: dict, pending: dict):
        size, section, query = self.size(), self.current_section(), self.search.text()
        old = QWidget()
        old.setLayout(self.layout())   # старое содержимое уходит вместе с временным окном
        old.deleteLater()
        self._found_widgets = []
        self._build(cfg)
        self.resize(size)
        self.autostart.setChecked(bool(pending.get("autostart")))
        self.show_section(section)
        self.search.setText(query)
        self.language_rebuilt.emit()

    def _email_min_width(self):
        """Подсказка в поле почты видна целиком на любом языке и при любой ширине экрана (шрифт после стилей окна)."""
        self.tr_email.ensurePolished()
        text = self.tr_email.placeholderText()
        self.tr_email.setMinimumWidth(QFontMetrics(self.tr_email.font()).horizontalAdvance(text) + 40)

    # --- построение --------------------------------------------------------

    def _card(self, root, title, syn="") -> QGridLayout:
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
        self._cards.append((self._root_key[id(root)], title, syn, card))
        return grid

    def _check(self, grid, row, text, value) -> QCheckBox:
        box = WrapCheck(text)
        box.setChecked(bool(value))
        grid.addWidget(box, row, 0, 1, 3)
        return box

    def _hotkey_row(self, grid, row, text, value) -> HotkeyEditor:
        label = QLabel(text + ":")
        grid.addWidget(label, 2 * row, 0, 1, 3)      # подпись над полем: поле с кнопками широкое
        editor = HotkeyEditor(value)
        editor.label = label
        grid.addWidget(editor, 2 * row + 1, 0, 1, 3)
        return editor

    def _check_updates_now(self):
        """«Проверить обновления»: тот же путь, что у пункта меню значка (из исходников: сообщение updater.disabled.dev)."""
        if self.update_ctx is None:
            return
        from . import updater
        updater.get_updater(self.update_ctx).check_now(manual=True)

    def _request_tour(self):
        self.want_tour = True
        self.accept()

    def _show_color(self, key, color):
        color = QColor(color).name()
        self.colors[key].setProperty("color", color)
        fg = "#000000" if QColor(color).lightnessF() > 0.6 else "#ffffff"
        self.colors[key].setText(color.upper())
        self.colors[key].setStyleSheet(f"QPushButton {{ background: {color}; color: {fg}; border: 1px solid #777; }}")
        self._refresh_apply()

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
        """Вид «Без цветной рамки»: цвет и толщина рамки на окно не влияют, пока он выбран; «Тонкая линия» (1.32):
        толщина не влияет (линия всегда тонкая), цвет акцента влияет."""
        style = self.frame_style.currentData()
        plain = style == "plain"
        tip = tr("settings.frame_inactive_tip") if plain else (tr("settings.frame_inactive_thin_tip") if style == "thin" else "")
        self.frame.setEnabled(style not in ("plain", "thin"))
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
            "snapshot_size": self.snapshot_size.currentData(),
            "pdf_page": self.pdf_page.currentData(),
            "clip_html": self.clip_html.isChecked(),
            "autostart": self.autostart.isChecked(),
            "update_check": self.update_check.isChecked(),
            "novoe_enabled": self.novoe_enabled.isChecked(),
            "ui_accent": self.colors["ui_accent"].property("color"),
            "ui_panel": self.colors["ui_panel"].property("color"),
            "ui_field": self.colors["ui_field"].property("color"),
            "ui_frame": self.frame.currentData(),
            "editor_frame_style": self.frame_style.currentData(),
            "frame_style_132": True,   # вид рамки выбран в окне настроек 1.32: «Свечение» больше не читается как «Тонкая линия»
            "editor_system_title": self.system_title.isChecked(),
            "ui_theme": self.ui_theme.currentData(),
            "language": self.language.currentData(),
            "settings_page": self.current_section(),
        }
