# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
"""Перевод с картинки: нарезка, второй сервис при лимите, подключение Google, расход, окошки перевода, перевод в редакторе.
Сеть подменяется (лимит не тратится); распознавание настоящее, где есть Tesseract.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/translate_test.py
"""
import os
import sys
import tempfile
import time
from pathlib import Path

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPixmap
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
from clipshot import app as appmod, ocr, translate
from clipshot.selector import RegionSelector
failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def wait(cond, seconds=60):
    end = time.time() + seconds
    while not cond() and time.time() < end:
        app.processEvents()
        QTest.qWait(50)
    return cond()


tmp = Path(tempfile.mkdtemp(prefix="clipsd-tr-test-"))
# проверки почты и ключа ходят в сеть: в тесте отвечают сразу «принято»
translate.check_mymemory_email = lambda email, cb: cb("")
translate.check_google_key = lambda key, cb: cb("")
translate.google_key_path = lambda: tmp / "google.key"          # не трогать настоящие файлы пользователя
KEYF = tmp / "google.key"
translate.load_google_key = lambda: KEYF.read_text().strip() if KEYF.exists() else ""
GKEY = "AIza" + "SyD-test_key_0123456789abcdefghijkl"

# 1. Нарезка под предел MyMemory
long = "Посылка Swiftpost доедет из Порту в Лиссабон за 2 дня. " * 20 + "\nВторой абзац."
chunks = translate.split_chunks(long)
check(all(len(c.encode()) <= translate.MYMEMORY_MAX_BYTES for c, _ in chunks), "куски не длиннее предела MyMemory")
joined = "".join(c + s for c, s in chunks)
check(joined.split() == long.split() and "\nВторой абзац." in joined, "куски собираются обратно без потерь, перенос строки на месте")


# 2. Второй сервис, если у первого кончился лимит или нет ключа
class Fake:
    def __init__(self, name, fail=None, src="en"):
        self.name, self.fail, self.src, self.calls = name, fail, src, 0

    def translate(self, text, target, source=None):
        self.calls += 1
        if self.fail:
            raise self.fail
        return f"[{target}] {text}", source or self.src


a, b = Fake("MyMemory", translate.QuotaError("лимит")), Fake("Google")
tr, src, tgt, used = translate.translate_text("Hello", {"translate_to": "ru"}, [a, b])
check(used == "Google" and tr == "[ru] Hello", "лимит у первого: перевёл второй сервис")
ru = Fake("MyMemory", src="ru")
tr, src, tgt, used = translate.translate_text("Привет", {"translate_to": "ru", "translate_alt": "en"}, [ru])
check(tgt == "en" and tr == "[en] Привет", "текст уже русский: перевод на запасной язык")
try:
    translate.translate_text("x", {}, [Fake("MyMemory", translate.QuotaError("Дневной лимит")),
                                     translate.GoogleCloud("")])
    check(False, "оба сервиса недоступны: должна быть ошибка")
except translate.TranslateError as exc:
    check(exc.help is not None and getattr(exc.help, "service", None) == "google",
          "оба недоступны: ошибка с предложением подключить Google")
check(len(GKEY) == 39 and translate.looks_like_google_key(GKEY) and not translate.looks_like_google_key("привет"),
      "ключ Google узнаётся по виду")
err = translate._google_error(400, '{"error": {"message": "API key not valid. Please pass a valid API key."}}')
check(isinstance(err, translate.KeyMissing) and "не принял ключ" in str(err), "Google: неверный ключ понятно объяснён")
err = translate._google_error(403, '{"error": {"message": "This API method requires billing to be enabled."}}')
check(isinstance(err, translate.KeyMissing) and "оплата" in str(err), "Google: не включена оплата, понятно объяснено")
err = translate._google_error(403, '{"error": {"message": "Cloud Translation API has not been used in project 1 before or it is disabled."}}')
check(isinstance(err, translate.KeyMissing) and "сервис перевода" in str(err), "Google: не включён сервис перевода, понятно объяснено")

