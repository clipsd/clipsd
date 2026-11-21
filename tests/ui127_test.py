# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Интерфейс 1.27: окно редактора со своей шапкой и скруглёнными углами (или с системным заголовком по настройке),
три вида рамки, состав кнопок не изменился, перевод в двух видах («Поверх текста» по умолчанию и «Карточкой»),
окошко перевода в редакторе отдельное и уходит за пределы окна. Сеть подменяется; распознавание настоящее (Tesseract).

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/ui127_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import json
import os
import sys
import tempfile
import time

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
_cfg = os.path.join(tempfile.mkdtemp(prefix="clipsd-ui127-"), "screen.json")
with open(_cfg, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1600, "height": 1000,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _cfg

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PyQt6.QtCore import QEvent
from PyQt6.QtGui import QColor, QImage, QMouseEvent, QPainter
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QToolButton

app = QApplication(sys.argv)
from clipshot import app as appmod, themes, translate, translate_ui
from clipshot import editor as editormod
from clipshot.editor import EditorWindow, TRANSLATE, MOVE, ConfirmDialog, chrome_params
from clipshot.settings import SettingsDialog
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


# Состав и порядок кнопок панелей редактора в main (версия 1.26): снято с окна ветки main; с 1.28 перевод это сдвоенная
# кнопка (две половины вместо одной «Перевести»), строки обновлены
BASELINE_MAIN = [
    ["DraggableToolButton", "tool", "", "Выделение и перемещение (V)"],
    ["DraggableToolButton", "tool", "", "Сноска (K)"],
    ["DraggableToolButton", "tool", "", "Текст (T)"],
    ["DraggableToolButton", "tool", "", "Номер (N)"],
    ["DraggableToolButton", "tool", "", "Стрелка (A)"],
    ["DraggableToolButton", "tool", "", "Стрелка в обе стороны (D)"],
    ["DraggableToolButton", "tool", "", "Свободная стрелка (F)"],
    ["DraggableToolButton", "tool", "", "Плавная линия (G)"],
    ["DraggableToolButton", "tool", "", "Линия (L)"],
    ["DraggableToolButton", "tool", "", "Прямоугольник (R)"],
    ["DraggableToolButton", "tool", "", "Эллипс (E)"],
    ["DraggableToolButton", "tool", "", "Свободная фигура (O)"],
    ["DraggableToolButton", "tool", "", "Маркер (M)"],
    ["DraggableToolButton", "tool", "", "Карандаш (P)"],
    ["DraggableToolButton", "tool", "", "Размытие (B)"],
    ["DraggableToolButton", "tool", "", "Ластик (X)"],
    ["DraggableToolButton", "tool", "", "Копировать текст (I)"],
    ["DraggableToolButton", "tool", "", "Перевести выделенное (Y)"],
    ["DraggableToolButton", "tool", "", "Обрезка (C)"],
    ["QToolButton", "action", "", "Отменить (Ctrl+Z)"],
    ["QToolButton", "action", "", "Повторить (Ctrl+Y)"],
    ["QToolButton", "action", "", "Вставить картинку поверх снимка"],
    ["QToolButton", "action", "", "Справка: знакомство (F1), обновления, о программе"],
    ["QToolButton", "action", "", "Настройки (Ctrl+,)"],
    ["QToolButton", "action", "", "Язык · Language"],   # 1.31: глобус выбора языка рядом с «?» и шестерёнкой
    ["SwatchButton", "swatch", "", "#D60808"],   # 1.32: цвета рисуются сами (квадрат с обводкой, кольцо выбранного)
    ["SwatchButton", "swatch", "", "#FF8C00"],
    ["SwatchButton", "swatch", "", "#FFD800"],
    ["SwatchButton", "swatch", "", "#2DB400"],
    ["SwatchButton", "swatch", "", "#1E78FF"],
    ["SwatchButton", "swatch", "", "#8B3DFF"],
    ["SwatchButton", "swatch", "", "#000000"],
    ["SwatchButton", "swatch", "", "#808080"],
    ["SwatchButton", "swatch", "", "#FFFFFF"],
    ["SwatchButton", "swatch", "+", "Другой цвет…"],
    ["QToolButton", "action", "", "Цвет текста в номере и сноске"],
    ["QPushButton", "", "Авто", "Белый или чёрный, смотря по заливке"],
    ["QToolButton", "", "", "#D60808"],
    ["QToolButton", "", "", "#FF8C00"],
    ["QToolButton", "", "", "#FFD800"],
    ["QToolButton", "", "", "#2DB400"],
    ["QToolButton", "", "", "#1E78FF"],
    ["QToolButton", "", "", "#8B3DFF"],
    ["QToolButton", "", "", "#000000"],
    ["QToolButton", "", "", "#808080"],
    ["QToolButton", "", "", "#FFFFFF"],
    ["QToolButton", "", "+", "Другой цвет…"],
    ["QToolButton", "size", "", "Толщина и размер текста 1 (клавиша 1)"],
    ["QToolButton", "size", "", "Толщина и размер текста 2 (клавиша 2)"],
    ["QToolButton", "size", "", "Толщина и размер текста 3 (клавиша 3)"],
    ["QToolButton", "size", "", "Толщина и размер текста 4 (клавиша 4)"],
    ["QToolButton", "size", "", "Толщина и размер текста 5 (клавиша 5)"],
    ["QToolButton", "size", "Целиком", "Задетый объект удаляется полностью"],
    ["QToolButton", "size", "Частично", "Стирает куски объектов; если объект выделен, только его"],
    ["QPushButton", "ocrButton", "Копировать текст", "Копировать текст (I): снимок распознаётся, слова подсвечиваются."],
    ["QPushButton", "trAllButton", "Перевести всё", "Перевести весь снимок (Shift+Y)"],
    ["QPushButton", "trButton", "Выделенное", "Перевести выделенное: выделите мышью текст (Y)"],
    ["QPushButton", "zoomSeg", "−", "Уменьшить масштаб (Ctrl+минус, Ctrl+колесо вниз)"],   # 1.32: масштаб одной группой
    ["QPushButton", "zoomSeg", "100%", "Вернуть масштаб 100% (Ctrl+0)"],
    ["QPushButton", "zoomSeg", "+", "Увеличить масштаб (Ctrl+плюс, Ctrl+колесо вверх)"],
    ["QPushButton", "zoomSeg", "Вписать", "Показать весь снимок в окне (Ctrl+9)"],
    ["QPushButton", "", "Подряд", "Нажмите на слово и тяните в любую сторону: выделится весь текст подряд до места, где отпустите (как на телефоне)"],
    ["QPushButton", "", "Маркер", "Ведите по нужным словам, как текстовым маркером: попадёт только то, по чему провели. Ctrl + мазок: добавить ещё кусок"],
    ["QPushButton", "light", "Сохранить", "Сохранить в файл (Ctrl+S)"],   # 1.32: лёгкие кнопки
    ["QPushButton", "light", "Скопировать", "Скопировать в буфер обмена (Ctrl+C или Enter). Окно остаётся открытым"],
    ["QPushButton", "finish", "Скопировать и закрыть", "Скопировать в буфер обмена и закрыть окно (Ctrl+Enter)"],
]


translate.check_mymemory_email = lambda email, cb: cb("")
translate.check_google_key = lambda key, cb: cb("")
ABOUT = {"Dear": "Уважаемая г-жа Тейлор, благодарим за заказ № 4581. Подтверждаем, что посылка Swiftpost уже едет в Фару.",
         "shipment": "Отгрузка уйдёт с нашего склада в понедельник, 23 ноября, и должна прибыть в Порту в течение четырёх рабочих дней.",
         "delivery": "Если вам нужна более ранняя доставка, сообщите нам до пятницы. Мы можем организовать экспресс-перевозку за небольшую доплату."}


class FakeEngine:
    name = "MyMemory"
    calls = 0   # сколько раз сервис перевода вызывали

    def translate(self, text, target, source=None):
        FakeEngine.calls += 1
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


class Ctx:
    def __init__(self, **kw):
        self.config = dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True, **kw)
        self.icon = appmod.make_icon()
        self.saved = 0

    def copy_image(self, image):
        self.clipboard = image

    def notify(self, text):
        pass

    def save_config(self):
        self.saved += 1


