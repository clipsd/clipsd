# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Г3 проверки гонок 1.32.2: Alt+W в момент смены версии на Linux.

Помощник clipsd-switch убедился, что старая копия вышла, пишет switch-pending, делает sync и только потом переключает
current. Если в этот момент нажать Alt+W, GNOME запускает ~/.local/bin/clipsd --region, а это ещё старая версия: она
поднимается снова. В 1.32.2 помощник запускал новую версию, та отдавала команду старой копии и выходила: метки запуска
нет, обновление откатывалось (rolled_back no_start_mark), через 10 минут окно сбоя.

Настоящий packaging/linux/clipsd-switch в песочнице: versions/1.0.0 и 1.0.1 с поддельной программой (одна копия на
сокет, метка запуска, ответ «ok» или «busy:selector» на quit-for-update), службы systemd нет. Момент Alt+W задаёт тест:
поддельный sync в PATH ждёт сигнала (файл, предел 20 с).
- Alt+W во время первого sync (current ещё старый, старая копия поднялась снова): обновление встаёт, старая копия
  вышла по просьбе, новая записала метку, current на новой версии.
- То же, но старая копия занята (человек выделяет область): смена откладывается (код 4, deferred), current снова на
  старой версии, switch-pending убран; ничего не откатывается и не убивается.
- Обратный порядок: Alt+W во время второго sync (current уже новый): запускается новая версия, обновление встаёт.
Запускатель сборки (clipsd_launcher._current_program): если current уже указывает на другую установленную версию,
запускается она, а не та, что запущена по старой ссылке.

Запуск: python3 tests/race_switch_altw_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import json
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
SWITCH = ROOT / "packaging/linux/clipsd-switch"
failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


# Как у настоящей сборки, процесс программы узнаётся по папке своей версии (у сборки /proc/<pid>/exe, здесь первый
# аргумент Python): versions/<v>/clipsd запускает fake.py из своей настоящей папки, даже через ~/.local/bin/clipsd.
WRAPPER = r'''#!/bin/bash
here="$(dirname "$(readlink -f "$0")")"
exec {python} "$here/fake.py" "$@"
'''

FAKE = r'''#!{python}
# Поддельная ClipSD: одна копия на сокет (вторая отдаёт команду и выходит), метка запуска started-<версия>,
# ответ на quit-for-update: «busy:selector», если есть файл SB/busy; с файлом SB/okstay первый ответ «ok», но копия
# остаётся (окно выделения открылось после ответа, Н1 проверки 1.32.3), дальше «busy:selector»; иначе «ok» и выход.
import os, signal, socket, sys, time
ver = os.path.basename(os.path.dirname(os.path.realpath(__file__)))
sb = os.environ["CLIPSD_TEST_SB"]
sock_path = os.path.join(os.environ["XDG_RUNTIME_DIR"], "clipsd.sock")
state = os.path.join(os.environ["XDG_STATE_HOME"], "clipsd")
def note(text):
    with open(os.path.join(sb, "fake.log"), "a") as f:
        f.write(f"{{time.time():.3f}} {{ver}} pid={{os.getpid()}} {{text}}\n")
def term(signum, frame):
    note("KILLED by SIGTERM")
    sys.exit(143)
signal.signal(signal.SIGTERM, term)
asked = [0]
cmd = sys.argv[1] if len(sys.argv) > 1 else ""
c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
try:
    c.connect(sock_path)
    c.sendall(cmd.encode())
    c.close()
    note(f"handed over '{{cmd}}', exit")
    sys.exit(0)
except OSError:
    pass
try:
    os.unlink(sock_path)
except OSError:
    pass
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.bind(sock_path)
s.listen(5)
note(f"running {{sys.argv[1:]}}")
os.makedirs(state, exist_ok=True)
open(os.path.join(state, f"started-{{ver}}"), "w").write("{{}}")
while True:
    conn, _ = s.accept()
    data = conn.recv(64).decode()
    if data == "quit-for-update":
        if os.path.exists(os.path.join(sb, "okstay")) and "--region" in sys.argv[1:]:
            asked[0] += 1
            conn.sendall(b"ok\n" if asked[0] == 1 else b"busy:selector\n")
            conn.close()
            note("ok, but stayed" if asked[0] == 1 else "busy")
            continue
        if os.path.exists(os.path.join(sb, "busy")):
            conn.sendall(b"busy:selector\n")
            conn.close()
            note("busy")
            continue
        conn.sendall(b"ok\n")
        conn.close()
        s.close()
        os.unlink(sock_path)
        note("quit for update")
        sys.exit(0)
    conn.close()
'''

