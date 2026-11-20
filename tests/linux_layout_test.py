# ClipSD: layout test of the Linux packaging. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""install -> update (switch) -> rollback when the new version does not start -> uninstall.

Everything runs with HOME pointing at a temporary folder; systemctl, systemd-run, gsettings,
gnome-extensions and glib-compile-schemas are replaced by stubs in PATH, the program is a fake
shell script. The test also compares key paths of the REAL home before and after.

Run from the project root:   python3 tests/linux_layout_test.py
Exit code 0: all checks passed.
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import json
import os
import pwd
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIN = ROOT / "packaging/linux"
EXT = "clipsd@clipsd.github.io"
failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


# ---------------------------------------------------------------- stubs
STUBS = {
"systemctl": r'''#!/bin/bash
echo "systemctl $*" >> "$STUB_LOG"
args="$*"
case "$args" in
  *"is-active --quiet graphical-session.target"*) [ -e "$STUB_DIR/no_systemd" ] && exit 1; exit 0 ;;
  *clipshot.service*) exit 1 ;;
  *"restart clipsd.service"*)
    pf="$HOME/.local/state/clipsd/fake.pid"; [ -f "$pf" ] && kill "$(cat "$pf")" 2>/dev/null; sleep 0.3
    setsid -f "$HOME/.local/bin/clipsd" >/dev/null 2>&1 </dev/null; exit 0 ;;
  *"stop clipsd.service"*|*"disable --now clipsd.service"*)
    pf="$HOME/.local/state/clipsd/fake.pid"; [ -f "$pf" ] && kill "$(cat "$pf")" 2>/dev/null; exit 0 ;;
esac
exit 0
''',
"systemd-run": r'''#!/bin/bash
echo "systemd-run $*" >> "$STUB_LOG"
while [ $# -gt 0 ]; do case "$1" in --*) shift ;; *) break ;; esac; done
setsid -f "$@" >/dev/null 2>&1 </dev/null
exit 0
''',
"gsettings": r'''#!/bin/bash
echo "gsettings $*" >> "$STUB_LOG"
store="$STUB_DIR/gs"; mkdir -p "$store"
fname() { echo "$1__$2" | tr '/:' '__'; }
case "$1" in
  list-schemas) printf '%s\n' org.gnome.settings-daemon.plugins.media-keys org.gnome.shell.keybindings org.gnome.shell ;;
  get)
    f="$store/$(fname "$2" "$3")"
    if [ -f "$f" ]; then cat "$f"; else
      case "$3" in
        enabled-extensions) echo "['clipsd@old-copy', 'other@x']" ;;
        show-screenshot-ui) echo "['<Alt>w', '<Super><Shift>s']" ;;
        custom-keybindings) echo "@as []" ;;
        *) echo "''" ;;
      esac
    fi ;;
  set) printf '%s\n' "$4" > "$store/$(fname "$2" "$3")" ;;
  reset-recursively) rm -f "$store/$(echo "$2" | tr '/:' '__')"* ;;
esac
exit 0
''',
"glib-compile-schemas": "#!/bin/bash\necho \"glib-compile-schemas $*\" >> \"$STUB_LOG\"\nexit 0\n",
"gnome-extensions": "#!/bin/bash\necho \"gnome-extensions $*\" >> \"$STUB_LOG\"\nexit 0\n",
"gtk-update-icon-cache": "#!/bin/bash\nexit 0\n",
}

# The fake program: `clipsd` re-executes a loop script by its real path, so /proc shows versions/<ver>/...
FAKE_LOOP = r'''#!/bin/bash
HERE="$(cd "$(dirname "$0")" && pwd)"
VER="$(cat "$HERE/VERSION")"
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/clipsd"
mkdir -p "$STATE"; echo $$ > "$STATE/fake.pid"
[ "$(cat "$HERE/behavior" 2>/dev/null)" = nomark ] || touch "$STATE/started-$VER"
while :; do sleep 0.2; done
'''
FAKE_BIN = r'''#!/bin/bash
HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/clipsd"
case "${1:-}" in
  --quit) pf="$STATE/fake.pid"; [ -f "$pf" ] && kill "$(cat "$pf")" 2>/dev/null; rm -f "$pf"; exit 0 ;;
  --make-icons) mkdir -p "$2/48x48/apps"; echo png > "$2/48x48/apps/clipsd.png"; exit 0 ;;
  --region) exit 0 ;;
esac
exec /bin/bash "$HERE/loop.sh"
'''