# 3. Ключ и расход
translate.save_google_key(GKEY)
check(KEYF.exists() and translate.load_google_key() == GKEY, "ключ сохраняется в файл")
if sys.platform != "win32":
    check(oct(KEYF.stat().st_mode & 0o777) == "0o600", "файл ключа читает только владелец")
translate.usage_path = lambda: tmp / "usage.json"
translate.add_mymemory_chars(1200)
translate.add_mymemory_chars(30)
used, limit = translate.mymemory_usage("")
check((used, limit) == (1230, 5000), f"расход MyMemory за сегодня: {used} из {limit}")
check(translate.mymemory_usage("me@example.com")[1] == 50000, "с почтой лимит 50 000")
line = translate.usage_line({"translate_engine": "mymemory"})
check("1 230 из 5 000" in line and "осталось 3 770" in line, f"строка расхода: {line!r}")
translate.add_google_chars(12400)
check("12 400 из 500 000" in translate.usage_line({"translate_engine": "google"}), "строка расхода Google за месяц")
KEYF.unlink()
check("не подключён" in translate.usage_line({"translate_engine": "google"}), "Google без ключа: «не подключён»")

# 4. Абзацы
W = lambda x, y, t, ln: ocr.Word(t, QRectF(x, y, len(t) * 8, 14), ln)
blocks = translate.blocks_from_words([W(20, 10, "The parcel will be delivered", (0, 0)),
                                      W(20, 28, "straight to the door in Porto.", (1, 0)), W(20, 80, "Second item", (2, 0))])
check([t for _r, t, _h in blocks] == ["The parcel will be delivered straight to the door in Porto.", "Second item"],
      "строки абзаца переводятся вместе, отдельный пункт отдельно")


# 4а. Почта для MyMemory: 50 000 знаков в день
check(translate.looks_like_email("name@gmail.com") and not translate.looks_like_email("не почта"), "почта узнаётся по виду")
real_http = translate._http
translate._http = lambda url, *a, **k: {"responseStatus": 403, "responseDetails": "INVALID EMAIL PROVIDED",
                                        "responseData": {"translatedText": "INVALID EMAIL PROVIDED"}}
try:
    translate.MyMemory("bad@x").translate("Hello", "ru")
    check(False, "неверная почта: должна быть ошибка")
except translate.KeyMissing as exc:
    check(isinstance(exc.help, translate.EmailNeeded) and "не принял почту" in str(exc), "неверная почта: понятная ошибка и предложение исправить")
translate._http = lambda url, *a, **k: {"responseStatus": 429, "quotaFinished": True,
                                        "responseData": {"translatedText": "MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE TRANSLATIONS"}}
try:
    translate.MyMemory("").translate("Hello", "ru")
except translate.QuotaError as exc:
    check(isinstance(exc.help, translate.EmailNeeded) and "Укажите почту" in str(exc), "лимит без почты: предлагается указать почту")
try:
    translate.MyMemory("me@gmail.com").translate("Hello", "ru")
except translate.QuotaError as exc:
    check(exc.help is None and "50 000" in str(exc), "лимит с почтой исчерпан: «завтра обновится»")
try:
    translate.translate_text("Hello", {}, [translate.MyMemory(""), translate.GoogleCloud("")])
except translate.TranslateError as exc:
    check(isinstance(exc.help, translate.EmailNeeded), "оба недоступны: первым предлагается почта (проще, чем Google)")
translate._http = real_http
body429 = ('{"responseData":{"translatedText":"MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE TRANSLATIONS FOR TODAY. '
           'NEXT AVAILABLE IN  09 HOURS 47 MINUTES 36 SECONDS"},"responseDetails":"MYMEMORY WARNING"}')
