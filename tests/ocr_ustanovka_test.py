# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Установка распознавания одной кнопкой (1.36) и предупреждение заранее.

Ничего настоящего не ставится и не запускается: pkexec, apt-get, dnf, pacman, zypper, Dism подменены заглушками
(QProcess-заглушка записывает, что её просили запустить; Dism через sysenv.run_elevated_wait).
1. Linux: argv для pkexec у debian, fedora, arch, opensuse: полные пути, без shell, только пакеты из таблицы;
   нет pkexec, Flatpak, неизвестное семейство, чужой код языка: argv нет или код пропущен.
2. Ход: отказ пароля, ошибка (с понятным текстом), успех, нет pkexec (остаётся команда), «Поставить вручную».
3. Windows: кнопка в окне текста, в окне выделенного текста, в карточке перевода; после «Готово» распознавание
   текущего снимка повторяется само, выделенное остаётся выделенным.
4. Заранее: нет языка, окно «нужно распознавание» до распознавания, распознавание после закрытия или установки;
   есть язык: сразу; предложение один раз за запуск.
5. Строка в настройках: «Распознавание: …» и «Установить ещё язык».
6. 12 языков: новые строки на месте, кнопки и подписи не обрезаны, светлая и тёмная тема.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/ocr_ustanovka_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import json
import os
import re
import sys
import tempfile
import time

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
os.environ.pop("CLIPSD_LANG", None)   # тест сам перебирает языки
tmp = tempfile.mkdtemp(prefix="clipsd-ocru-")
_cfg = os.path.join(tmp, "screen.json")
with open(_cfg, "w", encoding="utf-8") as _f:   # большой экран: высота окон не режется 60 % маленького экрана
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1600, "height": 1200,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _cfg
for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[name] = os.path.join(tmp, name)

from PyQt6.QtCore import QObject, QPoint, QProcess, QRect, Qt, pyqtSignal  # noqa: E402
from PyQt6.QtGui import QColor, QFontMetrics, QImage  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QAbstractButton, QApplication, QLabel  # noqa: E402

qapp = QApplication(sys.argv)
qapp.setQuitOnLastWindowClosed(False)
from clipshot import app as appmod, i18n, ocr, sysenv, themes  # noqa: E402
from clipshot.editor import EditorWindow, TRANSLATE  # noqa: E402
from clipshot.i18n import tr  # noqa: E402
from clipshot.translate_ui import TranslateCard  # noqa: E402

i18n.set_language("ru", notify=False)

failures = []
errors = []
_hook = sys.excepthook


def _catch(*exc):
    errors.append(exc)
    _hook(*exc)


sys.excepthook = _catch


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


def settle(n=6):
    for _ in range(n):
        qapp.processEvents()
        QTest.qWait(10)


def wait(cond, seconds=15):
    end = time.time() + seconds
    while not cond() and time.time() < end:
        qapp.processEvents()
        QTest.qWait(20)
    return cond()


class FakeProc(QObject):
    """Вместо QProcess: ничего не запускает; тест сам «завершает» процесс нужным кодом."""
    finished = pyqtSignal(int, QProcess.ExitStatus)
    errorOccurred = pyqtSignal(QProcess.ProcessError)
    readyReadStandardOutput = pyqtSignal()
    made = []

    def __init__(self):
        super().__init__()
        self.started = None
        self.output = b""
        FakeProc.made.append(self)

    def setProcessChannelMode(self, mode):
        pass

    def start(self, program, args):
        self.started = [program] + list(args)

    def closeWriteChannel(self):
        pass

    def readAllStandardOutput(self):
        out, self.output = self.output, b""
        return out

    def kill(self):
        pass

    def say(self, text):
        self.output += text.encode()
        self.readyReadStandardOutput.emit()

    def end(self, code):
        self.finished.emit(code, QProcess.ExitStatus.NormalExit)


ocr.PROCESS_FACTORY = FakeProc   # что бы ни нажали, настоящий pkexec не запустится


def which_all(name, path=None):
    return f"/usr/bin/{name}"


def which_no_pkexec(name, path=None):
    return None if name == "pkexec" else f"/usr/bin/{name}"


# пакеты, которые вообще разрешено ставить: значения таблицы
ALLOWED = {pkg for spec in ocr.LINUX_PACKAGES.values() for pkg in list(spec["base"]) + list(spec["langs"].values())}
MANAGERS = {spec["manager"] for spec in ocr.LINUX_PACKAGES.values()}

