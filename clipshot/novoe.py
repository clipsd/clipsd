# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Новинки после обновления (1.34, слова владельца 21.11.2026): «кто скачивает не первый раз, основные функции он уже
знает, а новые можно подсвечивать. И задавать вопрос: хотите ещё узнать о других функциях?»

Как устроено:
- Первая установка: как раньше (выбор оформления, знакомство). Новинки не показываются, меток нет.
- Обновление с прежней версии (config novoe_version меньше установленной; у настроек 1.33 и старше этого поля нет,
  там признак прежней работы: tour_done, tour_selector_done или theme_chosen): при первом открытии редактора одно окно
  «Новое в версии X» (2-4 пункта) с кнопками «Отложить ▾» и «Показать новое». «Показать новое» проводит коротким курсом по
  новым кнопкам и потом спрашивает «Хотите узнать о других функциях программы?» («Да, показать обзор» запускает всё
  знакомство, «Не сейчас» до следующей версии не спрашивает). 1.35: «Показать новое» открывает окно «Ознакомление»
  (oznakomlenie.py) на группе новинок; короткого курса поверх рабочего окна больше нет; вопрос про другие функции
  приходит после этого окна, если смотрели одни новинки, и ведёт в то же окно. Если обновление поставила сама программа, то же окно
  приходит вместо окна «ClipSD обновлён» в спокойную минуту (updater.py, Clipshot.show_novoe_after_update).
- Метка «Новое» на новых кнопках (или точка, если кнопка маленькая): до первого нажатия или до трёх показов окна, где
  кнопка видна, потом исчезает навсегда.
- Настройка novoe_enabled («Показывать новинки после обновления», раздел «Обновления»): выключено, нет ни окна, ни меток.
  В меню значка у часов пункт «Что нового» открывает окно в любой момент.

Новинки задаются строками таблицы ITEMS ниже: (версия, id, где, значок). Тексты: ключи novoe.<id>_title и
novoe.<id>_text в clipshot/i18n/<язык>/novoe.json (12 языков). Где:
  "selector:<ключ>"     плитка или кнопка панели окна выделения (ключ из RegionSelector.BAR_BUTTONS; "window": чип
                        «Открытые окна ▾»);
  "editor:<имя>"        виджет редактора self.<имя> (QWidget);
  "editor:tool:<код>"   кнопка инструмента редактора (tool_buttons; инструмент в свёрнутой группе: кнопка группы);
  "editor:a|b"          первая из целей, которая сейчас не спрятана (узкое окно прячет большие кнопки).
