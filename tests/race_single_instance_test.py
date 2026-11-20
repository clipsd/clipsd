# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Г6 проверки гонок 1.32.2: две копии ClipSD при одновременном запуске.

Проверка «есть ли запущенная копия» и открытие своего канала команд были разнесены во времени (около 0,2 с), замка
не было. Два запуска почти одновременно (двойной щелчок по значку, автозапуск и ручной запуск) давали две работающие
копии: две иконки, одна без канала команд (Alt+W и --quit до неё не доходят), настройки затирают друг друга. При
выходе копия удаляла файл канала по имени, даже если он уже чужой.

Настоящий `python -m clipshot` (Qt offscreen, своё окружение). Момент задаёт тест: у первой копии открытие канала
(QLocalServer.listen) ждёт сигнала (файл, предел 20 с), то есть она уже прошла проверку и ещё не слушает.
- Вторая копия запускается в этот момент: она не становится второй работающей копией, а отдаёт команду первой,
  когда та откроет канал, и выходит.
- Обратный порядок: первая уже слушает, вторая отдаёт команду и выходит сразу.
- Выход копии, чей файл канала уже заменён другим: чужой файл остаётся.

Запуск: python3 tests/race_single_instance_test.py
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


# Запуск программы с подменённым QLocalServer.listen: отмечает, что дошла до открытия канала (файл reached), и, если
# задан файл barrier, ждёт его появления (предел 20 с).
RUNNER = r'''
import os, sys, time
reached, barrier = sys.argv[1], sys.argv[2]
sys.argv = ["clipsd", *sys.argv[3:]]
from PyQt6.QtNetwork import QLocalServer
import clipshot.app as appmod
class Server(QLocalServer):
    def listen(self, name):
        open(reached, "w").close()
        if barrier:
            end = time.monotonic() + 20
            while not os.path.exists(barrier) and time.monotonic() < end:
                time.sleep(0.02)
        return super().listen(name)
appmod.QLocalServer = Server
from clipshot.exitutil import quick_exit
quick_exit(appmod.main())
'''


def wait_for(cond, limit=10.0):
    end = time.monotonic() + limit
    while not cond() and time.monotonic() < end:
        time.sleep(0.02)
    return cond()


def main():
    if os.name == "nt":
        print("ИТОГ: только Linux (канал команд в файле), пропущено")
        return 0
    base = Path(tempfile.mkdtemp(prefix="clipsd-race-one-"))
    run = Path(os.environ.get("XDG_RUNTIME_DIR") or base / "run")
    run.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", XDG_RUNTIME_DIR=str(run),
               PYTHONPATH=str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    for k in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS"):
        env.pop(k, None)
    sock = run / "clipshot.sock"             # канал копии из исходников (ipc.SOURCE_SOCKET_NAME)
    procs = []

    def start(name, barrier="", *args):
        p = subprocess.Popen([sys.executable, "-c", RUNNER, str(base / f"reached-{name}"), barrier, *args],
                             env=env, cwd=str(base), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        procs.append(p)
        return p

    def listening():
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(1)
        try:
            s.connect(str(sock))
            return True
        except OSError:
            return False
        finally:
            s.close()

    def stop_all():
        for p in procs:
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGKILL)
                p.wait()
        procs.clear()
        for f in run.glob("clipshot.sock*"):
            if f.name == "clipshot.sock":
                f.unlink(missing_ok=True)

    try:
        # --- 1. вторая копия, пока первая между проверкой и открытием канала ---------------------------------
        a = start("a", str(base / "go-a"))
        check(wait_for(lambda: (base / "reached-a").exists(), 20), "первая копия дошла до открытия канала и ждёт")
        b = start("b", "")
        # вторая копия за 4 с либо стала бы второй работающей копией (дошла до открытия канала), либо ждёт первую
        wait_for(lambda: (base / "reached-b").exists() or b.poll() is not None, 4)
        became_second = (base / "reached-b").exists()
        (base / "go-a").write_text("")
        check(wait_for(lambda: b.poll() is not None, 20), "вторая копия вышла, отдав команду первой")
        time.sleep(1.0)
        check(not became_second and a.poll() is None and b.poll() is not None,
              f"работает одна копия (вторая дошла до своего канала: {became_second}, "
              f"первая жива: {a.poll() is None}, вторая жива: {b.poll() is None})")
        check(listening(), "у работающей копии открыт канал команд")
        q = subprocess.run([sys.executable, "-m", "clipshot", "--quit"], env=env, cwd=str(base), timeout=30,
                           capture_output=True)
        check(wait_for(lambda: a.poll() is not None, 15), f"--quit закрывает работающую копию (код {q.returncode})")
        stop_all()

        # --- 2. обратный порядок: первая уже слушает ------------------------------------------------------
        a = start("a2", "")
        check(wait_for(listening, 20), "первая копия открыла канал")
        b = start("b2", "")
        check(wait_for(lambda: b.poll() is not None, 20) and a.poll() is None,
              "вторая копия при работающей первой отдаёт команду и выходит")
        stop_all()

        # --- 3. выход копии, чей файл канала уже чужой ------------------------------------------------------
        a = start("a3", "")
        check(wait_for(listening, 20), "копия открыла канал")
        sock.unlink()
        other = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        other.bind(str(sock))                  # на этом месте теперь канал другой копии
        other.listen(1)
        ino = sock.stat().st_ino
        os.kill(a.pid, signal.SIGTERM)         # выход (как systemctl stop)
        check(wait_for(lambda: a.poll() is not None, 20), "копия вышла по SIGTERM")
        check(sock.exists() and sock.stat().st_ino == ino, "чужой файл канала после выхода копии остался на месте")
        other.close()
        stop_all()
    finally:
        stop_all()
        shutil.rmtree(base, ignore_errors=True)
    print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено {len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
