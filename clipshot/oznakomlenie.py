# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Окно «Ознакомление» (слова владельца 22.11.2026, компоновка А1): отдельное обычное окно, слева список ВСЕХ функций
программы группами (новое в этой версии сверху, с меткой «Новое»), справа учебный снимок в настоящем редакторе.

Учебный режим: редактор настоящий (EditorWindow), но у него свой ctx (TrainCtx): настройки копия, запись настроек,
автосохранение, буфер обмена и уведомления выключены; «Сохранить» и «Скопировать» только говорят, что снимок учебный;
закрытие без вопроса «Снимок не сохранён». Выбор пункта включает нужный инструмент и обводит нужную кнопку (жёлтая
рамка, как в знакомстве); «Показать» проигрывает короткий пример на снимке, «Попробовать» оставляет человека делать
самому, «Сначала» возвращает снимок. Функции окна выделения и внешние (телефон) показаны учебной картинкой панели и
кнопкой «Попробовать по-настоящему», которая запускает настоящую функцию.

Состояние в config: ozn_seen [id] (пункты, которые человек уже открывал)."""

from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QImage, QMouseEvent, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QStackedWidget,
                             QAbstractButton, QVBoxLayout, QWidget)

from . import icons, novoe, otlozhit
from .i18n import tr
from .later import later
from .ozn_lesson import Cursor, Dimmer, Lesson

# --- каталог функций ----------------------------------------------------------------------------------------
# (id, группа, значок, вид, цель, пример, настоящее действие)
#   вид "tool": инструмент редактора (цель: код инструмента), "widget": кнопка редактора (цель: поле окна, как в
#   novoe.ITEMS), "panel": плитка или кнопка панели окна выделения (цель: ключ из RegionSelector.BAR_BUTTONS,
#   "window": чип «Открытые окна», "frame": вся рамка).
#   настоящее действие: "region" (окно выделения), "full" (весь экран), "phone" (окно с QR-кодом), "record".
# ПРАВИЛО ВЛАДЕЛЬЦА (23.11.2026): в «Ознакомлении» и в его списке «Новое в версии» только то, что человек может
# использовать, включить или настроить. Внутренние доработки и мелкая шлифовка интерфейса (вид "info": «нельзя показать
# на учебном снимке») и форма снимка (скругление углов, «forma») сюда не попадают; «Тень, рамка и поля» (ten_ramka) оставлена по решению владельца, её путь через меню показывается явно: tests/ozn_guide_test.py падает, если в CATALOG есть вид "info" или пункт forma (решение владельца 23.11.2026:
# в списке только то, что что-то делает: снимок, пометки, текст, телефон, сохранение/печать, закрепление, QR, пипетка, настройки).
GROUPS = ("snimok", "pometki", "text", "phone", "forma", "save", "settings")
CATALOG = (
    ("phone_tile", "phone", "phone", "panel", "phone", None, "phone"),
    ("windows", "snimok", "window", "panel", "window", None, "region"),
    ("other_area", "snimok", "region", "panel", "manual", None, "region"),
    ("phone_editor", "phone", "phone", "widget", "phone_button", None, "phone"),
    ("translate_head", "text", "translate", "widget", "tr_block|tool:translate", None, None),
    ("numbers", "pometki", "number", "tool", "number", "numbers", None),
    ("stikery", "pometki", "sticker", "tool", "sticker", "stikery", None),
    ("ten_ramka", "forma", "deco", "widget", "form_button|more_button", "ten_ramka", None),   # путь: «Форма снимка» ▾ → «Тень, рамка и поля…»
    ("region", "snimok", "region", "panel", "frame", None, "region"),
    ("full", "snimok", "fullscreen", "panel", "full", None, "full"),
    ("record", "snimok", "record", "panel", "record", None, "record"),
    ("arrows", "pometki", "arrow", "tool", "arrow", "arrows", None),
    ("shapes", "pometki", "rect", "tool", "rect", "shapes", None),
    ("text", "pometki", "text", "tool", "text", "text", None),
    ("marker", "pometki", "marker", "tool", "marker", "marker", None),
    ("blur", "pometki", "blur", "tool", "blur", "blur", None),
    ("eraser", "pometki", "eraser", "tool", "eraser", None, None),
    ("crop", "pometki", "crop", "tool", "crop", None, None),
    ("move", "pometki", "move", "tool", "move", None, None),
    ("ocr", "text", "ocr", "tool", "ocr", None, None),
    ("phone_tray", "phone", "phone", "panel", "phone", None, "phone"),
    ("undo", "save", "redo", "widget", "undo_button", "undo", None),
    ("save", "save", "save", "widget", "save_button", None, None),
    ("copy", "save", "copy", "widget", "copy_button", None, None),
    ("pechat", "save", "print", "widget", "print_button", None, None),   # 1.36
    ("settings", "settings", "settings", "widget", "settings_button", None, None),
    ("help", "settings", "help", "widget", "help_button", None, None),
    ("pdf", "save", "print", "widget", "print_button", None, None),   # 1.36: PDF: стрелка «Печать ▾» и окно «Сохранить»
    # новинки 1.36
    ("zakrepit", "snimok", "pin", "panel", "pin", None, "region"),
    ("qr_chtenie", "text", "qr", "widget", "qr_button", None, None),   # на учебном снимке нарисован QR-код
    ("pipetka", "pometki", "pipette", "tool", "pipette", None, None),
)
BY_ID = {c[0]: c for c in CATALOG}
NEW_KEYS = {c[0] for c in CATALOG if c[0] in {it[1] for it in novoe.ITEMS}}   # какие пункты бывают «новыми»

# Цвет значка на мягком квадрате (светлая, тёмная); у пунктов новинок цвета из novoe.ICON_COLORS
DEFAULT_ICON = ("#1660d0", "#7fb2ff")
ROW_H = 54
LEFT_W = 340


def _version_label(version: str) -> str:
    return ".".join(str(version).split(".")[:2])


def new_ids(cfg, version: str = None) -> list:
    """Какие пункты сейчас «Новое в версии»: после обновления то, что вышло после прежней версии; иначе новинки самой
    свежей версии таблицы novoe.ITEMS, которая не новее установленной. Порядок: как в novoe.ITEMS."""
    version = version or novoe.__version__
    items = novoe.items_since(cfg, version) or novoe.items_of(version)
    if not items:
        past = [it for it in novoe.ITEMS if novoe._key(it[0]) <= novoe._key(version)]
        if past:
            top = max(novoe._key(it[0]) for it in past)
            items = [it for it in past if novoe._key(it[0]) == top]
    return [it[1] for it in items if it[1] in BY_ID]


def new_version(cfg, version: str = None) -> str:
    version = version or novoe.__version__
    ids = set(new_ids(cfg, version))
    vers = [it[0] for it in novoe.ITEMS if it[1] in ids]
    top = max(vers, key=novoe._key) if vers else version
    return _version_label(top)


def item_title(ident: str) -> str:
    return novoe.title(ident) if ident in NEW_KEYS else tr(f"ozn.{ident}_title")


def item_line(ident: str) -> str:
    return tr(f"ozn.{ident}_text")


def item_hint(ident: str) -> str:
    return novoe.text(ident) if ident in NEW_KEYS else tr(f"ozn.{ident}_hint")


def icon_color(ident: str, icon: str, dark: bool) -> str:
    pair = novoe.ICON_COLORS.get(icon, DEFAULT_ICON)
    return pair[1 if dark else 0]


# --- учебный снимок -----------------------------------------------------------------------------------------

DEMO_W, DEMO_H = 760, 420


def demo_image(with_qr: bool = False) -> QImage:
    """Таблица продаж за неделю, как в роликах: день, заказы, выручка. Нарисована программой, личных данных нет."""
    image = QImage(DEMO_W, DEMO_H, QImage.Format.Format_RGB32)
    image.fill(QColor("#ffffff"))
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    from .themes import BLUE_BUTTON
    p.fillRect(QRect(0, 0, DEMO_W, 50), QColor(BLUE_BUTTON))
    font = QFont()
    font.setPixelSize(22)
    font.setBold(True)
    p.setFont(font)
    p.setPen(QColor("#ffffff"))
    p.drawText(QRect(24, 0, 700, 50), Qt.AlignmentFlag.AlignVCenter, tr("ozn.demo_title"))
    font.setPixelSize(17)
    p.setFont(font)
    p.fillRect(QRect(0, 66, DEMO_W, 38), QColor("#eef2f7"))
    p.setPen(QColor("#1c1f24"))
    heads = (tr("ozn.demo_day"), tr("ozn.demo_orders"), tr("ozn.demo_revenue"))
    xs = (40, 300, 520)
    for x, h in zip(xs, heads):
        p.drawText(QRect(x, 66, 200, 38), Qt.AlignmentFlag.AlignVCenter, h)
    font.setBold(False)
    p.setFont(font)
    days = tr("ozn.demo_days").split(",")
    orders = (18, 24, 21, 31, 27, 40, 35)
    for i in range(7):
        y = 104 + 40 * i
        if i % 2 == 1:
            p.fillRect(QRect(0, y, DEMO_W, 40), QColor("#f8fafc"))
        p.setPen(QColor("#33373d"))
        p.drawText(QRect(xs[0], y, 200, 40), Qt.AlignmentFlag.AlignVCenter, days[i % len(days)].strip())
        p.drawText(QRect(xs[1], y, 200, 40), Qt.AlignmentFlag.AlignVCenter, str(orders[i]))
        p.drawText(QRect(xs[2], y, 200, 40), Qt.AlignmentFlag.AlignVCenter, f"€ {orders[i] * 62:,}".replace(",", " "))
    p.setPen(QPen(QColor("#d9dee6"), 1))
    p.drawLine(0, 104, DEMO_W, 104)
    if with_qr:   # пункт «Чтение QR-кода»: настоящий код в углу учебного снимка (адрес сайта программы)
        from . import qr
        matrix = qr.encode("https://clipsd.github.io/")
        n, px = len(matrix) + 8, 5
        x0, y0 = DEMO_W - n * px - 16, DEMO_H - n * px - 16
        p.fillRect(QRect(x0, y0, n * px, n * px), QColor("#ffffff"))
        for yy, row in enumerate(matrix):
            for xx, dark in enumerate(row):
                if dark:
                    p.fillRect(x0 + (xx + 4) * px, y0 + (yy + 4) * px, px, px, QColor("#10161f"))
    p.end()
    return image


def row_y(i: int) -> float:
    return 104 + 40 * i + 20


# --- учебный ctx и учебный редактор --------------------------------------------------------------------------

class TrainCtx:
    """ctx учебного редактора: то, что редактор обычно записывает, копирует и сохраняет, здесь не делает ничего.
    Остальное (язык, настройки, окно с QR-кодом) отдаётся настоящему приложению."""

    def __init__(self, app, host):
        self._app = app
        self._host = host
        self.config = dict(app.config)
        self.config["editor_system_title"] = True    # без своей шапки и тени: редактор лежит внутри окна
        self.icon = app.icon

    def __getattr__(self, name):
        return getattr(self._app, name)

    def save_config(self, *_a):
        return None

    def autosave(self, *_a, **_k):
        return ""

    def _toast(self, text):
        """1.36.1: ничего молча не пропадает: то, что редактор сообщил или не смог сделать на учебном снимке, видно
        человеку короткой плашкой на учебном редакторе."""
        ed = getattr(self._host, "editor", None)
        try:
            if ed is not None and text:
                ed.show_toast(text)
        except RuntimeError:
            pass

    def copy_image(self, *_a, **_k):
        self._toast(tr("ozn.no_save"))   # буфер обмена человека не трогаем

    def notify(self, text=None, *_a, **_k):
        self.last_notice = text
        self._toast(text)

    last_notice = None

    def open_editor(self, *_a, **_k):
        return None

    def capture_into(self, *_a, **_k):
        self._toast(tr("ozn.hint_capture"))   # новый снимок экрана поверх учебного: в настоящем редакторе

    def open_phone(self, *_a, **_k):
        self._host.explain("phone_editor")


def make_editor_class():
    from .editor import EditorWindow

    class TrainEditor(EditorWindow):
        """Настоящий редактор в учебном режиме: ничего не сохраняет, не копирует и не спрашивает при закрытии."""
        training = True

        def __init__(self, image, ctx, host):
            self._host = host
            self._really_close = False
            super().__init__(image, ctx)

        def _toast_training(self):
            self.show_toast(tr("ozn.no_save"))

        def save_and_close(self, *_a):
            self._toast_training()
            self._host.lesson.note("save")

        def copy_and_close(self):
            self._toast_training()
            self._host.lesson.note("copy")

        def copy_to_clipboard(self):
            self._toast_training()
            self._host.lesson.note("copy")

        def print_image(self):
            """1.36.1: как в настоящем редакторе: предпросмотр учебного снимка, печать из него по выбору человека
            (на принтер уходит только по его кнопке в окне предпросмотра)."""
            self._host.lesson.note("pechat")
            super().print_image()

        def save_pdf(self):
            """PDF учебного снимка: человек сам выбирает файл; остальные настройки и список снимков не затрагиваются."""
            self.ctx.last_notice = None
            EditorWindow.save_and_close(self, "pdf")   # настоящее сохранение (учебное «Сохранить» только объясняет)
            if self.ctx.last_notice:
                self._host.lesson.note("pdf")

        def insert_from_phone(self):
            self._host.explain("phone_editor")

        def start_tour(self, *_a, **_k):
            self.show_toast(tr("ozn.hint_tour"))   # F1 и «Знакомство» в «?»: окно «Ознакомление» и есть знакомство

        def fit_size(self):                       # размер задаёт окно «Ознакомление»
            self._measure_rows()
            self._adapt_rows(max(200, self.width() - 12))

        def _align_to_origin(self):
            return None

        def _screen_area(self):
            return QGuiApplication.primaryScreen().availableGeometry()

        def really_close(self):
            self._really_close = True
            self.canvas.modified = False
            self.exported = True
            self.close()

        def closeEvent(self, event):
            if not self._really_close:
                event.ignore()
                return
            super().closeEvent(event)

    return TrainEditor


# --- учебная картинка панели окна выделения -------------------------------------------------------------------

PANEL_RECTS = {}   # где что на последней нарисованной учебной панели (точки картинки)


PANEL_OVERFLOW = []   # подписи учебной панели, которые не поместились целиком даже мелким шрифтом (тест следит: пусто)


def _fit_text(p: QPainter, rect: QRectF, text: str, align, base_px: int, color: QColor, min_px: int = 9):
    """Подпись целиком: перенос по словам, при нехватке места шрифт мельче (не ниже min_px). Не «…»."""
    flags = int(Qt.TextFlag.TextWordWrap) | int(align)
    box = QRect(0, 0, int(rect.width()), 100000)
    chosen = min_px
    for px in range(base_px, min_px - 1, -1):
        f = QFont()
        f.setPixelSize(px)
        r = QFontMetrics(f).boundingRect(box, flags, text)
        if r.width() <= rect.width() and r.height() <= rect.height():
            chosen = px
            break
    else:
        PANEL_OVERFLOW.append(text)
    f = QFont()
    f.setPixelSize(chosen)
    p.setFont(f)
    p.setPen(color)
    p.drawText(rect, flags, text)


def panel_pixmap(target: str, dark: bool, width: int = 640) -> QPixmap:
    """Панель, как после Alt+W: сверху плитки, чип «Открытые окна ▾», снизу четыре кнопки. Нужное место обведено."""
    from .dialogs import PALETTES
    from .selector import RegionSelector
    c = PALETTES[bool(dark)]
    dpr = 2
    h = 272
    pix = QPixmap(width * dpr, h * dpr)
    pix.setDevicePixelRatio(dpr)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor(c["edge"]), 1))
    p.setBrush(QColor(c["card"]))
    frame = QRectF(0.5, 0.5, width - 1, h - 1)
    p.drawRoundedRect(frame, 12, 12)
    font = QFont()
    font.setPixelSize(13)
    p.setFont(font)
    fm = QFontMetrics(font)
    marks = {}
    top = ("record", "full", "ocr", "phone", "translate", "translate_pick")
    labels = {b[0]: tr(b[1]) for b in RegionSelector.BAR_BUTTONS}
    tile_w = (width - 24 - 5 * 8) / 6
    for i, key in enumerate(top):
        r = QRectF(12 + i * (tile_w + 8), 14, tile_w, 88)
        marks[key] = r
        p.setPen(QPen(QColor(c["line"]), 1))
        p.setBrush(QColor(c["soft"]))
        p.drawRoundedRect(r, 8, 8)
        icon = {"record": "record", "full": "fullscreen", "ocr": "ocr", "phone": "phone", "translate": "translate_pick",
                "translate_pick": "translate_all"}.get(key, "info")
        col = novoe.ICON_COLORS.get(icon, DEFAULT_ICON)[1 if dark else 0]
        icons.icon(icon, col).paint(p, QRect(int(r.center().x()) - 12, int(r.top()) + 8, 24, 24))
        _fit_text(p, QRectF(r.left() + 4, r.top() + 38, r.width() - 8, 46), labels.get(key, ""),
                  Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, 13, QColor(c["text"]))
    chip = QRectF(12, 114, 200, 30)
    marks["window"] = chip
    p.setPen(QPen(QColor(c["line"]), 1))
    p.setBrush(QColor(c["soft"]))
    p.drawRoundedRect(chip, 14, 14)
    _fit_text(p, chip.adjusted(14, 0, -10, 0), tr("selector.win_chip") + " ▾", Qt.AlignmentFlag.AlignVCenter, 13, QColor(c["text"]))
    bottom = ("save", "edit", "manual", "copy")
    weights = {"save": 1.0, "edit": 1.2, "manual": 1.4, "copy": 1.65}
    total = sum(weights[k] for k in bottom)
    free = width - 24 - 3 * 8
    x = 12.0
    for key in bottom:
        w = free * weights[key] / total
        r = QRectF(x, 158, w, 54)
        x += w + 8
        marks[key] = r
        main = key == "edit"
        p.setPen(QPen(QColor("#1f8a3b" if main else c["line"]), 1))
        p.setBrush(QColor("#2db400" if main else c["soft"]))
        p.drawRoundedRect(r, 8, 8)
        _fit_text(p, r.adjusted(8, 4, -8, -4), labels.get(key, ""), Qt.AlignmentFlag.AlignCenter, 13,
                  QColor("#ffffff" if main else c["text"]))
    _fit_text(p, QRectF(12, 224, width - 24, 40), tr("ozn.panel_caption"), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
              12, QColor(c["muted"]))
    PANEL_RECTS.clear()
    PANEL_RECTS.update(marks)
    PANEL_RECTS["frame"] = frame.adjusted(4, 4, -4, -4)
    PANEL_RECTS["size"] = QSize(width, h)
    rect = frame.adjusted(4, 4, -4, -4) if target == "frame" else marks.get(target)
    if rect is not None:
        p.setPen(QPen(QColor("#ffd23f"), 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(rect).adjusted(-3, -3, 3, 3), 9, 9)
    p.end()
    return pix


# --- список функций ------------------------------------------------------------------------------------------

class Row(QAbstractButton):
    """Строка списка: значок на мягком квадрате, название и пояснение (переносятся по словам, без «…»), метка «Новое»,
    отметка «просмотрено»."""
    TEXT_X = 64
    ROW_W = LEFT_W - 30       # ширина строки в списке (поля и полоса прокрутки)
    PILL_RESERVE = 62         # место у названия под метку «Новое»
    CHECK_RESERVE = 20        # место справа под галочку

    def __init__(self, ident: str, is_new: bool, dark: bool, seen: bool):
        super().__init__()
        self.ident, self.is_new, self.dark, self.seen = ident, is_new, dark, seen
        self.studied = False   # изучено («Получилось» или показ до конца): метка «Новое» серая
        self.done = False   # «Получилось» в обучении: галочка цветом акцента
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setObjectName("oznRow")
        self.setToolTip(item_title(ident) + "\n" + item_line(ident))
        self.setAccessibleName(item_title(ident) + (". " + tr("novoe.badge") if is_new else ""))
        self._measure()

    def _fonts(self):
        tf = QFont(self.font())
        tf.setPixelSize(14)
        tf.setBold(True)
        sf = QFont(self.font())
        sf.setPixelSize(12)
        return tf, sf

    def _measure(self):
        """Размеры названия и пояснения при переносе по словам; overflow: слово не поместилось в ширину (тест следит)."""
        tf, sf = self._fonts()
        flags = int(Qt.TextFlag.TextWordWrap)
        avail = self.ROW_W - self.TEXT_X - 12
        self.title_w = avail - (self.PILL_RESERVE if self.is_new else 0) - self.CHECK_RESERVE
        self.text_w = avail - self.CHECK_RESERVE
        tr_ = QFontMetrics(tf).boundingRect(QRect(0, 0, self.title_w, 10000), flags, item_title(self.ident))
        xr = QFontMetrics(sf).boundingRect(QRect(0, 0, self.text_w, 10000), flags, item_line(self.ident))
        self.title_h, self.text_h = tr_.height(), xr.height()
        self.overflow = tr_.width() > self.title_w or xr.width() > self.text_w
        self.setFixedHeight(max(ROW_H, 9 + self.title_h + 2 + self.text_h + 9))

    def sizeHint(self):
        return QSize(self.ROW_W, self.height())

    def paintEvent(self, _e):
        from .dialogs import PALETTES
        c = PALETTES[bool(self.dark)]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 1.5, -0.5, -1.5)
        if self.isChecked():
            p.setPen(QPen(QColor(c["accent"]), 1.5))
            p.setBrush(QColor(c["soft"]))
            p.drawRoundedRect(r, 9, 9)
        elif self.underMouse() or self.hasFocus():
            if self.hasFocus():
                p.setPen(QPen(QColor(c["accent"]), 1))
            else:
                p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(c["close_hover"]))
            p.drawRoundedRect(r, 9, 9)
        d = ROW_H - 18
        box = QRectF(10, 9, d, d)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#2f3338" if self.dark else "#eceff3"))
        p.drawRoundedRect(box, 8, 8)
        icon = BY_ID[self.ident][2]
        icons.icon(icon, icon_color(self.ident, icon, self.dark)).paint(p, QRect(int(box.left()) + 7, int(box.top()) + 7, d - 14, d - 14))
        x = self.TEXT_X
        if self.is_new:
            size = novoe.badge_size(QFontMetrics(novoe.badge_font()))
            novoe.paint_badge(p, "pill", QRect(self.width() - 12 - size.width(), 9, size.width(), size.height()), self.dark, self.studied)
        tf, sf = self._fonts()
        flags = int(Qt.TextFlag.TextWordWrap) | int(Qt.AlignmentFlag.AlignTop) | int(Qt.AlignmentFlag.AlignLeft)
        p.setFont(tf)
        p.setPen(QColor(c["text"]))
        p.drawText(QRect(x, 9, self.title_w, self.title_h), flags, item_title(self.ident))
        p.setFont(sf)
        p.setPen(QColor(c["muted"]))
        p.drawText(QRect(x, 9 + self.title_h + 2, self.text_w, self.text_h), flags, item_line(self.ident))
        if self.seen or self.done:   # галочка внизу справа; «получилось»: цветом акцента, жирнее
            p.setPen(QPen(QColor(c["accent"] if self.done else c["muted"]), 2.4 if self.done else 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            cx, cy = self.width() - 18, self.height() - 16
            p.drawPolyline([QPointF(cx - 4, cy), QPointF(cx - 1, cy + 3), QPointF(cx + 4, cy - 3)])
        p.end()


# --- окно ----------------------------------------------------------------------------------------------------

class OznakomlenieWindow(QWidget):
    """Окно «Ознакомление». app: Clipshot (или объект с config, icon, save_config)."""

    def __init__(self, app, focus_new: bool = False):
        super().__init__()
        from . import themes
        self.app = app
        self.dark = themes.is_dark()
        self.rows = {}
        self.current = None
        self.editor = None
        self._gen = 0
        self._real_wait = None
        self._relang = False
        self.order = []
        self.lesson = Lesson(self)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("ClipSD: " + tr("ozn.window_title"))
        self.setWindowIcon(app.icon)
        self.setObjectName("oznWindow")
        self._build()
        self._fit_to_screen()
        self._apply_layout()
        from . import i18n, ozn_lesson
        ozn_lesson.warm_reduce_motion()
        self._off_lang = i18n.on_change(lambda _lang: QTimer.singleShot(0, self._safe_retranslate))
        QApplication.instance().installEventFilter(self)   # Esc во время обучения (lesson.escape)
        self.new_list = new_ids(app.config)
        if focus_new and self.new_list:
            later(self, 0, lambda: self.select(self.new_list[0]))

    # --- построение ---------------------------------------------------------------------------------------

    def _fit_to_screen(self):
        screen = QGuiApplication.screenAt(QGuiApplication.primaryScreen().availableGeometry().center()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        w = min(1240, area.width() - 16)
        h = min(740, area.height() - 8)
        self.setMinimumSize(min(900, w), min(440, h))
        self.resize(w, h)
        self.move(area.center() - QPoint(w // 2, h // 2))

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._keep_frame_on_screen)

    def _keep_frame_on_screen(self):
        """В5 проверки 1.35.0: высота считается без заголовка окна, а на Windows заголовок рисует система, и низ окна
        с «Готово» мог уйти под панель задач. Когда рамка уже известна, окно поднимается и при нужде укорачивается так,
        чтобы целиком (с заголовком) стоять в доступной области экрана."""
        try:
            screen = self.screen() or QGuiApplication.primaryScreen()
            area = screen.availableGeometry()
            frame = self.frameGeometry()
        except RuntimeError:
            return
        extra = frame.height() - self.height()          # заголовок и рамка; без системной рамки 0
        if extra <= 0 and area.contains(frame):
            return
        h = min(self.height(), area.height() - extra)
        if h != self.height():
            self.resize(self.width(), max(self.minimumHeight(), h))
        frame = self.frameGeometry()
        top = min(max(frame.top(), area.top()), area.bottom() - frame.height() + 1)
        left = min(max(frame.left(), area.left()), area.right() - frame.width() + 1)
        if (left, top) != (frame.left(), frame.top()):
            self.move(left, top)

    NARROW_BELOW = LEFT_W + 880 + 8   # уже этого: список и редактор по очереди (редактор уже 848 не бывает)

    @property
    def narrow(self) -> bool:
        return self.width() < self.NARROW_BELOW

    def _apply_layout(self):
        """Широкое окно: список слева, снимок справа. Узкое (1366x768 при масштабе 150 % это 910 точек): одно из двух,
        «‹ Все функции» возвращает к списку, выбор пункта переходит к снимку."""
        if not hasattr(self, "left_w"):
            return
        if self.narrow:
            self.left_w.setMinimumWidth(0)
            self.left_w.setMaximumWidth(16777215)
            self.left_w.setVisible(self._show_list)
            self.right_w.setVisible(not self._show_list)
            self.back_button.setVisible(not self._show_list)
        else:
            self.left_w.setFixedWidth(LEFT_W)
            self.left_w.show()
            self.right_w.show()
            self.back_button.hide()

    COMPACT_BELOW = 600   # ниже этого окно «низкое» (1366x768 при масштабе 150 %): описание сворачивается, снимку всё место

    @property
    def compact(self) -> bool:
        return self.height() < self.COMPACT_BELOW

    def _toggle_more(self):
        self._more = not self._more
        self._apply_compact()

    def _apply_compact(self):
        """Низкое окно: у пояснения остаётся название и кнопки, подробности по «Подробнее ▾»; учебному снимку отдано всё
        место."""
        if not hasattr(self, "hint"):
            return
        c = self.compact
        full = not c or self._more
        self.hint_title.setVisible(full)
        self.hint_text.setVisible(full)
        self.hint_line.setVisible(full)
        self.more_button.setVisible(c and self.hint.isVisible() and self.current is not None)
        self.more_button.setText(tr("ozn.less") if self._more else tr("ozn.more"))
        m = 8 if c else 16
        self.right_w.layout().setContentsMargins(m, 8 if c else 14, m, 6 if c else 12)
        self.right_w.layout().setSpacing(6 if c else 10)
        self._place_next()

    def _to_list(self):
        self._show_list = True
        self._apply_layout()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_layout()
        self._apply_compact()

    def _qss(self) -> str:
        from .dialogs import PALETTES, style
        c = PALETTES[self.dark]
        return style(self.dark) + f"""
