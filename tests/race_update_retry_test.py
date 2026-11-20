# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Г5 проверки гонок 1.32.2: «Повторить» в окне сбоя обновления, пока уже идёт загрузка.

При запуске окно сбоя прошлой попытки («Повторить», «Закрыть») ждёт человека. Поверх него по таймеру приходит
предложение версии, человек жмёт «Обновить», загрузка пошла; потом «Повторить» в окне сбоя. В 1.32.2 «Повторить»
сбрасывал занятость и начинал вторую загрузку в тот же файл: второе окно загрузки поверх всех навсегда, испорченный
архив, падение программы (TypeError в _on_downloaded, SIGABRT).

Порядок A: загрузка идёт (момент задаёт тест: после первого куска загрузка ждёт сигнала), «Повторить» нажат: вторая
загрузка не начинается, окно загрузки одно, установка одна; запоздавший результат чужой загрузки пропускается.
Порядок B: окно сбоя открыто: пока оно на экране, программа занята, автоматическая проверка (таймер) не начинает
загрузку поверх него; «Повторить» после закрытия начинает одну загрузку.

Запуск: python3 tests/race_update_retry_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import hashlib
import io
import shutil
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from PyQt6.QtCore import QEventLoop, QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)
import channel_sign as cs  # noqa: E402
from clipshot import updater as up  # noqa: E402

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


keys = Path(tempfile.mkdtemp(prefix="clipsd-race-keys-"))
try:
    PUB = cs.keygen(keys / "s.pem")
    PRIV = cs.load_private(keys / "s.pem")
finally:
    shutil.rmtree(keys, ignore_errors=True)
NOW = datetime.now(timezone.utc)
PAYLOAD = b"x" * (64 * 1024 * 8)
SHA = hashlib.sha256(PAYLOAD).hexdigest()
DOC = cs.dump({"schema": 1, "channel": "stable", "version": "2.0.1", "released": cs.utc(NOW - timedelta(days=1)),
               "expires": cs.utc(NOW + timedelta(days=30)),
               "files": {p: {"url": f"https://example.invalid/f-{p}", "size": len(PAYLOAD), "sha256": SHA}
                         for p in ("windows", "linux")},
               "notes": {"en": "n", "ru": "n"}})
SIG = cs.sign_bytes(PRIV, DOC)
RECORD = {"from": "2.0.0", "to": "2.0.1", "attempt_id": "deadbeef0000", "trace_id": "t", "time": cs.utc(NOW)}


def wait_for(cond, limit=10.0):
    end = time.monotonic() + limit
    while not cond() and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)
    return cond()


class Ctx:
    config = {}

    def save_config(self):
        pass

    def notify(self, text):
        pass

    def quit_blocker(self):
        return ""


class UI:
    def __init__(self):
        self.events = []

    def offer(self, manifest, installed, critical=False):
        self.events.append("offer")
        return "update"

    def progress_start(self, version, cancel):
        self.events.append("progress_start")

    def progress_show(self):
        self.events.append("progress_show")

    def progress_stage(self, text):
        pass

    def progress_update(self, done, total):
        pass

    def progress_close(self):
        self.events.append("progress_close")

    def info(self, text):
        self.events.append("info")

    def error(self, text):
        self.events.append("error")

    def whats_new(self, *a):
        pass

    def open_url(self, *a):
        pass


def make(go):
    started = []

    class Response(io.BytesIO):
        def read(self, n=-1):
            if self.tell() > 0:
                go.wait(10)          # после первого куска загрузка ждёт сигнала теста
            return super().read(n)

        def __exit__(self, *a):
            return False

    def opener(request, timeout=10):
        started.append(time.monotonic())
        return Response(PAYLOAD)

    ui = UI()
    u = up.Updater(Ctx(), fetch=lambda url, limit: SIG if url.endswith(".sig") else DOC, opener=opener,
                   kind="linux", installed="2.0.0", ui=ui, stable_keys=[PUB], test_keys=[])
    installs = []

    def install(path, manifest, trace_id):
        installs.append(manifest.version)
        u._pending = None             # как _install_started
        u.busy = False

    u.install = install
    return u, ui, installs, started


# --- порядок A: загрузка идёт, потом «Повторить» --------------------------------------------------------------
shutil.rmtree(up.downloads_dir(), ignore_errors=True)
go = threading.Event()
u, ui, installs, started = make(go)
u.check_now(manual=True)                                     # «Обновить» в окне-предложении: загрузка №1
check(wait_for(lambda: len(started) == 1 and u._pending is not None, 10), "загрузка №1 идёт")
u.retry_update(RECORD)                                       # «Повторить» в окне сбоя под ним
wait_for(lambda: False, 0.5)                                 # вторая проверка канала успела бы прийти
check(u.busy, "после «Повторить» программа по-прежнему занята загрузкой")
check(len(started) == 1 and ui.events.count("progress_start") == 1,
      f"вторая загрузка не начата, окно загрузки одно (загрузок {len(started)}, окон {ui.events.count('progress_start')})")
check("progress_show" in ui.events, "«Повторить» показывает идущую загрузку")
go.set()
check(wait_for(lambda: bool(installs), 10), "загрузка дошла до установки")
wait_for(lambda: False, 0.3)
check(installs == ["2.0.1"], f"установка одна: {installs}")
# запоздавший результат другой загрузки (номер не тот) не трогает состояние
u._pending = None
u._downloaded.emit(None, up.UpdateError("cancelled"), 999)
wait_for(lambda: False, 0.1)
check(installs == ["2.0.1"] and "error" not in ui.events, "чужой результат загрузки пропущен без ошибки")

# --- порядок B: окно сбоя открыто, потом таймер, потом «Повторить» -----------------------------------------------
shutil.rmtree(up.downloads_dir(), ignore_errors=True)
go2 = threading.Event()
go2.set()
u2, ui2, installs2, started2 = make(go2)
seen = {}


def failed(version, report, title, hint=""):
    """Окно сбоя: модальное, свой цикл событий. Пока оно открыто, срабатывает таймер обновлений."""
    loop = QEventLoop()
    seen["busy_inside"] = u2.busy
    seen["auto_started"] = u2.check_now(manual=False)        # суточная проверка или срочное по таймеру
    QTimer.singleShot(300, loop.quit)
    loop.exec()
    return "retry"


ui2.failed = failed
u2._show_failure(RECORD, "no_start_mark", "switch")
check(seen.get("busy_inside") is True, "пока окно сбоя открыто, программа занята")
check(seen.get("auto_started") is False, "таймер не начинает проверку и загрузку поверх окна сбоя")
check(wait_for(lambda: bool(installs2), 10), "«Повторить»: версия скачана и дошла до установки")
check(len(started2) == 1 and ui2.events.count("progress_start") == 1,
      f"«Повторить»: одна загрузка и одно окно (загрузок {len(started2)}, окон {ui2.events.count('progress_start')})")

print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено {len(failures)}")
from clipshot.exitutil import quick_exit  # noqa: E402
quick_exit(1 if failures else 0)
