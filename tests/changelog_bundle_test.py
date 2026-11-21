# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""«Что нового» в колокольчике и при новой установке (1.32): папка CHANGELOG попадает в сборки Linux и Windows.

Колокольчик редактора (clipshot/notifications.py) берёт заметки версии из CHANGELOG/<версия>/<язык>.md: рядом с
пакетом (исходники) или в <sys._MEIPASS>/CHANGELOG (сборка PyInstaller). Проверяется:
- build_linux.sh и build.ps1 кладут CHANGELOG в программу (--add-data), stage_windows.py копирует папку в раскладку
  сборки Windows (только заметки .md);
- в «замороженной» программе заметки находятся в sys._MEIPASS, даже если рядом с пакетом папки нет;
- заметки выпусков 1.32.0-1.34.0 есть на 12 языках, без длинных тире, с одинаковым числом пунктов;
- в 1.34.0 все пункты 1.33.0 (кнопка окон под новым именем) и названия новых кнопок как в каталогах программы;
- в 1.32.2 первый пункт говорит, что у зажатого окошка перевода крестик в углу, а кнопки появляются при наведении мыши;
- в 1.32.3 названия кнопок взяты из каталогов программы на каждом языке («Копировать текст», «Повторить»,
  «Скопировать и закрыть», «Что нового», «Проверить обновления»).

Запуск: python3 tests/changelog_bundle_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
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

# --- заметки выпусков 1.32.0, 1.32.1, 1.32.2 и 1.32.3 ----------------------------------------------------------------
for version in ("1.32.0", "1.32.1", "1.32.2", "1.32.3", "1.33.0", "1.34.0"):
    folder = ROOT / "CHANGELOG" / version
    missing = [lang for lang in LANGS if not (folder / f"{lang}.md").is_file()]
    check(not missing, f"CHANGELOG/{version}: 12 языков {missing or ''}")
    counts, dashes = set(), []
    for lang in LANGS:
        path = folder / f"{lang}.md"
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        counts.add(sum(1 for line in text.splitlines() if line.startswith("- ")))
        if "—" in text:
            dashes.append(lang)
    check(len(counts) == 1, f"CHANGELOG/{version}: одинаковое число пунктов на всех языках {sorted(counts)}")
    check(not dashes, f"CHANGELOG/{version}: без длинных тире {dashes or ''}")

# 1.32.2, первый пункт: сказано, что у зажатого окошка перевода крестик, а кнопки при наведении мыши (П4 проверки)
CROWDED = {"ru": ("крестик", "наведении"), "en": ("cross", "hover"), "bg": ("кръстче", "мишката"), "de": ("Kreuz", "Maus"),
           "es": ("cruz", "ratón"), "fr": ("croix", "survol"), "it": ("croce", "mouse"), "pl": ("krzyżyk", "myszą"),
           "pt": ("cruz", "mouse"), "tr": ("çarpı", "fare"), "uk": ("хрестик", "мишу"), "zh": ("叉号", "鼠标")}
for lang, words in CROWDED.items():
    path = ROOT / "CHANGELOG" / "1.32.2" / f"{lang}.md"
    first = path.read_text(encoding="utf-8").splitlines()[0] if path.is_file() else ""
    check(all(w in first for w in words), f"CHANGELOG/1.32.2/{lang}: в первом пункте крестик и кнопки при наведении мыши {words}")

# 1.32.3: названия кнопок в заметках такие же, как в программе на этом языке (каталоги clipshot/i18n/<язык>/*.json)
import json  # noqa: E402

BUTTONS = (("selector", "selector.btn_ocr"), ("updater", "updater.button.retry"), ("editor", "editor.copy_close"),
           ("updater", "updater.offer.whatsnew"), ("updater", "updater.menu.check"))
