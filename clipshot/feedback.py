# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Окно «Оценить ClipSD» (1.32; спецификация С12, архитектура 4.6, ADR-0004, ADR-0006). Перенесено из ветки 2.0
без «Сообщить о проблеме» через Sentry и без статистики.

Правила показа (чистые функции, время параметром, чтобы тесты его подставляли):
  * окно предлагается само после 7 дней работы И 20 снимков; день работы: календарный день, в который программа
    запускалась или делала снимок; «Позже» и крестик откладывают на 30 дней; не больше 3 показов;
  * «Больше не показывать» и отправленная оценка выключают окно навсегда (пункт меню открывает его всегда);
  * 1-5 звёзд, отзыв до 1000 знаков, без имени и почты (адреса почты в тексте заменяются на <e-mail>).
Отправка: POST RATE_URL {stars, review, lang, version, platform, key, fill_ms}; key: случайный номер ЭТОЙ оценки
(он же заголовок Idempotency-Key, повторы идут с тем же номером, приёмник второй раз не пишет), fill_ms: сколько
окно было открыто. Номера установки нет. Сначала оценка кладётся в очередь на диске (config_dir()/rating-outbox),
потом сразу пробуется отправка; ответ 2xx: «отправлено», 429/5xx/нет сети: ждёт в очереди (попытки при
следующих запусках и раз в час: всего MAX_ATTEMPTS, паузы RETRY_PAUSES), остальные 4xx: приёмник не принял,
повторять бесполезно. «Отправлено» пишется только после 2xx (1.32, П1 проверки: раньше отметка ставилась по кнопке).
После отправки: окно со ссылками на каталоги (список CATALOGS в одном месте, показываются только включённые),
у 1-3 звёзд ещё «Сообщить о проблеме»: страница новой задачи на GitHub с вписанными версией, системой и отзывом.
Сеть только в фоновом потоке, окна её не ждут.
Оценка одна: пока она дошла до приёмника или ждёт в очереди, пункт меню открывает окно «Вы уже оценили ClipSD»
(звёзды и дата этой оценки, ждёт ли она отправки, как изменить или удалить её письмом автору, ссылки на каталоги),
второй записи нет. Если приёмник её не принял или попытки кончились, пункт меню снова открывает окно оценки
(окно «Сервер не принял оценку» так и обещает), а само окно больше не предлагается (rating_disabled).
Номер установки ради этого не заводится: приёмник находит оценку по дате и тексту.
Счётчики в config: usage_days, last_usage_day, capture_count, rating_shown, rating_next_ts, rating_disabled,
rating_sent (только после 2xx); своя оценка для окна «Вы уже оценили»: rating_stars, rating_day (только на этом
компьютере). Оценку, которую отправил фоновый проход очереди, отмечает файл DELIVERED_MARK в папке очереди: config
пишет только главный поток, отметка переносится в него при следующем открытии окна (sync_delivered).
"""
from __future__ import annotations

import html
import json
import os
import platform as _platform
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import date, datetime
from pathlib import Path

from . import __version__
from .i18n import current as current_language, tr

RATE_URL = "https://clipsd-ratings.clipsd.workers.dev/rate"     # Cloudflare Worker clipsd-ratings (ADR-0004)
PRIVACY_URL = "https://clipsd.github.io/{lang}/privacy.html#ratings"
ISSUE_URL = "https://github.com/clipsd/clipsd/issues/new"
SUPPORT_EMAIL = "clipsd.app@gmail.com"   # изменить или удалить отправленную оценку: письмом с датой и текстом
ISSUE_URL_LIMIT = 7_000           # вся строка адреса задачи (GitHub отказывает около 8 КБ)
MAX_REVIEW = 1000                 # знаков (кодовых точек), столько же принимает приёмник
MIN_DAYS, MIN_CAPTURES, LATER_DAYS, MAX_SHOWS = 7, 20, 30, 3
MAX_ATTEMPTS = 3                  # всего попыток отправки одной оценки, первая сразу по кнопке
RETRY_PAUSES = (3600, 86400)      # пауза после 1-й и 2-й неудачи, секунды
MAX_OUTBOX = 20
NETWORK_TIMEOUT_S = 15
DAY = 86400
OUTBOX_DIR = "rating-outbox"
DELIVERED_MARK = "delivered"      # в папке очереди: приёмник подтвердил оценку (2xx); без данных оценки

# Каталоги для «оцените и там» в одном месте: (ключ, название, адрес, ключ текста кнопки, включён).
# Включать только после регистрации страницы (ADR-0006: регистрации делает Сергей): неработающие ссылки не показываются.
CATALOGS = [
    ("github", "GitHub", "https://github.com/clipsd/clipsd", "feedback.catalog_github", True),
    ("sourceforge", "SourceForge", "https://sourceforge.net/projects/clipsd/reviews/", "feedback.rate_in", False),
    ("alternativeto", "AlternativeTo", "https://alternativeto.net/software/clipsd/about/", "feedback.rate_in", False),
    ("store", "Microsoft Store", "", "feedback.rate_in", False),
]

_EMAIL = re.compile(r"[^\s@<>()\"',;:]+@[^\s@<>()\"',;:]+\.[A-Za-z]{2,}")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
_outbox_lock = threading.RLock()
_results: dict = {}           # имя файла очереди -> итог, если его отправил проход flush_outbox
FRESH_S = 120                 # свежую оценку (первая попытка идёт по кнопке) проход очереди не трогает


# ---------------------------------------------------------------- счётчики и правила

def _ts(now=None) -> float:
    if now is None:
        return time.time()
    if isinstance(now, datetime):
        return now.timestamp()
    if isinstance(now, date):
        return datetime(now.year, now.month, now.day).timestamp()
    return float(now)


def note_use_day(config: dict, now=None) -> None:
    """День работы: один на календарный день, сколько бы запусков и снимков в нём ни было."""
    today = datetime.fromtimestamp(_ts(now)).strftime("%Y-%m-%d")
    if config.get("last_usage_day") != today:
        config["last_usage_day"] = today
        config["usage_days"] = int(config.get("usage_days", 0) or 0) + 1


def note_capture(config: dict, now=None) -> None:
    config["capture_count"] = int(config.get("capture_count", 0) or 0) + 1
    note_use_day(config, now)


def should_show_rating(config: dict, now=None) -> bool:
    if config.get("rating_disabled") or config.get("rating_sent"):
        return False
    if int(config.get("rating_shown", 0) or 0) >= MAX_SHOWS:
        return False
    if int(config.get("usage_days", 0) or 0) < MIN_DAYS or int(config.get("capture_count", 0) or 0) < MIN_CAPTURES:
        return False
    return _ts(now) >= float(config.get("rating_next_ts", 0) or 0)


def rating_shown(config: dict) -> None:
    config["rating_shown"] = int(config.get("rating_shown", 0) or 0) + 1


def rating_later(config: dict, now=None) -> None:
    config["rating_next_ts"] = _ts(now) + LATER_DAYS * DAY


def rating_never(config: dict) -> None:
    config["rating_disabled"] = True


def rating_submitted(config: dict, stars: int = None, now=None) -> None:
    """Нажата «Отправить»: окно само больше не предлагается. «Отправлено» здесь не ставится: только после 2xx
    (rating_delivered), иначе при отказе приёмника меню говорило бы «Вы уже оценили» и не давало повторить."""
    config["rating_disabled"] = True
    if stars is not None:              # для окна «Вы уже оценили»: звёзды и день, больше ничего
        config["rating_stars"] = int(stars)
        config["rating_day"] = datetime.fromtimestamp(_ts(now)).strftime("%Y-%m-%d")


def rating_delivered(config: dict) -> None:
    """Приёмник подтвердил оценку (2xx)."""
    config["rating_sent"] = True
    config["rating_disabled"] = True


def delivered(directory=None) -> bool:
    """Отметка в папке очереди: оценку подтвердил приёмник (в том числе при фоновом проходе очереди)."""
    try:
        return (outbox_dir(directory) / DELIVERED_MARK).exists()
    except OSError:
        return False


def sync_delivered(config: dict, directory=None) -> bool:
    """Главный поток: отметку из папки очереди в config. True, если config изменился (его стоит записать)."""
    if not config.get("rating_sent") and delivered(directory):
        rating_delivered(config)
        return True
    return False


def has_rated(config: dict, directory=None) -> bool:
    """Оценка дошла до приёмника или ждёт в очереди: второй оценки не нужно. Не принята или попытки кончились:
    False, пункт меню снова даёт оценить."""
    return bool(config.get("rating_sent")) or delivered(directory) or pending_count(directory) > 0


def clean_review(text: str) -> str:
    """Текст отзыва как его примет приёмник: без управляющих знаков, без адресов почты, не длиннее MAX_REVIEW."""
    s = _CONTROL.sub("", str(text or "").replace("\r\n", "\n").replace("\r", "\n")).strip()
    s = _EMAIL.sub("<e-mail>", s)
    return s[:MAX_REVIEW]


def platform_name() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "macos"
    return "other"


def enabled_catalogs() -> list:
    """[(название, адрес, текст кнопки)] только включённых каталогов с адресом."""
    out = []
    for _key, name, url, text_key, enabled in CATALOGS:
        if enabled and url:
            out.append((name, url, tr(text_key, name=name)))
    return out


def privacy_url(lang: str = None) -> str:
    return PRIVACY_URL.format(lang=lang or current_language())


# ---------------------------------------------------------------- очередь и отправка

def outbox_dir(directory=None) -> Path:
    if directory is None:
        from . import paths
        directory = paths.config_dir() / OUTBOX_DIR
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def make_payload(stars: int, text: str, fill_ms: int, lang: str = None) -> dict:
    stars = int(stars)
    if not 1 <= stars <= 5:
        raise ValueError("stars must be 1..5")
    return {"stars": stars, "review": clean_review(text), "lang": lang or current_language(),
            "version": __version__, "platform": platform_name(), "key": uuid.uuid4().hex,
            "fill_ms": max(0, int(fill_ms))}


def enqueue(payload: dict, directory=None) -> Path:
    folder = outbox_dir(directory)
    path = folder / f"{time.time():.3f}-{payload['key']}.json"
    _write_json(path, {"payload": payload, "attempts": 0, "next_try_ts": 0})
    for old in sorted(folder.glob("*.json"))[:-MAX_OUTBOX]:      # держим не больше MAX_OUTBOX самых новых
        old.unlink(missing_ok=True)
    return path


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):      # приёмник не перенаправляет: редирект = чужой ответ
        return None


def post_rating(payload: dict, url: str = None, timeout: float = NETWORK_TIMEOUT_S) -> int:
    """POST оценки. Код ответа HTTP или 0, если ответа нет (сеть, таймаут, сертификат)."""
    url = url or RATE_URL
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Content-Type": "application/json; charset=utf-8", "Idempotency-Key": payload["key"],
        "User-Agent": f"ClipSD/{__version__}", "Accept": "application/json"})
    handlers = [_NoRedirect()]
    if url.startswith("https:"):
        from . import tls
        handlers.append(urllib.request.HTTPSHandler(context=tls.context()))
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(req, timeout=timeout) as resp:
            resp.read(4096)
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, OSError, ValueError):
        return 0


def classify(status: int) -> str:
    """sent: приёмник принял; retry: попробовать позже; rejected: не принял, повтор бесполезен."""
    if 200 <= status < 300:
        return "sent"
    if status == 0 or 300 <= status < 400 or status in (408, 425, 429) or status >= 500:
        return "retry"          # нет ответа, чужой редирект (точка доступа с входом), лимит, сбой сервера
    return "rejected"


def _attempt(path: Path, sender=None, now=None) -> str:
    """Одна попытка отправить файл очереди: sent | retry | rejected | dropped (попытки кончились) | gone (файла нет)."""
    try:
        item = json.loads(path.read_text(encoding="utf-8"))
        payload = item["payload"]
        payload["key"]
    except FileNotFoundError:
        return _results.pop(path.name, "gone")
    except (OSError, ValueError, KeyError, TypeError):
        path.unlink(missing_ok=True)
        return "rejected"
    status = (sender or post_rating)(payload)
    result = classify(status)
    if result == "sent":
        _mark_delivered(path.parent)    # до удаления файла очереди: has_rated не увидит «ни там, ни там»
    if result in ("sent", "rejected"):
        path.unlink(missing_ok=True)
        return result
    attempts = int(item.get("attempts") or 0) + 1
    if attempts >= MAX_ATTEMPTS:              # попытки кончились: оценка удаляется из очереди
        path.unlink(missing_ok=True)
        return "dropped"
    item["attempts"] = attempts
    item["next_try_ts"] = _ts(now) + RETRY_PAUSES[min(attempts, len(RETRY_PAUSES)) - 1]
    _write_json(path, item)
    return "retry"


def _mark_delivered(folder: Path) -> None:
    try:
        fd = os.open(folder / DELIVERED_MARK, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.close(fd)
    except OSError:
        pass


def flush_outbox(sender=None, directory=None, now=None) -> int:
    """Отправить из очереди всё, у чего вышла пауза. Возвращает число отправленных. Вызывать в фоне."""
    sent = 0
    with _outbox_lock:
        try:
            files = sorted(outbox_dir(directory).glob("*.json"))
        except OSError:
            return 0
        for path in files:
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                path.unlink(missing_ok=True)
                continue
            if float(item.get("next_try_ts") or 0) > _ts(now):
                continue
            try:
                if not item.get("attempts") and time.time() - path.stat().st_mtime < FRESH_S:
                    continue
            except OSError:
                continue
            result = _attempt(path, sender, now)
            if result in ("sent", "rejected", "dropped"):
                _results[path.name] = result
            if result == "sent":
                sent += 1
    return sent


def pending_count(directory=None) -> int:
    """Сколько оценок ждёт отправки в очереди."""
    try:
        return len(list(outbox_dir(directory).glob("*.json")))
    except OSError:
        return 0


def flush_in_background(sender=None, directory=None) -> threading.Thread:
    t = threading.Thread(target=flush_outbox, args=(sender, directory), name="clipsd-rating-outbox", daemon=True)
    t.start()
    return t


class Delivery:
    """Итог фоновой отправки: state "sending", затем "sent" | "queued" | "rejected"."""

    def __init__(self):
        self.state = "sending"
        self.done = threading.Event()

    def finish(self, state: str) -> None:
        self.state = state
        self.done.set()


def submit(config: dict, stars: int, text: str, fill_ms: int, sender=None, directory=None,
           background: bool = True) -> Delivery:
    """Кнопка «Отправить»: оценка в очередь, окно больше не предлагается, первая попытка сразу (в фоне).
    «Отправлено» (rating_sent) только после 2xx: в фоне config не трогается (его пишет главный поток), приёмник
    отмечает успех файлом DELIVERED_MARK; при background=False config отмечается сразу."""
    payload = make_payload(stars, text, fill_ms)
    path = enqueue(payload, directory)
    rating_submitted(config, payload["stars"])
    delivery = Delivery()

    def run():
        try:
            with _outbox_lock:
                result = _attempt(path, sender)
        except Exception:      # noqa: BLE001 — сбой отправки не должен ронять программу, оценка в очереди
            result = "retry"
        delivery.finish({"sent": "sent", "rejected": "rejected", "dropped": "rejected"}.get(result, "queued"))
    if background:
        threading.Thread(target=run, name="clipsd-rating-send", daemon=True).start()
    else:
        run()
        if delivery.state == "sent":
            rating_delivered(config)
    return delivery


def status_key(delivery) -> str:
    """Текст окна после отправки: «отправлено» только когда приёмник подтвердил (2xx)."""
    if delivery is None:
        return "feedback.thanks_queued"
    state = getattr(delivery, "state", delivery)
    return {"sent": "feedback.thanks_text", "queued": "feedback.thanks_queued",
            "rejected": "feedback.thanks_rejected"}.get(state, "feedback.thanks_sending")


# ---------------------------------------------------------------- «Сообщить о проблеме» на GitHub

def system_line() -> str:
    """Система без имени пользователя и путей: «Windows 11», «Linux (Ubuntu 26.04)»."""
    if sys.platform == "win32":
        return f"Windows {_platform.release()}".strip()
    name = _platform.system() or sys.platform
    try:
        pretty = _platform.freedesktop_os_release().get("PRETTY_NAME", "")
    except (OSError, AttributeError):
        pretty = ""
    return f"{name} ({pretty})" if pretty else name


def issue_url(stars: int, text: str, limit: int = ISSUE_URL_LIMIT) -> str:
    """Страница новой задачи на GitHub с заголовком и текстом. Длинный отзыв укорачивается под предел адреса."""
    title = tr("feedback.issue_title", version=__version__)
    review = clean_review(text)

    def build(body_text):
        body = tr("feedback.issue_body", text=body_text or "", version=__version__, system=system_line(),
                  lang=current_language(), stars=stars)
        return ISSUE_URL + "?" + urllib.parse.urlencode({"title": title, "body": body}, quote_via=urllib.parse.quote)
    url = build(review)
    while len(url) > limit and review:
        review = review[:max(0, len(review) - max(20, len(review) // 5))].rstrip()
        url = build(review + "…" if review else "")
    return url


def _open_url(url: str) -> None:
    """Ссылка открывается через sysenv.open_url (1.31.2): в сборке Linux браузер без окружения сборки."""
    from .sysenv import open_url
    open_url(url)


# ---------------------------------------------------------------- окна

STAR_ON, STAR_OFF, STAR_HOVER = "#f5a623", "#c8d0db", "#f8c46a"
STAR_OFF_DARK = "#7d8691"


def extra_style(dark: bool = False) -> str:
    """Добавка к стилю окон-карточек для окон оценки; цвета берутся из палитры карточки (светлой или тёмной)."""
    from .dialogs import PALETTES
    c = PALETTES[bool(dark)]
    return f"""
