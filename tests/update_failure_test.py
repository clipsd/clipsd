# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the person sees when an update does not go in, or waits (1.31.2, after the 19.11.2026 case where 1.31.0
said nothing for 10 minutes and then only "did not finish").

- the switch helper is watched right after its start: an exit code other than 0/4, a result that says failed, or no
  helper holding update.lock within 60 s -> the failure window at once; a living helper (update.lock) is never
  declared failed;
- the failure window: text with the version, "Retry", "Send an error report", "Close"; Retry never starts a second
  helper (update.lock) and otherwise asks the channel again and installs without the offer, using the archive
  kept from the failed attempt when its size and sha256 match;
- the error report: versions, platform, step, error code, trace_id / attempt_id, the end of update.log, without the
  home folder and the user name; Copy, the GitHub issue page (title and body in the address, cut to a safe length),
  e-mail; "Send" only when REPORT_ENDPOINT is set;
- waiting update: the message has "Restart now"; "Update installed: ClipSD N is ready" in What's new;
- the download window stays after the download and says "Installing version N. ClipSD will restart by itself."

Run: QT_QPA_PLATFORM=offscreen python3 tests/update_failure_test.py
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import types
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
tmp = Path(tempfile.mkdtemp(prefix="clipsd-update-failure-"))
for name, sub in (("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"), ("XDG_STATE_HOME", "state"),
                  ("XDG_CACHE_HOME", "cache"), ("LOCALAPPDATA", "data")):
    os.environ[name] = str(tmp / sub)
(tmp / "runtime").mkdir(mode=0o700)
os.environ["XDG_RUNTIME_DIR"] = str(tmp / "runtime")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QTimer  # noqa: E402
from PyQt6.QtGui import QGuiApplication  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel, QMessageBox  # noqa: E402

qapp = QApplication(sys.argv)

from clipshot import i18n  # noqa: E402
from clipshot import updater as up  # noqa: E402
from clipshot.i18n import tr  # noqa: E402

failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


NOW = datetime(2026, 11, 19, 17, 39, 10, tzinfo=timezone.utc)
RECORD = {"trace_id": "5dba4c06310644bf9a6a57629c109216", "attempt_id": "a69037f388304601bcfea647e86283ae",
          "from": "1.31.0", "to": "1.31.1", "time": "2026-11-19T17:39:10Z", "platform": "linux", "channel": "stable"}
BITS = [("/home/alice", "~"), ("alice", "<user>")]

# --- the report ------------------------------------------------------------------------------------------------
log_lines = ["2026-11-19T19:39:10+02:00 start from=1.31.0 to=1.31.1",
             "2026-11-19T19:39:11+02:00 cannot open /home/alice/.local/share/clipsd/current",
             "session of alice, folder malice stays"]
report = up.failure_report(RECORD, "helper_exit_1", "switch", "linux", "1.31.0", now=NOW, log_lines=log_lines, bits=BITS)
for want in ("From version: 1.31.0", "To version: 1.31.1", "Platform: linux", "Install kind: linux", "Step: switch",
             "Error code: helper_exit_1", "trace_id: 5dba4c06310644bf9a6a57629c109216",
             "attempt_id: a69037f388304601bcfea647e86283ae", "Update log (last 3 lines):", "start from=1.31.0 to=1.31.1"):
    check(want in report, f"report: «{want}»")
check("/home/alice" not in report and "~/.local/share/clipsd/current" in report, "report: home folder replaced by ~")
check(" alice" not in report and "session of <user>" in report and "malice" in report,
      "report: user name replaced as a whole word only")
real = up.failure_report(RECORD, "x", "switch", "linux", "1.31.0", now=NOW,
                         log_lines=[os.path.expanduser("~") + "/secret/file"])
check(os.path.expanduser("~") not in real, "report with the real home folder: not inside")
title = up.report_title(RECORD, "helper_exit_1")
check(title == "Update 1.31.0 -> 1.31.1 failed: helper_exit_1", f"report title ({title})")

# --- issue page and e-mail addresses ---------------------------------------------------------------------------
url = up.issue_url(title, report)
q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
check(url.startswith(up.ISSUE_URL + "?") and q["title"] == [title] and q["body"] == [report],
      "issue page: title and the whole short report in the address")
long_report = report + "\n" + "\n".join(f"line {i} " + "x" * 80 for i in range(400))
url = up.issue_url(title, long_report)
q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
check(len(url) <= up.ISSUE_URL_LIMIT and q["body"][0].startswith("ClipSD update failure report")
      and q["body"][0].endswith("[... cut]"), f"issue page: long report cut to a safe length ({len(url)} chars)")
