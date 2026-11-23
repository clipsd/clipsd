# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""1.36: чтение QR-кода и штрихкода со снимка (clipshot/qr_read.py, qr_ui.py, кнопка «QR» в шапке редактора).

1. Чтение: QR, сгенерированный нашим qr.encode, находится на картинке (одна, две, внутри большого снимка, с текстом на
   русском); пустая картинка и снимок без кода: кодов нет. Нет библиотеки (zxing-cpp): кодов нет, ошибок нет.
2. Ссылки: «Открыть ссылку» только для http и https (с узлом, без пробелов); javascript:, file:, ftp:, mailto:, tel:,
   «голый» адрес без схемы не открываются.
3. Редактор: кнопки «QR» нет, пока кода нет; она появляется, когда код найден (на снимке и после вставки картинки с
   кодом), исчезает вместе с кодом (отмена). Без интернета: сокеты за всё время теста не открывались.
4. Окно «Код на снимке»: текст кода целиком (длинный адрес не обрезается), «Скопировать текст кода» кладёт текст в
   буфер, «Открыть ссылку» сначала спрашивает с адресом целиком, адрес открывается только после «Открыть»; «Не открывать» и
   Esc ничего не открывают; у текста, который не ссылка, кнопки «Открыть ссылку» нет.
5. Обе темы, узкое окно, 12 языков.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/qr_chtenie_test.py   (чтение кода нужно zxing-cpp: pip install zxing-cpp)
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import json
import os
import socket
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
tmp = tempfile.mkdtemp(prefix="clipsd-qrr-")
for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[name] = os.path.join(tmp, name)
_screen = os.path.join(tmp, "screen.json")
with open(_screen, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1600, "height": 1000,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _screen

from PyQt6 import sip  # noqa: E402
from PyQt6.QtCore import QPoint, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QGuiApplication, QImage, QPainter  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

qapp = QApplication(sys.argv)
qapp.setQuitOnLastWindowClosed(False)
from clipshot import app as appmod, i18n, qr, qr_read, qr_ui, sysenv  # noqa: E402
from clipshot.editor import SOFT, EditorWindow  # noqa: E402
from clipshot.i18n import tr  # noqa: E402

failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


# сеть: за время теста ни одного соединения
connects = []
_real_connect = socket.socket.connect
socket.socket.connect = lambda self, *a, **k: connects.append(a) or (_ for _ in ()).throw(OSError("сеть в тесте запрещена"))


def code_image(text, module=5, pad=6):
    m = qr.encode(text)
    n = len(m) + 2 * pad
    img = QImage(n * module, n * module, QImage.Format.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("black"))
    for y, row in enumerate(m):
        for x, dark in enumerate(row):
            if dark:
                p.drawRect((x + pad) * module, (y + pad) * module, module, module)
    p.end()
    return img


def plain(w=900, h=500, color="#336699"):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    return img


def settle(ms=40):
    QTest.qWait(ms)


def wait_for(cond, ms=4000):
    waited = 0
    while not cond() and waited < ms:
        QTest.qWait(40)
        waited += 40
    return cond()


LONG = "https://example.com/very/long/path/" + "segment-" * 16 + "end?token=abc123&from=qr"
URL = "https://example.com/a?b=1"
if not qr_read.available():
    print("нет zxing-cpp, пропуск (необязательная зависимость: pip install zxing-cpp)")
    print("ИТОГ: пропущено, нет zxing-cpp")
    sys.exit(0)

# --- 1. чтение -------------------------------------------------------------------------------------------------------
got = qr_read.find_codes(code_image(URL))
check(len(got) == 1 and got[0].text == URL and got[0].kind == "QRCode" and got[0].link == URL, f"QR найден, ссылка: {got}")
got = qr_read.find_codes(code_image("Привет, мир: 12345"))
check(len(got) == 1 and got[0].text == "Привет, мир: 12345" and got[0].link == "", f"текст на русском читается, не ссылка: {got}")
big = plain(1400, 800)
p = QPainter(big)
p.drawImage(777, 123, code_image(URL, 4))
p.drawImage(60, 400, code_image("second code"))
p.end()
got = qr_read.find_codes(big)
check({c.text for c in got} == {URL, "second code"}, f"два кода внутри большого снимка: {[c.text for c in got]}")
check(got[0].text == URL, "порядок сверху вниз")
got = qr_read.find_codes(code_image(LONG, 3))
check(len(got) == 1 and got[0].text == LONG, "длинный адрес читается целиком")
check(qr_read.find_codes(plain()) == [] and qr_read.find_codes(QImage()) == [] and qr_read.find_codes(None) == [],
      "снимок без кода, пустая и отсутствующая картинки: кодов нет")
noise = QImage(300, 300, QImage.Format.Format_RGB32)
for y in range(300):
    for x in range(300):
        noise.setPixel(x, y, 0xFFFFFF if (x * 7 + y * 13 + x * y) % 5 < 2 else 0)
check(qr_read.find_codes(noise) == [], "шум не принимается за код")
real_zx = qr_read._zx
qr_read._zx = None
check(not qr_read.available() and qr_read.find_codes(code_image(URL)) == [], "нет библиотеки: кодов нет, ошибки нет")
qr_read._zx = real_zx

# --- 2. только http и https --------------------------------------------------------------------------------------------
ok = ["http://example.com", "https://example.com/a?b=1&c=2#x", "HTTPS://Example.COM/Path", "http://localhost:8080/x",
      "http://192.168.0.10:8770/abc", "https://пример.рф/страница", "  https://example.com/pad  "]
bad = ["javascript:alert(1)", "file:///etc/passwd", "ftp://example.com/x", "mailto:a@b.c", "tel:+3591234", "www.example.com",
       "example.com/path", "//evil.example.com", "http://", "https:///path", "http://exa mple.com", "https://a.com/\nb",
       "data:text/html;base64,AAAA", "ms-settings:", "smb://host/share", "intent://x#Intent;end", "", "   ", None, 5]
check(all(qr_read.web_url(u) for u in ok), "http и https открываются: " + str([u for u in ok if not qr_read.web_url(u)]))
check(not any(qr_read.web_url(u) for u in bad), "остальное не открывается: " + str([u for u in bad if qr_read.web_url(u)]))
check(qr_read.web_url("  https://example.com/pad  ") == "https://example.com/pad", "пробелы по краям убираются, адрес не меняется")

# --- 3. редактор ---------------------------------------------------------------------------------------------------------
a = appmod.Clipshot(qapp)
a.save_config = lambda: None
a.notify = lambda *_x: None
a.config.update(theme_chosen=True, tour_done=True, novoe_enabled=False, auto_save=False)
i18n.set_language("ru")
ed = a.open_editor(plain(), None)
settle(200)
check(ed.qr_button.isHidden() and ed.qr_codes == [], "кода нет: кнопки «QR» нет")
check(ed.qr_button.text() == "QR" and ed.qr_button.toolTip() == tr("qr_chtenie.tip"), "у кнопки подпись «QR» и подсказка")
settle(QTest.qWait(0) or 700)
check(ed.qr_button.isHidden(), "после паузы чтения кода по-прежнему нет")
ed.canvas.insert_image(code_image(URL, 5))
check(wait_for(lambda: not ed.qr_button.isHidden()), "вставили картинку с кодом: кнопка «QR» появилась (чтение в потоке)")
check(len(ed.qr_codes) == 1 and ed.qr_codes[0].link == URL, f"в окне записан найденный код: {ed.qr_codes}")
ed.canvas.undo()
check(wait_for(lambda: ed.qr_button.isHidden()), "отмена вставки: кода нет, кнопка исчезла")
ed.canvas.redo()
check(wait_for(lambda: not ed.qr_button.isHidden()), "повтор: кнопка снова есть")
ed.canvas.modified = False
ed.close()
settle()

ed2 = a.open_editor(code_image(URL, 6), None)
check(wait_for(lambda: not ed2.qr_button.isHidden()), "снимок с кодом при открытии: кнопка «QR» появилась")
check(ed2.qr_button.isVisible() and ed2.top_icons.isAncestorOf(ed2.qr_button) or ed2.system_title,
      "кнопка стоит в шапке рядом с «С телефона»")
check(ed2.qr_button.geometry().right() <= ed2.top_icons.width() and ed2.min_content_width() <= ed2.width(),
      "шапка с кнопкой помещается в окно")

# --- 4. окно «Код на снимке» ----------------------------------------------------------------------------------------------
opened = []
real_open = sysenv.open_url
sysenv.open_url = lambda url: opened.append(str(url)) or True
asked = []


def run_confirm(answer):
    """Подменяет exec окна подтверждения: записывает адрес из окна и отвечает «open» или «no»."""
    def fake(self):
        asked.append((self.url, self.address.toPlainText()))
        if answer == "open":
            self.yes.click()
        elif answer == "no":
            self.no.click()
        else:
            self.reject()
        return 0
    qr_ui.OpenLinkConfirm.exec = fake


ed2.canvas.setFocus()
dlg = ed2.show_qr()
settle()
check(dlg is not None and dlg.isVisible() and len(dlg.rows) == 1, "кнопка «QR» открыла окно «Код на снимке»")
check(dlg.title.text() == tr("qr_chtenie.title_one"), "заголовок для одного кода")
code, field, open_b, copy_b = dlg.rows[0]
check(field.toPlainText() == URL and open_b is not None and open_b.text() == tr("qr_chtenie.open")
      and copy_b.text() == tr("qr_chtenie.copy"), "текст кода и обе кнопки на месте")
check(not opened and not asked, "пока ничего не нажато, адрес не открывался и не спрашивался")
copy_b.click()
check(QGuiApplication.clipboard().text() == URL and dlg.status.text() == tr("qr_chtenie.copied"),
      "«Скопировать текст кода»: текст в буфере, строка «Текст кода скопирован»")
for answer in ("no", "esc"):
    run_confirm(answer)
    open_b.click()
    check(len(asked) >= 1 and asked[-1] == (URL, URL) and not opened, f"«Открыть ссылку»: сначала вопрос с адресом целиком, ответ «{answer}»: ничего не открыто")
run_confirm("open")
open_b.click()
check(opened == [URL], f"после «Открыть» адрес открыт ровно один раз: {opened}")
check(not connects, f"сеть не использовалась: {connects}")
dlg.close()
settle()

# длинный адрес: не обрезается ни в окне кода, ни в подтверждении
ed2.qr_codes = [qr_read.Code(LONG, "QRCode", qr_read.web_url(LONG))]
dlg = ed2.show_qr()
settle()
_c, field, open_b, copy_b = dlg.rows[0]
check(field.toPlainText() == LONG and field.document().size().height() <= field.height() + 4,
      f"длинный адрес ({len(LONG)} знаков) виден целиком: высота поля {field.height()}, текста {field.document().size().height():.0f}")
asked.clear()
opened.clear()
run_confirm("no")
open_b.click()
check(asked and asked[-1][1] == LONG, "в подтверждении адрес целиком")
conf = qr_ui.OpenLinkConfirm(None, LONG)
conf.show()
settle()
check(conf.address.toPlainText() == LONG and conf.address.document().size().height() <= conf.address.height() + 4
      and conf.focusWidget() is conf.no and conf.no.isDefault(), "окно подтверждения: адрес целиком, фокус и Enter на «Не открывать»")
conf.close()
dlg.close()

# не ссылки: кнопки «Открыть ссылку» нет, открыть нельзя даже вызовом
bad_codes = [qr_read.Code("javascript:alert(1)", "QRCode", ""), qr_read.Code("file:///etc/passwd", "QRCode", ""),
             qr_read.Code("просто текст", "QRCode", ""), qr_read.Code("4006381333931", "EAN13", "")]
ed2.qr_codes = bad_codes
dlg = ed2.show_qr()
settle()
check(dlg.title.text() == tr("qr_chtenie.title_many", n=4) and all(r[2] is None for r in dlg.rows) and all(r[3] is not None for r in dlg.rows),
      "четыре кода без ссылок: у каждого только «Скопировать текст кода»")
asked.clear()
check(dlg.ask_open("javascript:alert(1)") is False and dlg.ask_open("file:///etc/passwd") is False and not asked and not opened,
      "javascript: и file: не открываются даже прямым вызовом, вопроса нет")
dlg.close()
mixed = [qr_read.Code(URL, "QRCode", URL), qr_read.Code("текст", "QRCode", ""), qr_read.Code("https://b.example/x", "QRCode", "https://b.example/x")]
ed2.qr_codes = mixed
dlg = ed2.show_qr()
settle()
check([r[2] is not None for r in dlg.rows] == [True, False, True], "смесь: кнопка «Открыть ссылку» только у ссылок")
dlg.close()
ed2.qr_codes = []
check(ed2.show_qr() is None, "кодов нет: окно не открывается")
sysenv.open_url = real_open
ed2.canvas.modified = False
ed2.close()
settle()

# --- 5. обе темы, узкое окно -----------------------------------------------------------------------------------------------
def lum(c):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    c = QColor(c)
    return 0.2126 * ch(c.red()) + 0.7152 * ch(c.green()) + 0.0722 * ch(c.blue())


def contrast(x, y):
    hi, lo = sorted((lum(x), lum(y)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


for dark in (False, True):
    bg, fg, hover, icon = SOFT["qr"][1 if dark else 0]
    check(contrast(fg, bg) >= 4.5 and contrast(fg, hover) >= 4.5 and contrast(icon, bg) >= 3.0,
          f"{'тёмная' if dark else 'светлая'} тема: текст «QR» {contrast(fg, bg):.1f}:1, значок {contrast(icon, bg):.1f}:1")
for theme_name in ("pro", "standard"):
    a.config["ui_theme"] = theme_name
    ed3 = a.open_editor(code_image(URL, 6), None)
    check(wait_for(lambda: not ed3.qr_button.isHidden()), f"оформление {theme_name}: кнопка есть")
    ss = ed3.styleSheet()
    check("QToolButton#qrFound" in ss, f"оформление {theme_name}: у кнопки есть стиль")
    ed3.canvas.modified = False
    ed3.close()
    settle()
a.config.pop("ui_theme", None)

# узкое окно: шапка с кнопкой «QR» помещается, окно не шире экрана 1600
a.config["editor_system_title"] = False
ed4 = a.open_editor(code_image(URL, 6), None)
check(wait_for(lambda: not ed4.qr_button.isHidden()), "окно: кнопка есть")
ed4.resize(ed4.minimumWidth(), ed4.height())
settle(120)
need = ed4.min_content_width() + ed4._rim()[0]
check(ed4.width() >= need - 1 and ed4.minimumWidth() >= need - 1 and ed4.minimumWidth() <= 1580,
      f"самое узкое окно с кнопкой «QR»: ширина {ed4.width()}, нужно {need}")
top = ed4.top_icons
kids = [w for w in (ed4.qr_button, ed4.phone_button, ed4.bell_button, ed4.help_button, ed4.settings_button, ed4.language_button) if w.isVisible()]
check(all(top.rect().contains(w.geometry()) for w in kids) and not any(
    kids[i].geometry().intersects(kids[j].geometry()) for i in range(len(kids)) for j in range(i + 1, len(kids))),
      "в самом узком окне кнопки шапки не налезают друг на друга и не вылезают")
ed4.canvas.modified = False
ed4.close()
settle()

# --- 6. 12 языков --------------------------------------------------------------------------------------------------------------
keys = ["qr_chtenie.tip", "qr_chtenie.title_one", "qr_chtenie.open", "qr_chtenie.copy", "qr_chtenie.close", "qr_chtenie.copied",
        "qr_chtenie.confirm_title", "qr_chtenie.confirm_text", "qr_chtenie.confirm_note", "qr_chtenie.confirm_yes",
        "qr_chtenie.confirm_no", "qr_chtenie.not_link"]
sysenv.open_url = lambda url: True
for lang in i18n.LANGUAGES:
    i18n.set_language(lang)
    vals = [tr(k) for k in keys]
    check(all(v and v != k and "{" not in v for v, k in zip(vals, keys)) and "3" in tr("qr_chtenie.title_many", n=3), f"{lang}: строки есть")
    dlg = qr_ui.QrDialog(None, [qr_read.Code(LONG, "QRCode", LONG), qr_read.Code("text", "QRCode", "")])
    dlg.show()
    conf = qr_ui.OpenLinkConfirm(None, LONG)
    conf.show()
    settle(30)
    scr = QGuiApplication.primaryScreen().availableGeometry()
    ok_fit = dlg.width() <= scr.width() and dlg.height() <= scr.height() and conf.width() <= scr.width() and conf.height() <= scr.height()
    btns = [b for r in dlg.rows for b in (r[2], r[3]) if b is not None] + [dlg.close_button, conf.yes, conf.no]
    clipped = [b.text() for b in btns if b.fontMetrics().horizontalAdvance(b.text()) + 20 > b.width()]
    check(ok_fit and not clipped, f"{lang}: окна помещаются на экране, подписи кнопок не обрезаны {clipped}")
    dlg.close()
    conf.close()
i18n.set_language("ru")
sysenv.open_url = real_open
check(not connects, "сеть за весь тест не использовалась")
socket.socket.connect = _real_connect

print("\nИТОГ: " + ("всё хорошо" if not failures else f"{len(failures)} ошибок: {failures}"))
sys.exit(1 if failures else 0)
