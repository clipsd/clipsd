# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Тесты убирают за собой временные папки (1.32.3).

Тесты 1.32.x брали папки tempfile.mkdtemp и не удаляли их: после сотен прогонов во временной папке лежали тысячи
папок clipsd-* (ui129_test создавал новую папку на каждое чтение счётчика перевода). Проверяется:
- папки mkdtemp процесса с tests/tmpclean.py удаляются при выходе через sys.exit, конец скрипта и
  clipshot.exitutil.quick_exit (os._exit);
- каждый тест, который зовёт mkdtemp, импортирует tmpclean раньше первого вызова;
- tools/run_tests.sh удаляет свою временную папку теста.

Запуск: python3 tests/tmpclean_test.py
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


CHILD = r'''
import sys
sys.path.insert(0, sys.argv[1])
import tmpclean
import tempfile
for i in range(3):
    open(tempfile.mkdtemp(prefix="clipsd-probe-") + "/f.txt", "w").write("x")
mode = sys.argv[2]
if mode == "quick":
    from clipshot.exitutil import quick_exit
    quick_exit(0)
elif mode == "exit":
    sys.exit(0)
'''

base = Path(tempfile.mkdtemp(prefix="clipsd-tmpclean-"))
try:
    for mode in ("end", "exit", "quick"):
        tmp = base / mode
        tmp.mkdir()
        env = dict(os.environ, TMPDIR=str(tmp), PYTHONPATH=str(ROOT))
        res = subprocess.run([sys.executable, "-c", CHILD, str(ROOT / "tests"), mode], env=env, timeout=60,
                             capture_output=True, text=True)
        left = [p.name for p in tmp.iterdir()]
        check(res.returncode == 0 and not left,
              f"выход «{mode}»: временные папки удалены (код {res.returncode}, осталось {left}){res.stderr[-300:]}")
finally:
    shutil.rmtree(base, ignore_errors=True)

late = []
for f in sorted((ROOT / "tests").glob("*.py")):
    if f.name in ("tmpclean.py", "tmpclean_test.py"):
        continue
    text = f.read_text(encoding="utf-8")
    first = re.search(r"mkdtemp\(", text)
    if first is None:
        continue
    imp = re.search(r"^import tmpclean\b", text, re.M)
    if imp is None or imp.start() > first.start():
        late.append(f.name)
check(not late, f"тесты с mkdtemp импортируют tmpclean до первого вызова {late}")
check('rm -rf "$tmp"' in (ROOT / "tools/run_tests.sh").read_text(encoding="utf-8"),
      "tools/run_tests.sh удаляет временную папку каждого теста")

print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено {len(failures)}")
sys.exit(1 if failures else 0)
