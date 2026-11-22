# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Photo from phone: the receiver in the home network (no Qt widgets here; the window is phone_ui.py).

While the window "Photo from phone" is open, ClipSD listens on the address of this computer in the home network
(not 0.0.0.0, not the address of a VPN) and gives the phone one page. The address and a one-time code go into the
QR code: http://<lan ip>:<port>/<code>. Nothing leaves the home network: no server on the internet, no account,
no app on the phone. Specification and threat model: specs/005-clipsd-otkrytaya-versiya/foto-s-telefona/.

Rules (each one is checked by tests/phone_test.py):
- the code: 8 characters of an alphabet without look-alikes (0/o, 1/l/i), random from `secrets`, compared in
  constant time; valid CLAIM_TTL seconds until a phone opens it;
- the first phone that opens the code takes it: the code is bound to that phone's address, the page gets a key
  for ONE upload; every accepted photo returns the next key, a used key never works again; the same phone may
  reload the page (Android sometimes drops the tab while the camera is open), another address gets 409;
- a photo: POST with Content-Length (no chunked), at most MAX_BYTES, type jpeg/png/webp by header and by the
  first bytes, decoded before the answer (a file that is not a picture is refused), at most MAX_PHOTOS per open;
- the request must name this receiver in Host (DNS rebinding) and, for the upload, come from this page (Origin,
  Sec-Fetch-Site); the client must be in the subnet of the chosen interface;
- MAX_BAD wrong codes or keys close the receiver (somebody in the network is guessing);
- at most MAX_CONNECTIONS connections at a time and MAX_PER_IP per device (the bound phone keeps its slots),
  a socket timeout per connection, an overall deadline per upload;
