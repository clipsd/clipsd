# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Код в окне «Скриншот/фото с телефона» крупнее и кнопка «Увеличить» (просьба владельца 22.11.2026).

1. Код в окне не меньше 240 логических точек (целое число точек на модуль, тихая зона 4 модуля), на экране 1366 x 768.
   Код настоящий: картинка совпадает с матрицей qr.encode (по центру каждого модуля), тихая зона белая.
2. 12 языков: окно с кодом целиком на экране 1366 x 768 (ширина, высота), адрес для ручного ввода не обрезан даже
   длинным, подпись кнопки есть и переведена.
3. Кнопка «Увеличить» (со значком) открывает крупное окно с тем же адресом: код около 70 % меньшей стороны экрана,
   целое число точек на модуль, подпись «Наведите камеру телефона на код»; закрывается Esc, щелчком и крестиком.
4. «Новый код» и обновление кода: крупное окно показывает новый адрес. Телефон подключился, срок истёк, окно приёма
   закрылось: крупное окно закрывается само.
5. Маленький экран (по высоте): код сжимается ступенями, но не меньше 148 точек (как было), окно не растёт.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/phone_qr_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import json
import os
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
os.environ.pop("CLIPSD_LANG", None)
_cfg = os.path.join(tempfile.mkdtemp(prefix="clipsd-qr-"), "screen.json")
with open(_cfg, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1366, "height": 768,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _cfg

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
from clipshot import i18n, phone, phone_ui, qr
from clipshot.i18n import tr

phone.LISTEN_PORTS = ()
failures = []
LOOP = [{"ip": "127.0.0.1", "prefix": 8, "name": "lo-test", "kind": "wifi"}]
SCREEN_W, SCREEN_H = 1366, 768


def check(cond, msg):
    if not cond:
        failures.append(msg)
        print("FAIL " + msg)


def settle(n=5):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(10)


class Ctx:
    def __init__(self):
        self.config = {phone_ui.CONFIG_HIDE_NOTE: True}

    def save_config(self):
        pass

    def notify(self, text):
        pass


def window():
    win = phone_ui.PhoneDialog(Ctx(), None, candidates=LOOP)
    check(win.start(), "приём открылся")
    win.open_centered()
    settle()
    return win


def gone(w):
    """Окно закрыто (оно с WA_DeleteOnClose: объект может быть уже удалён)."""
    try:
        return not w.isVisible()
    except RuntimeError:
        return True


def need_height(w):
    lay = w.layout()
    lay.activate()
    return lay.totalHeightForWidth(w.width())


def matches_matrix(pixmap, url):
    """Картинка = матрица qr.encode: цвет по центру каждого модуля; тихая зона в 4 модуля белая."""
    m = qr.encode(url)
    n = len(m) + 8
    img = pixmap.toImage()
    px = img.width() // n
    if px * n != img.width() or img.height() != img.width():
        return False
    for y in range(n):
        for x in range(n):
            dark = 4 <= x < n - 4 and 4 <= y < n - 4 and m[y - 4][x - 4]
            c = img.pixelColor(x * px + px // 2, y * px + px // 2)
            if (c.lightness() < 128) != bool(dark):
                return False
    return True


# --- 1: размер и читаемость -------------------------------------------------------------------------------------
i18n.set_language("ru")
win = window()
url = win.receiver.url
pm = win.qr_label.pixmap()
side = pm.deviceIndependentSize().width()
n_modules = len(qr.encode(url)) + 8
check(side >= 240, f"код в окне не меньше 240 точек ({side})")
check(side == int(side) and int(side) % n_modules == 0, f"целое число точек на модуль ({side} / {n_modules})")
check(win.qr_label.width() >= 240 and win.qr_label.height() >= 240, "поле кода не меньше 240 точек")
check(matches_matrix(pm, url), "код совпадает с матрицей qr.encode, тихая зона белая")
check(win.address.text() == url.split("://", 1)[1], "адрес для ручного ввода на месте")
check(win.zoom_btn.text() == "Увеличить" and not win.zoom_btn.icon().isNull(), "под кодом кнопка «Увеличить» со значком")
check(win.zoom_btn.height() <= 36 and win.zoom_btn.y() >= win.qr_label.y() + win.qr_label.height() - 1,
      "кнопка маленькая и стоит под кодом")
check(win.zoom_btn.x() >= win.qr_label.x() - 1 and win.zoom_btn.x() + win.zoom_btn.width() <= win.qr_label.x() + win.qr_label.width() + 1,
      "кнопка под кодом, не шире его")
check(win.width() <= SCREEN_W and need_height(win) <= SCREEN_H and win.height() >= need_height(win),
      f"окно целиком на экране 1366 x 768 ({win.width()} x {win.height()}, нужно {need_height(win)})")
check(win.address.sizeHint().width() <= win.address.width(), "адрес не обрезан")

# --- 3: крупное окно --------------------------------------------------------------------------------------------
win.zoom_btn.click()
settle()
z = win.zoom_win
check(z is not None and z.isVisible(), "«Увеличить» открывает крупное окно")
check(z.url == win.receiver.url, "в крупном окне тот же адрес")
zp = z.qr_label.pixmap()
zside = zp.deviceIndependentSize().width()
want = min(SCREEN_W, SCREEN_H) * phone_ui.ZOOM_SHARE
check(want - zside < n_modules and zside <= want, f"крупный код около 70 % меньшей стороны экрана ({zside} из {want:.0f})")
check(zside > side * 1.8, f"крупный код заметно больше, чем в окне ({zside} против {side})")
check(matches_matrix(zp, win.receiver.url), "крупный код совпадает с матрицей, тихая зона белая")
check(z.caption.text() == "Наведите камеру телефона на код", "подпись под крупным кодом")
check(z.width() <= SCREEN_W and z.height() <= SCREEN_H, f"крупное окно на экране ({z.width()} x {z.height()})")
check(z.palette().window().color().name() == "#ffffff" or "#ffffff" in z.styleSheet(), "фон белый")
win.zoom_btn.click()
settle()
check(win.zoom_win is z, "повторное «Увеличить» не открывает второе окно")
QTest.keyClick(z, Qt.Key.Key_Escape)
settle()
check(win.zoom_win is None and gone(z), "Esc закрывает крупное окно")
win.zoom_btn.click()
settle()
z = win.zoom_win
QTest.mouseClick(z.qr_label, Qt.MouseButton.LeftButton)
settle()
check(win.zoom_win is None and gone(z), "щелчок по коду закрывает крупное окно")
win.zoom_btn.click()
settle()
z = win.zoom_win
z.close_b.click()
settle()
check(win.zoom_win is None and gone(z), "крестик закрывает крупное окно")
check(win.isVisible(), "окно приёма осталось")

# --- 4: обновление и закрытие -----------------------------------------------------------------------------------
win.zoom_btn.click()
settle()
z = win.zoom_win
old = win.receiver.url
win.new_code()
settle()
check(win.receiver.url != old, "новый код: адрес сменился")
check(win.zoom_win is z and z.url == win.receiver.url and z.isVisible(), "«Новый код»: крупное окно показывает новый адрес")
check(matches_matrix(z.qr_label.pixmap(), win.receiver.url), "крупный код перерисован под новый адрес")
win._on_event("connected", {"ip": "192.168.1.40"})
settle()
check(win.zoom_win is None and gone(z), "телефон подключился: крупное окно закрылось")
check(not win.zoom_btn.isVisible(), "кода больше нет: кнопки тоже")
win.zoom_btn.click()
settle()
check(win.zoom_win is None, "после подключения «Увеличить» ничего не открывает")
win.close()
settle()

win = window()
win.zoom_btn.click()
settle()
z = win.zoom_win
win._on_event("closed", {"reason": "expired"})
settle()
check(win.zoom_win is None and gone(z), "срок истёк: крупное окно закрылось")
win.close()
settle()

win = window()
win.zoom_btn.click()
settle()
z = win.zoom_win
check(z is not None and z.isVisible(), "крупное окно перед закрытием окна приёма")
win.close()
settle()
check(gone(z) and win.zoom_win is None, "окно приёма закрыто: крупное окно закрылось")
check(win.receiver is None, "приём остановлен")

# --- 2: 12 языков, длинный адрес ---------------------------------------------------------------------------------
for lang in i18n.LANGUAGES:
    i18n.set_language(lang)
    win = window()
    sh = win.zoom_btn.text()
    check(sh and not sh.startswith("phone.") and win.zoom_btn.toolTip() and not win.zoom_btn.toolTip().startswith("phone."),
          f"{lang}: кнопка «{sh}» переведена")
    check(tr("phone.zoom_caption") and not tr("phone.zoom_caption").startswith("phone."), f"{lang}: подпись крупного окна переведена")
    check(win.qr_label.pixmap().deviceIndependentSize().width() >= 240, f"{lang}: код не меньше 240 точек")
    check(win.width() <= SCREEN_W and need_height(win) <= SCREEN_H and win.height() >= need_height(win),
          f"{lang}: окно с кодом целиком на экране 1366 x 768 ({win.width()} x {need_height(win)})")
    check(win.title.height() >= win.title.heightForWidth(win.title.width()), f"{lang}: заголовок виден целиком")
    win.address.setText("192.168.100.200:8765/abcd2345")   # самый длинный адрес
    win.address.adjustSize()
    right_edge = win.address.mapTo(win, win.address.rect().topRight()).x()
    check(win.address.sizeHint().width() <= win.address.width() or right_edge <= win.width(),
          f"{lang}: длинный адрес помещается ({win.address.sizeHint().width()})")
    win._no_phone_yet()   # 20 с без телефона: открылась подсказка, кнопка «Увеличить» остаётся
    settle(30)
    check(win.hint.isVisible() and win.zoom_btn.isVisible() and win.zoom_btn.visibleRegion().boundingRect().height() > 0,
          f"{lang}: с подсказкой кнопка «Увеличить» на месте")
    check(win.qr_label.pixmap().deviceIndependentSize().width() >= 148 and need_height(win) <= SCREEN_H
          and win.height() >= need_height(win), f"{lang}: окно с подсказкой целиком на экране 1366 x 768 ({win.height()})")
    win.collapse_hint()
    settle(30)
    check(win.qr_label.pixmap().deviceIndependentSize().width() >= 240, f"{lang}: подсказка свернулась, код снова крупный")
    win.zoom_btn.click()
    settle()
    zz = win.zoom_win
    check(zz is not None and zz.width() <= SCREEN_W and zz.height() <= SCREEN_H
          and zz.caption.height() >= zz.caption.heightForWidth(zz.caption.width()), f"{lang}: крупное окно целиком, подпись видна")
    win.close()
    settle()
i18n.set_language("ru")

# --- 5: маленький экран ------------------------------------------------------------------------------------------
class SmallScreen:
    def availableGeometry(self):
        return QRect(0, 0, 911, 512)   # 1366 x 768 при масштабе 150 %


win = window()
win.screen = lambda: SmallScreen()
win.new_code()
settle()
small = win.qr_label.pixmap().deviceIndependentSize().width()
check(small == 4 * n_modules, f"на низком экране код сжимается до прежних 148 точек ({small})")
check(win.height() <= 768, "окно не растёт сверх размера экрана")
win.close()
settle()

print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено {len(failures)}")
sys.exit(1 if failures else 0)
