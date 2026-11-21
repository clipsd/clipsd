# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Фото с телефона: просмотр снятого фото крупно до отправки (решение владельца 21.11.2026).

Владелец: «если на него нажать, чтобы оно крупно выделилось, потом крестиком закрыть. Чтобы можно было его
приближать, смотреть, всё ли хорошо сфотографировано».

Часть 1, всегда: разметка и скрипт страницы на 12 языках (подсказка под миниатюрой, окно просмотра, крестик с
подписью, политика страницы та же, без внешних адресов и библиотек, без style-атрибутов).
Часть 2, если на компьютере есть Chrome или Chromium (Linux, macOS): настоящий приёмник на 127.0.0.1 и страница
в безголовом браузере с экраном телефона 390 x 844 (касания, мобильный режим), связь по своему каналу отладки
(--remote-debugging-pipe, без сети и без сторонних пакетов). Проверяется: нажатие на миниатюру открывает фото крупно
(тот же адрес blob:, ничего не грузится заново), крестик не меньше 44 x 44 точек, двойное касание 2x и обратно,
два пальца увеличивают, один двигает, сама страница не масштабируется, кнопка «Назад» и крестик закрывают,
меньше 30 секунд приёма: строка времени видна в просмотре, «Отправить и закончить» после просмотра работает,
ни одного нарушения политики страницы и ни одной ошибки скрипта. Браузер берётся из CLIPSD_CHROME или из PATH;
нет браузера: часть 2 пропускается с пометкой.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/foto_prosmotr_test.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

here = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(here)
sys.path.insert(0, ROOT)
sys.path.insert(0, here)
os.environ.pop("CLIPSD_LANG", None)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tmpclean  # noqa: E402,F401  (временные папки этого теста убираются при его выходе)

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice  # noqa: E402
from PyQt6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
from clipshot import i18n, phone, phone_page, phone_ui  # noqa: E402

phone.LISTEN_PORTS = ()   # a free port of the system: other runs do not fight for 8765-8767

failures = []
checks = [0]
LANGS = ("ru", "en", "es", "de", "fr", "it", "pt", "pl", "tr", "uk", "bg", "zh")


def check(cond, msg):
    checks[0] += 1
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


# --- part 1: markup and script ------------------------------------------------------------------------------------