def make_release(base: Path, ver: str, behavior="ok") -> Path:
    rel = base / f"clipsd-{ver}"
    rel.mkdir(parents=True)
    (rel / "clipsd").write_text(FAKE_BIN)
    (rel / "loop.sh").write_text(FAKE_LOOP)
    (rel / "VERSION").write_text(ver + "\n")
    (rel / "behavior").write_text(behavior + "\n")
    for name in ("clipsd-switch", "install.sh", "uninstall.sh"):
        shutil.copy2(LIN / name, rel / name)
    shutil.copytree(ROOT / "packaging/gnome-extension", rel / "gnome-extension")
    for name in ("clipsd", "loop.sh"):
        (rel / name).chmod(0o755)
    return rel


def snapshot(home: Path):
    """Names, sizes and mtimes of everything ClipSD could write in the real home."""
    paths = [home / ".local/share/clipsd", home / ".local/bin/clipsd", home / ".config/systemd/user/clipsd.service",
             home / ".config/autostart/clipsd.desktop", home / ".local/share/applications/clipsd.desktop",
             home / ".local/state/clipsd", home / ".config/clipshot", home / ".cache/clipsd"]
    paths += list((home / ".local/share/gnome-shell/extensions").glob("clipsd@*"))
    paths += list((home / ".local/share/icons/hicolor").glob("*/apps/clipsd.png"))
    snap = {}
    for p in paths:
        try:
            for q in [p] + (list(p.rglob("*")) if p.is_dir() and not p.is_symlink() else []):
                st = q.lstat()
                snap[str(q)] = (st.st_size, st.st_mtime_ns, os.readlink(q) if q.is_symlink() else "")
        except OSError:
            pass
    return snap


class Sandbox:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.home = tmp / "home"
        self.stubs = tmp / "stubs"
        self.log = tmp / "stub.log"
        self.home.mkdir()
        self.stubs.mkdir()
        self.log.write_text("")
        for name, body in STUBS.items():
            p = self.stubs / name
            p.write_text(body)
            p.chmod(0o755)
        self.environ = {k: v for k, v in os.environ.items() if not k.startswith(("XDG_", "CLIPSD_", "DBUS_"))}
        self.environ.update(HOME=str(self.home), PATH=f"{self.stubs}:/usr/bin:/bin", STUB_DIR=str(self.stubs),
                            STUB_LOG=str(self.log), LANG="C.UTF-8")
        self.app = self.home / ".local/share/clipsd"
        self.state = self.home / ".local/state/clipsd"

    def run(self, *cmd, timeout=90):
        return subprocess.run([str(c) for c in cmd], env=self.environ, cwd=str(self.home), capture_output=True,
                              text=True, timeout=timeout)

    def logtext(self):
        return self.log.read_text()

    def current(self):
        link = self.app / "current"
        return os.readlink(link) if link.is_symlink() else None

    def gs(self, schema, key):
        f = self.stubs / "gs" / f"{schema}__{key}".replace("/", "_").replace(":", "_")
        return f.read_text().strip() if f.exists() else None

    def program_pid(self):
        pf = self.state / "fake.pid"
        try:
            pid = int(pf.read_text())
            os.kill(pid, 0)
            return pid
        except (OSError, ValueError):
            return None

    def program_cmd(self):
        pid = self.program_pid()
        if not pid:
            return ""
        try:
            return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode().strip()
        except OSError:
            return ""

    @staticmethod
    def wait_for(fn, seconds=15):
        end = time.time() + seconds
        while time.time() < end:
            if fn():
                return True
            time.sleep(0.2)
        return fn()


def kill_leftovers(tmp: Path):
    for p in Path("/proc").glob("[0-9]*"):
        try:
            cmd = (p / "cmdline").read_bytes().replace(b"\0", b" ").decode()
            if str(tmp) in cmd and int(p.name) != os.getpid():
                os.kill(int(p.name), signal.SIGKILL)
        except (OSError, ValueError):
            pass


def main():
    real_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    before = snapshot(real_home)
    tmp = Path(tempfile.mkdtemp(prefix="clipsd-linux-"))
    try:
        scenario_systemd(tmp / "a")
        scenario_xdg_autostart_and_purge(tmp / "b")
        scenario_dev_working_copy(tmp / "c")
        scenario_quit_over_socket(tmp / "d")
        scenario_home_through_link(tmp / "e")
        scenario_install_asks_first(tmp / "f")
    finally:
        kill_leftovers(tmp)
        shutil.rmtree(tmp, ignore_errors=True)
    after = snapshot(real_home)
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    check(not changed, f"nothing was written to the real home (key paths unchanged){': ' + ', '.join(changed) if changed else ''}")
    print(f"\n{'FAILED: ' + str(len(failures)) if failures else 'ALL CHECKS PASSED'}")
    return 1 if failures else 0


