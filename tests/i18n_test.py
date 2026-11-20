# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Переводы: у каждого из 12 языков ровно ключи ru (эталон), подстановки {поле} те же, формы чисел полные;
каждый tr("ключ") в коде есть в каталоге ru; без каталога языка программа говорит по-русски.

Запуск: python3 tests/i18n_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import os  # noqa: E402
os.environ.pop("CLIPSD_LANG", None)   # тест сам выбирает язык
from clipshot import i18n  # noqa: E402

PLURAL = {"ru": {"one", "few", "many"}, "uk": {"one", "few", "many"}, "pl": {"one", "few", "many"},
          "zh": {"other"}, "en": {"one", "other"}, "de": {"one", "other"}, "fr": {"one", "other"}}
failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)
        print("FAIL", msg)


def fields(v):
    vals = v.values() if isinstance(v, dict) else [v]
    return set().union(*(set(re.findall(r"\{(\w+)", x)) for x in vals))


def test_languages_complete():
    ref = i18n._load("ru")
    check(len(ref) > 500, f"в ru мало ключей: {len(ref)}")
    for lang in i18n.LANGUAGES:
        check((i18n.HERE / lang).is_dir(), f"нет папки {lang}")
        cat = i18n._load(lang)
        missing, extra = set(ref) - set(cat), set(cat) - set(ref)
        check(not missing, f"{lang}: нет {sorted(missing)[:10]}")
        check(not extra, f"{lang}: лишние {sorted(extra)[:10]}")
        for k in set(ref) & set(cat):
            check(fields(ref[k]) <= fields(cat[k]) | {"n"} and fields(cat[k]) <= fields(ref[k]) | {"n"},
                  f"{lang}:{k}: поля {fields(cat[k])} != {fields(ref[k])}")
            v = cat[k]
            if isinstance(v, dict) and lang in PLURAL:
                check(PLURAL[lang] <= set(v), f"{lang}:{k}: формы {set(v)}")
            if lang != "ru" and isinstance(v, str) and isinstance(ref[k], str) and ref[k].strip():
                check(v.strip() != "", f"{lang}:{k}: пусто")


def test_same_area_files():
    """Ключ лежит в одном файле области, у всех языков одинаково (иначе слияние каталогов спорное)."""
    def where(lang):
        out = {}
        for f in (i18n.HERE / lang).glob("*.json"):
            for k in json.loads(f.read_text(encoding="utf-8")):
                check(k not in out, f"{lang}: ключ {k} в двух файлах ({out.get(k)}, {f.name})")
                out[k] = f.name
        return out
    ref = where("ru")
    for lang in i18n.LANGUAGES[1:]:
        w = where(lang)
        bad = [k for k in ref if w.get(k) != ref[k]]
        check(not bad, f"{lang}: ключи не в том файле: {bad[:5]}")


def test_code_keys_exist():
    """Каждый литерал tr("область.ключ") в коде есть в ru."""
    ref = i18n._load("ru")
    used = set()
    for f in (ROOT / "clipshot").glob("*.py"):
        used |= set(re.findall(r'\btr(?:_in)?\((?:[a-z_]+, )?"([a-z_0-9]+\.[a-z_0-9.]+)"', f.read_text(encoding="utf-8")))
    missing = sorted(k for k in used if k not in ref)
    check(not missing, f"нет в каталоге ru: {missing}")


def test_plural_ru():
    check([i18n.plural_category("ru", n) for n in (1, 2, 5, 21, 11, 14, 22)] ==
          ["one", "few", "many", "one", "many", "many", "few"], "формы ru")


def test_names_and_lookup():
    check(set(i18n.LANGUAGE_NAMES) == set(i18n.LANGUAGES), "названия языков")
    check(i18n.tr_in("de", "settings.save") != i18n.tr_in("ru", "settings.save"), "tr_in de")
    check(i18n.tr_in("ru", "settings.save") == "Сохранить", "tr_in ru")


def test_fallback_without_catalog():
    """Только каталог ru: выбран de, все надписи русские, ключей на экране нет. Без de-ключа: en, потом ru."""
    tmp = Path(tempfile.mkdtemp(prefix="clipsd-i18n-"))
    pkg = tmp / "clipshot"
    shutil.copytree(ROOT / "clipshot", pkg, ignore=shutil.ignore_patterns("__pycache__"))
    for lang in i18n.LANGUAGES:
        if lang not in ("ru", "en"):
            shutil.rmtree(pkg / "i18n" / lang)
    shutil.rmtree(pkg / "i18n" / "en")
    code = ("import sys; sys.path.insert(0, sys.argv[1]); from clipshot import i18n; i18n.set_language('de');"
            "ref = i18n._load('ru'); bad = [k for k in ref if isinstance(ref[k], str) and i18n.tr(k) != ref[k]];"
            "print('BAD', len(bad), bad[:3])")
    out = subprocess.run([sys.executable, "-c", code, str(tmp)], capture_output=True, text=True).stdout
    check("BAD 0 " in out, f"без каталога de не по-русски: {out.strip()}")
    # ключа нет в de -> en
    de = i18n._load("de")
    saved = de.pop("settings.save")
    try:
        i18n._current = "de"
        check(i18n.tr("settings.save") == i18n._load("en")["settings.save"], "нет ключа de -> en")
    finally:
        de["settings.save"] = saved
        i18n._current = "ru"


