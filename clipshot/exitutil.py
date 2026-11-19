# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Упорядоченный выход. Обычный sys.exit разбирает обёртки Qt при завершении интерпретатора, и изредка (до 9 запусков
из 120) процесс падал с кодом 139 в Py_Exit (sip_api_get_address). У службы стоит Restart=on-failure, поэтому после
команды «Выход» программа через 2 секунды запускалась снова. Здесь всё нужное сделано заранее (вывод сброшен),
и процесс завершается сразу, не трогая обёртки."""

import os
import sys


def quick_exit(rc=0):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (OSError, ValueError, AttributeError):
            pass
    os._exit(int(rc or 0))
