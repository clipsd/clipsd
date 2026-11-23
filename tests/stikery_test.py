# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Эмодзи и стикеры (1.36): набор Twemoji внутри программы, рисование без системного шрифта, постановка, перенос,
масштаб, поворот, отмена, поиск по названиям на 12 языках, недавние, плашки, палитра, обе темы, узкое окно.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/stikery_test.py
"""
import hashlib
import math
import os
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
sys.path.insert(0, here)
import tmpclean  # noqa: F401,E402  (временные папки этого теста убираются при его выходе)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QImage, QPainter
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
from clipshot import app as appmod, i18n, stickers
from clipshot.editor import MOVE, STICKER, TOOLS, EditorWindow
from clipshot.shapes import Shape
from clipshot.stickers_ui import StickerPalette

failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


class Ctx:
    def __init__(self):
        self.config = dict(appmod.DEFAULTS)
        self.icon = appmod.make_icon()
        self.copied = []

    def copy_image(self, image, config=None):
        self.copied.append(image)

    def notify(self, text):
        pass

    def save_config(self):
        pass


def picture(w, h, color="#3366cc"):
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(color))
    return img


def digest(img):
    return hashlib.sha256(bytes(img.constBits().asarray(img.sizeInBytes()))).hexdigest()


def settle(n=4):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(15)


def click(cv, pt):
    QTest.mouseClick(cv, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(round(pt.x() * cv.zoom), round(pt.y() * cv.zoom)))


def drag(cv, a, b):
    QTest.mousePress(cv, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(round(a.x() * cv.zoom), round(a.y() * cv.zoom)))
    QTest.mouseMove(cv, QPoint(round(b.x() * cv.zoom), round(b.y() * cv.zoom)))
    QTest.mouseRelease(cv, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(round(b.x() * cv.zoom), round(b.y() * cv.zoom)))


# --- 1. Набор внутри программы: файлы, размер, лицензия ---------------------------------------------------------
check(stickers.selfcheck() == [], "все эмодзи набора читаются (SVG внутри программы)")
check(len(stickers.EMOJI) == len(set(stickers.EMOJI)) and 60 <= len(stickers.EMOJI) <= 100,
      f"эмодзи без повторов, их {len(stickers.EMOJI)} (цель 60-100)")
files = sorted(p for p in stickers.ASSETS.glob("*.svg"))
check({p.stem for p in files} == set(stickers.EMOJI), "в папке ровно выбранные эмодзи, лишних файлов нет")
total = sum(p.stat().st_size for p in files)
check(total < 1_000_000, f"добавка к сборке {total // 1024} КБ (цель до 1-2 МБ)")
root = os.path.dirname(here)
lic = os.path.join(root, "packaging", "licenses", "Twemoji-CC-BY-4.0.txt")
check(os.path.isfile(lic) and "Attribution 4.0" in open(lic, encoding="utf-8").read()[:200], "лицензия CC BY 4.0 лежит в packaging/licenses")
sys.path.insert(0, os.path.join(root, "packaging"))
import make_notices  # noqa: E402
notice = make_notices.build("linux")
check("Twemoji" in notice and "CC-BY-4.0" in notice and "Twitter" in notice, "список сторонних компонентов: Twemoji, CC-BY-4.0, правообладатель")
check("Attribution 4.0 International" in notice, "полный текст лицензии попадает в THIRD-PARTY-NOTICES")
check(not [s for s in stickers.ALL if not stickers.valid(s)] and not stickers.valid("nope") and not stickers.valid(None), "valid() знает только свой набор")

# --- 2. Цветной эмодзи рисуется одинаково без системного шрифта -------------------------------------------------
def render_emoji(sid, side=64):
    img = QImage(side, side, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    stickers.draw(p, sid, QRectF(0, 0, side, side))
    p.end()
    return img


base_font = app.font()
reference = {sid: digest(render_emoji(sid)) for sid in stickers.EMOJI}
blank = [sid for sid in stickers.EMOJI if not any(render_emoji(sid).pixelColor(x, y).alpha() for x in range(0, 64, 4) for y in range(0, 64, 4))]
check(not blank, f"ни один эмодзи не пустой ({blank[:3]})")
same = True
for family in ("NoSuchFontFamilyXYZ", "Symbol", "serif", ""):
    for hint in (QFont.HintingPreference.PreferNoHinting, QFont.HintingPreference.PreferFullHinting):
        f = QFont(family) if family else QFont()
        f.setHintingPreference(hint)
        f.setPixelSize(7)
        app.setFont(f)
        if any(digest(render_emoji(sid)) != reference[sid] for sid in ("check", "fire", "heart", "smile", "warn", "new")):
            same = False
app.setFont(base_font)
check(same, "эмодзи побитово одинаковы при любом шрифте приложения (системный шрифт эмодзи не нужен)")
big = render_emoji("check", 256)
small = render_emoji("check", 24)
check(big.pixelColor(128, 128).alpha() == 255 or big.pixelColor(128, 128).alpha() > 200, "масштаб 256 px: значок плотный")
check(big.pixelColor(2, 2).alpha() == 0 or big.pixelColor(2, 2).alpha() < 30, "угол у скруглённого значка прозрачный")
check(small.pixelColor(12, 12).alpha() == 255, "масштаб 24 px: значок рисуется заново из вектора, середина плотная")
green = render_emoji("check").pixelColor(10, 32)
check(green.green() > green.red() and green.green() > green.blue(), f"галочка зелёная, цвет настоящий ({green.name()})")
fire = render_emoji("fire")
fc = [fire.pixelColor(x, y) for x in range(20, 44, 4) for y in range(24, 60, 4) if fire.pixelColor(x, y).alpha() > 200]
check(fc and any(c.red() > 200 and c.green() < 160 for c in fc), "огонь оранжево-красный (цветной, не однотонный)")

# --- 3. Плашки и номера: рисует программа ------------------------------------------------------------------------
os.environ["CLIPSD_LANG"] = "ru"
i18n.set_language("ru", notify=False)
check(stickers.plate_text("plate_click") == "Нажмите сюда", "плашка «Нажмите сюда» по-русски")
check(set(stickers.PLATES) >= {"plate_click", "plate_important", "plate_new", "plate_error", "plate_done"} and 6 <= len(stickers.PLATES) <= 10,
      f"плашек {len(stickers.PLATES)} (6-10), среди них нужные")
a_click, a_new = stickers.aspect("plate_click", "Нажмите сюда"), stickers.aspect("plate_new", "Новое")
check(a_click > a_new >= 1.6, f"плашка шире при длинном тексте ({a_click:.2f} > {a_new:.2f})")
check(stickers.aspect("check") == 1.0 and stickers.aspect("num3") == 1.0, "эмодзи и номер квадратные")
img = QImage(200, 60, QImage.Format.Format_ARGB32_Premultiplied)
img.fill(Qt.GlobalColor.transparent)
p = QPainter(img)
stickers.draw(p, "plate_important", QRectF(0, 0, 200, 60), QColor("#d60808"), "Важно")
p.end()
check(img.pixelColor(100, 3).name() == "#d60808" or img.pixelColor(10, 30).name() == "#d60808", "плашка залита выбранным цветом")
light = QImage(200, 60, QImage.Format.Format_ARGB32_Premultiplied)
light.fill(Qt.GlobalColor.transparent)
p = QPainter(light)
stickers.draw(p, "plate_important", QRectF(0, 0, 200, 60), QColor("#ffd800"), "Важно")
p.end()
dark_px = [light.pixelColor(x, y) for x in range(60, 140) for y in range(15, 45) if light.pixelColor(x, y).lightness() < 80]
check(bool(dark_px), "на светлой плашке текст тёмный (контраст выбирается сам)")
num = QImage(60, 60, QImage.Format.Format_ARGB32_Premultiplied)
num.fill(Qt.GlobalColor.transparent)
p = QPainter(num)
stickers.draw(p, "num4", QRectF(0, 0, 60, 60), QColor("#2db400"))
p.end()
check(num.pixelColor(8, 30).name() == "#2db400" and num.pixelColor(1, 1).alpha() == 0, "номер в кружке: круг цвета из палитры")

# --- 4. Поиск по названиям на 12 языках --------------------------------------------------------------------------
check(i18n.selfcheck() == [], "каталоги 12 языков полные (ключи есть везде)")
miss = []
for lang in i18n.LANGUAGES:
    for sid in stickers.EMOJI:
        names = stickers.names(sid, lang)
        if not names:
            miss.append((lang, sid))
check(not miss, f"у каждого эмодзи есть названия на всех 12 языках ({miss[:3]})")
bad = []
for lang in i18n.LANGUAGES:
    for sid in stickers.EMOJI:
        first = stickers.names(sid, lang)[0]
        upper = first.replace("i", "İ").upper() if lang == "tr" else first.upper()   # турецкая заглавная i это İ
        if sid not in stickers.search(first, lang) or sid not in stickers.search(upper, lang):
            bad.append((lang, sid, first))
check(not bad, f"поиск по главному названию находит свой эмодзи на каждом языке, регистр не важен ({bad[:3]})")
check(stickers.search("галочка", "ru")[0] == "check" and stickers.search("heart", "en")[0] == "heart", "ru: «галочка» → check; en: heart → heart")
check("fire" in stickers.search("огонь", "ru") and "fire" not in stickers.search("огонь", "en"), "поиск идёт только по языку запроса")
check("excl" in stickers.search("wichtig", "de") and "warn" in stickers.search("avertissement", "fr"), "de: wichtig; fr: avertissement")
check("check" in stickers.search("对勾", "zh") and "sad" in stickers.search("难过", "zh"), "zh: 对勾, 难过")
check(stickers.search("   ", "ru") == list(stickers.ALL) and stickers.search("яяяяяя", "ru") == [], "пустой запрос: все; нет совпадений: пусто")
check("plate_new" in stickers.search("новое", "ru") and "plate_error" in stickers.search("Erro", "pt"), "плашки ищутся по их тексту")
for lang in i18n.LANGUAGES:
    texts = {i18n.tr_in(lang, f"stiker.plate_{k}") for k in ("click", "important", "new", "error", "done")}
    if len(texts) != 5 or any(t.startswith("stiker.") for t in texts):
        failures.append(f"плашки {lang}")
check(not [f for f in failures if f.startswith("плашки")], "тексты плашек на 12 языках разные и переведены")

# --- 5. Недавние -------------------------------------------------------------------------------------------------
cfg = {}
check(stickers.recent(cfg) == [], "недавних нет")
for sid in ("check", "fire", "heart", "check"):
    stickers.remember(cfg, sid)
check(stickers.recent(cfg) == ["check", "heart", "fire"], f"повтор поднимается наверх, порядок: {stickers.recent(cfg)}")
for sid in stickers.EMOJI[:20]:
    stickers.remember(cfg, sid)
check(len(stickers.recent(cfg)) == stickers.RECENT_MAX and stickers.recent(cfg)[0] == stickers.EMOJI[19], "недавних не больше предела, новый первый")
cfg["sticker_recent"] = ["nope", "fire", 5, "fire", None]
check(stickers.recent(cfg) == ["fire"], "мусор в настройках отброшен")
stickers.remember(cfg, "nope")
check(stickers.recent(cfg) == ["fire"], "неизвестный код не запоминается")

# --- 6. Редактор: инструмент, постановка, перенос, масштаб, поворот, отмена ------------------------------------------
ctx = Ctx()
ed = EditorWindow(picture(600, 400), ctx, QPoint(50, 50))
ed.present()
settle()
cv = ed.canvas
check(STICKER in ed.tool_buttons, "кнопка «Стикер» есть в ряду инструментов")
check(any(t == STICKER and k == "S" for t, _g, _tip, k in TOOLS), "клавиша S")
check(not ed.tool_buttons[STICKER].icon().isNull(), "у кнопки есть значок")
check(i18n.tr("editor.tip_sticker").startswith("Стикер (S)"), "подсказка кнопки по-русски")
keys = [k for _t, _g, _tip, k in TOOLS]
check(len(keys) == len(set(keys)), "клавиши инструментов не повторяются")
ed.select_tool(STICKER, open_palette=False)
check(cv.tool == STICKER, "инструмент включён")
cv.set_sticker("check")
click(cv, QPointF(200, 150))
check(len(cv.shapes) == 1 and cv.shapes[0].kind == "sticker", "щелчок ставит стикер")
s = cv.shapes[0]
c = s.rect().center()
check(abs(c.x() - 200) < 0.6 and abs(c.y() - 150) < 0.6, f"центр стикера в точке щелчка ({c.x():.1f}, {c.y():.1f})")
check(abs(s.rect().width() - stickers.SIZES[cv.pen_size]) < 0.1, f"размер по кнопке 1-5 (уровень {cv.pen_size}: {s.rect().width():.0f})")
check(cv.selected is s, "поставленный стикер выделен (сразу видны ручки)")
check(len(s.handles()) == 5, "четыре угла и ручка поворота")
check(ctx.config.get("sticker_recent") == ["check"], "поставленный попал в недавние")
out = cv.render()
px = out.pixelColor(200, 150)
check(px.green() > px.red() + 30 and px.green() > 120, f"на готовой картинке галочка зелёная ({px.name()})")
check(out.pixelColor(100, 100).name() == "#3366cc", "вокруг стикера снимок не тронут")
cv.undo()
check(not cv.shapes and cv.render().pixelColor(200, 150).name() == "#3366cc", "отмена убирает стикер")
cv.redo()
check(len(cv.shapes) == 1 and cv.shapes[0].sticker == "check", "повтор возвращает")

# протяжка
drag(cv, QPointF(300, 100), QPointF(380, 150))
s2 = cv.shapes[-1]
check(len(cv.shapes) == 2 and abs(s2.rect().width() - 80) < 0.6 and abs(s2.rect().height() - 80) < 0.6,
      f"протяжка задаёт размер, пропорции сохранены ({s2.rect().width():.0f} × {s2.rect().height():.0f})")
check(abs(s2.rect().left() - 300) < 0.6 and abs(s2.rect().top() - 100) < 0.6, "угол протяжки в точке нажатия")
drag(cv, QPointF(500, 300), QPointF(460, 280))
s3 = cv.shapes[-1]
check(s3.rect().right() > 499 and s3.rect().bottom() > 299 and s3.rect().width() > 30, "протяжка влево-вверх работает")
cv.undo()
check(len(cv.shapes) == 2, "отмена протяжки: один шаг")

# перенос (выделенный стикер двигается любым инструментом, MOVE тоже)
ed.select_tool(MOVE, open_palette=False)
s = cv.shapes[0]   # после отмены объекты заменены копиями
before = s.rect().center()
drag(cv, QPointF(200, 150), QPointF(230, 190))
check(abs(s.rect().center().x() - (before.x() + 30)) < 0.6 and abs(s.rect().center().y() - (before.y() + 40)) < 0.6, "перенос мышью")
cv.undo()
check(abs(s.rect().center().x() - before.x()) < 0.6 or abs(cv.shapes[0].rect().center().x() - before.x()) < 0.6, "отмена переноса")
s = cv.shapes[0]
cv.select(s)

# масштаб за угол: противоположный угол стоит на месте, пропорции сохраняются
corners = s.sticker_corners()
fixed = QPointF(corners[0])
target = corners[2] + QPointF(30, 30)
cv.handle_index = None
QTest.mousePress(cv, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(round(corners[2].x()), round(corners[2].y())))
QTest.mouseMove(cv, QPoint(round(target.x()), round(target.y())))
QTest.mouseRelease(cv, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(round(target.x()), round(target.y())))
r = s.rect()
now = s.sticker_corners()
check(r.width() > 70 and abs(r.width() - r.height()) < 0.6, f"масштаб ручкой: стал больше, пропорции прежние ({r.width():.0f} × {r.height():.0f})")
check(abs(now[0].x() - fixed.x()) < 0.6 and abs(now[0].y() - fixed.y()) < 0.6, "противоположный угол остался на месте")
cv.undo()
check(abs(s.rect().width() - stickers.SIZES[cv.pen_size]) < 0.6 or abs(cv.shapes[0].rect().width() - stickers.SIZES[cv.pen_size]) < 0.6, "отмена масштаба")
s = cv.shapes[0]
cv.select(s)

# поворот за круглую ручку
knob = s.rotate_handle()
check(knob.y() < s.rect().top() - 10, "ручка поворота над верхней стороной")
right = s.rect().center() + QPointF(100, 0)   # курсор справа от центра: стикер повёрнут на 90 градусов по часовой
QTest.mousePress(cv, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(round(knob.x()), round(knob.y())))
QTest.mouseMove(cv, QPoint(round(right.x()), round(right.y())))
QTest.mouseRelease(cv, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(round(right.x()), round(right.y())))
check(abs(s.angle - 90) < 2.0, f"поворот ручкой: {s.angle:.1f}° (ждём 90°)")
kc = s.rotate_handle()
check(kc.x() > s.rect().center().x() + 20 and abs(kc.y() - s.rect().center().y()) < 2, "ручка поворота ушла вправо вместе со стикером")
cv.undo()
check(abs(cv.shapes[0].angle) < 0.01, "отмена поворота")
s = cv.shapes[0]
s.angle = 30.0
rot = cv.render()
check(rot.pixelColor(200, 150).green() > 100, "повёрнутый стикер рисуется на готовой картинке")
inside = s.rect().center() + QPointF(15, 0)
check(s.hit(inside) and not s.hit(s.rect().center() + QPointF(60, 0)), "попадание считается по повёрнутому контуру")
bb = s.bounding_rect()
check(bb.width() > s.rect().width() and bb.height() > s.rect().height(), "рамка повёрнутого стикера шире исходной")
s.angle = 0.0

# размер кнопками 1-5 и колесом
ed.select_tool(MOVE, open_palette=False)
cv.select(s)
cv.set_size(5)
check(abs(cv.shapes[0].rect().width() - stickers.SIZES[5]) < 0.6, f"кнопка размера 5: {cv.shapes[0].rect().width():.0f}")
check(abs(cv.shapes[0].rect().center().x() - 200) < 1.0, "размер меняется вокруг центра")
cv.undo()
check(abs(cv.shapes[0].rect().width() - stickers.SIZES[cv.pen_size]) < 0.6, "отмена смены размера")

# копия, удаление, порядок
cv.select(cv.shapes[0])
n = len(cv.shapes)
cv.duplicate_selected()
check(len(cv.shapes) == n + 1 and cv.shapes[-1].sticker == cv.shapes[0].sticker and cv.shapes[-1].angle == cv.shapes[0].angle, "дубликат стикера")
cv.delete_selected()
check(len(cv.shapes) == n, "удаление стикера")
cv.undo()
check(len(cv.shapes) == n + 1, "отмена удаления")
cv.undo()

# плашка: текст на языке интерфейса, цвет по умолчанию, цвет из палитры
ed.select_tool(STICKER, open_palette=False)
cv.set_sticker("plate_important")
click(cv, QPointF(400, 330))
plate = cv.shapes[-1]
check(plate.sticker == "plate_important" and plate.text == "Важно", "плашка «Важно» с русским текстом")
check(plate.color.name() == "#d60808", f"у плашки свой цвет из палитры ({plate.color.name()})")
check(plate.rect().width() > plate.rect().height() * 1.5, "плашка прямоугольная по длине текста")
ed.select_color("#1e78ff")
check(cv.shapes[-1].color.name() == "#1e78ff", "цвет из палитры перекрашивает выделенную плашку")
cv.undo()
check(cv.shapes[-1].color.name() == "#d60808", "отмена перекраски")
cv.select(None)
ed.select_color("#2db400")
click(cv, QPointF(300, 350))
check(cv.shapes[-1].color.name() == "#2db400", "цвет, выбранный до постановки, получает следующая плашка")
os.environ["CLIPSD_LANG"] = "en"   # язык из окружения важнее настройки
i18n.set_language("en", notify=False)
check(plate.text == "Важно", "текст уже поставленной плашки не меняется при смене языка")
cv.set_sticker("plate_important")
click(cv, QPointF(100, 350))
check(cv.shapes[-1].text == "Important", "новая плашка берёт язык интерфейса (английский)")
os.environ["CLIPSD_LANG"] = "ru"
i18n.set_language("ru", notify=False)
# номер в кружке
cv.set_sticker("num7")
cv.select(None)
click(cv, QPointF(80, 60))
check(cv.shapes[-1].sticker == "num7" and cv.shapes[-1].rect().width() == cv.shapes[-1].rect().height(), "номер в кружке 7: квадратный стикер")
check(cv.shapes[-1].color.name() == "#2db400", "номер берёт цвет из палитры")
check(ctx.config["sticker_recent"][0] == "num7" and "plate_important" in ctx.config["sticker_recent"], "плашки и номера тоже в недавних")

# --- 7. Палитра -----------------------------------------------------------------------------------------------------
ctx.config["sticker_recent"] = ["fire", "plate_new", "heart"]
for dark in (False, True):
    pal = StickerPalette(ed, ctx.config, dark, "fire")
    pal.show()
    settle(2)
    ids = pal.visible_ids()
    check(ids[0] == "fire" and ids[1] == "heart", f"{'тёмная' if dark else 'светлая'} тема: недавние сверху")
    check(len(ids) >= len(stickers.ALL), "в палитре весь набор")
    check(not pal.grab().isNull() and pal.width() >= 300, "палитра рисуется")
    got = []
    pal.chosen.connect(got.append)
    pal.buttons["star"].click()
    check(got == ["star"] and not pal.isVisible(), "выбор закрывает палитру и сообщает код")
    pal2 = StickerPalette(ed, ctx.config, dark)
    pal2.search.setText("огонь")
    check(pal2.visible_ids() == ["fire"], f"поиск «огонь» оставляет один эмодзи ({pal2.visible_ids()})")
    pal2.search.setText("нет такого слова")
    check(pal2.visible_ids() == [], "ничего не найдено: пусто")
    pal2.search.setText("важно")
    check("excl" in pal2.visible_ids() and "plate_important" in pal2.visible_ids(), "поиск «важно»: восклицание и плашка")
    pal2.search.setText("")
    check(pal2.visible_ids()[0] == "fire", "очистка поиска возвращает недавние")
    pal2.search.setText("heart")
    check(pal2.visible_ids() == [], "английское слово в русском интерфейсе не находит (поиск на языке интерфейса)")
    pal2.search.setText("серд")
    check(pal2.visible_ids() == ["heart"], "поиск по части слова")
    pal2.close()
    pal.close()
pal = ed.show_sticker_palette()
settle(2)
check(pal.isVisible(), "окно палитры открывается из редактора")
pal.buttons["rocket"].click()
settle(2)
check(cv.sticker_id == "rocket" and ctx.config["sticker_last"] == "rocket" and cv.tool == STICKER, "выбор в палитре: стикер и инструмент включены")
click(cv, QPointF(500, 60))
check(cv.shapes[-1].sticker == "rocket", "щелчок ставит выбранный стикер")
ed.exported = True   # без вопроса при закрытии
ed.close()

# палитра запоминает последний стикер между снимками
ed2 = EditorWindow(picture(400, 300), ctx, QPoint(50, 50))
ed2.present()
settle()
check(ed2.canvas.sticker_id == "rocket", "новое окно: последний выбранный стикер")
# --- 8. Узкое окно: «Все инструменты» -------------------------------------------------------------------------------
ed2.resize(520, 480)
settle(6)
menu = ed2.build_all_tools_menu()
check(STICKER in ed2.all_tools_rows, "«Все инструменты»: инструмент «Стикер» есть")
row = ed2.all_tools_rows[STICKER]
check(row.isEnabled(), "строка «Стикер» доступна")
ed2.select_tool(STICKER, open_palette=False)
check(ed2.canvas.tool == STICKER, "из узкого окна инструмент включается")
ed2.exported = True
ed2.close()

if failures:
    print(f"\nПРОВАЛ: {len(failures)}")
    for f in failures:
        print(" -", f)
    sys.exit(1)
print("\nИТОГ: все проверки пройдены")