def test_builtin_ru_and_selfcheck():
    """Встроенный запасной ru совпадает с каталогом; без папки ru программа по-русски; самопроверка сборки."""
    from clipshot.i18n import ru_builtin
    check(ru_builtin.CATALOG == i18n._load("ru"), "ru_builtin.py устарел: python3 tools/build_ru_builtin.py")
    check(i18n.selfcheck() == [], f"самопроверка: {i18n.selfcheck()}")
    tmp = Path(tempfile.mkdtemp(prefix="clipsd-i18n-"))
    pkg = tmp / "clipshot"
    shutil.copytree(ROOT / "clipshot", pkg, ignore=shutil.ignore_patterns("__pycache__"))
    for lang in i18n.LANGUAGES:
        shutil.rmtree(pkg / "i18n" / lang)
    code = ("import sys; sys.path.insert(0, sys.argv[1]); from clipshot import i18n; i18n.set_language('de');"
            "print('NAME', i18n.tr('settings.save'), '|', i18n.tr('app.name'), '|', len(i18n.selfcheck()))")
    out = subprocess.run([sys.executable, "-c", code, str(tmp)], capture_output=True, text=True)
    check("NAME Сохранить | ClipSD | " in out.stdout and int(out.stdout.split('|')[-1]) > 0 and "встроенный русский" in out.stderr,
          f"пустая сборка: {out.stdout.strip()} {out.stderr.strip()[-200:]}")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    out = subprocess.run([sys.executable, "-m", "clipshot", "--selfcheck"], capture_output=True, text=True, cwd=ROOT, env=env)
    check(out.returncode == 0 and out.stdout.startswith("i18n ok: 12 languages"), f"--selfcheck: {out.returncode} {out.stdout} {out.stderr[-300:]}")
    report = tmp / "report.txt"
    out = subprocess.run([sys.executable, "-m", "clipshot", "--selfcheck", str(report)], capture_output=True, text=True, cwd=ROOT, env=env)
    check(out.returncode == 0 and report.read_text(encoding="utf-8").startswith("i18n ok"), "--selfcheck ФАЙЛ: отчёт в файл, как в 1.30")
    check(i18n.selfcheck_lines()[0].startswith("i18n ok"), "selfcheck_lines")


def test_de_strg():
    """Немецкая клавиатура: клавиша подписана «Strg», в каталоге de нет «Ctrl»."""
    bad = [k for k, v in i18n._load("de").items() if "Ctrl" in json.dumps(v, ensure_ascii=False)]
    check(not bad, f"de: Ctrl вместо Strg в {bad[:5]}")
    i18n._current = "de"
    check(i18n.keys("Ctrl+Shift+L") == "Strg+Shift+L", "keys() на de")
    i18n._current = "ru"
    check(i18n.keys("Ctrl+L") == "Ctrl+L", "keys() на ru")


def test_plural_of_n():
    """«m из N абзацев»: форма существительного по N, проверка на 1, 2, 5, 11, 21, 22 во всех 12 языках."""
    want = {
        "ru": {1: "из 1 абзаца", 2: "из 2 абзацев", 5: "из 5 абзацев", 11: "из 11 абзацев", 21: "из 21 абзаца", 22: "из 22 абзацев"},
        "uk": {1: "з 1 абзацу", 2: "з 2 абзаців", 5: "з 5 абзаців", 11: "з 11 абзаців", 21: "з 21 абзацу", 22: "з 22 абзаців"},
        "pl": {1: "z 1 akapitu", 2: "z 2 akapitów", 5: "z 5 akapitów", 11: "z 11 akapitów", 21: "z 21 akapitów", 22: "z 22 akapitów"},
        "de": {1: "von 1 Absatz", 2: "von 2 Absätzen", 21: "von 21 Absätzen"},
        "en": {1: "of 1 paragraph", 2: "of 2 paragraphs", 21: "of 21 paragraphs"},
        "bg": {1: "от 1 абзац", 2: "от 2 абзаца", 21: "от 21 абзаца"},
        "fr": {1: "sur 1 paragraphe", 2: "sur 2 paragraphes"},
        "es": {1: "de 1 párrafo", 2: "de 2 párrafos"},
        "it": {1: "1 paragrafo", 2: "2 paragrafi"},
        "pt": {1: "de 1 parágrafo", 2: "de 2 parágrafos"},
        "tr": {1: "1 paragraftan", 22: "22 paragraftan"},
        "zh": {1: "1 段", 22: "22 段"},
    }
    for lang in i18n.LANGUAGES:
        for k in (1, 2, 5, 11, 21, 22):
            text = i18n.tr_in(lang, "translate_ui.partial_of", n=k, m=0, k=k)
            check("{" not in text and str(k) in text, f"{lang} {k}: {text}")
            if k in want[lang]:
                check(want[lang][k] in text, f"{lang} из {k}: «{text}», ждали «{want[lang][k]}»")
    for lang, cases in (("ru", {1: "1 знак", 2: "2 знака", 5: "5 знаков", 11: "11 знаков", 21: "21 знак", 22: "22 знака"}),
                        ("uk", {1: "1 знак", 2: "2 знаки", 5: "5 знаків", 21: "21 знак", 22: "22 знаки"}),
                        ("pl", {1: "1 znak", 2: "2 znaki", 5: "5 znaków", 22: "22 znaki"})):
        for n, w in cases.items():
            check(f"{n} " + i18n.tr_in(lang, "translate.chars_word", n=n) == w, f"{lang} {n} знак")


