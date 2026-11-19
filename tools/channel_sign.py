#!/usr/bin/env python3
# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Update channel tool for the signer (the owner of the channel key) and GitHub Actions (test channel).

Commands:
  keygen  --private PATH                      new Ed25519 pair; private key PEM with mode 0600
                                              (refused inside a git working tree), public key printed
  pubkey  --private PATH                      print the public key (base64, for update_channel.py)
  build   --version V --channel stable|test|proba --sums SHA256SUMS --dist DIR --changelog DIR
          [--base-url URL] --out latest.json [--min-version V] [--critical] [--days 90]
          [--windows-file NAME] [--linux-file NAME]
          stable and test: --base-url https://... is required. proba (preview builds, a local folder):
          no --base-url, each file is named by its plain file name next to latest.json; the CRITICAL
          marker is not required there (the owner may try an urgent update in the preview channel)
          --critical marks an urgent security fix (default: not urgent). It must agree with the
          marker CHANGELOG/<version>/CRITICAL written by tools/release.sh --critical: a mismatch
          either way is refused, so the urgency is decided once, at release.sh, and never by accident
  card    --in latest.json                    the release card: what the signer is asked to sign; an
                                              urgent document starts with "СРОЧНО (исправление безопасности)"
  sign    --private PATH --role stable|test|proba --in latest.json [--out latest.json.sig]
          [--last-signed COPY] [--critical]
          the release card is printed BEFORE signing; an urgent document ("critical": true) is signed
          only with --critical (confirmation), --critical for an ordinary one is refused; with
          --last-signed the same version is never signed again with another "critical" value
          a new document: it must pass check_document (schema, channel = role, versions, https files,
          sha256, sizes, expires at most 120 days after released and after now); with --last-signed
          its version must not be lower than the last signed one, and COPY is updated after signing
  sign    --private PATH --role stable|test --in latest.json --refresh --public B64 [--public B64 ...]
          --last-signed COPY [--days 90]
          renew "expires" only: the current file must carry a valid signature of a --public key and,
          apart from "expires", be byte-for-byte equal to COPY, the signer's own copy of the last
          document it signed (kept outside any git working tree, never the repository copy)
  verify  --public B64 [--public B64 ...] --in latest.json [--sig latest.json.sig] [--channel C]

The card (build, sign, verify and card print it) shows "СРОЧНО (исправление безопасности)" first
when the document has "critical": true: the program then offers it at once and on every start.