# --- 1. argv для pkexec -------------------------------------------------------------------------------------------
want = {
    "debian": ["/usr/bin/pkexec", "/usr/bin/apt-get", "install", "-y", "tesseract-ocr", "tesseract-ocr-eng",
               "tesseract-ocr-rus"],
    "fedora": ["/usr/bin/pkexec", "/usr/bin/dnf", "install", "-y", "tesseract", "tesseract-langpack-eng",
               "tesseract-langpack-rus"],
    "arch": ["/usr/bin/pkexec", "/usr/bin/pacman", "-S", "--noconfirm", "--needed", "tesseract", "tesseract-data-eng",
             "tesseract-data-rus"],
    "opensuse": ["/usr/bin/pkexec", "/usr/bin/zypper", "--non-interactive", "install", "tesseract-ocr",
                 "tesseract-ocr-traineddata-english", "tesseract-ocr-traineddata-russian"],
}
for family, argv_want in want.items():
    argv = ocr.linux_install_argv(["rus", "eng"], family, which_all)
    check(argv == argv_want, f"1: {family}: argv {argv}")
    check(all(os.path.isabs(a) for a in argv[:2]), f"1: {family}: pkexec и менеджер по полному пути")
    check(argv[1].rsplit("/", 1)[1] in MANAGERS, f"1: {family}: менеджер из таблицы")
    pk = [a for a in argv[2:] if not a.startswith("-") and a != "install"]
    check(pk and set(pk) <= ALLOWED, f"1: {family}: только пакеты из таблицы ({pk})")
    check(not any(re.search(r"[;&|$`<>\\\s'\"*?]", a) for a in argv), f"1: {family}: ни shell-знаков, ни пробелов в аргументах")
    check("sh" not in [os.path.basename(a) for a in argv] and "-c" not in argv, f"1: {family}: без sh -c")
# строки от человека не попадают: чужие коды пропускаются
evil = ocr.linux_install_argv(["rus; rm -rf ~", "../../etc", "deu", "$(id)", 5, None], "debian", which_all)
check(evil == ["/usr/bin/pkexec", "/usr/bin/apt-get", "install", "-y", "tesseract-ocr", "tesseract-ocr-eng",
               "tesseract-ocr-deu"], f"1: чужие коды языка пропущены, остался только deu ({evil})")
check(ocr.linux_install_argv(["chi_sim"], "debian", which_all)[-1] == "tesseract-ocr-chi-sim", "1: китайский: tesseract-ocr-chi-sim")
check(ocr.linux_install_argv(["chi_sim"], "fedora", which_all)[-1] == "tesseract-langpack-chi_sim", "1: fedora: chi_sim")
check(ocr.linux_install_argv(["rus"], "debian", which_no_pkexec) is None, "1: нет pkexec: argv нет")
check(ocr.linux_install_argv(["rus"], "", which_all) is None, "1: семейство не известно: argv нет")
check(ocr.linux_install_argv(["rus"], "gentoo", which_all) is None, "1: чужое семейство: argv нет")
check(ocr.linux_install_argv(["rus"], "debian", lambda n, path=None: "pkexec") is None, "1: не полный путь: argv нет")
os.environ["FLATPAK_ID"] = "org.example.ClipSD"
check(ocr.linux_install_argv(["rus"], "debian", which_all) is None, "1: Flatpak: argv нет (остаётся команда)")
del os.environ["FLATPAK_ID"]
real_platform = sys.platform
sys.platform = "win32"
check(ocr.linux_install_argv(["rus"], "debian", which_all) is None, "1: Windows: Linux-установки нет")
sys.platform = real_platform
for family in want:
    for code in ocr._TESS_LANGS:
        pkg = ocr.LINUX_PACKAGES[family]["langs"][code]
        check(re.fullmatch(r"[a-z0-9_.-]+", pkg) is not None, f"1: {family}/{code}: имя пакета {pkg} безопасно")

# --- 2. ход установки (Linux) -------------------------------------------------------------------------------------
real_family = ocr.linux_family
ocr.linux_family = lambda: "debian"
real_which_argv = ocr.linux_install_argv
ocr.linux_install_argv = lambda codes, family=None, which=None: real_which_argv(codes, family, which or which_all)
help_ru = ocr.install_help("no_rus")
check(help_ru.install_langs == ("rus",), "2: подсказка «нет русского» знает язык для кнопки")
check(ocr.can_install(help_ru), "2: кнопка доступна (pkexec на месте)")
check(tr("ocr.lin_no_lang_need", lang="Русский") == help_ru.what, "2: объяснение про кнопку и пароль, а не про терминал")
check(help_ru.command.startswith("sudo apt install"), "2: команда для терминала осталась в подсказке")