def mk(img=None, **kw):
    ctx = Ctx(**kw)
    themes.apply_app(app, ctx.config)
    ed = EditorWindow(img if img is not None else letter(), ctx, QPoint(60, 40))
    ed.present()
    settle()
    return ed, ctx


def hidden(w):
    """Окно закрыто (объект мог быть уже удалён: WA_DeleteOnClose)."""
    try:
        return not w.isVisible()
    except RuntimeError:
        return True


def done(ed):
    ed.canvas.modified, ed.exported = False, True
    ed.close()
    themes.apply_app(app, {"ui_theme": "standard"})


# 1. Окно без системной рамки по умолчанию, с системной при настройке
ed, ctx = mk()
check(bool(ed.windowFlags() & Qt.WindowType.FramelessWindowHint) and ed.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground),
      "по умолчанию окно без системной рамки, фон прозрачный (скруглённые углы)")
check(ed.titlebar is not None and ed.titlebar.isVisible() and ed.titlebar.label.text() == "ClipSD", "своя шапка: «ClipSD»")
check(not ctx.config["editor_system_title"] and ctx.config["editor_frame_style"] == "thin", "по умолчанию: свой заголовок, вид рамки «thin» (1.32)")
check(ed.shell.radius() == 8 and ed.shell.outer() > 0, "скругление 8 (вид А 1.32), поля под тень есть")
done(ed)
ed, _ = mk(editor_system_title=True)
check(not (ed.windowFlags() & Qt.WindowType.FramelessWindowHint) and ed.titlebar is None
      and not ed.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground),
      "с настройкой «Системный заголовок»: системная рамка, своей шапки нет")
