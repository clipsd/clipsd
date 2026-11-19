# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Названия клавиш для горячих сочетаний: формат настроек ↔ GNOME/X11 ↔ Windows. Без Qt."""

# Особые клавиши: название в настройках → (имя keysym X11/GNOME, код VK Windows, подпись в списке)
SPECIAL = {
    "Print": ("Print", 0x2C, "Print Screen"),
    "Space": ("space", 0x20, "keys.space"),
    "Insert": ("Insert", 0x2D, "Insert"),
    "Delete": ("Delete", 0x2E, "Delete"),
    "Home": ("Home", 0x24, "Home"),
    "End": ("End", 0x23, "End"),
    "PageUp": ("Page_Up", 0x21, "Page Up"),
    "PageDown": ("Page_Down", 0x22, "Page Down"),
    "Tab": ("Tab", 0x09, "Tab"),
    "Backspace": ("BackSpace", 0x08, "Backspace"),
    "Pause": ("Pause", 0x13, "Pause"),
    "ScrollLock": ("Scroll_Lock", 0x91, "Scroll Lock"),
    "-": ("minus", 0xBD, "keys.minus"),
    "=": ("equal", 0xBB, "keys.equal"),
    "[": ("bracketleft", 0xDB, "keys.bracketleft"),
    "]": ("bracketright", 0xDD, "keys.bracketright"),
    ";": ("semicolon", 0xBA, "keys.semicolon"),
    "'": ("apostrophe", 0xDE, "keys.apostrophe"),
    ",": ("comma", 0xBC, "keys.comma"),
    ".": ("period", 0xBE, "keys.period"),
    "/": ("slash", 0xBF, "/"),
    "\\": ("backslash", 0xDC, "\\"),
    "`": ("grave", 0xC0, "keys.grave"),
}
for _n in range(1, 25):
    SPECIAL[f"F{_n}"] = (f"F{_n}", 0x6F + _n, f"F{_n}")

# Синонимы, которые выдаёт запись сочетания в Qt
ALIASES = {"Ins": "Insert", "Del": "Delete", "PgUp": "PageUp", "PgDown": "PageDown", "Backtab": "Tab",
           "SysReq": "Print", "Scroll Lock": "ScrollLock", "Esc": "Escape"}

LETTERS_DIGITS = [chr(c) for c in range(ord("A"), ord("Z") + 1)] + [str(d) for d in range(10)]


def canonical(key: str) -> str:
    key = ALIASES.get(key, key)
    return key.upper() if len(key) == 1 and key.isalpha() else key


def x_keysym_name(key: str):
    """Имя keysym для X11/GNOME или None."""
    key = canonical(key)
    if len(key) == 1 and key.isalnum():
        return key.lower()
    return SPECIAL.get(key, (None,))[0]


# Коды физических клавиш (evdev) латинских букв и цифр. Код xkb = evdev + 8.
_EVDEV = {**dict(zip("QWERTYUIOP", range(16, 26))), **dict(zip("ASDFGHJKL", range(30, 39))),
          **dict(zip("ZXCVBNM", range(44, 51))), **dict(zip("1234567890", range(2, 12)))}


def xkb_keycode(key: str):
    """Код физической клавиши для GNOME («0x19» для W) или None. Такое сочетание не зависит от раскладки."""
    code = _EVDEV.get(canonical(key))
    return f"0x{code + 8:02x}" if code is not None else None


def windows_vk(key: str):
    key = canonical(key)
    if len(key) == 1 and key.isascii() and key.isalnum():
        return ord(key.upper())
    return SPECIAL.get(key, (None, None))[1]


def choices():
    """(значение, подпись) для списка клавиш в настройках."""
    from .i18n import tr
    return [(k, k) for k in LETTERS_DIGITS] + [(k, tr(v[2]) if v[2].startswith("keys.") else v[2])
                                              for k, v in SPECIAL.items()]