mail = up.mail_url("ClipSD: " + title, long_report)
mq = urllib.parse.parse_qs(urllib.parse.urlparse(mail).query)
check(mail.startswith("mailto:clipsd.app@gmail.com?subject=") and len(mail) <= up.MAIL_URL_LIMIT
      and mq["subject"] == ["ClipSD: " + title] and mq["body"][0].startswith("ClipSD update failure report"),
      f"e-mail: support address, subject, body cut ({len(mail)} chars)")

# --- receiver: one constant -----------------------------------------------------------------------------------
check(up.REPORT_ENDPOINT == "", "1.31: no receiver, nothing is sent anywhere")
check(up.send_report(report, title) is False and up.send_report(report, title, "http://example.invalid/r") is False,
      "send_report: without an https receiver nothing is sent")
posted = []


class Resp:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


ok = up.send_report(report, title, "https://example.invalid/report",
                    opener=lambda req, timeout: posted.append(req) or Resp())
body = json.loads(posted[0].data.decode("utf-8")) if posted else {}
check(ok and posted and posted[0].get_method() == "POST" and body.get("report") == report
      and body.get("kind") == "update_failure", "send_report: with the receiver set, the shown report is posted as JSON")

# --- failure window and report window (real widgets) ------------------------------------------------------------
for lang in ("ru", "en", "de", "zh"):
    i18n.set_language(lang)
    urls = []
    d = up.FailedDialog("1.31.1", report, title, open_url=urls.append)
    text = d.findChild(QLabel, "text").text()
    check(text == tr("updater.failed.text", version="1.31.1") and "1.31.1" in text
          and d.retry_button.text() == tr("updater.button.retry") and d.report_button.text() == tr("updater.button.report")
          and d.close_button.text() == tr("updater.button.close") and d.retry_button.isDefault(),
          f"failure window ({lang}): text with the version, Retry (default), Send an error report, Close")
    seen = []
    QTimer.singleShot(150, lambda: (seen.append(d.report_dialog), d.report_dialog.accept()))
    d.report_button.click()
    check(seen and seen[0] is not None and seen[0].report == report and d.choice == "close",
          f"failure window ({lang}): «Send an error report» opens the report window, the failure window stays")
    d.retry_button.click()
    check(d.choice == "retry", f"failure window ({lang}): Retry")
i18n.set_language("ru")
urls = []
r = up.ReportDialog(report, title, open_url=urls.append, endpoint="")
check(r.text.toPlainText() == report and r.text.isReadOnly(), "report window: the exact report text, read-only")
check(r.send_button.isHidden() and not r.copy_button.isHidden(), "report window: no «Send» without the receiver")
r.copy_button.click()
check(QGuiApplication.clipboard().text() == report and r.status.text() == tr("updater.report.copied"),
      "report window: Copy puts the report into the clipboard")
r.issue_button.click()
r.mail_button.click()
check(len(urls) == 2 and urls[0].startswith(up.ISSUE_URL + "?title=") and urls[1].startswith("mailto:clipsd.app@gmail.com"),
      "report window: the bug report page and e-mail open with the report")
check(r.copy_button.text() == tr("updater.button.copy") and r.issue_button.text() == tr("updater.button.open_issue")
      and r.mail_button.text() == tr("updater.button.email"), "report window: button texts")
sent = []
r2 = up.ReportDialog(report, title, endpoint="https://example.invalid/r",
                     sender=lambda rep, t, e: sent.append((rep, t, e)) or True)
check(not r2.send_button.isHidden(), "report window: «Send» appears when REPORT_ENDPOINT is set")
check(r2.send() and sent == [(report, title, "https://example.invalid/r")] and r2.status.text() == tr("updater.report.sent")
      and not r2.send_button.isEnabled(), "Send: the shown text goes to the receiver, «sent»")
r3 = up.ReportDialog(report, title, endpoint="https://example.invalid/r", sender=lambda *a: False)
check(not r3.send() and r3.status.text() == tr("updater.report.send_failed"), "Send failed: says so, copy and e-mail remain")

# --- success, progress, waiting messages (real widgets) -------------------------------------------------------
w = up.WhatsNewDialog("1.31.1", "- notes")
check(w.findChild(QLabel, "installed").text() == "<b>" + tr("updater.whatsnew.installed", version="1.31.1") + "</b>"
      and "ClipSD 1.31.1" in tr("updater.whatsnew.installed", version="1.31.1"),
      "What's new starts with «Update installed: ClipSD 1.31.1 is ready»")
