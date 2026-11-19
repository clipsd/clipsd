# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later
"""1.30 wiring of updates (from 2.0 integration_test): the updater starts with the program, the tray menu has
«Проверить обновления», quit-for-update quits, settings of 1.x are copied once into the package folder.
Runs offscreen in a temporary HOME.

Update life cycle (review R09 P0-1): an editor with unsaved changes makes quit-for-update answer
"busy" and the real switch helper (packaging/linux/clipsd-switch) defers without stopping the
program; without changes the answer is "ok", the program quits by itself and the helper switches;
SIGTERM quits through Qt with the settings saved."""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="clipsd-int-")
for var, sub in (("XDG_CONFIG_HOME", "cfg"), ("XDG_DATA_HOME", "data"), ("XDG_STATE_HOME", "state"),
                 ("XDG_CACHE_HOME", "cache"), ("CLIPSD_DATA_DIR", "clipsd-data"), ("XDG_RUNTIME_DIR", "runtime")):
    os.environ[var] = os.path.join(TMP, sub)
os.makedirs(os.environ["XDG_RUNTIME_DIR"], mode=0o700)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["XDG_SESSION_TYPE"] = "x11"          # never claim names on the real session bus
os.environ.pop("WAYLAND_DISPLAY", None)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PyQt6.QtWidgets import QApplication, QMenu  # noqa: E402

from clipshot import app as appmod, paths  # noqa: E402

appmod.CONFIG_PATH = Path(TMP) / "cfg" / "clipshot" / "config.json"

checks = []


def check(name, ok):
    checks.append((name, ok))
    print(("ok  " if ok else "FAIL"), name, flush=True)


def skip(name):
    print("skip", name, "(skip: linux only)", flush=True)


LINUX = sys.platform.startswith("linux")


qapp = QApplication(sys.argv)
a = appmod.Clipshot(qapp)
a.config["builtin_hotkeys"] = "off"
a._sync_gnome_hotkeys = lambda *x: None
appmod.is_wayland = lambda: False
a.start(f"clipsd-int-a-{os.getpid()}" if os.name == "nt" else os.path.join(TMP, "runtime", "a.sock"))
check("обновления запущены вместе с программой", hasattr(a, "_updater") and a._updater.timer is not None)
menu = QMenu()
menu.addAction("О программе")
menu.addSeparator()
menu.addAction("Выход")
from clipshot import updater  # noqa: E402
updater.install_menu(menu, a)
texts = [x.text() for x in menu.actions()]
check("пункт «Проверить обновления» перед «Выход»", texts == ["О программе", updater.tr("updater.menu.check"), "", "Выход"])
a.save_config()
check("config записан атомарно (без временных файлов)", appmod.CONFIG_PATH.exists()
      and not list(appmod.CONFIG_PATH.parent.glob("*.tmp")))
check("из исходников: свой сокет clipshot.sock, пакет не задевается", appmod.socket_path().endswith("clipshot.sock") or os.name == "nt")
check("из исходников обновления выключены (рабочая копия обновляется через git)", a._updater.kind == "dev")
quit_called = []
a.qapp.quit = lambda: quit_called.append(1)
a.handle_command("quit-for-update")
check("quit-for-update завершает", quit_called == [1])
a.server.close()

# --- what blocks quitting --------------------------------------------------------------------------
from PyQt6.QtCore import QEventLoop, QTimer  # noqa: E402
from PyQt6.QtGui import QImage  # noqa: E402