def scenario_systemd(tmp: Path):
    print("\n== scenario A: 1.x -> 1.30.0 install (systemd), update, rollback, uninstall")
    tmp.mkdir()
    e = Sandbox(tmp)
    rel0 = make_release(tmp / "rel", "1.30.0")
    rel1 = make_release(tmp / "rel", "1.30.1")
    rel2 = make_release(tmp / "rel", "1.30.2", behavior="nomark")
    for rel, ver in ((rel1, "1.30.1"), (rel2, "1.30.2")):   # every release ships its own extension files
        (rel / "gnome-extension" / EXT / f"from-{ver}").write_text(ver)

    # state left by ClipSD 1.x
    h = e.home
    (e.app / "venv/bin").mkdir(parents=True)
    (e.app / "venv/bin/python").write_text("")
    (e.app / "app/clipshot").mkdir(parents=True)
    (h / ".local/bin").mkdir(parents=True)
    (h / ".local/bin/clipsd").write_text("#!/bin/sh\nexit 0\n")
    (h / ".local/bin/clipsd").chmod(0o755)
    (h / ".config/systemd/user").mkdir(parents=True)
    (h / ".config/systemd/user/clipsd.service").write_text("[Service]\nExecStart=/old\n")
    (h / ".config/clipshot").mkdir(parents=True)
    (h / ".config/clipshot/config.json").write_text('{"hotkey_region": "Alt+W"}\n')
    old_ext = h / ".local/share/gnome-shell/extensions/clipsd@old-copy"
    old_ext.mkdir(parents=True)
    (old_ext / "metadata.json").write_text('{"uuid": "clipsd@old-copy", "settings-schema": "org.gnome.shell.extensions.clipsd"}')

    r = e.run("bash", rel0 / "install.sh")
    check(r.returncode == 0, f"install 1.30.0 exits 0 ({r.stderr.strip()[-200:]})")
    check((e.app / "versions/1.30.0/clipsd").is_file(), "versions/1.30.0/clipsd exists")
    check(e.current() == "versions/1.30.0", "current -> versions/1.30.0")
    bin_ = h / ".local/bin/clipsd"
    check(bin_.is_symlink() and bin_.resolve() == (e.app / "versions/1.30.0/clipsd").resolve(),
          "~/.local/bin/clipsd is a link to current/clipsd")
    check(not (e.app / "venv").exists() and not (e.app / "app").exists(), "1.x venv and app removed")
    check((h / ".config/clipshot/config.json").read_text().startswith('{"hotkey_region"'), "1.x settings kept")
    unit = (h / ".config/systemd/user/clipsd.service").read_text()
    check(f"ExecStart={bin_}\n" in unit, "service ExecStart is the constant path ~/.local/bin/clipsd")
    check("systemctl --user enable clipsd.service" in e.logtext() and "restart clipsd.service" in e.logtext(),
          "service enabled and restarted")
    check(not (h / ".config/autostart/clipsd.desktop").exists(), "no XDG autostart next to the service")
    check((e.state / "started-1.30.0").exists(), "start mark started-1.30.0 seen")
    check(not old_ext.exists(), "old extension clipsd@old-copy removed")
    check((h / f".local/share/gnome-shell/extensions/{EXT}/metadata.json").exists(), "new extension installed")
    ens = e.gs("org.gnome.shell", "enabled-extensions") or ""
    check(EXT in ens and "clipsd@old-copy" not in ens and "other@x" in ens, f"enabled-extensions: new on, old off ({ens})")
    kb = e.gs("org.gnome.settings-daemon.plugins.media-keys", "custom-keybindings") or ""
    check("custom-keybindings/clipsd/" in kb, "fallback custom keybinding registered")
    check((e.app / "gnome-screenshot-keys.bak").exists(), "screenshot keys backup saved")
    check((h / ".local/share/icons/hicolor/48x48/apps/clipsd.png").exists(), "icons written")
    check(e.program_pid() is not None, "program is running after install")

    # update 1.30.0 -> 1.30.1: helper detached via systemd-run, program still running (helper stops it)
    shutil.copytree(rel1, e.app / "versions/1.30.1", symlinks=True)
    r = e.run(e.app / "versions/1.30.1/clipsd-switch", "--detach", "--from", "1.30.0", "--to", "1.30.1",
              "--timeout", "15", "--exit-wait", "2")
    check(r.returncode == 0, "switch --detach returns at once")
    check("systemd-run --user --collect" in e.logtext(), "helper started through systemd-run --user --collect")
    run_line = next((ln for ln in e.logtext().splitlines() if ln.startswith("systemd-run")), "")
    check(f"--setenv=HOME={h} " in run_line and f"--setenv=XDG_STATE_HOME={h}/.local/state " in run_line
          and f"--setenv=XDG_DATA_HOME={h}/.local/share " in run_line and "--setenv=XDG_CONFIG_HOME=" in run_line,
          "systemd-run gets HOME and the XDG folders of the caller (P2-8)")
    desk = h / ".local/share/applications/clipsd.desktop"
    desk.write_text("[Desktop Entry]\nExec=/old\n")
    res = e.state / "update-result.json"
    check(e.wait_for(res.exists, 30), "update-result.json written")
    data = json.loads(res.read_text()) if res.exists() else {}
    check(data.get("result") == "ok" and data.get("to") == "1.30.1", f"update result ok ({data})")
    check(data.get("reason") == "started", "reason is a code: started (P2-1)")
    ext_dir = h / f".local/share/gnome-shell/extensions/{EXT}"
    check((ext_dir / "from-1.30.1").exists() and "1.30.1" in (ext_dir / ".clipsd-package").read_text(),
          "after the mark: the package extension comes from the new version (P2-13)")
    check(f"Exec={bin_} --region" in desk.read_text(), "after the mark: the menu entry is written by the new version (P2-13)")
    check(e.current() == "versions/1.30.1", "current -> versions/1.30.1")
    check(not (e.app / "versions/1.30.0").exists(), "old version removed after the mark")
    check((e.state / "started-1.30.1").exists() and not (e.state / "started-1.30.0").exists(), "marks: only the new one")
    check("versions/1.30.1" in e.program_cmd(), "program runs from 1.30.1")
    # the helper writes the result before exit; its lock goes in the EXIT trap a moment later
    e.wait_for(lambda: not (e.state / "update.lock").exists(), 10)
    check(not list(e.app.glob(".current.*")) and not (e.state / "update.lock").exists(), "no leftovers of the helper")

    # failed update: 1.30.2 never writes the mark; no systemd unit -> direct start by setsid
    (h / ".config/systemd/user/clipsd.service").unlink()
    shutil.copytree(rel2, e.app / "versions/1.30.2", symlinks=True)
    t0 = time.time()
    r = e.run(e.app / "versions/1.30.2/clipsd-switch", "--from", "1.30.1", "--to", "1.30.2",
              "--timeout", "3", "--exit-wait", "2")
    check(r.returncode == 3, f"switch to the bad version exits 3 (got {r.returncode}, {time.time() - t0:.0f} s)")
    data = json.loads(res.read_text())
    check(data.get("result") == "rolled_back", f"result rolled_back ({data})")
    check(data.get("reason") == "no_start_mark", "reason is a code: no_start_mark (P2-1)")
    check(not (ext_dir / "from-1.30.2").exists(), "rollback: the extension of the version that did not start is not put in")
    check(e.current() == "versions/1.30.1", "current returned to 1.30.1")
    check((e.app / "versions/1.30.1/clipsd").exists(), "old version kept on rollback")
    check(e.wait_for(lambda: "versions/1.30.1" in e.program_cmd(), 10), "old program is running again")

    # missing target changes nothing
    r = e.run(e.app / "versions/1.30.1/clipsd-switch", "--from", "1.30.1", "--to", "9.9.9", "--timeout", "2")
    check(r.returncode == 2 and e.current() == "versions/1.30.1", "missing target: exit 2, current untouched")
    check(json.loads(res.read_text()).get("reason") == "missing_version", "reason is a code: missing_version")
    r = e.run(e.app / "versions/1.30.1/clipsd-switch", "--from", "../x", "--to", "1")
    check(r.returncode == 2, "bad version string rejected")
    check(json.loads(res.read_text()).get("reason") == "missing_version" and "reason=bad_version" in
          (e.state / "update.log").read_text(), "bad arguments: logged as bad_version, the last result file is kept")

    # uninstall without --purge
    r = e.run("bash", e.app / "current/uninstall.sh")
    check(r.returncode == 0, f"uninstall exits 0 ({r.stderr.strip()[-200:]})")
    check(not e.app.exists() and not bin_.exists() and not bin_.is_symlink(), "program folder and command removed")
    check(not (h / ".config/systemd/user/clipsd.service").exists(), "service file removed")
    check(not (h / ".local/share/applications/clipsd.desktop").exists(), "menu entry removed")
    check(not list((h / ".local/share/icons").rglob("clipsd.png")), "icons removed")
    check(not (h / f".local/share/gnome-shell/extensions/{EXT}").exists(), "extension folder removed")
    ens = e.gs("org.gnome.shell", "enabled-extensions") or ""
    check("clipsd" not in ens and "other@x" in ens, f"extension off in enabled-extensions ({ens})")
    kb = e.gs("org.gnome.settings-daemon.plugins.media-keys", "custom-keybindings") or ""
    check("clipsd" not in kb, "custom keybinding removed")
    check("<Alt>w" in (e.gs("org.gnome.shell.keybindings", "show-screenshot-ui") or ""), "GNOME screenshot Alt+W restored")
    check(not e.state.exists(), "state folder removed")
    check((h / ".config/clipshot/config.json").exists(), "settings kept without --purge")
    check(e.program_pid() is None, "program stopped")
    bad = [ln for ln in e.logtext().splitlines() if "clipshot.service" in ln and
           not any(v in ln for v in ("is-enabled", "is-active"))]
    check(not bad, "the working copy clipshot.service was only looked at, never changed")


