# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Современный вид редактора 1.32 (направление А) и колокольчик уведомлений.

Вид: рамка «Тонкая линия» по умолчанию (и перенос старого «Свечения»), палитра светлая и тёмная (прежние цвета
оформлений заменяются, свои сохраняются), выбранный инструмент мягкой подложкой с полоской, «Копировать текст» и
«Перевести» мягкие, «Сохранить»/«Скопировать» лёгкие, зелёная «Скопировать и закрыть», колокольчик, «?», шестерёнка
и глобус в своей шапке (при системном заголовке справа в первом ряду).
Колокольчик: точка при непрочитанном, «Доступна версия», «Что нового» (CHANGELOG и запись обновления), сообщение о
лимите перевода (один раз в день), «Прочитать все», прочитанное в config, новая установка без точки.
Знакомство: шаги «Все инструменты» и «Уведомления» с подсветкой.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/look132_test.py
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
os.environ.pop("CLIPSD_LANG", None)
_cfg = os.path.join(tempfile.mkdtemp(prefix="clipsd-look132-"), "screen.json")
with open(_cfg, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1600, "height": 1000,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _cfg

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
from clipshot import __version__, app as appmod, i18n, notifications, themes, translate
from clipshot import editor as em
from clipshot.editor import ARROW, RECT, EditorWindow, chrome_params, frame_style, palette

failures = []
checks = [0]


def check(cond, msg):
    checks[0] += 1
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def settle(n=5):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(10)


class Ctx:
    def __init__(self, **kw):
        self.config = dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True, **kw)
        self.icon = appmod.make_icon()
        self.saved = 0

    def save_config(self):
        self.saved += 1

    def notify(self, text):
        pass


def mk(w=300, **kw):
    ctx = Ctx(**kw)
    themes.apply_app(app, ctx.config)
    img = QImage(w, 220, QImage.Format.Format_RGB32)
    img.fill(QColor("#ffffff"))
    ed = EditorWindow(img, ctx, QPoint(0, 0))
    ed.present()
    settle()
    return ed, ctx


def done(ed):
    ed.canvas.modified, ed.exported = False, True
    ed.close()
    settle(2)


def near(c, hexcolor, tol=40):
    q = QColor(hexcolor)
    return abs(c.red() - q.red()) + abs(c.green() - q.green()) + abs(c.blue() - q.blue()) <= tol


i18n.set_language("ru")
# --- 1. палитра и рамка -------------------------------------------------------------------------------------
check(appmod.DEFAULTS["editor_frame_style"] == "thin" and frame_style({}) == "thin", "по умолчанию рамка «Тонкая линия»")
check(frame_style({"editor_frame_style": "glow"}) == "thin", "«Свечение» из настроек 1.31 читается как «Тонкая линия»")
check(frame_style({"editor_frame_style": "glow", "frame_style_132": True}) == "glow", "«Свечение», выбранное в 1.32, остаётся")
light = palette({"ui_theme": "standard"})
dark = palette({"ui_theme": "pro"})
check(light["panel"] == "#f5f6f8" and light["stage"] == "#34383e" and light["s2"] == "#eceff3" and not light["dark"],
      "светлая палитра: панели #f5f6f8, поле #34383e")
check(dark["panel"] == "#202327" and dark["stage"] == "#111315" and dark["dark"], "тёмная палитра: панели #202327, поле #111315, без чёрного")
check(palette({"ui_theme": "standard", "ui_panel": "#d9dbdf", "ui_field": "#3a3d42"})["panel"] == "#f5f6f8",
      "прежние цвета оформления (сохранены в 1.31) заменяются новой палитрой")
own = palette({"ui_theme": "standard", "ui_panel": "#e8d9c0", "ui_field": "#40302a"})
check(own["panel"] == QColor("#e8d9c0").lighter(106).name() and own["stage"] != "#34383e", "свои цвета панелей и поля сохраняются (подложка чуть светлее, как до 1.32)")
cp = chrome_params({"ui_theme": "standard"})
check(cp["style"] == "thin" and cp["line"] == 1 and cp["halo"] == 0 and cp["color"].alpha() < 255, "тонкая линия цвета акцента, без свечения")