events = []
FakeProc.made.clear()
job = ocr.begin_install(help_ru, lambda ok, text, outcome: events.append((ok, text, outcome)),
                        lambda text: events.append(("state", text)), verify=lambda codes: [])
check(job is not None and FakeProc.made[-1].started == want["debian"],
      f"2: запущен ровно pkexec apt-get ... ({FakeProc.made[-1].started})")
check(events and events[0] == ("state", tr("ocr.lin_install_started")), "2: сразу «Устанавливается…»")
FakeProc.made[-1].say("Setting up tesseract-ocr-rus (1:4.1.0-2)\nDone.\n")
FakeProc.made[-1].end(0)
settle()
check(events[-1] == (True, tr("ocr.win_install_done"), "ok"), f"2: код 0: «Готово» ({events[-1]})")

events.clear()
ocr.begin_install(help_ru, lambda ok, text, outcome: events.append((ok, text, outcome)), None, verify=lambda c: [])
FakeProc.made[-1].end(126)
settle()
check(events[-1] == (False, "Установка отменена.", "declined"), f"2: отказ пароля (126): «Установка отменена.» ({events[-1]})")
events.clear()
ocr.begin_install(help_ru, lambda ok, text, outcome: events.append((ok, text, outcome)), None, verify=lambda c: [])
FakeProc.made[-1].end(127)
settle()
check(events[-1][2] == "declined", "2: окно пароля закрыли (127): тоже отмена")
events.clear()
ocr.begin_install(help_ru, lambda ok, text, outcome: events.append((ok, text, outcome)), None, verify=lambda c: [])
FakeProc.made[-1].say("E: Unable to locate package tesseract-ocr-rus\n")
FakeProc.made[-1].end(100)
settle()
check(events[-1][0] is False and events[-1][2] == "failed" and tr("ocr.lin_err_nopkg") in events[-1][1],
      f"2: ошибка менеджера понятным текстом ({events[-1][1]})")
events.clear()
ocr.begin_install(help_ru, lambda ok, text, outcome: events.append((ok, text, outcome)), None, verify=lambda c: [])
FakeProc.made[-1].say("E: Could not get lock /var/lib/dpkg/lock-frontend\n")
FakeProc.made[-1].end(100)
settle()
check(tr("ocr.lin_err_lock") in events[-1][1], "2: менеджер занят: объяснено")
events.clear()
ocr.begin_install(help_ru, lambda ok, text, outcome: events.append((ok, text, outcome)), None, verify=lambda c: [])
FakeProc.made[-1].say("something odd happened\n")
FakeProc.made[-1].end(1)
settle()
check(events[-1][0] is False and "something odd happened" in events[-1][1], "2: прочая ошибка: последняя строка вывода в тексте")
events.clear()
ocr.begin_install(help_ru, lambda ok, text, outcome: events.append((ok, text, outcome)), None, verify=lambda c: ["rus"])
FakeProc.made[-1].end(0)
settle()
check(events[-1][0] is False, "2: код 0, но языка по-прежнему нет: не «Готово», а ошибка")
events.clear()
ocr.begin_install(help_ru, lambda ok, text, outcome: events.append((ok, text, outcome)), None, verify=lambda c: [])
FakeProc.made[-1].errorOccurred.emit(QProcess.ProcessError.FailedToStart)
settle()
check(events[-1][2] == "failed", "2: pkexec не запустился: ошибка, не зависание")

# нет pkexec: кнопки нет, команда на виду
ocr.linux_install_argv = lambda codes, family=None, which=None: real_which_argv(codes, family, which_no_pkexec)
help_np = ocr.install_help("no_rus")
check(not ocr.can_install(help_np), "2: нет pkexec: кнопки нет")
check(ocr.begin_install(help_np, lambda *a: None) is None, "2: нет pkexec: begin_install ничего не запускает")
check(help_np.what == tr("ocr.no_rus_need"), "2: без pkexec прежнее объяснение про терминал")
blk = ocr.InstallBlock(help_np)
blk.show()
check(blk.install_button is None and blk.command_field.isVisibleTo(blk), "2: без pkexec: команда видна, кнопки нет (как раньше)")
blk.close()
os.environ["FLATPAK_ID"] = "x"
ocr.linux_install_argv = real_which_argv
check(not ocr.can_install(ocr.install_help("missing")), "2: Flatpak: кнопки нет")
del os.environ["FLATPAK_ID"]
ocr.linux_install_argv = lambda codes, family=None, which=None: real_which_argv(codes, family, which or which_all)

