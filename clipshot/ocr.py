# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Текст с картинки (распознавание, OCR).

Linux и Windows с установленным Tesseract: программа tesseract (языки rus+eng).
Windows без Tesseract: встроенное распознавание Windows 10/11 (Windows.Media.Ocr) через PowerShell,
ничего докачивать не нужно; язык берётся из установленных в системе (русский, если есть).

Распознавание идёт в фоновом потоке (OcrJob), окно не замирает.
"""

import base64
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading

from PyQt6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRect, QRectF, QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QGuiApplication, QImage, QPainter, QTextOption
from PyQt6.QtWidgets import (QFrame, QGraphicsOpacityEffect, QLabel, QPushButton, QSizePolicy, QTextEdit,
                             QVBoxLayout)

from .dialogs import ClipDialog, icon_pixmap, link_colored
from .i18n import tr
from .sysenv import child_env, elevated_powershell_parameters, encoded_command, open_url

DEFAULT_LANGS = "rus+eng"
# 1.31: языки распознавания по умолчанию (config ocr_langs = "auto"): язык интерфейса и английский
TESS_CODES = {"ru": "rus", "en": "eng", "bg": "bul", "uk": "ukr", "de": "deu", "fr": "fra", "es": "spa", "it": "ita",
              "pt": "por", "pl": "pol", "tr": "tur", "zh": "chi_sim"}
# компонент Windows «распознавание текста» для языка (Add-WindowsCapability Language.OCR~~~<тег>~0.0.1.0)
OCR_CAPS = {"rus": "ru-RU", "eng": "en-US", "bul": "bg-BG", "ukr": "uk-UA", "deu": "de-DE", "fra": "fr-FR",
            "spa": "es-ES", "ita": "it-IT", "por": "pt-BR", "pol": "pl-PL", "tur": "tr-TR", "chi_sim": "zh-CN"}
WIN_TAGS = {"rus": "ru", "eng": "en-US", "bul": "bg", "ukr": "uk", "deu": "de-DE", "fra": "fr-FR", "spa": "es-ES",
            "ita": "it-IT", "por": "pt-BR", "pol": "pl", "tur": "tr", "chi_sim": "zh-Hans"}


def default_langs() -> str:
    """Язык интерфейса + английский (русский только при русском интерфейсе): «deu+eng», «rus+eng», «eng»."""
    from .i18n import current
    main = TESS_CODES.get(current(), "eng")
    return "eng" if main == "eng" else f"{main}+eng"


def resolve_langs(value) -> str:
    """Значение настройки ocr_langs: «auto» (по умолчанию для новых установок) или явный набор вида «rus+eng»."""
    return default_langs() if value in (None, "", "auto") else value


def langs_title(langs: str) -> str:
    """«Немецкий, Английский»: набор языков Tesseract названиями на языке интерфейса."""
    return ", ".join(_lang_title(c) for c in (langs or "").split("+") if c)


def win_tags(langs: str) -> str:
    """Языки встроенного распознавания Windows по очереди (через запятую): язык интерфейса, затем запасные.
    Русский: как в 1.29 (ru, ru-RU); другие: язык, затем английский. Дальше PowerShell берёт языки профиля."""
    tag = win_tag(langs)
    fallback = ["ru", "ru-RU"] if tag == "ru" else ["en-US", "en"]
    return ",".join(dict.fromkeys([tag] + fallback))


def win_tag(langs: str) -> str:
    """Язык встроенного распознавания Windows (оно читает один язык): первый не английский из набора, иначе английский."""
    codes = [c for c in (langs or "").split("+") if c]
    main = next((c for c in codes if c != "eng"), codes[0] if codes else "eng")
    return WIN_TAGS.get(main, "en-US")
last_info = ""   # Windows: каким языком распознавало и сколько строк нашло (для проверки и разбора сбоев)
_found = threading.local()   # .help: подсказка последнего распознавания в этом потоке (Windows взял не тот язык)
TIMEOUT = 90            # секунд на одно распознавание
MAX_PIXELS = 24_000_000  # после увеличения: больше не нужно, Tesseract только замедлится

TESSERACT_GUIDE = "https://tesseract-ocr.github.io/tessdoc/Installation.html"
TESSERACT_WINDOWS = "https://github.com/UB-Mannheim/tesseract/wiki"
WINDOWS_LANG_GUIDE = "https://support.microsoft.com/ru-ru/windows/language-packs-for-windows-a5094319-a92d-18de-5b53-1cfc697cfca8"
WINDOWS_LANG_SETTINGS = "ms-settings:regionlanguage"


class InstallHelp:
    """Что поставить, чтобы распознавание заработало: объяснение, команда (если есть) и ссылка на инструкцию."""

    def __init__(self, what: str, command: str = None, url: str = None, url_title: str = "",
                 settings_url: str = None, ocr_capability: str = None):
        self.what, self.command, self.url, self.url_title = what, command, url, url_title
        self.settings_url = settings_url   # Windows: кнопка «Открыть параметры языка»
        self.ocr_capability = ocr_capability   # Windows: кнопка «Установить распознавание» (тег, напр. ru-RU)


def linux_family() -> str:
    """debian (Ubuntu, Mint…), fedora, arch или пусто: по /etc/os-release."""
    try:
        with open("/etc/os-release", encoding="utf-8") as fh:
            data = dict(line.rstrip("\n").split("=", 1) for line in fh if "=" in line)
    except OSError:
        return ""
    ids = (data.get("ID", "") + " " + data.get("ID_LIKE", "")).replace('"', "").lower().split()
    for family, names in (("debian", ("debian", "ubuntu", "linuxmint", "pop")), ("fedora", ("fedora", "rhel", "centos")),
                          ("arch", ("arch", "manjaro", "endeavouros"))):
        if any(n in ids for n in names):
            return family
    return ""


LINUX_COMMANDS = {
    "debian": ("sudo apt install tesseract-ocr tesseract-ocr-rus", "sudo apt install tesseract-ocr-rus"),
    "fedora": ("sudo dnf install tesseract tesseract-langpack-rus", "sudo dnf install tesseract-langpack-rus"),
    "arch": ("sudo pacman -S tesseract tesseract-data-rus tesseract-data-eng", "sudo pacman -S tesseract-data-rus"),
}


LANG_PACKAGES = {"debian": "sudo apt install tesseract-ocr-{pkg}", "fedora": "sudo dnf install tesseract-langpack-{pkg}",
                 "arch": "sudo pacman -S tesseract-data-{pkg}"}


def _lang_title(code: str) -> str:
    """Название языка Tesseract на языке интерфейса (для подсказок)."""
    two = next((k for k, v in TESS_CODES.items() if v == code), "")
    if not two:
        return code
    from .translate import lang_name
    return lang_name(two)


def install_help(kind: str = "missing", lang: str = "") -> InstallHelp:
    """kind: missing — нет программы распознавания; no_rus — Tesseract есть, но без русского языка;
    windows_lang — в Windows нет языка для встроенного распознавания."""
    if kind == "windows_lang" or (sys.platform == "win32" and kind == "missing"):
        if lang and lang != "rus":   # 1.31: нерусский интерфейс: нужен язык интерфейса, а не русский
            return InstallHelp(tr("ocr.win_lang_need_lang", lang=_lang_title(lang)), None, WINDOWS_LANG_GUIDE,
                               tr("ocr.win_lang_guide_title"), settings_url=WINDOWS_LANG_SETTINGS,
                               ocr_capability=OCR_CAPS.get(lang))
        return InstallHelp(
            tr("ocr.win_lang_need"),
            None, WINDOWS_LANG_GUIDE, tr("ocr.win_lang_guide_title"),
            settings_url=WINDOWS_LANG_SETTINGS, ocr_capability=OCR_CAPS["rus"])
    family = linux_family()
    full, rus_only = LINUX_COMMANDS.get(family, (None, None))
    if kind == "no_rus":
        return InstallHelp(tr("ocr.no_rus_need"),
                           rus_only, TESSERACT_GUIDE, tr("ocr.guide_title"))
    if kind == "no_lang":
        pkg = lang.replace("_", "-") if family == "debian" else lang
        command = LANG_PACKAGES[family].format(pkg=pkg) if family in LANG_PACKAGES else None
        return InstallHelp(tr("ocr.no_lang_need", lang=_lang_title(lang)), command, TESSERACT_GUIDE, tr("ocr.guide_title"))
    return InstallHelp(tr("ocr.missing_need_command") if full else tr("ocr.missing_need_guide"),
                       full, TESSERACT_GUIDE, tr("ocr.guide_title"))


class OcrError(Exception):
    """Понятная человеку причина, почему текст не получен; help — как это исправить установкой."""

    def __init__(self, key: str, help: InstallHelp = None, **fields):
        super().__init__(key)
        self.key, self.fields = key, fields   # текст получается при показе (язык может смениться)
        self.help = help

    def __str__(self):
        return tr(self.key, **self.fields)


def _no_window():
    return {"creationflags": 0x08000000} if sys.platform == "win32" else {}   # CREATE_NO_WINDOW


def find_tesseract():
    path = shutil.which("tesseract")
    if path:
        return path
    if sys.platform == "win32":
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
            candidate = os.path.join(base, "Tesseract-OCR", "tesseract.exe")
            if os.path.isfile(candidate):
                return candidate
    return None


def engine_name() -> str:
    if find_tesseract():
        return "tesseract"
    if sys.platform == "win32":
        return "windows"
    return ""


def tesseract_langs(exe) -> set:
    try:
        out = subprocess.run([exe, "--list-langs"], capture_output=True, text=True, timeout=20, env=child_env(),
                             **_no_window())
    except (OSError, subprocess.TimeoutExpired):
        return set()
    return {line.strip() for line in (out.stdout + out.stderr).splitlines()[1:] if line.strip()}


# --- подготовка картинки --------------------------------------------------------

def _mean_brightness(img: QImage) -> float:
    step = max(1, min(img.width(), img.height()) // 60)
    total = count = 0
    for y in range(0, img.height(), step):
        for x in range(0, img.width(), step):
            total += img.pixelColor(x, y).value()
            count += 1
    return total / max(1, count)


def prepare(image: QImage, quality: str = "accurate") -> QImage:
    """Экранный текст мелкий и бывает светлым на тёмном: серый цвет, тёмная тема переворачивается
    в светлую, картинка увеличивается в 2-3 раза. Так Tesseract ошибается заметно реже."""
    img = image.convertToFormat(QImage.Format.Format_Grayscale8)
    img.setDevicePixelRatio(1.0)
    if _mean_brightness(img) < 128:
        img.invertPixels()
    pixels = max(1, img.width() * img.height())
    factor = 3 if pixels * 9 <= MAX_PIXELS else 2 if pixels * 4 <= MAX_PIXELS else 1
    if quality == "fast":
        factor = 1   # «Быстрее»: без увеличения, в 2-4 раза быстрее, мелкий текст читается хуже
    if factor > 1:
        img = img.scaled(img.width() * factor, img.height() * factor, Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    return img


def tidy(text: str) -> str:
    """Убрать пробелы в концах строк, лишние пустые строки и мусорные одиночные символы на отдельных строках."""
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\f", "").split("\n")]
    lines = [line for line in lines if not re.fullmatch(r"\s*[|_~`'\"]\s*", line)]
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    return out.strip()


class Word:
    """Распознанное слово: текст, рамка в пикселях исходной картинки, ключ строки (слова одной строки рядом)."""
    __slots__ = ("text", "rect", "line")

    def __init__(self, text: str, rect: QRectF, line):
        self.text, self.rect, self.line = text, rect, line

    def __repr__(self):
        return f"Word({self.text!r}, {self.line})"


def words_text(words) -> str:
    """Слова по порядку чтения в текст: в строке через пробел, новая строка с новой строки."""
    out, prev = [], None
    for w in words:
        if prev is not None:
            out.append("\n" if w.line != prev.line else " ")
        out.append(w.text)
        prev = w
    return "".join(out)


# --- раскладка по столбцам ---------------------------------------------------------
# Tesseract на снимках экрана часто склеивает строки соседних столбцов в одну. Как на телефоне Samsung, текст
# читается по смыслу: строка рвётся на широком промежутке, куски собираются в столбцы по пустым вертикальным
# коридорам, порядок чтения: сверху вниз по полосам, внутри полосы со столбцами слева направо, столбец целиком.

SPLIT_GAP = 1.5     # промежуток между словами шире стольких высот строки: это граница столбца
GUTTER = 1.5        # пустой вертикальный коридор шире стольких высот строки: столбцы


class _Seg:
    __slots__ = ("words", "x1", "y1", "x2", "y2")

    def __init__(self, words):
        self.words = words
        self.x1 = min(w.rect.left() for w in words)
        self.y1 = min(w.rect.top() for w in words)
        self.x2 = max(w.rect.right() for w in words)
        self.y2 = max(w.rect.bottom() for w in words)


def _median(values, default=12.0):
    values = sorted(values)
    return values[len(values) // 2] if values else default


def _gutters(segs, width):
    """Пустые по всей высоте вертикальные коридоры шириной не меньше width: [(лево, право)]."""
    spans = sorted((s.x1, s.x2) for s in segs)
    out, reach = [], spans[0][1]
    for x1, x2 in spans[1:]:
        if x1 - reach >= width:
            out.append((reach, x1))
        reach = max(reach, x2)
    return out


def _bands(segs):
    """Полосы сверху вниз: соседние по высоте куски, которые перекрываются, в одной полосе."""
    segs = sorted(segs, key=lambda s: (s.y1, s.x1))
    bands, cur, bottom = [], [segs[0]], segs[0].y2
    for s in segs[1:]:
        if s.y1 >= bottom - 1:
            bands.append(cur)
            cur, bottom = [s], s.y2
        else:
            cur.append(s)
            bottom = max(bottom, s.y2)
    bands.append(cur)
    return bands


def _order(segs, unit, depth=0):
    """Куски в порядке чтения, сгруппированные в блоки (список списков кусков)."""
    if len(segs) <= 1 or depth > 12:
        return [sorted(segs, key=lambda s: (s.y1, s.x1))] if segs else []
    width = unit * GUTTER
    # полосы с общими столбцами сливаются: два столбца одной высоты читаются каждый целиком
    merged, cur = [], None
    for band in _bands(segs):
        if cur is None:
            cur = band
            continue
        if _gutters(cur, width) and _gutters(band, width) and _gutters(cur + band, width):
            cur = cur + band
        else:
            merged.append(cur)
            cur = band
    merged.append(cur)
    blocks = []
    for band in merged:
        gut = _gutters(band, width)
        if not gut:
            blocks.append(sorted(band, key=lambda s: (s.y1, s.x1)))
            continue
        edges = [g[1] for g in gut]
        columns = [[] for _ in range(len(edges) + 1)]
        for sg in band:
            columns[sum(1 for e in edges if sg.x1 >= e)].append(sg)
        for col in columns:
            if col:
                blocks.extend(_order(col, unit, depth + 1))
    return blocks


def layout(words):
    """Слова в порядке чтения по столбцам; у каждого слова ключ строки (блок, строка) для сборки текста."""
    if not words:
        return []
    unit = _median([w.rect.height() for w in words])
    lines = {}
    for w in words:
        lines.setdefault(w.line, []).append(w)
    segs = []
    for line_words in lines.values():
        line_words.sort(key=lambda w: w.rect.left())
        h = max(unit, _median([w.rect.height() for w in line_words], unit))
        cur = [line_words[0]]
        for w in line_words[1:]:
            if w.rect.left() - cur[-1].rect.right() > SPLIT_GAP * h:
                segs.append(_Seg(cur))
                cur = [w]
            else:
                cur.append(w)
        segs.append(_Seg(cur))
    out = []
    for bi, block in enumerate(_order(segs, unit)):
        for li, sg in enumerate(block):
            for w in sorted(sg.words, key=lambda w: w.rect.left()):
                out.append(Word(w.text, w.rect, (bi, li)))
    return out


def _parse_tsv(tsv: str, scale_x: float, scale_y: float):
    words = []
    for row in tsv.splitlines()[1:]:
        cols = row.split("\t")
        if len(cols) < 12 or cols[0] != "5" or not cols[11].strip():
            continue
        try:
            left, top, width, height = (float(c) for c in cols[6:10])
            conf = float(cols[10])
        except ValueError:
            continue
        text = cols[11].strip()
        if conf < 0 or (conf < 30 and re.fullmatch(r"[|_~`'\".,:;-]", text)):
            continue   # одиночный мусорный знак с низкой уверенностью: рамки окон, линии
        words.append(Word(text, QRectF(left / scale_x, top / scale_y, width / scale_x, height / scale_y),
                          (cols[1], cols[2], cols[3], cols[4])))
    return words


# --- движки ----------------------------------------------------------------------

def _run_tesseract(exe, path, langs) -> str:
    have = tesseract_langs(exe)
    wanted = [lang for lang in langs.split("+") if lang]
    use = [lang for lang in wanted if lang in have] or ([l for l in ("eng",) if l in have])
    if not use:
        raise OcrError("ocr.err_no_langs", install_help("missing"))
    try:
        out = subprocess.run([exe, path, "stdout", "-l", "+".join(use), "--psm", "3", "tsv"],
                             capture_output=True, timeout=TIMEOUT, env=child_env(), **_no_window())
    except subprocess.TimeoutExpired:
        raise OcrError("ocr.err_timeout")
    except OSError as exc:
        raise OcrError("ocr.err_tesseract_start", detail=exc)
    if out.returncode != 0:
        err = out.stderr.decode("utf-8", "replace").strip().splitlines()
        raise OcrError("ocr.err_tesseract_read_detail", detail=err[-1]) if err else OcrError("ocr.err_tesseract_read")
    return out.stdout.decode("utf-8", "replace")


# Встроенное распознавание Windows 10/11. Windows PowerShell 5.1 умеет звать WinRT; асинхронные вызовы ждём через AsTask.
# 1.34.1: слова идут в вывод строкой «U» с текстом в base64 от UTF-8, то есть только латиницей и цифрами. Кодовая
# страница консоли (cp866 у русской Windows, cp1251, UTF-8) на них не влияет: кириллица не превращается в каракули,
# даже если [Console]::OutputEncoding не подействовал (вывод в трубу, Console.Out создан раньше и т.п.).
# 1.34.1 (Б4 проверки): сценарий идёт в PowerShell через -EncodedCommand, без файла во временной папке (файл можно
# подменить между записью и чтением); путь картинки и языки через переменные окружения CLIPSD_OCR_PATH и
# CLIPSD_OCR_LANG. Сбой: строка OCR_ERROR=… в поток ошибок (без CLIXML, который PowerShell пишет при -EncodedCommand).
WINDOWS_PS_HEAD = r'''
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
trap { [Console]::Error.WriteLine("OCR_ERROR=" + $_.Exception.Message); exit 4 }
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
function Emit-Word($li, $x, $y, $w, $h, [string]$text) {
    $b64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($text))
    [Console]::Out.WriteLine((@("U", $li, [int]$x, [int]$y, [int]$w, [int]$h, $b64) -join "`t"))
}
'''
WINDOWS_PS = WINDOWS_PS_HEAD + r'''
$Path = $env:CLIPSD_OCR_PATH
$Lang = $env:CLIPSD_OCR_LANG
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Storage.StorageFile, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$type) {
    $task = $asTask.MakeGenericMethod($type).Invoke($null, @($op))
    $null = $task.Wait(-1)
    $task.Result
}
# 1.34.1: язык выбирается из установленных в Windows языков распознавания (AvailableRecognizerLanguages) по основной
# части тега: «ru» найдёт и «ru», и «ru-RU». Список идёт в отчёт (OCR_AVAIL) для подсказки и разбора сбоев.
$avail = @()
try { $avail = @([Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages) } catch { }
[Console]::Error.WriteLine("OCR_AVAIL=" + (($avail | ForEach-Object { $_.LanguageTag }) -join ','))
$engine = $null
foreach ($tag in ($Lang -split ',')) {
    if (-not $engine -and $tag) {
        $main = ($tag -split '-')[0]
        $hit = @($avail | Where-Object { $_.LanguageTag -eq $tag }) + @($avail | Where-Object { ($_.LanguageTag -split '-')[0] -eq $main })
        if ($hit.Count -gt 0) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($hit[0]) }
        if (-not $engine) {
            $l = New-Object Windows.Globalization.Language $tag
            if ([Windows.Media.Ocr.OcrEngine]::IsLanguageSupported($l)) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($l) }
        }
    }
}
if (-not $engine) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
if (-not $engine) { [Console]::Error.WriteLine("NO_OCR_LANGUAGE"); exit 3 }
[Console]::Error.WriteLine("OCR_WANT=" + ($Lang -split ',')[0] + " OCR_LANG=" + $engine.RecognizerLanguage.LanguageTag)
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($Path)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
[Console]::Error.WriteLine("OCR_LINES=" + $result.Lines.Count + " OCR_SIZE=" + $bitmap.PixelWidth + "x" + $bitmap.PixelHeight)
$li = 0
foreach ($line in $result.Lines) {
    foreach ($word in $line.Words) {
        $r = $word.BoundingRect
        Emit-Word $li $r.X $r.Y $r.Width $r.Height $word.Text
    }
    $li++
}
$stream.Dispose()
'''


def _decode_console(data: bytes, fallback: str = None) -> str:
    """Вывод PowerShell в текст: UTF-8, а если байты не UTF-8 (кодировка вывода не переключилась), кодовая страница
    консоли Windows (oem: cp866 у русской Windows). Слова приходят в base64 и от этого не зависят; это для сообщений
    об ошибках, которые PowerShell пишет сам на языке Windows."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    if fallback is None and sys.platform == "win32":
        fallback = "oem"
    if fallback:
        try:
            return data.decode(fallback)
        except (LookupError, UnicodeDecodeError):
            pass
    return data.decode("utf-8", "replace")


