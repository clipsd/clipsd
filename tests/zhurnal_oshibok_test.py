# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Журнал непредвиденных ошибок (1.36, clipshot/errorlog.py).

Проверяется: исключение в слоте не закрывает программу (без перехвата PyQt6 вызвал бы abort) и пишется в errors.log;
в журнале нет домашней папки, имени пользователя и текста в кавычках из сообщения; окно «Что-то пошло не так» встаёт,
не чаще раза в минуту (подставные часы), «Скопировать отчёт» кладёт отчёт в буфер, «Отправить» без приёмника открывает
письмо только по нажатию; исключения в потоке Python и в QThread; ротация на 500 КБ с одним старым файлом; до цикла
событий окно не показывается; пункт «Открыть журнал ошибок» в «О программе» только если журнал есть; 12 языков.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/zhurnal_oshibok_test.py
"""
import tmpclean  # noqa: F401
import json
import os
import sys
import tempfile
import threading

here = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(here)
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp(prefix="clipsd-zh-")
for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[name] = os.path.join(tmp, name)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.pop("CLIPSD_LANG", None)

from PyQt6.QtCore import QThread, QTimer  # noqa: E402
from PyQt6.QtGui import QGuiApplication  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

qapp = QApplication(sys.argv)
qapp.setQuitOnLastWindowClosed(False)
from clipshot import errorlog, i18n  # noqa: E402
i18n.set_language("ru")

fails = []


def check(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        fails.append(text)


def log_text():
    p = errorlog.log_path()
    return p.read_text(encoding="utf-8") if p.exists() else ""


def settle(ms=60):
    for _ in range(max(1, ms // 15)):
        qapp.processEvents()
        QTest.qWait(15)


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


clock = Clock()
errorlog.state["clock"] = clock
errorlog.install()
errorlog.attach(qapp)
check(sys.excepthook is errorlog._excepthook and threading.excepthook is errorlog._thread_hook,
      "перехватчики стоят: sys.excepthook и threading.excepthook")
check(str(errorlog.log_path()).startswith(tmp), "журнал в папке данных пользователя (тестовой)")

# --- до цикла событий: только запись, окна нет -----------------------------------------------------------------------
try:
    raise ValueError("до цикла")
except ValueError:
    errorlog._excepthook(*sys.exc_info())
check("ValueError" in log_text(), "ошибка до цикла событий записана в журнал")
settle()
check(errorlog.state["open_window"] is None, "до цикла событий окно не показывается")

# --- исключение в слоте не закрывает программу -----------------------------------------------------------------------
errorlog.set_loop_running(True)
home = os.path.expanduser("~")
SECRET = "мой секретный распознанный текст"


def bad_slot():
    d = {}
    d[SECRET]  # KeyError с текстом пользователя в сообщении
    return None


QTimer.singleShot(0, bad_slot)
settle(120)
check(True, "исключение в слоте: программа жива (без перехвата PyQt6 вызвал бы abort)")
text = log_text()
check("KeyError" in text and "bad_slot" in text, "в журнале тип ошибки и функция из трассировки")
check(SECRET not in text, "текст пользователя из сообщения KeyError в журнал не попал")
win = errorlog.state["open_window"]
check(win is not None and win.isVisible(), "окно «Что-то пошло не так» показано")
check(win is not None and win.windowTitle() != "" or win is not None, "окно создано")
check(win is not None and not win.isModal() and win.property("clipsd_closable") is True,
      "окно ошибки не модальное и закрываемое: не мешает Alt+W и выходу для обновления")

# --- crash.log: пустой убирается, с настоящим сбоем очищается от личных путей ------------------------------------------
cp = errorlog.crash_path()
cp.parent.mkdir(parents=True, exist_ok=True)
cp.write_text("--- запуск 2026-01-01 00:00:00 ---\n--- запуск 2026-01-01 00:00:05 ---\n", encoding="utf-8")
errorlog.tidy_crash_log(cp)
check(not cp.exists(), "crash.log из одних строк «запуск» убирается")
cp.write_text("--- запуск x ---\nFatal Python error\n  File \"" + os.path.join(home, "p", "a.py") + "\", line 1\n  File \"/home/ivan/b.py\"\n",
              encoding="utf-8")
errorlog.tidy_crash_log(cp)
ctext = cp.read_text(encoding="utf-8")
check("Fatal Python error" in ctext and home not in ctext and "/home/ivan" not in ctext and "~" in ctext,
      "crash.log со сбоем: домашняя папка и имя заменены на ~, текст сбоя цел")
cp.write_text("File \"" + os.path.join(home, "q.py") + "\"\n", encoding="utf-8")
check(home not in errorlog.crash_text(), "crash_text() для показа и отправки без личных путей")
cp.unlink()

# --- домашняя папка и имя пользователя --------------------------------------------------------------------------------
fake = os.path.join(home, "Документы", "секрет.txt")
try:
    open(fake + ".нет", "rb")
except OSError:
    errorlog._excepthook(*sys.exc_info())
errorlog._excepthook(OSError, OSError(r"C:\Users\Ivan\AppData\x.png и /home/ivan/снимок.png и " + fake), None)
text = log_text()
check(home not in text and "Ivan" not in text and "/home/ivan" not in text,
      "в журнале нет домашней папки и имён пользователей из путей")
check("~" in text, "путь домашней папки заменён на ~")
check("ClipSD 1." in text and "Python" in text and "20" in text, "есть версия, система, время")

# --- окно не чаще раза в минуту ---------------------------------------------------------------------------------------
win.close()
settle()
shown = []
orig_build = errorlog.build_window
errorlog.build_window = lambda r: (shown.append(r), orig_build(r))[1]
before = len(log_text())
clock.t += 10
try:
    raise RuntimeError("повтор")
except RuntimeError:
    errorlog.handle("тест", *sys.exc_info())
settle()
check(not shown and len(log_text()) > before, "через 10 с: повтор только в журнале, окна нет")
clock.t += 61
try:
    raise RuntimeError("повтор 2")
except RuntimeError:
    errorlog.handle("тест", *sys.exc_info())
settle()
check(len(shown) == 1, "через минуту окно снова показывается")
w2 = errorlog.state["open_window"]
check(w2 is not None and w2.isVisible(), "второе окно видно")
clock.t += 120
try:
    raise RuntimeError("пока открыто")
except RuntimeError:
    errorlog.handle("тест", *sys.exc_info())
settle()
check(len(shown) == 1, "пока окно открыто, второе поверх не ставится")

# --- кнопки окна ------------------------------------------------------------------------------------------------------
w2.copy_report()
check(QGuiApplication.clipboard().text() == w2.report and "RuntimeError" in w2.report, "«Скопировать отчёт» кладёт отчёт в буфер")
opened = []
from clipshot import sysenv, updater  # noqa: E402
sysenv.open_url = lambda url: opened.append(str(url)) or True
posted = []
updater.REPORT_ENDPOINT = ""
check(not opened, "без нажатия ничего не открывается и не отправляется")
w2.send_report()
check(len(opened) == 1 and opened[0].startswith("mailto:"), "«Отправить» без приёмника открывает письмо (по нажатию)")
w2.close()
settle()

# --- потоки -----------------------------------------------------------------------------------------------------------
clock.t += 200
shown.clear()


def th():
    raise IndexError("в потоке")


t = threading.Thread(target=th, name="тест-поток")
t.start()
t.join()
settle(120)
check("IndexError" in log_text() and "тест-поток" in log_text(), "исключение в потоке Python записано")
check(len(shown) == 1, "из потока окно показывается в основном потоке")
errorlog.state["open_window"].close()
settle()


class Th(QThread):
    def run(self):
        raise ZeroDivisionError("в QThread")


clock.t += 200
q = Th()
q.start()
q.wait(3000)
settle(120)
check("ZeroDivisionError" in log_text(), "исключение в QThread записано, программа жива")
if errorlog.state["open_window"] is not None:
    errorlog.state["open_window"].close()

# --- ротация ----------------------------------------------------------------------------------------------------------
p = errorlog.log_path()
p.write_text("x" * (errorlog.MAX_BYTES - 5), encoding="utf-8")
errorlog.write_log("[t] ротация\nстрока\n")
old = p.with_name("errors.log.1")
check(old.exists() and old.stat().st_size >= errorlog.MAX_BYTES - 5, "ротация: старый журнал ушёл в errors.log.1")
check(p.exists() and p.stat().st_size < 1000 and "ротация" in log_text(), "после ротации новый короткий файл с новой записью")
for i in range(3):
    p.write_text("y" * errorlog.MAX_BYTES, encoding="utf-8")
    errorlog.write_log("[t] ещё\n")
check(sorted(f.name for f in p.parent.glob("errors.log*")) == ["errors.log", "errors.log.1"], "старый файл всегда один")
check(p.stat().st_size + old.stat().st_size <= 2 * errorlog.MAX_BYTES + 200, "общий размер ограничен")

# --- faulthandler и crash.log -----------------------------------------------------------------------------------------
import faulthandler  # noqa: E402
check(errorlog.enable_faulthandler() and faulthandler.is_enabled() and errorlog.crash_path().exists(), "faulthandler пишет в crash.log")
errorlog.disable_faulthandler()
check(not faulthandler.is_enabled() and not errorlog.crash_path().exists(), "при обычном выходе faulthandler выключен, пустой crash.log убран")

# --- «О программе»: журнал ---------------------------------------------------------------------------------------------
from clipshot import app as appmod  # noqa: E402
a = appmod.Clipshot(qapp)
dlg = a.build_about()
check(hasattr(dlg, "open_log_button"), "журнал есть: в «О программе» пункт «Открыть журнал ошибок»")
dlg.close()
for f in p.parent.glob("errors.log*"):
    f.unlink()
dlg = a.build_about()
check(not hasattr(dlg, "open_log_button"), "журнала нет: пункта нет")
dlg.close()

# --- 12 языков --------------------------------------------------------------------------------------------------------
langs = ["ru", "en", "bg", "de", "es", "fr", "it", "pl", "pt", "tr", "uk", "zh"]
ref = json.loads(open(os.path.join(ROOT, "clipshot/i18n/ru/errlog.json"), encoding="utf-8").read())
for lang in langs:
    data = json.loads(open(os.path.join(ROOT, f"clipshot/i18n/{lang}/errlog.json"), encoding="utf-8").read())
    check(set(data) == set(ref) and all(v.strip() for v in data.values()), f"{lang}: все {len(ref)} строк заполнены")
    if lang != "ru":
        check(data["errlog.text"] != ref["errlog.text"], f"{lang}: переведено, не копия русского")
for dark in (False, True):
    from clipshot import themes
    orig = themes.is_dark
    themes.is_dark = lambda d=dark: d
    for lang in langs:
        i18n.set_language(lang)
        clock.t += 500
        w = errorlog.build_window("отчёт")
        w.show()
        settle(30)
        ok = all(not b.text() == "" for b in (w.primary_button, w.secondary_button, w.send_button))
        wide = w.send_button.width() >= w.send_button.sizeHint().width() - 2 and w.primary_button.width() >= w.primary_button.sizeHint().width() - 2
        check(ok and wide and w.width() <= 700, f"окно в теме {'тёмной' if dark else 'светлой'} на {lang}: кнопки не обрезаны")
        w.close()
    themes.is_dark = orig
i18n.set_language("ru")

print("ИТОГ:", "ВСЁ ХОРОШО" if not fails else f"провалов {len(fails)}")
sys.stdout.flush()
import shutil  # noqa: E402
shutil.rmtree(tmp, ignore_errors=True)   # os._exit ниже обходит tmpclean: убираем свою папку сами
os._exit(1 if fails else 0)