# блок с кнопкой
blk = ocr.InstallBlock(help_ru, again=False)
blk.show()
settle()
check(blk.install_button is not None and blk.install_button.text() == tr("ocr.win_install_button"), "2: блок: кнопка «Установить распознавание»")
check(blk.manual_link is not None and blk.manual_link.isVisibleTo(blk), "2: блок: мелкая ссылка «Поставить вручную»")
check(not blk.command_field.isVisibleTo(blk), "2: блок: команда спрятана до «Поставить вручную»")
got = []
blk.installed.connect(lambda: got.append(1))
FakeProc.made.clear()
blk.install_button.click()
settle()
check(not blk.install_button.isEnabled() and blk.install_status.text() == tr("ocr.lin_install_started"),
      "2: нажали: кнопка неактивна, «Устанавливается…»")
check(FakeProc.made[-1].started[:2] == ["/usr/bin/pkexec", "/usr/bin/apt-get"], "2: нажатие запускает pkexec apt-get (через заглушку)")
FakeProc.made[-1].end(126)
settle()
check(blk.install_status.text() == "Установка отменена." and blk.install_button.isEnabled() and not got,
      "2: отказ пароля: «Установка отменена.», кнопка снова доступна")
blk.manual_link.linkActivated.emit("manual")
settle()
check(blk.command_field.isVisibleTo(blk) and blk.command_field.text().startswith("sudo apt install"),
      "2: «Поставить вручную» открывает команду")
blk.install_button.click()
FakeProc.made[-1].say("E: Unable to locate package\n")
FakeProc.made[-1].end(100)
settle()
check(tr("ocr.lin_install_failed", error=tr("ocr.lin_err_nopkg")) == blk.install_status.text(), "2: ошибка в блоке понятным текстом")
blk.install_button.click()
real_verify = ocr._missing_after_install
ocr._missing_after_install = lambda codes: []
FakeProc.made[-1].end(0)
settle()
check(blk.install_status.text() == tr("ocr.win_install_done") and got == [1] and not blk.install_button.isEnabled(),
      "2: успех: «Готово: распознайте ещё раз», сигнал installed, кнопка неактивна")
blk.close()
blk = ocr.InstallBlock(help_ru, again=True)
blk.install_button.click()
FakeProc.made[-1].end(0)
settle()
check(blk.install_status.text() == tr("ocr.install_done_again"), "2: когда владелец повторит сам: «Готово. Распознаю ещё раз…»")
blk.close()
ocr._missing_after_install = real_verify

# --- 3. окна редактора --------------------------------------------------------------------------------------------
class Ctx:
    def __init__(self):
        self.config = dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True, translate_view="overlay")
        self.icon = appmod.make_icon()

    def copy_image(self, image):
        pass

    def notify(self, text):
        pass

    def save_config(self):
        pass


def image(w=500, h=240):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor("white"))
    return img


class Job:
    words = []
    used = ""
    help = None


def make_words(texts, ox=10):
    from PyQt6.QtCore import QRectF
    return [ocr.Word(t, QRectF(ox + 60 * i, 20, 50, 20), ("l", 0)) for i, t in enumerate(texts)]


def editor():
    i18n.set_language("ru")
    ctx = Ctx()
    themes.apply_app(qapp, ctx.config)
    ed = EditorWindow(image(), ctx, QPoint(20, 20))
    ed.present()
    settle()
    return ed, ctx


real_start, real_show = ocr.start, ocr.show_result
real_dism, real_langs, real_sysdir = sysenv.run_elevated_wait, ocr.installed_ocr_languages, getattr(sysenv, "_system_dir", None)
calls = []
state = {"garbled": True}


def fake_start(img, on_done, langs=None, quality=None):
    """Распознавание-заглушка: пока «не установлено»: каракули и подсказка; после установки: русские слова."""
    job = Job()
    calls.append(state["garbled"])
    if state["garbled"]:
        job.words = make_words(["PeKOMeHAOBaHO", "TEKCT"])
        help_ = ocr.install_help("windows_lang")
    else:
        job.words = make_words(["Рекомендовано", "текст"])
        help_ = None
    from PyQt6.QtCore import QTimer
    QTimer.singleShot(0, lambda: on_done("", "", help_))
    return job


ocr.start = fake_start
ocr._early[ocr.resolve_langs("auto")] = "ok"
sys.platform = "win32"
dism_calls = []


def fake_dism(exe, args, timeout):
    dism_calls.append(args)
    state["garbled"] = False   # «установилось»
    return 0, "", False