def test_markup():
    hints = set()
    for lang in LANGS:
        i18n.set_language(lang)
        t = phone_ui.page_texts()
        check(t.get("page_zoom_hint") and not t["page_zoom_hint"].startswith("phone.")
              and t.get("page_zoom_close") and not t["page_zoom_close"].startswith("phone."),
              f"{lang}: подсказка «Нажмите, чтобы рассмотреть» и подпись крестика переведены")
        hints.add(t["page_zoom_hint"])
        html = phone_page.render_page(t, lang, "/abc", "KEY", "nonce1")
        esc = phone_page._e
        check(f'<p id="zoomhint">{esc(t["page_zoom_hint"])}</p>' in html
              and html.index('id="preview"') < html.index('id="zoomhint"') < html.index('id="dims"'),
              f"{lang}: подсказка сразу под миниатюрой")
        check(f'aria-label="{esc(t["page_zoom_close"])}"' in html and 'id="zv"' in html and 'id="zimg"' in html
              and 'id="zleft"' in html and 'role="dialog"' in html,
              f"{lang}: окно просмотра с крестиком (подпись для чтения с экрана) и строкой времени")
        check(re.search(r'<img id="preview" alt="" role="button" tabindex="0" aria-label="[^"]+">', html) is not None,
              f"{lang}: миниатюра нажимается (кнопка для клавиатуры и чтения с экрана)")
        check(html.count("</script>") == 2 and "http://" not in html.split("<script")[0] and "https://" not in html
              and 'style="' not in html.split("<script")[0],
              f"{lang}: один скрипт страницы, без внешних адресов и style-атрибутов")
    check(len(hints) == len(LANGS), "подсказка на 12 языках, все разные")
    i18n.set_language("ru")
    t = phone_ui.page_texts()
    check(t["page_zoom_hint"] == "Нажмите, чтобы рассмотреть" and t["page_zoom_close"] == "Закрыть", "русские тексты")
    js = phone_page._VIEWER_SCRIPT
    css = phone_page._VIEWER_STYLE
    check("pointerdown" in js and "pointermove" in js and "pointercancel" in js and "setPointerCapture" in js,
          "жесты своим кодом на событиях указателя (палец, мышь, перо)")
    check("gesturestart" in js and "passive:false" in js and "touchmove" in js,
          "Safari: свои события масштаба и прокрутка страницы отменяются, пока открыт просмотр")
    check("touch-action:none" in css and "overflow:hidden" in css and "min-width:44px;min-height:44px" in css,
          "сцена без жестов браузера, страница под просмотром не прокручивается, крестик не меньше 44 x 44")
    check("history.pushState" in js and "popstate" in js and "history.back()" in js,
          "кнопка «Назад» телефона закрывает просмотр (одна запись истории)")
    check("pv.getAttribute('src')" in js and "fetch(" not in js and "XMLHttpRequest" not in js and "import(" not in js,
          "просмотр показывает тот же адрес миниатюры, ничего не запрашивает")
    check("MutationObserver" in js and "'ready'" in js and "amber" in js,
          "просмотр закрывается, когда страница уходит с «Фото готово»; меньше 30 секунд: строка времени")
    check("{_STYLE}{_VIEWER_STYLE}" in open(phone_page.__file__, encoding="utf-8").read(), "стили просмотра отдельным блоком")
    rx = phone.Receiver("127.0.0.1", texts=phone_ui.page_texts())
    rx.start()
    try:
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", rx.port, timeout=5)
        c.request("GET", f"/{rx.token}", headers={"Host": rx.authority})
        r = c.getresponse()
        body = r.read().decode("utf-8")
        csp = r.getheader("Content-Security-Policy") or ""
        nonce = re.search(r"'nonce-([^']+)'", csp).group(1)
        check(r.status == 200 and csp == (f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
                                          "img-src blob: data:; connect-src 'self'; base-uri 'none'; "
                                          "form-action 'none'; frame-ancestors 'none'"),
              "политика страницы (Content-Security-Policy) та же, что в 1.33.0")
        check('id="zv"' in body and body.count(f'nonce="{nonce}"') == 2, "страница приёмника с просмотром, скрипт и стиль с меткой")
    finally:
        rx.stop()


# --- part 2: the page in a headless browser -----------------------------------------------------------------------

def find_chrome():
    if os.name != "posix":
        return None
    env = os.environ.get("CLIPSD_CHROME")
    if env and os.path.exists(env):
        return env
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        p = shutil.which(name)
        if p:
            return p
    mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    return mac if os.path.exists(mac) else None


