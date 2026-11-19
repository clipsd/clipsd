# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""«Что нового» в колокольчике и при новой установке (1.32): папка CHANGELOG попадает в сборки Linux и Windows.

Колокольчик редактора (clipshot/notifications.py) берёт заметки версии из CHANGELOG/<версия>/<язык>.md: рядом с
пакетом (исходники) или в <sys._MEIPASS>/CHANGELOG (сборка PyInstaller). Проверяется:
- build_linux.sh и build.ps1 кладут CHANGELOG в программу (--add-data), stage_windows.py копирует папку в раскладку
  сборки Windows (только заметки .md);
- в «замороженной» программе заметки находятся в sys._MEIPASS, даже если рядом с пакетом папки нет;
- заметки выпуска 1.32.0 есть на 12 языках, без длинных тире.

Запуск: python3 tests/changelog_bundle_test.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packaging"))

LANGS = ("ru", "en", "bg", "uk", "de", "fr", "es", "it", "pt", "pl", "tr", "zh")
failed = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failed.append(msg)


# --- сборки кладут CHANGELOG в программу ---------------------------------------------------------------------
linux = (ROOT / "packaging/linux/build_linux.sh").read_text(encoding="utf-8")
check('--add-data "$ROOT/CHANGELOG:CHANGELOG"' in linux,
      "build_linux.sh: PyInstaller получает папку CHANGELOG по полному пути (относительный считается от --specpath)")
ps1 = (ROOT / "packaging/windows-exe/build.ps1").read_text(encoding="utf-8-sig")
check('--add-data "$Root\\CHANGELOG;CHANGELOG"' in ps1, "build.ps1: PyInstaller получает папку CHANGELOG по полному пути")

import stage_windows  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="clipsd-changelog-"))
try:
    (tmp / "stage").mkdir()
    stage_windows.stage_changelog(tmp / "stage")
    staged = tmp / "stage" / "CHANGELOG"
    versions = sorted(p.name for p in (ROOT / "CHANGELOG").iterdir() if p.is_dir())
    check(staged.is_dir() and sorted(p.name for p in staged.iterdir() if p.is_dir()) == versions,
          f"stage_windows.py: в раскладке все версии CHANGELOG ({len(versions)})")
    others = [p.relative_to(staged).as_posix() for p in staged.rglob("*") if p.is_file() and p.suffix != ".md"]
    check(not others, f"stage_windows.py: в раскладке только заметки .md {others or ''}")
    check("stage_changelog(out)" in (ROOT / "packaging/stage_windows.py").read_text(encoding="utf-8"),
          "stage_windows.stage() вызывает stage_changelog")

    # --- «замороженная» программа находит заметки в sys._MEIPASS -----------------------------------------------
    from clipshot import notifications
    meipass = tmp / "meipass"
    (meipass / "CHANGELOG" / "9.9.9").mkdir(parents=True)
    (meipass / "CHANGELOG" / "9.9.9" / "en.md").write_text("- Bundled note\n", encoding="utf-8")
    sys._MEIPASS = str(meipass)
    try:
        check("9.9.9" in notifications.changelog_versions(), "сборка: версия из <_MEIPASS>/CHANGELOG видна колокольчику")
        check(notifications.changelog_notes("9.9.9", "de") == "- Bundled note",
              "сборка: заметки читаются (нет своего языка: английский)")
    finally:
        del sys._MEIPASS
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# --- заметки выпуска 1.32.0 ------------------------------------------------------------------------------------
folder = ROOT / "CHANGELOG" / "1.32.0"
missing = [lang for lang in LANGS if not (folder / f"{lang}.md").is_file()]
check(not missing, f"CHANGELOG/1.32.0: 12 языков {missing or ''}")
counts, dashes = set(), []
for lang in LANGS:
    path = folder / f"{lang}.md"
    if not path.is_file():
        continue
    text = path.read_text(encoding="utf-8")
    counts.add(sum(1 for line in text.splitlines() if line.startswith("- ")))
    if "—" in text:
        dashes.append(lang)
check(len(counts) == 1, f"CHANGELOG/1.32.0: одинаковое число пунктов на всех языках {sorted(counts)}")
check(not dashes, f"CHANGELOG/1.32.0: без длинных тире {dashes or ''}")

print(f"ИТОГ: провалено {len(failed)}")
sys.exit(1 if failed else 0)
