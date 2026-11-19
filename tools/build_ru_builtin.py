"""Встроенный запасной русский каталог: clipshot/i18n/ru_builtin.py из clipshot/i18n/ru/*.json.
Нужен, если папка каталогов не попала в сборку: программа тогда говорит по-русски, а не показывает ключи.
Запуск после правки ru/*.json: python3 tools/build_ru_builtin.py (тест i18n_test сверяет файл с каталогом)."""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
merged = {}
for f in sorted((ROOT / "clipshot/i18n/ru").glob("*.json")):
    merged.update(json.loads(f.read_text(encoding="utf-8")))
body = json.dumps(merged, ensure_ascii=False, indent=0, sort_keys=True)
(ROOT / "clipshot/i18n/ru_builtin.py").write_text(
    "# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)\n"
    "# SPDX-License-Identifier: GPL-3.0-or-later.\n"
    '"""Запасной русский каталог внутри модуля (создаётся tools/build_ru_builtin.py из ru/*.json, руками не править)."""\n'
    "import json\n\nCATALOG = json.loads(r'''" + body.replace("'''", "\\'\\'\\'") + "''')\n", encoding="utf-8")
print(len(merged), "ключей")