def scenario_xdg_autostart_and_purge(tmp: Path):
    print("\n== scenario B: no systemd (XDG autostart), reinstall of the same version, uninstall --purge")
    tmp.mkdir()
    e = Sandbox(tmp)
    (e.stubs / "no_systemd").write_text("")
    rel = make_release(tmp / "rel", "1.30.0")
    h = e.home
    shots = h / "Downloads/Screens"
    shots.mkdir(parents=True)
    mine = ["Screenshot_2026-01-02_03-04-05.png", "Screenshot_2026-01-02_03-04-05_2.png", "Screenshot_2026-01-02_03-04-06.jpg"]
    foreign = ["a.png", "holiday.jpg", "photo.jpeg", "Screenshot_notes.png", "notes.txt"]
    for name in mine + foreign:
        (shots / name).write_text("x")
    (h / ".config/clipsd").mkdir(parents=True)
    (h / ".config/clipsd/config.json").write_text(json.dumps({"auto_save_dir": str(shots)}))
    (h / ".config/clipshot").mkdir(parents=True)     # settings of a working copy: must survive everything
    (h / ".config/clipshot/config.json").write_text(json.dumps({"auto_save_dir": str(shots)}))

    for n in (1, 2):
        r = e.run("bash", rel / "install.sh")
        check(r.returncode == 0, f"install #{n} exits 0 ({r.stderr.strip()[-200:]})")
    auto_file = h / ".config/autostart/clipsd.desktop"
    auto = auto_file.read_text() if auto_file.exists() else ""
    check(f"Exec={h}/.local/bin/clipsd\n" in auto, "autostart points at ~/.local/bin/clipsd")
    check(not (h / ".config/systemd/user/clipsd.service").exists(), "no service file without systemd")
    check(e.wait_for(lambda: e.program_pid() is not None), "program started directly")
    check(sorted(p.name for p in (e.app / "versions").iterdir()) == ["1.30.0"], "reinstall leaves one version folder")
    r = e.run("bash", e.app / "current/uninstall.sh", "--purge")
    check(r.returncode == 0, "uninstall --purge exits 0")
    check(not (h / ".config/clipsd").exists(), "--purge removed the package settings ~/.config/clipsd")
    check((h / ".config/clipshot/config.json").exists(), "--purge never touches ~/.config/clipshot")
    check(not any((shots / n).exists() for n in mine), "--purge removed the screenshots named by ClipSD")
    check(all((shots / n).exists() for n in foreign), "--purge kept foreign png/jpg/jpeg and other files")
    check(shots.exists(), "the screenshot folder with foreign files stays")
    (h / ".config/clipsd").mkdir(parents=True)
    (shots / "Screenshot_2026-01-02_03-04-05.png").write_text("x")
    for n in foreign:
        (shots / n).unlink()
    (h / ".config/clipsd/config.json").write_text(json.dumps({"auto_save_dir": str(shots)}))
    r = e.run("bash", rel / "install.sh")
    r = e.run("bash", e.app / "current/uninstall.sh", "--purge")
    check(r.returncode == 0 and not shots.exists(), "--purge removes the folder when only ClipSD screenshots were in it")
    check(not auto_file.exists() and not e.app.exists(), "autostart and program removed")
    check(e.program_pid() is None, "program stopped")


