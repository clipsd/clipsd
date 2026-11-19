# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Разложить исходники в структуру, которую ждёт packaging/build.ps1 (сборка Windows-установщика).

Запуск: python packaging/stage_windows.py <папка>   (облако GitHub и build_dist.sh)
"""

import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Same codes and order as [Languages] in packaging/windows-exe/ClipSD.iss
INSTALLER_LANGUAGES = ("en", "ru", "bg", "uk", "de", "fr", "es", "it", "pt", "pl", "tr", "zh")


def text_for_windows(src: Path, dst: Path, bom=True):
    text = src.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\n", "\r\n")
    dst.write_text(text, encoding="utf-8-sig" if bom else "utf-8", newline="")


def stage(out: Path):
    if out.exists():
        shutil.rmtree(out)
    (out / "packaging").mkdir(parents=True)
    shutil.copytree(ROOT / "clipshot", out / "clipshot", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "tests", out / "tests", ignore=shutil.ignore_patterns("__pycache__", "output"))
    win = ROOT / "packaging" / "windows-exe"
    for name in ("build.ps1", "ClipSD.iss", "clipsd_app_entry.py", "version_info.txt", "staging-complete.txt"):
        shutil.copy2(win / name, out / "packaging" / name)
    for folder in ("launcher", "languages"):   # languages: ChineseSimplified.isl (not shipped with Inno Setup 6)
        shutil.copytree(win / folder, out / "packaging" / folder)
    shutil.copy2(ROOT / "packaging" / "requirements-build-windows.txt", out / "packaging")
    shutil.copy2(ROOT / "packaging" / "stamp_version.py", out / "packaging")
    shutil.copy2(ROOT / "packaging" / "make_notices.py", out / "packaging")   # build.ps1: --check-windows-dlls
    shutil.copy2(win / "clipsd.ico", out / "clipsd.ico")
    shutil.copy2(ROOT / "LICENSE", out / "LICENSE")
    text_for_windows(ROOT / "LICENSE.ru.txt", out / "LICENSE.ru.txt")
    # name and icon: additional terms under GPLv3 section 7, installed next to LICENSE (ClipSD.iss [Files])
    text_for_windows(ROOT / "TRADEMARKS.md", out / "TRADEMARKS.txt")
    text_for_windows(ROOT / "TRADEMARKS.ru.md", out / "TRADEMARKS.ru.txt")
    sys.path.insert(0, str(ROOT / "packaging"))
    import make_notices
    notices = out / "THIRD-PARTY-NOTICES.txt"
    notices.write_text(make_notices.build("windows"), encoding="utf-8")
    text_for_windows(notices, notices)
    text_for_windows(ROOT / "packaging" / "README.txt", out / "README.txt")
    text_for_windows(ROOT / "packaging" / "README.en.txt", out / "README.en.txt")
    stage_whats_new(out)
    stage_changelog(out)
    if (ROOT / "clipshot" / "_preview_build.py").exists():
        # a preview installer carries this mark next to the program: tools/release.sh assemble refuses it (innoextract)
        (out / "PREVIEW").write_text("ClipSD preview build (proba channel): never a release.\n", encoding="utf-8")


def app_version() -> str:
    text = (ROOT / "clipshot" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'^__version__ = "([^"]+)"', text, re.M).group(1)


def stage_changelog(out: Path):
    """CHANGELOG/<version>/<lang>.md next to the sources: build.ps1 puts the folder into the program
    (--add-data CHANGELOG), so "What's new" of the editor bell has the notes on a fresh install too, not only
    after an update (clipshot/notifications.py looks in <sys._MEIPASS>/CHANGELOG)."""
    src = ROOT / "CHANGELOG"
    if not src.is_dir():
        return
    def not_notes(folder, names):   # only the notes: no CRITICAL marks or other files
        return [n for n in names if not n.endswith(".md") and not (Path(folder) / n).is_dir()]
    shutil.copytree(src, out / "CHANGELOG", ignore=not_notes)


def stage_whats_new(out: Path):
    """CHANGELOG/<version>/<lang>.md -> whatsnew/<lang>.txt for the installer page "What's new".

    Every installer language gets a file (English text when its own is missing), or none at all
    when there is no CHANGELOG for this version: ClipSD.iss shows the page only if whatsnew/en.txt exists.
    """
    folder = ROOT / "CHANGELOG" / app_version()
    if not folder.is_dir():
        return
    fallback = folder / "en.md"
    (out / "whatsnew").mkdir()
    for lang in INSTALLER_LANGUAGES:
        src = folder / f"{lang}.md"
        if not src.exists():
            src = fallback
        if src.exists():
            text_for_windows(src, out / "whatsnew" / f"{lang}.txt")


if __name__ == "__main__":
    stage(Path(sys.argv[1]).resolve())
    print("Готово:", sys.argv[1])
