# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Окно «Снимок не сохранён» при закрытии редактора (замечание владельца 21.11.2026: текст бледный, читается трудно).

Окно открывается тем же путём, что у человека (закрытие редактора с несохранёнными правками). Проверки: текст цветом
основного текста карточки и 15 px, строка «Esc: вернуться к редактированию» не бледнее 4,5:1 (по пикселям снимка
окна, светлая и тёмная тема, ru и de, масштаб 1 и 1,5); одна зелёная кнопка «Скопировать и закрыть», «Сохранить»
спокойная, «Закрыть без сохранения» слева красным текстом; Enter копирует и закрывает, Esc и крестик возвращают к
редактированию; что делает каждая кнопка; окно не шире экрана 1280 на 12 языках, подписи кнопок не сжаты; карточка
без QGraphicsEffect (на Windows эффект делал буквы бледными и размытыми).

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/vyhod_okno_test.py  (масштаб 1,5: QT_SCALE_FACTOR=1.5, тест сам
перезапускает себя с ним)
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
os.environ.pop("CLIPSD_LANG", None)
SCALE = os.environ.get("QT_SCALE_FACTOR", "1")
_cfg = os.path.join(tempfile.mkdtemp(prefix="clipsd-vyhod-"), "screen.json")
with open(_cfg, "w", encoding="utf-8") as _f:
    k = float(SCALE)
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": int(1280 * k), "height": int(720 * k),
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _cfg

from PyQt6.QtCore import QEvent, QPoint, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QFontMetrics, QGuiApplication, QImage, QKeyEvent  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QPushButton  # noqa: E402

app = QApplication(sys.argv)
from clipshot import app as appmod, dialogs, i18n, themes  # noqa: E402
from clipshot import editor as em  # noqa: E402
from clipshot.editor import ConfirmDialog, EditorWindow  # noqa: E402

LANGS = ("ru", "en", "es", "de", "fr", "it", "pt", "pl", "tr", "uk", "bg", "zh")
failures = []
checks = [0]


def check(cond, msg):
    checks[0] += 1
    print(("OK   " if cond else "FAIL ") + f"[x{SCALE}] " + msg)
    if not cond:
        failures.append(msg)


def settle(ms=30):
    QTest.qWait(ms)


def lum(c):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c.red()) + 0.7152 * ch(c.green()) + 0.0722 * ch(c.blue())


def contrast(a, b):
    la, lb = sorted((lum(QColor(a)), lum(QColor(b))), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def text_contrast(img, rect):
    """Контраст текста по пикселям: фон самый частый цвет, текст самый далёкий от него (встречается не раз)."""
    r = rect.intersected(img.rect())
    counts = Counter()
    for y in range(r.top(), r.bottom() + 1):
        for x in range(r.left(), r.right() + 1):
            counts[img.pixel(x, y) & 0xFFFFFF] += 1
    bg = QColor(counts.most_common(1)[0][0])
    best, fg = 1.0, bg
    for rgb, n in counts.items():
        if n >= 2 and contrast(bg, QColor(rgb)) > best:
            best, fg = contrast(bg, QColor(rgb)), QColor(rgb)
    return best, bg, fg


class Ctx:
    def __init__(self, **kw):
        self.config = dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True, **kw)
        self.icon = appmod.make_icon()
        self.notes = []

    def save_config(self):
        pass

    def notify(self, text):
        self.notes.append(text)

    def copy_image(self, image, config=None):
        from clipshot import hidpi
        hidpi.copy_image(image, config or self.config)


def image(w=600, h=300):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor("#f4f6f9"))
    return img


def mk(theme="standard"):
    ctx = Ctx(ui_theme=theme)
    themes.apply_app(app, ctx.config)
    ed = EditorWindow(image(), ctx, QPoint(0, 0))
    ed.present()
    settle(60)
    ed.canvas.modified, ed.exported = True, False
    return ed, ctx