QPlainTextEdit#rateText {{ padding: 6px 8px; border: 1px solid {c['line']}; border-radius: 8px; font-size: 14px;
                          background: {c['field']}; color: {c['text']}; }}
QPlainTextEdit#rateText:focus {{ border: 2px solid {c['accent']}; padding: 5px 7px; }}
QLabel#rateCounter {{ color: {c['muted']}; font-size: 12px; }}
QLabel#rateStarsHint {{ color: {c['muted']}; font-size: 13px; }}
QToolButton#rateStar {{ background: transparent; border: none; font-size: 30px; padding: 0 2px; }}
QLabel#thanksStatus {{ font-size: 14px; }}
"""


EXTRA_STYLE = extra_style(False)


def _star_style(color: str) -> str:
    return f"QToolButton#rateStar {{ color: {color}; }}"


def build_rating_dialog(config: dict, on_done=None, parent=None, sender=None, directory=None):
    """Окно оценки в стиле «О программе». on_done(outcome, dialog): sent | later | never | closed, вызывается один раз.
    После «Отправить»: dialog.delivery (Delivery), dialog.stars, dialog.review."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QToolButton
    from .dialogs import ClipDialog, style as STYLE_FOR

    class RatingDialog(ClipDialog):
        def __init__(self):
            super().__init__(parent, tr("feedback.rate_title"), tr("feedback.rate_question"), "star", 520)
            self.setStyleSheet(STYLE_FOR(self.dark) + extra_style(self.dark))
            self.outcome = None
            self.stars = 0
            self.review = ""
            self.delivery = None
            self._opened = time.monotonic()
            row = QHBoxLayout()
            row.setSpacing(2)
            self.star_buttons = []
            for n in range(1, 6):
                b = QToolButton()
                b.setObjectName("rateStar")
                b.setText("★")
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.setToolTip(tr("feedback.stars_tip", n=n))
                b.setAccessibleName(tr("feedback.stars_tip", n=n))
                b.clicked.connect(lambda _=False, k=n: self.set_stars(k))
                b.installEventFilter(self)
                self.star_buttons.append(b)
                row.addWidget(b)
            row.addSpacing(10)
            self.stars_hint = QLabel(tr("feedback.stars_hint"))
            self.stars_hint.setObjectName("rateStarsHint")
            row.addWidget(self.stars_hint)
            row.addStretch(1)
            self.body.addLayout(row)
            self.text_edit = QPlainTextEdit()
            self.text_edit.setObjectName("rateText")
            self.text_edit.setPlaceholderText(tr("feedback.rate_placeholder", n=MAX_REVIEW))
            self.text_edit.setMinimumHeight(110)
            self.text_edit.setTabChangesFocus(True)
            self.text_edit.textChanged.connect(self._limit)
            self.body.addWidget(self.text_edit)
            self.counter = QLabel()
            self.counter.setObjectName("rateCounter")
            self.counter.setAlignment(Qt.AlignmentFlag.AlignRight)
            self.body.addWidget(self.counter)
            self.note = self.text(html.escape(tr("feedback.publish_note")) + f' <a href="{privacy_url()}">'
                                  + html.escape(tr("feedback.privacy_link")) + "</a>", "clipNote")
            self.note.linkActivated.connect(_open_url)   # not Qt's own opener: see sysenv.open_url
            self.never_btn = self.link(tr("feedback.never"))
            self.later_btn = self.secondary(tr("feedback.later"))
            self.send_btn = self.primary(tr("feedback.send"))
            self.send_btn.setEnabled(False)
            self.send_btn.clicked.connect(self._send)
            self.later_btn.clicked.connect(lambda: self._finish("later"))
            self.never_btn.clicked.connect(lambda: self._finish("never"))
            self._paint_stars(0)
            self._limit()

        # звёзды: выбранные золотые, при наведении подсветка до звезды под мышью
        def _paint_stars(self, upto: int, hover: bool = False):
            for i, b in enumerate(self.star_buttons, 1):
                color = (STAR_HOVER if hover else STAR_ON) if i <= upto else (STAR_OFF_DARK if self.dark else STAR_OFF)
                b.setStyleSheet(_star_style(color))

        def eventFilter(self, obj, event):
            from PyQt6.QtCore import QEvent
            if obj in getattr(self, "star_buttons", ()):
                if event.type() == QEvent.Type.Enter:
                    self._paint_stars(self.star_buttons.index(obj) + 1, hover=True)
                elif event.type() == QEvent.Type.Leave:
                    self._paint_stars(self.stars)
                return False
            return super().eventFilter(obj, event)

        def set_stars(self, n: int):
            self.stars = max(1, min(5, int(n)))
            self._paint_stars(self.stars)
            self.stars_hint.setText(tr("feedback.stars_tip", n=self.stars))
            self.send_btn.setEnabled(True)

        def _limit(self):
            t = self.text_edit.toPlainText()
            if len(t) > MAX_REVIEW:
                cursor = self.text_edit.textCursor()
                pos = min(cursor.position(), MAX_REVIEW)
                self.text_edit.blockSignals(True)
                self.text_edit.setPlainText(t[:MAX_REVIEW])
                self.text_edit.blockSignals(False)
                cursor = self.text_edit.textCursor()
                cursor.setPosition(pos)
                self.text_edit.setTextCursor(cursor)
                t = t[:MAX_REVIEW]
            self.counter.setText(f"{len(t)} / {MAX_REVIEW}")

        def fill_ms(self) -> int:
            return int((time.monotonic() - self._opened) * 1000)

        def _send(self):
            if not self.stars or self.outcome:
                return
            self.review = self.text_edit.toPlainText()
            self.delivery = submit(config, self.stars, self.review, self.fill_ms(), sender=sender, directory=directory)
            self._finish("sent")

        def _finish(self, outcome):
            if self.outcome is None:
                self.outcome = outcome
                if on_done is not None:
                    on_done(outcome, self)
            self.close()

        def showEvent(self, event):
            super().showEvent(event)
            if getattr(self, "_shown_once", False) is False:
                self._shown_once = True
                self._opened = time.monotonic()

        def closeEvent(self, event):
            if self.outcome is None:          # крестик или Esc
                self.outcome = "closed"
                if on_done is not None:
                    on_done("closed", self)
            super().closeEvent(event)

    return RatingDialog()


