# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Перевод текста с картинки, как в переводчике с камеры: язык определяется сам, перевод ложится поверх текста.

Сервисы (только официальные открытые API):
  MyMemory (по умолчанию): без регистрации, около 5000 знаков в день; с почтой в настройках до 50 000.
                           За один запрос не больше 500 байт, поэтому длинный текст режется по предложениям.
  Google Cloud Translation: нужен ключ Google Cloud, 500 000 знаков каждый месяц бесплатно (Google требует
                            привязать карту для проверки; в пределах бесплатного объёма деньги не списываются).
Текст для перевода уходит в выбранный сервис через интернет.
"""

import html
import json
import os
import re
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PyQt6.QtCore import QRectF, QThread, pyqtSignal
from PyQt6.QtGui import QImage

from . import __version__, ocr, tls
from .i18n import tr

TIMEOUT = 20
USER_AGENT = f"ClipSD/{__version__} (screenshot tool; https://clipsd.github.io/)"
MYMEMORY_URL = "https://api.mymemory.translated.net/get"
MYMEMORY_MAX_BYTES = 450   # у MyMemory предел 500 байт на запрос, запас на кодирование
GOOGLE_URL = "https://translation.googleapis.com/language/translate/v2"
GOOGLE_LIMIT = 500000   # бесплатно каждый месяц (Basic и Advanced вместе), дальше 20 $ за миллион знаков
# Шаги подключения Google Cloud: (ключ «что сделать», ключ кнопки, ссылка); текст: tr() при показе
GOOGLE_STEPS = (
    ("translate.google_step1",
     "translate.google_step1_button", "https://console.cloud.google.com/projectcreate"),
    ("translate.google_step2", "translate.google_step2_button", "https://console.cloud.google.com/billing"),
    ("translate.google_step3",
     "translate.google_step3_button", "https://console.cloud.google.com/apis/library/translate.googleapis.com"),
    ("translate.google_step4", "translate.google_step4_button", "https://console.cloud.google.com/apis/credentials"),
)


class _Engines:
    """Сервисы перевода [(код, подпись)]: подпись переводится при каждом обходе (язык меняется во время работы)."""
    _rows = (("mymemory", "translate.engine_mymemory"), ("google", "translate.engine_google"))

    def __iter__(self):
        return iter([(code, tr(key)) for code, key in self._rows])

    def __len__(self):
        return len(self._rows)

    def __getitem__(self, i):
        return list(self)[i]


ENGINES = _Engines()


class _LangNames:
    """Названия языков перевода на языке интерфейса ({код: название}), tr() при каждом обращении."""
    _codes = ("ru", "en", "bg", "de", "fr", "es", "it", "uk", "pl", "tr", "el", "ro", "sr", "pt", "nl", "cs", "zh", "ja",
              "ko", "ar")

    def __getitem__(self, code):
        if code not in self._codes:
            raise KeyError(code)
        return tr(f"translate.lang_{code}")

    def __contains__(self, code):
        return code in self._codes

    def __iter__(self):
        return iter(self._codes)

    def __len__(self):
        return len(self._codes)

    def get(self, code, default=None):
        return self[code] if code in self._codes else default

    def keys(self):
        return list(self._codes)

    def items(self):
        return [(c, self[c]) for c in self._codes]

    def values(self):
        return [self[c] for c in self._codes]


LANG_NAMES = _LangNames()
TARGETS = ("ru", "en", "bg", "de", "fr", "es", "it", "uk", "pl", "tr", "el", "ro", "sr", "pt", "nl", "cs", "zh", "ja",
           "ko", "ar")


def system_lang(cfg: dict = None) -> str:
    """Язык перевода «auto»: язык интерфейса ClipSD (1.31). Установки 1.x без поля language (в config помечены
    translate_auto_system) сохраняют прежнее поведение: язык системы."""
    if (cfg or {}).get("translate_auto_system"):
        from PyQt6.QtCore import QLocale
        code = (QLocale.system().name() or "").split("_")[0].lower()
    else:
        from .i18n import current
        code = current()
    return code if code in LANG_NAMES else "en"


def auto_label(cfg: dict = None) -> str:
    """Подпись пункта «auto» в списке языков перевода: «Как язык программы (…)», у старых установок «Как в системе (…)»."""
    key = "translate_ui.lang_auto" if (cfg or {}).get("translate_auto_system") else "translate_ui.lang_auto_ui"
    return tr(key, lang=LANG_NAMES[system_lang(cfg)])


def target_lang(cfg: dict) -> str:
    """На какой язык переводить: «auto» (по умолчанию) — язык программы (у старых установок язык системы), иначе выбранный."""
    t = (cfg or {}).get("translate_to", "auto")
    return system_lang(cfg) if t in (None, "", "auto") else t


def alt_lang(cfg: dict, target: str) -> str:
    """Запасной язык (текст уже на целевом): из настроек, но не совпадающий с целевым."""
    alt = (cfg or {}).get("translate_alt", "en") or "en"
    return alt if alt != target else ("ru" if target != "ru" else "en")

# Языки распознавания для перевода: все установленные из этого списка (Tesseract). Без них, например,
# немецкие умлауты и болгарские буквы читаются с ошибками.
OCR_LANGS = ("eng", "rus", "bul", "deu", "fra", "spa", "ita", "ukr", "pol", "tur", "ell", "ron", "srp", "por", "nld", "ces", "chi_sim")
OCR_EXTRA_COMMAND = ("sudo apt install tesseract-ocr-bul tesseract-ocr-deu tesseract-ocr-fra tesseract-ocr-spa "
                     "tesseract-ocr-ita tesseract-ocr-ukr")


class TranslateError(Exception):
    """Понятная человеку причина, почему перевода нет; help — инструкция, как это исправить (или None).

    Текст: либо готовая строка message, либо ключ каталога key с полями; tr() вызывается при показе (str(e)).
    wait: (часы, минуты) до обновления лимита, отдельным полем, чтобы не разбирать текст."""

    def __init__(self, message: str = "", help=None, key: str = "", wait=None, **fields):
        super().__init__(message or key)
        self.message, self.help, self.key, self.fields, self.wait_hm = message, help, key, fields, wait

    @property
    def wait(self) -> str:
        """Через сколько обновится лимит, на языке интерфейса («9 ч 47 мин»), или пустая строка."""
        return wait_text(self.wait_hm)

    def __str__(self):
        if self.key:
            return tr(self.key, **self.fields, **({"wait": self.wait} if self.wait_hm else {}))
        return self.message


def wait_text(hm) -> str:
    return tr("translate.wait_hm", h=hm[0], m=hm[1]) if hm else ""


class QuotaError(TranslateError):
    """У сервиса кончился лимит или он просит подождать: можно попробовать второй сервис."""


class KeyMissing(TranslateError):
    """Сервису нужен ключ, а его нет или он не принят."""


class SetupNeeded:
    """Метка ошибки «нужно подключить Google»: карточка покажет «Подключить Google…» и «Перевести через MyMemory»."""
    command = None
    url = "https://console.cloud.google.com/apis/credentials"
    service = "google"

    @property
    def title(self):
        return tr("translate.setup_title")

    @property
    def what(self):
        return tr("translate.setup_what")


def google_setup_needed():
    return SetupNeeded()


class EmailNeeded:
    """Метка «лимит MyMemory без почты исчерпан или почта не принята»: карточка предложит указать почту.
    wait_hm: (часы, минуты) до обновления лимита, если MyMemory сообщил; wait: то же текстом."""
    command = None
    url = None
    service = "mymemory_email"

    def __init__(self, wait=None):
        self.wait_hm = wait

    @property
    def wait(self) -> str:
        return wait_text(self.wait_hm)

    @property
    def title(self):
        return tr("translate.email_title")

    @property
    def what(self):
        return tr("translate.email_what")


def looks_like_email(text: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]{2,}", (text or "").strip()))


def lang_name(code: str) -> str:
    code = (code or "").lower()
    return LANG_NAMES.get(code, code.upper() or "?")


def _norm(code: str) -> str:
    return (code or "").split("-")[0].split("_")[0].lower()


def ocr_langs_for_translation() -> str:
    """Все установленные в Tesseract языки из списка OCR_LANGS. Нет Tesseract (Windows, встроенное распознавание)
    или нет ни одного языка: «auto», то есть язык интерфейса + английский (1.31; раньше всегда rus+eng)."""
    exe = ocr.find_tesseract()
    if not exe:
        return ocr.default_langs()
    have = ocr.tesseract_langs(exe)
    use = [lang for lang in OCR_LANGS if lang in have]
    return "+".join(use) or ocr.default_langs()


def missing_ocr_langs() -> list:
    exe = ocr.find_tesseract()
    if not exe:
        return []
    have = ocr.tesseract_langs(exe)
    return [lang for lang in ("bul", "deu", "fra", "spa", "ita", "ukr") if lang not in have]


# --- нарезка текста -------------------------------------------------------------

def split_chunks(text: str, max_bytes: int = MYMEMORY_MAX_BYTES):
    """Куски не длиннее max_bytes (UTF-8) по границам предложений: [(кусок, разделитель после него)].
    Переносы строк сохраняются: перевод собирается обратно с теми же разделителями."""
    out = []
    parts = re.split(r"(\n+)", text)
    for i in range(0, len(parts), 2):
        para = parts[i]
        sep = parts[i + 1] if i + 1 < len(parts) else ""
        cur, chunks = "", []
        for sentence in (x for x in re.split(r"(?<=[.!?…;:])\s+", para) if x.strip()):
            for piece in _split_long(sentence, max_bytes):
                cand = cur + " " + piece if cur else piece
                if cur and len(cand.encode("utf-8")) > max_bytes:
                    chunks.append(cur)
                    cur = piece
                else:
                    cur = cand
        if cur:
            chunks.append(cur)
        for j, chunk in enumerate(chunks):
            out.append((chunk, " " if j < len(chunks) - 1 else sep))
        if not chunks and sep and out:
            out[-1] = (out[-1][0], out[-1][1] + sep)
    return out


def _split_long(piece: str, max_bytes: int):
    if len(piece.encode("utf-8")) <= max_bytes:
        return [piece]
    words, chunks, cur = piece.split(" "), [], ""
    for w in words:
        cand = (cur + " " + w) if cur else w
        if cur and len(cand.encode("utf-8")) > max_bytes:
            chunks.append(cur)
            cur = w
        else:
            cur = cand
    if cur:
        chunks.append(cur)
    return chunks


# --- сервисы ------------------------------------------------------------------

def _http(url, data=None, headers=None, on_error=None):
    """JSON-ответ сервиса. Ошибка HTTP: on_error(код, тело) даёт понятную причину (или общая)."""
    req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=tls.context()) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", "replace")
        except Exception:   # noqa: BLE001
            pass
        raise (on_error or _http_message)(exc.code, body) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise TranslateError(key="translate.err_no_connection") from None
    except ValueError:
        raise TranslateError(key="translate.err_bad_answer") from None


def _http_message(code, body):
    if code == 429:
        return QuotaError(key="translate.err_too_many")
    return TranslateError(key="translate.err_code", code=code)


def _google_error(code, body):
    """Ответ Google Cloud с ошибкой: что именно не так с ключом или проектом."""
    try:
        msg = json.loads(body).get("error", {}).get("message", "")
    except ValueError:
        msg = ""
    low = msg.lower()
    if "api key not valid" in low or "api_key_invalid" in low or code == 401:
        return KeyMissing(help=google_setup_needed(), key="translate.err_google_bad_key")
    if "billing" in low:
        return KeyMissing(help=google_setup_needed(), key="translate.err_google_billing")
    if "has not been used" in low or "disabled" in low or "not been enabled" in low:
        return KeyMissing(help=google_setup_needed(), key="translate.err_google_api_off")
    if code == 403 and ("quota" in low or "limit" in low):
        return QuotaError(key="translate.err_google_quota")
    if code == 403:
        return KeyMissing(help=google_setup_needed(), key="translate.err_google_denied", detail=msg) if msg else \
            KeyMissing(help=google_setup_needed(), key="translate.err_google_denied_check")
    if code == 429:
        return QuotaError(key="translate.err_google_too_many")
    return TranslateError(key="translate.err_google_code_detail", code=code, detail=msg) if msg else \
        TranslateError(key="translate.err_google_code", code=code)


class MyMemory:
    name = "MyMemory"

    def __init__(self, email: str = ""):
        self.email = email.strip()

    def _quota(self, wait=None):
        """wait: (часы, минуты) до обновления лимита или None."""
        if self.email:
            return QuotaError(key="translate.err_mm_quota_email_wait" if wait else "translate.err_mm_quota_email", wait=wait)
        return QuotaError(help=EmailNeeded(wait), key="translate.err_mm_quota_wait" if wait else "translate.err_mm_quota",
                          wait=wait)

    def _http_error(self, code, body):
        """MyMemory сообщает об исчерпанном дневном лимите кодом 429 с текстом «YOU USED ALL AVAILABLE FREE
        TRANSLATIONS FOR TODAY. NEXT AVAILABLE IN 09 HOURS 47 MINUTES»: это лимит, а не временная перегрузка."""
        up = (body or "").upper()
        if "INVALID EMAIL" in up:
            return KeyMissing(help=EmailNeeded(), key="translate.err_mm_bad_email")
        if code == 429 or "ALL AVAILABLE FREE TRANSLATIONS" in up:
            m = re.search(r"NEXT AVAILABLE IN\s+(\d+)\s+HOURS?\s+(\d+)\s+MINUTES?", up)
            return self._quota((int(m.group(1)), int(m.group(2))) if m else None)
        return _http_message(code, body)

    def _one(self, text, source, target):
        params = {"q": text, "langpair": f"{source or 'autodetect'}|{target}"}
        if self.email:
            params["de"] = self.email
        data = _http(MYMEMORY_URL + "?" + urllib.parse.urlencode(params), on_error=self._http_error)
        add_mymemory_chars(len(text))
        status = int(data.get("responseStatus") or 0)
        rd = data.get("responseData") or {}
        out = html.unescape(rd.get("translatedText") or "")
        if "DISTINCT LANGUAGES" in str(data.get("responseDetails", "")).upper():
            return text, target   # текст уже на целевом языке: вызывающий переведёт на запасной
        if "INVALID EMAIL" in str(data.get("responseDetails", "")).upper() or "INVALID EMAIL" in out.upper():
            raise KeyMissing(help=EmailNeeded(), key="translate.err_mm_bad_email")
        if status != 200 or data.get("quotaFinished") or "MYMEMORY WARNING" in out:
            if data.get("quotaFinished") or "MYMEMORY WARNING" in out or status == 429:
                raise self._http_error(429, out)
            raise TranslateError(key="translate.err_mm_failed", detail=data.get('responseDetails') or status)
        return out, _norm(rd.get("detectedLanguage") or source or "")

    def translate(self, text: str, target: str, source: str = None):
        """(перевод, язык оригинала)."""
        detected = source
        out = []
        for chunk, sep in split_chunks(text):
            if not chunk.strip():
                out.append(chunk + sep)
                continue
            tr, src = self._one(chunk, detected, target)
            detected = detected or src or None
            out.append(tr + sep)
        return "".join(out).strip(), _norm(detected or "")


class GoogleCloud:
    """Google Cloud Translation (Basic, v2): ключ проекта Google Cloud, 500 000 знаков в месяц бесплатно."""
    name = "Google"

    def __init__(self, key: str):
        self.key = key.strip()

    def translate(self, text: str, target: str, source: str = None):
        if not self.key:
            raise KeyMissing(help=google_setup_needed(), key="translate.err_google_not_connected")
        form = [("q", text), ("target", target), ("format", "text")]
        if source:
            form.append(("source", source))
        data = _http(GOOGLE_URL + "?" + urllib.parse.urlencode({"key": self.key}),
                     data=urllib.parse.urlencode(form).encode(),
                     headers={"Content-Type": "application/x-www-form-urlencoded"}, on_error=_google_error)
        add_google_chars(len(text))
        item = ((data.get("data") or {}).get("translations") or [{}])[0]
        src = _norm(item.get("detectedSourceLanguage") or source or "")
        out = html.unescape(item.get("translatedText", ""))
        return out, src


def looks_like_google_key(text: str) -> bool:
    """Похоже на ключ Google Cloud: «AIza» и ещё 35 букв, цифр, «-» или «_»."""
    return bool(re.fullmatch(r"AIza[0-9A-Za-z_\-]{35}", text.strip()))


def config_dir() -> Path:
    """Та же папка, что у config.json (clipshot/paths.py): готовая сборка ~/.config/clipsd, исходники ~/.config/clipshot.
    Windows: %APPDATA%\\ClipSD, как и в 1.x."""
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", "")) / "ClipSD"
    from . import paths
    return paths.config_dir()


def google_key_path() -> Path:
    return config_dir() / "google-translate.key"


def load_google_key() -> str:
    """Ключ Google из файла настроек ClipSD (его пишет окно «Подключить Google…»). Других мест программа не читает."""
    try:
        return google_key_path().read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def save_google_key(key: str):
    path = google_key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not key.strip():
        try:
            path.unlink()
        except OSError:
            pass
        return
    path.write_text(key.strip() + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)   # ключ читает только владелец
    except OSError:
        pass


# --- расход лимитов ------------------------------------------------------------------
# Ни MyMemory, ни ключ Google не дают справки о расходе: ClipSD считает отправленные знаки сам (MyMemory за день,
# Google за месяц). Число примерное: тем же лимитом могут пользоваться и другие программы.

MYMEMORY_LIMIT, MYMEMORY_LIMIT_EMAIL = 5000, 50000


def usage_path() -> Path:
    return config_dir() / "translate-usage.json"


def _month() -> str:
    return _today()[:7]


def add_google_chars(n: int):
    data = _load_usage()
    g = data.get("google", {})
    if g.get("month") != _month():
        g = {"month": _month(), "chars": 0}
    g["chars"] = int(g.get("chars", 0)) + int(n)
    data["google"] = g
    _save_usage(data)


def google_usage():
    """(отправлено в этом месяце, бесплатный лимит) по подсчёту ClipSD."""
    g = _load_usage().get("google", {})
    return (int(g.get("chars", 0)) if g.get("month") == _month() else 0), GOOGLE_LIMIT


def _save_usage(data: dict):
    try:
        usage_path().parent.mkdir(parents=True, exist_ok=True)
        usage_path().write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


def _today() -> str:
    import datetime
    return datetime.date.today().isoformat()


def _load_usage() -> dict:
    try:
        return json.loads(usage_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def add_mymemory_chars(n: int):
    data = _load_usage()
    mm = data.get("mymemory", {})
    if mm.get("date") != _today():
        mm = {"date": _today(), "chars": 0}
    mm["chars"] = int(mm.get("chars", 0)) + int(n)
    data["mymemory"] = mm
    _save_usage(data)


def mymemory_usage(email: str = ""):
    """(отправлено сегодня, дневной лимит) по подсчёту ClipSD."""
    mm = _load_usage().get("mymemory", {})
    used = int(mm.get("chars", 0)) if mm.get("date") == _today() else 0
    return used, MYMEMORY_LIMIT_EMAIL if email.strip() else MYMEMORY_LIMIT


def _n(x: int) -> str:
    from .i18n import number
    return number(x)   # по правилам языка интерфейса (ru: «50 000», de: «50.000»)


def usage_line(cfg: dict, engine: str = None) -> str:
    """Строка расхода для выбранного сервиса: сколько использовано и сколько осталось."""
    engine = engine or cfg.get("translate_engine", "mymemory")
    if engine == "google":
        if not load_google_key():
            return tr("translate.usage_google_off")
        used, limit = google_usage()
        return tr("translate.usage_google", used=_n(used), limit=_n(limit), left=_n(max(0, limit - used)))
    email = cfg.get("translate_email", "")
    used, limit = mymemory_usage(email)
    return tr("translate.usage_mm_email" if email.strip() else "translate.usage_mm", used=_n(used), limit=_n(limit),
              left=_n(max(0, limit - used)))


def shortfall(cfg: dict, need: int):
    """Не хватит ли знаков на перевод в `need` знаков: None, если хватит или есть второй сервис, который подхватит;
    иначе сколько знаков осталось по подсчёту ClipSD. Второй сервис есть, если основной Google (запасной MyMemory
    не требует ключа) или основной MyMemory, а ключ Google подключён."""
    google_ready = bool(load_google_key())
    if cfg.get("translate_engine") == "google" and google_ready:
        return None   # основной Google; при нехватке его лимита запасным пойдёт MyMemory
    if google_ready:
        return None   # основной MyMemory, но второй сервис (Google) подключён
    used, limit = mymemory_usage(cfg.get("translate_email", ""))
    left = max(0, limit - used)
    return left if need > left else None


def usage_short(cfg: dict, engine: str = None) -> str:
    """Короткая строка расхода для полосы режима перевода: сколько осталось. Полный текст: usage_line."""
    engine = engine or cfg.get("translate_engine", "mymemory")
    if engine == "google":
        if not load_google_key():
            return tr("translate.usage_short_google_off")
        used, limit = google_usage()
        return tr("translate.usage_short_google", left=_n(max(0, limit - used)))
    used, limit = mymemory_usage(cfg.get("translate_email", ""))
    return tr("translate.usage_short_mm", left=_n(max(0, limit - used)))


class KeyCheckJob(QThread):
    """Проверка ключа Google в фоне коротким переводом: done(ошибка или пустая строка)."""
    done = pyqtSignal(str)

    def __init__(self, key: str, parent=None):
        super().__init__(parent)
        self.key = key

    def run(self):
        try:
            GoogleCloud(self.key).translate("Hello", "ru")
            self.done.emit("")
        except TranslateError as exc:
            self.done.emit(str(exc))


class EmailCheckJob(QThread):
    """Проверка почты для MyMemory в фоне пробным переводом: done(ошибка или пустая строка)."""
    done = pyqtSignal(str)

    def __init__(self, email: str, parent=None):
        super().__init__(parent)
        self.email = email

    def run(self):
        try:
            MyMemory(self.email)._one("Hello", "en", "ru")
            self.done.emit("")
        except TranslateError as exc:
            self.done.emit(str(exc))


def check_mymemory_email(email: str, on_done):
    job = EmailCheckJob(email)
    _jobs.append(job)

    def finished(error):
        on_done(error)
    job.done.connect(finished)
    job.finished.connect(lambda: _forget(job))   # поток удаляется, только когда run() вернулся (иначе «QThread: Destroyed while thread is still running»)
    job.start()
    return job


def check_google_key(key: str, on_done):
    job = KeyCheckJob(key)
    _jobs.append(job)

    def finished(error):
        on_done(error)
    job.done.connect(finished)
    job.finished.connect(lambda: _forget(job))   # поток удаляется, только когда run() вернулся (иначе «QThread: Destroyed while thread is still running»)
    job.start()
    return job


def engines_from_config(cfg: dict) -> list:
    """Основной сервис из настроек, второй как запасной (на случай лимита или если Google не подключён)."""
    mm, gc = MyMemory(cfg.get("translate_email", "")), GoogleCloud(load_google_key())
    return [gc, mm] if cfg.get("translate_engine") == "google" else [mm, gc]


def engine_from_config(cfg: dict):
    return engines_from_config(cfg)[0]


def translate_text(text: str, cfg: dict, engines=None):
    """(перевод, язык оригинала, язык перевода, сервис). Текст уже на целевом языке: переводится на запасной.
    engines — список сервисов по порядку; кончился лимит или нет ключа: сервис убирается из списка, пробуется
    следующий. Не сработал ни один: последняя ошибка (с инструкцией по ключу, если её можно дать)."""
    if engines is None:
        engines = engines_from_config(cfg)
    elif not isinstance(engines, list):
        engines = [engines]
    target = target_lang(cfg)
    alt = alt_lang(cfg, target)
    errors = []
    while engines:
        engine = engines[0]
        try:
            tr, src = engine.translate(text, target)
            if src and src == target and alt and alt != target:
                tr, _ = engine.translate(text, alt, source=src)
                return tr, src, alt, engine.name
            return tr, src, target, engine.name
        except (QuotaError, KeyMissing) as exc:
            errors.append(exc)
            engines.pop(0)
    quota = [e for e in errors if isinstance(e, QuotaError)]
    keys = [e for e in errors if isinstance(e, KeyMissing)]
    email = next((e for e in errors if isinstance(e.help, EmailNeeded)), None)
    if email is not None:
        raise TranslateError(email.message, email.help, email.key, email.wait_hm, **email.fields)   # проще всего указать почту: это и предлагаем первым
    if quota and keys:
        raise TranslateError(help=keys[0].help, key="translate.err_quota_and_key", quota=quota[0], keyerr=keys[0])
    raise errors[-1] if errors else TranslateError(key="translate.err_no_engine")


# --- блоки текста на картинке -----------------------------------------------------

def blocks_from_words(words):
    """Слова (ocr.layout) в блоки: [(рамка блока, текст, высота строки)]. Строки абзаца склеиваются пробелом, чтобы переводчик
    видел предложение целиком; короткая строка или строка с точкой в конце заканчивает абзац."""
    groups = {}
    order = []
    for w in words:
        key = w.line[0] if isinstance(w.line, tuple) else w.line
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(w)
    # Абзац: соседние блоки одного столбца с обычным межстрочным промежутком переводятся вместе,
    # чтобы предложение, перенесённое на следующую строку, не резалось. Пункты списка с большим промежутком
    # остаются отдельными.
    merged = []
    for key in order:
        ws = groups[key]
        if merged:
            prev = merged[-1]
            h = sorted(w.rect.height() for w in prev)[len(prev) // 2]
            p_left, p_bottom = min(w.rect.left() for w in prev), max(w.rect.bottom() for w in prev)
            c_left, c_top = min(w.rect.left() for w in ws), min(w.rect.top() for w in ws)
            if 0 <= c_top - p_bottom < 0.8 * h and abs(c_left - p_left) < 1.5 * h:
                merged[-1] = prev + ws
                continue
        merged.append(list(ws))
    out = []
    for ws in merged:
        rect = QRectF(ws[0].rect)
        for w in ws[1:]:
            rect = rect.united(w.rect)
        lines = []
        for w in ws:
            if lines and lines[-1][0] == w.line:
                lines[-1][1].append(w)
            else:
                lines.append((w.line, [w]))
        text = ""
        for i, (_k, lws) in enumerate(lines):
            line_text = " ".join(w.text for w in lws)
            if i:
                prev_text = " ".join(w.text for w in lines[i - 1][1])
                prev_right = max(w.rect.right() for w in lines[i - 1][1])
                short = prev_right < rect.left() + rect.width() * 0.7
                text += "\n" if (re.search(r"[.!?:;]$", prev_text) or short) else " "
            text += line_text
        heights = sorted(w.rect.height() for w in ws)
        out.append((rect, text, heights[len(heights) // 2]))
    return out


# Сообщения о результате (сравниваются в окнах): в модуле хранятся ключи, translate.NO_TEXT и т.п. дают текст
# на языке интерфейса в момент обращения (__getattr__ модуля). Внутри модуля: tr(_MESSAGES[...]).
_MESSAGES = {"NO_TEXT": "translate.no_text", "CANCELLED": "translate.cancelled", "ALREADY": "translate.already_ru",
             "TOO_BIG_FULL": "translate.too_big_full", "EXHAUSTED_SMALL": "translate.exhausted_small"}


def __getattr__(name):
    if name in _MESSAGES:
        return tr(_MESSAGES[name])
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def znak_word(n: int) -> str:
    """«знак» после числа: 1 знак, 2-4 знака, 5-20 знаков, 21 знак, 111 знаков."""
    return tr("translate.chars_word", n=n)


_RU_ALPHABET = set("абвгдеёжзийклмнопрстуфхцчшщъыьэюя")


class ResultList(list):
    """Результаты перевода [{"rect", "orig", "text", …}]; skipped: сколько блоков не отправлялось (уже на русском)."""
    skipped = 0
    total = 0   # блоков к переводу до обрезки по лимиту


_skip_target = "ru"   # язык перевода последнего прогона «весь экран» (для сообщений о пропуске)


def skipped_text(n: int) -> str:
    """Спокойная формулировка про блоки, которые не переводились, потому что уже на языке перевода."""
    if _skip_target == "ru":
        return tr("translate.skipped", n=n)
    return tr("translate.skipped_lang", n=n, lang=lang_name(_skip_target))


def already_text(target: str) -> str:
    """«Перевод не нужен: текст уже на …»: для русского прежняя фраза, для других языков с названием языка."""
    if target == "ru":
        return tr(_MESSAGES["ALREADY"])
    return tr("translate.already_lang", lang=lang_name(target))


def is_already(msg: str) -> bool:
    """Сообщение «текст уже на языке перевода» (любой язык; окна сравнивают по нему)."""
    return bool(msg) and (msg == tr(_MESSAGES["ALREADY"]) or msg == already_text(_skip_target))


# Служебные слова для «уже на языке перевода» (латиница). Слова, общие для нескольких языков (de, en, la, a, e, o, i,
# na, is, que, el…), убираются автоматически: считаются только характерные для одного языка. Языки без перевода
# в ClipSD (nl, hr, ca, gl, cs, ro, sv) нужны как соперники: нидерландский не должен сойти за испанский.
_STOPWORDS_ALL = {
    "en": "the and of to in is you that it for on with are this be as at your have from or by not we can will an our has was".split(),
    "de": "der die das und ist nicht sie zu den mit von ein eine ich auf für sich dem des im es auch wir bitte ihr wird dass oder".split(),
    "fr": "le la les et est des une un du que pour dans pas vous sur avec ce qui il nous au sont par votre cette aux merci sera très aussi".split(),
    "es": "el la los las y es de que en un una por para con no se su sus del al lo usted nos como está muy pero este esta estos hay también cuando porque gracias será sí".split(),
    "it": "il lo la gli le e di che un una per non con del della sono è si ci al nel ti questo alla perché grazie tuo tua sarà anche molto degli delle".split(),
    "pt": "o a os as e é de que um uma para com não do da no na por se você em ao pelo obrigado seu sua também será muito".split(),
    "pl": "i w nie się na to jest z do że jak ale co po za od dla są oraz zostanie".split(),
    "tr": "ve bir bu için ile da de ne çok var mı daha gibi olarak sonra kadar ama siz".split(),
    "nl": "de het een en van is dat op te niet voor met zijn wij u uw wordt ook naar".split(),
    "hr": "i na je se za da od su u nije koji što će biti ili kao".split(),
    "ca": "el els les per amb que del una és i la al aquest aquesta també".split(),
    "gl": "o os e é un unha non co coa do da no na para que tamén".split(),
    "cs": "a je se na v že to jsou pro který není".split(),
    "ro": "și este în de la cu nu pe care pentru sunt".split(),
}
_COUNTS = {}
for _words in _STOPWORDS_ALL.values():
    for _w in set(_words):
        _COUNTS[_w] = _COUNTS.get(_w, 0) + 1
_STOPWORDS = {lang: {w for w in words if _COUNTS[w] == 1} for lang, words in _STOPWORDS_ALL.items()}
_NOISE = re.compile(r"(https?://\S+|www\.\S+|\S+@\S+|\S*[/\\]\S*|\S+\.(?:com|org|net|de|ru|html?)\b)", re.I)


def _latin_already(text: str, target: str) -> bool:
    """Латиница: уже на языке перевода, только если характерных слов этого языка много, вдвое больше, чем у любого
    другого, и другого языка почти нет (смешанный абзац переводится). При сомнении: False (уйдёт в сервис)."""
    low = _NOISE.sub(" ", text.lower())   # адреса, почта, пути не считаются словами языка
    if _script_share(low, lambda ch: ch.isascii() or "\u00c0" <= ch <= "\u024f") <= 0.8:
        return False
    words = re.findall(r"[^\W\d_]+", low)
    if len(words) < 5:
        return False
    hits = {lang: sum(1 for w in words if w in stop) for lang, stop in _STOPWORDS.items()}
    mine = hits.pop(target, 0)
    other = max(hits.values()) if hits else 0
    if not (mine >= max(3, len(words) * 0.15) and mine >= 2 * max(other, 1) and other <= 1):
        return False
    # смешанный абзац: короткое предложение другого языка («Click the button now.») тоже уходит в перевод
    for sentence in re.split(r"[.!?;:\n]+", low):
        sw = re.findall(r"[^\W\d_]+", sentence)
        if len(sw) < 3:
            continue
        s_mine = sum(1 for w in sw if w in _STOPWORDS.get(target, ()))
        for lang, stop in _STOPWORDS.items():
            found = [w for w in sw if w in stop]
            # одно двухбуквенное слово («si») ещё не язык: нужно два слова или одно подлиннее («the»)
            if lang != target and len(found) > s_mine and (len(found) >= 2 or len(found[0]) >= 3):
                return False
    return True


def _script_share(text: str, test) -> float:
    letters = [ch for ch in text if ch.isalpha()]
    return sum(1 for ch in letters if test(ch)) / len(letters) if letters else 0.0


_LATIN_STOP = {w for words in _STOPWORDS_ALL.values() for w in words if len(w) > 1}
_UK_STOP = set("що це щоб від але або цей ця ці ще вже лише тільки дуже також немає є як які який яка мені тобі вона він".split())
_RU_STOP = set("что это как он она они был была если или нет так только уже очень также чтобы когда его её".split())
_BG_HARD_SIGN = re.compile(r"ъ(?=[бвгджзйклмнпрстфхцчшщ])")   # болгарское «ъ» перед согласной: път, къща, България


def _latin_sentence(text: str) -> bool:
    """В тексте другой письменности есть предложение латиницей (три слова и больше, среди них служебное слово
    какого-нибудь языка: «Please click the button»). Названия вроде «Microsoft Windows Server» не считаются."""
    words = re.findall(r"[A-Za-z\u00c0-\u024f]{2,}", _NOISE.sub(" ", text))
    return len(words) >= 3 and any(w.lower() in _LATIN_STOP for w in words)


def _foreign_script_words(text: str) -> int:
    """Слова из двух и больше букв не латиницей (кириллица, иероглифы, греческий…) в латинском тексте."""
    return len([w for w in re.findall(r"[^\W\d_]{2,}", text)
                if not all(ch.isascii() or "\u00c0" <= ch <= "\u024f" for ch in w)])


def _uk_already(low: str) -> bool:
    """Украинский: слов с і ї є ґ и украинских служебных заметно больше, чем русских; одно украинское слово
    в русской строке её украинской не делает."""
    words = re.findall(r"[^\W\d_]+", low)
    if not words:
        return False
    uk = sum(1 for w in words if any(ch in w for ch in "іїєґ") or w in _UK_STOP)
    ru = sum(1 for w in words if w in _RU_STOP)
    if not uk or uk < 2 * ru:
        return False
    if len(words) <= 3:
        return True
    return uk >= 2 and uk >= 0.2 * len(words)


def already_in_target(text: str, target: str) -> bool:
    """Блок уже на языке перевода, и отправлять его в сервис не нужно. Русский: подробная проверка ниже.
    Украинский и болгарский: кириллица со своими буквами. Китайский: иероглифы без японской каны.
    Языки на латинице: доля служебных слов этого языка заметна и больше, чем у других. Сомнение: блок уходит в сервис."""
    if target in ("ru", "uk", "bg", "zh") and _latin_sentence(text):
        return False   # смешанный абзац: короткое предложение латиницей тоже надо перевести
    if target == "ru":
        return _already_ru(text)
    cyr = lambda ch: "\u0400" <= ch <= "\u052f"   # noqa: E731
    low = text.lower()
    if target in ("uk", "bg"):
        if _script_share(text, cyr) <= 0.5 or any(ch in low for ch in "ыэё"):
            return False
        if target == "uk":
            return _uk_already(low)
        # «ъ» только перед е, ё, ю, я бывает и в русском (объявление, съезд): болгарским считается «ъ» перед согласной
        return not any(ch in low for ch in "іїєґўјљњћђџ") and (bool(_BG_HARD_SIGN.search(low)) or bool(re.search(r"\b(ще|със|са|който|която|които|това|тези|някой)\b", low)))
    if target == "zh":
        # китайский: иероглифы без японской каны и хотя бы два частых китайских служебных знака
        # (японская надпись только иероглифами их обычно не содержит)
        return (_script_share(text, lambda ch: "\u4e00" <= ch <= "\u9fff") > 0.5
                and not any("\u3040" <= ch <= "\u30ff" for ch in text)
                and sum(text.count(ch) for ch in "的了是在我有和这们您将们吗呢把被给") >= 2)
    if target in ("en", "de", "fr", "es", "it", "pt", "pl", "tr"):
        return _foreign_script_words(text) == 0 and _latin_already(text, target)
    return False


def _already_ru(text: str, target: str = "ru") -> bool:
    """Блок уже по-русски, и переводить его не нужно. Только для перевода на русский и только если выполнено всё сразу:
    больше половины букв кириллица; все кириллические буквы из русского алфавита (без і ї є ґ ў ј љ њ ћ ђ џ и других);
    есть хотя бы одна из ы, э, ё (по ним русский отличается от болгарского и сербского); «ъ» только перед е, ё, ю, я
    (объём, съезд): «ъ» в конце слова или перед другой буквой это болгарский (България, път, къща).
    Иначе блок уходит в сервис: лучше потратить несколько знаков, чем не перевести болгарский. Короткие русские надписи
    без ы, э, ё («Корзина») тоже уходят в сервис: это осознанная цена."""
    if target != "ru":
        return False
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return False
    cyr = [ch.lower() for ch in letters if "\u0400" <= ch <= "\u052f"]
    if len(cyr) * 2 <= len(letters):
        return False
    if any(ch not in _RU_ALPHABET for ch in cyr):
        return False
    if not any(ch in "ыэё" for ch in cyr):
        return False
    low = text.lower()
    for i, ch in enumerate(low):
        if ch == "ъ" and (low[i + 1:i + 2] not in tuple("еёюя")):
            return False
    return True


def fit_blocks(blocks, left: int):
    """Блоки по порядку, которые вместе укладываются в `left` знаков («Перевести, сколько хватит»)."""
    out, total = [], 0
    for b in blocks:
        n = len(b[1])
        if total + n <= left:
            out.append(b)
            total += n
    return out


class TranslateJob(QThread):
    """Распознать кусок снимка и перевести каждый блок. done(результаты, ошибка): результаты —
    [{"rect": QRectF в пикселях куска, "orig": текст, "text": перевод, "src": язык, "tgt": язык}].
    Большой текст (весь экран): если знаков больше, чем осталось у сервиса, а второго сервиса нет, до отправки
    приходит сигнал ask(нужно, осталось); ответ даёт answer(True: «сколько хватит», False: «Отмена»)."""
    done = pyqtSignal(list, str)
    ask = pyqtSignal(int, int)
    ASK_WAIT = 600   # секунд: столько ждём ответа человека, потом считаем отменой

    def __init__(self, image: QImage, cfg: dict, parent=None, check_limit=False, full=False):
        super().__init__(parent)
        self.full = full
        self.skipped = 0   # сколько блоков не отправлялось (уже на русском)
        self.total = 0     # блоков к переводу до обрезки по лимиту
        self.image = image.copy()
        self.cfg = dict(cfg)
        self.help = None
        self.quota = ""   # 1.32: кончился лимит сервиса: код сообщения для колокольчика редактора (notifications)
        self.check_limit = check_limit
        self.cancelled = False
        self._reply = None
        self._event = threading.Event()

    def answer(self, partial: bool):
        self._reply = bool(partial)
        self._event.set()

    def cancel(self):
        """Окно закрыто или нажали Esc: дальше в сеть не ходим, ответа человека не ждём."""
        self.cancelled = True
        self._event.set()

    def run(self):
        try:
            words = ocr.recognize_words(self.image, ocr_langs_for_translation(), self.cfg.get("ocr_quality", "accurate"))
            blocks = blocks_from_words(words)
            if self.cancelled:
                self.done.emit([], tr(_MESSAGES["CANCELLED"]))
                return
            if not blocks:
                self.done.emit([], tr(_MESSAGES["NO_TEXT"]))
                return
            if self.full:
                # весь экран: блоки, уже написанные на языке перевода, не отправляются (и в расход не идут)
                target = target_lang(self.cfg)
                global _skip_target
                _skip_target = target
                kept = [b for b in blocks if not already_in_target(b[1], target)]
                self.skipped = len(blocks) - len(kept)
                if not kept:
                    self.done.emit([], already_text(target))
                    return
                blocks = kept
            self.total = len(blocks)
            need = sum(len(b[1]) for b in blocks)
            left = shortfall(self.cfg, need) if self.check_limit else None
            if left == 0:
                # лимит на сегодня исчерпан: вопрос не нужен, сразу то же окно про почту или «обновится завтра»
                email = self.cfg.get("translate_email", "")
                self.quota = "translate_quota"
                if email.strip():
                    self.done.emit([], tr("translate.err_mm_quota_tomorrow"))
                else:
                    self.help = EmailNeeded()
                    self.done.emit([], tr("translate.err_free_over"))
                return
            if left is not None:
                self._reply = None
                self.ask.emit(need, left)
                self._event.wait(self.ASK_WAIT)
                if self.cancelled or not self._reply:
                    self.done.emit([], tr(_MESSAGES["CANCELLED"]))   # «Отмена»: в сеть не ушло ни одного знака
                    return
                blocks = fit_blocks(blocks, left)
                if not blocks:   # ни один абзац не влезает: в сервис не уходит ничего
                    self.done.emit([], tr(_MESSAGES["EXHAUSTED_SMALL"]))
                    return
            engines = engines_from_config(self.cfg)
            results = []
            for rect, text, line_h in blocks:
                if self.cancelled:
                    self.done.emit([], tr(_MESSAGES["CANCELLED"]))
                    return
                out, src, tgt, used = translate_text(text, self.cfg, engines)
                results.append({"rect": rect, "orig": text, "text": out, "src": src, "tgt": tgt,
                                "line_h": line_h, "engine": used})
            self.done.emit(results, "")
        except ocr.OcrError as exc:
            self.help = exc.help
            msg = str(exc)
            if self.full and (getattr(exc, "key", "") == "ocr.err_timeout" or "слишком долго" in msg):
                msg = tr(_MESSAGES["TOO_BIG_FULL"])
            self.done.emit([], msg)
        except TranslateError as exc:
            self.help = exc.help
            key = getattr(exc, "key", "") or ""
            if isinstance(exc.help, EmailNeeded) or key.startswith("translate.err_mm_quota") \
                    or key == "translate.err_quota_and_key":
                self.quota = "translate_quota"
            elif key == "translate.err_google_quota":
                self.quota = "translate_quota_month"
            self.done.emit([], str(exc))
        except Exception as exc:   # noqa: BLE001 — любая неожиданность должна дойти до человека
            self.done.emit([], tr("translate.err_unexpected", error=exc))


_jobs = []


def _forget(job):
    """После выхода из run() (сигнал finished): убрать из живых заданий и удалить. Раньше, по сигналу done из run(),
    ссылка пропадала, пока поток ещё работал: «QThread: Destroyed while thread is still running»."""
    if job in _jobs:
        _jobs.remove(job)
    job.deleteLater()


def start(image: QImage, cfg: dict, on_done, confirm=None, full=False):
    """Запустить перевод картинки. confirm(нужно, осталось, job): окно с вопросом «сколько хватит или отмена»,
    вызывается в потоке окна, только когда текста больше остатка и второго сервиса нет; None: не спрашивать."""
    job = TranslateJob(image, cfg, check_limit=confirm is not None, full=full or confirm is not None)
    if confirm is not None:
        def ask(need, left):
            try:
                confirm(need, left, job)
            except RuntimeError:   # неожиданное исключение: в журнал, а поток не оставляем ждать ответа
                import sys
                sys.excepthook(*sys.exc_info())
                job.cancel()
        job.ask.connect(ask)
    _jobs.append(job)

    def finished(results, error):
        res = ResultList(results)
        res.skipped = job.skipped
        res.total = job.total
        if job.quota:   # 1.32: лимит кончился: короткое сообщение в колокольчик редактора (один раз за день)
            from . import notifications
            notifications.post(job.quota)
        # получатель сам проверяет, что его окно не удалено (sip.isdeleted), и пропускает только этот случай
        on_done(res, error, job.help)

    job.done.connect(finished)
    job.finished.connect(lambda: _forget(job))   # поток удаляется, только когда run() вернулся (иначе «QThread: Destroyed while thread is still running»)
    job.start()
    return job