def ask(ed, answer=None, on_show=None):
    """Закрыть редактор с несохранёнными правками; окно показывается, on_show(dlg) смотрит его, ответ answer
    (по умолчанию: что окно получило от кнопок или клавиш внутри on_show)."""
    seen = []
    real = ConfirmDialog.exec

    def fake(dlg):
        dlg.show()
        settle(120)
        seen.append(dlg)
        if on_show is not None:
            on_show(dlg)
        res = answer if answer is not None else dlg.result()
        dlg.hide()
        return res
    ConfirmDialog.exec = fake
    try:
        ed.close()
    finally:
        ConfirmDialog.exec = real
    settle(60)
    return seen[0] if seen else None


def finish(ed):
    ed.canvas.modified, ed.exported = False, True
    ed.close()
    settle(20)


# --- 1. вид: тексты, цвет и размер, кнопки -----------------------------------------------------------------------
for theme in ("standard", "pro"):
    dark = theme == "pro"
    pal = dialogs.PALETTES[dark]
    for lang in ("ru", "de"):
        i18n.set_language(lang)
        ed, ctx = mk(theme)
        info = {}

        def look(dlg, info=info):
            img = dlg.grab().toImage()
            dpr = img.devicePixelRatio()
            for name, w in (("body", dlg.body_label), ("note", dlg.note_label), ("title", dlg.title)):
                g = w.geometry()
                top_left = w.mapTo(dlg, QPoint(0, 0))
                from PyQt6.QtCore import QRect
                r = QRect(int(top_left.x() * dpr), int(top_left.y() * dpr), int(g.width() * dpr), int(g.height() * dpr))
                info[name] = text_contrast(img, r)
            info["dlg"] = dlg
            info["fonts"] = (dlg.body_label.font().pixelSize(), dlg.note_label.font().pixelSize())
            info["texts"] = (dlg.body_label.text(), dlg.note_label.text())
            info["buttons"] = [(b.objectName(), b.text()) for b in dlg.findChildren(QPushButton) if b.isVisible()]
            info["left"] = [dlg.footer_left.itemAt(i).widget() for i in range(dlg.footer_left.count())]
            info["effect"] = dlg.card.graphicsEffect()
            info["size"] = (dlg.width(), dlg.height())
        dlg = ask(ed, ConfirmDialog.CANCEL, look)
        tag = f"{lang} {'тёмная' if dark else 'светлая'}"
        check(dlg is not None and ed.isVisible(), f"{tag}: закрытие с правками спрашивает, «вернуться» оставляет редактор")
        body_k, body_bg, body_fg = info["body"]
        check(body_k >= 4.5 and contrast(body_fg, pal["text"]) < 1.25 and body_k >= 0.8 * contrast(pal["text"], pal["card"]),
              f"{tag}: основной текст цветом основного текста ({body_fg.name()} на {body_bg.name()}, {body_k:.1f}:1)")
        note_k = info["note"][0]
        check(note_k >= 4.5, f"{tag}: «Esc: …» не бледнее 4,5:1 ({note_k:.1f}:1)")
        check(info["fonts"][0] >= 15 and info["fonts"][1] >= 13, f"{tag}: текст 15 px, пояснение 13 px ({info['fonts']})")
        check(info["texts"][0] == i18n.tr("editor.unsaved_text") and info["texts"][1] == i18n.tr("editor.unsaved_hint")
              and "\n" not in info["texts"][0], f"{tag}: текст и отдельная строка про Esc")
        names = [n for n, _t in info["buttons"]]
        check(names.count("clipPrimary") == 1 and dict((t, n) for n, t in info["buttons"]).get(i18n.tr("editor.copy_close")) == "clipPrimary",
              f"{tag}: одна зелёная кнопка, это «{i18n.tr('editor.copy_close')}»")
        check(dict((t, n) for n, t in info["buttons"]).get(i18n.tr("editor.save")) == "clipSecondary",
              f"{tag}: «{i18n.tr('editor.save')}» спокойная")
        disc = [w for w in info["left"] if isinstance(w, QPushButton)]
        check(len(disc) == 1 and disc[0].objectName() == "clipDanger" and disc[0].text() == i18n.tr("editor.unsaved_discard"),
              f"{tag}: «{i18n.tr('editor.unsaved_discard')}» отдельно слева, красным текстом")
        check(contrast(pal["danger"], pal["card"]) >= 4.5, f"{tag}: красный текст кнопки {contrast(pal['danger'], pal['card']):.1f}:1")
        check(info["effect"] is None, f"{tag}: карточка без QGraphicsEffect, текст рисуется прямо в окно")
        finish(ed)

