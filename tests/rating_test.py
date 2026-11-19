# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Окно «Оценить ClipSD» (1.32, feedback.py): правила показа, что уходит в приёмник, очередь без интернета
и ответы приёмника (локальный сервер: 201, 200 повтор, 400, 422, 429, 500, редирект, нет сервера),
«отправлено» только при 2xx, окна (звёзды, предел 1000 знаков, «Позже», «Больше не показывать», крестик),
окно после отправки (каталоги из одного списка, «Сообщить о проблеме» на GitHub у 1-3 звёзд),
«Вы уже оценили ClipSD» из меню после отправки (второй оценки нет), а после отказа приёмника или кончившихся
попыток пункт меню снова даёт оценить (П1 проверки 1.32),
пункты «Оценить ClipSD» в меню значка и в меню «?» редактора, счётчики снимков и окно по правилам в приложении.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/rating_test.py
"""
import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
_cfg = os.path.join(tempfile.mkdtemp(prefix="clipsd-rate-"), "screen.json")
with open(_cfg, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1600, "height": 1000,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _cfg
os.environ.setdefault("CLIPSD_LANG", "ru")

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QColor, QImage, QPixmap
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
import clipshot  # noqa: E402
from clipshot import app as appmod, feedback, i18n  # noqa: E402
from clipshot.i18n import tr  # noqa: E402

failures = []
checks = [0]
DAY = 86400


def check(cond, msg):
    checks[0] += 1
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def settle(n=6):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(15)


def wait(cond, seconds=10):
    end = time.time() + seconds
    while not cond() and time.time() < end:
        app.processEvents()
        QTest.qWait(20)
    return cond()


def tmpdir():
    return Path(tempfile.mkdtemp(prefix="clipsd-rate-q-", dir=os.environ.get("TMPDIR")))


# ---------------------------------------------------------------- локальный приёмник

class Receiver:
    """Приёмник на 127.0.0.1: отвечает кодами из очереди self.codes (последний повторяется), запоминает запросы."""

    def __init__(self):
        self.codes = [201]
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                outer.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
                code = outer.codes.pop(0) if len(outer.codes) > 1 else outer.codes[0]
                self.send_response(code)
                if code in (301, 302):
                    self.send_header("Location", "http://127.0.0.1:9/login")
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok":true}' if 200 <= code < 300 else b'{"ok":false}')

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/rate"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def sender(self, payload):
        return feedback.post_rating(payload, self.url, timeout=5)


rx = Receiver()
feedback.RATE_URL = rx.url          # окна и очередь без явного sender тоже идут в локальный приёмник


def closed_port_url():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}/rate"


# ---------------------------------------------------------------- правила показа

def test_rules():
    now = 1_800_000_000
    c = {}
    for d in range(6):
        feedback.note_use_day(c, now + d * DAY)
        feedback.note_use_day(c, now + d * DAY + 60)       # второй запуск в тот же день не считается
    check(c["usage_days"] == 6, f"дни работы: один на календарный день ({c.get('usage_days')})")
    for _ in range(25):
        feedback.note_capture(c, now + 5 * DAY)
    check(c["capture_count"] == 25, "снимки считаются")
    check(not feedback.should_show_rating(c, now + 5 * DAY), "6 дней и 25 снимков: окна нет")
    feedback.note_capture(c, now + 6 * DAY)                   # снимок в новый день = день работы
    check(c["usage_days"] == 7 and feedback.should_show_rating(c, now + 6 * DAY), "7 дней и 26 снимков: окно есть")
    c2 = {"usage_days": 30, "capture_count": 19}
    check(not feedback.should_show_rating(c2, now), "30 дней, 19 снимков: окна нет")
    c2["capture_count"] = 20
    check(feedback.should_show_rating(c2, now), "30 дней, 20 снимков: окно есть")
    feedback.rating_shown(c2)
    feedback.rating_later(c2, now)
    check(not feedback.should_show_rating(c2, now + 29 * DAY), "«Позже»: 29 дней окна нет")
    check(feedback.should_show_rating(c2, now + 30 * DAY + 1), "«Позже»: через 30 дней снова")
    feedback.rating_shown(c2)
    feedback.rating_shown(c2)
    check(not feedback.should_show_rating(c2, now + 99 * DAY), "больше 3 показов не бывает")
    c3 = {"usage_days": 30, "capture_count": 99}
    feedback.rating_never(c3)
    check(not feedback.should_show_rating(c3, now), "«Больше не показывать»: окна нет")
    c4 = {"usage_days": 30, "capture_count": 99}
    feedback.rating_submitted(c4)
    check(not feedback.should_show_rating(c4, now) and not c4.get("rating_sent"),
          "«Отправить»: окна нет, «отправлено» до ответа приёмника не отмечается")
    feedback.rating_delivered(c4)
    check(not feedback.should_show_rating(c4, now) and c4["rating_sent"], "приёмник подтвердил: «отправлено»")


# ---------------------------------------------------------------- что уходит

def test_payload():
    text = "Отлично!\r\nПишите: ivan.petrov@mail.example.com\x07 " + "я" * 2000
    p = feedback.make_payload(4, text, 3456, lang="de")
    check(set(p) == {"stars", "review", "lang", "version", "platform", "key", "fill_ms"},
          f"в оценке только звёзды, отзыв, язык, версия, платформа, номер оценки, время окна: {sorted(p)}")
    check(p["stars"] == 4 and p["lang"] == "de" and p["version"] == clipshot.__version__, "поля оценки")
    check(p["platform"] in ("linux", "windows", "macos", "other"), f"платформа {p['platform']}")
    check(len(p["review"]) == feedback.MAX_REVIEW, f"отзыв не длиннее 1000 знаков ({len(p['review'])})")
    check("@" not in p["review"] and "<e-mail>" in p["review"] and "\x07" not in p["review"] and "\r" not in p["review"],
          "почта в отзыве заменена, управляющих знаков нет")
    check(len(p["key"]) == 32 and int(p["key"], 16) >= 0, "номер оценки: случайные 32 hex")
    check(feedback.make_payload(5, "", 0)["key"] != p["key"], "у каждой оценки свой номер")
    for bad in (0, 6):
        try:
            feedback.make_payload(bad, "", 0)
            check(False, f"звёзды {bad} не принимаются")
        except ValueError:
            check(True, f"звёзды {bad} не принимаются")
    check(feedback.classify(201) == "sent" and feedback.classify(200) == "sent", "2xx: отправлено")
    check(all(feedback.classify(c) == "retry" for c in (0, 302, 429, 500, 503)), "нет сети, редирект, 429, 5xx: позже")
    check(all(feedback.classify(c) == "rejected" for c in (400, 403, 413, 415, 422)), "остальные 4xx: не принято")


# ---------------------------------------------------------------- очередь и приёмник

def queue_files(d):
    return sorted(Path(d).glob("*.json"))


def test_send_and_queue():
    d = tmpdir()
    # 201: отправлено сразу, очередь пуста, запрос как у программы (без Origin, ключ повтора = номер оценки)
    rx.codes, rx.requests = [201], []
    cfg = {}
    dl = feedback.submit(cfg, 5, "Хорошо", 2500, sender=rx.sender, directory=d, background=False)
    check(dl.state == "sent" and feedback.status_key(dl) == "feedback.thanks_text", "201: «Оценка отправлена»")
    check(cfg.get("rating_sent") and cfg.get("rating_disabled"), "после «Отправить» окно больше не предлагается")
    check(queue_files(d) == [], "201: очередь пуста")
    req = rx.requests[-1]
    body = json.loads(req["body"])
    h = {k.lower(): v for k, v in req["headers"].items()}
    check(h.get("idempotency-key") == body["key"], "заголовок Idempotency-Key = номер оценки")
    check("origin" not in h and h.get("content-type", "").startswith("application/json"), "без Origin, JSON")
    check(h.get("user-agent") == f"ClipSD/{clipshot.__version__}", "в заголовке только название и версия программы")
    check(body["review"] == "Хорошо" and body["fill_ms"] == 2500, "отзыв и время окна дошли")

    # 200 (повтор той же оценки у приёмника) тоже «отправлено»
    rx.codes = [200]
    dl = feedback.submit({}, 3, "", 2000, sender=rx.sender, directory=d, background=False)
    check(dl.state == "sent", "200 (повтор): отправлено")

    # 500: в очереди; паузы 1 час и сутки; номер оценки тот же; после 3 попыток удаляется
    rx.codes, rx.requests = [500], []
    t0 = time.time()
    dl = feedback.submit({}, 2, "Падает", 3000, sender=rx.sender, directory=d, background=False)
    check(dl.state == "queued" and feedback.status_key(dl) == "feedback.thanks_queued", "500: «отправит, когда появится связь»")
    files = queue_files(d)
    check(len(files) == 1, "500: оценка в очереди")
    item = json.loads(files[0].read_text(encoding="utf-8"))
    check(item["attempts"] == 1 and abs(item["next_try_ts"] - (t0 + 3600)) < 30, "после 1-й неудачи пауза час")
    check(feedback.flush_outbox(rx.sender, d, now=t0 + 60) == 0 and len(rx.requests) == 1, "до конца паузы не шлёт")
    feedback.flush_outbox(rx.sender, d, now=t0 + 3601)
    item = json.loads(queue_files(d)[0].read_text(encoding="utf-8"))
    check(len(rx.requests) == 2 and item["attempts"] == 2, "2-я попытка через час")
    keys = {json.loads(r["body"])["key"] for r in rx.requests}
    check(len(keys) == 1, "повторы с тем же номером оценки")
    feedback.flush_outbox(rx.sender, d, now=t0 + 3601 + DAY - 60)
    check(len(rx.requests) == 2, "3-я попытка не раньше чем через сутки")
    feedback.flush_outbox(rx.sender, d, now=t0 + 3601 + DAY + 1)
    check(len(rx.requests) == 3 and queue_files(d) == [], "после 3 попыток оценка удалена из очереди")

    # 500, затем 201 из очереди: отправлено, файл удалён
    rx.codes, rx.requests = [500, 201], []
    feedback.submit({}, 4, "", 2000, sender=rx.sender, directory=d, background=False)
    sent = feedback.flush_outbox(rx.sender, d, now=time.time() + 3601)
    check(sent == 1 and queue_files(d) == [], "очередь: при следующей попытке отправлено (201)")

    # 429 и редирект (точка доступа с входом): ждёт
    for code in (429, 302):
        rx.codes = [code]
        dl = feedback.submit({}, 4, "", 2000, sender=rx.sender, directory=d, background=False)
        check(dl.state == "queued", f"{code}: в очереди")
    for f in queue_files(d):
        f.unlink()

    # 400 и 422: приёмник не принял, повторять бесполезно
    for code in (400, 422):
        rx.codes = [code]
        dl = feedback.submit({}, 4, "", 2000, sender=rx.sender, directory=d, background=False)
        check(dl.state == "rejected" and feedback.status_key(dl) == "feedback.thanks_rejected" and queue_files(d) == [],
              f"{code}: «не принял», из очереди убрано")

    # нет приёмника вовсе
    url = closed_port_url()
    dl = feedback.submit({}, 1, "", 2000, sender=lambda p: feedback.post_rating(p, url, timeout=3), directory=d,
                         background=False)
    check(dl.state == "queued" and len(queue_files(d)) == 1, "нет сервера: оценка ждёт в очереди")
    # свежую оценку проход очереди не трогает (первую попытку делает кнопка)
    for f in queue_files(d):
        f.unlink()
    rx.codes, rx.requests = [201], []
    feedback.enqueue(feedback.make_payload(5, "", 2000), d)
    check(feedback.flush_outbox(rx.sender, d) == 0 and rx.requests == [], "свежая оценка: проход очереди ждёт")
    for f in queue_files(d):
        os.utime(f, (time.time() - 600, time.time() - 600))
    check(feedback.flush_outbox(rx.sender, d) == 1, "через 2 минуты проход очереди её отправляет")
    # испорченный файл очереди не роняет проход
    (d / "0-bad.json").write_text("{broken", encoding="utf-8")
    feedback.flush_outbox(rx.sender, d)
    check(not (d / "0-bad.json").exists(), "испорченный файл очереди удалён")
    # не больше MAX_OUTBOX файлов
    for _ in range(feedback.MAX_OUTBOX + 5):
        feedback.enqueue(feedback.make_payload(5, "", 2000), d)
    check(len(queue_files(d)) == feedback.MAX_OUTBOX, "очередь не растёт больше 20")

    # фоновая отправка: Delivery «sending» -> «sent»
    d2 = tmpdir()
    rx.codes = [201]
    dl = feedback.submit({}, 5, "", 2000, sender=rx.sender, directory=d2)
    check(dl.done.wait(10) and dl.state == "sent", "фоновая отправка: отправлено")
    check(feedback.status_key(feedback.Delivery()) == "feedback.thanks_sending", "пока идёт отправка: «Отправляем…»")


# ---------------------------------------------------------------- окна

def test_rating_dialog():
    d = tmpdir()
    rx.codes, rx.requests = [201], []
    outcomes = []
    cfg = {}
    dlg = feedback.build_rating_dialog(cfg, lambda o, w: outcomes.append(o), sender=rx.sender, directory=d)
    dlg.open_centered()
    settle()
    check(dlg.windowTitle() == "ClipSD: " + tr("feedback.rate_title"), "заголовок окна")
    check(dlg.send_btn.objectName() == "clipPrimary" and not dlg.send_btn.isEnabled(), "зелёная «Отправить» ждёт звёзд")
    check(len(dlg.star_buttons) == 5, "5 звёзд")
    dlg.star_buttons[3].click()
    check(dlg.stars == 4 and dlg.send_btn.isEnabled(), "4 звезды выбраны, «Отправить» доступна")
    check(dlg.stars_hint.text() == tr("feedback.stars_tip", n=4), f"подпись звёзд: {dlg.stars_hint.text()}")
    dlg.text_edit.setPlainText("ж" * 1500)
    settle(2)
    check(len(dlg.text_edit.toPlainText()) == 1000 and dlg.counter.text() == "1000 / 1000", "отзыв не длиннее 1000 знаков")
    check("privacy.html#ratings" in dlg.note.text() and "/ru/" in dlg.note.text(), "ссылка «Что отправляется» на политику")
    QTest.qWait(1100)
    dlg.send_btn.click()
    check(outcomes == ["sent"] and cfg.get("rating_disabled") and not cfg.get("rating_sent"),
          "«Отправить»: итог sent, окно больше не предлагается, «отправлено» ждёт ответа приёмника")
    check(wait(lambda: dlg.delivery.done.is_set()) and dlg.delivery.state == "sent", "отправлено (201)")
    check(feedback.has_rated(cfg, d) and feedback.delivered(d), "после 2xx оценка считается отправленной")
    body = json.loads(rx.requests[-1]["body"])
    check(body["stars"] == 4 and len(body["review"]) == 1000 and body["fill_ms"] >= 1000, "звёзды, отзыв и время окна")
    settle()

    for button, expected in (("later_btn", "later"), ("never_btn", "never")):
        out = []
        w = feedback.build_rating_dialog({}, lambda o, _w: out.append(o), directory=d)
        w.open_centered()
        settle(2)
        getattr(w, button).click()
        settle(2)
        check(out == [expected], f"кнопка {button}: итог {expected}")
    out = []
    w = feedback.build_rating_dialog({}, lambda o, _w: out.append(o), directory=d)
    w.open_centered()
    settle(2)
    QTest.keyClick(w, Qt.Key.Key_Escape)
    settle(2)
    check(out == ["closed"], "Esc: итог closed")
    out = []
    w = feedback.build_rating_dialog({}, lambda o, _w: out.append(o), directory=d)
    w.open_centered()
    settle(2)
    w.close_b.click()
    settle(2)
    check(out == ["closed"], "крестик: итог closed")


def test_thanks_dialog():
    dl = feedback.Delivery()
    t = feedback.build_thanks_dialog(5, "", dl)
    t.open_centered()
    settle(2)
    check(t.status.text() == tr("feedback.thanks_sending"), "пока отправляется: «Отправляем оценку…»")
    dl.finish("sent")
    check(wait(lambda: t.status.text() == tr("feedback.thanks_text")), "после 2xx: «Оценка отправлена»")
    urls = [b.url for b in t.link_buttons]
    check(urls == ["https://github.com/clipsd/clipsd"], f"каталоги: только включённые ({urls})")
    check(t.problem_button is None, "5 звёзд: без «Сообщить о проблеме»")
    check(t.close_button.objectName() == "clipPrimary", "зелёная «Готово»")
    t.close()

    saved = list(feedback.CATALOGS)
    feedback.CATALOGS[:] = [(k, n, u, key, False) for k, n, u, key, _e in saved]
    t = feedback.build_thanks_dialog(5, "", None)
    check(t.link_buttons == [], "все каталоги выключены: ссылок нет")
    t.close()
    feedback.CATALOGS[:] = [(k, n, u, key, True) if k == "sourceforge" else (k, n, u, key, e)
                            for k, n, u, key, e in saved]
    names = [b.text() for b in feedback.build_thanks_dialog(5, "", None).link_buttons]
    check(names == [tr("feedback.catalog_github"), tr("feedback.rate_in", name="SourceForge")],
          f"включённый каталог появляется из того же списка ({names})")
    feedback.CATALOGS[:] = saved

    for stars in (1, 2, 3):
        t = feedback.build_thanks_dialog(stars, "Не вставляется снимок", None)
        check(t.problem_button is not None and t.problem_button.isVisibleTo(t), f"{stars} звезды: «Сообщить о проблеме»")
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(t.issue_url).query)
        check(t.issue_url.startswith("https://github.com/clipsd/clipsd/issues/new?"), "задача на GitHub")
        check(q["title"][0] == tr("feedback.issue_title", version=clipshot.__version__), "заголовок задачи с версией")
        check("Не вставляется снимок" in q["body"][0] and f"{stars} из 5" in q["body"][0]
              and clipshot.__version__ in q["body"][0], "в задаче отзыв, оценка и версия")
        t.close()
    t = feedback.build_thanks_dialog(4, "x", None)
    check(t.problem_button is None, "4 звезды: без «Сообщить о проблеме»")
    t.close()
    long_url = feedback.issue_url(1, "ы" * 1000)
    check(len(long_url) <= feedback.ISSUE_URL_LIMIT, f"длинный отзыв укорочен под предел адреса ({len(long_url)})")
    home = str(Path.home())
    check(home not in urllib.parse.unquote(long_url) and os.environ.get("USER", "@@") not in urllib.parse.unquote(
        feedback.issue_url(1, "x")), "в задаче нет домашней папки и имени пользователя")


class Ctx:
    def __init__(self, **cfg):
        self.config = dict(cfg)
        self.saved = 0

    def save_config(self):
        self.saved += 1


def test_flow():
    rx.codes = [201]
    ctx = Ctx(usage_days=9, capture_count=30)
    flow = feedback.RatingFlow(ctx, auto=True, sender=rx.sender, directory=tmpdir())
    flow.open()
    settle(2)
    check(ctx.config.get("rating_shown") == 1 and ctx.saved >= 1, "показ по правилам засчитан и записан до открытия")
    check(feedback.is_open(flow), "окно открыто")
    flow.dialog.close()
    settle(2)
    check(flow.outcome == "closed" and ctx.config.get("rating_next_ts", 0) > time.time() + 29 * DAY,
          "крестик при показе по правилам = «Позже» на 30 дней")

    ctx = Ctx()
    flow = feedback.RatingFlow(ctx, auto=False, sender=rx.sender, directory=tmpdir())
    flow.open()
    settle(2)
    flow.dialog.close()
    settle(2)
    check("rating_next_ts" not in ctx.config and "rating_shown" not in ctx.config, "из меню: крестик ничего не откладывает")

    ctx = Ctx()
    flow = feedback.RatingFlow(ctx, sender=rx.sender, directory=tmpdir())
    flow.open()
    flow.dialog.never_btn.click()
    settle(2)
    check(ctx.config.get("rating_disabled") is True, "«Больше не показывать» записано")

    ctx = Ctx()
    flow = feedback.RatingFlow(ctx, sender=rx.sender, directory=tmpdir())
    flow.open()
    flow.dialog.later_btn.click()
    settle(2)
    check(ctx.config.get("rating_next_ts", 0) > time.time() + 29 * DAY, "«Позже» записано")

    ctx = Ctx()
    flow = feedback.RatingFlow(ctx, sender=rx.sender, directory=tmpdir())
    flow.open()
    flow.dialog.set_stars(2)
    flow.dialog.text_edit.setPlainText("Медленно открывается")
    flow.dialog.send_btn.click()
    check(wait(lambda: flow.thanks is not None and flow.thanks.isVisible()), "после «Отправить»: окно с итогом")
    check(wait(lambda: flow.thanks.status.text() == tr("feedback.thanks_text")), "итог: «Оценка отправлена»")
    check(flow.thanks.problem_button is not None and "Медленно открывается" in urllib.parse.unquote(flow.thanks.issue_url),
          "2 звезды: задача на GitHub с текстом отзыва")
    flow.thanks.close()
    settle(2)


def test_menus_and_app():
    # меню значка у часов
    class FakeApp:
        def __init__(self):
            self.config = dict(appmod.DEFAULTS)
            self.editors, self.tray, self.qapp = [], None, app
            self.rated = 0

        def show_rating(self):
            self.rated += 1

        def save_config(self):
            pass

        def capture_region(self, **_k):
            pass
        capture_fullscreen = open_screen_recording = open_file = open_folder = open_settings = capture_region
        demo_tour = demo_selector_tour = show_about = capture_region   # 1.32: и знакомство с окном выделения
        _build_tray_menu = appmod.Clipshot._build_tray_menu

    fake = FakeApp()
    menu = fake._build_tray_menu()
    texts = [a.text() for a in menu.actions()]
    check(tr("feedback.rate_title") in texts, f"меню значка: «Оценить ClipSD» ({texts})")
    check(texts.index(tr("feedback.rate_title")) == texts.index(tr("app.menu_about")) - 1, "сразу над «О программе»")
    next(a for a in menu.actions() if a.text() == tr("feedback.rate_title")).trigger()
    check(fake.rated == 1, "пункт меню значка открывает оценку")

    # меню «?» редактора
    from clipshot.editor import EditorWindow
    image = QImage(300, 200, QImage.Format.Format_RGB32)
    image.fill(QColor("#ffffff"))
    fake.config.update(tour_done=True, theme_chosen=True)
    fake.icon = appmod.make_icon()
    fake.notify = lambda *_a: None
    ed = EditorWindow(image, fake, QPoint(0, 0))
    ed.present()
    settle()
    labels = [a.text() for a in ed.help_menu.actions()]
    check(tr("feedback.rate_title") in labels, f"меню «?» редактора: «Оценить ClipSD» ({labels})")
    next(a for a in ed.help_menu.actions() if a.text() == tr("feedback.rate_title")).trigger()
    check(fake.rated == 2, "пункт «?» редактора открывает оценку")
    ed.close()
    settle()

    # приложение: снимок считается, окно по правилам только в спокойную минуту
    appmod.CONFIG_PATH = Path(tempfile.mkdtemp(prefix="clipsd-rate-cfg-")) / "config.json"
    c = appmod.Clipshot(app)
    c.config.update(auto_save=False, usage_days=7, capture_count=19)

    class Sel:
        action, full_mode = "copy", False
    c.selector = Sel()
    pm = QPixmap(40, 30)
    pm.fill(QColor("#ff0000"))
    from PyQt6.QtCore import QRect
    c._region_done(pm, QRect(0, 0, 40, 30))
    saved = json.loads(appmod.CONFIG_PATH.read_text(encoding="utf-8"))
    check(c.config["capture_count"] == 20 and saved["capture_count"] == 20, "снимок посчитан и записан в настройки")
    c.selector = Sel()
    c._region_done(None, QRect())
    check(c.config["capture_count"] == 20, "отменённый снимок не считается")
    c.selector = object()
    check(not c.maybe_offer_rating(), "идёт выделение: окна нет")
    c.selector = None
    from clipshot.dialogs import ClipDialog
    other = ClipDialog(None, "x")
    other.show()
    settle(2)
    check(not c.maybe_offer_rating(), "открыто другое окно ClipSD: окна оценки нет")
    other.close()
    settle(2)
    feedback.RATE_URL = closed_port_url()
    check(c.maybe_offer_rating() and feedback.is_open(c._rating), "спокойная минута, правила выполнены: окно оценки")
    check(not c.maybe_offer_rating(), "второй раз не открывается")
    check(c.config["rating_shown"] == 1, "показ засчитан")
    c._rating.dialog.close()
    settle(2)
    check(not c.maybe_offer_rating(), "после крестика 30 дней окна нет")
    c.show_rating()
    settle(2)
    check(feedback.is_open(c._rating) and not c._rating.auto, "пункт меню открывает окно и вне правил")
    c._rating.dialog.close()
    settle(2)
    feedback.RATE_URL = rx.url


def test_already_rated():
    """После отправленной оценки пункт меню: «Вы уже оценили ClipSD», второй оценки нет."""
    rx.codes, rx.requests = [201], []
    d = tmpdir()
    ctx = Ctx()
    flow = feedback.RatingFlow(ctx, sender=rx.sender, directory=d)
    flow.open()
    flow.dialog.set_stars(4)
    flow.dialog.send_btn.click()
    check(wait(lambda: flow.thanks is not None and flow.thanks.isVisible()), "оценка отправлена")
    check(wait(lambda: flow.thanks.delivery.done.is_set()), "приёмник ответил")
    flow.thanks.close()
    settle(2)
    check(ctx.config.get("rating_stars") == 4 and len(ctx.config.get("rating_day", "")) == 10,
          "на компьютере запомнены только звёзды и день оценки")
    sent_before = len(rx.requests)
    again = feedback.RatingFlow(ctx, sender=rx.sender, directory=d)
    again.open()
    settle(2)
    check(again.dialog is None and again.outcome == "already" and again.thanks.isVisible(),
          "пункт меню после отправки: окно «Вы уже оценили», окна оценки нет")
    w = again.thanks
    check(w.windowTitle() == "ClipSD: " + tr("feedback.already_title"), "заголовок «Вы уже оценили ClipSD»")
    check(w.summary is not None and "4" in w.summary.text(), f"звёзды и дата оценки: {w.summary.text()}")
    check(w.pending is None, "оценка дошла: про очередь ни слова")
    check(feedback.SUPPORT_EMAIL in w.change.text() and "mailto:" in w.change.text(), "как изменить или удалить: письмо автору")
    check([b.url for b in w.link_buttons] == ["https://github.com/clipsd/clipsd"], "ссылки на каталоги")
    check(feedback.is_open(again), "окно считается открытым (второе не плодится)")
    w.close()
    settle(2)
    check(len(rx.requests) == sent_before, "вторая оценка не отправлена")
    # оценка ещё в очереди: окно честно говорит, что она не отправлена
    ctx2 = Ctx()
    d2 = tmpdir()
    feedback.submit(ctx2.config, 2, "", 2000, sender=lambda p: 0, directory=d2, background=False)
    w2 = feedback.RatingFlow(ctx2, directory=d2).open()
    settle(2)
    check(w2.pending is not None and w2.pending.text() == tr("feedback.already_pending"), "оценка в очереди: «ещё не отправлена»")
    w2.close()
    # по правилам окно после отправки не предлагается вовсе
    auto = feedback.RatingFlow(Ctx(usage_days=30, capture_count=99, rating_sent=True), auto=True)
    check(not feedback.should_show_rating(auto.ctx.config), "по правилам после отправки окна нет")
    # старая запись без звёзд: окно без строки оценки, без ошибок
    w3 = feedback.build_already_dialog({"rating_sent": True}, directory=tmpdir())
    check(w3.summary is None, "нет звёзд в настройках: строки оценки нет")
    w3.close()
    check(feedback.local_date("2026-11-19") != "" and feedback.local_date("bad") == "bad", "дата по правилам языка")


def test_rejected_and_retry():
    """П1 проверки 1.32: «отправлено» только после 2xx. Отказ приёмника (4xx) или кончившиеся попытки: пункт меню
    снова открывает окно оценки (как обещает окно «Сервер не принял оценку»), само окно не навязывается."""
    # 403 (например, защита Cloudflare в сети организации)
    ctx = Ctx(usage_days=30, capture_count=99)
    d = tmpdir()
    dl = feedback.submit(ctx.config, 4, "Хорошая программа", 5000, sender=lambda p: 403, directory=d, background=False)
    check(dl.state == "rejected" and tr(feedback.status_key(dl)) == tr("feedback.thanks_rejected"),
          "403: «Сервер не принял оценку. Попробуйте ещё раз из меню»")
    check(not ctx.config.get("rating_sent") and not feedback.has_rated(ctx.config, d) and not feedback.delivered(d),
          "403: оценка не отмечена отправленной")
    check(not feedback.should_show_rating(ctx.config), "403: само окно больше не предлагается (не навязывается)")
    rx.codes = [201]
    flow = feedback.RatingFlow(ctx, sender=rx.sender, directory=d)
    flow.open()
    settle(2)
    check(flow.outcome is None and flow.thanks is None and flow.dialog is not None and flow.dialog.isVisible(),
          "403: пункт меню открывает окно оценки, а не «Вы уже оценили»")
    # повтор из меню: новая оценка уходит и доходит
    flow.dialog.set_stars(5)
    flow.dialog.send_btn.click()
    check(wait(lambda: flow.thanks is not None and flow.thanks.delivery.done.is_set())
          and flow.thanks.delivery.state == "sent", "повтор из меню: приёмник принял (201)")
    check(wait(lambda: flow.thanks.status.text() == tr("feedback.thanks_text")) and feedback.has_rated(ctx.config, d),
          "повтор из меню: «Оценка отправлена»")
    flow.thanks.close()
    settle(2)
    again = feedback.RatingFlow(ctx, directory=d)
    again.open()
    settle(2)
    check(again.outcome == "already" and again.thanks.pending is None, "после повтора: «Вы уже оценили», очередь пуста")
    again.thanks.close()
    settle(2)

    # нет связи все 3 попытки: пока ждёт, «Вы уже оценили» с пометкой об очереди; попытки кончились: снова оценить
    ctx = Ctx()
    d = tmpdir()
    t0 = time.time()
    dl = feedback.submit(ctx.config, 3, "", 2000, sender=lambda p: 0, directory=d, background=False)
    check(dl.state == "queued" and feedback.has_rated(ctx.config, d) and not ctx.config.get("rating_sent"),
          "нет связи: оценка ждёт в очереди, второй не нужно")
    w = feedback.RatingFlow(ctx, directory=d)
    w.open()
    settle(2)
    check(w.outcome == "already" and w.thanks.pending is not None, "ждёт отправки: «Вы уже оценили» и «ещё не отправлена»")
    w.thanks.close()
    feedback.flush_outbox(lambda p: 0, d, now=t0 + 3601)
    check(feedback.pending_count(d) == 1 and feedback.has_rated(ctx.config, d), "2-я попытка без связи: ещё ждёт")
    feedback.flush_outbox(lambda p: 0, d, now=t0 + 3601 + DAY + 1)
    check(feedback.pending_count(d) == 0 and not feedback.has_rated(ctx.config, d),
          "3 попытки без связи: оценка не дошла, не считается отправленной")
    w = feedback.RatingFlow(ctx, directory=d)
    w.open()
    settle(2)
    check(w.outcome is None and w.dialog is not None and w.dialog.isVisible(), "попытки кончились: пункт меню даёт оценить снова")
    w.dialog.close()
    settle(2)

    # 500 по кнопке, 201 при фоновом проходе очереди (может быть и после перезапуска): отметка в папке очереди,
    # config пишет главный поток при следующем открытии окна
    ctx = Ctx()
    d = tmpdir()
    feedback.submit(ctx.config, 4, "", 2000, sender=lambda p: 500, directory=d, background=False)
    rx.codes = [201]
    check(feedback.flush_outbox(rx.sender, d, now=time.time() + 3601) == 1, "фоновый проход очереди: 201")
    check(not ctx.config.get("rating_sent") and feedback.delivered(d) and feedback.has_rated(ctx.config, d),
          "фоновая отправка дошла: config в фоне не трогается, отметка в папке очереди")
    saved = ctx.saved
    w = feedback.RatingFlow(ctx, directory=d)
    w.open()
    settle(2)
    check(ctx.config.get("rating_sent") is True and ctx.saved > saved, "окно переносит отметку в настройки и записывает их")
    check(w.outcome == "already" and w.thanks.pending is None, "после фоновой отправки: «Вы уже оценили», очередь пуста")
    w.thanks.close()
    settle(2)
    mark = Path(d) / feedback.DELIVERED_MARK
    check(mark.stat().st_size == 0 and oct(mark.stat().st_mode & 0o777) == "0o600", "отметка пустая, права 0600")


def test_languages():
    for lang in i18n.LANGUAGES:
        i18n.set_language(lang)
        for key in ("feedback.rate_title", "feedback.issue_body", "feedback.thanks_rejected"):
            check(tr(key) != key, f"{lang}: {key}")
        body = tr("feedback.issue_body", text="T", version="1.32.0", system="S", lang=lang, stars=2)
        check("T" in body and "1.32.0" in body and "2" in body and "{" not in body, f"{lang}: шаблон задачи заполняется")
    i18n.set_language("ru")


for fn in (test_rules, test_payload, test_send_and_queue, test_rating_dialog, test_thanks_dialog, test_flow,
           test_already_rated, test_rejected_and_retry, test_menus_and_app, test_languages):
    try:
        fn()
    except Exception as exc:     # noqa: BLE001
        import traceback
        traceback.print_exc()
        check(False, f"{fn.__name__}: исключение {exc!r}")

rx.server.shutdown()
print(f"ИТОГ: проверок {checks[0]}, провалено: {len(failures)}")
sys.exit(1 if failures else 0)
