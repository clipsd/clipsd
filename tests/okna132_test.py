# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Окна обновления и сообщения в стиле окон ClipSD (1.32).

Что проверяется: (1) цвета светлой и тёмной карточки по норме 4,5:1 без окон; (2) каждое новое окно нарисовано в
обеих темах, каждый видимый текст измерен по пикселям (не ниже 4,5:1, включая белый на зелёной кнопке); (3) в окне
одна главная зелёная кнопка; (4) стандартных окошек Qt (QMessageBox) в коде не осталось; (5) окно предложения: краткий
список изменений, ссылка «Показать все изменения», срочное без «Пропустить», Esc = «Позже»; (6) все 12 языков: окна
помещаются в экран 1280 x 720, подписи кнопок не сжаты, тексты найдены в каталоге.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/okna132_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import glob
import os
import re
import sys
import tempfile
from collections import Counter
from datetime import datetime, timedelta, timezone

here = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(here)
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp(prefix="clipsd-okna-")
for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[name] = os.path.join(tmp, name)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.pop("CLIPSD_LANG", None)

from PyQt6.QtCore import QRect, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QImage  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QAbstractButton, QApplication, QLabel, QPlainTextEdit, QPushButton, QTextEdit, QWidget  # noqa: E402

app = QApplication(sys.argv)
_font = app.font()
_font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)   # пиксели текста ровно цвета текста: точное измерение
app.setFont(_font)

from clipshot import app as appmod, dialogs, i18n, themes  # noqa: E402
from clipshot import update_channel as uc, update_windows as uw, updater as up  # noqa: E402
from clipshot.i18n import tr  # noqa: E402

failures = []
measured = [0]


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