for lang in LANGS:
    path = ROOT / "CHANGELOG" / "1.32.3" / f"{lang}.md"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    missing = []
    for catalog, key in BUTTONS:
        name = json.loads((ROOT / "clipshot" / "i18n" / lang / f"{catalog}.json").read_text(encoding="utf-8"))[key]
        if name not in text:
            missing.append(name)
    check(not missing, f"CHANGELOG/1.32.3/{lang}: названия кнопок как в программе {missing or ''}")

# 1.33.0: названия кнопок в заметках такие же, как в программе на этом языке
BUTTONS_133 = (("editor", "editor.tr_copy"), ("editor", "editor.tr_seg_translation"), ("editor", "editor.tr_seg_original"),
               ("updater", "updater.button.retry"), ("selector", "selector.win_do_update"),
               # selector.win_chip не сверяется: заметки 1.33.0 про чип «Окна», после 1.33.0 он «Открытые окна» (21.11.2026)
               ("phone", "phone.menu"), ("phone", "phone.full_size"), ("phone", "phone.fw_allow"))
for lang in LANGS:
    path = ROOT / "CHANGELOG" / "1.33.0" / f"{lang}.md"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    missing = []
    for catalog, key in BUTTONS_133:
        name = json.loads((ROOT / "clipshot" / "i18n" / lang / f"{catalog}.json").read_text(encoding="utf-8"))[key]
        if name not in text:
            missing.append(name)
    check(not missing, f"CHANGELOG/1.33.0/{lang}: названия кнопок как в программе {missing or ''}")

# 1.34.0 (всё из 1.33.0, которая публично не выходила, и новое 1.34): названия кнопок как в программе на этом языке
BUTTONS_134 = tuple(b for b in BUTTONS_133) + (
    ("selector", "selector.win_chip"), ("phone", "phone.tile_title"), ("selector", "selector.btn_edit"),
    ("selector", "selector.btn_copy"), ("selector", "selector.btn_save"), ("selector", "selector.btn_retake"),
    ("editor", "editor.unsaved_title"), ("editor", "editor.unsaved_discard"), ("novoe", "novoe.menu"),
    ("novoe", "novoe.badge"), ("settings", "settings.nav_updates"), ("forma", "forma.title"), ("editor", "editor.all_tools"),
    ("editor", "editor.insert_title"))
notes_133 = {lang: (ROOT / "CHANGELOG" / "1.33.0" / f"{lang}.md").read_text(encoding="utf-8") for lang in LANGS
             if (ROOT / "CHANGELOG" / "1.33.0" / f"{lang}.md").is_file()}
for lang in LANGS:
    path = ROOT / "CHANGELOG" / "1.34.0" / f"{lang}.md"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    missing = []
    for catalog, key in BUTTONS_134:
        name = json.loads((ROOT / "clipshot" / "i18n" / lang / f"{catalog}.json").read_text(encoding="utf-8"))[key]
        if name not in text:
            missing.append(name)
    check(not missing, f"CHANGELOG/1.34.0/{lang}: названия кнопок как в программе {missing or ''}")
    lines = [ln for ln in text.splitlines() if ln.startswith("- ")]
    old = [ln for ln in notes_133.get(lang, "").splitlines() if ln.startswith("- ")]
    chip = json.loads((ROOT / "clipshot" / "i18n" / lang / "selector.json").read_text(encoding="utf-8"))["selector.win_chip"]
    # пункт про снимок окна: та же фраза, только кнопка под новым именем (текст после «▾» совпадает)
    kept = sum(1 for ln in old if ln in lines or "▾" in ln and any(chip in x and x.split("▾", 1)[1] == ln.split("▾", 1)[1]
                                                                   for x in lines))
    check(old and kept == len(old) and len(lines) > len(old), f"CHANGELOG/1.34.0/{lang}: все пункты 1.33.0 на месте и есть новые ({kept}/{len(old)})")

print(f"ИТОГ: провалено {len(failed)}")
sys.exit(1 if failed else 0)
