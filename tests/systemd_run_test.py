# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later
"""clipsd-switch with the REAL `systemd-run --user` (no stubs): after an update without clipsd.service (XFCE, MATE,
Cinnamon: the program autostarts from ~/.config/autostart) the new version must outlive the helper's transient unit.

Everything ClipSD writes goes into a temporary HOME; only the user manager of this session is real. The helper runs as
clipsd-update-<pid>, the program as clipsd-app-<time>-<pid>; both are short transient units, stopped and collected at
the end. The fake program only writes its start mark and sleeps (it never opens a window).
Skipped (exit 0) where there is no user manager (CI runners, containers).

Run: python3 tests/systemd_run_test.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


def user_manager_env():
    """The real runtime folder of this user, where systemctl --user reaches the manager."""
    runtime = f"/run/user/{os.getuid()}"
    if not shutil.which("systemd-run") or not Path(runtime, "systemd/private").exists():
        return None
    r = subprocess.run(["systemctl", "--user", "is-system-running"], capture_output=True, text=True,
                       env=dict(os.environ, XDG_RUNTIME_DIR=runtime))
    return runtime if r.stdout.strip() in ("running", "degraded") else None


runtime = user_manager_env()
if runtime is None:
    print("skip: no systemd user manager here")
    sys.exit(0)

tmp = Path(tempfile.mkdtemp(prefix="clipsd-sdrun-"))
home = tmp / "home"
app = home / ".local/share/clipsd"
state = home / ".local/state/clipsd"
for d in (app / "versions", home / ".local/bin", state, home / ".config"):
    d.mkdir(parents=True)
FAKE = r'''#!/bin/bash
# fake ClipSD: start mark, pid, then sleep (at most 120 s, so nothing outlives the test for long)
HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
S="${XDG_STATE_HOME:-$HOME/.local/state}/clipsd"; mkdir -p "$S"
echo $$ > "$S/app.pid"
cat /proc/self/cgroup > "$S/app.cgroup"
env | grep -E '^(DISPLAY|DBUS_SESSION_BUS_ADDRESS|XDG_SESSION_TYPE|XDG_CURRENT_DESKTOP)=' | sort > "$S/app.env"
touch "$S/started-$(cat "$HERE/VERSION")"
exec sleep 120
'''
for ver in ("1.30.0", "1.30.1"):
    d = app / "versions" / ver
    d.mkdir()
    (d / "clipsd").write_text(FAKE)
    (d / "clipsd").chmod(0o755)
    (d / "VERSION").write_text(ver + "\n")
    shutil.copy2(ROOT / "packaging/linux/clipsd-switch", d / "clipsd-switch")
(app / "current").symlink_to("versions/1.30.0")
(home / ".local/bin/clipsd").symlink_to(app / "current/clipsd")

env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "XDG_RUNTIME_DIR": runtime,
       "XDG_CONFIG_HOME": str(home / ".config"), "XDG_DATA_HOME": str(home / ".local/share"),
       "XDG_STATE_HOME": str(home / ".local/state"), "XDG_CACHE_HOME": str(home / ".cache"),
       # what a window would need; the fake program only reports that they arrived
       "DISPLAY": ":97", "DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent/clipsd-test-bus",
       "XDG_SESSION_TYPE": "x11", "XDG_CURRENT_DESKTOP": "XFCE"}
sock = tmp / "none.sock"   # no program listens: nothing to ask


def units(prefix):
    out = subprocess.run(["systemctl", "--user", "list-units", "--all", "--plain", "--no-legend", f"{prefix}*"],
                         capture_output=True, text=True, env=env).stdout
    return [ln.split()[0] for ln in out.splitlines() if ln.strip()]


app_units = []
pid = None
try:
    r = subprocess.run([str(app / "versions/1.30.1/clipsd-switch"), "--detach", "--from", "1.30.0", "--to", "1.30.1",
                        "--timeout", "20", "--exit-wait", "2", "--socket", str(sock)],
                       env=env, capture_output=True, text=True, timeout=30)
    check(r.returncode == 0, f"clipsd-switch --detach через настоящий systemd-run (код {r.returncode} {r.stderr[-200:]})")
    result = state / "update-result.json"
    end = time.time() + 40
    while time.time() < end and not result.exists():
        time.sleep(0.5)
    data = json.loads(result.read_text()) if result.exists() else {}
    check(data.get("result") == "ok", f"переключение прошло: {data}")
    check(os.readlink(app / "current") == "versions/1.30.1", "current -> versions/1.30.1")
    end = time.time() + 15
    while time.time() < end and units("clipsd-update-"):
        time.sleep(0.5)
    check(not units("clipsd-update-"), "служба помощника завершилась и убрана")
    time.sleep(10)
    pid = int((state / "app.pid").read_text()) if (state / "app.pid").exists() else None
    alive = pid is not None and Path(f"/proc/{pid}").exists()
    check(alive, f"программа жива через 10 с после завершения помощника (pid {pid})")
    cg = (state / "app.cgroup").read_text() if (state / "app.cgroup").exists() else ""
    app_units = units("clipsd-app-")
    check("clipsd-app-" in cg and app_units, f"программа в своей службе clipsd-app-*, не в службе помощника ({cg.strip()})")
    got = (state / "app.env").read_text() if (state / "app.env").exists() else ""
    check(all(f"{k}={env[k]}" in got for k in ("DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP")),
          "программа получила DISPLAY, DBUS_SESSION_BUS_ADDRESS, XDG_SESSION_TYPE, XDG_CURRENT_DESKTOP")
    check(not (state / "switch-pending").exists(), "отметка незавершённого переключения убрана после успеха")
finally:
    for u in units("clipsd-app-") + units("clipsd-update-"):
        subprocess.run(["systemctl", "--user", "stop", u], env=env, capture_output=True)
    if pid and Path(f"/proc/{pid}").exists():
        try:
            os.kill(pid, 15)
        except OSError:
            pass
    check(not units("clipsd-app-") and not units("clipsd-update-"), "после теста временных служб не осталось")

print()
if failures:
    print(f"ИТОГ: {len(failures)} проверок не прошли")
    sys.exit(1)
print("ИТОГ: все проверки пройдены")
