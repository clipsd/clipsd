# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""1.34: новинки после обновления (novoe.py).

Что проверяется: (1) данные новинок читаются, у каждой строки есть тексты на 12 языках, цели записаны верно; (2) первая
установка: окна «Новое в версии» нет, меток нет, знакомство как раньше; (3) обновление (настройки 1.33 без поля версии
и обновление с записанной версии): окно приходит при первом редакторе один раз, «Позже» откладывает не больше двух раз,
«Показать новое» ведёт коротким курсом и задаёт вопрос про обзор; «Не сейчас» больше не спрашивает, «Да, показать
обзор» запускает всё знакомство; (4) метка «Новое» в редакторе и на панели выделения: исчезает после нажатия и после
трёх показов; (5) настройка «Показывать новинки после обновления» выключает окно и метки; (6) меню значка у часов:
«Что нового»; окно обновления программы заменяется окном новинок; (7) окно и вопрос в обеих темах, одна зелёная кнопка,
помещаются в 1280 x 720 на 12 языках, тексты без длинных тире и эмодзи, контраст метки и значков.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/novoe_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import json
import os
import re
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(here)
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp(prefix="clipsd-novoe-")
for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[name] = os.path.join(tmp, name)
_screen = os.path.join(tmp, "screen.json")
with open(_screen, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1600, "height": 1000,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _screen
os.environ.pop("CLIPSD_LANG", None)

from PyQt6.QtCore import QPoint, QRect, Qt, QTimer  # noqa: E402
from PyQt6.QtGui import QColor, QFontMetrics, QImage, QPixmap  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QPushButton  # noqa: E402

qapp = QApplication(sys.argv)

import clipshot  # noqa: E402
from clipshot import app as appmod, i18n, novoe, themes  # noqa: E402
from clipshot.i18n import tr  # noqa: E402

V = "1.34.0"                       # версия, для которой в таблице есть новинки
clipshot.__version__ = V           # программа «стала» 1.34.0: и окно, и метки берут версию отсюда
novoe.__version__ = V

failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


def settle(ms=30):
    for _ in range(3):
        qapp.processEvents()
        QTest.qWait(ms // 3 or 1)


def lum_hex(h):
    def lin(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def ratio(a, b):
    la, lb = sorted((lum_hex(a), lum_hex(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


i18n.set_language("ru")

# --- 1. данные новинок ----------------------------------------------------------------------------------------------
check(len(novoe.ITEMS) >= 3 and all(len(it) == 4 for it in novoe.ITEMS), f"таблица новинок читается: {len(novoe.ITEMS)} строк")
ids = [it[1] for it in novoe.ITEMS]
check(len(ids) == len(set(ids)), "id новинок не повторяются")
check(all(re.fullmatch(r"\d+\.\d+\.\d+", it[0]) for it in novoe.ITEMS), "версии в виде 1.34.0")
check(all(re.fullmatch(r"(selector:[a-z_]+|editor:(tool:)?[a-z_]+(\|(tool:)?[a-z_]+)*)", it[2]) for it in novoe.ITEMS), "цели selector:… или editor:…")
src = open(os.path.join(ROOT, "clipshot", "novoe.py"), encoding="utf-8").read()
merge_ids = re.findall(r'#\s*\("\d+\.\d+\.\d+", "([a-z_]+)"', src)
check(not merge_ids and ids[:4] == ["phone_tile", "forma", "windows", "other_area"] and "phone_editor" in ids,
      f"новинки 1.34 сведены: в окне «С телефона», «Форма снимка», «Открытые окна», «Другая область» ({ids}, {merge_ids})")
for lang in i18n.LANGUAGES:
    cat = i18n._load(lang)
    missing = [f"novoe.{i}_{p}" for i in ids + merge_ids for p in ("title", "text") if f"novoe.{i}_{p}" not in cat]
    check(not missing, f"{lang}: тексты новинок на месте {missing[:3]}")
    texts = {k: v for k, v in cat.items() if k.startswith("novoe.") or k.startswith("settings.novoe")}
    bad = [k for k, v in texts.items() if "—" in v or re.search("[\U0001F300-\U0001FAFF☀-⛿✀-➿]", v)]
    check(not bad, f"{lang}: без длинных тире и эмодзи {bad[:3]}")
check(set(novoe.ICON_COLORS) >= {it[3] for it in novoe.ITEMS} | {"phone", "region"}, "у каждого значка новинки свой цвет")

# --- 2. состояние: первая установка, обновление, та же версия -------------------------------------------------------
fresh = dict(appmod.DEFAULTS)
check(novoe.on_start(fresh) and fresh["novoe_version"] == V and fresh["novoe_from"] is None, "первая установка: версия записана, обновления нет")
check(not novoe.window_pending(fresh) and novoe.badges(fresh, "editor") == {} and novoe.badges(fresh, "selector") == {},
      "первая установка: окна «Новое» и меток нет")
check(not novoe.on_start(fresh), "второй запуск той же версии: ничего не меняется")

old = dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True)   # настройки 1.33: поля версии нет
novoe.on_start(old)
check(old["novoe_from"] == "" and novoe.window_pending(old), "настройки 1.33 (знакомство пройдено): это обновление, окно ждёт")
check(set(novoe.badges(old, "editor")) == {"form_button|more_button", "phone_button", "tr_block|tool:translate", "tool:number"}
      and set(novoe.badges(old, "selector")) == {"window", "phone", "manual"},
      f"метки: редактор {novoe.badges(old, 'editor')}, панель {novoe.badges(old, 'selector')}")
check([it[1] for it in novoe.window_items(old)] == ids[:novoe.MAX_WINDOW], "окно: пункты в порядке таблицы, не больше четырёх")

later_v = dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True, novoe_version="1.33.0")
novoe.on_start(later_v)
check(later_v["novoe_from"] == "1.33.0" and later_v["novoe_version"] == V and novoe.window_pending(later_v),
      "обновление с записанной 1.33.0: окно ждёт")
same = dict(appmod.DEFAULTS, tour_done=True, novoe_version=V)
novoe.on_start(same)
check(not novoe.window_pending(same) and novoe.badges(same, "editor") == {}, "та же версия без записи об обновлении: ничего")
back = dict(appmod.DEFAULTS, tour_done=True, novoe_version="1.35.0")
novoe.on_start(back)
check(back["novoe_from"] is None and not novoe.window_pending(back), "вернулись на прежнюю версию: окна нет")
old_items = dict(appmod.DEFAULTS, tour_done=True, novoe_version="1.34.0")
check(novoe.items_since(dict(old_items, novoe_from="1.34.0")) == [], "новинки той версии, с которой обновились, не показываются")

off = dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True, novoe_enabled=False)
novoe.on_start(off)
check(not novoe.window_pending(off) and novoe.badges(off, "editor") == {}, "настройка выключена: ни окна, ни меток")

# --- 3. окно при первом редакторе ----------------------------------------------------------------------------------
seen = []


def answer(attr, record=None, timeout_ms=4000):
    """Когда появится модальное окно, запомнить его и нажать кнопку attr."""
    state = {"left": timeout_ms // 30}

    def go():
        w = QApplication.activeModalWidget()
        if w is None:
            state["left"] -= 1
            if state["left"] > 0:
                QTimer.singleShot(30, go)
            return
        seen.append(w)
        if record is not None:
            record(w)
        getattr(w, attr).click()
    QTimer.singleShot(30, go)


def image(w=1200, h=640):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor("#ffffff"))
    return img


a = appmod.Clipshot(qapp)
a.save_config = lambda: None
a.notify = lambda *_x: None


def fresh_app_config(**kw):
    """Настройки при запуске: с tour_done (1.33, знакомство пройдено) это обновление; без него первая установка, после
    запуска человек выбирает оформление (theme_chosen ставится уже после on_start, как в программе)."""
    a.config.clear()
    first = not kw.get("tour_done")
    a.config.update(dict(appmod.DEFAULTS) if first else dict(appmod.DEFAULTS, **kw))
    novoe.on_start(a.config)
    a.config.update(kw)


def close_all():
    for ed in list(a.editors):
        ed.canvas.modified = False
        ed.close()
    settle(60)


# первая установка: знакомство, окна новинок нет
fresh_app_config(theme_chosen=True)
ed = a.open_editor(image(), None)
settle(900)
check(getattr(ed, "tour", None) is not None and getattr(a, "_novoe_window", None) is None and not seen,
      "первая установка: при первом редакторе знакомство, окна «Новое» нет")
check(not (getattr(ed, "_novoe", None) and ed._novoe.badges), "первая установка: меток «Новое» в редакторе нет")
ed.tour.finish()
close_all()

# обновление: окно один раз; «Позже» откладывает
fresh_app_config(tour_done=True, theme_chosen=True)
got = {}


def remember(w):
    got["title"] = w.title.text()
    got["rows"] = len(w.rows)
    got["primary"] = [b.text() for b in w.findChildren(QPushButton) if b.objectName() == "clipPrimary"]
    got["closable"] = bool(w.property("clipsd_closable"))


answer("later_button", remember)
ed = a.open_editor(image(), None)
settle(1200)
check(got.get("title") == "Новое в версии 1.34.0" and got.get("rows") == 4, f"обновление: окно «Новое в версии 1.34.0», 4 пункта ({got})")
check(got.get("primary") == ["Показать новое"], f"одна зелёная кнопка «Показать новое» ({got.get('primary')})")
check(got.get("closable"), "окно не мешает выходу для обновления (clipsd_closable)")
check(a.config.get("novoe_later") == 1 and novoe.window_pending(a.config), "«Позже»: окно придёт при следующем редакторе")
close_all()
answer("later_button")
ed = a.open_editor(image(), None)
settle(1200)
close_all()
check(not novoe.window_pending(a.config), "после двух «Позже» окно само больше не приходит")
n_before = len(seen)
ed = a.open_editor(image(), None)
settle(1200)
check(len(seen) == n_before, "третий редактор: окна нет")
close_all()

# «Показать новое»: короткий курс по новым кнопкам, потом вопрос; «Не сейчас»
fresh_app_config(tour_done=True, theme_chosen=True)
answer("show_button")
ed = a.open_editor(image(), None)
settle(1300)
tour = getattr(ed, "tour", None)
check(tour is not None and tour.steps_fn is not None, "«Показать новое»: короткий курс поверх редактора")
if tour is not None:
    titles = [s[1] for s in tour.steps]
    check(titles[:4] == [novoe.title("forma"), novoe.title("phone_editor"), novoe.title("translate_head"), novoe.title("numbers")]
          and titles[-1] == tr("novoe.panel_title"), f"курс: новые кнопки редактора, потом карточка о панели выделения ({titles})")
    check(tour.steps[0][0] is ed.form_button, f"первый шаг подсвечивает кнопку «Форма снимка» ({tour.steps[0][0]})")
    check(tour.steps[1][0] is ed.phone_button, f"второй шаг подсвечивает кнопку «С телефона» ({tour.steps[1][0]})")
    check(tour.steps[2][0] is ed.tr_block, f"третий шаг подсвечивает строку перевода ({tour.steps[2][0]}, видна {ed.tr_block.isVisible()})")
    panel_text = tour.steps[-1][2]
    check(all(novoe.title(i) in panel_text for i in ("phone_tile", "other_area", "windows")),
          "карточка о панели: «С телефона», «Другая область», «Открытые окна»")
    check(not novoe.window_pending(a.config), "после «Показать новое» окно само больше не приходит")
    q = {}
    answer("secondary_button", lambda w: q.update(title=w.title.text(), yes=w.primary_button.text(), no=w.secondary_button.text()))
    tour.finish()
    settle(800)
    check(q.get("title") == "Хотите узнать о других функциях программы?" and q.get("yes") == "Да, показать обзор"
          and q.get("no") == "Не сейчас", f"вопрос про обзор ({q})")
    check(not novoe.ask_pending(a.config) and getattr(ed, "tour", None) is None, "«Не сейчас»: обзор не начат, больше не спрашивает")
close_all()
n_before = len(seen)
ed = a.open_editor(image(), None)
settle(1200)
check(len(seen) == n_before, "после ответа: ни окна, ни вопроса")
close_all()

# «Да, показать обзор»: всё знакомство без шага языка
fresh_app_config(tour_done=True, theme_chosen=True)
answer("show_button")
ed = a.open_editor(image(), None)
settle(1300)
if getattr(ed, "tour", None) is not None:
    answer("primary_button")
    ed.tour.finish()
    settle(1000)
from clipshot import tour as tourmod  # noqa: E402
full = getattr(ed, "tour", None)
check(full is not None and full.steps_fn is tourmod.steps and len(full.steps) == len(tourmod.steps(ed, False)),
      "«Да, показать обзор»: всё знакомство с программой")
if full is not None:
    full.finish()
close_all()

# окно из меню значка без редактора: «Показать новое» открывает пример снимка
fresh_app_config(tour_done=True, theme_chosen=True)
novoe.window_done(a.config)
answer("show_button")
a.show_novoe()
settle(800)
check(len(a.editors) == 1 and getattr(a.editors[0], "tour", None) is not None, "«Что нового» без редактора: пример снимка и курс по новому")
if a.editors and getattr(a.editors[0], "tour", None) is not None:
    answer("secondary_button")
    a.editors[0].tour.finish()
    settle(600)
close_all()

# М6 проверки 1.34.0: язык сменили, пока окно новинок открыто: окно открывается заново на новом языке
fresh_app_config(tour_done=True, theme_chosen=True)
titles = []


def relang_then_later():
    w = QApplication.activeModalWidget()
    if w is None or not hasattr(w, "later_button"):
        QTimer.singleShot(30, relang_then_later)
        return
    titles.append(w.show_button.text())
    if len(titles) == 1:
        i18n.set_language("en")   # меню значка у часов, пока окно открыто
        QTimer.singleShot(30, relang_then_later)
    else:
        w.later_button.click()


QTimer.singleShot(30, relang_then_later)
ch = a.show_novoe(None, auto=True)
i18n.set_language("ru")
check(titles == [i18n._load("ru")["novoe.show"], i18n._load("en")["novoe.show"]] and ch == "later",
      f"смена языка при открытом окне: окно на новом языке, ответ человека тот же ({titles}, {ch})")
close_all()

# окно обновления программы (updater) заменяется окном новинок
fresh_app_config(tour_done=True, theme_chosen=True)
got.clear()
answer("later_button", lambda w: got.update(sub=w.subtitle.text()))
check(a.show_novoe_after_update(V) is True, "после установки обновления: окно новинок вместо «ClipSD обновлён»")
settle(100)
check(got.get("sub") == tr("updater.whatsnew.installed", version=V), f"в окне строка «Обновление установлено» ({got})")
check(a.show_novoe_after_update("1.33.0") is False, "другая версия: обычное окно «Что нового»")
fresh_app_config()
check(a.show_novoe_after_update(V) is False, "первая установка: обычное окно")
from clipshot import updater as up  # noqa: E402


class FakeUI:
    def __init__(self):
        self.calls = []

    def whats_new(self, v, md):
        self.calls.append(v)


u = up.Updater.__new__(up.Updater)
u.ctx, u.ui, u.installed = a, FakeUI(), V
fresh_app_config(tour_done=True, theme_chosen=True)
answer("later_button")
u._whats_new_after_update("- x")
settle(100)
check(u.ui.calls == [], "updater: окно «ClipSD обновлён» не показано, если показаны новинки")
u.ctx = type("Ctx", (), {"config": {}})()
u._whats_new_after_update("- x")
check(u.ui.calls == [V], "updater без приложения (тесты, старый ctx): обычное окно «Что нового»")

# --- 4. метка «Новое» в редакторе ------------------------------------------------------------------------------------
fresh_app_config(tour_done=True, theme_chosen=True)
novoe.window_done(a.config)
ed = a.open_editor(image(), None)
settle(200)
mgr = getattr(ed, "_novoe", None)
check(mgr is not None and set(mgr.badges) == {"forma", "phone_editor", "translate_head", "numbers"}, f"метки в редакторе: {sorted(mgr.badges) if mgr else None}")
if mgr is not None and "numbers" in mgr.badges:
    b = mgr.badges["numbers"]
    check(b.isVisible() and b.kind == "dot", "у маленькой кнопки «Номер» метка-точка")
    check(mgr.badges["translate_head"].kind == "pill" and mgr.badges["translate_head"].isVisible(),
          "у кнопки перевода метка «Новое»")
    check(tr("novoe.badge_tip") in ed.tool_buttons["number"].accessibleDescription(), "метка названа для экранного диктора")
    check(a.config["novoe_shows"] == {"forma": 1, "phone_editor": 1, "translate_head": 1, "numbers": 1},
          f"показ посчитан один раз на окно ({a.config.get('novoe_shows')})")
    check(mgr.badges["phone_editor"].isVisible() and mgr.badges["phone_editor"].target is ed.phone_button,
          "у кнопки «С телефона» в шапке редактора метка «Новое»")
    check(mgr.badges["forma"].isVisible() and mgr.badges["forma"].target is ed.form_button,
          "у кнопки «Форма снимка» метка «Новое»")
    ed.retranslate()
    settle(100)
    check(set(ed._novoe.badges) == {"forma", "phone_editor", "translate_head", "numbers"} and a.config["novoe_shows"]["numbers"] == 1,
          "смена языка: метки на новых кнопках, показ не посчитан заново")
    QTest.mouseClick(ed.tool_buttons["number"], Qt.MouseButton.LeftButton)
    settle(60)
    check("numbers" in a.config.get("novoe_used", []) and "numbers" not in ed._novoe.badges, "нажатие на кнопку: метка исчезла")
    check(ed.tool_buttons["number"].accessibleDescription().find(tr("novoe.badge_tip")) < 0, "описание для диктора вернулось прежним")
close_all()
for _ in range(2):
    ed = a.open_editor(image(), None)
    settle(150)
    close_all()
check(a.config["novoe_shows"].get("translate_head") == 3, f"три окна с меткой ({a.config['novoe_shows']})")
ed = a.open_editor(image(), None)
settle(150)
check(not ed._novoe.badges, "после трёх показов и нажатия меток больше нет")
close_all()
# узкое окно: большой кнопки перевода нет, метка на кнопке группы «Текст с картинки»
fresh_app_config(tour_done=True, theme_chosen=True)
novoe.window_done(a.config)
ed = a.open_editor(image(420, 300), None)
settle(300)
b = ed._novoe.badges.get("translate_head")
check(b is not None and ed.tr_block.isHidden() and b.target is not ed.tr_block and b.isVisible(),
      f"узкое окно: метка перевода на видимой кнопке ({getattr(getattr(b, 'target', None), 'objectName', lambda: None)()})")
bf = ed._novoe.badges.get("forma")
check(bf is not None and (bf.target is ed.more_button if ed.form_button.isHidden() else bf.target is ed.form_button) and bf.isVisible(),
      f"узкое окно: метка формы на видимой кнопке (форма в ряду: {not ed.form_button.isHidden()})")
close_all()

# --- 5. метка на панели выделения -----------------------------------------------------------------------------------
from clipshot.selector import RegionSelector  # noqa: E402


def selector(cfg):
    pm = QPixmap(1280, 720)
    pm.fill(QColor("#4a78b0"))
    sel = RegionSelector(pm, QRect(0, 0, 1280, 720), last_rect=QRect(300, 200, 500, 300))
    saves = []
    sel.tr_cfg, sel.tr_save = cfg, lambda: saves.append(1)
    sel.lang_ctx = a
    sel.windows_state = "ready"
    sel.show_zoom = False
    sel.resize(1280, 720)
    sel.show()
    settle(60)
    sel.grab()
    settle(30)
    return sel, saves


scfg = dict(appmod.DEFAULTS, tour_done=True, tour_selector_done=True, theme_chosen=True)
novoe.on_start(scfg)
sel, saves = selector(scfg)
check(sel._novoe_targets() == {"window": "windows", "phone": "phone_tile", "manual": "other_area"} and not sel.win_rect.isEmpty(),
      f"панель выделения: метки у «Открытые окна ▾», «С телефона», «Другая область» ({sel._novoe_targets()})")
check(scfg["novoe_shows"].get("windows") == 1 and scfg["novoe_shows"].get("phone_tile") == 1
      and scfg["novoe_shows"].get("other_area") == 1 and saves, f"показ на панели посчитан и записан ({scfg['novoe_shows']})")
pix = sel.grab()
kind, r = novoe.badge_rect(sel.win_rect, QFontMetrics(novoe.badge_font()), sel.rect())
# панель сбоку от рамки (в dev/next чип справа внизу): места в строке подсказки мало, чип одним значком, метка точкой
c = QColor(pix.toImage().pixel(r.center().x() - r.width() // 2 + 3 if kind == "pill" else r.center().x(), r.center().y()))
check(kind in ("pill", "dot") and abs(c.red() - 0x16) + abs(c.green() - 0x60) + abs(c.blue() - 0xd0) < 60,
      f"метка «Новое» нарисована над чипом ({kind}, {c.name()})")
sel.grab()
check(scfg["novoe_shows"]["windows"] == 1, "перерисовка не считается новым показом")
s4 = dict(appmod.DEFAULTS, tour_done=True, tour_selector_done=True, theme_chosen=True)
novoe.on_start(s4)
s4sel, s4saves = selector(s4)
s4.pop("novoe_shows", None)
s4sel._novoe_counted.clear()
s4saves.clear()
s4sel.grab()   # отрисовка: показ считается, а запись на диск после неё (М4 проверки 1.34.0)
counted, during = bool(s4.get("novoe_shows")), len(s4saves)
settle(30)
check(counted and during == 0 and s4saves, f"настройки пишутся не из отрисовки, а сразу после неё ({during} в отрисовке, {len(s4saves)} после)")
s4sel.close()
settle(20)
sel._do("window")
check("windows" in scfg.get("novoe_used", []) and "window" not in sel._novoe_targets(), "нажатие на «Открытые окна ▾»: метка исчезла навсегда")
sel.close()
settle(30)
s2 = dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True)
novoe.on_start(s2)
for _ in range(3):
    s, _sv = selector(s2)
    s.close()
    settle(20)
s, _sv = selector(s2)
check(s._novoe_targets() == {} and s2["novoe_shows"]["windows"] == 3, "после трёх окон выделения метки нет")
s.close()
settle(20)
s3 = dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True)
novoe.on_start(s3)
s, _sv = selector(s3)
s.tour = object()   # идёт знакомство с окном выделения: метки не рисуются и не считаются
s3.pop("novoe_shows", None)
s._novoe_counted.clear()
s.grab()
check("novoe_shows" not in s3, "во время знакомства метки не считаются")
s.tour = None
s.close()
settle(20)

# --- 6. настройка и меню значка ----------------------------------------------------------------------------------
from clipshot.settings import SettingsDialog  # noqa: E402
dlg = SettingsDialog(dict(appmod.DEFAULTS))
check(dlg.novoe_enabled.isChecked() and dlg.novoe_enabled.text() == "Показывать новинки после обновления",
      "настройка «Показывать новинки после обновления» включена по умолчанию")
check(dlg.pages["updates"][0].widget().isAncestorOf(dlg.novoe_enabled), "настройка в разделе «Обновления»")
dlg.novoe_enabled.setChecked(False)
check(dlg.values()["novoe_enabled"] is False, "values() отдаёт настройку")
dlg.deleteLater()
menu = a._build_tray_menu()
texts = [x.text() for x in menu.actions()]
check("Что нового" in texts and texts.index("Что нового") + 1 == texts.index(tr("app.menu_tour")),
      f"меню значка: «Что нового» перед «Знакомство с программой» ({texts})")

# --- 7. вид окна: темы, языки, контраст ----------------------------------------------------------------------------
check(ratio("#ffffff", novoe.BADGE_BG) >= 4.5, f"белый на метке {ratio('#ffffff', novoe.BADGE_BG):.1f}:1")
for name, (light, dark) in novoe.ICON_COLORS.items():
    check(ratio(light, "#eceff3") >= 3 and ratio(dark, "#2f3338") >= 3,
          f"значок {name}: {ratio(light, '#eceff3'):.1f}:1 светлая, {ratio(dark, '#2f3338'):.1f}:1 тёмная")
cfg_items = dict(appmod.DEFAULTS, tour_done=True)
novoe.on_start(cfg_items)
all_items = list(novoe.window_items(cfg_items)) + [("1.34.0", i, "selector:x", "phone") for i in merge_ids][:1]
for lang in i18n.LANGUAGES:
    i18n.set_language(lang)
    for dark in (False, True):
        w = novoe.make_window(V, all_items, None, updated=dark, dark=dark)
        w.adjustSize()
        hint = w.sizeHint()
        greens = [b for b in w.findChildren(QPushButton) if b.objectName() == "clipPrimary"]
        w.show()
        settle(10)
        squeezed = [b.text() for b in w.findChildren(QPushButton) if b.isVisibleTo(w) and b.width() < b.sizeHint().width()]
        ok = hint.width() <= 1280 and hint.height() <= 720 and not squeezed and len(greens) == 1
        if not ok or lang in ("ru", "de"):
            check(ok, f"{lang}: окно {hint.width()}x{hint.height()} в 1280x720, одна зелёная, подписи не сжаты {squeezed}")
        w.close()
        qbox = novoe.make_question(None, dark=dark)
        qbox.show()
        settle(10)
        qh = qbox.sizeHint()
        if qh.width() > 1280 or qh.height() > 720 or lang in ("ru", "zh"):
            check(qh.width() <= 1280 and qh.height() <= 720, f"{lang}: вопрос {qh.width()}x{qh.height()} в 1280x720")
        qbox.close()
i18n.set_language("ru")

print("ИТОГ:", "все проверки пройдены" if not failures else f"{len(failures)} не пройдено")
sys.exit(1 if failures else 0)
