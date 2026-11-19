# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
import sys

from .ipc import command_from_args, send

# Быстрый путь: фоновая копия уже работает — отдаём команду, не загружая Qt.
_command = command_from_args(sys.argv[1:])
if _command and send(_command):
    sys.exit(0)

from .app import main  # noqa: E402
from .exitutil import quick_exit  # noqa: E402

quick_exit(main())