def scenario_dev_working_copy(tmp: Path):
    print("\n== scenario C: the developer's working copy is on the machine (foreign command, foreign extension)")
    tmp.mkdir()
    e = Sandbox(tmp)
    rel = make_release(tmp / "rel", "1.30.0")
    h = e.home
    wrapper_text = '#!/bin/sh\n# working copy\ntouch "$HOME/dev-wrapper-ran"\nexit 0\n'
    (h / ".local/bin").mkdir(parents=True)
    wrapper = h / ".local/bin/clipsd"
    wrapper.write_text(wrapper_text)
    wrapper.chmod(0o755)
    dev_ext = h / ".local/share/gnome-shell/extensions/clipsd@old-copy"
    dev_ext.mkdir(parents=True)
    (dev_ext / "metadata.json").write_text('{"uuid": "clipsd@old-copy", "settings-schema": "org.gnome.shell.extensions.clipsd"}')
    (h / ".config/clipshot").mkdir(parents=True)
    (h / ".config/clipshot/config.json").write_text("{}")

    r = e.run("bash", rel / "install.sh")
    check(r.returncode != 0 and "Another ClipSD installation" in (r.stdout + r.stderr), f"install.sh refuses ({r.returncode})")
    e.environ["LANG"] = "ru_RU.UTF-8"   # the same refusal in a Russian terminal: in Russian
    r = e.run("bash", rel / "install.sh")
    e.environ["LANG"] = "C.UTF-8"
    check(r.returncode != 0 and "другая установка" in (r.stdout + r.stderr), f"install.sh refuses in Russian ({r.returncode})")
    check(wrapper.read_text() == wrapper_text and not wrapper.is_symlink(), "the working copy command is untouched")
    check(not (h / "dev-wrapper-ran").exists(), "the working copy command was not started (no --quit)")
    check(not e.app.exists() and dev_ext.exists(), "nothing installed, the working copy extension stays")

    # uninstall.sh on this machine must not touch the working copy either
    (e.app / "versions/1.30.0").mkdir(parents=True)
    r = e.run("bash", rel / "uninstall.sh", "--purge")
    check(r.returncode == 0, "uninstall.sh runs")
    check(wrapper.read_text() == wrapper_text and not wrapper.is_symlink(), "uninstall keeps the working copy command")
    check(not (h / "dev-wrapper-ran").exists(), "uninstall did not start the working copy command")
    check((dev_ext / "metadata.json").exists(), "uninstall keeps the extension folder without the package mark")
    check((h / ".config/clipshot/config.json").exists(), "uninstall --purge keeps ~/.config/clipshot")
    check("clipshot.service" not in e.logtext() or not any(
        "clipshot.service" in ln and not any(v in ln for v in ("is-enabled", "is-active")) for ln in e.logtext().splitlines()),
        "clipshot.service never changed")

    # forced install: the old command is saved, the extension of the working copy is still not touched
    r = e.run("bash", rel / "install.sh", "--force-replace-dev")
    check(r.returncode == 0, f"install.sh --force-replace-dev exits 0 ({r.stderr.strip()[-200:]})")
    bak = h / ".local/bin/clipsd.dev-backup"
    check(bak.is_file() and bak.read_text() == wrapper_text, "the working copy command is kept as clipsd.dev-backup")
    check(wrapper.is_symlink() and wrapper.resolve() == (e.app / "versions/1.30.0/clipsd").resolve(), "package command in place")
    check(dev_ext.exists() and not (dev_ext / ".clipsd-package").exists(), "the working copy extension is still untouched")
    # 1.30: the working copy's extension is enabled, so the package does not add a second one fighting it for Alt+W
    check(not (h / f".local/share/gnome-shell/extensions/{EXT}").exists()
          and "keeping it" in (r.stdout + r.stderr), "package extension not added next to the enabled working copy one")
    ens = e.gs("org.gnome.shell", "enabled-extensions") or ""
    check("clipsd@old-copy" in ens and EXT not in ens, f"the working copy extension stays enabled, alone ({ens})")
    r = e.run("bash", e.app / "current/uninstall.sh")
    check(r.returncode == 0 and not (h / f".local/share/gnome-shell/extensions/{EXT}").exists(), "uninstall removes the marked extension")
    check(dev_ext.exists() and bak.exists() and not wrapper.exists(), "uninstall: working copy extension and backup stay, package command goes")