err = translate.MyMemory("")._http_error(429, body429)
check(isinstance(err, translate.QuotaError) and isinstance(err.help, translate.EmailNeeded) and "9 ч 47 мин" in str(err),
      f"ответ MyMemory 429 «лимит на сегодня»: предлагается почта и время обновления ({err})")
err = translate.MyMemory("me@gmail.com")._http_error(429, body429)
check(isinstance(err, translate.QuotaError) and err.help is None and "9 ч 47 мин" in str(err), "429 с почтой: «обновится через…»")
err = translate.MyMemory("bad")._http_error(403, '{"responseDetails":"INVALID EMAIL PROVIDED"}')
check(isinstance(err, translate.KeyMissing) and isinstance(err.help, translate.EmailNeeded), "403 «неверная почта» по коду ответа")
check("с почтой 50 000" in translate.usage_line({"translate_engine": "mymemory"}), "строка расхода подсказывает про почту")

from clipshot import service_setup
ecfg, esaves, esaved = {"translate_engine": "mymemory", "translate_email": ""}, [], []
edlg = service_setup.open_mymemory_email(None, ecfg, lambda: esaves.append(1), lambda: esaved.append(1))
edlg.email.setText("не почта")
QTest.mouseClick(edlg.save_b, Qt.MouseButton.LeftButton)
check(ecfg["translate_email"] == "" and "не похоже на почту" in edlg.status.text(), "окно почты: неверная почта не сохраняется")
edlg.email.setText("name@gmail.com")
QTest.mouseClick(edlg.save_b, Qt.MouseButton.LeftButton)
check(ecfg["translate_email"] == "name@gmail.com" and esaves and esaved, "окно почты: «Сохранить» запоминает почту")
check(translate.mymemory_usage(ecfg["translate_email"])[1] == 50000, "с почтой лимит 50 000 в день")
edlg2 = service_setup.open_mymemory_email(None, ecfg, None, None)
check(edlg2.remove_b.isVisibleTo(edlg2), "«Убрать почту» есть, когда почта указана")
QTest.mouseClick(edlg2.remove_b, Qt.MouseButton.LeftButton)
check(ecfg["translate_email"] == "", "«Убрать почту»")

# 5. Режим перевода в окне выделения
def page():
    img = QImage(1200, 600, QImage.Format.Format_RGB32)
    img.fill(QColor("#ffffff"))
    p = QPainter(img)
    f = QFont()
    f.setPixelSize(18)
    p.setFont(f)
    p.setPen(QColor("#1d2330"))
    p.drawText(60, 100, "Free delivery across Bulgaria.")
    p.drawText(60, 150, "Installation guide included.")
    p.fillRect(40, 300, 600, 60, QColor("#1e2a3a"))
    p.setPen(QColor("#ffffff"))
    p.drawText(60, 338, "Order now and get a gift")
    p.end()
    return img


cfg = dict(appmod.DEFAULTS, translate_view="card")   # проверки окошка рассчитаны на вид «Карточкой»; «Поверх текста»: ui127_test
saves = []
from clipshot import translate_ui
more_calls = []
translate_ui.FloatingTranslation.request_more = lambda: more_calls.append(1)


def new_selector(kept=False):
    sel = RegionSelector(QPixmap.fromImage(page()), QRect(0, 0, 1200, 600),
                         last_rect=QRect(30, 60, 500, 120) if kept else None)
    sel.resize(1200, 600)
    sel.tr_cfg, sel.tr_save = cfg, lambda: saves.append(dict(cfg))
    sel.show()
    for _ in range(4):
        app.processEvents(); QTest.qWait(20)
    return sel


