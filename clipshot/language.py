# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
"""Выбор языка интерфейса из разных окон (1.31): меню значка у часов, глобус в редакторе, первый шаг знакомства,
раздел в настройках. Языки названы на самих себе; смена сразу, без перезапуска программы.

Значение настройки config["language"]: код языка или "auto" (язык системы). Файл настроек без поля language
(установка 1.x до 1.31) остаётся на русском; новая установка (файла ещё нет) берёт язык установщика Windows
(файл installer-language рядом с настройками, его пишет ClipSD.iss), а без него язык системы."""

import json

from PyQt6.QtGui import QAction, QActionGroup
from PyQt6.QtWidgets import QMenu

from . import i18n
from .i18n import tr, tr_in

AUTO = i18n.AUTO


INSTALLER_FILE = "installer-language"   # код языка установщика Windows, пишет ClipSD.iss при новой установке


def installer_choice(config_dir) -> str:
    """Язык, на котором прошла установка (Windows): код из списка; совпал с языком системы: auto
    (программа и дальше идёт за системой). Файла нет или в нём мусор: auto."""
    try:
        code = (config_dir / INSTALLER_FILE).read_text(encoding="utf-8-sig").strip().lower()
    except (OSError, ValueError, TypeError, AttributeError):
        return AUTO
    if code not in i18n.LANGUAGES or code == i18n.system_language():
        return AUTO
    return code


def config_choice(raw_config, file_exists: bool, config_dir=None) -> str:
    """Что выбрано: поле language из файла; файл есть, а поля нет (обновление с 1.x): ru;
    файла нет: язык установщика (config_dir/installer-language), иначе auto."""
    if isinstance(raw_config, dict) and raw_config.get("language") in i18n.LANGUAGES + [AUTO]:
        return raw_config["language"]
    if file_exists:
        return "ru"
    return installer_choice(config_dir) if config_dir is not None else AUTO


def early_choice(path) -> str:
    """Выбор языка прямо из файла настроек, до создания окон и до разбора командной строки."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        return config_choice(None, False, path.parent)
    except ValueError:
        return config_choice(None, True)   # файл испорчен, но он был: как у старой установки
    return config_choice(raw, True)


def menu_title() -> str:
    """«Язык · Language» (на английском интерфейсе «Language · Язык»): пункт находят, не понимая текущего языка."""
    own = tr("common.language")
    other = tr_in("ru" if i18n.current() == "en" else "en", "common.language")
    return own if own == other else f"{own} · {other}"


def auto_label() -> str:
    """«Как в системе (Deutsch)»: в скобках язык, который сейчас выбрала бы система."""
    return f'{tr("settings.lang_auto")} ({i18n.LANGUAGE_NAMES[i18n.system_language()]})'


def entries():
    """[(значение, подпись)]: «Как в системе», затем 12 языков на самих себе."""
    return [(AUTO, auto_label())] + [(code, i18n.LANGUAGE_NAMES[code]) for code in i18n.LANGUAGES]


def current_choice(ctx) -> str:
    return getattr(ctx, "config", {}).get("language", i18n.choice())


def fill_menu(menu: QMenu, ctx):
    """Пункты выбора языка в меню (подменю значка у часов, меню глобуса в редакторе)."""
    menu.clear()
    group = QActionGroup(menu)
    group.setExclusive(True)
    chosen = current_choice(ctx)
    for code, label in entries():
        action = QAction(label, menu)
        action.setCheckable(True)
        action.setChecked(code == chosen)
        action.setData(code)
        group.addAction(action)
        action.triggered.connect(lambda _checked=False, c=code: change(ctx, c))
        menu.addAction(action)
        if code == AUTO:
            menu.addSeparator()
    return menu


def make_menu(ctx, parent=None) -> QMenu:
    from . import icons
    from .menus import style_menu
    menu = QMenu(menu_title(), parent)
    menu.setIcon(icons.icon("globe"))
    style_menu(menu, getattr(ctx, "config", {}))
    menu.aboutToShow.connect(lambda: fill_menu(menu, ctx))   # отметка и «Как в системе» всегда свежие
    fill_menu(menu, ctx)
    return menu


def change(ctx, choice: str):
    """Сменить язык: у приложения его метод (запись настроек, перерисовка окон), иначе только язык и config."""
    if hasattr(ctx, "set_language"):
        ctx.set_language(choice)
        return
    if isinstance(getattr(ctx, "config", None), dict):
        ctx.config["language"] = choice
    i18n.set_language(choice)