def settle(n=4):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(5)


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def lum_hex(h):
    def lin(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = rgb(h)
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def ratio(a, b):
    la, lb = sorted((lum_hex(a), lum_hex(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# --- 1. цвета карточки ------------------------------------------------------------------------------------------
for dark in (False, True):
    c = dialogs.PALETTES[dark]
    name = "тёмная" if dark else "светлая"
    for fg, bg, what, need in ((c["text"], c["card"], "текст", 4.5), (c["muted"], c["card"], "пояснение", 4.5),
                               (c["link"], c["card"], "ссылка", 4.5), (c["warn_text"], c["warn_bg"], "текст плашки", 4.5),
                               (c["text"], c["note_bg"], "текст в поле заметок", 4.5),
                               (c["accent"], c["track"], "полоса загрузки на дорожке", 3.0),
                               (c["text"], c["field"], "текст в поле", 4.5)):
        r = ratio(fg, bg)
        check(r >= need, f"{name} карточка, {what}: {fg} на {bg} {r:.2f}:1 (нужно {need}:1)")
check(ratio("#ffffff", themes.GREEN) >= 4.5 and ratio("#ffffff", themes.GREEN_HOVER) >= 4.5, "белый на зелёной главной кнопке 4,5:1 и выше")
for dark, ok_c, err_c in ((False, "#157a40", "#b42318"), (True, "#5fd08a", "#ff8a80")):
    card = dialogs.PALETTES[dark]["card"]
    check(ratio(ok_c, card) >= 4.5 and ratio(err_c, card) >= 4.5, f"статус «готово» и «ошибка» на карточке ({'тёмной' if dark else 'светлой'}) читается")

# --- 2. стандартных окошек Qt в коде нет -----------------------------------------------------------------------
offenders = []
for path in glob.glob(os.path.join(ROOT, "clipshot", "*.py")):
    text = open(path, encoding="utf-8").read()
    if re.search(r"QMessageBox\s*[.(]", text):
        offenders.append(os.path.basename(path))
check(not offenders, f"в коде нет QMessageBox (стандартное окошко Qt с «OK»): {offenders or 'чисто'}")

# --- окна ----------------------------------------------------------------------------------------------------------
NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
NOTES = {lang: open(os.path.join(ROOT, "CHANGELOG", "1.32.0", f"{lang}.md"), encoding="utf-8").read() for lang in ("ru", "en")}
MANIFEST = uc.Manifest(channel="stable", version="1.32.0", released=NOW, expires=NOW + timedelta(days=30), files={}, notes=NOTES)
REPORT = "ClipSD 1.32.0\nreason: helper_exit_1\nlog:\n  start\n"


def lum(c: QColor) -> float:
    return lum_hex(c.name())


def contrast(a: QColor, b: QColor) -> float:
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def text_contrast(img, rect, inset):
    r = rect.adjusted(inset, inset, -inset, -inset).intersected(img.rect())
    counts = Counter()
    for y in range(r.top(), r.bottom() + 1):
        for x in range(r.left(), r.right() + 1):
            counts[img.pixel(x, y) & 0xFFFFFF] += 1
    if not counts:
        return None
    bg = QColor(counts.most_common(1)[0][0])
    best, fg = 1.0, bg
    for rgb_value, n in counts.items():
        if n < 2:
            continue
        k = contrast(bg, QColor(rgb_value))
        if k > best:
            best, fg = k, QColor(rgb_value)
    return best, bg, fg


def texts_of(root):
    out = []
    for w in root.findChildren(QWidget):
        if not w.isVisible() or w.width() < 8 or w.height() < 8:
            continue
        if isinstance(w, QLabel) and w.text().strip() and w.pixmap().isNull():
            out.append((w, 0))
        elif isinstance(w, QAbstractButton) and w.text().strip():
            out.append((w, 4))
        elif isinstance(w, (QPlainTextEdit, QTextEdit)):
            out.append((w.viewport(), 2))
    return out


def audit(window, where):
    window.ensurePolished()
    settle()
    img = window.grab().toImage().convertToFormat(QImage.Format.Format_RGB32)
    scale = img.width() / max(window.width(), 1)
    bad = []
    for w, inset in texts_of(window):
        if not w.isEnabled() or w.objectName() == "rateStar" or (isinstance(w, QLabel) and w.text().strip().isdigit()):
            continue   # звёзды оценки и номера шагов: значки, не текст (по 3:1, утверждены раньше)
        seen = w.visibleRegion().boundingRect()
        if seen.isEmpty():
            continue
        top_left = w.mapTo(window, seen.topLeft())
        rect = QRect(int(top_left.x() * scale), int(top_left.y() * scale), int(seen.width() * scale), int(seen.height() * scale))
        res = text_contrast(img, rect, inset)
        if res is None:
            continue
        k, bg, fg = res
        measured[0] += 1
        owner = w.parentWidget() if w.objectName() == "qt_scrollarea_viewport" else w
        if k < 4.5:
            bad.append(f"«{str(getattr(owner, 'text', lambda: owner.objectName())())[:30]}» {k:.2f} ({fg.name()} на {bg.name()})")
    check(not bad, f"{where}: каждый видимый текст не ниже 4,5:1{': ' + '; '.join(bad) if bad else ''}")


def primaries(window):
    return [b for b in window.findChildren(QPushButton) if b.objectName() == "clipPrimary" and b.isVisibleTo(window)]


class Ctx:
    def __init__(self, theme):
        self.config = dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True, ui_theme=theme)
        self.icon = appmod.make_icon()

    def save_config(self):
        pass

    def notify(self, _t):
        pass


def make_windows():
    """(название, окно): всё, что мы нарисовали заново в 1.32."""
    ui = up.UpdaterUI()
    windows = [("предложение", uw.OfferDialog(MANIFEST, "1.31.2")),
               ("срочное", uw.OfferDialog(MANIFEST, "1.31.2", critical=True)),
               ("что нового", uw.WhatsNewDialog("1.32.0", NOTES["en"])),
               ("не установилась", uw.FailedDialog("1.32.0", REPORT, "t")),
               ("не установилась, подсказка", uw.FailedDialog("1.32.0", REPORT, "t", hint=tr("updater.failed.cannot_detach"))),
               ("отчёт", uw.ReportDialog(REPORT, "t", endpoint="")),
               ("отчёт с отправкой", uw.ReportDialog(REPORT, "t", endpoint="https://example.invalid/r")),
               ("ожидание", uw.waiting_card(tr("updater.wait.unsaved", version="1.32.0"))),
               ("сообщение", dialogs.MessageCard(None, tr("updater.offer.title"), tr("updater.up_to_date", version="1.32.0"))),
               ("ошибка", dialogs.MessageCard(None, tr("updater.error.title"), tr("updater.error.check"), "error")),
               ("вручную", dialogs.MessageCard(None, tr("updater.manual.title", version="1.32.0"), tr("updater.manual.text", version="1.32.0"),
                                              "info", primary=tr("updater.button.open_site"), secondary=tr("updater.button.close"))),
               ("ошибка сохранения", dialogs.MessageCard(None, tr("editor.error"), tr("editor.save_error", path="/home/u/a.png"), "error"))]
    ui.progress_start("1.32.0", lambda: None)
    ui.progress_update(23 * 1024 * 1024, 59 * 1024 * 1024)
    windows.append(("загрузка", ui.progress))
    return ui, windows


# --- 3. обе темы, ru и en: пиксели, одна зелёная кнопка ----------------------------------------------------------
for theme in ("standard", "pro"):
    ctx = Ctx(theme)
    for lang in ("ru", "en"):
        i18n.set_language(lang)
        themes.apply_app(app, ctx.config)
        ui, windows = make_windows()
        for name, w in windows:
            w.show()
            settle(3)
            tag = f"{theme}/{lang}/{name}"
            check(w.dark == (theme == "pro"), f"{tag}: карточка {'тёмная' if theme == 'pro' else 'светлая'}")
            img = w.grab().toImage()
            card = w.card.mapTo(w, w.card.rect().center())
            probe = img.pixelColor(int(card.x() * img.width() / w.width()), int(w.card.mapTo(w, w.card.rect().topLeft()).y() * img.height() / w.height()) + 4)
            check(probe.name() == dialogs.PALETTES[w.dark]["card"], f"{tag}: фон карточки {probe.name()}")
            audit(w, tag)
            n = len(primaries(w))
            if name != "загрузка":
                check(n == 1, f"{tag}: одна главная зелёная кнопка (найдено {n})")
            else:
                check(n == 0, f"{tag}: в загрузке главной кнопки нет, только «Отмена»")
        ui.progress_stage(tr("updater.install.started", version="1.32.0"))
        audit(ui.progress, f"{theme}/{lang}/установка")
        ui.progress_close()
        for _name, w in windows:
            w.close()
        # выбор оформления
        from clipshot.theme_chooser import ThemeChooser
        ch = ThemeChooser(Ctx(theme))
        ch.show()
        settle(3)
        audit(ch, f"{theme}/{lang}/выбор оформления")
        check(len(primaries(ch)) == 1 and ch.ok.text() == tr("theme_chooser.ok"), f"{theme}/{lang}: выбор оформления, одна зелёная «Продолжить»")
        ch.close()
check(measured[0] > 300, f"измерено текстов: {measured[0]}")

# --- 3b. прежние окна-карточки тоже следуют оформлению (решение владельца 19.11.2026) --------------------------------
def make_cards():
    from types import SimpleNamespace
    from PyQt6.QtGui import QIcon
    from clipshot import feedback, ocr, service_setup
    from clipshot.editor import ConfirmDialog
    cfg = dict(appmod.DEFAULTS)
    cards = [("О программе", appmod.Clipshot.build_about(SimpleNamespace(icon=QIcon()))),
             ("оценка", feedback.build_rating_dialog(cfg)),
             ("спасибо за оценку", feedback.build_thanks_dialog(5, "", None)),
             ("уже оценили", feedback.build_already_dialog(dict(cfg, rating_stars=4, rating_day="2026-11-19"))),
             ("почта MyMemory", service_setup.MyMemoryEmailDialog(None, {})),
             ("ключ Google", service_setup.GoogleSetupDialog(None, {})),
             ("распознанный текст", ocr.TextResultDialog("Пример текста\nвторая строка")),
             ("вопрос", ConfirmDialog(None, "Снимок не сохранён", "Закрыть без сохранения?"))]
    return [(n, w) for n, w in cards]


for theme in ("standard", "pro"):
    for lang in ("ru", "en"):
        i18n.set_language(lang)
        themes.apply_app(app, Ctx(theme).config)
        for name, w in make_cards():
            w.show()
            settle(3)
            tag = f"{theme}/{lang}/{name}"
            check(w.dark == (theme == "pro"), f"{tag}: карточка {'тёмная' if theme == 'pro' else 'светлая'}")
            audit(w, tag)
            w.close()

# --- 4. окно предложения ------------------------------------------------------------------------------------------
i18n.set_language("ru")
themes.apply_app(app, Ctx("standard").config)
bullets = uw.note_headlines(NOTES["ru"])
check(len(bullets) == uw.NOTE_ITEMS and all(0 < len(b) <= uw.NOTE_CHARS + 1 for b in bullets), f"краткий список: {len(bullets)} строки не длиннее {uw.NOTE_CHARS} знаков")
check(uw.note_headlines("Просто текст без списка") == [] and uw.note_headlines("- **Жирное** [ссылка](https://x.y). Дальше.") == ["Жирное ссылка."],
      "краткий список: без списка пусто, разметка снята, берётся первое предложение")
offer = up.OfferDialog(MANIFEST, "1.31.2")
offer.show()
settle()
check(offer.headlines == bullets and offer.title.text() == tr("updater.offer.heading", version="1.32.0")
      and offer.subtitle.text() == tr("updater.offer.installed", current="1.31.2"), "предложение: заголовок, «У вас версия», три изменения")
check(not offer.notes_view.isVisibleTo(offer) and offer.notes_link.text() == tr("updater.offer.show_notes"), "полные заметки свёрнуты за ссылкой")
offer.notes_link.click()
check(offer.notes_view.isVisibleTo(offer) and offer.notes_link.text() == tr("updater.offer.hide_notes") and offer.height() < 900,
      "ссылка раскрывает полные заметки внутри окна, и окно остаётся невысоким")
offer.close()
plain = uw.OfferDialog(uc.Manifest(channel="stable", version="1.32.0", released=NOW, expires=NOW + timedelta(days=30), files={},
                                   notes={"ru": "Просто текст без списка"}), "1.31.2")
plain.show()
settle()
check(plain.headlines == [] and plain.notes_link.text().startswith(tr("updater.offer.whatsnew")), "заметки без пунктов: без списка, ссылка «Что нового»")
plain.close()
for key, expect in (("skip_button", "skip"), ("later_button", "later"), ("update_button", "update")):
    o = up.OfferDialog(MANIFEST, "1.31.2")
    o.show()
    getattr(o, key).click()
    check(o.choice == expect, f"предложение: «{getattr(o, key).text()}» даёт {expect}")
o = up.OfferDialog(MANIFEST, "1.31.2")
o.show()
QTest.keyClick(o, Qt.Key.Key_Escape)
check(o.choice == "later" and not o.isVisible(), "Esc и крестик = «Позже»")
c = up.OfferDialog(MANIFEST, "1.31.2", critical=True)
c.show()
settle()
check(c.skip_button.isHidden() and c.windowTitle().endswith(tr("updater.offer.title_security")) and c.findChild(QLabel, "security") is not None,
      "срочное: «Пропустить» скрыто, плашка «Обновление безопасности»")
c.close()

# --- 5. загрузка ----------------------------------------------------------------------------------------------------
pd = up.ProgressDialog("1.32.0", lambda: None)
pd.show()
pd.set_progress(23 * 1024 * 1024, 59 * 1024 * 1024)
check(pd.bar.value() == 38 and "38%" in pd.status.text() and not pd.bar.isTextVisible() and pd.bar.height() <= 8,
      f"загрузка: тонкая полоса без текста, рядом «{pd.status.text()}»")
pd.set_stage("Installing")
check(pd.bar.maximum() == 0 and pd.cancel_button.isHidden() and pd.subtitle.isHidden(), "установка: полоса без процентов, отмены нет")
pd.close()

# --- 6. 12 языков: помещается в экран 1280 x 720, кнопки не сжаты, ключи найдены ------------------------------------
for lang in i18n.LANGUAGES:
    i18n.set_language(lang)
    for theme in ("standard", "pro"):
        themes.apply_app(app, Ctx(theme).config)
        ui, windows = make_windows()
        bad_size, bad_btn, raw = [], [], []
        for name, w in windows:
            w.show()
            settle(2)
            if w.height() > 720 or w.width() > 1280:
                bad_size.append(f"{name} {w.width()}x{w.height()}")
            for b in w.findChildren(QAbstractButton):
                if b.isVisibleTo(w) and b.text() and b.width() < b.sizeHint().width():
                    bad_btn.append(f"{name}:{b.text()}")
            for label in w.findChildren(QLabel):
                if label.isVisibleTo(w) and re.match(r"^(updater|dialogs|editor|theme_chooser)\.\w+", label.text() or ""):
                    raw.append(label.text())
        check(not bad_size, f"{lang}/{theme}: окна помещаются в 1280 x 720 {bad_size or ''}")
        check(not bad_btn, f"{lang}/{theme}: подписи кнопок целиком {bad_btn[:3] or ''}")
        check(not raw, f"{lang}/{theme}: тексты найдены в каталоге {raw[:3] or ''}")
        ui.progress_close()
        for _name, w in windows:
            w.close()

# --- 7. новые строки без длинных тире и без эмодзи ----------------------------------------------------------------
import json  # noqa: E402
pat = re.compile("[—–\U0001F300-\U0001FAFF☀-➿]")
keys = ("updater.button.done", "updater.offer.lead", "updater.offer.whatsnew", "updater.offer.show_notes", "updater.offer.hide_notes",
        "updater.offer.security_head", "updater.progress.sub", "updater.failed.title", "updater.wait.title", "updater.manual.title",
        "updater.whatsnew.head", "updater.error.title", "updater.download.progress_pct", "updater.failed.text")
dirty = []
for lang in i18n.LANGUAGES:
    cat = json.load(open(os.path.join(ROOT, "clipshot", "i18n", lang, "updater.json"), encoding="utf-8"))
    dlg = json.load(open(os.path.join(ROOT, "clipshot", "i18n", lang, "dialogs.json"), encoding="utf-8"))
    for k in keys:
        if k not in cat or pat.search(cat[k]):
            dirty.append(f"{lang}:{k}")
    if "dialogs.ok" not in dlg or pat.search(dlg["dialogs.ok"]):
        dirty.append(f"{lang}:dialogs.ok")
check(not dirty, f"новые строки есть во всех 12 языках, без длинных тире и эмодзи {dirty[:4] or ''}")

print(f"ИТОГ: измерено текстов {measured[0]}, провалено: {len(failures)}")
sys.exit(1 if failures else 0)
