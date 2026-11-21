# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Режим перевода в окне выделения (кнопка «Перевести», Ctrl+L), как переводчик с камеры телефона.

Экран заморожен. Выделяете мышью кусок: он распознаётся, переводится, и перевод ложится поверх исходного текста,
каждый столбец отдельно, на фоне цвета картинки. Над переводом: «Язык → Язык», «Скопировать», «Оригинал», крестик.
Переводы остаются, можно выделять следующий кусок. Esc или «Готово» закрывают режим.
"""

import math
import sys

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QPainter, QPainterPath, QPen, QRegion
from PyQt6 import sip
from PyQt6.QtWidgets import QWidget

from .frame_extents import track_frame_extents
from .i18n import number, tr

def _report(owner=None):
    """Внутри except RuntimeError. Удалён сам объект (окно закрыли, пока шёл перевод): это обычное дело, тихо.
    Любая другая RuntimeError: в sys.excepthook, чтобы попасть в журнал, а не пропасть."""
    import sys
    if owner is not None and sip.isdeleted(owner):
        return
    sys.excepthook(*sys.exc_info())


class _Tr:
    """Надпись-атрибут класса: хранится ключ, текст на языке интерфейса при каждом чтении (у класса и у объекта)."""

    def __init__(self, key: str):
        self.key = key

    def __get__(self, obj, owner=None):
        return tr(self.key)


# «Текст на экране (снимке) не найден» и вопрос про лимит: целые фразы для экрана и для снимка (tr_full_noun)
_NOT_FOUND = {"screen": "translate_ui.not_found_screen", "snapshot": "translate_ui.not_found_snapshot"}
_ASK = {"screen": "translate_ui.ask_screen", "snapshot": "translate_ui.ask_snapshot"}


TEAL = QColor("#0d9488")
TEAL_DARK = QColor("#0b766c")


class TranslateCard:
    """Один выделенный кусок и его перевод."""

    def __init__(self, region: QRect):
        self.region = QRect(region)   # в точках окна выделения
        self.state = "wait"           # wait: снимок ещё не готов; busy: переводится; done; error
        self.blocks = []              # {"rect", "draw", "text", "orig", "src", "tgt", "bg", "fg", "px"}
        self.message = ""
        self.help = None
        self.show_original = False
        self.buttons = {}             # имя -> QRectF кнопки над карточкой
        self.offset = QPointF(0, 0)   # перевод отодвинут мышью в сторону от оригинала
        self.content = QRectF(region) # область перевода на своём месте (блоки могут быть выше рамки)
        self.handle = QRectF()        # шапка: за неё тоже можно тащить
        self.scale = 1.0              # накопленный масштаб (редактор: Ctrl+колесо)
        self.px = 14                  # общий размер букв перевода (до масштаба)
        self.paras, self.px_draw = [], 14
        self.scroll, self.scroll_max = 0.0, 0.0
        self.laid = None              # ключ последней раскладки (_tr_layout)
        self.cover = None             # редактор: выделенная область, которую карточка закрывает не целиком
        self.header_need = 0
        self.view = None              # "overlay" (поверх текста) или "card" (карточкой); None: из настроек
        self.head_off = QPointF(0, 0) # «Поверх текста»: плашка с кнопками оттащена мышью
        self.chip = QRectF()          # «Поверх текста»: где плашка
        self.req_lang = ""            # язык, на который ушёл запрос этого куска (пусто: кусок собран без запроса)
        self.redo_lang = False        # язык сменили, пока шёл перевод: ответ на прежний язык не показывается, перевод заново
        self.full = False             # «Перевести весь экран (снимок)»: кусок это всё окно, ждать может долго
        self.job = None               # идущее распознавание и перевод (чтобы отменить по Esc)
        self.popup = None             # открытое окно «сколько хватит или отмена»
        self.partial = False          # человек выбрал «Перевести, сколько хватит»
        self.skipped = 0              # блоков, не отправленных на перевод (уже на русском)
        self.note = None              # «Карточкой»: (строки про лимит и пропуск, y, высота)
        self.total = 0                # абзацев к переводу до обрезки по лимиту

    def box(self) -> QRectF:
        """Где перевод сейчас на экране (с учётом сдвига)."""
        return self.content.translated(self.offset)

    def moved(self) -> bool:
        return abs(self.offset.x()) + abs(self.offset.y()) > 0.5

    def text(self) -> str:
        return "\n\n".join(b["text"] for b in self.blocks if b["text"])

    def langs(self) -> str:
        from .translate import lang_name
        pairs, engines = [], []
        for b in self.blocks:
            pair = (b["src"], b["tgt"])
            if pair not in pairs:
                pairs.append(pair)
            if b.get("engine") and b["engine"] not in engines:
                engines.append(b["engine"])
        text = ", ".join(f"{lang_name(s)} → {lang_name(t)}" for s, t in pairs[:2])
        return text + (f" · {', '.join(engines)}" if engines else "")

    def source_label(self) -> str:
        """Подпись слева: язык оригинала и сервис («Английский · MyMemory»); язык перевода на кнопке рядом."""
        from .translate import lang_name
        srcs, engines = [], []
        for b in self.blocks:
            if b["src"] and b["src"] not in srcs:
                srcs.append(b["src"])
            if b.get("engine") and b["engine"] not in engines:
                engines.append(b["engine"])
        text = ", ".join(lang_name(x) for x in srcs[:2]) or tr("translate_ui.translation")
        return text + (f" · {', '.join(engines)}" if engines else "")

    def target(self) -> str:
        return self.blocks[0]["tgt"] if self.blocks else ""

    def key_help(self) -> bool:
        """Перевод не прошёл, потому что Google не подключён (нет ключа, ключ не принят, не включена оплата)."""
        return self.help is not None and getattr(self.help, "service", None) == "google"

    def email_help(self) -> bool:
        """Перевод не прошёл: кончился лимит MyMemory без почты или почта не принята."""
        return self.help is not None and getattr(self.help, "service", None) == "mymemory_email"


def _text_box(px: int, width: int, text: str) -> QRect:
    """Сколько места занимает текст размером px с переносами по словам в строке шириной width. Слово длиннее строки
    Qt не переносит: тогда ширина ответа больше width."""
    font = QFont()
    font.setPixelSize(px)
    return QFontMetrics(font).boundingRect(QRect(0, 0, width, 100000), Qt.TextFlag.TextWordWrap, text)


def fit_font(text: str, rect: QRectF, base_px: float):
    """Шрифт, при котором текст с переносами помещается в рамку и по высоте, и по ширине; не помещается даже мелким:
    рамка растёт вниз, а если одно слово шире рамки, то и вправо. Раньше ширина не проверялась: слово перевода,
    которое длиннее своей строки рамки, обрезалось при рисовании («команда» на месте «team» читалась «команд», 1.32.3)."""
    width = max(20, int(rect.width()))
    for px in range(max(9, int(base_px)), 8, -1):
        box = _text_box(px, width, text)
        if box.height() <= rect.height() + 2 and box.width() <= rect.width():
            return px, QRectF(rect)
    box = _text_box(9, width, text)
    return 9, QRectF(rect.x(), rect.y(), max(rect.width(), box.width() + 2.0), box.height() + 4)


def unify_sizes(blocks):
    """Один размер букв на всё окошко: медиана размеров абзацев, но не ниже 12 px. Абзац, которому нужно
    меньше 0,7 медианы (мелкая сноска), остаётся со своим размером, чтобы не раздувать его рамку.
    Абзацу, который стал крупнее своего подбора, рамка подрастает вниз по высоте текста. Рамка в одну строку
    (вкладка, адрес, подпись) не растёт: если крупнее её строка перенеслась бы, она остаётся своего размера."""
    if not blocks:
        return
    sizes = sorted(b["px"] for b in blocks)
    median = sizes[len(sizes) // 2] if len(sizes) % 2 else (sizes[len(sizes) // 2 - 1] + sizes[len(sizes) // 2]) / 2
    shared = max(12, int(round(median)))
    font = QFont()
    for b in blocks:
        if b["px"] < 0.7 * median:
            continue
        if b["px"] != shared:
            own, b["px"] = b["px"], shared
            font.setPixelSize(shared)
            d = b["draw"]
            box = _text_box(shared, max(20, int(d.width())), b["text"])
            need = box.height()
            if box.width() > d.width() and shared > own:
                b["px"] = own   # крупнее своего слово перевода вышло бы за рамку справа и обрезалось
            elif need > d.height() + 2 and d.height() < 1.6 * QFontMetrics(font).lineSpacing():
                b["px"] = own   # одна строка (вкладка, адрес): крупнее своей она ушла бы в столбик ниже рамки
            elif need > d.height() + 2:
                b["draw"] = QRectF(d.x(), d.y(), d.width(), need + 4)


def sample_colors(image, phys: QRect):
    """Цвет фона вокруг блока на снимке (медиана по краю) и контрастный цвет текста."""
    pts = []
    x1, y1 = max(0, phys.left()), max(0, phys.top())
    x2, y2 = min(image.width() - 1, phys.right()), min(image.height() - 1, phys.bottom())
    if x2 <= x1 or y2 <= y1:
        return QColor("#ffffff"), QColor("#111111")
    step = max(1, (x2 - x1) // 24)
    for x in range(x1, x2 + 1, step):
        pts.append(image.pixelColor(x, y1))
        pts.append(image.pixelColor(x, y2))
    step = max(1, (y2 - y1) // 12)
    for y in range(y1, y2 + 1, step):
        pts.append(image.pixelColor(x1, y))
        pts.append(image.pixelColor(x2, y))

    def med(values):
        values = sorted(values)
        return values[len(values) // 2]
    bg = QColor(med([c.red() for c in pts]), med([c.green() for c in pts]), med([c.blue() for c in pts]))
    lum = 0.299 * bg.red() + 0.587 * bg.green() + 0.114 * bg.blue()
    return bg, QColor("#111111") if lum > 140 else QColor("#ffffff")


class TranslateMixin:
    """Режим перевода для RegionSelector. Переменные: translate_mode, tr_cards, tr_cfg."""

    def _tr_init(self):
        self.translate_mode = False
        self.tr_cards = []
        self.tr_start = None
        self.tr_cur = None
        self.tr_banner = {}
        self.tr_hover = None
        self.tr_cfg = {}
        self.tr_save = None          # сохранить настройки (выбор сервиса), даёт приложение
        self.tr_drag = None          # перевод, который сейчас тащат мышью
        self.tr_banner_off = QPointF(0, 0)   # на сколько владелец перетащил полосу режима (разово, не сохраняется)
        self.tr_banner_drag = None   # идущий перенос полосы: (где нажали, прежний сдвиг, дальше порога)
        self.tr_usage_texts = None   # (короткая, полная) строки расхода: считаются в _tr_refresh_usage
        self.tr_phase = 0            # кружок «думаю» на карточках, которые переводятся
        self.tr_timer = QTimer(self)
        self.tr_timer.timeout.connect(self._tr_tick)

    # --- места, которые зависят от окна (окно выделения по умолчанию; редактор подменяет) -----------

    tr_banner_enabled = True   # полоса режима внизу (в редакторе вместо неё нижняя панель окна)
    tr_dim = True              # лёгкое затемнение экрана в режиме перевода
    tr_more_button = False     # кнопка «Ещё» (перевести следующий кусок) у отдельного окошка перевода
    tr_floating = False        # окно выделения: перевод уходит в отдельное окошко, экран сразу живой
    tr_fill_card = False       # заливать весь прямоугольник перевода (отдельное окошко), а не только строки
    tr_floating_chip = True    # окошки перевода получают плашку с кнопками (окно выделения: только в панели, пока режим идёт)
    tr_chip = True             # «Поверх текста»: плашка с кнопками над переводом (в редакторе 1.29 кнопки внизу окна)

    VIEWS = ("overlay", "card")
    CHIP_H = 44                # плашка с кнопками в виде «Поверх текста» (высота как у шапки карточки)
    CHIP_SPACE = 50            # плашка и зазор: место над или под переведённой областью
    chip_below = False         # плашку ставить под областью (сверху нет места)
    chip_side = "above"        # окошко перевода: плашка снаружи области: above | below | right | left | none (плашки нет)
    chip_dx = 0.0              # окошко перевода: плашка над или под областью сдвинута вправо (> 0) или у правого края экрана
    #                            влево (< 0), плашка справа от области въезжает влево на своё поле (< 0)
    CHIP_SIDE_W = 600          # место под плашку сбоку от области (окошко с плашкой справа или слева)

    def _tr_view_default(self) -> str:
        view = (self.tr_cfg or {}).get("translate_view", "overlay")
        return view if view in self.VIEWS else "overlay"

    def _tr_view(self, card) -> str:
        """Вид показа перевода этого куска: «Поверх текста» (по умолчанию) или «Карточкой»."""
        if card.view not in self.VIEWS:
            card.view = self._tr_view_default()
        return card.view

    def _tr_toggle_view(self, card):
        """Кнопка вида в шапке: переключает, запоминает в настройках (translate_view)."""
        new = "card" if self._tr_view(card) == "overlay" else "overlay"
        card.view, card.laid = new, None
        card.head_off = QPointF(0, 0)
        self.tr_cfg["translate_view"] = new
        if callable(self.tr_save):
            self.tr_save()
        self._tr_view_changed(card, new)
        self.update()

    def _tr_view_changed(self, card, new: str):
        pass

    def _tr_alive(self) -> bool:
        return not self._done

    def _tr_scale(self) -> float:
        """Сколько пикселей снимка в одной точке окна."""
        return self.ratio

    def _tr_phys(self, rect: QRectF) -> QRect:
        return self.to_physical(rect.toAlignedRect())

    def _tr_image(self):
        return self.image

    def _tr_crop_image(self, region: QRect):
        if self.desktop is None or self.image.isNull():
            return None   # кадр ещё готовится
        return self.image.copy(self.to_physical(region))

    def _tr_orig(self, p: QPainter, target: QRectF, region: QRect):
        if self.desktop is not None:
            p.drawPixmap(target, self.desktop, QRectF(self.to_physical(region)))

    def _tr_close_mode(self):
        self._finish(None)

    def _tr_leave_for_browser(self):
        """Перед открытием сайта: окно выделения поверх всего, его надо закрыть, чтобы был виден браузер."""
        self._tr_close_mode()

    def _tr_more(self, rect=None):
        pass

    def _tr_rescale(self, f: float):
        """Масштаб окна изменился в f раз (редактор: Ctrl+колесо): переводы едут и растут вместе со снимком."""
        def sc(r):
            return QRectF(r.x() * f, r.y() * f, r.width() * f, r.height() * f)
        for card in self.tr_cards:
            card.region = sc(QRectF(card.region)).toAlignedRect()
            card.offset = QPointF(card.offset.x() * f, card.offset.y() * f)
            card.content = sc(card.content)
            card.scale *= f
            card.laid = None
            for b in card.blocks:
                b["rect"], b["draw"] = sc(b["rect"]), sc(b["draw"])
        self.update()

    def translate_enabled(self) -> bool:
        return bool(self.tr_cfg.get("translate_enabled", True))

    def enter_translate(self, hint=True):
        self.translate_mode = True
        self.kept = None
        self.full_mode = False
        self.start = None
        self.hover_button = None
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._tr_refresh_usage()
        if hint:
            self._tr_hint()
        self.update()

    def _tr_hint(self):
        """Всплывающая подсказка: программа ждёт, что человек выделит кусок (крупно, у верхнего края)."""
        from . import hints
        hints.hint(self, tr("translate_ui.hint_select"), tr("translate_ui.hint_exit"))   # в окне выделения кнопка называется «Закрыть (Esc)»

    def _tr_refresh_usage(self):
        """Расход считает сам ClipSD (у MyMemory за день, у Google за месяц): без запросов в сеть.
        Строки считаются здесь один раз и хранятся: при перерисовке файлы не читаются."""
        from . import translate
        try:
            self.tr_usage_texts = (translate.usage_short(self.tr_cfg), translate.usage_line(self.tr_cfg))
        except Exception:   # noqa: BLE001
            self.tr_usage_texts = ("", "")
        self._tr_safe_update()

    def _tr_safe_update(self):
        try:
            if self._tr_alive():
                self.update()
        except RuntimeError:
            pass

    def _tr_set_engine(self, engine: str):
        self.tr_cfg["translate_engine"] = engine
        if callable(self.tr_save):
            self.tr_save()
        self._tr_retry_errors()
        self._tr_refresh_usage()
        self.update()

    def _tr_lang_actions(self):
        """Пункты списка языков: [(код, подпись)]; первый «Как в системе»."""
        from . import translate
        items = [("auto", translate.auto_label(self.tr_cfg))]
        return items + [(code, translate.LANG_NAMES[code]) for code in translate.TARGETS]

    def _tr_lang_menu(self, rect: QRectF, card):
        """Список языков у кнопки; выбрали: запоминается, перевод в этом окошке делается заново."""
        self._tr_lang_menu_at(self.mapToGlobal(rect.bottomLeft().toPoint()), card)

    def _tr_lang_menu_at(self, gpos: QPoint, card, parent=None):
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(parent or self)
        from .menus import style_menu
        style_menu(menu, self.tr_cfg)
        current = self.tr_cfg.get("translate_to", "auto") or "auto"
        from . import icons
        for i, (code, title) in enumerate(self._tr_lang_actions()):
            act = menu.addAction(icons.flag_icon(code), title)   # 1.32: флаг языка; «Как в системе» и арабский: глобус
            act.setCheckable(True)
            act.setChecked(code == current)
            act.setData(code)
            if i == 0:
                menu.addSeparator()
        chosen = menu.exec(gpos)
        if chosen is not None:
            self._tr_choose_lang(chosen.data(), card)

    def _tr_choose_lang(self, code: str, card=None):
        if (self.tr_cfg.get("translate_to", "auto") or "auto") == code:
            # тот же язык: лишний запрос и расход лимита не нужны; но кусок, устаревший после смены языка в другом редакторе,
            # переводится заново (на кнопке язык уже стоит, а на куске прежний)
            from . import translate
            want = translate._norm(translate.target_lang(self.tr_cfg))
            for c in ([card] if card is not None else list(self.tr_cards)):
                if c is not None and c.req_lang and c.req_lang != want:
                    if c.state in ("done", "error"):
                        self._tr_redo(c)
                    elif c.state == "busy":
                        c.redo_lang = True
            self.update()
            return
        self.tr_cfg["translate_to"] = code
        if callable(self.tr_save):
            self.tr_save()
        for c in ([card] if card is not None else list(self.tr_cards)):
            if c is not None and c.state in ("done", "error"):
                self._tr_redo(c)
            elif c is not None and c.state == "busy":
                c.redo_lang = True   # ответ придёт на прежний язык: по приходе перевод запустится заново на новом
        self.update()

    def _tr_redo_allowed(self) -> bool:
        """Можно ли запускать новый запрос после смены языка: слой редактора только пока режим перевода открыт."""
        return True

    def _tr_redo(self, card):
        """Перевести кусок заново (другой язык или сервис)."""
        card.state, card.message, card.help, card.blocks = "wait", "", None, []
        card.content = QRectF(card.region)
        card.show_original = False
        self._tr_run(card)

    def _tr_retry_errors(self):
        for card in self.tr_cards:
            if card.state == "error":
                card.state, card.message, card.help, card.blocks = "wait", "", None, []
                self._tr_run(card)

    def _tr_open_email(self, reason: str = "upgrade", wait: str = ""):
        """Окно почты для MyMemory (лимит 50 000 знаков в день) по центру экрана; после сохранения переводы
        с ошибкой повторяются (и в этом окне, и в отдельных окошках перевода)."""
        from .service_setup import open_mymemory_email
        self._tr_leave_for_browser()   # окно выделения держит клавиатуру: закрыть, иначе почту не напечатать
        me = self

        def saved():
            for w in [me] + list(_floating):
                try:
                    w._tr_retry_errors()
                    w.update()
                except RuntimeError:
                    pass
        open_mymemory_email(None, self.tr_cfg, self.tr_save, saved, reason, wait)

    def _tr_auto_email(self, card):
        """Бесплатный лимит закончился: окно почты само, по центру экрана (не искать мелкую кнопку)."""
        self._tr_open_email("limit", getattr(card.help, "wait", "") or "")   # время до обновления: поле, не разбор текста

    def _tr_open_setup(self):
        """«Подключить Google…»: окно с шагами и полем для ключа; после сохранения перевод повторяется."""
        from .service_setup import open_google_setup
        self._tr_leave_for_browser()   # окно выделения держит клавиатуру: закрыть, иначе ключ не вставить

        def saved():
            try:
                self._tr_retry_errors()
                self.update()
            except RuntimeError:
                pass
        open_google_setup(None, self.tr_cfg, self.tr_save, saved)

    def _tr_copy_msg(self, text, near):
        from . import ocr
        bubble = ocr.toast(self, text)
        x = max(4, min(near.center().x() - bubble.width() // 2, self.width() - bubble.width() - 4))
        y = near.bottom() + 10 if near.bottom() + 10 + bubble.height() < self.height() else near.top() - bubble.height() - 40
        bubble.move(x, max(4, y))

    # --- перевод куска ---------------------------------------------------------

    def _tr_run(self, card: TranslateCard):
        from . import translate
        crop = self._tr_crop_image(card.region)
        if crop is None:
            card.state = "wait"   # кадр ещё готовится: переведём, как только придёт (set_desktop)
            if not self.tr_timer.isActive():
                self.tr_timer.start(80)
            return
        card.state = "busy"
        card.req_lang = translate._norm(translate.target_lang(self.tr_cfg))   # на какой язык ушёл этот запрос
        if not self.tr_timer.isActive():
            self.tr_timer.start(80)
        confirm = (lambda need, left, job, c=card: self._tr_confirm(c, need, left, job)) if card.full else None
        card.job = translate.start(crop, self.tr_cfg, lambda res, err, help, c=card: self._tr_done(c, res, err, help),
                                   confirm=confirm, full=card.full)

    # --- «Перевести весь экран»: большой текст, вопрос про лимит, отмена ---------------------------------

    tr_full_noun = "screen"   # «Текст на экране не найден» и вопрос про лимит (_NOT_FOUND, _ASK; редактор: snapshot)
    tr_full_wait = _Tr("translate_ui.full_wait_screen")

    tr_full_all = _Tr("translate_ui.all_done_screen")   # «Весь экран уже переведён» (редактор: «Весь снимок …»)
    tr_state_hook = None         # редактор: перерисовать строку подсказки, когда состояние перевода всего снимка изменилось

    def tr_state_changed(self):
        hook = self.tr_state_hook
        if callable(hook):
            try:
                hook()
            except RuntimeError:
                _report(getattr(hook, "__self__", None))

    def _tr_full_exists(self):
        """None; «busy»: перевод всего уже идёт; «done»: весь уже переведён (и показан)."""
        state = None
        for c in self.tr_cards:
            if c.full and c.state in ("busy", "wait"):
                return "busy"
            if c.full and c.state == "done":
                state = "done"
        return state

    def tr_translate_all(self, rect=None):
        """Весь экран (в редакторе весь снимок) сразу, без выделения мышью. Результат: как у выделенной области.
        Повторный вызов, пока перевод идёт или уже готов, ничего не запускает и лимит не тратит."""
        rect = QRect(rect if rect is not None else self.rect())
        if rect.width() < 8 or rect.height() < 8:
            return
        state = self._tr_full_exists()
        if state == "done":
            self._tr_say(self.tr_full_all)
            return
        if state:
            return
        if self.tr_floating:
            self._tr_spawn_full(rect)
            self.tr_state_changed()
            return
        card = TranslateCard(rect)
        card.full = True
        self.tr_cards.append(card)
        self._tr_run(card)
        self.update()
        self.tr_state_changed()

    def _tr_spawn_full(self, rect: QRect):
        """Окно выделения: весь монитор. Пока идёт распознавание и сеть, на экране только маленькое окошко ожидания
        (кружок, «Перевожу весь экран…», Esc, крестик); окно на весь монитор появляется с готовым переводом."""
        crop = self._tr_crop_image(rect)
        if crop is None:   # снимок ещё готовится: дождаться его (set_desktop → _tr_pending)
            if any(c.full for c in self.tr_cards):
                return
            card = TranslateCard(rect)
            card.full = True
            card.state = "wait"
            self.tr_cards.append(card)
            if not self.tr_timer.isActive():
                self.tr_timer.start(80)
            self.update()
            return
        grect = QRect(self.mapToGlobal(rect.topLeft()), rect.size())
        ratio = self._tr_scale()
        cfg, save = self.tr_cfg, self.tr_save
        busy = full_state(grect)
        if busy:
            self._tr_say(self.tr_full_all if busy == "done" else tr("translate_ui.already_running"))
            self._tr_after_spawn(False, full=True)
            return

        def make(local: QRect):
            k = ratio
            sub = crop.copy(QRect(round(local.x() * k), round(local.y() * k), max(1, round(local.width() * k)),
                                  max(1, round(local.height() * k))))
            win = FloatingTranslation(sub, ratio, QRect(grect.topLeft() + local.topLeft(), local.size()), cfg, save,
                                      full=local.size() == rect.size())
            win._full_rect = grect if local.size() == rect.size() else None
            return win
        from . import hints
        FullRun(crop, cfg, grect, rect.size(), make, say=lambda text: hints.floating_toast(text, grect.center()),   # окно выделения к концу уже закрыто
                noun=self.tr_full_noun, wait=self.tr_full_wait)
        self._tr_after_spawn(True, full=True)

    def _tr_confirm(self, card, need: int, left: int, job):
        """Текста больше, чем осталось по подсчёту ClipSD, а второго сервиса нет: всплывающее окно с выбором."""
        from . import hints, translate
        if sip.isdeleted(self) or not self._tr_alive() or card not in self.tr_cards:
            job.cancel()
            return
        n = number   # числа по правилам языка интерфейса
        # подсчёт дневной (запрос только когда Google не подключён)

        def answered(partial):
            card.popup = None
            if partial:
                card.partial = True
            job.answer(partial)
        popup = hints.ChoicePopup(self.window(), tr(_ASK[self.tr_full_noun], n=need, need=n(need), left=n(left)),
                                  tr("translate_ui.translate_partial"), tr("settings.cancel"), answered,
                                  tr("translate_ui.no_second_engine"))
        card.popup = popup
        g = self.window().frameGeometry()
        popup.show_at(QPoint(g.center().x(), g.top() + int(g.height() * 0.38)))   # над кружком ожидания, не закрывая его
        self.tr_popup = popup

    def _tr_cancel_busy(self):
        """Esc или «Готово» во время долгого перевода всего экрана: ожидание отменяется, в сеть больше ничего не уходит."""
        for card in list(self.tr_cards):
            if card.full and card.state in ("busy", "wait"):
                self._tr_cancel_card(card)
                self.tr_cards.remove(card)
        self.update()
        self.tr_state_changed()

    def _tr_shutdown(self):
        """Окно закрывается (редактор, окно выделения): всё, что ждёт ответа или сети, отменяется, и результат
        больше никому не адресуется. Иначе поток вызвал бы уже удалённое окно, и программа упала бы."""
        self._done = True
        for card in list(self.tr_cards):
            self._tr_cancel_card(card)

    def _tr_cancel_card(self, card):
        if card.popup is not None:
            try:
                card.popup.dismiss()
            except RuntimeError:
                _report(card.popup)
            card.popup = None
        if card.job is not None:
            card.job.cancel()

    def _tr_say(self, text: str):
        """Всплывающее сообщение «Текст на экране не найден» и подобные: окно выделения к этому времени уже закрыто,
        поэтому сообщение посреди монитора, а не внутри окна."""
        from . import hints
        hints.floating_toast(text, self.window().frameGeometry().center())   # информация: без галочки

    def _tr_tick(self):
        if any(c.state in ("busy", "wait") for c in self.tr_cards) and self._tr_alive():
            self.tr_phase += 1
            self.update()
        else:
            self.tr_timer.stop()   # нечего ждать: таймер не крутится зря

    def _tr_pending(self):
        for card in list(self.tr_cards):
            if card.state == "wait":
                if self.tr_floating:
                    self.tr_cards.remove(card)
                    if card.full:
                        self._tr_spawn_full(card.region)
                    else:
                        self._tr_spawn_floating(card.region)
                    return
                self._tr_run(card)

    def _tr_backdrop(self):
        """Кадр экрана для выбора места плашки окошка (окно выделения): (изображение, глобальный угол, точек в точке)."""
        return None

    def _tr_after_spawn(self, spawned=True, full=False, win=None):
        """Окошко перевода запущено. По умолчанию окно выделения закрывается; в окне выделения (1.29) оно остаётся:
        режим перевода продолжается, следующий обведённый кусок тоже переводится."""
        self._finish(None)

    def _tr_spawn_floating(self, rect: QRect):
        """Окно выделения: перевод в отдельное окошко на месте текста."""
        crop = self._tr_crop_image(rect)
        if crop is None:   # снимок ещё готовится: дождаться его (set_desktop → _tr_pending)
            card = TranslateCard(rect)
            card.state = "wait"
            self.tr_cards.append(card)
            if not self.tr_timer.isActive():
                self.tr_timer.start(80)
            self.update()
            return
        win = FloatingTranslation(crop, self._tr_scale(), QRect(self.mapToGlobal(rect.topLeft()), rect.size()),
                                  self.tr_cfg, self.tr_save, chip=self.tr_floating_chip, backdrop=self._tr_backdrop(),
                                  avoid=True)
        win.start()
        self.spawned = getattr(self, "spawned", []) + [win]
        self._tr_after_spawn(True, win=win)

    def _tr_done(self, card, results, error, help=None):
        if sip.isdeleted(self):
            return   # окно закрыто, пока шёл перевод: показывать некому
        try:
            self._tr_done_inner(card, results, error, help)
        except RuntimeError:
            _report(self)
            self._tr_fail(card)

    def _tr_fail(self, card):
        """Неожиданная ошибка в обработчике результата: карточка не остаётся с вечным кружком, а показывает ошибку."""
        if sip.isdeleted(self) or card not in self.tr_cards or card.state not in ("wait", "busy"):
            return
        card.state, card.message, card.help, card.laid = "error", tr("translate_ui.unexpected_error"), None, None
        self.update()

    def _tr_done_inner(self, card, results, error, help=None):
        if not self._tr_alive() or card not in self.tr_cards:
            return
        from . import translate
        if card.redo_lang and error != translate.CANCELLED:
            card.redo_lang = False   # 1.32.4: язык сменили во время запроса; ответ на прежний язык (и его ошибка) не показываются
            if self._tr_redo_allowed():
                self._tr_redo(card)
            else:   # режим перевода уже закрыт (Esc): новый запрос не уходит, кусок убирается
                self.tr_cards = [c for c in self.tr_cards if c is not card]
            self.update()
            self.tr_state_changed()
            return
        card.skipped = getattr(results, "skipped", 0)
        card.total = getattr(results, "total", 0)
        if error == translate.CANCELLED:
            self._tr_cancel_card(card)   # заодно закрывается окно вопроса, если оно ещё висит
            self.tr_cards = [c for c in self.tr_cards if c is not card]   # «Отмена»: кусок убирается, лимит не тронут
            self.update()
            self.tr_state_changed()
            return
        if card.full and (error == translate.NO_TEXT or translate.is_already(error)):
            self.tr_cards = [c for c in self.tr_cards if c is not card]
            self._tr_say(tr(_NOT_FOUND[self.tr_full_noun]) if error == translate.NO_TEXT else error.rstrip("."))
            self.update()
            self.tr_state_changed()
            return
        if error:
            card.state, card.message, card.help = "error", error, help
            self.update()
            self.tr_state_changed()
            if card.email_help():
                self._tr_auto_email(card)
            return
        r = self._tr_scale()
        for res in results:
            rr = res["rect"]
            rect = QRectF(card.region.x() + rr.x() / r, card.region.y() + rr.y() / r, rr.width() / r, rr.height() / r)
            rect = rect.adjusted(-3, -2, 3, 2)
            bg, fg = sample_colors(self._tr_image(), self._tr_phys(rect.adjusted(-2, -2, 2, 2)))
            # рамка слова у Tesseract ниже кегля (от верха заглавной до низа): кегль ≈ 1,3 высоты рамки
            px, draw = fit_font(res["text"], rect.adjusted(2, 1, -2, -1), res.get("line_h", 11) * 1.3 / r)
            card.blocks.append({"rect": rect, "draw": draw, "text": res["text"], "orig": res["orig"],
                                "src": res["src"], "tgt": res["tgt"], "bg": bg, "fg": fg, "px": px,
                                "engine": res.get("engine", "")})
        unify_sizes(card.blocks)
        pxs = sorted(b["px"] for b in card.blocks)
        card.px = max(14, min(18, pxs[len(pxs) // 2] if pxs else 14))   # медиана, в пределах 14-18 px
        self._tr_refresh_usage()   # расход изменился после перевода
        card.content = QRectF(card.region)
        card.laid = None
        card.state = "done"
        if (card.partial or card.skipped) and self._tr_view(card) == "overlay":   # «Карточкой» то же самое строками в карточке
            self._tr_say(self._tr_partial_text(card))
        self.update()
        self.tr_state_changed()

    @staticmethod
    def _tr_partial_text(card) -> str:
        """Одно сообщение про неполный перевод: лимит и/или пропуск русского текста."""
        from . import translate
        m, n, k = len(card.blocks), card.skipped, card.total
        skipped = translate.skipped_text(n)
        if card.partial:
            head = (tr("translate_ui.partial_of", n=k, m=m, k=k) if k and not n else tr("translate_ui.partial", n=m, m=m))
            return tr("translate_ui.with_skipped", text=head, skipped=skipped) if n else head
        head = tr("translate_ui.done_count", n=m, m=m)
        return tr("translate_ui.with_skipped", text=head, skipped=skipped) if n else head

    def _tr_cover_edges(self, card, content: QRectF) -> QRectF:
        """Карточка закрывает всю выделенную область; где выделение оборвало строку текста, карточка растёт
        вместе с ней (в редакторе). Окно выделения и окошко перевода работают по рамке выделения и не меняются."""
        return content

    def _tr_grow_selection(self, rect: QRect) -> QRect:
        """Обведённый кусок перед распознаванием. Редактор дотягивает рамку до конца разрезанной ею строки
        (TranslateLayer); окно выделения работает по рамке как есть."""
        return rect

    # --- кнопки -------------------------------------------------------------------

    def _tr_copy(self, text: str, near: QRect = None, what=None):
        from . import ocr
        if not text:
            return
        what = what or tr("translate_ui.copied")
        ocr.copy_text(text)
        # окно выделения на все мониторы: сообщение у карточки, а не посередине стола
        self._tr_copy_msg(what, near if near is not None else self._tr_banner_rect().toAlignedRect())

    def _tr_all_text(self) -> str:
        return "\n\n".join(c.text() for c in self.tr_cards if c.state == "done" and c.text())

    def _tr_click(self, pos: QPointF) -> bool:
        for name, rect in self.tr_banner.items():
            if rect.contains(pos):
                if name == "done":
                    self._tr_close_mode()
                elif name.startswith("engine:"):
                    self._tr_set_engine(name[7:])
                elif name == "lang":
                    self._tr_lang_menu(rect, None)
                elif name == "email":
                    self._tr_open_email()
                elif name == "copyall":
                    self._tr_copy(self._tr_all_text(), self._tr_banner_rect().toAlignedRect(), tr("translate_ui.all_copied"))
                return True
        for card in reversed(self.tr_cards):
            for name, rect in card.buttons.items():
                if rect.contains(pos):
                    if name == "close":
                        self.tr_cards.remove(card)
                    elif name == "copy":
                        self._tr_copy(card.text(), card.box().toAlignedRect())
                    elif name == "orig":
                        card.show_original = not card.show_original
                    elif name == "view":
                        self._tr_toggle_view(card)
                        return True
                    elif name == "command" and card.help is not None and card.help.command:
                        self._tr_copy(card.help.command, card.region, tr("translate_ui.command_copied"))
                    elif name == "more":
                        self._tr_more(rect)
                        return True
                    elif name == "lang":
                        self._tr_lang_menu(rect, card)
                        return True
                    elif name == "retry":
                        if card.state == "error":   # второе нажатие до перерисовки запрос не дублирует
                            self._tr_redo(card)
                        return True
                    elif name == "setup":
                        self._tr_open_setup()
                    elif name == "email":
                        self._tr_auto_email(card) if card.email_help() else self._tr_open_email()
                    elif name == "usemm":
                        self._tr_copy_msg(tr("translate_ui.via_mymemory"), card.box().toAlignedRect())   # видно, что нажатие дошло
                        self._tr_set_engine("mymemory")   # перевести через MyMemory, Google не нужен
                    elif name == "link" and card.help is not None and card.help.url:
                        self._tr_copy(card.help.url, card.region, tr("translate_ui.link_copied"))
                    elif name == "site" and card.help is not None and card.help.url:
                        from .sysenv import open_url
                        url = card.help.url
                        self._tr_leave_for_browser()
                        open_url(url)
                        return True
                    self.update()
                    return True
        return False

    # --- мышь и клавиши (возвращают True, если событие обработано) -----------------------------

    def _tr_press(self, event) -> bool:
        if not self.translate_mode:
            return False
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            if self._tr_click(pos):
                return True
            if self._tr_banner_free_at(pos):
                # свободное место полосы режима: полосу можно перетащить, если она закрывает текст (разово)
                self.tr_banner_drag = (pos, QPointF(self.tr_banner_off), False)
                return True
            card = self._tr_card_at(pos)
            if card is not None:
                # нажали на перевод: его можно оттащить в сторону, чтобы видеть оригинал
                # («Поверх текста»: оттаскивается плашка с кнопками, текст остаётся на своём месте)
                self.tr_cards.remove(card)
                self.tr_cards.append(card)   # перетаскиваемый поверх остальных
                attr = "head_off" if self._tr_view(card) == "overlay" else "offset"
                self.tr_drag = {"card": card, "from": pos, "offset": QPointF(getattr(card, attr)), "attr": attr}
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                return True
            self.tr_start = pos.toPoint()
            self.tr_cur = self.tr_start
            self.update()
        return True

    def _tr_card_at(self, pos: QPointF):
        for card in reversed(self.tr_cards):
            if self._tr_view(card) == "overlay":
                if card.handle.contains(pos):
                    return card
            elif card.box().contains(pos) or card.handle.contains(pos):
                return card
        return None

    def _tr_move(self, event) -> bool:
        if not self.translate_mode:
            return False
        pos = event.position()
        bdrag = getattr(self, "tr_banner_drag", None)
        if bdrag is not None:
            start, off0, active = bdrag
            delta = pos - start
            if active or abs(delta.x()) + abs(delta.y()) >= 5:
                self.tr_banner_off = off0 + delta
                self.tr_banner_drag = (start, off0, True)
                self.setCursor(Qt.CursorShape.SizeAllCursor)
                self.update()
            return True
        drag = getattr(self, "tr_drag", None)
        if drag is not None:
            card = drag["card"]
            off = drag["offset"] + (pos - drag["from"])
            if drag.get("attr") == "head_off":
                card.head_off = off   # границы окна держит _tr_chip_rect
                self.update()
                return True
            box = card.content.translated(off)
            # не уводить за край окна выделения
            off.setX(off.x() - max(0.0, box.right() - self.width() + 2) + max(0.0, -box.left() + 2))
            off.setY(off.y() - max(0.0, box.bottom() - self.height() + 2) + max(0.0, -box.top() + 30))
            card.offset = off
            self.update()
            return True
        if self.tr_start is not None:
            self.tr_cur = pos.toPoint()
            self.update()
            return True
        tip = getattr(self, "tr_banner_tip", None)
        if tip is not None and tip[0].contains(pos):
            from PyQt6.QtWidgets import QToolTip
            QToolTip.showText(event.globalPosition().toPoint(), tip[1], self)
        over = any(r.contains(pos) for r in self.tr_banner.values()) or \
            any(r.contains(pos) for c in self.tr_cards for r in c.buttons.values())
        if over:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        elif self._tr_banner_free_at(pos):
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        elif self._tr_card_at(pos) is not None:
            self.setCursor(Qt.CursorShape.OpenHandCursor)   # перевод (или его плашку) можно схватить и оттащить
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)
        return True

    def _tr_release(self, event) -> bool:
        if not self.translate_mode:
            return False
        if event.button() == Qt.MouseButton.LeftButton and getattr(self, "tr_banner_drag", None) is not None:
            self.tr_banner_drag = None
            self.update()
            return True
        if event.button() == Qt.MouseButton.LeftButton and getattr(self, "tr_drag", None) is not None:
            self.tr_drag = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self.update()
            return True
        if event.button() == Qt.MouseButton.LeftButton and self.tr_start is not None:
            a, b = self.tr_start, event.position().toPoint()
            self.tr_start = self.tr_cur = None
            rect = QRect(a, b).normalized().intersected(self.rect())
            if rect.width() >= 8 and rect.height() >= 8:
                rect = self._tr_grow_selection(rect)
                if self.tr_floating:
                    self._tr_spawn_floating(rect)
                    return True
                card = TranslateCard(rect)
                self.tr_cards.append(card)
                self._tr_run(card)
            self.update()
        return True

    def _tr_key(self, event) -> bool:
        if not self.translate_mode:
            return False
        if event.key() == Qt.Key.Key_Escape:
            self._tr_close_mode()
        elif event.key() == Qt.Key.Key_C and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._tr_copy(self._tr_all_text(), self._tr_banner_rect().toAlignedRect(), tr("translate_ui.all_copied"))
        return True

    # --- отрисовка ---------------------------------------------------------------------

    def _tr_banner_rect(self) -> QRectF:
        """Полоса режима внизу монитора, где был курсор: сверху она закрывала бы начало документа."""
        if not self.tr_banner_enabled:
            return QRectF()
        if getattr(self, "_tr_anchor", None) is None:
            from PyQt6.QtGui import QCursor
            s0 = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
            self._tr_anchor = s0.geometry() if s0 else QRect(self.origin, self.size())
        area = QRectF(self._tr_anchor.translated(-self.origin)).intersected(QRectF(self.rect()))
        w = min(1240.0, area.width() - 32)
        bar = QRectF(area.left() + (area.width() - w) / 2, area.bottom() - 60 - 18, w, 60)
        off = getattr(self, "tr_banner_off", QPointF(0, 0))   # перетащена владельцем: сдвиг в пределах монитора
        if not off.isNull():
            bar.translate(off)
            dx = max(0.0, area.left() - bar.left()) - max(0.0, bar.right() - area.right())
            dy = max(0.0, area.top() - bar.top()) - max(0.0, bar.bottom() - area.bottom())
            bar.translate(dx, dy)
            self.tr_banner_off = QPointF(bar.left() - (area.left() + (area.width() - w) / 2),
                                         bar.top() - (area.bottom() - 78))
        return bar

    def _tr_banner_free_at(self, pos) -> bool:
        """Свободное место полосы режима (не кнопки): за него полоса переносится."""
        if not self.tr_banner_enabled or not self.translate_mode:
            return False
        bar = self._tr_banner_rect()
        if bar.isEmpty() or not bar.contains(pos):
            return False
        return not any(r.contains(pos) for r in self.tr_banner.values())

    @staticmethod
    def _tr_fit(fm: QFontMetrics, variants, width) -> str:
        """Первый вариант надписи, который помещается в ширину; если не помещается ни один, последний с многоточием."""
        for text in variants:
            if fm.horizontalAdvance(text) <= width:
                return text
        return fm.elidedText(variants[-1], Qt.TextElideMode.ElideRight, int(width))

    def _tr_paint(self, p: QPainter):
        if self.tr_dim:
            p.fillRect(self.rect(), QColor(0, 0, 0, 30))   # лёгкое затемнение: видно, что включён режим
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for card in self.tr_cards:
            self._tr_paint_card(p, card)
        if self.tr_start is not None and self.tr_cur is not None:
            r = QRect(self.tr_start, self.tr_cur).normalized()
            p.fillRect(r, QColor(13, 148, 136, 40))
            p.setPen(QPen(TEAL, 2, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(r)
        if self.tr_banner_enabled:
            self._tr_paint_banner(p)

    def _chip_font(self, px=13, bold=True):
        f = QFont()
        f.setPixelSize(px)
        f.setBold(bold)
        return f

    # --- карточка перевода: светлая карточка, шапка внутри (вариант А) ---------------------------------

    HEAD_H = 44          # шапка карточки
    PAD_X, PAD_Y = 18, 16
    MIN_W, MAX_W = 360, 720
    tr_cover_region = False   # редактор: карточка не меньше выделенной области и закрывает её целиком

    def _tr_palette(self) -> dict:
        """Цвета карточки: светлая бирюзовая тема, в тёмном оформлении программы цвета берутся из темы."""
        from . import themes
        t = themes.tokens(self.tr_cfg or {})
        if t.get("dark"):
            return {"card": QColor(t["card_bg"]), "text": QColor(t["text"]), "head": QColor("#16322f"),
                    "line": QColor("#24504b"), "border": QColor("#2c5a54"), "muted": QColor(t["text_dim"]),
                    "btn": QColor(t["button_bg"]), "btn_line": QColor(t["button_border"]), "btn_text": QColor(t["button_text"]),
                    "teal": QColor("#0b8f84"), "lang": QColor("#7fe0d6")}
        return {"card": QColor("#ffffff"), "text": QColor("#10161f"), "head": QColor("#e9f6f4"), "line": QColor("#d5e9e6"),
                "border": QColor("#cfe1de"), "muted": QColor("#6b7785"), "btn": QColor("#ffffff"),
                "btn_line": QColor("#cfe1de"), "btn_text": QColor("#10161f"), "teal": QColor("#0b8f84"),
                "lang": QColor("#0b5f57")}

    def _tr_head(self, card):
        """Что стоит в шапке: (подпись слева, сервис, [(имя, текст, главная)])."""
        from .translate import lang_name
        if card.state == "done":
            srcs = []
            for b in card.blocks:
                if b["src"] and b["src"] not in srcs:
                    srcs.append(b["src"])
            src = ", ".join(lang_name(x) for x in srcs[:2]) or tr("translate_ui.translation")
            engines = []
            for b in card.blocks:
                if b.get("engine") and b["engine"] not in engines:
                    engines.append(b["engine"])
            items = [("copy", tr("editor.copy"), True), ("orig", tr("translate_ui.translation") if card.show_original else tr("translate_ui.original"), False),
                     ("view", tr("translate_ui.view_card") if self._tr_view(card) == "overlay" else tr("translate_ui.view_overlay"), False)]
            if self.tr_more_button:
                items.append(("more", tr("translate_ui.more"), False))
            return f"{src} → {lang_name(card.target())} ▾", ", ".join(engines), items
        if card.state == "error":
            if card.email_help():
                items = [("email", tr("translate_ui.email_button"), True), ("setup", tr("translate_ui.connect_google"), False)]
            elif card.key_help():
                items = [("setup", tr("translate_ui.connect_google"), True), ("usemm", tr("translate_ui.use_mymemory"), False)]
            elif card.help is not None and card.help.command:
                items = [("command", tr("translate_ui.copy_command"), True)]
            else:
                items = [("retry", tr("updater.button.retry"), True)]   # у обычной ошибки одно действие: повторить
            return tr("translate_ui.failed"), "", items
        return (tr("translate_ui.busy") if card.state == "busy" else tr("selector.preparing")), "", []

    def _tr_layout(self, card):
        """Размер и место карточки, абзацы тела. Пересчитывается, когда меняется состояние, масштаб или область."""
        if self._tr_view(card) == "overlay":
            self._tr_layout_overlay(card)
            return
        r = card.region
        key = (card.state, card.show_original, round(card.scale, 3), r.x(), r.y(), r.width(), r.height(), card.message, card.skipped, card.partial,
               self.width() if self.tr_cover_region else 0, self.height() if self.tr_cover_region else 0)
        if getattr(card, "laid", None) == key:
            return
        card.laid = key
        sc = card.scale
        label, service, items = self._tr_head(card)
        fb, fn = self._chip_font(14), self._chip_font(14, bold=False)
        fmb, fmn = QFontMetrics(fb), QFontMetrics(fn)
        iw = [fmn.horizontalAdvance(t) + 26 for _k, t, _m in items]
        head_need = 14 + fmb.horizontalAdvance(label) + 14 + sum(iw) + 6 * len(iw) + 30 + 10
        card.header_need = head_need
        base = QRectF(r)
        if self.tr_cover_region and card.blocks and card.state == "done":
            base = self._tr_cover_edges(card, base)
        W = max(base.width(), self.MIN_W * sc) if self.tr_cover_region else min(max(base.width(), self.MIN_W * sc), self.MAX_W * sc)
        W = max(W, head_need)
        screen = self.screen()
        area = screen.availableGeometry() if screen is not None else QRect(0, 0, 1280, 800)
        hmax = 0.6 * area.height()
        lineh = 20
        card.paras, card.px_draw = [], 0
        tw = int(W - 2 * self.PAD_X)
        if card.state == "done" and not card.show_original:
            px = max(14, min(18, card.px)) * sc if card.px else 14 * sc
            px = max(12, round(px))
            card.px_draw = px
            font = QFont()
            font.setPixelSize(px)
            fm = QFontMetrics(font)
            lineh = fm.lineSpacing()
            y, gap = self.PAD_Y, max(6, round(px * 0.6))
            for blk in card.blocks:
                if not blk["text"]:
                    continue
                h = fm.boundingRect(QRect(0, 0, tw, 100000), Qt.TextFlag.TextWordWrap, blk["text"]).height()
                card.paras.append((blk["text"], y, h))
                y += h + gap
            body = (y - gap if card.paras else self.PAD_Y) + self.PAD_Y + 2
            card.note = None
            if card.skipped or card.partial:   # честно говорим, что перевод неполный и почему
                from . import translate
                lines = []
                if card.partial:
                    m, k = len(card.blocks), card.total
                    lines.append(tr("translate_ui.partial_of", n=k, m=m, k=k) if k else tr("translate_ui.partial", n=m, m=m))
                if card.skipped:
                    lines.append(translate.skipped_text(card.skipped))
                nh = (QFontMetrics(fn).height() + 2) * len(lines) + 2
                card.note = (lines, body - self.PAD_Y, nh)
                body += nh + 6
        elif card.state == "done":   # «Оригинал»: исходный кусок по ширине карточки
            ratio = max(0.05, r.height() / max(1.0, r.width()))
            body = self.PAD_Y * 2 + min(tw * ratio, max(60.0, hmax - self.HEAD_H - 2 * self.PAD_Y))
        elif card.state == "error":
            text = card.message
            if card.email_help():
                text += "\n\n" + tr("translate_ui.no_registration")
            elif card.key_help():
                text += "\n\n" + tr("translate_ui.setup_note")
            elif card.help is not None and card.help.command:
                text += "\n" + card.help.command
            W = max(W, 440)
            tw = int(W - 2 * self.PAD_X - 40)
            th = QFontMetrics(fn).boundingRect(QRect(0, 0, tw, 100000), Qt.TextFlag.TextWordWrap, text).height()
            card.paras = [(text, self.PAD_Y, th)]
            body = th + 2 * self.PAD_Y + 4
        else:
            body = max(96.0, 0.0)
        H = self.HEAD_H + body
        card.scroll_max = 0.0
        if H > hmax:
            card.scroll_max = H - hmax
            H = hmax
        card.cover = None
        if self.tr_cover_region:
            # высота по тексту, до высоты области тянем не больше чем на две строки; остаток области не заливаем,
            # его обводит тонкий пунктир цветом перевода
            H = max(H, min(base.height(), H + 2 * lineh))
            card.cover = QRectF(base)
        card.scroll = max(0.0, min(card.scroll, card.scroll_max))
        x, y0 = (base.x(), base.y())
        if self.tr_cover_region:   # не выходить за снимок
            x = max(0.0, min(x, self.width() - W)) if self.width() >= W else 0.0
            y0 = max(0.0, min(y0, self.height() - H)) if self.height() >= H else 0.0
        card.content = QRectF(x, y0, W, H)

    # --- «Поверх текста»: строки перевода на местах исходных, под ними заливка цветом фона, плашка с кнопками ----

    def _tr_layout_overlay(self, card):
        """Занятая область: выделенный кусок и все блоки; ширина плашки с кнопками."""
        r = card.region
        key = ("ov", card.state, card.show_original, round(card.scale, 3), r.x(), r.y(), r.width(), r.height(),
               len(card.blocks))
        if getattr(card, "laid", None) == key:
            return
        card.laid = key
        area = QRectF(r)
        for b in card.blocks:
            area = area.united(b["draw"]).united(b["rect"])
        card.content, card.cover, card.paras = area, None, []
        card.scroll, card.scroll_max = 0.0, 0.0
        label, _service, items = self._tr_head(card)
        fmb, fmn = QFontMetrics(self._chip_font(14)), QFontMetrics(self._chip_font(14, bold=False))
        iw = [fmn.horizontalAdvance(t) + 26 for _k, t, _m in items]
        card.header_need = 14 + fmb.horizontalAdvance(label) + 14 + sum(iw) + 6 * len(iw) + 30 + 10

    def _tr_chip_rect(self, card) -> QRectF:
        """Где плашка: над областью, а если сверху нет места, под ней, а если и там нет, внутри сверху.
        Оттащенную мышью плашку держим в границах окна (отдельное окошко таскается целиком)."""
        box = card.content
        w, h = max(card.header_need, 200.0), float(self.CHIP_H)
        x = box.left()
        dx = self.chip_dx if self.tr_fill_card and self.chip_side != "left" else 0.0
        if self.tr_fill_card and self.chip_side in ("right", "left"):
            x = box.right() + 8 + dx if self.chip_side == "right" else box.left() - w - 8
            y = box.top()
        elif self.chip_below:
            x, y = x + dx, box.bottom() + 6
        elif self.tr_fill_card:
            x, y = x + dx, box.top() - h - 6
        else:
            # Слой на снимке: над областью, под ней, сбоку, внутри сверху или снизу; берётся место, где плашка
            # меньше всего закрывает перевод (при равенстве выигрывает более ранний вариант: над областью)
            bnd = self._tr_bounds()

            def fit(r):
                return QRectF(max(bnd.left() + 2, min(r.x(), bnd.right() - r.width() - 2)),
                              max(bnd.top() + 2, min(r.y(), bnd.bottom() - r.height() - 2)), r.width(), r.height())
            text = [b["draw"].united(b["rect"]) for b in card.blocks]

            def covered(r):
                return sum(r.intersected(t).width() * r.intersected(t).height() for t in text if r.intersects(t))
            spots = [fit(r) for r in (QRectF(x, box.top() - h - 6, w, h), QRectF(x, box.bottom() + 6, w, h),
                                      QRectF(box.right() + 8, box.top(), w, h), QRectF(box.left() - w - 8, box.top(), w, h),
                                      QRectF(x, box.top() + 4, w, h), QRectF(x, box.bottom() - h - 4, w, h))]
            if card.full and not card.blocks:
                # весь снимок ещё переводится: где текст, неизвестно; плашка «Перевожу…» в правом верхнем углу,
                # слева обычно начинается текст
                spots.insert(0, fit(QRectF(box.right() - w - 8, box.top() + 4, w, h)))
            spot = min(spots, key=covered)
            x, y = spot.x(), spot.y()
        if not self.tr_fill_card:
            x, y = x + card.head_off.x(), y + card.head_off.y()
            bnd = self._tr_bounds()
            x = max(bnd.left() + 2, min(x, bnd.right() - w - 2))
            y = max(bnd.top() + 2, min(y, bnd.bottom() - h - 2))
        return QRectF(x, y, w, h)

    def _tr_paint_overlay(self, p: QPainter, card: TranslateCard):
        self._tr_layout_overlay(card)
        col = self._tr_palette()
        reg = QRectF(card.region)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # Обводка занятой области (выделение и строки перевода, вышедшие за него) рисуется ДО текста
        # и снаружи заливки строк: линия не зачёркивает перевод
        p.setPen(QPen(TEAL, 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(card.content.adjusted(-2.25, -2.25, 2.25, 2.25), 5, 5)
        if card.state == "done" and not card.show_original:
            if self.tr_fill_card and getattr(self, "_user_moved", False) and card.blocks:
                # окошко унесли мышью: вся область одним цветом фона, а не строчками поверх чужого фона
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(card.blocks[0]["bg"])
                p.drawRect(card.content)
            for b in card.blocks:
                area = b["draw"].united(b["rect"])
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(b["bg"])   # заливка цветом фона оригинала: исходный текст не просвечивает
                p.drawRoundedRect(area.adjusted(-1, -1, 1, 1), 3, 3)
                f = QFont()
                f.setPixelSize(b["px"])
                p.setFont(f)
                p.setPen(b["fg"])
                p.drawText(b["draw"], int(Qt.TextFlag.TextWordWrap) | int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
                           b["text"])
        elif card.state == "done":
            if self.tr_fill_card:   # отдельное окошко: исходный кусок рисуем сами; в редакторе он и так виден под слоем
                self._tr_orig(p, reg, card.region)
        elif card.state in ("busy", "wait"):
            from .busy import draw_spinner
            p.fillRect(reg, QColor(255, 255, 255, 90))
            radius = max(10.0, min(24.0, min(reg.width(), reg.height()) / 4))
            c = reg.center()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 235))
            p.drawEllipse(QPointF(c.x(), c.y()), radius + 12, radius + 12)
            draw_spinner(p, QPointF(c.x(), c.y()), radius, self.tr_phase, TEAL)
            if card.full:
                self._tr_busy_label(p, QPointF(c.x(), c.y() + radius + 12), self.tr_full_wait)
        if not (self.tr_chip or card.state == "error"):   # ошибке нужны её кнопки («Подключить Google…»), остальным нет
            card.chip, card.handle, card.buttons = QRectF(), QRectF(), {}
            if getattr(self, "mini", False) or getattr(self, "crowded", False):
                # окошко в окне выделения: только маленький крестик в углу внутри области (остальное в панели окна выделения)
                close = QRectF(reg.right() - 24, reg.top() + 3, 21, 21)
                card.buttons["close"] = close
                p.setPen(QPen(QColor(255, 255, 255, 230), 1))
                p.setBrush(QColor(0, 0, 0, 120))
                p.drawEllipse(close)
                p.setPen(QPen(QColor("#ffffff"), 1.6))
                c = close.center()
                p.drawLine(QPointF(c.x() - 4, c.y() - 4), QPointF(c.x() + 4, c.y() + 4))
                p.drawLine(QPointF(c.x() + 4, c.y() - 4), QPointF(c.x() - 4, c.y() + 4))
            return
        if card.state == "error":
            self._tr_paint_error_card(p, card, col)   # 1.32.4: одна карточка: заголовок, действия, объяснение
            return
        chip = self._tr_chip_rect(card)
        card.chip = chip
        p.setPen(Qt.PenStyle.NoPen)
        for i, alpha in ((8, 8), (5, 12), (2, 16)):   # мягкая тень плашки
            p.setBrush(QColor(8, 60, 55, alpha))
            p.drawRoundedRect(chip.adjusted(-i, -i + 4, i, i + 4), 14 + i, 14 + i)
        p.setPen(QPen(col["border"], 1))
        p.setBrush(col["card"])
        p.drawRoundedRect(chip.adjusted(0.5, 0.5, -0.5, -0.5), 14, 14)
        self._tr_paint_head(p, card, chip, col)

    def _tr_error_card_rect(self, card) -> tuple:
        """Одна карточка ошибки поверх снимка: шапка с заголовком и действиями, под ней объяснение. Целиком в видимой части."""
        text = self._tr_error_text(card)
        note, text_h = self._tr_notice_box(QRectF(card.region), text)   # место и высота строк текста объяснения
        bounds = self._tr_bounds()
        w = min(max(note.width(), card.header_need, 260.0), max(120.0, bounds.width() - 8))
        h = self.CHIP_H + text_h + 28
        x = max(bounds.left() + 4, min(note.left(), bounds.right() - w - 4))
        y = max(bounds.top() + 4, min(note.top(), bounds.bottom() - h - 4))
        return QRectF(x, y, w, h), text, text_h

    def _tr_paint_error_card(self, p: QPainter, card, col: dict):
        self._tr_layout_overlay(card)
        box, text, text_h = self._tr_error_card_rect(card)
        card.chip = box
        p.setPen(Qt.PenStyle.NoPen)
        for i, alpha in ((8, 8), (5, 12), (2, 16)):
            p.setBrush(QColor(8, 60, 55, alpha))
            p.drawRoundedRect(box.adjusted(-i, -i + 4, i, i + 4), 14 + i, 14 + i)
        p.setPen(QPen(col["border"], 1))
        p.setBrush(col["card"])
        p.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), 14, 14)
        self._tr_paint_head(p, card, box, col)
        p.setPen(QPen(col["line"], 1))
        p.drawLine(QPointF(box.left() + 1, box.top() + self.CHIP_H), QPointF(box.right() - 1, box.top() + self.CHIP_H))
        circle = QRectF(box.left() + 14, box.top() + self.CHIP_H + 12, 26, 26)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#f59e0b"))
        p.drawEllipse(circle)
        p.setPen(QColor("#ffffff"))
        p.setFont(self._chip_font(16))
        p.drawText(circle, Qt.AlignmentFlag.AlignCenter, "!")
        p.setPen(col["text"])
        p.setFont(self._chip_font(13, bold=False))
        p.drawText(QRectF(box.left() + 52, box.top() + self.CHIP_H + 12, box.width() - 66, text_h + 4),
                   int(Qt.TextFlag.TextWordWrap) | int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop), text)

    def _tr_paint_card(self, p: QPainter, card: TranslateCard):
        if self._tr_view(card) == "overlay":
            self._tr_paint_overlay(p, card)
            return
        self._tr_layout(card)
        col = self._tr_palette()
        reg = QRectF(card.region)
        off = card.offset
        box = card.box()
        if card.cover is not None and card.cover.height() > card.content.height() + 1:
            p.setPen(QPen(col["teal"], 1.2, Qt.PenStyle.DashLine))   # остаток выделенной области: тонкий пунктир
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(card.cover.translated(off).adjusted(0.5, 0.5, -0.5, -0.5))
        if card.moved() and not self.tr_fill_card:
            # на старом месте снова виден оригинал, только тонкая пунктирная рамка
            p.setPen(QPen(col["teal"], 1.5, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(reg)
        # мягкая тень
        p.setPen(Qt.PenStyle.NoPen)
        for i, alpha in ((10, 8), (6, 12), (3, 16)):
            p.setBrush(QColor(8, 60, 55, alpha))
            p.drawRoundedRect(box.adjusted(-i, -i + 6, i, i + 6), 14 + i, 14 + i)
        path = QPainterPath()
        path.addRoundedRect(box, 14, 14)
        p.save()
        p.setClipPath(path)
        p.fillRect(box, col["card"])
        head = QRectF(box.left(), box.top(), box.width(), self.HEAD_H)
        p.fillRect(head, col["head"])
        p.fillRect(QRectF(head.left(), head.bottom() - 1, head.width(), 1), col["line"])
        body = QRectF(box.left(), head.bottom(), box.width(), box.height() - self.HEAD_H)
        p.save()
        p.setClipRect(body)
        if card.state == "done" and not card.show_original:
            font = QFont()
            font.setPixelSize(card.px_draw)
            p.setFont(font)
            p.setPen(col["text"])
            for text, y, h in card.paras:
                p.drawText(QRectF(body.left() + self.PAD_X, body.top() + y - card.scroll, body.width() - 2 * self.PAD_X, h + 4),
                           int(Qt.TextFlag.TextWordWrap) | int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop), text)
            if card.note:
                lines, ny, nh = card.note
                p.setFont(self._chip_font(13, bold=False))
                p.setPen(col["muted"])
                lh = nh / max(1, len(lines))
                for i, line in enumerate(lines):
                    p.drawText(QRectF(body.left() + self.PAD_X, body.top() + ny - card.scroll + i * lh,
                                      body.width() - 2 * self.PAD_X, lh),
                               int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), line)
            if card.scroll_max > 0:   # тонкая полоса прокрутки справа
                frac = body.height() / (body.height() + card.scroll_max)
                th = max(24.0, body.height() * frac)
                ty = body.top() + (body.height() - th) * (card.scroll / card.scroll_max)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(col["muted"].red(), col["muted"].green(), col["muted"].blue(), 110))
                p.drawRoundedRect(QRectF(body.right() - 7, ty + 2, 4, th - 4), 2, 2)
        elif card.state == "done":
            target = body.adjusted(self.PAD_X, self.PAD_Y, -self.PAD_X, -self.PAD_Y)
            self._tr_orig(p, target, card.region)
        elif card.state == "error":
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            circle = QRectF(body.left() + self.PAD_X, body.top() + self.PAD_Y, 26, 26)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#f59e0b"))
            p.drawEllipse(circle)
            p.setPen(QColor("#ffffff"))
            p.setFont(self._chip_font(16))
            p.drawText(circle, Qt.AlignmentFlag.AlignCenter, "!")
            text, y, h = card.paras[0]
            p.setPen(col["text"])
            p.setFont(self._chip_font(14, bold=False))
            p.drawText(QRectF(body.left() + self.PAD_X + 40, body.top() + y, body.width() - 2 * self.PAD_X - 40, h + 4),
                       int(Qt.TextFlag.TextWordWrap) | int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop), text)
        else:
            from .busy import draw_spinner
            radius = max(10.0, min(22.0, min(body.width(), body.height()) / 4))
            c = body.center()
            draw_spinner(p, QPointF(c.x(), c.y()), radius, self.tr_phase, col["teal"])
            if card.full:
                self._tr_busy_label(p, QPointF(c.x(), c.y() + radius + 12), self.tr_full_wait)
        p.restore()
        p.restore()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(col["border"], 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), 14, 14)
        self._tr_paint_head(p, card, box, col)

    def _tr_paint_head(self, p: QPainter, card, box: QRectF, col: dict):
        """Шапка: язык (нажатие открывает список), сервис приглушённо, кнопки справа, круглый крестик."""
        label, service, items = self._tr_head(card)
        fb, fn = self._chip_font(14), self._chip_font(14, bold=False)
        fmb, fmn = QFontMetrics(fb), QFontMetrics(fn)
        top = box.top() + (self.HEAD_H - 28) / 2
        card.buttons = {}
        card.handle = QRectF(box.left(), box.top(), box.width(), self.HEAD_H)
        # круглый крестик
        cx = box.right() - 10 - 28
        close = QRectF(cx, top, 28, 28)
        card.buttons["close"] = close
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 18) if col["card"].lightness() > 128 else QColor(255, 255, 255, 28))
        p.drawEllipse(close)
        p.setPen(QPen(col["muted"], 1.8))
        c = close.center()
        p.drawLine(QPointF(c.x() - 5, c.y() - 5), QPointF(c.x() + 5, c.y() + 5))
        p.drawLine(QPointF(c.x() + 5, c.y() - 5), QPointF(c.x() - 5, c.y() + 5))
        x = cx - 8
        left_limit = box.left() + 14 + fmb.horizontalAdvance(label) + 12
        p.setFont(fn)
        for kind, text, main in reversed(items):
            w = fmn.horizontalAdvance(text) + 26
            r = QRectF(x - w, top, w, 28)
            card.buttons[kind] = r
            p.setPen(QPen(col["teal"] if main else col["btn_line"], 1))
            p.setBrush(col["teal"] if main else col["btn"])
            p.drawRoundedRect(r, 8, 8)
            p.setPen(QColor("#ffffff") if main else col["btn_text"])
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)
            x -= w + 6
        # слева: язык и сервис
        p.setFont(fb)
        lab = QRectF(box.left() + 14, top, fmb.horizontalAdvance(label) + 4, 28)
        p.setPen(col["lang"])
        p.drawText(lab, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), label)
        if card.state == "done":
            card.buttons["lang"] = lab.adjusted(-4, 0, 4, 0)
            if service and x - left_limit >= fmn.horizontalAdvance(service) + 8:
                p.setFont(fn)
                p.setPen(col["muted"])
                p.drawText(QRectF(lab.right() + 8, top, x - lab.right() - 8, 28),
                           int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), service)

    def _tr_busy_label(self, p: QPainter, top_center: QPointF, text: str):
        """Подпись под кружком ожидания («Перевожу весь экран…») и напоминание про Esc."""
        font = self._chip_font(15)
        fm = QFontMetrics(font)
        sub = tr("translate_ui.esc_cancel")
        w = max(fm.horizontalAdvance(text), QFontMetrics(self._chip_font(12, bold=False)).horizontalAdvance(sub)) + 32
        box = QRectF(top_center.x() - w / 2, top_center.y() + 4, w, 50)
        bnd = self._tr_bounds()
        box.moveLeft(max(bnd.left() + 2, min(box.left(), bnd.right() - w - 2)))
        box.moveTop(max(bnd.top() + 2, min(box.top(), bnd.bottom() - box.height() - 2)))
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(32, 33, 36, 235))
        p.drawRoundedRect(box, 12, 12)
        p.setFont(font)
        p.setPen(QColor("#ffffff"))
        p.drawText(QRectF(box.left(), box.top() + 4, box.width(), 24), Qt.AlignmentFlag.AlignCenter, text)
        p.setFont(self._chip_font(12, bold=False))
        p.setPen(QColor(255, 255, 255, 190))
        p.drawText(QRectF(box.left(), box.top() + 27, box.width(), 18), Qt.AlignmentFlag.AlignCenter, sub)
        p.restore()

    def _tr_error_text(self, card) -> str:
        """Текст карточки ошибки перевода: сообщение и подсказка, что делать."""
        text = card.message
        if card.email_help():
            text += "\n\n" + tr("translate_ui.no_registration")
        elif card.key_help():
            text += "\n\n" + tr("translate_ui.setup_note")
        elif card.help is not None and card.help.command:
            text += "\n" + card.help.command
        return text

    def _tr_bounds(self) -> QRectF:
        """Где карточки и плашки должны помещаться целиком: окно целиком (в слое редактора переопределено: видимая часть снимка)."""
        return QRectF(0, 0, self.width(), self.height())

    def _tr_notice_box(self, reg: QRectF, text: str, window_width: int = None):
        """Место карточки сообщения (_tr_notice) в координатах окна и высота строк текста. Не меньше 220x56 точек: на
        маленьком куске она больше самого куска. window_width: прижать к правому краю окна такой ширины."""
        font = self._chip_font(13, bold=False)
        bounds = self._tr_bounds()   # 1.32.4: карточка целиком в видимой части, а не по краю сдвинутого снимка
        vis = QRectF(reg).intersected(bounds)
        if vis.width() < 40 or vis.height() < 20:
            vis = bounds
        width = int(max(220, min(vis.width() - 16, 560)))
        width = int(min(width, max(120.0, bounds.width() - 8)))
        br = QFontMetrics(font).boundingRect(QRect(0, 0, width - 64, 2000), Qt.TextFlag.TextWordWrap, text)
        box = QRectF(vis.left() + 8, vis.top() + 8, width, max(br.height() + 24, 56))
        box.moveLeft(max(bounds.left() + 4, min(box.left(), bounds.right() - box.width() - 4)))
        box.moveTop(max(bounds.top() + 4, min(box.top(), bounds.bottom() - box.height() - 4)))
        return box, br.height()

    def _tr_notice(self, p: QPainter, reg: QRectF, text: str):
        """Предупреждение в стиле окон ClipSD: светлая карточка, оранжевый значок «!», тёмный текст."""
        font = self._chip_font(13, bold=False)
        box, text_h = self._tr_notice_box(reg, text, self.width())
        width = int(box.width())
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(QColor("#f5c45b"), 1))
        p.setBrush(QColor("#fffbeb"))
        p.drawRoundedRect(box, 10, 10)
        circle = QRectF(box.left() + 14, box.top() + 14, 28, 28)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#f59e0b"))
        p.drawEllipse(circle)
        p.setPen(QColor("#ffffff"))
        p.setFont(self._chip_font(16))
        p.drawText(circle, Qt.AlignmentFlag.AlignCenter, "!")
        p.setPen(QColor("#3b2f12"))
        p.setFont(font)
        p.drawText(QRectF(box.left() + 52, box.top() + 12, width - 64, text_h + 4),
                   int(Qt.TextFlag.TextWordWrap) | int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop), text)
        p.restore()

    def _tr_label(self, p: QPainter, reg: QRectF, text: str, color: QColor, wide=False):
        font = self._chip_font(13)
        fm = QFontMetrics(font)
        width = max(160, min(int(reg.width()) - 8, 520)) if reg.width() > 170 else 300
        if wide:
            width = 560   # инструкция по ключу: читаемой ширины, даже если кусок маленький
        br = fm.boundingRect(QRect(0, 0, width, 1000), Qt.TextFlag.TextWordWrap, text)
        box = QRectF(reg.center().x() - (br.width() + 20) / 2, reg.center().y() - (br.height() + 14) / 2,
                     br.width() + 20, br.height() + 14)
        if wide:
            box.moveTop(reg.top() + 6)   # длинная инструкция: от верха карточки, под строкой кнопок
            box.moveLeft(reg.left() + 6)
        bnd = self._tr_bounds()
        box.moveLeft(max(bnd.left() + 4, min(box.left(), bnd.right() - box.width() - 4)))   # не уходить за край видимой части
        box.moveTop(max(bnd.top() + 34, min(box.top(), bnd.bottom() - box.height() - 4)))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(box, 8, 8)
        p.setPen(QColor("#ffffff"))
        p.setFont(font)
        align = (Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop) if wide else Qt.AlignmentFlag.AlignCenter
        p.drawText(box.adjusted(10, 7, -10, -7), int(Qt.TextFlag.TextWordWrap) | int(align), text)

    def _tr_paint_banner(self, p: QPainter):
        """Полоса режима: белая скруглённая плашка с мягкой тенью, как карточка перевода; цвета из темы."""
        col = self._tr_palette()
        bar = self._tr_banner_rect()
        p.setPen(Qt.PenStyle.NoPen)
        for i, alpha in ((10, 8), (6, 12), (3, 16)):   # мягкая тень
            p.setBrush(QColor(8, 60, 55, alpha))
            p.drawRoundedRect(bar.adjusted(-i, -i + 5, i, i + 5), 14 + i, 14 + i)
        p.setPen(QPen(col["border"], 1))
        p.setBrush(col["card"])
        p.drawRoundedRect(bar.adjusted(0.5, 0.5, -0.5, -0.5), 14, 14)
        font, small = self._chip_font(14), self._chip_font(14, bold=False)
        fm, fms = QFontMetrics(font), QFontMetrics(small)
        p.setFont(font)
        bh = bar.height() - 20
        x = bar.right() - 10
        self.tr_banner = {}

        def place(name, text, w=None):
            nonlocal x
            w = w or fm.horizontalAdvance(text) + 26
            r = QRectF(x - w, bar.top() + 10, w, bh)
            x -= w + 8
            self.tr_banner[name] = r
            return r
        place("done", "✕  " + tr("translate_ui.close_esc"))
        if any(c.state == "done" for c in self.tr_cards):
            place("copyall", tr("translate_ui.copy_all"))
        from .translate import lang_name, target_lang
        lang_text = tr("translate_ui.to_lang", lang=lang_name(target_lang(self.tr_cfg))) + " ▾"
        place("lang", lang_text)   # язык перевода: список языков
        engine = self.tr_cfg.get("translate_engine", "mymemory")
        if engine == "mymemory" and not self.tr_cfg.get("translate_email", "").strip():
            place("email", tr("translate_ui.email_short"))   # почта для MyMemory: лимит в 10 раз больше
        seg_w = [fm.horizontalAdvance(t) + 24 for t in ("Google", "MyMemory")]
        place("engine:google", "Google", seg_w[0])
        x += 8   # две половинки переключателя вплотную
        place("engine:mymemory", "MyMemory", seg_w[1])
        left = bar.left() + 16
        text_w = x - left - 4
        # надписи слева помещаются целиком: берётся самый полный вариант из тех, что влезают в место
        head = self._tr_fit(fm, (tr("translate_ui.head_long"), tr("translate_ui.head_mid"),
                                 tr("translate_ui.head_short")), text_w)
        p.setPen(col["lang"])
        p.drawText(QRectF(left, bar.top() + 7, text_w, 24), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), head)
        p.setFont(small)
        p.setPen(col["muted"])
        if getattr(self, "tr_usage_texts", None) is None:
            self._tr_refresh_usage()
        short, full_usage = self.tr_usage_texts
        usage = self._tr_fit(fms, (short, short.split(": ", 1)[-1]), text_w)
        p.drawText(QRectF(left, bar.top() + 31, text_w, 22), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), usage)
        self.tr_banner_texts = (head, usage, text_w)   # что нарисовано и сколько было места (для проверки)
        # полный текст: всплывающая подсказка над надписями (расход считает сам ClipSD, без запросов в сеть)
        self.tr_banner_tip = (QRectF(left, bar.top() + 4, text_w, bar.height() - 8),
                              tr("translate_ui.banner_tip", usage=full_usage))
        p.setFont(font)
        for name, r in self.tr_banner.items():
            on = name.startswith("engine:") and name[7:] == engine
            p.setPen(QPen(col["teal"] if on else col["btn_line"], 1))
            p.setBrush(col["teal"] if on else col["btn"])
            if name.startswith("engine:"):
                p.drawRoundedRect(r, 8, 8)   # сегменты вплотную: общий вид переключателя
                text = "Google" if name.endswith("google") else "MyMemory"
            else:
                p.drawRoundedRect(r, 8, 8)
                text = {"lang": lang_text, "email": tr("translate_ui.email_short"), "done": "✕  " + tr("translate_ui.close_esc")}.get(name, tr("translate_ui.copy_all"))
            p.setPen(QColor("#ffffff") if on else col["btn_text"])
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)


class TranslateLayer(TranslateMixin, QWidget):
    """Режим перевода в редакторе: прозрачный слой поверх снимка, те же переводы, что при снимке.
    Переводы не попадают в сохраняемый снимок; при обрезке или отмене снимок меняется, и они убираются."""

    tr_banner_enabled = False
    tr_dim = False
    tr_chip = False          # 1.29: переключатели и «Скопировать перевод» внизу окна редактора, плашка на снимке не рисуется
    tr_cover_region = True   # карточка не меньше выделенной области и закрывает её целиком

    def __init__(self, canvas, on_close):
        super().__init__(canvas)
        self.canvas = canvas
        self.on_close = on_close
        self._done = False
        self._tr_init()
        self.translate_mode = True
        self.setMouseTracking(True)
        self._last_w = max(1, canvas.width())
        self.floats = []   # окошки перевода вида «Карточкой»: отдельные окна верхнего уровня, не слой
        canvas.installEventFilter(self)
        self.setGeometry(canvas.rect())
        self.activate(False)

    def _tr_redo_allowed(self) -> bool:
        return self.isVisible()   # режим закрыт (Esc или «Готово»): слой скрыт

    def _tr_bounds(self) -> QRectF:
        """Слой лежит на всём снимке, а окно показывает его часть: карточки и плашки прижимаются к видимой части."""
        vis = self.visibleRegion().boundingRect()
        return QRectF(vis) if not vis.isEmpty() else QRectF(self.rect())

    @property
    def tr_floating(self) -> bool:
        """Вид «Карточкой»: перевод уходит в отдельное окошко, его можно унести за пределы окна редактора."""
        return self._tr_view_default() == "card"

    def set_floats_visible(self, on: bool):
        """Редактор свёрнут: окошки прячутся, при восстановлении возвращаются."""
        for win in list(self.floats):
            try:
                win.setVisible(on)
            except RuntimeError:
                pass

    def close_floats(self):
        for win in list(self.floats):
            try:
                win.tr_state_hook = None   # слой уходит вместе с редактором: окошко не должно звать его после закрытия
                win.close()
            except RuntimeError:
                pass
        self.floats = []

    tr_full_noun = "snapshot"
    tr_full_wait = _Tr("translate_ui.full_wait_snapshot")

    def activate(self, on: bool):
        if not on:
            self._tr_cancel_busy()   # Esc или «Готово»: долгий перевод всего снимка отменяется
            self.close_floats()   # окошки закрываются вместе с выходом из режима перевода
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, not on)
        self.setVisible(on)
        if on:
            self.setGeometry(self.canvas.rect())
            self.raise_()
            self.setCursor(Qt.CursorShape.CrossCursor)
            self._tr_refresh_usage()

    def clear(self):
        self.tr_cards = []
        self.close_floats()
        self.update()
        self.tr_state_changed()

    # --- вид «Карточкой»: отдельное окошко ---------------------------------------------------------

    def _tr_new_float(self, rect: QRect):
        crop = self.canvas.base.copy(self._tr_phys(QRectF(rect)))
        win = FloatingTranslation(crop, self._tr_scale(), QRect(self.mapToGlobal(rect.topLeft()), rect.size()),
                                  self.tr_cfg, self.tr_save, view="card", owner=self, source=QRect(rect))
        self.floats.append(win)
        win.tr_state_hook = self.tr_state_changed   # состояние окошка («Карточкой») доходит до строки внизу редактора
        win.destroyed.connect(lambda *_: self.floats.remove(win) if win in self.floats else None)
        return win

    def _tr_spawn_floating(self, rect: QRect):
        win = self._tr_new_float(rect)
        win.place_hook = self._tr_place
        win.start()

    tr_full_all = _Tr("translate_ui.all_done_snapshot")

    def _tr_full_exists(self):
        state = super()._tr_full_exists()
        if state == "busy":
            return state
        if any(r.owner is self for r in _runs):
            return "busy"
        for win in list(self.floats):
            if sip.isdeleted(win):
                continue
            if win.tr_cards and win.tr_cards[0].full:
                st = win.tr_cards[0].state
                state = "busy" if st in ("busy", "wait") else ("done" if st == "done" else state)
                if state == "busy":
                    return state
        return state

    def _tr_spawn_full(self, rect: QRect):
        """Вид «Карточкой»: окошко перевода всего снимка появляется с готовым результатом, до этого маленькое ожидание."""
        crop = self._tr_crop_image(rect)

        def make(local: QRect):
            win = self._tr_new_float(QRect(local))
            win.place_hook = self._tr_place
            return win
        FullRun(crop, self.tr_cfg, QRect(self.mapToGlobal(rect.topLeft()), rect.size()), rect.size(), make,
                say=self._tr_say, noun=self.tr_full_noun, wait=self.tr_full_wait, owner=self,
                on_state=self.tr_state_changed, center=self.window().frameGeometry().center())

    # --- управление всеми переводами сразу (нижняя бирюзовая полоса редактора) -------------------------

    def all_cards(self):
        """Все куски перевода: на снимке и в окошках «Карточкой»."""
        cards = list(self.tr_cards)
        for win in list(self.floats):
            if not sip.isdeleted(win):
                cards += list(win.tr_cards)
        return cards

    def all_text(self) -> str:
        """Переведённое для копирования: всё, что видно как перевод текущего запроса (в том числе кусок или абзац, который
        сервис перевёл на запасной язык, потому что текст уже на языке перевода). Не копируется ответ прежнего запроса:
        кусок, ушедший на другой язык, чем выбран сейчас, пока он не переведён заново."""
        from . import translate
        want = translate._norm(translate.target_lang(self.tr_cfg))
        parts = []
        for c in self.all_cards():
            if c.state != "done" or (c.req_lang and c.req_lang != want):
                continue
            text = c.text()
            if text:
                parts.append(text)
        return "\n\n".join(parts)

    def stats(self):
        """(переведено абзацев, пропущено как русские, всего к переводу, обрезано лимитом) по готовым кускам."""
        done = [c for c in self.all_cards() if c.state == "done"]
        return (sum(len(c.blocks) for c in done), sum(c.skipped for c in done), sum(c.total for c in done),
                any(c.partial for c in done))

    def set_original(self, on: bool):
        """«Перевод / Оригинал» для всех кусков."""
        for c in self.all_cards():
            c.show_original = bool(on)
        for win in list(self.floats):
            if not sip.isdeleted(win):
                win.update()
        self.update()

    def showing_original(self) -> bool:
        cards = [c for c in self.all_cards() if c.state == "done"]
        return bool(cards) and all(c.show_original for c in cards)

    def set_view_all(self, new: str):
        """«Поверх текста / Карточкой» для всех кусков; выбор запоминается (translate_view)."""
        if new not in self.VIEWS:
            return
        self.tr_cfg["translate_view"] = new
        if callable(self.tr_save):
            self.tr_save()
        if new == "card":
            for card in list(self.tr_cards):
                if card.state in ("done", "error"):
                    card.view, card.laid = "card", None
                    self._tr_view_changed(card, "card")
        else:
            for win in list(self.floats):
                if not sip.isdeleted(win) and win.tr_cards and win._tr_view(win.tr_cards[0]) == "card":
                    win._tr_toggle_view(win.tr_cards[0])
        self.update()
        self.tr_state_changed()

    def shutdown(self):
        """Редактор закрывается: идущие переводы и вопрос про лимит отменяются, результат больше некому показывать."""
        self._tr_shutdown()
        for run in [r for r in _runs if r.owner is self]:
            run.cancel()
        self.close_floats()
        self.tr_state_hook = None

    def _tr_say(self, text: str):
        """В редакторе сообщение всплывает в окне редактора."""
        from . import ocr
        ocr.toast(self, text, mark=False)   # информация, не «успех»: без галочки

    def _tr_full_skipped(self) -> int:
        """Сколько абзацев готового перевода всего снимка пропущено (уже на русском)."""
        n = sum(c.skipped for c in self.tr_cards if c.full)
        for win in list(self.floats):
            if not sip.isdeleted(win):
                n += sum(c.skipped for c in win.tr_cards if c.full)
        return n

    def _tr_full_partial(self) -> bool:
        """Готовый перевод всего снимка неполный из-за дневного лимита."""
        cards = [c for c in self.tr_cards if c.full]
        for win in list(self.floats):
            if not sip.isdeleted(win):
                cards += [c for c in win.tr_cards if c.full]
        return any(c.partial for c in cards)

    def _tr_cancel_busy(self):
        super()._tr_cancel_busy()
        for run in [r for r in _runs if r.owner is self]:
            run.cancel()   # Esc или «Готово»: ожидание перевода всего снимка снимается
        for win in list(self.floats):   # окошко вида «Карточкой» с идущим переводом всего снимка закроется вместе с режимом
            if not sip.isdeleted(win) and any(c.full and c.state in ("busy", "wait") for c in win.tr_cards):
                win.close()

    def _tr_view_changed(self, card, new: str):
        """«Карточкой»: перевод этого куска переезжает из слоя в своё окошко (без нового запроса в сеть)."""
        if new != "card":
            return
        win = self._tr_new_float(QRect(card.region))
        win.place_hook = self._tr_place
        win.load(card)
        if card in self.tr_cards:
            self.tr_cards.remove(card)
        win.start(run=False)

    def _tr_choose_lang(self, code: str, card=None):
        """Язык меняется: куски на снимке и окошки «Карточкой» переводятся заново."""
        super()._tr_choose_lang(code, card)
        if card is None:
            for win in list(self.floats):
                if sip.isdeleted(win) or not win.tr_cards:
                    continue
                if win.tr_cards[0].state in ("done", "error"):
                    win._tr_redo(win.tr_cards[0])
                elif win.tr_cards[0].state == "busy":
                    win.tr_cards[0].redo_lang = True
        self.tr_state_changed()

    def adopt(self, win, card_src):
        """Окошко «Карточкой» переключили на «Поверх текста»: кусок возвращается на снимок слоем."""
        src = QRect(win.source)
        card = TranslateCard(src)
        card.view = "overlay"
        dx = src.x() - card_src.region.x()
        dy = src.y() - card_src.region.y()
        card.state, card.message, card.help = card_src.state, card_src.message, card_src.help
        card.show_original, card.px = card_src.show_original, card_src.px
        card.req_lang = card_src.req_lang   # язык запроса переезжает вместе с куском (иначе копировался бы прежний перевод)
        for b in card_src.blocks:
            nb = dict(b)
            nb["rect"], nb["draw"] = QRectF(b["rect"]).translated(dx, dy), QRectF(b["draw"]).translated(dx, dy)
            card.blocks.append(nb)
        card.content = QRectF(src)
        self.tr_cards.append(card)
        self.update()

    def _tr_place(self, win):
        """Где первый раз встаёт окошко: справа от окна редактора, если на экране есть место; иначе слева;
        иначе на месте выделенной области. Дальше его двигает владелец."""
        ed = self.window()
        screen = ed.screen() or QGuiApplication.primaryScreen()
        area = screen.availableGeometry() if screen is not None else QRect(0, 0, 1280, 800)
        fg, w, h = ed.frameGeometry(), win.width(), win.height()
        ey = max(area.top(), min(win.anchor_top(), area.bottom() + 1 - h))
        if fg.right() + 8 + w <= area.right() + 1:
            return QPoint(fg.right() + 8, ey)
        if fg.left() - 8 - w >= area.left():
            return QPoint(fg.left() - 8 - w, ey)
        # сбоку места нет: окошко остаётся на снимке, но в пределах поля снимка (ниже панелей инструментов, выше строки
        # состояния; выше поля: прижато к верху). Дальше человек тащит его куда угодно.
        vp = ed.scroll.viewport()   # поле снимка
        field = QRect(vp.mapToGlobal(QPoint(0, 0)), vp.size())
        left, right, top, bottom = win.frame_extents_margins()
        vis = QRect(win.x() + left, win.y() + top, win.width() - left - right, win.height() - top - bottom)
        dy = 0
        if vis.top() < field.top() or vis.height() > field.height():
            dy = field.top() - vis.top()
        elif vis.bottom() > field.bottom():
            dy = field.bottom() - vis.bottom()
        dx = 0
        if vis.left() < field.left():
            dx = field.left() - vis.left()
        elif vis.right() > field.right() and vis.width() <= field.width():
            dx = field.right() - vis.right()
        return QPoint(win.x() + dx, win.y() + dy) if (dx or dy) else None

    # места, зависящие от окна
    def _tr_alive(self):
        return not self._done

    def _tr_scale(self):
        return self.canvas.base.devicePixelRatio() / self.canvas.zoom

    def _tr_phys(self, rect: QRectF) -> QRect:
        k = self._tr_scale()
        return QRect(round(rect.x() * k), round(rect.y() * k), max(1, round(rect.width() * k)), max(1, round(rect.height() * k)))

    def _tr_image(self):
        return self.canvas.base

    def _tr_crop_image(self, region: QRect):
        return self.canvas.base.copy(self._tr_phys(QRectF(region)))

    def _tr_orig(self, p, target, region):
        p.drawImage(target, self.canvas.base, QRectF(self._tr_phys(QRectF(region))))

    def _tr_close_mode(self):
        self.on_close()

    def _tr_leave_for_browser(self):
        pass   # редактор не держит клавиатуру и не закрывает экран: окно можно открыть сразу

    def _tr_copy_msg(self, text, near):
        """Сообщение «Скопировано» ложится в строку подсказки редактора, а не рядом с карточкой на текст снимка."""
        from . import ocr
        ocr.toast(self, text)

    def _tr_cover_edges(self, card, content: QRectF) -> QRectF:
        """Выделение рамкой часто режет строку пополам: оставшаяся часть оригинала торчала бы из-под карточки.
        Смотрим на снимке полосу сразу за каждой стороной рамки: есть «чернила» (отличие от фона), значит строка
        продолжается, и карточка растёт, пока не кончатся чернила, но не больше чем на полстроки с каждой стороны."""
        image, k = self.canvas.base, self._tr_scale()
        if image is None or image.isNull() or not card.blocks:
            return content
        bg = card.blocks[0]["bg"]
        line = max(8.0, min(b["rect"].height() for b in card.blocks))   # высота строки в точках снимка
        limit = int(line * 0.5 * k)   # не дальше половины строки: соседнюю непереведённую строку не накрываем
        iw, ih = image.width(), image.height()
        reg = self._tr_phys(QRectF(content))
        x1, x2 = max(0, reg.left()), min(iw - 1, reg.right())
        y1, y2 = max(0, reg.top()), min(ih - 1, reg.bottom())

        def ink(points):
            n = 0
            for x, y in points:
                c = image.pixelColor(x, y)
                if abs(c.red() - bg.red()) + abs(c.green() - bg.green()) + abs(c.blue() - bg.blue()) > 90:
                    n += 1
            return n

        def grow(edge, step, horizontal):
            """Насколько (в пикселях снимка) выйти за сторону: пока в соседней полосе есть чернила."""
            done, quiet = 0, 0
            for d in range(1, limit + 1):
                if horizontal:
                    pos = edge + step * d
                    if not 0 <= pos < ih:
                        break
                    pts = ((x, pos) for x in range(x1, x2 + 1, max(1, (x2 - x1) // 160)))
                else:
                    pos = edge + step * d
                    if not 0 <= pos < iw:
                        break
                    pts = ((pos, y) for y in range(y1, y2 + 1, max(1, (y2 - y1) // 160)))
                if ink(pts):
                    done, quiet = d, 0
                elif d <= 3:
                    continue   # щель в пару пикселей между рамкой и строкой не считается концом
                else:
                    quiet += 1
                    if quiet >= 2:
                        break
            return done

        out = QRectF(content)
        pad = 3.0 / max(k, 0.01)
        for edge, step, horizontal, side in ((y2, 1, True, "b"), (y1, -1, True, "t"),
                                             (x2, 1, False, "r"), (x1, -1, False, "l")):
            n = grow(edge, step, horizontal)
            if not n:
                continue
            grown = min(n / k + pad, line * 0.5)
            if side == "b":
                out.setBottom(out.bottom() + grown)
            elif side == "t":
                out.setTop(out.top() - grown)
            elif side == "r":
                out.setRight(out.right() + grown)
            else:
                out.setLeft(out.left() - grown)
        return out.intersected(QRectF(self.rect()))

    def _tr_grow_selection(self, rect: QRect) -> QRect:
        """Рамка выделения часто режет строку: верх рамки проходит по середине букв, край по середине слова.
        Распознавание по такому обрезку давало мусор («SEs SEE = чи»), а разрезанная строка оставалась без перевода
        (1.32.3: заголовок, по которому владелец провёл маркер, обведён от середины первой строки). Перед распознаванием
        рамка поправляется по чистому снимку (без пометок): строка, от которой захвачена хотя бы треть, берётся целиком,
        а тонкая полоска чужой строки у края в распознавание не идёт; слово, разрезанное боковым краем, дочитывается
        до пробела (не дальше трёх высот букв). Край меняется, только если режет «чернила» (отличие от фона прямо по обе
        стороны края); рамка по пустому месту остаётся как есть. Окно выделения экрана работает по рамке как раньше."""
        image, k = self.canvas.base, self._tr_scale()
        if image is None or image.isNull():
            return rect
        iw, ih = image.width(), image.height()
        reg = self._tr_phys(QRectF(rect)).intersected(QRect(0, 0, iw, ih))
        if reg.width() < 4 or reg.height() < 4:
            return rect
        bg = sample_colors(image, reg)[0]

        def ink(x, y):
            c = image.pixelColor(x, y)
            return abs(c.red() - bg.red()) + abs(c.green() - bg.green()) + abs(c.blue() - bg.blue()) > 90

        def row(y, a, b):
            return 0 <= y < ih and any(ink(x, y) for x in range(a, b + 1, max(1, (b - a) // 1200)))

        def col(x, a, b):
            return 0 <= x < iw and any(ink(x, y) for y in range(a, b + 1, max(1, (b - a) // 600)))

        def reach(has, limit, gap):
            """Последний шаг с чернилами, если идти от края (пустых шагов подряд не больше gap); -1: чернил нет."""
            last = -1
            for d in range(max(0, limit)):
                if has(d):
                    last = d
                elif d - last > gap:
                    break
            return last

        pad = 2   # пикселя снимка за последними чернилами: буквы не касаются края куска
        x1, x2, y1, y2 = reg.left(), reg.right(), reg.top(), reg.bottom()
        least = max(4, round(8 * k))   # ниже этого кусок не сжимается
        # сверху и снизу: строка, разрезанная по высоте. Захвачена хотя бы треть строки: рамка забирает её целиком;
        # меньше (задет низ строки над абзацем или верх строки под ним): полоска не идёт в распознавание
        if row(y1, x1, x2) and row(y1 - 1, x1, x2):
            inside = reach(lambda d: row(y1 + d, x1, x2), y2 - y1 + 1, 2) + 1
            out = reach(lambda d: row(y1 - 1 - d, x1, x2), 3 * inside + 2, 2) + 1
            if out <= 2 * inside:
                y1 = max(0, y1 - out - pad)
            elif y2 - (y1 + inside) + 1 >= least:
                y1 += inside
        if row(y2, x1, x2) and row(y2 + 1, x1, x2):
            inside = reach(lambda d: row(y2 - d, x1, x2), y2 - y1 + 1, 2) + 1
            out = reach(lambda d: row(y2 + 1 + d, x1, x2), 3 * inside + 2, 2) + 1
            if out <= 2 * inside:
                y2 = min(ih - 1, y2 + out + pad)
            elif (y2 - inside) - y1 + 1 >= least:
                y2 -= inside

        def glyph_height(xa, xb):
            """Высота букв у края: самая длинная полоса рядов с чернилами (разрывы до 2 рядов) в полосе у края."""
            best = run = gap = 0
            for y in range(y1, y2 + 1):
                if any(ink(x, y) for x in range(max(0, xa), min(iw - 1, xb) + 1)):
                    run, gap = run + 1 + gap, 0
                    best = max(best, run)
                elif run:
                    gap += 1
                    if gap > 2:
                        run = gap = 0
            return best

        band = max(3, round(12 * k))
        # справа и слева: слово, разрезанное по ширине. Конец слова: пустой промежуток больше 0,4 высоты букв
        # (между буквами меньше, пробел больше); лишнее слово лучше разрезанной буквы
        if col(x2, y1, y2) and col(x2 + 1, y1, y2):
            h = glyph_height(x2 - band, x2)
            gap = max(2, round(h * 0.4))
            out = reach(lambda d: col(x2 + 1 + d, y1, y2), 3 * h + gap, gap)
            x2 = min(iw - 1, x2 + out + 1 + pad)
        if col(x1, y1, y2) and col(x1 - 1, y1, y2):
            h = glyph_height(x1, x1 + band)
            gap = max(2, round(h * 0.4))
            out = reach(lambda d: col(x1 - 1 - d, y1, y2), 3 * h + gap, gap)
            x1 = max(0, x1 - (out + 1 + pad))
        if (x1, x2, y1, y2) == (reg.left(), reg.right(), reg.top(), reg.bottom()):
            return rect
        left, top = math.floor(x1 / k), math.floor(y1 / k)
        grown = QRect(left, top, math.ceil((x2 + 1) / k) - left, math.ceil((y2 + 1) / k) - top)
        return grown.intersected(self.rect())

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        if obj is self.canvas and event.type() == QEvent.Type.Resize:
            w = max(1, self.canvas.width())
            if w != self._last_w:
                self._tr_rescale(w / self._last_w)   # Ctrl+колесо: переводы вместе со снимком
                self._last_w = w
            self.setGeometry(self.canvas.rect())
        return False

    def mousePressEvent(self, event):
        self._tr_press(event)

    def mouseMoveEvent(self, event):
        self._tr_move(event)

    def mouseReleaseEvent(self, event):
        self._tr_release(event)

    def wheelEvent(self, event):
        """Колесо над длинной карточкой прокручивает её; иначе событие идёт дальше (масштаб снимка)."""
        pos = event.position()
        for c in reversed(self.tr_cards):
            if c.scroll_max > 0 and c.box().contains(pos) and not event.modifiers():
                c.scroll = max(0.0, min(c.scroll_max, c.scroll - event.angleDelta().y() / 2.0))
                self.update()
                event.accept()
                return
        event.ignore()

    def paintEvent(self, _event):
        p = QPainter(self)
        self._tr_paint(p)


_floating = []   # открытые окошки перевода: живут сами по себе, после закрытия окна выделения


class FloatingTranslation(TranslateMixin, QWidget):
    """Отдельное окошко перевода поверх всех окон: экран при этом живой (браузер прокручивается, окна
    переключаются). Появляется на месте выделенного текста, перетаскивается мышью за перевод или подпись.
    Сверху «Язык → Язык», «Скопировать», «Оригинал», «Ещё»; справа вверху крестик."""

    tr_banner_enabled = False
    tr_dim = False
    tr_more_button = True
    tr_fill_card = True
    MARGIN, HEADER = 16, 16   # поля под тень карточки; шапка теперь внутри карточки
    request_more = None   # приложение: начать выделение следующего куска для перевода

    def __init__(self, crop, ratio: float, global_rect: QRect, cfg: dict, save=None, view=None, owner=None, source=None,
                 chip=True, backdrop=None, full=False, avoid=False):
        flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        if owner is None:
            flags |= Qt.WindowType.WindowStaysOnTopHint   # окно выделения: поверх всего
        # окошко редактора: не поверх всех программ, а дочернее окно редактора (transient): остаётся над ним,
        # прячется вместе с ним при сворачивании
        super().__init__(owner.window() if owner is not None else None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(tr("translate_ui.window_title"))
        self.crop, self.ratio_k = crop, ratio
        self._done = False
        self._tr_init()
        self.translate_mode = True
        self.tr_cfg, self.tr_save = cfg, save
        self.owner, self.source = owner, source   # редактор: слой перевода, из которого открыто окошко, и область в нём
        self.place_hook = None                    # редактор: где встать первый раз (рядом с окном редактора)
        if owner is not None:
            self.tr_more_button = False           # «Ещё» это новое выделение на экране; у окошка редактора его нет
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)   # фокус остаётся у редактора
        self._drag_from = None
        self.setMouseTracking(True)
        self.select_hook = None    # окно выделения: «это окошко выбрано» (кнопки его панели относятся к нему)
        self.more_hook = None      # окно выделения: «Перевести ещё кусок» без нового окна выделения
        # окно выделения открыто и в режиме перевода: у окошка нет плашки, только перевод и маленький крестик в углу;
        # кнопки языка, копирования, оригинала и вида стоят в строке панели окна выделения
        # кадр экрана вокруг куска: (QImage в физических точках, глобальная точка его левого верхнего угла, точек в точке);
        # по нему плашка обходит ещё не переведённый текст
        self.backdrop = backdrop
        self.mini = bool(owner is None and not chip)
        if self.mini:
            self.tr_chip = False
        self._full_area = bool(full)   # перевод всего экрана: плашка по прежним правилам (за краем монитора)
        if avoid and owner is None and not full:
            global_rect = self._free_spot(QRect(global_rect))   # кусок зашёл на открытое окошко: сдвиг на минимум
        m, h = self.MARGIN, self.HEADER
        self._anchor = QPoint(global_rect.x(), global_rect.y())   # где был оригинал (левый верхний угол выделения)
        self._user_moved = False
        view = "overlay" if self.mini else (view if view in self.VIEWS else self._tr_view_default())
        # «Поверх текста»: плашка снаружи области (под ней или над ней, потом справа и слева) и не поверх
        # других окошек и их плашек; на переведённый текст плашка не попадает
        self.crowded = False   # места для плашки нет: только крестик в углу, плашка при наведении мыши
        self._peek = False     # плашка зажатого окошка показана, пока над ним мышь
        self._peek_timer = None   # задержка перед тем, как убрать плашку зажатого окошка
        if self.mini or view != "overlay":
            self.chip_side, self.chip_dx = "none", 0.0
        else:
            self.chip_side, self.chip_dx, free = self._pick_chip(QRect(global_rect), 300)
            if not free:
                self.chip_side, self.chip_dx, self.crowded, self.tr_chip = "none", 0.0, True, False
        self.chip_below = self.chip_side == "below"
        rx, ry = self._side_offsets(view, self.chip_side, self.chip_dx)
        region = QRect(rx, ry, global_rect.width(), global_rect.height())
        self.setGeometry(global_rect.x() - rx, global_rect.y() - ry,
                         rx + global_rect.width() + m + (self.CHIP_SIDE_W + 8 if self.chip_side == "right" else 0),
                         ry + global_rect.height() + m + (self.CHIP_SPACE if self.chip_side == "below" else 0))
        card = TranslateCard(region)
        card.view = view
        self.tr_cards.append(card)
        _floating.append(self)
        self.destroyed.connect(lambda *_: _floating.remove(self) if self in _floating else None)
        for other in list(_floating):   # новое окошко могло оказаться на месте чужой плашки: та переезжает
            if other is not self and not sip.isdeleted(other):
                other._repick_chip()

    def _side_offsets(self, view, side, dx=0.0):
        """Где область перевода внутри окошка: (слева, сверху) с полями под тень и местом под плашку над или слева
        (и под плашку над или под областью, сдвинутую влево у правого края экрана)."""
        m = self.MARGIN
        left = self.CHIP_SIDE_W + 8 if view == "overlay" and side == "left" else 0
        if view == "overlay" and side in ("above", "below") and dx < 0:
            left = int(-dx + 0.999)
        return (m + left, self.HEADER + (self.CHIP_SPACE if view == "overlay" and side == "above" else 0))

    def _area_global(self, card=None) -> QRect:
        """Где область этого куска на экране (в глобальных точках)."""
        card = card or self.tr_cards[0]
        if getattr(self, "_user_moved", False) or self.isVisible():
            return QRect(self.geometry().topLeft() + card.region.topLeft(), card.region.size())
        return QRect(self._anchor, card.region.size())

    def _others(self, exclude=None):
        """Другие открытые окошки перевода (без закрытых и без перевода всего экрана)."""
        out = []
        for win in list(_floating):
            if win is exclude or win is self or sip.isdeleted(win) or getattr(win, "_done", False) or not win.tr_cards:
                continue
            if getattr(win, "_full_area", False) or win.tr_cards[0].full:
                continue
            out.append(win)
        return out

    def _free_spot(self, rect: QRect) -> QRect:
        """Новое окошко не ложится на уже открытые: если обведённый кусок заходит на область другого окошка, окошко
        сдвигается на наименьшее расстояние (вверх, вниз, влево или вправо) так, чтобы не задевать ни одно, в пределах
        экрана. Не нашлось такого места: остаётся на месте текста."""
        others = [QRect(w._area_global()) for w in self._others()]
        if not any(o.intersects(rect) for o in others):
            return rect
        screen = QGuiApplication.screenAt(rect.center()) or QGuiApplication.primaryScreen()
        bounds = screen.geometry() if screen is not None else QRect(0, 0, 1280, 800)
        gap = 4
        moves = set()
        for o in others:
            moves.add((0, o.top() - gap - (rect.top() + rect.height())))   # над ним
            moves.add((0, o.top() + o.height() + gap - rect.top()))        # под ним
            moves.add((o.left() - gap - (rect.left() + rect.width()), 0))  # слева
            moves.add((o.left() + o.width() + gap - rect.left(), 0))       # справа
        for dx, dy in sorted(moves, key=lambda d: (abs(d[0]) + abs(d[1]), d[1] < 0, d[0] < 0)):
            r = rect.translated(dx, dy)
            if bounds.contains(r) and not any(r.intersects(o) for o in others):
                return r
        return rect

    def _origin_global(self, card=None) -> QPoint:
        """Где левый верхний угол окошка на экране (до показа: по месту оригинала)."""
        card = card or self.tr_cards[0]
        return self._area_global(card).topLeft() - card.region.topLeft()

    def _box_global(self, card=None) -> QRectF:
        """Область перевода (выделение и строки, вышедшие за него) в глобальных точках."""
        card = card or self.tr_cards[0]
        o = self._origin_global(card)
        box = QRectF(card.content) if not card.content.isEmpty() else QRectF(card.region)
        return box.translated(o.x(), o.y())

    def _texts_global(self, card=None):
        """Строки перевода этого окошка в глобальных точках."""
        card = card or self.tr_cards[0]
        o = self._origin_global(card)
        return [QRectF(b["draw"]).united(QRectF(b["rect"])).translated(o.x(), o.y()) for b in card.blocks if b.get("text")]

    def _chip_spot(self, box: QRectF, side: str, dx: float, w: float) -> QRectF:
        """Плашка шириной w у области box (глобальные точки), как её рисует _tr_chip_rect."""
        h = float(self.CHIP_H)
        if side == "below":
            return QRectF(box.left() + dx, box.bottom() + 6, w, h)
        if side == "above":
            return QRectF(box.left() + dx, box.top() - h - 6, w, h)
        if side == "right":
            return QRectF(box.right() + 8 + dx, box.top(), w, h)
        return QRectF(box.left() - w - 8, box.top(), w, h)

    def _chip_global(self) -> QRectF:
        """Где плашка этого окошка на экране; пустой прямоугольник: плашки нет."""
        if self.mini or not self.tr_chip or self.chip_side == "none" or self._done or not self.tr_cards:
            return QRectF()
        card = self.tr_cards[0]
        if self._tr_view(card) != "overlay":
            return QRectF()
        return self._chip_spot(self._box_global(card), self.chip_side, self.chip_dx, max(card.header_need or 300, 200.0))

    CHIP_ORDER = ("below", "above", "right", "left")   # при равенстве: под областью, над ней, справа, слева
    TOP_RESERVE = 32   # плашка над областью не выше этого от верха монитора: там верхняя панель GNOME, и менеджер окон
    #                    сдвинул бы окошко вниз вместе с переводом (на нескольких мониторах Qt не знает о панели)

    def _pick_chip(self, area: QRect, need: float, exclude=None):
        """(сторона, сдвиг, свободно) плашки с кнопками. Плашка не заходит на переведённый текст этого окошка, на области
        и плашки других окошек и не выходит за экран. Места у левого края нет: плашка над или под областью едет вправо,
        но не дальше, чем на ширину области без 60 точек (плашка остаётся у своего окошка), у правого края экрана едет
        влево до края, плашка справа въезжает на пустое поле своей рамки. Из подходящих берётся место, где меньше всего ещё не переведённого текста, затем без
        сдвига, затем под областью, над ней, справа, слева. Подходящего нет (окошко зажато между соседними):
        свободно = False, место у своей области, где меньше всего закрыто переведённого текста (для показа плашки,
        пока над окошком мышь)."""
        if self._full_area:
            return self._pick_chip_side(area, need, exclude), 0.0, True
        w = float(int(max(need, 200)))
        screen = QGuiApplication.screenAt(area.center()) or QGuiApplication.primaryScreen()
        bounds = QRectF(screen.availableGeometry() if screen is not None else QRect(0, 0, 1280, 800))
        top_limit = max(bounds.top(), (screen.geometry().top() if screen is not None else 0) + self.TOP_RESERVE)

        def fits(side, rect):
            return bounds.contains(rect) and (side != "above" or rect.top() >= top_limit)
        hard, texts = [], []
        for win in self._others(exclude):
            hard.append(QRectF(win._area_global()))
            ch = win._chip_global()
            if not ch.isEmpty():
                hard.append(ch)
            texts += win._texts_global() or [QRectF(win._area_global())]   # перевод ещё идёт: текст займёт всю рамку
        own_area = QRectF(area)
        box, own = own_area, []
        if self.tr_cards:
            box, own = self._box_global(), self._texts_global()
        cands = []
        edge = bounds.right() - self.MARGIN   # сдвинутая плашка с полем под тень не выходит за экран: окошко не прыгает
        room = edge - w - box.left()   # насколько плашку над или под областью можно сдвинуть вправо (< 0: влево)
        span = max(0.0, min(room, box.width() - 60))   # плашка не уходит от своей области
        for side in ("below", "above"):
            for dx in sorted({0.0, round(span / 3), round(span * 2 / 3), round(span)}):
                cands.append((side, float(dx), self._chip_spot(box, side, dx, w)))
            if room < 0 and box.left() + room >= bounds.left():   # у правого края экрана плашка едет влево
                cands.append((side, float(math.floor(room)), self._chip_spot(box, side, math.floor(room), w)))
        r = self._chip_spot(box, "right", 0.0, w)
        cands.append(("right", 0.0, r))
        if r.right() > bounds.right():
            dx = edge - r.right()
            if box.right() + 8 + dx >= box.left():
                cands.append(("right", float(dx), self._chip_spot(box, "right", dx, w)))
        cands.append(("left", 0.0, self._chip_spot(box, "left", 0.0, w)))

        def hits(rect, rects):
            return sum(rect.intersected(o).width() * rect.intersected(o).height() for o in rects if rect.intersects(o))
        valid = [i for i, (side, _d, rect) in enumerate(cands)
                 if fits(side, rect) and not hits(rect, hard) and not hits(rect, own)]
        if valid:
            ink = {i: self._ink(cands[i][2].toAlignedRect()) for i in valid}
            low = min(ink.values())
            pool = [i for i in valid if ink[i] <= low + 0.004]
            best = min(pool, key=lambda i: (cands[i][2].intersects(own_area), abs(cands[i][1]),
                                            self.CHIP_ORDER.index(cands[i][0])))
            return cands[best][0], cands[best][1], True
        best = min(range(len(cands)), key=lambda i: (not fits(cands[i][0], cands[i][2]), hits(cands[i][2], texts + own),
                                                     hits(cands[i][2], hard), abs(cands[i][1]),
                                                     self.CHIP_ORDER.index(cands[i][0])))
        return cands[best][0], cands[best][1], False

    def _chip_is_free(self) -> bool:
        """Плашка стоит, на экране, не на тексте и не на рамках и плашках других окошек (тогда её не двигаем)."""
        ch = self._chip_global()
        if ch.isEmpty():
            return False
        screen = QGuiApplication.screenAt(ch.center().toPoint()) or QGuiApplication.primaryScreen()
        if screen is None or not QRectF(screen.availableGeometry()).contains(ch):
            return False
        busy = list(self._texts_global())
        for win in self._others():
            busy.append(QRectF(win._area_global()))
            busy += [r for r in (win._chip_global(),) if not r.isEmpty()]
        return not any(ch.intersects(r) for r in busy)

    def _apply_chip(self, side: str, shift: float, free: bool):
        """Плашка на свободное место; места нет: плашки нет (окошко зажато соседними), в углу только крестик, а плашка
        показывается, пока над окошком мышь."""
        if not free and self.tr_cards and self.tr_cards[0].state == "error":
            free = True   # у ошибки свои кнопки («Подключить Google…»): плашка нужна, пусть и на соседе
        self.crowded = not free
        self.tr_chip = free
        if free:
            self._set_chip_side(side, shift)
        else:
            self._set_chip_side("none", 0.0)
        self.update()

    def _pick_chip_side(self, area: QRect, need: float, exclude=None) -> str:
        """Перевод всего экрана (прежние правила 1.29). Сторона для плашки: под областью, если нет места, над ней,
        затем справа и слева. Плашка не заходит на область и на области других окошек и не выходит за экран; если
        не подходит ни одна, берётся с наименьшим наложением."""
        w, h = int(max(need, 200)), self.CHIP_H
        screen = QGuiApplication.screenAt(area.center()) or QGuiApplication.primaryScreen()
        bounds = screen.availableGeometry() if screen is not None else QRect(0, 0, 1280, 800)
        others = []
        for win in list(_floating):
            if win is exclude or win is self or sip.isdeleted(win) or getattr(win, "_done", False) or not win.tr_cards:
                continue
            others.append(win._area_global())
        spots = {"right": QRect(area.left() + area.width() + 8, area.top(), w, h),
                 "above": QRect(area.left(), area.top() - h - 6, w, h),
                 "below": QRect(area.left(), area.top() + area.height() + 6, w, h),
                 "left": QRect(area.left() - w - 8, area.top(), w, h)}
        order = ("right", "above", "below", "left")   # при равенстве: справа, над, под, слева

        def overlap(r):
            return sum(max(0, r.intersected(o).width()) * max(0, r.intersected(o).height()) for o in others if r.intersects(o))
        valid = [side for side in order if overlap(spots[side]) == 0 and bounds.contains(spots[side])]
        if valid:
            ink = {side: self._ink(spots[side]) for side in valid}
            low = min(ink.values())
            return next(side for side in valid if ink[side] <= low + 0.004)   # там, где меньше всего ещё не переведённого текста
        best, best_cost = "below", None
        for side in order:
            r = spots[side]
            cost = overlap(r) + (0 if bounds.contains(r) else 10 ** 9)
            if best_cost is None or cost < best_cost:
                best, best_cost = side, cost
        return best

    def _ink(self, r: QRect) -> float:
        """Сколько текста на кадре экрана в прямоугольнике r (глобальные точки): доля резких переходов цвета между
        соседними точками строк. У букв переходов много; ровная заливка (пустое поле страницы, рабочий стол) их не
        даёт, край окна или полоса прокрутки дают совсем мало. Так плашка не ложится на ещё не переведённый абзац,
        а уходит на пустое место, даже если там другой цвет."""
        bd = self.backdrop
        if not bd:
            return 0.0
        img, origin, ratio = bd
        if img is None or img.isNull():
            return 0.0
        x0, y0 = int((r.left() - origin.x()) * ratio), int((r.top() - origin.y()) * ratio)
        x1, y1 = int((r.right() + 1 - origin.x()) * ratio), int((r.bottom() + 1 - origin.y()) * ratio)
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(img.width(), x1), min(img.height(), y1)
        if x1 - x0 < 2 or y1 <= y0:
            return 0.0
        step = max(1, int(ratio))
        edges = pairs = 0
        for yy in range(y0, y1, max(2, int(ratio * 2))):
            prev = img.pixel(x0, yy)
            for xx in range(x0 + step, x1, step):
                c = img.pixel(xx, yy)
                if abs(((c >> 16) & 255) - ((prev >> 16) & 255)) + abs(((c >> 8) & 255) - ((prev >> 8) & 255)) \
                        + abs((c & 255) - (prev & 255)) > 90:
                    edges += 1
                prev = c
                pairs += 1
        return edges / pairs if pairs else 0.0

    def _set_chip_side(self, side: str, shift: float = 0.0):
        """Плашка переезжает на другую сторону (или сдвигается вдоль неё): область остаётся на месте оригинала,
        окошко меняет размер."""
        card = self.tr_cards[0]
        if self._tr_view(card) != "overlay" or (side == self.chip_side and shift == self.chip_dx):
            self.chip_side, self.chip_below, self.chip_dx = side, side == "below", shift
            return
        nx, ny = self._side_offsets("overlay", side, shift)
        dx, dy = nx - card.region.x(), ny - card.region.y()
        self.chip_side, self.chip_below, self.chip_dx = side, side == "below", shift
        if dx or dy:
            card.region = card.region.translated(dx, dy)
            for b in card.blocks:
                b["rect"], b["draw"] = b["rect"].translated(dx, dy), b["draw"].translated(dx, dy)
            card.content = card.content.translated(dx, dy)
            if self._user_moved:
                self.move(self.x() - dx, self.y() - dy)
        card.laid = None
        self._tr_sync_window()

    def _repick_chip(self):
        """После появления другого окошка проверить, что плашка этого ему не мешает."""
        if self.mini or not self.tr_cards or self._done or self.tr_cards[0].full:
            return
        card = self.tr_cards[0]
        if self._tr_view(card) != "overlay":
            return
        if self._peek or (not self.crowded and self._chip_is_free()):
            return   # плашка стоит на свободном месте: не прыгает
        self._apply_chip(*self._pick_chip(self._area_global(card), card.header_need or 300))

    def enable_chip(self):
        """Окно выделения закрыто (или режим перевода завершён): окошку возвращается плашка с кнопками, снаружи области."""
        if not self.mini or self._done:
            return
        self.mini = False
        self.tr_chip = True
        card = self.tr_cards[0]
        if self._tr_view(card) == "overlay":
            self._apply_chip(*self._pick_chip(self._area_global(card), card.header_need or 300))
        self.update()

    def frame_extents_margins(self):
        """Поля под тень по фактической геометрии: карточка (или область перевода) отстоит от края окна на поле;
        плашка с кнопками над областью видима, поэтому сверху её место в поле не входит."""
        m = self.MARGIN
        top = m
        if self.tr_cards:
            card = self.tr_cards[0]
            top = int(card.region.y())
            if self._tr_view(card) == "overlay" and self.chip_side == "above":
                top -= self.CHIP_SPACE
        return (m, m, max(0, top), m)

    def showEvent(self, event):
        super().showEvent(event)
        # менеджеру окон: видимая часть без полей под тень (слева, справа, сверху, снизу)
        track_frame_extents(self, self.frame_extents_margins)

    def start(self, run=True):
        track_frame_extents(self, self.frame_extents_margins)   # свойство ставится до первого показа
        self.show()
        self.raise_()
        if run:
            self._tr_run(self.tr_cards[0])
        self._tr_sync_window()
        if self.tr_cards and self.tr_cards[0].full:
            self.activateWindow()   # Esc во время долгого перевода всего экрана должен дойти до окошка

    def anchor_top(self) -> int:
        """Верх окошка, при котором оно стоит на месте оригинала (для первой расстановки рядом с редактором)."""
        card = self.tr_cards[0]
        return self._anchor.y() - int(card.region.y())

    def load(self, src):
        """Готовый перевод из слоя редактора (переключили вид): без нового запроса в сеть."""
        card = self.tr_cards[0]
        dx, dy = card.region.x() - src.region.x(), card.region.y() - src.region.y()
        card.state, card.message, card.help = src.state, src.message, src.help
        card.show_original, card.px = src.show_original, src.px
        card.req_lang = src.req_lang
        card.blocks = []
        for b in src.blocks:
            nb = dict(b)
            nb["rect"], nb["draw"] = QRectF(b["rect"]).translated(dx, dy), QRectF(b["draw"]).translated(dx, dy)
            card.blocks.append(nb)
        card.content, card.laid = QRectF(card.region), None
        self._src_card = src

    def _tr_view_changed(self, card, new: str):
        """Переключили вид в самом окошке. С редактором: «Поверх текста» возвращает кусок на снимок и закрывает окошко.
        Без редактора (окно выделения): окошко перестраивается на месте."""
        if self.owner is not None and new == "overlay":
            self.owner.adopt(self, card)
            self.close()
            return
        self.crowded = self._peek = False
        self.chip_side, self.chip_dx = "none", 0.0
        if new == "overlay" and not self.mini:
            side, shift, free = self._pick_chip(self._area_global(card), card.header_need or 300)
            free = free or card.state == "error"   # у ошибки свои кнопки: плашка нужна
            if free:
                self.chip_side, self.chip_dx = side, shift
            self.crowded, self.tr_chip = not free, free
        elif not self.mini:
            self.tr_chip = True
        self.chip_below = self.chip_side == "below"
        nx, ny = self._side_offsets(new, self.chip_side, self.chip_dx)
        dx, dy = nx - card.region.x(), ny - card.region.y()
        if dx or dy:   # область переезжает в окне: плашка рядом с ней появляется или исчезает
            card.region = card.region.translated(dx, dy)
            for b in card.blocks:
                b["rect"], b["draw"] = b["rect"].translated(dx, dy), b["draw"].translated(dx, dy)
            card.content = card.content.translated(dx, dy)
            if self._user_moved:
                self.move(self.x() - dx, self.y() - dy)   # окошко, которое уже унесли, остаётся на месте текста
        card.laid = None
        self._tr_sync_window()

    # места, зависящие от окна
    def _tr_alive(self):
        return not self._done

    def _tr_scale(self):
        return self.ratio_k

    def _tr_phys(self, rect: QRectF) -> QRect:
        reg, k = self.tr_cards[0].region if self.tr_cards else QRect(), self.ratio_k
        return QRect(round((rect.x() - reg.x()) * k), round((rect.y() - reg.y()) * k),
                     max(1, round(rect.width() * k)), max(1, round(rect.height() * k)))

    def _tr_image(self):
        return self.crop

    def _tr_crop_image(self, region):
        return self.crop

    def _tr_orig(self, p, target, region):
        p.drawImage(target, self.crop)

    def _tr_close_mode(self):
        self.close()

    def _tr_say(self, text: str):
        if self.owner is not None:
            self.owner._tr_say(text)   # окошко редактора: сообщение в окне редактора
        else:
            super()._tr_say(text)

    def _tr_leave_for_browser(self):
        pass   # окошко не мешает браузеру

    def _tr_more(self, rect=None):
        """«Ещё»: меню (сервис, остаток лимита, почта, скопировать всё, перевести ещё кусок)."""
        if rect is None:
            rect = QRectF(0, 0, 0, 0)
        self._tr_more_menu_at(self.mapToGlobal(QPoint(int(rect.left()), int(rect.bottom()))))

    def _tr_more_menu_at(self, gpos: QPoint, parent=None):
        from PyQt6.QtWidgets import QMenu
        from .menus import style_menu
        from . import translate
        menu = QMenu(parent or self)
        style_menu(menu, self.tr_cfg)
        engine = self.tr_cfg.get("translate_engine", "mymemory")
        for code, title in (("google", "Google"), ("mymemory", "MyMemory")):
            act = menu.addAction(tr("translate_ui.service", name=title))
            act.setCheckable(True)
            act.setChecked(engine == code)
            act.setData(("engine", code))
        try:
            used, limit = (translate.google_usage() if engine == "google" else translate.mymemory_usage(self.tr_cfg.get("translate_email", "")))
            n = number   # числа по правилам языка интерфейса
            usage = tr("translate_ui.left_month" if engine == "google" else "translate_ui.left_today", left=n(max(0, limit - used)), limit=n(limit))
        except Exception:   # noqa: BLE001
            usage = tr("translate_ui.left_unknown")
        act = menu.addAction(usage)
        act.setEnabled(False)
        if engine == "mymemory" and not self.tr_cfg.get("translate_email", "").strip():
            menu.addAction(tr("translate_ui.email_menu")).setData(("email", None))
        menu.addSeparator()
        menu.addAction(tr("translate_ui.copy_all_menu")).setData(("copyall", None))
        menu.addAction(tr("translate_ui.translate_more")).setData(("more", None))
        self.tr_more_menu = menu   # для проверки в тестах
        chosen = menu.exec(gpos)
        if chosen is not None and chosen.data():
            self._tr_more_action(*chosen.data())

    def _tr_more_action(self, kind, value=None):
        if kind == "engine":
            self._tr_set_engine(value)
        elif kind == "email":
            self._tr_open_email()
        elif kind == "copyall":
            self._tr_copy_all_windows()
        elif kind == "more":
            if callable(self.more_hook):
                self.more_hook()
            elif callable(FloatingTranslation.request_more):
                FloatingTranslation.request_more()

    @staticmethod
    def all_windows_text() -> str:
        """Переводы всех открытых окошек (готовые), один за другим."""
        texts = []
        for win in list(_floating):
            if sip.isdeleted(win) or getattr(win, "_done", False) or not win.tr_cards:
                continue
            c = win.tr_cards[0]
            if c.state == "done" and c.text():
                texts.append(c.text())
        return "\n\n".join(texts)

    def _tr_copy_all_windows(self):
        text = self.all_windows_text()
        if text:
            self._tr_copy(text, self.tr_cards[0].box().toAlignedRect() if self.tr_cards else None, tr("translate_ui.all_copied"))

    def _tr_sync_window(self):
        """Окошко ровно по карточке (плюс поля под тень); низ и край не уходят за экран."""
        if not self.tr_cards:
            return
        card = self.tr_cards[0]
        self._tr_layout(card)
        m = self.MARGIN
        overlay = self._tr_view(card) == "overlay"
        if self.isVisible():
            track_frame_extents(self, self.frame_extents_margins)   # вид или плашка сменились: поля могли измениться
        w, h = int(card.content.right()) + m, int(card.content.bottom()) + m
        if overlay:   # плашка с кнопками может быть шире области
            side = self.chip_side
            if side in ("above", "below"):
                w = max(w, int(card.content.left() + self.chip_dx + max(card.header_need, 200)) + m)
            elif side == "right":
                w = max(w, int(card.content.right() + 8 + self.chip_dx + max(card.header_need, 200)) + m)
                h = max(h, int(card.content.top() + self.CHIP_H) + m)
            elif side == "left":
                h = max(h, int(card.content.top() + self.CHIP_H) + m)
            h += self.CHIP_SPACE if side == "below" else 0
            if card.state == "error":
                # карточка сообщения об ошибке не меньше 220x56 и на маленьком куске выходит за него: окно (и маска,
                # _input_region) должны вмещать её целиком (П5 проверки 1.32.2: текст обрезался справа и снизу)
                note, _ = self._tr_notice_box(QRectF(card.region), self._tr_error_text(card))
                w = max(w, int(note.right()) + 4)
                h = max(h, int(note.bottom()) + 4)
        if (w, h) != (self.width(), self.height()):
            self.resize(w, h)
        self._update_mask()
        screen = self.screen()
        area = screen.availableGeometry() if screen is not None else QRect(0, 0, 1280, 800)
        if not self._user_moved:
            if overlay:   # текст перевода ровно на месте оригинала, плашка над ним (или под ним)
                self.move(self._anchor.x() - int(card.region.x()), self._anchor.y() - int(card.region.y()))
            else:
                # шапка над выделенным местом, если сверху есть место: текст перевода ложится на место оригинала
                up = self.HEAD_H if self._anchor.y() - self.HEAD_H >= area.top() else 0
                self.move(self._anchor.x() - m, self._anchor.y() - int(card.region.y()) - up)
            if self.place_hook is not None:
                spot = self.place_hook(self)
                if spot is not None:
                    self.move(spot)
        if overlay and not self._user_moved and self.place_hook is None:
            return   # на месте оригинала: за край экрана не двигаем (нижняя плашка и поля могут выступать)
        g = self.frameGeometry()
        x = min(max(g.left(), area.left()), max(area.left(), area.right() + 1 - g.width()))
        y = min(max(g.top(), area.top()), max(area.top(), area.bottom() + 1 - g.height()))
        if (x, y) != (g.left(), g.top()):
            self.move(x, y)

    def _input_region(self) -> QRegion:
        """Видимые части окошка «Поверх текста»: рамка перевода, плашка и мостик между ними (с тенью). Пустая область:
        окошко целиком (вид «Карточкой»)."""
        if not self.tr_cards:
            return QRegion()
        card = self.tr_cards[0]
        if self._tr_view(card) != "overlay":
            return QRegion()
        box = QRectF(card.content)
        region = QRegion(box.adjusted(-6, -6, 6, 6).toAlignedRect())
        if card.state == "error":   # карточка сообщения шире и выше маленького куска (П5 проверки 1.32.2)
            note, _ = self._tr_notice_box(QRectF(card.region), self._tr_error_text(card), self.width())
            region = region.united(QRegion(note.adjusted(-2, -2, 2, 4).toAlignedRect()))
        if (self.tr_chip or card.state == "error") and self.chip_side != "none":
            chip = self._tr_chip_rect(card)
            region = region.united(QRegion(chip.adjusted(-10, -6, 10, 14).toAlignedRect()))
            # мостик: полоса между областью и плашкой там, где они друг напротив друга (мышь идёт к плашке по окошку)
            x1, x2 = max(chip.left(), box.left()), min(chip.right(), box.right())
            y1, y2 = max(chip.top(), box.top()), min(chip.bottom(), box.bottom())
            if x2 > x1:
                top, bottom = (chip.bottom(), box.top()) if chip.bottom() <= box.top() else (box.bottom(), chip.top())
                if bottom > top:
                    region = region.united(QRegion(QRectF(x1, top, x2 - x1, bottom - top).toAlignedRect()))
            elif y2 > y1:
                left, right = (chip.right(), box.left()) if chip.right() <= box.left() else (box.right(), chip.left())
                if right > left:
                    region = region.united(QRegion(QRectF(left, y1, right - left, y2 - y1).toAlignedRect()))
        return region

    def _update_mask(self):
        """Linux (X11 и XWayland): мышь и колесо проходят сквозь прозрачные части окошка (поле между областью и
        сдвинутой плашкой, поля под тень) к странице под ним: окно ловит их только на рамке перевода, плашке и мостике
        между ними. В Windows прозрачные точки слоистого окна и так пропускают мышь."""
        if sys.platform == "win32":
            return
        region = self._input_region()
        if region.isEmpty():
            if not self.mask().isEmpty():
                self.clearMask()
        elif region != self.mask():
            self.setMask(region)

    def _tr_done(self, card, results, error, help=None):
        if sip.isdeleted(self) or self._done:
            return   # окошко закрыли, пока шёл перевод (выход из режима перевода, закрытие редактора)
        try:
            super()._tr_done(card, results, error, help)
            if not self.tr_cards:
                self.close()   # «Отмена» или «Текст не найден»: показывать нечего, окошко уходит
                return
            if self.mini and self.tr_cards and self.tr_cards[0].state == "error":
                self.enable_chip()   # у ошибки свои кнопки: плашка нужна и в окне выделения
            elif not self.mini:
                self._repick_chip()   # готовая плашка шире, чем ждали: сторона могла стать другой
            self._tr_sync_window()
            self.update()
        except RuntimeError:
            _report(self)
            self._tr_fail(card)

    def wheelEvent(self, event):
        if self.tr_cards and self.tr_cards[0].scroll_max > 0:
            c = self.tr_cards[0]
            c.scroll = max(0.0, min(c.scroll_max, c.scroll - event.angleDelta().y() / 2.0))
            self.update()

    PEEK_GRACE_MS = 450   # мышь ушла с зажатого окошка: плашка ещё столько держится (по пути к ней, на край тени)

    def enterEvent(self, event):
        """Зажатое соседями окошко: пока над ним мышь, плашка с кнопками видна у своей области (на время может лечь на
        соседа). Окошко на это время поднимается над соседями: мышь по пути к плашке остаётся на нём, кнопки доступны."""
        super().enterEvent(event)
        if self._peek_timer is not None:
            self._peek_timer.stop()   # вернулась до конца задержки: плашка остаётся
        if not self.crowded or self.mini or self._done or self._peek or not self.tr_cards \
                or self._tr_view(self.tr_cards[0]) != "overlay":
            return
        card = self.tr_cards[0]
        side, shift, free = self._pick_chip(self._area_global(card), card.header_need or 300)
        if free:   # место освободилось (соседа закрыли или окошко унесли): плашка снова постоянная
            self._apply_chip(side, shift, True)
            return
        self._peek, self.tr_chip = True, True
        self._set_chip_side(side, shift)
        self.raise_()
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if self._peek and not self._done:
            if self._peek_timer is None:
                self._peek_timer = QTimer(self)
                self._peek_timer.setSingleShot(True)
                self._peek_timer.timeout.connect(self._end_peek)
            self._peek_timer.start(self.PEEK_GRACE_MS)

    def _end_peek(self):
        """Конец показа плашки зажатого окошка: мышь так и не вернулась на окошко."""
        if not self._peek or self._done or sip.isdeleted(self):
            return
        if self.geometry().contains(QCursor.pos()) and self.underMouse():
            return
        self._peek = False
        if self.crowded:
            self.tr_chip = False
            self._set_chip_side("none", 0.0)
            self.update()

    def closeEvent(self, event):
        self._done = True
        for card in self.tr_cards:
            self._tr_cancel_card(card)   # окно закрыто (Esc): ожидание перевода и окно вопроса про лимит снимаются
        super().closeEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        elif event.key() == Qt.Key.Key_C and event.modifiers() & Qt.KeyboardModifier.ControlModifier and self.tr_cards:
            self._tr_copy(self.tr_cards[0].text(), self.tr_cards[0].box().toAlignedRect())

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position()
        if callable(self.select_hook):
            self.select_hook(self)   # окно выделения: кнопки его панели теперь относятся к этому окошку
        if self._tr_click(pos):
            if not self.tr_cards:
                self.close()   # крестик
            return
        if self.tr_cards and self.tr_cards[0].full and not self.tr_cards[0].handle.contains(pos) \
                and not self.tr_cards[0].chip.contains(pos):
            return   # окно на весь монитор: перетаскивается только за шапку-плашку, не за произвольное место
        # тащить окошко целиком: системное перемещение, а где его нет, вручную
        self._user_moved = True   # дальше окошко не возвращается на место само
        handle = self.windowHandle()
        if handle is not None and handle.startSystemMove():
            return
        self._drag_from = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self._drag_from is not None:
            self.move(event.globalPosition().toPoint() - self._drag_from)
            return
        self._tr_move(event)

    def mouseReleaseEvent(self, event):
        if self._drag_from is not None:
            self._drag_from = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)

    def paintEvent(self, _event):
        p = QPainter(self)
        self._tr_paint(p)


_runs = []   # идущие переводы всего экрана (пока нет готового окна)


def full_state(grect: QRect, owner=None):
    """«busy»: перевод этого прямоугольника уже идёт; «done»: готовое окошко на нём уже есть; иначе None."""
    for run in _runs:
        if run.owner is owner and run.grect == grect:
            return "busy"
    for win in list(_floating):
        if sip.isdeleted(win):
            continue
        if win.isVisible() and getattr(win, "_full_rect", None) == grect and win.tr_cards and win.tr_cards[0].full \
                and win.tr_cards[0].state in ("busy", "wait", "done"):
            return "done"
    return None


class WaitBox(QWidget):
    """Маленькое окошко ожидания посреди монитора: кружок, подпись, «Esc: отменить», крестик. Никакой вуали и перехвата
    остального экрана: монитор остаётся живым, пока идёт распознавание и перевод."""
    W, H = 300, 170

    def __init__(self, text: str, on_cancel):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setObjectName("clipsdWaitBox")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setMouseTracking(True)
        self.setFixedSize(self.W, self.H)
        self.text, self.on_cancel, self.phase = text, on_cancel, 0
        self.cross = QRect(self.W - 40, 12, 28, 28)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

    def show_at(self, global_center: QPoint):
        self.move(global_center.x() - self.W // 2, global_center.y() - self.H // 2)
        self.show()
        self.raise_()
        self.activateWindow()   # Esc должен доходить сюда
        self.timer.start(80)

    def _tick(self):
        self.phase += 1
        self.update()

    def paintEvent(self, _event):
        from .busy import draw_spinner
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        for i, alpha in ((6, 18), (3, 28)):
            p.setBrush(QColor(8, 60, 55, alpha))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(4 - i, 4 - i + 2, -4 + i, -4 + i + 2), 16 + i, 16 + i)
        p.setPen(QPen(TEAL, 1.5))
        p.setBrush(QColor(255, 255, 255, 245))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(5, 5, -5, -5), 14, 14)
        draw_spinner(p, QPointF(self.W / 2, 64), 24, self.phase, TEAL)
        f = QFont()
        f.setPixelSize(16)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#1d2330"))
        p.drawText(QRectF(10, 98, self.W - 20, 26), Qt.AlignmentFlag.AlignCenter, self.text)
        f2 = QFont()
        f2.setPixelSize(13)
        p.setFont(f2)
        p.setPen(QColor("#5a6270"))
        p.drawText(QRectF(10, 126, self.W - 20, 22), Qt.AlignmentFlag.AlignCenter, tr("translate_ui.esc_cancel"))
        c = QRectF(self.cross)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 20))
        p.drawEllipse(c)
        p.setPen(QPen(QColor("#5a6270"), 1.8))
        m = c.center()
        p.drawLine(QPointF(m.x() - 5, m.y() - 5), QPointF(m.x() + 5, m.y() + 5))
        p.drawLine(QPointF(m.x() + 5, m.y() - 5), QPointF(m.x() - 5, m.y() + 5))
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.cross.contains(event.position().toPoint()):
            self.on_cancel()

    def mouseMoveEvent(self, event):
        self.setCursor(Qt.CursorShape.PointingHandCursor if self.cross.contains(event.position().toPoint())
                       else Qt.CursorShape.ArrowCursor)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.on_cancel()

    def closeEvent(self, event):
        self.timer.stop()
        super().closeEvent(event)


class FullRun:
    """Перевод всего экрана (снимка) в виде отдельного окошка. Распознавание и сеть идут за маленьким окошком ожидания
    (WaitBox); окно на весь монитор появляется только с готовым результатом (или маленькое с ошибкой).
    make(local) создаёт FloatingTranslation для прямоугольника local (в координатах области), не запуская его."""

    def __init__(self, crop, cfg, grect: QRect, size, make, say, noun="screen", wait=None,
                 owner=None, on_state=None, center: QPoint = None):
        from . import translate
        wait = wait or tr("translate_ui.full_wait_screen")
        self.grect, self.size, self.make, self.say, self.owner = QRect(grect), size, make, say, owner
        self.on_state, self.cancelled, self.partial, self.popup, self.noun = on_state, False, False, None, noun
        _runs.append(self)
        self.center = center if center is not None else grect.center()
        self.closed = False
        self.box = WaitBox(wait, self.cancel)
        # окошко показывается и активируется после закрытия окна выделения (оно держит клавиатуру до тех пор)
        QTimer.singleShot(0, self._show_box)
        self.job = translate.start(crop, cfg, self._done, confirm=self._confirm, full=True)
        self._state()

    def _show_box(self):
        if self.closed or sip.isdeleted(self.box):
            return   # отменили или закончили раньше: окошко-сирота не появляется
        self.box.show_at(self.center)

    def _state(self):
        if callable(self.on_state):
            try:
                self.on_state()
            except RuntimeError:
                _report(getattr(self.on_state, "__self__", None))

    def _confirm(self, need, left, job):
        from . import hints, translate
        if self.cancelled:
            job.cancel()
            return
        n = number   # числа по правилам языка интерфейса

        def answered(partial):
            self.popup = None
            self.partial = self.partial or partial
            job.answer(partial)
        self.popup = hints.ChoicePopup(self.box, tr(_ASK.get(self.noun, _ASK["screen"]), n=need, need=n(need), left=n(left)),
                                       tr("translate_ui.translate_partial"), tr("settings.cancel"), answered,
                                       tr("translate_ui.no_second_engine"))
        self.popup.show_at(QPoint(self.center.x(), self.center.y() - self.box.H // 2 - 20 - self.popup.height() // 2))

    def _close_ui(self):
        self.closed = True
        if self in _runs:
            _runs.remove(self)
        for w in (self.popup, self.box):
            if w is None or sip.isdeleted(w):
                continue
            w.dismiss() if hasattr(w, "dismiss") else w.close()
        self.popup = None

    def cancel(self):
        """Esc, крестик или закрытие редактора: ожидание снимается, в сеть больше ничего не уходит."""
        if self.cancelled:
            return
        self.cancelled = True
        self._close_ui()
        self.job.cancel()
        self._state()

    def _done(self, results, error, help):
        try:
            self._done_inner(results, error, help)
        except RuntimeError:
            _report(self.owner)   # неожиданная ошибка: в журнал; окошко ожидания в любом случае закрыто
            self._close_ui()
            self._state()   # редактор узнаёт, что перевод закончился (иначе строка внизу вечно «Перевожу…»)

    def _done_inner(self, results, error, help):
        from . import translate
        self._close_ui()
        if self.cancelled or error == translate.CANCELLED:
            self._state()
            return
        if error == translate.NO_TEXT:
            self.say(tr(_NOT_FOUND.get(self.noun, _NOT_FOUND["screen"])))
            self._state()
            return
        if translate.is_already(error):
            self.say(error.rstrip("."))
            self._state()
            return
        full = QRect(0, 0, self.size.width(), self.size.height())
        if error:   # ошибка: маленькое окошко посреди области, не на весь монитор
            w, h = min(560, full.width()), min(240, full.height())
            local = QRect((full.width() - w) // 2, (full.height() - h) // 2, w, h)
        else:
            local = full
        try:
            win = self.make(local)
        except RuntimeError:   # область (редактор) удалена: тихо, иначе в журнал
            _report(self.owner)
            return
        card = win.tr_cards[0]
        card.full, card.partial = True, self.partial
        win.start(run=False)
        win._tr_done(card, results, error, help)
        self._state()


def hide_floating():
    """Перед новым снимком окошки прячутся, чтобы не попасть на снимок и не закрыть текст."""
    hidden = [w for w in _floating if w.isVisible()]
    for w in hidden:
        w.hide()
    return hidden


def show_floating(windows):
    for w in windows:
        try:
            w.show()
            w.raise_()
        except RuntimeError:
            pass
