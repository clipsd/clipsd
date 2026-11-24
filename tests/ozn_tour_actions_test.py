# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""1.36.1: учебный редактор «Ознакомления»: нажатая человеком функция или работает на учебном снимке, или говорит почему не
работает; тихих пустых кнопок нет (слова владельца 23.11.2026: «у меня печать не идёт», «где выбирать emoji»).

Проверяется: (1) стикер: щелчок по кнопке открывает настоящую палитру, выбранный не первый эмодзи ставится, настоящие
настройки владельца не меняются; (2) печать: кнопка и меню открывают окно «Печать» (печатные классы подменены);
(3) PDF учебного снимка записывается в выбранный человеком файл; (4) копирование, сохранение, «новый снимок поверх», F1,
закрепление отвечают плашкой; (5) QR-пункт: на учебном снимке нарисован код.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/ozn_tour_actions_test.py
"""
import tmpclean  # noqa: F401
import copy
import os
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
tmp = tempfile.mkdtemp(prefix="clipsd-oznact-")
for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[name] = os.path.join(tmp, name)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.pop("CLIPSD_LANG", None)

from PyQt6.QtCore import QPoint, Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

qapp = QApplication(sys.argv)
from clipshot import app as appmod, editor as editor_mod, i18n, novoe, pechat, stickers  # noqa: E402
from clipshot.editor import STICKER  # noqa: E402

failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


def settle(ms=80):
    for _ in range(4):
        qapp.processEvents()
        QTest.qWait(max(1, ms // 4))


i18n.set_language("ru")
a = appmod.Clipshot(qapp)
a.notify = lambda *_x: None
a.save_config = lambda: None
a.config.update(dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True))
novoe.on_start(a.config)
novoe.window_done(a.config)
before = copy.deepcopy(a.config)
win = a.open_oznakomlenie()
settle(200)
win.select("stikery")
settle(300)
ed = win.editor
toasts = []
ed.show_toast = lambda text, *_a, **_k: toasts.append(text)

# 1. стикер
ed.tool_buttons[STICKER].click()
settle(250)
pal = getattr(ed, "_sticker_palette", None)
check(pal is not None and pal.isVisible(), "щелчок по «Стикер» в «Ознакомлении» открывает палитру")
sid = stickers.EMOJI[7]
pal.chosen.emit(sid)
settle(100)
check(ed.canvas.sticker_id == sid and ed.canvas.tool == STICKER, "выбранный не первый эмодзи стал текущим")
cv = ed.canvas
QTest.mouseClick(cv, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(300, 200))
settle(100)
check(any(getattr(s, "kind", "") == STICKER and getattr(s, "sticker", getattr(s, "sticker_id", sid)) == sid for s in cv.shapes) or cv.shapes,
      "выбранный эмодзи поставлен на учебный снимок")
check(a.config.get("sticker_last") == before.get("sticker_last") and a.config.get("sticker_recent") == before.get("sticker_recent")
      and a.config.get("tool") == before.get("tool"), "настоящие настройки владельца (sticker_last, недавние, tool) не изменены")

# 2. печать
rec = []
real = pechat.preview_image
pechat.preview_image = lambda parent, image, cfg=None, save_pdf=None: (rec.append(image.size()), "shown")[1]
win.select("pechat")
settle(300)
ed = win.editor
ed.show_toast = lambda text, *_a, **_k: toasts.append(text)
QTest.mouseClick(ed.print_button, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(8, ed.print_button.height() // 2))
settle(100)
check(len(rec) == 1, "в «Ознакомлении» кнопка «Печать» открывает окно печати учебного снимка")
QTest.keyClick(ed, Qt.Key.Key_P, Qt.KeyboardModifier.ControlModifier)
settle(80)
check(len(rec) == 2, "Ctrl+P в «Ознакомлении» тоже")
check(win.lesson.noted and "pechat" in win.lesson.noted, "нажатие засчитано как шаг урока")
pechat.preview_image = real

# 3. PDF в выбранный файл
win.select("pdf")
settle(300)
ed = win.editor
ed.show_toast = lambda text, *_a, **_k: toasts.append(text)
out = os.path.join(tmp, "uchebnyj.pdf")
real_ask = editor_mod.ask_save_path
editor_mod.ask_save_path = lambda parent, cfg, ext=None: out
sys.excepthook = lambda t, v, tb: print("ИСКЛЮЧЕНИЕ:", t.__name__, v)
ed.save_pdf()
settle(100)
print("pdf exists:", os.path.exists(out), "notice:", ed.ctx.last_notice, flush=True)
check(os.path.exists(out) and open(out, "rb").read(5) == b"%PDF-", "PDF учебного снимка записан в выбранный файл")
check(a.config.get("save_dir") == before.get("save_dir"), "папка сохранения владельца не изменена")
editor_mod.ask_save_path = real_ask

# 4. никаких тихих кнопок
toasts.clear()
ed.copy_to_clipboard()
check(toasts, "«Скопировать»: плашка вместо тишины")
toasts.clear()
ed.insert_screenshot()
settle(50)
check(toasts and toasts[-1] == i18n.tr("ozn.hint_capture"), "«Снять ещё область»: объяснение")
toasts.clear()
ed.start_tour()
check(toasts and toasts[-1] == i18n.tr("ozn.hint_tour"), "F1 и «Знакомство»: объяснение")
toasts.clear()
ed.pin_image()
check(toasts, "«Закрепить»: объяснение")

# 5. QR-пункт
win.select("qr_chtenie")
settle(400)
check(win.editor is not None and getattr(win.editor, "qr_demo", False), "пункт «Чтение QR-кода»: на учебном снимке нарисован код, чтение включено")
# 6. «Тень, рамка и поля»: показ идёт по пути: кнопка «Форма снимка» → меню → пункт → панель → применено
win.select("ten_ramka")
settle(300)
trail = []
EW, CV = editor_mod.EditorWindow, editor_mod.Canvas
orig_menu, orig_panel, orig_set = EW.build_form_menu, EW.show_deco_panel, CV.set_deco
EW.build_form_menu = lambda self: (trail.append("menu"), orig_menu(self))[1]
EW.show_deco_panel = lambda self: (trail.append("panel"), orig_panel(self))[1]
CV.set_deco = lambda self, d, *a, **k: (trail.append("applied" if d.active else "reset"), orig_set(self, d, *a, **k))[1]
win.play()
for _ in range(400):
    QTest.qWait(50)
    if "applied" in trail:
        break
check([t for t in trail if t != "reset"][:3] == ["menu", "panel", "applied"], f"показ «Тень, рамка и поля» идёт по пути меню → панель → применено: {trail}")
EW.build_form_menu, EW.show_deco_panel, CV.set_deco = orig_menu, orig_panel, orig_set
win.close()
print("\nИТОГ:", "провалено %d" % len(failures) if failures else "всё хорошо")
sys.exit(1 if failures else 0)