def _add_catalogs(dlg) -> None:
    """«Если хотите, поддержите ClipSD и здесь:» и ссылки на включённые каталоги (dlg.link_buttons)."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QPushButton
    dlg.link_buttons = []
    catalogs = enabled_catalogs()
    if not catalogs:
        return
    dlg.text(tr("feedback.catalogs_intro"))
    for _name, url, label in catalogs:
        b = QPushButton(label)
        b.setObjectName("clipLink")
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        dlg.body.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
        b.url = url
        b.clicked.connect(lambda _=False, u=url: _open_url(u))
        dlg.link_buttons.append(b)


def local_date(iso: str) -> str:
    """День оценки по правилам языка интерфейса (короткий формат Qt), при ошибке как есть."""
    from PyQt6.QtCore import QDate, QLocale, Qt
    d = QDate.fromString(str(iso or ""), Qt.DateFormat.ISODate)
    if not d.isValid():
        return str(iso or "")
    return QLocale(current_language()).toString(d, QLocale.FormatType.ShortFormat)


def build_already_dialog(config: dict, parent=None, directory=None):
    """Пункт меню после отправленной оценки: «Вы уже оценили ClipSD». Вторую оценку не даёт: изменить или удалить
    отправленную можно письмом автору (дата и текст), как в политике конфиденциальности."""
    from .dialogs import ClipDialog, style as STYLE_FOR
    dlg = ClipDialog(parent, tr("feedback.already_title"), tr("feedback.thanks_title"), "star", 480)
    dlg.setStyleSheet(STYLE_FOR(dlg.dark) + extra_style(dlg.dark))
    stars = config.get("rating_stars")
    dlg.summary = None
    if isinstance(stars, int) and 1 <= stars <= 5:
        dlg.summary = dlg.text(tr("feedback.already_text", stars=stars, date=local_date(config.get("rating_day"))),
                               "thanksStatus")
    dlg.pending = dlg.text(tr("feedback.already_pending")) if pending_count(directory) else None
    mail = f'<a href="mailto:{SUPPORT_EMAIL}">{SUPPORT_EMAIL}</a>'
    marker = "@@EMAIL@@"                          # адрес почты станет ссылкой mailto после экранирования текста
    dlg.change = dlg.text(html.escape(tr("feedback.already_change", email=marker)).replace(marker, mail), "clipNote")
    dlg.change.linkActivated.connect(_open_url)   # mailto: тоже через sysenv.open_url
    _add_catalogs(dlg)
    dlg.close_button = dlg.primary(tr("feedback.done"))
    dlg.close_button.clicked.connect(dlg.close)
    return dlg


def build_thanks_dialog(stars: int, review: str = "", delivery=None, parent=None):
    """Окно после отправки: что с оценкой (следит за фоновой отправкой), ссылки на включённые каталоги,
    у 1-3 звёзд кнопка «Сообщить о проблеме» (новая задача на GitHub с вписанным отзывом)."""
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QLabel
    from .dialogs import ClipDialog, style as STYLE_FOR

    dlg = ClipDialog(parent, tr("feedback.thanks_title"), "", "star", 480)
    dlg.setStyleSheet(STYLE_FOR(dlg.dark) + extra_style(dlg.dark))
    dlg.status = dlg.text(tr(status_key(delivery)), "thanksStatus")
    dlg.delivery = delivery

    def refresh():
        dlg.status.setText(tr(status_key(delivery)))
        if delivery is None or getattr(delivery, "state", "sent") != "sending":
            dlg.status_timer.stop()
    dlg.refresh_status = refresh
    dlg.status_timer = QTimer(dlg)
    dlg.status_timer.setInterval(250)
    dlg.status_timer.timeout.connect(refresh)
    if getattr(delivery, "state", None) == "sending":
        dlg.status_timer.start()

    _add_catalogs(dlg)
    dlg.problem_button = None
    dlg.issue_url = None
    if stars <= 3:
        intro = QLabel(tr("feedback.problem_intro"))
        intro.setWordWrap(True)
        dlg.body.addWidget(intro)
        dlg.issue_url = issue_url(stars, review)
        dlg.problem_button = dlg.secondary(tr("feedback.problem_button"))
        dlg.problem_button.clicked.connect(lambda: _open_url(dlg.issue_url))
    close = dlg.primary(tr("feedback.done"))
    close.clicked.connect(dlg.close)
    dlg.close_button = close
    return dlg


class RatingFlow:
    """Окно оценки и окно после отправки для приложения: ctx.config, ctx.save_config().
    auto=True: показ по правилам (засчитывается показ, крестик = «Позже»). Из меню после отправленной оценки:
    окно «Вы уже оценили ClipSD» (self.thanks), окна оценки нет."""

    def __init__(self, ctx, auto: bool = False, sender=None, directory=None):
        self.ctx, self.auto = ctx, auto
        self.sender, self.directory = sender, directory
        self.dialog = None
        self.thanks = None
        self.outcome = None

    def open(self):
        from PyQt6.QtCore import Qt
        config = self.ctx.config
        if sync_delivered(config, self.directory):   # фоновая отправка дошла: отметка из папки очереди в config
            self._save()
        if not self.auto and has_rated(config, self.directory):   # оценка дошла или ждёт в очереди: второй нет
            self.outcome = "already"
            self.thanks = build_already_dialog(config, directory=self.directory)
            self.thanks.open_centered()
            return self.thanks
        if self.auto:
            rating_shown(config)            # показ засчитан до открытия: сбой окна не зациклит показы
            self._save()
        self.dialog = build_rating_dialog(config, self._done, sender=self.sender, directory=self.directory)
        self.dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.dialog.open_centered()
        return self.dialog

    def _save(self):
        save = getattr(self.ctx, "save_config", None)
        if save is not None:
            save()

    def _done(self, outcome, dialog):
        from PyQt6.QtCore import QTimer
        self.outcome = outcome
        config = self.ctx.config
        if outcome == "later" or (outcome == "closed" and self.auto):
            rating_later(config)
        elif outcome == "never":
            rating_never(config)
        self._save()
        if outcome == "sent":
            stars, review, delivery = dialog.stars, dialog.review, dialog.delivery
            QTimer.singleShot(0, lambda: self._show_thanks(stars, review, delivery))

    def _show_thanks(self, stars, review, delivery):
        self.thanks = build_thanks_dialog(stars, review, delivery)
        self.thanks.open_centered()

    def close_for_capture(self) -> bool:
        """Alt+W при открытом окне оценки (1.32, Б1 проверки): окно модальное, под ним окно выделения не получило бы
        ни мыши, ни клавиш. Окно закрывается: показанное по правилам как «Позже» (снова через 30 дней), открытое
        из меню как крестиком (правила не трогаются). Окно после отправки не модальное и остаётся.
        True, если окно оценки было открыто."""
        dlg = self.dialog
        try:
            if dlg is None or not dlg.isVisible():
                return False
            if self.auto:
                dlg._finish("later")
            else:
                dlg.close()
        except RuntimeError:          # окно уже удалено (WA_DeleteOnClose)
            return False
        return True


def is_open(flow) -> bool:
    """Окно оценки или окно после отправки этого потока сейчас на экране."""
    for w in (getattr(flow, "dialog", None), getattr(flow, "thanks", None)):
        try:
            if w is not None and w.isVisible():
                return True
        except RuntimeError:          # окно уже удалено (WA_DeleteOnClose)
            pass
    return False
