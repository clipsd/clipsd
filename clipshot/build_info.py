# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Kind of this build: release, preview ("проба") or Microsoft Store.

A preview build carries the generated module clipshot/_preview_build.py. Only
packaging/preview_build.py writes it, and only into a separate copy of the sources made for the
owner's own tests; it is never committed (.gitignore), release.sh refuses to run while it exists
and tools/release_check.py fails a build that has it. Release and stable builds have no such
module, so here PREVIEW is False and PROBA_PUBLIC_KEYS is empty: the "proba" channel, its key and
downloads from local files are refused there (update_channel.trusted_keys, updater.download_file).

A preview build:
- uses only the channel "proba", a local folder (updater.proba_dir()), signed by its own key;
- shows "Пробная сборка" in the tray tip and the About window.

A Microsoft Store build (MSIX package, packaging/windows-store) carries the generated module
clipshot/_store_build.py, written by `packaging/stage_windows.py --store` into the staged copy only
(never committed: .gitignore, tools/release_check.py). There STORE is True and STORE_PRODUCT_ID is
the Store ID from Partner Center (may be empty until the listing exists). A Store build:
- never updates itself: the Store does it; "Check for updates" opens the product page in the Store;
- starts at login through the StartupTask of its package manifest, not a Startup folder shortcut;
- says "build: store" in its selfcheck and "Microsoft Store" next to the version.
"""

try:
    from . import _preview_build as _generated
except ImportError:
    _generated = None

PREVIEW = bool(_generated is not None and getattr(_generated, "PREVIEW", False) is True)
PROBA_PUBLIC_KEYS = tuple(getattr(_generated, "PROBA_PUBLIC_KEYS", ())) if PREVIEW else ()

try:
    from . import _store_build as _store_generated
except ImportError:
    _store_generated = None

STORE = bool(_store_generated is not None and getattr(_store_generated, "STORE", False) is True)
STORE_PRODUCT_ID = str(getattr(_store_generated, "STORE_PRODUCT_ID", "") or "") if STORE else ""
STORE_LABEL = "Microsoft Store"   # a brand name: not translated


def is_preview() -> bool:
    """Read at call time, so tests can switch a release build into a preview one and back."""
    return PREVIEW is True


def proba_keys() -> tuple:
    return tuple(PROBA_PUBLIC_KEYS) if is_preview() else ()


def is_store() -> bool:
    """A build made for Microsoft Store (read at call time, like is_preview)."""
    return STORE is True


def store_product_id() -> str:
    return STORE_PRODUCT_ID if is_store() else ""


def kind() -> str:
    """"preview", "store" or "release": the line "build: <kind>" of the selfcheck."""
    if is_preview():
        return "preview"
    return "store" if is_store() else "release"


def version_label(version: str) -> str:
    """'1.30.1' in a release build, '1.30.1 · Пробная сборка' in a preview one, '1.30.1 · Microsoft Store'
    in a Store build."""
    if is_preview():
        return f"{version} · {preview_label()}"
    if is_store():
        return f"{version} · {STORE_LABEL}"
    return version


def preview_label() -> str:
    """"Пробная сборка" in the program language (key app.preview_build)."""
    from .i18n import tr
    return tr("app.preview_build")
