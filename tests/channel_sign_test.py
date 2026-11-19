# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Signer tool test (tools/channel_sign.py): keygen, build, sign, refresh, verify and every refusal.

No network, no Qt. Keys and documents live in a temporary folder; the signer's "last signed" copy too.
Run: python3 tests/channel_sign_test.py [project]
"""

import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

here = os.path.dirname(os.path.abspath(__file__))
project = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(here)
sys.path.insert(0, project)
sys.path.insert(0, os.path.join(project, "tools"))

import channel_sign as cs  # noqa: E402
from clipshot import update_channel as uc  # noqa: E402

failures = []
tmp = Path(tempfile.mkdtemp(prefix="clipsd-sign-test-"))


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def refused(fn, words=""):
    """True if fn raises ToolError (and its text contains words)."""
    try:
        fn()
    except cs.ToolError as exc:
        if words and words not in str(exc):
            print(f"     other reason: {exc}")
            return False
        return True
    return False


# --- keygen -------------------------------------------------------------------------------------------
keys = tmp / "keys"
STABLE_PUB = cs.keygen(keys / "stable.pem")
BACKUP_PUB = cs.keygen(keys / "backup.pem")
TEST_PUB = cs.keygen(keys / "test.pem")
STABLE, TEST = keys / "stable.pem", keys / "test.pem"
if os.name != "nt":
    check(oct(STABLE.stat().st_mode & 0o777) == "0o600", "keygen: закрытый ключ с правами 0600")
inside = Path(project) / "tests" / "output" / "should-not-exist.pem"
check(refused(lambda: cs.keygen(inside), "git") and not inside.exists(), "keygen: отказ внутри рабочей копии git")
check(refused(lambda: cs.keygen(STABLE), "exists"), "keygen: не перезаписывает существующий ключ")
check(cs.public_b64(cs.load_private(STABLE)) == STABLE_PUB, "pubkey: открытый ключ совпадает с выданным keygen")

# --- build ----------------------------------------------------------------------------------------------
rel = tmp / "release"
(rel / "dist").mkdir(parents=True)
(rel / "CHANGELOG" / "2.0.1").mkdir(parents=True)
(rel / "dist" / "ClipSD-2.0.1-Setup.exe").write_bytes(b"windows" * 100)
(rel / "dist" / "clipsd-2.0.1-linux-x86_64.tar.gz").write_bytes(b"linux" * 100)
sums = "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in sorted((rel / "dist").iterdir()))
(rel / "dist" / "SHA256SUMS").write_text(sums)
(rel / "CHANGELOG" / "2.0.1" / "en.md").write_text("- Fixed things\n")
(rel / "CHANGELOG" / "2.0.1" / "ru.md").write_text("- Исправления\n", encoding="utf-8")
latest = rel / "latest.json"
sig = rel / "latest.json.sig"
BASE = "https://github.com/ClipSD/ClipSD/releases/download/v2.0.1"


def build(channel="stable", version="2.0.1", out=latest, days=90):
    return cs.main(["build", "--version", version, "--channel", channel, "--sums", str(rel / "dist" / "SHA256SUMS"),
                    "--dist", str(rel / "dist"), "--changelog", str(rel / "CHANGELOG"), "--base-url", BASE,
                    "--out", str(out), "--days", str(days)])


rc = build()
built = json.loads(latest.read_text(encoding="utf-8"))
check(rc == 0 and set(built["files"]) == {"windows", "linux"} and built["notes"]["ru"].startswith("- Исправления")
      and built["files"]["windows"]["url"].endswith("/ClipSD-2.0.1-Setup.exe"), "build: latest.json из SHA256SUMS и CHANGELOG")
check(cs.main(["build", "--version", "2.0.1", "--channel", "stable", "--sums", str(rel / "dist" / "SHA256SUMS"),
               "--dist", str(rel / "dist"), "--changelog", str(rel / "CHANGELOG"), "--base-url", "http://x",
               "--out", str(tmp / "x.json")]) == 2, "build: адрес не https отвергнут")
check(refused(lambda: cs.version_tuple("2.0.١")), "версия с не-ASCII цифрой отвергнута")
GOOD = latest.read_bytes()

# --- urgent security fix: --critical and the CHANGELOG marker must agree, the card shows it ---------------
import contextlib  # noqa: E402
import io  # noqa: E402


def run_out(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cs.main(argv)
    return rc, buf.getvalue()


def build_args(out, *extra):
    return ["build", "--version", "2.0.1", "--channel", "stable", "--sums", str(rel / "dist" / "SHA256SUMS"),
            "--dist", str(rel / "dist"), "--changelog", str(rel / "CHANGELOG"), "--base-url", BASE,
            "--out", str(out), *extra]


check(built.get("critical") is None, "build без --critical: не срочный (по умолчанию false)")
rc, text = run_out(["card", "--in", str(latest)])
check(rc == 0 and cs.URGENT_BANNER not in text and "ordinary" in text, "карточка обычного выпуска: без пометки СРОЧНО")
urgent_out = tmp / "urgent.json"
check(cs.main(build_args(urgent_out, "--critical")) == 2 and not urgent_out.exists(),
      "build --critical без CHANGELOG/2.0.1/CRITICAL: отказ (срочность решается в release.sh --critical)")
marker = rel / "CHANGELOG" / "2.0.1" / cs.CRITICAL_MARKER
marker.write_text(cs.URGENT_BANNER + "\n", encoding="utf-8")
check(cs.main(build_args(urgent_out)) == 2 and not urgent_out.exists(),
      "CHANGELOG помечен срочным, а --critical не указан: отказ")
rc, text = run_out(build_args(urgent_out, "--critical"))
urgent_doc = json.loads(urgent_out.read_text(encoding="utf-8"))
check(rc == 0 and urgent_doc.get("critical") is True, "build --critical с меткой CHANGELOG: critical true")
first = text.splitlines()[:3]
check(any(cs.URGENT_BANNER in line for line in first), "build: карточка начинается с «СРОЧНО (исправление безопасности)»")
rc, text = run_out(["card", "--in", str(urgent_out)])
check(rc == 0 and cs.URGENT_BANNER in text.splitlines()[1], "card: срочный документ с пометкой СРОЧНО вверху")
check(cs.release_card(urgent_doc).count(cs.URGENT_BANNER) == 2, "карточка: пометка СРОЧНО и в баннере, и в строке версии")
marker.unlink()

# --- sign: a fresh document -------------------------------------------------------------------------------
signer_home = tmp / "signer-home"      # the signer's own folder, outside any git working tree
signer_home.mkdir()
last = signer_home / "last-signed-stable.json"


def sign(*extra, key=STABLE, role="stable", inp=latest):
    return cs.main(["sign", "--private", str(key), "--role", role, "--in", str(inp), *extra])


rc = sign("--last-signed", str(last))
check(rc == 0 and cs.main(["verify", "--public", STABLE_PUB, "--in", str(latest), "--channel", "stable"]) == 0,
      "sign + verify: подпись верна")
check(last.read_bytes() == GOOD, "sign: копия последнего подписанного сохранена у подписанта")
if os.name != "nt":
    check(oct(last.stat().st_mode & 0o777) == "0o600", "копия подписанта с правами 0600")
check(cs.main(["verify", "--public", TEST_PUB, "--in", str(latest)]) == 1, "verify: чужим ключом не проходит")
m = uc.load_verified(latest.read_bytes(), sig.read_bytes(), "stable", datetime.now(timezone.utc), "", [STABLE_PUB], [TEST_PUB])
check(m.version == "2.0.1" and m.files["linux"]["sha256"] == hashlib.sha256(b"linux" * 100).hexdigest(),
      "программа принимает latest.json, собранный и подписанный инструментом")


# every refusal leaves the existing signature untouched
def refused_sign(doc_bytes, msg, *extra, role="stable", key=STABLE):
    bad = tmp / "bad.json"
    bad_sig = tmp / "bad.json.sig"
    bad.write_bytes(doc_bytes)
    bad_sig.unlink(missing_ok=True)
    rc = sign(*extra, key=key, role=role, inp=bad)
    check(rc == 2 and not bad_sig.exists(), f"sign отказывает: {msg}")


def edited(**changes):
    doc = json.loads(GOOD.decode("utf-8"))
    for key, value in changes.items():
        if value is None:
            doc.pop(key, None)
        else:
            doc[key] = value
    return cs.dump(doc)


def edited_file(platform="linux", **changes):
    doc = json.loads(GOOD.decode("utf-8"))
    doc["files"][platform].update(changes)
    return cs.dump(doc)


now = datetime.now(timezone.utc)
refused_sign(b"not json", "не JSON")
refused_sign(cs.dump(["a"]), "JSON не объект")
refused_sign(GOOD.replace(b"\n", b"\r\n"), "не каноническая запись (лишние байты)")
refused_sign(GOOD.replace(b'"schema": 1,', b'"schema": 1, "schema": 1,'), "повтор ключа")
refused_sign(edited(schema=2), "схема 2")
refused_sign(edited(schema=None), "нет схемы")
refused_sign(edited(channel="test"), "документ тестового канала под ролью stable")
refused_sign(GOOD, "документ основного канала под ролью test", role="test", key=TEST)
refused_sign(edited(version="2.0.1-beta"), "версия с суффиксом")
refused_sign(edited(version="2.0.١"), "версия с не-ASCII цифрой")
refused_sign(edited(min_version="2.1"), "min_version выше версии")
refused_sign(edited(critical="yes"), "critical не логическое")
refused_sign(edited(extra="x"), "неизвестное поле")
refused_sign(edited(files={}), "нет файлов")
refused_sign(edited(files={"macos": built["files"]["linux"]}), "неизвестная платформа")
refused_sign(edited_file(url="http://example.com/a.tar.gz"), "адрес файла http")
refused_sign(edited_file(url="https://"), "пустой https-адрес")
refused_sign(edited_file(url="https://example.com/a b"), "пробел в адресе")
refused_sign(edited_file(sha256="ABC"), "sha256 короче 64")
refused_sign(edited_file(sha256="A" * 64), "sha256 заглавными")
refused_sign(edited_file(sha256="g" * 64), "sha256 не hex")
refused_sign(edited_file(size=0), "размер 0")
refused_sign(edited_file(size=-5), "размер отрицательный")
refused_sign(edited_file(size=True), "размер true")
refused_sign(edited_file(size="100"), "размер строкой")
refused_sign(edited_file(extra=1), "лишнее поле файла")
refused_sign(edited(notes={"ru": "x"}), "нет изменений на английском")
refused_sign(edited(released="2026-11-02T12:00:00"), "время без часового пояса")
refused_sign(edited(released=cs.utc(now - timedelta(days=10)), expires=cs.utc(now - timedelta(days=1))),
             "срок уже истёк")
refused_sign(edited(expires=built["released"]), "expires не позже released")
refused_sign(edited(released=cs.utc(now + timedelta(days=5)), expires=cs.utc(now + timedelta(days=60))),
             "released в будущем")
refused_sign(edited(released=cs.utc(now - timedelta(days=30)), expires=cs.utc(now + timedelta(days=100))),
             "expires дальше released + 120 дней")
refused_sign(edited(expires=cs.utc(now + timedelta(days=121))), "expires дальше 120 дней от сегодня")
# version lower than the last signed one
old_doc = tmp / "old" / "latest.json"
old_doc.parent.mkdir()
build(version="2.0.1", out=old_doc)
older = json.loads(old_doc.read_text(encoding="utf-8"))
older["version"] = "2.0.0"
refused_sign(cs.dump(older), "версия ниже последней подписанной", "--last-signed", str(last))
check(last.read_bytes() == GOOD, "после отказа копия подписанта не изменилась")
inside_last = Path(project) / "tests" / "output" / "last-signed.json"
refused_sign(GOOD, "--last-signed внутри рабочей копии git", "--last-signed", str(inside_last))
check(not inside_last.exists(), "копия внутри рабочей копии git не создана")
refused_sign(GOOD, "--last-signed указывает на сам документ", "--last-signed", str(tmp / "bad.json"))
# the urgency of a signed version never changes (review R04b P2-3): last signed 2.0.1 is ordinary
refused_sign(edited(critical=True), "та же версия 2.0.1 срочной после обычной", "--last-signed", str(last), "--critical")
crit_last = signer_home / "last-critical.json"
crit_last.write_bytes(edited(critical=True))
refused_sign(GOOD, "та же версия 2.0.1 обычной после срочной", "--last-signed", str(crit_last))
crit_last.unlink()
for _bad_sha in ("a" * 64 + "\n",):
    refused_sign(edited_file(sha256=_bad_sha), "sha256 с переводом строки в конце")
# a preview file never goes into stable or test (review R04b P2-6)
prel = tmp / "proba-only"
(prel / "dist").mkdir(parents=True)
(prel / "dist" / "ClipSD-2.0.1-proba-Setup.exe").write_bytes(b"p" * 50)
(prel / "dist" / "SHA256SUMS").write_text(
    f"{hashlib.sha256(b'p' * 50).hexdigest()}  ClipSD-2.0.1-proba-Setup.exe\n")
for _ch, _extra in (("stable", ["--base-url", BASE]), ("test", ["--base-url", BASE])):
    check(cs.main(["build", "--version", "2.0.1", "--channel", _ch, "--sums", str(prel / "dist" / "SHA256SUMS"),
                   "--dist", str(prel / "dist"), "--changelog", str(rel / "CHANGELOG"), "--out", str(prel / "l.json"),
                   *_extra]) == 2 and not (prel / "l.json").exists(),
          f"build {_ch}: файл пробной сборки (-proba-) отвергнут")
# signing an urgent document prints the card with the banner
urgent_sig = tmp / "urgent.json.sig"
rc, text = run_out(["sign", "--private", str(STABLE), "--role", "stable", "--in", str(urgent_out)])
check(rc == 2 and not urgent_sig.exists() and cs.URGENT_BANNER in text,
      "sign срочного без --critical: карточка СРОЧНО показана, подпись не сделана")
rc, text = run_out(["sign", "--private", str(STABLE), "--role", "stable", "--in", str(latest), "--out",
                    str(tmp / "x.sig"), "--critical"])
check(rc == 2 and not (tmp / "x.sig").exists(), "sign --critical для обычного документа: отказ")
rc, text = run_out(["sign", "--private", str(STABLE), "--role", "stable", "--in", str(urgent_out), "--critical"])
check(rc == 0 and cs.URGENT_BANNER in text and text.index(cs.URGENT_BANNER) < text.index("signed "),
      "sign --critical: карточка «СРОЧНО (исправление безопасности)» напечатана до подписи, документ подписан")
check(uc.load_verified(urgent_out.read_bytes(), (tmp / "urgent.json.sig").read_bytes(), "stable",
                       datetime.now(timezone.utc), "", [STABLE_PUB], [TEST_PUB]).critical is True,
      "программа видит critical в подписанном документе")
# the test channel signs its own documents with the test key
tlatest = tmp / "test-channel" / "latest.json"
tlatest.parent.mkdir()
build(channel="test", out=tlatest)
check(sign(key=TEST, role="test", inp=tlatest) == 0
      and cs.main(["verify", "--public", TEST_PUB, "--in", str(tlatest), "--channel", "test"]) == 0,
      "тестовый канал: документ test подписан тестовым ключом")

# --- proba (preview channel): plain file names instead of https, its own key ------------------------------
PROBA_PUB = cs.keygen(keys / "proba.pem")
PROBA = keys / "proba.pem"
plat = tmp / "proba-channel" / "latest.json"
plat.parent.mkdir()
proba_args = ["build", "--version", "2.0.1", "--channel", "proba", "--sums", str(rel / "dist" / "SHA256SUMS"),
              "--dist", str(rel / "dist"), "--changelog", str(rel / "CHANGELOG"), "--out", str(plat)]
check(cs.main(proba_args + ["--base-url", BASE]) == 2 and not plat.exists(), "proba: --base-url не нужен, отказ")
rc, text = run_out(proba_args)
pdoc = json.loads(plat.read_text(encoding="utf-8"))
check(rc == 0 and pdoc["channel"] == "proba" and pdoc["files"]["linux"]["url"] == "clipsd-2.0.1-linux-x86_64.tar.gz"
      and pdoc["files"]["windows"]["url"] == "ClipSD-2.0.1-Setup.exe" and "PROBA" in text,
      "build proba: файлы названы именами рядом с latest.json, карточка помечена PROBA")
check(sign(key=PROBA, role="proba", inp=plat) == 0
      and cs.main(["verify", "--public", PROBA_PUB, "--in", str(plat), "--channel", "proba"]) == 0,
      "sign proba: подписан ключом proba")
check(cs.main(["verify", "--public", STABLE_PUB, "--in", str(plat)]) == 1, "документ proba не подписан основным ключом")
refused_sign(plat.read_bytes(), "документ proba под ролью stable")
_pd = dict(pdoc)
_pd["files"] = {"linux": dict(pdoc["files"]["linux"], url="../clipsd.tar.gz")}
refused_sign(cs.dump(_pd), "proba: путь с «..» вместо имени файла", role="proba", key=PROBA)
_pd["files"] = {"linux": dict(pdoc["files"]["linux"], url="https://example.com/a.tar.gz")}
refused_sign(cs.dump(_pd), "proba: https-адрес вместо имени файла", role="proba", key=PROBA)
for _name in ("a.tar.gz\n", "CON", "nul.exe", "x."):
    _pd["files"] = {"linux": dict(pdoc["files"]["linux"], url=_name)}
    refused_sign(cs.dump(_pd), f"proba: имя {_name!r} отвергнуто", role="proba", key=PROBA)
# an urgent update in the preview channel needs no release marker (review R04b P1-1)
pcrit = tmp / "proba-channel" / "critical.json"
rc, text = run_out(proba_args[:-1] + [str(pcrit), "--critical"])
check(rc == 0 and json.loads(pcrit.read_text(encoding="utf-8")).get("critical") is True and cs.URGENT_BANNER in text,
      "build proba --critical без метки CHANGELOG: собран, critical true, карточка СРОЧНО")
check(refused(lambda: cs.check_document(cs.dump(dict(json.loads(GOOD.decode("utf-8")), channel="stable")), "proba")),
      "документ основного канала под ролью proba: отказ")

# --- refresh ---------------------------------------------------------------------------------------------------
before = json.loads(latest.read_text(encoding="utf-8"))
rc = sign("--refresh", "--days", "100", "--public", STABLE_PUB, "--public", BACKUP_PUB, "--last-signed", str(last))
after = json.loads(latest.read_text(encoding="utf-8"))
check(rc == 0 and after["expires"] != before["expires"]
      and {k: v for k, v in after.items() if k != "expires"} == {k: v for k, v in before.items() if k != "expires"},
      "refresh: изменился только срок")
check(cs.main(["verify", "--public", STABLE_PUB, "--in", str(latest)]) == 0, "refresh: новая подпись верна")
check(last.read_bytes() == latest.read_bytes(), "refresh: копия подписанта обновлена")
REFRESHED, REFRESHED_SIG = latest.read_bytes(), sig.read_bytes()


def restore():
    latest.write_bytes(REFRESHED)
    sig.write_bytes(REFRESHED_SIG)
    last.write_bytes(REFRESHED)


def refused_refresh(msg, *args):
    restore()
    rc = sign("--refresh", *args)
    check(rc == 2 and sig.read_bytes() == REFRESHED_SIG and latest.read_bytes() == REFRESHED,
          f"refresh отказывает: {msg}")


refused_refresh("без --public", "--last-signed", str(last))
refused_refresh("без --last-signed", "--public", STABLE_PUB)
refused_refresh("нет копии подписанта", "--public", STABLE_PUB, "--last-signed", str(signer_home / "missing.json"))
refused_refresh("копия подписанта внутри рабочей копии git", "--public", STABLE_PUB, "--last-signed", str(inside_last))
refused_refresh("ключ подписи не из списка --public", "--public", BACKUP_PUB, "--last-signed", str(last))
refused_refresh("срок дальше 120 дней", "--days", "121", "--public", STABLE_PUB, "--last-signed", str(last))
# a file swapped in the channel without a signature (signed check fails first)
restore()
latest.write_bytes(REFRESHED.replace(b"Fixed", b"Broke"))
check(sign("--refresh", "--public", STABLE_PUB, "--last-signed", str(last)) == 2 and sig.read_bytes() == REFRESHED_SIG,
      "refresh отказывает: файл, изменённый мимо подписи")
# a validly signed but different document planted in the channel: refused against the signer's copy
restore()
planted = json.loads(REFRESHED.decode("utf-8"))
planted["files"]["linux"]["url"] = "https://evil.example/clipsd.tar.gz"
latest.write_bytes(cs.dump(planted))
sig.write_bytes(cs.sign_bytes(cs.load_private(STABLE), latest.read_bytes()))
planted_sig = sig.read_bytes()
check(sign("--refresh", "--public", STABLE_PUB, "--last-signed", str(last)) == 2 and sig.read_bytes() == planted_sig,
      "refresh отказывает: подложенный подписанный документ отличается от копии подписанта")
# an older signed document put back into the channel
restore()
older_doc = json.loads(REFRESHED.decode("utf-8"))
older_doc["version"] = "2.0.0"
latest.write_bytes(cs.dump(older_doc))
sig.write_bytes(cs.sign_bytes(cs.load_private(STABLE), latest.read_bytes()))
check(sign("--refresh", "--public", STABLE_PUB, "--last-signed", str(last)) == 2, "refresh отказывает: версия ниже последней подписанной")
# the copy of another channel
restore()
check(sign("--refresh", "--public", STABLE_PUB, "--last-signed", str(tlatest)) == 2,
      "refresh отказывает: копия подписанта другого канала")
# role mismatch on refresh
restore()
check(sign("--refresh", "--public", STABLE_PUB, "--last-signed", str(last), role="test") == 2
      and sig.read_bytes() == REFRESHED_SIG,
      "refresh отказывает: роль test для документа stable")
check(refused(lambda: cs.check_only_expires_changed(REFRESHED, REFRESHED.replace(b'"2.0.1"', b'"2.0.9"'))),
      "refresh: смена версии запрещена")

shutil.rmtree(tmp, ignore_errors=True)
print()
if failures:
    print(f"ИТОГ: {len(failures)} проверок не прошли")
    sys.exit(1)
print("ИТОГ: все проверки пройдены")