ui = up.UpdaterUI()
ui.progress_start("1.31.1", lambda: None)
ui.progress_update(50, 100)
ui.progress_stage(tr("updater.install.started", version="1.31.1"))
pd = ui.progress
check(pd is not None and pd.bar.maximum() == 0 and pd.heading.text() == tr("updater.install.started", version="1.31.1")
      and pd.status.isHidden()
      and pd.cancel_button.isHidden() and not pd.isModal() and pd.property(up.CLOSABLE),
      "after the download the same window says «Installing… ClipSD will restart by itself», never blocks quitting")
restarted = []
ui.deferred_notice(tr("updater.wait.unsaved", version="1.31.1"), lambda: restarted.append(1))
box = ui._notice
check(ui.progress is None and box is not None and not box.isModal() and box.property(up.CLOSABLE),
      "waiting message: non-modal, does not block quitting, replaces the progress window")
restart = [b for b in box.buttons() if b.text() == tr("updater.button.restart_now")]
check(box.text() == tr("updater.wait.unsaved", version="1.31.1") and restart, "waiting message has «Restart now»")
if restart:
    restart[0].click()
    for _ in range(5):
        qapp.processEvents()
check(restarted == [1], "«Restart now» calls the updater")


# --- the controller: watch of the helper, Retry, Restart now -------------------------------------------------------
class RecUI:
    def __init__(self, choice="close"):
        self.choice, self.failures, self.infos, self.errors, self.notices = choice, [], [], [], []
        self.hints = []

    def failed(self, version, report_text, title_text, hint=""):
        self.failures.append((version, report_text, title_text))
        self.hints.append(hint)
        return self.choice

    def info(self, text):
        self.infos.append(text)

    def error(self, text):
        self.errors.append(text)

    def deferred_notice(self, text, on_restart):
        self.notices.append((text, on_restart))

    def progress_close(self):
        pass

    def progress_stage(self, text):
        pass


class Ctx:
    def __init__(self):
        self.config = {}
        self.blocker = ""

    def save_config(self):
        pass

    def quit_blocker(self):
        return self.blocker


class FakeProc:
    def __init__(self, code):
        self.code = code

    def poll(self):
        return self.code


def fresh_attempt(minutes=0):
    up.write_attempt(up.attempt_path(), "2.0.0", "2.0.1", NOW + timedelta(minutes=minutes))
    (up.versions_dir() / "2.0.1").mkdir(parents=True, exist_ok=True)
    (up.versions_dir() / "2.0.1" / "clipsd-switch").write_text("#!/bin/bash\n")
    (up.downloads_dir() / "2.0.1").mkdir(parents=True, exist_ok=True)
    (up.downloads_dir() / "2.0.1" / "ClipSD-2.0.1-linux-x86_64.tar.gz").write_bytes(b"archive")
    return up.read_attempt(up.attempt_path())


def make(choice="close"):
    ui_ = RecUI(choice)
    ctx_ = Ctx()
    u_ = up.Updater(ctx_, kind="linux", installed="2.0.0", ui=ui_, sync=True, clock=lambda: NOW + timedelta(minutes=1))
    return u_, ui_, ctx_


events = []
up.telemetry_event = lambda name, **f: events.append((name, f))

# helper died at once (the 19.11.2026 case): failure window on the first tick, not 10 minutes later
u, rui, _ = make()
rec = fresh_attempt()
u._watch_helper(rec)
up._helper_process = FakeProc(1)
state = u.helper_tick()
check(state == "failed" and rui.failures and "Error code: helper_exit_1" in rui.failures[0][1]
      and rui.failures[0][0] == "2.0.1", "helper exited with 1: the failure window at the first tick, report says helper_exit_1")
check(not up.attempt_path().exists() and not (up.versions_dir() / "2.0.1").exists()
      and (up.downloads_dir() / "2.0.1" / "ClipSD-2.0.1-linux-x86_64.tar.gz").exists() and not u.busy,
      "after the failure: attempt and unpacked version removed, downloaded archive kept for Retry")
check(events and events[-1][0] == "update_failed" and events[-1][1]["reason"] == "helper_exit_1", "event update_failed helper_exit_1")
check(not u._helper_timer.isActive(), "the watch stops after the failure")