sysenv.run_elevated_wait = fake_dism
sysenv.dism_exe = lambda: r"C:\Windows\System32\Dism.exe"
ocr.installed_ocr_languages = lambda: ["en-US"]
try:
    # 3a. окно текста (режим «Копировать текст»): ошибка/подсказка с кнопкой
    ed, ctx = editor()
    ed.start_text_mode()
    wait(lambda: ed.canvas.has_words(), 5)
    dlg = ed._ocr_dialog
    check(dlg is not None and dlg.install is not None and dlg.install.install_button is not None,
          "3: Windows, окно текста: кнопка «Установить распознавание» есть")
    check(ed.canvas.words[0].text == "PeKOMeHAOBaHO", "3: сначала каракули")
    # выделили маркером: окно выделенного текста
    ed.canvas.text_sel = {0, 1}
    ed.canvas.update()
    ed.canvas.text_selected.emit(ed.canvas.selected_text())
    settle()
    panel = ed._text_panel
    check(panel is not None and panel.install is not None and panel.install.install_button is not None,
          "3: Windows, окно выделенного текста: кнопка «Установить распознавание» есть")
    n_calls = len(calls)
    panel.install.install_button.click()
    check(wait(lambda: len(calls) > n_calls and ed.canvas.has_words() and ed.canvas.words[0].text == "Рекомендовано", 10),
          "3: после «Готово» распознавание текущего снимка повторилось само")
    settle(10)
    check(dism_calls and "Language.OCR~~~ru" in dism_calls[0], f"3: установка ушла в (подменённый) Dism ({dism_calls})")
    check(ed.canvas.selected_text() == "Рекомендовано текст", f"3: выделенное осталось выделенным уже по новому тексту ({ed.canvas.selected_text()!r})")
    check(ed._text_panel is not None and ed._text_panel.edit.toPlainText() == "Рекомендовано текст",
          "3: в окне выделенного текста новый текст (в буфере обмена тоже)")
    check(ed._text_panel.install is None, "3: блок установки в окне исчез")
    # 3b. окно текста закрывается само после «Готово», распознавание идёт заново
    state["garbled"] = True
    dism_calls.clear()
    ed.canvas.words, ed.canvas.text_sel = [], set()
    ed._text_panel and ed._text_panel.close()
    settle()
    ed.start_text_mode()
    wait(lambda: ed.canvas.has_words(), 5)
    dlg = ed._ocr_dialog
    n_calls = len(calls)
    dlg.install.install_button.click()
    check(wait(lambda: len(calls) > n_calls and ed.canvas.words and ed.canvas.words[0].text == "Рекомендовано", 10),
          "3: из окна текста: после «Готово» слова снимка обновились сами")
    from PyQt6 import sip  # noqa: E402
    check(wait(lambda: sip.isdeleted(dlg) or not dlg.isVisible(), 5), "3: окно с подсказкой закрылось после «Готово»")
    ed.close()
    settle()

    # 3c. перевод экрана: карточка с ошибкой распознавания
    state["garbled"] = True
    dism_calls.clear()
    ed, ctx = editor()
    ed.select_tool(TRANSLATE)
    settle()
    layer = ed.tr_layer
    card = TranslateCard(QRect(40, 40, 400, 120))
    card.state, card.message, card.help = "error", tr("ocr.err_windows_no_lang"), ocr.install_help("windows_lang")
    layer.tr_cards.append(card)
    layer.repaint()
    settle()
    check("ocrinst" in card.buttons, f"3: Windows, перевод: в карточке кнопка «Установить распознавание» ({list(card.buttons)})")
    retried = []
    layer._tr_run = lambda c: retried.append(c)   # перевод запускается заново: проверяем сам повтор
    QTest.mouseClick(layer, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, card.buttons["ocrinst"].center().toPoint())
    check(wait(lambda: retried, 10), "3: перевод: после «Готово» перевод куска запустился заново сам")
    check(dism_calls, "3: перевод: установка ушла в (подменённый) Dism")
    ed.close()
    settle()
finally:
    sys.platform = real_platform
    sysenv.run_elevated_wait, ocr.installed_ocr_languages = real_dism, real_langs
    ocr.start = real_start

# 3d. то же в карточке на Linux: кнопка, ход, отказ
ed, ctx = editor()
ed.select_tool(TRANSLATE)
settle()
layer = ed.tr_layer
card = TranslateCard(QRect(40, 40, 400, 120))
card.state, card.message, card.help = "error", tr("ocr.err_not_installed"), ocr.install_help("missing")
layer.tr_cards.append(card)
layer.repaint()
settle()
check("ocrinst" in card.buttons, "3: Linux, перевод: в карточке кнопка «Установить распознавание»")
FakeProc.made.clear()
QTest.mouseClick(layer, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, card.buttons["ocrinst"].center().toPoint())
settle()
check(card.installing and card.message == tr("ocr.lin_install_started") and FakeProc.made, "3: Linux, карточка: идёт установка, ход в тексте")
FakeProc.made[-1].end(126)
settle()
check(not card.installing and card.message == "Установка отменена.", "3: Linux, карточка: отказ пароля: «Установка отменена.»")
ed.close()
settle()

