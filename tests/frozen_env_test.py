# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""The 19.11.2026 case: ClipSD 1.31.0 (PyInstaller package) on Ubuntu 26.04 downloaded and unpacked 1.31.1, and
nothing was switched. The running program has LD_LIBRARY_PATH = <versions/1.31.0>/_internal (the bootloader puts it
there); systemd-run inherited it and did not start ("OPENSSL_3.4.0 not found"), the helper started instead in a new
session inherited it too and died at "#!/usr/bin/env bash" (rust coreutils env: "LIBSYSTEMD_254 not found").

Here the build folder is modelled by a folder of broken libraries with the names of the real ones (libsystemd,
libcrypto, libselinux, ...): every system tool that loads one of them stops, as on Ubuntu 26.04. The checks:
1. sysenv.child_env(): the environment of a child without the build (LD_LIBRARY_PATH_ORIG back, _PYI_* and the Qt
   paths into the build gone, nothing changed when run from the sources);
2. the updater passes that environment to systemd-run (and to the helper);
3. the updater of a "frozen" program with the broken LD_LIBRARY_PATH really switches: the real clipsd-switch
   runs in a new session, writes "ok", current -> versions/2.0.1, the new program got a clean environment;
4. an OLD program (1.31.0, 1.31.1) starts the NEW helper with the broken environment and inside its own service
   clipsd.service (its systemd-run failed): the new helper cleans the environment itself, moves out of the
   service through systemd-run (a stub here) and switches.
On 1.31.1 checks 2-4 fail. Nothing outside a temporary HOME is touched (no real systemd-run, no user manager).

Run: python3 tests/frozen_env_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


if not sys.platform.startswith("linux"):
    print("skip: Linux package only")
    sys.exit(0)

from clipshot import sysenv  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="clipsd-frozen-env-"))

# --- 1. child_env --------------------------------------------------------------------------------------------
bundle = TMP / "b" / "versions" / "1.31.0" / "_internal"
bundle.mkdir(parents=True)
_saved = (getattr(sys, "frozen", None), getattr(sys, "_MEIPASS", None), sys.executable)


def frozen(on=True, meipass=bundle, exe=None):
    if on:
        sys.frozen = True
        sys._MEIPASS = str(meipass)
        sys.executable = str(exe or Path(meipass).parent / "clipsd")
    else:
        for name in ("frozen", "_MEIPASS"):
            if hasattr(sys, name):
                delattr(sys, name)
        sys.executable = _saved[2]


base = {"PATH": "/usr/bin:/bin", "HOME": "/home/x", "LD_LIBRARY_PATH": f"{bundle}:/opt/own/lib",
        "_PYI_ARCHIVE_FILE": str(bundle.parent / "clipsd"), "_PYI_PARENT_PROCESS_LEVEL": "1",
        "QT_PLUGIN_PATH": str(bundle / "PyQt6/Qt6/plugins"), "QML2_IMPORT_PATH": f"{bundle}/PyQt6/Qt6/qml:/usr/lib/qml"}
frozen(False)
check(sysenv.child_env({"PATH": "/x", "LD_LIBRARY_PATH": "/y"}) == {"PATH": "/x", "LD_LIBRARY_PATH": "/y"},
      "from the sources: the environment is passed on unchanged")
frozen(True)
env = sysenv.child_env(base)
check(env.get("LD_LIBRARY_PATH") == "/opt/own/lib", f"build folder removed from LD_LIBRARY_PATH, own folder kept ({env.get('LD_LIBRARY_PATH')})")
check(not [k for k in env if k.startswith("_PYI_")], "no _PYI_* variables")
check("QT_PLUGIN_PATH" not in env and env.get("QML2_IMPORT_PATH") == "/usr/lib/qml", "Qt paths into the build removed")
check(env.get("PYINSTALLER_RESET_ENVIRONMENT") == "1" and env["PATH"] == "/usr/bin:/bin" and env["HOME"] == "/home/x",
      "PYINSTALLER_RESET_ENVIRONMENT=1, the rest unchanged")
env = sysenv.child_env(dict(base, LD_LIBRARY_PATH=str(bundle), LD_LIBRARY_PATH_ORIG="/usr/local/mine"))
check(env.get("LD_LIBRARY_PATH") == "/usr/local/mine" and "LD_LIBRARY_PATH_ORIG" not in env,
      "LD_LIBRARY_PATH_ORIG (the person's own value saved by the bootloader) comes back")
