# ClipSD: entry point of ClipSD-app.exe (PyInstaller). Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
# Shortcuts start the C launcher {app}\ClipSD.exe (launcher/clipsd_launcher.c), which starts this program.
# In the Microsoft Store package (packaging/windows-store) there is no launcher: Windows starts this exe itself.
#
# Internal command (never shown to the user, used by build.ps1 and CI):
#   ClipSD-app.exe --selfcheck REPORT_FILE
#     import everything the program needs, verify an Ed25519 vector through the update channel code,
#     check the bundled certificate store (no network); write the result into REPORT_FILE and exit
#     0 or 1. The last line is "build: release|preview|store"; a Store build adds "package: <full name>|none"
#     and, inside its package, "startup task: <state>".
#   ClipSD-app.exe --selfcheck-startup REPORT_FILE
#     Store package only, for CI: the start at login on and off again (see _selfcheck_startup). The exe is windowed (no console, an uncaught error would open a dialog), so the result goes
#     to a file and every error is caught.
import os
import sys

# Fixed Ed25519 vector made once for this check only (its private key was thrown away). It is NOT a
# channel key: it proves that the bundled cryptography really verifies signatures.
# The same vector is in packaging/linux/clipsd_launcher.py.
SELFCHECK_PUBLIC_KEY = "k4fngxwp5CDPamLYIcG6Xk6bS0/vDom7F5sMU67VFlw="
SELFCHECK_MESSAGE = b"ClipSD selfcheck vector 1: not a channel key"
SELFCHECK_SIGNATURE = "Me1NMy6yxhpEcQ6F2UTNHk5Rkbk/mpFY1pljDDB4Yd2WGMIsW1I4bK7PiShH0wM6Weq3rZrnzG09BY+IiyMFBw=="


def _check_signature():
    import cryptography
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
    """certifi travels inside the build (clipshot/tls.py uses it where the system store is missing)."""
    import certifi
    if not os.path.isfile(certifi.where()):
        raise AssertionError("certifi CA bundle is missing from the build")
    from clipshot import tls
    tls.context()
    return certifi.__version__


def _selfcheck(report_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
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
        kind = build_info.kind()   # preview | store | release
        from clipshot import i18n
        lines = i18n.selfcheck_lines()   # translation catalogs of all 12 languages are inside the build
        if not lines[0].startswith("i18n ok"):
            raise AssertionError("\n".join(lines))
        if kind == "store":   # Microsoft Store: package identity and the start at login (none outside the package)
            from clipshot import store
            lines += store.selfcheck_lines()
        from clipshot import stickers
        problems = stickers.selfcheck()   # 1.36: emoji of the Sticker tool (Twemoji SVG files + QtSvg) are inside the build
        if problems:
            raise AssertionError("\n".join(problems))
        text = (f"ClipSD {clipshot.__version__} selfcheck ok (PyQt6 {PYQT_VERSION_STR}, cryptography {crypto},"
                f" signature ok, certifi {certs})\n" + "\n".join(lines) + f"\nbuild: {kind}\n")   # build.ps1 and the workflows check it
        code = 0
    except BaseException:  # noqa: BLE001 (windowed exe: an uncaught error would open a dialog)
        import traceback
        text = "ClipSD selfcheck FAILED\n" + traceback.format_exc()
        code = 1
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(text)
    return code


def _selfcheck_startup(report_path):
    """Microsoft Store package only (CI, packaging/windows-store/store_test.ps1): turn the start at login on and
    off again through the same code as the settings window (store.set_startup, WinRT StartupTask) and write the
    state after each step into REPORT_FILE. Exit 0 when it was "enabled" after turning on and "disabled" after
    turning off. Ends with the start at login off, as before."""
    lines = []
    code = 1
    try:
        from clipshot import store
        lines.append(f"package: {store.package_full_name() or 'none'}")
        lines.append(f"before: {store.startup_state()}")
        results = {}
        for name, want in (("enable", True), ("disable", False)):
            try:
                results[name] = store.set_startup(want)
            except store.StartupError as exc:
                results[name] = f"refused {exc.state}"
            lines.append(f"{name}: {results[name]}")
        lines.append(f"after: {store.startup_state()}")
        code = 0 if results == {"enable": "enabled", "disable": "disabled"} else 1
    except BaseException:  # noqa: BLE001 (windowed exe)
        import traceback
        lines.append("FAILED\n" + traceback.format_exc())
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return code


def main():
    args = sys.argv[1:]
    if args[:1] == ["--selfcheck"] and len(args) == 2:
        return _selfcheck(args[1])
    if args[:1] == ["--selfcheck-startup"] and len(args) == 2:
        return _selfcheck_startup(args[1])
    from clipshot.app import main as app_main
    return app_main()


if __name__ == "__main__":
    from clipshot.exitutil import quick_exit
    quick_exit(main())