def test_numbers():
    """Числа по правилам языка интерфейса (лимиты переводчика)."""
    got = {}
    for lang in ("ru", "de", "en", "fr", "zh"):
        i18n._current = lang
        got[lang] = i18n.number(50000)
    i18n._current = "ru"
    check(got["ru"] == "50 000" and got["de"] == "50.000" and got["en"] == "50,000" and got["zh"] == "50,000"
          and got["fr"].replace("\u202f", " ").replace("\xa0", " ") == "50 000", f"числа: {got}")
    # четыре цифры так же, как в текстах каталога (лимит MyMemory 5 000 знаков)
    import re as _re
    for lang, want in (("bg", "5 000"), ("it", "5.000"), ("pl", "5 000"), ("es", "5000"), ("ru", "5 000"), ("de", "5.000")):
        i18n._current = lang
        got4 = i18n.number(5000)
        quota = i18n.tr("translate.err_mm_quota")
        i18n._current = "ru"
        check(got4 == want and want in quota, f"{lang}: 5000 -> {got4!r}, в каталоге {_re.findall(r'5.?000', quota)}")
    for lang in i18n.LANGUAGES:
        i18n._current = lang
        n5, n50, q = i18n.number(5000), i18n.number(50000), i18n.tr("translate.usage_mm")
        i18n._current = "ru"
        check(n50 in q, f"{lang}: 50000 -> {n50!r} как в тексте каталога")