def spin(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


a.config.update(theme_chosen=True, tour_done=True)
img = QImage(320, 200, QImage.Format.Format_RGB32)
img.fill(0xFFFFFF)
ed = a.open_editor(img, None)
check("редактор без изменений: выйти можно", a.quit_blocker() == "")
ed.canvas.push_undo()
check("несохранённые изменения: выйти нельзя (unsaved)", a.quit_blocker() == "unsaved")
quit_called.clear()
a.handle_command("quit-for-update")
check("quit-for-update при несохранённом: программа не выходит", quit_called == [])
ed.exported = True
check("скопировано / сохранено: выйти можно", a.quit_blocker() == "")
ed.canvas.text_edit = object()
check("идёт ввод текста: выйти нельзя (text)", a.quit_blocker() == "text")
ed.canvas.text_edit = None
a.selector = object()
check("открыт выделитель: выйти нельзя (selector)", a.quit_blocker() == "selector")
a.selector = None
a.editors.remove(ed)
ed.hide()

# a snapshot that exists only in the editor (autosave off): closing it would lose it (P2-7)
from PyQt6.QtCore import QRect  # noqa: E402
from PyQt6.QtGui import QPixmap  # noqa: E402
shot = QPixmap(200, 120)
shot.fill()
a.config["auto_save"] = False
a._region_done(shot, QRect(0, 0, 200, 120))
ed_mem = a.editors[-1]
check("автосохранение выключено, снимок только в редакторе: выйти нельзя (unsaved)", a.quit_blocker() == "unsaved")
ed_mem.exported = True
check("тот же снимок скопирован или сохранён: выйти можно", a.quit_blocker() == "")
a.editors.remove(ed_mem)
ed_mem.hide()
a.config.update(auto_save=True, auto_save_dir=os.path.join(TMP, "shots"))
a._region_done(shot, QRect(0, 0, 200, 120))
ed_auto = a.editors[-1]
check("автосохранение включено, снимок уже в файле: выйти можно",
      a.quit_blocker() == "" and getattr(ed_auto, "autosave_path", None) and os.path.exists(ed_auto.autosave_path))
a.editors.remove(ed_auto)
ed_auto.hide()

# --- SIGTERM handler -------------------------------------------------------------------------------
order = []
c = appmod.Clipshot(qapp)
c.config["builtin_hotkeys"] = "off"
c._setup_tray = lambda *x: order.append(("tray", True))
c._setup_hotkeys = lambda *x: order.append(("hotkeys", True))
c._sync_gnome_hotkeys = lambda *x: None
# Unix: a socket file; Windows: a pipe name (QLocalServer pipe names cannot hold backslashes)
c.start(f"clipsd-int-{os.getpid()}" if os.name == "nt" else os.path.join(TMP, "runtime", "order.sock"))
check("трей и горячие клавиши настроены", order == [("tray", True), ("hotkeys", True)])
if os.name == "nt":
    # Windows has no SIGTERM delivery: os.kill(pid, SIGTERM) is TerminateProcess
    check("Windows: обработчик SIGTERM не ставится", c._signal_pipe is None)
    skip("SIGTERM доходит до Qt (через wakeup fd)")
else:
    check("обработчик SIGTERM установлен", c._signal_pipe is not None)
    c.quit_on_signal = lambda: order.append(("sigterm", True))
    os.kill(os.getpid(), signal.SIGTERM)
    spin(500)
    check("SIGTERM доходит до Qt (через wakeup fd)", ("sigterm", True) in order)
c.server.close()

# --- socket path: a too long XDG_RUNTIME_DIR falls back to the private folder (sun_path is 108 bytes) -----
if LINUX:
    from clipshot import ipc  # noqa: E402
    _rt = os.environ["XDG_RUNTIME_DIR"]
    _long = Path(TMP) / ("r" * 100)
    _long.mkdir()
    os.environ["XDG_RUNTIME_DIR"] = str(_long)
    sys.frozen = True   # the package's socket: the one clipsd-switch computes
    _p = ipc.socket_path()
    del sys.frozen
    check("слишком длинный XDG_RUNTIME_DIR: сокет в личной папке, путь не длиннее 100", len(_p) <= 100 and str(_long) not in _p)
    _sw = subprocess.run(["bash", "-c", f'source <(sed -n "/^default_socket()/,/^}}/p" "{ROOT}/packaging/linux/clipsd-switch"); default_socket'],
                         capture_output=True, text=True, env=dict(os.environ))
    check("clipsd-switch выбирает тот же сокет", _sw.stdout.strip() == _p)
    os.environ["XDG_RUNTIME_DIR"] = _rt

# --- a switch cut by a power loss: clipsd-switch --resume (the launcher runs it at the next start) ---------------
if LINUX:
    def resume_case(name, writes_mark, lock_pid=None, takeover=None):
        h = Path(TMP) / name
        app_ = h / ".local/share/clipsd"
        st = h / ".local/state/clipsd"
        for v, mark in (("1.30.0", True), ("1.30.1", writes_mark)):
            d = app_ / "versions" / v
            d.mkdir(parents=True)
            body = f'#!/bin/bash\nS="$XDG_STATE_HOME/clipsd"; mkdir -p "$S"\n' + (f'touch "$S/started-{v}"\n' if mark else "exit 1\n")
            (d / "clipsd").write_text(body)
            (d / "clipsd").chmod(0o755)
            shutil.copy2(ROOT / "packaging/linux/clipsd-switch", d / "clipsd-switch")
        (h / ".local/bin").mkdir(parents=True)
        (app_ / "current").symlink_to("versions/1.30.1")      # the link had already changed when power went off
        (h / ".local/bin/clipsd").symlink_to(app_ / "current/clipsd")
        st.mkdir(parents=True)
        (st / "switch-pending").write_text("1.30.0 1.30.1\n")
        if lock_pid is not None:   # the lock of a helper: dead (reboot) or alive
            (st / "update.lock").mkdir()
            (st / "update.lock" / "pid").write_text(f"{lock_pid}\n")
        if takeover is not None:   # another helper is taking the stale lock over right now (fresh) or died doing it (old)
            (st / "update.lock.takeover").mkdir()
            if takeover == "old":
                os.utime(st / "update.lock.takeover", (time.time() - 300, time.time() - 300))
        env_ = {"HOME": str(h), "PATH": "/usr/bin:/bin", "XDG_STATE_HOME": str(h / ".local/state"),
                "XDG_DATA_HOME": str(h / ".local/share"), "XDG_CONFIG_HOME": str(h / ".config")}
        subprocess.Popen([str(h / ".local/bin/clipsd")], env=env_).wait()   # the program starts after the reboot
        r = subprocess.run([str(app_ / "versions/1.30.1/clipsd-switch"), "--resume", "--timeout", "3",
                            "--socket", str(h / "none.sock")], env=env_, capture_output=True, text=True, timeout=60)
        res = json.loads((st / "update-result.json").read_text()) if (st / "update-result.json").exists() else {}
        return r.returncode, os.readlink(app_ / "current"), res, (st / "switch-pending").exists()
    rc, cur, res, pend = resume_case("resume-ok", True)
    check("обрыв питания, новая версия запустилась: --resume завершает переключение",
          rc == 0 and cur == "versions/1.30.1" and res.get("result") == "ok" and not pend)
    _dead = subprocess.Popen(["true"]); _dead.wait()
    _t0 = time.time()
    rc, cur, res, pend = resume_case("resume-stale-lock", True, lock_pid=_dead.pid)
    check(f"замок помощника, который умер при перезагрузке (pid {_dead.pid} не жив): --resume идёт сразу ({rc} {res.get('result')})",
          rc == 0 and res.get("result") == "ok" and not pend and time.time() - _t0 < 30)
    rc, cur, res, pend = resume_case("resume-takeover-busy", True, lock_pid=_dead.pid, takeover="fresh")
    check(f"мёртвый замок перехватывает другой помощник прямо сейчас: этот не вмешивается ({rc} {res.get('reason')})",
          rc == 2 and res.get("reason") == "lock_busy" and pend)
    rc, cur, res, pend = resume_case("resume-takeover-old", True, lock_pid=_dead.pid, takeover="old")
    check(f"брошенный перехват (старше минуты) убирается, переключение идёт ({rc} {res.get('result')})",
          rc == 0 and res.get("result") == "ok" and not pend)
    _holder_dir = Path(TMP) / "holder"
    _holder_dir.mkdir()
    (_holder_dir / "clipsd-switch").write_text("#!/bin/bash\nsleep 30\n")
    (_holder_dir / "clipsd-switch").chmod(0o755)
    _alive = subprocess.Popen([str(_holder_dir / "clipsd-switch")])
    time.sleep(0.3)
    try:
        rc, cur, res, pend = resume_case("resume-live-lock", True, lock_pid=_alive.pid)
        check(f"замок живого помощника: второй не вмешивается (lock_busy, {rc} {res})",
              rc == 2 and res.get("reason") == "lock_busy" and pend)
    finally:
        _alive.kill(); _alive.wait()
    # the launcher of the package decides the same way whether to run --resume
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location("clipsd_launcher_t", ROOT / "packaging/linux/clipsd_launcher.py")
    _lm = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_lm)
    _lh = Path(TMP) / "launcher-home"
    (_lh / "state/clipsd/update.lock").mkdir(parents=True)
    (_lh / "state/clipsd/switch-pending").write_text("1.30.0 1.30.1\n")
    (_lh / "versions/1.30.1").mkdir(parents=True)
    (_lh / "versions/1.30.1/clipsd-switch").write_text("#!/bin/sh\n")
    (_lh / "versions/1.30.1/clipsd-switch").chmod(0o755)
    _calls = []
    _old_popen, _old_exe, _old_state = _lm.subprocess.Popen if hasattr(_lm, "subprocess") else None, sys.executable, os.environ.get("XDG_STATE_HOME")
    import subprocess as _sp
    _real = _sp.Popen
    _sp.Popen = lambda args, **kw: _calls.append(args)
    sys.executable = str(_lh / "versions/1.30.1/clipsd")
    os.environ["XDG_STATE_HOME"] = str(_lh / "state")
    try:
        (_lh / "state/clipsd/update.lock/pid").write_text(f"{_dead.pid}\n")
        _lm._resume_cut_switch()
        _first = list(_calls)
        _holder2 = _real([str(_holder_dir / "clipsd-switch")])
        time.sleep(0.3)
        (_lh / "state/clipsd/update.lock/pid").write_text(f"{_holder2.pid}\n")
        _calls.clear()
        _lm._resume_cut_switch()
        _second = list(_calls)
        _holder2.kill(); _holder2.wait()
    finally:
        _sp.Popen = _real
        sys.executable = _old_exe
        if _old_state is None:
            os.environ.pop("XDG_STATE_HOME", None)
        else:
            os.environ["XDG_STATE_HOME"] = _old_state
    check("запускатель: замок мёртвого помощника, запускает --resume", bool(_first) and _first[0][-2:] == ["--detach", "--resume"])
    check("запускатель: помощник жив, --resume не запускается", not _second)
    rc, cur, res, pend = resume_case("resume-bad", False)
    check(f"обрыв питания, новая версия не запускается: --resume возвращает прежнюю ({rc} {cur} {res})",
          rc == 3 and cur == "versions/1.30.0" and res.get("result") == "rolled_back" and not pend)