# --- 4а. сама проверка до распознавания (без подмены early_help) ---------------------------------------------------
real_find, real_tlangs, real_winl = ocr.find_tesseract, ocr.tesseract_langs, ocr.installed_ocr_languages
ocr.find_tesseract = lambda: None
h = ocr.early_help("rus+eng")
check(h is not None and h.install_langs == ("rus", "eng"), "4а: Linux без Tesseract: подсказка с кнопкой (языки rus, eng)")
ocr.find_tesseract = lambda: "/usr/bin/tesseract"
ocr.tesseract_langs = lambda exe: {"eng", "osd"}
h = ocr.early_help("rus+eng")
check(h is not None and h.install_langs == ("rus",), "4а: Linux, Tesseract без русского: подсказка про русский")
ocr.tesseract_langs = lambda exe: {"eng", "rus"}
check(ocr.early_help("rus+eng") is None, "4а: Linux, русский есть: предупреждения нет")
check(ocr.early_help("eng") is None, "4а: английский интерфейс: предупреждения нет")
check(ocr.installed_codes() == ["eng", "rus"], "4а: Linux: installed_codes из tesseract --list-langs")
ocr.find_tesseract = lambda: None
check(ocr.installed_codes() is None, "4а: Linux без Tesseract: installed_codes None")
sys.platform = "win32"
try:
    ocr.installed_ocr_languages = lambda: ["en-US"]
    h = ocr.early_help("rus+eng")
    check(h is not None and h.ocr_capability == "ru-RU", "4а: Windows, в списке только en-US: нужен ru-RU (AvailableRecognizerLanguages)")
    ocr.installed_ocr_languages = lambda: ["ru", "en-US"]
    check(ocr.early_help("rus+eng") is None, "4а: Windows, русский в списке: предупреждения нет")
    ocr.installed_ocr_languages = lambda: None
    check(ocr.early_help("rus+eng") is None, "4а: Windows, список узнать не удалось: не мешаем")
    ocr.installed_ocr_languages = lambda: ["en-US"]
    h = ocr.early_help("deu+eng")
    check(h is not None and h.ocr_capability == "de-DE", "4а: Windows, немецкий: нужен de-DE")
    ocr.find_tesseract = lambda: "C:/Tesseract-OCR/tesseract.exe"
    ocr.tesseract_langs = lambda exe: {"eng", "rus"}
    check(ocr.early_help("rus+eng") is None, "4а: Windows, русский есть у Tesseract: предупреждения нет")
    # строка состояния в настройках на Windows: список приходит из PowerShell в фоне
    ocr.find_tesseract = lambda: None
    ocr.installed_ocr_languages = lambda: ["ru", "en-US"]
    row = ocr.OcrStatusRow()
    check(row.label.text() == tr("ocr.status_checking") and not row.more_button.isEnabled(), "4а: Windows: сначала «проверяю…»")
    check(wait(lambda: row.label.text() == "Распознавание: русский, английский", 5), f"4а: Windows: «{row.label.text()}»")
    check("ru-RU" not in str(row.menu_languages()) and "bul" in row.menu_languages(), "4а: Windows: меню ещё не установленных языков")
    row.close()
finally:
    sys.platform = real_platform
    ocr.find_tesseract, ocr.tesseract_langs, ocr.installed_ocr_languages = real_find, real_tlangs, real_winl

# --- 4. заранее ---------------------------------------------------------------------------------------------------
ocr.linux_family = lambda: "debian"
ocr._early.clear()
asked = []
ocr.early_help = lambda langs=None: help_ru   # «нет русского»
real_start = ocr.start
calls.clear()
state["garbled"] = False


def fake_start2(img, on_done, langs=None, quality=None):
    job = Job()
    job.words = make_words(["Привет", "мир"])
    calls.append(1)
    from PyQt6.QtCore import QTimer
    QTimer.singleShot(0, lambda: on_done("", "", None))
    return job


ocr.start = fake_start2
ed, ctx = editor()
ed.start_text_mode()
dialogs = []
wait(lambda: [w for w in qapp.topLevelWidgets() if isinstance(w, ocr.TextResultDialog) and w.isVisible()], 5)
dialogs = [w for w in qapp.topLevelWidgets() if isinstance(w, ocr.TextResultDialog) and w.isVisible()]
check(len(dialogs) == 1 and tr("ocr.early_need", lang="Русский") in dialogs[0].note.text(),
      "4: нет языка: окно «Для текста на языке «Русский» нужно распознавание» до распознавания")