SYNC = r'''#!/bin/bash
# Поддельный sync: вызов номер N ждёт файла release-N, если тест положил hold-N (предел 20 с)
n=$(( $(cat "$CLIPSD_TEST_SB/sync-count" 2>/dev/null || echo 0) + 1 ))
echo "$n" > "$CLIPSD_TEST_SB/sync-count"
if [ -f "$CLIPSD_TEST_SB/hold-$n" ]; then
  : > "$CLIPSD_TEST_SB/in-sync-$n"
  for i in $(seq 200); do [ -f "$CLIPSD_TEST_SB/release-$n" ] && break; sleep 0.1; done
fi
exit 0
'''


def kill_sandbox(sb: Path):
    for p in Path("/proc").glob("[0-9]*"):
        try:
            cmd = (p / "cmdline").read_bytes().replace(b"\0", b" ").decode()
            if str(sb) in cmd and int(p.name) != os.getpid():
                os.kill(int(p.name), signal.SIGKILL)
        except (OSError, ValueError):
            pass


def wait_for(cond, limit=20.0):
    end = time.monotonic() + limit
    while not cond() and time.monotonic() < end:
        time.sleep(0.02)
    return cond()


def listening(path: Path) -> bool:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(1)
    try:
        s.connect(str(path))
        return True
    except OSError:
        return False
    finally:
        s.close()


def scenario(base: Path, name: str, hold: int, busy: bool = False, okstay: bool = False):
    """hold: номер вызова sync, во время которого нажимается Alt+W (1: current ещё старый, 2: уже новый)."""
    sb = Path(tempfile.mkdtemp(prefix=f"{name}-", dir=base))
    home, run = sb / "h", sb / "r"
    app, state, binp = home / ".local/share/clipsd", home / ".local/state/clipsd", home / ".local/bin/clipsd"
    for d in (run, app / "versions", state, binp.parent, sb / "bin"):
        d.mkdir(parents=True, exist_ok=True)
    run.chmod(0o700)
    for v in ("1.0.0", "1.0.1"):
        (app / "versions" / v).mkdir()
        f = app / "versions" / v / "clipsd"
        f.write_text(WRAPPER.format(python=sys.executable))
        f.chmod(0o755)
        (app / "versions" / v / "fake.py").write_text(FAKE.format(python=sys.executable))
    shutil.copy2(SWITCH, app / "versions/1.0.1/clipsd-switch")
    os.symlink("versions/1.0.0", app / "current")
    os.symlink(app / "current/clipsd", binp)
    (sb / "bin/sync").write_text(SYNC)
    (sb / "bin/sync").chmod(0o755)
    (sb / "fake.log").write_text("")
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("XDG_", "CLIPSD_", "DBUS_", "INVOCATION_ID", "LD_LIBRARY_PATH"))}
    env.update(HOME=str(home), XDG_RUNTIME_DIR=str(run), XDG_DATA_HOME=str(home / ".local/share"),
               XDG_STATE_HOME=str(state.parent), XDG_CONFIG_HOME=str(home / ".config"), CLIPSD_TEST_SB=str(sb),
               PATH=f"{sb / 'bin'}:/usr/bin:/bin", LANG="C.UTF-8")
    sock = run / "clipsd.sock"
    try:
        subprocess.Popen([str(binp)], env=env, start_new_session=True)     # работающая ClipSD 1.0.0
        if not wait_for(lambda: listening(sock), 10):
            return {"error": "old copy did not start"}
        (sb / f"hold-{hold}").write_text("")
        helper = subprocess.Popen([str(app / "versions/1.0.1/clipsd-switch"), "--from", "1.0.0", "--to", "1.0.1",
                                   "--timeout", "5", "--exit-wait", "10", "--socket", str(sock)], env=env,
                                  start_new_session=True)
        if not wait_for(lambda: (sb / f"in-sync-{hold}").exists(), 20):
            helper.kill()
            return {"error": "helper did not reach sync"}
        if busy:
            (sb / "busy").write_text("")
        if okstay:
            (sb / "okstay").write_text("")
        # Alt+W: GNOME запускает ~/.local/bin/clipsd --region; ждём, пока поднявшаяся копия откроет свой сокет
        subprocess.Popen([str(binp), "--region"], env=env, start_new_session=True)
        up = wait_for(lambda: listening(sock), 10)
        (sb / f"release-{hold}").write_text("")
        try:
            rc = helper.wait(timeout=60)
        except subprocess.TimeoutExpired:
            helper.kill()
            rc = None
        try:
            result = json.loads((state / "update-result.json").read_text())
        except (OSError, ValueError):
            result = {}
        return {"rc": rc, "up": up, "result": result, "current": os.readlink(app / "current"),
                "pending": (state / "switch-pending").exists(), "log": (sb / "fake.log").read_text(),
                "alive_old": [ln for ln in (sb / "fake.log").read_text().splitlines()]}
    finally:
        kill_sandbox(sb)