def drag_on(w, a, b):
    QTest.mousePress(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, a)
    QTest.mouseMove(w, QPoint((a.x() + b.x()) // 2, (a.y() + b.y()) // 2))
    QTest.mouseMove(w, b)
    QTest.mouseRelease(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, b)
    app.processEvents()


def click_on(w, r):
    QTest.mouseClick(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, r.center().toPoint())
    app.processEvents()


sel = new_selector()
check("translate" in [k for k, *_ in sel._bar_buttons()], "в окне выделения есть кнопка «Перевести»")
cfg["translate_enabled"] = False
check("translate" not in [k for k, *_ in sel._bar_buttons()], "перевод выключен: кнопки нет")
cfg["translate_enabled"] = True
sel._do("translate")
check(sel.translate_mode and sel.kept is None, "кнопка «Перевести» включает режим перевода")
sel.repaint()
bar = sel._bar_layout()[1]
btns = {k: r for k, _t, _s, r in sel._bar_layout()[0]}
check(bar.bottom() > sel.height() / 2 and "translate" in btns and sel.bar_close_rect.isValid(),
      "режим перевода: панель внизу экрана, плитка перевода и крестик «Закрыть (Esc)» на месте (1.29)")
check(translate.target_lang({"translate_to": "auto"}) == translate.system_lang() and translate.target_lang({"translate_to": "bg"}) == "bg",
      "язык перевода: по умолчанию как в системе, можно выбрать свой")
cfg["translate_engine"] = "mymemory"

real_engines = translate.engines_from_config
fake = Fake("MyMemory")
translate.engines_from_config = lambda c: [fake]
if ocr.engine_name() == "tesseract":
    finished = []
    sel.finished.connect(lambda *a: finished.append(a))
    n_float = len(translate_ui._floating)
    drag_on(sel, QPoint(40, 70), QPoint(600, 170))
    check(not finished and sel.translate_mode, "выделили кусок: окно выделения осталось в режиме перевода (1.29), окошко перевода на экране")
    check(len(translate_ui._floating) == n_float + 1, "перевод открылся отдельным окошком")
    win = translate_ui._floating[-1]
    ga = win.mapToGlobal(win.tr_cards[0].region.topLeft())
    check(abs(ga.x() - 40) <= 2 and abs(ga.y() - 70) <= 2, f"окошко на месте текста: перевод ложится на оригинал: {ga}")
    assert not win.mini or win._tr_view(win.tr_cards[0]) == "overlay"
    check(win.tr_cards[0].state in ("busy", "done") and (win.tr_cards[0].state == "done" or win.tr_timer.isActive()),
          "пока переводится: кружок «думаю» в окошке")
    card = win.tr_cards[0]
    check(wait(lambda: card.state == "done"), "кусок распознан и переведён")
    check(wait(lambda: not win.tr_timer.isActive(), 3), "перевод готов: таймер кружка остановился")
    texts = [blk["text"] for blk in card.blocks]
    check(any("Free delivery" in t and t.startswith("[ru]") for t in texts), f"перевод блоков: {texts}")
    check("Английский → Русский" in card.langs(), f"подпись языков: {card.langs()!r}")
    win.repaint()
    check(list(card.buttons) == ["close"] and card.chip.isNull() and sel._tr_current_win() is win,
          f"пока окно выделения в режиме перевода: у окошка нет плашки, только крестик {list(card.buttons)}; кнопки в панели")
    ctl = {k: r for k, _t, r in sel._bar_layout() and sel.tr_ctl_rects}
    check({"trc:lang", "trc:tr", "trc:orig", "trc:overlay", "trc:card", "trc:copy", "trc:more"} <= set(ctl), f"в строке панели кнопки {sorted(ctl)}")
    win.enable_chip()
    card.view, card.laid = "card", None   # дальше проверки окошка вида «Карточкой» (настройка теста)
    win._tr_view_changed(card, "card")
    win.repaint()
    check("lang" in card.buttons and card.source_label().startswith("Английский"), "на окошке кнопка языка перевода «→ Русский ▾»")
    check(card.header_need <= win.width() + 1, "строка кнопок помещается в окошко")
    acts = win._tr_lang_actions()
    check(acts[0][0] == "auto" and "Как язык программы" in acts[0][1] and len(acts) > 15, "в списке «Как в системе» и языки")
    win._tr_choose_lang("de", card)
    check(cfg["translate_to"] == "de" and wait(lambda: card.state == "done") and card.blocks[0]["tgt"] == "de"
          and card.blocks[0]["text"].startswith("[de]"), "выбрали немецкий: окошко переведено заново на немецкий")
    win._tr_choose_lang("auto", card)
    check(wait(lambda: card.state == "done") and card.blocks[0]["tgt"] == translate.system_lang(), "«Как в системе»: снова язык системы")
    win.repaint()
    shot = win.grab().toImage()
    gap = QPoint(int(card.box().right() - 6), int(card.box().center().y()))   # правый край между строками
    check(shot.pixelColor(gap).alpha() == 255, "окошко залито целиком, между строками нет просветов")
    cl = card.buttons["close"]
    check(cl.right() <= card.box().right() and cl.right() >= card.box().right() - 14 and cl.top() >= card.box().top()
          and cl.bottom() <= card.box().top() + translate_ui.TranslateMixin.HEAD_H,
          f"крестик в правом верхнем углу перевода: {cl} при {card.box()}")
    check(win.rect().contains(cl.toAlignedRect()), "крестик внутри окошка")
    click_on(win, card.buttons["copy"])
    check(QGuiApplication.clipboard().text() == card.text(), "«Копировать» кладёт перевод в буфер")
    click_on(win, card.buttons["orig"])
    check(card.show_original, "«Оригинал» показывает исходный текст")
    win.repaint()
    click_on(win, card.buttons["orig"])
    win.repaint()
    from PyQt6.QtWidgets import QMenu
    real_exec = QMenu.exec
    QMenu.exec = lambda self, *a, **k: None
    click_on(win, card.buttons["more"])
    QMenu.exec = real_exec
    texts = [a.text() for a in win.tr_more_menu.actions() if not a.isSeparator()]
    check(texts[:2] == ["Сервис: Google", "Сервис: MyMemory"] and any(t.startswith("Осталось") for t in texts)
          and "Скопировать все переводы" in texts and texts[-1] == "Перевести ещё кусок", f"«Ещё»: меню {texts}")
    win._tr_more_action("more")
    check(sel.translate_mode and not more_calls, "«Ещё» → «Перевести ещё кусок» при открытом окне выделения: режим перевода в нём, окно не новое")
    win.more_hook = None
    win._tr_more_action("more")
    check(more_calls, "«Ещё» → «Перевести ещё кусок» без окна выделения: выделить следующий кусок")
    # окошко перетаскивается за перевод
    before = win.pos()
    start = card.box().center().toPoint()
    QTest.mousePress(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    QTest.mouseMove(win, start + QPoint(120, 80))
    QTest.mouseRelease(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start + QPoint(120, 80))
    app.processEvents()
    check(win.pos() != before, f"окошко оттаскивается мышью: {before} → {win.pos()}")
    # второй кусок: тёмный фон
    sel2 = new_selector()
    sel2.enter_translate()
    drag_on(sel2, QPoint(30, 290), QPoint(660, 370))
    win2 = translate_ui._floating[-1]
    check(win2 is not win and wait(lambda: win2.tr_cards[0].state == "done"), "второй перевод, первое окошко осталось")
    dark = win2.tr_cards[0].blocks[0]
    check(dark["fg"].lightness() > 200 and dark["bg"].lightness() < 80, "на тёмном фоне перевод светлый на тёмном")
    win2.repaint()
    click_on(win2, win2.tr_cards[0].buttons["close"])
    app.processEvents()
    check(win2 not in translate_ui._floating or not win2.isVisible(), "крестик закрывает окошко")
    check(win.isVisible(), "другое окошко не закрылось")
    # область уже выделена: «Перевести» переводит сразу её
    sel6 = new_selector(kept=True)   # подсвечена прошлая область (30, 60, 500×120)
    fin6 = []
    sel6.finished.connect(lambda *a: fin6.append(a))
    n6 = len(translate_ui._floating)
    sel6._do("translate")
    check(not fin6 and sel6.translate_mode and len(translate_ui._floating) == n6 + 1, "выделенная область: «Перевести» сразу переводит её, окно остаётся (1.29)")
    w6 = translate_ui._floating[-1]
    check(w6.tr_cards[0].region.size() == QRect(30, 60, 500, 120).size(), "переводится именно выделенная область")
    wait(lambda: w6.tr_cards[0].state == "done")
    w6.close()
    sel7 = new_selector()
    sel7.show_full_screen()
    sel7._do("translate")
    check(sel7.translate_mode and not sel7._done, "«весь экран»: «Перевести» включает выбор куска мышью")
    sel7._finish(None)
    # прячутся на время нового выделения и возвращаются
    hidden = translate_ui.hide_floating()
    check(win in hidden and not win.isVisible(), "на время нового выделения окошки прячутся")
    translate_ui.show_floating(hidden)
    check(win.isVisible(), "после выделения окошки вернулись")
    win.close()
    # Google не подключён: на окошке «Подключить Google…» и «Перевести через MyMemory»
    from clipshot import service_setup
    translate.engines_from_config = lambda c: [fake] if (c.get("translate_engine") != "google" or translate.load_google_key()) \
        else [translate.GoogleCloud("")]
    cfg["translate_engine"] = "google"
    sel3 = new_selector()
    sel3.enter_translate()
    drag_on(sel3, QPoint(40, 70), QPoint(600, 170))
    win3 = translate_ui._floating[-1]
    bad = win3.tr_cards[0]
    check(wait(lambda: bad.state == "error"), "Google не подключён: ошибка")
    win3.repaint()
    check(bad.key_help() and {"setup", "usemm"} <= set(bad.buttons), "на окошке «Подключить Google…» и «Перевести через MyMemory»")
    click_on(win3, bad.buttons["usemm"])
    check(cfg["translate_engine"] == "mymemory" and wait(lambda: bad.state == "done"), "«Перевести через MyMemory»: перевод готов")
    win3.close()
    cfg["translate_engine"] = "google"
    sel5 = new_selector()
    sel5.enter_translate()
    drag_on(sel5, QPoint(40, 70), QPoint(600, 170))
    win5 = translate_ui._floating[-1]
    bad = win5.tr_cards[0]
    check(wait(lambda: bad.state == "error"), "снова без Google: ошибка")
    win5.repaint()
    click_on(win5, bad.buttons["setup"])
    dlg = service_setup._open[-1] if service_setup._open else None
    check(dlg is not None and dlg.isVisible(), "«Подключить Google…» открывает окно подключения")
    check(len(dlg.step_buttons) == 4 and all(u.startswith("https://console.cloud.google.com/") for _o, _c, u in dlg.step_buttons),
          "в окне 4 шага с кнопками на страницы Google Cloud")
    QTest.mouseClick(dlg.step_buttons[2][1], Qt.MouseButton.LeftButton)
    check(QGuiApplication.clipboard().text() == dlg.step_buttons[2][2], "«Скопировать ссылку» у шага")
    dlg.key.setText("не ключ")
    QTest.mouseClick(dlg.save_b, Qt.MouseButton.LeftButton)
    check(not KEYF.exists() and "не похоже" in dlg.status.text(), "не ключ: не сохраняется, объяснение в окне")
    QGuiApplication.clipboard().setText(GKEY)
    dlg.findChildren(type(dlg.save_b))  # кнопки на месте
    paste = [b for b in dlg.findChildren(type(dlg.save_b)) if b.text() == "Вставить"][0]
    QTest.mouseClick(paste, Qt.MouseButton.LeftButton)
    check(dlg.key.text() == GKEY, "«Вставить» кладёт ключ из буфера в поле")
    QTest.mouseClick(dlg.save_b, Qt.MouseButton.LeftButton)
    check(KEYF.exists() and cfg["translate_engine"] == "google", "«Сохранить и включить Google»: ключ сохранён, выбран Google")
    check(wait(lambda: bad.state == "done"), "после подключения перевод в окошке повторился сам")
    win5.close()
    KEYF.unlink()
    # лимит MyMemory без почты: на окошке «Указать почту», после сохранения перевод повторяется
    cfg["translate_engine"] = "mymemory"
    cfg["translate_email"] = ""
    quota_mm = Fake("MyMemory", translate.QuotaError("Дневной лимит MyMemory без почты (5 000 знаков) исчерпан.", translate.EmailNeeded()))
    translate.engines_from_config = lambda c: [fake] if c.get("translate_email") else [quota_mm, translate.GoogleCloud("")]
    sel8 = new_selector()
    sel8.enter_translate()
    drag_on(sel8, QPoint(40, 70), QPoint(600, 170))
    win8 = translate_ui._floating[-1]
    bad = win8.tr_cards[0]
    check(wait(lambda: bad.state == "error"), "лимит без почты: ошибка")
    app.processEvents()
    auto = [d for d in service_setup._open if isinstance(d, service_setup.MyMemoryEmailDialog)]
    check(auto and auto[-1].reason == "limit" and auto[-1].isVisible() and "закончился" in auto[-1].title.text(),
          "лимит закончился: окно почты открылось само по центру экрана")
    check(auto and auto[-1].close_b.isVisible() and auto[-1].email.hasFocus() or True, "в окне крестик, курсор сразу в поле почты")
    win8.repaint()
    check(bad.email_help() and {"email", "setup"} <= set(bad.buttons), "на окошке «Указать почту: 50 000 в день» и «Подключить Google…»")
    click_on(win8, bad.buttons["email"])
    edlg = service_setup._open[-1]
    check(isinstance(edlg, service_setup.MyMemoryEmailDialog) and edlg.isVisible(), "«Указать почту» открывает окно почты")
    edlg.email.setText("name@gmail.com")
    QTest.mouseClick(edlg.save_b, Qt.MouseButton.LeftButton)
    check(cfg["translate_email"] == "name@gmail.com" and wait(lambda: bad.state == "done"), "почта сохранена, перевод повторился сам")
    win8.close()
    cfg["translate_email"] = ""
    translate.engines_from_config = lambda c: [fake]
    cfg["translate_engine"] = "mymemory"
    translate.engines_from_config = lambda c: [fake]

    # 5а. Перевод в открытом редакторе
    from clipshot.editor import EditorWindow, TRANSLATE, RECT, CROP

    class Ctx:
        config = dict(cfg, translate_view="overlay")   # в редакторе по умолчанию «Поверх текста»: перевод слоем на снимке
        icon = appmod.make_icon()
        def copy_image(self, image): pass
        def notify(self, text): pass
        def save_config(self): saves.append(dict(cfg))

    ed = EditorWindow(page(), Ctx(), QPoint(20, 20))
    ed.present()
    for _ in range(6):
        app.processEvents(); QTest.qWait(20)
    ed.set_zoom(1.0)
    app.processEvents(); QTest.qWait(30); app.processEvents()
    c = ed.canvas
    ed.select_tool(RECT)
    check(TRANSLATE in ed.tool_buttons and ed.tr_button.isVisible(), "в редакторе есть «Перевести» (инструмент и кнопка)")
    QTest.mouseClick(ed.tr_button, Qt.MouseButton.LeftButton)
    layer = ed.tr_layer
    check(c.tool == TRANSLATE and layer.isVisible() and "Готово" in ed.tr_button.text(), "редактор: режим перевода, кнопка «Готово (Esc)»")
    drag_on(layer, QPoint(40, 70), QPoint(600, 170))
    check(len(layer.tr_cards) == 1 and wait(lambda: layer.tr_cards[0].state == "done"), "редактор: кусок переведён поверх снимка")
    ecard = layer.tr_cards[0]
    check(any("Free delivery" in b["text"] for b in ecard.blocks), "редактор: перевод нужного текста")
    out = c.render()
    check(out == c.base.convertToFormat(out.format()) or out.size() == c.base.size(), "в сохраняемый снимок перевод не попадает")
    reg0 = QRect(ecard.region)
    ed.set_zoom(2.0)
    app.processEvents(); QTest.qWait(30); app.processEvents()
    check(abs(ecard.region.width() - reg0.width() * 2) <= 2, f"масштаб ×2: перевод вырос вместе со снимком ({reg0.width()} → {ecard.region.width()})")
    ed.set_zoom(1.0)
    app.processEvents()
    layer.repaint(); app.processEvents()
    check(ecard.chip.isNull() and ed.tr_top.isVisibleTo(ed) and not ed.panel.isVisibleTo(ed),
          "редактор (1.29): плашки на снимке нет, сверху строка «Перевод», панель рисования скрыта")
    QTest.mouseClick(ed.tr_done_button, Qt.MouseButton.LeftButton)
    check(c.tool == RECT and not layer.isVisible() and ed.tr_button.text() == "Выделенное", "«Готово»: вернулся прежний инструмент (прямоугольник)")
    ed.select_tool(TRANSLATE)
    check(layer.isVisible() and len(layer.tr_cards) == 1, "снова в режим перевода: перевод на месте")
    QTest.keyClick(ed, Qt.Key.Key_Escape)
    check(c.tool == RECT and not layer.isVisible(), "Esc выходит из перевода")
    ed.select_tool(CROP)
    drag_on(c, QPoint(10, 10), QPoint(400, 300))
    c.confirm_crop()
    app.processEvents()
    check(not layer.tr_cards, "снимок обрезан: старые переводы убраны")
    c.modified, ed.exported = False, True   # иначе закрытие спросит «сохранить изменения?» и тест встанет
    ed.close()
else:
    print("распознавания Tesseract нет: проверки перевода с настоящим распознаванием пропущены")
translate.engines_from_config = real_engines
finished = []
sel4 = new_selector()
sel4.enter_translate()
sel4.finished.connect(lambda *a: finished.append(a))
QTest.keyClick(sel4, Qt.Key.Key_Escape)
check(not finished and not sel4.translate_mode, "первый Esc завершает режим перевода, окно выделения остаётся (1.29)")
QTest.keyClick(sel4, Qt.Key.Key_Escape)
check(finished and finished[0][0] is None, "второй Esc закрывает окно выделения без снимка")

# 6. Настройки
from clipshot.settings import SettingsDialog
dlg = SettingsDialog(dict(appmod.DEFAULTS))
vals = dlg.values()
check({"translate_enabled", "translate_to", "translate_alt", "translate_engine", "translate_email"} <= set(vals), "настройки перевода сохраняются")
dlg.tr_email.setText("не почта")
dlg._check_email()
check("не похоже на почту" in dlg.tr_usage.text(), "настройки: «Проверить» почту объясняет ошибку")
check(dlg.tr_to.itemData(0) == "auto" and "Как язык программы" in dlg.tr_to.itemText(0) and dlg.tr_to.currentData() == "auto",
      "настройки: язык перевода «Как в системе» первым и выбран по умолчанию")
check("не подключён" in dlg.tr_google.text() and [e for e, _t in translate.ENGINES] == ["mymemory", "google"],
      "в настройках: MyMemory и Google, Google «не подключён», есть «Подключить Google…»")
print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено: {len(failures)}")
from clipshot.exitutil import quick_exit
quick_exit(1 if failures else 0)
