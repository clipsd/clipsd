# ClipSD: first install of the Linux package. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""install.sh WITHOUT CLIPSD_NO_SYSTEM on a machine where the service does not exist yet:
`systemctl --user stop clipsd.service` returns 5, the install must still finish with exit code 0 (1.31.1 fix).
Also: when an enabled extension of a working copy already holds Alt+W, no second (GNOME custom) Alt+W is created.

Everything runs in a temporary HOME; systemctl, gsettings, gnome-extensions are stubs in PATH.
Run from the project root:   python3 tests/install_firstrun_test.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIN = ROOT / "packaging/linux"
failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


STUBS = {
"systemctl": r'''#!/bin/bash
echo "systemctl $*" >> "$STUB_LOG"
case "$*" in
  *"is-active --quiet graphical-session.target"*) exit 1 ;;   # no systemd session: desktop autostart path
  *"stop clipsd.service"*) exit 5 ;;                          # a service that does not exist yet
  *clipshot.service*) exit 1 ;;
esac
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
        enabled-extensions) cat "$STUB_DIR/enabled" ;;
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
"glib-compile-schemas": "#!/bin/bash\nexit 0\n",
"gnome-extensions": "#!/bin/bash\nexit 0\n",
"gtk-update-icon-cache": "#!/bin/bash\nexit 0\n",
}
FAKE_BIN = r'''#!/bin/bash
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/clipsd"
case "${1:-}" in
  --quit|--region) exit 0 ;;
  --make-icons) mkdir -p "$2/48x48/apps"; echo png > "$2/48x48/apps/clipsd.png"; exit 0 ;;
esac
mkdir -p "$STATE"; touch "$STATE/started-$(cat "$(dirname "$(readlink -f "$0")")/VERSION")"
exit 0
'''


def run_install(tmp: Path, enabled: str, work_copy: bool):
    home, stubs = tmp / "home", tmp / "stubs"
    home.mkdir()
    stubs.mkdir()
    (tmp / "stub.log").write_text("")
    (stubs / "enabled").write_text(enabled + "\n")
    for name, body in STUBS.items():
        (stubs / name).write_text(body)
        (stubs / name).chmod(0o755)
    rel = tmp / "clipsd-1.31.1"
    rel.mkdir()
    (rel / "clipsd").write_text(FAKE_BIN)
    (rel / "clipsd").chmod(0o755)
    (rel / "VERSION").write_text("1.31.1\n")
    shutil.copy2(LIN / "install.sh", rel / "install.sh")
    shutil.copytree(ROOT / "packaging/gnome-extension", rel / "gnome-extension")
    if work_copy:   # extension of a developer's working copy: a real folder, no package mark, same schema, enabled
        ext = home / ".local/share/gnome-shell/extensions/clipsd@work-copy"
        ext.mkdir(parents=True)
        (ext / "metadata.json").write_text('{"uuid": "clipsd@work-copy", "settings-schema": "org.gnome.shell.extensions.clipsd"}')
    env = {k: v for k, v in os.environ.items() if not k.startswith(("XDG_", "CLIPSD_", "DBUS_"))}
    env.update(HOME=str(home), PATH=f"{stubs}:/usr/bin:/bin", STUB_DIR=str(stubs), STUB_LOG=str(tmp / "stub.log"), LANG="C.UTF-8")
    r = subprocess.run(["bash", str(rel / "install.sh")], env=env, cwd=str(home), capture_output=True, text=True, timeout=120)
    gs = lambda k: (stubs / "gs" / f"org.gnome.settings-daemon.plugins.media-keys__{k}").read_text().strip() \
        if (stubs / "gs" / f"org.gnome.settings-daemon.plugins.media-keys__{k}").exists() else None
    return r, home, (tmp / "stub.log").read_text(), gs("custom-keybindings")


with tempfile.TemporaryDirectory(prefix="clipsd-firstrun-") as t:
    tmp = Path(t)
    (tmp / "a").mkdir()
    r, home, log, kb = run_install(tmp / "a", "['other@x']", work_copy=False)
    check("stop clipsd.service" in log, "the stub saw `systemctl --user stop clipsd.service` (returns 5)")
    check(r.returncode == 0, f"first install (no CLIPSD_NO_SYSTEM, stop returns 5) exits 0 ({r.stderr.strip()[-200:]})")
    check((home / ".local/share/clipsd/current").is_symlink() and (home / ".local/bin/clipsd").is_symlink(),
          "the program is really installed (current and ~/.local/bin/clipsd)")
    check(kb is not None and "clipsd/" in kb, f"plain case: the fallback Alt+W (custom keybinding) is created ({kb})")

    (tmp / "b").mkdir()
    r, home, log, kb = run_install(tmp / "b", "['clipsd@work-copy', 'other@x']", work_copy=True)
    check(r.returncode == 0, f"install next to an enabled working-copy extension exits 0 ({r.stderr.strip()[-200:]})")
    check(kb is None or "clipsd/" not in kb, f"the working-copy extension holds Alt+W: no second grab is created ({kb})")

print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено {len(failures)}")
sys.exit(1 if failures else 0)