check(ed.shell.radius() == 0 and ed.shell.outer() == 0, "системный заголовок: внешних скруглений и теней нет")
done(ed)

# 2. Кнопки своей шапки
ed, _ = mk()
tb = ed.titlebar
check([tb.min_button.toolTip(), tb.max_button.toolTip(), tb.close_button.toolTip()] == ["Свернуть", "Развернуть", "Закрыть"],
      "подсказки кнопок шапки")
mins = []
ed.showMinimized = lambda: mins.append(1)
tb.min_button.click()
check(mins == [1], "кнопка «Свернуть» сворачивает окно")
tb.max_button.click()
settle()
check(ed.isMaximized() and tb.max_button.toolTip() == "Восстановить" and ed.shell.outer() == 0 and ed.shell.radius() == 0,
      "кнопка «Развернуть»: окно развёрнуто, без полей, теней и скруглений")
check(not ed.shell.edge_at(QPointF(2, 2)), "в развёрнутом окне края не тянутся")
tb.max_button.click()
settle()
check(not ed.isMaximized() and tb.max_button.toolTip() == "Развернуть" and ed.shell.outer() > 0, "повторное нажатие восстанавливает окно")
asked = []
real_exec = ConfirmDialog.exec
ConfirmDialog.exec = lambda self: (asked.append(self.title.text()), ConfirmDialog.CANCEL)[1]
ed.canvas.modified, ed.exported = True, False
tb.close_button.click()
settle()
check(asked == ["Снимок не сохранён"] and ed.isVisible(), "закрытие своей кнопкой при несохранённых правках задаёт вопрос и не закрывает молча")
ConfirmDialog.exec = real_exec
closed = []
ed.closed.connect(closed.append)
ed.canvas.modified, ed.exported = False, True
tb.close_button.click()
settle()
check(len(closed) == 1, "закрытие без правок: окно закрылось")
themes.apply_app(app, {"ui_theme": "standard"})

# 3. Края и углы окна
ed, _ = mk()
sh = ed.shell
c = sh.card()
Edge = Qt.Edge
check(sh.edge_at(QPointF(c.left() - 3, c.center().y())) == Edge.LeftEdge, "левый край: зона захвата снаружи карточки")
check(sh.edge_at(QPointF(c.right() + 3, c.center().y())) == Edge.RightEdge, "правый край")
check(sh.edge_at(QPointF(c.center().x(), c.bottom() + 3)) == Edge.BottomEdge, "нижний край")
check(sh.edge_at(QPointF(c.left() + 2, c.top() + 2)) == (Edge.LeftEdge | Edge.TopEdge), "левый верхний угол")
check(sh.edge_at(QPointF(c.right() - 2, c.bottom() - 2)) == (Edge.RightEdge | Edge.BottomEdge), "правый нижний угол")
check(not sh.edge_at(c.center()), "середина окна не край")
# перенос за шапку: событиями через DragFilter (если системный перенос недоступен, срабатывает ручной)
start = ed.pos()
filt = ed._drag_filter
g0 = QPointF(ed.mapToGlobal(QPoint(60, 20)))
press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(60, 20), g0, Qt.MouseButton.LeftButton,
                    Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
