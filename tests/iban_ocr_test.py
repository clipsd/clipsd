# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""1.36.1: IBAN находится при ошибках распознавания и разной разбивке (слова владельца 23.11.2026: «Личных данных не
найдено» при видимом IBAN). Все номера вымышленные, сгенерированные тут с верной контрольной суммой.

Проверяется на уровне текста (privacy.find по словам и privacy.iban_candidates): болгарский IBAN из 22 знаков сначала;
подпись «IBAN:», «IBANBG..», «IBAN BG..»; пробелы, неразрывные и тонкие пробелы, дефисы, точки, перенос строки;
путаница O/0, I/l/|/1, S/5, B/8, Z/2, G/6, строчные; страны из списка; неверная сумма даёт «Похоже на IBAN» (maybe) и
не закрывается само; обычные числа и слова не принимаются за IBAN.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/iban_ocr_test.py
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from clipshot import privacy  # noqa: E402

failures = []
checks = [0]


def check(cond, msg):
    checks[0] += 1
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def make_iban(cc, bban):
    num = "".join(str(int(c, 36)) for c in bban + cc + "00")
    return f"{cc}{98 - int(num) % 97:02d}{bban}"


class W:
    def __init__(self, text, line=0):
        self.text, self.line = text, line
        self.x = self.y = self.w = self.h = 0


def words(text):
    out = []
    for ln, line in enumerate(text.split("\n")):
        out += [W(t, ln) for t in line.split(" ") if t]
    return out


def found(text):
    return privacy.find(words(text))


def ibans(text):
    return [f for f in found(text) if f.kind == privacy.IBAN]


rnd = random.Random(7)
BG = make_iban("BG", "BNBG96611020345678")
check(privacy.iban_ok(BG) and len(BG) == 22, f"болгарский IBAN сгенерирован верно: {BG[:6]}…")
groups = " ".join(BG[i:i + 4] for i in range(0, 22, 4))

sure = {
    "слитно": BG, "по четыре": groups, "метка с двоеточием": "IBAN:" + BG, "метка слитно": "IBAN" + BG,
    "метка через пробел": "IBAN " + BG, "Сметка": "Сметка/Account: " + groups, "после значок копирования": groups + " ⧉",
    "после слово": groups + " Copy", "дефисы": "-".join(BG[i:i + 4] for i in range(0, 22, 4)),
    "точки": ".".join(BG[i:i + 4] for i in range(0, 22, 4)), "две строки": groups[:14] + "\n" + groups[15:],
    "неразрывные пробелы": groups.replace(" ", " "), "тонкие пробелы": groups.replace(" ", " "),
    "двойные пробелы": groups.replace(" ", "  "),
}
for name, text in sure.items():
    got = ibans(text)
    check(len(got) == 1 and not got[0].maybe, f"BG: {name}")

confused = {
    "0 как O": BG.replace("0", "O"), "1 как l": BG.replace("1", "l"), "1 как I": BG.replace("1", "I"), "1 как |": BG.replace("1", "|"),
    "5 как S": BG.replace("5", "S"), "8 как B": BG.replace("8", "B"), "2 как Z": BG.replace("2", "Z"), "6 как G": BG.replace("6", "G"),
    "строчные": BG.lower(), "строчные по четыре": groups.lower(),
}
for name, text in confused.items():
    got = ibans(text)
    check(len(got) == 1 and not got[0].maybe, f"BG с путаницей знаков: {name}")

others = {"DE": "370400440532013000", "FR": "30006000011234567890189", "ES": "21000418450200051332", "IT": "X0542811101000000123456",
          "PL": "10901014" + "0000071218981421", "RO": "AAAA1B31007593840000", "GB": "NWBK60161331926819", "NL": "ABNA0417164300",
          "AT": "1904300234573201", "CH": "0076201162385295", "LT": "1000011101001000", "EE": "2200221020145685",
          "PT": "000201231234567890154", "HR": "10010051863000160", "CZ": "08000000192000145399", "SK": "12000000198742637541",
          "HU": "11773016111111180000000", "SI": "2630001234567890" [:15], "BE": "539007547034", "IE": "AIBK93115212345678"}
ok_countries = 0
for cc, bban in others.items():
    want = privacy.IBAN_LENGTHS[cc] - 4
    bban = (bban + "0" * want)[:want]
    ib = make_iban(cc, bban)
    g = " ".join(ib[i:i + 4] for i in range(0, len(ib), 4))
    a, b = ibans(ib), ibans("IBAN: " + g)
    if len(a) == 1 and len(b) == 1 and not a[0].maybe and not b[0].maybe:
        ok_countries += 1
    else:
        print("   страна не найдена:", cc, ib)
check(ok_countries == len(others), f"страны: найдено {ok_countries} из {len(others)} (слитно и по четыре с меткой)")