def _powershell(script_text: str, env: dict = None, timeout: int = None) -> subprocess.CompletedProcess:
    """Запустить сценарий в Windows PowerShell без окна и без файла: полный путь из системной папки
    (sysenv.powershell_exe, не по имени), текст через -EncodedCommand, данные через переменные окружения env.
    Вывод байтами. OcrError, если не запустился."""
    from .sysenv import powershell_exe
    try:
        exe = powershell_exe()
        child = dict(os.environ)
        child.update(env or {})
        return subprocess.run([exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-EncodedCommand", encoded_command(script_text)],
                              stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout or TIMEOUT, env=child,
                              **_no_window())
    except subprocess.TimeoutExpired:
        raise OcrError("ocr.err_timeout")
    except OSError as exc:
        raise OcrError("ocr.err_powershell_start", detail=exc)


# 1.34.1: кнопка «Установить распознавание». Б4 проверки: с правами администратора идёт только PowerShell Windows по
# полному пути из системной папки, команда целиком в -EncodedCommand (тег языка только из OCR_CAPS, вписан в текст),
# файлов пользователя он не читает и не пишет; итог: код выхода, который ClipSD ждёт в фоне (sysenv.run_elevated_wait).
WINDOWS_INSTALL_PS = r'''
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
try {
    $name = "Language.OCR~~~@TAG@~0.0.1.0"
    $cap = Get-WindowsCapability -Online -Name $name
    if (-not $cap -or -not $cap.Name) { exit 4 }
    if ("$($cap.State)" -ne "Installed") { $null = Add-WindowsCapability -Online -Name $name }
    if ("$((Get-WindowsCapability -Online -Name $name).State)" -eq "Installed") { exit 0 }
    exit 1
} catch { exit 3 }
'''
INSTALL_TIMEOUT = 20 * 60   # секунд: скачивание компонента через Windows Update


def install_parameters(tag: str) -> str:
    """Командная строка PowerShell для установки распознавания языка tag (только из OCR_CAPS, иначе ValueError)."""
    if tag not in OCR_CAPS.values():
        raise ValueError(f"unknown OCR language: {tag!r}")
    return elevated_powershell_parameters(WINDOWS_INSTALL_PS.replace("@TAG@", tag))


class InstallJob(QThread):
    """Установка распознавания в фоне: запрос UAC и ожидание конца установки, окно не замирает.
    done(ok, причина, отказ UAC). Живёт в _install_jobs, а не в окне: окно можно закрыть посреди установки."""
    done = pyqtSignal(bool, str, bool)

    def __init__(self, tag: str):
        super().__init__()
        self.tag = tag

    def run(self):
        from . import sysenv
        try:
            code, reason, declined = sysenv.run_elevated_wait(sysenv.powershell_exe(), install_parameters(self.tag),
                                                              INSTALL_TIMEOUT * 1000)
        except (OSError, ValueError) as exc:
            code, reason, declined = None, str(exc), False
        if code == 0:
            self.done.emit(True, "", False)
        else:
            self.done.emit(False, reason or f"exit {code}", declined)


_install_jobs = []   # живые установки: иначе QThread удалится раньше времени


def _forget_install(job):
    if job in _install_jobs:
        _install_jobs.remove(job)
    job.deleteLater()


def _lang_main(tag: str) -> str:
    """«ru-RU» и «ru» → «ru»; «zh-Hans» → «zh»."""
    return (tag or "").strip().split("-")[0].lower()


def _tess_code(tag: str) -> str:
    """Код Tesseract для тега Windows: «ru» → «rus», «de-DE» → «deu» (для подсказки, какой язык поставить)."""
    main = _lang_main(tag)
    return next((c for c, t in WIN_TAGS.items() if _lang_main(t) == main), "rus")


def windows_fallback_help(info: str):
    """1.34.1: Windows распознал не тем языком, что просили (русского в Windows нет, взял английский из профиля):
    русский текст тогда выходит похожими латинскими буквами, «каракулями». Подсказка, как поставить язык (иначе None).
    info: строка last_info («OCR_WANT=ru OCR_LANG=en-US …»)."""
    fields = dict(part.split("=", 1) for part in (info or "").split() if "=" in part)
    want, got = fields.get("OCR_WANT", ""), fields.get("OCR_LANG", "")
    if not want or not got or _lang_main(want) == _lang_main(got):
        return None
    return install_help("windows_lang", _tess_code(want))


def _run_windows(path, lang="ru") -> str:
    out = _powershell(WINDOWS_PS, {"CLIPSD_OCR_PATH": path, "CLIPSD_OCR_LANG": lang})
    err = _decode_console(out.stderr)
    global last_info
    last_info = " ".join(line.strip() for line in err.splitlines() if line.startswith("OCR_"))
    if out.returncode != 0:
        if "NO_OCR_LANGUAGE" in err:
            raise OcrError("ocr.err_windows_no_lang", install_help("windows_lang", _tess_code(lang.split(",")[0])))
        failed = [line.split("=", 1)[1] for line in err.splitlines() if line.startswith("OCR_ERROR=")]
        tail = failed or [line for line in err.strip().splitlines()
                          if line.strip() and not line.startswith(("#< CLIXML", "<Objs", "OCR_"))]
        raise OcrError("ocr.err_windows_failed_detail", detail=tail[-1]) if tail else OcrError("ocr.err_windows_failed")
    _found.help = windows_fallback_help(last_info)
    return _decode_console(out.stdout)


def _parse_windows(out: str, scale_x: float, scale_y: float):
    """Строки «U» (1.34.1: текст слова в base64 от UTF-8) и прежние «W» (текст как есть)."""
    words = []
    for row in out.splitlines():
        cols = row.rstrip("\r").split("\t")
        if len(cols) < 7 or cols[0].lstrip("\ufeff") not in ("U", "W"):
            continue
        text = cols[6].strip()
        if cols[0].lstrip("\ufeff") == "U":
            try:
                text = base64.b64decode(text, validate=True).decode("utf-8").strip()
            except (ValueError, UnicodeDecodeError):
                continue
        if not text:
            continue
        try:
            x, y, w, h = (float(c) for c in cols[2:6])
        except ValueError:
            continue
        words.append(Word(text, QRectF(x / scale_x, y / scale_y, w / scale_x, h / scale_y), ("w", cols[1])))
    return words


def recognize(image: QImage, langs: str = DEFAULT_LANGS, quality: str = "accurate") -> str:
    """Текст с картинки целиком. Бросает OcrError с понятной причиной."""
    return tidy(words_text(recognize_words(image, langs, quality)))


def recognize_words(image: QImage, langs: str = DEFAULT_LANGS, quality: str = "accurate"):
    """Слова с рамками в пикселях исходной картинки, по порядку чтения. Бросает OcrError."""
    langs = resolve_langs(langs)
    _found.help = None
    if image is None or image.isNull():
        raise OcrError("ocr.err_empty_image")
    exe = find_tesseract()
    if not exe and sys.platform != "win32":
        raise OcrError("ocr.err_not_installed", install_help("missing"))
    folder = tempfile.mkdtemp(prefix="clipsd-ocr-")
    try:
        path = os.path.join(folder, "image.png")
        # Windows сам увеличивает мелкий текст плохо: подготовка помогает обоим движкам, но для Windows без
        # переворота цвета (его движок сам справляется с тёмной темой, а предел размера у него 10 000 px).
        img = prepare(image, quality) if exe else _prepare_windows(image, quality)
        if not img.save(path, "PNG"):
            raise OcrError("ocr.err_prepare")
        sx, sy = img.width() / max(1, image.width()), img.height() / max(1, image.height())
        if exe:
            return layout(_parse_tsv(_run_tesseract(exe, path, langs), sx, sy))
        return layout(_parse_windows(_run_windows(path, win_tags(resolve_langs(langs))), sx, sy))
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _prepare_windows(image: QImage, quality: str = "accurate") -> QImage:
    img = image.convertToFormat(QImage.Format.Format_RGB32)
    img.setDevicePixelRatio(1.0)
    limit = 9000   # у Windows.Media.Ocr предел 10 000 px по стороне
    factor = 2 if max(img.width(), img.height()) * 2 <= limit and img.width() * img.height() * 4 <= MAX_PIXELS else 1
    if max(img.width(), img.height()) > limit:
        return img.scaled(limit, limit, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    if factor > 1 and quality != "fast":
        img = img.scaled(img.width() * factor, img.height() * factor, Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    return img


def missing_rus_help(langs: str = None):
    """Tesseract есть, а нужного языка распознавания нет: подсказка с командой установки (иначе None).
    Русский: прежняя подсказка; другие языки (1.31): та же, с названием языка."""
    langs = resolve_langs(langs)
    exe = find_tesseract()
    if not exe:
        return None
    have = tesseract_langs(exe)
    missing = [c for c in langs.split("+") if c and c != "eng" and c not in have]
    if "rus" in missing:
        return install_help("no_rus")
    if missing:
        return install_help("no_lang", missing[0])
    return None


def engine_help(langs: str = None):
    """Подсказка по установке для окна настроек, если чего-то не хватает (иначе None)."""
    if not find_tesseract() and sys.platform != "win32":
        return install_help("missing")
    return missing_rus_help(langs)


def engine_status() -> str:
    """Что установлено, одной строкой для окна настроек."""
    exe = find_tesseract()
    if exe:
        langs = tesseract_langs(exe)
        pairs = [("rus", tr("ocr.lang_rus")), ("eng", tr("ocr.lang_eng"))]
        main = TESS_CODES.get(__import__("clipshot.i18n", fromlist=["current"]).current(), "rus")
        if main not in ("rus", "eng"):   # 1.31: язык интерфейса первым, русский дальше только если установлен
            pairs.insert(0, (main, _lang_title(main).lower() if main != "chi_sim" else _lang_title(main)))
        names = [n for code, n in pairs if code in langs]
        return tr("ocr.status_installed_langs", langs=", ".join(names)) if names else tr("ocr.status_installed_nolangs")
    if sys.platform == "win32":
        return tr("ocr.status_windows")
    return tr("ocr.status_missing")


# --- фон и окно результата -----------------------------------------------------------

class OcrJob(QThread):
    """Распознавание в фоне. done(text, error): одно из двух пустое. self.help: подсказка по установке или None."""
    done = pyqtSignal(str, str)

    def __init__(self, image: QImage, langs: str = DEFAULT_LANGS, parent=None, quality: str = "accurate"):
        super().__init__(parent)
        self.image = image.copy()
        self.langs = langs
        self.quality = quality
        self.help = None
        self.words = []

    def run(self):
        try:
            _found.help = None
            self.words = recognize_words(self.image, self.langs, self.quality)
            text = tidy(words_text(self.words))
            # текст есть, но нужного языка нет: подсказать. Tesseract без русского; Windows без русского
            # распознал английским (1.34.1, «каракули» вместо русского текста)
            self.help = missing_rus_help(self.langs) or getattr(_found, "help", None)
            self.done.emit(text, "")
        except OcrError as exc:
            self.help = exc.help
            self.done.emit("", str(exc))
        except Exception as exc:   # noqa: BLE001 — любая неожиданность должна дойти до человека, а не убить поток
            self.done.emit("", tr("ocr.err_unexpected", detail=exc))


_jobs = []   # живые задания: иначе QThread удалится раньше времени


def _forget(job):
    """После выхода из run() (сигнал finished): убрать из живых заданий и удалить. Раньше, по сигналу done из run(),
    ссылка пропадала, пока поток ещё работал: «QThread: Destroyed while thread is still running»."""
    if job in _jobs:
        _jobs.remove(job)
    job.deleteLater()


def start(image: QImage, on_done, langs: str = DEFAULT_LANGS, quality: str = "accurate"):
    job = OcrJob(image, langs, quality=quality)
    _jobs.append(job)

    def finished(text, error):
        try:
            try:
                on_done(text, error, job.help)
            except TypeError:   # старый обработчик с двумя аргументами
                on_done(text, error)
        except RuntimeError:
            # окно обработчика удалено, пока шло распознавание (wrapped C/C++ object has been deleted): в журнал,
            # а не необработанной ошибкой в обработчике сигнала, которая роняет всю программу (Г1 проверки гонок)
            import sys
            sys.excepthook(*sys.exc_info())

    job.done.connect(finished, Qt.ConnectionType.QueuedConnection)
    job.finished.connect(lambda: _forget(job))   # поток удаляется, только когда run() вернулся
    job.start()
    return job


def copy_text(text: str):
    QGuiApplication.clipboard().setText(text)


class Toast(QLabel):
    """Всплывающая плашка, как на телефоне: плавно появляется (150 мс), висит около 1,4 с, плавно гаснет (400 мс).
    Скруглённый фон рисуется сам (стиль на дочернем виджете углы не скругляет).
    Место: у окна есть toast_anchor() (прямоугольник в его координатах): плашка по центру у нижнего края
    высокого прямоугольника или по центру низкого; иначе внизу окна."""
    FADE_IN, SHOW, FADE_OUT = 150, 1400, 400

    def __init__(self, window):
        super().__init__(window)
        self.setObjectName("clipsdToast")
        self.setStyleSheet("QLabel#clipsdToast { color: #ffffff; font-size: 14px; font-weight: bold;"
                           " padding: 9px 18px; background: transparent; }")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.effect)
        self.anim = QPropertyAnimation(self.effect, b"opacity", self)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._fade_out)
        self.hide()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(32, 33, 36, 235))
        p.drawRoundedRect(QRectF(self.rect()), 18, 18)
        p.end()
        super().paintEvent(event)

    def _place(self):
        win = self.parentWidget()
        anchor = win.toast_anchor() if hasattr(win, "toast_anchor") else None
        if anchor is not None and not anchor.isEmpty():
            x = anchor.left() + max(0, (anchor.width() - self.width()) // 2)
            if anchor.height() > 70:   # область снимка: у нижнего края
                y = anchor.bottom() - self.height() - 24
            else:                      # узкое место (ряд кнопок): по центру
                y = anchor.top() + (anchor.height() - self.height()) // 2
            self.move(x, y)
        else:
            self.move((win.width() - self.width()) // 2, max(8, win.height() - self.height() - 70))

    def pop(self, text: str, ms: int = None):
        self.setText(text)
        self.adjustSize()
        self._place()
        was_visible = self.isVisible()
        if not was_visible:
            self.effect.setOpacity(0.0)   # первый показ: проявляется плавно
        self.raise_()
        self.show()
        self.anim.stop()
        self.anim.setDuration(self.FADE_IN)
        self.anim.setStartValue(self.effect.opacity())
        self.anim.setEndValue(1.0)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        try:
            self.anim.finished.disconnect()
        except TypeError:
            pass
        self.anim.start()
        self.timer.start(self.FADE_IN + (ms if ms else self.SHOW))
        # подсказка действия стоит у верхнего края, итог внизу; если окно низкое и они сошлись, подсказка уступает
        from .hints import HintPlate
        host = self.parentWidget()
        for plate in (host.findChildren(HintPlate) if host is not None else []):
            if plate.isVisible() and plate.geometry().intersects(self.geometry()):
                plate.dismiss()

    def _fade_out(self):
        self.anim.stop()
        self.anim.setDuration(self.FADE_OUT)
        self.anim.setStartValue(self.effect.opacity())
        self.anim.setEndValue(0.0)
        try:
            self.anim.finished.disconnect()
        except TypeError:
            pass
        self.anim.finished.connect(self.hide)
        self.anim.start()


def toast(widget, text: str = None, ms: int = None, mark: bool = True):
    """Показать всплывающее сообщение в окне, где находится widget. mark=False: без галочки (информация, не «успех»)."""
    if text is None:
        text = tr("ocr.toast_copied")
    win = widget.window()
    bubble = win.findChild(Toast, "clipsdToast")
    if bubble is None or bubble.parentWidget() is not win:
        bubble = Toast(win)
    bubble.pop(("✓  " + text) if mark else text, ms)
    return bubble


# Размеры букв окон с текстом и установкой (владелец, 17.11.2026: «очень мелко, не читается»): не меньше 15 px
FONT_BODY = 15      # пояснение, подписи, кнопки
FONT_FIELD = 17     # сам текст в поле и команды
FONT_HINT = 13      # вторая строка с оговоркой: помельче, но читается
BUTTON_H = 40       # кнопки одной высоты

# Общий вид ClipDialog (карточка, скругления, шрифт; светлая или тёмная по оформлению) плюс размеры для окон с текстом
def dialog_extra(dark: bool = False) -> str:
    from .dialogs import PALETTES
    c = PALETTES[bool(dark)]
    return f"""
QLabel#ocrNote {{ font-size: {FONT_BODY}px; color: {c['text']}; }}
QLabel#ocrHint {{ font-size: {FONT_HINT}px; color: {c['muted']}; }}
QTextEdit#ocrEdit {{ font-size: {FONT_FIELD}px; padding: 8px 10px; border: 1px solid {c['line']}; border-radius: 8px;
                     background: {c['field']}; color: {c['text']}; }}
QTextEdit#ocrEdit:focus {{ border: 2px solid {c['accent']}; padding: 7px 9px; }}
"""


DIALOG_EXTRA = dialog_extra(False)
BTN_BASE = f"font-size: {FONT_BODY}px; padding: 0px 18px; border-radius: 8px;"


def copy_style(dark: bool = False) -> str:
    from .dialogs import PALETTES
    c = PALETTES[bool(dark)]
    return ("QPushButton { " + BTN_BASE + f" background: {c['card']}; color: {c['text']}; border: 1px solid {c['line']}; }}"
            f" QPushButton:hover {{ background: {c['soft']}; }}")


COPY_STYLE = copy_style(False)
from .themes import GREEN as _GREEN, GREEN_BORDER as _GREEN_BORDER   # noqa: E402  (1.32: один зелёный)
COPIED_STYLE = ("QPushButton { " + BTN_BASE + f" background: {_GREEN}; color: #ffffff; font-weight: bold;"
                f" border: 1px solid {_GREEN_BORDER}; }}")
CLOSE_STYLE = COPY_STYLE


class _NoScreen:
    """Экрана нет (редкий сбой): запасная область, чтобы окно не падало."""
    @staticmethod
    def availableGeometry():
        return QRect(0, 0, 1280, 800)


def _screen_for(widget):
    from PyQt6.QtGui import QCursor
    win = widget.window() if widget is not None else None
    handle = win.windowHandle() if win is not None else None
    screen = handle.screen() if handle is not None else None
    return screen or QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen() or _NoScreen()


class TextResultDialog(ClipDialog):
    """Окно с распознанным текстом: текст уже в буфере обмена, здесь его можно проверить и поправить.
    Вид как у остальных окон ClipSD; высота по содержимому (не выше 60 % экрана, дальше прокрутка в поле)."""

    WIDTH = 640           # ширина карточки: в строку влезает команда установки
    MAX_SHARE = 0.6       # выше этой доли высоты экрана окно не растёт

    def __init__(self, text: str, error: str = "", parent=None, help: InstallHelp = None):
        super().__init__(parent, tr("ocr.window_title"), "", "info", self.WIDTH)
        # не поверх всех окон: окно-спутник редактора, а не отдельное приложение
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        self.setStyleSheet(self.styleSheet() + dialog_extra(self.dark))
        # компактнее обычного ClipDialog: короткий текст должен давать невысокое окно
        self.layout().setContentsMargins(14, 10, 18, 18)
        card_lay = self.card.layout()
        card_lay.setContentsMargins(20, 14, 16, 16)
        card_lay.setSpacing(10)
        self.icon.setFixedSize(30, 30)
        self.icon.setPixmap(icon_pixmap("info", 30))
        self.header.layout().setSpacing(10)
        self.title.setText(tr("ocr.title"))
        self.install = None
        hint = ""
        if error:
            note = error
        elif text:
            note = tr("ocr.note_copied")
            hint = tr("ocr.hint_symbols")
        else:
            note = tr("ocr.note_empty")
        self.note = QLabel(note)
        self.note.setObjectName("ocrNote")
        self.note.setWordWrap(True)
        self.note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.body.addWidget(self.note)
        self.hint = QLabel(hint)
        self.hint.setObjectName("ocrHint")
        self.hint.setWordWrap(True)
        self.hint.setVisible(bool(hint))
        self.body.addWidget(self.hint)
        if help is not None:
            self.install = InstallBlock(help, dark=self.dark)
            self.body.addWidget(self.install)
        self.edit = QTextEdit()
        self.edit.setObjectName("ocrEdit")
        self.edit.setAcceptRichText(False)
        font = self.edit.font()
        font.setPixelSize(FONT_FIELD)
        self.edit.setFont(font)
        self.edit.setPlainText(text)
        self.edit.setVisible(bool(text))
        self.body.addWidget(self.edit, 1)
        self.copy_button = QPushButton(tr("editor.copy"))
        self.copy_button.setFixedHeight(BUTTON_H)
        self.copy_button.setMinimumWidth(150)
        self.copy_button.setStyleSheet(copy_style(self.dark))
        self.copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_button.setVisible(bool(text))
        self.copy_button.clicked.connect(self._copy)
        self._copied = None   # какой текст сейчас лежит в буфере обмена из этого окна
        self.edit.textChanged.connect(self._edited)
        self.close_button = QPushButton(tr("about.close"))
        self.close_button.setFixedHeight(BUTTON_H)
        self.close_button.setStyleSheet(copy_style(self.dark))
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.clicked.connect(self.close)
        self.footer_right.addWidget(self.copy_button)
        self.footer_right.addWidget(self.close_button)
        if text and not error:
            self.mark_copied(text)   # текст уже положили в буфер, когда открывали окно
        self._fit()

    def toast_anchor(self):
        """Плашка «Текст скопирован» ложится по центру ряда кнопок слева от них, не на поле текста."""
        if not self.copy_button.isVisible():
            return None
        top_left = self.copy_button.mapTo(self, QPoint(0, 0))
        left = self.card.mapTo(self, QPoint(24, 0)).x()
        return QRect(left, top_left.y(), max(40, top_left.x() - 8 - left), self.copy_button.height())

    def _fit(self):
        """Окно по содержимому: невысокое для короткого текста, для длинного выше, но не больше 60 % экрана."""
        if self.edit.isVisible() or self.edit.isVisibleTo(self):
            self.ensurePolished()
            doc = self.edit.document()
            doc.setDefaultFont(self.edit.font())
            doc.setTextWidth(self.WIDTH - 36 - 22 - 4)
            line = QFontMetrics(self.edit.font()).lineSpacing()
            want = int(doc.size().height()) + 20
            lo = 2 * line + 20
            self.edit.setMinimumHeight(0)
            self.edit.setMaximumHeight(16777215)
            self.edit.setFixedHeight(lo)
            self.layout().activate()
            chrome = self.sizeHint().height() - lo
            limit = int(_screen_for(self.parentWidget() or self).availableGeometry().height() * self.MAX_SHARE) - chrome
            self.edit.setFixedHeight(max(lo, min(want, max(lo, limit))))
        for lay in (self.body, self.card.layout(), self.layout()):   # вложенные раскладки хранят старые размеры
            lay.invalidate()
        self.layout().activate()
        self.setMinimumHeight(0)
        width = max(self.minimumSizeHint().width(), self.WIDTH + 32)
        self.resize(width, 10)          # сначала до минимума: раскладка пересчитывается под новое поле
        self.layout().activate()
        self.resize(width, self.minimumSizeHint().height())   # по содержимому: и вверх, и вниз

    def _keep_on_screen(self):
        """Новый длинный текст растит окно вниз: если низ ушёл за край экрана, окно сдвигается вверх."""
        area = _screen_for(self).availableGeometry()
        frame = self.frameGeometry()
        y = min(frame.top(), area.bottom() + 1 - frame.height())
        x = min(max(frame.left(), area.left()), max(area.left(), area.right() + 1 - frame.width()))
        self.move(x, max(area.top(), y))

    def set_text(self, text: str):
        """Новый выделенный кусок: показать его (он уже в буфере обмена, кнопка «Скопировано»)."""
        self.edit.setPlainText(text)
        self.edit.setVisible(True)
        self.copy_button.setVisible(True)
        self.mark_copied(text)
        self._fit()
        self._keep_on_screen()

    def mark_copied(self, text: str):
        """Текст в буфере: кнопка зелёная «✓ Скопировано»; правка в поле вернёт «Скопировать»."""
        self._copied = text
        self.copy_button.setText(tr("ocr.copied_mark"))
        self.copy_button.setStyleSheet(COPIED_STYLE)

    def _edited(self):
        if self._copied is not None and self.edit.toPlainText() != self._copied:
            self._copied = None
            self.copy_button.setText(tr("editor.copy"))
            self.copy_button.setStyleSheet(copy_style(self.dark))

    def _copy(self):
        text = self.edit.toPlainText()
        copy_text(text)
        self.mark_copied(text)
        toast(self)


class _WrapField(QTextEdit):
    """Поле только для чтения, где длинная команда или ссылка переносится по строкам и видна целиком.
    Как QLineEdit: text(), кнопка рядом (copy_button)."""

    def __init__(self, value: str, compact: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("installField")
        self.setReadOnly(True)
        self.setAcceptRichText(False)
        self.setPlainText(value)
        self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        font = self.font()
        font.setPixelSize(13 if compact else FONT_FIELD)
        self.setFont(font)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._refit()

    def text(self) -> str:
        return self.toPlainText()

    def _refit(self):
        width = max(120, self.viewport().width() or self.width() or 560)
        doc = self.document()
        doc.setDefaultFont(self.font())
        doc.setDocumentMargin(0)
        doc.setTextWidth(width - 20)   # минус отступы поля слева и справа
        self.setFixedHeight(int(doc.size().height()) + 16)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refit()


class InstallBlock(QFrame):
    """Как установить: объяснение, команда и ссылка, у каждой кнопка «Скопировать»; ссылка открывается щелчком.
    Поля на всю ширину окна, длинное переносится по строкам; буквы не меньше 15 px, как в окне с текстом."""

    @staticmethod
    def style_for(tokens=None, dark: bool = False) -> str:
        """Крупный вид для отдельного окна (tokens=None, светлая карточка) или вид под тему окна настроек:
        мельче, цвета и фон из темы, без жёстко белого."""
        if tokens is None:
            body, field = FONT_BODY, FONT_FIELD
            from .dialogs import PALETTES
            c = PALETTES[bool(dark)]
            bg, fg, field_bg, line = c["card"], c["text"], c["note_bg"] if dark else "#f6f7f9", c["line"]
            button = (f" QFrame#installBlock QPushButton {{ font-size: {FONT_BODY}px; padding: 0px 16px; min-height: 36px;"
                      f" max-height: 36px; border-radius: 8px; border: 1px solid {c['line']}; background: {c['card']}; color: {c['text']}; }}"
                      f" QFrame#installBlock QPushButton:hover {{ background: {c['soft']}; }}")
        else:
            body, field = 13, 13
            bg, fg, field_bg, line = "transparent", tokens["text"], tokens["input_bg"], tokens["button_border"]
            button = ""   # кнопки как у соседних карточек настроек
        return (f"QFrame#installBlock {{ border: 2px solid #7c3aed; border-radius: 10px; background: {bg}; }}"
                f" QFrame#installBlock QLabel {{ font-size: {body}px; color: {fg}; border: none; background: transparent; }}"
                f" QFrame#installBlock QTextEdit#installField {{ font-size: {field}px; padding: 6px 10px;"
                f" border: 1px solid {line}; border-radius: 8px; background: {field_bg}; color: {fg}; }}" + button)

    def __init__(self, help: InstallHelp, parent=None, tokens=None, dark: bool = False):
        super().__init__(parent)
        self.setObjectName("installBlock")
        self.setStyleSheet(self.style_for(tokens, dark))
        self._compact = tokens is not None
        box = QVBoxLayout(self)
        box.setContentsMargins(14, 12, 14, 14)
        box.setSpacing(8)
        heading = getattr(help, "title", None) or (tr("ocr.heading_install")
                                                   if help.command or sys.platform != "win32"
                                                   else tr("ocr.heading_windows"))
        title = QLabel(f"<b>{heading}</b>")
        title.setWordWrap(True)
        box.addWidget(title)
        what = QLabel(help.what)
        what.setWordWrap(True)
        what.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.addWidget(what)
        self.command_field = self.url_field = self.settings_button = None
        if help.command:
            self.command_field = self._copy_row(box, help.command, tr("ocr.copy_command"), self._compact)
            hint = QLabel(tr("ocr.terminal_hint"))
            hint.setWordWrap(True)
            box.addWidget(hint)
        self.install_button = self.install_status = None
        if sys.platform == "win32" and getattr(help, "ocr_capability", None):
            self.install_button = QPushButton(tr("ocr.win_install_button"))
            self.install_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.install_button.clicked.connect(lambda: self.install_ocr(help.ocr_capability))
            box.addWidget(self.install_button, 0, Qt.AlignmentFlag.AlignLeft)
            self.install_status = QLabel()
            self.install_status.setWordWrap(True)
            self.install_status.setVisible(False)
            box.addWidget(self.install_status)
        if help.settings_url:
            self.settings_button = QPushButton(tr("ocr.open_win_settings"))
            self.settings_button.clicked.connect(lambda: open_url(help.settings_url))
            box.addWidget(self.settings_button, 0, Qt.AlignmentFlag.AlignLeft)
        if help.url:
            link = QLabel(link_colored(f'<a href="{help.url}">{help.url_title or help.url}</a>', dark))
            link.linkActivated.connect(open_url)   # not Qt's own opener: see sysenv.open_url
            link.setWordWrap(True)
            link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            box.addWidget(link)
            self.url_field = self._copy_row(box, help.url, tr("ocr.copy_link"), self._compact)
        if getattr(help, "url2", None):
            link2 = QLabel(link_colored(f'<a href="{help.url2}">{help.url2_title or help.url2}</a>', dark))
            link2.linkActivated.connect(open_url)
            link2.setWordWrap(True)
            box.addWidget(link2)
            self._copy_row(box, help.url2, tr("ocr.copy_link"), self._compact)
        if sys.platform == "win32" and help.settings_url:
            link2 = QLabel(link_colored(tr("ocr.second_link", url=TESSERACT_WINDOWS), dark))
            link2.linkActivated.connect(open_url)
            link2.setWordWrap(True)
            box.addWidget(link2)
            self._copy_row(box, TESSERACT_WINDOWS, tr("ocr.copy_link"), self._compact)

    def install_ocr(self, tag: str):
        """«Установить распознавание»: запрос UAC и ожидание конца установки в фоне (InstallJob)."""
        job = InstallJob(tag)
        _install_jobs.append(job)
        job.done.connect(self._install_finished)   # метод окна: закрытое окно Qt отвязывает само
        job.finished.connect(lambda: _forget_install(job))
        self.install_button.setEnabled(False)
        self.install_status.setVisible(True)
        self.install_status.setText(tr("ocr.win_install_started"))
        job.start()
        return job

    def _install_finished(self, ok: bool, error: str, declined: bool):
        self.install_button.setEnabled(not ok)
        self.install_status.setText(tr("ocr.win_install_done") if ok else tr("ocr.win_install_declined") if declined
                                    else tr("ocr.win_install_failed", error=error))

    @staticmethod
    def _copy_row(box, value, caption, compact=False):
        """Поле на всю ширину блока, под ним кнопка «Скопировать»."""
        field = _WrapField(value, compact)
        button = QPushButton(caption)
        button.setCursor(Qt.CursorShape.PointingHandCursor)

        def copy():
            copy_text(value)
            button.setText(tr("ocr.copied_mark"))
            toast(button, tr("ocr.command_copied") if value.startswith("sudo ") else tr("ocr.link_copied"))
        button.clicked.connect(copy)
        box.addWidget(field)
        box.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft)
        field.copy_button = button
        return field


def show_result(text: str, error: str, parent=None, help: InstallHelp = None) -> TextResultDialog:
    if text and not error:
        copy_text(text)
    dlg = TextResultDialog(text, error, parent, help)
    if text and not error:
        QTimer.singleShot(150, lambda: toast(dlg))
    # у окна нет рамки системы: ставим по центру родителя (или экрана), иначе оно прижмётся к углу
    area = (parent.frameGeometry() if parent is not None and parent.isVisible()
            else _screen_for(parent).availableGeometry())
    dlg.move(area.center().x() - dlg.width() // 2, area.center().y() - dlg.height() // 2)
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    return dlg
