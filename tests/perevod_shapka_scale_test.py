# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Строка режима «Перевод» при масштабе экрана 150 % и 200 % (QT_SCALE_FACTOR).

Те же проверки раскладки, что в perevod_shapka_test.py (короткий набор: ширины в логических точках, 12 языков, состояния,
клавиатура), только процесс запускается с QT_SCALE_FACTOR=1.5 и 2. Масштаб нужно задавать до создания приложения,
поэтому каждый прогон идёт отдельным процессом с тем же временным окружением. Это искусственная проверка (QT_SCALE_FACTOR
умножается на настоящий масштаб системы); живая проверка на Windows 150 % и 200 % перед выпуском.
"""
import os
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
failed = []
for scale in ("1.5", "2"):
    env = dict(os.environ, QT_SCALE_FACTOR=scale, SHAPKA_SHORT="1")
    run = subprocess.run([sys.executable, os.path.join(here, "perevod_shapka_test.py")], env=env, capture_output=True, text=True, timeout=1500)
    tail = [ln for ln in run.stdout.splitlines() if ln.startswith(("FAIL", "ИТОГ"))]
    print(f"масштаб {scale}: код {run.returncode}; " + "; ".join(tail[-6:]), flush=True)
    if run.returncode != 0:
        failed.append(scale)
        print(run.stdout[-3000:], run.stderr[-2000:])
print("ИТОГ: " + ("все проверки пройдены" if not failed else f"провалено при масштабе {failed}"))
sys.exit(1 if failed else 0)
