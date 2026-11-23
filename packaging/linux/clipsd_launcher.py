# ClipSD: entry point of the self-contained Linux build (PyInstaller). Copyright (C) 2026 Sergey Dayneko
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Same fast path as `python -m clipshot`, plus internal commands used by install.sh.

Internal commands (never shown to the user):
  --make-icons DIR    write hicolor icons clipsd.png into DIR/<size>x<size>/apps
  --build-fonts       build the static "ClipSD Sans" files into the cache
  --selfcheck         import everything the program needs, verify an Ed25519 vector through the update
                      channel code, check the bundled certificate store; exit 0 (build and CI);
                      the last line is "build: release" or "build: preview", "build: localtest" (or "preview-localtest") for a local test build
"""
import os
import sys


def _make_icons(base):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    app = QApplication([])  # noqa: F841 (must stay alive while pixmaps are drawn)
    from clipshot.icons import logo_pixmap
    for size in (16, 22, 24, 32, 48, 64, 128, 256):
        folder = os.path.join(base, f"{size}x{size}", "apps")
        os.makedirs(folder, exist_ok=True)
        logo_pixmap(size).save(os.path.join(folder, "clipsd.png"))
    return 0


# Fixed Ed25519 vector made once for this check only (its private key was thrown away). It is NOT a
# channel key: it proves that the bundled cryptography really verifies signatures.
SELFCHECK_PUBLIC_KEY = "k4fngxwp5CDPamLYIcG6Xk6bS0/vDom7F5sMU67VFlw="
SELFCHECK_MESSAGE = b"ClipSD selfcheck vector 1: not a channel key"
SELFCHECK_SIGNATURE = "Me1NMy6yxhpEcQ6F2UTNHk5Rkbk/mpFY1pljDDB4Yd2WGMIsW1I4bK7PiShH0wM6Weq3rZrnzG09BY+IiyMFBw=="


def _check_signature():
    """The update channel code path (clipshot.update_channel) with the bundled cryptography."""
    import cryptography  # noqa: F401
    from clipshot import update_channel as uc
    uc.verify_signature(SELFCHECK_MESSAGE, SELFCHECK_SIGNATURE, "stable",
                        stable_keys=[SELFCHECK_PUBLIC_KEY], test_keys=[])
    try:
        uc.verify_signature(SELFCHECK_MESSAGE + b"!", SELFCHECK_SIGNATURE, "stable",
                            stable_keys=[SELFCHECK_PUBLIC_KEY], test_keys=[])
    except uc.ChannelError as exc:
        if exc.code != "bad_signature":
            raise
    else:
        raise AssertionError("a changed message passed the signature check")
    return cryptography.__version__


def _check_tls():
    """certifi travels inside the build: the fallback certificate store for https (clipshot/tls.py)."""
    import certifi
    if not os.path.isfile(certifi.where()):
        raise AssertionError("certifi CA bundle is missing from the build")
    from clipshot import tls
    tls.context()
    return certifi.__version__


def _selfcheck():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import fontTools  # noqa: F401
    import Xlib  # noqa: F401
    from PyQt6.QtCore import PYQT_VERSION_STR
    from PyQt6.QtWidgets import QApplication
    app = QApplication([])  # noqa: F841
    import clipshot
    import clipshot.app  # noqa: F401
    import clipshot.editor  # noqa: F401
    import clipshot.updater  # noqa: F401
    crypto = _check_signature()
    certs = _check_tls()
    from clipshot import build_info
    kind = "preview" if build_info.is_preview() else "release"
    if os.path.isfile(os.path.join(os.path.dirname(os.path.realpath(sys.executable)), "LOCALTEST")):
        kind = "localtest" if kind == "release" else kind + "-localtest"   # CLIPSD_ALLOW_NEW_GLIBC=1: never a release
    from clipshot import i18n
    lines = i18n.selfcheck_lines()   # translation catalogs of all 12 languages are inside the build
    if not lines[0].startswith("i18n ok"):
        print("\n".join(lines))
        raise AssertionError(lines[0])
    from clipshot import stickers
    problems = stickers.selfcheck()   # 1.36: emoji of the Sticker tool (Twemoji SVG files + QtSvg) are inside the build
    if problems:
        raise AssertionError("\n".join(problems))
    print("ClipSD", clipshot.__version__, f"selfcheck ok (PyQt6 {PYQT_VERSION_STR}, cryptography {crypto},"
          f" signature ok, certifi {certs})")
    print("\n".join(lines))
    print(f"build: {kind}")   # build_linux.sh and the workflows check it

    return 0


def _resume_cut_switch():
    """A version switch cut by a power loss (clipsd-switch wrote switch-pending, but no helper holds the lock any
    more: the pid written into update.lock is not a running clipsd-switch, e.g. right after a reboot): start
    clipsd-switch --resume, which waits for this version's start mark and otherwise rolls back."""
    import time
    state = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "clipsd")
    pending = os.path.join(state, "switch-pending")
    if not os.path.isfile(pending):
        return
    lock = os.path.join(state, "update.lock")
    if os.path.isdir(lock):
        try:
            with open(os.path.join(lock, "pid"), encoding="ascii") as f:
                pid = int(f.read().strip())
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                if b"clipsd-switch" in f.read():
                    return   # the helper is at work: it waits for the mark itself
        except (OSError, ValueError):
            try:   # a lock without a readable pid: trusted for 10 minutes
                if not os.path.exists(os.path.join(lock, "pid")) and time.time() - os.stat(lock).st_mtime < 600:
                    return
            except OSError:
                pass
    helper = os.path.join(os.path.dirname(os.path.realpath(sys.executable)), "clipsd-switch")
    if os.access(helper, os.X_OK):
        import subprocess
        from clipshot.sysenv import child_env   # without the LD_LIBRARY_PATH of this build (see clipshot/sysenv.py)
        try:
            subprocess.Popen([helper, "--detach", "--resume"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True, env=child_env())
        except OSError:
            pass


def _current_program(executable=None, data_home=None):
    """The program `current` points at, when that is another installed version than the one running this launcher;
    "" otherwise. An update moves `current` while ClipSD is down: Alt+W in that moment (GNOME runs ~/.local/bin/clipsd
    --region) may start the old build, which by now must not come up again, or the update rolls back (Г3 of the race
    review of 1.32.2). Only an installed version (APP/versions/<v>/clipsd) is redirected, never an unpacked archive."""
    if executable is None:
        if not getattr(sys, "frozen", False):
            return ""
        executable = sys.executable
    data = data_home or os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    app = os.path.join(data, "clipsd")
    versions = os.path.realpath(os.path.join(app, "versions"))
    own = os.path.dirname(os.path.realpath(executable))
    if os.path.dirname(own) != versions:
        return ""
    current = os.path.realpath(os.path.join(app, "current"))
    if current == own or os.path.dirname(current) != versions:
        return ""
    target = os.path.join(current, "clipsd")
    return target if os.path.isfile(target) and os.access(target, os.X_OK) else ""


def main():
    args = sys.argv[1:]
    if args[:1] == ["--make-icons"] and len(args) == 2:
        return _make_icons(args[1])
    if args == ["--build-fonts"]:
        from clipshot import fonts
        return 0 if fonts.build() else 1
    if args == ["--selfcheck"]:
        return _selfcheck()
    _resume_cut_switch()
    # Fast path: a running copy takes the command without loading Qt.
    from clipshot.ipc import command_from_args, send
    command = command_from_args(args)
    if command and send(command):
        return 0
    other = _current_program()
    if other:   # the update has switched to another version meanwhile: that one starts, not this one
        from clipshot.sysenv import child_env   # an independent build: without this build's libraries and _PYI_*
        try:
            os.execve(other, [other, *args], child_env())
        except OSError:
            pass   # cannot run it: this version starts, as before
    from clipshot.app import main as app_main
    return app_main()


if __name__ == "__main__":
    from clipshot.exitutil import quick_exit   # as python -m clipshot: no Qt teardown at exit
    quick_exit(main())