Private keys are never printed and never written into a repository.
"""

import argparse
import base64
import fnmatch
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

# notes read from CHANGELOG/<version>/<lang>.md (1.x: ru and en are written; others are taken when present)
LANGUAGES = ["ru", "en", "bg", "uk", "de", "fr", "es", "it", "pt", "pl", "tr", "zh"]
DEFAULT_DAYS = 90
MAX_DAYS_AFTER_RELEASE = 120        # a fresh document: expires <= released + 120 days
MAX_DAYS_AHEAD = 120                # any signature: expires <= signing time + 120 days
RELEASED_FUTURE_TOLERANCE = timedelta(days=1)
MAX_DOCUMENT_BYTES = 256 * 1024     # the same limit as clipshot/update_channel.py
PLATFORMS = ("windows", "linux")
TOP_LEVEL_KEYS = {"schema", "channel", "version", "released", "expires", "min_version", "critical", "files",
                  "notes", "heartbeat"}
_VERSION_RE = re.compile(r"^[0-9]{1,4}(\.[0-9]{1,4}){0,3}$")   # ASCII digits only, unlike \d
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_LOCAL_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}")   # the same rule as update_channel.py
_WINDOWS_DEVICE_RE = re.compile(r"(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?", re.IGNORECASE)
CHANNELS = ("stable", "test", "proba")
WINDOWS_PATTERNS = ("*Setup*.exe", "*.exe")
URGENT_BANNER = "СРОЧНО (исправление безопасности)"
CRITICAL_MARKER = "CRITICAL"        # file in CHANGELOG/<version>/, written by tools/release.sh --critical
LINUX_PATTERNS = ("*linux*.tar.gz", "*.tar.gz")


class ToolError(Exception):
    pass


def utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_utc(text: str) -> datetime:
    if not isinstance(text, str):
        raise ToolError(f"time is not a string: {text!r}")
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise ToolError(f"bad time: {text!r}") from None
    if value.tzinfo is None:
        raise ToolError(f"time without timezone: {text}")
    return value.astimezone(timezone.utc)


def local_name_ok(name) -> bool:
    """The same rule as clipshot/update_channel.local_name_ok: a plain file name, whole string."""
    return (isinstance(name, str) and _LOCAL_NAME_RE.fullmatch(name) is not None and ".." not in name
            and not name.endswith(".") and _WINDOWS_DEVICE_RE.fullmatch(name) is None)


def version_tuple(text: str) -> tuple:
    if not isinstance(text, str) or not _VERSION_RE.fullmatch(text):
        raise ToolError(f"bad version: {text!r}")
    parts = [int(p) for p in text.split(".")]
    return tuple(parts + [0] * (4 - len(parts)))


def dump(doc: dict) -> bytes:
    """Canonical bytes: the signature covers exactly what is written to disk."""
    return (json.dumps(doc, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


# Windows opens os.open() files in text mode unless O_BINARY is given: every "\n" would become "\r\n"
# and the written document would no longer be the canonical bytes the signature covers.
_O_BINARY = getattr(os, "O_BINARY", 0)


def write_atomic(path: Path, data: bytes, mode: int = 0o644) -> None:
    path = Path(path)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _O_BINARY, mode)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def inside_git_tree(path: Path) -> bool:
    for parent in [path.resolve().parent, *path.resolve().parent.parents]:
        if (parent / ".git").exists():
            return True
    return False


# --- keys -------------------------------------------------------------------

def public_b64(private: Ed25519PrivateKey) -> str:
    raw = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode("ascii")


def load_private(path: Path) -> Ed25519PrivateKey:
    path = Path(path)
    if os.name != "nt" and path.stat().st_mode & 0o077:
        raise ToolError(f"{path}: private key must not be readable by others (chmod 600)")
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ToolError(f"{path}: not an Ed25519 key")
    return key


def load_public(text: str) -> Ed25519PublicKey:
    raw = base64.b64decode(text.strip(), validate=True)
    if len(raw) != 32:
        raise ToolError("public key must be 32 bytes (base64)")
    return Ed25519PublicKey.from_public_bytes(raw)


def keygen(path: Path, allow_git: bool = False) -> str:
    path = Path(path)
    if path.exists():
        raise ToolError(f"{path} already exists: refusing to overwrite a key")
    if inside_git_tree(path) and not allow_git:
        raise ToolError(f"{path} is inside a git working tree: keep private keys out of repositories")
    path.parent.mkdir(parents=True, exist_ok=True)
    private = Ed25519PrivateKey.generate()
    pem = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_BINARY, 0o600)
    try:
        os.write(fd, pem)
        os.fsync(fd)
    finally:
        os.close(fd)
    if os.name != "nt":
        os.chmod(path, 0o600)
    return public_b64(private)


# --- sign / verify ------------------------------------------------------------

def sign_bytes(private: Ed25519PrivateKey, data: bytes) -> bytes:
    return base64.b64encode(private.sign(data)) + b"\n"


def verify_bytes(public_keys, data: bytes, signature: bytes) -> bool:
    try:
        raw = base64.b64decode(signature.strip(), validate=True)
    except ValueError:
        return False
    for text in public_keys:
        try:
            load_public(text).verify(raw, data)
            return True
        except (InvalidSignature, ValueError, ToolError):
            continue
    return False


# --- build ----------------------------------------------------------------------

def read_sums(path: Path) -> dict:
    """SHA256SUMS lines: '<hex>  <name>' or '<hex> *<name>'."""
    sums = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        digest, _, name = line.partition(" ")
        name = name.strip().lstrip("*")
        if len(digest) != 64 or not name:
            raise ToolError(f"bad SHA256SUMS line: {line}")
        sums[name] = digest.lower()
    return sums


def pick(names, patterns, explicit):
    if explicit:
        if explicit not in names:
            raise ToolError(f"{explicit} is not in SHA256SUMS")
        return explicit
    for pattern in patterns:
        found = sorted(n for n in names if fnmatch.fnmatch(n.lower(), pattern.lower()))
        if len(found) == 1:
            return found[0]
        if len(found) > 1:
            raise ToolError(f"several files match {pattern}: {found}; name one explicitly")
    return None


def notes_folder(changelog: Path, version: str) -> Path:
    folder = Path(changelog)
    return folder / version if (folder / version).is_dir() else folder


def changelog_critical(changelog: Path, version: str) -> bool:
    """Did tools/release.sh --critical mark this version as an urgent security fix?"""
    return (notes_folder(changelog, version) / CRITICAL_MARKER).is_file()


def read_notes(changelog: Path, version: str) -> dict:
    folder = notes_folder(changelog, version)
    notes = {}
    for lang in LANGUAGES:
        f = folder / f"{lang}.md"
        if f.is_file():
            notes[lang] = f.read_text(encoding="utf-8").strip() + "\n"
    if "en" not in notes:
        raise ToolError(f"{folder}: en.md is required (fallback language)")
    return notes


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build(version, channel, sums_path, dist, changelog, base_url, min_version="", critical=False,
          days=DEFAULT_DAYS, windows_file="", linux_file="", now=None) -> dict:
    version_tuple(version)
    if channel not in CHANNELS:
        raise ToolError("channel must be stable, test or proba")
    if channel == "proba":
        if base_url:
            raise ToolError("proba: files are plain names in the channel folder, no --base-url")
    elif not base_url.startswith("https://"):
        raise ToolError("--base-url must be https")
    marked = changelog_critical(changelog, version)
    if channel != "proba":   # the preview channel may try an urgent update without a release marker
        if marked and not critical:
            raise ToolError(f"CHANGELOG/{version}/{CRITICAL_MARKER} marks {version} as an urgent security fix: "
                            "pass --critical (or remove the marker if that was a mistake)")
        if critical and not marked:
            raise ToolError(f"--critical without CHANGELOG/{version}/{CRITICAL_MARKER}: an urgent release is "
                            "prepared with tools/release.sh --critical")
    now = now or datetime.now(timezone.utc)
    sums = read_sums(sums_path)
    files = {}
    for platform, patterns, explicit in (("windows", WINDOWS_PATTERNS, windows_file),
                                         ("linux", LINUX_PATTERNS, linux_file)):
        name = pick(list(sums), patterns, explicit)
        if name is None:
            continue
        local = Path(dist) / name
        if not local.is_file():
            raise ToolError(f"{local} not found (needed for the size and to confirm the sum)")
        if sha256_file(local) != sums[name]:
            raise ToolError(f"{name}: sha256 differs from SHA256SUMS")
        if channel == "proba" and not local_name_ok(name):
            raise ToolError(f"proba: {name} is not a plain file name")
        if channel != "proba" and "proba" in name.lower():
            raise ToolError(f"{name} is a preview (proba) build: it never goes into the {channel} channel")
        url = name if channel == "proba" else f"{base_url.rstrip('/')}/{name}"
        files[platform] = {"url": url, "size": local.stat().st_size, "sha256": sums[name]}
    if not files:
        raise ToolError("no Windows or Linux file in SHA256SUMS")
    doc = {"schema": 1, "channel": channel, "version": version, "released": utc(now),
           "expires": utc(now + timedelta(days=days))}
    if min_version:
        version_tuple(min_version)
        doc["min_version"] = min_version
    if critical:
        doc["critical"] = True
    doc["files"] = files
    doc["notes"] = read_notes(changelog, version)
    return doc


# --- release card ------------------------------------------------------------------

def release_card(doc: dict) -> str:
    """What the signer is asked to sign, in a few lines. Urgent documents start with a banner."""
    lines = []
    urgent = doc.get("critical") is True
    if urgent:
        bar = "!" * 64
        lines += [bar, f"!!! {URGENT_BANNER}",
                  "!!! programs offer it at once and on every start until it is installed", bar]
    lines.append(f"ClipSD {doc.get('version')}, channel {doc.get('channel')}"
                 + (f": {URGENT_BANNER}" if urgent else ", ordinary update (offered at most once a week)"))
    if doc.get("channel") == "proba":
        lines.append("PROBA: preview channel (a local folder for the owner's tests), never a release")
    lines.append(f"released {doc.get('released')}, expires {doc.get('expires')}"
                 + (f", min_version {doc['min_version']}" if doc.get("min_version") else ""))
    for platform, entry in sorted((doc.get("files") or {}).items()):
        if isinstance(entry, dict):
            lines.append(f"  {platform}: {entry.get('size')} bytes, sha256 {str(entry.get('sha256'))[:16]}..., "
                         f"{entry.get('url')}")
    notes = doc.get("notes") if isinstance(doc.get("notes"), dict) else {}
    lines.append("notes: " + ", ".join(sorted(notes)))
    return "\n".join(lines)


# --- checks before signing ------------------------------------------------------

def load_document(data: bytes) -> dict:
    """JSON object in canonical form: exactly the bytes dump() writes (no duplicate keys, no extra bytes)."""
    if len(data) > MAX_DOCUMENT_BYTES:
        raise ToolError("document is too large")
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ToolError(f"not json: {exc}") from None
    if not isinstance(doc, dict):
        raise ToolError("document is not a JSON object")
    if dump(doc) != data:
        raise ToolError("document is not in canonical form (written by channel_sign.py build)")
    return doc


def _check_file(name, entry, role: str = "stable") -> None:
    if not isinstance(entry, dict) or set(entry) != {"url", "size", "sha256"}:
        raise ToolError(f"files.{name} must have exactly url, size, sha256")
    url, size, digest = entry["url"], entry["size"], entry["sha256"]
    if role == "proba":
        if not local_name_ok(url):
            raise ToolError(f"files.{name}.url must be a plain file name in the proba folder")
    elif not isinstance(url, str) or not url.startswith("https://") or len(url) <= len("https://") \
            or any(c.isspace() for c in url):
        raise ToolError(f"files.{name}.url must be an https address")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise ToolError(f"files.{name}.size must be a positive integer")
    if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
        raise ToolError(f"files.{name}.sha256 must be 64 lowercase hex digits")


def check_document(data: bytes, role: str, now=None, fresh=True) -> dict:
    """Everything the signer checks before a signature. Raises ToolError, returns the parsed document.

    role is the channel of the key (stable|test): a document of the other channel is never signed.
    fresh: a new document (released must be recent, expires <= released + 120 days); a refresh only
    keeps expires <= now + 120 days, because "released" stays as it was.
    """
    if role not in CHANNELS:
        raise ToolError("role must be stable, test or proba")
    now = now or datetime.now(timezone.utc)
    doc = load_document(data)
    unknown = set(doc) - TOP_LEVEL_KEYS
    if unknown:
        raise ToolError(f"unknown fields: {sorted(unknown)}")
    if doc.get("schema") != 1 or isinstance(doc.get("schema"), bool):
        raise ToolError(f"schema must be 1, not {doc.get('schema')!r}")
    if doc.get("channel") != role:
        raise ToolError(f"document channel {doc.get('channel')!r} does not match the key role {role!r}")
    version = version_tuple(doc.get("version"))
    if "min_version" in doc and version_tuple(doc["min_version"]) > version:
        raise ToolError("min_version is higher than version")
    if "critical" in doc and not isinstance(doc["critical"], bool):
        raise ToolError("critical must be true or false")
    released, expires = parse_utc(doc.get("released")), parse_utc(doc.get("expires"))
    if expires <= released:
        raise ToolError("expires is not after released")
    if expires <= now:
        raise ToolError(f"expires {doc['expires']} is already in the past")
    if expires > now + timedelta(days=MAX_DAYS_AHEAD):
        raise ToolError(f"expires is more than {MAX_DAYS_AHEAD} days ahead")
    if fresh:
        if released > now + RELEASED_FUTURE_TOLERANCE:
            raise ToolError("released is in the future")
        if expires > released + timedelta(days=MAX_DAYS_AFTER_RELEASE):
            raise ToolError(f"expires is more than {MAX_DAYS_AFTER_RELEASE} days after released")
    files = doc.get("files")
    if not isinstance(files, dict) or not files:
        raise ToolError("files must name at least one platform")
    if set(files) - set(PLATFORMS):
        raise ToolError(f"unknown platforms in files: {sorted(set(files) - set(PLATFORMS))}")
    for name, entry in files.items():
        _check_file(name, entry, role)
    notes = doc.get("notes")
    if not isinstance(notes, dict) or not isinstance(notes.get("en"), str) or \
            not all(isinstance(k, str) and isinstance(v, str) for k, v in notes.items()):
        raise ToolError("notes must map languages to text and include en")
    return doc


def without_expires(doc: dict) -> bytes:
    """Normalized bytes of a document apart from its expiry: what a refresh must keep byte for byte."""
    rest = dict(doc)
    rest.pop("expires", None)
    return dump(rest)


def check_against_last(doc: dict, last: dict, refresh_mode: bool) -> None:
    """Compare with the signer's own copy of the last signed document."""
    if last.get("channel") != doc.get("channel"):
        raise ToolError("last signed copy belongs to another channel")
    if version_tuple(doc.get("version")) < version_tuple(last.get("version")):
        raise ToolError(f"version {doc.get('version')} is lower than the last signed {last.get('version')}")
    if version_tuple(doc.get("version")) == version_tuple(last.get("version")) and \
            (doc.get("critical") is True) != (last.get("critical") is True):
        raise ToolError(f"version {doc.get('version')} was signed with critical={last.get('critical') is True}: "
                        "the urgency of a signed version never changes; release a new version instead")
    if refresh_mode and without_expires(doc) != without_expires(last):
        raise ToolError("refresh: the document differs from the last signed copy (only expires may change)")


