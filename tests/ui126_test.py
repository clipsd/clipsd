# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Интерфейс 1.26: окно текста крупное и по содержимому, один размер букв в окошке перевода, Ctrl+L переводит рамку,
подсказка режима не обрезается, полоса перевода помещается в 1280, круглые ручки рамки, настройки с прокруткой.
Сеть подменяется; распознавание настоящее (нужен Tesseract).

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/ui126_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import math
import os
import sys
import time

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
import json
import tempfile
# экран 1280x800 точек: на нём проверяется полоса перевода (по умолчанию у offscreen экран 800x600)
_cfg = os.path.join(tempfile.mkdtemp(prefix="clipsd-ui126-"), "screen.json")
with open(_cfg, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1280, "height": 800,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _cfg

from PyQt6.QtCore import QPoint, QPointF, QRect, Qt
from PyQt6.QtGui import QColor, QFontMetrics, QGuiApplication, QImage, QPainter, QPixmap
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLabel

app = QApplication(sys.argv)
from clipshot import app as appmod, ocr, translate, translate_ui, themes
from clipshot.selector import RegionSelector
failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def settle(n=6):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(15)


def wait(cond, seconds=60):
    end = time.time() + seconds
    while not cond() and time.time() < end:
        app.processEvents()
        QTest.qWait(50)
    return cond()


translate.check_mymemory_email = lambda email, cb: cb("")
translate.check_google_key = lambda key, cb: cb("")
ABOUT = {"Dear": "Уважаемая г-жа Тейлор, благодарим за заказ № 4581. Подтверждаем, что посылка Swiftpost уже едет в Фару.",
         "shipment": "Отгрузка уйдёт с нашего склада в понедельник, 23 ноября, и должна прибыть в Порту в течение четырёх рабочих дней.",
         "delivery": "Если вам нужна более ранняя доставка, сообщите нам до пятницы. Мы можем организовать экспресс-перевозку за небольшую доплату."}


class FakeEngine:
    name = "MyMemory"

    def translate(self, text, target, source=None):
        for key, ru in ABOUT.items():
            if key in text:
                return ru, "en"
        return "Перевод: " + text, "en"


translate.engines_from_config = lambda c: [FakeEngine()]
translate_ui.FloatingTranslation.request_more = lambda: None

LETTER = [["Dear Ms. Taylor,", "thank you for your order No. 4581.", "We confirm that your parcel was shipped today."],
          ["The shipment will leave our warehouse on", "Monday, 23 November, and should arrive", "in Porto within four working days."],
          ["If you need the delivery earlier, please let", "us know by Friday. We can arrange express", "transport for a small extra fee."]]


def letter(w=900, h=440):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor("#ffffff"))
    p = QPainter(img)
    f = p.font()
    f.setPixelSize(20)
    p.setFont(f)
    p.setPen(QColor("#1d2330"))
    y = 70
    for para in LETTER:
        for line in para:
            p.drawText(60, y, line)
            y += 30
        y += 34
    p.end()
    return img


# 1. Окно «Текст с картинки»: крупно, невысокое для короткого текста, не выше 60 % экрана для длинного
screen_h = QGuiApplication.primaryScreen().availableGeometry().height()
short = ocr.TextResultDialog("shipment will leave\nMonday,", "", None)
short.show()
settle()
check(short.note.font().pixelSize() >= 15, f"пояснение не мельче 15 px: {short.note.font().pixelSize()}")
check(short.edit.font().pixelSize() >= 15 and short.edit.fontMetrics().height() > short.hint.fontMetrics().height(),
      f"текст в поле {short.edit.font().pixelSize()} px крупнее оговорки")
check(short.height() < 300, f"короткий текст: окно ниже 300 px ({short.height()})")
check(short.copy_button.height() == short.close_button.height(), "«Скопировать» и «Закрыть» одной высоты")
check("Текст уже в буфере обмена" in short.note.text() and "₽" in short.hint.text(), "пояснение одной фразой, оговорка отдельной строкой")
short.set_text("Новый кусок")
check(short.edit.toPlainText() == "Новый кусок" and "Скопировано" in short.copy_button.text(), "set_text обновляет окно")
short_h = short.height()
short.close()
big = ocr.TextResultDialog("\n".join(f"Строка {i}: Отгрузка уйдёт с нашего склада." for i in range(1, 40)), "", None)
big.show()
settle()
check(big.height() <= screen_h * 0.6 + 2, f"длинный текст: не выше 60 % экрана ({big.height()} из {screen_h})")
check(big.height() > short_h, "длинный текст: окно выше, чем для короткого")
check(big.edit.verticalScrollBar().maximum() > 0, "длинный текст прокручивается в поле")
big.close()