env = sysenv.child_env(dict(base, LD_LIBRARY_PATH=str(bundle)))
check("LD_LIBRARY_PATH" not in env, "only the build folder: LD_LIBRARY_PATH removed")
check(base["LD_LIBRARY_PATH"].startswith(str(bundle)), "the given environment itself is not changed")

# --- the broken "build" -------------------------------------------------------------------------------------
POISON = ["libsystemd.so.0", "libcrypto.so.3", "libssl.so.3", "libselinux.so.1", "libacl.so.1", "libattr.so.1",
          "libcap.so.2", "libmount.so.1", "libblkid.so.1", "libpcre2-8.so.0", "libz.so.1", "liblzma.so.5",
          "libzstd.so.1", "liblz4.so.1", "libgcrypt.so.20", "libgpg-error.so.0", "libstdc++.so.6",
          "libglib-2.0.so.0", "libgio-2.0.so.0", "libgobject-2.0.so.0", "libseccomp.so.2", "libaudit.so.1",
          "libcap-ng.so.0", "libcrypt.so.1", "libgmp.so.10", "libonig.so.5", "libexpat.so.1", "libffi.so.8",
          "libuuid.so.1", "libbz2.so.1.0"]


def poison_folder(folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    for name in POISON:
        (folder / name).write_bytes(b"not a library: ClipSD frozen_env_test\n")


poisoned_env_probe = TMP / "probe" / "_internal"
poison_folder(poisoned_env_probe)
broken = []
for tool in (["/usr/bin/env", "true"], ["mkdir", "--version"], ["ln", "--version"], ["systemd-run", "--version"]):
    if not shutil.which(tool[0]):
        continue
    r = subprocess.run(tool, env=dict(os.environ, LD_LIBRARY_PATH=str(poisoned_env_probe)), capture_output=True)
    if r.returncode != 0:
        broken.append(tool[0])
print(f"     with the broken build folder these tools do not start here: {broken or 'none'}")

# --- a temporary HOME with versions 2.0.0 (running) and 2.0.1 (new) ----------------------------------------------
FAKE = r'''#!/bin/bash
# fake ClipSD: what it got from the helper, its start mark, then exit
HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
S="${XDG_STATE_HOME:-$HOME/.local/state}/clipsd"; mkdir -p "$S"
printf 'LD_LIBRARY_PATH=%s\nPYI=%s\nQT_PLUGIN_PATH=%s\n' "${LD_LIBRARY_PATH:-}" "${_PYI_ARCHIVE_FILE:-}" "${QT_PLUGIN_PATH:-}" > "$S/app-$(cat "$HERE/VERSION").env"
touch "$S/started-$(cat "$HERE/VERSION")"
'''
SYSTEMD_RUN_STUB = r'''#!/bin/bash
# stub systemd-run: records what it got, then runs the command like a transient unit (new session, only --setenv)
printf 'ARGS %s\nLD_LIBRARY_PATH=%s\n' "$*" "${LD_LIBRARY_PATH:-}" >> "$STUB_LOG"
envs=(INVOCATION_ID=stub-unit STUB_LOG="$STUB_LOG")
while [ $# -gt 0 ]; do case "$1" in --setenv=*) envs+=("${1#--setenv=}"); shift ;; --*) shift ;; *) break ;; esac; done
setsid -f /usr/bin/env -i "${envs[@]}" "$@" >/dev/null 2>&1 </dev/null
exit 0
'''


def layout(name, helper_src=ROOT / "packaging/linux/clipsd-switch"):
    home = TMP / name / "home"
    app = home / ".local/share/clipsd"
    state = home / ".local/state/clipsd"
    run = TMP / name / "run"
    for d in (app / "versions", home / ".local/bin", home / ".config", state, run):
        d.mkdir(parents=True, exist_ok=True)
    run.chmod(0o700)
    for ver in ("2.0.0", "2.0.1"):
        d = app / "versions" / ver
        d.mkdir()
        (d / "clipsd").write_text(FAKE)
        (d / "clipsd").chmod(0o755)
        (d / "VERSION").write_text(ver + "\n")
        shutil.copy2(helper_src, d / "clipsd-switch")
    poison_folder(app / "versions/2.0.0/_internal")
    (app / "current").symlink_to("versions/2.0.0")
    (home / ".local/bin/clipsd").symlink_to(app / "current/clipsd")
    return home, app, state, run


def wait_for(cond, seconds):
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.2)
    return cond()