def read_last_signed(path: Path, allow_git: bool, required: bool):
    """The signer's copy of the last signed latest.json, or None when there is none yet (first release)."""
    path = Path(path)
    if inside_git_tree(path) and not allow_git:
        raise ToolError(f"{path} is inside a git working tree: --last-signed must be the signer's own copy")
    if not path.exists():
        if required:
            raise ToolError(f"{path} not found: refresh needs the signer's copy of the last signed document")
        return None
    return load_document(path.read_bytes())


def refresh(data: bytes, days: int, now=None) -> bytes:
    """New expires, nothing else. Raises ToolError if anything else would change."""
    now = now or datetime.now(timezone.utc)
    old = load_document(data)
    new = dict(old)
    new_expires = now + timedelta(days=days)
    if new_expires <= parse_utc(old.get("expires")):
        raise ToolError("the new expiry is not later than the current one")
    new["expires"] = utc(new_expires)
    out = dump(new)
    check_only_expires_changed(data, out)
    return out


def check_only_expires_changed(old: bytes, new: bytes) -> None:
    a, b = json.loads(old.decode("utf-8")), json.loads(new.decode("utf-8"))
    if without_expires(a) != without_expires(b):
        raise ToolError("refresh may change only 'expires'")


def sign_command(private_path, role, inp, out="", refresh_mode=False, days=DEFAULT_DAYS, public=(),
                 last_signed="", allow_git=False, now=None, critical_ack=False, show=print) -> Path:
    """The whole sign step. Nothing is written unless every check passes. Returns the signature path.

    The release card goes to show() BEFORE the signature is made. A new urgent document ("critical":
    true) is signed only with critical_ack (--critical): the signer has read "СРОЧНО" on the card;
    --critical for a document that is not urgent is refused too."""
    now = now or datetime.now(timezone.utc)
    inp = Path(inp)
    sig_path = Path(out or str(inp) + ".sig")
    if last_signed and Path(last_signed).resolve() in (inp.resolve(), sig_path.resolve()):
        raise ToolError("--last-signed must be a separate copy kept by the signer")
    private = load_private(Path(private_path))
    data = inp.read_bytes()
    if refresh_mode:
        if not public:
            raise ToolError("--refresh needs --public: the current file must carry a valid signature")
        if not last_signed:
            raise ToolError("--refresh needs --last-signed: the signer's copy of the last signed document")
        if public_b64(private) not in [k.strip() for k in public]:
            raise ToolError("the private key is not one of the --public keys of this channel")
        old_sig = sig_path.read_bytes() if sig_path.exists() else b""
        if not verify_bytes(public, data, old_sig):
            raise ToolError("current file is not signed by the given key: refusing to refresh")
        last = read_last_signed(Path(last_signed), allow_git, required=True)
        check_against_last(load_document(data), last, refresh_mode=True)
        data = refresh(data, days, now)
        check_document(data, role, now, fresh=False)
    else:
        doc = check_document(data, role, now, fresh=True)
        if last_signed:
            last = read_last_signed(Path(last_signed), allow_git, required=False)
            if last is not None:
                check_against_last(doc, last, refresh_mode=False)
    doc_now = load_document(data)
    show(release_card(doc_now))
    urgent = doc_now.get("critical") is True
    if not refresh_mode and urgent and not critical_ack:
        raise ToolError(f"{URGENT_BANNER}: read the card above and sign again with --critical to confirm")
    if critical_ack and not urgent:
        raise ToolError("--critical, but the document is not urgent (no \"critical\": true): nothing signed")
    signature = sign_bytes(private, data)
    if refresh_mode:
        write_atomic(inp, data)
    write_atomic(sig_path, signature)
    if last_signed:
        write_atomic(Path(last_signed), data, 0o600)
    return sig_path


