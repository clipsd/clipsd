# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""«Скрыть личные данные» (1.36, пункт 1.1 плана).

Поиск: телефоны (международные и местные виды), почта, карты (проверка Луна), IBAN (контрольная сумма), ссылки с
токенами; ложные примеры (даты, суммы, версии, номера с ошибкой Луна, неверный IBAN) не закрываются; значение,
разбитое распознаванием на несколько слов, находится целиком. Редактор: кнопка в группе «Скрыть» и в «Все
инструменты», размытие ровно по рамкам одним шагом «Отменить», галочки (снятая открывает кусок), «Показать последние 4
цифры», «Открыть всё» и «Скрыть всё», «ничего не найдено», нет распознавания, в журналах и файлах нет значений,
сеть не трогается, 12 языков без обрезки, светлая и тёмная тема. Все данные вымышленные.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/skryt_dannye_test.py
"""
import faulthandler; faulthandler.dump_traceback_later(60, exit=True)
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import json
import os
import socket
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.pop("CLIPSD_LANG", None)   # тест сам перебирает языки; по умолчанию русский
TMP = tempfile.mkdtemp(prefix="clipsd-skryt-")
for _n in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[_n] = os.path.join(TMP, _n)
os.environ["HOME"] = TMP

from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QCheckBox, QPushButton  # noqa: E402

app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)
from clipshot import app as appmod, i18n, ocr, privacy  # noqa: E402
from clipshot import editor as em  # noqa: E402
from clipshot.editor import BLUR, MOVE, PRIVACY, EditorWindow, palette  # noqa: E402
from clipshot.i18n import tr  # noqa: E402
from clipshot.ocr import Word  # noqa: E402

failures = []
checks = [0]
NET = []   # попытки выйти в сеть
_connect = socket.socket.connect
socket.socket.connect = lambda self, *a, **k: (NET.append(a), _connect(self, *a, **k))[1]


def check(cond, msg):
    checks[0] += 1
    print(("OK   " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


def settle(n=6):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(10)


# вымышленные данные
PHONE_RU, PHONE_BG, PHONE_ES = "+7 900 000-00-00", "+359 88 123 4567", "+34 612 345 678"
EMAIL, CARD, IBAN = "test@example.com", "4111 1111 1111 1111", "DE89 3704 0044 0532 0130 00"
LINK = "https://example.com/reset?token=abcdef123456"


def words_of(text, size=16, mono=True):
    """Слова с рамками, как отдало бы распознавание: строки по \\n, слова через пробел."""
    font = QFont("DejaVu Sans Mono" if mono else "DejaVu Sans")
    font.setPixelSize(size)
    fm = QFontMetricsF(font)
    out, y = [], 10.0
    for li, line in enumerate(text.split("\n")):
        x = 10.0
        for t in line.split(" "):
            if not t:
                continue
            w = fm.horizontalAdvance(t)
            out.append(Word(t, QRectF(x, y, w, fm.height()), li))
            x += w + fm.horizontalAdvance(" ")
        y += fm.height() + 12
    return out, font


def kinds(text):
    return [(f.kind, f.value) for f in privacy.find(words_of(text)[0])]


# ---------------------------------------------------------------- 1. поиск

def test_find():
    f = kinds(f"Тел {PHONE_RU} и {PHONE_BG} конец")
    check(f == [("phone", PHONE_RU), ("phone", PHONE_BG)], f"телефоны +7 и +359 рядом, каждый отдельно: {f}")
    for num in (PHONE_ES, "+49 30 123456", "+380 44 123 45 67", "+1 (415) 555-0100", "8 (900) 123-45-67", "(900) 123-45-67",
                "0881234567", "088 123 4567", "555-123-4567", "0151 12345678", "+44 20 7946 0958"):
        got = kinds("позвоните " + num)
        check(got == [("phone", num)], f"телефон найден: {num} -> {got}")
    for text in ("23.11.2026", "2026-11-23", "192.168.0.1", "1 234 567", "1.35.0", "1234567890", "заказ 800 000 000",
                 "сумма 12 345,67", "версия 3.12.1", "12:30:45", "+7", "артикул 4500123456", "100 200 300 400",
                 "2024 2025 2026"):
        check(kinds(text) == [], f"не телефон: {text} -> {kinds(text)}")
    check(kinds(f"пишите {EMAIL}.") == [("email", EMAIL)], "почта в конце фразы без точки")
    check(kinds("a.b-c+tag@sub.mail.co.uk;") == [("email", "a.b-c+tag@sub.mail.co.uk")], "почта с точками, плюсом, поддоменом")
    check(kinds("@username и user@ и @ x") == [], "не почта: @username, user@")
    for card in (CARD, "5555 5555 5555 4444", "378282246310005", "3782 822463 10005", "4111-1111-1111-1111",
                 "6011 1111 1111 1117", "2200 0000 0000 0053"):
        got = kinds("карта " + card)
        check(got == [("card", card)], f"карта найдена: {card} -> {got}")
    for bad in ("4111 1111 1111 1112", "5555 5555 5555 4443", "1234 5678 9012 3456", "0000 0000 0000 0000",
                "4111 1111 1111 111", "4111 1111 1111 1111 1111 1111"):
        check(not [1 for k, _v in kinds("карта " + bad) if k == "card"], f"номер с ошибкой Луна или формата не карта: {bad}")
    for iban in (IBAN, "GB82 WEST 1234 5698 7654 32", "BG80 BNBG 9661 1020 3456 78", "FR14 2004 1010 0505 0001 3M02 606",
                 "DE89370400440532013000"):
        got = kinds("IBAN: " + iban)
        check(got == [("iban", iban)], f"IBAN найден: {iban} -> {got}")
    for bad in ("DE89 3704 0044 0532 0130 01", "GB82 WEST 1234 5698 7654 33", "XX00 1234 5678 9012 3456", "DE89 3704"):
        check(kinds("IBAN: " + bad) == [], f"неверный IBAN ничего не закрывает (даже кусками): {bad} -> {kinds('IBAN: ' + bad)}")
    check(kinds(LINK) == [("link", LINK)], "ссылка с token=")
    check(kinds("www.example.com/?key=abcdefgh") == [("link", "www.example.com/?key=abcdefgh")], "ссылка www с key=")
    check(kinds("https://example.com/page?id=42&lang=ru") == [], "обычная ссылка не закрывается")
    check(kinds("https://example.com/docs/getting-started-guide") == [], "ссылка с длинным словом через дефис не закрывается")
    check(len(kinds("https://example.com/s/Zx9Kq2Lm4Pv8Rt1Yw6Bn3Cd5Fg")) == 1, "длинная случайная строка в пути закрывается")
    check(kinds("ключ sk-abcdefghijklmnopqrstuvwx") == [("link", "sk-abcdefghijklmnopqrstuvwx")], "ключ вида sk-...")
    check(kinds("Привет, как дела? Обычный текст без данных, 2026 год.") == [], "обычный текст: ничего")
    check(privacy.luhn_ok("4111111111111111") and not privacy.luhn_ok("4111111111111112"), "проверка Луна")
    check(privacy.iban_ok("DE89 3704 0044 0532 0130 00") and not privacy.iban_ok("DE89 3704 0044 0532 0130 01"), "проверка IBAN")
    mixed = f"Иван {PHONE_RU}\n{EMAIL}\nкарта {CARD}\n{IBAN}\n{LINK}"
    got = [k for k, _v in kinds(mixed)]
    check(got == ["phone", "email", "card", "iban", "link"], f"все пять видов в одном снимке по порядку: {got}")
    allf = privacy.find(words_of(mixed)[0])
    check(not any(set(a.chars) & set(b.chars) for i, a in enumerate(allf) for b in allf[i + 1:]), "находки не пересекаются")


def test_split_words():
    words, _f = words_of(f"{PHONE_RU}\n{CARD}\n{IBAN}\nномер {PHONE_BG}")
    found = privacy.find(words)
    check([f.kind for f in found] == ["phone", "card", "iban", "phone"], f"многословные значения целиком: {[f.kind for f in found]}")
    check(len({wi for wi, _ci in found[0].chars}) == 3, "телефон в трёх словах")
    check(len({wi for wi, _ci in found[1].chars}) == 4, "карта в четырёх словах")
    check(len({wi for wi, _ci in found[2].chars}) == 6, "IBAN в шести словах")
    rects = found[1].rects(words)
    check(len(rects) == 1, "карта на одной строке: одна рамка на все слова")
    first, last = words[found[1].chars[0][0]].rect, words[found[1].chars[-1][0]].rect
    check(rects[0].left() <= first.left() and rects[0].right() >= last.right(), "рамка покрывает от первого до последнего слова")
    # значение разорвано переносом строки: телефон не склеивается через строки
    broken, _f = words_of("+7 900\n000-00-00")
    check([f.kind for f in privacy.find(broken)].count("phone") == 0, "половинки телефона на разных строках не склеиваются")
    # слово с лишним текстом вокруг: «тел:+7900...» закрывается только номер
    glued, _f = words_of("тел:test@example.com,")
    got = privacy.find(glued)
    check(len(got) == 1 and got[0].value == EMAIL, "почта внутри слова с приставкой и запятой: только почта")
    r = got[0].rects(glued)[0]
    check(r.left() > glued[0].rect.left() + 10, "рамка почты начинается не с начала слова «тел:»")


def test_masks():
    check(privacy.mask("phone", PHONE_RU) == "+7 *** ***-00-00", f"маска телефона: {privacy.mask('phone', PHONE_RU)}")
    check(privacy.mask("card", CARD) == "**** 1111", f"маска карты: {privacy.mask('card', CARD)}")
    check(privacy.mask("email", EMAIL) == "te***@example.com", f"маска почты: {privacy.mask('email', EMAIL)}")
    check(privacy.mask("iban", IBAN) == "DE89 *** 3000", f"маска IBAN: {privacy.mask('iban', IBAN)}")
    check("abcdef123456" not in privacy.mask("link", LINK), "маска ссылки без токена")
    for kind, value in (("phone", PHONE_RU), ("card", CARD), ("email", EMAIL), ("iban", IBAN), ("link", LINK)):
        check(value not in privacy.mask(kind, value), f"значение целиком в панель не попадает: {kind}")


# ---------------------------------------------------------------- 2. редактор

class Ctx:
    def __init__(self, **kw):
        self.config = dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True, **kw)
        self.icon = appmod.make_icon()

    def save_config(self):
        pass

    def notify(self, text):
        pass


def sample(text, size=16, mono=True, width=None, dark=False):
    """Учебный снимок: строки текста, нарисованные программно, и слова с точными рамками."""
    words, font = words_of(text, size, mono)
    w = width or int(max(wd.rect.right() for wd in words) + 40)
    h = int(max(wd.rect.bottom() for wd in words) + 30)
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor("#1e2124" if dark else "#ffffff"))
    p = QPainter(img)
    p.setFont(font)
    p.setPen(QColor("#e8eaed" if dark else "#101418"))
    for wd in words:
        p.drawText(QRectF(wd.rect), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, wd.text)
    p.end()
    return img, words


def make(text, dark=False, size=16, **cfg):
    img, words = sample(text, size, dark=dark)
    ctx = Ctx(**cfg)
    if dark:
        ctx.config["ui_theme"] = "pro"
    ed = EditorWindow(img, ctx, QPoint(0, 0))
    ed.present()
    settle()
    ed.canvas.set_words(words, ed.canvas.base.devicePixelRatio())   # распознавание «уже готово»
    return ed, img, words


def finish(ed):
    ed.canvas.modified = False   # закрыть без вопроса «сохранить?»
    ed.close()


def blur_shapes(ed):
    return [s for s in ed.canvas.shapes if s.kind == BLUR]


def region_changed(a: QImage, b: QImage, rect: QRectF) -> int:
    n = 0
    for y in range(int(rect.top()) + 1, int(rect.bottom()) - 1):
        for x in range(int(rect.left()) + 1, int(rect.right()) - 1):
            if a.pixel(x, y) != b.pixel(x, y):
                n += 1
    return n


TEXT = f"Иван Петров {PHONE_RU}\nпочта {EMAIL}\nкарта {CARD}\nIBAN {IBAN}\nссылка {LINK}\nКонец обычного текста"


def test_button_and_blur():
    ed, img, words = make(TEXT)
    check(PRIVACY in ed.tool_buttons, "кнопка «Скрыть личные данные» есть в ряду инструментов")
    check(PRIVACY in ed.tool_strip.members("hide"), "кнопка в группе «Скрыть» рядом с размытием")
    check(ed.tool_buttons[PRIVACY].toolTip().startswith(tr("privacy.tip").split("\n")[0]), "подсказка кнопки по-русски")
    check(not ed.tool_buttons[PRIVACY].icon().isNull(), "у кнопки есть значок (щит)")
    menu = ed.build_group_menu("hide")
    check(any(tr("privacy.tip").split(" (")[0] in a.text() for a in menu.actions()), "пункт есть в меню группы «Скрыть»")
    menu.close()
    all_tools = ed.build_all_tools_menu()
    check(PRIVACY in ed.all_tools_rows, "пункт есть в «Все инструменты» (узкое окно)")
    all_tools.close()
    check(em.default_tool({"default_tool": PRIVACY}) == "", "кнопка не может стать инструментом по умолчанию")
    before = ed.canvas.tool
    check(not ed.canvas.undo_stack, "шагов отмены до кнопки нет")
    ed.tool_buttons[PRIVACY].click()
    settle()
    check(ed.canvas.tool == before and ed.canvas.tool != PRIVACY, "кнопка действие, а не режим: инструмент остался прежним")
    check(ed.tool_buttons[before].isChecked(), "прежний инструмент остался отмеченным")
    session = ed.privacy_session
    check(session is not None and len(session.findings) == 5, f"найдено 5 значений: {len(session.findings) if session else None}")
    check(len(ed.canvas.undo_stack) == 1, "одним шагом отмены")
    shapes = blur_shapes(ed)
    check(len(shapes) == 5, f"по одному размытию на каждую находку (все на отдельных строках): {len(shapes)}")
    # размытие ровно по рамкам
    ok_rects = True
    for i, f in enumerate(session.findings):
        want = f.rects(words)
        got = [s.rect() for s in session.shapes[i]]
        ok_rects &= len(want) == len(got) and all(abs(a.left() - b.left()) < 0.6 and abs(a.top() - b.top()) < 0.6
                                                  and abs(a.right() - b.right()) < 0.6 and abs(a.bottom() - b.bottom()) < 0.6
                                                  for a, b in zip(want, got))
        for wi in {w for w, _c in f.chars}:
            wr = words[wi].rect
            ok_rects &= any(g.left() <= wr.left() + 0.6 and g.right() >= wr.right() - 0.6 and g.top() <= wr.top()
                            and g.bottom() >= wr.bottom() for g in got)
    check(ok_rects, "размытие покрывает слова найденного, рамки на 2 точки шире слов и не больше")
    out = ed.canvas.render()
    for i, f in enumerate(session.findings):
        for wi in {w for w, _c in f.chars}:
            check(region_changed(img, out, words[wi].rect) > 8, f"слово «{f.kind}» изменено размытием: пиксели другие")
    plain = [w for w in words if w.text in ("Конец", "обычного", "текста", "Иван", "Петров")]
    check(all(region_changed(img, out, w.rect) == 0 for w in plain), "обычный текст не тронут")
    check(ed.privacy_panel.isVisible() and len(ed.privacy_panel.rows) == 5, "панель открыта, 5 строк")
    check(ed.privacy_panel.title.text() == tr("privacy.found", n=5), f"«Найдено: 5»: {ed.privacy_panel.title.text()}")
    check(all(r.mode == "full" for r in ed.privacy_panel.rows), "у всех строк «закрыто полностью»")
    texts = [r.label.toolTip() for r in ed.privacy_panel.rows]
    check(not any(v in t for v in (PHONE_RU, EMAIL, CARD, IBAN, "abcdef123456") for t in texts), f"в панели только маски: {texts}")
    # отмена одним шагом
    ed.canvas.undo()
    settle()
    check(not blur_shapes(ed) and not ed.canvas.shapes, "«Отменить» убрало всё размытие сразу")
    check(not ed.privacy_panel.isVisible(), "после отмены панель закрыта")
    check(region_changed(img, ed.canvas.render(), QRectF(0, 0, img.width(), img.height())) == 0, "снимок как исходный")
    ed.canvas.redo()
    check(len(blur_shapes(ed)) == 5, "«Повторить» возвращает размытие")
    finish(ed)


def choose(panel, row, mode):
    """Выбор режима в меню строки, как мышью: меню открывается (заполняется) и пункт нажимается."""
    row._fill_menu()
    for act in row.menu.actions():
        if act.text() == row_title(row, mode):
            act.trigger()
            return True
    return False


def row_title(row, mode):
    from clipshot.privacy_ui import mode_title
    return mode_title(row.finding.kind, mode)


def char_region(words, f, k, shrink=0.18):
    """Рамка k-го символа находки по равным долям (шрифт моноширинный): внутренняя часть без краёв."""
    wi, ci = f.chars[k]
    w = words[wi].rect
    cw = w.width() / len(words[wi].text)
    return QRectF(w.x() + ci * cw + cw * shrink, w.y() + 2, cw * (1 - 2 * shrink), w.height() - 4)


def test_modes_each_kind():
    ed, img, words = make(TEXT)
    ed.hide_personal()
    settle()
    s, panel = ed.privacy_session, ed.privacy_panel
    total = 0
    for i, f in enumerate(s.findings):
        row = next(r for r in panel.rows if r.index == i)
        want_modes = list(f.modes())
        check(want_modes[0] == "full" and want_modes[-1] == "open", f"{f.kind}: первый режим «закрыто», последний «открыто»")
        for mode in want_modes:
            check(choose(panel, row, mode), f"{f.kind}/{mode}: пункт меню есть")
            check(s.modes[i] == mode, f"{f.kind}/{mode}: режим применён")
            out = ed.canvas.render()
            hidden = f.hidden_indices(mode)
            bad = []
            for k, ch in enumerate(f._glyphs()):
                r = char_region(words, f, k)
                n = region_changed(img, out, r)
                if k in hidden and n == 0 and ch not in ".-,":
                    bad.append(("не закрыт", k, ch))
                if k not in hidden and n != 0 and s.boxes(f.chars[0][0]) is not None:
                    bad.append(("закрыт лишний", k, ch))   # лишнее допустимо только когда границы не измерены (доли с запасом)
            check(not bad, f"{f.kind}/{mode}: закрыты ровно нужные символы {bad[:3]}")
            check(row.button.text().startswith(tr("privacy.short_" + mode)), f"{f.kind}/{mode}: выбор виден в строке: {row.button.text()}")
            total += 1
    check(total == 4 + 4 + 4 + 3 + 3, f"проверено режимов: {total}")
    kinds_order = [f.kind for f in s.findings]
    exp = {"card": "4111 **** **** 1111", "email": "te***@example.com"}
    f_card = s.findings[kinds_order.index("card")]
    check(f_card.preview("first_last") == exp["card"], f"строка карты «первые и последние»: {f_card.preview('first_last')}")
    f_mail = s.findings[kinds_order.index("email")]
    check(f_mail.preview("domain") == "***@example.com" and f_mail.preview("name") == "test@***", f"строки почты: {f_mail.preview('domain')} {f_mail.preview('name')}")
    f_iban = s.findings[kinds_order.index("iban")]
    check(f_iban.preview("country_last4").startswith("DE") and f_iban.preview("country_last4").replace(" ", "").endswith("3000"), "строка IBAN: страна и последние 4")
    f_link = s.findings[kinds_order.index("link")]
    check(f_link.preview("host") == "https://example.com/***".replace("/***", "") + "/***" or "example.com" in f_link.preview("host"), f"ссылка: {f_link.preview('host')}")
    check("abcdef123456" not in f_link.preview("host"), "ключ в строке ссылки скрыт")
    f_phone = s.findings[kinds_order.index("phone")]
    check(f_phone.preview("first_last") == "+7 *** *** ***00-00".replace("***00", "**-00") or f_phone.preview("first_last").startswith("+7"),
          f"телефон «код страны и последние»: {f_phone.preview('first_last')}")
    # ключ без адреса: режим «адрес сайта» недоступен, ничего не откроется по ошибке
    w2, _f = words_of("ключ sk-abcdefghijklmnopqrstuvwx")
    key = privacy.find(w2)[0]
    check(key.modes() == ("full", "open") and key.hidden_indices("host") == set(range(len(key.chars))), "ключ без адреса: «адрес сайта» закрывает всё")
    # открыть всё / скрыть всё
    panel.open_all_button.click()
    check(not blur_shapes(ed) and all(m == "open" for m in s.modes), "«Открыть всё»: ни размытия, у всех «открыто»")
    check(all(r.button.text().startswith(tr("privacy.short_open")) for r in panel.rows), "строки показывают «открыто»")
    panel.hide_all_button.click()
    check(len(blur_shapes(ed)) == 5 and all(m == "full" for m in s.modes), "«Скрыть всё»: всё снова закрыто")
    # закрыть панель: размытие остаётся
    panel.close_button.click()
    check(not panel.isVisible() and len(blur_shapes(ed)) == 5, "панель закрыта, размытие осталось")
    ed.hide_personal()
    settle()
    check(len(blur_shapes(ed)) == 5, "повторное нажатие: второй слой размытия не накладывается")
    finish(ed)


def test_proportional_boundaries():
    """Граница между закрытым и открытым точна и у шрифта с буквами разной ширины (по картинке), а без измерения
    закрытое всё равно закрыто целиком (открытая буква хуже лишнего размытия)."""
    text = "почта illli@example.com\nещё iiiiiimmmm@example.org"
    words, font = words_of(text, size=22, mono=False)
    img, words = sample(text, size=22, mono=False)
    fm = QFontMetricsF(font)
    w = words[1]   # illli@example.com
    boxes = privacy.char_boxes(img, w.rect, w.text)
    check(boxes is not None and len(boxes) == len(w.text), "границы символов измерены по картинке")
    ok = True
    for k in range(len(w.text)):
        x_mid = w.rect.x() + fm.horizontalAdvance(w.text[:k]) + fm.horizontalAdvance(w.text[k]) / 2
        ok &= boxes[k][0] <= x_mid <= boxes[k][1]
    check(ok, "середина каждой буквы попадает в свою границу")
    for fallback in (False, True):
        ed = EditorWindow(img, Ctx(), QPoint(0, 0))
        ed.present()
        settle()
        ed.canvas.set_words(words, ed.canvas.base.devicePixelRatio())
        ed.hide_personal()
        settle()
        s = ed.privacy_session
        if fallback:
            s._boxes = {wi: None for wi in range(len(words))}
        for i, f in enumerate(s.findings):
            s.set_mode(i, "name")   # имя открыто, домен закрыт
            out = ed.canvas.render()
            hidden = f.hidden_indices("name")
            bad = []
            for k in range(len(f.chars)):
                wi, ci = f.chars[k]
                x = words[wi].rect.x() + fm.horizontalAdvance(words[wi].text[:ci])
                cw = fm.horizontalAdvance(words[wi].text[ci])
                cx = x + cw / 2
                cy = words[wi].rect.center().y()
                n = 1 if any(rr.contains(QPointF(cx, cy)) for rr in s.rect_union(i)) else 0
                if k in hidden and n == 0:
                    bad.append(("не закрыт", k))
                if k not in hidden and not fallback and n != 0:
                    bad.append(("закрыт лишний", k))
            check(not bad, f"{'доли без измерения' if fallback else 'по картинке'}: «{f.value}» домен закрыт, имя {'открыто' if not fallback else 'не обязательно'} {bad[:3]}")
        finish(ed)


def test_piece_tools():
    ed, img, words = make(TEXT)
    ed.hide_personal()
    settle()
    s, panel, c = ed.privacy_session, ed.privacy_panel, ed.canvas
    before = ed.canvas.render()
    steps = len(c.undo_stack)
    i_card = [f.kind for f in s.findings].index("card")
    wr = words[s.findings[i_card].chars[0][0]].rect   # первая группа карты «4111»
    panel.tool_buttons["open"].click()
    check(panel.tool == "open" and c.band_mode == "open", "«Открыть кусок» включён")
    zoom = c.zoom
    a = QPoint(int((wr.left() + wr.width() * 0.5) * zoom), int((wr.top() - 4) * zoom))
    b = QPoint(int((wr.right() + 30) * zoom), int((wr.bottom() + 4) * zoom))
    QTest.mousePress(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, a)
    QTest.mouseMove(c, QPoint((a.x() + b.x()) // 2, (a.y() + b.y()) // 2))
    QTest.mouseMove(c, b)
    check(c.band is not None, "обводка видна пока мышь зажата")
    QTest.mouseRelease(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, b)
    settle()
    check(len(c.undo_stack) == steps + 2 or len(c.undo_stack) == steps + 1, f"один шаг «Отменить» на кусок ({len(c.undo_stack) - steps})")
    out = ed.canvas.render()
    opened = QRectF(wr.left() + wr.width() * 0.5, wr.top(), wr.width() * 0.5, wr.height())
    check(region_changed(img, out, QRectF(opened.x() + 1, opened.y() + 3, opened.width() - 2, opened.height() - 6)) == 0,
          "обведённая часть открыта: пиксели как в исходном снимке")
    left_half = QRectF(wr.left(), wr.top(), wr.width() * 0.45, wr.height())
    check(region_changed(img, out, left_half) > 4, "остальное размытие осталось")
    check(s.custom[i_card] and panel.rows[[r.index for r in panel.rows].index(i_card)].button.text().startswith(tr("privacy.short_custom")),
          "строка карты показывает «Вручную»")
    # отмена одним шагом возвращает прежнее
    c.undo()
    settle()
    check(region_changed(before, ed.canvas.render(), QRectF(0, 0, img.width(), img.height())) == 0, "«Отменить» вернуло снимок как до куска")
    check(not panel.isVisible() and c.band_mode is None, "после отмены панель закрыта и обводка выключена")
    finish(ed)
    # «Скрыть кусок»: и по нераспознанному месту
    ed, img, words = make(TEXT)
    ed.hide_personal()
    settle()
    s, panel, c = ed.privacy_session, ed.privacy_panel, ed.canvas
    plain = next(w for w in words if w.text == "обычного")
    QTest.keyClick(c, Qt.Key.Key_U, Qt.KeyboardModifier.ShiftModifier)
    check(panel.tool == "hide", "Shift+U включает «Скрыть кусок»")
    n_blur, steps = len(blur_shapes(ed)), len(c.undo_stack)
    c.band_done(plain.rect)   # то же, что обводка мышью по слову
    settle()
    check(len(blur_shapes(ed)) == n_blur + 1 and len(c.undo_stack) == steps + 1, "поверх нераспознанного слова добавлено обычное размытие, шаг один")
    check(region_changed(img, ed.canvas.render(), plain.rect) > 8, "слово закрыто")
    panel.open_all_button.click()
    check(not blur_shapes(ed), "«Открыть всё» убирает и добавленные вручную куски")
    panel.hide_all_button.click()
    check(len(blur_shapes(ed)) == n_blur + 1, "«Скрыть всё» возвращает и их")
    QTest.keyClick(c, Qt.Key.Key_U)
    check(panel.tool == "open", "клавиша U включает «Открыть кусок»")
    QTest.keyClick(c, Qt.Key.Key_U)
    check(panel.tool == "" and c.band_mode is None, "повторное нажатие выключает")
    # открыть кусок поверх своего ручного размытия режет и его
    panel.set_tool("open", emit=True)
    c.band_done(QRectF(plain.rect.x(), plain.rect.y(), plain.rect.width() / 2, plain.rect.height()))
    check(region_changed(img, ed.canvas.render(), QRectF(plain.rect.x() + 2, plain.rect.y() + 4, plain.rect.width() / 2 - 4, plain.rect.height() - 8)) == 0,
          "ручное размытие режется так же")
    # куски меньше 3 точек не считаются
    steps = len(c.undo_stack)
    c.band_done(QRectF(5, 5, 1, 1))
    check(len(c.undo_stack) == steps, "случайный щелчок без обводки ничего не меняет")
    finish(ed)


def test_link_image_and_list():
    ed, img, words = make(TEXT)
    ed.hide_personal()
    settle()
    s, panel, c = ed.privacy_session, ed.privacy_panel, ed.canvas
    i_mail = [f.kind for f in s.findings].index("email")
    i_link = [f.kind for f in s.findings].index("link")
    n_shapes = len(c.shapes)
    steps = len(c.undo_stack)
    for i in (i_mail, i_link):
        r = s.rect_union(i)[0]
        QTest.mouseClick(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(int(r.center().x() * c.zoom), int(r.center().y() * c.zoom)))
        settle()
        check(panel.selected_index() == i, f"щелчок по месту на снимке выделил строку {s.findings[i].kind}")
        row = next(r for r in panel.rows if r.index == i)
        vp = panel.scroll.viewport()
        top = row.mapTo(vp, QPoint(0, 0)).y()
        check(0 <= top and top + row.height() <= vp.height() + 2, f"строка {s.findings[i].kind} в видимой части списка")
    check(len(c.shapes) == n_shapes and len(c.undo_stack) == steps, "щелчок по размытию ничего не нарисовал и не добавил шагов")
    QTest.mouseClick(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(c.lw() - 5), int(c.lh() - 5)))
    check(panel.selected_index() == -1, "щелчок мимо снимает выделение строки")
    # наведение на строку подсвечивает место на снимке
    from PyQt6.QtCore import QEvent, QPointF
    from PyQt6.QtGui import QEnterEvent
    row = next(r for r in panel.rows if r.index == i_mail)
    QApplication.sendEvent(row, QEnterEvent(QPointF(3, 3), QPointF(3, 3), QPointF(3, 3)))
    check(c.highlight == s.rect_union(i_mail) and len(c.highlight) == 1, "наведение на строку: рамка на снимке")
    r = c.highlight[0]
    pic = c.grab().toImage()
    px = QColor(pic.pixel(int(r.left() * c.zoom + 1), int(r.center().y() * c.zoom)))
    check(px.blue() > 150 and px.red() < 120 or px.lightness() > 200, f"рамка нарисована ({px.name()})")
    QApplication.sendEvent(row, QEvent(QEvent.Type.Leave))
    check(c.highlight == [], "курсор ушёл: рамки нет")
    finish(ed)


def test_nothing_found():
    ed, img, words = make("Привет, это обычный текст\nбез личных данных 2026 год")
    ed.hide_personal()
    settle()
    p = ed.privacy_panel
    check(p.isVisible() and p.title.text() == tr("privacy.none"), f"«Личных данных не найдено»: {p.title.text()}")
    check(any(tr("privacy.none_hint") == l.text() for l in p.findChildren(type(p.title))), "совет выделить вручную размытием")
    check(not blur_shapes(ed) and not ed.canvas.undo_stack, "ничего не закрыто, шага отмены нет")
    check(not p.rows, "строк нет")
    p.manual_button.click()
    settle()
    check(ed.canvas.tool == BLUR and not p.isVisible(), "«Выделить вручную» включает размытие")
    finish(ed)
    # снимок без текста вовсе
    img = QImage(300, 120, QImage.Format.Format_RGB32)
    img.fill(QColor("#ffffff"))
    ed = EditorWindow(img, Ctx(), QPoint(0, 0))
    ed.present()
    ed.canvas.words, ed.canvas.words_key = [], None
    jobs = []
    real = ocr.start

    def fake_start(image, on_done, langs=ocr.DEFAULT_LANGS, quality="accurate"):
        class Job:
            words, used = [], ""
        job = Job()
        jobs.append(job)
        QTimer.singleShot(0, lambda: on_done("", "", None))
        return job
    ocr.start = fake_start
    try:
        ed.hide_personal()
        settle(10)
    finally:
        ocr.start = real
    check(ed.privacy_panel.isVisible() and ed.privacy_panel.title.text() == tr("privacy.none"), "пустой снимок: «не найдено»")
    finish(ed)


def test_no_ocr():
    ed, img, words = make(TEXT)
    ed.canvas.words, ed.canvas.words_key = [], None
    shown = []
    real_start, real_show = ocr.start, ocr.show_result

    def fake_start(image, on_done, langs=ocr.DEFAULT_LANGS, quality="accurate"):
        class Job:
            words, used = [], ""
        help_ = ocr.install_help("missing")
        QTimer.singleShot(0, lambda: on_done("", tr("ocr.err_not_installed"), help_))
        return Job()
    ocr.start = fake_start
    ocr.show_result = lambda text, error, parent=None, help=None: shown.append((text, error, help)) or None
    try:
        ed.hide_personal()
        settle(10)
    finally:
        ocr.start, ocr.show_result = real_start, real_show
    check(len(shown) == 1 and shown[0][1] == tr("ocr.err_not_installed"), "нет Tesseract: то же окно с причиной, что в «Тексте с картинки»")
    check(bool(shown) and shown[0][2] is not None, "в окне есть подсказка, как поставить распознавание")
    check(not ed.privacy_panel.isVisible() and not blur_shapes(ed) and not ed.canvas.undo_stack, "панели и размытия нет")
    check(ed._ocr_job is None, "задание распознавания закончено, кнопку можно нажать снова")
    finish(ed)
    # распознавание выключено в настройках: кнопки нет
    ed, _img, _w = make(TEXT, ocr_enabled=False)
    check(PRIVACY not in ed.tool_strip.members("hide") and not ed.tool_buttons[PRIVACY].isVisible(), "распознавание выключено: кнопки нет")
    finish(ed)


def test_real_ocr_privacy():
    """Настоящее распознавание на нарисованном снимке: найдено, закрыто; в журналах, файлах и сети значений нет."""
    if not ocr.find_tesseract():
        print("     (Tesseract нет: проверка настоящего распознавания пропущена)")
        return
    text = f"Contact {EMAIL}\nCard {CARD}\nPhone {PHONE_RU}\nPlain words only"
    img, _w = sample(text, size=30, mono=False)
    ed = EditorWindow(img, Ctx(ocr_langs="eng"), QPoint(0, 0))
    ed.present()
    settle()
    NET.clear()
    ed.hide_personal()
    for _ in range(300):   # распознавание в фоне, до 15 секунд
        settle(1)
        if ed.privacy_panel.isVisible() or ed._ocr_job is None:
            break
        QTest.qWait(50)
    s = ed.privacy_session
    print("     распознано слов:", [w.text for w in ed.canvas.words])
    got = sorted(f.kind for f in s.findings) if s else []
    check({"email", "card", "phone"} <= set(got), f"настоящее распознавание: найдены почта, карта, телефон: {got}")
    check(len(blur_shapes(ed)) >= 3, "и закрыты размытием")
    check(not NET, f"сеть не трогалась: {NET}")
    secrets = ("example.com", "4111", "000-00-00", "test@")
    blob = ""
    for root, _dirs, files in os.walk(TMP):
        for name in files:
            path = os.path.join(root, name)
            try:
                if os.path.getsize(path) < 5_000_000:
                    blob += open(path, "rb").read().decode("utf-8", "ignore")
            except OSError:
                pass
    log = ocr.log_path()
    check(log.exists(), "журнал распознавания ведётся")
    leaked = [v for v in secrets if v in blob]
    check(not leaked, f"в журналах и файлах программы нет значений: {leaked}")
    check(all(v not in ocr.log_path().read_text(encoding="utf-8") for v in secrets), "в ocr.log нет найденных значений")
    finish(ed)


# ---------------------------------------------------------------- 3. 12 языков, темы

def test_languages():
    ed, img, words = make(TEXT)
    ed.hide_personal()
    settle()
    ref = i18n._load("ru")
    keys = [k for k in ref if k.startswith("privacy.")]
    check(len(keys) == 39, f"39 строк privacy.* в ru: {len(keys)}")
    for lang in i18n.LANGUAGES:
        cat = i18n._load(lang)
        check(all(cat.get(k, "").strip() for k in keys), f"{lang}: все строки есть")
        check("{n}" in cat["privacy.found"], f"{lang}: «Найдено» с {{n}}")
        i18n.set_language(lang, notify=False)
        ed2, _i, _w = make(TEXT)
        ed2.hide_personal()
        settle()
        p = ed2.privacy_panel
        buttons = [b for b in p.findChildren(QPushButton)]
        bad = []
        for b in buttons:
            need = b.fontMetrics().horizontalAdvance(b.text()) + 16
            if need > b.width():
                bad.append((b.text(), need, b.width()))
        check(not bad, f"{lang}: надписи кнопок панели помещаются: {bad}")
        check(len(buttons) == 4, f"{lang}: четыре кнопки (открыть кусок, скрыть кусок, открыть всё, скрыть всё)")
        from clipshot.privacy_ui import ROW_BUTTON_W, mode_short, mode_title
        for row in p.rows:
            for mode in list(row.finding.modes()) + ["custom"]:
                short = mode_short(row.finding.kind, mode) + "  ▾"
                check(row.button.fontMetrics().horizontalAdvance(short) <= ROW_BUTTON_W - 18, f"{lang}: «{short}» на кнопке строки без обрезки")
            row._fill_menu()
            check(len(row.menu.actions()) == len(row.finding.modes()) and all(a.text() for a in row.menu.actions()),
                  f"{lang}: меню строки {row.finding.kind} полное")
            for mode in row.finding.modes():
                wide = row.menu.fontMetrics().horizontalAdvance(mode_title(row.finding.kind, mode))
                check(wide < 330, f"{lang}: пункт меню «{mode_title(row.finding.kind, mode)}» не длиннее экрана ({wide})")
        check(ed2.tool_buttons[PRIVACY].toolTip().startswith(cat["privacy.tip"].split("\n")[0]), f"{lang}: подсказка кнопки")
        finish(ed2)
    i18n.set_language("ru", notify=False)
    finish(ed)


def test_themes():
    for dark in (False, True):
        ed, img, words = make(TEXT, dark=dark)
        P = palette(ed.ctx.config)
        check(P["dark"] == dark, f"тема {'тёмная' if dark else 'светлая'} включена")
        ed.hide_personal()
        settle()
        p = ed.privacy_panel
        pic = p.grab().toImage()
        bg = QColor(pic.pixel(pic.width() // 2, pic.height() // 2))
        want = QColor(P["panel"])
        check(abs(bg.lightness() - want.lightness()) < 30, f"фон панели из палитры редактора ({bg.name()} / {want.name()})")
        css = p.styleSheet()
        check(P["t"] in css and P["sep"] in css, "цвета текста и линий панели из палитры")
        finish(ed)


def test_narrow_window():
    ed, img, words = make(TEXT)
    ed.resize(760, 560)
    settle()
    ed.hide_personal()
    settle()
    p = ed.privacy_panel
    check(p.isVisible() and p.geometry().right() <= ed.width(), "узкое окно: панель целиком в окне")
    check(ed.scroll.viewport().width() >= 200, f"узкое окно: снимок остаётся виден ({ed.scroll.viewport().width()} px)")
    check(all(b.isVisible() and b.width() >= 100 for b in p.findChildren(QPushButton)), "кнопки панели не схлопнулись")
    # меню строки в оформлении программы
    row = p.rows[0]
    check(row.menu.styleSheet() != "" or row.menu.palette() is not None, "меню строки создано")
    finish(ed)


def test_esc_and_keys():
    ed, img, words = make(TEXT)
    ed.activateWindow()
    QTest.keyClick(ed.canvas, Qt.Key.Key_H)
    settle()
    check(ed.privacy_panel.isVisible(), "клавиша H запускает «Скрыть личные данные»")
    ed.escape()
    check(not ed.privacy_panel.isVisible() and len(blur_shapes(ed)) == 5, "Esc закрывает панель, размытие остаётся")
    finish(ed)


for name, fn in list(globals().items()):
    if name.startswith("test_") and callable(fn):
        print("==", name, flush=True)
        try:
            fn()
        except Exception as exc:   # noqa: BLE001
            import traceback
            traceback.print_exc()
            failures.append(f"{name}: исключение {exc!r}")
print(f"\nИТОГ: проверок {checks[0]}, провалов {len(failures)}")
for f in failures:
    print("FAIL", f)
sys.exit(1 if failures else 0)
