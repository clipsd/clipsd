# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Где лежат настройки.

Готовая сборка (установщик Windows, архив Linux, обновление) держит настройки в своей папке:
  Linux   ${XDG_CONFIG_HOME:-~/.config}/clipsd/
  Windows %APPDATA%\\ClipSD\\
Запуск из исходников (рабочая копия разработчика) оставляет прежнюю папку 1.x ${XDG_CONFIG_HOME:-~/.config}/clipshot/,
поэтому пакет и рабочая копия на одной машине не пишут в один файл.

При первом настоящем запуске готовой сборки настройки 1.x копируются (не переносятся) в новую папку один раз:
config.json, ключ Google (google-translate.key) и счётчик бесплатного перевода (translate-usage.json).
Оригиналы не трогаются. Импорт модулей (selfcheck сборки, тесты) ничего не пишет.
"""

import os
import sys
from pathlib import Path

LEGACY_FILES = ("config.json", "google-translate.key", "translate-usage.json")


def _xdg_config() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def legacy_config_dir() -> Path:
    """Папка настроек 1.x: ~/.config/clipshot (и в Windows, где её писал установщик 1.x)."""
    return _xdg_config() / "clipshot"


def is_package_build() -> bool:
    return bool(getattr(sys, "frozen", False))


def config_dir() -> Path:
    if not is_package_build():
        return legacy_config_dir()
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData/Roaming") / "ClipSD"
    return _xdg_config() / "clipsd"


def config_file() -> Path:
    return config_dir() / "config.json"


def migrate_legacy(new_dir: Path = None, legacy_dir: Path = None) -> list:
    """Один раз скопировать файлы 1.x в папку готовой сборки. Возвращает имена скопированных файлов.
    Файл копируется, только если в новой папке такого ещё нет; config.json решает, был ли перенос:
    если он уже есть, ничего не копируется (настройки 2-го и следующих запусков не перетираются)."""
    new_dir = Path(new_dir or config_dir())
    legacy_dir = Path(legacy_dir or legacy_config_dir())
    if new_dir == legacy_dir or (new_dir / "config.json").exists() or not (legacy_dir / "config.json").exists():
        return []
    copied = []
    try:
        new_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return []
    # config.json последним: по нему видно, что перенос закончен
    for name in sorted(LEGACY_FILES, key=lambda n: n == "config.json"):
        src, dst = legacy_dir / name, new_dir / name
        if not src.is_file() or dst.exists():
            continue
        try:
            tmp = dst.with_name(dst.name + ".tmp")
            # only this user may read them: the settings hold the e-mail for MyMemory, the key file the Google key
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(src.read_bytes())
            os.chmod(tmp, 0o600)
            os.replace(tmp, dst)
            copied.append(name)
        except OSError:
            continue
    return copied