QWidget#oznWindow {{ background: {c['card']}; }}
QWidget#oznLeft {{ background: {c['field']}; border-right: 1px solid {c['line']}; }}
QScrollArea#oznScroll, QScrollArea#oznScroll > QWidget > QWidget {{ background: transparent; border: none; }}
QLabel#oznGroup {{ color: {c['muted']}; font-size: 12px; font-weight: bold; padding: 10px 8px 2px 8px; }}
QFrame#oznHint {{ background: {c['soft']}; border: 1px solid {c['edge']}; border-radius: 10px; }}
QLabel#oznHintTitle {{ font-size: 16px; font-weight: bold; color: {c['text']}; }}
QLabel#oznHintText {{ font-size: 13px; color: {c['text']}; }}
QLabel#oznHintLine {{ font-size: 12px; color: {c['muted']}; }}
QLabel#oznWelcomeTitle {{ font-size: 16px; font-weight: bold; color: {c['text']}; }}
QLabel#oznWelcomeText {{ font-size: 13px; color: {c['muted']}; }}
QLabel#oznOk {{ font-size: 15px; font-weight: bold; color: {'#7be08f' if self.dark else '#157a40'}; }}
QPushButton#oznLink {{ border: none; background: transparent; color: {c['link']}; font-size: 12px; text-decoration: underline; padding: 0; }}
QPushButton#oznBtn {{ background: {c['card']}; color: {c['text']}; border: 1px solid {c['line']}; border-radius: 8px;
    padding: 7px 14px; font-size: 13px; }}