# A program that listens on the ClipSD socket like the real one: the answer comes from the file "mode"
# next to it (busy | ok | hang). "ok" quits, "hang" accepts and never answers (a hung program).
SOCKET_FAKE = r'''
import os, socket, sys, time
here = os.path.dirname(os.path.abspath(__file__))
path = sys.argv[1]
try:
    os.unlink(path)
except OSError:
    pass
srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
srv.bind(path)
srv.listen(4)
held = []
while True:
    conn, _ = srv.accept()
    if not conn.recv(64):        # a probe: connect and close without a command (ClipSD ignores it too)
        conn.close()
        continue
    mode = open(os.path.join(here, "mode")).read().strip()
    with open(os.path.join(here, "asked"), "a") as f:
        f.write(mode + "\n")
    if mode == "hang":
        held.append(conn)
        continue
    conn.sendall((mode + "\n").encode())
    conn.close()
    if mode == "ok":
        time.sleep(0.2)
        sys.exit(0)
'''


def scenario_quit_over_socket(tmp: Path):
    print("\n== scenario D: the helper asks over the socket: busy defers, ok quits, a hung program is stopped")
    tmp.mkdir()
    e = Sandbox(tmp)
    runtime = tmp / "runtime"
    runtime.mkdir(mode=0o700)
    e.environ["XDG_RUNTIME_DIR"] = str(runtime)
    sock = runtime / "clipsd.sock"
    old = e.app / "versions/1.30.0"
    old.mkdir(parents=True)
    (old / "fake.py").write_text(SOCKET_FAKE)
    (old / "clipsd").write_text("#!/bin/bash\nexit 0\n")
    (old / "clipsd").chmod(0o755)
    rel = make_release(tmp / "rel", "1.30.1")
    shutil.copytree(rel, e.app / "versions/1.30.1", symlinks=True)
    (e.app / "current").symlink_to("versions/1.30.0")
    (e.home / ".local/bin").mkdir(parents=True)
    (e.home / ".local/bin/clipsd").symlink_to(e.app / "current/clipsd")
    helper = e.app / "versions/1.30.1/clipsd-switch"

    def start(mode):
        (old / "mode").write_text(mode + "\n")
        p = subprocess.Popen(["python3", str(old / "fake.py"), str(sock)], env=e.environ, cwd=str(e.home),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        check(Sandbox.wait_for(sock.exists, 10), f"fake program ({mode}) listens on the socket")
        return p

    p = start("busy")
    try:
        r = e.run(helper, "--from", "1.30.0", "--to", "1.30.1", "--timeout", "10", "--exit-wait", "2")
        data = json.loads((e.state / "update-result.json").read_text())
        check(r.returncode == 4 and data.get("result") == "deferred", f"busy: exit 4, result deferred ({r.returncode}, {data})")
        check(data.get("reason") == "busy", "reason is a code: busy (P2-1)")
        check(p.poll() is None, "busy: the program is not stopped")
        check(e.current() == "versions/1.30.0" and (e.app / "versions/1.30.1").is_dir(),
              "busy: nothing switched, the new version stays for later")
        check(not (e.state / "update.lock").exists(), "busy: lock released")
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()

    p = start("hang")
    try:
        t0 = time.time()
        r = e.run(helper, "--from", "1.30.0", "--to", "1.30.1", "--timeout", "10", "--exit-wait", "2", timeout=120)
        log = (e.state / "update.log").read_text()
        check(p.wait(timeout=10) is not None and "stopping it" in log,
              f"hung (connects, never answers): stopped only as the last resort ({time.time() - t0:.0f} s)")
        check("quit-for-update: none" in log and "quit-for-update (again): none" in log,
              "hung: asked twice before any force")
        check(r.returncode == 0 and e.current() == "versions/1.30.1", f"hung: then switched (exit {r.returncode})")
    finally:
        if p.poll() is None:
            p.kill()


def exited(proc, seconds) -> bool:
    try:
        proc.wait(timeout=seconds)
        return True
    except subprocess.TimeoutExpired:
        return False


def start_socket_fake(e, folder: Path, sock: Path, mode: str):
    """The socket fake (SOCKET_FAKE) from folder, by its resolved path, in the given mode."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "fake.py").write_text(SOCKET_FAKE)
    (folder / "mode").write_text(mode + "\n")
    if sock.exists():
        sock.unlink()
    p = subprocess.Popen(["python3", str((folder / "fake.py").resolve()), str(sock)], env=e.environ,
                         cwd=str(e.home), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    check(Sandbox.wait_for(sock.exists, 10), f"fake program ({mode}) listens on the socket")
    return p


def scenario_home_through_link(tmp: Path):
    print("\n== scenario E: HOME is a symbolic link; the program runs by the resolved path (P1-1)")
    tmp.mkdir()
    e = Sandbox(tmp)
    real = tmp / "real-home"
    e.home.rename(real)
    e.home.symlink_to(real)
    runtime = tmp / "runtime"
    runtime.mkdir(mode=0o700)
    e.environ["XDG_RUNTIME_DIR"] = str(runtime)
    sock = runtime / "clipsd.sock"
    old = e.app / "versions/1.30.0"
    old.mkdir(parents=True)
    (old / "clipsd").write_text("#!/bin/bash\nexit 0\n")
    (old / "clipsd").chmod(0o755)
    rel = make_release(tmp / "rel", "1.30.1")
    shutil.copytree(rel, e.app / "versions/1.30.1", symlinks=True)
    (e.app / "current").symlink_to("versions/1.30.0")
    (e.home / ".local/bin").mkdir(parents=True)
    (e.home / ".local/bin/clipsd").symlink_to(e.app / "current/clipsd")
    helper = e.app / "versions/1.30.1/clipsd-switch"
    check(str(old.resolve()).startswith(str(real)) and not str(old).startswith(str(real)),
          "the program folder is reached through the link, the process runs by the resolved path")

    p = start_socket_fake(e, old, sock, "busy")
    try:
        r = e.run(helper, "--from", "1.30.0", "--to", "1.30.1", "--timeout", "10", "--exit-wait", "2")
        data = json.loads((e.state / "update-result.json").read_text())
        check(r.returncode == 4 and data.get("result") == "deferred" and data.get("reason") == "busy",
              f"link HOME, busy: asked over the socket, deferred ({r.returncode}, {data})")
        check(p.poll() is None and e.current() == "versions/1.30.0", "link HOME, busy: the program lives, nothing switched")
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()

    p = start_socket_fake(e, old, sock, "hang")
    try:
        r = e.run(helper, "--from", "1.30.0", "--to", "1.30.1", "--timeout", "10",
                  "--exit-wait", "2", timeout=120)
        log = (e.state / "update.log").read_text()
        check(exited(p, 10) and "stopping it" in log,
              "link HOME, hung: the process is found by the resolved path and stopped as the last resort")
        check(r.returncode == 0 and e.current() == "versions/1.30.1", f"link HOME, hung: then switched (exit {r.returncode})")
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
    kill_leftovers(tmp)

    # back to 1.30.0 with a program that says ok: it quits by itself, nobody is killed
    shutil.copytree(rel, e.app / "versions/1.30.0b", symlinks=True)
    (e.app / "versions/1.30.0b/VERSION").write_text("1.30.0b\n")
    os.unlink(e.app / "current")
    (e.app / "current").symlink_to("versions/1.30.1")
    (e.state / "update.log").unlink()
    p = start_socket_fake(e, e.app / "versions/1.30.1", sock, "ok")
    try:
        r = e.run(e.app / "versions/1.30.0b/clipsd-switch", "--from", "1.30.1", "--to", "1.30.0b",
                  "--timeout", "10", "--exit-wait", "5", timeout=120)
        log = (e.state / "update.log").read_text()
        check(r.returncode == 0 and e.current() == "versions/1.30.0b" and exited(p, 5) and p.returncode == 0
              and "stopping it" not in log,
              f"link HOME, ok: the program quit by itself, switched, nobody stopped (exit {r.returncode})")
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()


def scenario_install_asks_first(tmp: Path):
    print("\n== scenario F: install.sh and uninstall.sh ask the program first; uninstall keeps a source run's files")
    tmp.mkdir()
    e = Sandbox(tmp)
    runtime = tmp / "runtime"
    runtime.mkdir(mode=0o700)
    e.environ["XDG_RUNTIME_DIR"] = str(runtime)
    sock = runtime / "clipsd.sock"
    rel0 = make_release(tmp / "rel", "1.30.0")
    rel1 = make_release(tmp / "rel", "1.30.1")
    r = e.run("bash", rel0 / "install.sh")
    check(r.returncode == 0, f"install 1.30.0 exits 0 ({r.stderr.strip()[-200:]})")
    loop_pid = e.wait_for(lambda: e.program_pid() is not None) and e.program_pid()
    fake_dir = tmp / "running-program"
    p = start_socket_fake(e, fake_dir, sock, "busy")
    try:
        r = e.run("bash", rel1 / "install.sh")
        check(r.returncode == 4 and "Close the ClipSD editor" in (r.stdout + r.stderr),
              f"install.sh, program busy: stops with a clear message ({r.returncode})")
        check(p.poll() is None and e.program_pid() == loop_pid, "install.sh, busy: nothing stopped")
        check(e.current() == "versions/1.30.0" and not (e.app / "versions/1.30.1").exists(), "install.sh, busy: nothing copied or switched")
        r = e.run("bash", e.app / "current/uninstall.sh")
        check(r.returncode == 4 and "Close the ClipSD editor" in (r.stdout + r.stderr) and e.app.exists()
              and p.poll() is None and e.program_pid() == loop_pid,
              f"uninstall.sh, program busy: stops with a clear message, nothing removed ({r.returncode})")
        (fake_dir / "mode").write_text("ok\n")
        r = e.run("bash", rel1 / "install.sh")
        check(r.returncode == 0 and exited(p, 10) and p.returncode == 0 and e.current() == "versions/1.30.1",
              f"install.sh, program says ok: it quits by itself, the new version goes in ({r.returncode})")
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()

    # a run from the sources shares ~/.local/state/clipsd and ~/.cache/clipsd: only the package's files go
    (e.state / ".source-run").write_text("")
    (e.state / "clipsd.log").write_text("log of the source run\n")
    fonts = e.home / ".cache/clipsd/fonts"
    fonts.mkdir(parents=True)
    (fonts / "ClipSDSans-Regular.ttf").write_text("x")
    (e.state / "update-result.json").write_text("{}")
    (e.state / "update.log").write_text("x")
    r = e.run("bash", e.app / "current/uninstall.sh")
    check(r.returncode == 0 and not e.app.exists(), f"uninstall exits 0 ({r.stderr.strip()[-200:]})")
    check((e.state / "clipsd.log").exists() and (e.state / ".source-run").exists()
          and (fonts / "ClipSDSans-Regular.ttf").exists(), "uninstall keeps the log and the font cache of a source run (P2-12)")
    check(not list(e.state.glob("started-*")) and not (e.state / "update-result.json").exists()
          and not (e.state / "update.log").exists(), "uninstall removes the package's marks and update files")


if __name__ == "__main__":
    sys.exit(main())