# 2. Блок установки: команда и ссылка видны целиком
dlg = ocr.TextResultDialog("", "Распознавание не установлено.", None, ocr.install_help("missing"))
dlg.show()
settle()
blk = dlg.install
for fld in (blk.command_field, blk.url_field):
    doc = fld.document()
    check(fld.height() >= int(doc.size().height()) and fld.width() > 300, f"поле видно целиком: «{fld.text()[:30]}…»")
check(blk.command_field.font().pixelSize() >= 15, "команда установки не мельче 15 px")
dlg.close()

# 3. Редактор: подсказка режима отдельной строкой, не обрезана; уведомление не на тексте
from clipshot.editor import EditorWindow, OCR, TRANSLATE


class Ctx:
    def __init__(self, **kw):
        self.config = dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True, **kw)
        self.icon = appmod.make_icon()

    def copy_image(self, image): pass
    def notify(self, text): pass
    def save_config(self): pass


def mk_editor(**kw):
    ctx = Ctx(**kw)
    themes.apply_app(app, ctx.config)
    ed = EditorWindow(letter(), ctx, QPoint(40, 30))
    ed.present()
    settle()
    ed.set_zoom(1.0)
    return ed


ed = mk_editor()
ed.select_tool(OCR)
check(wait(lambda: ed.canvas.has_words()), "распознавание в редакторе отработало")
settle()
for mode in ("range", "marker"):
    ed.set_text_mode(mode)
    settle()
    hint = ed.text_message   # 1.29.1: сообщение режима текста живёт в фиолетовой полосе внизу
    fm = QFontMetrics(hint.font())
    check(hint.isVisible() and fm.horizontalAdvance(hint.text()) <= hint.width() - 24,
          f"режим текста «{mode}»: подсказка помещается целиком ({fm.horizontalAdvance(hint.text())} из {hint.width() - 24})")
check(not ed.info.text() or QFontMetrics(ed.info.font()).horizontalAdvance(ed.info.text()) <= ed.info.width(),
      "строка состояния внизу не обрезана")
ed.show_toast("Текст скопирован в буфер обмена")
settle()
host = ed.centralWidget()
sc_top = ed.scroll.mapTo(host, QPoint(0, 0)).y()
scroll_bottom = sc_top + ed.scroll.height()
hint_top = ed.text_bottom.mapTo(host, QPoint(0, 0)).y()
tb = ed.toast
check(tb.geometry().bottom() <= scroll_bottom and tb.geometry().bottom() < hint_top,
      "плашка у нижнего края области снимка, над строкой подсказки и нижней панелью")