class CDP:
    """Chrome DevTools Protocol over --remote-debugging-pipe (fd 3: commands in, fd 4: answers out), JSON + NUL."""

    def __init__(self, binary, workdir):
        to_chrome_r, self._w = os.pipe()
        self._r, from_chrome_w = os.pipe()
        import fcntl
        hi_r = fcntl.fcntl(to_chrome_r, fcntl.F_DUPFD, 20)
        hi_w = fcntl.fcntl(from_chrome_w, fcntl.F_DUPFD, 20)
        os.close(to_chrome_r)
        os.close(from_chrome_w)

        def child():
            os.dup2(hi_r, 3)
            os.dup2(hi_w, 4)

        args = [binary, "--headless", "--remote-debugging-pipe", f"--user-data-dir={workdir}/profile",
                "--no-first-run", "--no-default-browser-check", "--disable-background-networking",
                "--disable-component-update", "--disable-sync", "--disable-default-apps", "--disable-extensions",
                "--metrics-recording-only", "--password-store=basic", "--use-mock-keychain", "--mute-audio",
                "--disable-gpu", "--hide-scrollbars", "about:blank"]
        env = dict(os.environ, HOME=workdir)
        self.proc = subprocess.Popen(args, preexec_fn=child, pass_fds=(3, 4), stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, cwd=workdir)
        os.close(hi_r)
        os.close(hi_w)
        self._id = 0
        self._answers = {}
        self.events = []
        self._cv = threading.Condition()
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()
        self.session = None

    def _read(self):
        buf = b""
        while True:
            try:
                chunk = os.read(self._r, 65536)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while b"\0" in buf:
                msg, buf = buf.split(b"\0", 1)
                try:
                    m = json.loads(msg)
                except ValueError:
                    continue
                with self._cv:
                    if "id" in m:
                        self._answers[m["id"]] = m
                    else:
                        self.events.append(m)
                    self._cv.notify_all()
        with self._cv:
            self._cv.notify_all()

    def send(self, method, params=None, session=True, timeout=15):
        with self._cv:
            self._id += 1
            mid = self._id
        msg = {"id": mid, "method": method, "params": params or {}}
        if session and self.session:
            msg["sessionId"] = self.session
        os.write(self._w, json.dumps(msg).encode() + b"\0")
        end = time.time() + timeout
        with self._cv:
            while mid not in self._answers:
                left = end - time.time()
                if left <= 0 or self.proc.poll() is not None:
                    raise RuntimeError(f"no answer to {method}")
                self._cv.wait(min(left, 0.5))
            m = self._answers.pop(mid)
        if "error" in m:
            raise RuntimeError(f"{method}: {m['error']}")
        return m.get("result", {})

    def js(self, expr):
        r = self.send("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
        if "exceptionDetails" in r:
            raise RuntimeError(f"js: {r['exceptionDetails'].get('text')} in {expr[:80]}")
        return r.get("result", {}).get("value")

    def wait(self, expr, timeout=8.0):
        end = time.time() + timeout
        while time.time() < end:
            try:
                if self.js(expr):
                    return True
            except RuntimeError:
                pass
            time.sleep(0.05)
        return False

    def touch(self, kind, points):
        self.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": [
            {"x": x, "y": y, "id": i, "radiusX": 4, "radiusY": 4, "force": 1} for i, (x, y) in points]})

    def tap(self, x, y):
        self.touch("touchStart", [(0, (x, y))])
        self.touch("touchEnd", [])

    def close(self):
        try:
            self.send("Browser.close", session=False, timeout=3)
        except Exception:   # noqa: BLE001
            pass
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(5)
        for fd in (self._w, self._r):
            try:
                os.close(fd)
            except OSError:
                pass


def photo_file(path, w=1600, h=1200):
    """A photo with fine detail (thin lines and small squares), so that zooming has something to show."""
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor("#f4f1ea"))
    p = QPainter(img)
    for i in range(0, w, 40):
        p.setPen(QColor("#1d4ed8") if i % 200 else QColor("#b91c1c"))
        p.drawLine(i, 0, i, h)
    for j in range(0, h, 40):
        p.setPen(QColor("#15803d"))
        p.drawLine(0, j, w, j)
    p.fillRect(w // 2 - 6, h // 2 - 6, 12, 12, QColor("#000000"))
    p.end()
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "JPEG", 90)
    buf.close()
    with open(path, "wb") as f:
        f.write(bytes(ba))


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def rect(cdp, sel):
    return cdp.js(f"(function(){{var r=document.querySelector('{sel}').getBoundingClientRect();"
                  "return {x:r.left,y:r.top,w:r.width,h:r.height};})()")