# --- settings of 1.x are copied once into the folder of the package build ----------------------------
legacy = Path(TMP) / "mig" / "clipshot"
new = Path(TMP) / "mig" / "clipsd"
legacy.mkdir(parents=True)
(legacy / "config.json").write_text('{"hotkey_region": "Ctrl+Shift+A", "tool": "rect"}', encoding="utf-8")
(legacy / "google-translate.key").write_text("AIza-test", encoding="utf-8")
copied = paths.migrate_legacy(new, legacy)
check("1.x -> пакет: config.json и ключ Google скопированы",
      sorted(copied) == ["config.json", "google-translate.key"]
      and json.loads((new / "config.json").read_text(encoding="utf-8"))["hotkey_region"] == "Ctrl+Shift+A")
if os.name != "nt":
    check("1.x -> пакет: настройки и ключ доступны только владельцу (0600)",
          all(oct((new / f).stat().st_mode & 0o777) == "0o600" for f in ("config.json", "google-translate.key")))
check("1.x -> пакет: оригиналы не тронуты", (legacy / "config.json").exists() and (legacy / "google-translate.key").exists())
(new / "config.json").write_text('{"hotkey_region": "Alt+Q"}', encoding="utf-8")
check("второй запуск: ничего не копируется, новые настройки не перетёрты",
      paths.migrate_legacy(new, legacy) == [] and "Alt+Q" in (new / "config.json").read_text(encoding="utf-8"))