def launcher_checks(base: Path):
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "packaging/linux"))
    import clipsd_launcher as cl
    data = base / "launcher" / "share"
    app = data / "clipsd"
    for v in ("1.0.0", "1.0.1"):
        (app / "versions" / v).mkdir(parents=True)
        (app / "versions" / v / "clipsd").write_text("#!/bin/sh\n")
        (app / "versions" / v / "clipsd").chmod(0o755)
    os.symlink("versions/1.0.1", app / "current")
    got = cl._current_program(str(app / "versions/1.0.0/clipsd"), str(data))
    check(got == str(app.resolve() / "versions/1.0.1/clipsd") or got == str(app / "versions/1.0.1/clipsd"),
          f"запускатель старой версии при current на новой: запускается новая ({got})")
    check(cl._current_program(str(app / "versions/1.0.1/clipsd"), str(data)) == "",
          "запускатель версии, на которую указывает current: запускается сам")
    outside = base / "launcher" / "unpacked" / "clipsd"
    outside.parent.mkdir(parents=True)
    outside.write_text("#!/bin/sh\n")
    check(cl._current_program(str(outside), str(data)) == "", "распакованный архив вне versions: запускается сам")


def main():
    if not sys.platform.startswith("linux") or shutil.which("bash") is None:
        print("ИТОГ: только Linux, пропущено")
        return 0
    base = Path(tempfile.mkdtemp(prefix="clipsd-race-sw-"))
    try:
        r = scenario(base, "a", hold=1)
        check("error" not in r, f"песочница: {r.get('error', 'ok')}")
        if "error" not in r:
            check(r["up"], "Alt+W во время смены: старая версия поднялась снова (условие гонки создано)")
            check(r["rc"] == 0 and r["result"].get("result") == "ok" and r["current"] == "versions/1.0.1",
                  f"Alt+W до переключения current: обновление встало (код {r['rc']}, {r['result']}, current -> "
                  f"{r['current']})" + ("" if r["rc"] == 0 else "\n" + r["log"]))
            check(not r["pending"], "switch-pending убран")
        r = scenario(base, "b", hold=1, busy=True)
        check("error" not in r, f"песочница: {r.get('error', 'ok')}")
        if "error" not in r:
            check(r["rc"] == 4 and r["result"].get("result") == "deferred" and r["current"] == "versions/1.0.0"
                  and not r["pending"],
                  f"старая копия занята выделением: смена отложена, current на старой версии (код {r['rc']}, "
                  f"{r['result']}, current -> {r['current']}, pending {r['pending']})" + ("" if r["rc"] == 4 else "\n" + r["log"]))
            check("quit for update" not in r["log"].split("busy")[-1] and "rolled_back" not in json.dumps(r["result"]),
                  "занятая копия не остановлена и ничего не откатывалось")
        # Н1 проверки 1.32.3: копия, поднятая Alt+W, ответила «ok» до открытия окна выделения и осталась с ним
        r = scenario(base, "d", hold=1, okstay=True)
        check("error" not in r, f"песочница: {r.get('error', 'ok')}")
        if "error" not in r:
            check("KILLED" not in r["log"], "копия, ответившая «ok» и оставшаяся с выделением, не остановлена силой"
                  + ("" if "KILLED" not in r["log"] else "\n" + r["log"]))
            check(r["rc"] == 4 and r["result"].get("result") == "deferred" and r["current"] == "versions/1.0.0"
                  and not r["pending"],
                  f"её спросили ещё раз, ответ «занята»: смена отложена, current на старой версии (код {r['rc']}, "
                  f"{r['result']}, current -> {r['current']})")
        r = scenario(base, "c", hold=2)
        check("error" not in r, f"песочница: {r.get('error', 'ok')}")
        if "error" not in r:
            check(r["rc"] == 0 and r["result"].get("result") == "ok" and r["current"] == "versions/1.0.1",
                  f"Alt+W после переключения current: запущена новая версия, обновление встало (код {r['rc']}, "
                  f"{r['result']})" + ("" if r["rc"] == 0 else "\n" + r["log"]))
        launcher_checks(base)
    finally:
        kill_sandbox(base)
        shutil.rmtree(base, ignore_errors=True)
    print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено {len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