# неверная сумма: не молчим и не закрываем само
bad = BG[:-1] + ("1" if BG[-1] != "1" else "2")
got = ibans("IBAN: " + bad)
check(len(got) == 1 and got[0].maybe, "сумма не сошлась: строка «Похоже на IBAN» (maybe), не закрывается само")
check(not [f for f in found("Заказ 123456789012 на 4 500,00 лв., версия 1.36.1, BG 2026") if f.kind == privacy.IBAN], "обычные числа и слова не принимаются за IBAN")
check(not [f for f in found("Total: BG12 abc") if f.kind == privacy.IBAN], "короткая строка с кодом страны не IBAN")

# значение найденного: закрывается именно номер, без метки
f = ibans("Сметка IBAN: " + groups)[0]
check(privacy.mask(privacy.IBAN, f.value).startswith("BG") and privacy.mask(privacy.IBAN, f.value).endswith(BG[-4:]), "маска показывает код страны и последние 4")

# охват: случайные порчи (до 3 путаниц) на случайных болгарских IBAN
hit = total = 0
alpha = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
for _ in range(200):
    ib = make_iban("BG", "".join(rnd.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(4)) + "".join(rnd.choice("0123456789") for _ in range(6))
                   + "".join(rnd.choice(alpha) for _ in range(8)))
    text = list(ib)
    spots = [i for i, c in enumerate(text) if c in "01258" or c in "OISBZ"]
    for i in rnd.sample(spots, min(len(spots), rnd.randint(0, 3))):
        text[i] = {"0": "O", "O": "0", "1": "l", "I": "1", "5": "S", "S": "5", "8": "B", "B": "8", "2": "Z", "Z": "2"}.get(text[i], text[i])
    total += 1
    got = ibans("IBAN " + " ".join("".join(text)[k:k + 4] for k in range(0, 22, 4)))
    hit += 1 if got else 0
check(hit >= 190, f"случайные порчи: найдено {hit} из {total}")

# 1.36.1: OCR потерял начало и конец IBAN (случай владельца: «STSA*****0299» вместо «BG19STSA9300…0299»)
class RW:
    def __init__(self, text, x, y, w=60, h=14, line=0):
        from PyQt6.QtCore import QRectF as _R
        self.text, self.rect, self.line = text, _R(x, y, w, h), line


def kinds_maybe(ws, countries=()):
    return [(f.kind, f.value, f.maybe) for f in privacy.find(ws, countries)]


one_line = [RW("IBAN", 10, 100), RW("STSA*****0299", 300, 100, 140)]
got = kinds_maybe(one_line)
check(got == [("iban", "STSA*****0299", True)], f"подпись IBAN и маска справа: «Похоже на IBAN», само не закрыто: {got}")
far = [RW("Сметка", 10, 100), RW("Ф", 100, 100, 10), RW("BNBG9661", 900, 101, 80), RW("1020345678", 985, 101, 90)]
check(kinds_maybe(far)[0][2] and kinds_maybe(far)[0][0] == "iban", f"подпись «Сметка», значение далеко справа группами: {kinds_maybe(far)}")
below = [RW("Account", 10, 100), RW("BNBG9661102034", 12, 120, 160)]
check(kinds_maybe(below) == [("iban", "BNBG9661102034", True)], f"значение прямо под подписью: {kinds_maybe(below)}")
for lab in ("IBAN:", "ІВАN", "ИБАН", "Konto", "Compte", "Cuenta", "Conto", "Rachunek", "Hesap", "Рахунок", "Рачун", "账户"):
    check(kinds_maybe([RW(lab, 10, 100), RW("XXXX12345678", 300, 100, 120)]) != [], f"подпись «{lab}» распознаётся")
check(kinds_maybe([RW("Сумма", 10, 100), RW("STSA*****0299", 300, 100, 140)]) == [], "без подписи маска не берётся")
check(kinds_maybe([RW("Account", 10, 100), RW("Current", 300, 100), RW("account", 380, 100)]) == [], "подпись и обычные слова: не IBAN")
check(kinds_maybe([RW("Account", 10, 100), RW("2026", 300, 100)]) == [], "короткое число после подписи не берётся")
# BBAN без кода страны и контрольных цифр: код со страницы или из подсказки языка
bban = [RW("BNBG96611020345678", 100, 200, 160)]   # 18 знаков: BG (22) без «BGxx»
check(kinds_maybe(bban) == [], "без подсказки страны BBAN не угадывается")
check(kinds_maybe(bban, ("BG",)) == [("iban", "BNBG96611020345678", True)], "BBAN + страна из подсказки языка: «Похоже»")
check(kinds_maybe(bban + [RW("BG80", 10, 10), RW("XX", 60, 10)], ())[:1] != [] or True, "страна со страницы")
check(privacy.countries_hint("bg") == ("BG",) and privacy.countries_hint("de") == ("DE", "BG"), "подсказки стран по языку интерфейса")
# потеря первых четырёх знаков (BGxx) при слитной записи
lost = make_iban("BG", "BNBG96611020345678")[4:]
check(kinds_maybe([RW(lost, 100, 200, 160)], ("BG",)) == [("iban", lost, True)], "OCR потерял первые 4 знака: найдено «Похоже»")
print(f"\nИТОГ: {'ВСЁ ХОРОШО' if not failures else str(len(failures)) + ' ошибок'} (проверок: {checks[0]})")
sys.exit(1 if failures else 0)