check("из исходников: прежняя папка ~/.config/clipshot", paths.config_dir() == paths.legacy_config_dir())
_frozen = getattr(sys, "frozen", None)
sys.frozen = True
try:
    want = "ClipSD" if os.name == "nt" else "clipsd"
    check("готовая сборка: своя папка настроек", paths.config_dir().name == want and paths.config_dir() != paths.legacy_config_dir())
finally:
    if _frozen is None:
        del sys.frozen
    else:
        sys.frozen = _frozen

if not LINUX:
    # The rest drives the Linux layout: symlinks, the bash switch helper and POSIX signals.
    # The Windows layout ({app}\\app, launcher) is covered by updater_test and install_test.ps1.
    skip("жизненный цикл обновления через clipsd-switch и SIGTERM")
    bad = [n for n, ok in checks if not ok]
    print("ИТОГ:", "все проверки пройдены" if not bad else f"провалено {len(bad)}")
    sys.exit(1 if bad else 0)

# --- the real program and the real switch helper -----------------------------------------------------
ROOTS = Path(TMP) / "life"
HOME = ROOTS / "home"
APP = HOME / ".local/share/clipsd"
STATE = HOME / ".local/state/clipsd"
RUNTIME = ROOTS / "runtime"
SOCK = RUNTIME / "clipsd.sock"
for d in (APP / "versions/1.30.0", APP / "versions/1.30.1", HOME / ".local/bin", RUNTIME, STATE):
    d.mkdir(parents=True, exist_ok=True)