def result_of(state):
    try:
        return json.loads((state / "update-result.json").read_text())
    except (OSError, ValueError):
        return {}


def env_file(state, ver):
    try:
        return dict(line.split("=", 1) for line in (state / f"app-{ver}.env").read_text().splitlines())
    except (OSError, ValueError):
        return {}


KEEP = {k: os.environ.get(k) for k in ("HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME",
                                       "XDG_RUNTIME_DIR", "LD_LIBRARY_PATH", "_PYI_ARCHIVE_FILE",
                                       "_PYI_PARENT_PROCESS_LEVEL", "QT_PLUGIN_PATH", "INVOCATION_ID", "PATH")}


def restore_env():
    for k, v in KEEP.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


from clipshot import updater as up  # noqa: E402  (after QT_QPA_PLATFORM)

# --- 2. the updater: systemd-run gets the clean environment ----------------------------------------------------
home, app, state, run = layout("sdrun")
build = app / "versions/2.0.0/_internal"
frozen(True, meipass=build)
os.environ.update(LD_LIBRARY_PATH=str(build), _PYI_ARCHIVE_FILE=str(build.parent / "clipsd"),
                  _PYI_PARENT_PROCESS_LEVEL="1", QT_PLUGIN_PATH=str(build / "PyQt6/Qt6/plugins"))
calls = []
try:
    how = up.launch_linux_switch(app / "versions/2.0.1", "2.0.0", "2.0.1", "a" * 32, systemd=True, socket=str(run / "x.sock"),
                                 run=lambda cmd, **kw: calls.append(kw) or type("R", (), {"returncode": 0})(),
                                 popen=lambda cmd, **kw: calls.append(kw))
finally:
    restore_env()
kw = calls[0] if calls else {}
child = kw.get("env")
check(how == "systemd-run" and isinstance(child, dict), "systemd-run is started with an explicit environment (env=)")
check(isinstance(child, dict) and str(build) not in child.get("LD_LIBRARY_PATH", "")
      and not [k for k in child if k.startswith("_PYI_")] and "QT_PLUGIN_PATH" not in child,
      "... without the build's LD_LIBRARY_PATH, _PYI_* and Qt paths (1.31.1: systemd-run inherited them and did not start)")

# --- 3. the updater of a frozen program really switches (helper in a new session) --------------------------------
home, app, state, run = layout("switch")
build = app / "versions/2.0.0/_internal"
frozen(True, meipass=build)
os.environ.pop("INVOCATION_ID", None)
os.environ.update(HOME=str(home), XDG_DATA_HOME=str(home / ".local/share"), XDG_STATE_HOME=str(home / ".local/state"),
                  XDG_CONFIG_HOME=str(home / ".config"), XDG_CACHE_HOME=str(home / ".cache"), XDG_RUNTIME_DIR=str(run),
                  LD_LIBRARY_PATH=str(build), _PYI_ARCHIVE_FILE=str(build.parent / "clipsd"),
                  _PYI_PARENT_PROCESS_LEVEL="1", QT_PLUGIN_PATH=str(build / "PyQt6/Qt6/plugins"))
try:
    how = up.launch_linux_switch(app / "versions/2.0.1", "2.0.0", "2.0.1", "b" * 32, systemd=False, socket=str(run / "none.sock"))
finally:
    restore_env()
    frozen(False)
check(how == "setsid", "helper started in a new session (no user manager)")
ok = wait_for(lambda: result_of(state).get("result"), 40)
res = result_of(state)
check(ok and res.get("result") == "ok" and res.get("reason") == "started",
      f"the helper ran and switched: update-result.json {res or 'missing'} (1.31.1: the helper died at its first line, no result)")
check(os.readlink(app / "current") == "versions/2.0.1", f"current -> versions/2.0.1 ({os.readlink(app / 'current')})")
got = env_file(state, "2.0.1")
check(got and str(build) not in got.get("LD_LIBRARY_PATH", "") and not got.get("PYI") and not got.get("QT_PLUGIN_PATH"),
      f"the new program got a clean environment ({got})")
_exit_code = getattr(up, "helper_exit_code", lambda: None)   # 1.31.1 has no watch of the helper
wait_for(lambda: _exit_code() is not None, 10)
check(_exit_code() == 0, f"helper exit code 0, the program can see it ({_exit_code()})")

