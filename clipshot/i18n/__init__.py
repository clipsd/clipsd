# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
"""Translations: tr("key", **fields), plural forms, language choice.

Catalog layout: clipshot/i18n/<lang>/<area>.json, every file is a flat {"key": "text"} object.
Files of one language are merged, so each module keeps its own file (no merge conflicts).
Russian (ru) is the source text and the reference set of keys: a test fails if another language
misses a key. Lookup chain: chosen language -> en (if the chosen one is not ru) -> ru -> the key itself.
Plural forms: a value may be an object {"one": ..., "few": ..., "many": ..., "other": ...};
call tr("key", n=5) and the CLDR category for the current language is picked.
CLIPSD_LANG=<code> in the environment wins over settings (tests, screenshots).
tr() must be called when a text is shown, never at module import: the language may change at runtime.
"""
import json
import locale
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LANGUAGES = ["ru", "en", "bg", "uk", "de", "fr", "es", "it", "pt", "pl", "tr", "zh"]
REFERENCE = "ru"
# Название языка на нём самом: в меню выбора языка не переводится
LANGUAGE_NAMES = {"ru": "Русский", "en": "English", "bg": "Български", "uk": "Українська", "de": "Deutsch",
                  "fr": "Français", "es": "Español", "it": "Italiano", "pt": "Português", "pl": "Polski",
                  "tr": "Türkçe", "zh": "中文"}
# «Как в системе» на всех языках сразу не пишем: пункт подписан на текущем языке, плюс значок
AUTO = "auto"

_current = os.environ.get("CLIPSD_LANG") if os.environ.get("CLIPSD_LANG") in LANGUAGES else REFERENCE
_choice = _current
_source = "env" if os.environ.get("CLIPSD_LANG") in LANGUAGES else "default"
_catalogs: dict = {}
_missing: set = set()
_listeners: list = []


def _load(lang: str) -> dict:
    if lang not in _catalogs:
        merged = {}
        folder = HERE / lang
        if folder.is_dir():
            for f in sorted(folder.glob("*.json")):
                try:
                    merged.update(json.loads(f.read_text(encoding="utf-8")))
                except (OSError, ValueError) as e:
                    print(f"i18n: не прочитан {f}: {e}", file=sys.stderr)
        if lang == REFERENCE and not merged:
            # Папка ru не попала в сборку или пуста: встроенный запасной каталог, ключи на экран не выходят
            from .ru_builtin import CATALOG
            merged = dict(CATALOG)
            print(f"i18n: нет каталога {folder}, взят встроенный русский ({len(merged)} ключей)", file=sys.stderr)
        _catalogs[lang] = merged
    return _catalogs[lang]


def selfcheck() -> list:
    """Самопроверка сборки (clipsd --selfcheck): каталог ru на месте, tr("app.name") не ключ, 12 языков полные.
    Возвращает список проблем (пусто: всё хорошо)."""
    problems = []
    for lang in LANGUAGES:
        folder = HERE / lang
        if not folder.is_dir() or not any(folder.glob("*.json")):
            problems.append(f"нет каталога {lang}: {folder}")
    ref = set(_load(REFERENCE))
    for lang in LANGUAGES[1:]:
        missing = ref - set(_load(lang))
        if missing:
            problems.append(f"{lang}: нет {len(missing)} ключей, например {sorted(missing)[:3]}")
    if _render("app.name", REFERENCE, {}) == "app.name":
        problems.append('tr("app.name") вернул ключ')
    return problems


def selfcheck_lines() -> list:
    """Строки для отчёта самопроверки сборки. Первая строка «i18n ok: …» или «i18n FAILED: …», дальше проблемы.
    Встраивание в самопроверку 1.30 (packaging/*/clipsd_*.py, _selfcheck): после импорта clipshot добавить
        from clipshot import i18n
        lines = i18n.selfcheck_lines(); text += "\n".join(lines) + "\n"
        if not lines[0].startswith("i18n ok"): raise AssertionError(lines[0])   # 1.30 пишет FAILED и код 1
    Сборка без каталогов при этом не выйдет: build_linux.sh и build.ps1 уже падают на любом FAILED."""
    problems = selfcheck()
    if not problems:
        return [f"i18n ok: {len(LANGUAGES)} languages, {len(_load(REFERENCE))} keys"]
    return [f"i18n FAILED: {len(problems)} problem(s)"] + problems


