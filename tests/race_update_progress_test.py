# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Г2 проверки гонок 1.32.2: окно загрузки обновления закрыли, пока загрузка идёт.

«Обновить» в окне предложения: окно загрузки по центру, «Можно продолжать работу». Человек жмёт Esc или крестик,
чтобы убрать окно. В 1.32.2 окно закрывалось и удалялось, а поток загрузки продолжал слать прогресс в удалённое окно:
RuntimeError в обработчике сигнала, программа падала (SIGABRT). Теперь Esc и крестик только прячут окно, загрузка
идёт дальше; окно, удалённое иначе (менеджер окон), UpdaterUI забывает.

Момент загрузки задаёт тест: первый кусок приходит сразу, остальные после сигнала (Event, предел 10 с), то есть окно
закрыто строго посреди загрузки. Окна настоящие (UpdaterUI), сеть подменена, подпись документа канала тестовыми
ключами. Каждый сценарий в своём процессе: падение не роняет сам тест.

Запуск: python3 tests/race_update_progress_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def child(mode: str) -> int:
    import hashlib
    import io
    import shutil
    import tempfile
    import threading
    import time
    from datetime import datetime, timedelta, timezone

    from PyQt6 import sip
    from PyQt6.QtCore import QEvent, Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    import channel_sign as cs
    from clipshot import updater as up
    shutil.rmtree(up.downloads_dir(), ignore_errors=True)   # архив прошлого сценария иначе взялся бы без загрузки

    keys = Path(tempfile.mkdtemp(prefix="clipsd-race-keys-"))
    try:
        pub = cs.keygen(keys / "s.pem")
        priv = cs.load_private(keys / "s.pem")
    finally:
        shutil.rmtree(keys, ignore_errors=True)
    now = datetime.now(timezone.utc)
    payload = b"x" * (64 * 1024 * 8)
    sha = hashlib.sha256(payload).hexdigest()
    doc = cs.dump({"schema": 1, "channel": "stable", "version": "2.0.1", "released": cs.utc(now - timedelta(days=1)),
                   "expires": cs.utc(now + timedelta(days=30)),
                   "files": {p: {"url": f"https://example.invalid/f-{p}", "size": len(payload), "sha256": sha}
                             for p in ("windows", "linux")},
                   "notes": {"en": "n", "ru": "n"}})
    sig = cs.sign_bytes(priv, doc)
    go = threading.Event()
    first = threading.Event()

    class Response(io.BytesIO):
        def read(self, n=-1):
            if self.tell() > 0:
                go.wait(10)              # остальные куски: только после того, как окно закрыто
            data = super().read(n)
            first.set()
            return data

        def __exit__(self, *a):
            return False

    class Ctx:
        config = {}

        def save_config(self):
            pass

        def notify(self, t):
            pass

        def quit_blocker(self):
            return ""

    ui = up.UpdaterUI()
    ui.offer = lambda *a, **k: "update"   # человек нажал «Обновить»
    u = up.Updater(Ctx(), fetch=lambda url, limit: sig if url.endswith(".sig") else doc,
                   opener=lambda req, timeout=10: Response(payload), kind="linux", installed="2.0.0", ui=ui,
                   stable_keys=[pub], test_keys=[])
    installed = []
    u.install = lambda path, manifest, trace_id: installed.append(path)   # дальше загрузки этой проверке не нужно

    def wait_for(cond, limit=10.0):
        end = time.monotonic() + limit
        while not cond() and time.monotonic() < end:
            app.processEvents()
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
            time.sleep(0.01)
        return cond()

    u.check_now(manual=True)
    if not wait_for(lambda: ui.progress is not None and ui.progress.isVisible() and first.is_set(), 10):
        print("download window did not open", flush=True)
        return 2
    wait_for(lambda: False, 0.2)                 # первый прогресс дошёл до окна
    w = ui.progress
    if mode == "esc":
        QTest.keyClick(w, Qt.Key.Key_Escape)
    elif mode == "cross":
        w.close_b.click()
    else:                                        # окно закрыто не кнопкой (менеджер окон): удаляется
        w.close()
    wait_for(lambda: False, 0.3)
    print("window deleted:", sip.isdeleted(w), "| visible:", (not sip.isdeleted(w)) and w.isVisible(), flush=True)
    go.set()                                     # загрузка продолжается после закрытия окна
    if not wait_for(lambda: bool(installed), 10):
        print("download did not finish", flush=True)
        return 2
    print("download finished, install step reached", flush=True)
    ui.progress_stage("installing")             # окно говорит, что дальше (как _on_downloaded)
    ui.progress_update(1, 2)
    ui.progress_close()
    wait_for(lambda: False, 0.3)
    print("ALIVE", flush=True)
    return 0


def run(mode: str):
    env = dict(os.environ, QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", "offscreen"))
    res = subprocess.run([sys.executable, __file__, "child", mode], capture_output=True, text=True, timeout=120,
                         env=env, cwd=str(ROOT))
    return res.returncode, res.stdout + res.stderr


if __name__ == "__main__":
    if sys.argv[1:2] == ["child"]:
        from clipshot.exitutil import quick_exit
        quick_exit(child(sys.argv[2]))
    rc, out = run("esc")
    check(rc == 0 and "ALIVE" in out and "download finished" in out,
          f"Esc в окне загрузки посреди загрузки: программа жива, загрузка дошла до установки (код {rc})"
          + ("" if rc == 0 else "\n" + out[-1500:]))
    check("window deleted: False | visible: False" in out, "Esc: окно загрузки спрятано, а не удалено")
    rc, out = run("cross")
    check(rc == 0 and "ALIVE" in out and "download finished" in out,
          f"крестик окна загрузки: программа жива (код {rc})" + ("" if rc == 0 else "\n" + out[-1500:]))
    check("window deleted: False | visible: False" in out, "крестик: окно загрузки спрятано, а не удалено")
    rc, out = run("wm_close")
    check(rc == 0 and "ALIVE" in out and "download finished" in out,
          f"окно загрузки удалено не кнопкой (менеджер окон): программа жива (код {rc})"
          + ("" if rc == 0 else "\n" + out[-1500:]))
    print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено {len(failures)}")
    sys.exit(1 if failures else 0)
