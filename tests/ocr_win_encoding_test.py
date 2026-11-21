# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Текст с картинки на Windows «каракулями» (21.11.2026, проба 1.34.0): откуда берутся и что их ловит.

Две причины, обе на пути «встроенное распознавание Windows → PowerShell → ClipSD → буфер обмена»:
1. Язык. В Windows нет русского языка распознавания: PowerShell молча брал язык профиля (английский), русский текст
   выходил похожими латинскими буквами, подсказки не было (у Tesseract она была). Теперь сценарий сообщает, какой
   язык просили (OCR_WANT) и какой взяли (OCR_LANG); не тот: подсказка, как поставить язык.
2. Кодировка. Слова шли в стандартный вывод кириллицей как есть; если кодовая страница консоли не переключилась на
   UTF-8 (cp866 у русской Windows, cp1251), буквы превращались в «����». Теперь слова идут в base64 от UTF-8.
Ещё: буфер обмена получает текст как Юникод (на Windows CF_UNICODETEXT). Язык выбирается из установленных в Windows
языков распознавания; в подсказке кнопка «Установить распознавание» (запрос UAC).
Б4 проверки 1.34.1: PowerShell только по полному пути из системной папки, сценарий через -EncodedCommand без файла,
с правами администратора идёт только PowerShell с командой и тегом из списка, итог кодом выхода, файлов не пишет.

На Linux: подменённый запуск PowerShell отдаёт вывод в cp866, cp1251, UTF-8 (с BOM и без), с CRLF.
На Windows (CI): настоящий PowerShell, вывод в cp866; настоящее распознавание русского, если в образе есть русский язык
распознавания, иначе пропуск с пометкой и проверка подсказки на английском движке; формат буфера через WinAPI.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/ocr_win_encoding_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import base64
import os
import subprocess
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CLIPSD_LANG", "ru")

from PyQt6.QtGui import QColor, QGuiApplication, QImage
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
from clipshot import ocr
from clipshot.i18n import tr
failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


RU = ["Привет,", "мир!", "Съешь", "ещё", "этих", "мягких", "булок", "ЁЖ", "Hello", "2026"]


