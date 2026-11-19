# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Kind of this build: release or preview ("проба").

A preview build carries the generated module clipshot/_preview_build.py. Only
packaging/preview_build.py writes it, and only into a separate copy of the sources made for the
owner's own tests; it is never committed (.gitignore), release.sh refuses to run while it exists
and tools/release_check.py fails a build that has it. Release and stable builds have no such
module, so here PREVIEW is False and PROBA_PUBLIC_KEYS is empty: the "proba" channel, its key and
downloads from local files are refused there (update_channel.trusted_keys, updater.download_file).

A preview build:
- uses only the channel "proba", a local folder (updater.proba_dir()), signed by its own key;
- shows "Пробная сборка" in the tray tip and the About window.
"""

try:
    from . import _preview_build as _generated
except ImportError:
    _generated = None

PREVIEW = bool(_generated is not None and getattr(_generated, "PREVIEW", False) is True)
PROBA_PUBLIC_KEYS = tuple(getattr(_generated, "PROBA_PUBLIC_KEYS", ())) if PREVIEW else ()


def is_preview() -> bool:
    """Read at call time, so tests can switch a release build into a preview one and back."""
    return PREVIEW is True


def proba_keys() -> tuple:
    return tuple(PROBA_PUBLIC_KEYS) if is_preview() else ()


def version_label(version: str) -> str:
    """'1.30.1' in a release build, '1.30.1 · Пробная сборка' in a preview one."""
    if not is_preview():
        return version
    return f"{version} · {preview_label()}"


def preview_label() -> str:
    """"Пробная сборка" in the program language (key app.preview_build)."""
    from .i18n import tr
    return tr("app.preview_build")