# --- command line -------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="channel_sign.py", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("keygen")
    p.add_argument("--private", required=True)
    p.add_argument("--allow-git-tree", action="store_true", help=argparse.SUPPRESS)  # tests only

    p = sub.add_parser("pubkey")
    p.add_argument("--private", required=True)

    p = sub.add_parser("build")
    p.add_argument("--version", required=True)
    p.add_argument("--channel", required=True, choices=list(CHANNELS))
    p.add_argument("--sums", required=True)
    p.add_argument("--dist", required=True)
    p.add_argument("--changelog", required=True)
    p.add_argument("--base-url", default="")
    p.add_argument("--out", required=True)
    p.add_argument("--min-version", default="")
    p.add_argument("--critical", action="store_true")
    p.add_argument("--days", type=int, default=DEFAULT_DAYS)
    p.add_argument("--windows-file", default="")
    p.add_argument("--linux-file", default="")

    p = sub.add_parser("sign")
    p.add_argument("--private", required=True)
    p.add_argument("--role", required=True, choices=list(CHANNELS))
    p.add_argument("--in", dest="inp", required=True)
    p.add_argument("--out", default="")
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--days", type=int, default=DEFAULT_DAYS)
    p.add_argument("--public", action="append", default=[])
    p.add_argument("--last-signed", default="")
    p.add_argument("--critical", action="store_true",
                   help="confirm signing an urgent security fix (the card with СРОЧНО is printed first)")
    p.add_argument("--allow-git-tree", action="store_true", help=argparse.SUPPRESS)  # tests only

    p = sub.add_parser("card")
    p.add_argument("--in", dest="inp", required=True)

    p = sub.add_parser("verify")
    p.add_argument("--public", action="append", required=True)
    p.add_argument("--in", dest="inp", required=True)
    p.add_argument("--sig", default="")
    p.add_argument("--channel", default="")

    args = parser.parse_args(argv)
    try:
        if args.cmd == "keygen":
            print(keygen(Path(args.private), args.allow_git_tree))
        elif args.cmd == "pubkey":
            print(public_b64(load_private(Path(args.private))))
        elif args.cmd == "build":
            doc = build(args.version, args.channel, args.sums, args.dist, args.changelog, args.base_url,
                        args.min_version, args.critical, args.days, args.windows_file, args.linux_file)
            write_atomic(Path(args.out), dump(doc))
            print(release_card(doc))
            print(f"{args.out}: {args.channel} {args.version}, expires {doc['expires']}")
        elif args.cmd == "sign":
            sig_path = sign_command(args.private, args.role, args.inp, args.out, args.refresh, args.days,
                                    args.public, args.last_signed, args.allow_git_tree,
                                    critical_ack=args.critical)
            print(f"signed {args.inp} -> {sig_path}")
        elif args.cmd == "card":
            print(release_card(load_document(Path(args.inp).read_bytes())))
        elif args.cmd == "verify":
            data = Path(args.inp).read_bytes()
            sig = Path(args.sig or args.inp + ".sig").read_bytes()
            if not verify_bytes(args.public, data, sig):
                print("FAIL: signature does not match", file=sys.stderr)
                return 1
            doc = json.loads(data.decode("utf-8"))
            if args.channel and doc.get("channel") != args.channel:
                print(f"FAIL: channel {doc.get('channel')} != {args.channel}", file=sys.stderr)
                return 1
            if parse_utc(doc["expires"]) < datetime.now(timezone.utc):
                print(f"FAIL: expired {doc['expires']}", file=sys.stderr)
                return 1
            print(release_card(doc))
            print(f"OK {doc.get('channel')} {doc.get('version')} expires {doc['expires']}")
    except (ToolError, OSError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