# exit code 0 (moved itself out through systemd-run) or 4 (deferred): no failure
for code in (0, 4, None):
    u, rui, _ = make()
    rec = fresh_attempt()
    u._watch_helper(rec)
    up._helper_process = FakeProc(code)
    check(u.helper_tick() == "" and not rui.failures, f"helper exit code {code}: still waiting")

# a living helper (update.lock with the pid of a clipsd-switch) is never declared failed
holder = subprocess.Popen(["bash", "-c", "exec -a clipsd-switch sleep 30"])
time.sleep(0.3)
lock = up.state_dir() / "update.lock"
lock.mkdir(parents=True, exist_ok=True)
(lock / "pid").write_text(f"{holder.pid}\n")
check(up.switch_lock_alive(), "update.lock held by a living clipsd-switch: alive")
u, rui, _ = make()
rec = fresh_attempt()
u._watch_helper(rec)
up._helper_process = FakeProc(2)   # e.g. lock_busy: another helper works
for _ in range(up.HELPER_ASK_TICKS + 5):
    u.helper_tick()
check(not rui.failures and up.attempt_path().exists(), "a living helper holds the lock: no failure even after 60 s")
# Retry while a helper is at work: never a second one
rui.choice = "retry"
check(u.retry_update(rec) is False and rui.infos == [tr("updater.retry.busy")], "Retry while update.lock is held: «already installing»")
fresh_attempt(minutes=-11)
check(u.check_previous_attempt() == "pending" and not rui.failures and up.attempt_path().exists()
      and (up.versions_dir() / "2.0.1").exists(), "10-minute check while the helper lives: it decides, nothing removed")
# install() while a helper is at work: nothing unpacked, no attempt written
up._unlink(up.attempt_path())
u2, rui2, _ = make()
u2.install(tmp / "none.tar.gz", types.SimpleNamespace(version="2.0.1", notes={}), "t" * 32)
check(rui2.infos == [tr("updater.retry.busy")] and not up.attempt_path().exists() and not u2.busy,
      "install while a helper works: «already installing», nothing written")
holder.kill()
holder.wait()
check(not up.switch_lock_alive(), "the helper of the lock is gone: not alive")
(lock / "pid").unlink()
lock.rmdir()

# no helper at all within 60 s
u, rui, _ = make()
rec = fresh_attempt()
u._watch_helper(rec)
up._helper_process = None
results = [u.helper_tick() for _ in range(up.HELPER_ASK_TICKS)]
check(results[:-1] == [""] * (up.HELPER_ASK_TICKS - 1) and results[-1] == "failed" and "Error code: helper_silent" in rui.failures[0][1],
      "no helper holds update.lock 60 s after the start: failure window (helper_silent)")

# a result of this attempt that says failed
u, rui, _ = make()
rec = fresh_attempt()
u._watch_helper(rec)
up._helper_process = None
up.write_json_atomic(up.mark_dir() / "update-result.json",
                     {"from": "2.0.0", "to": "2.0.1", "result": "error", "reason": "missing_version",
                      "time": up.uc.format_utc(NOW + timedelta(minutes=1))})
check(u.helper_tick() == "failed" and "Error code: missing_version" in rui.failures[0][1], "helper result error: failure window at once")
(up.mark_dir() / "update-result.json").unlink()

# the helper could not leave clipsd.service (no systemd-run): failure window with what to do, nothing else touched
u, rui, _ = make()
rec = fresh_attempt()
u._watch_helper(rec)
up._helper_process = FakeProc(2)
up.write_json_atomic(up.mark_dir() / "update-result.json",
                     {"from": "2.0.0", "to": "2.0.1", "result": "error", "reason": "cannot_detach",
                      "time": up.uc.format_utc(NOW + timedelta(minutes=1))})
check(u.helper_tick() == "failed" and "Error code: cannot_detach" in rui.failures[0][1]
      and rui.hints == [tr("updater.failed.cannot_detach")] and "install.sh" in rui.hints[0],
      "cannot_detach: failure window at once, with «install by hand: install.sh»")
(up.mark_dir() / "update-result.json").unlink()
fd = up.FailedDialog("2.0.1", "r", "t", hint=tr("updater.failed.cannot_detach"))
check(fd.findChild(QLabel, "hint") is not None and fd.findChild(QLabel, "hint").text() == tr("updater.failed.cannot_detach"),
      "failure window shows the hint under its text")
check(up.FailedDialog("2.0.1", "r", "t").findChild(QLabel, "hint") is None, "no hint for other reasons")