# --- 2. клавиши и кнопки -------------------------------------------------------------------------------------------
i18n.set_language("ru")
themes.apply_app(app, {"ui_theme": "standard"})


def press(key):
    return lambda dlg: dlg.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))


ed, ctx = mk()
ask(ed, None, press(Qt.Key.Key_Escape))
check(ed.isVisible() and not ed.exported, "Esc: окно закрылось, редактор остался, ничего не сделано")
ask(ed, None, lambda dlg: dlg.close_b.click())
check(ed.isVisible(), "крестик: вернуться к редактированию")
closed = []
ed.closed.connect(closed.append)
QGuiApplication.clipboard().clear()
ask(ed, None, press(Qt.Key.Key_Return))
settle(150)
clip = QGuiApplication.clipboard().image()
check(closed == [ed] and not clip.isNull(), "Enter: «Скопировать и закрыть», снимок в буфере обмена, редактор закрыт")

ed, ctx = mk()
asked_path = []
real_ask = em.ask_save_path
em.ask_save_path = lambda *a, **k: asked_path.append(1) or ""
ask(ed, None, lambda dlg: dlg.no.click())
settle(120)
em.ask_save_path = real_ask
check(asked_path == [1] and ed.isVisible(), "«Сохранить»: окно выбора файла; отказ в нём оставляет редактор")
closed = []
ed.closed.connect(closed.append)
ask(ed, None, lambda dlg: dlg.yes.click())
settle(60)
check(closed == [ed], "«Закрыть без сохранения»: редактор закрыт")

ed, ctx = mk()
closed = []
ed.closed.connect(closed.append)
asked = []
ask(ed, None, lambda dlg: (asked.append(1), dlg.extra.click()))
settle(150)
check(closed == [ed] and asked == [1], "«Скопировать и закрыть» мышью: скопировано, закрыто без второго вопроса")

# старый вызов (две кнопки) работает как раньше
cd = ConfirmDialog(None, "Снимок не сохранён", "текст", "Завершить без сохранения", "Сохранить", default_yes=False)
cd.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier))
check(cd.result() == ConfirmDialog.NO and cd.extra is None and cd.note_label is None, "вызов без новых полей: Enter даёт «Сохранить»")

# --- 3. 12 языков: окно помещается на экране 1280, подписи кнопок целиком ------------------------------------------
for lang in LANGS:
    i18n.set_language(lang)
    ed, ctx = mk()
    info = {}

    def measure(dlg, info=info):
        info["w"] = dlg.width()
        info["ok"] = all(b.width() >= QFontMetrics(b.font()).horizontalAdvance(b.text()) + 16
                         for b in dlg.findChildren(QPushButton) if b.isVisible())
        info["texts"] = [b.text() for b in dlg.findChildren(QPushButton) if b.isVisible()]
    ask(ed, ConfirmDialog.CANCEL, measure)
    check(info.get("w", 9999) <= 1280 - 40 and info.get("ok"), f"{lang}: окно {info.get('w')} px, кнопки целиком {info.get('texts')}")
    for s in (i18n.tr("editor.unsaved_text"), i18n.tr("editor.unsaved_hint"), i18n.tr("editor.unsaved_discard")):
        check("—" not in s and s.strip() == s, f"{lang}: без длинных тире: {s!r}")
    finish(ed)

i18n.set_language("ru")
print(f"ИТОГ [x{SCALE}]: проверок {checks[0]}, провалено: {len(failures)}")
rc = 1 if failures else 0
if SCALE == "1":   # тот же тест при масштабе 150 %
    env = dict(os.environ, QT_SCALE_FACTOR="1.5")
    env["QT_QPA_PLATFORM"] = "offscreen"
    rc = max(rc, subprocess.call([sys.executable, os.path.abspath(__file__)], env=env))
sys.exit(rc)