- after IDLE_TTL seconds (AFTER_PHOTO_TTL once a photo has come) without a photo the receiver closes; stop() closes the socket and every connection.
"""

import hmac
import http.server
import ipaddress
import json
import os
import secrets
import shutil
import socket
import sys
import threading
import time
import urllib.parse

TOKEN_ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"
TOKEN_LEN = 8
KEY_BYTES = 24
CLAIM_TTL = 180          # s: the code lives 3 minutes until a phone opens it
IDLE_TTL = 600           # s: after the phone came, the receiver closes after 10 minutes without a photo
AFTER_PHOTO_TTL = 180    # s: each photo extends the reception by 3 minutes from the last photo ("Send and take another")
MAX_PHOTOS = 20          # per opening of the window
MAX_BYTES = 25 * 1024 * 1024
MAX_PIXELS = 60_000_000  # 60 MP: bigger than any phone camera (Samsung 50 MP is 8160 x 6120)
MAX_BAD = 20             # wrong codes or keys per opening of the window
MAX_CONNECTIONS = 24     # open connections at a time, all devices together (a slow one is dropped for a new one)
MAX_PER_IP = 3           # per device: one device cannot take every slot; the bound phone keeps its own
SOCKET_TIMEOUT = 15      # s without a byte: the connection is closed (slow clients)
HEADER_DEADLINE = 8      # s for the whole request line and headers (a byte every few seconds does not keep a slot)
UPLOAD_DEADLINE = 120    # s for the whole body of one photo
PROGRESS_EVERY = 0.1     # s: how often the window of the computer is told how much of the photo has come
PREFERRED_PORTS = tuple(range(8765, 8768))   # 3 ports: a stable port helps a firewall rule; else any free one
LISTEN_PORTS = None      # tests: () = always a free port of the system (runs of several agents do not fight for 8765-8767)
HEIC_BRANDS = (b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1", b"avif")
SEEN_MAX = 64            # photo ids remembered, so a repeated upload of the same photo is not opened twice
IMAGE_MAGIC = {"image/jpeg": (b"\xff\xd8\xff",), "image/png": (b"\x89PNG\r\n\x1a\n",), "image/webp": (b"RIFF",)}

# states of a session
WAITING, PAIRED, CLOSED = "waiting", "paired", "closed"


def new_token() -> str:
    return "".join(secrets.choice(TOKEN_ALPHABET) for _ in range(TOKEN_LEN))


def _looks_like_code(segment: str) -> bool:
    """A guess at the code (counted as a wrong attempt), not /favicon.ico or /apple-touch-icon.png."""
    return 4 <= len(segment) <= 16 and segment.isalnum()


def sniff_type(data: bytes):
    for mime, magics in IMAGE_MAGIC.items():
        for magic in magics:
            if data.startswith(magic) and (mime != "image/webp" or data[8:12] == b"WEBP"):
                return mime
    return None


def decode_image(data: bytes):
    """QImage of the photo (EXIF orientation applied, metadata dropped) or None. Safe outside the GUI thread."""
    from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
    from PyQt6.QtGui import QImageReader
    buf = QBuffer()
    buf.setData(QByteArray(data))
    buf.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buf)
    reader.setAutoTransform(True)
    size = reader.size()
    if not size.isValid() or size.width() * size.height() > MAX_PIXELS:
        return None
    image = reader.read()
    return None if image.isNull() else image


def is_heic(data: bytes) -> bool:
    return len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in HEIC_BRANDS


def quick_check(data: bytes):
    """The fast check before the answer to the phone, without decoding: None when the bytes may be a photo, else the
    error ("heic", "type"). Type by the first bytes, size of the picture from the header (QImageReader.size())."""
    if is_heic(data):
        return "heic"
    if sniff_type(data) is None:
        return "type"
    from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
    from PyQt6.QtGui import QImageReader
    buf = QBuffer()
    buf.setData(QByteArray(data))
    buf.open(QIODevice.OpenModeFlag.ReadOnly)
    size = QImageReader(buf).size()
    if not size.isValid() or size.width() * size.height() > MAX_PIXELS:
        return "type"
    return None


def prepare_image(image, mode: str = "fit", screen=None):
    """The decoded photo as it goes to the editor: no metadata (EXIF with GPS never reaches the editor or the saved
    file: only pixels are kept), and for mode "fit" scaled down to the screen of this computer (never up), smooth.
    Runs in a worker thread, not in the interface thread."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QImage
    if image is None or image.isNull():
        return None
    from PyQt6.QtGui import QPainter
    fmt = QImage.Format.Format_ARGB32 if image.hasAlphaChannel() else QImage.Format.Format_RGB32
    clean = QImage(image.width(), image.height(), fmt)   # a new image painted from the old: no text keys, nothing carried
    clean.fill(0)
    painter = QPainter(clean)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    painter.drawImage(0, 0, image)
    painter.end()
    image = clean
    if mode != "orig" and screen and screen[0] and screen[1]:
        w, h = image.width(), image.height()
        k = min(1.0, screen[0] / w, screen[1] / h)
        if k < 1.0:
            image = image.scaled(max(1, round(w * k)), max(1, round(h * k)), Qt.AspectRatioMode.IgnoreAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
    return image


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    # Windows: SO_REUSEADDR would let another program bind the same port; SO_EXCLUSIVEADDRUSE instead
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def process_request(self, request, client_address):
        rx = self.receiver
        ip = client_address[0]
        victims = []
        with rx._lock:
            same = sum(1 for v in rx._conns.values() if v == ip)
            others = len(rx._conns) - sum(1 for v in rx._conns.values() if v == rx.phone_ip)
            limit = MAX_CONNECTIONS
            if rx.state == PAIRED and ip != rx.phone_ip:
                limit = MAX_CONNECTIONS - MAX_PER_IP   # slots of the bound phone stay free
                busy_total = others >= limit
            else:
                busy_total = len(rx._conns) >= limit
            busy_ip = same >= MAX_PER_IP
            # a new connection never waits behind a slow one: the oldest one that still has not sent its request
            # (the same device first, then anybody) gives its place
            if busy_ip:
                victim = rx._oldest_header(ip)
                if victim is not None:
                    victims.append(victim)
                    busy_ip = False
            if busy_total:
                victim = rx._oldest_header(None, skip=victims)
                if victim is not None:
                    victims.append(victim)
                    busy_total = False
            busy = busy_ip or busy_total
            for v in victims:
                rx._conns.pop(v, None)
                rx._hdr.pop(v, None)
            if not busy:
                rx._conns[request] = ip
                rx._hdr[request] = time.monotonic()
        for v in victims:
            try:
                v.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if busy:
            self.shutdown_request(request)
            return
        super().process_request(request, client_address)

    def shutdown_request(self, request):
        with self.receiver._lock:
            self.receiver._conns.pop(request, None)
            self.receiver._hdr.pop(request, None)
        super().shutdown_request(request)

    def handle_error(self, request, client_address):
        pass   # a broken connection of a phone is not an error of the program


class _Handler(http.server.BaseHTTPRequestHandler):
    server_version = "ClipSD"
    sys_version = ""
    timeout = SOCKET_TIMEOUT
    _header_timer = None

    def setup(self):
        super().setup()
        # the whole request line and the headers within HEADER_DEADLINE: one byte every few seconds is not a request
        self._header_timer = threading.Timer(HEADER_DEADLINE, self._header_late)
        self._header_timer.daemon = True
        self._header_timer.start()

    def _header_late(self):
        try:
            self.request.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def parse_request(self):
        ok = super().parse_request()   # reads the headers too
        if self._header_timer is not None:
            self._header_timer.cancel()
        with self.server.receiver._lock:
            self.server.receiver._hdr.pop(self.request, None)
        return ok

    def finish(self):
        if self._header_timer is not None:
            self._header_timer.cancel()
        super().finish()

    def log_message(self, fmt, *args):
        pass   # no log with addresses and codes

    # --- answers ---------------------------------------------------------------

    def _send(self, status: int, body: bytes = b"", ctype: str = "text/plain; charset=utf-8", extra=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Connection", "close")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
        self.close_connection = True

    def _send_json(self, status: int, data: dict):
        self._send(status, json.dumps(data).encode(), "application/json")

    def _send_page(self, status: int, html: str, nonce: str):
        csp = (f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; img-src blob: data:; "
               "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self._send(status, html.encode("utf-8"), "text/html; charset=utf-8", {"Content-Security-Policy": csp})

    def _message_page(self, status: int, text_key: str):
        rx = self.server.receiver
        from .phone_page import render_message
        nonce = secrets.token_urlsafe(12)
        self._send_page(status, render_message(rx.texts, rx.lang, rx.texts.get(text_key, ""), nonce), nonce)

    # --- checks ------------------------------------------------------------------

    def _gate(self):
        """(receiver, path parts) or None after an answer: host, client network, closed receiver."""
        rx = self.server.receiver
        if self.headers.get("Host", "") != rx.authority:
            self._send(400, b"bad host")
            return None
        if not rx.client_allowed(self.client_address[0]):
            self._send(403, b"forbidden")
            return None
        path = urllib.parse.urlsplit(self.path).path
        parts = [p for p in path.split("/") if p]
        return rx, parts

    def _log_timing(self, rx):
        """X-ClipSD-Timing: step times measured on the phone (debug of the demo only: letters, digits and =;.,: -)."""
        text = self.headers.get("X-ClipSD-Timing", "")
        if text and len(text) <= 200 and all(c.isalnum() or c in "=;.,: _-" for c in text):
            rx._emit("timing", {"text": text})

    # --- requests ----------------------------------------------------------------

    def do_GET(self):
        gate = self._gate()
        if gate is None:
            return
        rx, parts = gate
        if not parts or not hmac.compare_digest(parts[0].encode(), rx.token.encode()):
            if parts and _looks_like_code(parts[0]):
                rx._bad_attempt()
            self._send(404, b"not found")
            return
        ip = self.client_address[0]
        if len(parts) == 1:
            result, key = rx._claim(ip)
            if result == "ok":
                from .phone_page import render_page
                nonce = secrets.token_urlsafe(12)
                self._send_page(200, render_page(rx.texts, rx.lang, f"/{rx.token}", key, nonce, screen=rx.screen), nonce)
            elif result == "taken":
                self._message_page(409, "page_used")
            else:
                self._message_page(410, "page_closed")
            return
        if parts[1:] == ["key"]:
            # the page lost its key (a response got lost, "Cancel" while the computer had just accepted the photo):
            # the bound phone gets a fresh one; nobody else, and not while a photo is still arriving
            result, fresh = rx._refresh_key(ip)
            if result == "ok":
                self._send_json(200, {"key": fresh})
            else:
                self._send_json({"busy": 409, "taken": 409, "closed": 410}.get(result, 403), {"error": result})
            return
        if parts[1:] == ["alive"]:
            ok = rx._key_ok(ip, self.headers.get("X-ClipSD-Key", ""), count=False)
            if ok:
                self._log_timing(rx)
                self._send_json(200, dict({"left": rx.time_left(), "failed": rx.failed_to_report()}, **rx.confirmations()))
            else:
                self._send(410)
            return
        self._send(404, b"not found")

    def do_POST(self):
        gate = self._gate()
        if gate is None:
            return
        rx, parts = gate
        if len(parts) != 2 or parts[1] not in ("photo", "close") \
                or not hmac.compare_digest(parts[0].encode(), rx.token.encode()):
            if parts and _looks_like_code(parts[0]):
                rx._bad_attempt()
            self._send(404, b"not found")
            return
        origin = self.headers.get("Origin")
        site = self.headers.get("Sec-Fetch-Site")
        if (origin is not None and origin != f"http://{rx.authority}") or (site is not None and site != "same-origin"):
            self._send_json(403, {"error": "origin"})
            return
        ip = self.client_address[0]
        key = self.headers.get("X-ClipSD-Key", "")
        if parts[1] == "close":   # "Close" on the phone: the phone ends the reception (only with the key of this phone)
            if rx._key_ok(ip, key):
                self._log_timing(rx)
                answer = rx.confirmations()
                rx._close("phone")           # closed first: the answer says it is
                self._send_json(200, answer)
            else:
                self._send_json(403, {"error": "key"})
            return
        pid = self.headers.get("X-ClipSD-Photo", "")
        pid = pid if 8 <= len(pid) <= 40 and all(c in "0123456789abcdef" for c in pid) else ""
        dup = rx._dup_key(ip, pid) if pid else None
        if dup is not None:   # the same photo again (the answer got lost, the tab was in the background): already received
            self._send_json(200, {"dup": True, "key": dup, "count": rx.photos})
            return
        self._log_timing(rx)
        ticket = rx._begin_upload(ip, key)
        if ticket != "ok":
            self._send_json({"limit": 429, "closed": 410, "busy": 409}.get(ticket, 403), {"error": ticket})
            return
        try:
            status, answer = self._receive_photo(rx, pid)
        except (OSError, ValueError):
            status, answer = 400, {"error": "read"}
        rx._end_upload(ip, ok=(status == 200), answer=answer)
        self._send_json(status, answer)

    def _receive_photo(self, rx, pid=""):
        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            return 411, {"error": "length"}
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return 411, {"error": "length"}
        if length <= 0:
            return 411, {"error": "length"}
        if length > MAX_BYTES:
            return 413, {"error": "size"}   # the body is not read: the connection is closed after the answer
        ctype = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if ctype in ("image/heic", "image/heif"):
            return 415, {"error": "heic"}
        if ctype not in IMAGE_MAGIC:
            return 415, {"error": "type"}
        deadline = time.monotonic() + UPLOAD_DEADLINE
        chunks, got = [], 0
        rx._emit("receiving", {"total": length})
        last_pct, last_t = -1, 0.0
        while got < length:
            if time.monotonic() > deadline:
                return 408, {"error": "slow"}
            chunk = self.rfile.read(min(65536, length - got))
            if not chunk:
                return 400, {"error": "read"}
            chunks.append(chunk)
            got += len(chunk)
            pct, now = got * 100 // length, time.monotonic()
            if pct != last_pct and (now - last_t >= PROGRESS_EVERY or got == length):
                last_pct, last_t = pct, now
                rx._emit("progress", {"got": got, "total": length, "percent": pct})
        data = b"".join(chunks)
        error = quick_check(data)           # type by the first bytes, size from the header: no decoding yet
        if error:
            return 415, {"error": error}
        mode = "orig" if rx.full_size else "fit"   # the computer decides (the check box in the window); a phone header is ignored
        count = rx._accept(pid)             # the photo is ours from now on: counted, remembered by its id
        rx._process_async(data, ctype, mode, pid, count)   # decode, turn, shrink, open: after the answer, in a worker thread
        return 200, {}


class Receiver:
    """One opening of the window "Photo from phone": one code, one bound phone, a socket while it is open.

    on_event(kind, data) is called from the threads of the server (the window passes it on to the GUI thread):
    "connected" {"ip"}, "receiving" {"total"}, "progress" {"got", "total", "percent"}, "photo" {"image", "type",
    "count"}, "failed" {"error"} (an upload that did not arrive: aborted, too slow, not a picture), "bad" {"count"},
    "closed" {"reason"}.
    Reasons of "closed": "expired" (no phone within CLAIM_TTL), "idle", "locked" (MAX_BAD), "limit", "phone" (the
    phone pressed "Close"), "stopped".
    """

    def __init__(self, host: str, network=None, on_event=None, texts=None, lang: str = "ru",
                 clock=time.monotonic, decode=decode_image, ports=None, screen=None):
        self.host = host
        self.network = ipaddress.ip_network(network, strict=False) if network else None
        self.on_event = on_event or (lambda kind, data: None)
        self.texts = dict(texts or {})
        self.lang = lang
        self.clock = clock
        self.decode = decode
        self.ports = tuple(ports if ports is not None else (PREFERRED_PORTS if LISTEN_PORTS is None else LISTEN_PORTS))
        self.full_size = False  # the check box "Save photos in full size" (off: fit to the screen of this computer)
        self.screen = screen    # (w, h) of the computer's screen in physical pixels: "Fit to the computer screen"
        self.port = None
        self.token = ""
        self.state = CLOSED
        self.reason = ""
        self.phone_ip = None
        self.photos = 0
        self.bad = 0
        self._key = None
        self._in_flight = None
        self._seen = []
        self._hdr = {}          # socket -> time of accepting, until its request line and headers have been read
        self._done = []         # ids of photos the computer opened (told to the phone once: it drops its copy)
        self._lost = []         # ids of photos the computer could not open
        self._failed = []       # numbers of photos the computer could not open (reported to the phone once)
        self._busy = 0
        self._closed_pending = ""
        self._proc_lock = threading.Lock()
        self._created = self._last = 0.0
        self._lock = threading.RLock()
        self._conns = {}   # socket -> client address
        self._server = None
        self._thread = None

    # --- life ------------------------------------------------------------------

    @property
    def authority(self) -> str:
        return f"{self.host}:{self.port}"

    @property
    def url(self) -> str:
        return f"http://{self.authority}/{self.token}"

    def start(self) -> str:
        """Open the socket on host (a preferred port, else any free one) and a new code. Returns the url.
        OSError when nothing can be bound (the address is gone, the system refuses)."""
        last_error = None
        for port in self.ports + (0,):
            try:
                server = _Server((self.host, port), _Handler, bind_and_activate=False)
                server.receiver = self
                server.server_bind()
                server.server_activate()
            except OSError as exc:
                last_error = exc
                try:
                    server.server_close()
                except Exception:   # noqa: BLE001
                    pass
                continue
            self._server = server
            self.port = server.server_address[1]
            break
        else:
            raise last_error or OSError("no port")
        self.renew()
        self._thread = threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.2},
                                        name="clipsd-phone", daemon=True)
        self._thread.start()
        return self.url

    def renew(self) -> str:
        """A new code (the old one dies): "Show a new code" after expiry, a lock or the limit."""
        with self._lock:
            self.token = new_token()
            self.state = WAITING
            self.reason = ""
            self.phone_ip = None
            self._key = None
            self._in_flight = None
            self._seen = []
            self._done = []
            self._lost = []
            self.photos = 0
            self.bad = 0
            self._created = self._last = self.clock()
        return self.url

    def stop(self):
        """Close the socket and every open connection. The code dies with it."""
        self._close("stopped")
        server, self._server = self._server, None
        if server is not None:
            server.shutdown()
            server.server_close()
        with self._lock:
            conns, self._conns = list(self._conns), {}
        for c in conns:
            try:
                c.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                c.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    @property
    def running(self) -> bool:
        return self._server is not None

    def tick(self) -> str:
        """Called by the window every second: closes the session on expiry. Returns the state. The close itself is
        done outside the lock: whoever listens to the events never runs inside it."""
        reason = ""
        with self._lock:
            now = self.clock()
            if self.state == WAITING and now - self._created > CLAIM_TTL:
                reason = "expired"
            elif self.state == PAIRED and now - self._last > self.idle_ttl() and self._in_flight is None:
                reason = "idle"
        if reason:
            self._close(reason)
        return self.state

    def idle_ttl(self) -> int:
        """Seconds of silence after which a paired receiver closes: long before the first photo (the person is
        finding the camera), short after one (the window hid itself; \"Take another\" is for a moment)."""
        return AFTER_PHOTO_TTL if self.photos > 0 else IDLE_TTL

    def remaining(self) -> int:
        """Seconds left for the code while no phone has come (0 when it is gone)."""
        with self._lock:
            if self.state != WAITING:
                return 0
            return max(0, int(CLAIM_TTL - (self.clock() - self._created) + 0.999))

    # --- inside (called from the handler threads) ----------------------------------

    def client_allowed(self, ip: str) -> bool:
        try:
            addr = ipaddress.ip_address(ip.split("%")[0])
        except ValueError:
            return False
        if getattr(addr, "ipv4_mapped", None):
            addr = addr.ipv4_mapped
        if self.network is not None:
            return addr in self.network
        return addr.is_loopback or is_home_address(addr)

    def _emit(self, kind, data):
        try:
            self.on_event(kind, data)
        except Exception:   # noqa: BLE001: the window may be gone; the server must not die of it
            pass

    def _close(self, reason: str):
        with self._lock:
            if self.state == CLOSED:
                return
            self.state, self.reason = CLOSED, reason
            self._key = None
            if self._busy > 0 and reason != "stopped":
                self._closed_pending = reason   # a photo is still being opened: the window learns of it after the photo
                return
        self._emit("closed", {"reason": reason})

    def _bad_attempt(self):
        with self._lock:
            if self.state == CLOSED:
                return
            self.bad += 1
            count = self.bad
        self._emit("bad", {"count": count})
        if count >= MAX_BAD:
            self._close("locked")

    def _alive(self) -> bool:
        self.tick()
        return self.state != CLOSED

    def _claim(self, ip: str):
        """GET /<code>: ("ok", key) for the first phone or a reload by the same phone; ("taken", None) for
        another address; ("closed", None) when the code is gone."""
        with self._lock:
            if not self._alive():
                return "closed", None
            if self.state == PAIRED and ip != self.phone_ip:
                taken = True
            else:
                taken = False
                first = self.state == WAITING
                self.state, self.phone_ip = PAIRED, ip
                self._key = secrets.token_urlsafe(KEY_BYTES)
                self._in_flight = None
                self._last = self.clock()
                key = self._key
        if taken:
            self._bad_attempt()
            return "taken", None
        if first:
            self._emit("connected", {"ip": ip})
        return "ok", key

    def _refresh_key(self, ip: str):
        """GET /<code>/key: ("ok", new key) for the bound phone; ("busy", None) while a photo is arriving;
        ("taken", None) another address (counted as a guess); ("closed", None)."""
        with self._lock:
            if not self._alive():
                return "closed", None
            if self.state != PAIRED or ip != self.phone_ip:
                taken = True
            elif self._in_flight is not None:
                return "busy", None
            else:
                taken = False
                self._key = secrets.token_urlsafe(KEY_BYTES)
                key = self._key
        if taken:
            self._bad_attempt()
            return "taken", None
        return "ok", key

    def _key_ok(self, ip: str, key: str, count: bool = True) -> bool:
        with self._lock:
            if not self._alive() or self.state != PAIRED:
                return False
            ok = ip == self.phone_ip and self._key is not None and hmac.compare_digest(key.encode(), self._key.encode())
        if not ok and count and key:
            self._bad_attempt()
        return ok

    def _begin_upload(self, ip: str, key: str) -> str:
        with self._lock:
            if not self._alive():
                return "closed"
            if self.state != PAIRED or ip != self.phone_ip or self._key is None \
                    or not hmac.compare_digest(key.encode(), self._key.encode()):
                wrong = True
            elif self._in_flight is not None:
                return "busy"   # the same key twice at once: only one of them may pass
            elif self.photos >= MAX_PHOTOS:
                return "limit"
            else:
                wrong = False
                self._in_flight = key
        if wrong:
            self._bad_attempt()
            return "key"
        return "ok"

    def _accept(self, pid: str = "") -> int:
        """The bytes of a photo came and passed the quick check: count it, extend the reception, remember its id."""
        with self._lock:
            self.photos += 1
            self._last = self.clock()   # every received photo extends the reception (AFTER_PHOTO_TTL from the last)
            if pid:
                self._seen = (self._seen + [pid])[-SEEN_MAX:]
            return self.photos

    def _process_async(self, data, ctype, mode, pid, count):
        with self._lock:
            self._busy += 1
        threading.Thread(target=self._process, args=(data, ctype, mode, pid, count), name="clipsd-phone-photo",
                         daemon=True).start()

    def _process(self, data, ctype, mode, pid, count):
        try:
            with self._proc_lock:           # photos open in the order they came
                try:
                    image = self.decode(data)   # EXIF orientation applied; metadata is not kept
                    src_size = (image.width(), image.height()) if image is not None else None
                    image = prepare_image(image, mode, self.screen)
                except Exception:   # noqa: BLE001
                    image, src_size = None, None
                del data
                if image is None:
                    self.reject(pid, count)
                    self._emit("failed", {"error": "decode", "count": count, "pid": pid})
                else:
                    self._emit("photo", {"image": image, "type": ctype, "count": count, "pid": pid,
                                         "info": {"mode": mode, "src": src_size, "screen": self.screen}})
        finally:
            pending = ""
            with self._lock:
                self._busy -= 1
                if self._busy == 0 and self._closed_pending:
                    pending, self._closed_pending = self._closed_pending, ""
            if pending:
                self._emit("closed", {"reason": pending})

    def wait_idle(self, timeout: float = 10.0) -> bool:
        """For tests and shutdown: no photo is being opened any more."""
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            with self._lock:
                if self._busy == 0:
                    return True
            time.sleep(0.01)
        return False

    def _oldest_header(self, ip, skip=()):
        """The connection in the header phase that came first (of this device when ip is given). Under _lock."""
        best = None
        for sock, t0 in self._hdr.items():
            if sock in skip or (ip is not None and self._conns.get(sock) != ip):
                continue
            if best is None or t0 < self._hdr[best]:
                best = sock
        return best

    def confirm(self, pid: str):
        """The computer opened (saved) the photo: the phone may drop its own copy."""
        if pid:
            with self._lock:
                self._done.append(pid)

    def reject(self, pid: str, count: int = 0):
        """The computer could not open the photo."""
        with self._lock:
            if pid:
                self._lost.append(pid)
            if count and count not in self._failed:
                self._failed.append(count)

    def confirmations(self) -> dict:
        with self._lock:
            done, self._done = self._done, []
            lost, self._lost = self._lost, []
        return {"done": done, "lost": lost}

    def failed_to_report(self) -> list:
        with self._lock:
            out, self._failed = self._failed, []
            return out

    def _deliver(self, image, ctype: str, pid: str = "", info=None):
        """Accept and open at once (the whole path in one call: tests and simple callers)."""
        count = self._accept(pid)
        self._emit("photo", {"image": image, "type": ctype, "count": count, "info": info or {}})

    def _dup_key(self, ip: str, pid: str):
        """The current key for the bound phone when this photo id was already received, else None."""
        with self._lock:
            if self.state != PAIRED or ip != self.phone_ip or pid not in self._seen or self._key is None:
                return None
            return self._key

    def time_left(self) -> int:
        """Seconds the reception stays open if nothing comes (shown on the phone): the code before a phone came,
        then AFTER_PHOTO_TTL from the last photo (IDLE_TTL before the first)."""
        with self._lock:
            now = self.clock()
            if self.state == WAITING:
                return max(0, int(CLAIM_TTL - (now - self._created)))
            if self.state == PAIRED:
                return max(0, int(self.idle_ttl() - (now - self._last)))
            return 0

    def _end_upload(self, ip: str, ok: bool, answer: dict):
        """Accepted: the used key dies, the answer carries the next one. Refused: the same key may try again."""
        limit = False
        if not ok:
            self._emit("failed", {"error": answer.get("error", "")})
        with self._lock:
            self._in_flight = None
            if ok and self.state == PAIRED:
                self._key = secrets.token_urlsafe(KEY_BYTES)
                self._last = self.clock()
                answer["key"] = self._key
                answer["count"] = self.photos
                limit = self.photos >= MAX_PHOTOS
        if limit:
            answer["limit"] = True
            self._close("limit")


# --- the network of this computer ----------------------------------------------------------------------------

VIRTUAL_PREFIXES = ("docker", "br-", "veth", "virbr", "vmnet", "vboxnet", "tun", "tap", "wg", "tailscale", "zt",
                    "utun", "ppp", "lxc", "lxd", "cni", "flannel", "podman", "ham", "nordlynx", "proton", "outline")
CGNAT = ipaddress.ip_network("100.64.0.0/10")   # Tailscale and carrier NAT, never the home network
# Home networks are the RFC 1918 ranges. ipaddress' is_private is wider (documentation ranges such as 203.0.113.0/24
# count as "private" there), so the ranges are named here.
HOME_RANGES = tuple(ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def is_home_address(addr) -> bool:
    return addr.version == 4 and any(addr in net for net in HOME_RANGES)


def rank_candidate(c: dict):
    """Order of interfaces: Wi-Fi, then cable, then the rest; 192.168 before 10 before 172.16."""
    kind = {"wifi": 0, "ethernet": 1}.get(c.get("kind"), 2)
    ip = ipaddress.ip_address(c["ip"])
    net = 0 if ip in ipaddress.ip_network("192.168.0.0/16") else 1 if ip in ipaddress.ip_network("10.0.0.0/8") else 2
    return (kind, net, c.get("name", ""))


def usable_candidate(c: dict) -> bool:
    try:
        ip = ipaddress.ip_address(c["ip"])
    except (KeyError, ValueError):
        return False
    name = (c.get("name") or "").lower()
    if not is_home_address(ip):
        return False
    if c.get("point_to_point") or c.get("kind") == "virtual":
        return False
    if any(name.startswith(p) for p in VIRTUAL_PREFIXES):
        return False
    human = (c.get("human") or "").lower()
    if any(w in human for w in ("vpn", "virtual", "hyper-v", "vethernet", "tap-", "wireguard", "tailscale", "vmware",
                                "virtualbox", "loopback")):
        return False
    prefix = c.get("prefix", 24)
    return 8 <= prefix <= 30


EDITOR_MARGIN = (80, 290)   # px around the picture in the editor window: side rims, tool panels and title bar


def editor_scale(width: int, height: int, avail_width: int, avail_height: int) -> float:
    """devicePixelRatio for a picture from the phone: the editor sizes its window by the picture in points, and
    draws arrows and text in points, so a 4000 x 3000 photo would fill the screen (zoomed out, arrows tiny).
    With this ratio the picture in points fits the screen together with the panels, as a screenshot does.
    1.0 for a picture that fits already (never enlarges)."""
    target_w = max(200, avail_width - EDITOR_MARGIN[0])
    target_h = max(200, avail_height - EDITOR_MARGIN[1])
    return max(1.0, width / target_w, height / target_h)


def lan_candidates() -> list:
    """Interfaces of this computer that can be the home network, best first (Qt's list of interfaces)."""
    from PyQt6.QtNetwork import QAbstractSocket, QNetworkInterface
    flags = QNetworkInterface.InterfaceFlag
    types = QNetworkInterface.InterfaceType
    found = []
    for iface in QNetworkInterface.allInterfaces():
        f = iface.flags()
        if not (f & flags.IsUp and f & flags.IsRunning) or f & flags.IsLoopBack:
            continue
        t = iface.type()
        kind = "wifi" if t in (types.Wifi, types.Ieee80211) else "ethernet" if t == types.Ethernet \
            else "virtual" if t in (types.Virtual, types.Ppp) else "other"
        for entry in iface.addressEntries():
            ip = entry.ip()
            if ip.protocol() != QAbstractSocket.NetworkLayerProtocol.IPv4Protocol:
                continue
            c = {"ip": ip.toString(), "prefix": entry.prefixLength(), "name": iface.name(),
                 "human": iface.humanReadableName(), "kind": kind,
                 "point_to_point": bool(f & flags.IsPointToPoint)}
            if usable_candidate(c):
                found.append(c)
    return sorted(found, key=rank_candidate)


def network_of(c: dict) -> str:
    return str(ipaddress.ip_network(f"{c['ip']}/{c.get('prefix', 24)}", strict=False))


# --- what may block the phone on this computer ----------------------------------------------------------------

def linux_firewall() -> str:
    """"ufw" or "firewalld" when one of them is on (read from their files, no root and no child process), else ""."""
    try:
        with open("/etc/ufw/ufw.conf", encoding="utf-8") as f:
            if any(line.strip().replace(" ", "").lower() == "enabled=yes" for line in f):
                return "ufw"
    except OSError:
        pass
    for pid in ("/run/firewalld/firewalld.pid", "/var/run/firewalld/firewalld.pid"):
        if os.path.exists(pid):
            return "firewalld"
    return ""


def linux_firewall_command(kind: str, network: str, ports=PREFERRED_PORTS) -> str:
    """One command for the terminal that lets the phone in: only the home subnet, only our ports."""
    span = f"{ports[0]}:{ports[-1]}" if kind == "ufw" else f"{ports[0]}-{ports[-1]}"
    if kind == "ufw":
        return f"sudo ufw allow proto tcp from {network} to any port {span} comment 'ClipSD photo from phone'"
    if kind == "firewalld":
        return (f"sudo firewall-cmd --add-rich-rule='rule family=\"ipv4\" source address=\"{network}\" "
                f"port port=\"{span}\" protocol=\"tcp\" accept'")
    return ""


FIREWALL_COMMENT = "ClipSD photo from phone"
SYSTEM_PATH = "/usr/sbin:/usr/bin:/sbin:/bin"   # ufw lives in /usr/sbin, which a user's PATH may lack
FIREWALL_TOOLS = {"ufw": "ufw", "firewalld": "firewall-cmd"}
PKEXEC_DECLINED = (126, 127)   # pkexec: the password window was dismissed / not authorized


def firewall_network(network):
    """The subnet for a firewall rule as text, or None. Only a real home subnet (RFC 1918, /8 to /30) is accepted:
    never 0.0.0.0/0, never a public range, never a single address or a host network of a VPN."""
    try:
        net = ipaddress.ip_network(str(network), strict=False)
    except ValueError:
        return None
    if net.version != 4 or not 8 <= net.prefixlen <= 30:
        return None
    if not any(net.subnet_of(home) for home in HOME_RANGES):
        return None
    return str(net)


def firewall_allow_argv(kind: str, network, which=shutil.which):
    """argv for pkexec that lets the phone in, or None (no such firewall, no pkexec, no tool, a network that is not
    a home subnet). Absolute paths, no shell, no script: the only variable parts are the subnet checked by
    firewall_network and the port constants. ufw: a permanent rule. firewalld: a runtime rule (until reload)."""
    net = firewall_network(network)
    tool_name = FIREWALL_TOOLS.get(kind)
    if net is None or tool_name is None:
        return None
    pkexec = which("pkexec", path=SYSTEM_PATH)
    tool = which(tool_name, path=SYSTEM_PATH)
    if not pkexec or not tool or not os.path.isabs(pkexec) or not os.path.isabs(tool):
        return None
    if kind == "ufw":
        return [pkexec, tool, "allow", "proto", "tcp", "from", net, "to", "any", "port",
                f"{PREFERRED_PORTS[0]}:{PREFERRED_PORTS[-1]}", "comment", FIREWALL_COMMENT]
    return [pkexec, tool, f'--add-rich-rule=rule family="ipv4" source address="{net}" '
            f'port port="{PREFERRED_PORTS[0]}-{PREFERRED_PORTS[-1]}" protocol="tcp" accept']


def allow_outcome(code: int) -> str:
    """Exit code of pkexec: "ok", "declined" (the person closed the password window) or "failed"."""
    if code == 0:
        return "ok"
    return "declined" if code in PKEXEC_DECLINED else "failed"


def windows_firewall_commands(program: str, ports=PREFERRED_PORTS, netsh: str = None) -> list:
    """netsh commands for "Allow again": remove the inbound rules Windows made for this program (a block rule wins over
    any allow rule, and Windows does not ask again while it exists), then allow it on private networks only, from the
    local subnet only, on our ports only. netsh by full path from the system folder, never by name (Б4 of the 1.34.1
    review: a bare name is looked up first in the folder of ClipSD, writable for the user)."""
    if netsh is None:
        if sys.platform == "win32":
            from .sysenv import system_program
            netsh = system_program("netsh.exe")
        else:
            netsh = "netsh"
    return [
        [netsh, "advfirewall", "firewall", "delete", "rule", "name=all", "dir=in", f"program={program}"],
        [netsh, "advfirewall", "firewall", "add", "rule", "name=ClipSD photo from phone", "dir=in", "action=allow",
         f"program={program}", "enable=yes", "profile=private", "protocol=TCP",
         f"localport={ports[0]}-{ports[-1]}", "remoteip=localsubnet"],
    ]


def firewall_program(program: str = None, executable: str = None) -> str:
    """The program of the firewall rule: this very ClipSD (sys.executable), an absolute path to an existing file.
    ValueError otherwise: the path goes into a command that runs as administrator."""
    executable = executable or sys.executable
    program = program or executable
    if not os.path.isabs(program) or not os.path.isfile(program):
        raise ValueError(f"not an existing absolute path: {program!r}")
    if os.path.normcase(os.path.abspath(program)) != os.path.normcase(os.path.abspath(executable)):
        raise ValueError(f"not this program: {program!r}")
    return program


def windows_firewall_script(program: str, netsh: str = None) -> str:
    """PowerShell script of "Allow again": the two netsh commands, every argument a single-quoted literal
    (sysenv.ps_quote), so nothing in the path is expanded. Only the language and netsh.exe by full path: no cmdlet,
    so no module is needed (the elevated prologue switches module loading off, Б5 of the 1.34.1 review). PowerShell
    and not two netsh starts: one UAC prompt instead of two. Exit code: that of the add command."""
    from .sysenv import ps_quote
    delete, add = windows_firewall_commands(program, netsh=netsh)
    line = lambda argv: "$null = & " + " ".join(ps_quote(a) for a in argv)   # noqa: E731
    return "\n".join([line(delete), line(add), "exit $LASTEXITCODE"]) + "\n"


def firewall_parameters(program: str = None, executable: str = None, netsh: str = None) -> str:
    """Command line for the elevated PowerShell of "Allow again" (sysenv.run_elevated_wait); built in the normal
    process, the elevated one reads nothing from the user's folders. ValueError for a wrong program path."""
    from .sysenv import elevated_powershell_parameters
    return elevated_powershell_parameters(windows_firewall_script(firewall_program(program, executable), netsh))