check(not calls, "4: распознавание ещё не запускалось (предупреждение до попытки, а не после каракулей)")
check(dialogs and dialogs[0].install is not None and dialogs[0].install.install_button is not None, "4: в окне кнопка «Установить распознавание»")
dialogs[0].close()
check(wait(lambda: calls, 5) and wait(lambda: ed.canvas.has_words(), 5), "4: окно закрыли: распознавание идёт как раньше")
ed.canvas.words = []
ed.start_text_mode()
settle(20)
check(len([w for w in qapp.topLevelWidgets() if isinstance(w, ocr.TextResultDialog) and w.isVisible()]) == 0 and len(calls) == 2,
      "4: предложение один раз за запуск: второй раз сразу распознаёт")
ed.close()
settle()

# установка из этого окна: после «Готово» окно закрывается и распознавание идёт само
ocr._early.clear()
calls.clear()
ed, ctx = editor()
ed.start_text_mode()
wait(lambda: [w for w in qapp.topLevelWidgets() if isinstance(w, ocr.TextResultDialog) and w.isVisible()], 5)
dlg = [w for w in qapp.topLevelWidgets() if isinstance(w, ocr.TextResultDialog) and w.isVisible()][0]
FakeProc.made.clear()
real_verify = ocr._missing_after_install
ocr._missing_after_install = lambda codes: []
dlg.install.install_button.click()
settle()
check(not calls and FakeProc.made, "4: идёт установка: распознавание ждёт")
FakeProc.made[-1].end(0)
check(wait(lambda: dlg.install.install_status.text() == tr("ocr.install_done_again"), 5), "4: в окне «Готово. Распознаю ещё раз…»")
check(wait(lambda: calls, 6) and wait(lambda: ed.canvas.has_words(), 5), "4: после «Готово» распознавание снимка запустилось само")
ocr._missing_after_install = real_verify
ed.close()
settle()

# язык есть: сразу, без окна
ocr._early.clear()
calls.clear()
ocr.early_help = lambda langs=None: None
ed, ctx = editor()
ed.start_text_mode()
check(wait(lambda: calls, 5), "4: язык есть: распознавание сразу")
check(not [w for w in qapp.topLevelWidgets() if isinstance(w, ocr.TextResultDialog) and w.isVisible()], "4: язык есть: окна нет")
ed.close()
settle()
ocr.start = real_start

# --- 5. строка в настройках ---------------------------------------------------------------------------------------
row = ocr.OcrStatusRow(codes=["rus", "eng"])
row.show()
settle()
check(row.label.text() == "Распознавание: русский, английский", f"5: строка состояния: {row.label.text()!r}")
check(row.more_button.text() == "Установить ещё язык" and row.more_button.isVisibleTo(row), "5: рядом кнопка «Установить ещё язык»")
check("rus" not in row.menu_languages() and "eng" not in row.menu_languages() and "bul" in row.menu_languages(),
      "5: в меню только ещё не установленные языки")
FakeProc.made.clear()
ocr._missing_after_install = lambda codes: []
ocr.installed_codes = lambda: ["bul", "eng", "rus"]
row.install_language("bul")
check(FakeProc.made and FakeProc.made[-1].started == ["/usr/bin/pkexec", "/usr/bin/apt-get", "install", "-y", "tesseract-ocr",
                                                      "tesseract-ocr-eng", "tesseract-ocr-bul"], "5: болгарский: pkexec apt-get install ... tesseract-ocr-bul")
check(row.progress.text() == tr("ocr.lin_install_started"), "5: ход в строке под состоянием")
FakeProc.made[-1].end(0)
settle()
check(row.label.text() == "Распознавание: русский, английский, болгарский" and row.progress.text() == tr("ocr.win_install_done"),
      f"5: после установки строка обновилась ({row.label.text()!r})")
row.close()
# отказ
row = ocr.OcrStatusRow(codes=["rus", "eng"])
row.install_language("deu")
FakeProc.made[-1].end(126)
settle()
check(row.progress.text() == "Установка отменена." and row.more_button.isEnabled(), "5: отказ пароля: «Установка отменена.»")
row.close()
# Tesseract нет совсем: строка про установку
ocr.installed_codes = lambda: None
check(ocr.status_line(None) == tr("ocr.status_missing"), "5: нет программы: «Не установлено…»")
# нет pkexec: меню ведёт к команде
ocr.linux_install_argv = lambda codes, family=None, which=None: real_which_argv(codes, family, which_no_pkexec)
row = ocr.OcrStatusRow(codes=["rus", "eng"])
row.install_language("deu")
check(row.manual is not None and row.manual.command_field is not None and "tesseract-ocr-deu" in row.manual.command_field.text(),
      "5: нет pkexec: под строкой команда для терминала")