# --- 4. an OLD program starts the NEW helper: broken environment, inside clipsd.service -------------------------
home, app, state, run = layout("old-program")
build = app / "versions/2.0.0/_internal"
stubs = TMP / "old-program" / "stubs"
stubs.mkdir()
(stubs / "systemd-run").write_text(SYSTEMD_RUN_STUB)
(stubs / "systemd-run").chmod(0o755)
stub_log = TMP / "old-program" / "stub.log"
cgroup = TMP / "old-program" / "cgroup"
cgroup.write_text("0::/user.slice/user-1000.slice/user@1000.service/app.slice/clipsd.service\n")
old_env = {k: v for k, v in os.environ.items() if k != "INVOCATION_ID"}
old_env.update(HOME=str(home), XDG_DATA_HOME=str(home / ".local/share"), XDG_STATE_HOME=str(home / ".local/state"),
               XDG_CONFIG_HOME=str(home / ".config"), XDG_CACHE_HOME=str(home / ".cache"), XDG_RUNTIME_DIR=str(run),
               PATH=f"{stubs}:/usr/bin:/bin", STUB_LOG=str(stub_log), CLIPSD_SWITCH_CGROUP_FILE=str(cgroup),
               # exactly what the program of a ClipSD package up to 1.31.1 passes to the helper (launch_linux_switch)
               LD_LIBRARY_PATH=str(build), _PYI_ARCHIVE_FILE=str(build.parent / "clipsd"), _PYI_PARENT_PROCESS_LEVEL="1",
               _PYI_LINUX_PROCESS_NAME="clipsd", QT_PLUGIN_PATH=str(build / "PyQt6/Qt6/plugins"))
helper = app / "versions/2.0.1/clipsd-switch"
p = subprocess.Popen([str(helper), "--from", "2.0.0", "--to", "2.0.1", "--socket", str(run / "none.sock")],
                     env=old_env, start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.PIPE)
_, err = p.communicate(timeout=60)
check(p.returncode == 0, f"the new helper started by an old program exits 0 ({p.returncode} {err.decode(errors='replace')[-200:]})")
log = (state / "update.log").read_text() if (state / "update.log").exists() else ""
check("started inside clipsd.service: moving out of it" in log, "inside clipsd.service the helper moves out (--detach)")
stub = stub_log.read_text() if stub_log.exists() else ""
check("ARGS --user --collect --quiet --unit=clipsd-update-" in stub and "--setenv=CLIPSD_SWITCH_DETACHED=1" in stub,
      "... through systemd-run --user, the moved copy is marked (no second move)")
_lib_lines = [ln for ln in stub.splitlines() if ln.startswith("LD_LIBRARY_PATH=")]
check(_lib_lines and all(str(build) not in ln for ln in _lib_lines),
      f"systemd-run got a clean environment from the helper itself ({_lib_lines})")
ok = wait_for(lambda: result_of(state).get("result"), 40)
res = result_of(state)
check(ok and res.get("result") == "ok" and os.readlink(app / "current") == "versions/2.0.1",
      f"the switch is done by the moved helper ({res or 'no result'}, current {os.readlink(app / 'current')})")
got = env_file(state, "2.0.1")
check(got and not got.get("LD_LIBRARY_PATH") and not got.get("PYI"), f"the new program got a clean environment ({got})")

# --- 4b. inside clipsd.service and no systemd-run: the program is not asked to quit, nothing changes -------------
import socket  # noqa: E402
import threading  # noqa: E402

home, app, state, run = layout("no-sdrun")
build = app / "versions/2.0.0/_internal"
stubs = TMP / "no-sdrun" / "stubs"
stubs.mkdir()
(stubs / "systemd-run").write_text("#!/bin/bash\necho \"systemd-run $*\" >> \"$STUB_LOG\"\nexit 1\n")
(stubs / "systemd-run").chmod(0o755)
stub_log = TMP / "no-sdrun" / "stub.log"
cgroup = TMP / "no-sdrun" / "cgroup"
cgroup.write_text("0::/user.slice/user-1000.slice/user@1000.service/app.slice/clipsd.service\n")
sock_path = run / "clipsd.sock"
asked = []
server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
server.bind(str(sock_path))
server.listen(4)
server.settimeout(0.5)


def serve():
    end = time.time() + 30
    while time.time() < end:
        try:
            conn, _ = server.accept()
        except OSError:
            continue
        with conn:
            conn.settimeout(2)
            try:
                data = conn.recv(64)
            except OSError:
                data = b""
            if data:
                asked.append(data)
                conn.sendall(b"ok\n")


