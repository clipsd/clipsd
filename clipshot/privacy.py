# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Поиск личных данных в распознанном тексте снимка (1.36, «Скрыть личные данные»).

Работает на готовых словах распознавания (ocr.Word: текст, рамка, ключ строки), без сети и без записи значений
куда-либо: модуль ничего не пишет в журналы. Находит телефоны, электронную почту, номера банковских карт (проверка
Луна), IBAN (контрольная сумма), ссылки с токенами и ключами. Правило: лучше пропустить, чем закрыть лишнее, поэтому
номер без надёжного признака (плюс, ведущий 0 или 8 с нужной длиной, скобки) не считается телефоном, а число с
ошибкой Луна не считается картой. Одно значение, разбитое распознаванием на несколько слов, склеивается в общий
поток текста и находится целиком; рамки считаются по словам и по символам внутри слова.
"""
import re
from dataclasses import dataclass, field

from PyQt6.QtCore import QRectF

PHONE, EMAIL, CARD, IBAN, LINK = "phone", "email", "card", "iban", "link"
KINDS = (CARD, IBAN, PHONE, EMAIL, LINK)   # порядок в панели
LAST_DIGITS = 4                            # сколько последних цифр можно оставить открытыми
PAD = 2.0                                  # запас вокруг рамки, точки снимка

_LEN = ("AD24 AE23 AL28 AT20 AZ28 BA20 BE16 BG22 BH22 BR29 BY28 CH21 CR22 CY28 CZ24 DE22 DK18 DO28 EE20 EG29 ES24 "
        "FI18 FO18 FR27 GB22 GE22 GI23 GL18 GR27 GT28 HR21 HU28 IE22 IL23 IQ23 IS26 IT27 JO30 KW30 KZ20 LB28 LC32 "
        "LI21 LT20 LU20 LV21 MC27 MD24 ME22 MK19 MR27 MT31 MU30 NL18 NO15 PK24 PL28 PS29 PT25 QA29 RO24 RS22 SA24 "
        "SC31 SE24 SI19 SK24 SM27 TL23 TN24 TR26 UA29 VA22 VG24 XK20")
IBAN_LENGTHS = {p[:2]: int(p[2:]) for p in _LEN.split()}


MODES = {   # что можно оставить открытым у значения каждого вида (первый режим: закрыто целиком, последний: открыто целиком)
    CARD: ("full", "last4", "first_last", "open"),
    PHONE: ("full", "last4", "first_last", "open"),
    EMAIL: ("full", "domain", "name", "open"),
    IBAN: ("full", "country_last4", "open"),
    LINK: ("full", "host", "open"),
}


_LETTER_W = {**{ch: 0.45 for ch in "iljtf.,:;'|!()[]/ I"}, **{ch: 0.7 for ch in "r-1"}, **{ch: 1.5 for ch in "mwMW@%&"}}


@dataclass
class Finding:
    """Одно найденное значение. chars: [(индекс слова, номер символа)] всех символов значения (без пробелов между
    словами); value живёт только в памяти окна и в панель целиком не попадает (там masked)."""
    kind: str
    value: str
    chars: list = field(default_factory=list)

    def _glyphs(self) -> str:
        return self.value.replace(" ", "").replace("\n", "")

    @property
    def digit_chars(self) -> list:
        return [c for c, ch in zip(self.chars, self._glyphs()) if ch.isdigit()]

    def masked(self) -> str:
        return mask(self.kind, self.value)

    def modes(self) -> tuple:
        """Режимы этого значения. «Только адрес сайта» у ссылки только для настоящего адреса (http, www): у ключа
        без адреса его нет, иначе ничего не закрылось бы."""
        modes = MODES[self.kind]
        if self.kind == LINK and not self._glyphs().lower().startswith(("http", "www.")):
            return ("full", "open")
        return modes

    def hidden_indices(self, mode: str) -> set:
        """Номера символов (в порядке chars), которые в этом режиме закрыты. Лишнее закрывается, а не открывается."""
        g = self._glyphs()
        n = len(self.chars)
        every = set(range(n))
        if mode == "open":
            return set()
        if mode not in self.modes() or n != len(g):
            return every
        digits = [i for i, ch in enumerate(g) if ch.isdigit()]
        if mode == "last4":
            return {i for i in every if i < digits[-4]} if len(digits) > 4 else every
        if mode == "first_last":
            if self.kind == CARD:
                return {i for i in every if digits[3] < i < digits[-4]} if len(digits) > 8 else every
            head = self.value.split(" ")[0] if self.value.startswith("+") and " " in self.value else ""
            keep_head = len(head) if len(head) <= 5 else 0
            if len(digits) <= 2 + keep_head:
                return every
            return {i for i in every if keep_head <= i < digits[-2]}
        if mode == "domain":
            return {i for i in every if i < g.index("@")}
        if mode == "name":
            return {i for i in every if i > g.index("@")}
        if mode == "country_last4":
            return {i for i in every if 2 <= i < n - 4}
        if mode == "host":
            m = re.match(r"(?:[A-Za-z][A-Za-z0-9+.-]*://)?[^/?#]+", g)
            return {i for i in every if i >= m.end()} if m and m.end() < n else every
        return every

    def preview(self, mode: str) -> str:
        """Вид строки в панели при этом режиме: закрытое звёздочками, оставленное открытым как на снимке. Для
        «закрыто» и «открыто» обычная маска (значение целиком в панель не попадает)."""
        if mode in ("full", "open", "custom") or mode not in self.modes():
            return self.masked()
        hidden = self.hidden_indices(mode)
        out, gi = [], 0
        for ch in self.value:
            if ch in " \n":
                out.append(ch)
                continue
            out.append("*" if gi in hidden else ch)
            gi += 1
        text = "".join(out)
        return text if self.kind in (CARD, PHONE) else re.sub(r"\*{4,}", "***", text)

    def rects(self, words, mode: str = "full", boxes=None) -> list:
        """Рамки закрытия (в системе координат слов) для режима. boxes(слово) -> [(x0, x1)] по символам, если их
        удалось измерить по картинке; иначе границы по долям ширины слова с запасом в сторону закрытого."""
        hidden = self.hidden_indices(mode)
        runs, cur = [], []
        for i, c in enumerate(self.chars):
            if i in hidden:
                cur.append(c)
            elif cur:
                runs.append(cur)
                cur = []
        if cur:
            runs.append(cur)
        out = []
        for run in runs:
            by_line = {}
            per_word = {}
            for wi, ci in run:
                per_word.setdefault(wi, []).append(ci)
            for wi, cis in per_word.items():
                w = words[wi]
                n = max(1, len(w.text))
                lo, hi = min(cis), max(cis) + 1
                exact = boxes(wi) if boxes else None
                if exact and len(exact) == n:
                    x0, x1 = exact[lo][0], exact[hi - 1][1]
                else:
                    # границы по картинке не измерены: берём и равные доли, и доли по ширине букв шрифта (узкие i, l,
                    # широкие m, w), обе оценки вместе и ещё запас в сторону закрытого: открытая цифра хуже лишнего размытия
                    cw = w.rect.width() / n
                    ws = [_LETTER_W.get(ch, 1.0) for ch in w.text]
                    total = sum(ws) or 1.0
                    u0, u1 = lo * cw, hi * cw
                    v0, v1 = sum(ws[:lo]) / total * w.rect.width(), sum(ws[:hi]) / total * w.rect.width()
                    x0 = w.rect.x() + min(u0, v0) - (0.3 * cw if lo > 0 else 0)
                    x1 = w.rect.x() + max(u1, v1) + (0.3 * cw if hi < n else 0)
                if lo == 0:
                    x0 = w.rect.x()
                if hi >= n:
                    x1 = w.rect.right()
                pad_l = PAD if lo == 0 else 0.0   # у границы с открытым местом запаса нет: открытое остаётся открытым
                pad_r = PAD if hi >= n else 0.0
                r = QRectF(x0 - pad_l, w.rect.y() - PAD, max(1.0, x1 - x0) + pad_l + pad_r, w.rect.height() + 2 * PAD)
                by_line[w.line] = r if w.line not in by_line else by_line[w.line].united(r)
            out.extend(by_line.values())
        return out


def char_boxes(image, rect: QRectF, text: str):
    """Границы символов слова по картинке: [(x0, x1)] в точках холста или None. Столбцы с чернилами собираются в
    пятна; если пятен ровно столько, сколько символов, границы идут посередине просветов между ними (точно при
    любом шрифте). Склеенные или разорванные буквы (подчёркивание, мелкий шрифт): None, дальше доли ширины."""
    ratio = image.devicePixelRatio() or 1.0
    x0, y0 = int(rect.left() * ratio), int(rect.top() * ratio)
    x1, y1 = int(rect.right() * ratio + 0.999), int(rect.bottom() * ratio + 0.999)
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(image.width(), x1), min(image.height(), y1)
    if x1 - x0 < 4 or y1 - y0 < 4 or not text:
        return None

    def lum(x, y):
        c = image.pixelColor(x, y)
        return 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
    border = sorted([lum(x, y0) for x in range(x0, x1, 2)] + [lum(x, y1 - 1) for x in range(x0, x1, 2)])
    bg = border[len(border) // 2]
    ink = []
    for x in range(x0, x1):
        ink.append(any(abs(lum(x, y) - bg) > 60 for y in range(y0, y1)))
    blobs, start = [], None
    for k, has in enumerate(ink + [False]):
        if has and start is None:
            start = k
        elif not has and start is not None:
            blobs.append((start, k))
            start = None
    if len(blobs) != len(text):
        return None
    edges = [(blobs[i][1] + blobs[i + 1][0]) / 2 for i in range(len(blobs) - 1)]
    bounds = [0.0] + edges + [float(x1 - x0)]
    return [(rect.left() + bounds[i] / ratio, rect.left() + bounds[i + 1] / ratio) for i in range(len(text))]


def luhn_ok(digits: str) -> bool:
    total, flip = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if flip:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        flip = not flip
    return total % 10 == 0


def iban_ok(text: str) -> bool:
    s = text.replace(" ", "").upper()
    if len(s) < 15 or IBAN_LENGTHS.get(s[:2]) != len(s) or not s.isalnum():
        return False
    moved = s[4:] + s[:4]
    number = "".join(str(int(ch, 36)) for ch in moved)
    return int(number) % 97 == 1


def card_ok(raw: str) -> bool:
    """13-19 цифр, проверка Луна, правдоподобное начало, группы по 4 (Amex 4-6-5), не одна цифра подряд."""
    digits = re.sub(r"\D", "", raw)
    if not 13 <= len(digits) <= 19 or len(set(digits)) < 2 or not luhn_ok(digits):
        return False
    if not (digits[0] in "3456" or digits[:2] == "22" or digits[:2] == "62" or digits[:2] == "50"):
        return False
    groups = re.split(r"[ -]", raw)
    if len(groups) > 1:
        sizes = [len(g) for g in groups]
        ok_4 = sizes[:4] == [4, 4, 4, 4] and len(sizes) <= 5 and (len(sizes) == 4 or sizes[4] == 3)
        # распознавание иногда склеивает группы («4111 111111111111»): группы короче четырёх не годятся, остальное
        # решают проверка Луна и правдоподобное начало
        if not (ok_4 or sizes == [4, 6, 5] or sizes == [4, 6, 4] or (len(sizes) <= 3 and min(sizes) >= 4)):
            return False
    return True


_DATE = re.compile(r"^(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}[./-]\d{1,2}[./-]\d{1,2})$")
_US = re.compile(r"^\(?\d{3}\)?[- .]\d{3}[- .]\d{4}$")


def phone_ok(raw: str) -> bool:
    """Телефон по надёжному признаку: «+» и 8-15 цифр; «00» и 10-15 цифр с разделителями; ведущий 0 (9-12 цифр с
    разделителем или 10 цифр подряд); ведущая 8 (ровно 11 цифр, разделители не обязательны); скобки (10-11 цифр);
    американский вид 555-123-4567. Даты, суммы, адреса IP и номера версий не подходят."""
    s = raw.strip()
    digits = re.sub(r"\D", "", s)
    if not s or _DATE.match(s) or re.search(r"[^\d+()\- .]", s):
        return False
    seps = re.findall(r"[ ()\-]", s)
    if s.startswith("+"):
        return 8 <= len(digits) <= 15 and not digits.startswith("0") and "(" not in s[:1] \
            and not re.search(r"\d\.\d+\.\d+", s)
    if s.startswith("00"):
        return 10 <= len(digits) <= 15 and len(seps) >= 1
    if _US.match(s):
        return True
    if "." in s and not seps:
        return False
    if s.startswith("("):
        return 10 <= len(digits) <= 11 and ")" in s
    if s.startswith("8"):
        return len(digits) == 11 and "." not in s
    if s.startswith("0"):
        if "." in s:
            return False
        return (9 <= len(digits) <= 12 and len(seps) >= 1) or (len(digits) == 10 and not seps)
    return False


_SENSITIVE = {"token", "access_token", "refresh_token", "id_token", "auth", "authorization", "key", "api_key", "apikey",
              "secret", "client_secret", "password", "passwd", "pwd", "pass", "sig", "signature", "session",
              "sessionid", "sid", "jwt", "code", "otp", "bearer", "apitoken", "x-amz-signature", "x-amz-credential"}


def link_sensitive(url: str) -> bool:
    """Ссылка с токеном или ключом: параметр token/key/secret/... со значением от 6 знаков, либо длинная случайная
    строка (смешанный регистр с цифрами от 24 знаков или шестнадцатеричная от 32) в пути."""
    base, _q, query = url.partition("?")
    query = query or (url.partition("#")[2] if "#" in url else "")
    for part in re.split(r"[&;#?]", query):
        name, eq, value = part.partition("=")
        if eq and name.lower() in _SENSITIVE and len(value) >= 6:
            return True
    for seg in re.split(r"[/?&=#]", url):
        if len(seg) >= 24 and re.fullmatch(r"[A-Za-z0-9_\-]+", seg):
            if (re.search(r"[a-z]", seg) and re.search(r"[A-Z]", seg) and re.search(r"\d", seg)) \
                    or re.fullmatch(r"[0-9a-fA-F]{32,}", seg):
                return True
    return False


_KEY_TOKENS = re.compile(
    r"(?<![\w-])(?:sk-[A-Za-z0-9_-]{20,}|(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{16,}|gh[pousr]_[A-Za-z0-9]{30,}|"
    r"AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{30,}|"
    r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,})(?![\w-])")
_URL = re.compile(r"(?<![\w@/.-])(?:https?://|www\.)[^\s<>\"']+|(?<![\w@/.-])[A-Za-z0-9.-]+\.[A-Za-z]{2,}/[^\s<>\"']*[?#][^\s<>\"']*")
_EMAIL = re.compile(r"(?<![\w.%+-])[\w.%+-]{1,64}@[\w-]+(?:\.[\w-]+)*\.[^\W\d_]{2,}(?![\w-])")
_IBAN = re.compile(r"(?<![A-Za-z0-9])[A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30}")
_CARD = re.compile(r"(?<![\d+\w-])\d(?:[ -]?\d){11,18}(?![\d])")


def _stream(words):
    """Слова в общий текст (в строке через пробел, новая строка через перевод строки) и карта символ -> (слово, номер)."""
    text, pos = [], []
    for i, w in enumerate(words):
        if i:
            text.append(" " if words[i - 1].line == w.line else "\n")
            pos.append(None)
        for j, ch in enumerate(w.text):
            text.append(ch)
            pos.append((i, j))
    return "".join(text), pos


def _trim(s: str, start: int):
    """Лишние знаки препинания в конце (и открывающая скобка перед парой) убираются: (start, значение)."""
    while s and s[-1] in ".,;:!?)»\"'":
        if s[-1] == ")" and s.count("(") >= s.count(")"):
            break
        s = s[:-1]
    return start, s


def find(words) -> list:
    """Все личные данные в словах распознавания. Возвращает список Finding в порядке следования по тексту."""
    words = list(words or [])
    if not words:
        return []
    text, pos = _stream(words)
    taken = [False] * len(text)
    found = []

    def add(kind, start, end):
        if end <= start or any(taken[start:end]):
            return False
        chars = [p for p in pos[start:end] if p is not None]
        if not chars:
            return False
        for i in range(start, end):
            taken[i] = True
        found.append((start, Finding(kind, text[start:end], chars)))
        return True

    for m in _KEY_TOKENS.finditer(text):
        add(LINK, m.start(), m.end())
    for m in _URL.finditer(text):
        s, v = _trim(m.group(0), m.start())
        if link_sensitive(v):
            add(LINK, s, s + len(v))
    for m in _EMAIL.finditer(text):
        add(EMAIL, m.start(), m.end())
    for m in _IBAN.finditer(text):
        raw = m.group(0)
        cc = raw[:2]
        want = IBAN_LENGTHS.get(cc)
        if not want:
            continue
        count, end = 0, 0
        for k, ch in enumerate(raw):
            if ch != " ":
                count += 1
            if count == want:
                end = k + 1
                break
        if not end or (end < len(raw) and raw[end] not in " \n"):
            continue
        if iban_ok(raw[:end]):
            add(IBAN, m.start(), m.start() + end)
        else:   # по виду IBAN, но сумма не сходится (ошибка распознавания или чужое число): не закрываем и не принимаем за телефон или карту
            for i in range(m.start(), m.start() + end):
                taken[i] = True
    for m in _CARD.finditer(text):
        raw = m.group(0)
        spans = [(g.start(), g.end()) for g in re.finditer(r"\d+", raw)]
        for k in range(len(spans), 0, -1):   # самый длинный начальный набор групп, прошедший проверку
            cand = raw[:spans[k - 1][1]]
            if re.match(r"[ -]\d{4}\b", raw[len(cand):] + text[m.end():m.end() + 6]):
                continue   # за группами идёт ещё группа из четырёх цифр: это не карта, а длинное число
            if card_ok(cand) and add(CARD, m.start(), m.start() + len(cand)):
                break
    toks = [(t.start(), t.end()) for t in re.finditer(r"\S+", text)]
    run = []
    runs = []
    for k, (a0, b0) in enumerate(toks):
        raw = text[a0:b0].rstrip(",;:")
        ok = re.fullmatch(r"\+?[\d()\-.]+", raw) and re.search(r"\d", raw)
        if ok and raw.startswith("+") and run:
            runs.append(run)
            run = []
        if ok and not (run and text[toks[run[-1]][1]:a0] != " "):
            run.append(k)
            continue
        if run:
            runs.append(run)
        run = [k] if ok else []
    if run:
        runs.append(run)
    for run in runs:
        i = 0
        while i < len(run):
            hit = None
            for j in range(min(len(run), i + 6), i, -1):
                s0, e0 = toks[run[i]][0], toks[run[j - 1]][1]
                cand = text[s0:e0].rstrip(".,;:-")
                if phone_ok(cand):
                    hit = (s0, s0 + len(cand), j)
                    break
            if hit and add(PHONE, hit[0], hit[1]):
                i = hit[2]
            else:
                i += 1
    found.sort(key=lambda t: t[0])
    return [f for _s, f in found]


def mask(kind: str, value: str) -> str:
    """Замаскированный вид для панели: целиком значение не показывается."""
    digits = re.sub(r"\D", "", value)
    if kind == CARD:
        return "**** " + digits[-4:]
    if kind == PHONE:
        head = ""
        body = value
        if value.startswith("+"):   # код страны остаётся: «+7 *** *** 12 34»
            first = value.split(" ")[0]
            if " " in value and len(first) <= 4:
                head, body = first, value[len(first):]
        total = len(re.sub(r"\D", "", body))
        seen, out = 0, []
        for ch in body:
            if ch.isdigit():
                seen += 1
                out.append(ch if seen > total - LAST_DIGITS else "*")
            else:
                out.append(ch)
        return head + "".join(out)
    if kind == EMAIL:
        local, _at, domain = value.partition("@")
        return (local[:2] if len(local) > 2 else local[:1]) + "***@" + domain
    if kind == IBAN:
        s = value.replace(" ", "")
        return s[:4] + " *** " + s[-4:]
    m = re.match(r"(?:https?://)?[^/?#\s]+", value)
    if m and "." in m.group(0):
        return m.group(0) + "/***"
    return value[:4] + "***"
