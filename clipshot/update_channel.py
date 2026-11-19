# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
"""Update channel trust: embedded keys, Ed25519 signature check, expiry, version rules.

This module is the "signature check module" of architecture.md section 2: the signer hashes this
file and warns on the release card when it changes. Keep it small, pure (no Qt, no network) and
change it only with an independent code review.

Channel format (ADR-0001): latest.json
    {"schema": 1, "channel": "stable", "version": "2.0.1", "released": "...Z", "expires": "...Z",
     "min_version": "2.0.0"?, "critical": false?,
     "files": {"windows": {"url", "size", "sha256"}, "linux": {...}},
     "notes": {"<lang>": "markdown"}, "heartbeat": ...?}
and latest.json.sig: base64 of the Ed25519 signature over the exact bytes of latest.json.

Key rules:
- stable accepts only the signer's primary or backup key and NEVER a test or proba key (even if one
  was pasted into STABLE_PUBLIC_KEYS by mistake, it is filtered out);
- test accepts only the test key, never a proba key;
- proba (the owner's preview tests, a local folder) exists only in a preview build
  (build_info.PREVIEW): its own key, never a stable or test key; files are plain names inside the
  channel folder instead of https addresses. A release build has no proba key and refuses the channel;
- placeholder keys (not valid base64 of 32 bytes) are ignored, so a build with placeholders only
  accepts nothing.
"""

import base64
import binascii
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

CHANNEL_URLS = {
    "stable": "https://clipsd.github.io/channel/stable/latest.json",
    "test": "https://clipsd.github.io/channel-test/latest.json",
}
SIGNATURE_SUFFIX = ".sig"
CHANNELS = ("stable", "test", "proba")

# Raw Ed25519 public keys, base64 (32 bytes). Printed by tools/channel_sign.py keygen.
# Stable channel keys (created 19.11.2026): the private parts are kept only by the owner, never in this repository.
STABLE_PUBLIC_KEYS = (
    "8zDz0dfCJfRDiQ1cXdGyhizz6LIJuQvjx6B7YrhWR3Q=",   # primary, private part only at the owner
    "AHXQY98N2SOGkKO5Ext0BYypa5+sqYrp3hTyTTeGxyw=",   # backup, private part only at the owner
)
# TODO(release workflow): the test key is generated for GitHub Actions (secret) and pasted here.
TEST_PUBLIC_KEYS = (
    "TODO-test-channel-public-key",
)
# The proba (preview) channel key, embedded in every build only as a FORBIDDEN key: stable and test
# never trust it, whatever their lists say. It is not a secret; the preview build gets it as a trusted
# key from its generated module (build_info). The same key is in packaging/proba-public-key.txt.
PREVIEW_ONLY_KEYS = (
    "SBq9Ms9skCqSpbhz2IUefATXQ8YZ0muE6/pnbuJUWKY=",
)

SCHEMA = 1
CLOCK_TOLERANCE = timedelta(days=2)      # user clocks may be wrong by this much
# Upper bound of a document's validity. Counted from the reader's clock, not from "released": the
# refresh rule (ADR-0011) re-signs the same content, "released" included, with a new "expires" every
# 60 days, so a bound on released would reject every refreshed document after the first refresh.
MAX_VALIDITY = timedelta(days=120)
MAX_DOCUMENT_BYTES = 256 * 1024
PLATFORMS = ("windows", "linux")
_VERSION_RE = re.compile(r"^[0-9]{1,4}(\.[0-9]{1,4}){0,3}$")   # ASCII digits only
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_LOCAL_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}")   # proba: a file name, no folders
_WINDOWS_DEVICE_RE = re.compile(r"(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?", re.IGNORECASE)