threading.Thread(target=serve, daemon=True).start()
env4b = {k: v for k, v in os.environ.items() if k != "INVOCATION_ID"}
env4b.update(HOME=str(home), XDG_DATA_HOME=str(home / ".local/share"), XDG_STATE_HOME=str(home / ".local/state"),
             XDG_CONFIG_HOME=str(home / ".config"), XDG_CACHE_HOME=str(home / ".cache"), XDG_RUNTIME_DIR=str(run),
             PATH=f"{stubs}:/usr/bin:/bin", STUB_LOG=str(stub_log), CLIPSD_SWITCH_CGROUP_FILE=str(cgroup),
             LD_LIBRARY_PATH=str(build), _PYI_ARCHIVE_FILE=str(build.parent / "clipsd"))
p = subprocess.run([str(app / "versions/2.0.1/clipsd-switch"), "--from", "2.0.0", "--to", "2.0.1", "--socket", str(sock_path)],
                   env=env4b, capture_output=True, timeout=60)
time.sleep(0.5)
server.close()
res = result_of(state)
log = (state / "update.log").read_text() if (state / "update.log").exists() else ""
check(p.returncode == 2 and res.get("result") == "error" and res.get("reason") == "cannot_detach",
      f"no systemd-run inside clipsd.service: result error cannot_detach, exit 2 ({p.returncode} {res})")
check("systemd-run --user" in (stub_log.read_text() if stub_log.exists() else ""), "... after trying systemd-run")
check(not asked and "quit-for-update" not in log and os.readlink(app / "current") == "versions/2.0.0"
      and (app / "versions/2.0.1").is_dir(), f"the program is not asked to quit, nothing is switched or removed ({asked})")

# --- 5. every external program of the package gets the clean environment -----------------------------------------
# (the same root cause outside the update: with the build's libraries tesseract stops with "GLIBCXX_3.4.32 not found",
# systemctl and gdbus do not start, xdg-open's gio and coreutils neither: OCR, autostart, links did nothing)
import re  # noqa: E402

bare = []
for f in sorted((ROOT / "clipshot").glob("*.py")):
    src = f.read_text(encoding="utf-8")
    for m in re.finditer(r"subprocess\.(run|Popen|call|check_output|check_call)\(", src):
        depth, i = 0, m.end() - 1
        while i < len(src):
            depth += {"(": 1, ")": -1}.get(src[i], 0)
            if depth == 0:
                break
            i += 1
        call = src[m.start():i + 1]
        if "env=" not in call and "powershell" not in call:   # Windows-only calls have no PyInstaller LD_LIBRARY_PATH
            bare.append(f"{f.name}:{src.count(chr(10), 0, m.start()) + 1}")
    if f.name != "sysenv.py" and "QDesktopServices.openUrl(" in src:
        bare.append(f"{f.name}: QDesktopServices.openUrl")
    if "setOpenExternalLinks(True)" in src:
        bare.append(f"{f.name}: setOpenExternalLinks(True)")
check(not bare, f"every external program and link goes through sysenv (child_env / open_url): {bare or 'yes'}")

tools = TMP / "tools"
tools.mkdir()
(tools / "xdg-open").write_text("#!/bin/sh\nexit 0\n")
(tools / "xdg-open").chmod(0o755)
spawned = []
_real_popen = subprocess.Popen
frozen(True, meipass=build)
os.environ.update(PATH=f"{tools}:{os.environ.get('PATH', '')}", LD_LIBRARY_PATH=str(build), _PYI_ARCHIVE_FILE=str(build.parent / "clipsd"))
subprocess.Popen = lambda cmd, **kw: spawned.append((cmd, kw))
try:
    opened = sysenv.open_url("https://github.com/clipsd/clipsd/issues/new?title=x")
finally:
    subprocess.Popen = _real_popen
    restore_env()
    frozen(False)
cmd, kw = spawned[0] if spawned else ([], {})
check(opened and cmd[:1] == [str(tools / "xdg-open")] and cmd[1].startswith("https://github.com/clipsd/clipsd/issues/new")
      and str(build) not in kw.get("env", {}).get("LD_LIBRARY_PATH", "") and "_PYI_ARCHIVE_FILE" not in kw.get("env", {"_PYI_ARCHIVE_FILE": 1}),
      "package: an address opens through xdg-open with the clean environment")

restore_env()
if _saved[0] is not None:
    sys.frozen = _saved[0]
print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено {len(failures)}")
sys.exit(1 if failures else 0)