check(filt.eventFilter(ed.titlebar, press) is True, "нажатие на шапку забирает DragFilter")
if filt.drag is not None:
    move = QMouseEvent(QEvent.Type.MouseMove, QPointF(90, 40), g0 + QPointF(30, 20), Qt.MouseButton.NoButton,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    filt.eventFilter(ed.titlebar, move)
    check(ed.pos() == start + QPoint(30, 20), "окно переносится за шапку (ручной запасной перенос DragFilter)")
    release = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(90, 40), g0 + QPointF(30, 20), Qt.MouseButton.LeftButton,
                          Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    filt.eventFilter(ed.titlebar, release)
    check(filt.drag is None, "после отпускания перенос закончен")
else:
    print("OK   системный перенос startSystemMove принял нажатие (ручной запасной путь не нужен)")
done(ed)

# 4. Состав и порядок кнопок панелей не изменились (список снят с main)
ed, _ = mk(letter(300, 200))
ed.resize(1600, ed.height())   # 1.32: узкое окно сворачивает группы и подписи; состав сверяется в широком
settle()
now = []
# 1.32: колокольчик, «?», шестерёнка и глобус живут в своей шапке окна (top_icons), а не в панели
hosts = [ed.panel, ed.bottom] + ([ed.top_icons] if not ed.panel.isAncestorOf(ed.top_icons) else [])
for host in hosts:
    for w in host.findChildren((QToolButton, QPushButton)):
        now.append([type(w).__name__, w.objectName(), w.text().strip(), w.toolTip().split("\n")[0]])
# 1.29.1: «Подряд / Маркер» переехали из нижней панели в фиолетовую полосу режима текста
# 1.31.1: «Отменить» и «Повторить» переехали в начало верхнего ряда (быстрый доступ слева от инструментов)
expected = [x for x in BASELINE_MAIN if x[2] not in ("Подряд", "Маркер")]
quick = [x for x in expected if x[3].startswith(("Отменить", "Повторить"))]
expected = quick + [x for x in expected if x not in quick]
# 1.32: кнопки шести групп (видны, когда группа свёрнута) и «⋯ Все инструменты»
expected += [["GroupButton", "group", "", t] for t in ("Стрелки и линии: Стрелка (A)", "Фигуры: Прямоугольник (R)",
             "Надписи: Текст (T)", "Рисование: Маркер (M)", "Скрыть и стереть: Размытие (B)", "Текст с картинки: Копировать текст (I)")]
expected += [["QToolButton", "more", "Все инструменты", "Все инструменты по группам, с горячими клавишами"]]
expected += [["BellButton", "bell", "", "Уведомления: новая версия, что нового, сообщения программы"]]   # 1.32: колокольчик
expected += [["QToolButton", "phone", "С телефона", "С телефона · Снять камерой или отправить картинку с телефона"]]   # 1.34
expected += [["FormButton", "group", "", "Форма снимка: скруглённые углы, овал, круг"]]   # 1.34: форма снимка
check(sorted(now) == sorted(expected) and now[:2] == quick, f"кнопки панелей: {len(now)} шт., состав как в main, отмена и повтор первыми")
if sorted(now) != sorted(expected):
    print("   лишние:", [x for x in now if x not in expected], "нет:", [x for x in expected if x not in now])
done(ed)

# 5. Вид рамки: по умолчанию «Тонкая линия со свечением», три значения сохраняются и читаются, картинки разные
dlg = SettingsDialog(dict(appmod.DEFAULTS))
check(dlg.frame_style.currentData() == "thin" and dlg.frame_style.currentText() == "Тонкая линия",
      "настройки: по умолчанию вид рамки 1 («Тонкая линия со свечением»)")
check([dlg.frame_style.itemText(i) for i in range(4)] == ["Тонкая линия", "Тонкая линия со свечением", "Толстая скруглённая", "Без цветной рамки"],
      "настройки: три вида рамки по порядку")
check(dlg.values()["editor_system_title"] is False, "настройки: «Системный заголовок» выключен по умолчанию")
for key in ("thick", "plain", "glow", "thin"):
    dlg.frame_style.setCurrentIndex(dlg.frame_style.findData(key))
    check(dlg.values()["editor_frame_style"] == key and dlg.values()["frame_style_132"] is True, f"настройки: значение {key} сохраняется")
    dlg2 = SettingsDialog(dict(appmod.DEFAULTS, editor_frame_style=key, frame_style_132=True))
    check(dlg2.frame_style.currentData() == key, f"настройки: значение {key} читается")
    dlg2.close()
dlg.frame_style.setCurrentIndex(dlg.frame_style.findData("plain"))
check(not dlg.frame.isEnabled() and dlg.frame.toolTip(), "вид 3: толщина рамки неактивна, есть подсказка")
dlg.frame_style.setCurrentIndex(dlg.frame_style.findData("thin"))
check(not dlg.frame.isEnabled() and "тонкая" in dlg.frame.toolTip(), "«Тонкая линия»: толщина рамки неактивна, есть подсказка")
dlg.frame_style.setCurrentIndex(dlg.frame_style.findData("glow"))
check(dlg.frame.isEnabled(), "вид «со свечением»: толщина рамки активна")
dlg.close()
# 1.32: «Свечение» было видом по умолчанию и записано в настройки у всех: до выбора в окне настроек 1.32 оно
# читается как «Тонкая линия»; выбранное в настройках 1.32 (frame_style_132) остаётся
from clipshot.editor import frame_style  # noqa: E402
check(frame_style({"editor_frame_style": "glow"}) == "thin" and frame_style({"editor_frame_style": "glow", "frame_style_132": True}) == "glow"
      and frame_style({"editor_frame_style": "plain"}) == "plain" and frame_style({}) == "thin", "перенос вида рамки 1.31 → 1.32")


def strip(style, theme="standard"):
    ed, _ = mk(letter(300, 200), editor_frame_style=style, ui_theme=theme, frame_style_132=True)
    img = ed.grab().toImage()
    mid = img.height() // 2
    pix = [img.pixelColor(x, mid).getRgb() for x in range(0, 40)]
    done(ed)
    return pix


A, B, C = strip("glow"), strip("thick"), strip("plain")
check(A != B and B != C and A != C, "отрисовка на рамке различается между тремя видами")
accent = QColor("#1e78ff")
check(any(abs(px[0] - accent.red()) + abs(px[1] - accent.green()) + abs(px[2] - accent.blue()) < 30 for px in A), "вид 1: на рамке цвет рамки")
check(any(abs(px[0] - accent.red()) + abs(px[1] - accent.green()) + abs(px[2] - accent.blue()) < 30 for px in B), "вид 2: на рамке цвет рамки")
check(not any(abs(px[0] - accent.red()) + abs(px[1] - accent.green()) + abs(px[2] - accent.blue()) < 60 for px in C), "вид 3: цветной рамки нет")
thin = sum(1 for px in A if abs(px[0] - accent.red()) + abs(px[1] - accent.green()) + abs(px[2] - accent.blue()) < 30)
thick = sum(1 for px in B if abs(px[0] - accent.red()) + abs(px[1] - accent.green()) + abs(px[2] - accent.blue()) < 30)
check(0 < thin < thick, f"линия вида 1 тоньше рамки вида 2 ({thin} px против {thick} px)")
# смена вида сразу в открытом окне
ed, ctx = mk(letter(300, 200))
before = ed.grab().toImage().pixelColor(int(ed.shell.card().left()) + 1, 100).getRgb()
ctx.config["editor_frame_style"] = "thick"   # 1.32: с «Тонкой линии» по умолчанию на толстую: разница у края видна
ctx.config["frame_style_132"] = True
ed.refresh_theme()
settle()
after = ed.grab().toImage().pixelColor(int(ed.shell.card().left()) + 1, 100).getRgb()
check(before != after and ed.shell.params["style"] == "thick", "смена вида рамки применяется в открытом редакторе сразу")
done(ed)
# тёмное оформление: фон панелей тёмный, на рамке нет светлых пятен
ed, _ = mk(letter(300, 200), ui_theme="pro")
img = ed.grab().toImage()
dark_ok = all(QColor(img.pixel(int(x), int(y))).lightness() < 90 or QColor(img.pixel(int(x), int(y))).alpha() < 255
              for x, y in ((ed.shell.card().left() + 10, ed.shell.card().top() + 60), (img.width() // 2, img.height() - 40)))
check(dark_ok and chrome_params(ed.ctx.config)["dark"], "тёмное оформление: панели тёмные")
done(ed)

# 5б. Флажок «Системный заголовок» действует только на новые окна: у открытого окна рамка не меняется
ed, ctx = mk()
ctx.config["editor_system_title"] = True
ed.refresh_theme()
settle()
check(ed.shell.custom() and ed.shell.radius() == 8 and ed.shell.outer() == 16 and ed.titlebar is not None
      and bool(ed.shell.edge_at(QPointF(ed.shell.card().left() - 3, ed.shell.card().center().y()))),
      "сценарий А: окно со своей шапкой после включения флажка остаётся прежним (скругления, тень, размер тянется)")
done(ed)
ed, ctx = mk(editor_system_title=True)
ctx.config["editor_system_title"] = False
ed.refresh_theme()
settle()
check(not ed.shell.custom() and ed.shell.outer() == 0 and ed.shell.radius() == 0 and ed.titlebar is None
      and not ed.shell.edge_at(QPointF(2, 2)),
      "сценарий Б: окно с системной рамкой после снятия флажка остаётся прежним (без поля тени и своего размера)")
done(ed)
dlg = SettingsDialog(dict(appmod.DEFAULTS))
check(any(l.text() == "Действует для следующего снимка" for l in dlg.findChildren(QLabel)),
      "настройки: под флажком пояснение «Действует для следующего снимка»")
dlg.close()

# 6. Перевод: вид по умолчанию «Поверх текста», переключение запоминается
check(appmod.DEFAULTS["translate_view"] == "overlay", "вид перевода по умолчанию «Поверх текста»")
ed, ctx = mk()
ed.set_zoom(1.0)
ref_render = ed.canvas.render()   # эталон снимка до включения перевода
ed.select_tool(TRANSLATE)
settle()
layer = ed.tr_layer


def drag_on(w, a, b):
    QTest.mousePress(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, a)
    QTest.mouseMove(w, QPoint((a.x() + b.x()) // 2, (a.y() + b.y()) // 2))
    QTest.mouseMove(w, b)
    QTest.mouseRelease(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, b)
    app.processEvents()


drag_on(layer, QPoint(40, 40), QPoint(560, 360))
check(wait(lambda: layer.tr_cards and layer.tr_cards[0].state == "done"), "«Поверх текста»: перевод в редакторе готов")
card = layer.tr_cards[0]
layer.repaint()
settle()
check(layer._tr_view(card) == "overlay" and not layer.floats, "«Поверх текста»: перевод лежит слоем на снимке, отдельных окон нет")
check(card.chip.isNull() and not card.buttons,
      "1.29: плашка с кнопками на снимке не рисуется (в редакторе она закрывала текст), кнопки внизу окна")
check(all(w.isVisibleTo(ed) for w in (ed.tr_lang_button, ed.tr_more_button, ed.tr_copy_button, ed.tr_top))
      and (ed.tr_show_orig.isVisibleTo(ed) or ed.tr_seg_box.isHidden())   # узкое окно: «Перевод / Оригинал» в меню «⋯»
      and not ed.panel.isVisibleTo(ed) and not ed.bottom.isVisibleTo(ed),
      "1.32.4: в строке сверху язык, «Перевод/Оригинал», «⋯» и «Скопировать перевод»; панель рисования и нижняя панель скрыты")
sizes = {b["px"] for b in card.blocks}
check(len(sizes) <= 2 and max(sizes) >= 12, f"размер букв общий по правилу 1.26 (медиана, не ниже 12): {sizes}")
# в сохранённый снимок перевод не попадает
check(layer.isVisible() and card.state == "done" and ed.canvas.render() == ref_render,
      "«Поверх текста»: слой с переводом виден, а экспорт равен эталону до перевода (перевод не в снимке)")
# обводка области не зачёркивает строки: в прямоугольнике каждого блока перевода нет цвета обводки
img_l = layer.grab().toImage()
teal_hits = 0
for bl in card.blocks:
    r = bl["draw"].toAlignedRect().adjusted(2, 2, -2, -2)
    for yy in range(max(0, r.top()), min(img_l.height(), r.bottom()), 2):
        for xx in range(max(0, r.left()), min(img_l.width(), r.right()), 2):
            c = img_l.pixelColor(xx, yy)
            if abs(c.red() - 13) + abs(c.green() - 148) + abs(c.blue() - 136) < 40 and c.alpha() > 200:
                teal_hits += 1
check(teal_hits == 0 and all(card.content.contains(bl["draw"]) for bl in card.blocks),
      "обводка охватывает область вместе со строками перевода и не пересекает текст")
# «Оригинал»: исходный текст временно виден (блоки не рисуются)
ed.tr_show_orig.click()
check(card.show_original and ed.tr_show_orig.isChecked(), "«Оригинал» (переключатель в строке сверху) включает исходный текст")
ed.tr_show_tr.click()
check(not card.show_original and ed.tr_show_tr.isChecked(), "«Перевод» возвращает перевод")
# переключатель вида: подпись, запоминание, переезд в отдельное окошко
check(ed.tr_view_overlay.isChecked() and not ed.tr_view_card.isChecked(), "в виде «Поверх текста» пункт меню «⋯» отмечен «Поверх текста»")
n_saved = ctx.saved
calls_before = FakeEngine.calls
ed.tr_view_card.trigger()
settle()
check(ctx.config["translate_view"] == "card" and ctx.saved > n_saved, "переключатель вида запоминается в настройках (translate_view)")
check(len(layer.floats) == 1 and not layer.tr_cards, "«Карточкой»: перевод ушёл в отдельное окошко, слоя нет")
win = layer.floats[0]
check(wait(lambda: win.tr_cards[0].state == "done") and win.tr_cards[0].blocks, "окошко получило готовый перевод")
settle(10)
check(FakeEngine.calls == calls_before, f"переключение вида без нового запроса в сеть (вызовов сервиса: {calls_before} до, {FakeEngine.calls} после)")
check(win.isWindow() and win.parentWidget() is ed and not (win.windowFlags() & Qt.WindowType.WindowStaysOnTopHint),
      "в виде «Карточкой» перевод: отдельное окно верхнего уровня, дочернее окну редактора, не поверх всех программ")
# сворачивание редактора прячет окошко, восстановление возвращает
ed.isMinimized = lambda: True
ed.changeEvent(QEvent(QEvent.Type.WindowStateChange))
check(not win.isVisible(), "редактор свёрнут: окошко перевода спрятано")
ed.isMinimized = lambda: False
ed.changeEvent(QEvent(QEvent.Type.WindowStateChange))
check(win.isVisible(), "редактор восстановлен: окошко перевода вернулось")
del ed.isMinimized
check(win.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating), "окошко не перехватывает фокус у редактора")
check(layer._tr_head(win.tr_cards[0])[2][2][1] == "Поверх текста", "в виде «Карточкой» на кнопке написано «Поверх текста»")
# рядом с редактором, оригинал не закрыт: справа от окна, если есть место на экране
eg = ed.frameGeometry()
screen_w = QApplication.primaryScreen().availableGeometry().width()
if eg.right() + 8 + win.width() <= screen_w:
    check(win.frameGeometry().left() >= eg.right(), f"окошко встало справа от редактора ({win.frameGeometry().left()} >= {eg.right()})")
else:
    check(win.frameGeometry().right() <= eg.left() or win.frameGeometry().intersects(eg),
          "справа нет места: окошко слева от редактора или на месте области")
# унести за пределы окна редактора
far = QPoint(eg.right() + 300, eg.top() + 100)
win.move(far)
settle()
check(not ed.geometry().intersects(win.geometry()) and win.pos() == far, "окошко переносится за пределы окна редактора")
check(ed.canvas.render() == ref_render, "«Карточкой»: окошко открыто, а экспорт равен эталону до перевода")
# обратно «Поверх текста» из окошка
win._tr_click(QPointF(win.tr_cards[0].buttons["view"].center()))
settle()
check(ctx.config["translate_view"] == "overlay" and len(layer.tr_cards) == 1 and not layer.floats,
      "переключение из окошка возвращает перевод слоем на снимок, окошко закрыто")
# новый кусок в виде «Карточкой»: сразу окошко
ctx.config["translate_view"] = "card"
drag_on(layer, QPoint(40, 330), QPoint(560, 420))
check(wait(lambda: len(layer.floats) == 1), "новое выделение в виде «Карточкой» открывает окошко")
check(wait(lambda: layer.floats and layer.floats[0].tr_cards[0].state == "done"), "окошко перевело кусок")
w2 = layer.floats[0]
# выход из режима перевода закрывает окошко
gone = []
w2.destroyed.connect(lambda *_: gone.append(1))
ed.exit_translate_mode()
settle()
check(not layer.floats and hidden(w2), "окошко закрывается вместе с выходом из режима перевода")
ed.select_tool(TRANSLATE)
drag_on(layer, QPoint(40, 330), QPoint(560, 420))
wait(lambda: len(layer.floats) == 1)
w3 = layer.floats[0]
check(w3.isVisible(), "окошко открыто перед закрытием редактора")
done(ed)
settle()
check(hidden(w3), "окошко закрывается вместе с редактором")

# 7. Окно выделения: окошко перевода в двух видах
crop = letter(900, 440).copy(30, 30, 560, 330)
from clipshot.translate_ui import FloatingTranslation
for view in ("overlay", "card"):
    cfg = dict(appmod.DEFAULTS, translate_view=view)
    saved = []
    w = FloatingTranslation(crop, 1.0, QRect(300, 200, 560, 330), cfg, lambda: saved.append(1))
    w.start()
    check(wait(lambda: w.tr_cards[0].state == "done"), f"окошко в окне выделения, вид {view}: перевод готов")
    w.repaint()
    settle()
    c0 = w.tr_cards[0]
    if view == "overlay":
        check(c0.content.toAlignedRect().contains(c0.region) and not c0.chip.intersects(QRectF(c0.region))
              and w.chip_side in ("right", "above", "below", "left"),
              f"«Поверх текста»: окошко без общей карточки, плашка снаружи области ({w.chip_side}), не на ней (1.29)")
        occupied = [b["draw"].united(b["rect"]).adjusted(-3, -3, 3, 3) for b in c0.blocks]
        free = next((QPoint(x, y) for y in range(int(c0.region.top()) + 6, int(c0.region.bottom()) - 6, 6)
                     for x in range(int(c0.region.left()) + 6, int(c0.region.right()) - 6, 6)
                     if not any(o.contains(QPointF(x, y)) for o in occupied)), None)
        check(free is not None and w.grab().toImage().pixelColor(free).alpha() == 0,
              "«Поверх текста»: между строками окошко прозрачное, снимок виден")
        w._user_moved = True   # окошко унесли мышью: область заливается целиком цветом фона
        w.repaint()
        settle()
        px = w.grab().toImage().pixelColor(free)
        bgc = c0.blocks[0]["bg"]
        check(px.alpha() == 255 and abs(px.red() - bgc.red()) + abs(px.green() - bgc.green()) + abs(px.blue() - bgc.blue()) < 8,
              "«Поверх текста»: после переноса окошка вся область залита цветом фона первого блока")
        w._user_moved = False
    else:
        check(c0.content.width() >= 360 and c0.paras, "«Карточкой»: карточка с абзацами")
    w._tr_click(QPointF(c0.buttons["view"].center()))
    settle()
    nxt = "card" if view == "overlay" else "overlay"
    check(cfg["translate_view"] == nxt and saved and w._tr_view(w.tr_cards[0]) == nxt, f"переключатель в окне выделения: {view} → {nxt}, запомнено")
    w.repaint()
    settle()
    w.close()

print()
print("ИТОГО: проверок", "ok" if not failures else f"провалено {len(failures)}")
from clipshot.exitutil import quick_exit
quick_exit(1 if failures else 0)