Элемента нет в этой сборке (ветка не сведена): метки нет, в окне пункт остаётся, если версия совпадает.
Состояние в config: novoe_version, novoe_from (с какой версии обновились; None: меток нет), novoe_window (для какой
версии окно уже было), novoe_later, novoe_asked, novoe_shows {id: сколько раз показана метка}, novoe_used [id]."""

from PyQt6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from . import __version__, otlozhit
from .i18n import tr

# (версия, id, где, значок). Порядок внутри версии = порядок в окне «Новое в версии» (показываются первые MAX_WINDOW).
# 1.34: в окне четыре главных: «С телефона» (плитка панели и кнопка редактора одним пунктом, с просмотром фото на
# телефоне), «Форма снимка», «Открытые окна ▾» с именами программ, «Другая область» и «Сохранить» без закрытия окна.
# Кнопка «С телефона» в редакторе, перевод одной строкой и номера по цветам (из 1.33.0, которая публично не выходила)
# идут дальше: в окно не попадают, но отмечены меткой «Новое» и есть в коротком курсе.
ITEMS = (
    ("1.34.0", "phone_tile", "selector:phone", "phone"),
    ("1.34.0", "forma", "editor:form_button|more_button", "form_round2"),   # узкое окно: формы в «Все инструменты»
    ("1.34.0", "windows", "selector:window", "window"),
    ("1.34.0", "other_area", "selector:manual", "region"),
    ("1.34.0", "phone_editor", "editor:phone_button", "phone"),
    ("1.34.0", "translate_head", "editor:tr_block|tool:translate", "translate"),
    ("1.34.0", "numbers", "editor:tool:number", "number"),
    # 1.35.0. Цели «app:…» живут не на кнопках редактора (меню значка, окна обновления, настройки, окно «С телефона»):
    # метки у них нет, пункт есть в окне «Новое в версии» и в «Ознакомлении». Последние три придут из других веток
    # (otlozhit, settings_apply, phone_target): цели в этой сборке ещё нет, пункт от этого ничего не ломает.
    ("1.35.0", "oznakomlenie", "app:tray_ozn", "info"),
    ("1.35.0", "color_swatch", "app:pen_hint", "marker"),
    ("1.35.0", "qr_big", "app:phone_qr", "phone"),
    ("1.35.0", "ocr_install", "app:ocr_install", "ocr"),
    ("1.35.0", "otlozhit", "app:otlozhit", "update"),
    ("1.35.0", "settings_apply", "app:settings_apply", "settings"),
    ("1.35.0", "phone_target", "editor:phone_target", "phone"),
)

MAX_WINDOW = 4        # пунктов в окне «Новое в версии»
MAX_SHOWS = 3         # метка видна в трёх окнах, потом исчезает
# «Отложить ▾» (otlozhit.py, 1.35): время в config["otlozhit"]["novoe"]; после трёх откладываний подряд окно приходит
# не раньше чем через неделю, а «Что нового» в меню значка открывает его всегда
USE_MARKERS = ("tour_done", "tour_selector_done", "theme_chosen")   # программой уже пользовались (настройки 1.33-)

# Цвет значка в окне (светлая, тёмная карточка): на мягком квадрате не ниже 3:1
ICON_COLORS = {"window": ("#2a6df4", "#7fb2ff"), "translate": ("#0b766c", "#4fd1c5"), "number": ("#c81e1e", "#ff8a80"),
               "phone": ("#b4236e", "#f48fc1"), "region": ("#0b4fb3", "#7fb2ff"), "form_round2": ("#6d3fd0", "#b9a4ff"),
               "info": ("#0b4fb3", "#7fb2ff"), "marker": ("#9a5200", "#f5b45c"), "ocr": ("#6d3fd0", "#b9a4ff"),
               "update": ("#0b766c", "#4fd1c5"), "settings": ("#4b5563", "#aab1ba")}
BADGE_BG = "#1660d0"      # белый текст 5,8:1 (цвет ссылки); метка значит «новое», не ошибку и не главное действие
BADGE_GRAY = (("#666c75", "#ffffff"), ("#474d55", "#e3e6ea"))   # изучено (1.35): фон и текст метки, светлая и тёмная тема, контраст текста не ниже 4,5:1
BADGE_RING = ("#ffffff", "#232323")   # тонкое кольцо цвета панели: метка отделена от кнопки в обеих темах
BADGE_FONT_PX = 10
DOT = 9


def _key(v: str):
    out = []
    for part in str(v or "").split("."):
        num = "".join(ch for ch in part if ch.isdigit())
        out.append(int(num) if num else 0)
    return tuple(out)


def _save(owner):
    save = getattr(owner, "save_config", None) or getattr(owner, "tr_save", None)
    if callable(save):
        try:
            save()
        except Exception as exc:   # запись настроек не должна ронять окно
            print(f"novoe: настройки не записаны: {exc}")


# --- состояние ----------------------------------------------------------------------------------------

def enabled(cfg) -> bool:
    return isinstance(cfg, dict) and bool(cfg.get("novoe_enabled", True))


def on_start(cfg: dict, version: str = None) -> bool:
    """Запуск программы: первая установка, та же версия или обновление. True: настройки изменились (записать)."""
    version = version or __version__
    if not isinstance(cfg, dict):
        return False
    last = cfg.get("novoe_version")
    if not last:
        cfg["novoe_version"] = version
        if any(cfg.get(k) for k in USE_MARKERS):   # настройки 1.33 и старше: программой уже пользовались
            _upgraded(cfg, "")
        else:
            cfg["novoe_from"] = None               # первая установка: знакомство как раньше, новинок нет
            cfg["novoe_window"] = version
            cfg["novoe_asked"] = version
        return True
    if _key(last) == _key(version):
        return False
    cfg["novoe_version"] = version
    if _key(last) < _key(version):
        _upgraded(cfg, str(last))
    else:                                          # вернулись на прежнюю версию: ничего не показываем
        cfg["novoe_from"] = None
        cfg["novoe_window"] = version
    return True


def _upgraded(cfg, previous: str):
    cfg["novoe_from"] = previous   # "" : с версии без этой записи (1.33 и старше)
    cfg.pop("novoe_window", None)
    cfg.pop("novoe_later", None)
    for topic in ("novoe", "ask", "ozn"):
        otlozhit.clear(cfg, topic)   # откладывания прежней версии забываются
    cfg.pop("novoe_asked", None)


def items_since(cfg, version: str = None) -> list:
    """Новинки, вышедшие после версии, с которой обновились, до установленной: [(версия, id, где, значок)],
    новые версии выше, внутри версии порядок таблицы."""
    version = version or __version__
    start = cfg.get("novoe_from") if isinstance(cfg, dict) else None
    if start is None:
        return []
    out = [it for it in ITEMS if _key(start) < _key(it[0]) <= _key(version)]
    order = {it: i for i, it in enumerate(ITEMS)}
    return sorted(out, key=lambda it: (tuple(-x for x in _key(it[0])), order[it]))


def items_of(version: str = None) -> list:
    """Новинки самой этой версии (пункт меню «Что нового», первая установка)."""
    version = version or __version__
    return [it for it in ITEMS if _key(it[0]) == _key(version)]


def window_items(cfg, version: str = None) -> list:
    return (items_since(cfg, version) or items_of(version))[:MAX_WINDOW]


def window_pending(cfg, version: str = None) -> bool:
    version = version or __version__
    return (enabled(cfg) and cfg.get("novoe_from") is not None and cfg.get("novoe_window") != version
            and bool(items_since(cfg, version)) and not otlozhit.is_snoozed(cfg, "novoe"))


def window_done(cfg, version: str = None):
    cfg["novoe_window"] = version or __version__
    otlozhit.clear(cfg, "novoe")


def ask_pending(cfg, version: str = None) -> bool:
    return (isinstance(cfg, dict) and cfg.get("novoe_asked") != (version or __version__)
            and not otlozhit.is_snoozed(cfg, "ask"))


def ask_done(cfg, version: str = None):
    cfg["novoe_asked"] = version or __version__
    otlozhit.clear(cfg, "ask")


def badges(cfg, scope: str, version: str = None) -> dict:
    """Метки, которые ещё видны: {цель без "scope:": id} для scope "selector" или "editor"."""
    if not enabled(cfg):
        return {}
    used = set(cfg.get("novoe_used") or [])
    shows = cfg.get("novoe_shows") if isinstance(cfg.get("novoe_shows"), dict) else {}
    out = {}
    for _v, ident, where, _icon in items_since(cfg, version):
        kind, _, target = where.partition(":")
        if kind == scope and ident not in used and int(shows.get(ident, 0)) < MAX_SHOWS:
            out[target] = ident
    return out


def note_shown(cfg, ident: str):
    shows = dict(cfg.get("novoe_shows") or {}) if isinstance(cfg.get("novoe_shows"), dict) else {}
    shows[ident] = int(shows.get(ident, 0)) + 1
    cfg["novoe_shows"] = shows


def mark_used(cfg, ident: str) -> bool:
    used = list(cfg.get("novoe_used") or [])
    if ident in used:
        return False
    used.append(ident)
    cfg["novoe_used"] = used
    return True


def title(ident: str) -> str:
    return tr(f"novoe.{ident}_title")


def text(ident: str) -> str:
    return tr(f"novoe.{ident}_text")


# --- метка «Новое» ------------------------------------------------------------------------------------

def badge_size(fm: QFontMetrics) -> QSize:
    return QSize(fm.horizontalAdvance(tr("novoe.badge")) + 12, fm.height() + 2)


def badge_font() -> QFont:
    f = QFont()
    f.setPixelSize(BADGE_FONT_PX)
    f.setBold(True)
    return f


def badge_rect(target: QRect, fm: QFontMetrics, room: QRect = None):
    """Где рисовать метку для кнопки target: («pill», прямоугольник) над правым верхним углом, а у маленькой кнопки
    («dot», круг 9 px) в её углу. room: куда метка должна поместиться (родитель)."""
    size = badge_size(fm)
    if target.width() >= size.width() + 14:
        r = QRect(QPoint(target.right() - size.width() + 6, target.top() - size.height() // 2 - 1), size)
        kind = "pill"
    else:
        r = QRect(target.right() - DOT - 1, target.top() + 1, DOT, DOT)
        kind = "dot"
    if room is not None:
        r.moveLeft(max(room.left(), min(r.left(), room.right() - r.width())))
        r.moveTop(max(room.top(), min(r.top(), room.bottom() - r.height())))
    return kind, r


def paint_badge(p: QPainter, kind: str, rect: QRect, dark: bool = False, studied: bool = False):
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(QPen(QColor(BADGE_RING[1 if dark else 0]), 1.5))
    bg, fg = BADGE_GRAY[1 if dark else 0] if studied else (BADGE_BG, "#ffffff")
    p.setBrush(QColor(bg))
    if kind == "dot":
        p.drawEllipse(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5))
    else:
        r = QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        p.setFont(badge_font())
        p.setPen(QColor(fg))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, tr("novoe.badge"))
    p.restore()


class Badge(QWidget):
    """Метка над кнопкой редактора. Живёт у родителя кнопки и ходит за ней (перемещение, размер, показ); мышь проходит
    насквозь. Нажатие на кнопку: метка исчезает навсегда (novoe_used)."""

    def __init__(self, target: QWidget, ident: str, owner):
        super().__init__(target.parentWidget())
        self.target, self.ident, self.owner = target, ident, owner
        self.kind = "pill"
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setObjectName("novoeBadge")
        self._desc = target.accessibleDescription()
        target.setAccessibleDescription(((self._desc + ". ") if self._desc else "") + tr("novoe.badge_tip"))
        target.installEventFilter(self)
        target.destroyed.connect(self._target_gone)
        self.place()

    def _target_gone(self, *_a):
        self.target = None
        try:
            self.hide()
            self.deleteLater()
        except RuntimeError:   # родитель удаляется вместе с кнопкой
            pass

    def place(self):
        t = self.target
        if t is None:
            return
        parent = self.parentWidget()
        if parent is None or t.parentWidget() is not parent:
            self.hide()
            return
        fm = QFontMetrics(badge_font())
        kind, r = badge_rect(t.geometry(), fm, parent.rect())
        self.kind = kind
        self.setGeometry(r)
        visible = t.isVisible() and not t.isHidden()
        self.setVisible(visible)
        if visible:
            self.raise_()
            self.owner.badge_seen(self.ident)
        self.update()

    def remove(self):
        t = self.target
        if t is not None:
            try:
                t.removeEventFilter(self)
                t.setAccessibleDescription(self._desc)
            except RuntimeError:
                pass
        self.target = None
        self.hide()
        self.deleteLater()

    def eventFilter(self, obj, event):
        if obj is self.target:
            et = event.type()
            if et in (QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.Hide, QEvent.Type.ParentChange):
                self.place()
                if et in (QEvent.Type.Show, QEvent.Type.Hide):
                    self.owner.attach_soon()   # группа свернулась или развернулась: метка переходит на видимую кнопку
            elif et == QEvent.Type.MouseButtonPress:
                self.owner.used(self.ident)
        return False

    def paintEvent(self, _e):
        from . import themes
        p = QPainter(self)
        paint_badge(p, self.kind, self.rect(), themes.is_dark())
        p.end()


def editor_widget(ed, where: str):
    """Виджет редактора по цели из ITEMS ("tool:<код>", имя поля окна, варианты через «|»); нет такого: None."""
    if "|" in where:
        found = [editor_widget(ed, part) for part in where.split("|")]
        found = [w for w in found if w is not None]
        return next((w for w in found if not w.isHidden()), found[0] if found else None)
    if where.startswith("tool:"):
        tool = where[5:]
        button = (getattr(ed, "tool_buttons", None) or {}).get(tool)
        if button is not None and button.isHidden():   # инструмент в свёрнутой группе: метка на кнопке группы
            from .editor import TOOL_GROUP
            group = (getattr(ed, "group_buttons", None) or {}).get(TOOL_GROUP.get(tool))
            if group is not None and not group.isHidden():
                return group
        return button
    w = getattr(ed, where, None)
    return w if isinstance(w, QWidget) else None


class EditorBadges(QObject):
    """Метки одного окна редактора. Показ метки считается один раз на окно (MAX_SHOWS окон)."""

    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.badges = {}        # id -> Badge
        self.counted = set()
        from PyQt6.QtCore import QTimer
        self._again = QTimer(self)   # таймер принадлежит окну: закрытый редактор его удаляет вместе с собой
        self._again.setSingleShot(True)
        self._again.setInterval(0)
        self._again.timeout.connect(self.attach)
        editor.installEventFilter(self)   # окно сузилось или расширилось: метка переходит на видимую кнопку

    def eventFilter(self, obj, event):
        if obj is self.editor and event.type() == QEvent.Type.Resize:
            self.attach_soon()
        return False

    def attach_soon(self):
        self._again.start()

    @property
    def cfg(self):
        ctx = getattr(self.editor, "ctx", None)
        cfg = getattr(ctx, "config", None)
        return cfg if isinstance(cfg, dict) else None

    def attach(self):
        cfg = self.cfg
        wanted = badges(cfg, "editor") if cfg is not None else {}
        for ident in [i for i in self.badges if i not in wanted.values()]:
            self.badges.pop(ident).remove()
        for where, ident in wanted.items():
            target = editor_widget(self.editor, where)
            old = self.badges.get(ident)
            if old is not None and old.target is target and target is not None:
                old.place()
                continue
            if old is not None:
                self.badges.pop(ident).remove()
            if target is None or target.parentWidget() is None:
                continue
            self.badges[ident] = Badge(target, ident, self)

    def badge_seen(self, ident):
        cfg = self.cfg
        if cfg is None or ident in self.counted:
            return
        self.counted.add(ident)
        note_shown(cfg, ident)
        _save(getattr(self.editor, "ctx", None))

    def used(self, ident):
        cfg = self.cfg
        if cfg is None:
            return
        if mark_used(cfg, ident):
            _save(getattr(self.editor, "ctx", None))
        badge = self.badges.pop(ident, None)
        if badge is not None:
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, badge.remove)   # нажатие доходит до кнопки, метка уходит сразу после


def attach_editor(editor):
    """Окно редактора показано или перестроено (смена языка): метки на новых кнопках."""
    try:
        manager = getattr(editor, "_novoe", None)
        if manager is None:
            manager = EditorBadges(editor)
            editor._novoe = manager
        manager.attach()
    except RuntimeError:
        pass


# --- окно «Новое в версии» и вопрос про обзор -------------------------------------------------------

def _icon_pixmap(name: str, dark: bool, size: int = 36):
    from PyQt6.QtGui import QPixmap
    from . import icons
    pix = QPixmap(size * 3, size * 3)
    pix.setDevicePixelRatio(3)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#2f3338" if dark else "#eceff3"))
    p.drawRoundedRect(QRectF(0, 0, size, size), 9, 9)
    color = ICON_COLORS.get(name, ("#1660d0", "#58a4f2"))[1 if dark else 0]
    icons.icon(name, color).paint(p, QRect((size - 22) // 2, (size - 22) // 2, 22, 22))
    p.end()
    return pix


def _item_row(ident: str, icon_name: str, dark: bool) -> QWidget:
    from .dialogs import PALETTES
    row = QWidget()
    row.setObjectName("novoeItem")
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 2, 0, 2)
    lay.setSpacing(12)
    pic = QLabel()
    pic.setPixmap(_icon_pixmap(icon_name, dark))
    pic.setFixedSize(36, 36)
    lay.addWidget(pic, 0, Qt.AlignmentFlag.AlignTop)
    col = QVBoxLayout()
    col.setSpacing(1)
    head = QLabel(title(ident))
    head.setObjectName("novoeItemTitle")
    head.setWordWrap(True)
    head.setTextFormat(Qt.TextFormat.PlainText)
    head.setStyleSheet("font-weight: bold; font-size: 14px;")
    sub = QLabel(text(ident))
    sub.setObjectName("novoeItemText")
    sub.setWordWrap(True)
    sub.setTextFormat(Qt.TextFormat.PlainText)
    sub.setStyleSheet(f"color: {PALETTES[bool(dark)]['muted']}; font-size: 13px;")
    col.addWidget(head)
    col.addWidget(sub)
    lay.addLayout(col, 1)
    return row


def make_window(version: str, items: list, parent=None, updated: bool = False, notes: bool = True, dark=None):
    """Окно «Новое в версии X»: значок программы, 2-4 пункта со значками, ссылка «Показать все изменения» (если есть
    заметки), «Отложить ▾» (otlozhit.SnoozeButton), зелёная «Показать новое». После закрытия choice: show, snooze
    (box.delay: код времени), notes, close."""
    from .dialogs import ClipDialog

    class NovoeDialog(ClipDialog):
        def __init__(self):
            sub = tr("updater.whatsnew.installed", version=version) if updated else tr("novoe.subtitle")
            super().__init__(parent, tr("novoe.title", version=version), sub, "info", 500, dark=dark, logo=True)
            self.setProperty("clipsd_closable", True)   # работы не держит: выход для обновления его просто закрывает
            self.setModal(True)
            self.choice = "close"
            self.delay = None
            self.rows = [_item_row(ident, icon_name, self.dark) for _v, ident, _w, icon_name in items]
            for r in self.rows:
                self.body.addWidget(r)
            self.notes_link = self.link(tr("updater.offer.show_notes")) if notes else None
            self.later_button = otlozhit.SnoozeButton(self.dark)
            self.footer_right.addWidget(self.later_button)
            self.show_button = self.primary(tr("novoe.show"))
            if self.notes_link is not None:
                self.notes_link.clicked.connect(lambda: self._pick("notes"))
            self.later_button.chosen.connect(lambda key: self._pick("snooze", key))
            self.show_button.clicked.connect(lambda: self._pick("show"))
            self.show_button.setFocus()
            # М6 проверки 1.34.0: язык сменили, пока окно открыто (меню значка у часов). Тексты задаются при
            # создании, поэтому окно закрывается с choice "relang", и Clipshot.show_novoe открывает его заново.
            from . import i18n
            self._off_lang = i18n.on_change(lambda _lang: QTimer.singleShot(0, lambda: self._pick("relang")))
            self.finished.connect(lambda _r: self._off_lang())

        def _pick(self, choice, delay=None):
            if self.isVisible() or choice != "relang":
                self.choice = choice
                self.delay = delay
                self.accept()

        def showEvent(self, event):
            super().showEvent(event)
            if self.parentWidget() is not None:   # над окном редактора, из которого открыто
                frame = self.frameGeometry()
                frame.moveCenter(self.parentWidget().frameGeometry().center())
                self.move(frame.topLeft())

    return NovoeDialog()


def make_question(parent=None, dark=None):
    """«Хотите узнать о других функциях программы?»: «Отложить ▾», «Не сейчас» и зелёная «Да, показать обзор».
    После закрытия choice: primary, secondary, snooze (box.delay), close."""
    from .dialogs import MessageCard
    box = MessageCard(parent, tr("novoe.ask_title"), tr("novoe.ask_text"), "info", primary=tr("novoe.ask_yes"),
                      secondary=tr("novoe.ask_no"), logo=True, dark=dark, snooze=True)
    box.setProperty("clipsd_closable", True)
    return box