# П2: a result of an earlier try (same from/to, written just now) is not taken for the new one
u, rui, _ = make()
rec = fresh_attempt()
up.write_json_atomic(up.mark_dir() / "update-result.json",
                     {"from": "2.0.0", "to": "2.0.1", "result": "error", "reason": "lock_busy",
                      "time": up.uc.format_utc(NOW + timedelta(minutes=1))})
check(up.switch_result(rec).get("reason") == "lock_busy", "the old result would pass for this attempt (2 min slack)")
_launched = []
_real_launch = up.launch_linux_switch
up.launch_linux_switch = lambda folder, a, b, attempt: _launched.append((a, b)) or "setsid"
up._helper_process = None
check(u.retry_switch(rec) is True and _launched == [("2.0.0", "2.0.1")], "Retry: the helper is started again")
check(not (up.mark_dir() / "update-result.json").exists(), "the old update-result.json is removed before the start")
check(u.helper_tick() == "" and not rui.failures and (up.versions_dir() / "2.0.1").exists(),
      "first tick after Retry: still waiting, the new version is not removed from under the helper")
up.launch_linux_switch = _real_launch
u._stop_helper_watch()

# deferred: the watch ends quietly
u, rui, ctx = make()
rec = fresh_attempt()
u._watch_helper(rec)
rec["deferred"] = True
up.write_json_atomic(up.attempt_path(), rec)
check(u.helper_tick() == "done" and not rui.failures, "deferred attempt: the watch ends, no failure")

# Retry without a living helper: the channel again, installed without the offer
u, rui, _ = make("retry")
asked = []
u.check_now = lambda manual=True, auto=False: asked.append((manual, auto)) or True
rec = fresh_attempt()
u._watch_helper(rec)
up._helper_process = FakeProc(1)
u.helper_tick()
check(asked == [(True, True)], "Retry: the channel is asked again (manual) and the version found is installed at once")
u, rui, _ = make()
started = []
u.start_download = lambda m, trace_id="": started.append(m.version)
u.busy, u._auto_update = True, True
u.ui.offer = lambda *a, **k: (_ for _ in ()).throw(AssertionError("offer shown"))
u._present(types.SimpleNamespace(version="2.0.1"), "notify", False, NOW)
check(started == ["2.0.1"] and u._auto_update is False, "Retry: no «version N is available» window, download starts")

# the kept archive is used again when it has the signed size and sha256
arch = up.downloads_dir() / "2.0.1" / "ClipSD-2.0.1-linux-x86_64.tar.gz"
arch.parent.mkdir(parents=True, exist_ok=True)
arch.write_bytes(b"archive bytes")
sha = hashlib.sha256(b"archive bytes").hexdigest()
check(up.verified_file(arch, len(b"archive bytes"), sha), "kept archive: size and sha256 match")
check(not up.verified_file(arch, 5, sha) and not up.verified_file(arch, len(b"archive bytes"), "0" * 64),
      "kept archive: another size or sha256 is not used")
(up.downloads_dir() / "2.0.0").mkdir(parents=True, exist_ok=True)
(arch.parent / "old.part").write_bytes(b"x")
up.clean_downloads(keep=arch)
check(arch.exists() and not (arch.parent / "old.part").exists() and not (up.downloads_dir() / "2.0.0").exists(),
      "before a download only the kept archive stays")

# 10 minutes later without a helper: the failure window (not only a message)
u, rui, _ = make()
fresh_attempt(minutes=-11)
check(u.check_previous_attempt() == "failed" and rui.failures and "Step: switch" in rui.failures[0][1],
      "10-minute check: failure window with the report")

# Restart now
u, rui, ctx = make()
rec = fresh_attempt()
ctx.blocker = "unsaved"
u.note_deferred("unsaved")
for _ in range(5):
    qapp.processEvents()
check(rui.notices and rui.notices[0][0] == tr("updater.wait.unsaved", version="2.0.1") and rui.notices[0][1] == u.restart_now,
      "waiting: message «installs when you close the editor» with «Restart now»")
switches = []
real_switch = up.launch_linux_switch
up.launch_linux_switch = lambda folder, a, b, attempt: switches.append((a, b)) or "setsid"
check(u.restart_now() is False and not switches and len(rui.notices) == 2, "Restart now with the editor still open: says so again")
ctx.blocker = ""
check(u.restart_now() is True and switches == [("2.0.0", "2.0.1")] and u._helper_timer.isActive(),
      "Restart now with nothing open: switch started and watched")
up.launch_linux_switch = real_switch
u._stop_helper_watch()
u._stop_watch()

print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено {len(failures)}")
sys.exit(1 if failures else 0)