def test_ocr_and_already_for_any_language():
    """Распознавание по умолчанию: язык интерфейса + английский; «уже на языке перевода» для любого языка;
    язык перевода «auto»: язык программы, у старых установок язык системы."""
    from clipshot import ocr, translate
    got = {}
    for lang in ("ru", "de", "en", "zh", "uk"):
        i18n._current = lang
        got[lang] = ocr.resolve_langs("auto")
    i18n._current = "ru"
    check(got == {"ru": "rus+eng", "de": "deu+eng", "en": "eng", "zh": "chi_sim+eng", "uk": "ukr+eng"}, f"языки OCR: {got}")
    check(ocr.resolve_langs("rus+eng") == "rus+eng", "явный набор языков остаётся")
    check(ocr.win_tags("rus+eng") == "ru,ru-RU" and ocr.win_tags("deu+eng") == "de-DE,en-US,en",
          f"Windows OCR: запасные языки {ocr.win_tags('deu+eng')}")
    real_find = ocr.find_tesseract
    ocr.find_tesseract = lambda: None   # Windows без Tesseract
    i18n._current = "de"
    check(translate.ocr_langs_for_translation() == "deu+eng", "перевод без Tesseract: язык интерфейса + английский")
    i18n._current = "ru"
    check(translate.ocr_langs_for_translation() == "rus+eng", "перевод без Tesseract на ru: как раньше")
    ocr.find_tesseract = real_find
    check(ocr.win_tag("deu+eng") == "de-DE" and ocr.win_tag("eng") == "en-US" and ocr.win_tag("rus+eng") == "ru", "язык Windows OCR")
    samples = {
        "en": "Thank you for your order. We confirm that the goods are in stock and will ship on Monday.",
        "de": "Vielen Dank für die Bestellung. Wir bestätigen, dass die Ware auf Lager ist und am Montag versendet wird.",
        "fr": "Merci pour votre commande. Nous confirmons que la marchandise est en stock et sera expédiée lundi.",
        "es": "Gracias por su pedido. Confirmamos que la mercancía está en stock y se enviará el lunes. Si necesita la entrega antes, avísenos: también hay envío urgente.",
        "it": "Grazie per il tuo ordine. Confermiamo che la merce è disponibile e sarà spedita lunedì. Se ti serve prima, scrivici: è possibile anche la spedizione espressa.",
        "pl": "Dziękujemy za zamówienie. Potwierdzamy, że towar jest na magazynie i zostanie wysłany w poniedziałek.",
        "uk": "Дякуємо за замовлення. Підтверджуємо, що товар є на складі і буде відправлений у понеділок.",
        "bg": "Благодарим за поръчката. Потвърждаваме, че стоката е на склад и ще бъде изпратена в понеделник.",
        "ru": "Спасибо за заказ. Мы подтверждаем, что товар есть на складе и будет отправлен в понедельник.",
        "zh": "感谢您的订单。我们确认货物有库存，将于周一发货。",
    }
    for target in samples:
        wrong = [src for src, text in samples.items() if translate.already_in_target(text, target) != (src == target)]
        check(not wrong, f"«уже на {target}» ошибается на {wrong}")
    check(not translate.already_in_target("Save", "en"), "короткая надпись уходит в сервис")
    # Ложные срабатывания из независимой проверки: при сомнении перевод должен идти в сервис
    false_cases = [
        ("es", "De levering is gepland voor maandag en de goederen zijn op voorraad in het magazijn."),   # нидерландский
        ("pl", "Hvala na narudžbi i potvrđujemo da je roba na skladištu i bit će poslana u ponedjeljak."),   # хорватский
        ("en", "Vielen Dank für Ihre Bestellung, mehr unter www.example.com/the-best-of-the-year und im Shop."),
        ("en", "Merci pour votre commande, voir www.example.com/the-best-of-the-year pour les détails."),
        ("de", "Thank you for your order and the quick payment. Wir bestätigen, dass die Ware auf Lager ist."),   # смесь
        ("zh", "東京都新宿区西新宿二丁目八番一号"),   # японский адрес только иероглифами
        ("pt", "Grazas polo teu pedido, a mercadoría está no almacén e enviarase o luns coa factura."),   # галисийский
        ("es", "Gràcies per la comanda, la mercaderia és al magatzem i s'enviarà dilluns amb la factura."),   # каталанский
        ("en", "Contact: info@example.com, /home/user/the/and/of/you/report.pdf"),
    ]
    for target, text in false_cases:
        check(not translate.already_in_target(text, target), f"ложное «уже на {target}»: {text[:50]}")
    check(translate.already_text("de") != translate.already_text("ru") and translate.is_already(translate.already_text("ru")),
          "сообщение «уже на языке перевода»")
    check(translate.system_lang({}) == i18n.current(), "auto = язык программы")
    check(translate.auto_label({}).startswith("Как язык программы") and
          translate.auto_label({"translate_auto_system": True}).startswith("Как в системе"), "подписи auto")


def test_already_review_131():
    """Правки «уже на языке перевода» по проверке 1.31: bg «ъ» перед согласной, uk не по одному слову,
    смешанный абзац с коротким иноязычным предложением переводится."""
    from clipshot.translate import already_in_target
    for text, target, want in (
            ("Объявление: съезд делегатов в пятницу", "bg", False),
            ("Подъезд и объём", "bg", False),
            ("Всяка година пътят до къщата е по-дълъг", "bg", True),
            ("Купить сейчас скидка на товар їжа", "uk", False),
            ("Нажмите кнопку, чтобы отправить, і всё", "uk", False),
            ("Ця програма робить знімки екрана і зберігає їх", "uk", True),
            ("Їжа", "uk", True),
            ("Сегодня мы выпустили новую версию программы. Please click the button below.", "ru", False),
            ("Сегодня мы выпустили новую версию для Microsoft Windows Server.", "ru", True),
            ("今天我们发布了新版本，它比旧版本更快。Please click the button below.", "zh", False),
            ("Heute haben wir eine neue Version veröffentlicht, und sie ist schneller als die alte. Click the button now.", "de", False),
            ("Heute haben wir eine neue Version veröffentlicht, und sie ist schneller als die alte. Это короткое предложение.", "de", False),
            ("Heute haben wir eine neue Version veröffentlicht, und sie ist schneller als die alte und auch stabiler.", "de", True)):
        check(already_in_target(text, target) is want, f"уже на {target}: {want} для «{text[:40]}»")


def test_set_language_listeners():
    seen = []
    off = i18n.on_change(seen.append)
    i18n.set_language("de")
    i18n.set_language("ru")
    off()
    check(seen == ["de", "ru"], f"подписчики: {seen}")
    check(i18n.choice() == "ru", "choice")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ИТОГ:", "все проверки пройдены" if not failures else f"{len(failures)} ошибок")
    sys.exit(1 if failures else 0)