ed, ctx = mk()
check(ed.shell.radius() == 8 and ed.shell.inner() == 1, "окно: скругление 8, линия 1 px")
img = ed.grab().toImage()
r = img.devicePixelRatio()
card = ed.shell.card()
row1_y = int(ed.panel.mapTo(ed, QPoint(0, 0)).y() + 8)
c_panel = img.pixelColor(int((card.left() + 6) * r), int(row1_y * r))
check(near(c_panel, "#f5f6f8", 12), f"панель светлая #f5f6f8 ({c_panel.name()})")
c_stage = img.pixelColor(int((card.left() + 12) * r), int((ed.scroll.mapTo(ed, QPoint(0, 0)).y() + 20) * r))
check(near(c_stage, "#34383e", 12), f"поле вокруг снимка #34383e ({c_stage.name()})")
# выбранный инструмент: мягкая подложка без рамки, полоска акцента снизу
b = ed.tool_strip.visible_widget(ed.canvas.tool)
shot = b.grab().toImage()
rr = shot.devicePixelRatio()
bar = shot.pixelColor(int(b.width() / 2 * rr), int((b.height() - 3.5) * rr))
edge = shot.pixelColor(int(1 * rr), int(b.height() / 2 * rr))
check(near(bar, "#1e78ff", 60), f"полоска акцента под выбранным инструментом ({bar.name()})")
check(edge.alpha() < 110 or not near(edge, "#1e78ff", 90), f"у выбранного нет синей рамки, только мягкая подложка ({edge.name()}, α {edge.alpha()})")
# кнопки внизу
check(ed.save_button.objectName() == "light" and ed.copy_button.objectName() == "light" and ed.copy_close_button.objectName() == "finish",
      "«Сохранить», «Скопировать» лёгкие, «Скопировать и закрыть» главная")
fin = ed.copy_close_button.grab().toImage()
cf = fin.pixelColor(int(8 * fin.devicePixelRatio()), int(fin.height() / 2))
check(near(cf, themes.GREEN, 30), f"«Скопировать и закрыть» зелёная #157a40 ({cf.name()})")
check(themes.GREEN == "#157a40" and themes.GREEN_HOVER == "#126b38" and themes.GREEN_BORDER == "#0f5c30",
      "зелёный главной кнопки #157a40 (решение владельца 19.11.2026)")