def script_rows(words):
    """Вывод сценария WINDOWS_PS так, как его пишет Emit-Word (строка «U», текст в base64 от UTF-8)."""
    rows = []
    for i, w in enumerate(words):
        b64 = base64.b64encode(w.encode("utf-8")).decode("ascii")
        rows.append("\t".join(["U", str(i // 4), str(10 + 60 * (i % 4)), str(20 + 30 * (i // 4)), "50", "20", b64]))
    return "\r\n".join(rows) + "\r\n"


# 1. Сценарий PowerShell: слова не кириллицей в выводе, просимый и взятый язык в отчёте
check("Emit-Word" in ocr.WINDOWS_PS and "ToBase64String" in ocr.WINDOWS_PS and "UTF8.GetBytes" in ocr.WINDOWS_PS,
      "сценарий пишет текст слов в base64 от UTF-8")
check("$word.Text) -join" not in ocr.WINDOWS_PS, "сценарий не пишет текст слова в вывод как есть")
check("OCR_WANT=" in ocr.WINDOWS_PS and "OCR_LANG=" in ocr.WINDOWS_PS, "сценарий сообщает просимый и взятый язык")
check("param(" not in ocr.WINDOWS_PS and "$env:CLIPSD_OCR_PATH" in ocr.WINDOWS_PS and "$env:CLIPSD_OCR_LANG" in ocr.WINDOWS_PS,
      "сценарий без param(): путь и языки из переменных окружения (сценарий идёт через -EncodedCommand)")
check("Write-Error" not in ocr.WINDOWS_PS and "OCR_ERROR=" in ocr.WINDOWS_PS,
      "ошибки строкой OCR_ERROR в поток ошибок (Write-Error при -EncodedCommand даёт CLIXML)")

# 2. Разбор вывода при любой кодовой странице консоли
for enc in ("utf-8", "utf-8-sig", "cp866", "cp1251", "cp437"):
    raw = script_rows(RU).encode(enc)
    words = ocr._parse_windows(ocr._decode_console(raw), 1.0, 1.0)
    check([w.text for w in words] == RU, f"вывод в {enc}: русские слова целы ({' '.join(w.text for w in words)[:60]})")

# прежний вывод (кириллица как есть) в cp866 и декодирование UTF-8: те самые каракули, от которых base64 защищает
old = "\t".join(["W", "0", "1", "2", "3", "4", "Привет"]) + "\r\n"
garbled = old.encode("cp866").decode("utf-8", "replace")
check("Привет" not in garbled, f"для сравнения: кириллица как есть в cp866 портится ({garbled.split(chr(9))[-1].strip()!r})")
check([w.text for w in ocr._parse_windows(old, 1.0, 1.0)] == ["Привет"], "прежние строки «W» тоже читаются")
check(ocr._parse_windows("U\t0\t1\t2\t3\t4\t%%%не base64\n", 1.0, 1.0) == [], "испорченный base64 пропускается, не роняет")

# сообщения PowerShell об ошибке на языке Windows (не UTF-8): читаются кодовой страницей консоли
msg = "Не удается найти файл"
check(ocr._decode_console(msg.encode("cp866"), "cp866") == msg, "ошибка PowerShell в cp866 читается")
check(ocr._decode_console(msg.encode("utf-8"), "cp866") == msg, "ошибка PowerShell в UTF-8 читается")

# 3. Весь путь recognize_words / OcrJob с подменённым PowerShell (как на Windows без Tesseract)
calls = []


def fake_run_factory(stdout: bytes, stderr: bytes, rc: int = 0):
    def fake_run(cmd, **kw):
        script = base64.b64decode(cmd[cmd.index("-EncodedCommand") + 1]).decode("utf-16-le")
        calls.append((cmd, script, kw.get("env") or {}))
        return subprocess.CompletedProcess(cmd, rc, stdout, stderr)
    return fake_run


def sample_image():
    img = QImage(300, 80, QImage.Format.Format_RGB32)
    img.fill(QColor("#ffffff"))
    return img


from clipshot import sysenv  # noqa: E402
real_run, real_platform, real_find, real_sysdir = ocr.subprocess.run, sys.platform, ocr.find_tesseract, sysenv._system_dir
FAKE_SYSTEM = os.path.join(os.path.abspath(os.sep), "Windows", "System32")   # абсолютный путь и на Linux


def as_windows(stdout: bytes, stderr: bytes, rc: int = 0, langs: str = "rus+eng"):
    """OcrJob.run() в этом потоке, как на Windows без Tesseract. Вернуть (слова, текст, ошибка, подсказка)."""
    got = {}
    ocr.subprocess.run = fake_run_factory(stdout, stderr, rc)
    ocr.find_tesseract = lambda: None
    sysenv._system_dir = lambda: FAKE_SYSTEM
    sys.platform = "win32"
    try:
        job = ocr.OcrJob(sample_image(), langs)
        job.done.connect(lambda t, e: got.update(text=t, error=e))
        job.run()
    finally:
        ocr.subprocess.run, sys.platform, ocr.find_tesseract, sysenv._system_dir = real_run, real_platform, real_find, real_sysdir
    return job.words, got.get("text", ""), got.get("error", ""), job.help


out = script_rows(RU).encode("cp866")
words, text, error, help_ = as_windows(out, b"OCR_WANT=ru OCR_LANG=ru OCR_LINES=3 OCR_SIZE=600x160\r\n")
cmd, script, env = calls[-1]
check(cmd[0] == os.path.join(FAKE_SYSTEM, "WindowsPowerShell", "v1.0", "powershell.exe") and os.path.isabs(cmd[0]),
      f"PowerShell по полному пути из системной папки, не по имени ({cmd[0]})")
check(env.get("CLIPSD_OCR_LANG", "").split(",")[0] == "ru", f"русский интерфейс: Windows просят русский ({env.get('CLIPSD_OCR_LANG')})")
check(script == ocr.WINDOWS_PS and "-File" not in cmd, "сценарий целиком в -EncodedCommand, файла сценария нет")
check(os.path.basename(env.get("CLIPSD_OCR_PATH", "")) == "image.png", "картинка передаётся путём в переменной окружения")
check(not error and [w.text for w in words] == RU and text.startswith("Привет, мир!"),
      f"вывод PowerShell в cp866: в ClipSD русский текст ({text[:40]!r})")
check(help_ is None, "Windows распознал русским: подсказки нет")

words, text, error, help_ = as_windows(script_rows(["npnBeT", "Mnp"]).encode("ascii"),
                                       b"OCR_WANT=ru OCR_LANG=en-US OCR_LINES=1 OCR_SIZE=600x160\r\n")
check(not error and text == "npnBeT Mnp", "Windows без русского: текст есть (английский движок)")
check(help_ is not None and help_.settings_url == ocr.WINDOWS_LANG_SETTINGS and help_.what == tr("ocr.win_lang_need")
      and help_.ocr_capability == "ru-RU",
      "Windows без русского распознал английским: подсказка «поставьте русский язык» с кнопкой параметров")
check(ocr.windows_fallback_help("OCR_WANT=ru OCR_LANG=ru-RU") is None, "ru и ru-RU один язык: без подсказки")
check(ocr.windows_fallback_help("OCR_WANT=en-US OCR_LANG=en-GB") is None, "en-US и en-GB один язык: без подсказки")
check(ocr.windows_fallback_help("OCR_LANG=en-US") is None, "старый сценарий без OCR_WANT: без подсказки")
de = ocr.windows_fallback_help("OCR_WANT=de-DE OCR_LANG=en-US")
check(de is not None and de.what == tr("ocr.win_lang_need_lang", lang=ocr._lang_title("deu")),
      "немецкий интерфейс без немецкого языка в Windows: подсказка про немецкий")

words, text, error, help_ = as_windows(b"", "NO_OCR_LANGUAGE\r\n".encode("cp866"), rc=3)
check(error == tr("ocr.err_windows_no_lang") and help_ is not None, "в Windows нет ни одного языка: понятная ошибка")
words, text, error, help_ = as_windows(b"", "Ошибка: не удается прочитать картинку\r\n".encode("utf-8"), rc=1)
check("не удается прочитать картинку" in error, f"ошибка PowerShell по-русски без каракулей ({error[:60]!r})")

# 3а. Выбор языка из установленных в Windows и кнопка «Установить распознавание» (UAC)
check("AvailableRecognizerLanguages" in ocr.WINDOWS_PS and "OCR_AVAIL=" in ocr.WINDOWS_PS,
      "сценарий выбирает язык из установленных в Windows (ru найдёт и ru-RU) и сообщает их список")
check(ocr.install_help("windows_lang").ocr_capability == "ru-RU", "подсказка про русский: кнопка ставит Language.OCR ru-RU")
check(ocr.install_help("windows_lang", "deu").ocr_capability == "de-DE", "подсказка про немецкий: кнопка ставит de-DE")
for bad in ("ru-RU; calc", "ru-RU\"; Remove-Item C:\\", "", "xx-XX"):
    try:
        ocr.install_parameters(bad)
        check(False, f"чужой тег {bad!r} не принимается")
    except ValueError:
        pass
params = ocr.install_parameters("ru-RU")
parts = params.split()
check(parts[:-1] == ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand"]
      and "-File" not in parts and "-Command" not in parts,
      "администратору только -EncodedCommand, без -File и -Command")
inst = base64.b64decode(parts[-1]).decode("utf-16-le")
check('"Language.OCR~~~ru-RU~0.0.1.0"' in inst and "Add-WindowsCapability" in inst and "@TAG@" not in inst,
      "команда ставит Language.OCR~~~ru-RU~0.0.1.0, тег вписан из списка")
check(not any(w in inst for w in ("WriteAllText", "Out-File", "Set-Content", "$env:", "TEMP", "Get-Content", "param(")),
      "команда администратора не читает и не пишет файлы и не берёт данных из окружения")
check(all(ocr.install_parameters(t) for t in ocr.OCR_CAPS.values()), "все теги списка дают команду")


class FakeApi:
    """Подмена ShellExecuteExW, WaitForSingleObject, GetExitCodeProcess, CloseHandle для sysenv.run_elevated_wait."""

    def __init__(self, ok=True, error=0, wait=0, code=0):
        self.ok, self.error, self.wait, self.code = ok, error, wait, code
        self.info = None
        self.closed = []

    def ShellExecuteExW(self, ref):
        info = ref._obj   # ctypes.byref(структура)
        self.info = dict(verb=info.lpVerb, file=info.lpFile, params=info.lpParameters, show=info.nShow, mask=info.fMask)
        if self.ok:
            info.hProcess = 4242
        return self.ok, self.error

    def WaitForSingleObject(self, handle, ms):
        self.waited = (handle, ms)
        return self.wait

    def GetExitCodeProcess(self, handle, ref):
        ref._obj.value = self.code
        return True

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return True


exe = os.path.join(FAKE_SYSTEM, "WindowsPowerShell", "v1.0", "powershell.exe")
api = FakeApi(code=0)
check(sysenv.run_elevated_wait(exe, params, 1000, api=api) == (0, "", False)
      and api.info == dict(verb="runas", file=exe, params=params, show=0, mask=0x140) and api.closed == [4242],
      "UAC: runas, полный путь, без окна, SEE_MASK_NOCLOSEPROCESS; итог кодом выхода, дескриптор закрыт")
check(sysenv.run_elevated_wait(exe, params, 1000, api=FakeApi(code=3))[0] == 3, "код выхода сбоя доходит до окна")
check(sysenv.run_elevated_wait(exe, params, 1000, api=FakeApi(ok=False, error=1223)) == (None, "ShellExecuteEx 1223", True),
      "отказ в запросе UAC (1223) различается")
check(sysenv.run_elevated_wait(exe, params, 1000, api=FakeApi(wait=0x102))[1] == "timeout", "предел ожидания: «timeout»")
api = FakeApi()
check(sysenv.run_elevated_wait("powershell.exe", params, 1000, api=api)[0] is None and api.info is None,
      "программа не по полному пути не запускается")

# Окно подсказки: кнопка, ожидание в фоне, никаких файлов во временной папке
before = set(os.listdir(tempfile.gettempdir()))
elevated = []
real_wait, real_ps = sysenv.run_elevated_wait, sysenv.powershell_exe


def fake_wait(program, parameters, timeout_ms, api=None):
    import time
    elevated.append((program, parameters, timeout_ms))
    time.sleep(0.3)   # окно не ждёт: кнопка уже выключена, интерфейс живёт
    return outcome


def run_block(result):
    global outcome
    outcome = result
    block = ocr.InstallBlock(ocr.install_help("windows_lang"))
    block.install_button.click()
    busy = not block.install_button.isEnabled() and block.install_status.text() == tr("ocr.win_install_started")
    job = ocr._install_jobs[-1]
    deadline = __import__("time").time() + 10
    while (job.isRunning() or block.install_status.text() == tr("ocr.win_install_started")) and __import__("time").time() < deadline:
        app.processEvents()
    app.processEvents()
    return block, busy


sys.platform = "win32"
sysenv._system_dir = lambda: FAKE_SYSTEM
sysenv.run_elevated_wait = fake_wait
try:
    block, busy = run_block((0, "", False))
    check(block.install_button is not None and block.install_button.text() == tr("ocr.win_install_button"),
          "Windows: в подсказке кнопка «Установить распознавание»")
    check(busy, "кнопка: сразу «Идёт установка», кнопка выключена, ожидание в фоне")
    check(elevated and elevated[0][0] == exe and elevated[0][1] == params and elevated[0][2] == ocr.INSTALL_TIMEOUT * 1000,
          "с правами администратора: PowerShell по полному пути и команда только с тегом ru-RU")
    check(block.install_status.text() == tr("ocr.win_install_done") and not block.install_button.isEnabled(),
          "код 0: «Готово, распознайте текст ещё раз»")
    block, _ = run_block((None, "ShellExecuteEx 1223", True))
    check(block.install_status.text() == tr("ocr.win_install_declined") and block.install_button.isEnabled(),
          "отказ в запросе UAC: понятный текст, кнопку можно нажать снова")
    block, _ = run_block((3, "", False))
    check(block.install_status.text() == tr("ocr.win_install_failed", error="exit 3") and block.install_button.isEnabled(),
          "сбой установки: код выхода в тексте, кнопку можно нажать снова")
    outcome = (0, "", False)
    block = ocr.InstallBlock(ocr.install_help("windows_lang"))
    block.install_button.click()
    job = ocr._install_jobs[-1]
    from PyQt6 import sip  # noqa: E402
    sip.delete(block)   # окно закрыто и удалено, пока установка идёт
    deadline = __import__("time").time() + 10
    while ocr._install_jobs and __import__("time").time() < deadline:
        app.processEvents()
    check(not ocr._install_jobs, "окно закрыли посреди установки: итог пришёл без падения, задание убрано")
finally:
    sysenv.run_elevated_wait, sys.platform, sysenv._system_dir = real_wait, real_platform, real_sysdir
after = set(os.listdir(tempfile.gettempdir()))
check(not [n for n in after - before if n.startswith("clipsd")], f"установка не создаёт файлов и папок во временной папке ({sorted(after - before)})")
check(ocr.InstallBlock(ocr.install_help("no_rus")).install_button is None, "Tesseract без русского: кнопки Windows нет")
check(not hasattr(ocr, "install_windows_ocr") and not hasattr(ocr, "install_result_path"),
      "прежней команды ClipSD с правами администратора и файла итога нет")
cli = subprocess.run([sys.executable, "-m", "clipshot", "--install-ocr-lang", "ru-RU"], capture_output=True, timeout=60,
                     env=dict(os.environ, PYTHONPATH=os.path.dirname(here)))
check(cli.returncode == 2 and b"install-ocr-lang" in cli.stderr, f"clipsd --install-ocr-lang больше нет (код {cli.returncode})")

# netsh у «Разрешить заново» (тоже с правами администратора): полный путь
from clipshot import phone  # noqa: E402
sys.platform = "win32"
sysenv._system_dir = lambda: FAKE_SYSTEM
try:
    cmds = phone.windows_firewall_commands("C:\\x.exe")
finally:
    sys.platform, sysenv._system_dir = real_platform, real_sysdir
check(all(c[0] == os.path.join(FAKE_SYSTEM, "netsh.exe") for c in cmds), f"netsh по полному пути из системной папки ({cmds[0][0]})")

# 4. Буфер обмена: текст как Юникод
sample_text = "Привет, мир! Съешь ещё этих мягких булок. ЁЖ 2026"
ocr.copy_text(sample_text)
md = QGuiApplication.clipboard().mimeData()
check(md is not None and md.hasText() and md.text() == sample_text and QGuiApplication.clipboard().text() == sample_text,
      "в буфере тот же русский текст (text/plain, Юникод)")

if sys.platform == "win32":
    # 5. Windows: настоящий PowerShell. Консоль переключена на cp866 (как русская Windows без UTF-8): слова целы
    body = ocr.WINDOWS_PS_HEAD + '\n[Console]::OutputEncoding = [System.Text.Encoding]::GetEncoding(866)\n' + "\n".join(
        f'Emit-Word {i} {i * 10} 5 40 20 "{w}"' for i, w in enumerate(RU))
    res = ocr._powershell(body)
    words = ocr._parse_windows(ocr._decode_console(res.stdout), 1.0, 1.0)
    print("PowerShell:", res.returncode, [w.text for w in words], ocr._decode_console(res.stderr)[-300:])
    check(res.returncode == 0 and [w.text for w in words] == RU, "Windows: настоящий PowerShell с выводом cp866 отдаёт русские слова целыми")

    # 6. Windows: какие языки распознавания есть в образе
    langs_ps = ("$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]\n"
                "[Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages | ForEach-Object { [Console]::Out.WriteLine($_.LanguageTag) }")
    res = ocr._powershell(langs_ps)
    have = [t.strip() for t in ocr._decode_console(res.stdout).splitlines() if t.strip()]
    print("языки распознавания Windows:", have)

    def draw(path, lines):
        ps = ("Add-Type -AssemblyName System.Drawing; $b = New-Object System.Drawing.Bitmap 900,150; "
              "$g = [System.Drawing.Graphics]::FromImage($b); $g.Clear([System.Drawing.Color]::White); "
              "$f = New-Object System.Drawing.Font 'Segoe UI',22; "
              + "".join(f"$g.DrawString('{t}', $f, [System.Drawing.Brushes]::Black, 12, {20 + 50 * i}); "
                        for i, t in enumerate(lines))
              + f"$b.Save('{path}', [System.Drawing.Imaging.ImageFormat]::Png)")
        ocr._powershell(ps)   # через -EncodedCommand (UTF-16): кириллица в сценарии читается верно
        return QImage(path)

    folder = tempfile.mkdtemp(prefix="clipsd-ocrw-")
    if any(ocr._lang_main(t) == "ru" for t in have):
        img = draw(os.path.join(folder, "ru.png"), ["Привет, мир 2026", "Снимок экрана"])
        job = ocr.OcrJob(img, "rus+eng")
        got = {}
        job.done.connect(lambda t, e: got.update(text=t, error=e))
        job.run()
        print("Windows OCR по-русски:", repr(got.get("text")), ocr.last_info)
        check("Привет" in got.get("text", "") and "Снимок" in got.get("text", ""),
              "Windows: настоящее распознавание русского текста без каракулей")
        check(job.help is None, "Windows с русским языком: подсказки нет")
    else:
        print("ПРОПУСК: в образе Windows нет русского языка распознавания (есть: %s); проверяю подсказку" % ", ".join(have))
        img = draw(os.path.join(folder, "en.png"), ["Hello ClipSD 2026", "Screenshot text"])
        job = ocr.OcrJob(img, "rus+eng")
        got = {}
        job.done.connect(lambda t, e: got.update(text=t, error=e))
        job.run()
        print("Windows OCR:", repr(got.get("text")), got.get("error"), ocr.last_info)
        if have:
            check("ClipSD" in got.get("text", "") and job.help is not None
                  and job.help.settings_url == ocr.WINDOWS_LANG_SETTINGS,
                  "Windows без русского: английский текст распознан и есть подсказка поставить русский")

    if have:
        check("OCR_AVAIL=" in ocr.last_info and "OCR_WANT=ru" in ocr.last_info,
              f"Windows: в отчёте просимый язык и список установленных ({ocr.last_info})")

    # 6а. Windows: путь к PowerShell и netsh настоящий, из системной папки
    import ctypes
    buf = ctypes.create_unicode_buffer(1024)
    ctypes.windll.kernel32.GetSystemDirectoryW(buf, 1024)
    ps_exe = sysenv.powershell_exe()
    print("PowerShell:", ps_exe)
    check(os.path.isabs(ps_exe) and os.path.isfile(ps_exe) and ps_exe.lower().startswith(buf.value.lower())
          and ps_exe.lower().endswith("\\windowspowershell\\v1.0\\powershell.exe"),
          "Windows: PowerShell по полному пути из системной папки, файл есть")
    check(os.path.isfile(phone.windows_firewall_commands("C:\\x.exe")[0][0]), "Windows: netsh.exe по полному пути, файл есть")

    # 7. Windows: буфер обмена настоящий (платформа windows, не offscreen), формат CF_UNICODETEXT
    child = r'''
import ctypes, sys
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
from clipshot import ocr
text = "Привет, мир! ЁЖ"
ocr.copy_text(text)
app.processEvents()
u = ctypes.windll.user32
k = ctypes.windll.kernel32
u.GetClipboardData.restype = ctypes.c_void_p
k.GlobalLock.restype = ctypes.c_void_p
k.GlobalLock.argtypes = [ctypes.c_void_p]
k.GlobalUnlock.argtypes = [ctypes.c_void_p]
ok = u.OpenClipboard(None)
has = u.IsClipboardFormatAvailable(13)
h = u.GetClipboardData(13)
p = k.GlobalLock(h)
got = ctypes.wstring_at(p) if p else None
k.GlobalUnlock(h)
u.CloseClipboard()
print("CLIP", ok, has, got == text, repr(got))
'''
    env = dict(os.environ, QT_QPA_PLATFORM="windows", PYTHONPATH=os.path.dirname(here), PYTHONIOENCODING="utf-8")
    try:
        res = subprocess.run([sys.executable, "-c", child], capture_output=True, timeout=60, env=env)
        out = res.stdout.decode("utf-8", "replace")
        print("буфер Windows:", out.strip()[-200:], res.stderr.decode("utf-8", "replace")[-300:])
        if "CLIP" in out:
            check("CLIP 1 1 True" in out, "Windows: в буфере CF_UNICODETEXT с тем же русским текстом")
        else:
            print("ПРОПУСК: окно Qt на платформе windows в этом образе не запустилось, буфер не проверен")
    except subprocess.TimeoutExpired:
        print("ПРОПУСК: проверка буфера Windows не уложилась в 60 с")

print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено {len(failures)}: {failures}")
# как программа и другие тесты Windows: без разбора обёрток Qt в Py_Exit (на CI Windows 1.34.1 update_app_test
# после «ИТОГ» падал там с 0xC0000005)
from clipshot.exitutil import quick_exit  # noqa: E402
quick_exit(1 if failures else 0)