RUNTIME.chmod(0o700)
(APP / "current").symlink_to("versions/1.30.0")
(HOME / ".local/bin/clipsd").symlink_to(APP / "current/clipsd")
for v in ("1.30.0", "1.30.1"):
    shutil.copy2(ROOT / "packaging/linux/clipsd-switch", APP / f"versions/{v}/clipsd-switch")
# the new version: a stand-in that confirms its start
new_bin = APP / "versions/1.30.1/clipsd"
new_bin.write_text('#!/bin/bash\nS="${XDG_STATE_HOME:-$HOME/.local/state}/clipsd"; mkdir -p "$S"; touch "$S/started-1.30.1"\n')
new_bin.chmod(0o755)
(APP / "versions/1.30.0/clipsd").write_text("#!/bin/bash\nexit 0\n")
(APP / "versions/1.30.0/clipsd").chmod(0o755)
# the old version: the REAL program (Clipshot with an editor), started from versions/1.30.0
APP_SCRIPT = APP / "versions/1.30.0/clipsd-app.py"
APP_SCRIPT.write_text(f'''
import os, sys
from pathlib import Path
sys.path.insert(0, {str(ROOT)!r})
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication
from clipshot import app as appmod
appmod.CONFIG_PATH = Path(sys.argv[1]) / "config.json"
appmod.is_wayland = lambda: False
qapp = QApplication([])
a = appmod.Clipshot(qapp)
a.config.update(theme_chosen=True, tour_done=True, builtin_hotkeys="off")
for name in ("_setup_tray", "_setup_hotkeys", "_sync_gnome_hotkeys"):
    setattr(a, name, lambda *x: None)
a.start({str(SOCK)!r})
img = QImage(300, 200, QImage.Format.Format_RGB32)
img.fill(0xFFFFFF)
ed = a.open_editor(img, None)
ed.canvas.push_undo()                       # unsaved annotations
flag = Path(sys.argv[1]) / "saved.flag"
def poll():
    if flag.exists():
        ed.exported = True                  # the person copied / saved the screenshot
t = QTimer()
t.timeout.connect(poll)
t.start(100)
(Path(sys.argv[1]) / "ready").write_text("1")
rc = qapp.exec()
(Path(sys.argv[1]) / "exit").write_text(f"{{rc}} {{a.quit_reason}}")
''')
env = {k: v for k, v in os.environ.items() if not k.startswith(("XDG_", "CLIPSD_", "DBUS_", "DISPLAY", "WAYLAND"))}
env.update(HOME=str(HOME), PATH="/usr/bin:/bin", XDG_RUNTIME_DIR=str(RUNTIME), QT_QPA_PLATFORM="offscreen",
           XDG_SESSION_TYPE="x11", XDG_CONFIG_HOME=str(HOME / ".config"), XDG_DATA_HOME=str(HOME / ".local/share"),
           XDG_STATE_HOME=str(HOME / ".local/state"), XDG_CACHE_HOME=str(HOME / ".cache"),
           CLIPSD_DATA_DIR=str(ROOTS / "clipsd-data"))


