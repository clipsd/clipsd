# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Временные папки теста убираются, когда тест кончается (1.32.3).

Тесты 1.32.x брали папки tempfile.mkdtemp и не удаляли их: после сотен прогонов во временной папке лежали тысячи
папок clipsd-* (на машине, где /tmp в оперативной памяти, это память). Импорт этого модуля в начале теста (до первого
mkdtemp): каждая папка, созданная tempfile.mkdtemp в этом процессе, удаляется при выходе: обычном (sys.exit, конец
скрипта) и через clipshot.exitutil.quick_exit (os._exit, без atexit). Папки дочерних процессов убирают сами дочерние
процессы (тот же импорт в их скрипте).

Не тест (имя без _test): tools/run_tests.sh и tools/release.sh его не запускают.
"""
import atexit
import os
import shutil
import sys
import tempfile

_made = []
_real_mkdtemp = tempfile.mkdtemp
_owner = os.getpid()


def _mkdtemp(*args, **kwargs):
    path = _real_mkdtemp(*args, **kwargs)
    _made.append(path)
    return path


def cleanup():
    """Удалить папки этого процесса (в дочернем процессе после fork не трогать чужие)."""
    if os.getpid() != _owner:
        return
    while _made:
        shutil.rmtree(_made.pop(), ignore_errors=True)


tempfile.mkdtemp = _mkdtemp
atexit.register(cleanup)

# quick_exit выходит через os._exit, atexit при этом не работает: убрать папки перед ним
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)
from clipshot import exitutil  # noqa: E402

_real_quick_exit = exitutil.quick_exit


def _quick_exit(rc=0):
    cleanup()
    _real_quick_exit(rc)


exitutil.quick_exit = _quick_exit