check(abs(tb.geometry().center().x() - (ed.scroll.mapTo(host, QPoint(0, 0)).x() + ed.scroll.width() // 2)) <= 2,
      "плашка по центру по горизонтали")
check(wait(lambda: tb.effect.opacity() > 0.99, 3), "плашка плавно появилась (прозрачность дошла до 1)")
wait(lambda: tb.effect.opacity() > 0.99, 3)
# on a slow machine (CI) the 1.4 s of showing may already be over before the grab: hold the toast while it is measured
if not tb.isVisible():   # already shown and gone while the machine was busy: show it again for the picture
    ed.show_toast("Текст скопирован в буфер обмена", 5000)
    tb = ed.toast
    wait(lambda: tb.effect.opacity() > 0.99, 3)
held = tb.timer.isActive()
tb.timer.stop()
img = ed.grab().toImage()   # снимок всего окна: плашка с эффектом прозрачности рисуется как для человека
visible_at_grab = tb.isVisible()
if held:
    tb.timer.start(300)   # then it fades out by itself as usual
g = tb.geometry().translated(tb.parentWidget().mapTo(ed, QPoint(0, 0)))   # in the coordinates of the grabbed window
dpr = img.devicePixelRatio()
corner = img.pixelColor(round(g.left() * dpr), round(g.top() * dpr))
# the plate colour is read in the side padding (padding 9px 18px), never on a letter: in the middle of the toast the
# white bold text may fall exactly on the sampled pixel (it did on Ubuntu 22.04 with another font)
mid = img.pixelColor(round((g.left() + 10) * dpr), round(g.center().y() * dpr))
mid_r = img.pixelColor(round((g.right() - 10) * dpr), round(g.center().y() * dpr))
print("плашка:", g, "сдвиг родителя", tb.parentWidget().mapTo(ed, QPoint(0, 0)), "dpr", dpr)
plate = (48, 50, 54)   # (32, 33, 36) с прозрачностью 235/255 поверх белого поля
close_to = lambda c: all(abs(a_ - b_) <= 12 for a_, b_ in zip((c.red(), c.green(), c.blue()), plate))
check(visible_at_grab and close_to(mid) and close_to(mid_r) and not close_to(corner),
      f"углы плашки скруглены (в углу {corner.name()} не цвет плашки, у краёв посередине высоты {mid.name()}, "
      f"{mid_r.name()} цвет плашки; "
      f"плашка видна: {visible_at_grab}, таймер шёл: {held})")
check(ocr.Toast.FADE_IN == 150 and ocr.Toast.SHOW == 1400 and ocr.Toast.FADE_OUT == 400, "время плашки: 150 / 1400 / 400 мс")
check(wait(lambda: tb.effect.opacity() < 0.99, 3) and wait(lambda: not tb.isVisible(), 3), "плашка угасла и скрылась сама")
ed.select_tool(TRANSLATE)
settle()
hint = ed.tr_message   # 1.32.4: сообщение режима перевода в строке сверху; не помещается: режется многоточием
shown = QLabel.text(hint)
check((not hint.isVisible() and hint.text() in ed.tr_icon_button.toolTip())
      or (shown == hint.text() and QFontMetrics(hint.font()).horizontalAdvance(shown) <= hint.width()),
      f"режим перевода: сообщение в строке сверху показано целиком или спрятано совсем (виден в подсказке значка): «{shown}»")
ed.canvas.modified, ed.exported = False, True
ed.close()
themes.apply_app(app, {"ui_theme": "standard"})


# 4. Окошко перевода: один размер букв на все абзацы
def card_done(win):
    return win.tr_cards and win.tr_cards[0].state == "done"


crop = letter(900, 440).copy(30, 30, 560, 330)
win = translate_ui.FloatingTranslation(crop, 1.0, QRect(100, 100, 560, 330), dict(appmod.DEFAULTS, translate_view="card"), None)
win.start()
check(wait(lambda: card_done(win)), "FloatingTranslation: перевод готов")
sizes = {b["px"] for b in win.tr_cards[0].blocks}
check(len(win.tr_cards[0].blocks) >= 2 and len(sizes) <= 2, f"FloatingTranslation: абзацев {len(win.tr_cards[0].blocks)}, размеры: {sizes}")
c0 = win.tr_cards[0]
check(360 <= c0.content.width() <= 720, f"FloatingTranslation: ширина карточки {c0.content.width():.0f} в пределах 360-720")
check(14 <= c0.px_draw <= 18, f"FloatingTranslation: размер букв {c0.px_draw} в пределах 14-18")
check(c0.content.height() <= 0.6 * QGuiApplication.primaryScreen().availableGeometry().height() + 1, "FloatingTranslation: высота не больше 60 % экрана")
check(win.width() >= c0.content.right() and win.height() >= c0.content.bottom(), "окошко по карточке")
win.grab()
check("copy" in win.tr_cards[0].buttons, "на карточке кнопка «Скопировать»")
win.close()

ed = mk_editor()
ed.select_tool(TRANSLATE)
settle()
layer = ed.tr_layer
QTest.mousePress(layer, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(40, 40))
QTest.mouseMove(layer, QPoint(300, 200))
QTest.mouseMove(layer, QPoint(560, 360))
QTest.mouseRelease(layer, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(560, 360))
check(wait(lambda: layer.tr_cards and layer.tr_cards[0].state == "done"), "TranslateLayer: перевод готов")
card = layer.tr_cards[0]
sizes = {b["px"] for b in card.blocks}
check(len(card.blocks) >= 2 and len(sizes) <= 2, f"TranslateLayer: размер букв общий (кроме мелкой сноски): {sizes}")
check(card.content.toAlignedRect().contains(card.region), "TranslateLayer: вид «Поверх текста» занимает всю выделенную область")
ed.canvas.modified, ed.exported = False, True
ed.close()
themes.apply_app(app, {"ui_theme": "standard"})

# 4б. Вид «Карточкой» в редакторе: окошко FloatingTranslation с владельцем (слоем перевода)
ed = mk_editor(translate_view="card")
ed.select_tool(TRANSLATE)
settle()
layer = ed.tr_layer


def drag_layer(a, b):
    QTest.mousePress(layer, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, a)
    QTest.mouseMove(layer, QPoint((a.x() + b.x()) // 2, (a.y() + b.y()) // 2))
    QTest.mouseMove(layer, b)
    QTest.mouseRelease(layer, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, b)
    app.processEvents()


drag_layer(QPoint(40, 40), QPoint(560, 360))
check(wait(lambda: layer.floats and card_done(layer.floats[0])), "редактор, «Карточкой»: окошко с переводом готово")
fw = layer.floats[0]
fc = fw.tr_cards[0]
fw.repaint()
settle()
check(fw.owner is layer and fc.view == "card", "окошко принадлежит слою перевода редактора, вид «Карточкой»")
check(360 <= fc.content.width() <= 720, f"редактор, «Карточкой»: ширина карточки {fc.content.width():.0f} в пределах 360-720")
check(14 <= fc.px_draw <= 18, f"редактор, «Карточкой»: размер букв {fc.px_draw} в пределах 14-18")
check(fc.content.height() <= 0.6 * QGuiApplication.primaryScreen().availableGeometry().height() + 1,
      "редактор, «Карточкой»: высота не больше 60 % экрана")
layer.close_floats()
# большая область: высота по тексту, а не по области
drag_layer(QPoint(20, 20), QPoint(880, 430))
check(wait(lambda: layer.floats and card_done(layer.floats[0])), "редактор, «Карточкой», большая область: перевод готов")
fw = layer.floats[0]
bc = fw.tr_cards[0]
fw.repaint()
settle()
last_y, last_h = bc.paras[-1][1], bc.paras[-1][2]
text_h = translate_ui.TranslateMixin.HEAD_H + last_y + last_h + fw.PAD_Y + 2
check(bc.content.height() <= text_h + 2 and bc.content.height() < bc.region.height() - 20,
      f"редактор, «Карточкой», большая область: высота карточки {bc.content.height():.0f} по тексту ({text_h:.0f}), область {bc.region.height()}")
check(bc.content.width() >= 360, "редактор, «Карточкой», большая область: ширина карточки не уже 360")
ed.canvas.modified, ed.exported = False, True
ed.close()
themes.apply_app(app, {"ui_theme": "standard"})

# 5. Строка режима перевода на панели окна выделения (1.29), экран 1280: надпись помещается целиком
pm = QPixmap(1280, 720)
pm.fill(QColor("#e0e0e0"))
for engine in ("mymemory", "google"):
    sel = RegionSelector(pm, QRect(0, 0, 1280, 720))
    sel.tr_cfg, sel.tr_save = dict(appmod.DEFAULTS, translate_engine=engine), lambda: None
    sel.resize(1280, 720)
    sel.show()
    sel.enter_translate()
    settle()
    sel.grab()
    head = sel.bar_hint_text
    inner = sel._bar_layout()[1].width() - 2 * sel.BAR_PAD
    small_f = sel._bar_fonts(sel.bar_level)[1]
    small_f.setBold(True)
    ok = QFontMetrics(small_f).horizontalAdvance(head) <= inner and not head.endswith("…") and head.startswith("Режим перевода")
    check(ok, f"строка режима перевода ({engine}) на 1280: «{head}» помещается в {inner} px")
    sel.close()

# 6. Ctrl+L при выделенной рамке переводит её без повторного выделения
kept = QRect(100, 100, 300, 200)
sel = RegionSelector(pm, QRect(0, 0, 1280, 720), last_rect=kept)
sel.tr_cfg, sel.tr_save = dict(appmod.DEFAULTS), lambda: None
sel.resize(1280, 720)
sel.show()
settle()
spawned = []
sel._tr_spawn_floating = lambda r: spawned.append(QRect(r))
QTest.keyClick(sel, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier)
settle()
check(spawned == [kept] and sel.translate_mode, f"Ctrl+L с рамкой: переводится рамка {spawned}")
sel.close()
sel = RegionSelector(pm, QRect(0, 0, 1280, 720))
sel.tr_cfg, sel.tr_save = dict(appmod.DEFAULTS), lambda: None
sel.resize(1280, 720)
sel.show()
spawned = []
sel._tr_spawn_floating = lambda r: spawned.append(QRect(r))
QTest.keyClick(sel, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier)
check(not spawned and sel.translate_mode, "Ctrl+L без рамки: режим перевода, кусок выбирается мышью")
sel.close()

# 7. Круглые ручки рамки выделения
sel = RegionSelector(pm, QRect(0, 0, 1280, 720), last_rect=QRect(200, 150, 300, 200))
sel.tr_cfg, sel.tr_save = dict(appmod.DEFAULTS), lambda: None
sel.show_zoom = False   # лупа у курсора закрывала бы угол в кадре
sel.resize(1280, 720)
sel.show()
settle()
hs = sel._handles(sel.kept)
check(len(hs) == 8, f"область 300x200: 8 ручек ({len(hs)})")
check({h[0] for h in hs if h[0] in ("tl", "tr", "bl", "br")} == {"tl", "tr", "bl", "br"} and
      all(r == 8 for n, c, r in hs if len(n) == 2) and all(r == 6 for n, c, r in hs if len(n) == 1),
      "углы диаметром 16, стороны 12")
x0, y0 = sel.kept.left(), sel.kept.top()
r = sel.HANDLE_R_CORNER
check(sel._edge_at(QPoint(x0 - r, y0)) == "tl" and sel._edge_at(QPoint(x0, y0 - r)) == "tl",
      "угловая ручка берётся на расстоянии радиуса от угла")
check(sel._edge_at(QPoint(x0 - 8 - 3, y0)) == "tl" and sel._edge_at(QPoint(x0 - 8 - 12, y0 - 12)) is None,
      "зона захвата: радиус плюс запас, дальше не берётся")
xm = x0 + 150
check(sel._edge_at(QPoint(xm, y0 - 6)) == "t", "боковая ручка берётся на радиусе")
img = sel.grab().toImage()
cx, cy = sel.kept.left(), sel.kept.top()
ring = img.pixelColor(cx - 7, cy)   # обводка ручки слева от угла: вне выделения, рамки там нет
accent = QColor(appmod.DEFAULTS.get("ui_accent", "#1e78ff"))
from clipshot.selector import ACCENT as _ACC
check(abs(ring.red() - _ACC.red()) + abs(ring.green() - _ACC.green()) + abs(ring.blue() - _ACC.blue()) < 90,
      f"обводка ручки цвета рамки на окружности ручки: {ring.name()}")
close_rect = sel._corner_rects()[0]
check(all(not close_rect.adjusted(-2, -2, 2, 2).intersects(QRect(c.x() - rad, c.y() - rad, 2 * rad, 2 * rad)) for n, c, rad in hs),
      "крестик закрытия не перекрывает ручки")
sel.close()
sel = RegionSelector(pm, QRect(0, 0, 1280, 720), last_rect=QRect(200, 150, 30, 20))
sel.tr_cfg, sel.tr_save = dict(appmod.DEFAULTS), lambda: None
sel.resize(1280, 720)
sel.show()
settle()
hs = sel._handles(sel.kept)
check(len(hs) == 4, f"область 30x20: только угловые ручки ({len(hs)})")
check(sel._edge_at(QPoint(215, 160)) is None and sel.kept.contains(QPoint(215, 160)), "область 30x20: середину можно взять и перенести")
close_rect = sel._corner_rects()[0]
check(all(not close_rect.adjusted(-2, -2, 2, 2).intersects(QRect(c.x() - rad, c.y() - rad, 2 * rad, 2 * rad)) for n, c, rad in hs),
      "малая область: крестик не перекрывает ручки")
check(close_rect.left() >= sel.kept.left() + 14 + sel._size_label_width() or close_rect.top() >= sel.kept.bottom(),
      "малая область: крестик не закрывает подпись размера")
sel.grab()
sel.close()

# 9. TextResultDialog: рост и сжатие, не за край экрана
scr = QGuiApplication.primaryScreen().availableGeometry()
dlg = ocr.TextResultDialog("коротко", "", None)
dlg.show()
settle()
dlg.move(scr.left() + 100, scr.bottom() - dlg.height() - 5)
settle()
dlg.set_text("\n".join(f"Строка {i}: длинный текст для проверки роста окна." for i in range(1, 60)))
settle()
check(dlg.frameGeometry().bottom() <= scr.bottom() and dlg.frameGeometry().top() >= scr.top(),
      f"длинный текст у нижнего края: окно целиком на экране ({dlg.frameGeometry().top()}..{dlg.frameGeometry().bottom()} из {scr.bottom()})")
tall = dlg.height()
dlg.set_text("снова коротко")
settle()
check(dlg.height() < tall - 50, f"короткий текст после длинного: окно сжалось ({tall} -> {dlg.height()})")
# плашка в окне текста: над рядом кнопок, не на поле
ocr.toast(dlg)
settle()
tb = dlg.findChild(ocr.Toast, "clipsdToast")
check(tb is not None and tb.isVisible() and tb.geometry().top() >= dlg.edit.mapTo(dlg, QPoint(0, 0)).y() + dlg.edit.height() - 2,
      "плашка в окне текста лежит у ряда кнопок, не на поле текста")
dlg.close()

# 10. unify_sizes: медиана, мелкая сноска остаётся своей, не ниже 12
from PyQt6.QtCore import QRectF


def blk(px, text="Слово " * 3):
    return {"px": px, "text": text, "draw": QRectF(0, 0, 400, 200)}


b = [blk(20), blk(20), blk(20)]
translate_ui.unify_sizes(b)
check({x["px"] for x in b} == {20}, "unify_sizes: равные размеры не меняются")
b = [blk(24), blk(22), blk(10)]   # заголовок, текст и мелкая сноска
translate_ui.unify_sizes(b)
check(b[0]["px"] == b[1]["px"] == 22 and b[2]["px"] == 10, f"заголовок плюс мелкая сноска: общий {b[0]['px']}, сноска {b[2]['px']}")
b = [blk(9), blk(9), blk(9)]
translate_ui.unify_sizes(b)
check({x["px"] for x in b} == {12}, "общий размер не ниже 12 px")

# 11. _tr_cover_edges: строка, оборванная рамкой, закрывается, но не дальше полстроки; чистый зазор не трогаем
from clipshot.translate_ui import TranslateCard
ed = mk_editor()
ed.select_tool(TRANSLATE)
settle()
layer = ed.tr_layer


def covered(bottom):
    reg = QRect(40, 40, 520, bottom - 40)
    card = TranslateCard(reg)
    card.blocks = [{"rect": QRectF(reg), "bg": QColor("#ffffff")}]
    # высота строки для предела роста: 30
    card.blocks[0]["rect"] = QRectF(40, 40, 520, 30)
    return layer._tr_cover_edges(card, QRectF(reg))


grown = covered(360)     # рамка кончается над строкой «transport…», её верх торчит
check(360 < grown.bottom() <= 360 + 15.5, f"рамка оборвала строку: карточка выросла на {grown.bottom() - 360:.1f} (не больше полстроки 15)")
flat = covered(290)      # рамка кончается в пустом зазоре между абзацами
check(flat.bottom() <= 290.5, f"рамка в чистом зазоре: карточка не выросла ({flat.bottom():.1f})")
ed.canvas.modified, ed.exported = False, True
ed.close()
themes.apply_app(app, {"ui_theme": "standard"})

# 8. Настройки: прокрутка, кнопки на виду, подсказка почты, блок языков в карточке текста
from clipshot.settings import SettingsDialog
dlg = SettingsDialog(dict(appmod.DEFAULTS))
dlg.show()
settle()
area = QGuiApplication.primaryScreen().availableGeometry()
check(dlg.height() <= area.height(), f"окно настроек не выше экрана ({dlg.height()} из {area.height()})")
buttons = [b for b in dlg.findChildren(type(dlg.tr_email_check)) if b.text() in ("ОК", "Отмена", "Применить")]
check(len(buttons) == 3 and all(dlg.rect().contains(b.mapTo(dlg, QPoint(0, 0))) and b.isVisible() for b in buttons),
      "«ОК», «Отмена» и «Применить» видны")
check(dlg.scroll.widget().sizeHint().height() > dlg.scroll.viewport().height(), "карточки прокручиваются: содержимое выше окна")
fm = QFontMetrics(dlg.tr_email.font())
check(fm.horizontalAdvance(dlg.tr_email.placeholderText()) < dlg.tr_email.width() - 20,
      f"подсказка почты помещается ({fm.horizontalAdvance(dlg.tr_email.placeholderText())} из {dlg.tr_email.width()})")
dlg.close()

# 12. Окно выбора оформления: карточки одного размера, превью по центру
from clipshot.theme_chooser import ThemeChooser
ch = ThemeChooser(Ctx())
ch.show()
settle()
sizes = {(c.width(), c.height()) for c in ch.cards.values()}
check(len(sizes) == 1, f"выбор оформления: карточки одного размера {sizes}")
cards = list(ch.cards.values())
check(len({c.findChild(__import__('PyQt6.QtWidgets', fromlist=['QLabel']).QLabel, 'cardNote').height() for c in cards}) == 1,
      "подписи-пояснения одинаковой высоты")
ch.close()

# 13. Меню, «О программе», «Снимок не сохранён», тёмная карточка перевода
from clipshot.menus import ClipMenuStyle
ed = mk_editor()
menu = ed.build_context_menu(None)
check(menu.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) and bool(menu.windowFlags() & Qt.WindowType.FramelessWindowHint),
      "меню правой кнопки в стиле ClipSD (скруглённое)")
menu2 = ed.build_context_menu(ed.canvas.shapes[0]) if ed.canvas.shapes else None
check(any("Ctrl+" in a.text() for a in menu.actions()) and all(a.text().count("\t") <= 1 for a in menu.actions()),
      "в меню сочетания после табуляции (рисуются справа приглушённо)")
ed.canvas.modified, ed.exported = False, True
ed.close()
themes.apply_app(app, {"ui_theme": "standard"})
shim = type("Shim", (), {"icon": appmod.make_icon()})()
about = appmod.Clipshot.build_about(shim)
about.show()
settle()
from PyQt6.QtWidgets import QLabel as _QL, QPushButton as _QB
check(about.title.text().startswith("ClipSD ") and all(l.fontMetrics().height() >= 16 for l in about.findChildren(_QL) if l.text()),
      "«О программе»: название с версией, буквы 14 px")
check(any(b.text() == "Закрыть" for b in about.findChildren(_QB)), "«О программе»: кнопка «Закрыть»")
about.close()
from clipshot.editor import ConfirmDialog
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtCore import QEvent
cd = ConfirmDialog(None, "Снимок не сохранён", "текст", "Завершить без сохранения", "Сохранить", default_yes=False)
cd.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier))
check(cd.result() == ConfirmDialog.NO, "«Снимок не сохранён»: Enter даёт кнопку по умолчанию («Сохранить»)")
cd = ConfirmDialog(None, "Снимок не сохранён", "текст", "Завершить без сохранения", "Сохранить", default_yes=False)
cd.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
check(cd.result() == ConfirmDialog.CANCEL, "«Снимок не сохранён»: Esc отменяет")
win = translate_ui.FloatingTranslation(letter(300, 120), 1.0, QRect(50, 50, 300, 120), dict(appmod.DEFAULTS, ui_theme="pro", translate_view="card"), None)
check(win._tr_palette()["card"].lightness() < 100, "карточка перевода берёт цвета тёмной темы (не белая)")
win.close()

# 14. Меню в обеих темах: рисунок, скруглённый угол, фон из темы, отметка у выбранного пункта подменю
from clipshot.shapes import Shape, RECT
from PyQt6.QtCore import QPointF


def px14(w):
    f = w.font()
    return f.pixelSize() if f.pixelSize() > 0 else f.pointSizeF() * 96 / 72


for theme_name in ("standard", "pro"):
    ctx = Ctx()
    ctx.config["ui_theme"] = theme_name
    themes.apply_app(app, ctx.config)
    ed = EditorWindow(letter(), ctx, QPoint(40, 30))
    ed.present()
    settle()
    sh = Shape(RECT, QColor(clipshot_palette := "#d60808"), 2, QPointF(10, 10))
    sh.points = [QPointF(10, 10), QPointF(80, 60)]
    ed.canvas.shapes.append(sh)
    ed.canvas.selected = sh
    from clipshot.editor import PALETTE
    sh.color = QColor(PALETTE[0])
    menu = ed.build_context_menu(None)
    menu.popup(ed.mapToGlobal(QPoint(300, 200)))
    settle(10)
    img = menu.grab().toImage()
    bg = img.pixelColor(img.width() // 2, 4)
    check(img.pixelColor(0, 0).alpha() == 0 and bg.alpha() > 200, f"меню ({theme_name}): угол прозрачный, фон непрозрачный")
    if theme_name == "pro":
        check(bg.name() != "#262626" and bg.lightness() < 110, f"меню (тёмное): фон из темы, не старый #262626: {bg.name()}")
    else:
        check(bg.lightness() > 240, "меню (светлое): белый фон")
    menu.close()
    menu2 = ed.build_context_menu(sh)
    check(menu2.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) and len(menu2.actions()) > 5, f"меню объекта ({theme_name}) в стиле ClipSD")
    colors = next(a for a in menu2.actions() if a.text() == "Цвет").menu()
    check(colors.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground), f"подменю «Цвет» ({theme_name}) в стиле ClipSD")
    colors.popup(ed.mapToGlobal(QPoint(500, 200)))
    settle(10)
    cimg = colors.grab().toImage()
    checked = next(a for a in colors.actions() if a.isChecked())
    other = next(a for a in colors.actions() if a.menu() is None and not a.isChecked() and not a.isSeparator() and not a.icon().isNull())
    gx = colors.actionGeometry(checked)
    go = colors.actionGeometry(other)
    xx = gx.left() + 14 + 22 - 3   # левый край рамки вокруг значка выбранного пункта
    pc = cimg.pixelColor(xx, gx.center().y())
    po = cimg.pixelColor(xx, go.center().y())
    from clipshot.selector import ACCENT as _A2
    check(pc != po and abs(pc.red() - _A2.red()) + abs(pc.green() - _A2.green()) + abs(pc.blue() - _A2.blue()) < 120,
          f"выбранный пункт «Цвет» ({theme_name}) виден: рамка {pc.name()} против {po.name()}")
    colors.close()
    ed.canvas.modified, ed.exported = False, True
    ed.close()
    themes.apply_app(app, {"ui_theme": "standard"})

