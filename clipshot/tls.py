# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
"""Проверка сертификатов https для обновлений и перевода.

Сборка для Linux делается на Ubuntu, и её OpenSSL ищет корневые сертификаты там, где они лежат на Ubuntu
(/usr/lib/ssl). На Fedora, openSUSE и других системах их там нет, и любой https-запрос падал бы с ошибкой
проверки сертификата. Тогда берётся набор certifi, который едет внутри сборки. Если системные сертификаты
находятся (Ubuntu, Debian, Mint, запуск из исходников, Windows), используются они.
"""

import functools
import logging
import os
import ssl

log = logging.getLogger("clipsd.tls")


def _system_store_found() -> bool:
    paths = ssl.get_default_verify_paths()
    if paths.cafile and os.path.isfile(paths.cafile):
        return True
    try:
        return bool(paths.capath) and os.path.isdir(paths.capath) and any(os.scandir(paths.capath))
    except OSError:
        return False


@functools.lru_cache(maxsize=1)
def context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if os.name != "nt" and not _system_store_found():
        try:
            import certifi
            ctx.load_verify_locations(cafile=certifi.where())
        except (ImportError, OSError, ssl.SSLError) as exc:
            log.warning("no certificate store for https: %s", exc)
    return ctx
