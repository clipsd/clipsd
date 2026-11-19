# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Внешние адреса программы (1.32): канал Telegram с новостями и обновлениями (под постами комментарии).
Короткий адрес без «app» на конце занят чужим каналом: только clipsdapp. Открывать через sysenv.open_url, как остальные внешние
ссылки (в пакете для Linux xdg-open запускается без библиотек сборки, иначе на Ubuntu 26.04 ссылка не открывается).
Тексты: clipshot/i18n/<язык>/links.json."""

TELEGRAM_URL = "https://t.me/clipsdapp"
TELEGRAM_SHORT = "t.me/clipsdapp"


def open_telegram() -> bool:
    from .sysenv import open_url
    return open_url(TELEGRAM_URL)