# «О программе»: буквы 14 px по настоящему размеру шрифта; ConfirmDialog: крестик возвращает к редактированию
about = appmod.Clipshot.build_about(type("Shim", (), {"icon": appmod.make_icon()})())
about.show()
settle()
check(all(px14(l) >= 14 for l in about.findChildren(_QL) if l.text() and l.objectName() not in ("clipTitle",)),
      "«О программе»: размер шрифта подписей не меньше 14 px")
about.close()
cd = ConfirmDialog(None, "Снимок не сохранён", "текст", "Завершить без сохранения", "Сохранить", default_yes=False)
cd.show()
cd.close_b.click()
check(cd.result() == ConfirmDialog.CANCEL, "«Снимок не сохранён»: крестик = вернуться к редактированию")

# 16. Окошко перевода: шапка над областью, если сверху есть место
top = QGuiApplication.primaryScreen().availableGeometry().top()
for gy, expect_up in ((300, True), (top + 10, False)):
    w = translate_ui.FloatingTranslation(letter(300, 120), 1.0, QRect(100, gy, 300, 120), dict(appmod.DEFAULTS, translate_view="card"), None)
    w.start()
    wait(lambda: w.tr_cards[0].state == "done")
    want = gy - w.MARGIN - (translate_ui.TranslateMixin.HEAD_H if expect_up else 0)
    check(abs(w.frameGeometry().top() - max(want, top)) <= 2, f"окошко при y={gy}: шапка {'над' if expect_up else 'не над'} областью ({w.frameGeometry().top()}, ожидалось {want})")
    w.close()

# 17. Окно Google: кнопки шага одной высоты
from clipshot import service_setup
g = service_setup.GoogleSetupDialog(None, dict(appmod.DEFAULTS), None, None)
g.show()
settle()
check(all(o.height() == c.height() == 36 and o.mapTo(g, QPoint(0, 0)).y() == c.mapTo(g, QPoint(0, 0)).y()
          for o, c, _u in g.step_buttons), "окно Google: «Скопировать ссылку» той же высоты 36 и на одной линии с соседней")
g.close()

print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено: {len(failures)}")
from clipshot.exitutil import quick_exit
quick_exit(1 if failures else 0)
