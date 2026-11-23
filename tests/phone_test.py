# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Фото с телефона (после 1.32): свой QR-код, приёмник в домашней сети, окно с кодом, страница для телефона.

Приёмник проверяется настоящими запросами на 127.0.0.1 (второй «телефон» с адреса 127.0.0.2): одноразовый код,
привязка к первому телефону, один ключ на одну загрузку, размер, тип по заголовку и по первым байтам, Host и Origin,
время жизни кода, закрытие после подбора кода, предел фото, предел соединений, медленный клиент, закрытие сокета.
Окно: напоминание про Wi-Fi с галочкой, код и адрес, фото открывается в редакторе или ложится поверх снимка,
устаревший код, нет сети, окно причин (VPN, Wi-Fi, сетевой экран), пункты меню значка и «Вставить» редактора.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/phone_test.py
"""
import http.client
import json
import os
import re
import socket
import threading
import sys
import time

here = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(here)
sys.path.insert(0, ROOT)
os.environ.pop("CLIPSD_LANG", None)
sys.path.insert(0, here)
import tmpclean  # noqa: E402,F401  (временные папки этого теста убираются при его выходе)
import tempfile  # noqa: E402
_cfg = os.path.join(tempfile.mkdtemp(prefix="clipsd-phone-"), "screen.json")
with open(_cfg, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1280, "height": 720,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _cfg

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QPoint, QProcess, Qt, pyqtSignal  # noqa: E402
from PyQt6.QtGui import QColor, QGuiApplication, QImage  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
from clipshot import app as appmod, i18n, phone, phone_page, phone_ui, qr  # noqa: E402

phone.LISTEN_PORTS = ()   # every receiver of this test takes a free port of the system: other runs do not fight for 8765-8767
from clipshot.i18n import tr  # noqa: E402

failures = []
checks = [0]


def check(cond, msg):
    checks[0] += 1
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def settle(ms=50):
    QTest.qWait(ms)


def jpeg(w=640, h=480, fmt="JPEG") -> bytes:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor("#336699"))
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, fmt)
    return bytes(ba)


def fitted(w, h, screen=None):
    """Размер после «Под экран компьютера» (делает компьютер): вписать в экран, не увеличивать."""
    sc = QGuiApplication.primaryScreen()
    sw, sh = screen or (round(sc.geometry().width() * sc.devicePixelRatio()), round(sc.geometry().height() * sc.devicePixelRatio()))
    k = min(1.0, sw / w, sh / h)
    return (round(w * k), round(h * k))


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Client:
    """A phone: plain HTTP from a given source address (127.0.0.2 = another device)."""

    def __init__(self, rx, source="127.0.0.1"):
        self.rx, self.source = rx, source

    def request(self, method, path, body=None, headers=None, host=None):
        c = http.client.HTTPConnection("127.0.0.1", self.rx.port, timeout=5, source_address=(self.source, 0))
        c.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        c.putheader("Host", host or self.rx.authority)
        for k, v in (headers or {}).items():
            c.putheader(k, v)
        if body is not None:
            c.putheader("Content-Length", str(len(body)))
        c.endheaders(body)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r, data

    def open_page(self):
        r, data = self.request("GET", f"/{self.rx.token}")
        key = None
        m = re.search(rb'id="cfg">(.*?)</script>', data)
        if m:
            key = json.loads(m.group(1).decode())["key"]
        return r, data.decode("utf-8", "replace"), key

    def post(self, key, body, ctype="image/jpeg", origin=True, extra=None):
        h = {"Content-Type": ctype, "X-ClipSD-Key": key}
        if origin:
            h["Origin"] = f"http://{self.rx.authority}"
        h.update(extra or {})
        r, data = self.request("POST", f"/{self.rx.token}/photo", body=body, headers=h)
        self.rx.wait_idle()   # the computer answers at once and opens the photo afterwards: tests wait for it
        try:
            return r.status, json.loads(data or b"{}")
        except ValueError:
            return r.status, {}


def receiver(**kw):
    events = []
    kw.setdefault("texts", phone_ui.page_texts())
    rx = phone.Receiver("127.0.0.1", on_event=lambda k, d: events.append((k, d)), **kw)
    rx.start()
    return rx, events


def kinds(events):
    return [k for k, _ in events]


# --- QR code -----------------------------------------------------------------------------------------------------

def test_qr():
    check(qr.format_bits("M", 0) == 0b101010000010010, "QR: биты формата M/0 по таблице стандарта")
    check(qr.format_bits("L", 0) == 0b111011111000100, "QR: биты формата L/0")
    check(qr.format_bits("L", 4) == 0b110011000101111, "QR: биты формата L/4")
    # «HELLO WORLD» 1-M: известный пример кодов Рида-Соломона
    data = [32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17]
    check(qr.rs_remainder(data, qr.rs_divisor(10)) == [196, 35, 39, 119, 235, 215, 231, 226, 93, 23],
          "QR: коды Рида-Соломона совпадают с примером стандарта")
    url = "http://192.168.100.200:8765/abcd2345"
    m = qr.encode(url)
    n = len(m)
    check(n == 29, f"QR: адрес приёма помещается в версию 3, 29 × 29 ({n})")

    def finder(x0, y0):
        return all(m[y0 + dy][x0 + dx] == (max(abs(dx - 3), abs(dy - 3)) != 2)
                   for dy in range(7) for dx in range(7))
    check(finder(0, 0) and finder(n - 7, 0) and finder(0, n - 7), "QR: три угловых квадрата на месте")
    check(m[n - 8][8], "QR: тёмный модуль у левого нижнего квадрата")
    check(all(m[6][i] == (i % 2 == 0) for i in range(8, n - 8)), "QR: линия синхронизации")
    try:
        qr.encode("x" * 400)
        check(False, "QR: слишком длинный текст даёт ошибку")
    except qr.DataTooLong:
        check(True, "QR: слишком длинный текст даёт ошибку")
    try:
        import numpy
        import zxingcpp
    except ImportError:
        print("     (чтение QR независимой библиотекой пропущено: нет zxing-cpp; это проверка разработчика)")
        return
    for text in (url, "http://10.0.0.5:8770/" + "k" * 8, "Фото с телефона"):
        mm = qr.encode(text)
        size = (len(mm) + 8) * 4
        a = numpy.full((size, size), 255, numpy.uint8)
        for y, row in enumerate(mm):
            for x, d in enumerate(row):
                if d:
                    a[(y + 4) * 4:(y + 5) * 4, (x + 4) * 4:(x + 5) * 4] = 0
        got = zxingcpp.read_barcodes(a)
        check(bool(got) and got[0].text == text, f"QR читается zxing-cpp: {text}")


# --- the receiver ------------------------------------------------------------------------------------------------

def test_token_and_page():
    rx, ev = receiver()
    try:
        check(re.fullmatch(r"http://127\.0\.0\.1:\d+/[%s]{8}" % phone.TOKEN_ALPHABET, rx.url) is not None,
              f"адрес приёма: http://адрес:порт/код из 8 знаков без похожих букв ({rx.url})")
        check(rx.port in phone.PREFERRED_PORTS or rx.port > 1024, "порт из своего ряда или свободный")
        phone_a = Client(rx)
        r, _ = phone_a.request("GET", f"/{rx.token}", host="evil.example:80")
        check(r.status == 400 and rx.state == phone.WAITING, "чужое имя в Host: 400, код не занят (DNS rebinding)")
        r, _ = phone_a.request("GET", "/favicon.ico")
        check(r.status == 404 and rx.bad == 0, "значок сайта: 404 и не считается подбором")
        r, _ = phone_a.request("GET", "/abcdefgh")
        check(r.status == 404 and rx.bad == 1, "неверный код: 404 и счёт подбора")
        r, page, key = phone_a.open_page()
        check(r.status == 200 and key and len(key) >= 30, "верный код: страница и ключ на одну загрузку")
        csp = r.getheader("Content-Security-Policy") or ""
        check("default-src 'none'" in csp and "connect-src 'self'" in csp and "frame-ancestors 'none'" in csp,
              "страница с запретом чужих источников (Content-Security-Policy)")
        check(r.getheader("Cache-Control") == "no-store" and r.getheader("Referrer-Policy") == "no-referrer",
              "страница не кэшируется и не отдаёт адрес")
        check('capture="environment"' in page and 'accept="image/*"' in page,
              "кнопка съёмки открывает камеру телефона (input capture, без getUserMedia)")
        check('id="shoot"' in page and 'id="gal"' in page and "http" not in page.split("<script")[0].replace(
            'http-equiv', ''), "две большие кнопки первого экрана, ни одной внешней ссылки")
        check(kinds(ev) == ["bad", "connected"], f"события: подбор, телефон подключился ({kinds(ev)})")
        other = Client(rx, "127.0.0.2")
        r, page2, key2 = other.open_page()
        check(r.status == 409 and key2 is None and rx.bad == 2, "второй телефон с тем же кодом: 409, код занят")
        st, _ = other.post(key, jpeg())
        check(st == 403, "ключ первого телефона с другого адреса не работает")
        r, _, key_reload = phone_a.open_page()
        check(r.status == 200 and key_reload and key_reload != key, "тот же телефон обновил страницу: новый ключ")
        st, _ = phone_a.post(key, jpeg())
        check(st == 403, "старый ключ после обновления страницы не работает")
        st, ans = phone_a.post(key_reload, jpeg(800, 600))
        photos = [d for k, d in ev if k == "photo"]
        check(st == 200 and ans.get("key") and ans["key"] != key_reload and ans.get("count") == 1,
              "фото принято, в ответе следующий ключ")
        check(len(photos) == 1 and photos[0]["image"].width() == 800 and photos[0]["type"] == "image/jpeg",
              "событие «фото» с картинкой 800 × 600")
        st, _ = phone_a.post(key_reload, jpeg())
        check(st == 403 and len([1 for k, _ in ev if k == "photo"]) == 1, "использованный ключ второй раз: 403")
        key = ans["key"]
        r, _ = phone_a.request("GET", f"/{rx.token}/alive", headers={"X-ClipSD-Key": key})
        check(r.status == 200, "проверка связи с действующим ключом: 200 и оставшееся время")
        r, _ = phone_a.request("GET", f"/{rx.token}/alive", headers={"X-ClipSD-Key": "x" * 32})
        check(r.status == 410, "проверка связи с чужим ключом: 410")
        st, ans = phone_a.post(key, jpeg(320, 240, "PNG"), ctype="image/png")
        check(st == 200, "PNG принимается")
        key = ans["key"]
    finally:
        rx.stop()


def test_size_type_origin():
    rx, ev = receiver()
    try:
        ph = Client(rx)
        _, _, key = ph.open_page()
        st, _ = ph.post(key, b"hello world", ctype="text/plain")
        check(st == 415, "тип text/plain: 415")
        st, _ = ph.post(key, b"hello world, not a picture", ctype="image/jpeg")
        check(st == 415, "заголовок image/jpeg, внутри не картинка: 415")
        st, ans0 = ph.post(key, jpeg(), ctype="image/png")
        check(st == 200, "метка PNG, внутри настоящий JPEG: принято (решают байты, не метка галереи)")
        key = ans0["key"]
        broken = jpeg()[:200]
        st, _ = ph.post(key, broken, ctype="image/jpeg")
        check(st == 415, "обрезанный JPEG не открывается как картинка: 415")
        st, _ = ph.post(key, jpeg(), origin=False, extra={"Origin": "http://evil.example"})
        check(st == 403, "запрос с чужой страницы (Origin): 403")
        # больше предела: ответ сразу, тело не читается
        s = socket.create_connection(("127.0.0.1", rx.port), timeout=5)
        s.sendall((f"POST /{rx.token}/photo HTTP/1.1\r\nHost: {rx.authority}\r\nContent-Type: image/jpeg\r\n"
                   f"X-ClipSD-Key: {key}\r\nContent-Length: {phone.MAX_BYTES + 1}\r\n\r\n").encode())
        t0 = time.monotonic()
        head = s.recv(200)
        s.close()
        check(head.startswith(b"HTTP/1.0 413") and time.monotonic() - t0 < 2, "больше 25 МБ: 413 сразу, без чтения")
        s = socket.create_connection(("127.0.0.1", rx.port), timeout=5)
        s.sendall((f"POST /{rx.token}/photo HTTP/1.1\r\nHost: {rx.authority}\r\nContent-Type: image/jpeg\r\n"
                   f"X-ClipSD-Key: {key}\r\nTransfer-Encoding: chunked\r\n\r\n").encode())
        head = s.recv(200)
        s.close()
        check(head.startswith(b"HTTP/1.0 411"), "без длины (chunked): 411")
        st, _ = ph.post(key, jpeg())
        check(st == 200, "после отказов тот же ключ годен для настоящего фото")
        check(rx.bad == 0, "отказы по типу и размеру не считаются подбором")
    finally:
        rx.stop()


def test_expiry_idle_lock_limit():
    clock = Clock()
    rx, ev = receiver(clock=clock)
    try:
        check(rx.remaining() == phone.CLAIM_TTL, "код действует 3 минуты")
        clock.t += phone.CLAIM_TTL + 1
        rx.tick()
        check(rx.state == phone.CLOSED and ("closed", {"reason": "expired"}) in ev, "через 3 минуты код устарел")
        r, page, key = Client(rx).open_page()
        check(r.status == 410 and key is None and tr("phone.page_closed") in page,
              "устаревший код: 410 и понятная страница")
        url = rx.renew()
        check(rx.state == phone.WAITING and url.endswith(rx.token), "новый код")
        r, _, key = Client(rx).open_page()
        clock.t += phone.IDLE_TTL + 1
        rx.tick()
        check(rx.reason == "idle", "10 минут без фото: приём закрыт")
        rx.renew()
        for i in range(phone.MAX_BAD):
            Client(rx).request("GET", f"/zz{i:06d}")
        check(rx.state == phone.CLOSED and rx.reason == "locked", f"{phone.MAX_BAD} неверных кодов: приём закрыт")
        r, _, key = Client(rx).open_page()
        check(r.status == 410, "после подбора и верный код не работает")
        rx.renew()
        saved = phone.MAX_PHOTOS
        phone.MAX_PHOTOS = 2
        try:
            ph = Client(rx)
            _, _, key = ph.open_page()
            st, a1 = ph.post(key, jpeg())
            st2, a2 = ph.post(a1["key"], jpeg())
            check(st == 200 and st2 == 200 and a2.get("limit") and rx.reason == "limit",
                  "предел фото за одно открытие: второе принято, приём закрыт")
            st3, _ = ph.post(a2.get("key", ""), jpeg())
            check(st3 == 410, "после предела: 410")
        finally:
            phone.MAX_PHOTOS = saved
    finally:
        rx.stop()


def test_connections_and_stop():
    saved = phone._Handler.timeout
    phone._Handler.timeout = 1
    rx, ev = receiver()
    try:
        def conn(src):
            c = socket.socket()
            c.settimeout(3)
            c.bind((src, 0))
            c.connect(("127.0.0.1", rx.port))
            return c

        def closed_by_server(c):
            try:
                return c.recv(10) == b""
            except OSError:
                return True

        idle = [conn("127.0.0.1") for _ in range(phone.MAX_PER_IP)]
        wait_for(lambda: len(rx._conns) >= phone.MAX_PER_IP)
        extra = conn("127.0.0.1")
        check(closed_by_server(extra), f"больше {phone.MAX_PER_IP} соединений с одного устройства: лишнее закрывается")
        extra.close()
        other = conn("127.0.0.3")
        other.sendall(f"GET /favicon.ico HTTP/1.0\r\nHost: {rx.authority}\r\n\r\n".encode())
        check(other.recv(12).startswith(b"HTTP/1.0 404"), "другое устройство при этом обслуживается")
        other.close()
        t0 = time.monotonic()
        check(closed_by_server(idle[0]) and time.monotonic() - t0 < 3, "молчащее соединение закрывается по времени")
        for s in idle:
            s.close()
        wait_for(lambda: len(rx._conns) == 0, 8)   # the quiet ones are dropped by time (1 s here)
        r, _, key = Client(rx).open_page()
        check(r.status == 200, "после закрытия молчащих соединений приём работает")
    finally:
        phone._Handler.timeout = saved
        port = rx.port
        rx.stop()
    try:
        socket.create_connection(("127.0.0.1", port), timeout=1).close()
        check(False, "после закрытия окна порт не слушается")
    except OSError:
        check(True, "после закрытия окна порт не слушается")
    check(not rx.running and rx.state == phone.CLOSED, "приёмник закрыт, код мёртв")
    rx.stop()
    check(True, "повторное закрытие без ошибки")
    rx2 = phone.Receiver("127.0.0.1", ports=(port,))
    rx2.start()
    check(rx2.port == port, "тот же порт снова свободен")
    rx2.stop()


def test_network_rules():
    rx = phone.Receiver("192.168.1.23", network="192.168.1.23/24")
    check(rx.client_allowed("192.168.1.7") and not rx.client_allowed("10.0.0.5")
          and not rx.client_allowed("8.8.8.8"), "принимаются только адреса своей подсети")
    rx = phone.Receiver("127.0.0.1")
    check(rx.client_allowed("127.0.0.2") and rx.client_allowed("10.1.2.3") and not rx.client_allowed("1.1.1.1"),
          "без подсети: только частные адреса")
    cands = [
        {"ip": "172.17.0.1", "prefix": 16, "name": "docker0", "kind": "ethernet"},
        {"ip": "10.8.0.2", "prefix": 24, "name": "tun0", "kind": "other", "point_to_point": True},
        {"ip": "100.101.5.6", "prefix": 32, "name": "tailscale0", "kind": "other"},
        {"ip": "10.2.0.2", "prefix": 32, "name": "wg0", "kind": "other"},
        {"ip": "169.254.3.4", "prefix": 16, "name": "eth9", "kind": "ethernet"},
        {"ip": "203.0.113.5", "prefix": 24, "name": "eth1", "kind": "ethernet"},
        {"ip": "192.168.56.1", "prefix": 24, "name": "Ethernet 3", "human": "VirtualBox Host-Only", "kind": "ethernet"},
        {"ip": "10.0.0.15", "prefix": 24, "name": "enp3s0", "kind": "ethernet"},
        {"ip": "192.168.1.23", "prefix": 24, "name": "wlp2s0", "kind": "wifi"},
    ]
    usable = sorted([c for c in cands if phone.usable_candidate(c)], key=phone.rank_candidate)
    check([c["name"] for c in usable] == ["wlp2s0", "enp3s0"],
          f"домашний адрес: Wi-Fi, потом кабель; без docker, VPN, Tailscale, WireGuard ({[c['name'] for c in usable]})")
    check(phone.network_of(usable[0]) == "192.168.1.0/24", "подсеть домашнего адреса")
    cmd = phone.linux_firewall_command("ufw", "192.168.1.0/24")
    check(cmd.startswith("sudo ufw allow proto tcp from 192.168.1.0/24 to any port 8765:8767"),
          "ufw: одна команда, только своя подсеть и свои порты")
    check("192.168.1.0/24" in phone.linux_firewall_command("firewalld", "192.168.1.0/24")
          and phone.linux_firewall_command("", "x") == "", "firewalld и «нет сетевого экрана»")
    cmds = phone.windows_firewall_commands(r"C:\Users\A B\AppData\Local\Programs\ClipSD\app\ClipSD-app.exe")
    add = cmds[1]
    check(os.path.basename(cmds[0][0]).lower() in ("netsh", "netsh.exe")   # на Windows полный путь из System32
          and cmds[0][1:5] == ["advfirewall", "firewall", "delete", "rule"]
          and "profile=private" in add and "remoteip=localsubnet" in add and "localport=8765-8767" in add
          and any(a.endswith("ClipSD-app.exe") and a.startswith("program=C:\\Users\\A B") for a in add),
          "Windows: удалить запрет, разрешить только частные сети, свою подсеть и свои порты")
    check(not hasattr(phone, "apply_windows_firewall"), "прежней команды ClipSD с правами администратора нет")


def test_new_name():
    names = {"ru": "Скриншот/фото с телефона", "en": "Screenshot/photo from phone"}
    for lang in i18n.LANGUAGES:
        i18n.set_language(lang)
        n = tr("phone.menu")
        check("/" in n and n == tr("phone.insert_menu") == tr("phone.title") and n in tr("phone.page_closed")
              and tr("phone.page_title") == "ClipSD" and tr("phone.page_choose"),
              f"{lang}: название «{n}» одно в меню, «Вставить», заголовке окна и на странице")
    for lang, n in names.items():
        i18n.set_language(lang)
        check(tr("phone.menu") == n and tr("phone.title") == n, f"{lang}: название по решению владельца")
    i18n.set_language("ru")


def test_page_render():
    for lang in i18n.LANGUAGES:
        i18n.set_language(lang)
        t = phone_ui.page_texts()
        check(all(v and not v.startswith("phone.") for v in t.values()), f"{lang}: все тексты страницы есть")
        html = phone_page.render_page(t, lang, "/abc", "KEY", "nonce1")
        check(f'lang="{lang}"' in html and t["page_intro"].replace("&", "&amp;") in html, f"{lang}: страница")
    i18n.set_language("ru")
    evil = dict(phone_ui.page_texts(), page_send="</script><script>alert(1)</script>",
                page_intro='<img src=x onerror=alert(1)>')
    html = phone_page.render_page(evil, "ru", "/abc", "KEY", "n")
    check(html.count("</script>") == 2 and "<img src=x" not in html, "тексты экранируются в разметке и в JSON")


# --- the window --------------------------------------------------------------------------------------------------

class FakeCanvas:
    def __init__(self):
        self.inserted = []

    def insert_image(self, image):
        self.inserted.append(image.size())


class FakeEditor:
    def __init__(self):
        self.canvas = FakeCanvas()
        self.shown = 0

    def show(self):
        self.shown += 1

    def raise_(self):
        pass

    def activateWindow(self):
        pass


class Ctx:
    def __init__(self):
        self.config = dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True)
        self.saved = 0
        self.opened = []
        self.editors = []

    def save_config(self):
        self.saved += 1

    def autosave(self, image, ext=None, quality=None):
        self.autosaved = getattr(self, "autosaved", []) + [(image.size(), image.devicePixelRatio(), ext, quality)]
        return "/tmp/x.png"

    def open_editor(self, image, origin):
        self.opened.append(image.size())
        self.opened_dpr = getattr(self, "opened_dpr", []) + [image.devicePixelRatio()]
        return type("E", (), {})()

    def notify(self, text):
        pass


LOOP = [{"ip": "127.0.0.1", "prefix": 8, "name": "lo-test", "kind": "wifi"}]


def phone_window(ctx, target=None):
    dlg = phone_ui.PhoneDialog(ctx, target, candidates=LOOP)
    dlg.start()
    dlg.open_centered()
    settle()
    return dlg


def test_window_flow():
    i18n.set_language("ru")
    ctx = Ctx()
    real_show = phone_ui._show
    phone_ui._show = lambda c, t=None: _show_loop(c, t)
    try:
        note = phone_ui.open_phone(ctx)
        check(isinstance(note, phone_ui.WifiNote), "первый раз: напоминание про одну сеть Wi-Fi")
        check(note.ok_btn.text() == "Понятно, показать код" and note.hide_box.text() == "Не показывать больше",
              "кнопки напоминания как на эскизе")
        from PyQt6.QtCore import Qt as _Qt
        QTest.mouseClick(note.hide_box, _Qt.MouseButton.LeftButton)
        check(note.hide_box.isChecked(), "галочка ставится щелчком (свой рисунок, обычный QCheckBox)")
        note.hide_box.setFocus()
        QTest.keyClick(note.hide_box, _Qt.Key.Key_Space)
        QTest.keyClick(note.hide_box, _Qt.Key.Key_Space)
        check(note.hide_box.isChecked(), "и пробелом с клавиатуры")
        note.ok_btn.click()
        settle(400)
        check(ctx.config.get(phone_ui.CONFIG_HIDE_NOTE) is True and ctx.saved == 1, "галочка запомнена в настройках")
        win = phone_ui.current_window()
        check(win is not None and win.receiver is not None and win.receiver.running, "окно с кодом, приём открыт")
        again = phone_ui.open_phone(ctx)
        check(again is win, "второе окно не открывается, поднимается открытое")
    finally:
        phone_ui._show = real_show
    rx = win.receiver
    check(not win.qr_label.pixmap().isNull(), "QR-код нарисован")
    check(win.address.text() == rx.url.split("://")[1], f"адрес для ручного ввода без http:// ({win.address.text()})")
    check(win.ttl.text().startswith("Код действует ещё 3:00") or win.ttl.text().startswith("Код действует ещё 2:5"),
          f"время кода ({win.ttl.text()})")
    check(win.step1.state == "done" and win.step2.state == "now" and win.step3.state == "todo",
          "шаги: 1 готов, 2 сейчас, 3 потом")
    check("127.0.0.1" in win.step1.text.text(), "в шаге 1 адрес компьютера")
    check(win.vpn.text() == "VPN на телефоне может мешать связи.", "строка про VPN видна всегда")
    ph = Client(rx)
    _, _, key = ph.open_page()
    settle()
    check(win.connected and win.step2.state == "done" and win.step3.state == "now" and not win.qr_box.isVisible(),
          "телефон подключился: шаг 2 готов, код спрятан")
    st, ans = ph.post(key, jpeg(1200, 900))
    settle()
    check(st == 200 and ctx.opened == [jpeg_size(*fitted(1200, 900))], "фото открылось в редакторе как снимок (под экран компьютера)")
    check(win.received.text() == "Получено фото: 1 (%d × %d)" % fitted(1200, 900) and win.received_box.isVisibleTo(win) and not win.thumb.pixmap().isNull(),
          "в окне «Получено фото: 1» и картинка")
    st, ans = ph.post(ans["key"], jpeg(300, 200))
    settle()
    check(len(ctx.opened) == 2 and win.received.text() == "Получено фото: 2 (300 × 200)", "второе фото подряд")
    port = rx.port
    win.close()
    settle()
    check(not rx.running, "окно закрыто: приём закрыт")
    try:
        socket.create_connection(("127.0.0.1", port), timeout=1).close()
        check(False, "порт закрыт вместе с окном")
    except OSError:
        check(True, "порт закрыт вместе с окном")
    # note hidden: straight to the code
    ctx2 = Ctx()
    ctx2.config[phone_ui.CONFIG_HIDE_NOTE] = True
    phone_ui._show = lambda c, t=None: _show_loop(c, t)
    try:
        w2 = phone_ui.open_phone(ctx2)
        check(isinstance(w2, phone_ui.PhoneDialog), "галочка стоит: сразу окно с кодом")
        w2.close()
        settle()
    finally:
        phone_ui._show = real_show


def jpeg_size(w, h):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    return img.size()


def _show_loop(ctx, target=None):
    win = phone_ui.PhoneDialog(ctx, target, candidates=LOOP)
    phone_ui._window = win
    win.start()
    win.open_centered()
    return win


def test_window_states():
    i18n.set_language("ru")
    ctx = Ctx()
    ed = FakeEditor()
    ctx.editors = [ed]
    win = phone_window(ctx, target=ed)
    ph = Client(win.receiver)
    _, _, key = ph.open_page()
    st, _ = ph.post(key, jpeg(400, 300))
    settle()
    check(ed.canvas.inserted == [jpeg_size(400, 300)] and not ctx.opened and ed.shown,
          "из «Вставить» редактора: фото легло поверх снимка")
    check(win.hidden_for_photo and not win.isVisible(), "фото получено: окно приёма спрятало себя само")
    win.bring_back()
    settle()
    win._on_event("closed", {"reason": "expired"})
    check(win.warn.isVisible() and win.warn.text().startswith("Код устарел") and win.new_code_btn.isVisible(),
          "устаревший код: пояснение и «Показать новый код»")
    old = win.receiver.token
    win.new_code_btn.click()
    settle()
    check(win.receiver.token != old and win.qr_box.isVisible() and not win.warn.isVisible(), "новый код показан")
    win._on_event("closed", {"reason": "locked"})
    check("подбирает код" in win.warn.text(), "подбор кода: предупреждение")
    win.close()
    settle()
    none = phone_ui.PhoneDialog(ctx, candidates=[])
    ok = none.start()
    none.open_centered()
    settle()
    check(not ok and none.retry_btn.isVisible() and not none.qr_box.isVisible()
          and "не подключён к домашней сети" in none.step1.text.text(), "нет домашней сети: пояснение и «Повторить»")
    none.close()
    saved = phone_ui.TROUBLE_AFTER_MS
    phone_ui.TROUBLE_AFTER_MS = 100
    try:
        w = phone_window(ctx)
        w.trouble_timer.setInterval(100)
        w.trouble_timer.start()
        settle(300)
        check(w.trouble_btn.property("loud") == "true", "20 секунд без телефона: кнопка «Не удалось подключиться?» заметнее")
        w.close()
        settle()
    finally:
        phone_ui.TROUBLE_AFTER_MS = saved


def test_trouble_dialog():
    i18n.set_language("ru")
    ctx = Ctx()
    win = phone_window(ctx)
    d = phone_ui.TroubleDialog(win, platform="linux", firewall="ufw")
    d.open_centered()
    settle()
    check(d.steps[0].title.text() == "Выключите VPN или блокировщик на телефоне на минуту" and d.steps[0].state == "now"
          and d.steps[1].title.text() == "Телефон с Android 17"
          and "ERR_TOO_MANY_RETRIES или ERR_LOCAL_NETWORK_PERMISSION_MISSING" in d.steps[1].text.text()
          and "«Устройства поблизости» → Разрешить" in d.steps[1].text.text() and "Chrome 158" in d.steps[1].text.text(),
          "окно причин: первой VPN, второй «Телефон с Android 17» с кодами ошибок и путём в настройках")
    check(d.command.startswith("sudo ufw allow") and "127.0.0.0/8" in d.command and d.copy_btn is not None,
          "Linux с ufw: готовая команда и «Скопировать команду»")
    d.copy_btn.click()
    check(QGuiApplication.clipboard().text() == d.command and d.status.text() == "Команда скопирована",
          "команда в буфере обмена")
    d.close()
    d2 = phone_ui.TroubleDialog(win, platform="linux", firewall="")
    check(d2.copy_btn is None and d2.steps[3].text.text() == "Возможно, на компьютере стоит другой сетевой экран или защита. Разрешите входящие подключения к портам 8765-8767 из домашней сети.", "Linux, сетевой экран не распознан: строка про другой сетевой экран и порты 8765-8767")
    d2.close()
    d3 = phone_ui.TroubleDialog(win, platform="win32")
    check(d3.allow_btn is not None and d3.allow_btn.text() == "Разрешить заново" and "частную" in d3.steps[3].text.text(),
          "Windows: «Разрешить заново» и совет про частную сеть")
    d3.close()
    win.trouble_btn.click()
    settle()
    check(win.trouble_dialog is not None and win.trouble_dialog.isVisible(), "кнопка открывает окно причин")
    win.trouble_dialog.show_btn.click()
    settle()
    check(win.isVisible() and win.receiver.running, "«Показать код ещё раз»: окно с кодом, приём открыт")
    win.close()
    settle()


def test_menus():
    i18n.set_language("ru")

    class FakeApp:
        def __init__(self):
            self.config = dict(appmod.DEFAULTS)
            self.editors, self.tray, self.qapp = [], None, app
            self.phone_calls = []

        def save_config(self):
            pass

        def open_phone(self, target=None):
            self.phone_calls.append(target)

        def capture_region(self, **_k):
            pass
        capture_fullscreen = open_screen_recording = open_file = open_folder = open_settings = capture_region
        demo_tour = demo_selector_tour = show_about = show_rating = capture_region
        _build_tray_menu = appmod.Clipshot._build_tray_menu

    fake = FakeApp()
    menu = fake._build_tray_menu()
    texts = [a.text() for a in menu.actions()]
    check("Скриншот/фото с телефона" in texts and texts.index("Скриншот/фото с телефона") == texts.index(tr("app.menu_open")) - 1,
          "меню значка: «Скриншот/фото с телефона» перед «Открыть изображение…»")
    next(a for a in menu.actions() if a.text() == "Скриншот/фото с телефона").trigger()
    check(fake.phone_calls == [None], "пункт меню значка открывает окно (фото станет новым снимком)")
    from clipshot.editor import EditorWindow
    image = QImage(300, 200, QImage.Format.Format_RGB32)
    image.fill(QColor("#ffffff"))
    fake.config.update(tour_done=True, theme_chosen=True)
    fake.icon = appmod.make_icon()
    fake.notify = lambda *_a: None
    ed = EditorWindow(image, fake, QPoint(0, 0))
    ed.present()
    settle()
    items = [a.text() for a in ed.insert_button.menu().actions()]
    # 22.11.2026: после пункта телефона идёт разделитель и выбор «Вставить в этот снимок / Открыть отдельным снимком»
    check(items[3] == "Скриншот/фото с телефона" and items[-2:] == ["Вставить в этот снимок", "Открыть отдельным снимком"],
          f"«Вставить» редактора: пункт «Скриншот/фото с телефона», затем выбор места ({items})")
    ed.insert_button.menu().actions()[3].trigger()
    check(fake.phone_calls[-1] is ed, "пункт «Вставить» передаёт свой редактор: фото ляжет поверх снимка")
    ed.canvas.modified, ed.exported = False, True
    ed.close()
    check("phone_wifi_note_hidden" in appmod.DEFAULTS and appmod.DEFAULTS["phone_wifi_note_hidden"] is False,
          "настройка галочки по умолчанию выключена")


def need_height(w):
    lay = w.layout()
    lay.activate()
    return lay.totalHeightForWidth(w.width())


def test_languages():
    for lang in i18n.LANGUAGES:
        i18n.set_language(lang)
        ctx = Ctx()
        win = phone_window(ctx)
        texts = [win.step1.title.text(), win.step2.title.text(), win.step3.title.text(), win.trouble_btn.text(),
                 win.vpn.text(), win.close_btn.text(), win.ttl.text()]
        check(all(t and "phone." not in t for t in texts), f"{lang}: окно переведено")
        check(win.width() <= 1280 and need_height(win) <= 720 and win.height() >= need_height(win),
              f"{lang}: окно с кодом целиком на экране 1280 × 720 ({win.width()} × {need_height(win)})")
        check(win.title.height() >= win.title.heightForWidth(win.title.width()) and win.title.text() == tr("phone.title"),
              f"{lang}: заголовок окна «{win.title.text()}» виден целиком ({win.title.width()} px)")
        win._on_event("connected", {"ip": "192.168.1.40"})
        for ev_name, ev_data in (("progress", {"percent": 99}), ("failed", {"error": "read"})):
            win._on_event(ev_name, ev_data)
            settle(30)
            check(need_height(win) <= 720 and win.height() >= need_height(win) and not win.recv.text().startswith("phone."),
                  f"{lang}: окно со статусом получения ({ev_name}) целиком, высота {win.height()} нужно {need_height(win)}")
        d = phone_ui.TroubleDialog(win, platform="win32")
        d.open_centered()
        settle()
        check(d.height() <= 700 and d.scroll.height() > 100, f"{lang}: окно причин с запасом до края экрана 720 (высота {d.height()}), список прокручивается внутри окна")
        check(need_height(d) <= 720 and d.height() >= need_height(d) and "phone." not in d.steps[0].text.text(),
              f"{lang}: окно причин целиком, без обрезанных строк ({d.width()} × {need_height(d)})")
        d.close()
        note = phone_ui.WifiNote(ctx, None)
        note.open_centered()
        settle()
        check(note.height() >= need_height(note) and note.width() <= 1280, f"{lang}: напоминание про Wi-Fi целиком")
        note.close()
        win.close()
        settle()
        for label, kw in (("шаг «Разрешить»", {}), ("шаг без pkexec", {"which": which_no_pkexec})):
            w = fw_window(Ctx(), **kw)
            alltexts = [w.step2.title.text(), w.step2.text.text(), w.allow_btn.text(), w.fw_status.text()]
            check(all(not t.startswith("phone.") and "{" not in t for t in alltexts), f"{lang}: {label} переведён")
            check(w.width() <= 1280 and need_height(w) <= 720 and w.height() >= need_height(w),
                  f"{lang}: {label} целиком на экране 1280 × 720 ({w.width()} × {need_height(w)})")
            w.close()
            settle()
        d = phone_ui.TroubleDialog(win, platform="linux", firewall="ufw", which=which_all)
        d.open_centered()
        settle()
        check(need_height(d) <= 720 and d.height() >= need_height(d), f"{lang}: окно причин с «Разрешить» целиком")
        d.close()
    i18n.set_language("ru")


# --- 1.32.3 + решение владельца 21.11.2026: отправка сразу после «OK» камеры, «Закрыть» на телефоне, гонки -----------

def raw_upload_start(rx, key, body, src="127.0.0.1", send_part=None):
    """Начало загрузки "медленным телефоном": заголовки и часть тела; возвращает сокет."""
    c = socket.socket()
    c.settimeout(5)
    c.bind((src, 0))
    c.connect(("127.0.0.1", rx.port))
    head = (f"POST /{rx.token}/photo HTTP/1.1\r\nHost: {rx.authority}\r\nOrigin: http://{rx.authority}\r\n"
            f"Content-Type: image/jpeg\r\nX-ClipSD-Key: {key}\r\nContent-Length: {len(body)}\r\n\r\n").encode()
    c.sendall(head + body[:send_part if send_part is not None else len(body) // 2])
    return c


def wait_for(cond, timeout=3.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if cond():
            return True
        settle(20)
    return cond()


def wait_flight(rx, timeout=5.0):
    """A photo upload has started on the server (headers read): the test waits for the event, not for a fixed time."""
    return wait_for(lambda: rx._in_flight is not None, timeout)


def test_page_new_flow():
    """Решения владельца 21.11.2026: файл уходит как есть, очередь, «Отправить и снять ещё», «Отправить и закончить»."""
    for lang in ("ru", "en", "de", "fr", "es", "it", "pl", "pt", "tr", "uk", "bg", "zh"):
        i18n.set_language(lang)
        t = phone_ui.page_texts()
        empty = [k for k, v in t.items() if not v or v == "phone." + k]
        check(not empty, f"{lang}: все тексты страницы телефона есть ({len(t)} строк)")
        html = phone_page.render_page(t, lang, "/abc", "key", "nonce", screen=(2560, 1440))
        missing = [i for i in ("sendmore", "sendend", "retake", "cancel", "finish", "resend", "fill", "pct", "dims",
                               "gal", "shoot", "gal2", "shoot2", "startbar", "note", "qline", "left", "offerbar",
                               "offersend", "offerdel", "offbar") if f'id="{i}"' not in html]
        check(not missing, f"{lang}: на странице есть все элементы {missing}")
        check('id="close1"' not in html and 'id="close2"' not in html and 'id="send"' not in html,
              f"{lang}: нет прежних «Закрыть» и «Отправить на компьютер»")
        for key_name, count in (("page_queue", 2), ("page_left", 1), ("page_offer_title", 1), ("page_progress", 1)):
            check(all(f"{{{n}}}" in t[key_name] for n in {"page_queue": ("sent", "queue"), "page_left": ("t",),
                                                           "page_offer_title": ("n",), "page_progress": ("n",)}[key_name]),
                  f"{lang}: {key_name} с местами для чисел")
    i18n.set_language("ru")
    t = phone_ui.page_texts()
    check(t["page_send_more"] == "Отправить и снять ещё" and t["page_send_end"] == "Отправить и закончить"
          and t["page_retake"] == "Переснять" and t["page_cancel"] == "Отмена" and t["page_finish"] == "Закончить"
          and t["page_queue"] == "Отправлено: {sent}, в очереди: {queue}" and t["page_left"] == "Приём открыт ещё {t}",
          "русские подписи: две главные кнопки, «Переснять», «Отмена», строка очереди, строка времени")
    check(t["page_intro"] == "Снимок с телефона сразу на компьютер" and t["page_shoot"] == "Сфотографировать"
          and t["page_choose"] == "Выбрать скриншот или фото" and t["page_choose_more"] == "Выбрать ещё",
          "первый экран: заголовок, «Сфотографировать», «Выбрать скриншот или фото»")
    html1 = phone_page.render_page(t, "ru", "/abc", "key", "nonce")
    check("После снимка камера телефона покажет кнопку «OK»: нажмите её, затем «Отправить и закончить» или «Отправить и снять ещё»." in html1,
          "под кнопками строка про «OK» камеры и обе кнопки отправки")
    check("font-size:clamp(16px,4.37vw,44px)" in html1 and "min-height:4.6rem" in html1 and 'id="cambar"' not in html1
          and 'id="hint"' not in html1, "размеры в rem от ширины страницы (работает и в режиме «Версия для ПК»); нет видоискателя")
    check('<link rel="icon" type="image/png" href="data:image/png;base64,' in html1 and 'src="data:image/png;base64,' in html1
          and "<title>ClipSD</title>" in html1 and html1.count('name="theme-color"') == 2
          and "prefers-color-scheme:dark" in html1 and "http://" not in html1.split("<script")[0] and "https://" not in html1,
          "логотип и значок вкладки встроены (data:), title ClipSD, theme-color светлая и тёмная, тёмная тема, без внешних адресов")
    check("«Отправить и снять ещё»" not in t["page_failed"] and "Отправить ещё раз" in t["page_failed"], "ошибка отправки называет «Отправить ещё раз»")
    cfg = json.loads(re.search(r'id="cfg">(.*?)</script>', html1).group(1))
    check(cfg["screen"] is None, "размер экрана неизвестен: страница работает по запасному пределу")
    html = phone_page.render_page(t, "ru", "/abc", "key", "nonce", screen=(2560, 1440))
    cfg = json.loads(re.search(r'id="cfg">(.*?)</script>', html).group(1))
    check(cfg["screen"] == [2560, 1440] and cfg["max"] == phone.MAX_BYTES, "страница знает размер экрана компьютера и предел файла")
    js = phone_page._SCRIPT
    chosen = js[js.index("function chosen"):js.index("/* ---------- the queue")]
    check("enqueue(" not in chosen and "showReady(" in chosen and "fallback(" in chosen,
          "выбор снимка (камера, галерея) ничего не отправляет и не перекодирует: показывает как есть (запасной путь только для HEIC, больших и чужих типов)")
    check("URL.createObjectURL(cur.blob)" in js and "toDataURL" not in js and "FileReader" not in js,
          "превью через createObjectURL файла, без dataURL и без чтения файла")
    send_more = js[js.index("function sendMore"):js.index("function sendEnd")]
    check(send_more.index("cam.click()") < send_more.index("pump()"), "«Отправить и снять ещё»: камера открывается в том же нажатии, отправка идёт в фоне")
    check("X-ClipSD-Photo" in js and "X-ClipSD-Timing" in js and "x.upload.onprogress" in js
          and "indexedDB" in js and js.count("try{") >= 4, "заголовки id фото и времён; полоса; очередь в хранилище в try/catch")
    check("X-ClipSD-Mode" not in js and "localStorage" not in js and 'id="mode"' not in html1 and 'id="modenote"' not in html1
          and "page_size" not in js and "page_mode" not in js,
          "на странице телефона нет переключателя размера, пояснений про размер и заголовка режима: файл всегда как есть")
    check(re.search(r'id="sendend" class="btn main"', html1) and re.search(r'id="sendmore" class="btn"', html1)
          and html1.index('id="sendend"') < html1.index('id="sendmore"'),
          "экран «Фото готово»: главная зелёная «Отправить и закончить» первой, «Отправить и снять ещё» обычная второй")
    check(js.count("X-ClipSD-Timing") >= 3 and "function closeReception" in js
          and "lastTiming" in js[js.index("function closeReception"):js.index("/* ---------- buttons")],
          "времена шагов уходят и с «закончить»: время отправки последнего фото не теряется")
    check('style="' not in html1.split("<script")[0] and "unsafe-inline" not in html1,
          "в разметке нет style-атрибутов (политика страницы их блокирует)")
    for name in ("persist(", "dbDo(", "showAsk(", "layoutPanel(", "freshKey(", "closeReception("):
        defined = f"function {name}"
        check(defined in js, f"в скрипте страницы определена {name[:-1]}")
    check("upDone" in js and "now-upDone>20000" in js and "now-t0>5000" in js and "now-last>8000" in js,
          "тайм-ауты: нет первого байта 5 с, нет движения 8 с, после тела ответ ждём 20 с (ПК отвечает сразу)")
    check("if(finishing){finishing=false;showAsk();return;}" in js and 'id="askagain"' in html1 and 'id="askdrop"' in html1,
          "«Закончить» без циклов: одна попытка, потом вопрос «Отправить ещё раз / Закончить без него»")
    check("data-state=ready] #readybar{position:fixed" in html1.replace(" #", " #") or "[data-state=ready] #readybar{position:fixed" in html1,
          "кнопки отправки закреплены внизу экрана «Фото готово»")
    check("closeReception()" in js[js.index("function afterQueue"):js.index("function closeReception")],
          "«Отправить и закончить»: после очереди страница сама закрывает приём")


def test_phone_close():
    rx, ev = receiver()
    try:
        ph = Client(rx)
        _, _, key = ph.open_page()
        st, ans = ph.post(key, jpeg())
        key = ans["key"]
        r, _ = ph.request("POST", f"/{rx.token}/close", headers={"X-ClipSD-Key": "wrong", "Origin": f"http://{rx.authority}"})
        check(r.status == 403 and rx.state == phone.PAIRED and rx.bad == 1, "«Закрыть» с чужим ключом: 403, приём работает, это попытка подбора")
        r, _ = Client(rx, "127.0.0.2").request("POST", f"/{rx.token}/close",
                                               headers={"X-ClipSD-Key": key, "Origin": f"http://{rx.authority}"})
        check(r.status == 403 and rx.state == phone.PAIRED, "«Закрыть» с другого устройства не закрывает")
        r, _ = ph.request("POST", f"/{rx.token}/close", headers={"X-ClipSD-Key": key, "Origin": "http://evil.example"})
        check(r.status == 403 and rx.state == phone.PAIRED, "«Закрыть» с чужой страницы (Origin) не закрывает")
        r, _ = ph.request("POST", f"/{rx.token}/close", headers={"X-ClipSD-Key": key, "Origin": f"http://{rx.authority}"})
        check(r.status == 200 and rx.state == phone.CLOSED and rx.reason == "phone"
              and ("closed", {"reason": "phone"}) in ev, "«Закрыть» с телефона: приём закрыт, причина «phone»")
        st, _ = ph.post(key, jpeg())
        check(st == 410, "после «Закрыть» новая загрузка не принимается")
    finally:
        rx.stop()
    ctx = Ctx()
    win = phone_window(ctx)
    ph = Client(win.receiver)
    _, _, key = ph.open_page()
    ph.request("POST", f"/{win.receiver.token}/close", headers={"X-ClipSD-Key": key, "Origin": f"http://{win.receiver.authority}"})
    settle(150)
    check(win.warn.isVisible() and win.warn.text() == tr("phone.phone_done") and win.new_code_btn.isVisible(),
          "окно на компьютере: «Приём закрыт с телефона» и «Показать новый код»")
    win.close()
    settle()


def test_races():
    saved_timeout = phone._Handler.timeout
    # 1. окно закрыто во время загрузки фото
    ctx = Ctx()
    win = phone_window(ctx)
    rx = win.receiver
    _, _, key = Client(rx).open_page()
    settle()
    body = jpeg(2000, 1500)
    c = raw_upload_start(rx, key, body)
    check(wait_flight(rx), "загрузка началась")
    win.close()
    settle(200)
    try:
        got = c.recv(100)
    except OSError:
        got = b""
    check(not got.startswith(b"HTTP/1.1 200") and not ctx.opened and not rx.running,
          "окно закрыто во время загрузки: загрузка оборвана, фото нет, ошибки нет")
    c.close()
    # 2. выход из программы во время загрузки
    ctx = Ctx()
    win = phone_window(ctx)
    rx = win.receiver
    port = rx.port
    _, _, key = Client(rx).open_page()
    c = raw_upload_start(rx, key, body)
    check(wait_flight(rx), "загрузка началась")
    phone_ui._window = win
    phone_ui.stop_all()
    settle(200)
    try:
        got = c.recv(100)
    except OSError:
        got = b""
    check(not got.startswith(b"HTTP/1.1 200") and not ctx.opened, "выход во время загрузки: приём закрыт, фото не открывается")
    try:
        socket.create_connection(("127.0.0.1", port), timeout=1).close()
        check(False, "после выхода порт закрыт")
    except OSError:
        check(True, "после выхода порт закрыт")
    c.close()
    win.close()
    settle()
    # 3. два телефона, две загрузки одновременно
    rx, ev = receiver()
    try:
        a, b = Client(rx), Client(rx, "127.0.0.2")
        _, _, ka = a.open_page()
        r, _, kb = b.open_page()
        check(r.status == 409 and kb is None, "второй телефон: код уже занят")
        import threading
        out = {}

        def up(name, cl, k):
            out[name] = cl.post(k, jpeg(800, 600))

        ts = [threading.Thread(target=up, args=("a1", a, ka)), threading.Thread(target=up, args=("a2", a, ka)),
              threading.Thread(target=up, args=("b", b, ka))]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        ok = [n for n, v in out.items() if v[0] == 200]
        check(len(ok) == 1 and ok[0] in ("a1", "a2") and out["b"][0] in (403, 409) and rx.photos == 1,
              f"один ключ, три загрузки сразу (два телефона): принята ровно одна ({out.get('a1', ('-',))[0]}, "
              f"{out.get('a2', ('-',))[0]}, {out['b'][0]})")
        check(kinds(ev).count("photo") == 1, "событие «фото» ровно одно")
    finally:
        rx.stop()
    # 4. загрузка ровно в момент истечения
    clock = Clock()
    rx, ev = receiver(clock=clock)
    try:
        clock.t += phone.CLAIM_TTL
        r, _, key = Client(rx).open_page()
        check(r.status == 200, "код ровно на границе 3 минут ещё действует")
        rx.renew()
        clock.t += phone.CLAIM_TTL + 0.01
        r, page, key = Client(rx).open_page()
        check(r.status == 410 and rx.reason == "expired", "через 3 минуты и миг: 410")
        rx.renew()
        ph = Client(rx)
        _, _, key = ph.open_page()
        clock.t += phone.IDLE_TTL - 1
        t = rx.tick()
        check(t == phone.PAIRED, "перед границей простоя приём открыт")
        # загрузка идёт, граница простоя проходит: приём не закрывается под загрузкой
        ticket = rx._begin_upload("127.0.0.1", key)
        clock.t += 5
        check(rx.tick() == phone.PAIRED and ticket == "ok", "граница простоя прошла во время загрузки: приём не закрыт")
        rx._deliver(QImage(10, 10, QImage.Format.Format_RGB32), "image/jpeg")
        ans = {}
        rx._end_upload("127.0.0.1", True, ans)
        check(ans.get("key") and rx.state == phone.PAIRED and rx.remaining() == 0, "загрузка закончилась: новый ключ, приём открыт")
        clock.t += phone.IDLE_TTL + 1
        check(rx.tick() == phone.CLOSED and rx.reason == "idle", "дальше 10 минут тишины: закрыт")
        st, _ = ph.post(ans["key"], jpeg())
        check(st == 410, "загрузка после закрытия по простою: 410")
    finally:
        rx.stop()
    # 5. 20-е и 21-е фото (настоящий предел)
    rx, ev = receiver()
    try:
        ph = Client(rx)
        _, _, key = ph.open_page()
        last = {}
        small = jpeg(32, 24)
        for i in range(phone.MAX_PHOTOS):
            st, last = ph.post(key, small)
            if st != 200:
                break
            key = last.get("key", "")
        check(phone.MAX_PHOTOS == 20 and rx.photos == 20 and last.get("limit") is True and rx.reason == "limit",
              "20-е фото принято и сказано, что это последнее")
        st, _ = ph.post(key, small)
        check(st == 410 and rx.photos == 20 and kinds(ev).count("photo") == 20, "21-е фото: 410, принято 20")
    finally:
        rx.stop()
    # 6. редактор, в который вставляют, закрыт до прихода фото; и в другом порядке
    i18n.set_language("ru")
    ctx = Ctx()
    ed = FakeEditor()
    ctx.editors = [ed]
    win = phone_window(ctx, target=ed)
    ph = Client(win.receiver)
    _, _, key = ph.open_page()
    ctx.editors.remove(ed)   # редактор закрыт, окно с кодом ещё открыто
    st, ans = ph.post(key, jpeg(300, 200))
    settle(150)
    check(st == 200 and ctx.opened == [jpeg_size(300, 200)] and not ed.canvas.inserted,
          "редактор закрыт до прихода фото: фото открывается как новый снимок, ничего не потеряно")
    ed2 = FakeEditor()
    ctx.editors.append(ed2)
    win.target = ed2
    st, ans = ph.post(ans["key"], jpeg(200, 100))
    settle(150)
    check(ed2.canvas.inserted == [jpeg_size(200, 100)], "другой порядок: редактор ещё открыт, фото ложится в него")
    ctx.editors.remove(ed2)
    win.close()
    settle()
    check(True, "редактор закрыт после вставки, затем окно: без ошибок")
    # 7. фото пришло, окно закрыто до обработки сигнала
    ctx = Ctx()
    win = phone_window(ctx)
    ph = Client(win.receiver)
    _, _, key = ph.open_page()
    st, ans = ph.post(key, jpeg(120, 90))
    win.close()            # сигнал ещё стоит в очереди
    settle(200)
    check(st == 200 and wait_for(lambda: len(ctx.opened) == 1), f"фото принято, окно закрыто сразу: фото открыто в редакторе, не потеряно ({len(ctx.opened)})")
    phone._Handler.timeout = saved_timeout


# --- «Разрешить»: правило сетевого экрана через pkexec (решение владельца 21.11.2026) ---------------------------

def which_all(name, path=None):
    return "/usr/bin/" + name if name == "pkexec" else "/usr/sbin/" + name


def which_no_pkexec(name, path=None):
    return None if name == "pkexec" else "/usr/sbin/" + name


class FakeProc(QObject):
    """Вместо QProcess: ничего не запускает; тест сам «завершает» pkexec нужным кодом."""
    finished = pyqtSignal(int, QProcess.ExitStatus)
    errorOccurred = pyqtSignal(QProcess.ProcessError)
    made = []

    def __init__(self):
        super().__init__()
        self.started = None
        FakeProc.made.append(self)

    def start(self, program, args):
        self.started = [program] + list(args)

    def closeWriteChannel(self):
        pass

    def end(self, code):
        self.finished.emit(code, QProcess.ExitStatus.NormalExit)


HOME_FW = [{"ip": "192.168.1.23", "prefix": 24, "name": "wlp2s0", "kind": "wifi"}]


def fw_window(ctx, firewall="ufw", which=which_all, cands=HOME_FW):
    FakeProc.made.clear()
    dlg = phone_ui.PhoneDialog(ctx, None, candidates=cands, firewall=firewall, which=which, process_factory=FakeProc,
                               receiver_cls=lambda host, **kw: phone.Receiver("127.0.0.1", **kw))
    dlg.start()
    dlg.open_centered()
    settle()
    return dlg


def test_firewall_allow_argv():
    for net, good in (("192.168.1.0/24", True), ("192.168.1.23/24", True), ("10.0.0.0/8", True), ("172.16.5.0/24", True),
                      ("0.0.0.0/0", False), ("8.8.8.0/24", False), ("203.0.113.0/24", False), ("100.64.0.0/10", False),
                      ("192.168.1.5/32", False), ("127.0.0.0/8", False), ("::/0", False), ("fd00::/8", False),
                      ("192.168.0.0/15", False), ("10.0.0.0/7", False), ("192.168.1.0/24; rm -rf ~", False),
                      ("$(id)", False), ("", False), (None, False), ("192.168.1.0/24 to any", False)):
        got = phone.firewall_network(net)
        check((got is not None) == good, f"подсеть для правила {net!r}: {'принята' if good else 'отклонена'}")
    argv = phone.firewall_allow_argv("ufw", "192.168.1.23/24", which_all)
    check(argv == ["/usr/bin/pkexec", "/usr/sbin/ufw", "allow", "proto", "tcp", "from", "192.168.1.0/24", "to", "any",
                   "port", "8765:8767", "comment", "ClipSD photo from phone"],
          "ufw: pkexec, точный путь, аргументы списком, своя подсеть, порты 8765:8767")
    fw = phone.firewall_allow_argv("firewalld", "192.168.1.0/24", which_all)
    check(fw[:2] == ["/usr/bin/pkexec", "/usr/sbin/firewall-cmd"] and len(fw) == 3
          and fw[2] == '--add-rich-rule=rule family="ipv4" source address="192.168.1.0/24" port port="8765-8767" protocol="tcp" accept',
          "firewalld: одно правило, своя подсеть, порты 8765-8767")
    check(phone.PREFERRED_PORTS == (8765, 8766, 8767), "портов три: 8765-8767")
    for a in (argv, fw):
        check(all(isinstance(x, str) for x in a) and not any(x in ("sh", "bash", "-c", "/bin/sh") for x in a)
              and all(x.startswith("/") or not x.startswith("-") or x.startswith("--add-rich-rule=") for x in a),
              "в команде нет оболочки и посторонних ключей")
    check(phone.firewall_allow_argv("ufw", "0.0.0.0/0", which_all) is None
          and phone.firewall_allow_argv("ufw", "8.8.8.0/24", which_all) is None, "публичную подсеть и 0.0.0.0/0 не открываем")
    check(phone.firewall_allow_argv("ufw", "192.168.1.0/24", which_no_pkexec) is None, "нет pkexec: команды нет")
    check(phone.firewall_allow_argv("ufw", "192.168.1.0/24", lambda n, path=None: None) is None, "нет ufw: команды нет")
    check(phone.firewall_allow_argv("", "192.168.1.0/24", which_all) is None
          and phone.firewall_allow_argv("iptables", "192.168.1.0/24", which_all) is None, "неизвестный сетевой экран: команды нет")
    check(phone.firewall_allow_argv("ufw", "192.168.1.0/24", lambda n, path=None: "ufw" if n == "ufw" else "/usr/bin/pkexec") is None,
          "относительный путь программы не принимается")
    check([phone.allow_outcome(c) for c in (0, 126, 127, 1, 255)] == ["ok", "declined", "declined", "failed", "failed"],
          "коды pkexec: 0 готово, 126 и 127 отмена, остальное ошибка")


def test_allow_step():
    i18n.set_language("ru")
    ctx = Ctx()
    win = fw_window(ctx)
    check(win.fw_box.isVisible() and not win.qr_box.isVisible() and win.receiver is None
          and win.step2.title.text() == "Разрешите приём фото" and "откроются только 3 порта" in win.step2.text.text()
          and win.allow_btn.isVisible() and win.allow_btn.text() == "Разрешить",
          "сетевой экран включён, правила нет: шаг «Разрешить» перед кодом, кода ещё нет")
    check("Приём открыт" not in win.step1.text.text() and "192.168.1.23" in win.step1.text.text(),
          "в шаге 1 не написано «Приём открыт», пока приём не открыт")
    win.allow_btn.click()
    settle()
    proc = FakeProc.made[-1]
    check(proc.started[:2] == ["/usr/bin/pkexec", "/usr/sbin/ufw"] and "192.168.1.0/24" in proc.started
          and not win.allow_btn.isEnabled() and win.fw_status.text() == "Ждём ответ окна пароля…",
          "кнопка запускает pkexec со списком аргументов и ждёт окно пароля")
    proc.end(126)
    settle()
    check(win.fw_status.text().startswith("Не разрешено") and win.allow_btn.isEnabled() and win.receiver is None
          and not ctx.config.get(phone_ui.CONFIG_FW_NETWORKS), "отмена в окне пароля: «Не разрешено», кнопка осталась, без ошибок")
    win.allow_btn.click()
    FakeProc.made[-1].end(127)
    settle()
    check(win.fw_status.text().startswith("Не разрешено") and win.allow_btn.isEnabled(), "код 127 тоже отмена")
    win.allow_btn.click()
    FakeProc.made[-1].end(1)
    settle()
    check("код 1" in win.fw_status.text() and win.allow_btn.isEnabled() and win.receiver is None, "сбой ufw: понятная строка с кодом")
    win.allow_btn.click()
    FakeProc.made[-1].errorOccurred.emit(QProcess.ProcessError.FailedToStart)
    settle()
    check("код -1" in win.fw_status.text() and win.allow_btn.isEnabled(), "pkexec не запустился: строка, кнопка осталась")
    win.allow_btn.click()
    FakeProc.made[-1].end(0)
    settle()
    check(win.receiver is not None and win.receiver.running and win.qr_box.isVisible() and not win.fw_box.isVisible()
          and win.step2.text.text() == "Разрешено, наведите камеру на код.",
          "успех: «Разрешено, наведите камеру на код», код показан, приём открыт")
    check(ctx.config.get(phone_ui.CONFIG_FW_NETWORKS) == ["192.168.1.0/24"] and ctx.saved >= 1, "правило запомнено в настройках")
    win.close()
    settle()
    win2 = fw_window(ctx)
    check(win2.receiver is not None and win2.receiver.running and not win2.fw_box.isVisible() and not FakeProc.made,
          "повторное открытие окна: шага «Разрешить» нет, сразу код")
    win2.close()
    settle()
    # другая подсеть: шаг снова
    win3 = fw_window(ctx, cands=[{"ip": "10.1.2.3", "prefix": 24, "name": "wlp2s0", "kind": "wifi"}])
    check(win3.fw_box.isVisible() and win3.receiver is None, "другая подсеть: правила для неё нет, шаг есть")
    win3.close()
    settle()
    # сетевого экрана нет, чужая подсеть (петля), Windows: шага нет совсем
    for label, w in (("сетевой экран выключен", fw_window(Ctx(), firewall="")),
                     ("подсеть не домашняя", fw_window(Ctx(), cands=LOOP))):
        check(not w.fw_box.isVisible() and w.receiver is not None and w.receiver.running, f"{label}: шага нет, сразу код")
        w.close()
        settle()
    # firewalld: правило до перезагрузки правил, в настройках не запоминается
    ctx4 = Ctx()
    w4 = fw_window(ctx4, firewall="firewalld")
    w4.allow_btn.click()
    check(FakeProc.made[-1].started[1] == "/usr/sbin/firewall-cmd", "firewalld: firewall-cmd через pkexec")
    FakeProc.made[-1].end(0)
    settle()
    check(w4.receiver is not None and not ctx4.config.get(phone_ui.CONFIG_FW_NETWORKS), "firewalld: приём открыт, в настройках не запоминается")
    w4.close()
    settle()
    # нет pkexec: прежняя команда, «Скопировать», «Показать код»
    w5 = fw_window(Ctx(), which=which_no_pkexec)
    check(not w5.allow_btn.isVisible() and w5.fw_command.text().startswith("sudo ufw allow proto tcp from 192.168.1.0/24")
          and "port 8765:8767" in w5.fw_command.text() and w5.fw_copy_btn.isVisible() and w5.fw_next_btn.isVisible()
          and w5.receiver is None, "нет pkexec: команда, «Скопировать команду», «Показать код»")
    w5.fw_copy_btn.click()
    check(QGuiApplication.clipboard().text() == w5.fw_command.text(), "команда в буфере обмена")
    w5.fw_next_btn.click()
    settle()
    check(w5.receiver is not None and w5.receiver.running and not w5.fw_box.isVisible(), "«Показать код»: приём открыт")
    w5.close()
    settle()


def test_allow_races():
    i18n.set_language("ru")
    # окно закрыли, пока открыто окно пароля; ответ pkexec приходит после закрытия
    ctx = Ctx()
    win = fw_window(ctx)
    win.allow_btn.click()
    proc = FakeProc.made[-1]
    win.close()
    settle(100)
    proc.end(0)
    settle(100)
    check(win.receiver is None and True, "ответ pkexec после закрытия окна: не падает, приёмник не открывается")
    check(ctx.config.get(phone_ui.CONFIG_FW_NETWORKS) == ["192.168.1.0/24"], "правило всё же добавлено: оно запомнено")
    ctx = Ctx()
    win = fw_window(ctx)
    win.allow_btn.click()
    proc = FakeProc.made[-1]
    win.close()
    settle(100)
    proc.end(126)
    settle(100)
    check(win.receiver is None and not ctx.config.get(phone_ui.CONFIG_FW_NETWORKS),
          "отмена после закрытия окна: тихо, ничего не запомнено")
    check(not phone_ui._runners, "запущенных pkexec в памяти не осталось")
    # закрыли окно причин, пока открыто окно пароля
    win = fw_window(Ctx(), firewall="")
    d = phone_ui.TroubleDialog(win, platform="linux", firewall="ufw", which=which_all, process_factory=FakeProc)
    d.open_centered()
    FakeProc.made.clear()
    d.allow_btn.click()
    proc = FakeProc.made[-1]
    d.close()
    settle(100)
    proc.end(0)
    settle(100)
    check(True, "окно причин закрыто до ответа pkexec: не падает")
    win.close()
    settle()


def test_trouble_allow():
    i18n.set_language("ru")
    ctx = Ctx()
    win = fw_window(ctx, firewall="")
    d = phone_ui.TroubleDialog(win, platform="linux", firewall="ufw", which=which_all, process_factory=FakeProc)
    d.open_centered()
    settle()
    check(d.allow_btn is not None and d.allow_btn.text() == "Разрешить" and not d.command and d.copy_btn is None
          and "откроются только 3 порта" in d.steps[3].text.text(), "окно причин: пункт с кнопкой «Разрешить»")
    check(d.fw_net == "192.168.1.0/24", "подсеть та же, что у окна с кодом")
    FakeProc.made.clear()
    d.allow_btn.click()
    FakeProc.made[-1].end(126)
    settle()
    check(d.status.text().startswith("Не разрешено") and d.allow_btn.isEnabled(), "окно причин: отмена, кнопка осталась")
    d.allow_btn.click()
    FakeProc.made[-1].end(0)
    settle()
    check(d.status.text() == "Разрешено, наведите камеру на код." and ctx.config.get(phone_ui.CONFIG_FW_NETWORKS) == ["192.168.1.0/24"],
          "окно причин: успех, правило запомнено")
    d.close()
    d2 = phone_ui.TroubleDialog(win, platform="linux", firewall="ufw", which=which_no_pkexec)
    check(d2.allow_btn is None and d2.command.startswith("sudo ufw allow") and d2.copy_btn is not None,
          "окно причин без pkexec: команда и «Скопировать команду»")
    d2.close()
    win.close()
    settle()


# --- проба на Samsung 21.11.2026: «Отправить на компьютер», статус получения, размер под экран, ключ, Android 17 -----

def test_allow_again_windows():
    """Б4 проверки 1.34.1: «Разрешить заново» на Windows. С правами администратора идёт только PowerShell Windows по полному
    пути из системной папки, команда целиком в -EncodedCommand, netsh тоже по полному пути, путь программы проверен
    и в кавычках PowerShell; ClipSD сама не повышается, итог кодом выхода, ожидание в фоне, файлов нет."""
    import base64
    import tempfile
    from clipshot import sysenv
    i18n.set_language("ru")
    fake_sys = os.path.join(os.path.abspath(os.sep), "Windows", "System32")
    exe = sys.executable
    params = phone.firewall_parameters(exe, netsh=os.path.join(fake_sys, "netsh.exe"))
    parts = params.split()
    check(parts[:-1] == ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand"],
          "администратору только -EncodedCommand, без -File и -Command")
    script = base64.b64decode(parts[-1]).decode("utf-16-le")
    netsh_q = "'" + os.path.join(fake_sys, "netsh.exe") + "'"
    check(script.count("$null = & " + netsh_q + " 'advfirewall' 'firewall'") == 2 and "exit $LASTEXITCODE" in script
          and "Out-Null" not in script and script.startswith('$env:PSModulePath = "$PSHOME\\Modules"\n'),
          "две команды netsh по полному пути без командлетов, PSModulePath сброшен первой строкой, итог кодом выхода")
    check(f"'program={exe}'" in script and "'profile=private'" in script and "'remoteip=localsubnet'" in script
          and "'localport=8765-8767'" in script, "правило: эта программа, частные сети, своя подсеть, свои порты")
    body = script[len(sysenv.ELEVATED_PS_PROLOGUE):] if script.startswith(sysenv.ELEVATED_PS_PROLOGUE) else script
    check(not any(w in body for w in ("Out-File", "Set-Content", "WriteAllText", "Get-Content", "$env:", "TEMP")),
          "команда администратора не читает и не пишет файлы и не берёт данных из окружения")
    # путь программы проверяется: существует, абсолютный, это сама ClipSD
    folder = tempfile.mkdtemp(prefix="clipsd-fwtest-")
    odd = os.path.join(folder, "O'Brien $(calc) `x` ; & B", "ClipSD-app.exe")
    os.makedirs(os.path.dirname(odd))
    open(odd, "wb").close()
    script = phone.windows_firewall_script(phone.firewall_program(odd, executable=odd), netsh="netsh")
    check("'program=" + odd.replace("'", "''") + "'" in script,
          "апостроф удвоен, $( ), обратные кавычки, ; и & внутри одинарных кавычек PowerShell (не выполняются)")
    for bad, why in ((odd, "не эта программа"), ("ClipSD-app.exe", "не абсолютный путь"),
                     (os.path.join(folder, "нет.exe"), "файла нет")):
        try:
            phone.firewall_parameters(bad)
            check(False, f"путь отклонён: {why}")
        except ValueError:
            pass
    for bad in ("a\nb", "a\u2019b", "a\u2018b", "a\x00b"):
        try:
            sysenv.ps_quote(bad)
            check(False, f"ps_quote отклоняет {bad!r}")
        except ValueError:
            pass
    check(sysenv.ps_quote("A'B") == "'A''B'", "ps_quote: апостроф удвоен")
    import shutil
    shutil.rmtree(folder, ignore_errors=True)
    # окно причин: кнопка, ожидание в фоне, итог
    ctx = Ctx()
    win = fw_window(ctx, firewall="")
    calls = []
    real_wait, real_sysdir, real_platform = sysenv.run_elevated_wait, sysenv._system_dir, sys.platform

    def fake_wait(program, parameters, timeout_ms, api=None):
        import time
        calls.append((program, parameters, timeout_ms))
        time.sleep(0.2)
        return outcome[0]

    outcome = [(0, "", False)]
    before = set(os.listdir(tempfile.gettempdir()))
    sysenv.run_elevated_wait, sysenv._system_dir, sys.platform = fake_wait, (lambda: fake_sys), "win32"
    try:
        def press(result):
            outcome[0] = result
            d = phone_ui.TroubleDialog(win, platform="win32")
            d.allow_btn.click()
            busy = not d.allow_btn.isEnabled() and d.status.text() == tr("phone.allow_working")
            check(wait_for(lambda: not phone_ui._firewall_jobs and d.allow_btn.isEnabled(), 10), "ожидание закончилось")
            settle()
            return d, busy

        d, busy = press((0, "", False))
        check(busy and tr("phone.allow_working").startswith("Windows спросит разрешение для Windows PowerShell"),
              "кнопка: сразу «Windows спросит разрешение для Windows PowerShell…» (М11), кнопка выключена, окно живёт")
        program, parameters, _ = calls[-1]
        check(program == os.path.join(fake_sys, "WindowsPowerShell", "v1.0", "powershell.exe") and os.path.isabs(program),
              "с правами администратора: PowerShell по полному пути из системной папки, не ClipSD")
        check(parameters == phone.firewall_parameters(), "команда собрана в обычном процессе для этой ClipSD")
        check(d.status.text() == "Готово. Откройте код на телефоне ещё раз.", "код 0: «Готово»")
        d.close()
        d, _ = press((None, "ShellExecuteEx 1223", True))
        check(d.status.text() == "Разрешение не дано. Нажмите «Разрешить заново» и ответьте «Да».", "отказ UAC: понятный текст")
        d.close()
        d, _ = press((1, "", False))
        check(d.status.text() == "Правило Windows не изменено: exit 1", "сбой netsh: код выхода в тексте")
        d.close()
        outcome[0] = (0, "", False)
        d = phone_ui.TroubleDialog(win, platform="win32")
        d.allow_btn.click()
        from PyQt6 import sip
        sip.delete(d)   # окно удалено посреди ожидания
        check(wait_for(lambda: not phone_ui._firewall_jobs, 10), "окно удалили посреди ожидания: без падения, задание убрано")
    finally:
        sysenv.run_elevated_wait, sysenv._system_dir, sys.platform = real_wait, real_sysdir, real_platform
    after = set(os.listdir(tempfile.gettempdir()))
    check(not [n for n in after - before if n.startswith("clipsd")], f"файлов во временной папке нет ({sorted(after - before)})")
    check(not hasattr(sysenv, "run_elevated_self"), "повышения самой ClipSD больше нет (run_elevated_self убран)")
    import subprocess
    cli = subprocess.run([sys.executable, "-m", "clipshot", "--allow-phone-firewall"], capture_output=True, timeout=60,
                         env=dict(os.environ, PYTHONPATH=str(ROOT)))
    check(cli.returncode == 2 and b"allow-phone-firewall" in cli.stderr, f"clipsd --allow-phone-firewall больше нет (код {cli.returncode})")
    win.close()
    settle()


def test_receive_status_events():
    rx, ev = receiver(screen=(2560, 1440))
    try:
        ph = Client(rx)
        r, page, key = ph.open_page()
        cfg = json.loads(re.search(r'id="cfg">(.*?)</script>', page, re.S).group(1))
        check(cfg["screen"] == [2560, 1440], "страница получила размер экрана компьютера")
        big = jpeg(3000, 2000)
        st, ans = ph.post(key, big)
        ks = kinds(ev)
        check(st == 200 and ks.index("receiving") < ks.index("progress") < ks.index("photo"),
              "события: «получение», «ход», «фото» в таком порядке")
        total = [d for k, d in ev if k == "receiving"][0]["total"]
        pcts = [d["percent"] for k, d in ev if k == "progress"]
        check(total == len(big) and pcts == sorted(pcts) and pcts[-1] == 100 and all(0 <= p <= 100 for p in pcts),
              f"ход получения растёт до 100 % ({len(pcts)} отметок), всего {total} байт")
        photo = [d for k, d in ev if k == "photo"][0]
        check((photo["image"].width(), photo["image"].height()) == fitted(3000, 2000, (2560, 1440)), "компьютер сам уменьшил снимок под экран (2560 × 1440): 2160 × 1440")
        # обрыв на середине: «не дошло», ключ жив, приём работает, фото нет
        ev.clear()
        c = raw_upload_start(rx, ans["key"], big, send_part=len(big) // 3)
        wait_flight(rx)
        c.close()
        check(wait_for(lambda: "failed" in kinds(ev)), "обрыв на середине: событие «не дошло»")
        check("photo" not in kinds(ev) and rx.state == phone.PAIRED and rx._in_flight is None, "обрыв: фото нет, приём открыт, ключ свободен")
        st2, ans2 = ph.post(ans["key"], jpeg(100, 80))
        check(st2 == 200 and rx.photos == 2, "после обрыва тем же ключом фото проходит")
        # не картинка: «не дошло»
        ev.clear()
        st3, _ = ph.post(ans2["key"], b"not a picture at all" * 20)
        check(st3 == 415 and "failed" in kinds(ev), "не картинка: 415 и событие «не дошло»")
    finally:
        rx.stop()


def test_fresh_key():
    rx, ev = receiver()
    try:
        a = Client(rx)
        _, _, key = a.open_page()
        h = {"Origin": f"http://{rx.authority}"}
        r, data = a.request("GET", f"/{rx.token}/key", headers=h)
        j = json.loads(data)
        check(r.status == 200 and j["key"] and j["key"] != key, "«/key»: телефон получает новый ключ")
        st, _ = a.post(key, jpeg(50, 40))
        check(st == 403, "старый ключ после этого не работает")
        st, ans = a.post(j["key"], jpeg(50, 40))
        check(st == 200, "новый ключ работает")
        r, _ = Client(rx, "127.0.0.2").request("GET", f"/{rx.token}/key")
        check(r.status == 409 and rx.bad >= 1, "чужое устройство ключ не получает (попытка подбора)")
        # пока фото идёт: занято, ключ не меняется
        c = raw_upload_start(rx, ans["key"], jpeg(2000, 1500))
        wait_flight(rx)
        r, data = a.request("GET", f"/{rx.token}/key", headers=h)
        check(r.status == 409 and json.loads(data)["error"] == "busy", "пока фото принимается, новый ключ не выдаётся")
        c.close()
        check(wait_for(lambda: rx._in_flight is None), "после обрыва ключ свободен")
        r, _ = a.request("GET", f"/{rx.token}/key", headers=h)
        check(r.status == 200, "и новый ключ снова выдаётся")
        rx._close("stopped")
        r, _ = a.request("GET", f"/{rx.token}/key", headers=h)
        check(r.status == 410, "приём закрыт: 410")
    finally:
        rx.stop()


def test_close_during_upload():
    """«Закрыть» с телефона, пока фото ещё принимается (две вкладки): ничего не падает."""
    rx, ev = receiver()
    try:
        ph = Client(rx)
        _, _, key = ph.open_page()
        body = jpeg(1800, 1200)
        c = raw_upload_start(rx, key, body, send_part=len(body) // 2)
        wait_flight(rx)
        r, _ = ph.request("POST", f"/{rx.token}/close", headers={"X-ClipSD-Key": key, "Origin": f"http://{rx.authority}"})
        check(r.status == 200 and rx.state == phone.CLOSED and rx.reason == "phone", "«Закрыть» во время приёма фото закрывает приём")
        c.sendall(body[len(body) // 2:])
        try:
            got = c.recv(300)
        except OSError:
            got = b""
        check(got.startswith((b"HTTP/1.0 200", b"HTTP/1.1 200")) or got == b"", f"начатая загрузка дописывается без падения {got[:60]!r}")
        c.close()
        check(kinds(ev).count("photo") <= 1, "фото не дублируется")
    finally:
        rx.stop()


def test_photo_to_editor_size():
    i18n.set_language("ru")
    check(phone.editor_scale(800, 600, 2560, 1400) == 1.0 and phone.editor_scale(1000, 700, 2560, 1400) == 1.0,
          "снимок, который помещается, не уменьшается")
    k = phone.editor_scale(810, 1440, 2560, 1400)
    check(1.2 < k < 1.4, f"снимок 810 × 1440 на экране 2560 × 1400: масштаб в точках {k:.2f}")
    k = phone.editor_scale(4000, 3000, 1280, 720)
    check(4000 / k <= 1280 - phone.EDITOR_MARGIN[0] + 1 and 3000 / k <= 720 - phone.EDITOR_MARGIN[1] + 1 or k > 1,
          "большое фото вписывается вместе с панелями редактора")
    ctx = Ctx()
    win = phone_window(ctx)
    area = win._screen().availableGeometry()
    check(win.screen_pixels() == (round(win._screen().geometry().width() * win._screen().devicePixelRatio()),
                                  round(win._screen().geometry().height() * win._screen().devicePixelRatio())),
          f"окно знает размер своего экрана в физических пикселях {win.screen_pixels()}")
    check(win.receiver.screen == win.screen_pixels(), "приёмник передаёт его странице")
    ph = Client(win.receiver)
    _, page, key = ph.open_page()
    check(json.loads(re.search(r'id="cfg">(.*?)</script>', page, re.S).group(1))["screen"] == list(win.screen_pixels()),
          "страница из окна несёт размер экрана")
    st, ans = ph.post(key, jpeg(3000, 2000))
    settle(150)
    size, saved_dpr, ext, quality = ctx.autosaved[-1]
    dpr = ctx.opened_dpr[-1]   # the display scale of the editor; the saved file is made before it is set
    check(saved_dpr == 1.0, "автосохранение фото идёт до масштаба показа: файл с настоящими пикселями")
    fw, fh = fitted(3000, 2000)
    check(st == 200 and size.width() == fw and dpr >= 1 and fw / dpr <= area.width() - phone.EDITOR_MARGIN[0] + 1
          and fh / dpr <= area.height() - phone.EDITOR_MARGIN[1] + 1,
          f"фото 3000 × 2000 в редактор: {fw} × {fh}, масштаб {dpr:.2f}, помещается на экран {area.width()} × {area.height()}")
    check(ext == "jpg" and quality == phone_ui.PHOTO_QUALITY, "автосохранение фото: JPEG, качество 92, не PNG")
    check(win.received.text() == f"Получено фото: 1 ({fw} × {fh})", "в окне размер снимка")
    win.close()
    settle()


def test_receiving_window():
    i18n.set_language("ru")
    ctx = Ctx()
    win = phone_window(ctx)
    check(win.android.isVisible() and win.android.text().startswith("Android 17: разрешите браузеру доступ к локальной сети")
          and "Устройства поблизости" in win.android.text(), "рядом с кодом заметная строка про Android 17")
    ph = Client(win.receiver)
    _, _, key = ph.open_page()
    settle()
    check(not win.android.isVisible(), "телефон подключился: строка про Android 17 убрана")
    win._on_event("receiving", {"total": 1000})
    check(win.recv.isVisible() and win.recv.text() == "Получение фото… 0 %", "на ПК: «Получение фото… 0 %»")
    win._on_event("progress", {"percent": 47})
    check(win.recv.text() == "Получение фото… 47 %", "на ПК: «Получение фото… 47 %»")
    win._on_event("failed", {"error": "read"})
    check(win.recv.text().startswith("Фото не дошло") and win.recv.property("bad") == "true", "на ПК: ошибка видна")
    body = jpeg(640, 480)
    st, ans = ph.post(key, body)
    settle(150)
    check(st == 200 and not win.recv.isVisible() and win.received.text() == "Получено фото: 1 (640 × 480)",
          "фото получено: строка статуса убрана, в окне «Получено фото: 1 (640 × 480)»")
    win._on_event("receiving", {"total": 10})
    win.close()
    settle()
    win._on_event("progress", {"percent": 50})
    check(True, "событие получения после закрытия окна не падает")


def test_photo_files():
    from clipshot import hidpi
    base = tempfile.mkdtemp(prefix="clipsd-phone-save-")
    img = QImage(1200, 900, QImage.Format.Format_RGB32)
    for y in range(900):
        for x in range(0, 1200, 3):
            img.setPixelColor(x, y, QColor((x * 7 + y * 3) % 256, (x + y * 5) % 256, (x * 2) % 256))
    a, b = os.path.join(base, "a.jpg"), os.path.join(base, "b.jpg")
    check(hidpi.save_image(img, a, dict(appmod.DEFAULTS)) and hidpi.save_image(img, b, dict(appmod.DEFAULTS), 92)
          and os.path.getsize(b) > os.path.getsize(a), "качество JPEG можно задать (92 больше обычного)")
    clip = appmod.Clipshot(app)
    clip.config.update(auto_save=True, auto_save_dir=os.path.join(base, "snimki"), save_format="png")
    path = clip.autosave(img, ext="jpg", quality=92)
    check(path and path.endswith(".jpg") and os.path.getsize(path) > 1000, "Clipshot.autosave(ext='jpg'): файл .jpg")
    path2 = clip.autosave(img)
    check(path2 and path2.endswith(".png"), "обычный снимок по-прежнему по настройке (PNG)")


# --- решение владельца 21.11.2026 (02:15): окно приёма прячется само, приём живёт 2 минуты после фото -----------------

class NoteCtx(Ctx):
    def __init__(self):
        super().__init__()
        self.notes = []

    def notify(self, text):
        self.notes.append(text)

    def open_editor(self, image, origin):
        self.opened.append(image.size())
        ed = FakeEditor()
        self.editors.append(ed)
        return ed


def test_hide_after_photo():
    i18n.set_language("ru")
    real_show = phone_ui._show
    phone_ui._show = lambda c, t=None: _show_loop(c, t)
    try:
        ctx = NoteCtx()
        ctx.config[phone_ui.CONFIG_HIDE_NOTE] = True
        win = phone_ui.open_phone(ctx)
        settle()
        rx = win.receiver
        ph = Client(rx)
        _, _, key = ph.open_page()
        st, ans = ph.post(key, jpeg(500, 400))
        settle(150)
        check(st == 200 and len(ctx.opened) == 1 and win.hidden_for_photo and not win.isVisible() and rx.running,
              "фото получено: редактор открыт, окно приёма спрятано само, приём жив")
        check(ctx.notes == ["Фото получено. Можно снять ещё в течение 3 минут."], f"одно уведомление ({ctx.notes})")
        check(phone_ui.current_window() is win, "спрятанное окно считается открытым (для меню и выхода)")
        st, ans = ph.post(ans["key"], jpeg(300, 200))
        settle(150)
        check(st == 200 and len(ctx.opened) == 2 and len(ctx.notes) == 1 and not win.isVisible(),
              "второе фото: свой редактор, второго уведомления нет, окно не всплывает")
        settle(400)
        check(not win.isVisible() and len(ctx.notes) == 1, "если человек ничего не шлёт, ничего не всплывает")
        again = phone_ui.open_phone(ctx)
        settle()
        check(again is win and win.isVisible() and not win.hidden_for_photo and phone_ui._window is win,
              "пункт меню возвращает спрятанное окно, а не открывает второе")
        # окно снова спрятано следующим фото
        st, ans = ph.post(ans["key"], jpeg(200, 100))
        settle(150)
        check(not win.isVisible() and win.hidden_for_photo, "после следующего фото снова спрятано")
        # время вышло: приём закрылся, спрятанное окно закрывается целиком
        win._on_event("closed", {"reason": "idle"})
        settle(150)
        check(win.closing and phone_ui.current_window() is None and not rx.running, "3 минуты без фото: окно и приём закрыты полностью")
        # повторное открытие из меню во время закрытия: новое окно, старое не мешает
        win2 = phone_ui.open_phone(ctx)
        settle()
        check(win2 is not win and win2.receiver is not None and win2.receiver.running and phone_ui._window is win2,
              "повторное открытие из меню после закрытия: новое окно с новым кодом")
        win2.close()
        settle()
        check(phone_ui.current_window() is None, "новое окно закрыто: открытых окон нет")
        # два фото подряд до обработки (второе во время открытия первого редактора)
        ctx3 = NoteCtx()
        w3 = phone_window(ctx3)
        w3._on_event("photo", {"image": QImage(40, 30, QImage.Format.Format_RGB32), "count": 1})
        w3._on_event("photo", {"image": QImage(50, 30, QImage.Format.Format_RGB32), "count": 2})
        settle(100)
        check(len(ctx3.opened) == 2 and len(ctx3.notes) == 1 and w3.hidden_for_photo, "два фото подряд: два редактора, одно уведомление")
        w3.close()
        settle()
        # фото пришло, пока окно закрывают (спрятано и закрывается)
        ctx4 = NoteCtx()
        w4 = phone_window(ctx4)
        w4._on_event("photo", {"image": QImage(40, 30, QImage.Format.Format_RGB32), "count": 1})
        w4.close()
        w4._on_event("photo", {"image": QImage(40, 30, QImage.Format.Format_RGB32), "count": 2})
        settle(100)
        check(len(ctx4.opened) == 2 and ctx4.notes.count(tr("phone.photo_late")) == 1,
              "фото во время закрытия окна открыто в редакторе, одно уведомление «получено и открыто»")
    finally:
        phone_ui._show = real_show


def test_after_photo_ttl():
    check(phone.AFTER_PHOTO_TTL == 180 and phone.IDLE_TTL == 600, "после фото приём живёт 3 минуты от последнего фото, до первого фото 10")
    clock = Clock()
    rx, ev = receiver(clock=clock)
    try:
        ph = Client(rx)
        _, _, key = ph.open_page()
        clock.t += 300
        check(rx.tick() == phone.PAIRED, "до первого фото тишина 5 минут не закрывает приём")
        st, ans = ph.post(key, jpeg(50, 40))
        clock.t += 179
        check(rx.tick() == phone.PAIRED, "через 179 секунд после фото приём открыт")
        st2, ans2 = ph.post(ans["key"], jpeg(50, 40))
        clock.t += 181
        check(rx.tick() == phone.CLOSED and rx.reason == "idle", "через 3 минуты без фото приём закрыт полностью")
        st3, _ = ph.post(ans2["key"], jpeg(50, 40))
        check(st3 == 410, "телефон после этого: «Приём закрыт» (410)")
        rx.renew()
        _, _, key = ph.open_page()
        st, ans = ph.post(key, jpeg(50, 40))
        # загрузка, начатая до срока, доходит, хотя срок прошёл посреди неё
        ticket = rx._begin_upload("127.0.0.1", ans["key"])
        clock.t += 500
        check(ticket == "ok" and rx.tick() == phone.PAIRED, "срок вышел во время загрузки: приём не закрывается под ней")
        rx._deliver(QImage(10, 10, QImage.Format.Format_RGB32), "image/jpeg")
        res = {}
        rx._end_upload("127.0.0.1", True, res)
        check(res.get("key") and rx.tick() == phone.PAIRED, "загрузка дошла, срок отсчитывается заново")
        clock.t += 181
        check(rx.tick() == phone.CLOSED, "и через 3 минуты после неё приём закрыт")
    finally:
        rx.stop()
    i18n.set_language("ru")
    check("в течение 3 минут" in tr("phone.page_sent_more"), "страница после отправки: можно снять ещё в течение 3 минут")


# --- файл уходит как есть; метаданные, поворот и размер делает компьютер; очередь, повтор, время приёма -------------

def exif_jpeg(orientation: int, mark: bytes = b"SECRET-GPS-MARK-52.1N-4.3E", w=64, h=32) -> bytes:
    """JPEG 64 x 32 с угловыми цветными квадратами и EXIF: Orientation, описание-метка и GPS IFD (как с камеры)."""
    import struct
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor("#808080"))
    for (x, y), color in (((0, 0), "#ff0000"), ((w - 16, 0), "#00ff00"), ((0, h - 16), "#0000ff"), ((w - 16, h - 16), "#ffff00")):
        for yy in range(16):
            for xx in range(16):
                img.setPixelColor(x + xx, y + yy, QColor(color))
    base = jpeg_bytes_quality(img)
    desc = mark + b"\0"
    # TIFF: II, 42, offset 8; IFD0: 3 entries (ImageDescription, Orientation, GPSInfo), GPS IFD: 2 entries
    ifd0_off = 8
    n0 = 3
    desc_off = ifd0_off + 2 + n0 * 12 + 4
    gps_off = desc_off + len(desc) + (len(desc) % 2)
    ifd0 = struct.pack("<H", n0)
    ifd0 += struct.pack("<HHII", 0x010E, 2, len(desc), desc_off)
    ifd0 += struct.pack("<HHIHH", 0x0112, 3, 1, orientation, 0)
    ifd0 += struct.pack("<HHII", 0x8825, 4, 1, gps_off)
    ifd0 += struct.pack("<I", 0)
    gps = struct.pack("<H", 2) + struct.pack("<HHI4s", 0x0001, 2, 2, b"N\0\0\0") + struct.pack("<HHI4s", 0x0003, 2, 2, b"E\0\0\0") + struct.pack("<I", 0)
    tiff = b"II*\0" + struct.pack("<I", 8) + ifd0 + desc + (b"\0" if len(desc) % 2 else b"") + gps
    app1 = b"Exif\0\0" + tiff
    return base[:2] + b"\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1 + base[2:]


def jpeg_bytes_quality(img, q=95) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "JPEG", q)
    return bytes(ba)


def near(c1, c2, tol=40):
    return all(abs(a - b) <= tol for a, b in zip((c1.red(), c1.green(), c1.blue()), c2))


def test_exif_and_metadata():
    W, H = 64, 32
    centers = {(8, 8): (255, 0, 0), (W - 8, 8): (0, 255, 0), (8, H - 8): (0, 0, 255), (W - 8, H - 8): (255, 255, 0)}

    def where(o, x, y):   # the EXIF mapping of a raw pixel to the displayed one
        return {1: (x, y), 2: (W - 1 - x, y), 3: (W - 1 - x, H - 1 - y), 4: (x, H - 1 - y), 5: (y, x),
                6: (H - 1 - y, x), 7: (H - 1 - y, W - 1 - x), 8: (y, W - 1 - x)}[o]
    for o in range(1, 9):
        data = exif_jpeg(o)
        check(b"SECRET-GPS-MARK" in data and b"Exif" in data, f"EXIF {o}: проверочный файл несёт метаданные с GPS")
        img = phone.decode_image(data)
        want = (H, W) if o >= 5 else (W, H)
        ok = img is not None and (img.width(), img.height()) == want
        if ok:
            for (x, y), color in centers.items():
                dx, dy = where(o, x, y)
                ok = ok and near(img.pixelColor(dx, dy), color)
        check(ok, f"EXIF Orientation {o}: снимок повёрнут как показывает телефон ({want[0]} × {want[1]})")
    # метаданные не доходят ни до редактора, ни до файла
    data = exif_jpeg(6)
    out = phone.prepare_image(phone.decode_image(data), "orig", None)
    check(out is not None and not out.textKeys() and out.devicePixelRatio() == 1.0, "после приёма в изображении нет ключей метаданных")
    base = tempfile.mkdtemp(prefix="clipsd-phone-exif-")
    from clipshot import hidpi
    for ext in ("jpg", "png"):
        path = os.path.join(base, "saved." + ext)
        check(hidpi.save_image(out, path, dict(appmod.DEFAULTS), 92 if ext == "jpg" else None), f"сохранение {ext}")
        raw = open(path, "rb").read()
        check(b"SECRET-GPS-MARK" not in raw and b"Exif" not in raw and b"GPS" not in raw and b"52.1N" not in raw,
              f"сохранённый {ext}: ни GPS, ни EXIF, ни метки в файле")
    clip = appmod.Clipshot(app)
    clip.config.update(auto_save=True, auto_save_dir=os.path.join(base, "auto"))
    saved = clip.autosave(out, ext="jpg", quality=92)
    raw = open(saved, "rb").read()
    check(b"SECRET-GPS-MARK" not in raw and b"Exif" not in raw, "автосохранение фото: метаданных нет")
    # приём целиком: «Под экран компьютера» делает компьютер, «Оригинал» оставляет размер
    big = jpeg_bytes_quality(QImage(3200, 2400, QImage.Format.Format_RGB32))
    rx, ev = receiver(screen=(1920, 1080))
    try:
        ph = Client(rx)
        _, _, key = ph.open_page()
        st, ans = ph.post(key, big)
        img = [d for k, d in ev if k == "photo"][-1]["image"]
        info = [d for k, d in ev if k == "photo"][-1]["info"]
        check(st == 200 and (img.width(), img.height()) == (1440, 1080), f"режим «Под экран»: 3200 × 2400 стало {img.width()} × {img.height()} (экран 1920 × 1080)")
        check(info == {"mode": "fit", "src": (3200, 2400), "screen": (1920, 1080)}, f"в событии фото: режим, исходный размер и экран ({info})")
        check(rx.full_size is False, "по умолчанию «Под экран»: галочка «полный размер» выключена")
        st, ans = ph.post(ans["key"], big, extra={"X-ClipSD-Mode": "orig"})   # старый заголовок телефона игнорируется
        img = [d for k, d in ev if k == "photo"][-1]["image"]
        check(st == 200 and (img.width(), img.height()) == (1440, 1080), "заголовок режима от телефона игнорируется: решает компьютер")
        rx.full_size = True      # галочка в окне компьютера
        st, ans = ph.post(ans["key"], big)
        img = [d for k, d in ev if k == "photo"][-1]["image"]
        info = [d for k, d in ev if k == "photo"][-1]["info"]
        check(st == 200 and (img.width(), img.height()) == (3200, 2400) and info["mode"] == "orig", "галочка включена: полный размер, режим orig в событии")
        rx.full_size = False
        small = jpeg(300, 200)
        st, ans = ph.post(ans["key"], small)
        img = [d for k, d in ev if k == "photo"][-1]["image"]
        check((img.width(), img.height()) == (300, 200), "маленький снимок под экран не увеличивается")
        # HEIC: понятная ошибка
        ev.clear()
        st, a2 = ph.post(ans["key"], b"\0\0\0\x18ftypheic" + b"\0" * 40, ctype="image/heic")
        check(st == 415 and a2.get("error") == "heic" and ("failed", {"error": "heic"}) in ev, "HEIC по заголовку: 415 и ошибка heic")
        st, a3 = ph.post(ans["key"], b"\0\0\0\x18ftypheic" + b"\0" * 40, ctype="image/jpeg")
        check(st == 415 and a3.get("error") == "heic", "HEIC под видом JPEG: тоже ошибка heic, не тишина")
        # слишком много пикселей: отказ до раскодирования
        huge = QImage(9000, 7000, QImage.Format.Format_Grayscale8)
        huge.fill(128)
        st, a4 = ph.post(ans["key"], jpeg_bytes_quality(huge, 50))
        check(st == 415 and phone.MAX_PIXELS < 9000 * 7000, "63 Мп: отказ до раскодирования")
        del huge
        st, a5 = ph.post(ans["key"], b"x" * 100, ctype="text/plain")
        check(st == 415 and a5.get("error") == "type", "чужой тип: 415")
    finally:
        rx.stop()


def test_queue_dup_time():
    clock = Clock()
    rx, ev = receiver(clock=clock)
    try:
        ph = Client(rx)
        _, _, key = ph.open_page()
        ia, ib = "a" * 20, "b" * 20
        check(rx.time_left() == phone.IDLE_TTL, f"до первого фото приём открыт {phone.IDLE_TTL} секунд")
        clock.t += 100
        st, a1 = ph.post(key, jpeg(80, 60), extra={"X-ClipSD-Photo": ia})
        check(st == 200 and rx.time_left() == 180, "каждое фото продлевает приём на 3 минуты от последнего")
        clock.t += 170
        st, a2 = ph.post(a1["key"], jpeg(80, 60), extra={"X-ClipSD-Photo": ib})
        check(st == 200 and rx.photos == 2 and rx.time_left() == 180, "второе фото через 170 секунд: снова 3 минуты")
        # повтор после фона: телефон не получил ответ и шлёт то же фото со старым ключом
        n = kinds(ev).count("photo")
        r, data = ph.request("POST", f"/{rx.token}/photo", body=jpeg(80, 60), headers={
            "Content-Type": "image/jpeg", "X-ClipSD-Key": key, "X-ClipSD-Photo": ia, "Origin": f"http://{rx.authority}"})
        j = json.loads(data)
        check(r.status == 200 and j.get("dup") is True and kinds(ev).count("photo") == n and rx.photos == 2 and rx.bad == 0,
              "повтор того же фото: «уже получено», второго снимка нет, это не попытка подбора")
        st, a3 = ph.post(j["key"], jpeg(80, 60), extra={"X-ClipSD-Photo": "c" * 20})
        check(st == 200 and rx.photos == 3, "ключ из ответа на повтор рабочий: очередь идёт дальше")
        r, data = Client(rx, "127.0.0.2").request("POST", f"/{rx.token}/photo", body=jpeg(80, 60), headers={
            "Content-Type": "image/jpeg", "X-ClipSD-Key": "x", "X-ClipSD-Photo": ia, "Origin": f"http://{rx.authority}"})
        check(r.status != 200 or not json.loads(data).get("dup"), "чужое устройство «уже получено» не получает")
        # оставшееся время в ответе alive
        r, data = ph.request("GET", f"/{rx.token}/alive", headers={"X-ClipSD-Key": a3["key"], "X-ClipSD-Timing": "pick=120;send=800;kb=2100"})
        check(r.status == 200 and json.loads(data)["left"] == 180 and ("timing", {"text": "pick=120;send=800;kb=2100"}) in ev,
              "alive отдаёт оставшееся время и времена шагов с телефона")
        r, _ = ph.request("GET", f"/{rx.token}/alive", headers={"X-ClipSD-Key": a3["key"], "X-ClipSD-Timing": "<script>alert(1)</script>"})
        check(sum(1 for k, d in ev if k == "timing") == 1, "времена с недопустимыми знаками не принимаются")
        clock.t += 90
        r, data = ph.request("GET", f"/{rx.token}/alive", headers={"X-ClipSD-Key": a3["key"]})
        check(json.loads(data)["left"] == 90, "через 90 секунд осталось 90")
        # закончить во время очереди: «Закрыть» после последнего фото закрывает приём
        r, _ = ph.request("POST", f"/{rx.token}/close", headers={"X-ClipSD-Key": a3["key"], "Origin": f"http://{rx.authority}"})
        check(r.status == 200 and rx.state == phone.CLOSED and rx.reason == "phone", "«Отправить и закончить»: после очереди приём закрыт телефоном")
    finally:
        rx.stop()


# --- проба 6: ПК отвечает сразу после приёма байтов, раскодирование и открытие после ответа -----------------------------

def test_answer_before_processing():
    def slow_decode(data):
        time.sleep(3.0)
        return phone.decode_image(data)
    rx, ev = receiver(decode=slow_decode, screen=(1920, 1080))
    try:
        ph = Client(rx)
        _, _, key = ph.open_page()
        big = jpeg(2400, 1800)
        pid = "d" * 20
        t0 = time.monotonic()
        r, data = ph.request("POST", f"/{rx.token}/photo", body=big, headers={
            "Content-Type": "image/jpeg", "X-ClipSD-Key": key, "X-ClipSD-Photo": pid, "Origin": f"http://{rx.authority}"})
        dt = time.monotonic() - t0
        ans = json.loads(data)
        check(r.status == 200 and ans.get("key") and dt < 2.0 and "photo" not in kinds(ev),
              f"медленная обработка на ПК не задерживает ответ телефону ({dt:.2f} с, фото ещё не открыто)")
        # повтор того же фото, пока оно ещё обрабатывается: «уже получено», а не отказ и не цикл ошибок
        r2, data2 = ph.request("POST", f"/{rx.token}/photo", body=big, headers={
            "Content-Type": "image/jpeg", "X-ClipSD-Key": key, "X-ClipSD-Photo": pid, "Origin": f"http://{rx.authority}"})
        j2 = json.loads(data2)
        check(r2.status == 200 and j2.get("dup") is True and j2.get("key") and rx.photos == 1,
              "повтор с тем же id во время обработки: «уже получено» (ключ сменился, id совпал)")
        # следующее фото идёт сразу, не дожидаясь обработки первого
        t1 = time.monotonic()
        r3, data3 = ph.request("POST", f"/{rx.token}/photo", body=jpeg(100, 80), headers={
            "Content-Type": "image/jpeg", "X-ClipSD-Key": ans["key"], "X-ClipSD-Photo": "e" * 20, "Origin": f"http://{rx.authority}"})
        check(r3.status == 200 and time.monotonic() - t1 < 2.0 and rx.photos == 2, "второе фото принято сразу, очередь не стоит")
        # закрытие во время обработки: окно узнаёт о закрытии после фото
        r4, _ = ph.request("POST", f"/{rx.token}/close", headers={"X-ClipSD-Key": json.loads(data3)["key"], "Origin": f"http://{rx.authority}"})
        check(r4.status == 200 and rx.state == phone.CLOSED, "«закончить» во время обработки принято")
        check("closed" not in kinds(ev), "окно о закрытии ещё не знает: фото открываются")
        check(rx.wait_idle(10), "обработка закончилась")
        ks = kinds(ev)
        check(ks.count("photo") == 2 and ks.index("closed") > max(i for i, k in enumerate(ks) if k == "photo"),
              "оба фото открыты, и только потом пришло «закрыто»: спрятанное окно не теряет фото")
        photos = [d for k, d in ev if k == "photo"]
        check([d["count"] for d in photos] == [1, 2] and (photos[0]["image"].width(), photos[0]["image"].height()) == (1440, 1080),
              "фото открылись по порядку, первое уменьшено под экран 1920 × 1080")
    finally:
        rx.stop()
    # ошибка раскодирования после ответа: видна на ПК и при следующем alive на телефоне
    rx, ev = receiver(decode=lambda d: None)
    try:
        ph = Client(rx)
        _, _, key = ph.open_page()
        st, ans = ph.post(key, jpeg(200, 100))
        check(st == 200 and any(k == "failed" and d.get("error") == "decode" and d.get("count") == 1 for k, d in ev), "ПК не смог открыть фото уже после ответа: событие «не открылось»")
        r, data = ph.request("GET", f"/{rx.token}/alive", headers={"X-ClipSD-Key": ans["key"]})
        check(json.loads(data)["failed"] == [1], "телефон при следующем alive узнаёт номер фото, которое не открылось")
        r, data = ph.request("GET", f"/{rx.token}/alive", headers={"X-ClipSD-Key": ans["key"]})
        check(json.loads(data)["failed"] == [], "сообщается один раз")
    finally:
        rx.stop()
    # предел 20 фото: «закрыто» после последней обработки
    saved = phone.MAX_PHOTOS
    phone.MAX_PHOTOS = 1
    rx, ev = receiver(decode=slow_decode)
    try:
        ph = Client(rx)
        _, _, key = ph.open_page()
        r, data = ph.request("POST", f"/{rx.token}/photo", body=jpeg(100, 80), headers={
            "Content-Type": "image/jpeg", "X-ClipSD-Key": key, "Origin": f"http://{rx.authority}"})
        check(json.loads(data).get("limit") is True and "closed" not in kinds(ev), "последнее разрешённое фото: «предел» в ответе, окно ещё не закрыто")
        rx.wait_idle(10)
        ks = kinds(ev)
        check(ks.index("photo") < ks.index("closed"), "после последнего фото закрытие приходит после него")
    finally:
        phone.MAX_PHOTOS = saved
        rx.stop()


def test_full_size_checkbox():
    i18n.set_language("ru")
    ctx = Ctx()
    win = phone_window(ctx)
    check(win.full_box.text() == "Сохранять фото в полном размере" and not win.full_box.isChecked()
          and ctx.config.get(phone_ui.CONFIG_FULL) is False and win.receiver.full_size is False,
          "в окне одна галочка «Сохранять фото в полном размере», по умолчанию выключена (под экран)")
    ph = Client(win.receiver)
    _, _, key = ph.open_page()
    st, ans = ph.post(key, jpeg(3000, 2000))
    settle(100)
    check(ctx.autosaved[-1][0].width() == fitted(3000, 2000)[0], "выключена: снимок уменьшен под экран компьютера")
    win.full_box.setChecked(True)
    check(ctx.config[phone_ui.CONFIG_FULL] is True and ctx.saved >= 1 and win.receiver.full_size is True,
          "галочка запоминается в настройках и действует на следующее фото сразу")
    st, ans = ph.post(ans["key"], jpeg(3000, 2000))
    settle(100)
    check(ctx.autosaved[-1][0].width() == 3000, "включена: снимок в полном размере 3000 × 2000")
    check("полном размере" in win.received.text() or "3000 × 2000" in win.received.text(), "в строке получения итоговый размер")
    win.close()
    settle()
    win2 = phone_window(ctx)
    check(win2.full_box.isChecked() and win2.receiver.full_size is True, "в новом окне выбор помнится")
    win2.close()
    settle()
    for lang in i18n.LANGUAGES:
        i18n.set_language(lang)
        check(tr("phone.full_size") and not tr("phone.full_size").startswith("phone."), f"{lang}: подпись галочки переведена")
    i18n.set_language("ru")


def test_hint_block():
    i18n.set_language("ru")
    ctx = Ctx()
    win = phone_window(ctx)
    check(phone_ui.TROUBLE_AFTER_MS == 20_000 and win.trouble_timer.interval() == 20_000 and win.trouble_timer.isActive()
          and not win.hint.isVisible(), "таймер 20 секунд идёт с показа кода, подсказка закрыта")
    win.trouble_timer.stop()
    win.trouble_timer.setInterval(60)   # в тесте вместо 20 секунд
    win.trouble_timer.start()
    settle(250)
    text = win.hint.text()
    check(win.hint.isVisible() and win.qr_box.isVisible() and not win.step3.isVisible() and not win.vpn.isVisible(),
          "через 20 секунд без телефона подсказка раскрылась на месте, код остался виден")
    check(text.index("Android 17") < text.index("VPN") < text.index("Wi-Fi") and "Устройства поблизости → Разрешить. Затем отсканируйте код ещё раз." in text
          and "не удалось подключиться" in text.lower(), "пункты по порядку: Android 17, VPN, Wi-Fi и сетевой экран")
    check(win.height() <= 720 and win.height() >= need_height(win) and not any(w.isVisible() and w is not win and isinstance(w, phone_ui.ClipDialog)
                                                                              for w in QApplication.topLevelWidgets()),
          f"окно не выросло за экран 1280 × 720 ({win.height()} px), новых окон нет")
    win._on_event("connected", {"ip": "192.168.1.40"})
    check(not win.hint.isVisible() and win.step3.isVisible() and win.vpn.isVisible(), "телефон подключился: подсказка свёрнута")
    # гонка: подключение пришло раньше таймера: подсказка не раскрывается
    win._no_phone_yet()
    check(not win.hint.isVisible(), "подключение уже было: поздний таймер подсказку не раскрывает")
    win.close()
    settle()
    # гонка: раскрытие и подключение подряд
    win = phone_window(Ctx())
    win._no_phone_yet()
    check(win.hint.isVisible(), "раскрытие вручную")
    win._on_event("connected", {"ip": "192.168.1.41"})
    win._no_phone_yet()
    check(not win.hint.isVisible(), "подключение ровно в момент раскрытия: подсказка свёрнута и не возвращается")
    win.close()
    settle()
    # «Показать новый код»: подсказка закрывается и таймер идёт заново; истёк код: закрыта
    win = phone_window(Ctx())
    win._no_phone_yet()
    win.new_code()
    check(not win.hint.isVisible() and win.trouble_timer.isActive() and win.android.isVisible(), "«Показать новый код»: подсказка закрыта, таймер 20 секунд заново")
    win._no_phone_yet()
    win._on_event("closed", {"reason": "expired"})
    check(not win.hint.isVisible(), "код устарел: подсказка закрыта")
    win.close()
    settle()
    for lang in i18n.LANGUAGES:
        i18n.set_language(lang)
        w = phone_window(Ctx())
        w._no_phone_yet()
        settle(30)
        t = w.hint.text()
        check("phone." not in t.replace("phone.", "", 0) and not t.startswith("phone.") and "{" not in t and w.hint.isVisible()
              and w.height() <= 720 and w.height() >= need_height(w) and w.width() <= 1280,
              f"{lang}: подсказка на месте, окно целиком на экране 1280 × 720 ({w.width()} × {w.height()})")
        check(w.height() <= 700, f"{lang}: у окна с подсказкой запас не меньше 20 px до края экрана 720 ({w.height()})")
        w.close()
        settle()
    i18n.set_language("ru")


def test_obstacle_list():
    """Полный список помех в окне причин: что видит человек и одно-два действия (решение владельца 04:10)."""
    i18n.set_language("ru")
    win = phone_window(Ctx())
    for platform, firewall in (("linux", "ufw"), ("linux", ""), ("win32", None)):
        d = phone_ui.TroubleDialog(win, platform=platform, firewall=firewall if firewall is not None else None,
                                   which=which_all)
        texts = " ".join(lab.text() for lab in d.scroll.widget().findChildren(phone_ui.QLabel))
        need = {
            "Android 17": "Android 17" in texts and "Устройства поблизости" in texts and "Chrome 158" in texts and "Edge 157" in texts,
            "VPN и блокировщики (AdGuard)": "VPN" in texts and "AdGuard" in texts,
            "другая или гостевая Wi-Fi, мобильный интернет": "Гостевая сеть" in texts and "мобильные данные" in texts,
            "сетевой экран компьютера": "Разрешите приём на компьютере" in texts,
            "VPN на компьютере": "VPN на самом компьютере" in texts,
            "код устарел": "код устарел" in texts and "Показать новый код" in texts,
            "код открыт другим телефоном": "на другом телефоне" in texts,
            "20 фото": "20 фото" in texts,
            "файл больше 25 МБ": "25 МБ" in texts,
            "HEIC": "HEIC" in texts and "JPEG" in texts,
            "iPhone": "iPhone" in texts and "Safari" in texts,
            "компьютер не смог открыть фото": "не смог открыть фото" in texts,
        }
        missing = [k for k, v in need.items() if not v]
        check(not missing, f"окно причин ({platform}, {firewall}): есть все помехи, нет пропущенных {missing}")
        if platform == "win32":
            check("Разрешить заново" in texts or d.allow_btn.text() == "Разрешить заново", "Windows: «Разрешить заново»")
        d.close()
    win.close()
    settle()


# --- проверка 1.33.0: Б1 зависание, Б2 потеря фото, В1 медленные соединения, В2 обновление, В3 размер фото ---------------

def _watchdog(seconds, label):
    """Зависание теста = зависание программы: сторож снимает процесс со стеком всех потоков."""
    import faulthandler
    done = threading.Event()

    def guard():
        if not done.wait(seconds):
            print(f"FAIL ЗАВИСАНИЕ: {label}")
            faulthandler.dump_traceback(all_threads=True)
            os._exit(3)
    t = threading.Thread(target=guard, daemon=True)
    t.start()
    return done


def test_idle_close_does_not_deadlock():
    """Б1: закрытие по простою (таймер окна) и входящие соединения телефона: ни обработчик окна внутри замка приёмника,
    ни зависание stop()."""
    import threading as th
    i18n.set_language("ru")
    guard = _watchdog(60, "закрытие по простою с входящими соединениями")
    NOW = [1000.0]
    ctx = NoteCtx()
    win = phone_ui.PhoneDialog(ctx, None, candidates=LOOP, firewall="",
                               receiver_cls=lambda host, **kw: phone.Receiver("127.0.0.1", **dict(kw, clock=lambda: NOW[0])))
    win.start()
    win.open_centered()
    settle()
    rx = win.receiver
    ph = Client(rx)
    _, _, key = ph.open_page()
    st, ans = ph.post(key, jpeg(200, 100))
    settle(150)
    check(st == 200 and win.hidden_for_photo, "фото принято, окно спрятано")
    inside = []
    real = win._on_event

    def watched(kind, data):
        # окно не должно работать внутри замка приёмника и внутри tick()
        inside.append((kind, rx._lock._is_owned(), win._in_tick))
        real(kind, data)
    win._in_tick = False
    win.bridge.event.disconnect()
    win.bridge.event.connect(watched, Qt.ConnectionType.QueuedConnection)
    real_tick = rx.tick

    def tick():
        win._in_tick = True
        try:
            return real_tick()
        finally:
            win._in_tick = False
    rx.tick = tick
    stop_hammer = th.Event()
    answers = []

    def hammer():   # страница телефона спрашивает /alive; здесь чаще, чтобы попасть в момент закрытия
        while not stop_hammer.is_set():
            try:
                r, _ = ph.request("GET", f"/{rx.token}/alive", headers={"X-ClipSD-Key": ans["key"]})
                answers.append(r.status)
            except OSError:
                answers.append(0)
    threads = [th.Thread(target=hammer, daemon=True) for _ in range(3)]
    for t in threads:
        t.start()
    t_wait = time.monotonic()
    while 200 not in answers and time.monotonic() - t_wait < 3:
        time.sleep(0.01)
    NOW[0] += phone.AFTER_PHOTO_TTL + 1
    t0 = time.monotonic()
    win._tick()                          # так закрывает приём таймер окна
    settle(400)
    stop_hammer.set()
    for t in threads:
        t.join(5)
    check(time.monotonic() - t0 < 5 and not rx.running and win.closing, "закрытие по простою при потоке /alive: окно и приём закрыты, без зависания")
    closed = [x for x in inside if x[0] == "closed"]
    check(closed and all(not locked and not in_tick for _, locked, in_tick in closed),
          "событие «закрыто» дошло до окна из очереди: не внутри tick() и не под замком приёмника")
    check(200 in answers, f"телефону отвечали до закрытия ({len(answers)} запросов, коды {sorted(set(answers))})")
    guard.set()


class _GatedReceiver(phone.Receiver):
    GATE = threading.Event()

    def __init__(self, *a, **kw):
        kw["decode"] = self._gated
        super().__init__(*a, **kw)

    def _gated(self, data):
        _GatedReceiver.GATE.wait(20)
        return phone.decode_image(data)


def test_photo_not_lost_when_window_closed():
    """Б2: принятое фото открывается, даже если окно приёма закрыто до конца раскодирования (в обоих порядках, при
    «закончить» и при выходе из программы); телефон удаляет свою копию только после подтверждения компьютера."""
    i18n.set_language("ru")
    guard = _watchdog(90, "принятое фото и закрытие окна")
    for label, close_first in (("окно закрыто, потом раскодирование закончилось", True),
                               ("раскодирование закончилось, потом окно закрыто", False)):
        _GatedReceiver.GATE.clear()
        ctx = NoteCtx()
        win = phone_ui.PhoneDialog(ctx, None, candidates=LOOP, firewall="", receiver_cls=_GatedReceiver)
        win.start()
        win.open_centered()
        settle()
        rx = win.receiver
        ph = Client(rx)
        _, _, key = ph.open_page()
        pid = "a1" * 10
        r, data = ph.request("POST", f"/{rx.token}/photo", body=jpeg(800, 600), headers={
            "Content-Type": "image/jpeg", "X-ClipSD-Key": key, "X-ClipSD-Photo": pid, "Origin": f"http://{rx.authority}"})
        check(r.status == 200, f"{label}: телефону ответили «принято»")
        if close_first:
            win.close()
            settle(200)
            _GatedReceiver.GATE.set()
        else:
            _GatedReceiver.GATE.set()
            rx.wait_idle(10)
            win.close()
        rx.wait_idle(10)
        settle(300)
        check(len(ctx.opened) == 1, f"{label}: фото открыто в редакторе ({len(ctx.opened)}), не потеряно")
        check(rx.confirmations() == {"done": [pid], "lost": []}, f"{label}: компьютер подтвердил открытие фото {pid[:4]}...")
    # окно закрыто, фото ещё раскодируется: уведомление «получено и открыто», а не тишина
    _GatedReceiver.GATE.clear()
    ctx = NoteCtx()
    win = phone_ui.PhoneDialog(ctx, None, candidates=LOOP, firewall="", receiver_cls=_GatedReceiver)
    win.start()
    win.open_centered()
    settle()
    rx = win.receiver
    ph = Client(rx)
    _, _, key = ph.open_page()
    r, data = ph.request("POST", f"/{rx.token}/photo", body=jpeg(300, 200), headers={
        "Content-Type": "image/jpeg", "X-ClipSD-Key": key, "Origin": f"http://{rx.authority}"})
    win.close()
    settle(200)
    _GatedReceiver.GATE.set()
    rx.wait_idle(10)
    settle(300)
    check(len(ctx.opened) == 1 and tr("phone.photo_late") in ctx.notes, "окно закрыто: фото открыто и есть уведомление «получено и открыто»")
    # выход из программы, пока фото раскодируется: оно доставляется до закрытия
    _GatedReceiver.GATE.clear()
    ctx = NoteCtx()
    win = phone_ui.PhoneDialog(ctx, None, candidates=LOOP, firewall="", receiver_cls=_GatedReceiver)
    win.start()
    win.open_centered()
    settle()
    rx = win.receiver
    ph = Client(rx)
    _, _, key = ph.open_page()
    r, data = ph.request("POST", f"/{rx.token}/photo", body=jpeg(300, 200), headers={
        "Content-Type": "image/jpeg", "X-ClipSD-Key": key, "Origin": f"http://{rx.authority}"})
    threading.Timer(0.3, _GatedReceiver.GATE.set).start()
    phone_ui.stop_all()
    check(len(ctx.opened) == 1 and not rx.running, f"выход из программы во время раскодирования: фото открыто до закрытия приёма (редакторов {len(ctx.opened)}, приём работает: {rx.running})")
    win.close()
    settle()
    # ошибка раскодирования после ответа: видна на ПК, телефон узнаёт, свою копию удалит
    ctx = NoteCtx()
    win = phone_ui.PhoneDialog(ctx, None, candidates=LOOP, firewall="",
                               receiver_cls=lambda host, **kw: phone.Receiver("127.0.0.1", **dict(kw, decode=lambda d: None)))
    win.start()
    win.open_centered()
    settle()
    rx = win.receiver
    ph = Client(rx)
    _, _, key = ph.open_page()
    pid = "b2" * 10
    r, data = ph.request("POST", f"/{rx.token}/photo", body=jpeg(100, 80), headers={
        "Content-Type": "image/jpeg", "X-ClipSD-Key": key, "X-ClipSD-Photo": pid, "Origin": f"http://{rx.authority}"})
    rx.wait_idle(10)
    settle(200)
    check(any("не смог его открыть" in n for n in ctx.notes) and rx.confirmations() == {"done": [], "lost": [pid]},
          "компьютер не смог открыть фото: уведомление на ПК, телефону сказано (он удалит копию и сообщит)")
    win.close()
    settle()
    guard.set()


def test_slow_connections_do_not_block_phone():
    """В1: медленные неопознанные соединения (по байту раз в секунду с трёх адресов) не мешают телефону."""
    saved = (phone.HEADER_DEADLINE, phone.SOCKET_TIMEOUT)
    phone.HEADER_DEADLINE = 2
    guard = _watchdog(60, "медленные соединения")
    rx, ev = receiver(network="127.0.0.0/8")
    stop = threading.Event()
    dropped = []

    def trickler(src):
        try:
            sock = socket.socket()
            sock.settimeout(10)
            sock.bind((src, 0))
            sock.connect(("127.0.0.1", rx.port))
        except OSError:
            dropped.append("connect")
            return
        payload = b"GET /zzzzzzzz HTTP/1.1\r\nHost: x\r\n"
        i, t0 = 0, time.monotonic()
        try:
            while not stop.is_set():
                sock.send(payload[i % len(payload):i % len(payload) + 1])
                i += 1
                stop.wait(0.5)
        except OSError:
            dropped.append(round(time.monotonic() - t0, 1))
        finally:
            sock.close()
    try:
        ths = [threading.Thread(target=trickler, args=(f"127.0.0.{n}",), daemon=True) for n in (2, 3, 4) for _ in range(3)]
        for t in ths:
            t.start()
            time.sleep(0.03)
        wait_for(lambda: len(rx._conns) >= 9, 5)
        r, _, key = Client(rx, "127.0.0.9").open_page()
        check(r.status == 200 and key, "9 медленных соединений с 3 адресов: телефон открывает код сразу")
        wait_for(lambda: len(dropped) >= 9 and len(rx._conns) == 0, 20)   # the header deadline (2 s here) drops them
        with rx._lock:
            left = len(rx._conns)
        check(len(dropped) == 9 and max(d for d in dropped if isinstance(d, float)) < 8.0 and left == 0,
              f"запрос по байту не держит место: все 9 сброшены за срок на заголовки ({sorted(dropped)}), открытых {left}")
        stop.set()
        # больше мест, чем общий предел: новому всегда находится место (самое старое ожидающее уступает)
        stop.clear()
        dropped.clear()
        phone.HEADER_DEADLINE = 30
        many = [threading.Thread(target=trickler, args=(f"127.0.0.{n}",), daemon=True) for n in range(10, 19) for _ in range(3)]
        for t in many:
            t.start()
            time.sleep(0.01)
        wait_for(lambda: len(rx._conns) >= 20, 5)
        with rx._lock:
            n_conn = len(rx._conns)
        r2, _, _ = Client(rx, "127.0.0.9").open_page()
        check(n_conn <= phone.MAX_CONNECTIONS and r2.status == 200,
              f"27 медленных соединений при пределе {phone.MAX_CONNECTIONS}: открыто {n_conn}, телефон всё равно получает 200")
    finally:
        stop.set()
        phone.HEADER_DEADLINE, phone.SOCKET_TIMEOUT = saved
        rx.stop()
        guard.set()


def test_quit_blocker_counts_phone_window():
    """В2: окно приёма (видимое или спрятанное после фото) и раскодируемое фото считаются «занято» для обновления."""
    import types
    from clipshot import update_prompt
    i18n.set_language("ru")
    ctx = types.SimpleNamespace(config=dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True), editors=[], selector=None,
                                insert_target=None, save_config=lambda: None, autosave=lambda *a, **k: None,
                                open_editor=lambda *a: None, notify=lambda t: None)
    ctx.capture_pending = lambda: False
    ctx.quit_blocker = types.MethodType(appmod.Clipshot.quit_blocker, ctx)
    check(ctx.quit_blocker() == "", "окна приёма нет: можно закрыться")
    win = phone_ui.PhoneDialog(ctx, None, candidates=LOOP, firewall="",
                               receiver_cls=lambda host, **kw: phone.Receiver("127.0.0.1", **kw))
    win.start()
    win.open_centered()
    settle()
    check(ctx.quit_blocker() == "phone" and update_prompt.busy_reason(ctx) == "phone",
          "окно приёма открыто: quit_blocker и busy_reason говорят «phone», обновление ждёт")
    win.hide()
    win.hidden_for_photo = True
    check(ctx.quit_blocker() == "phone", "окно спрятано после фото, приём открыт: всё ещё «phone»")
    win.close()
    settle(200)
    check(ctx.quit_blocker() == "", "окно закрыто, ничего не раскодируется: можно закрыться")
    _GatedReceiver.GATE.clear()
    win = phone_ui.PhoneDialog(ctx, None, candidates=LOOP, firewall="", receiver_cls=_GatedReceiver)
    win.start()
    win.open_centered()
    settle()
    rx = win.receiver
    ph = Client(rx)
    _, _, key = ph.open_page()
    ph.request("POST", f"/{rx.token}/photo", body=jpeg(100, 80), headers={
        "Content-Type": "image/jpeg", "X-ClipSD-Key": key, "Origin": f"http://{rx.authority}"})
    win.close()
    settle(200)
    check(ctx.quit_blocker() == "phone", "окно закрыто, но принятое фото ещё раскодируется: «phone»")
    _GatedReceiver.GATE.set()
    rx.wait_idle(10)
    settle(300)
    check(ctx.quit_blocker() == "", "фото открыто: можно закрыться")


def test_photo_keeps_its_pixels():
    """В3: фото с телефона не уменьшается по масштабу показа: «Размер снимка: как на экране» его не трогает; с галочкой
    «полный размер» файл 4000 x 3000, без неё размер под экран (его даёт компьютер)."""
    import types
    from PyQt6.QtGui import QImageReader
    base = tempfile.mkdtemp(prefix="clipsd-phone-size-")
    for mode in ("full", "screen"):
        for full_ticked in (True, False):
            ctx = types.SimpleNamespace()
            ctx.config = dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True, snapshot_size=mode, auto_save=True,
                              auto_save_dir=os.path.join(base, f"{mode}-{full_ticked}"), phone_full_size=full_ticked)
            ctx.save_config = lambda: None
            ctx.editors = []
            ctx.opened = []
            ctx.open_editor = lambda image, origin, c=ctx: c.opened.append(image) or types.SimpleNamespace()
            ctx.notify = lambda t: None
            ctx.snapshot_path = types.MethodType(appmod.Clipshot.snapshot_path, ctx)
            ctx.autosave = types.MethodType(appmod.Clipshot.autosave, ctx)
            win = phone_ui.PhoneDialog(ctx, None, candidates=LOOP, firewall="",
                                       receiver_cls=lambda host, **kw: phone.Receiver("127.0.0.1", **kw))
            win.start()
            win.open_centered()
            settle()
            rx = win.receiver
            check(rx.full_size is full_ticked, f"галочка {full_ticked} дошла до приёмника")
            ph = Client(rx)
            _, _, key = ph.open_page()
            st, ans = ph.post(key, jpeg(4000, 3000))
            settle(300)
            files = os.listdir(ctx.config["auto_save_dir"])
            sz = QImageReader(os.path.join(ctx.config["auto_save_dir"], files[0])).size()
            sw, sh = win.screen_pixels()
            want = (4000, 3000) if full_ticked else fitted(4000, 3000, (sw, sh))
            check((sz.width(), sz.height()) == want and ctx.opened[0].devicePixelRatio() >= 1.0,
                  f"«Размер снимка: {mode}», галочка {full_ticked}: файл {sz.width()} × {sz.height()} (ждём {want[0]} × {want[1]})")
            win.close()
            settle()
    # сохранение и копирование из редактора идут тем же путём: настоящий редактор
    clip = appmod.Clipshot(app)
    clip.config.update(snapshot_size="screen", auto_save=True, auto_save_dir=os.path.join(base, "editor"), theme_chosen=True, tour_done=True)
    image = QImage(3000, 2000, QImage.Format.Format_RGB32)
    image.fill(QColor("#3366cc"))
    saved = clip.autosave(image, ext="jpg", quality=92)
    image.setDevicePixelRatio(3.0)
    editor = clip.open_editor(image, None)
    editor.autosave_path = saved
    editor.phone_photo = True
    check(editor.export_config()["snapshot_size"] == "full" and clip.config["snapshot_size"] == "screen",
          "редактор фото с телефона сохраняет и копирует без уменьшения по масштабу показа (настройки не тронуты)")
    editor.canvas.modified = True
    editor.copy_to_clipboard()
    got = QGuiApplication.clipboard().image()
    check(got.width() == 3000 and got.height() == 2000, f"копирование из редактора: {got.width()} × {got.height()}, не 1000 × 667")
    settle(300)
    editor.hide()


def test_no_take_another_note_when_quitting():
    """Р2-М5: программа закрывается, пока фото раскодируется: фото доставлено, но уведомления «можно снять ещё в течение
    3 минут» нет (и когда приём уже закрыт, тоже)."""
    i18n.set_language("ru")
    _GatedReceiver.GATE.clear()
    ctx = NoteCtx()
    win = phone_ui.PhoneDialog(ctx, None, candidates=LOOP, firewall="", receiver_cls=_GatedReceiver)
    win.start()
    win.open_centered()
    settle()
    phone_ui._window = win
    rx = win.receiver
    ph = Client(rx)
    _, _, key = ph.open_page()
    ph.request("POST", f"/{rx.token}/photo", body=jpeg(300, 200), headers={
        "Content-Type": "image/jpeg", "X-ClipSD-Key": key, "Origin": f"http://{rx.authority}"})
    threading.Timer(0.3, _GatedReceiver.GATE.set).start()
    phone_ui.stop_all()
    check(len(ctx.opened) == 1, "выход во время раскодирования: фото всё равно открыто")
    check(not any("снять ещё" in n for n in ctx.notes) and ctx.notes == [], f"при выходе нет уведомления «можно снять ещё» ({ctx.notes})")
    # приём уже закрыт, фото доходит позже: тоже без обещания
    _GatedReceiver.GATE.clear()
    ctx = NoteCtx()
    win = phone_ui.PhoneDialog(ctx, None, candidates=LOOP, firewall="", receiver_cls=_GatedReceiver)
    win.start()
    win.open_centered()
    settle()
    rx = win.receiver
    ph = Client(rx)
    _, _, key = ph.open_page()
    ph.request("POST", f"/{rx.token}/photo", body=jpeg(300, 200), headers={
        "Content-Type": "image/jpeg", "X-ClipSD-Key": key, "Origin": f"http://{rx.authority}"})
    rx._close("phone")
    _GatedReceiver.GATE.set()
    rx.wait_idle(10)
    settle(300)
    check(len(ctx.opened) == 1 and not any("снять ещё" in n for n in ctx.notes),
          f"приём закрыт до конца раскодирования: фото открыто, обещания «снять ещё» нет ({ctx.notes})")
    settle()


for fn in (test_qr, test_token_and_page, test_size_type_origin, test_expiry_idle_lock_limit, test_connections_and_stop,
           test_network_rules, test_page_render, test_window_flow, test_window_states, test_trouble_dialog,
           test_menus, test_languages, test_new_name, test_page_new_flow, test_phone_close, test_races, test_firewall_allow_argv,
           test_allow_step, test_allow_races, test_trouble_allow, test_allow_again_windows, test_receive_status_events, test_fresh_key,
           test_close_during_upload, test_photo_to_editor_size, test_receiving_window, test_photo_files, test_hide_after_photo, test_after_photo_ttl, test_exif_and_metadata, test_queue_dup_time, test_answer_before_processing, test_full_size_checkbox, test_hint_block, test_obstacle_list, test_idle_close_does_not_deadlock,
           test_photo_not_lost_when_window_closed, test_slow_connections_do_not_block_phone, test_quit_blocker_counts_phone_window,
           test_photo_keeps_its_pixels, test_no_take_another_note_when_quitting):
    try:
        fn()
    except Exception as exc:     # noqa: BLE001
        import traceback
        traceback.print_exc()
        check(False, f"{fn.__name__}: исключение {exc!r}")

# в конце нет живых потоков приёмника (сервер, обработка фото), у программы при выходе тоже: stop_all закрывает и ждёт
phone_ui.stop_all()
alive = [t.name for t in threading.enumerate() if t.name.startswith("clipsd-phone")]
check(wait_for(lambda: not [t for t in threading.enumerate() if t.name.startswith("clipsd-phone")], 10),
      f"после всех проверок и stop_all нет живых потоков приёмника ({alive})")
print(f"ИТОГ: проверок {checks[0]}, провалено: {len(failures)}")
sys.exit(1 if failures else 0)

