# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Каракули в окне «Текст с картинки» (Windows без русского распознавания, 22.11.2026).

Подсказка «Установить распознавание» раньше показывалась один раз отдельным окном при распознавании; при каждом
выделении текста маркером окно с каракулями («PeKOMeHAOBaHO» вместо «Рекомендовано») было без подсказки. Теперь редактор
помнит подсказку последнего распознавания снимка и передаёт её в окно выделенного текста (и в уже открытое окно).
Windows взял английский вместо русского (OCR_WANT=ru OCR_LANG=en-US): в окне блок установки с текстом ocr.win_lang_need;
взял русский (OCR_LANG=ru): блока нет.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/ocr_podskazka_okno_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import os
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CLIPSD_LANG", "ru")
tmp = tempfile.mkdtemp(prefix="clipsd-ocrp-")
for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[name] = os.path.join(tmp, name)

from PyQt6.QtGui import QColor, QImage  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel  # noqa: E402

qapp = QApplication(sys.argv)
qapp.setQuitOnLastWindowClosed(False)
from clipshot import app as appmod, ocr  # noqa: E402
from clipshot.i18n import tr  # noqa: E402

failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


def wait(n=10):
    for _ in range(n):
        qapp.processEvents()


ctx = appmod.Clipshot(qapp)
ctx.save_config = lambda: None
ctx.config.update(theme_chosen=True, tour_done=True, auto_save=False, ocr_enabled=True)
shown = []
ocr.show_result = lambda text, error, parent=None, help=None, again=False: shown.append((text, error, help)) or None
ocr.toast = lambda *_a, **_k: None
ocr.copy_text = lambda *_a, **_k: None


class Job:
    words = []


def fake_start_factory(info):
    def fake_start(image, on_done, langs=None, quality=None):
        job = Job()
        help_ = ocr.windows_fallback_help(info)
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, lambda: on_done("", "", help_))
        return job
    return fake_start


def run(info):
    img = QImage(400, 200, QImage.Format.Format_RGB32)
    img.fill(QColor("white"))
    ed = ctx.open_editor(img, None)
    wait()
    ocr.start = fake_start_factory(info)
    shown.clear()
    ocr._early[ocr.resolve_langs("auto")] = "ok"   # 1.36: проверка языка до распознавания здесь не нужна
    ed.start_text_mode()
    wait(30)
    return ed


def texts(panel):
    return " ".join(label.text() for label in panel.findChildren(QLabel))


# 1. Windows взял английский вместо русского: подсказка в окне выделенного текста
ed = run("OCR_WANT=ru OCR_LANG=en-US OCR_LINES=1")
check(ed._ocr_help is not None, "редактор запомнил подсказку распознавания")
ed._text_selected("PeKOMeHAOBaHO")
panel = ed._text_panel
check(panel is not None and panel.install is not None, "окно с каракулями: блок «Установить распознавание» есть")
check(tr("ocr.win_lang_need") in texts(panel), "в блоке текст ocr.win_lang_need")
# следующее выделение в уже открытом окне: блок остаётся, окно одно
ed._text_selected("Mnp")
check(ed._text_panel is panel and panel.install is not None, "следующее выделение: то же окно, блок на месте")
check(len(panel.findChildren(type(panel.install))) == 1, "блок один, не дублируется")
panel.close()
wait()
ed._text_selected("PeKOMeHAOBaHO")
check(ed._text_panel is not panel and ed._text_panel.install is not None, "окно открыто заново: блок есть")
ed._text_panel.close()
ed.close()
wait()

# 2. Windows распознал русским: блока нет
ed = run("OCR_WANT=ru OCR_LANG=ru OCR_LINES=1")
check(ed._ocr_help is None, "русский распознан: подсказки нет")
ed._text_selected("Рекомендовано")
check(ed._text_panel is not None and ed._text_panel.install is None, "окно с русским текстом: блока нет")
# подсказка исчезает из открытого окна, если снимок распознан заново без неё
ed._text_panel.set_help(ocr.install_help("windows_lang", "rus"))
check(ed._text_panel.install is not None, "set_help ставит блок в открытое окно")
ed._text_panel.set_help(None)
check(ed._text_panel.install is None, "set_help(None) убирает блок")
ed._text_panel.close()
ed.close()
wait()

print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено {len(failures)}")
from clipshot.exitutil import quick_exit  # noqa: E402
quick_exit(1 if failures else 0)