def test_browser():
    chrome = find_chrome()
    if not chrome:
        print("SKIP браузерная часть: нет Chrome или Chromium (CLIPSD_CHROME или PATH)")
        return
    work = tempfile.mkdtemp(prefix="clipsd-prosmotr-")
    jpg = os.path.join(work, "photo.jpg")
    photo_file(jpg)
    i18n.set_language("ru")
    events = []
    clock = Clock()
    rx = phone.Receiver("127.0.0.1", on_event=lambda k, d: events.append((k, d)), texts=phone_ui.page_texts(),
                        clock=clock)
    rx.start()
    cdp = None
    try:
        cdp = CDP(chrome, work)
        tid = cdp.send("Target.createTarget", {"url": "about:blank"}, session=False)["targetId"]
        cdp.session = cdp.send("Target.attachToTarget", {"targetId": tid, "flatten": True}, session=False)["sessionId"]
        for m in ("Page.enable", "Runtime.enable", "DOM.enable"):
            cdp.send(m)
        cdp.send("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 3, "mobile": True})
        cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 5})
        cdp.send("Emulation.setUserAgentOverride", {"userAgent": "Mozilla/5.0 (Linux; Android 15; SM-S921B) "
                                                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0 Mobile Safari/537.36"})
        cdp.send("Page.addScriptToEvaluateOnNewDocument", {"source":
                 "window.__csp=[];document.addEventListener('securitypolicyviolation',function(e){"
                 "window.__csp.push(e.violatedDirective+' '+e.blockedURI);});"})
        cdp.send("Page.navigate", {"url": rx.url})
        check(cdp.wait("document.readyState==='complete'&&!!document.getElementById('zv')"), "страница открылась в браузере")
        doc = cdp.send("DOM.getDocument")["root"]["nodeId"]
        cam = cdp.send("DOM.querySelector", {"nodeId": doc, "selector": "#cam"})["nodeId"]
        cdp.send("DOM.setFileInputFiles", {"nodeId": cam, "files": [jpg]})
        check(cdp.wait("document.getElementById('app').getAttribute('data-state')==='ready'&&"
                       "document.getElementById('preview').naturalWidth>0"), "после снимка экран «Фото готово»")
        hint = cdp.js("(function(){var h=document.getElementById('zoomhint'),p=document.getElementById('preview');"
                      "var a=h.getBoundingClientRect(),b=p.getBoundingClientRect();"
                      "return {text:h.textContent,shown:getComputedStyle(h).display!=='none',under:a.top>=b.bottom-1,"
                      "panel:a.bottom<=document.getElementById('readybar').getBoundingClientRect().top};})()")
        check(hint["text"] == "Нажмите, чтобы рассмотреть" and hint["shown"] and hint["under"],
              "под миниатюрой видна подсказка «Нажмите, чтобы рассмотреть»")
        check(hint["panel"], "подсказка не уходит под панель кнопок отправки (390 x 844)")
        hist0 = cdp.send("Page.getNavigationHistory")["currentIndex"]

        # open by a tap on the thumbnail
        r = rect(cdp, "#preview")
        cdp.tap(r["x"] + r["w"] / 2, r["y"] + r["h"] / 2)
        check(cdp.wait("!document.getElementById('zv').hidden&&document.getElementById('zimg').naturalWidth>0"),
              "нажатие на миниатюру открывает фото крупно")
        same = cdp.js("document.getElementById('zimg').getAttribute('src')===document.getElementById('preview').getAttribute('src')"
                      "&&document.getElementById('zimg').getAttribute('src').indexOf('blob:')===0")
        check(same, "крупно показан тот же локальный адрес blob:, что у миниатюры (фото не грузится заново)")
        z = rect(cdp, "#zimg")
        check(abs(z["w"] - 390) < 1.5 and z["h"] < 844 and abs((z["y"] + z["h"] / 2) - 422) < 2,
              f"фото вписано в экран по ширине и стоит по центру ({z['w']:.0f} x {z['h']:.0f})")
        x = rect(cdp, "#zclose")
        check(x["w"] >= 44 and x["h"] >= 44 and x["x"] + x["w"] > 390 - 40 and x["y"] < 40,
              f"крестик в правом верхнем углу, {x['w']:.0f} x {x['h']:.0f} точек (не меньше 44 x 44)")
        look = cdp.js("(function(){var s=getComputedStyle(document.getElementById('zclose'));"
                      "return [s.backgroundColor,s.borderTopColor,getComputedStyle(document.getElementById('zv')).backgroundColor];})()")
        check(look[0].startswith("rgba(0, 0, 0, 0.6") and look[1] == "rgb(255, 255, 255)" and look[2] == "rgb(0, 0, 0)",
              "крестик: тёмный круг с белой каймой (виден на светлом и тёмном фото), фон просмотра чёрный")
        check(cdp.js("getComputedStyle(document.documentElement).overflow==='hidden'"), "страница под просмотром не прокручивается")
        check(cdp.send("Page.getNavigationHistory")["currentIndex"] == hist0 + 1, "открытие добавляет одну запись истории")

        def scale():
            return float(cdp.js("document.getElementById('zv').getAttribute('data-scale')") or 0)

        # double tap: 2x around the finger, again: back to the whole photo
        cx, cy = 195, 422
        cdp.tap(cx, cy)
        time.sleep(0.08)
        cdp.tap(cx, cy)
        check(cdp.wait("document.getElementById('zv').getAttribute('data-scale')==='2.00'"), "двойное касание: увеличение 2x")
        time.sleep(0.3)
        z = rect(cdp, "#zimg")
        check(abs(z["w"] - 780) < 2 and abs(z["x"] + z["w"] / 2 - 195) < 3, "2x вокруг места касания, фото чёткое (размер, не растяжение)")
        time.sleep(0.4)
        cdp.tap(cx, cy)
        time.sleep(0.08)
        cdp.tap(cx, cy)
        check(cdp.wait("document.getElementById('zv').getAttribute('data-scale')==='1.00'"), "второе двойное касание: снова всё фото")
        time.sleep(0.4)

        # two fingers spread: zoom; the page itself does not zoom
        cdp.touch("touchStart", [(0, (160, 422)), (1, (230, 422))])
        for k in range(1, 11):
            cdp.touch("touchMove", [(0, (160 - 9 * k, 422)), (1, (230 + 9 * k, 422))])
            time.sleep(0.016)
        cdp.touch("touchEnd", [])
        s2 = scale()
        check(s2 > 2.0, f"два пальца раздвинуты: фото увеличено ({s2:.2f}x)")
        check(cdp.js("!window.visualViewport||Math.abs(window.visualViewport.scale-1)<0.01"),
              "сама страница не масштабируется")
        # one finger moves the enlarged photo
        before = rect(cdp, "#zimg")
        cdp.touch("touchStart", [(0, (200, 400))])
        for k in range(1, 9):
            cdp.touch("touchMove", [(0, (200 + 10 * k, 400 + 6 * k))])
            time.sleep(0.016)
        cdp.touch("touchEnd", [])
        after = rect(cdp, "#zimg")
        check(after["x"] - before["x"] > 40 and after["y"] - before["y"] > 20, "один палец двигает увеличенное фото")
        check(scale() == s2, "перемещение не меняет увеличение")

        # Back button of the phone
        h = cdp.send("Page.getNavigationHistory")
        cdp.send("Page.navigateToHistoryEntry", {"entryId": h["entries"][h["currentIndex"] - 1]["id"]})
        check(cdp.wait("document.getElementById('zv').hidden"), "кнопка «Назад» закрывает просмотр")
        check(cdp.js("document.getElementById('app').getAttribute('data-state')==='ready'"
                     "&&getComputedStyle(document.documentElement).overflow!=='hidden'"),
              "после «Назад» снова «Фото готово» с кнопками, страница та же")

        # the cross
        r = rect(cdp, "#preview")
        cdp.tap(r["x"] + r["w"] / 2, r["y"] + r["h"] / 2)
        check(cdp.wait("!document.getElementById('zv').hidden"), "миниатюра открывает просмотр снова")
        x = rect(cdp, "#zclose")
        cdp.tap(x["x"] + x["w"] / 2, x["y"] + x["h"] / 2)
        check(cdp.wait("document.getElementById('zv').hidden"), "крестик закрывает просмотр")
        time.sleep(0.3)
        check(cdp.send("Page.getNavigationHistory")["currentIndex"] == hist0, "после крестика лишней записи истории нет")
        check(cdp.js("document.getElementById('app').getAttribute('data-state')==='ready'&&!document.getElementById('zimg').getAttribute('src')"),
              "после крестика «Фото готово», большое фото освобождено")

        # less than 30 s of reception left: the line is in the viewer
        cdp.tap(r["x"] + r["w"] / 2, r["y"] + r["h"] / 2)
        check(cdp.wait("!document.getElementById('zv').hidden"), "просмотр открыт для проверки времени")
        check(cdp.js("document.getElementById('zleft').hidden"), "времени много: строки времени в просмотре нет")
        clock.t += phone.IDLE_TTL - 25
        check(cdp.wait("!document.getElementById('zleft').hidden", timeout=8), "меньше 30 секунд: строка времени видна в просмотре")
        zt = cdp.js("document.getElementById('zleft').textContent")
        check(bool(re.fullmatch(r"Приём открыт ещё 0:(2\d|1\d)", zt or "")), f"строка в просмотре: «{zt}»")
        lf = rect(cdp, "#zleft")
        check(lf["y"] + lf["h"] <= 844 and lf["y"] > 600 and lf["w"] < 390, "строка времени внизу просмотра, целиком на экране")
        cdp.send("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Escape", "code": "Escape", "windowsVirtualKeyCode": 27})
        cdp.send("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Escape", "code": "Escape", "windowsVirtualKeyCode": 27})
        check(cdp.wait("document.getElementById('zv').hidden"), "Esc закрывает просмотр")
        clock.t -= phone.IDLE_TTL - 25

        # sending works as before; the page leaving "Photo is ready" closes the viewer by itself
        cdp.tap(r["x"] + r["w"] / 2, r["y"] + r["h"] / 2)
        check(cdp.wait("!document.getElementById('zv').hidden"), "просмотр открыт перед отправкой")
        cdp.js("document.getElementById('sendend').click()")
        check(cdp.wait("document.getElementById('zv').hidden"), "страница ушла с «Фото готово»: просмотр закрылся сам")
        end = time.time() + 10
        while time.time() < end and "photo" not in [k for k, _ in events]:
            app.processEvents()
            time.sleep(0.05)
        check("photo" in [k for k, _ in events], "«Отправить и закончить» после просмотра: фото на компьютере")
        check(cdp.wait("document.getElementById('app').getAttribute('data-state')==='closed'"
                       "&&document.getElementById('app').hasAttribute('data-done')"), "страница: «Готово»")
        time.sleep(0.2)
        check(cdp.send("Page.getNavigationHistory")["currentIndex"] == hist0, "после закрытия просмотра история как до него")
        csp = cdp.js("window.__csp")
        check(csp == [], f"ни одного нарушения политики страницы {csp}")
        errs = [e for e in cdp.events if e.get("method") == "Runtime.exceptionThrown"]
        check(not errs, f"ни одной ошибки скрипта {[e['params']['exceptionDetails'].get('text') for e in errs][:3]}")
    finally:
        if cdp:
            cdp.close()
        rx.stop()
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    test_markup()
    test_browser()
    print(f"ИТОГ: проверок {checks[0]}, сбоев {len(failures)}")
    for f in failures:
        print("  FAIL", f)
    sys.exit(1 if failures else 0)
