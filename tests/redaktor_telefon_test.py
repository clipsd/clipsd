# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Кнопка «С телефона» в редакторе (просьба владельца 21.11.2026).

Кнопка в шапке окна слева от колокольчика: значок телефона, подпись и подсказка теми же строками, что плитка окна
выделения (phone.tile_title, phone.tile_tip); подпись видна и в самом узком окне, окно от кнопки не шире, чем в
1.33.0; при системном заголовке только значок с именем для экранного диктора. Нажатие открывает
окно приёма (сначала напоминание про Wi-Fi, если оно не отключено), окно приёма знает, в какой редактор класть фото.
Фото, присланное настоящим HTTP-запросом на 127.0.0.1, ложится поверх текущего снимка отдельной картинкой (её можно
двигать и масштабировать), нового редактора не открывается. 12 языков: подпись не обрезана, первый ряд помещается.

Сеть: приёмник только на 127.0.0.1, порт выбирает система. Запуск: QT_QPA_PLATFORM=offscreen python3 tests/redaktor_telefon_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import http.client
import json
import os
import re
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
os.environ.pop("CLIPSD_LANG", None)
_cfg = os.path.join(tempfile.mkdtemp(prefix="clipsd-redtel-"), "screen.json")
with open(_cfg, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1280, "height": 720,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _cfg

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QPoint, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QFontMetrics, QImage  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QToolButton  # noqa: E402

app = QApplication(sys.argv)
from clipshot import app as appmod, i18n, phone, phone_ui  # noqa: E402
from clipshot.editor import EditorWindow, PHONE_ICON_W, TOOL_W, soft_colors  # noqa: E402
from clipshot.shapes import IMAGE  # noqa: E402

phone.LISTEN_PORTS = ()   # свободный порт системы, только 127.0.0.1
LOOP = [{"ip": "127.0.0.1", "prefix": 8, "name": "lo-test", "kind": "wifi"}]
LANGS = ("ru", "en", "es", "de", "fr", "it", "pt", "pl", "tr", "uk", "bg", "zh")

failures = []
checks = [0]


def check(cond, msg):
    checks[0] += 1
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def settle(ms=40):
    QTest.qWait(ms)


class Ctx:
    """Программа без значка у часов и без сети, кроме приёмника на 127.0.0.1."""

    def __init__(self, **kw):
        self.config = dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True, **kw)
        self.config["save_dir"] = self.config["auto_save_dir"] = tempfile.mkdtemp(prefix="clipsd-redtel-shots-")
        self.icon = appmod.make_icon()
        self.editors = []
        self.opened = []
        self.phone_calls = []

    def save_config(self):
        pass

    def notify(self, text):
        pass

    def open_editor(self, image, origin):
        self.opened.append(image.size())
        return None

    def open_phone(self, target=None):
        self.phone_calls.append(target)
        return phone_ui.open_phone(self, target)


_real_dialog = phone_ui.PhoneDialog


def _loop_dialog(ctx, target=None, **kw):
    """Окно приёма только на 127.0.0.1 и без проверки сетевого экрана системы."""
    kw.setdefault("candidates", LOOP)
    kw.setdefault("firewall", "")
    return _real_dialog(ctx, target, **kw)


phone_ui.PhoneDialog = _loop_dialog


def image(w, h=300):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor("#ffffff"))
    return img


def jpeg(w, h) -> bytes:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor("#336699"))
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "JPEG")
    return bytes(ba)


def mk(ctx, w):
    ed = EditorWindow(image(w), ctx, QPoint(0, 0))
    ctx.editors.append(ed)
    ed.present()
    settle(60)
    return ed


def done(ctx, ed):
    ed.canvas.modified, ed.exported = False, True
    ed.close()
    if ed in ctx.editors:
        ctx.editors.remove(ed)
    settle(20)


