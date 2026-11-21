# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Две сборки Windows рядом: с сайта (Setup.exe) и из Microsoft Store (MSIX).

У обеих один замок одной копии и один канал команд (ipc.py), поэтому работает та, что запустилась первой, а вторая
отдаёт ей команду и выходит. Раньше вторая выходила молча: человек нажимал «Открыть» в Store и ничего не видел
(пункт Н4 проверки 1.32.3). Теперь запускаемая копия без команды спрашивает работающую, какая она, и если сборки
разные, показывает сообщение «ClipSD уже работает (версия ...). Значок у часов.» и выходит.

Протокол: запускаемая копия без команды пишет в канал «neighbor:<своя сборка>» (site | store); работающая отвечает
строкой «site\\n» или «store\\n» (app.py, _on_connection). Старая копия (1.32 и раньше) такую команду не знает и не
отвечает: если запускается Store-сборка, работающей считается сборка с сайта (Store-сборок до 1.33 не было).
Команды Alt+W и прочие (region, full, open:..., demo) идут как раньше, сообщения для них нет.
"""

import os

KIND_SITE = "site"      # установщик с сайта (Setup.exe), архив Linux, запуск из исходников
KIND_STORE = "store"    # пакет MSIX из Microsoft Store
KINDS = (KIND_SITE, KIND_STORE)
PROBE_PREFIX = "neighbor:"
REPLY_WAIT_MS = 1200    # сколько запускаемая копия ждёт ответа работающей


def enabled() -> bool:
    """Две сборки рядом бывают только в Windows; в Linux запрос не посылается (тесты подменяют эту функцию)."""
    return os.name == "nt"


def own_kind() -> str:
    """Какая это сборка: у процесса из пакета MSIX есть идентификатор пакета (updater.is_store_package)."""
    try:
        from . import updater
        return KIND_STORE if updater.is_store_package() else KIND_SITE
    except Exception:   # noqa: BLE001 — определение сборки не должно мешать запуску
        return KIND_SITE


def probe_command(own: str) -> str:
    return PROBE_PREFIX + (own if own in KINDS else KIND_SITE)


def is_probe(command: str) -> bool:
    return command.startswith(PROBE_PREFIX)


def reply_bytes(own: str = "") -> bytes:
    """Ответ работающей копии на запрос запускаемой."""
    return ((own or own_kind()) + "\n").encode()


def running_kind(reply: str, own: str) -> str:
    """Какая сборка работает: из ответа; без ответа (старая копия) для Store-сборки это сборка с сайта; иначе неизвестно."""
    reply = (reply or "").strip()
    if reply in KINDS:
        return reply
    if own == KIND_STORE:
        return KIND_SITE
    return ""


def should_explain(own: str, running: str) -> bool:
    """Сообщение нужно, когда работающая копия другой сборки."""
    return running in KINDS and own in KINDS and running != own


def message_for(running: str):
    """(заголовок, текст) на языке программы: «ClipSD уже работает (версия ...). Значок у часов. ...»."""
    from .i18n import tr
    key = "neighbor.text_store" if running == KIND_STORE else "neighbor.text_site"
    return tr("neighbor.title"), tr(key, quit=tr("app.menu_quit"))


def show_message(running: str) -> None:
    """Существующая карточка программы (MessageCard), без нового окна. Закрывается сама через минуту."""
    from PyQt6.QtCore import QTimer
    from .dialogs import MessageCard
    title, text = message_for(running)
    card = MessageCard(None, title, text, "info")
    QTimer.singleShot(60000, card.accept)
    card.exec()


def report(own: str, reply: str) -> bool:
    """После передачи пустой команды: показать сообщение, если работает другая сборка. True: показано."""
    running = running_kind(reply, own)
    if not should_explain(own, running):
        return False
    try:
        show_message(running)
    except Exception as exc:   # noqa: BLE001 — нет окна: выходим, как раньше, молча
        print(f"ClipSD уже работает ({running}); сообщение не показано: {exc}")
        return False
    return True