row.close()
ocr.linux_install_argv = lambda codes, family=None, which=None: real_which_argv(codes, family, which or which_all)

# настройки: строка есть в окне настроек
from clipshot.settings import SettingsDialog  # noqa: E402
ocr.installed_codes = lambda: ["eng", "rus"]
sctx = Ctx()
sd = SettingsDialog(sctx.config)
check(isinstance(sd.ocr_status, ocr.OcrStatusRow) and sd.ocr_status.label.text() == "Распознавание: русский, английский",
      "5: в окне настроек, раздел «Распознавание»: «Распознавание: русский, английский [Установить ещё язык]»")
sd.close()

# --- 6. 12 языков, светлая и тёмная тема -------------------------------------------------------------------------
NEW = ["ocr.lin_missing_need", "ocr.lin_no_lang_need", "ocr.lin_install_started", "ocr.lin_install_declined",
       "ocr.lin_install_failed", "ocr.lin_err_nopkg", "ocr.lin_err_lock", "ocr.install_manual", "ocr.install_done_again",
       "ocr.early_need", "ocr.status_line", "ocr.status_none", "ocr.status_checking", "ocr.install_more"]


def clipped(widget):
    """Подпись или кнопка, чей текст не помещается: обрезка."""
    bad = []
    for w in widget.findChildren(QAbstractButton):
        if w.isVisibleTo(widget) and w.text():
            need = QFontMetrics(w.font()).horizontalAdvance(w.text())
            if w.width() < need:
                bad.append(f"кнопка {w.text()!r}: {w.width()} < {need}")
    for w in widget.findChildren(QLabel):
        if w.isVisibleTo(widget) and w.text() and w.wordWrap() and w.width() > 20:
            if w.height() < w.heightForWidth(w.width()) - 1:
                bad.append(f"подпись {w.text()[:30]!r}: высота {w.height()} < {w.heightForWidth(w.width())}")
    return bad


ocr.linux_family = lambda: "debian"
for lang in i18n.LANGUAGES:
    i18n.set_language(lang, notify=False)
    cat = i18n._load(lang)
    ref = i18n._load("ru")
    check(all(k in cat and cat[k].strip() for k in NEW), f"6: {lang}: все новые строки есть")
    check(all(set(re.findall(r"\{(\w+)\}", ref[k])) == set(re.findall(r"\{(\w+)\}", cat[k])) for k in NEW),
          f"6: {lang}: поля {{...}} в строках те же, что в русской")
    if lang != "ru":
        same = [k for k in NEW if cat[k] == ref[k]]
        check(not same, f"6: {lang}: новые строки переведены ({same})")
    for dark in (False, True):
        tcfg = {"ui_theme": "pro" if dark else "standard"}
        themes.apply_app(qapp, tcfg)   # настоящая тема: светлая и тёмная карточка
        help_x = ocr.install_help("no_rus")
        dlg = ocr.TextResultDialog("", tr("ocr.early_need", lang=ocr._lang_title("rus")), None, help_x, again=True)
        check(dlg.dark == dark, f"6: {lang} dark={dark}: окно взяло тему")
        dlg.show()
        settle(3)
        blk = dlg.install
        blk.install_button.click()   # заглушка процесса: ничего настоящего
        settle(3)
        check(blk.install_status.text() == tr("ocr.lin_install_started"), f"6: {lang} dark={dark}: ход установки виден")
        bad = clipped(dlg)
        check(not bad, f"6: {lang} dark={dark}: окно текста с кнопкой без обрезки {bad[:2]}")
        FakeProc.made[-1].end(126)
        settle(3)
        blk.manual_link.linkActivated.emit("manual")
        settle(3)
        check(not clipped(dlg), f"6: {lang} dark={dark}: окно после отказа без обрезки {clipped(dlg)[:2]}")
        dlg.close()
        row = ocr.OcrStatusRow(tokens=themes.tokens(tcfg),
                               dark=dark, codes=["rus", "eng"])
        row.resize(560, row.sizeHint().height())
        row.show()
        settle(3)
        bad = clipped(row)
        check(not bad, f"6: {lang} dark={dark}: строка состояния без обрезки {bad[:2]}")
        row.close()
settle()
check(not errors, f"ни одного исключения ({len(errors)})")
i18n.set_language("ru", notify=False)
print("ИТОГ: " + ("все проверки пройдены" if not failures else f"провалено {len(failures)}: {failures}"))
sys.exit(1 if failures or errors else 0)
