# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Update module test: signature, expiry, rollback, keys, schedule with a fake clock, downloads, install.

No network: the channel is a fake fetch function, files come from http.server on 127.0.0.1.
Keys are generated in a temporary folder. Real config, services and dconf are not touched.

Run: QT_QPA_PLATFORM=offscreen python3 tests/updater_test.py [project] [output folder]
"""

import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import hashlib
import http.server
import io
import json
import os
import shutil
import socketserver
import sys
import tarfile
import tempfile
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

here = os.path.dirname(os.path.abspath(__file__))
project = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(here)
out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(here, "output", "updater")
os.makedirs(out, exist_ok=True)
tmp = Path(tempfile.mkdtemp(prefix="clipsd-updater-test-"))
os.environ["XDG_CONFIG_HOME"] = str(tmp / "config")
os.environ["XDG_DATA_HOME"] = str(tmp / "data")
os.environ["LOCALAPPDATA"] = str(tmp / "data")
os.environ["XDG_STATE_HOME"] = str(tmp / "state")
os.environ["XDG_CACHE_HOME"] = str(tmp / "cache")
os.environ["CLIPSD_DATA_DIR"] = str(tmp / "clipsd-data")
(tmp / "runtime").mkdir(mode=0o700)
os.environ["XDG_RUNTIME_DIR"] = str(tmp / "runtime")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, project)
sys.path.insert(0, os.path.join(project, "tools"))

from PyQt6.QtWidgets import QApplication, QMenu  # noqa: E402

qapp = QApplication(sys.argv)

import channel_sign as cs  # noqa: E402
from clipshot import update_channel as uc  # noqa: E402
from clipshot import updater as up  # noqa: E402
from clipshot.i18n import tr  # noqa: E402
from clipshot import i18n  # noqa: E402
NOTES_SHOWN = "Русские изменения" if i18n.current() == "ru" else "English notes"   # language of the program, else English

failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


LINUX = sys.platform.startswith("linux")


def skip(msg):
    print("SKIP " + msg + " (skip: linux only)")


def raises(fn, code):
    try:
        fn()
    except (uc.ChannelError, up.UpdateError) as exc:
        return exc.code == code or (print(f"     got {exc.code}: {exc}") and False)
    return False


# --- keys and documents ------------------------------------------------------
keys = tmp / "keys"
STABLE_PUB = cs.keygen(keys / "stable.pem")
BACKUP_PUB = cs.keygen(keys / "backup.pem")
TEST_PUB = cs.keygen(keys / "test.pem")
OTHER_PUB = cs.keygen(keys / "other.pem")
PRIV = {name: cs.load_private(keys / f"{name}.pem") for name in ("stable", "backup", "test", "other")}
KEYS = {"stable_keys": [STABLE_PUB, BACKUP_PUB], "test_keys": [TEST_PUB]}
NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
PAYLOAD = b"ClipSD fake installer " * 1000
PAYLOAD_SHA = hashlib.sha256(PAYLOAD).hexdigest()


def document(version="2.0.1", channel="stable", expires=NOW + timedelta(days=90), **extra):
    doc = {"schema": 1, "channel": channel, "version": version, "released": cs.utc(NOW - timedelta(days=1)),
           "expires": cs.utc(expires)}
    doc.update(extra)
    doc.setdefault("files", {p: {"url": f"https://github.com/ClipSD/ClipSD/releases/download/v{version}/f-{p}",
                                 "size": len(PAYLOAD), "sha256": PAYLOAD_SHA} for p in ("windows", "linux")})
    doc.setdefault("notes", {"en": f"# {version}\n- English notes", "ru": f"# {version}\n- Русские изменения"})
    return cs.dump(doc)


def signed(data, key="stable"):
    return cs.sign_bytes(PRIV[key], data)


def load(data, sig, channel="stable", now=NOW, last_seen="", **kw):
    return uc.load_verified(data, sig, channel, now, last_seen, **({**KEYS, **kw}))


# --- versions -----------------------------------------------------------------
check(uc.compare_versions("2.0.10", "2.0.9") == 1, "версии: 2.0.10 > 2.0.9")
check(uc.compare_versions("2.1", "2.0.99") == 1, "версии: 2.1 > 2.0.99")
check(uc.compare_versions("2.0", "2.0.0") == 0, "версии: 2.0 == 2.0.0")
check(uc.compare_versions("1.13.3", "2.0.0") == -1, "версии: 1.13.3 < 2.0.0")
check(raises(lambda: uc.parse_manifest(document(version="2.0.1-beta"), "stable"), "bad_document"),
      "версия с суффиксом отвергается")

# --- signature ------------------------------------------------------------------
doc = document()
m = load(doc, signed(doc))
check(m.version == "2.0.1" and m.files["linux"]["size"] == len(PAYLOAD), "подписанный основным ключом: принят")
check(load(doc, signed(doc, "backup")).version == "2.0.1", "подписанный резервным ключом: принят")
check(raises(lambda: load(doc, b""), "bad_signature"), "неподписанный (пустая подпись): отвергнут")
check(raises(lambda: load(doc, b"not base64 at all"), "bad_signature"), "подпись-мусор: отвергнута")
check(raises(lambda: load(doc, signed(doc, "other")), "bad_signature"), "чужая подпись: отвергнута")
tampered = doc.replace(b'"2.0.1"', b'"2.0.2"')
check(raises(lambda: load(tampered, signed(doc)), "bad_signature"), "изменённый после подписи: отвергнут")
check(raises(lambda: load(doc + b" ", signed(doc)), "bad_signature"), "лишний пробел после подписи: отвергнут")

# test key never opens the stable channel
check(raises(lambda: load(doc, signed(doc, "test")), "bad_signature"), "тестовый ключ в основном канале: отвергнут")
check(raises(lambda: load(doc, signed(doc, "test"), stable_keys=[STABLE_PUB, TEST_PUB]), "bad_signature"),
      "тестовый ключ, ошибочно вписанный в основные: всё равно отвергнут")
check(uc.trusted_keys("stable", [TEST_PUB], [TEST_PUB]) == [], "основной канал отбрасывает ключ из тестового списка")
tdoc = document(channel="test")
check(load(tdoc, signed(tdoc, "test"), channel="test").version == "2.0.1", "тестовый канал: тестовый ключ принят")
check(raises(lambda: load(tdoc, signed(tdoc, "stable"), channel="test"), "bad_signature"),
      "тестовый канал: основной ключ не принимается")
check(raises(lambda: load(tdoc, signed(tdoc, "stable")), "wrong_channel"),
      "документ тестового канала по адресу основного: отвергнут")

# embedded keys
emb_s = {uc._normalize(k) for k in uc.STABLE_PUBLIC_KEYS} - {b""}
emb_t = {uc._normalize(k) for k in uc.TEST_PUBLIC_KEYS} - {b""}
check(not (emb_s & emb_t), "вшитые ключи: основной и тестовый наборы не пересекаются")
if not uc.trusted_keys("stable"):   # placeholders: the build must refuse every update
    check(raises(lambda: uc.load_verified(doc, signed(doc), "stable", NOW), "no_keys"),
          "сборка с ключом-заглушкой: основной канал отказывает в любом обновлении")
    fetch0 = lambda url, limit: signed(doc) if url.endswith(".sig") else doc  # noqa: E731
    check(raises(lambda: up.fetch_manifest("stable", {}, NOW, fetch0), "no_keys"),
          "сборка с ключом-заглушкой: проверка обновлений ничего не предлагает")
else:
    check(all(len(uc._normalize(k)) == 32 for k in uc.STABLE_PUBLIC_KEYS), "вшитые основные ключи настоящие")

# --- expiry and rollback -----------------------------------------------------------
old = document(expires=NOW - timedelta(days=3))
check(raises(lambda: load(old, signed(old)), "expired"), "срок истёк 3 дня назад: отвергнут")
soon = document(expires=NOW - timedelta(days=1))
check(load(soon, signed(soon)).version == "2.0.1", "срок истёк день назад: принят (допуск часов 2 дня)")
check(raises(lambda: load(doc, signed(doc), last_seen="2.0.5"), "rollback"), "откат 2.0.5 -> 2.0.1: отвергнут")
check(load(doc, signed(doc), last_seen="2.0.1").version == "2.0.1", "та же версия, что видели: принята")
far = document(expires=NOW + timedelta(days=200))
check(raises(lambda: load(far, signed(far)), "expires_far"), "срок дальше now + 120 дней: отвергнут (код expires_far)")
edge = document(expires=NOW + timedelta(days=121))
check(load(edge, signed(edge)).version == "2.0.1", "срок now + 121 день (в допуске часов 2 дня): принят")
check(load(far, signed(far), now=NOW + timedelta(days=90)).version == "2.0.1",
      "продлённый документ (released тот же, expires +200 от выпуска): принят, граница от текущего времени")
for bad in ("\uff12.0.1", "2.\u0660.1", "2.0.\u0663"):   # fullwidth and Arabic-Indic digits
    try:
        uc.parse_version(bad)
        rejected = False
    except ValueError:
        rejected = True
    check(rejected, f"версия с не-ASCII цифрами отвергнута: {bad!r}")
check(raises(lambda: load(document(channel="stable").replace(b'"schema": 1', b'"schema": 2'),
                          signed(document().replace(b'"schema": 1', b'"schema": 2'))), "bad_schema"),
      "неизвестная схема: отвергнута")
http_doc = document(files={"linux": {"url": "http://x/f", "size": 5, "sha256": "0" * 64}})
check(raises(lambda: load(http_doc, signed(http_doc)), "bad_document"), "файл по http (не https): отвергнут")


# --- fake channel -------------------------------------------------------------------
class Channel:
    def __init__(self):
        self.doc, self.sig, self.requests, self.fail = doc, signed(doc), 0, None

    def publish(self, version, key="stable", **extra):
        self.doc = document(version=version, **extra)
        self.sig = signed(self.doc, key)

    def __call__(self, url, limit):
        self.requests += 1
        if self.fail:
            raise self.fail
        return self.sig if url.endswith(".sig") else self.doc


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class UI:
    def __init__(self, answer="later"):
        self.answer, self.offers, self.infos, self.errors, self.news, self.urls = answer, [], [], [], [], []
        self.critical = []   # critical flag of every offer, in the order of self.offers

    def offer(self, manifest, installed, critical=False):
        self.offers.append(manifest.version)
        self.critical.append(critical)
        return self.answer

    def manual_install(self, version):
        self.infos.append(("manual", version))

    def whats_new(self, version, markdown):
        self.news.append((version, markdown))

    def info(self, text):
        self.infos.append(text)

    def error(self, text):
        self.errors.append(text)

    def progress_start(self, version, cancel):
        pass

    def progress_update(self, done, total):
        pass

    def progress_close(self):
        pass

    def open_url(self, url):
        self.urls.append(url)


class Ctx:
    def __init__(self, **config):
        self.config = dict(config)
        self.saved = 0
        self.notes = []

    def save_config(self):
        self.saved += 1

    def notify(self, text):
        self.notes.append(text)


def make(kind="linux", installed="2.0.0", config=None, answer="later", channel=None, clock=None, **kw):
    ctx = Ctx(**(config or {}))
    ui = UI(answer)
    channel = channel or Channel()
    clock = clock or Clock(NOW)
    u = up.Updater(ctx, fetch=channel, clock=clock, kind=kind, installed=installed, ui=ui, sync=True,
                   stable_keys=KEYS["stable_keys"], test_keys=KEYS["test_keys"], **kw)
    return u, ctx, ui, channel, clock


# --- schedule (pure) ------------------------------------------------------------------
# The owner's decision 03.11.2026: the channel is asked quietly once a day, an ordinary update is offered at most
# once a week, an urgent security fix right away.
cfg = {}
check(up.should_check(cfg, NOW), "расписание: первая проверка разрешена")
up.mark_checked(cfg, NOW)
check(not up.should_check(cfg, NOW + timedelta(hours=23)), "расписание: через 23 часа рано")
check(up.should_check(cfg, NOW + timedelta(days=1)), "расписание: через сутки пора (тихая проверка раз в день)")
check(up.should_check(cfg, NOW + timedelta(hours=1), manual=True), "расписание: ручная проверка сразу")
check(not up.should_check({"update_check": False}, NOW), "расписание: выключенная проверка не ходит в сеть")
up.mark_notified(cfg, NOW)
check(not up.should_notify(cfg, "2.0.2", NOW + timedelta(days=3)), "окно: не чаще раза в 7 дней")
check(up.should_notify(cfg, "2.0.2", NOW + timedelta(days=7)), "окно: через 7 дней можно")
check(up.should_notify(cfg, "2.0.2", NOW + timedelta(days=1), manual=True), "окно: по кнопке сразу")
check(up.should_notify(cfg, "2.0.2", NOW + timedelta(hours=1), critical=True),
      "окно: исправление безопасности без ожидания 7 дней")
up.skip_version(cfg, "2.0.2")
check(not up.should_notify(cfg, "2.0.2", NOW + timedelta(days=30)), "окно: пропущенная версия не предлагается")
check(up.should_notify(cfg, "2.0.3", NOW + timedelta(days=30)), "окно: следующая версия после пропуска предлагается")
check(up.should_notify(cfg, "2.0.2", NOW + timedelta(days=30), critical=True), "окно: исправление безопасности несмотря на пропуск")
check(up.next_check_delay_ms({}, NOW) == up.STARTUP_DELAY_MS, "первая проверка через 60 с после запуска")

# 30 days of hourly ticks, a new ordinary version every day: requests once a day. 1.32 (the owner's decision
# 19.11.2026): the window is not shown by the check itself; the bell lights up, the window comes 3 days after the
# discovery (or 20 shots) in a quiet minute, "Later" postpones it for 3 more days (update_prompt.poll every half hour)
from clipshot import update_prompt as upr  # noqa: E402
u, ctx, ui, ch, clock = make()
request_times, offered_at = [], []
for half in range(30 * 48):
    clock.now = NOW + timedelta(minutes=30 * half)
    if half % 48 == 0:
        ch.publish(f"2.0.{half // 48 + 1}")
    before_req, before_off = ch.requests, len(ui.offers)
    if half % 2 == 0:
        u.tick()
    upr.poll(u)
    clock.now += timedelta(seconds=61)
    upr.poll(u)
    if ch.requests > before_req:
        request_times.append(clock.now)
    if len(ui.offers) > before_off:
        offered_at.append((clock.now, ui.offers[-1]))
gaps = [b - a for a, b in zip(request_times, request_times[1:])]
check(len(request_times) == 30 and all(g >= timedelta(days=1) for g in gaps),
      f"30 дней: {len(request_times)} тихих проверок, раз в сутки")
wgaps = [b[0] - a[0] for a, b in zip(offered_at, offered_at[1:])]
check(bool(offered_at) and offered_at[0][0] - NOW >= upr.DELAY and all(g >= upr.DELAY for g in wgaps)
      and 8 <= len(offered_at) <= 10,
      f"30 дней: окно не при проверке, а через 3 дня, «Позже» ещё на 3 дня: {len(offered_at)} раз")
check(all(v == f"2.0.{(t - NOW).days + 1}" for t, v in offered_at), "каждый раз предложена самая новая версия")
check(not any(ui.critical), "обычные версии предлагаются как обычные")

# disabled: no request at all, but the button still works
u, ctx, ui, ch, clock = make(config={"update_check": False})
for hour in range(0, 20 * 24, 6):
    clock.now = NOW + timedelta(hours=hour)
    u.tick()
check(ch.requests == 0, "проверка выключена: ни одного запроса к каналу за 20 дней")
check(u.check_now(manual=True) and ch.requests == 2 and ui.offers == ["2.0.1"],
      "проверка выключена: кнопка «Проверить обновления» работает сразу")

# manual check right after an automatic one
u, ctx, ui, ch, clock = make()
u.tick()
clock.now += timedelta(minutes=5)
u.tick()
check(ch.requests == 2 and len(ui.offers) == 0, "автопроверка: второй раз через 5 минут не ходит, окна нет (1.32: колокольчик)")
check(u.check_now(manual=True) and len(ui.offers) == 1, "ручная проверка сразу после автоматической показывает окно")
u, ctx, ui, ch, clock = make(installed="2.0.1")
u.check_now(manual=True)
check(ui.infos and "2.0.1" in ui.infos[-1] and not ui.offers, "ручная проверка: «у вас последняя версия»")

# skip / later / rollback memory / errors
u, ctx, ui, ch, clock = make(answer="skip")
u.check_now(manual=True)
check(ctx.config["update_skipped"] == ["2.0.1"], "«Пропустить эту версию» запоминается")
check(ctx.config["update_last_seen_version"] == "2.0.1", "последняя виденная версия запоминается")
ch.publish("2.0.0")
clock.now += timedelta(days=8)
u.check_now(manual=True)
check(not ui.offers[1:] and ui.infos and ui.infos[-1] == up.error_text("rollback") and not ui.errors,
      "подсунутый старый latest.json после виденного 2.0.1: без окна, свой текст об откате (P2-10)")
check(up.ERROR_KEYS["rollback"] != up.ERROR_KEYS["bad_signature"] != up.ERROR_KEYS["expired"]
      and "подпис" not in tr("updater.error.rollback").lower() and "подпис" not in tr("updater.error.expired").lower(),
      "тексты отката и срока не про подпись (P2-10)")
for _code, _when in (("expired", NOW - timedelta(days=30)), ("expires_far", NOW + timedelta(days=400))):
    u, ctx, ui, ch, clock = make()
    ch.doc = document(expires=_when)
    ch.sig = signed(ch.doc)
    u.check_now(manual=True)
    check(ui.errors == [up.error_text("expired")] and up.ERROR_KEYS[_code] == "updater.error.expired",
          f"срок ({_code}): текст про дату и часы компьютера (P2-10)")
u, ctx, ui, ch, clock = make()
ch.fail = urllib.error.URLError("offline")
u.check_now(manual=True)
check(len(ui.errors) == 1 and not ui.offers, "нет сети: понятное сообщение, окна нет")
u, ctx, ui, ch, clock = make()
ch.sig = b""
u.check_now(manual=False)
check(not ui.offers and not ui.errors, "неподписанный канал при автопроверке: молча, без окна")
u, ctx, ui, ch, clock = make()
ch.publish("2.0.1", min_version="2.0.0")
u2, ctx2, ui2, _, _ = make(installed="1.99", channel=ch)
u2.check_now(manual=True)
check(ui2.infos and ui2.infos[0] == ("manual", "2.0.1") and not ui2.offers, "min_version выше установленной: скачать с сайта")

# dev copy, Store, unsupported
check(up.install_kind() == "dev", "запуск из исходников: рабочая копия разработчика")
u, ctx, ui, ch, clock = make(kind="dev")
u.tick()
u.check_now(manual=True)
check(ch.requests == 0 and len(ui.infos) == 1, "рабочая копия: обновления выключены, по кнопке пояснение")
u, ctx, ui, ch, clock = make(kind="store")
u.tick()
u.check_now(manual=True)
check(ch.requests == 0 and len(ui.urls) == 1, "версия из Store: в канал не ходит, кнопка открывает магазин")


# --- urgent security fix ("critical": true, the owner's decision 03.11.2026) ---------------------------------------
up.drop_critical("stable")
recent = {"last_update_check": up.uc.format_utc(NOW - timedelta(days=1)),
          "update_last_notified": up.uc.format_utc(NOW - timedelta(days=1))}   # ordinary window closed for 6 days
u, ctx, ui, ch, clock = make(config=dict(recent))
ch.publish("2.0.1", critical=True)
u.tick()
check(ui.offers == ["2.0.1"] and ui.critical == [True],
      "исправление безопасности: предложено сразу при проверке, которая его нашла (без ожидания 7 дней)")
check(up.critical_path("stable").is_file(), "исправление безопасности: подписанный документ сохранён для напоминаний")
ch.publish("2.0.1", critical=True)
clock.now += timedelta(hours=5)
u.tick()
check(len(ui.offers) == 1, "то же исправление в том же запуске раньше чем через сутки: окно не повторяется")
clock.now = NOW + timedelta(days=1, minutes=1)
u.tick()
check(ui.offers == ["2.0.1", "2.0.1"] and ui.critical == [True, True],
      "программа работает дальше: напоминание об исправлении безопасности раз в сутки")
# "Later", then the next start of the program: offered again 60 s after start, no 24 h wait
_req = ch.requests
r_u, r_ctx, r_ui, _, r_clock = make(config=dict(ctx.config), channel=ch, clock=Clock(clock.now + timedelta(hours=1)))
r_u.tick()
check(r_ui.offers == ["2.0.1"] and r_ui.critical == [True] and ch.requests == _req,
      "следующий запуск в те же сутки: исправление предложено снова из сохранённой копии, без запроса к каналу")
_req = ch.requests
r2_u, _, r2_ui, _, _ = make(config=dict(r_ctx.config), channel=ch, clock=Clock(clock.now + timedelta(days=1, hours=1)))
r2_u.tick()
check(r2_ui.offers == ["2.0.1"] and r2_ui.critical == [True] and ch.requests == _req + 2,
      "следующий запуск через сутки: свежий документ канала и снова окно исправления")
# skip is not possible for a security fix: it comes back on the next start
s_u, s_ctx, s_ui, _, _ = make(config=dict(r_ctx.config), channel=ch, answer="skip",
                              clock=Clock(r_clock.now + timedelta(hours=1)))
s_u.tick()
check(s_ui.offers == ["2.0.1"] and "2.0.1" not in (s_ctx.config.get("update_skipped") or []),
      "«Пропустить» для исправления безопасности не запоминается")
s2_u, _, s2_ui, _, _ = make(config=dict(s_ctx.config), channel=ch, clock=Clock(r_clock.now + timedelta(hours=2)))
s2_u.tick()
check(s2_ui.offers == ["2.0.1"], "после «Пропустить» исправление возвращается при следующем запуске")
# a newer ordinary version while the fix is not installed: urgent too (it contains the fix)
ch.publish("2.0.2")
n_u, n_ctx, n_ui, _, _ = make(config=dict(s_ctx.config), channel=ch, clock=Clock(r_clock.now + timedelta(days=3)))
n_u.tick()
check(n_ui.offers == ["2.0.2"] and n_ui.critical == [True],
      "новая обычная версия, пока исправление не установлено: тоже предлагается сразу как срочная")
# automatic check off: no request, the verified saved copy is offered at start
_req = ch.requests
o_u, _, o_ui, _, _ = make(config={**s_ctx.config, "update_check": False}, channel=ch,
                          clock=Clock(r_clock.now + timedelta(hours=4)))
o_u.tick()
check(o_ui.offers == ["2.0.1"] and o_ui.critical == [True] and ch.requests == _req,
      "автопроверка выключена: исправление предложено из сохранённой подписанной копии, без запроса к каналу")
# offline at start: offered from the saved copy
ch.fail = urllib.error.URLError("offline")
f_u, _, f_ui, _, _ = make(config=dict(s_ctx.config), channel=ch, clock=Clock(r_clock.now + timedelta(days=3)))
f_u.tick()
check(f_ui.offers == ["2.0.1"] and f_ui.critical == [True] and not f_ui.errors,
      "нет сети при запуске: исправление предложено из сохранённой копии, без сообщения об ошибке")
ch.fail = None
# installed: the saved copy goes away, nothing urgent any more
i_u, _, i_ui, _, _ = make(installed="2.0.1", config=dict(s_ctx.config), channel=ch,
                          clock=Clock(r_clock.now + timedelta(hours=6)))
check(up.pending_critical("stable", "2.0.1", NOW, **KEYS) is None and not up.critical_path("stable").exists(),
      "исправление установлено: сохранённая копия удалена")
ch.publish("2.0.2")
i_u.tick()
check(not i_ui.offers, "после установки исправления обычная версия снова ждёт недельного окна")

# review R04b P1-2: the saved fix expired and no network: at most one request to the channel per 24 h
up.drop_critical("stable")
_d = document(version="2.0.1", critical=True, expires=NOW - timedelta(days=5))
up.save_critical("stable", _d, signed(_d))
u, ctx, ui, ch, clock = make()
ch.fail = urllib.error.URLError("offline")
for _h in range(30):
    u.tick()
    clock.now += timedelta(hours=1)
check(ch.requests == 2 and not ui.offers,
      f"просроченная копия, нет сети: {ch.requests} запроса за 30 часов (раз в сутки, не каждый час)")
ch.fail = None
ch2 = Channel()
ch2.doc, ch2.sig = _d, signed(_d)   # a frozen channel serves the expired document
u2, _, ui2, _, clock2 = make(channel=ch2)
for _h in range(6):
    u2.tick()
    clock2.now += timedelta(hours=1)
check(ch2.requests == 2 and not ui2.offers, f"канал отдаёт просроченный документ: {ch2.requests} обращения за 6 часов (один запрос)")
up.drop_critical("stable")

# critical is trusted only from a signed document
up.drop_critical("stable")
u, ctx, ui, ch, clock = make(config=dict(recent))
ch.publish("2.0.1", critical=True)
ch.sig = b""
u.tick()
check(not ui.offers and not up.critical_path("stable").exists(), "неподписанный документ с critical: окна нет, ничего не сохранено")
u, ctx, ui, ch, clock = make(config=dict(recent))
ch.publish("2.0.1")
ch.doc = ch.doc.replace(b'"version": "2.0.1",', b'"version": "2.0.1",\n  "critical": true,')
u.tick()
check(b'"critical": true' in ch.doc and not ui.offers and not up.critical_path("stable").exists(),
      "critical, дописанный после подписи: документ отвергнут, окна нет")
u, ctx, ui, ch, clock = make(config=dict(recent))
ch.publish("2.0.1", key="test", critical=True)
u.tick()
check(not ui.offers and not up.critical_path("stable").exists(), "critical, подписанный тестовым ключом: в основном канале отвергнут")
# a saved copy changed on disk: rejected and deleted, nothing offered
_d = document(version="2.0.1", critical=True)
up.save_critical("stable", _d, signed(_d))
check(up.pending_critical("stable", "2.0.0", NOW, **KEYS) is not None, "сохранённая копия с верной подписью принимается")
up.critical_path("stable").write_bytes(_d.replace(b"2.0.1", b"2.0.9"))
t_u, _, t_ui, t_ch, _ = make(config={**recent, "update_check": False})
t_u.tick()
check(not t_ui.offers and not up.critical_path("stable").exists(),
      "сохранённая копия изменена на диске: подпись не сходится, копия удалена, окна нет")
_d = document(version="2.0.1")   # validly signed, but not critical: never urgent
up.save_critical("stable", _d, signed(_d))
check(up.pending_critical("stable", "2.0.0", NOW, **KEYS) is None and not up.critical_path("stable").exists(),
      "сохранённая копия без critical: не срочная, удалена")
up.drop_critical("stable")

# --- downloads over a local HTTP server -----------------------------------------------------
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = PAYLOAD
        if self.path == "/broken.bin":
            body = PAYLOAD[:-1] + b"X"
        if self.path == "/missing.bin":
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(PAYLOAD)))
        self.end_headers()
        if self.path == "/cut.bin":
            self.wfile.write(body[: len(body) // 2])
            self.wfile.flush()
            self.connection.shutdown(2)
            return
        self.wfile.write(body)


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


server = Server(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
local_http = f"http://127.0.0.1:{server.server_address[1]}"
base = "https://clipsd-test.invalid"   # signed addresses are https; the test opener serves them locally


def local_opener(req, timeout):
    return urllib.request.urlopen(req.full_url.replace(base, local_http), timeout=timeout)


def fetch_local(url, *a, **kw):
    return up.download_file(url, *a, opener=local_opener, **kw)


dl = tmp / "dl"
seen = []
path = fetch_local(f"{base}/good.bin", dl / "good.bin", len(PAYLOAD), PAYLOAD_SHA,
                        progress=lambda d, t: seen.append(d))
check(path.read_bytes() == PAYLOAD and seen and seen[-1] == len(PAYLOAD), "загрузка: файл цел, полоса дошла до 100%")
check(raises(lambda: fetch_local(f"{base}/broken.bin", dl / "b.bin", len(PAYLOAD), PAYLOAD_SHA), "bad_checksum")
      and not list(dl.glob("b.bin*")), "битая сумма файла: ошибка, файл удалён")
check(raises(lambda: fetch_local(f"{base}/cut.bin", dl / "c.bin", len(PAYLOAD), PAYLOAD_SHA), "interrupted")
      and not list(dl.glob("c.bin*")), "обрыв загрузки: ошибка, недокачанный файл удалён")
check(raises(lambda: fetch_local(f"{base}/good.bin", dl / "s.bin", len(PAYLOAD) - 10, PAYLOAD_SHA), "size_mismatch")
      and not list(dl.glob("s.bin*")), "размер больше заявленного: ошибка, файл удалён")
check(raises(lambda: fetch_local(f"{base}/missing.bin", dl / "m.bin", len(PAYLOAD), PAYLOAD_SHA), "network")
      and not list(dl.glob("m.bin*")), "файла нет на сервере (404): ошибка, ничего не осталось")
check(raises(lambda: fetch_local(f"{base}/good.bin", dl / "n.bin", 10 ** 15, PAYLOAD_SHA), "no_space"),
      "нет места на диске: ошибка до начала загрузки")
cancel = threading.Event()
cancel.set()
check(raises(lambda: fetch_local(f"{base}/good.bin", dl / "x.bin", len(PAYLOAD), PAYLOAD_SHA, cancel=cancel),
             "cancelled") and not list(dl.glob("x.bin*")), "отмена загрузки: файл удалён")


for _url in (f"{local_http}/good.bin", "file:///etc/hostname", "ftp://example.com/x"):
    check(raises(lambda: up.download_file(_url, dl / "h.bin", len(PAYLOAD), PAYLOAD_SHA), "bad_url")
          and not list(dl.glob("h.bin*")), f"загрузка не по https отвергнута: {_url.split(':')[0]}")
try:
    up.http_get(f"{local_http}/good.bin", 10 ** 6)
    _ok = False
except urllib.error.URLError:
    _ok = True
check(_ok, "запрос канала не по https отвергнут")
_redir = up.HttpsOnlyRedirect()
try:
    _redir.redirect_request(urllib.request.Request("https://a.example/x"), None, 302, "Found", {}, "http://b.example/x")
    _ok = False
except urllib.error.URLError:
    _ok = True
check(_ok, "перенаправление с https на http отвергнуто")


# --- Linux package, switch helper ------------------------------------------------------------
def make_package(version, evil=False):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        def add(name, data, mode=0o644):
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), mode
            tar.addfile(info, io.BytesIO(data))
        add(f"clipsd-{version}/clipsd-switch", b"#!/bin/sh\nexit 0\n", 0o755)
        add(f"clipsd-{version}/ClipSD", b"binary")
        if evil:
            add("../evil.txt", b"x")
    return buf.getvalue()


versions = up.versions_dir()
pkg = tmp / "pkg.tar.gz"
pkg.write_bytes(make_package("2.0.1"))
folder = up.extract_linux_package(pkg, versions, "2.0.1")
check(folder == versions / "2.0.1" and (folder / "clipsd-switch").is_file() and os.access(folder / "clipsd-switch", os.X_OK),
      "Linux: архив распакован в versions/2.0.1, помощник исполняемый")
check(not [p for p in versions.iterdir() if p.name.startswith(".")], "Linux: временных папок не осталось")
pkg.write_bytes(make_package("2.0.2", evil=True))
check(raises(lambda: up.extract_linux_package(pkg, versions, "2.0.2"), "bad_package")
      and not (versions.parent / "evil.txt").exists() and not (versions / "2.0.2").exists(),
      "Linux: архив с путём «..» отвергнут, ничего не распаковано")
calls = []
how = up.launch_linux_switch(folder, "2.0.0", "2.0.1", "abcdef1234567890",
                             run=lambda cmd, **kw: calls.append(("run", cmd)) or type("R", (), {"returncode": 0})(),
                             popen=lambda cmd, **kw: calls.append(("popen", cmd, kw)), systemd=True)
if LINUX:
    check(how == "systemd-run" and calls[0][1][:4] == ["systemd-run", "--user", "--collect", "--quiet"]
          and calls[0][1][-7:] == [str(folder / "clipsd-switch"), "--from", "2.0.0", "--to", "2.0.1",
                                   "--socket", str(tmp / "runtime" / "clipshot.sock")],
          "Linux: помощник через systemd-run --user --collect, сокет программы передан")
    _sr = calls[0][1]
    check(f"--setenv=XDG_STATE_HOME={tmp / 'state'}" in _sr and f"--setenv=XDG_DATA_HOME={tmp / 'data'}" in _sr
          and f"--setenv=XDG_CONFIG_HOME={tmp / 'config'}" in _sr and f"--setenv=XDG_RUNTIME_DIR={tmp / 'runtime'}" in _sr
          and f"--setenv=HOME={os.path.expanduser('~')}" in _sr and _sr.index("--setenv=HOME=" + os.path.expanduser("~")) < _sr.index(str(folder / "clipsd-switch")),
          "Linux: systemd-run получает HOME и папки XDG программы (--setenv, P2-8)")
else:
    skip("Linux: помощник через systemd-run --user --collect, сокет программы передан")
    skip("Linux: systemd-run получает HOME и папки XDG программы (--setenv, P2-8)")
calls.clear()
how = up.launch_linux_switch(folder, "2.0.0", "2.0.1", "abcdef", run=None,
                             popen=lambda cmd, **kw: calls.append(("popen", cmd, kw)), systemd=False)
check(how == "setsid" and calls[0][2].get("start_new_session") is True and calls[0][1][0].endswith("clipsd-switch"),
      "Linux без systemd: помощник в новом сеансе (setsid)")
check(up.windows_command(Path("C:/t/ClipSD-2.0.1-Setup.exe"), "de")[1:] ==
      ["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/LANG=de", "/UPDATE=1"], "Windows: ключи установщика")
shutil.rmtree(versions / "2.0.1")

# --- whole path: offer -> download -> install -> next start -------------------------------------
pkg_bytes = make_package("2.0.1")
pkg_sha = hashlib.sha256(pkg_bytes).hexdigest()


class PkgHandler(Handler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(pkg_bytes)))
        self.end_headers()
        self.wfile.write(pkg_bytes)


pkg_server = Server(("127.0.0.1", 0), PkgHandler)
threading.Thread(target=pkg_server.serve_forever, daemon=True).start()
pkg_url = f"http://127.0.0.1:{pkg_server.server_address[1]}/clipsd-2.0.1-linux.tar.gz"

events = []
up.telemetry_event = lambda name, **f: events.append((name, f))
switches = []
real_switch = up.launch_linux_switch
up.launch_linux_switch = lambda folder, a, b, attempt: switches.append((folder, a, b)) or "setsid"
u, ctx, ui, ch, clock = make(answer="update")
ch.doc = document(files={"linux": {"url": "https://example.invalid/x.tar.gz", "size": len(pkg_bytes), "sha256": pkg_sha}})
ch.sig = signed(ch.doc)
# the signed URL is https; the test opener sends it to the local server instead
u.opener = lambda req, timeout: urllib.request.urlopen(pkg_url, timeout=timeout)
u.check_now(manual=True)
record = up.read_attempt(up.attempt_path())
check(switches and switches[0][0] == up.versions_dir() / "2.0.1" and switches[0][1:] == ("2.0.0", "2.0.1"),
      "обновление: архив скачан, распакован, помощник вызван с --from 2.0.0 --to 2.0.1")
check(record and record["from"] == "2.0.0" and record["to"] == "2.0.1" and len(record["trace_id"]) == 32
      and len(record["attempt_id"]) == 32 and record["time"].endswith("Z"), "update-attempt.json записан")
check([e[0] for e in events] == ["update_started"], "событие «обновление начато»")
check(not list(up.attempt_path().parent.glob("*.tmp")), "атомарная запись: временных файлов нет")

events.clear()
nu, nctx, nui, _, nclock = make(installed="2.0.1", clock=Clock(NOW + timedelta(minutes=1)))
check(nu.check_previous_attempt() == "completed" and nui.news and NOTES_SHOWN in nui.news[0][1],
      "новая версия: «Что нового» на языке программы")
check([e[0] for e in events] == ["update_completed"] and events[0][1]["trace_id"] == record["trace_id"],
      "событие «обновление завершено» с тем же trace_id")
check(not up.attempt_path().exists() and not up.downloads_dir().exists(), "после успеха попытка и загрузка убраны")
nu2, _, nui2, _, _ = make(installed="2.0.1")
check(nu2.check_previous_attempt() == "none" and not nui2.news, "«Что нового» показывается один раз")

# failure: still the old version 10 minutes later
up.write_attempt(up.attempt_path(), "2.0.0", "2.0.1", NOW)
(up.versions_dir() / "2.0.1").mkdir(parents=True, exist_ok=True)
(up.downloads_dir() / "2.0.1").mkdir(parents=True, exist_ok=True)
events.clear()
fu, _, fui, _, fclock = make(installed="2.0.0", clock=Clock(NOW + timedelta(minutes=3)))
check(fu.check_previous_attempt() == "pending" and up.attempt_path().exists(), "через 3 минуты: ещё ждём")
fclock.now = NOW + timedelta(minutes=11)
check(fu.check_previous_attempt() == "failed" and fui.errors, "через 11 минут старая версия: сообщение")
check([e[0] for e in events] == ["update_failed"] and events[0][1]["reason"] == "not_switched",
      "событие «обновление не удалось»")
check(not (up.versions_dir() / "2.0.1").exists() and (up.downloads_dir() / "2.0.1").is_dir() and not up.attempt_path().exists(),
      "после сбоя распакованная версия удалена, скачанный архив оставлен для «Повторить» (1.31.2)")
up._rmtree(up.downloads_dir())

# download failure in the full path: damaged file
up.launch_linux_switch = real_switch
events.clear()
u, ctx, ui, ch, clock = make(answer="update")
ch.doc = document(files={"linux": {"url": "https://example.invalid/x.tar.gz", "size": len(pkg_bytes), "sha256": "1" * 64}})
ch.sig = signed(ch.doc)
u.opener = lambda req, timeout: urllib.request.urlopen(pkg_url, timeout=timeout)
u.check_now(manual=True)
check(ui.errors and not up.attempt_path().exists() and not up.downloads_dir().exists() and not u.busy,
      "битый файл в полном пути: сообщение, ничего не установлено и не осталось")
check(events and events[0][0] == "update_failed" and events[0][1]["reason"] == "bad_checksum",
      "событие «не удалось» с причиной bad_checksum")


# --- P0/P1/P2 of the code review: deferred switch, bound results, marks, channels ----------------------
# seen version per channel
c2 = {}
up.remember_seen(c2, "2.0.9", "test")
check(c2.get("update_last_seen_version_test") == "2.0.9" and not c2.get("update_last_seen_version"),
      "последняя виденная версия тестового канала не влияет на основной")
up.remember_seen(c2, "2.0.3", "stable")
check(c2["update_last_seen_version"] == "2.0.3" and c2["update_last_seen_version_test"] == "2.0.9",
      "каналы помнят версии раздельно")
tdoc = document(version="2.0.4", channel="test")
tch = Channel()
tch.doc, tch.sig = tdoc, signed(tdoc, "test")
check(up.fetch_manifest("test", {"update_last_seen_version": "2.0.9"}, NOW, tch, **KEYS).version == "2.0.4",
      "основной канал видел 2.0.9: тестовый 2.0.4 не считается откатом")
check(raises(lambda: up.fetch_manifest("test", {"update_last_seen_version_test": "2.0.9"}, NOW, tch, **KEYS),
             "rollback"), "тестовый канал видел 2.0.9: 2.0.4 отвергнут")

# helper / launcher result bound to the attempt
rec = up.write_attempt(up.attempt_path(), "2.0.0", "2.0.1", NOW)
res_path = up.mark_dir() / "update-result.json"
res_path.parent.mkdir(parents=True, exist_ok=True)


def put_result(**kw):
    data = {"from": "2.0.0", "to": "2.0.1", "result": "rolled_back", "reason": "x",
            "time": "2026-11-02T14:05:00+02:00"}   # 12:05 UTC, helper writes date -Is with an offset
    data.update(kw)
    res_path.write_text(json.dumps(data))


put_result()
check(up.switch_result(rec).get("result") == "rolled_back", "результат помощника этой попытки принят")
put_result(to="2.0.2")
check(up.switch_result(rec) == {}, "результат о другой версии не принят")
put_result(time="2026-10-30T10:00:00Z")
check(up.switch_result(rec) == {}, "результат старше попытки не принят")
put_result()
(up.versions_dir() / "2.0.1").mkdir(parents=True, exist_ok=True)
events.clear()
bu, _, bui, _, _ = make(installed="2.0.0", clock=Clock(NOW + timedelta(minutes=3)))
check(bu.check_previous_attempt() == "failed" and bui.errors and not up.attempt_path().exists()
      and not (up.versions_dir() / "2.0.1").exists(), "откат помощника: сообщение сразу, без 10 минут ожидания")
check(events and events[0][0] == "update_failed" and events[0][1]["reason"] == "x", "событие с причиной помощника")
res_path.unlink()
# reasons are codes: a phrase of an old helper does not reach the statistics (P2-1)
for _reason, _sent in (("no_start_mark", "no_start_mark"), ("no start mark within 60s", "unknown")):
    up.write_attempt(up.attempt_path(), "2.0.0", "2.0.1", NOW)
    put_result(reason=_reason)
    events.clear()
    ru, _, _, _, _ = make(installed="2.0.0", clock=Clock(NOW + timedelta(minutes=3)))
    ru.check_previous_attempt()
    check(events and events[0][1]["reason"] == _sent, f"причина помощника «{_reason}» -> «{_sent}» в статистике")
res_path.unlink()

# deferred switch on Linux: an editor with unsaved changes blocks quitting
blocker = ["unsaved"]
switches.clear()
up.launch_linux_switch = lambda folder, a, b, attempt: switches.append((folder, a, b)) or "setsid"


class BusyUI(UI):
    def __init__(self, answer="later"):
        super().__init__(answer)
        self.notices = []

    def notice(self, text):
        self.notices.append(text)


events.clear()
u, ctx, ui, ch, clock = make(answer="update")
ui = u.ui = BusyUI("update")
ctx.quit_blocker = lambda: blocker[0]
ch.doc = document(files={"linux": {"url": "https://example.invalid/x.tar.gz", "size": len(pkg_bytes), "sha256": pkg_sha}})
ch.sig = signed(ch.doc)
u.opener = lambda req, timeout: urllib.request.urlopen(pkg_url, timeout=timeout)
u.check_now(manual=True)
qapp.processEvents()
record = up.read_attempt(up.attempt_path())
check(not switches and record and record.get("deferred") is True and record.get("deferred_reason") == "unsaved",
      "несохранённый редактор: помощник не запущен, попытка отложена")
check((up.versions_dir() / "2.0.1" / "clipsd-switch").is_file(), "новая версия распакована и ждёт")
check(ui.notices and ui.notices[0] == tr("updater.wait.unsaved", version="2.0.1"), "сообщение «установится, когда вы закроете редактор»")
check([e[0] for e in events] == ["update_started", "update_deferred"], "события: начато, отложено")
check(u.deferred_tick() is False and not switches, "редактор ещё открыт: переключения нет")
_req = ch.requests
ui.infos.clear()
check(u.check_now(manual=True) is False and ch.requests == _req and ui.infos
      and ui.infos[-1] == tr("updater.wait.unsaved", version="2.0.1"),
      "«Проверить обновления» при отложенном: «Обновление до 2.0.1 ждёт, когда вы закроете редактор» (P2-6)")
clock.now = NOW + timedelta(minutes=30)
check(u.check_previous_attempt() == "deferred" and up.attempt_path().exists() and not ui.errors,
      "через 30 минут отложенная попытка не считается сбоем")
blocker[0] = ""
check(u.deferred_tick() is True and switches and switches[-1][1:] == ("2.0.0", "2.0.1"),
      "редактор закрыт: помощник запущен")
check(up.read_attempt(up.attempt_path()).get("tries") == 1, "попытки переключения считаются")
# the helper deferred again (program answered busy): bound result "deferred" keeps the attempt
up.write_json_atomic(res_path, {"from": "2.0.0", "to": "2.0.1", "result": "deferred", "reason": "busy",
                                "time": up.uc.format_utc(NOW + timedelta(minutes=31))})
u2, _, u2ui, _, _ = make(installed="2.0.0", clock=Clock(NOW + timedelta(minutes=32)))
u2.ctx.quit_blocker = lambda: "unsaved"
check(u2.check_previous_attempt() == "deferred" and not u2ui.errors and up.attempt_path().exists(),
      "результат помощника «отложено»: попытка сохраняется, ошибки нет")
res_path.unlink()
# next start of the old version, nothing open: the switch goes at once
switches.clear()
u3, _, _, _, _ = make(installed="2.0.0", clock=Clock(NOW + timedelta(days=1)))
check(u3.check_previous_attempt() == "deferred", "следующий запуск: попытка всё ещё отложена")
qapp.processEvents()
check(switches and switches[-1][1:] == ("2.0.0", "2.0.1"), "следующий запуск старой версии: переключение сразу")
# the new version after a deferred switch: What's new and "completed"
events.clear()
nu, _, nui, _, _ = make(installed="2.0.1", clock=Clock(NOW + timedelta(days=1)))
check(nu.check_previous_attempt() == "completed" and nui.news and events[0][0] == "update_completed"
      and events[0][1].get("deferred") is True, "после отложенного переключения: «Что нового» и событие «завершено»")
# too many tries: give up, clean up
up.write_attempt(up.attempt_path(), "2.0.0", "2.0.1", NOW)
r5 = up.read_attempt(up.attempt_path())
r5.update(deferred=True, tries=up.MAX_SWITCH_TRIES)
up.write_json_atomic(up.attempt_path(), r5)
(up.versions_dir() / "2.0.1").mkdir(parents=True, exist_ok=True)
(up.versions_dir() / "2.0.1" / "clipsd-switch").write_text("#!/bin/sh\n")
switches.clear()
u4, _, u4ui, _, _ = make(installed="2.0.0")
check(u4.deferred_tick() is False and not switches and u4ui.errors and not up.attempt_path().exists()
      and not (up.versions_dir() / "2.0.1").exists(), "больше 5 попыток: сообщение, попытка и папка убраны")
# note_deferred from the program (Windows launcher or helper got "busy")
up.write_attempt(up.attempt_path(), "2.0.0", "2.0.1", NOW)
wu, _, wui, _, _ = make(kind="windows", installed="2.0.0", clock=Clock(NOW + timedelta(minutes=1)))
wu.ui = BusyUI()
wu.note_deferred("text")
qapp.processEvents()
check(up.read_attempt(up.attempt_path()).get("deferred") is True and wu.ui.notices,
      "ответ busy: попытка помечена отложенной, сообщение показано")
_unlink = up._unlink
_unlink(up.attempt_path())
wu.note_deferred("text")
check(not up.attempt_path().exists(), "busy без попытки этой программы: ничего не записано")

# unpacking off the interface thread
up.launch_linux_switch = lambda folder, a, b, attempt: switches.append((folder, a, b)) or "setsid"
seen_threads = []
real_extract = up.extract_linux_package


def extract_spy(*a, **kw):
    seen_threads.append(threading.current_thread() is threading.main_thread())
    return real_extract(*a, **kw)


up.extract_linux_package = extract_spy
_rmtree = up._rmtree
_rmtree(up.versions_dir() / "2.0.1")
tu, tctx, tui, _, _ = make()
tu.sync = False
archive = tmp / "thread-pkg.tar.gz"
archive.write_bytes(pkg_bytes)
switches.clear()
tu.install(archive, up.uc.parse_manifest(ch.doc, "stable"), "t" * 32)
import time as _time  # noqa: E402
end = _time.time() + 10
while not switches and _time.time() < end:
    qapp.processEvents()
    _time.sleep(0.02)
check(seen_threads == [False] and switches, "архив распакован в рабочем потоке, помощник запущен после")
up.extract_linux_package = real_extract
up.launch_linux_switch = real_switch
_unlink(up.attempt_path())

# start marks and previous
mu, _, _, _, _ = make(kind="windows", installed="2.0.1")
root = tmp / "winapp"
(root / "app").mkdir(parents=True)
(root / "previous").mkdir()
(root / "failed").mkdir()
(root / "ClipSD.exe").write_text("launcher")
real_root = up.windows_app_root
up.windows_app_root = lambda: root
mu.remove_previous()
check((root / "previous").exists(), "Windows: без своей отметки previous не удаляется")
(up.mark_dir() / "started-2.0.0").write_text("{}")
mu.mark_started()
check((up.mark_dir() / "started-2.0.1").exists() and not (up.mark_dir() / "started-2.0.0").exists(),
      "Windows: отметка started-2.0.1 записана, отметки других версий убраны")
mu.remove_previous()
check(not (root / "previous").exists() and not (root / "failed").exists(), "Windows: после отметки previous удалён")
up.windows_app_root = real_root
real_exe = up.sys.executable
(root / "app" / "ClipSD-app.exe").write_text("x")
up.sys.executable = str(root / "app" / "ClipSD-app.exe")
# windows_app_root() resolves the path (Windows: 8.3 short names in %TEMP% expand), so compare resolved
check(up.windows_app_root() == root.resolve(), "раскладка {app}\\\\app с запускателем узнаётся")
(root / "ClipSD.exe").unlink()
check(up.windows_app_root() is None, "без запускателя рядом: не раскладка установщика (обновление выключено)")
up.sys.executable = str(tmp / "ClipSD-app.exe")
check(up.windows_app_root() is None, "exe не в папке app: не раскладка установщика")
up.sys.executable = real_exe
lu, _, _, _, _ = make(kind="linux", installed="2.0.1")
lu.mark_started()
if LINUX:
    check((tmp / "state" / "clipsd" / "started-2.0.1").exists(), "Linux: отметка в ~/.local/state/clipsd/started-<версия>")
else:
    skip("Linux: отметка в ~/.local/state/clipsd/started-<версия>")
# the mark goes as soon as the event loop runs (not 15 s later), once (P2-5)
for _kind, _ver in (("linux", "2.0.3"), ("windows", "2.0.4")):
    tu5, _, _, _, _ = make(kind=_kind, installed=_ver)
    tu5.check_previous_attempt = tu5.tick = tu5.remove_previous = lambda: None
    _mark = up.mark_dir() / f"started-{_ver}"
    tu5.start_timers()
    tu5.timer.stop()
    check(not _mark.exists(), f"{_kind}: до цикла событий отметки ещё нет")
    qapp.processEvents()
    check(_mark.exists(), f"{_kind}: отметка started-{_ver} сразу после запуска цикла событий (P2-5)")
    _mark.unlink()
    tu5.mark_started()
    check(not _mark.exists(), f"{_kind}: отметка пишется один раз (при выходе повторно не нужна)")
if LINUX:
    up.write_json_atomic(up.mark_dir() / "started-2.0.1", {})
    du, _, _, _, _ = make(kind="dev", installed="2.0.1")
    du.mark_started()
    check((tmp / "state" / "clipsd" / ".source-run").exists() and not list((tmp / "state" / "clipsd").glob("started-2.0.1.*")),
          "запуск из исходников: только отметка .source-run для uninstall.sh (P2-12)")
else:
    skip("запуск из исходников: только отметка .source-run для uninstall.sh (P2-12)")

# local channel: never a shared /tmp/clipsd.sock
from clipshot import ipc  # noqa: E402
if os.name == "nt":
    # Windows: a per-user pipe name for QLocalServer, the same the launcher builds; not a file path
    # the same rule as on Linux: the package (sys.frozen) listens on clipsd-<SID>, the sources on clipshot-<SID>
    sid = ipc.windows_user_id()
    frozen = getattr(sys, "frozen", False)
    name = ipc.socket_path()
    want = ("clipsd-" if frozen else "clipshot-") + sid
    check(name == want and sid and not any(c in name for c in "\\/:"),
          f"Windows: канал команд — именованный канал {'clipsd' if frozen else 'clipshot'}-<SID пользователя> ({name})")
    sys.frozen = True
    check(ipc.socket_path() == "clipsd-" + sid, "Windows, готовая сборка: канал clipsd-<SID>, как у запускателя")
    if frozen:
        sys.frozen = frozen
    else:
        del sys.frozen
    skip("сокет в XDG_RUNTIME_DIR; без XDG_RUNTIME_DIR личная папка 0700")
else:
    frozen = getattr(sys, "frozen", False)
    own = "clipsd.sock" if frozen else "clipshot.sock"
    check(ipc.socket_path() == str(tmp / "runtime" / own), f"{'готовая сборка' if frozen else 'из исходников'}: сокет {own} в XDG_RUNTIME_DIR")
    sys.frozen = True
    check(ipc.socket_path() == str(tmp / "runtime" / "clipsd.sock"), "готовая сборка: сокет clipsd.sock")
    if frozen:
        sys.frozen = frozen
    else:
        del sys.frozen
    saved_runtime = os.environ.pop("XDG_RUNTIME_DIR")
    path = ipc.socket_path()
    check(path == str(tmp / "cache" / "clipsd" / "clipshot.sock") and oct(os.stat(tmp / "cache" / "clipsd").st_mode & 0o777) == "0o700",
          "без XDG_RUNTIME_DIR: личная папка с правами 0700, не /tmp/clipsd.sock")
    os.environ["XDG_RUNTIME_DIR"] = saved_runtime
check(ipc.command_from_args(["--quit-for-update"]) == "quit-for-update", "команда --quit-for-update для помощника")
check(ipc.request("quit-for-update", 0.5, str(tmp / "runtime" / "missing.sock")) is None,
      "нет запущенной копии: request возвращает None")

# --- preview build ("проба"): local channel folder, its own key, release builds refuse it ------------
from clipshot import build_info  # noqa: E402
PROBA_PUB = cs.keygen(keys / "proba.pem")
PRIV["proba"] = cs.load_private(keys / "proba.pem")
proba_pkg = make_package("2.0.1")
proba_sha = hashlib.sha256(proba_pkg).hexdigest()
PROBA_NAME = "ClipSD-2.0.1-proba-linux-x86_64.tar.gz"


def proba_document(version="2.0.1", url=PROBA_NAME, channel="proba", **extra):
    return document(version=version, channel=channel,
                    files={"linux": {"url": url, "size": len(proba_pkg), "sha256": proba_sha}}, **extra)


pdoc = proba_document()
check(not build_info.is_preview() and build_info.proba_keys() == () and build_info.version_label("2.0.0") == "2.0.0",
      "сборка из исходников и выпуск: не пробная, ключа proba нет, пометки нет")
check(up.channel_of({"update_channel": "proba"}) == "stable" and up.channel_of({"update_channel": "test"}) == "stable",
      "обычная сборка: ни канал proba, ни канал test из настроек не выбираются, всегда stable")
check(raises(lambda: uc.load_verified(pdoc, signed(pdoc, "proba"), "proba", NOW, "", proba_keys=[PROBA_PUB], **KEYS),
             "no_keys"), "обычная сборка: канал proba отвергнут даже с переданным ключом")
check(raises(lambda: up.fetch_signed("proba", {}, NOW), "unknown_channel"), "обычная сборка: папка канала proba не читается")
check(raises(lambda: up.file_get(str(tmp / "latest.json"), 100), "unknown_channel"),
      "обычная сборка: чтение канала из файла запрещено")
for _url in (PROBA_NAME, "file:///etc/hostname", "http://example.com/x.tar.gz", "../x.tar.gz"):
    _d = proba_document(url=_url, channel="stable")
    check(raises(lambda: load(_d, signed(_d)), "bad_document"), f"основной канал: адрес файла «{_url}» (не https) отвергнут")
check(raises(lambda: up.download_file("file:///etc/hostname", tmp / "f.bin", 10, "0" * 64), "bad_url")
      and not (tmp / "f.bin").exists(), "загрузка по адресу file:// отвергнута")
(tmp / "local").mkdir()
(tmp / "local" / PROBA_NAME).write_bytes(proba_pkg)
check(raises(lambda: up.download_file(PROBA_NAME, tmp / "l.bin", len(proba_pkg), proba_sha, local_root=tmp / "local"),
             "bad_url") and not (tmp / "l.bin").exists(), "обычная сборка: загрузка из локальной папки отвергнута")
check(len(uc.trusted_keys("stable", [STABLE_PUB, PROBA_PUB], [TEST_PUB], [PROBA_PUB])) == 1,
      "ключ proba, ошибочно вписанный в основные: отброшен")

_pk = uc.PREVIEW_ONLY_KEYS[0]
_alias = _pk[:-2] + chr(ord(_pk[-2]) + 1) + _pk[-1]   # another base64 spelling of the same 32 bytes
check(uc._normalize(_alias) == uc._normalize(_pk) and uc.trusted_keys("stable", [_pk, _alias], [TEST_PUB]) == []
      and uc.trusted_keys("test", [STABLE_PUB], [_pk, _alias]) == [],
      "вшитый ключ proba запрещён для stable и test в любой сборке, в любом написании base64")
for _name in ("a.tar.gz\n", "CON", "nul.exe", "Com1.tar.gz", "lpt9", "x.", "a b.exe", "a/b", "a\\b", "..x"):
    check(not uc.local_name_ok(_name), f"имя файла proba отвергнуто: {_name!r}")
check(uc.local_name_ok(PROBA_NAME) and uc.local_name_ok("console.tar.gz"), "обычные имена файлов proba принимаются")
check(raises(lambda: uc.parse_manifest(document().replace(PAYLOAD_SHA.encode(), PAYLOAD_SHA.encode() + b"\\n"),
                                       "stable"), "bad_document"), "sha256 с переводом строки в конце отвергнут")

# the same code as a preview build
build_info.PREVIEW, build_info.PROBA_PUBLIC_KEYS = True, (PROBA_PUB,)
check(build_info.version_label("2.0.0") == "2.0.0 · " + tr("app.preview_build"), "пробная сборка: пометка «Пробная сборка» у версии")
check(up.channel_of({}) == "proba" and up.channel_of({"update_channel": "test"}) == "proba",
      "пробная сборка: всегда канал proba")
check(up.proba_dir() == tmp / "data" / "clipsd" / "proba-channel", "папка канала proba: в папке данных пользователя")
check(uc.trusted_keys("stable", [PROBA_PUB], [TEST_PUB]) == [] and uc.trusted_keys("test", [STABLE_PUB], [PROBA_PUB]) == []
      and uc.trusted_keys("proba", [STABLE_PUB], [TEST_PUB], [STABLE_PUB, TEST_PUB]) == [],
      "ключи каналов не пересекаются: proba не открывает stable и test, их ключи не открывают proba")
check(raises(lambda: uc.load_verified(doc, signed(doc, "proba"), "stable", NOW, "", stable_keys=[STABLE_PUB, PROBA_PUB],
                                      test_keys=[TEST_PUB]), "bad_signature"),
      "пробная сборка: документ основного канала, подписанный ключом proba, отвергнут")
check(raises(lambda: uc.load_verified(pdoc, signed(pdoc, "stable"), "proba", NOW, "", **KEYS), "bad_signature"),
      "канал proba: подпись основным ключом отвергнута")
for _url in ("../evil.tar.gz", "sub/x.tar.gz", "https://example.com/x.tar.gz", "C:x.tar.gz"):
    _d = proba_document(url=_url)
    check(raises(lambda: uc.load_verified(_d, signed(_d, "proba"), "proba", NOW, "", **KEYS), "bad_document"),
          f"канал proba: «{_url}» вместо имени файла отвергнуто")
folder = up.proba_dir()
folder.mkdir(parents=True)
(folder / PROBA_NAME).write_bytes(proba_pkg)
(folder / "latest.json").write_bytes(pdoc)
(folder / "latest.json.sig").write_bytes(signed(pdoc, "proba"))
switches = []
up.launch_linux_switch = lambda folder_, a, b, attempt: switches.append((folder_, a, b)) or "setsid"
_rmtree(up.versions_dir() / "2.0.1")
pctx, pui = Ctx(), UI("update")
pu = up.Updater(pctx, clock=Clock(NOW), kind="linux", installed="2.0.0", ui=pui, sync=True, **KEYS)
pu.check_now(manual=True)
check(pui.offers == ["2.0.1"] and switches and switches[0][0] == up.versions_dir() / "2.0.1" and not pui.errors,
      "пробная сборка: обновление из папки proba (подпись, размер, sha256), архив распакован, помощник вызван")
check(up.read_attempt(up.attempt_path())["channel"] == "proba" and pctx.config.get("update_last_seen_version_proba") == "2.0.1",
      "попытка записана с каналом proba, виденная версия proba хранится отдельно")
_unlink(up.attempt_path())
_rmtree(up.versions_dir() / "2.0.1")
# damaged package in the folder: checksum error, nothing installed (the archive kept from the run above has the
# signed sha256 and would be used again, so it goes first: here the copy from the folder is checked)
up._rmtree(up.downloads_dir())
(folder / PROBA_NAME).write_bytes(proba_pkg[:-1] + b"X")
switches.clear()
pu2 = up.Updater(Ctx(), clock=Clock(NOW), kind="linux", installed="2.0.0", ui=UI("update"), sync=True, **KEYS)
pu2.check_now(manual=True)
check(pu2.ui.errors == [tr("updater.error.checksum")] and not switches and not up.attempt_path().exists()
      and not up.downloads_dir().exists(), "канал proba: изменённый пакет в папке отвергнут по sha256")
(folder / PROBA_NAME).write_bytes(proba_pkg)
# latest.json changed after signing: refused
(folder / "latest.json").write_bytes(pdoc.replace(b"2.0.1", b"2.0.2"))
pu3 = up.Updater(Ctx(), clock=Clock(NOW), kind="linux", installed="2.0.0", ui=UI("update"), sync=True, **KEYS)
pu3.check_now(manual=True)
check(pu3.ui.errors == [up.error_text("bad_signature")] and not pu3.ui.offers,
      "канал proba: latest.json, изменённый после подписи, отвергнут")
# a preview build's about window carries the mark and the channel folder
from types import SimpleNamespace  # noqa: E402
from PyQt6.QtGui import QIcon  # noqa: E402
from PyQt6.QtWidgets import QLabel, QTextBrowser  # noqa: E402
from clipshot import app as app_mod  # noqa: E402
_about = app_mod.Clipshot.build_about(SimpleNamespace(icon=QIcon()))
check(tr("app.preview_build") in _about.title.text(), "окно «О программе»: «Пробная сборка» у версии")
up.launch_linux_switch = real_switch
shutil.rmtree(folder)
build_info.PREVIEW, build_info.PROBA_PUBLIC_KEYS = False, ()
check(not build_info.is_preview() and up.channel_of({}) == "stable", "обратно обычная сборка: канал stable")

# --- windows of the program (offscreen) -----------------------------------------------------------
manifest = load(doc, signed(doc))
offer = up.OfferDialog(manifest, "2.0.0")
labels = " ".join(w.text() for w in offer.findChildren(QLabel))
check(tr("updater.offer.heading", version="2.0.1") in labels and "2.0.0" in labels, "окно: «Доступна версия 2.0.1» на языке программы")
check([offer.update_button.text(), offer.later_button.text(), offer.skip_button.text()] ==
      [tr("updater.button.update"), tr("updater.button.later"), tr("updater.button.skip")], "окно: кнопки Обновить, Позже, Пропустить эту версию")
browser = offer.findChildren(QTextBrowser)[0]
check(NOTES_SHOWN in browser.toPlainText(), "окно: изменения на языке программы")
offer.show()
offer.grab().save(os.path.join(out, "offer-ru.png"))
offer.skip_button.click()
check(offer.choice == "skip", "окно: нажатие «Пропустить эту версию»")
check(not offer.critical and offer.windowTitle() == tr("updater.offer.title"), "окно обычной версии: обычный заголовок")
crit_offer = up.OfferDialog(manifest, "2.0.0", critical=True)
crit_labels = " ".join(w.text() for w in crit_offer.findChildren(QLabel))
check(crit_offer.windowTitle() == tr("updater.offer.title_security") and tr("updater.offer.security") in crit_labels
      and tr("updater.button.later") in crit_labels and crit_offer.skip_button.isHidden(),
      "окно исправления безопасности: «Срочное обновление», текст о безопасности, без «Пропустить эту версию»")
crit_offer.show()
crit_offer.grab().save(os.path.join(out, "offer-critical-ru.png"))
check(up.notes_in({"en": "English notes", "de": "Deutsch"}, "ru") == "English notes",
      "нет изменений по-русски: показан английский")
progress = up.ProgressDialog("2.0.1", lambda: None)
progress.set_progress(512 * 1024, 1024 * 1024)
check(progress.bar.value() == 50 and tr("updater.download.progress_pct", done="0.5", total="1.0", percent=50) == progress.status.text(), "полоса загрузки: 50%")
progress.show()
progress.grab().save(os.path.join(out, "progress-ru.png"))
news = up.WhatsNewDialog("2.0.1", "- Русские изменения")
check(news.windowTitle() == tr("updater.whatsnew.title", version="2.0.1"), "окно «Что нового в 2.0.1»")
news.show()
news.grab().save(os.path.join(out, "whatsnew-ru.png"))
menu = QMenu()
menu.addAction("О программе")
menu.addSeparator()
menu.addAction("Выход")
action = up.install_menu(menu, Ctx())
texts = [a.text() for a in menu.actions()]
check(texts == ["О программе", tr("updater.menu.check"), "", "Выход"], "меню трея: «Проверить обновления» перед «Выход»")

# --- 1.32: the window of an ordinary update comes later (update_prompt), the bell at once ----------------------------
from clipshot import notifications as notes  # noqa: E402
up.drop_critical("stable")


def prompt_case(answer="later", **cfg):
    pu_, pctx_, pui_, pch_, pclock_ = make(answer=answer, config=cfg)
    pctx_.editors, pctx_.selector = [], None
    return pu_, pctx_, pui_, pch_, pclock_


def quiet_minute(pu_, pclock_):
    """Две проверки таймера с минутой спокойствия между ними; True, если окно показано при любой из них."""
    first = upr.poll(pu_)
    pclock_.now += timedelta(seconds=61)
    return upr.poll(pu_) or first


# found by the automatic check: no window, the bell shows the version, the count starts
pu, pctx, pui, pch, pclock = prompt_case()
pu.check_now(manual=False)
st = upr.state(pctx.config)
check(not pui.offers and st.get("version") == "2.0.1" and st.get("shots") == 0 and st.get("since") == up.uc.format_utc(NOW),
      "обычное обновление при автопроверке: окна нет, отсчёт с момента обнаружения")
check(notes.available_update(pctx.config, "2.0.0") == "2.0.1", "колокольчик: «Доступна версия 2.0.1»")
check(getattr(pu, "_prompt_timer", None) is not None and pu._prompt_timer.isActive(), "таймер ждёт спокойной минуты")
pclock.now = NOW + timedelta(days=2, hours=23)
check(not quiet_minute(pu, pclock) and not pui.offers, "через 2 дня 23 часа и 0 снимков: рано")
# 3 days: only in a quiet minute (no selection, no editor, nothing blocks)
pclock.now = NOW + timedelta(days=3)
pctx.editors = ["editor"]
check(not quiet_minute(pu, pclock) and not pui.offers, "3 дня прошло, но открыт редактор: окна нет")
pctx.editors, pctx.selector = [], "selector"
check(not quiet_minute(pu, pclock), "открыто окно выделения: окна нет")
pctx.selector = None
pctx.quit_blocker = lambda: "dialog"
check(not quiet_minute(pu, pclock), "открыто другое окно (quit_blocker): окна нет")
pctx.quit_blocker = lambda: ""
upr.poll(pu)
pclock.now += timedelta(seconds=30)
check(not upr.poll(pu) and not pui.offers, "спокойно только 30 секунд: ещё ждём")
pclock.now += timedelta(seconds=31)
check(upr.poll(pu) and pui.offers == ["2.0.1"] and pui.critical == [False], "3 дня и спокойная минута: окно-предложение")
st = upr.state(pctx.config)
check(st.get("since") == up.uc.format_utc(pclock.now) and st.get("shots") == 0 and not pu.busy,
      "«Позже»: отсчёт заново (ещё 3 дня или 20 снимков)")
pclock.now += timedelta(days=2)
check(not quiet_minute(pu, pclock) and len(pui.offers) == 1, "после «Позже» через 2 дня окна нет")
# 20 shots win over 3 days
for _ in range(19):
    upr.note_shot(pctx.config)
check(not quiet_minute(pu, pclock), "19 снимков: рано")
upr.note_shot(pctx.config)
check(quiet_minute(pu, pclock) and len(pui.offers) == 2, "20 снимков раньше трёх дней: окно")
# a newer version while waiting: the count goes on, the number changes
since_before = upr.state(pctx.config).get("since")
pch.publish("2.0.5")
pclock.now += timedelta(days=1, hours=1)
pu.tick()
st = upr.state(pctx.config)
check(st.get("version") == "2.0.5" and st.get("since") == since_before and len(pui.offers) == 2,
      "нашлась версия новее, пока ждём: номер новый, отсчёт не сбрасывается, окна нет")
pclock.now += timedelta(days=2)
check(quiet_minute(pu, pclock) and pui.offers[-1] == "2.0.5", "окно предлагает самую новую версию")
# "Skip this version": no window and no bell for it, later checks are silent
pu, pctx, pui, pch, pclock = prompt_case(answer="skip")
pu.check_now(manual=False)
pclock.now = NOW + timedelta(days=3)
check(quiet_minute(pu, pclock) and pui.offers == ["2.0.1"], "окно через 3 дня (ответ «Пропустить»)")
check(not upr.state(pctx.config) and "2.0.1" in pctx.config["update_skipped"]
      and notes.available_update(pctx.config, "2.0.0") == "", "«Пропустить»: отсчёт снят, колокольчик для 2.0.1 погас")
pclock.now += timedelta(days=2)
pu.tick()
pclock.now += timedelta(days=4)
quiet_minute(pu, pclock)
check(pui.offers == ["2.0.1"] and not upr.state(pctx.config), "пропущенная версия больше не предлагается")
# "Update": the download starts, the count is gone
pu, pctx, pui, pch, pclock = prompt_case(answer="update")
started = []
pu.start_download = lambda m, trace_id="": started.append(m.version)
pu.check_now(manual=False)
pclock.now = NOW + timedelta(days=3)
check(quiet_minute(pu, pclock) and started == ["2.0.1"] and not upr.state(pctx.config), "«Обновить» в окне: загрузка, отсчёт снят")
# the bell button and "Check for updates" are manual: the window at once; "Later" there starts the count
pu, pctx, pui, pch, pclock = prompt_case(answer="later")
pu.check_now(manual=False)
pclock.now = NOW + timedelta(hours=2)
check(pu.check_now(manual=True) and pui.offers == ["2.0.1"], "ручная «Проверить обновления» (и «Обновить» в колокольчике): окно сразу")
check(upr.state(pctx.config).get("since") == up.uc.format_utc(pclock.now), "«Позже» в ручном окне: отсчёт с этой минуты")
pu.installed = "2.0.1"
pclock.now = NOW + timedelta(days=5)
check(not quiet_minute(pu, pclock) and not upr.state(pctx.config), "версия уже установлена: отсчёт снят, окна нет")
# security fix: the window at once, the count is not used
pu, pctx, pui, pch, pclock = prompt_case()
pch.publish("2.0.1", critical=True)
pu.tick()
check(pui.offers == ["2.0.1"] and pui.critical == [True] and not upr.state(pctx.config),
      "срочное исправление безопасности: окно сразу, без отсчёта")
up.drop_critical("stable")
# restart: the count lives in config; the window comes after the next check of the channel in a quiet minute
pu, pctx, pui, pch, pclock = prompt_case(update_prompt={"version": "2.0.1", "since": up.uc.format_utc(NOW - timedelta(days=4)),
                                                       "shots": 3})
check(not quiet_minute(pu, pclock) and not pui.offers, "после перезапуска документа канала в памяти нет: окно ждёт проверки")
pu.tick()
check(not pui.offers and quiet_minute(pu, pclock) and pui.offers == ["2.0.1"], "проверка канала после перезапуска: окно в спокойную минуту")
# the clock moved back a lot: the count starts again
cfgx = {"update_prompt": {"version": "2.0.1", "since": up.uc.format_utc(NOW + timedelta(days=10)), "shots": 0}}
check(not upr.due(cfgx, NOW) and cfgx["update_prompt"]["since"] == up.uc.format_utc(NOW), "часы переведены назад: отсчёт заново")
# shots are counted only while an update waits
cfgy = {}
upr.note_shot(cfgy)
check(cfgy == {}, "снимок без ожидающего обновления: счётчика нет")
# app: each finished capture counts
_src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "clipshot", "app.py"),
            encoding="utf-8").read()
check("update_prompt.note_shot(self.config)" in _src.split("def _region_done", 1)[1].split("\n    def ", 1)[0],
      "приложение считает каждый снимок (Clipshot._region_done)")

# tools/channel_sign.py itself (sign, refresh, refusals): tests/channel_sign_test.py

server.shutdown()
pkg_server.shutdown()
shutil.rmtree(tmp, ignore_errors=True)
print()
if failures:
    print(f"ИТОГ: {len(failures)} проверок не прошли")
    sys.exit(1)
print("ИТОГ: все проверки пройдены")