QPushButton#oznBtn:hover {{ background: {c['close_hover']}; }}
QPushButton#oznBtn:disabled {{ color: {c['muted']}; }}
"""

    def _build(self):
        self.setStyleSheet(self._qss())
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        left = QWidget()
        left.setObjectName("oznLeft")
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 6, 0, 6)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("oznScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(8, 0, 8, 8)
        bl.setSpacing(2)
        seen = set(self.app.config.get("ozn_seen") or [])
        new = new_ids(self.app.config)
        self.new_list = new
        self.group_labels = []
        self.order = []

        def add_group(text, idents, is_new):
            lab = QLabel(text)
            lab.setObjectName("oznGroup")
            lab.setTextFormat(Qt.TextFormat.PlainText)
            bl.addWidget(lab)
            self.group_labels.append(lab)
            for ident in idents:
                row = Row(ident, is_new, self.dark, ident in seen)
                row.done = ident in set(self.app.config.get("ozn_done") or [])
                row.studied = ident in set(self.app.config.get("ozn_studied") or [])
                self.order.append(ident)
                row.clicked.connect(lambda _c=False, i=ident: self.select(i))
                self.rows[ident] = row
                bl.addWidget(row)

        if new:
            add_group(tr("ozn.group_new", version=new_version(self.app.config)), new, True)
        for g in GROUPS:
            idents = [c[0] for c in CATALOG if c[1] == g and c[0] not in new]
            if idents:
                add_group(tr(f"ozn.g_{g}"), idents, False)
        bl.addStretch(1)
        self.scroll.setWidget(body)
        ll.addWidget(self.scroll, 1)
        self.left_foot = QHBoxLayout()   # «Готово» и «Отложить ▾» живут под списком: не там, где ищут «Следующая функция»
        self.left_foot.setContentsMargins(8, 4, 8, 2)
        self.left_foot.setSpacing(8)
        ll.addLayout(self.left_foot)
        root.addWidget(left)
        self.left_w = left

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(16, 14, 16, 12)
        rl.setSpacing(10)
        self.hint = QFrame()
        self.hint.setObjectName("oznHint")
        hl = QVBoxLayout(self.hint)
        hl.setContentsMargins(14, 10, 14, 12)
        hl.setSpacing(4)
        self.hint_title = QLabel()
        self.hint_title.setObjectName("oznHintTitle")
        self.hint_title.setWordWrap(True)
        self.hint_text = QLabel()
        self.hint_text.setObjectName("oznHintText")
        self.hint_text.setWordWrap(True)
        self.hint_line = QLabel()
        self.hint_line.setObjectName("oznHintLine")
        self.hint_line.setWordWrap(True)
        for lab in (self.hint_title, self.hint_text, self.hint_line):
            lab.setTextFormat(Qt.TextFormat.PlainText)
            hl.addWidget(lab)
        self._more = False
        self.more_button = QPushButton(tr("ozn.more"))
        self.more_button.setObjectName("oznLink")
        self.more_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.more_button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.more_button.clicked.connect(self._toggle_more)
        self.more_button.hide()
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.back_button = QPushButton("‹ " + tr("ozn.back_list"))
        self.back_button.setObjectName("oznBtn")
        self.back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_button.clicked.connect(self._to_list)
        self.back_button.hide()
        self.show_button = QPushButton(tr("ozn.show"))
        self.show_button.setObjectName("oznBtn")
        self.try_button = QPushButton(tr("ozn.skip"))
        self.try_button.setObjectName("oznBtn")
        self.real_button = QPushButton(tr("ozn.real"))
        self.real_button.setObjectName("oznBtn")
        self.reset_button = QPushButton(tr("ozn.reset"))
        self.reset_button.setObjectName("oznBtn")
        self.next_button = QPushButton(tr("ozn.next") + " ›")
        self.next_button.setObjectName("oznBtn")
        self.next_button.clicked.connect(self.next_function)
        self.result_label = QLabel()
        self.result_label.setObjectName("oznOk")
        self.result_label.setTextFormat(Qt.TextFormat.PlainText)
        self.result_label.hide()
        hl.insertWidget(hl.count(), self.result_label)
        for b in (self.show_button, self.try_button, self.real_button, self.reset_button, self.next_button):
            b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            if b is not self.next_button:
                buttons.addWidget(b)
        buttons.addWidget(self.more_button)
        buttons.addStretch(1)
        buttons.addWidget(self.next_button)   # справа: куда смотрит человек, который ищет «дальше»
        self.done_button = QPushButton(tr("ozn.done"))
        self.done_button.setObjectName("oznBtn")
        buttons.insertWidget(0, self.back_button)   # «‹ Все функции» в узком окне: в одном ряду с кнопками
        hl.addSpacing(4)
        hl.addLayout(buttons)
        self.buttons_row = buttons
        self.next_row = QHBoxLayout()   # запасной ряд: когда кнопки в один ряд не помещаются, «Следующая функция ›» уходит сюда
        self.next_row.setContentsMargins(0, 0, 0, 0)
        self.next_row.addStretch(1)
        hl.addLayout(self.next_row)
        self._next_below = False
        self.show_button.clicked.connect(self.play)
        self.try_button.clicked.connect(self.try_myself)
        self.real_button.clicked.connect(self.try_real)
        self.reset_button.clicked.connect(self.reset)
        self.done_button.clicked.connect(self.close)
        self.snooze_button = otlozhit.SnoozeButton(self.dark)
        self.snooze_button.chosen.connect(self.snooze)
        self.left_foot.addWidget(self.done_button)
        self.left_foot.addWidget(self.snooze_button)
        self.left_foot.addStretch(1)
        rl.addWidget(self.hint)

        self.stack = QStackedWidget()
        welcome = QWidget()
        wl = QVBoxLayout(welcome)
        wl.addStretch(1)
        wt = QLabel(tr("ozn.welcome_title"))
        wt.setObjectName("oznWelcomeTitle")
        wt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wx = QLabel(tr("ozn.welcome_text"))
        wx.setObjectName("oznWelcomeText")
        wx.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wx.setWordWrap(True)
        wl.addWidget(wt)
        wl.addWidget(wx)
        wl.addStretch(1)
        self.welcome_title, self.welcome_text = wt, wx
        self.stack.addWidget(welcome)             # 0
        self.editor_host = QWidget()
        eh = QVBoxLayout(self.editor_host)
        eh.setContentsMargins(0, 0, 0, 0)
        self.stack.addWidget(self.editor_host)    # 1
        panel_page = QWidget()
        pl = QVBoxLayout(panel_page)
        pl.addStretch(1)
        self.panel_label = QLabel()
        self.panel_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pl.addWidget(self.panel_label)
        pl.addStretch(1)
        self.stack.addWidget(panel_page)          # 2
        info_page = QWidget()
        il = QVBoxLayout(info_page)
        il.addStretch(1)
        self.info_label = QLabel(tr("ozn.info_note"))
        self.info_label.setObjectName("oznWelcomeText")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info_label.setWordWrap(True)
        il.addWidget(self.info_label)
        il.addStretch(1)
        self.stack.addWidget(info_page)           # 3
        rl.addWidget(self.stack, 1)
        root.addWidget(right, 1)
        self.right_w = right
        self._show_list = True
        self._set_buttons(False, False, False, False)
        self.hint.hide()   # до выбора пункта подсказки нет: на экране только приглашение выбрать

    def _set_buttons(self, show, try_, real, reset):
        self.show_button.setVisible(show)
        self.try_button.setVisible(try_)
        self.real_button.setVisible(real)
        self.reset_button.setVisible(reset)
        self._update_next(False)

    @staticmethod
    def is_panel(ident) -> bool:
        return BY_ID[ident][3] == "panel"

    # --- учебный редактор -----------------------------------------------------------------------------------

    def _make_editor(self):
        from . import notifications
        if self.editor is not None:
            self._drop_editor()
        cls = make_editor_class()
        ctx = TrainCtx(self.app, self)
        qr = self.current == "qr_chtenie"
        ed = cls(demo_image(with_qr=qr), ctx, self)
        ed.qr_demo = qr   # чтение QR на учебном снимке включено только в пункте про QR
        if qr:
            ed._qr_schedule()
        notifications.register(self.app)   # EditorWindow запоминает свой ctx как «приложение»: вернуть настоящее
        ed.setParent(self.editor_host, Qt.WindowType.Widget)
        ed.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.editor_host.layout().addWidget(ed)
        ed.show()
        self.editor = ed
        ed.installEventFilter(self)
        self.lesson.attach(ed)
        QTimer.singleShot(0, self._settle_editor)
        for _ in range(3):   # размеры и масштаб устанавливаются до первого шага: окошко берёт настоящие координаты
            QApplication.processEvents()
        self._settle_editor()
        return ed

    def rebuild_editor(self):
        """Свежий учебный снимок (после показа, «Сначала»): слои обучения переезжают на новый редактор."""
        self.lesson.detach()
        self._make_editor()

    def _settle_editor(self):
        ed = self.editor
        if ed is None:
            return
        try:
            ed.fit_size()
            ed.zoom_fit()
        except RuntimeError:
            pass

    def _drop_editor(self):
        self.lesson.detach()
        ed, self.editor = self.editor, None
        if ed is not None:
            try:
                ed.really_close()
            except RuntimeError:
                pass

    def eventFilter(self, obj, event):
        if obj is self.editor and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._settle_editor)
        t = event.type()
        if t in (QEvent.Type.KeyPress, QEvent.Type.ShortcutOverride) and self.lesson.active:
            if event.key() == Qt.Key.Key_Escape and (self.isActiveWindow() or QApplication.activeWindow() is self):
                if t == QEvent.Type.ShortcutOverride:
                    event.accept()   # Esc наш: сочетания редактора не срабатывают
                    return False
                self.lesson.escape()
                return True
        return False

    def _person_acted(self):
        self.hint_line.setText("")

    # --- слои обучения на учебной картинке панели -------------------------------------------------------------

    def _panel_layers(self):
        page = self.stack.widget(2)
        if getattr(self, "panel_dimmer", None) is None:
            self.panel_dimmer = Dimmer(page, self.dark, self.lesson.skip)
            self.panel_cursor = Cursor(page)
        return page

    def panel_hole(self):
        """Где на странице панели нужное место (рамка вокруг плитки), координаты страницы."""
        ident = self.current
        if ident is None or not self.is_panel(ident):
            return None
        target = BY_ID[ident][4]
        r = PANEL_RECTS.get(target)
        size = PANEL_RECTS.get("size")
        if r is None or size is None:
            return None
        label = self.panel_label
        x0 = label.x() + (label.width() - size.width()) // 2
        y0 = label.y() + (label.height() - size.height()) // 2
        return QRect(int(x0 + r.left()), int(y0 + r.top()), int(r.width()), int(r.height()))

    def show_panel_dim(self, on: bool):
        if not on:
            if getattr(self, "panel_dimmer", None) is not None:
                self.panel_dimmer.hide()
                self.panel_cursor.hide()
            self.real_button.setStyleSheet("")
            return
        if self.current is None or not self.is_panel(self.current):
            return
        self._panel_layers()
        phase = self.lesson.phase
        caption = tr("ozn.step_panel") if phase == "demo" else tr("ozn.step_real")
        self.panel_dimmer.show_step(0, 1, caption, self.panel_hole)
        if phase != "demo":
            ring = "#ffd23f" if self.dark else "#a85d00"   # рамка не слабее 3:1 к фону карточки в обеих темах
            self.real_button.setStyleSheet("QPushButton { border: 3px solid %s; }" % ring)

    def refresh_panel_dim(self):
        d = getattr(self, "panel_dimmer", None)
        if d is not None and d.isVisible():
            d.refresh()

    def set_result(self, text: str):
        self.result_label.setText(text)
        self.result_label.setVisible(bool(text))

    def lesson_done(self, ident):
        """Получилось: подпись, галочка у пункта, кнопка «Следующая функция»."""
        self.mark_studied(ident)
        self.set_result(tr("ozn.success"))
        self.hint_line.setText("")
        done = list(self.app.config.get("ozn_done") or [])
        if ident not in done:
            done.append(ident)
            self.app.config["ozn_done"] = done
            save = getattr(self.app, "save_config", None)
            if callable(save):
                save()
        row = self.rows.get(ident)
        if row is not None:
            row.done = True
            row.update()
        self.try_button.setVisible(False)
        self._update_next(True)

    def _update_next(self, primary: bool):
        """«Следующая функция ›» есть у каждого пункта, кроме последнего: и у пояснений, и у учебных. Главной (зелёной)
        она становится, когда другой главной кнопки нет или урок пройден."""
        i = self.order.index(self.current) if self.current in self.order else -1
        b = self.next_button
        b.setVisible(0 <= i < len(self.order) - 1)
        self._lesson_finished = bool(primary)
        self._place_next()
        self.refresh_primary()

    def refresh_primary(self):
        """1.36.1 (слова владельца 23.11.2026: «все кнопки зелёные»): зелёная (clipPrimary) ровно одна, следующее ожидаемое
        действие: до показа «Показать»; после показа и пока человек пробует «Попробовать по-настоящему» (если оно есть);
        после «Получилось» (и когда других действий нет) «Следующая функция ›». Остальные: контурные (oznBtn)."""
        phase = getattr(self.lesson, "phase", "off")
        finished = getattr(self, "_lesson_finished", False) or phase == "done"
        visible = [b for b in (self.show_button, self.real_button, self.next_button) if not b.isHidden()]
        main = None
        if finished and not self.next_button.isHidden():
            main = self.next_button
        elif not self.real_button.isHidden() and phase in ("you", "free"):
            main = self.real_button
        elif not self.show_button.isHidden():
            main = self.show_button
        elif not self.real_button.isHidden():
            main = self.real_button
        elif not self.next_button.isHidden():
            main = self.next_button
        for b in (self.show_button, self.real_button, self.next_button):
            name = "clipPrimary" if b is main else "oznBtn"
            if b.objectName() != name:
                b.setObjectName(name)
                b.style().unpolish(b)
                b.style().polish(b)

    def _place_next(self):
        """Все кнопки в одном ряду, «Следующая функция ›» справа. Не помещаются (узкое окно, длинные подписи): она
        переходит в ряд ниже, справа, и не обрезается."""
        b = self.next_button
        row = [self.buttons_row.itemAt(i).widget() for i in range(self.buttons_row.count())]
        row = [w for w in row if w is not None and w is not b and not w.isHidden()]
        need = sum(w.sizeHint().width() for w in row) + b.sizeHint().width() + self.buttons_row.spacing() * len(row)
        have = self.right_w.width() - 2 * 16 - 28   # поля правой части и подсказки
        below = need > have
        if below == self._next_below and (b.parentWidget() is not None):
            return
        self._next_below = below
        if below:
            self.buttons_row.removeWidget(b)
            self.next_row.addWidget(b)
        else:
            self.next_row.removeWidget(b)
            self.buttons_row.addWidget(b)

    def mark_studied(self, ident):
        """Функцию изучили: у неё «Получилось» или показ досмотрен до конца. Метка «Новое» в списке становится серой и
        такой остаётся после перезапуска (config ozn_studied)."""
        studied = list(self.app.config.get("ozn_studied") or [])
        if ident not in studied:
            studied.append(ident)
            self.app.config["ozn_studied"] = studied
            save = getattr(self.app, "save_config", None)
            if callable(save):
                save()
        row = self.rows.get(ident)
        if row is not None and not row.studied:
            row.studied = True
            row.update()

    def lesson_skipped(self):
        self.hint_line.setText(tr("ozn.try_now"))
        self.try_button.setVisible(False)
        if self.editor is not None:
            self.editor.canvas.setFocus()

    def next_function(self):
        i = self.order.index(self.current) if self.current in self.order else -1
        if 0 <= i < len(self.order) - 1:
            self.select(self.order[i + 1])
            row = self.rows.get(self.current)
            if row is not None:
                self.scroll.ensureWidgetVisible(row)

    # --- выбор пункта ---------------------------------------------------------------------------------------

    def select(self, ident: str):
        if ident not in BY_ID:
            return
        self.lesson.stop_all()
        self.current = ident
        self._show_list = False
        self._apply_layout()
        _i, _g, _icon, kind, target, demo, real = BY_ID[ident]
        for k, row in self.rows.items():
            row.setChecked(k == ident)
        self._mark_seen(ident)
        self.hint.show()
        self.set_result("")
        self.hint_title.setText(item_title(ident))
        self.hint_text.setText(item_hint(ident))
        self.hint_line.setText("")
        self._apply_compact()
        if kind == "info":
            self.stack.setCurrentIndex(3)
            self._set_buttons(False, False, False, False)
            self.mark_studied(ident)   # показывать нечего: открыли и прочитали, метка «Новое» серая
            self._apply_compact()
            return
        if kind == "panel":
            self.panel_label.setPixmap(panel_pixmap(target, self.dark))
            self.stack.setCurrentIndex(2)
            self.hint_line.setText(tr("ozn.panel_note"))
            self._set_buttons(True, True, bool(real), False)
            QApplication.processEvents()
            self.lesson.start(ident)
            return
        if self.editor is not None and (ident == "qr_chtenie") != bool(getattr(self.editor, "qr_demo", False)):
            self._drop_editor()   # учебный снимок с QR-кодом только у пункта про QR
        if self.editor is None:
            self._make_editor()
        self.stack.setCurrentIndex(1)
        self._set_buttons(True, True, bool(real), True)
        self.hint_line.setText(tr("ozn.show_hint"))
        self.lesson.start(ident)

    def _mark_seen(self, ident):
        seen = list(self.app.config.get("ozn_seen") or [])
        if ident not in seen:
            seen.append(ident)
            self.app.config["ozn_seen"] = seen
            save = getattr(self.app, "save_config", None)
            if callable(save):
                save()
        row = self.rows.get(ident)
        if row is not None and not row.seen:
            row.seen = True
            row.update()

    def explain(self, ident):
        """Кнопка редактора, которая в учебном режиме открывает внешнее (фото с телефона): пояснение и настоящая кнопка."""
        if ident == self.current:
            self.lesson.note(ident)   # человек нажал именно её: шаг сделан
        elif ident in self.rows:
            self.select(ident)

    # --- кнопки ---------------------------------------------------------------------------------------------

    def try_myself(self):
        """«Пропустить»: затемнения нет, человек делает сам."""
        self.lesson.skip()

    def reset(self):
        """«Сначала»: свежий учебный снимок, тот же пункт."""
        ident = self.current
        self.lesson.stop_all()
        self._drop_editor()
        if ident:
            self.select(ident)

    def try_real(self):
        ident = self.current
        if ident is None:
            return
        real = BY_ID[ident][6]
        app = self.app
        if real == "phone":
            app.open_phone()
            self.lesson.note("real")   # окно с QR-кодом открыто: настоящая функция запущена
            return
        action = {"region": getattr(app, "capture_region", None), "full": getattr(app, "capture_fullscreen", None),
                  "record": getattr(app, "open_screen_recording", None)}.get(real)
        if action is None:
            return
        if real in ("region", "full"):
            self.showMinimized()         # окно не должно попасть в снимок; вернётся, когда выделение закончится
            if self._real_wait is not None:
                self._real_wait.stop()   # повторное нажатие: прежнее ожидание не копится
                self._real_wait.deleteLater()
            self._real_wait = QTimer(self)
            self._real_wait.setInterval(600)
            self._real_wait.timeout.connect(self._real_poll)
            self._real_wait.start()
            self._real_since = 0
            # окно выделения покажет шаги и подсветит нужную кнопку; пометка ставится в capture_* только при настоящем
            # старте выделения (отказ «занято» не оставляет её следующему Alt+W, С4 проверки 1.36.1)
            action(delay=400, guide=ident)
        else:
            action()
            self.lesson.note("real")

    def _real_poll(self):
        app = self.app
        self._real_since += 1
        busy = getattr(app, "selector", None) is not None or (getattr(app, "capture_pending", None) and app.capture_pending())
        if busy:
            self.lesson.note("real")   # окно выделения открылось: настоящая функция запущена (до этого шаг не засчитывается)
        if busy and self._real_since < 1500:
            return
        if self._real_since < 3 and not busy:
            return   # выделение ещё не успело открыться
        self._real_wait.stop()
        if self.current == "zakrepit":
            from . import zakrepit
            if zakrepit.OPEN:   # снимок закреплён: «Получилось» и как менять размер и снимать закрепление
                self.showNormal()
                self.raise_()
                self.activateWindow()
                self.lesson_done("zakrepit")
                self.hint_line.setText(tr("zakrepit.howto"))
                return
        if getattr(app, "editors", None):
            return   # после снимка открылся настоящий редактор: окно «Ознакомление» поверх него не поднимается
        if not self.isVisible() or self.isMinimized():
            self.showNormal()
            self.raise_()
            self.activateWindow()

    # --- примеры ---------------------------------------------------------------------------------------------

    def play(self):
        """«Показать»: живой показ с курсором, потом «Теперь вы»."""
        if self.current is not None:
            self.lesson.demo()

    def set_auto(self, auto: bool):
        """Окно открылось само (после «Показать новое» или после срока): в меню «Отложить ▾» последний пункт
        «Не открывать само». Открытое из меню значка пункта не имеет."""
        self.snooze_button.set_never("otl.never_ozn" if auto else None)

    def snooze(self, key=None):
        """«Отложить ▾»: учебный показ останавливается, окно закрывается и возвращается, когда срок выйдет, на той же
        функции (otlozhit, тема "ozn"). Отложенное окно не задаёт вопрос «Хотите узнать о других функциях?»."""
        cfg = self.app.config
        if key == otlozhit.NEVER:
            from . import novoe
            novoe.hide_version(cfg)   # само больше не приходит для этой версии; меню значка «Ознакомление» открывает
            mark = getattr(self.app, "mark_whatsnew_read", None)
            if callable(mark):
                mark()
            save = getattr(self.app, "save_config", None)
            if callable(save):
                save()
            self.close()
            return
        ident = self.current if self.current in BY_ID else None
        otlozhit.snooze(cfg, "ozn", key or otlozhit.DEFAULT, id=ident)
        save = getattr(self.app, "save_config", None)
        if callable(save):
            save()
        self.close()
        schedule = getattr(self.app, "schedule_otlozhit", None)
        if callable(schedule):
            schedule()

    # --- язык, закрытие ----------------------------------------------------------------------------------------

    def _safe_retranslate(self):
        try:
            self.retranslate()
        except RuntimeError:   # окно уже удалено
            pass

    def retranslate(self):
        """Язык сменили при открытом окне (меню значка, глобус учебного редактора): окно закрывается и открывается новое на
        новом языке с тем же пунктом. Старое окно к этому моменту уже не значится за приложением (closeEvent), поэтому
        open_window не возвращает закрывающееся окно (Б1 проверки 1.35.0)."""
        if self._relang:
            return
        self._relang = True
        try:
            ident, geo, app = self.current, self.geometry(), self.app
            self.close()
            win = open_window(app)
            win.setGeometry(geo)
            if ident:
                win.select(ident)
        except RuntimeError:
            pass

    def closeEvent(self, event):
        self.lesson.stop_all()
        QApplication.instance().removeEventFilter(self)
        if getattr(self.app, "_ozn_window", None) is self:
            self.app._ozn_window = None
        try:
            self._off_lang()
        except Exception:
            pass
        if self._real_wait is not None:
            self._real_wait.stop()
        self._drop_editor()
        super().closeEvent(event)


def open_window(app, focus_new: bool = False):
    """Открыть окно «Ознакомление» (одно на программу). Открытие на новинках отмечает «Что нового» прочитанным."""
    win = getattr(app, "_ozn_window", None)
    if win is not None:
        try:
            win.showNormal()
            win.raise_()
            win.activateWindow()
            if focus_new and win.new_list:
                win.select(win.new_list[0])
            return win
        except RuntimeError:
            app._ozn_window = None
    win = OznakomlenieWindow(app, focus_new)
    app._ozn_window = win
    win.destroyed.connect(lambda *_: setattr(app, "_ozn_window", None) if getattr(app, "_ozn_window", None) is win else None)
    win.show()
    win.raise_()
    win.activateWindow()
    return win