class ChannelError(Exception):
    """A channel document that must not be trusted. code is stable for logs and telemetry."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


# --- versions --------------------------------------------------------------

def parse_version(text) -> tuple:
    """'2.0.10' -> (2, 0, 10, 0). Trailing zeros are padded, so 2.0 == 2.0.0. Raises ValueError."""
    if not isinstance(text, str) or not _VERSION_RE.fullmatch(text.strip()):
        raise ValueError(f"bad version: {text!r}")
    parts = [int(p) for p in text.strip().split(".")]
    return tuple(parts + [0] * (4 - len(parts)))


def compare_versions(a: str, b: str) -> int:
    """-1, 0 or 1 like the old cmp(): numeric per part, so 2.0.10 > 2.0.9."""
    pa, pb = parse_version(a), parse_version(b)
    return (pa > pb) - (pa < pb)


# --- time ------------------------------------------------------------------

def parse_utc(text) -> datetime:
    """ISO 8601 with Z or an offset -> aware UTC datetime. Naive times are rejected."""
    if not isinstance(text, str):
        raise ValueError("time is not a string")
    value = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("time without timezone")
    return value.astimezone(timezone.utc)


def format_utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# --- keys and signature ----------------------------------------------------

def _load_key(text):
    """Base64 raw key -> Ed25519PublicKey, or None for placeholders and garbage."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        raw = base64.b64decode(text.strip(), validate=True)
    except (binascii.Error, ValueError, AttributeError):
        return None
    if len(raw) != 32:
        return None
    try:
        return Ed25519PublicKey.from_public_bytes(raw)
    except ValueError:
        return None


def _normalize(text) -> bytes:
    try:
        return base64.b64decode(str(text).strip(), validate=True)
    except (binascii.Error, ValueError):
        return b""


def local_name_ok(name) -> bool:
    """A file name of the proba folder: letters, digits, ".", "_", "-" only (whole string), no "..",
    no trailing dot, not a Windows device name (CON, NUL, COM1.exe ...)."""
    return (isinstance(name, str) and _LOCAL_NAME_RE.fullmatch(name) is not None and ".." not in name
            and not name.endswith(".") and _WINDOWS_DEVICE_RE.fullmatch(name) is None)


def preview_build() -> bool:
    from . import build_info
    return build_info.is_preview()


def trusted_keys(channel: str, stable_keys=None, test_keys=None, proba_keys=None) -> list:
    """Usable keys for a channel. No key of one channel is ever trusted by another one; the proba
    channel has keys only in a preview build (in a release build it gets none, whatever is passed)."""
    from . import build_info
    stable_keys = STABLE_PUBLIC_KEYS if stable_keys is None else stable_keys
    test_keys = TEST_PUBLIC_KEYS if test_keys is None else test_keys
    proba_keys = build_info.proba_keys() if proba_keys is None else proba_keys

    def raw(keys):
        return {_normalize(k) for k in keys} - {b""}

    preview_only = raw(PREVIEW_ONLY_KEYS) | raw(proba_keys)
    if channel == "stable":
        banned = raw(test_keys) | preview_only
        candidates = [k for k in stable_keys if _normalize(k) not in banned]
    elif channel == "test":
        banned = preview_only
        candidates = [k for k in test_keys if _normalize(k) not in banned]
    elif channel == "proba":
        if not preview_build():
            return []   # a release build never trusts the preview channel
        banned = raw(stable_keys) | raw(test_keys)
        candidates = [k for k in proba_keys if _normalize(k) not in banned]
    else:
        raise ChannelError("unknown_channel", str(channel))
    return [key for key in (_load_key(k) for k in candidates) if key is not None]


def verify_signature(document: bytes, signature, channel: str, stable_keys=None, test_keys=None,
                     proba_keys=None) -> None:
    """Raise ChannelError unless one trusted key of the channel signed exactly these bytes."""
    from cryptography.exceptions import InvalidSignature
    keys = trusted_keys(channel, stable_keys, test_keys, proba_keys)
    if not keys:
        raise ChannelError("no_keys", f"no usable public key for channel {channel}")
    if isinstance(signature, bytes):
        signature = signature.decode("ascii", "replace")
    raw = _normalize(signature or "")
    if len(raw) != 64:
        raise ChannelError("bad_signature", "signature missing or malformed")
    for key in keys:
        try:
            key.verify(raw, document)
            return
        except InvalidSignature:
            continue
    raise ChannelError("bad_signature", "no trusted key matches")


# --- document --------------------------------------------------------------

@dataclass
class Manifest:
    channel: str
    version: str
    released: datetime
    expires: datetime
    files: dict
    notes: dict = field(default_factory=dict)
    min_version: str = ""
    critical: bool = False
    raw: dict = field(default_factory=dict)

    def file_for(self, platform: str):
        return self.files.get(platform)

    def notes_for(self, lang: str) -> str:
        """Notes in the program language, else English, else any language, else empty."""
        for key in (lang, "en"):
            if isinstance(self.notes.get(key), str):
                return self.notes[key]
        for value in self.notes.values():
            if isinstance(value, str):
                return value
        return ""


