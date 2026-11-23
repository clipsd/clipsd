# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Program updates: schedule, download, install hand-off, result of the previous attempt, windows.

Trust (keys, signature, expiry, rollback) lives in update_channel.py; this module never installs
anything that did not pass update_channel.load_verified().

Schedule (the owner's decisions 02.11.2026 and 03.11.2026): the channel is asked quietly at most once
per 6 h (1.36, owner 23.11.2026; first time 60 s after start when 6 h have passed; also after the computer
wakes, and when the bell is opened if the last request is older than 30 min); an ordinary "version N is available"
window appears at most once per 7 days; "Check for updates" in the tray asks right away. An urgent
security fix ("critical": true, trusted only from the signed document) is offered on the check that
finds it, again 60 s after every start of the program until it is installed, and once a day while
the program keeps running (at most one automatic attempt per day and run, at most one automatic
request to the channel per 6 h); "Later" postpones it, "Skip this version" is not offered for it. While a
security fix is pending, every newer version found is offered the same way (it contains the fix).
The signed document of the pending fix is kept in data_dir()/critical-<channel>.json (+ .sig) and
re-verified each time it is used; a copy that fails the signature check is deleted. Turning
update_check off means no request to the channel at all, except when the person presses "Check for
updates" themselves; a pending security fix is then offered from the verified saved copy.

Wiring into app.py (done by the app.py owner, not here):

    from . import updater
    # in Clipshot._setup_tray(), after the menu is filled and before self.tray.setContextMenu(menu):
    updater.install_menu(menu, self)          # adds "Check for updates" above the last separator
    # in Clipshot.start(), after self._setup_tray():
    updater.start(self)                       # previous attempt result, timers, cleanup

ctx is the Clipshot object: the updater uses ctx.config (dict), ctx.save_config() and, if present,
ctx.notify(text). Config keys and defaults are in CONFIG_DEFAULTS (settings.py may expose
update_check as "Check for updates automatically"; update_channel stays hidden).

Interfaces with other parts:
- Quitting for an update: the program is never killed to be updated. The switch helper (Linux) and
  the launcher (Windows) send "quit-for-update" over the local channel (ipc.py); the program answers
  "ok" and quits, or "busy" when quitting would lose work (Clipshot.quit_blocker(): capture overlay,
  text being typed, an editor with unsaved changes, a modal window). On "busy" the update is
  deferred (note_deferred): the attempt record gets "deferred": true, a notice says the update
  installs when the editor is closed, and the switch is retried as soon as nothing blocks quitting
  (editor closed, checked every 5 s), or at the next start of the program.
- Windows: Setup.exe /SILENT /SUPPRESSMSGBOXES /NORESTART /LANG=<lang> /UPDATE=1; the running
  program is NOT closed here, the launcher (ClipSD.exe --switch) asks it to quit and switches
  {app}\\staging -> {app}\\app, starts the new version and waits up to 60 s for its start mark
  %LOCALAPPDATA%\\ClipSD\\started-<version>; without the mark it returns {app}\\previous and starts
  it. The new version writes the mark as soon as its event loop runs and the tray is set up (and, at the
  latest, on an ordinary quit: "Quit" in the tray, "ok" to quit-for-update), and removes {app}\\previous
  only after that.
- Linux: the tar.gz is unpacked (in a worker thread) to ~/.local/share/clipsd/versions/<version>/;
  if nothing blocks quitting, <versions>/<version>/clipsd-switch --from <old> --to <new> --socket <path>
  is started outside the service group (systemd-run --user --collect with --setenv HOME and the XDG
  folders of this program, otherwise a new session). The
  helper asks the program to quit over the socket, switches ~/.local/share/clipsd/current, starts the
  new version and waits for the mark ${XDG_STATE_HOME:-~/.local/state}/clipsd/started-<version>
  (STARTED_MARK in state_dir()), written at the same moment as on Windows; no mark -> rollback. After
  the mark the helper refreshes the menu entry, icons and the package's GNOME extension from the new
  version (install.sh --refresh-integration). A program run from the sources leaves state_dir()/.source-run,
  so that uninstall.sh keeps the folders it shares with it.
  systemd-run and the helper get sysenv.child_env(): the environment of the person's session, without the
  LD_LIBRARY_PATH of the PyInstaller build (with it systemd-run and the coreutils of Ubuntu 26.04 do not even
  start, 1.31.0 lost its update that way on 19.11.2026). After the start the helper is watched (helper_tick, every
  second): an exit code other than 0/4, a bound failure result, or no helper holding update.lock 60 s later while
  this program still runs -> the failure window at once, not 10 minutes later.
- Failure window (UpdaterUI.failed): "Retry" (no second helper while update.lock is held; the channel is asked
  again and an already downloaded archive with the signed size and sha256 is used instead of a new download) and
  "Send an error report": a window with the report text (versions, platform, step, error code, trace_id and
  attempt_id, the end of the helper's update.log without the home folder and the user name) and "Copy", "Open the
  bug report page" (GitHub issue with title and body in the address), "Write an e-mail". REPORT_ENDPOINT is
  empty in 1.31: when the receiver exists (1.32, ADR-0004) setting it adds "Send" to that window.
- Result files of the helper and the launcher: update-result.json ({from, to, result, reason, time})
  in state_dir() (Linux) or %LOCALAPPDATA%\\ClipSD (Windows); switch_result() uses it only when from,
  to and time belong to the current attempt.
- update-attempt.json in the data folder: {trace_id, attempt_id, from, to, time, platform, channel,
  notes, deferred?, tries?}. Read at start: version == to -> "update_completed" + "What's new"; a
  bound failure result, or still the old version 10 minutes after a not deferred attempt ->
  "update_failed", message, staging removed.
- telemetry_event(name, **fields) only writes to the log: nothing is sent anywhere.
- Preview builds (build_info.PREVIEW, the owner's own tests before the channel exists) use only the
  channel "proba": a local folder proba_dir() with latest.json, latest.json.sig and the package
  files named in it. The same signature, expiry, rollback, size and sha256 checks apply; only the
  source is a file instead of https. Release builds never read a channel or a package from a file.
"""

import getpass
import hashlib
import http.client
import json
import logging
import os
import platform as _platform
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PyQt6.QtCore import QCoreApplication, QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction

from . import __version__
from . import i18n
from . import build_info
from . import sysenv
from . import tls
from . import update_channel as uc
from .update_channel import ChannelError, Manifest
from .i18n import tr

log = logging.getLogger("clipsd.updater")

CHECK_INTERVAL = timedelta(hours=6)      # quiet request to the channel (03.11.2026: a day; 23.11.2026: 6 h, the bell must light up soon)
BELL_CHECK_INTERVAL = timedelta(minutes=30)   # opening the bell: a quiet request if the last one is older than this
WAKE_GAP = timedelta(minutes=5)          # the wake watch: no look at the clock for longer than this = the computer slept
WAKE_POLL_MS = 60_000                    # how often the wake watch looks at the clock
WAKE_DELAY_MS = 20_000                   # after waking: wait for the network before asking the channel
NOTIFY_INTERVAL = timedelta(days=7)      # ordinary update window (02.11.2026)
CRITICAL_REMIND = timedelta(days=1)      # security fix: reminder while the program keeps running
SWITCH_TIMEOUT = timedelta(minutes=10)
STARTUP_DELAY_MS = 60_000
TICK_MS = 3_600_000                 # hourly look at the schedule; the schedule itself is 6 h (CHECK_INTERVAL)
CRITICAL_FILE = "critical-{channel}.json"   # signed document of a pending security fix (+ .sig)
PREVIOUS_CLEANUP_DELAY_MS = 60_000
DEFERRED_POLL_MS = 5_000            # deferred update: how often to look whether quitting is possible
MAX_SWITCH_TRIES = 5                # deferred update: switch attempts before giving up
SWITCH_RELAUNCH_S = 30              # deferred update: no second helper for the same attempt within this time unless
                                    # the first one has answered (Г4 of the race review: two helpers 0.4 s apart)
RESULT_CLOCK_SLACK = timedelta(minutes=2)
NETWORK_TIMEOUT_S = 10
CHUNK = 64 * 1024
STARTED_MARK = "started-{version}"    # file in mark_dir(); clipsd-switch, install.sh and the launcher wait for it
SOURCE_RUN_MARK = ".source-run"       # Linux state_dir(): ClipSD from the sources ran here (uninstall.sh keeps the folder)
REASON_RE = re.compile(r"[a-z0-9_.\-]{1,60}")   # helper / launcher reasons are short codes
SITE_URL = "https://clipsd.github.io/"
HELPER_WATCH_MS = 1_000             # the switch helper is looked at every second after its start
HELPER_ASK_TICKS = 60               # ... and must hold update.lock (or have asked to quit) within 60 s
# Error reports of a failed update. REPORT_ENDPOINT: https address of the receiver (Cloudflare Worker, 1.32,
# ADR-0004); empty = nothing is sent, the report window offers copy, the bug report page and e-mail only.
REPORT_ENDPOINT = ""
ISSUE_URL = "https://github.com/clipsd/clipsd/issues/new"
SUPPORT_EMAIL = "clipsd.app@gmail.com"
ISSUE_URL_LIMIT = 7_000             # whole address of the issue page (GitHub refuses about 8 KB)
MAIL_URL_LIMIT = 1_800              # whole mailto: address (mail programs cut long ones)
REPORT_LOG_LINES = 30               # last lines of the helper's update.log in a report
# TODO(store): product id from Partner Center once the Store listing exists.
STORE_PRODUCT_ID = ""

CONFIG_DEFAULTS = {
    "update_check": True,           # quiet automatic check once per 6 h (1.36)
    "update_channel": "stable",     # not read by a release build (always stable); kept for config compatibility
    "last_update_check": "",        # ISO UTC of the last request to the channel
    "update_last_notified": "",     # ISO UTC of the last "version N is available" window
    "update_skipped": [],           # versions the person chose to skip
    "update_last_seen_version": "",  # highest signed version seen in the stable channel: never below it
    "update_last_seen_version_test": "",  # the same for the test channel (kept apart from stable)
    "update_last_seen_version_proba": "",  # the same for the preview channel (preview builds only)
}
PROBA_ENV = "CLIPSD_PROBA_CHANNEL"   # preview builds: another folder for the proba channel

# Texts of the update windows: keys of clipshot/i18n/<lang>/updater.json, read when shown (tr()).
# The notes of the channel document and Setup.exe /LANG= follow the program language (i18n.current()).


def seen_key(channel: str) -> str:
    return {"test": "update_last_seen_version_test",
            "proba": "update_last_seen_version_proba"}.get(channel, "update_last_seen_version")


# --- small helpers ---------------------------------------------------------

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def cfg(config: dict, key: str):
    value = config.get(key, CONFIG_DEFAULTS[key])
    return CONFIG_DEFAULTS[key] if value is None else value


def _time(text):
    try:
        return uc.parse_utc(text) if text else None
    except ValueError:
        return None


def channel_of(config: dict) -> str:
    """A preview build always uses the proba channel; a release build always the stable one: no setting (also not
    update_channel in config.json) moves a release build to the test or the proba channel."""
    if build_info.is_preview():
        return "proba"
    return "stable"


def platform_name() -> str:
    return "windows" if os.name == "nt" else "linux"


def write_json_atomic(path: Path, data) -> None:
    """Same contract as clipshot.app.write_json_atomic (temp file + fsync + os.replace)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _unlink(path) -> None:
    try:
        Path(path).unlink()
    except OSError:
        pass


def _rmtree(path) -> None:
    if path and Path(path).exists():
        shutil.rmtree(path, ignore_errors=True)


def telemetry_event(name: str, **fields) -> None:
    """Service event of the update: written to the log only. ClipSD 1.x sends nothing anywhere
    (no statistics, no reports); the name stays so that the call sites match 2.0."""
    log.info("update event %s %s", name, " ".join(f"{k}={v}" for k, v in sorted(fields.items())))


# --- schedule (pure, tested with a fake clock) ------------------------------

def should_check(config: dict, now: datetime, manual: bool = False, interval: timedelta = None) -> bool:
    """May the channel be asked now? Manual = the person pressed "Check for updates".
    interval: the shortest gap since the last request (default CHECK_INTERVAL; the bell uses BELL_CHECK_INTERVAL)."""
    if manual:
        return True
    if not cfg(config, "update_check"):
        return False
    last = _time(cfg(config, "last_update_check"))
    if last is None or last > now + uc.CLOCK_TOLERANCE:   # never, or clock moved back a lot
        return True
    return now - last >= (interval or CHECK_INTERVAL)


def should_notify(config: dict, version: str, now: datetime, manual: bool = False,
                  critical: bool = False) -> bool:
    """May the "version N is available" window be shown now? A security fix (critical, from a signed
    document only) is not held back by the 7-day window or by "Skip this version"; how often it
    reappears is the controller's job (each start, once a day while running)."""
    if manual or critical:
        return True
    if version in (cfg(config, "update_skipped") or []):
        return False
    last = _time(cfg(config, "update_last_notified"))
    if last is not None and last <= now + uc.CLOCK_TOLERANCE and now - last < NOTIFY_INTERVAL:
        return False
    return True


def mark_checked(config: dict, now: datetime) -> None:
    config["last_update_check"] = uc.format_utc(now)


def mark_notified(config: dict, now: datetime) -> None:
    config["update_last_notified"] = uc.format_utc(now)


def skip_version(config: dict, version: str) -> None:
    skipped = [v for v in (cfg(config, "update_skipped") or []) if v != version]
    config["update_skipped"] = (skipped + [version])[-20:]


def remember_seen(config: dict, version: str, channel: str = "stable") -> None:
    key = seen_key(channel)
    last = cfg(config, key)
    try:
        if not last or uc.compare_versions(version, last) > 0:
            config[key] = version
    except ValueError:
        config[key] = version


def next_check_delay_ms(config: dict, now: datetime) -> int:
    """Milliseconds until the next automatic check is due (at least the 60 s start delay)."""
    last = _time(cfg(config, "last_update_check"))
    if last is None or last > now + uc.CLOCK_TOLERANCE:
        return STARTUP_DELAY_MS
    due = (last + CHECK_INTERVAL - now).total_seconds() * 1000
    return int(max(STARTUP_DELAY_MS, min(due, TICK_MS)))


def decide(manifest: Manifest, config: dict, installed: str, now: datetime, manual: bool = False,
           critical=None) -> str:
    """What to do with a verified manifest: none | up_to_date | manual_install | notify.
    critical: None = the document's own flag; True when a pending security fix makes it urgent."""
    if critical is None:
        critical = manifest.critical
    if not uc.is_newer(manifest, installed):
        return "up_to_date" if manual else "none"
    if not should_notify(config, manifest.version, now, manual, critical):
        return "none"
    if manifest.min_version and uc.compare_versions(installed, manifest.min_version) < 0:
        return "manual_install"
    return "notify"


# --- where things live -----------------------------------------------------

def data_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local") / "ClipSD"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "clipsd"


def proba_dir() -> Path:
    """Preview builds: the folder of the proba channel. Default: the per-user data folder,
    ~/.local/share/clipsd/proba-channel (Linux), %LOCALAPPDATA%\\ClipSD\\proba-channel (Windows);
    CLIPSD_PROBA_CHANNEL names another one (for example the folder of the test kit)."""
    other = os.environ.get(PROBA_ENV, "").strip()
    return Path(other).expanduser() if other else data_dir() / "proba-channel"


def downloads_dir() -> Path:
    return data_dir() / "updates"


def attempt_path() -> Path:
    return data_dir() / "update-attempt.json"


def critical_path(channel: str) -> Path:
    return data_dir() / CRITICAL_FILE.format(channel=channel)


def state_dir() -> Path:
    """Linux state folder shared with packaging/linux/clipsd-switch: ${XDG_STATE_HOME:-~/.local/state}/clipsd."""
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return Path(base) / "clipsd"


def versions_dir() -> Path:
    return data_dir() / "versions"


FAILURE_PENDING = "update-failure-pending.json"   # in mark_dir(): a failure window not shown yet (Н2 of the review)


def mark_dir() -> Path:
    """Where the start mark and the helper's update-result.json live: Linux state_dir(), Windows
    %LOCALAPPDATA%\\ClipSD (the launcher reads and writes there)."""
    return data_dir() if os.name == "nt" else state_dir()


def is_store_package() -> bool:
    """Windows: the process has an MSIX package identity (installed from Microsoft Store)."""
    try:
        from .store import is_store_build   # optional module of the Store work
        return bool(is_store_build())
    except ImportError:
        pass
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        length = wintypes.UINT(0)
        rc = ctypes.windll.kernel32.GetCurrentPackageFullName(ctypes.byref(length), None)
    except (AttributeError, OSError):
        return False
    return rc in (0, 122)   # 0 / ERROR_INSUFFICIENT_BUFFER: packaged; 15700: APPMODEL_ERROR_NO_PACKAGE


def install_kind() -> str:
    """store | dev | windows | linux | unsupported. Only windows and linux update themselves."""
    if is_store_package():
        return "store"
    if not getattr(sys, "frozen", False):
        return "dev"   # running from sources (a git working copy): update with git
    if os.name == "nt":
        # only the installed layout {app}\\ClipSD.exe + {app}\\app\\ClipSD-app.exe can switch versions
        return "windows" if windows_app_root() is not None else "unsupported"
    if sys.platform.startswith("linux"):
        try:
            Path(sys.executable).resolve().relative_to(versions_dir().resolve())
            return "linux"
        except ValueError:
            return "unsupported"   # a build unpacked by hand outside the versions layout
    return "unsupported"


# --- channel request -------------------------------------------------------

def file_get(path: str, limit: int, timeout: float = 0) -> bytes:
    """Preview channel: read a file of the proba folder with the same size limit as a download."""
    if not build_info.is_preview():
        raise ChannelError("unknown_channel", "local channel files only in a preview build")
    with open(path, "rb") as f:
        data = f.read(limit + 1)
    if len(data) > limit:
        raise ChannelError("bad_document", "too large")
    return data


def channel_source(channel: str) -> str:
    """Where latest.json of a channel is: https address, or the proba folder in a preview build."""
    if channel == "proba":
        if not build_info.is_preview():
            raise ChannelError("unknown_channel", "proba: not a preview build")
        return str(proba_dir() / "latest.json")
    if channel not in uc.CHANNEL_URLS:
        raise ChannelError("unknown_channel", str(channel))
    return uc.CHANNEL_URLS[channel]


class HttpsOnlyRedirect(urllib.request.HTTPRedirectHandler):
    """Redirects are followed only to https (GitHub Releases redirect to another https host)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlparse(newurl).scheme != "https":
            raise urllib.error.URLError("redirect away from https refused")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def https_open(request, timeout: float = NETWORK_TIMEOUT_S):
    """Open an https request; any other scheme, also after a redirect, is refused."""
    url = request.full_url if isinstance(request, urllib.request.Request) else str(request)
    if urllib.parse.urlparse(url).scheme != "https":
        raise urllib.error.URLError("only https addresses")
    opener = urllib.request.build_opener(HttpsOnlyRedirect, urllib.request.HTTPSHandler(context=tls.context()))
    return opener.open(request, timeout=timeout)


def http_get(url: str, limit: int, timeout: float = NETWORK_TIMEOUT_S) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": f"ClipSD/{__version__}",
                                                   "Cache-Control": "no-cache"})
    with https_open(request, timeout=timeout) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ChannelError("bad_document", "too large")
    return data


def fetch_signed(channel: str, config: dict, now: datetime, fetch=None,
                 stable_keys=None, test_keys=None, proba_keys=None):
    """GET latest.json and latest.json.sig, run the full trust chain. Returns (manifest, document,
    signature): the exact bytes are kept for the saved copy of a security fix. Raises ChannelError.
    The proba channel (preview builds only) reads both files from proba_dir()."""
    url = channel_source(channel)
    if fetch is None:
        fetch = file_get if channel == "proba" else http_get
    try:
        document = fetch(url, uc.MAX_DOCUMENT_BYTES)
        signature = fetch(url + uc.SIGNATURE_SUFFIX, 4096)
    except ChannelError:
        raise
    except (OSError, urllib.error.URLError, http.client.HTTPException, ValueError) as exc:
        raise ChannelError("network", type(exc).__name__) from None
    manifest = uc.load_verified(document, signature, channel, now, cfg(config, seen_key(channel)),
                                stable_keys, test_keys, proba_keys)
    return manifest, document, signature


def fetch_manifest(channel: str, config: dict, now: datetime, fetch=None,
                   stable_keys=None, test_keys=None, proba_keys=None) -> Manifest:
    """GET latest.json and latest.json.sig, run the full trust chain. Raises ChannelError."""
    return fetch_signed(channel, config, now, fetch, stable_keys, test_keys, proba_keys)[0]


# --- pending security fix (saved signed copy) ---------------------------------

def write_bytes_atomic(path: Path, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def drop_critical(channel: str) -> None:
    path = critical_path(channel)
    _unlink(path)
    _unlink(str(path) + uc.SIGNATURE_SUFFIX)


def save_critical(channel: str, document: bytes, signature) -> None:
    """Keep the exact signed bytes of a security fix: they are verified again on every use."""
    if isinstance(signature, str):
        signature = signature.encode("ascii", "replace")
    path = critical_path(channel)
    try:
        write_bytes_atomic(Path(str(path) + uc.SIGNATURE_SUFFIX), signature)
        write_bytes_atomic(path, document)
    except OSError as exc:
        log.warning("cannot keep the security fix document: %s", exc)


def pending_critical(channel: str, installed: str, now: datetime, stable_keys=None, test_keys=None,
                     proba_keys=None, fresh: bool = True):
    """The saved security fix that is not installed yet, or None.

    The copy is verified again: signature (a copy that fails it is deleted), structure, "critical": true,
    newer than the installed version (otherwise deleted: the fix is installed). fresh=True also needs
    an unexpired document (it is about to be offered for installation); fresh=False is enough to know
    that newer versions are urgent too."""
    path = critical_path(channel)
    try:
        document = path.read_bytes()
        signature = Path(str(path) + uc.SIGNATURE_SUFFIX).read_bytes()
    except OSError:
        return None
    try:
        uc.verify_signature(document, signature, channel, stable_keys, test_keys, proba_keys)
        manifest = uc.parse_manifest(document, channel)
    except ChannelError as exc:
        log.warning("saved security fix document rejected: %s", exc)
        drop_critical(channel)
        return None
    if not manifest.critical or not uc.is_newer(manifest, installed):
        drop_critical(channel)
        return None
    if fresh:
        try:
            uc.check_expiry(manifest, now)
        except ChannelError:
            return None
    return manifest


# --- download --------------------------------------------------------------

class UpdateError(Exception):
    def __init__(self, code: str, detail: str = "", **fields):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail
        self.fields = fields


def safe_file_name(url: str) -> str:
    name = Path(urllib.parse.urlparse(url).path).name
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name).lstrip(".")
    return name or "update.bin"


def space_needed(size: int, platform: str) -> int:
    # archive + unpacked copy (Linux) or installer + staging copy (Windows), with a margin
    return size * 4 + 50 * 1024 * 1024


def local_source(name: str, local_root) -> Path:
    """Preview channel: the file `name` of the proba folder. Only a plain file name is accepted."""
    if not build_info.is_preview():
        raise UpdateError("bad_url", "local files only in a preview build")
    if not uc.local_name_ok(name):
        raise UpdateError("bad_url", "not a file name of the proba folder")
    return Path(local_root) / name


def verified_file(path: Path, size: int, sha256: str) -> bool:
    """An archive downloaded earlier (a failed attempt kept it for "Retry") with exactly the signed size and sha256."""
    path = Path(path)
    try:
        if not path.is_file() or path.stat().st_size != size:
            return False
        digest = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest() == str(sha256).lower()
    except OSError:
        return False


def clean_downloads(keep=None) -> None:
    """Remove the downloads folder, or everything in it except the file `keep` (and its folder)."""
    root = downloads_dir()
    if keep is None or not Path(keep).is_file():
        _rmtree(root)
        return
    keep = Path(keep)
    for item in list(root.iterdir()) if root.is_dir() else []:
        if item == keep.parent:
            for inner in item.iterdir():
                if inner != keep:
                    _rmtree(inner) if inner.is_dir() else _unlink(inner)
        else:
            _rmtree(item) if item.is_dir() else _unlink(item)


def download_file(url: str, dest: Path, size: int, sha256: str, progress=None, cancel=None,
                  opener=None, timeout: float = NETWORK_TIMEOUT_S, platform: str = "", local_root=None) -> Path:
    """Stream url to dest, checking the exact size and sha256. On any error nothing is left behind.
    local_root (preview builds only): url is a file name in that folder, copied with the same checks.
    Without it only https addresses are fetched (redirects too): http, file: and others are refused."""
    dest = Path(dest)
    if local_root is not None:
        source = local_source(url, local_root)
        open_source = lambda: open(source, "rb")  # noqa: E731
    else:
        if urllib.parse.urlparse(url).scheme != "https":
            raise UpdateError("bad_url", "only https addresses")
        opener = opener or https_open
        request = urllib.request.Request(url, headers={"User-Agent": f"ClipSD/{__version__}"})
        open_source = lambda: opener(request, timeout=timeout)  # noqa: E731
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    need = space_needed(size, platform or platform_name())
    try:
        free = shutil.disk_usage(dest.parent).free
    except OSError:
        free = need
    if free < need:
        raise UpdateError("no_space", need=need)
    digest = hashlib.sha256()
    got = 0
    step = max(size // 100, CHUNK)
    reported = 0
    try:
        with open_source() as response, open(part, "wb") as out:
            while True:
                if cancel is not None and cancel.is_set():
                    raise UpdateError("cancelled")
                chunk = response.read(CHUNK)
                if not chunk:
                    break
                got += len(chunk)
                if got > size:
                    raise UpdateError("size_mismatch", f"more than {size} bytes")
                digest.update(chunk)
                out.write(chunk)
                if progress is not None and (got - reported >= step or got == size):
                    reported = got
                    progress(got, size)
            out.flush()
            os.fsync(out.fileno())
        if got != size:
            raise UpdateError("interrupted", f"{got} of {size} bytes")
        if digest.hexdigest() != sha256.lower():
            raise UpdateError("bad_checksum")
        os.replace(part, dest)
        return dest
    except UpdateError:
        _unlink(part)
        _unlink(dest)
        raise
    except (OSError, urllib.error.URLError, http.client.HTTPException, ValueError) as exc:
        _unlink(part)
        _unlink(dest)
        raise UpdateError("interrupted" if got else "network", type(exc).__name__) from None


# --- update-attempt.json ---------------------------------------------------

def new_id() -> str:
    return uuid.uuid4().hex


def write_attempt(path: Path, from_version: str, to_version: str, now: datetime, trace_id: str = "",
                  channel: str = "stable", notes=None, platform: str = "") -> dict:
    record = {
        "trace_id": trace_id or new_id(),
        "attempt_id": new_id(),
        "from": from_version,
        "to": to_version,
        "time": uc.format_utc(now),
        "platform": platform or platform_name(),
        "channel": channel,
        "notes": notes or {},
    }
    write_json_atomic(path, record)
    return record


def read_attempt(path: Path):
    try:
        record = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def evaluate_attempt(record: dict, current_version: str, now: datetime) -> str:
    """completed | pending | deferred | failed | stale (a record that is not about this version change).
    deferred: the program answered "busy" and the switch waits until it can quit (no 10 min limit)."""
    to_version, from_version = str(record.get("to", "")), str(record.get("from", ""))
    try:
        if to_version and uc.compare_versions(current_version, to_version) == 0:
            return "completed"
        if not from_version or uc.compare_versions(current_version, from_version) != 0:
            return "stale"
    except ValueError:
        return "stale"
    if record.get("deferred"):
        return "deferred"
    started = _time(record.get("time"))
    if started is None or started > now + uc.CLOCK_TOLERANCE or now - started >= SWITCH_TIMEOUT:
        return "failed"
    return "pending"


def attempt_fields(record: dict) -> dict:
    return {"trace_id": record.get("trace_id", ""), "attempt_id": record.get("attempt_id", ""),
            "from_version": record.get("from", ""), "to_version": record.get("to", ""),
            "platform": record.get("platform", ""), "channel": record.get("channel", "")}


def notes_in(notes: dict, lang: str) -> str:
    return Manifest(channel="", version="0", released=utcnow(), expires=utcnow(), files={},
                    notes=notes if isinstance(notes, dict) else {}).notes_for(lang)


# --- installing ------------------------------------------------------------

def windows_command(setup: Path, lang: str) -> list:
    return [str(setup), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/LANG={lang}", "/UPDATE=1"]


def launch_windows_installer(setup: Path, lang: str, popen=subprocess.Popen) -> None:
    """Start Setup.exe detached; this program keeps running (the launcher switches versions)."""
    flags = 0x00000008 | 0x00000200   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    popen(windows_command(setup, lang), creationflags=flags, close_fds=True,
          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def read_switch_result(path=None) -> dict:
    """update-result.json of the launcher (Windows) or clipsd-switch (Linux), {} if none."""
    try:
        data = json.loads(Path(path or mark_dir() / "update-result.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def result_belongs(result: dict, record: dict) -> bool:
    """Is this helper/launcher result about this attempt? Same from and to, written after it started."""
    if not result or not record:
        return False
    try:
        if (uc.compare_versions(str(result.get("from", "")), str(record.get("from", ""))) != 0
                or uc.compare_versions(str(result.get("to", "")), str(record.get("to", ""))) != 0):
            return False
    except ValueError:
        return False
    written, started = _time(result.get("time")), _time(record.get("time"))
    return written is not None and started is not None and written >= started - RESULT_CLOCK_SLACK


def switch_result(record: dict, path=None) -> dict:
    """The result file only when it belongs to the attempt in record, else {}."""
    result = read_switch_result(path)
    return result if result_belongs(result, record) else {}


def windows_app_root():
    """{app} of the installed layout ({app}\\ClipSD.exe and {app}\\app\\ClipSD-app.exe), or None."""
    exe = Path(sys.executable).resolve()
    if exe.parent.name.lower() != "app":
        return None
    root = exe.parent.parent
    return root if (root / "ClipSD.exe").is_file() else None


def launch_windows_switch(root: Path, popen=subprocess.Popen) -> None:
    """Deferred update on Windows: run the launcher with --switch again (it asks this program to quit)."""
    flags = 0x00000008 | 0x00000200   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    popen([str(Path(root) / "ClipSD.exe"), "--switch"], creationflags=flags, close_fds=True, cwd=str(root),
          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def extract_linux_package(archive: Path, versions: Path, version: str) -> Path:
    """Unpack tar.gz into versions/<version>/ (via a temp folder and rename). Returns the folder."""
    uc.parse_version(version)
    versions = Path(versions)
    versions.mkdir(parents=True, exist_ok=True)
    target = versions / version
    current = versions.parent / "current"
    if current.exists() and current.resolve() == target.resolve():
        raise UpdateError("bad_package", "target is the current version")
    tmp = versions / f".{version}.partial-{new_id()[:8]}"
    try:
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(tmp, filter="data")   # rejects absolute paths, "..", unsafe links
        root = tmp
        entries = list(tmp.iterdir())
        if not (tmp / "clipsd-switch").exists() and len(entries) == 1 and entries[0].is_dir():
            root = entries[0]   # archive with one top-level folder
        if not (root / "clipsd-switch").is_file():
            raise UpdateError("bad_package", "no clipsd-switch")
        _rmtree(target)
        os.replace(root, target)
        return target
    except (tarfile.TarError, OSError) as exc:
        raise UpdateError("bad_package", type(exc).__name__) from None
    finally:
        _rmtree(tmp)


def _user_systemd() -> bool:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    return bool(runtime) and (Path(runtime) / "systemd" / "private").exists() and bool(shutil.which("systemd-run"))


PASSED_ENV = ("XDG_RUNTIME_DIR", "DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "XAUTHORITY",
              "XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP", "XDG_SESSION_DESKTOP", "DESKTOP_SESSION", "QT_QPA_PLATFORM",
              "LANG", "LANGUAGE", "LC_ALL", "PATH")


def switch_environment() -> list:
    """(name, value) of the folders this program uses. systemd-run starts the helper in the user
    manager's environment, which may differ (another XDG_DATA_HOME, no XDG_RUNTIME_DIR): passed on."""
    home = os.path.expanduser("~")
    env = [("HOME", home)]
    for name, default in (("XDG_DATA_HOME", ".local/share"), ("XDG_STATE_HOME", ".local/state"),
                          ("XDG_CONFIG_HOME", ".config"), ("XDG_CACHE_HOME", ".cache")):
        env.append((name, os.environ.get(name) or os.path.join(home, default)))
    # what the new version needs to open its windows (the user manager may lack them: XFCE, MATE, Cinnamon)
    for name in PASSED_ENV:
        if os.environ.get(name):
            env.append((name, os.environ[name]))
    return env


def linux_switch_command(version_dir: Path, from_version: str, to_version: str, attempt_id: str,
                         systemd: bool, socket: str = "") -> list:
    helper = [str(Path(version_dir) / "clipsd-switch"), "--from", from_version, "--to", to_version]
    if socket:
        helper += ["--socket", socket]
    if systemd:
        # KillMode=process: the program the helper starts is never stopped together with the helper's unit
        return ["systemd-run", "--user", "--collect", "--quiet", f"--unit=clipsd-update-{attempt_id[:12]}",
                "--property=KillMode=process",
                *[f"--setenv={name}={value}" for name, value in switch_environment()], *helper]
    return helper


_helper_process = None   # the helper started in a new session (not through systemd-run): its exit code is watched


def launch_linux_switch(version_dir: Path, from_version: str, to_version: str, attempt_id: str,
                        run=subprocess.run, popen=subprocess.Popen, systemd=None, socket=None) -> str:
    """Start the switch helper outside this program's service group. Returns the method used.
    The helper asks this program to quit over `socket` (ipc.socket_path() by default).
    Both systemd-run and the helper get sysenv.child_env(): with the LD_LIBRARY_PATH of the PyInstaller build
    systemd-run and the coreutils of newer systems (Ubuntu 26.04) cannot start at all."""
    global _helper_process
    if socket is None:
        from .ipc import socket_path
        socket = socket_path()
    helper = Path(version_dir) / "clipsd-switch"
    try:
        helper.chmod(helper.stat().st_mode | 0o100)
    except OSError:
        pass
    if systemd is None:
        systemd = _user_systemd()
    env = sysenv.child_env()
    _helper_process = None
    if systemd:
        try:
            done = run(linux_switch_command(version_dir, from_version, to_version, attempt_id, True, socket),
                       timeout=15, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, env=env)
            if done.returncode == 0:
                return "systemd-run"
            log.warning("systemd-run for the switch helper failed (%s), starting it in a new session", done.returncode)
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("systemd-run for the switch helper failed (%s), starting it in a new session", exc)
    _helper_process = popen(linux_switch_command(version_dir, from_version, to_version, attempt_id, False, socket),
                            start_new_session=True, close_fds=True, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    return "setsid"


def helper_exit_code():
    """Exit code of the helper started in a new session, None while it runs or when it went through systemd-run.
    Reaping it here also leaves no zombie behind."""
    proc = _helper_process
    poll = getattr(proc, "poll", None)
    if poll is None:
        return None
    try:
        return poll()
    except OSError:
        return None


def switch_lock_alive() -> bool:
    """Linux: a clipsd-switch holds update.lock now (the same rule as the helper and the launcher: the pid written
    into the lock is a running clipsd-switch; a lock without a pid counts for 10 minutes)."""
    lock = state_dir() / "update.lock"
    if not lock.is_dir():
        return False
    try:
        pid = int((lock / "pid").read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        try:
            return not (lock / "pid").exists() and time.time() - lock.stat().st_mtime < 600
        except OSError:
            return False
    try:
        return b"clipsd-switch" in Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return False


def remove_staging(record: dict, kind: str, installed: str = __version__, keep_download: bool = False) -> None:
    """After a failed attempt: remove what the attempt left (never the running version). keep_download: the
    downloaded archive of the attempt stays for "Retry" (it is checked against the signed sha256 before use)."""
    to_version = str(record.get("to", ""))
    if keep_download and to_version and (downloads_dir() / to_version).is_dir():
        for item in list(downloads_dir().iterdir()):
            if item.name != to_version:
                _rmtree(item) if item.is_dir() else _unlink(item)
    else:
        _rmtree(downloads_dir())
    if kind == "linux" and to_version and to_version != installed:
        target = versions_dir() / to_version
        current = data_dir() / "current"
        if not (current.exists() and current.resolve() == target.resolve()):
            _rmtree(target)
    elif kind == "windows":
        root = windows_app_root()
        if root is not None:
            _rmtree(root / "staging")
            _rmtree(root / "failed")   # a version the launcher rolled back from


# --- error report of a failed update ------------------------------------------

def private_bits() -> list:
    """(text, replacement) that must not leave the computer: the home folder (also resolved) and the user name."""
    bits = []
    for home in {os.path.expanduser("~"), os.path.realpath(os.path.expanduser("~"))}:
        if home and home not in ("/", "\\"):
            bits.append((home, "~"))
    try:
        user = getpass.getuser()
    except Exception:   # no user name in the environment or the password database
        user = ""
    if len(user) >= 2:
        bits.append((user, "<user>"))
    return bits


def scrub(text: str, bits=None) -> str:
    """The report text without the home folder and the user name (whole words: "alex" in a path, not in "alexander")."""
    for value, replacement in sorted(bits if bits is not None else private_bits(), key=lambda b: -len(b[0])):
        if replacement == "<user>":
            text = re.sub(r"(?<![A-Za-z0-9_.-])" + re.escape(value) + r"(?![A-Za-z0-9_-])", replacement, text)
        else:
            text = text.replace(value, replacement)
    return text


def os_description() -> str:
    """System name for a report: PRETTY_NAME of /etc/os-release (Linux), platform otherwise."""
    if sys.platform.startswith("linux"):
        try:
            for line in Path("/etc/os-release").read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
        except OSError:
            pass
    return _platform.platform(terse=True)


def helper_log_tail(lines: int = REPORT_LOG_LINES) -> list:
    """Last lines of the helper's update.log (Linux) or the launcher's (Windows), [] if none."""
    for path in (mark_dir() / "update.log", data_dir() / "update.log"):
        try:
            return path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
        except OSError:
            continue
    return []


def failure_report(record: dict, reason: str, stage: str, kind: str = "", installed: str = __version__,
                   now=None, log_lines=None, bits=None) -> str:
    """Plain text of the error report (English: it is read by the developer). Nothing personal: the home folder
    and the user name are replaced, nothing from the settings is included."""
    now = now or utcnow()
    session = " ".join(v for v in (os.environ.get("XDG_CURRENT_DESKTOP", ""), os.environ.get("XDG_SESSION_TYPE", "")) if v)
    lines = [
        "ClipSD update failure report",
        f"From version: {record.get('from', installed)}",
        f"To version: {record.get('to', '')}",
        f"Running version: {installed}",
        f"Platform: {record.get('platform') or platform_name()} ({os_description()}, {_platform.machine()})"
        + (f", session: {session}" if session else ""),
        f"Install kind: {kind or install_kind()}",
        f"Channel: {record.get('channel', '')}",
        f"Step: {stage}",
        f"Error code: {reason}",
        f"Attempt started: {record.get('time', '')}",
        f"Report time: {uc.format_utc(now)}",
        f"trace_id: {record.get('trace_id', '')}",
        f"attempt_id: {record.get('attempt_id', '')}",
    ]
    if record.get("deferred"):
        lines.append(f"Deferred: yes ({record.get('deferred_reason', '')}), tries: {record.get('tries', 0)}")
    result = read_switch_result()
    if result:
        lines.append("Helper result: " + json.dumps(result, ensure_ascii=False, sort_keys=True))
    tail = helper_log_tail() if log_lines is None else list(log_lines)
    lines.append("")
    lines.append(f"Update log (last {len(tail)} lines):" if tail else "Update log: none")
    lines.extend(tail)
    return scrub("\n".join(lines), bits)


def report_title(record: dict, reason: str) -> str:
    return f"Update {record.get('from', '')} -> {record.get('to', '')} failed: {reason}"


def _fit(make, body: str, limit: int) -> str:
    """The longest address make(body) not longer than limit: the end of the body is cut by lines, then by characters."""
    url = make(body)
    marker = "\n[... cut]"
    while len(url) > limit and body:
        cut = body.rfind("\n", 0, max(len(body) - 1, 0))
        body = body[:cut] if cut > len(body) // 2 else body[:int(len(body) * 0.9)]
        url = make(body + marker)
    return url


def issue_url(title: str, body: str, limit: int = ISSUE_URL_LIMIT) -> str:
    """GitHub "new issue" page with the title and the report filled in (body cut to a safe length)."""
    return _fit(lambda b: ISSUE_URL + "?" + urllib.parse.urlencode({"title": title, "body": b},
                                                                     quote_via=urllib.parse.quote), body, limit)


def mail_url(subject: str, body: str, limit: int = MAIL_URL_LIMIT) -> str:
    """mailto: the support address with a subject and the report (cut to what mail programs accept)."""
    def make(b):
        return (f"mailto:{SUPPORT_EMAIL}?subject={urllib.parse.quote(subject, safe='')}"
                f"&body={urllib.parse.quote(b, safe='')}")
    return _fit(make, body, limit)


def send_report(report: str, title: str, endpoint: str = "", opener=None, kind: str = "update_failure") -> bool:
    """POST the report to the receiver (REPORT_ENDPOINT, https only). Only when the person presses "Send" in the
    report window, which shows exactly this text. True when the receiver answered 2xx."""
    endpoint = endpoint or REPORT_ENDPOINT
    if not endpoint or urllib.parse.urlparse(endpoint).scheme != "https":
        return False
    data = json.dumps({"kind": kind, "title": title, "report": report,
                       "version": __version__}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(endpoint, data=data, method="POST",
                                     headers={"Content-Type": "application/json", "User-Agent": f"ClipSD/{__version__}"})
    try:
        with (opener or https_open)(request, timeout=NETWORK_TIMEOUT_S) as response:
            return 200 <= getattr(response, "status", 200) < 300
    except (OSError, urllib.error.URLError, http.client.HTTPException, ValueError):
        return False


# --- windows ---------------------------------------------------------------

# 1.32: окна в стиле окон ClipSD (карточка, значок программы, зелёная главная кнопка) живут в update_windows.py;
# логика показа не менялась, только вид. Имена классов и полей прежние.
from .update_windows import FailedDialog, OfferDialog, ProgressDialog, ReportDialog, WhatsNewDialog  # noqa: E402,F401


CLOSABLE = "clipsd_closable"   # property of a window that holds no work: quitting closes it (app.quit_blocker)


def closable(widget):
    """Mark a message of the updater: it never blocks quitting for an update or the removal of the program."""
    widget.setProperty(CLOSABLE, True)
    return widget


WAIT_KEYS = {   # why the update waits (Clipshot.quit_blocker): a whole sentence per reason, easy to translate
    "unsaved": "updater.wait.unsaved",
    "text": "updater.wait.text",
    "selector": "updater.wait.selector",
    "dialog": "updater.wait.dialog",
    "phone": "updater.wait.phone",
}


def wait_text(reason: str, version: str) -> str:
    """"Version N will be installed when ..." in the program language."""
    return tr(WAIT_KEYS.get(reason, WAIT_KEYS["unsaved"]), version=version)


class UpdaterUI:
    """All visible parts in one place, so tests can replace them with a recorder."""

    def __init__(self):
        self.progress = None

    def offer(self, manifest: Manifest, installed: str, critical: bool = False) -> str:
        dialog = closable(OfferDialog(manifest, installed, critical=critical))   # closed = «Позже»
        dialog.place_centered()
        dialog.exec()
        return dialog.choice

    def manual_install(self, version: str) -> None:
        from .dialogs import MessageCard
        box = closable(MessageCard(None, tr("updater.manual.title", version=version), tr("updater.manual.text", version=version),
                                   "info", primary=tr("updater.button.open_site"), secondary=tr("updater.button.close")))
        box.place_centered()
        box.exec()
        if box.choice == "primary":
            self.open_url(SITE_URL)

    def whats_new(self, version: str, markdown: str) -> None:
        dialog = closable(WhatsNewDialog(version, markdown))
        dialog.place_centered()
        dialog.exec()

    def info(self, text: str) -> None:
        from .dialogs import MessageCard
        box = closable(MessageCard(None, tr("updater.offer.title"), text, "info"))
        box.place_centered()
        box.exec()

    def notice(self, text: str) -> None:
        """Non-modal message: it must not block quitting (a modal window counts as busy)."""
        from .dialogs import MessageCard
        box = MessageCard(None, tr("updater.offer.title"), text, "info", modal=False)
        box.setWindowModality(Qt.WindowModality.NonModal)
        self._notice = box
        box.open_centered()

    def error(self, text: str) -> None:
        from .dialogs import MessageCard
        box = closable(MessageCard(None, tr("updater.error.title"), text, "error"))
        box.place_centered()
        box.exec()

    def failed(self, version: str, report: str, title: str, hint: str = "") -> str:
        """The failure window: returns "retry" or "close"."""
        self.progress_close()
        dialog = closable(FailedDialog(version, report, title, open_url=self.open_url, hint=hint))
        dialog.place_centered()
        self._failed = dialog
        try:
            dialog.exec()
        finally:
            self._failed = None
        return dialog.choice

    def failure_show(self) -> None:
        """The failure window again in front ("Check for updates" pressed while it is open, Н3 of the review)."""
        from PyQt6 import sip
        dialog = getattr(self, "_failed", None)
        if dialog is not None and not sip.isdeleted(dialog):
            dialog.raise_()
            dialog.activateWindow()

    def deferred_notice(self, text: str, on_restart) -> None:
        """Non-modal: the update waits (editor open); "Restart now" tries again at once."""
        from .update_windows import waiting_card
        self.progress_close()
        from PyQt6 import sip
        old = getattr(self, "_notice", None)
        if old is not None and not sip.isdeleted(old):
            old.close()   # never two waiting windows: the new one replaces the old one (a repeated "Restart now")
            old.deleteLater()
        box = closable(waiting_card(text, lambda: QTimer.singleShot(0, on_restart)))
        box.setWindowModality(Qt.WindowModality.NonModal)
        self._notice = box
        box.open_centered()

    def progress_start(self, version: str, on_cancel) -> None:
        self.progress_close()   # never two download windows: a window nobody closes stayed on top until quitting
        self.progress = closable(ProgressDialog(version, on_cancel))
        self.progress.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.progress.open_centered()

    def _progress_window(self):
        """The download window, or None. A window deleted under the updater (closed by the window manager, for
        example) is forgotten: the download goes on and must not touch it (Г2 of the race review)."""
        from PyQt6 import sip
        if self.progress is not None and sip.isdeleted(self.progress):
            self.progress = None
        return self.progress

    def progress_show(self) -> None:
        """The download window again (it was hidden by Esc or its cross; the download goes on)."""
        if self._progress_window() is not None:
            self.progress.open_centered()

    def progress_stage(self, text: str) -> None:
        if self._progress_window() is not None:
            self.progress.set_stage(text)

    def progress_update(self, done: int, total: int) -> None:
        if self._progress_window() is not None:
            self.progress.set_progress(done, total)

    def progress_close(self) -> None:
        if self._progress_window() is not None:
            self.progress.close()
            self.progress.deleteLater()
        self.progress = None

    def open_url(self, url: str) -> None:
        sysenv.open_url(url)


FAILURE_HINTS = {   # reason of a failed switch -> what the person can do (shown under the text of the failure window)
    "cannot_detach": "updater.failed.cannot_detach",   # runs as clipsd.service and systemd-run is not available
}

ERROR_KEYS = {   # error code of the update channel -> text key (clipshot/i18n/<lang>/updater.json)
    "network": "updater.error.check",
    "bad_signature": "updater.error.untrusted",
    "no_keys": "updater.error.untrusted",
    "wrong_channel": "updater.error.untrusted",
    "rollback": "updater.error.rollback",
    "bad_document": "updater.error.untrusted",
    "bad_schema": "updater.error.untrusted",
    "expired": "updater.error.expired",
    "expires_far": "updater.error.expired",   # dated too far ahead: usually the computer's clock
}


def error_text(code: str) -> str:
    """Text of a failed check in the program language (unknown code: "could not check")."""
    return tr(ERROR_KEYS.get(code, "updater.error.check"))
INFO_CODES = ("rollback",)   # not a fault: shown as information


# --- controller ------------------------------------------------------------

class Updater(QObject):
    """Glue between the schedule, the channel, downloads, installers and the windows."""

    _checked = pyqtSignal(object, object, bool)       # manifest, ChannelError, manual
    _progress = pyqtSignal(int, int)
    _downloaded = pyqtSignal(object, object, object)   # path, UpdateError, number of the download
    _extracted = pyqtSignal(object, object, object)    # folder, UpdateError, number (Linux, worker thread)

    def __init__(self, ctx, *, fetch=None, opener=None, clock=utcnow, kind=None, installed=None,
                 stable_keys=None, test_keys=None, proba_keys=None, ui=None, sync=False):
        super().__init__()
        self.ctx = ctx
        self.fetch = fetch
        self.opener = opener
        self.clock = clock
        self.kind = kind or install_kind()
        self.installed = installed or __version__
        self.stable_keys = stable_keys
        self.test_keys = test_keys
        self.proba_keys = proba_keys
        self.ui = ui or UpdaterUI()
        self.sync = sync               # tests: run network work inline instead of a thread
        self.busy = False
        self.cancel = threading.Event()
        self.timer = None
        self._pending = None           # (manifest, trace_id) while downloading
        self._installing = None        # (record, manifest) while the Linux package is unpacked
        self._work_no = 0              # number of the current download / unpack: a late result of another is ignored
        self._switch_started = None    # (attempt_id, time.monotonic()) of the last switch this program started
        self._quiet_queue = []         # windows waiting for a quiet minute (failure, What's new; _show_when_quiet)
        self._failures_waiting = set()  # attempt ids whose failure window waits in that queue
        self._quiet_timer = None
        self._quiet_since = None
        self._deferred_soon = None     # one timer for "an editor was closed" (Clipshot._editor_closed)
        self._failure_open = False     # the failure window is on the screen (Retry / Close)
        self._wake_seen = None         # clock at the last look of the wake watch (wake_tick)
        self._checking = False         # a request to the channel is running
        self._checking_manual = False  # "Check for updates" was pressed during a silent check: its result as a window
        self._deferred_timer = None
        self._helper_timer = None       # watch of the Linux switch helper right after its start
        self._helper_attempt = ""
        self._helper_ticks = 0
        self._auto_update = False       # "Retry" of the failure window: install the found version without the offer
        self._mark_written = False
        self._critical_offered_at = None   # last security fix window of this run (None: not yet)
        self._critical_tried_at = None     # last automatic attempt to remind of it (window or not)
        self._checked.connect(self._on_checked)
        self._progress.connect(lambda done, total: self.ui.progress_update(done, total))
        self._downloaded.connect(self._on_downloaded)
        self._extracted.connect(self._on_extracted)

    # config ----------------------------------------------------------------
    @property
    def config(self) -> dict:
        return self.ctx.config

    def _save(self):
        save = getattr(self.ctx, "save_config", None)
        if save is not None:
            save()

    def _notify(self, text):
        notify = getattr(self.ctx, "notify", None)
        if notify is not None:
            notify(text)

    def _run(self, fn):
        if self.sync:
            fn()
        else:
            threading.Thread(target=fn, name="clipsd-updater", daemon=True).start()

    # checking --------------------------------------------------------------
    def tick(self):
        """Timer: a pending security fix first (each start, then once a day), else the 6 h check."""
        if self.kind not in ("windows", "linux") or self.busy:
            return
        now = self.clock()
        if self._critical_attempt_due(now) and self._pending_critical(now, fresh=False) is not None:
            # the attempt is remembered, shown or not: an expired copy with no network must not
            # turn into a request every hour (review R04b P1-2)
            self._critical_tried_at = now
            if cfg(self.config, "update_check") and should_check(self.config, now):
                self.check_now(manual=False)        # the 6 h request is due: newest document, then the offer
            else:
                self._offer_saved_critical(now)     # no request: the verified saved copy
            return
        if should_check(self.config, now):
            self.check_now(manual=False)

    def _channel_keys(self) -> dict:
        return {"stable_keys": self.stable_keys, "test_keys": self.test_keys, "proba_keys": self.proba_keys}

    def _pending_critical(self, now, fresh=True):
        return pending_critical(channel_of(self.config), self.installed, now, fresh=fresh, **self._channel_keys())

    def _critical_due(self, now) -> bool:
        """May a security fix window be shown automatically now? Once per start, then once a day."""
        last = self._critical_offered_at
        return last is None or last > now + uc.CLOCK_TOLERANCE or now - last >= CRITICAL_REMIND

    def _critical_attempt_due(self, now) -> bool:
        """Has a day passed since the last automatic attempt to remind (None: not yet in this run)?"""
        last = self._critical_tried_at
        return last is None or last > now + uc.CLOCK_TOLERANCE or now - last >= CRITICAL_REMIND

    def _offer_saved_critical(self, now) -> bool:
        """Offer the saved security fix (verified again, unexpired). True when the window was shown."""
        if self.busy or not self._critical_due(now):
            return False
        manifest = self._pending_critical(now, fresh=True)
        if manifest is None:
            return False
        self.busy = True
        self._present(manifest, "notify", True, now)
        return True

    def check_now(self, manual: bool = True, auto: bool = False, interval: timedelta = None) -> bool:
        """Returns True when a request to the channel was started. auto ("Retry" after a failure): a newer
        version found is installed at once, without the "version N is available" window."""
        if self.kind == "store":
            if manual:
                self.ui.open_url(f"ms-windows-store://pdp/?productid={STORE_PRODUCT_ID}"
                                 if STORE_PRODUCT_ID else SITE_URL)
            return False
        if self.kind not in ("windows", "linux"):
            if manual:
                self.ui.info(tr("updater.disabled.dev" if self.kind == "dev" else "updater.disabled.unsupported"))
            return False
        if self.busy:
            if manual:
                waiting = self._deferred_version()
                if self._checking:
                    # the silent check (60 s after start, once a day) is running right now: the press joins it and its
                    # result comes as a window, as after any press (Г12 of the race review: nothing was shown at all)
                    self._checking_manual = True
                elif waiting:
                    reason = str((read_attempt(attempt_path()) or {}).get("deferred_reason", ""))
                    self.ui.info(wait_text(reason, waiting))
                elif self._pending is not None or self._installing is not None:
                    show = getattr(self.ui, "progress_show", None)   # the download goes on: its window again
                    if show is not None:
                        show()
                elif self._failure_open:
                    show = getattr(self.ui, "failure_show", None)    # the failure window (Retry) is the answer
                    if show is not None:
                        show()
            return False
        now = self.clock()
        if not should_check(self.config, now, manual, interval):
            return False
        self.busy = True
        self._checking = True
        self._checking_manual = False
        self._auto_update = auto
        mark_checked(self.config, now)
        self._save()
        channel = channel_of(self.config)
        config_copy = dict(self.config)

        def work():
            try:
                signed = fetch_signed(channel, config_copy, now, self.fetch, **self._channel_keys())
                self._checked.emit(signed, None, manual)
            except ChannelError as exc:
                self._checked.emit(None, exc, manual)
            except Exception as exc:   # never let a bug in the check kill the program
                log.exception("update check crashed")
                self._checked.emit(None, ChannelError("internal", type(exc).__name__), manual)

        self._run(work)
        return True

    def _on_checked(self, signed, error, manual):
        manual = manual or self._checking_manual
        self._checking = self._checking_manual = False
        now = self.clock()
        channel = channel_of(self.config)
        if error is not None:
            self.busy = False
            self._auto_update = False
            log.warning("update check failed: %s", error)
            telemetry_event("update_check_failed", reason=error.code, channel=channel)
            if manual:
                text = error_text(error.code)
                (self.ui.info if error.code in INFO_CODES else self.ui.error)(text)
            else:
                self._offer_saved_critical(now)   # offline: a pending security fix from the saved copy
            return
        manifest, document, signature = signed
        remember_seen(self.config, manifest.version, channel)
        self._refresh_bell()   # 1.36: the dot lights up as soon as the channel showed the version, whatever the window rules say
        # "critical" comes only from this verified document or from the verified saved copy
        pending = self._pending_critical(now, fresh=False)
        if manifest.critical and uc.is_newer(manifest, self.installed) and (
                pending is None or uc.compare_versions(manifest.version, pending.version) >= 0):
            save_critical(channel, document, signature)
            pending = manifest
        critical = manifest.critical or (
            pending is not None and uc.compare_versions(manifest.version, pending.version) >= 0)
        from . import update_prompt   # 1.32: обычное обновление сначала в колокольчике, окно позже (update_prompt)
        if update_prompt.hold(self, manifest, now, manual, critical):
            self.busy = False
            self._save()
            return
        action = decide(manifest, self.config, self.installed, now, manual, critical)
        if action == "notify" and critical and not manual and not self._critical_due(now):
            action = "none"   # already shown in this run less than a day ago
        self._save()
        self._present(manifest, action, critical, now)

    @staticmethod
    def _refresh_bell() -> None:
        try:
            from . import notifications
            notifications.refresh()
        except Exception:   # noqa: BLE001 — the bell must never break the update
            log.exception("bell refresh failed")

    def bell_check(self) -> bool:
        """The bell was opened (editor, tray): a quiet request when the last one is older than BELL_CHECK_INTERVAL.
        The answer refreshes the bell (_on_checked). True when a request was started."""
        if self.kind not in ("windows", "linux") or self.busy:
            return False
        return self.check_now(manual=False, interval=BELL_CHECK_INTERVAL)

    def wake_tick(self) -> bool:
        """Timer (WAKE_POLL_MS): the clock jumped forward by more than WAKE_GAP since the last look = the computer
        slept (Qt has no wake signal). Then, if CHECK_INTERVAL has passed, a quiet request after WAKE_DELAY_MS
        (the network needs time). True when a wake was seen."""
        now = self.clock()
        last, self._wake_seen = self._wake_seen, now
        if last is None or now - last <= WAKE_GAP:
            return False
        if self.kind in ("windows", "linux") and should_check(self.config, now):
            QTimer.singleShot(WAKE_DELAY_MS, self.tick)
        return True

    def _present(self, manifest: Manifest, action: str, critical: bool, now) -> None:
        auto, self._auto_update = self._auto_update, False
        if action == "none":
            self.busy = False
            return
        if action == "up_to_date":
            self.busy = False
            self.ui.info(tr("updater.up_to_date", version=self.installed))
            return
        mark_notified(self.config, now)
        if critical:
            self._critical_offered_at = now
            self._critical_recall = False   # окно показано сейчас, любой ответ человека закрывает вопрос (П4 проверки 1.32.1);
                                            # Alt+W во время окна взведёт повтор заново (clear_way_for_capture)
        self._save()
        if action == "manual_install":
            self.busy = False
            self.ui.manual_install(manifest.version)
            return
        choice = "update" if auto else self.ui.offer(manifest, self.installed, critical=critical)
        if choice == "skip" and critical:
            choice = "later"   # a security fix is never skipped, only postponed
        if not critical:
            from . import update_prompt
            update_prompt.after_offer(self, manifest.version, choice, now)   # «Позже»: ещё 3 дня или 20 снимков
        if choice == "skip":
            skip_version(self.config, manifest.version)
            self._save()
        if choice != "update":
            self.busy = False
            return
        if not auto:
            asked = getattr(self.ctx, "restart_requested", None)
            if asked is not None:
                asked()   # 1.36.1: «Обновить» нажал человек: окна без работы не держат смену версии (app.release_for_restart)
        self.start_download(manifest)

    # downloading -----------------------------------------------------------
    def start_download(self, manifest: Manifest, trace_id: str = ""):
        platform = "windows" if self.kind == "windows" else "linux"
        entry = manifest.file_for(platform)
        if entry is None:
            self.busy = False
            self.ui.error(tr("updater.error.no_package", version=manifest.version))
            return
        trace_id = trace_id or new_id()
        self._pending = (manifest, trace_id)
        self._work_no += 1
        number = self._work_no
        self.cancel.clear()
        dest = downloads_dir() / manifest.version / safe_file_name(entry["url"])
        clean_downloads(keep=dest)   # an archive kept from a failed attempt is checked below, all else goes
        local_root = proba_dir() if manifest.channel == "proba" else None   # preview builds only
        self.ui.progress_start(manifest.version, self.cancel.set)

        def work():
            try:
                if verified_file(dest, entry["size"], entry["sha256"]):
                    log.info("update %s: the archive downloaded before has the signed sha256, used again",
                             manifest.version)
                    self._downloaded.emit(dest, None, number)
                    return
                path = download_file(entry["url"], dest, entry["size"], entry["sha256"],
                                     progress=self._progress.emit, cancel=self.cancel,
                                     opener=self.opener, platform=platform, local_root=local_root)
                self._downloaded.emit(path, None, number)
            except UpdateError as exc:
                self._downloaded.emit(None, exc, number)
            except Exception as exc:
                log.exception("update download crashed")
                self._downloaded.emit(None, UpdateError("internal", type(exc).__name__), number)

        self._run(work)

    def _on_downloaded(self, path, error, number=None):
        if self._pending is None or (number is not None and number != self._work_no):
            # a result of another download (Г5 of the race review: two downloads into one file): not ours
            log.warning("update download result of another attempt ignored")
            return
        manifest, trace_id = self._pending
        if error is None and hasattr(self.ui, "progress_stage"):
            # the same window stays and says what happens now, until ClipSD restarts or a message replaces it
            self.ui.progress_stage(tr("updater.install.started", version=manifest.version))
        else:
            self.ui.progress_close()
        if error is not None:
            self.busy = False
            self._pending = None
            _rmtree(downloads_dir())
            log.warning("update download failed: %s", error)
            if error.code == "cancelled":
                return
            telemetry_event("update_failed", reason=error.code, stage="download", trace_id=trace_id,
                            from_version=self.installed, to_version=manifest.version)
            if error.code == "bad_checksum" or error.code == "size_mismatch":
                self.ui.error(tr("updater.error.checksum"))
            elif error.code == "no_space":
                self.ui.error(tr("updater.error.no_space", need=str(error.fields.get("need", 0) // (1024 * 1024))))
            else:
                self.ui.error(tr("updater.error.download"))
            return
        self.install(path, manifest, trace_id)

    # installing ------------------------------------------------------------
    CLIPBOARD_POLL_MS = DEFERRED_POLL_MS

    def install(self, path: Path, manifest: Manifest, trace_id: str):
        if self._clipboard_busy():
            # "Update" was pressed and the download is done, but the person has just copied a snapshot or text while
            # it ran ("You can keep working"): the restart would empty the clipboard (Windows always, X11 without a
            # clipboard manager). Wait as the deferred update does, at most Clipshot.CLIPBOARD_HOLD_S after the copy
            # (Н6 of the review of 1.32.3). The download window keeps saying "Installing".
            log.info("update %s: waiting for the clipboard (a snapshot was just copied)", manifest.version)
            QTimer.singleShot(self.CLIPBOARD_POLL_MS, lambda: self.install(path, manifest, trace_id))
            return
        if self.kind == "linux" and switch_lock_alive():
            # a switch helper is at work (an earlier attempt): never a second one, never unpack under it
            self.ui.progress_close()
            self.busy = False
            self._pending = None
            self.ui.info(tr("updater.retry.busy"))
            return
        record = write_attempt(attempt_path(), self.installed, manifest.version, self.clock(), trace_id,
                               channel_of(self.config), manifest.notes)
        telemetry_event("update_started", **attempt_fields(record))
        if self.kind == "windows":
            try:
                launch_windows_installer(path, i18n.current())
            except (OSError, ValueError) as exc:
                self._install_failed(record, exc)
                return
            self._install_started(record, manifest)
            return
        # Linux: up to 90 MB of tar.gz, unpacked off the interface thread
        self._installing = (record, manifest)
        self._work_no += 1
        number = self._work_no

        def work():
            try:
                self._extracted.emit(extract_linux_package(path, versions_dir(), manifest.version), None, number)
            except (UpdateError, OSError, ValueError) as exc:
                self._extracted.emit(None, exc, number)
            except Exception as exc:
                log.exception("update unpack crashed")
                self._extracted.emit(None, UpdateError("internal", type(exc).__name__), number)

        self._run(work)

    def _on_extracted(self, folder, error, number=None):
        if self._installing is None or (number is not None and number != self._work_no):
            log.warning("update unpack result of another attempt ignored")
            return
        record, manifest = self._installing
        self._installing = None
        if error is not None:
            self._install_failed(record, error)
            return
        blocker = self._quit_blocker()
        if blocker and self._release_blockers("install"):
            blocker = self._quit_blocker()
        if blocker:
            # quitting now would lose work: keep versions/<new>, switch when the editor is closed
            self._defer(record, blocker)
            return
        try:
            method = self._launch_switch(folder, self.installed, manifest.version, record["attempt_id"])
        except (OSError, ValueError) as exc:
            self._install_failed(record, exc)
            return
        log.info("switch helper started (%s); it asks the program to quit over the local socket", method)
        self._install_started(record, manifest)
        self._watch_helper(record)

    @staticmethod
    def _launch_switch(folder, from_version: str, to_version: str, attempt_id: str) -> str:
        """Start the Linux helper. The result file of an earlier try goes first: it has the same from and to and may be
        written less than RESULT_CLOCK_SLACK before this attempt, so it would pass for this attempt's result and the
        watch would report a failure while the new helper is only starting (review of 1.31.2, П2)."""
        _unlink(mark_dir() / "update-result.json")
        return launch_linux_switch(folder, from_version, to_version, attempt_id)

    def _install_failed(self, record: dict, exc) -> None:
        code = str(getattr(exc, "code", type(exc).__name__))
        log.warning("update install could not start: %s", exc)
        telemetry_event("update_failed", reason=code, stage="install", **attempt_fields(record))
        remove_staging(record, self.kind, self.installed, keep_download=True)
        _unlink(attempt_path())
        self.busy = False
        self._pending = None
        self._show_failure(record, code if REASON_RE.fullmatch(code) else "unknown", "install", "updater.error.install")

    def _show_failure(self, record: dict, reason: str, stage: str, fallback_key: str = "updater.error.failed") -> None:
        """The failure window (Retry / Send an error report / Close); a UI without it (tests) gets the old message."""
        version = str(record.get("to", ""))
        failed = getattr(self.ui, "failed", None)
        if failed is None:
            self.ui.progress_close()
            self.ui.error(tr(fallback_key, version=version))
            return
        report = failure_report(record, reason, stage, self.kind, self.installed, self.clock())
        hint = tr(FAILURE_HINTS[reason]) if reason in FAILURE_HINTS else ""
        close = getattr(self.ui, "progress_close", None)
        if close is not None:
            close()   # «Устанавливается…» must not stay on the screen while the failure waits for a quiet minute
        attempt = str(record.get("attempt_id", ""))
        if attempt and attempt in self._failures_waiting:
            return    # this failure already waits for a quiet minute
        if not self._show_when_quiet(lambda: self._failure_window(record, version, report, reason, hint)):
            # waits: kept on disk until shown, so that quitting before the quiet minute does not lose it (the attempt
            # record is already removed); the next start shows it (_show_saved_failure; Н2 of the review of 1.32.3)
            self._failures_waiting.add(attempt)
            try:
                write_json_atomic(mark_dir() / FAILURE_PENDING, {"record": record, "reason": reason, "stage": stage})
            except OSError as exc:
                log.warning("cannot keep the failure for the next start: %s", exc)

    def _show_saved_failure(self) -> bool:
        """At start: a failure window that waited for a quiet minute when the program quit. True when it was shown
        or queued again. Dropped when this program is already the version of that attempt (or newer)."""
        path = mark_dir() / FAILURE_PENDING
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            record, reason, stage = dict(saved["record"]), str(saved["reason"]), str(saved["stage"])
            stale = uc.compare_versions(self.installed, str(record.get("to", ""))) >= 0
        except (OSError, ValueError, KeyError, TypeError):
            return False
        if stale or not REASON_RE.fullmatch(reason):
            _unlink(path)
            return False
        self._show_failure(record, reason, stage)
        return True

    def _failure_window(self, record: dict, version: str, report: str, reason: str, hint: str) -> None:
        self._failures_waiting.discard(str(record.get("attempt_id", "")))
        _unlink(mark_dir() / FAILURE_PENDING)
        failed = self.ui.failed
        # While the window is open the updater is busy: a timer must not offer a version on top of it and start a
        # download that "Retry" below would start a second time (Г5 of the race review).
        self.busy = True
        self._failure_open = True
        try:
            choice = failed(version, report, report_title(record, reason), hint=hint)
        finally:
            self._failure_open = False
            if self._pending is None and self._installing is None:
                self.busy = False
        if choice == "retry":
            self.retry_update(record)

    def retry_update(self, record: dict) -> bool:
        """"Retry" of the failure window. Never a second switch helper (update.lock held by a living one: the
        person is told to wait). Otherwise the channel is asked again (signed document, the same checks) and the
        version found is installed at once; the archive kept from the failed attempt is used again when it has the
        signed size and sha256, else it is downloaded. Returns True when the request to the channel started."""
        if self.kind == "linux" and switch_lock_alive():
            self.ui.info(tr("updater.retry.busy"))
            return False
        if self._pending is not None or self._installing is not None:
            # the version is being downloaded or unpacked right now (offered again while the failure window was
            # open): never a second download into the same file, show the one that runs (Г5 of the race review)
            show = getattr(self.ui, "progress_show", None)
            if show is not None:
                show()
            return False
        self.busy = False
        telemetry_event("update_retry", **attempt_fields(record))
        return self.check_now(manual=True, auto=True)

    def _install_started(self, record: dict, manifest: Manifest) -> None:
        self._pending = None
        self._notify(tr("updater.install.started", version=manifest.version))
        delay = int(SWITCH_TIMEOUT.total_seconds() * 1000) + 5000
        QTimer.singleShot(delay, self.check_previous_attempt)

    # windows that come by a timer -------------------------------------------
    QUIET_POLL_MS = 5_000

    def _show_when_quiet(self, show) -> bool:
        """The failure window and What's new come by a timer (start, the watch of the helper), not as an answer to
        the person: never over the selection overlay or an editor (Г8 of the race review: a modal window over the
        overlay, which holds the keyboard, froze the selection). Now when nothing is open, otherwise after a quiet
        minute (update_prompt.QUIET), like the offer of a version and the rating window. True: shown now."""
        from . import update_prompt
        if not self._quiet_queue and not update_prompt.busy_reason(self.ctx):
            show()
            return True
        self._quiet_queue.append(show)
        if self._quiet_timer is None:
            self._quiet_timer = QTimer(self)
            self._quiet_timer.setInterval(self.QUIET_POLL_MS)
            self._quiet_timer.timeout.connect(self.quiet_poll)
        if not self._quiet_timer.isActive():
            self._quiet_since = None
            self._quiet_timer.start()
        return False

    def quiet_poll(self) -> bool:
        """Timer of _show_when_quiet. True when the waiting windows were shown."""
        from . import update_prompt
        if not self._quiet_queue:
            self._quiet_timer.stop()
            return False
        now = self.clock()
        if update_prompt.busy_reason(self.ctx):
            self._quiet_since = None
            return False
        if self._quiet_since is None or self._quiet_since > now:
            self._quiet_since = now
            return False
        if now - self._quiet_since < update_prompt.QUIET:
            return False
        self._quiet_timer.stop()
        self._quiet_since = None
        waiting, self._quiet_queue = self._quiet_queue, []
        for show in waiting:
            show()
        return True

    # deferred switch -------------------------------------------------------
    def _quit_blocker(self) -> str:
        blocker = getattr(self.ctx, "quit_blocker", None)
        return blocker() if blocker is not None else ""

    def note_deferred(self, reason: str = "busy") -> None:
        """The program answered "busy" to quit-for-update: keep the new version, switch later."""
        record = read_attempt(attempt_path())
        if record is None or evaluate_attempt(record, self.installed, self.clock()) not in (
                "pending", "failed", "deferred"):
            log.info("quit-for-update answered busy without an attempt of this program (%s)", reason)
            return
        self._defer(record, reason)

    def _deferred_version(self) -> str:
        """Version of a deferred update that waits for the editor to close, "" if none."""
        record = read_attempt(attempt_path())
        if record and record.get("deferred") and evaluate_attempt(record, self.installed, self.clock()) == "deferred":
            return str(record.get("to", ""))
        return ""

    def _defer(self, record: dict, reason: str) -> None:
        self._stop_helper_watch()
        self._switch_started = None    # the helper got its answer (busy) and ends: a new one may start later
        first = not record.get("deferred")
        record["deferred"] = True
        record["deferred_reason"] = reason
        try:
            write_json_atomic(attempt_path(), record)
        except OSError as exc:
            log.warning("cannot write the deferred attempt: %s", exc)
        self.busy = True
        if first:
            log.info("update to %s deferred: %s", record.get("to"), reason)
            telemetry_event("update_deferred", reason=reason, **attempt_fields(record))
            text = wait_text(reason, str(record.get("to", "")))
            # after the reply on the socket is written: a window must never delay "busy"
            QTimer.singleShot(0, lambda: self._show_wait(text))
        self._watch_deferred()

    def _show_wait(self, text: str) -> None:
        """The update is downloaded and waits: non-modal message with "Restart now" (a UI without it: notice/info)."""
        if hasattr(self.ui, "deferred_notice"):
            self.ui.deferred_notice(text, self.restart_now)
        elif hasattr(self.ui, "notice"):
            self.ui.notice(text)
        else:
            self.ui.info(text)

    def restart_now(self) -> bool:
        """"Restart now" of the waiting message: switch at once when nothing blocks quitting any more; otherwise
        say again what still has to be closed. True when the switch was started."""
        record = read_attempt(attempt_path())
        if record is None or not record.get("deferred"):
            return False
        # the person asked explicitly: a window of the phone reception that hides after a photo does not hold the
        # update for 120 s (Clipshot.restart_requested), otherwise the invisible window can never be closed
        asked = getattr(self.ctx, "restart_requested", None)
        if asked is not None:
            asked()
        reason = self._quit_blocker()
        if reason and self._release_blockers("restart_now"):
            reason = self._quit_blocker()
        if reason:
            # 1.36.1: the card never comes back unchanged: it names the window that could not be closed, and the window is
            # brought to the front
            log.warning("restart now: still blocked by %s", reason)
            self._show_wait(self._still_text(reason, str(record.get("to", ""))))
            return False
        self._stop_watch()
        return self.retry_switch(record)

    def _release_blockers(self, where: str) -> bool:
        """The person decided to update: close what holds no work, save what has (app.release_for_restart). True when
        the program can do it (the steps go to the log, so a report shows what happened)."""
        release = getattr(self.ctx, "release_for_restart", None)
        if release is None:
            return False
        try:
            steps = release()
        except Exception as exc:   # noqa: BLE001 - the update must not die on a window that cannot be closed
            log.warning("release before restart (%s) failed: %s", where, exc)
            return False
        log.warning("release before restart (%s): %s", where, steps)
        return True

    def _still_text(self, reason: str, version: str) -> str:
        """Which window still holds the update, by its title; the window is raised."""
        widget = None
        finder = getattr(self.ctx, "blocker_widget", None)
        if finder is not None:
            try:
                widget = finder(reason)
            except Exception:   # noqa: BLE001
                widget = None
        if widget is None:
            return wait_text(reason, version)
        try:
            name = widget.windowTitle() or type(widget).__name__
            widget.show()
            widget.raise_()
            widget.activateWindow()
        except Exception:   # noqa: BLE001 - окно уже удалено или не окно (подмена в тестах): обычная фраза причины
            return wait_text(reason, version)
        return tr("updater.wait.still", window=name, version=version)

    def _watch_deferred(self) -> None:
        if self._deferred_timer is None:
            self._deferred_timer = QTimer(self)
            self._deferred_timer.setInterval(DEFERRED_POLL_MS)
            self._deferred_timer.timeout.connect(self.deferred_tick)
        if not self._deferred_timer.isActive():
            self._deferred_timer.start()

    def _stop_watch(self) -> None:
        if self._deferred_timer is not None:
            self._deferred_timer.stop()

    def deferred_soon(self, ms: int = 1000) -> None:
        """An editor was closed: look at the deferred update in a moment. One shared timer: several editors closed
        in a row give one look, not one each (Г4 of the race review: two helpers for one attempt)."""
        if self._deferred_soon is None:
            self._deferred_soon = QTimer(self)
            self._deferred_soon.setSingleShot(True)
            self._deferred_soon.timeout.connect(self.deferred_tick)
        self._deferred_soon.start(ms)

    def _clipboard_busy(self) -> bool:
        """The program has just copied a snapshot or text and still holds it (Clipshot.clipboard_busy): quitting
        right now would empty the clipboard on Windows and on X11 without a clipboard manager (Г4)."""
        busy = getattr(self.ctx, "clipboard_busy", None)
        try:
            return bool(busy()) if busy is not None else False
        except RuntimeError:
            return False

    def deferred_tick(self) -> bool:
        """Deferred update: switch now if nothing blocks quitting. True when a switch was started."""
        record = read_attempt(attempt_path())
        if record is None or not record.get("deferred"):
            self._stop_watch()
            return False
        if self._quit_blocker() or self._clipboard_busy():
            self._watch_deferred()
            return False
        self._stop_watch()
        return self.retry_switch(record)

    def _switch_in_flight(self, record: dict) -> bool:
        """A helper for this attempt is at work: it holds update.lock (Linux), or this program started one less
        than SWITCH_RELAUNCH_S ago and it has not answered yet (it may not have taken the lock yet)."""
        if self.kind == "linux" and switch_lock_alive():
            return True
        last = self._switch_started
        return (last is not None and last[0] == str(record.get("attempt_id", ""))
                and 0 <= time.monotonic() - last[1] < SWITCH_RELAUNCH_S)

    def retry_switch(self, record: dict) -> bool:
        if self._switch_in_flight(record):
            log.info("deferred update to %s: a switch helper is already at work", record.get("to"))
            self._watch_deferred()   # look again later: the helper decides, or it is gone by then
            return False
        to_version = str(record.get("to", ""))
        tries = int(record.get("tries", 0) or 0) + 1
        record["tries"] = tries
        try:
            write_json_atomic(attempt_path(), record)
        except OSError:
            pass
        ready = False
        if self.kind == "linux":
            folder = versions_dir() / to_version
            ready = (folder / "clipsd-switch").is_file()
        elif self.kind == "windows":
            root = windows_app_root()
            ready = root is not None and (root / "staging" / ".complete").is_file()
        if not ready or tries > MAX_SWITCH_TRIES:
            self._fail_attempt(record, "deferred_lost" if not ready else "too_many_tries")
            return False
        try:
            if self.kind == "linux":
                self._launch_switch(folder, self.installed, to_version, str(record.get("attempt_id", "")))
            else:
                launch_windows_switch(root)
        except (OSError, ValueError) as exc:
            self._fail_attempt(record, type(exc).__name__)
            return False
        self._switch_started = (str(record.get("attempt_id", "")), time.monotonic())
        log.info("deferred update to %s: switch started (try %d)", to_version, tries)
        if self.kind == "linux":
            self._watch_helper(record)
        return True

    def _fail_attempt(self, record: dict, reason: str) -> None:
        self._stop_watch()
        self._stop_helper_watch()
        remove_staging(record, self.kind, self.installed, keep_download=True)
        _unlink(attempt_path())
        self.busy = False
        telemetry_event("update_failed", reason=reason, stage="switch", **attempt_fields(record))
        self._show_failure(record, reason, "switch")

    # watch of the switch helper (Linux) -------------------------------------
    def _watch_helper(self, record: dict) -> None:
        self._helper_attempt = str(record.get("attempt_id", ""))
        self._helper_ticks = 0
        if self._helper_timer is None:
            self._helper_timer = QTimer(self)
            self._helper_timer.setInterval(HELPER_WATCH_MS)
            self._helper_timer.timeout.connect(self.helper_tick)
        self._helper_timer.start()

    def _stop_helper_watch(self) -> None:
        if self._helper_timer is not None:
            self._helper_timer.stop()

    def helper_tick(self) -> str:
        """Every second after the helper was started, while this program still runs (on "ok" it quits and the
        watch ends with it). "" = still waiting, "done" = nothing to watch (deferred, another attempt), "failed" =
        the failure window was shown. A living helper (update.lock) is never declared failed: it decides itself.
        Failed: a result of this attempt that says so, an exit code of the helper other than 0 / 4 (4 = deferred),
        or no helper holding update.lock HELPER_ASK_TICKS seconds after the start (it died before its lock: the
        19.11.2026 case, where 1.31.0 waited 10 minutes and then said nothing useful)."""
        record = read_attempt(attempt_path())
        if record is None or str(record.get("attempt_id", "")) != self._helper_attempt or record.get("deferred"):
            self._stop_helper_watch()
            if record is None or not record.get("deferred"):
                self.ui.progress_close()   # deferred: the waiting message has replaced it already
            return "done"
        self._helper_ticks += 1
        if switch_lock_alive():
            return ""
        result = switch_result(record)
        outcome = str(result.get("result", ""))
        reason = ""
        if outcome in ("failed", "rolled_back", "error"):
            reason = str(result.get("reason") or outcome)
        else:
            code = helper_exit_code()
            if code not in (None, 0, 4):
                reason = f"helper_exit_{code}"
            elif self._helper_ticks >= HELPER_ASK_TICKS:
                reason = "helper_silent"
        if not reason:
            return ""
        if not REASON_RE.fullmatch(reason):
            reason = "unknown"
        log.warning("update to %s: the switch helper failed (%s)", record.get("to"), reason)
        self._fail_attempt(record, reason)
        return "failed"

    def _whats_new_after_update(self, notes: str) -> None:
        """1.34: when this version has highlighted features (novoe.py), the program shows its "New in version" window
        with the same "Update installed" line instead of "ClipSD updated"; otherwise the usual What's new window."""
        show = getattr(self.ctx, "show_novoe_after_update", None)
        if callable(show) and show(self.installed):
            return
        self.ui.whats_new(self.installed, notes)

    # previous attempt ------------------------------------------------------
    def check_previous_attempt(self) -> str:
        """At start (and 10 min after starting an install): result of the last attempt."""
        record = read_attempt(attempt_path())
        if record is None:
            return "failed" if self._show_saved_failure() else "none"
        state = evaluate_attempt(record, self.installed, self.clock())
        result = {}
        if state in ("pending", "failed", "deferred"):
            # the helper / launcher result decides at once, but only a result of THIS attempt
            result = switch_result(record)
            outcome = str(result.get("result", ""))
            if outcome == "deferred":
                state = "deferred"
            elif outcome in ("failed", "rolled_back", "error"):
                state = "failed"
        if state == "completed":
            _unlink(attempt_path())
            _rmtree(downloads_dir())
            telemetry_event("update_completed", deferred=bool(record.get("deferred")), **attempt_fields(record))
            from . import notifications   # 1.32: «Что нового» остаётся в колокольчике редактора
            notifications.remember_whats_new(self.config, self.installed, record.get("notes"))
            self._save()
            notes = notes_in(record.get("notes"), i18n.current())
            self._show_when_quiet(lambda: self._whats_new_after_update(notes))
        elif state == "deferred":
            # the switch waits until the program can quit; at start nothing is open, so it goes now
            if not record.get("deferred"):
                self._defer(record, "busy")
            else:
                self.busy = True
                self._watch_deferred()
                QTimer.singleShot(0, self.deferred_tick)
        elif state == "failed" and self.kind == "linux" and switch_lock_alive():
            # a helper still holds update.lock: it decides (switch or roll back); look again in a minute
            self.busy = True
            QTimer.singleShot(60_000, self.check_previous_attempt)
            state = "pending"
        elif state == "failed":
            remove_staging(record, self.kind, self.installed, keep_download=True)
            _unlink(attempt_path())
            self.busy = False
            self._stop_watch()
            self._stop_helper_watch()
            reason = str(result.get("reason") or result.get("result") or "not_switched")
            if not REASON_RE.fullmatch(reason):
                reason = "unknown"   # a helper older than reason codes wrote a phrase
            telemetry_event("update_failed", reason=reason, stage="switch", **attempt_fields(record))
            self._show_failure(record, reason, "switch")
        elif state == "pending":
            started = _time(record.get("time")) or self.clock()
            left = (started + SWITCH_TIMEOUT - self.clock()).total_seconds() * 1000
            self.busy = True
            QTimer.singleShot(int(max(left, 0)) + 5000, self.check_previous_attempt)
        else:
            _unlink(attempt_path())
        return state

    def mark_started(self):
        """Tell the switch helper (Linux) or the launcher (Windows) that this version came up; both
        roll back without the mark. Windows: marks of other versions are removed. Written once: when
        the event loop runs after the tray is set up, or on an ordinary quit if that came first.
        Run from the sources on Linux: only the mark SOURCE_RUN_MARK for uninstall.sh."""
        if self._mark_written:
            return
        if self.kind == "dev" and os.name != "nt":
            try:
                state_dir().mkdir(parents=True, exist_ok=True)
                (state_dir() / SOURCE_RUN_MARK).touch()
            except OSError:
                pass
            self._mark_written = True
            return
        if self.kind not in ("linux", "windows"):
            return
        folder = mark_dir()
        name = STARTED_MARK.format(version=self.installed)
        try:
            write_json_atomic(folder / name, {"version": self.installed, "time": uc.format_utc(self.clock()),
                                              "pid": os.getpid()})
            self._mark_written = True
        except OSError as exc:
            log.warning("cannot write started mark: %s", exc)
            return
        if self.kind == "windows":
            for old in folder.glob("started-*"):
                if old.name != name:
                    _unlink(old)

    def remove_previous(self):
        """Windows: the new version deletes {app}\\previous, only after its own start mark: until then
        the launcher may still need previous to roll back."""
        if self.kind != "windows" or not self._mark_written:
            return
        root = windows_app_root()
        if root is not None:
            _rmtree(root / "previous")
            _rmtree(root / "failed")

    def start_timers(self):
        QTimer.singleShot(2000, self.check_previous_attempt)
        # 0 ms: runs as soon as the event loop is up; start() is called after the tray is set up
        QTimer.singleShot(0, self.mark_started)
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.mark_started)   # quitting before the timer fired is not a failure
        QTimer.singleShot(PREVIOUS_CLEANUP_DELAY_MS, self.remove_previous)
        first = next_check_delay_ms(self.config, self.clock())
        if self.kind in ("windows", "linux") and self._pending_critical(self.clock(), fresh=False) is not None:
            first = STARTUP_DELAY_MS   # a security fix that is not installed: shown again 60 s after start
        QTimer.singleShot(first, self.tick)
        self.timer = QTimer(self)
        self.timer.setInterval(TICK_MS)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self._wake_seen = self.clock()
        self._wake_timer = QTimer(self)
        self._wake_timer.setInterval(WAKE_POLL_MS)
        self._wake_timer.timeout.connect(self.wake_tick)
        self._wake_timer.start()
        from . import update_prompt
        update_prompt.start(self)   # отложенное окно-предложение ждёт спокойной минуты


# --- integration -----------------------------------------------------------

def get_updater(ctx) -> Updater:
    updater = getattr(ctx, "_updater", None)
    if updater is None:
        updater = Updater(ctx)
        ctx._updater = updater
    return updater


def install_menu(tray_menu, ctx, before=None) -> QAction:
    """Add "Check for updates" to the tray menu (above the last separator unless before is given)."""
    action = QAction(tr("updater.menu.check"), tray_menu)
    action.triggered.connect(lambda: get_updater(ctx).check_now(manual=True))
    if before is None:
        separators = [a for a in tray_menu.actions() if a.isSeparator()]
        before = separators[-1] if separators else None
    if before is not None:
        tray_menu.insertAction(before, action)
    else:
        tray_menu.addAction(action)
    return action


def start(ctx) -> Updater:
    """Start-up work: result of the previous attempt, started mark, cleanup, check timers."""
    updater = get_updater(ctx)
    if updater.timer is None:
        updater.start_timers()
    return updater
