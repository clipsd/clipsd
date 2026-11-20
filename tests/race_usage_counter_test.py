# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Г11 проверки гонок 1.32.2: счётчик расхода перевода (translate-usage.json).

«Перевод кусками»: несколько окошек переводятся одновременно, каждый поток после ответа сервиса читает счётчик,
прибавляет и перезаписывает файл (сначала обрезая его). Без замка прибавки терялись (ClipSD считал, что знаки ещё
есть, и не предупреждал о лимите), а чтение во время перезаписи видело пустой файл: счётчик дня начинался с нуля.

Начало задаёт тест (Barrier: все потоки стартуют одновременно; в двух процессах общий файл-сигнал). Проверки:
сумма точная, читающий (строка «осталось N знаков») ни разу не видит, что счётчик уменьшился; то же для Google; два
процесса пишут один файл.

Запуск: python3 tests/race_usage_counter_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clipshot import translate  # noqa: E402

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


CHILD = r'''
import os, sys, time
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from clipshot import translate
translate.usage_path = lambda: Path(sys.argv[2])
go = sys.argv[3]
end = time.monotonic() + 20
while not os.path.exists(go) and time.monotonic() < end:
    time.sleep(0.005)
for _ in range(300):
    translate.add_mymemory_chars(10)
'''


def main():
    tmp = Path(tempfile.mkdtemp(prefix="clipsd-race-usage-"))
    try:
        usage = tmp / "translate-usage.json"
        translate.usage_path = lambda: usage

        # --- потоки одной программы: MyMemory и строка «осталось» в это время -------------------------------
        n_threads, n_blocks, chars = 4, 200, 10
        barrier = threading.Barrier(n_threads + 1)
        drops = []
        stop = threading.Event()

        def writer():
            barrier.wait(10)
            for _ in range(n_blocks):
                translate.add_mymemory_chars(chars)

        def reader():
            barrier.wait(10)
            last = 0
            while not stop.is_set():
                v = translate.mymemory_usage()[0]
                if v < last:
                    drops.append((last, v))
                last = max(last, v)

        threads = [threading.Thread(target=writer) for _ in range(n_threads)]
        r = threading.Thread(target=reader)
        for t in threads + [r]:
            t.start()
        for t in threads:
            t.join(60)
        stop.set()
        r.join(10)
        got = translate.mymemory_usage()[0]
        want = n_threads * n_blocks * chars
        check(got == want, f"MyMemory: 4 окошка одновременно, ожидалось {want} знаков, счётчик {got}")
        check(not drops, f"строка «осталось N знаков» ни разу не видела, что счётчик уменьшился ({len(drops)})")

        # --- Google за месяц ----------------------------------------------------------------------------------
        barrier2 = threading.Barrier(n_threads)

        def gwriter():
            barrier2.wait(10)
            for _ in range(100):
                translate.add_google_chars(7)

        gt = [threading.Thread(target=gwriter) for _ in range(n_threads)]
        for t in gt:
            t.start()
        for t in gt:
            t.join(60)
        check(translate.google_usage()[0] == n_threads * 100 * 7,
              f"Google: ожидалось {n_threads * 700}, счётчик {translate.google_usage()[0]}")
        check(translate.mymemory_usage()[0] == want, "счётчик MyMemory не задет записью Google")

        # --- два процесса пишут один файл --------------------------------------------------------------------
        usage2 = tmp / "two" / "translate-usage.json"
        usage2.parent.mkdir()
        go = tmp / "go"
        procs = [subprocess.Popen([sys.executable, "-c", CHILD, str(ROOT), str(usage2), str(go)]) for _ in range(2)]
        time.sleep(0.5)
        go.write_text("")
        for p in procs:
            p.wait(120)
        translate.usage_path = lambda: usage2
        got2 = translate.mymemory_usage()[0]
        check(got2 == 2 * 300 * 10, f"два процесса: ожидалось 6000, счётчик {got2}")
        leftovers = [f.name for f in usage2.parent.iterdir() if f.name.endswith(".tmp")]
        check(not leftovers, f"временных файлов записи не осталось {leftovers}")
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено {len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