def contrast(hexcolor):
    def lin(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    q = QColor(hexcolor)
    lum = 0.2126 * lin(q.red()) + 0.7152 * lin(q.green()) + 0.0722 * lin(q.blue())
    return 1.05 / (lum + 0.05)


check(all(contrast(c) >= 4.5 for c in (themes.GREEN, themes.GREEN_HOVER, themes.GREEN_PRESSED) + themes.GREEN_GRADIENT
          + themes.GREEN_GRADIENT_HOVER), "белый текст на зелёном читается: контраст не ниже 4,5:1 во всех состояниях")
check(ed.zoom_group.objectName() == "zoomGroup" and ed.zoom_label.parentWidget() is ed.zoom_group, "масштаб одной группой")
check(ed.quick_group.isVisible() and ed.quick_group.objectName() == "quickGroup", "«Отменить/Повторить» на своей подложке")
check(ed.tool_strip.order() == [t for t, _g, _tip, _k in em.TOOLS], "порядок инструментов 1.31.1")
gl = ed.language_button.icon().pixmap(24, 24).toImage()
blue = [gl.pixelColor(x, y) for x in range(gl.width()) for y in range(gl.height()) if gl.pixelColor(x, y).alpha() > 200]
check(blue and all(near(c, "#3a9be8", 60) for c in blue[:30]), "глобус голубой #3a9be8")
# значки справа в своей шапке
icons_order = [w for w in ed.top_icons.findChildren(type(ed.help_button)) if w.parentWidget() is ed.top_icons]
check(ed.titlebar is not None and ed.titlebar.isAncestorOf(ed.top_icons), "колокольчик, «?», шестерёнка, глобус в своей шапке окна")
xs = [w.mapTo(ed, QPoint(0, 0)).x() for w in (ed.bell_button, ed.help_button, ed.settings_button, ed.language_button)]
check(xs == sorted(xs) and ed.bell_button.isVisible(), "порядок: колокольчик, «?», шестерёнка, глобус")
check(ed.titlebar.min_button.mapTo(ed, QPoint(0, 0)).x() > xs[-1], "справа от них кнопки окна")
done(ed)
ed, ctx = mk(editor_system_title=True)
check(ed.titlebar is None and ed.panel.isAncestorOf(ed.top_icons) and ed.top_icons.isVisible(),
      "системный заголовок: значки справа в первом ряду, нативная шапка не тронута")
done(ed)
# тёмная тема
ed, ctx = mk(ui_theme="pro")
img = ed.grab().toImage()
r = img.devicePixelRatio()
card = ed.shell.card()
c_panel = img.pixelColor(int((card.left() + 6) * r), int((ed.panel.mapTo(ed, QPoint(0, 0)).y() + 8) * r))
check(near(c_panel, "#202327", 14), f"тёмная: панель #202327 ({c_panel.name()})")
done(ed)

# --- 2. колокольчик --------------------------------------------------------------------------------------------
newer = ".".join(str(int(x) + (1 if i == 0 else 0)) for i, x in enumerate(__version__.split(".")[:3]))
cfg = dict(appmod.DEFAULTS, tour_done=True, update_last_seen_version=newer)
check(notifications.available_update(cfg) == newer, f"канал видел {newer}: доступно обновление")
check(notifications.available_update(dict(cfg, update_skipped=[newer])) == "", "пропущенная версия не показывается")
check(notifications.available_update(dict(cfg, update_last_seen_version=__version__)) == "", "та же версия: ничего")
items = notifications.items(cfg)
check(items and items[0]["kind"] == "update" and newer in items[0]["title"], f"первый пункт: «Доступна версия {newer}»")
if notifications.changelog_versions():
    wn = [it for it in items if it["kind"] == "whatsnew"]
    check(wn and notifications.whats_new_notes(cfg, wn[0]["version"]), f"«Что нового» из CHANGELOG: {[w['version'] for w in wn]}")
notifications.remember_whats_new(cfg, "0.9.1", {"ru": "- Старое исправление", "en": "- Old fix"})
check(notifications.whats_new_notes(cfg, "0.9.1", "ru") == "- Старое исправление" and notifications.whats_new_notes(cfg, "0.9.1", "de") == "- Old fix",
      "заметки из записи обновления (язык, запасной английский)")
now = datetime(2026, 11, 19, 14, 20, tzinfo=timezone.utc)
check(notifications.post("translate_quota", cfg, now=now) and not notifications.post("translate_quota", cfg, now=now),
      "сообщение о лимите перевода добавляется один раз за день")
msg = [it for it in notifications.items(cfg) if it["kind"] == "message"]
check(msg and msg[0]["title"] == "Перевод: дневной лимит исчерпан", f"сообщение в списке: {msg[:1]}")
notifications.mark_read(cfg, [it["id"] for it in notifications.items(cfg)])
check(not notifications.unread(cfg) and cfg["notices_read"], "«Прочитать все»: прочитанное в config notices_read")
fresh = dict(appmod.DEFAULTS, tour_done=False)
notifications.first_run_seen(fresh)
check(f"whatsnew:{__version__}" in fresh["notices_read"], "новая установка: «Что нового» своей версии без точки")

# в редакторе
ed, ctx = mk(update_last_seen_version=newer)
bell = ed.bell_button
check(bell.unread >= 1, f"точка на колокольчике: непрочитанных {bell.unread}")
shot = bell.grab().toImage()
rr = shot.devicePixelRatio()
dot = shot.pixelColor(int((bell.width() - 10.5) * rr), int(9.5 * rr))
check(near(dot, "#e5484d", 40), f"красная точка ({dot.name()})")
menu = ed.build_notifications_menu()
rows = ed.notice_rows
check(f"update:{newer}" in rows and rows[f"update:{newer}"].action_button is not None
      and rows[f"update:{newer}"].action_button.text() == "Обновить", "пункт «Доступна версия» с кнопкой «Обновить»")
ab = rows[f"update:{newer}"].action_button
_bold = ab.font()
_bold.setBold(True)
from PyQt6.QtGui import QFontMetrics as _QFM  # noqa: E402
check(ab.width() >= _QFM(_bold).horizontalAdvance("Обновить") + 16, f"«Обновить» не обрезана ({ab.width()} px)")
past = [it for it in notifications.items(ctx.config) if it.get("history")]
check(all(it["id"] not in {u["id"] for u in notifications.unread(ctx.config)} for it in past)
      and all(not rows[it["id"]].unread for it in past), "«Что нового» прошлых версий: справка, без точки и подложки")
called = []
ed._check_updates = lambda: called.append(1)
rows[f"update:{newer}"].action_button.click()
check(called and f"update:{newer}" in ctx.config["notices_read"], "«Обновить»: проверка обновлений, пункт прочитан")
from clipshot import updater  # noqa: E402
opened = []
real_wn = updater.UpdaterUI.whats_new
updater.UpdaterUI.whats_new = lambda self, v, md: opened.append((v, md))
wn = [it for it in notifications.items(ctx.config) if it["kind"] == "whatsnew"]
if wn:
    ed.open_notice(wn[0])
    check(opened and opened[0][0] == wn[0]["version"] and opened[0][1], "«Что нового»: окно с заметками версии")
updater.UpdaterUI.whats_new = real_wn
notifications.post("translate_quota")   # зарегистрированное приложение: редактор ctx
settle(1)
check(any(m.get("kind") == "translate_quota" for m in ctx.config.get("notices_messages", [])) and bell.unread >= 1,
      "сообщение программы попадает в колокольчик открытого редактора")
ed.build_notifications_menu()
notifications.mark_read(ctx.config, [it["id"] for it in notifications.items(ctx.config)], ctx.save_config)
settle(1)
check(bell.unread == 0, "всё прочитано: точки нет")
done(ed)

# лимит перевода из задания перевода
job = translate.TranslateJob(QImage(10, 10, QImage.Format.Format_RGB32), dict(appmod.DEFAULTS))
real_rec, real_tr = translate.ocr.recognize_words, translate.translate_text
translate.ocr.recognize_words = lambda *a, **k: [translate.ocr.Word("Hallo", __import__("PyQt6.QtCore", fromlist=["QRectF"]).QRectF(0, 0, 30, 10), 0)]


def quota(*a, **k):
    raise translate.QuotaError(help=translate.EmailNeeded(), key="translate.err_mm_quota")


translate.translate_text = quota
got = []
job.done.connect(lambda res, err: got.append(err))
job.run()
translate.ocr.recognize_words, translate.translate_text = real_rec, real_tr
check(job.quota == "translate_quota", f"перевод: кончился лимит MyMemory: код для колокольчика ({job.quota!r})")

# М2 независимой проверки: перевод из окна выделения до первого редактора, сообщение всё равно в колокольчике
import tempfile as _tempfile  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
_real_config_path = appmod.CONFIG_PATH
appmod.CONFIG_PATH = _Path(_tempfile.mkdtemp(prefix="clipsd-look132-cfg-")) / "config.json"
notifications.register(None)   # как сразу после запуска: редакторов ещё не было
fresh_app = appmod.Clipshot(app)
check(notifications.post("translate_quota") and any(m.get("kind") == "translate_quota"
                                                     for m in fresh_app.config.get("notices_messages") or []),
      "приложение регистрирует колокольчик при запуске: лимит перевода записан до первого редактора")
appmod.CONFIG_PATH = _real_config_path

# --- 3. знакомство -----------------------------------------------------------------------------------------------
ed, ctx = mk(900)
ed.start_tour()
settle()
tour = ed.tour
targets = [s[0] for s in tour.steps]
check(ed.more_button in targets and ed.bell_button in targets, "в знакомстве шаги «Все инструменты» и «Уведомления»")
for target in (ed.tool_strip, ed.more_button, ed.bell_button):
    i = targets.index(target)
    tour.show_step(i)
    settle(1)
    hole = tour.hole
    tl = tour.parentWidget().mapFromGlobal(target.mapToGlobal(QPoint(0, 0)))
    check(hole.isValid() and hole.contains(tl + QPoint(target.width() // 2, target.height() // 2)),
          f"шаг {i + 1} «{tour.title.text()}»: подсветка на своей кнопке")
check(tour.card.geometry().intersects(tour._card_rect()), "карточка шага в окне")
tour.finish()
done(ed)

# --- 4. 12 языков: подписи не обрезаны, узкое окно в пределах ------------------------------------------------------
from PyQt6.QtWidgets import QAbstractButton  # noqa: E402
for lang in i18n.LANGUAGES:
    i18n.set_language(lang)
    for w in (300, 1500):
        ed, ctx = mk(w)
        for host in (ed.panel, ed.bottom, ed.top_icons):
            for btn in host.findChildren(QAbstractButton):
                if btn.isVisible() and btn.text().strip() and not isinstance(btn, em.ToolRow):
                    f = btn.font()
                    if btn.objectName() in ("ocrButton", "trAllButton", "trButton", "finish"):
                        f.setBold(True)
                    from PyQt6.QtGui import QFontMetrics  # noqa: E402
                    need = QFontMetrics(f).horizontalAdvance(btn.text().replace("&", "").strip())
                    check(btn.width() >= need, f"{lang} {w}: «{btn.text().strip()}» помещается ({btn.width()} >= {need})")
        done(ed)
i18n.set_language("ru")
print(f"ИТОГ: проверок {checks[0]}, провалено: {len(failures)}")
sys.exit(1 if failures else 0)