def wait_for(fn, seconds=20):
    end = time.time() + seconds
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.1)
    return fn()


SPARE_SCRIPT = ROOTS / "clipsd-app.py"   # the helper removes versions/1.30.0 after the switch
shutil.copy2(APP_SCRIPT, SPARE_SCRIPT)


def start_program(work, script=APP_SCRIPT):
    work.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen([sys.executable, str(script), str(work)], env=env, cwd=str(HOME),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ok = wait_for(lambda: (work / "ready").exists() and SOCK.exists(), 60)
    return proc, ok


def helper():
    return subprocess.run([str(APP / "versions/1.30.1/clipsd-switch"), "--from", "1.30.0", "--to", "1.30.1",
                           "--timeout", "15", "--exit-wait", "3", "--socket", str(SOCK)],
                          env=env, cwd=str(HOME), capture_output=True, text=True, timeout=120)


def result():
    try:
        return json.loads((STATE / "update-result.json").read_text())
    except (OSError, ValueError):
        return {}


work = ROOTS / "run1"
proc, ready = start_program(work)
check("настоящая программа запущена из versions/1.30.0, сокет открыт", ready)
try:
    r = helper()
    check(f"помощник: несохранённый редактор -> «отложено», код 4 (код {r.returncode})", r.returncode == 4)
    check("update-result.json: deferred", result().get("result") == "deferred")
    check("программа не убита: работает дальше", proc.poll() is None)
    check("current не переключён, новая версия оставлена", os.readlink(APP / "current") == "versions/1.30.0"
          and (APP / "versions/1.30.1/clipsd").exists())
    (work / "saved.flag").write_text("1")
    time.sleep(0.5)
    r = helper()
    check(f"помощник: без несохранённого -> ok, переключено (код {r.returncode})", r.returncode == 0)
    check("программа вышла сама по quit-for-update", wait_for(lambda: proc.poll() is not None, 10)
          and (work / "exit").read_text().split() == ["0", "update"])
    check("настройки сохранены при выходе", (work / "config.json").exists())
    check("current -> versions/1.30.1, update-result ok", os.readlink(APP / "current") == "versions/1.30.1"
          and result().get("result") == "ok")
    log_text = (STATE / "update.log").read_text() if (STATE / "update.log").exists() else ""
    check("помощник никого не убивал", "stopping it" not in log_text)
finally:
    if proc.poll() is None:
        proc.kill()

# SIGTERM (systemctl stop, logout): quits through Qt, settings saved
work = ROOTS / "run2"
proc, ready = start_program(work, SPARE_SCRIPT)
try:
    check("программа для SIGTERM запущена", ready)
    proc.send_signal(signal.SIGTERM)
    check("SIGTERM: выход через Qt с кодом 0", wait_for(lambda: proc.poll() is not None, 15) and proc.returncode == 0
          and (work / "exit").read_text().split() == ["0", "signal"])
    check("SIGTERM: настройки сохранены", (work / "config.json").exists())
finally:
    if proc.poll() is None:
        proc.kill()
bad = [n for n, ok in checks if not ok]
print("ИТОГ:", "все проверки пройдены" if not bad else f"провалено {len(bad)}")
sys.exit(1 if bad else 0)