def system_language() -> str:
    candidates = [os.environ.get(v, "") for v in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG")]
    try:
        candidates.append(locale.getlocale()[0] or "")
    except ValueError:
        pass
    if os.name == "nt":
        try:
            import ctypes
            lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            candidates.insert(0, locale.windows_locale.get(lcid, ""))
        except Exception:
            pass
    for c in candidates:
        for part in c.split(":"):
            code = part.split("_")[0].split(".")[0].split("-")[0].lower()
            if code == "ua":
                code = "uk"
            if code in LANGUAGES:
                return code
    return "en"


def resolve(choice) -> str:
    """Код языка для значения настройки: код из списка, иначе (auto, None, мусор) язык системы."""
    return choice if choice in LANGUAGES else system_language()


def set_language(choice, notify: bool = True) -> str:
    """choice: код языка или "auto" (язык системы). CLIPSD_LANG в окружении важнее.
    Возвращает язык, который реально включён; подписчики on_change узнают о смене."""
    global _current, _choice, _source
    env = os.environ.get("CLIPSD_LANG")
    old = _current
    _choice = choice if choice in LANGUAGES else AUTO
    if env in LANGUAGES:
        _current, _source = env, "env"
    elif choice in LANGUAGES:
        _current, _source = choice, "settings"
    else:
        _current, _source = system_language(), "system"
    print(f"i18n: язык {_current} ({_source}), ключей {len(_load(_current))}", file=sys.stderr)
    if notify and _current != old:
        for cb in list(_listeners):
            try:
                cb(_current)
            except Exception as e:      # окно уже закрыто и т.п.: смена языка не должна ронять программу
                print(f"i18n: подписчик смены языка: {e}", file=sys.stderr)
    return _current


def current() -> str:
    return _current


def choice() -> str:
    """Что выбрано в настройках: код языка или "auto"."""
    return _choice


def on_change(callback):
    """callback(lang) после смены языка. Возвращает функцию отписки."""
    _listeners.append(callback)

    def off():
        if callback in _listeners:
            _listeners.remove(callback)
    return off


def plural_category(lang: str, n: int) -> str:
    n = abs(int(n))
    if lang in ("ru", "uk"):
        if n % 10 == 1 and n % 100 != 11:
            return "one"
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
            return "few"
        return "many"
    if lang == "pl":
        if n == 1:
            return "one"
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
            return "few"
        return "many"
    if lang in ("fr", "pt"):
        return "one" if n in (0, 1) else "other"
    if lang == "zh":
        return "other"
    return "one" if n == 1 else "other"


def lookup(key: str, lang: str | None = None):
    """Значение ключа и язык, откуда оно взято: выбранный -> en (если выбран не ru) -> ru -> None."""
    lang = lang or _current
    chain = [lang] + (["en"] if lang != REFERENCE else []) + [REFERENCE]
    for code in chain:
        value = _load(code).get(key)
        if value is not None:
            return value, code
    return None, lang


def _render(key: str, lang: str, fields: dict) -> str:
    value, found = lookup(key, lang)
    if value is None:
        if key not in _missing:
            _missing.add(key)
            print(f"i18n: нет ключа {key}", file=sys.stderr)
        return key
    if isinstance(value, dict):
        cat = plural_category(found, fields.get("n", 0))
        value = value.get(cat) or value.get("other") or value.get("many") or next(iter(value.values()))
    try:
        return value.format(**fields) if fields else value
    except (KeyError, IndexError, ValueError):
        return value


def tr(key: str, **fields) -> str:
    return _render(key, _current, fields)


_QT_LOCALES = {"ru": "ru_RU", "en": "en_US", "zh": "zh_CN", "pt": "pt_BR", "uk": "uk_UA"}


# Разделитель тысяч как в текстах каталога (5 000, 5.000, 5,000…); испанский: четыре цифры без разделителя (RAE)
_THOUSANDS = {"ru": " ", "bg": " ", "uk": " ", "pl": " ", "es": "\u00a0", "it": ".", "pt": ".", "tr": ".", "de": ".",
              "fr": "\u202f", "en": ",", "zh": ","}
_FOUR_DIGITS_PLAIN = {"es"}


def number(x) -> str:
    """Целое число по правилам языка интерфейса и так же, как числа в текстах каталога:
    ru, bg, uk, pl «5 000», de, it, pt, tr «5.000», en, zh «5,000», fr «5 000» (узкий пробел), es «5000», «50 000»."""
    x = int(x)
    sign, digits = ("-" if x < 0 else ""), str(abs(x))
    if len(digits) <= 3 or (len(digits) == 4 and _current in _FOUR_DIGITS_PLAIN):
        return sign + digits
    return sign + f"{abs(x):,}".replace(",", _THOUSANDS.get(_current, ","))


def keys(text: str) -> str:
    """Названия клавиш в сочетании для показа: на немецком «Strg» вместо «Ctrl» (так подписана клавиша)."""
    if _current == "de" and text:
        import re
        return re.sub(r"\bCtrl\b", "Strg", text)
    return text


def tr_in(lang: str, key: str, **fields) -> str:
    """Текст на заданном языке, не меняя текущий (подпись «Язык · Language»)."""
    return _render(key, lang, fields)


class dynamic:
    """Надпись-атрибут класса, которая читается заново при каждом обращении (и у класса, и у объекта):
    BAR_SUB = dynamic(lambda self: {...: tr(...)}). Обычный @property у класса отдаёт сам property."""

    def __init__(self, fn):
        self.fn = fn

    def __get__(self, obj, owner=None):
        return self.fn(obj if obj is not None else owner)