def post_photo(rx, body):
    """Телефон: открыть страницу по коду, взять ключ, отправить фото (настоящий HTTP на 127.0.0.1)."""
    def req(method, path, data=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", rx.port, timeout=5)
        c.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        c.putheader("Host", rx.authority)
        for k, v in (headers or {}).items():
            c.putheader(k, v)
        if data is not None:
            c.putheader("Content-Length", str(len(data)))
        c.endheaders(data)
        r = c.getresponse()
        out = r.read()
        c.close()
        return r.status, out
    st, page = req("GET", f"/{rx.token}")
    m = re.search(rb'id="cfg">(.*?)</script>', page)
    key = json.loads(m.group(1).decode())["key"] if m else ""
    st, _ = req("POST", f"/{rx.token}/photo", body, {"Content-Type": "image/jpeg", "X-ClipSD-Key": key,
                                                     "Origin": f"http://{rx.authority}"})
    rx.wait_idle()
    return st


def contrast(a, b):
    def lum(c):
        def ch(v):
            v /= 255
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
        c = QColor(c)
        return 0.2126 * ch(c.red()) + 0.7152 * ch(c.green()) + 0.0722 * ch(c.blue())
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# --- 1. кнопка есть, рядом с «Вставить», с подписью и подсказкой ---------------------------------------------------
i18n.set_language("ru")
ctx = Ctx()
ed = mk(ctx, 1180)
b = getattr(ed, "phone_button", None)
check(isinstance(b, QToolButton) and b.isVisible() and not b.icon().isNull(), "в редакторе есть кнопка «С телефона» со значком")
row = ed.top_icons.layout()
idx = [row.itemAt(i).widget() for i in range(row.count())]
check(b in idx and ed.bell_button in idx and idx.index(b) < idx.index(ed.bell_button)
      and ed.titlebar is not None and ed.titlebar.isAncestorOf(b), "кнопка в шапке окна, слева от колокольчика")
check(b.text() == "С телефона" and b.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon,
      f"широкое окно: подпись «С телефона» ({b.text()!r})")
check(b.toolTip().startswith("С телефона · Снять камерой или отправить картинку с телефона\n"),
      f"подсказка как у плитки окна выделения: {b.toolTip()!r}")
check(b.accessibleName() == "С телефона" and "камерой" in b.accessibleDescription(), "имя и описание для экранного диктора")
check(b.focusPolicy() == Qt.FocusPolicy.TabFocus, "до кнопки можно дойти клавишей Tab, щелчок фокус у снимка не забирает (М3)")
for dark in (False, True):
    bg, fg, _hover, ic = soft_colors("phone", dark)
    check(contrast(fg, bg) >= 4.5, f"{'тёмная' if dark else 'светлая'}: подпись на кнопке {contrast(fg, bg):.1f}:1 (норма 4,5)")
    check(contrast(ic, bg) >= 3.0, f"{'тёмная' if dark else 'светлая'}: значок на кнопке {contrast(ic, bg):.1f}:1 (норма 3)")
done(ctx, ed)

# узкое окно: подпись остаётся, окно не шире, чем без кнопки
ed = mk(ctx, 300)
b = ed.phone_button
check(b.isVisible() and b.text() == "С телефона", "самое узкое окно: кнопка с подписью")
check(ed.panel.layout().minimumSize().width() <= ed.panel.width()
      and ed.titlebar.layout().minimumSize().width() <= ed.titlebar.width(), "узкое окно: шапка и первый ряд помещаются")
check(ed.min_content_width() == max(ed._need_row1[-1], ed._need_row2[-1], ed._need_bottom[1]),
      f"кнопка не делает окно шире: самое узкое по панелям ({ed.min_content_width()})")
done(ctx, ed)

# системный заголовок: группа в первом ряду, кнопка значком
ctx_sys = Ctx(editor_system_title=True)
ed = mk(ctx_sys, 1180)
b = ed.phone_button
check(ed.titlebar is None and b.isVisible() and b.text() == "" and b.width() == PHONE_ICON_W and b.accessibleName() == "С телефона"
      and b.toolTip().startswith("С телефона · "), "системный заголовок: значок без подписи, название в подсказке и для диктора")
done(ctx_sys, ed)

# --- 2. нажатие открывает окно приёма для этого редактора -----------------------------------------------------------
ctx = Ctx()
ed = mk(ctx, 900)
ed.phone_button.click()
settle(80)
note = [w for w in QApplication.topLevelWidgets() if isinstance(w, phone_ui.WifiNote) and w.isVisible()]
check(ctx.phone_calls == [ed] and len(note) == 1, "первое нажатие: напоминание «одна сеть Wi-Fi», вызов с этим редактором")
for w in note:
    w.close()
settle(40)
ctx.config[phone_ui.CONFIG_HIDE_NOTE] = True
ed.phone_button.click()
settle(120)
win = phone_ui.current_window()
check(win is not None and win.isVisible() and win.receiver is not None and win.target is ed,
      "нажатие открывает окно приёма с кодом, фото пойдёт в этот редактор")
check(win is not None and win.receiver is not None and win.receiver.host == "127.0.0.1", "приёмник теста только на 127.0.0.1")

# --- 3. принятое фото ложится в текущий снимок отдельной картинкой -------------------------------------------------
before = len(ed.canvas.shapes)
st = post_photo(win.receiver, jpeg(400, 300)) if win is not None and win.receiver is not None else 0
settle(200)
shapes = ed.canvas.shapes
new = shapes[before:] if len(shapes) > before else []
check(st == 200 and len(new) == 1 and new[0].kind == IMAGE, f"фото с телефона легло в снимок картинкой (ответ {st})")
check(bool(new) and ed.canvas.selected is new[0], "картинка выделена: её сразу можно двигать и тянуть за углы")
check(not ctx.opened and ctx.editors == [ed], "нового редактора не открылось")
check(ed.canvas.modified, "снимок отмечен изменённым (вставку можно отменить)")
ed.canvas.undo()
check(len(ed.canvas.shapes) == before, "«Отменить» убирает вставленное фото")
w2 = phone_ui.current_window()
if w2 is not None:
    w2.close()
settle(80)
check(phone_ui.current_window() is None or not phone_ui.current_window().isVisible(), "окно приёма закрыто")
done(ctx, ed)

# --- 4. 12 языков: подпись не обрезана, первый ряд помещается ------------------------------------------------------
for lang in LANGS:
    i18n.set_language(lang)
    ctx = Ctx()
    ed = mk(ctx, 1180)
    b = ed.phone_button
    label = i18n.tr("phone.tile_title")
    fm = QFontMetrics(b.font())
    need = fm.horizontalAdvance(label) + b.iconSize().width()
    check(b.text() == label and b.width() >= need + 10, f"{lang}: «{label}» целиком ({b.width()} ≥ {need + 10})")
    check(ed.titlebar.layout().minimumSize().width() <= ed.titlebar.width()
          and b.geometry().right() < ed.bell_button.geometry().left(), f"{lang}: шапка помещается, кнопки не налезают")
    done(ctx, ed)
    ed = mk(ctx, 300)
    b = ed.phone_button
    fits = ed.titlebar.layout().minimumSize().width() <= ed.titlebar.width()
    check(b.isVisible() and fits and (b.text() == label or b.width() == PHONE_ICON_W),
          f"{lang}: узкое окно, кнопка на месте ({'с подписью' if b.text() else 'значком'})")
    check(ed.width() <= 1280, f"{lang}: узкое окно не шире экрана 1280 ({ed.width()})")
    done(ctx, ed)

phone_ui.PhoneDialog = _real_dialog
phone_ui.stop_all()
i18n.set_language("ru")
print(f"ИТОГ: проверок {checks[0]}, провалено: {len(failures)}")
sys.exit(1 if failures else 0)
