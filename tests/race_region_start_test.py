# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Н1 проверки 1.32.3, сторона программы: запуск по Alt+W (clipsd --region) занят снимком с самого старта.

Копия, поднятая Alt+W, отдаёт себе команду region через 300 мс после открытия канала. Если в эти 300 мс приходил
вопрос quit-for-update (помощник смены версии), ответ был «ok»; через 200 мс окно выделения уже открыто, программа
оставалась, а помощник через минуту останавливал её силой вместе с выделением. Теперь с --region и --full снимок
считается запрошенным до открытия канала: ответ «busy:selector».

Настоящий `python -m clipshot` (Qt offscreen, своё окружение). Момент вопроса задаёт тест: сразу, как только канал
принимает соединения. Порядки: вопрос до открытия окна выделения и после; запуск без команды (ответ «ok», выход).

Запуск: python3 tests/race_region_start_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def main():
    if os.name == "nt":
        print("ИТОГ: только Linux (канал команд в файле), пропущено")
        return 0
    base = Path(tempfile.mkdtemp(prefix="clipsd-race-region-"))
    run = Path(os.environ.get("XDG_RUNTIME_DIR") or base / "run")
    run.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", XDG_RUNTIME_DIR=str(run), XDG_SESSION_TYPE="x11",
               PYTHONPATH=str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    for k in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS"):
        env.pop(k, None)
    sock = run / "clipshot.sock"
    procs = []

    def start(*args):
        sock.unlink(missing_ok=True)
        p = subprocess.Popen([sys.executable, "-m", "clipshot", *args], env=env, cwd=str(base),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        procs.append(p)
        return p

    def ask(limit=20.0):
        """quit-for-update, как только канал принимает соединения; ответ и сколько секунд ждали канал."""
        end = time.monotonic() + limit
        t0 = time.monotonic()
        while time.monotonic() < end:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(5)
            try:
                s.connect(str(sock))
            except OSError:
                s.close()
                time.sleep(0.003)
                continue
            s.sendall(b"quit-for-update")
            data = b""
            try:
                while b"\n" not in data:
                    chunk = s.recv(64)
                    if not chunk:
                        break
                    data += chunk
            except OSError:
                pass
            s.close()
            return data.decode().strip(), time.monotonic() - t0
        return None, limit

    def stop_all():
        for p in procs:
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGKILL)
                p.wait()
        procs.clear()

    try:
        # --- 1. Alt+W поднял программу; вопрос помощника сразу после открытия канала, до окна выделения -------
        p = start("--region")
        answer, waited = ask()
        time.sleep(1.0)
        check(answer == "busy:selector", f"вопрос до открытия окна выделения: ответ {answer!r} (канал через {waited:.2f} с)")
        check(p.poll() is None, "программа осталась работать с выделением, выхода для обновления нет")
        stop_all()

        # --- 2. обратный порядок: окно выделения уже открыто ----------------------------------------------------
        p = start("--region")
        ask()                                      # канал открыт (первый вопрос: см. выше)
        time.sleep(1.0)
        answer, _ = ask()
        check(answer == "busy:selector" and p.poll() is None, f"вопрос при открытом окне выделения: {answer!r}")
        stop_all()

        # --- 3. запуск без команды: ничего не мешает, ответ «ok» и выход -----------------------------------------
        p = start()
        answer, _ = ask()
        try:
            p.wait(15)
        except subprocess.TimeoutExpired:
            pass
        check(answer == "ok" and p.poll() is not None, f"запуск без команды: ответ {answer!r}, программа вышла")
    finally:
        stop_all()
        shutil.rmtree(base, ignore_errors=True)
    print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено {len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