def _check_file(name, entry, channel: str = "stable") -> dict:
    if not isinstance(entry, dict):
        raise ChannelError("bad_document", f"files.{name} is not an object")
    url, size, digest = entry.get("url"), entry.get("size"), entry.get("sha256")
    if channel == "proba":
        # preview channel: a file name inside the channel folder, never an address or a path
        if not local_name_ok(url):
            raise ChannelError("bad_document", f"files.{name}.url must be a file name of the proba folder")
    elif not isinstance(url, str) or not url.startswith("https://"):
        raise ChannelError("bad_document", f"files.{name}.url must be https")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise ChannelError("bad_document", f"files.{name}.size")
    if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest.lower()):
        raise ChannelError("bad_document", f"files.{name}.sha256")
    return {"url": url, "size": size, "sha256": digest.lower()}


def parse_manifest(document: bytes, channel: str) -> Manifest:
    """Structure check only. Call verify_signature first: never parse unsigned bytes for decisions."""
    if channel not in CHANNELS or (channel == "proba" and not preview_build()):
        raise ChannelError("unknown_channel", str(channel))
    if len(document) > MAX_DOCUMENT_BYTES:
        raise ChannelError("bad_document", "too large")
    try:
        doc = json.loads(document.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ChannelError("bad_document", f"not json: {exc}") from None
    if not isinstance(doc, dict):
        raise ChannelError("bad_document", "not an object")
    if doc.get("schema") != SCHEMA:
        raise ChannelError("bad_schema", repr(doc.get("schema")))
    if doc.get("channel") != channel:
        raise ChannelError("wrong_channel", f"{doc.get('channel')!r} != {channel!r}")
    try:
        parse_version(doc.get("version"))
        released = parse_utc(doc.get("released"))
        expires = parse_utc(doc.get("expires"))
        min_version = doc.get("min_version") or ""
        if min_version:
            parse_version(min_version)
    except ValueError as exc:
        raise ChannelError("bad_document", str(exc)) from None
    files = doc.get("files")
    if not isinstance(files, dict) or not files:
        raise ChannelError("bad_document", "files")
    checked = {name: _check_file(name, entry, channel) for name, entry in files.items() if name in PLATFORMS}
    notes = doc.get("notes") if isinstance(doc.get("notes"), dict) else {}
    return Manifest(channel=channel, version=doc["version"].strip(), released=released, expires=expires,
                    files=checked, notes=notes, min_version=min_version,
                    critical=doc.get("critical") is True, raw=doc)


def check_expiry(manifest: Manifest, now: datetime) -> None:
    """Expired documents and documents valid for too long (a far "expires" would let a frozen or
    replayed channel live for years) are both refused."""
    if now > manifest.expires + CLOCK_TOLERANCE:
        raise ChannelError("expired", format_utc(manifest.expires))
    if manifest.expires > now + MAX_VALIDITY + CLOCK_TOLERANCE:
        raise ChannelError("expires_far", format_utc(manifest.expires))   # usually a wrong clock here


def check_rollback(manifest: Manifest, last_seen_version: str) -> None:
    """The channel may never go back below a version this program has already seen signed."""
    if last_seen_version:
        try:
            if compare_versions(manifest.version, last_seen_version) < 0:
                raise ChannelError("rollback", f"{manifest.version} < {last_seen_version}")
        except ValueError:
            pass   # a damaged config value must not block updates forever


def load_verified(document: bytes, signature, channel: str, now: datetime, last_seen_version: str = "",
                  stable_keys=None, test_keys=None, proba_keys=None) -> Manifest:
    """Full trust chain: signature -> structure -> expiry -> rollback. Raises ChannelError."""
    verify_signature(document, signature, channel, stable_keys, test_keys, proba_keys)
    manifest = parse_manifest(document, channel)
    check_expiry(manifest, now)
    check_rollback(manifest, last_seen_version)
    return manifest


def is_newer(manifest: Manifest, installed_version: str) -> bool:
    return compare_versions(manifest.version, installed_version) > 0
