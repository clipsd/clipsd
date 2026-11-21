# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""«Снимок окна» (решение владельца 21.11.2026): чип «Окна ▾» и клавиша W в окне выделения, рамка ровно на окно,
закрытое другими окно снимается целиком, следующий снимок с того же места.

Проверяется без настоящего GNOME и Windows, подменой источников:
- список GNOME (ответ дополнения ListWindows), EWMH (поддельный Xlib), Windows (записи EnumWindows);
- пересчёт координат по монитору и запасной, когда мониторов у Shell и Qt разное число (монитор сняли);
- окно выделения: рамка на окно, клавиша W и меню с клавиатуры, Esc закрывает только меню;
- закрытое окно: содержимое приходит позже (GrabWindow) и вписывается в снимок; Enter до прихода ждёт его;
- свёрнутое окно: пометка в списке; нет содержимого: рамка не ставится, подсказка;
- гонки: окно закрылось между списком и выбором, дополнение ответило поздно, Esc во время запроса списка,
  поздний ответ на прежний выбор;
- дополнение GNOME старое или не стоит: строка-пояснение и «Обновить»/«Установить», неполный список XWayland;
  обновление дополнения в папке пользователя (подмена gsettings) и окно «выйдите и войдите»;
- настоящий Clipshot: last_region после снимка окна, названия окон не пишутся в настройки.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/vybor_okna_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import json
import os
import sys
import tempfile
import time
from pathlib import Path

here = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(here)
sys.path.insert(0, ROOT)
_cfg = os.path.join(tempfile.mkdtemp(prefix="clipsd-okno-"), "screen.json")
with open(_cfg, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1600, "height": 1000,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _cfg
os.environ.setdefault("CLIPSD_LANG", "ru")
# Никакой настоящей шины сеанса и никакого окружения сеанса человека. Убрать DBUS_SESSION_BUS_ADDRESS мало: тогда
# QtDBus (libdbus) находит шину сам по $XDG_RUNTIME_DIR/bus и в сеансе человека подключается к его настоящей шине,
# где есть GNOME Shell (так 21.11.2026 тест падал в окружении сеанса на ps-sd). Поэтому свои HOME, XDG_* и
# XDG_RUNTIME_DIR, адрес шины, которой нет, и без признаков GNOME, Wayland и экрана.
_iso = tempfile.mkdtemp(prefix="clipsd-okno-env-")
for _key, _sub in (("HOME", "home"), ("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"),
                   ("XDG_CACHE_HOME", "cache"), ("XDG_STATE_HOME", "state"), ("XDG_RUNTIME_DIR", "run")):
    os.makedirs(os.path.join(_iso, _sub), exist_ok=True)
    os.environ[_key] = os.path.join(_iso, _sub)
os.chmod(os.environ["XDG_RUNTIME_DIR"], 0o700)
os.environ["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=" + os.path.join(_iso, "run", "no-bus")
for _key in ("XDG_CURRENT_DESKTOP", "XDG_SESSION_TYPE", "WAYLAND_DISPLAY", "DISPLAY"):
    os.environ.pop(_key, None)

from PyQt6.QtCore import QObject, QPoint, QRect, Qt, QTimer, pyqtSignal  # noqa: E402
from PyQt6.QtGui import QColor, QPainter, QPixmap  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
from clipshot import app as appmod, gnome_ext, hints, windows  # noqa: E402
from clipshot.i18n import tr  # noqa: E402
from clipshot.selector import RegionSelector  # noqa: E402
from clipshot.windows import WindowList, WinInfo  # noqa: E402

failures = []
checks = [0]


def check(cond, msg):
    checks[0] += 1
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def test_isolated_from_session():
    """Тест не видит шину сеанса человека и его GNOME Shell (иначе проверки зависят от того, где его запустили)."""
    from PyQt6.QtDBus import QDBusConnection
    check(not QDBusConnection.sessionBus().isConnected() and windows.shell_owner() == "",
          "шины сеанса нет: тест не зависит от настоящего GNOME Shell")


def settle(n=4):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(15)


def wait(cond, seconds=3):
    end = time.time() + seconds
    while not cond() and time.time() < end:
        app.processEvents()
        QTest.qWait(15)
    return cond()


class FakeScreen:
    def __init__(self, x, y, w, h, dpr=1.0):
        self._g, self._d = QRect(x, y, w, h), dpr

    def geometry(self):
        return QRect(self._g)

    def devicePixelRatio(self):
        return self._d


# --- стол: окно A (красное) снизу, окно B (синее) сверху и частично закрывает A ---------------------------------
W, H = 800, 600
RA, RB, RM = QRect(100, 100, 300, 200), QRect(300, 150, 300, 220), QRect(50, 380, 200, 120)
RED, BLUE = QColor("#d92d20"), QColor("#2a6df4")


def desk():
    pm = QPixmap(W, H)
    pm.fill(QColor("#7fb2e5"))
    p = QPainter(pm)
    p.fillRect(RA, RED)
    p.fillRect(RB, BLUE)
    p.end()
    return pm


def solid(rect, color):
    pm = QPixmap(rect.size())
    pm.fill(color)
    return pm


def wl(source="gnome-ext", ext="ok", complete=True, extra=()):
    wins = [WinInfo("b", "Окно Б, тайное название письма", "Почта", rect=QRect(RB), z=3, focused=True, source=source),
            WinInfo("a", "Документ А", "Редактор", rect=QRect(RA), z=2, source=source),
            WinInfo("m", "Свёрнутое М", "Файлы", rect=QRect(RM), z=1, minimized=True, source=source), *extra]
    return WindowList(wins, source, complete, ext)


class FakeGrab(QObject):
    """Как windows.WindowGrab: done(QPixmap | None) через delay мс."""
    done = pyqtSignal(object)
    made = []

    def __init__(self, win, result, delay=0):
        super().__init__()
        self.win, self.result, self.delay = win, result, delay
        FakeGrab.made.append(self)

    def start(self):
        QTimer.singleShot(self.delay, lambda: self.done.emit(self.result))


def grab_factory(results, delay=0):
    return lambda win: FakeGrab(win, results.get(win.id), delay)


def make_selector(kept=None, source="gnome-ext", ext="ok", results=None, delay=0, complete=True, ctx=None):
    sel = RegionSelector(desk(), QRect(0, 0, W, H), show_zoom=False, show_size=True, last_rect=kept)
    cfg = dict(appmod.DEFAULTS)
    sel.tr_cfg, sel.tr_save = cfg, (lambda: None)
    sel.lang_ctx = ctx or type("C", (), {"config": cfg, "set_language": lambda *a: None})()
    sel.windows_state = "loading"
    sel.window_grab = grab_factory(results or {}, delay) if windows.can_grab(source) else None
    sel.set_windows(wl(source, ext, complete))
    got = []
    sel.finished.connect(lambda pm, r: got.append((pm, QRect(r))))
    sel.resize(W, H)
    sel.show()
    settle()
    return sel, got


def menu_rows(menu):
    return [(a.text(), a.isEnabled(), bool(a.property("clipsd_note")), a.data()) for a in menu.actions() if not a.isSeparator()]


def pixel(pm, x, y):
    return pm.toImage().pixelColor(x, y)


# =================================================================================== источники списка

def test_gnome_parse():
    shell = {"monitors": [{"index": 0, "x": 0, "y": 0, "w": 1280, "h": 720}, {"index": 1, "x": 1280, "y": 0, "w": 1920, "h": 1080}],
             "windows": [{"id": "11", "title": "T1", "app": "A1", "x": 100, "y": 50, "w": 640, "h": 360, "monitor": 0, "z": 1},
                         {"id": "12", "title": "T2", "app": "A2", "x": 1380, "y": 100, "w": 960, "h": 540, "monitor": 1, "z": 5,
                          "minimized": True}]}
    # Qt (через XWayland) видит первый монитор с масштабом 2: 2560x1440 точек, второй справа 1920x1080
    screens = [FakeScreen(0, 0, 2560, 1440), FakeScreen(2560, 0, 1920, 1080)]
    out = windows.parse_shell_json(json.dumps(shell), screens)
    check([w.id for w in out] == ["12", "11"], "GNOME: окна сверху вниз по наложению")
    check(out[1].rect == QRect(200, 100, 1280, 720), f"GNOME: пересчёт по монитору с масштабом ({out[1].rect})")
    check(out[0].rect == QRect(2660, 100, 960, 540) and out[0].minimized and out[0].monitor == 1,
          f"GNOME: второй монитор и пометка «свёрнуто» ({out[0].rect})")
    # монитор сняли: у Shell ещё два, у Qt уже один: запасной пересчёт всего стола, без падения
    one = [FakeScreen(0, 0, 3200, 1080)]
    out = windows.parse_shell_json(json.dumps(shell), one)
    check(len(out) == 2 and all(not w.rect.isEmpty() for w in out), "смена монитора: число мониторов разное, список есть")
    xml_old = '<node><interface name="org.gnome.Shell.Extensions.ClipSD"><method name="Grab"/></interface></node>'
    check(windows.ext_state_from_introspect(xml_old) == windows.EXT_OLD
          and windows.ext_state_from_introspect("<node/>") == windows.EXT_MISSING,
          "UnknownMethod одинаков для «нет метода» и «нет объекта»: различает описание объекта (Introspect)")


class FakeProp:
    def __init__(self, value):
        self.value = value


class FakeXWin:
    def __init__(self, disp, xid):
        self.disp, self.xid = disp, xid

    def get_full_property(self, atom, _kind):
        name = self.disp.names[atom]
        value = self.disp.props.get(self.xid, {}).get(name)
        return FakeProp(value) if value is not None else None

    def get_wm_class(self):
        return self.disp.props[self.xid].get("class", ("", ""))

    def get_geometry(self):
        g = self.disp.props[self.xid]["geo"]
        return type("G", (), {"width": g[2], "height": g[3]})()

    def translate_coords(self, _root, _x, _y):
        g = self.disp.props[self.xid]["geo"]
        return type("P", (), {"x": -g[0], "y": -g[1]})()


class FakeDisplay:
    def __init__(self, props):
        self.props, self.names, self.atoms = props, {}, {}

    def intern_atom(self, name):
        if name not in self.atoms:
            self.atoms[name] = len(self.atoms) + 100
            self.names[self.atoms[name]] = name
        return self.atoms[name]

    def screen(self):
        return type("S", (), {"root": FakeXWin(self, 0)})()

    def create_resource_object(self, _kind, xid):
        return FakeXWin(self, xid)

    def close(self):
        pass


def test_ewmh():
    d = FakeDisplay({})
    a = d.intern_atom
    normal, util, hidden, skip = (a("_NET_WM_WINDOW_TYPE_NORMAL"), a("_NET_WM_WINDOW_TYPE_UTILITY"),
                                  a("_NET_WM_STATE_HIDDEN"), a("_NET_WM_STATE_SKIP_TASKBAR"))
    d.props = {
        0: {"_NET_CLIENT_LIST_STACKING": [1, 2, 3, 4], "_NET_ACTIVE_WINDOW": [2]},
        1: {"geo": (90, 90, 332, 232), "_GTK_FRAME_EXTENTS": [16, 16, 10, 22], "_NET_WM_WINDOW_TYPE": [normal],
            "_NET_WM_NAME": "Окно GTK".encode(), "class": ("gedit", "Gedit"), "_NET_WM_PID": [41]},
        2: {"geo": (300, 180, 300, 190), "_NET_FRAME_EXTENTS": [0, 0, 30, 0], "_NET_WM_STATE": [hidden],
            "WM_NAME": b"Old X", "class": ("xterm", "XTerm")},
        3: {"geo": (0, 0, 50, 50), "_NET_WM_WINDOW_TYPE": [util], "_NET_WM_NAME": b"tool"},
        4: {"geo": (0, 0, 50, 50), "_NET_WM_STATE": [skip], "_NET_WM_NAME": b"panel"},
    }
    out = windows.from_ewmh([FakeScreen(0, 0, 1600, 1000)], display_factory=lambda: d)
    check([w.title for w in out] == ["Old X", "Окно GTK"], f"EWMH: служебные и «без панели задач» отброшены ({[w.title for w in out]})")
    gtk = out[1]
    check(gtk.rect == QRect(106, 100, 300, 200) and gtk.pid == 41,
          f"EWMH: тень GTK (_GTK_FRAME_EXTENTS) вычтена, pid есть ({gtk.rect})")
    xt = out[0]
    check(xt.rect == QRect(300, 150, 300, 220) and xt.minimized and xt.focused,
          f"EWMH: рамка оконного менеджера добавлена, свёрнутое и активное ({xt.rect})")


def test_win32_records():
    screens = [FakeScreen(0, 0, 1280, 720, 1.5), FakeScreen(1920, 0, 1920, 1080, 1.0)]
    recs = [
        {"hwnd": 10, "title": "Почта", "exe": "C:\\Apps\\mail.exe", "pid": 5, "visible": True, "exstyle": 0, "owner": False,
         "cloaked": False, "iconic": False, "foreground": True, "frame": (150, 150, 900, 600)},
        {"hwnd": 11, "title": "Скрытое на другом столе", "exe": "", "visible": True, "exstyle": 0, "owner": False,
         "cloaked": True, "iconic": False, "frame": (0, 0, 10, 10)},
        {"hwnd": 12, "title": "Панель инструментов", "exe": "", "visible": True, "exstyle": windows.WS_EX_TOOLWINDOW,
         "owner": False, "cloaked": False, "iconic": False, "frame": (0, 0, 10, 10)},
        {"hwnd": 13, "title": "Диалог с владельцем", "exe": "", "visible": True, "exstyle": 0, "owner": True,
         "cloaked": False, "iconic": False, "frame": (0, 0, 10, 10)},
        {"hwnd": 14, "title": "Своё окно в Alt+Tab", "exe": "", "visible": True, "exstyle": windows.WS_EX_APPWINDOW,
         "owner": True, "cloaked": False, "iconic": False, "frame": (2020, 100, 400, 300)},
        {"hwnd": 15, "title": "Свёрнутое", "exe": "C:\\x\\calc.exe", "visible": True, "exstyle": 0, "owner": False,
         "cloaked": False, "iconic": True, "frame": (-32000, -32000, 160, 28)},
        {"hwnd": 16, "title": "", "exe": "", "visible": True, "exstyle": 0, "owner": False, "cloaked": False,
         "iconic": False, "frame": (0, 0, 10, 10)},
        {"hwnd": 17, "title": "Окно выделения ClipSD", "exe": "", "visible": True, "exstyle": 0, "owner": False,
         "cloaked": False, "iconic": False, "frame": (0, 0, 10, 10)},
    ]
    out = windows.win32_records_to_list(recs, screens, exclude=(17,))
    check([w.id for w in out] == ["10", "14", "15"], f"Windows: как Alt+Tab, без скрытых DWM и своего окна ({[w.id for w in out]})")
    check(out[0].rect == QRect(100, 100, 600, 400) and out[0].app == "mail" and out[0].z > out[1].z,
          f"Windows: физические пиксели -> точки по масштабу монитора 150 % ({out[0].rect})")
    check(out[1].rect == QRect(2020, 100, 400, 300) and out[1].monitor == 1, "Windows: второй монитор 100 %")
    check(out[2].minimized and out[2].rect.isEmpty(), "Windows: свёрнутое окно без места (-32000) и с пометкой")


class FakeErr:
    def __init__(self, name):
        self._n = name

    def name(self):
        return self._n


class FakeReply:
    def __init__(self, args):
        self._a = args

    def arguments(self):
        return self._a


def test_lister_paths():
    os.environ["XDG_CURRENT_DESKTOP"], os.environ["XDG_SESSION_TYPE"] = "ubuntu:GNOME", "wayland"
    real = windows.from_ewmh
    windows.from_ewmh = lambda screens=None, display_factory=None: [WinInfo("x1", "XWayland", "X", rect=QRect(0, 0, 10, 10))]
    try:
        got = []
        lister = windows.WindowLister()
        lister.ready.connect(got.append)
        lister._err(FakeErr(windows.UNKNOWN_METHOD), None)
        check(len(got) == 1 and got[0].ext_state == windows.EXT_OLD and not got[0].complete and got[0].source == "ewmh",
              "старое дополнение: неполный список XWayland с пометкой «старое»")
        lister._ok(FakeReply([json.dumps({"windows": [], "monitors": []})]))
        check(len(got) == 1, "поздний ответ дополнения после запасного пути отброшен (один сигнал)")
        got.clear()
        lister = windows.WindowLister()
        lister.ready.connect(got.append)
        real_any = gnome_ext.installed_any
        gnome_ext.installed_any = lambda base=None: False
        lister._err(FakeErr("org.freedesktop.DBus.Error.ServiceUnknown"), None)
        gnome_ext.installed_any = real_any
        check(got and got[0].ext_state == windows.EXT_MISSING, "Shell не отвечает и дополнения нет: пометка «не стоит»")
        got.clear()
        real_any = gnome_ext.installed_any
        for on_disk, want in ((False, windows.EXT_MISSING), (True, windows.EXT_OLD)):
            gnome_ext.installed_any = lambda base=None, v=on_disk: v
            lister = windows.WindowLister()
            lister.ready.connect(got.append)
            lister._introspect_ok(FakeReply(["<node/>"]))
            check(got and got[-1].ext_state == want,
                  f"объекта ClipSD в Shell нет, в папке {'есть (выключено, ждёт входа)' if on_disk else 'нет'}: {want}")
        gnome_ext.installed_any = real_any
        got.clear()
        lister = windows.WindowLister(screens=[FakeScreen(0, 0, 1280, 720)])
        lister.ready.connect(got.append)
        lister.cancel()   # Esc: окно выделения закрыто раньше ответа
        lister._ok(FakeReply([json.dumps({"windows": [], "monitors": []})]))
        check(not got, "Esc во время запроса списка: ответ после отмены не приходит")
        lister = windows.WindowLister(screens=[FakeScreen(0, 0, 1280, 720)])
        lister.ready.connect(got.append)
        lister._ok(FakeReply(["{это не JSON"]))
        check(got and got[0].ext_state == windows.EXT_OLD, "испорченный ответ: запасной путь, без падения")
    finally:
        windows.from_ewmh = real
        os.environ.pop("XDG_CURRENT_DESKTOP", None)
        os.environ.pop("XDG_SESSION_TYPE", None)


# =================================================================================== окно выделения

def test_chip_and_keyboard():
    sel, _got = make_selector(kept=QRect(450, 420, 200, 120))
    sel._bar_layout()
    check(not sel.win_rect.isEmpty() and sel._button_at(sel.win_rect.center()) == "window",
          "чип «Окна ▾» в нижней строке панели, щелчок по нему открывает список")
    sel2 = RegionSelector(desk(), QRect(0, 0, W, H), last_rect=QRect(450, 420, 200, 120))
    sel2.lang_ctx = sel.lang_ctx
    sel2._bar_layout()
    check(sel2.win_rect.isEmpty(), "без списка окон (система не умеет) чипа нет, панель как в 1.32.3")
    sel2.deleteLater()

    QTest.keyClick(sel, Qt.Key.Key_W)
    settle()
    menu = sel.win_menu
    check(menu is not None and menu.isVisible(), "клавиша W открывает список окон")
    rows = menu_rows(menu)
    titles = [r[0].split("\t")[0] for r in rows]
    check(titles[:2] == ["Окно Б, тайное название письма · Почта", "Документ А · Редактор"],
          f"окна сверху вниз, после заголовка имя программы ({titles})")
    check(rows[2][0].endswith("\t" + tr("selector.win_minimized")) and not rows[2][1],
          "свёрнутое окно в конце с пометкой «свёрнуто»")
    check(menu.activeAction() is not None and menu.activeAction().data() == "b" and sel.preview_win is not None
          and sel.preview_win.id == "b", "с клавиатуры сразу выделено верхнее окно, его рамка видна на экране")
    QTest.keyClick(menu, Qt.Key.Key_Down)
    settle()
    check(menu.activeAction().data() == "a" and sel.preview_win.id == "a", "стрелка вниз: следующее окно и его рамка")
    QTest.keyClick(menu, Qt.Key.Key_Escape)
    settle()
    check(sel.win_menu is None and sel.isVisible() and sel.preview_win is None and sel.kept == QRect(450, 420, 200, 120),
          "Esc закрывает только список: окно выделения и прошлая рамка на месте")
    QTest.keyClick(sel, Qt.Key.Key_W)
    settle()
    QTest.keyClick(sel.win_menu, Qt.Key.Key_Down)
    QTest.keyClick(sel.win_menu, Qt.Key.Key_Return)
    settle()
    check(sel.kept == RA and sel.picked_win is not None and sel.picked_win.id == "a",
          f"Enter в списке: рамка ровно на окне ({sel.kept})")
    sel.close()
    settle()


def test_cyrillic_w():
    from PyQt6.QtGui import QKeyEvent
    from PyQt6.QtCore import QEvent
    ev = QKeyEvent(QEvent.Type.KeyPress, 0, Qt.KeyboardModifier.NoModifier, "ц")
    check(RegionSelector._is_w_key(ev), "W работает и на русской раскладке («ц»)")
    ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_W, Qt.KeyboardModifier.ControlModifier, "w")
    check(not RegionSelector._is_w_key(ev), "Ctrl+W не открывает список")


def test_covered_window_lifted():
    sel, got = make_selector(results={"a": solid(RA, RED)}, delay=120)
    a = next(w for w in sel.windows if w.id == "a")
    sel.pick_window(a)
    check(sel.kept == RA and sel._lift is not None, "окно под другим: рамка сразу, содержимое просится у дополнения")
    QTest.keyClick(sel, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    settle(2)
    check(not got and sel.pending == RA, "Ctrl+Enter до прихода содержимого: снимок ждёт его")
    check(wait(lambda: bool(got)), "содержимое пришло: снимок сделан")
    pm, rect = got[0]
    inside = QPoint(RB.left() - RA.left() + 20, RB.top() - RA.top() + 20)   # место, где сверху лежало окно Б
    check(rect == RA and pixel(pm, inside.x(), inside.y()) == RED,
          "в снимке окно целиком: там, где его закрывало другое окно, его собственное содержимое")


def test_closed_between_list_and_pick():
    sel, got = make_selector(results={"a": None}, delay=30)   # окно А закрылось после Alt+W: дополнение его не нашло
    sel.pick_window(next(w for w in sel.windows if w.id == "a"))
    check(wait(lambda: sel._lift is None), "ответ «окна нет» пришёл")
    plate = sel.findChild(hints.HintPlate, "clipsdHint")
    check(sel.kept == RA and plate is not None and plate.text == tr("selector.win_closed"),
          "окно закрылось: рамка остаётся, подсказка «в снимок попадёт то, что было видно»")
    QTest.keyClick(sel, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    check(wait(lambda: bool(got)) and got[0][1] == RA and pixel(got[0][0], 250, 100) == BLUE,
          "снимок из замороженного кадра, как было на экране")


def test_minimized():
    sel, _got = make_selector(results={"m": solid(RM, QColor("#157a40"))}, kept=QRect(450, 420, 200, 120))
    QTest.keyClick(sel, Qt.Key.Key_W)
    settle()
    m = next(r for r in menu_rows(sel.win_menu) if r[3] == "m")
    check(m[0].endswith("\t" + tr("selector.win_minimized")) and not m[1],
          "свёрнутое окно в списке с пометкой «свёрнуто», но не выбирается (содержимого нет)")
    sel.win_menu.close()
    settle()
    sel.pick_window(next(w for w in sel.windows if w.id == "m"))
    plate = sel.findChild(hints.HintPlate, "clipsdHint")
    check(sel.kept == QRect(450, 420, 200, 120) and sel.picked_win is None and not FakeGrab.made[-1:] == [None]
          and plate is not None and plate.text == tr("selector.win_min_failed") and plate.sub == tr("selector.win_min_failed_sub"),
          "свёрнутое окно выбрать нельзя: прежняя рамка на месте, подсказка «разверните его»")
    sel.close()


def test_late_answers():
    sel, got = make_selector(results={"a": solid(RA, RED)}, delay=150)
    sel.pick_window(next(w for w in sel.windows if w.id == "a"))
    first = sel._lift
    sel.clear_kept()   # «Выделить заново» до ответа
    QTest.qWait(250)
    settle()
    check(first is not None and sel.kept is None and sel._desktop_orig is None,
          "поздний ответ на прежний выбор отброшен: кадр не тронут")
    sel.close()

    sel = RegionSelector(desk(), QRect(0, 0, W, H), last_rect=QRect(450, 420, 200, 120))
    sel.lang_ctx = type("C", (), {"config": dict(appmod.DEFAULTS)})()
    sel.windows_state = "loading"
    sel.resize(W, H)
    sel.show()
    settle()
    sel.bar_pos = QPoint(20, 30)   # панель перетащили, пока список ещё шёл
    QTest.keyClick(sel, Qt.Key.Key_W)
    settle()
    plate = sel.findChild(hints.HintPlate, "clipsdHint")
    check(sel.win_menu is None and sel._win_open_pending and plate is not None and plate.text == tr("selector.win_loading"),
          "W до прихода списка: подсказка «готовится», меню откроется само")
    sel.set_windows(wl())
    settle()
    check(sel.win_menu is not None and sel.win_menu.isVisible(), "список пришёл: меню открылось")
    check(sel.bar_pos == QPoint(20, 30), "приход списка не двигает перетащенную панель")
    sel.win_menu.close()
    sel.close()


def test_offscreen_window():
    off = WinInfo("o", "За краем", "X", rect=QRect(1700, 100, 300, 200), z=9, source="gnome-ext")
    sel, _got = make_selector()
    sel.set_windows(wl(extra=(off,)))
    QTest.keyClick(sel, Qt.Key.Key_W)
    settle()
    check(all(r[3] != "o" for r in menu_rows(sel.win_menu)), "смена монитора: окно вне стола в список не попадает")
    sel.win_menu.close()
    settle()
    sel.pick_window(off)
    check(sel.kept is None and sel.picked_win is None, "окно вне стола выбрать нельзя, рамка не ставится")
    sel.close()


def test_extension_notice():
    calls = []
    ctx = type("C", (), {"config": dict(appmod.DEFAULTS), "update_gnome_extension": lambda self: calls.append(1)})()
    sel, got = make_selector(source="ewmh", ext=windows.EXT_OLD, complete=False, ctx=ctx)
    QTest.keyClick(sel, Qt.Key.Key_W)
    settle()
    rows = menu_rows(sel.win_menu)
    check(rows[0][0] == tr("selector.win_need_update") and rows[0][2] and not rows[0][1],
          "старое дополнение: сверху строка «Для полного списка окон нужно обновить дополнение ClipSD в GNOME»")
    check(rows[1][0] == tr("selector.win_do_update") and rows[1][1], "под ней пункт «Обновить»")
    check(any(r[3] == "a" for r in rows), "ниже неполный список окон (XWayland)")
    check(sel.win_menu.activeAction() is not None and sel.win_menu.activeAction().data() == "b",
          "с клавиатуры выделено первое окно, а не «Обновить» (случайный Enter ничего не ставит)")
    upd = next(a for a in sel.win_menu.actions() if a.objectName() == "clipsdUpdateExtension")
    upd.trigger()
    check(wait(lambda: bool(got) and bool(calls)) and got[0][0] is None,
          "«Обновить»: окно выделения закрывается без снимка, программа ставит дополнение")

    sel, _got = make_selector(source="none", ext=windows.EXT_MISSING, complete=False, ctx=ctx)
    sel.windows = []
    QTest.keyClick(sel, Qt.Key.Key_W)
    settle()
    rows = menu_rows(sel.win_menu)
    check(rows[0][0] == tr("selector.win_need_install") and rows[1][0] == tr("selector.win_do_install")
          and rows[-1][0] == tr("selector.win_empty"), "дополнения нет: «установить», «Установить», «Других окон не видно»")
    sel.win_menu.close()
    sel.close()

    sel, _got = make_selector(source="ewmh", ext=windows.EXT_OLD, complete=False, ctx=ctx)
    sel.window_ext_relogin = True
    QTest.keyClick(sel, Qt.Key.Key_W)
    settle()
    rows = menu_rows(sel.win_menu)
    check(rows[0][0] == tr("selector.win_relogin") and all(a.objectName() != "clipsdUpdateExtension" for a in sel.win_menu.actions()),
          "уже обновлено, ждёт входа: только пояснение «выйдите из системы и войдите снова», без кнопки")
    sel.win_menu.close()
    sel.close()


# =================================================================================== проверка 1.33 (В5, В6, О-М2, О-М3)

def test_v5_full_and_monitor_drop_lifted():
    """В5: выбранное окно А вписано поверх; затем «Весь экран» или монитор: в снимке то, что было на экране."""
    for action in ("full", "mon:0"):
        sel, got = make_selector(results={"a": solid(RA, RED)})
        sel.pick_window(next(w for w in sel.windows if w.id == "a"))
        wait(lambda: sel._lift is None)
        check(pixel(sel.desktop, 350, 250) == RED, f"{action}: окно А вписано в кадр (под окном Б красное)")
        if action == "full":
            sel._do("full")
        else:
            sel.show_full_screen()
            sel.select_monitor(0)
        check(sel.picked_win is None and pixel(sel.desktop, 350, 250) == BLUE,
              f"{action}: вписанное окно убрано, кадр как на экране")
        QTest.keyClick(sel, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        check(wait(lambda: bool(got)) and pixel(got[0][0], 350, 250) == BLUE,
              f"{action}: в снимке экрана нет картинки, которой на экране не было")


def test_v5_translate_other_place_drops_lifted():
    sel, _got = make_selector(results={"a": solid(RA, RED)})
    sel.pick_window(next(w for w in sel.windows if w.id == "a"))
    wait(lambda: sel._lift is None)
    sel.start_translate_pick()
    check(sel.picked_win is None and pixel(sel.desktop, 350, 250) == BLUE,
          "«Выделить и перевести» после выбора окна: перевод с кадра как на экране")
    sel.close()


def _loading_selector():
    sel = RegionSelector(desk(), QRect(0, 0, W, H), show_zoom=False, show_size=True, last_rect=None)
    cfg = dict(appmod.DEFAULTS)
    sel.tr_cfg, sel.tr_save = cfg, (lambda: None)
    sel.lang_ctx = type("C", (), {"config": cfg, "set_language": lambda *a: None})()
    sel.windows_state = "loading"
    sel.resize(W, H)
    sel.show()
    settle()
    return sel


def test_om3_pending_list_not_mid_action():
    """О-М3 (пробы p03 w_pending_drag, w_pending_translate, p04): W до прихода списка, потом протягивание или режим
    перевода: меню посреди действия не открывается, протягивание доходит до конца."""
    sel = _loading_selector()
    QTest.keyClick(sel, Qt.Key.Key_W)
    QTest.mousePress(sel, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(50, 50))
    QTest.mouseMove(sel, QPoint(150, 120))
    sel.set_windows(wl())
    settle()
    check(sel.win_menu is None and not sel._win_open_pending, "W, затем протягивание, затем пришёл список: меню не открылось")
    got = []
    sel.finished.connect(lambda pm, r: got.append(QRect(r)))
    QTest.mouseRelease(sel, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(150, 120))
    check(wait(lambda: bool(got)) and got[0] == QRect(50, 50, 100, 70), f"протягивание доведено до снимка ({got[:1]})")

    sel = _loading_selector()
    QTest.keyClick(sel, Qt.Key.Key_W)
    sel.enter_translate()
    sel.set_windows(wl())
    settle()
    check(sel.win_menu is None, "W, затем режим перевода, затем пришёл список: меню не открылось")
    QTest.keyClick(sel, Qt.Key.Key_W)
    check(sel.win_menu is None, "в режиме перевода W список не открывает")
    sel.close()

    sel = _loading_selector()
    QTest.keyClick(sel, Qt.Key.Key_W)
    QTest.keyClick(sel, Qt.Key.Key_W)
    sel.set_windows(wl())
    settle()
    from PyQt6.QtWidgets import QMenu
    check(len([m for m in sel.findChildren(QMenu) if m.isVisible()]) == 1, "W дважды до списка: одно меню")
    sel.win_menu.close()
    sel.close()


def test_om2_slow_extension():
    """О-М2: дополнение отвечает дольше 1,5 с: временный неполный список без «Обновить», потом полный."""
    os.environ["XDG_CURRENT_DESKTOP"], os.environ["XDG_SESSION_TYPE"] = "ubuntu:GNOME", "wayland"
    real = windows.from_ewmh
    windows.from_ewmh = lambda screens=None, display_factory=None: [WinInfo("x1", "XWayland", "X", rect=QRect(0, 0, 10, 10))]
    try:
        got = []
        lister = windows.WindowLister(screens=[FakeScreen(0, 0, W, H)])
        lister.ready.connect(got.append)
        lister._provisional()
        check(len(got) == 1 and not got[0].final and got[0].ext_state == windows.EXT_SLOW and not got[0].complete,
              "1,5 с без ответа: временный список, состояние «медленно», а не «старое»")
        lister._provisional()
        lister._ok(FakeReply([json.dumps({"monitors": [{"index": 0, "x": 0, "y": 0, "w": W, "h": H}],
                                          "windows": [{"id": "a", "title": "A", "x": 1, "y": 2, "w": 30, "h": 40, "monitor": 0}]})]))
        check(len(got) == 2 and got[1].final and got[1].ext_state == windows.EXT_OK and got[1].windows[0].id == "a",
              "настоящий ответ пришёл позже: полный список заменяет временный")
        got.clear()
        lister = windows.WindowLister()
        lister.ready.connect(got.append)
        lister._err(FakeErr("org.freedesktop.DBus.Error.NoReply"), None)
        check(got and got[0].final and got[0].ext_state == windows.EXT_SLOW,
              "дополнение так и не ответило (NoReply): «медленно», не «устарело»")
    finally:
        windows.from_ewmh = real
        os.environ.pop("XDG_CURRENT_DESKTOP", None)
        os.environ.pop("XDG_SESSION_TYPE", None)
    sel, _got = make_selector(source="ewmh", ext=windows.EXT_SLOW, complete=False)
    QTest.keyClick(sel, Qt.Key.Key_W)
    settle()
    rows = menu_rows(sel.win_menu)
    check(rows[0][0] == tr("selector.win_slow") and all(a.objectName() != "clipsdUpdateExtension" for a in sel.win_menu.actions()),
          "в меню «GNOME отвечает медленно», кнопки «Обновить» нет")
    sel.win_menu.close()
    sel.close()


def test_v6_windows_errors():
    """В6 (проба p06): ошибка ctypes в списке или снимке окна Windows не роняет программу."""
    import types
    real_sys, real_from = windows.sys, windows.from_win32
    windows.sys = types.SimpleNamespace(platform="win32")

    def boom(exclude=(), screens=None):
        raise OSError("ошибка внутри EnumWindows (подмена)")
    windows.from_win32 = boom
    try:
        got = []
        lister = windows.WindowLister()
        lister.ready.connect(got.append)
        lister.start()
        check(wait(lambda: bool(got)) and got[0].failed and got[0].windows == [] and got[0].final,
              "Windows: список упал, программа жива, пустой список с пометкой «не получен»")
        real_grab = windows.grab_window_win32
        windows.grab_window_win32 = lambda win: (_ for _ in ()).throw(OSError("PrintWindow (подмена)"))
        res = []
        job = windows.WindowGrab(WinInfo("1", "x", "x", rect=QRect(RA), source="win32"))
        job.done.connect(lambda pm: res.append(pm))
        job.start()
        check(wait(lambda: bool(res)) and res[0] is None, "Windows: PrintWindow упал: содержимого нет, программа жива")
        windows.grab_window_win32 = real_grab
    finally:
        windows.sys, windows.from_win32 = real_sys, real_from
    sel = RegionSelector(desk(), QRect(0, 0, W, H), show_zoom=False, last_rect=QRect(450, 420, 200, 120))
    sel.lang_ctx = type("C", (), {"config": dict(appmod.DEFAULTS)})()
    sel.windows_state = "loading"
    sel.set_windows(WindowList([], "win32", False, failed=True))
    sel.resize(W, H)
    sel.show()
    settle()
    QTest.keyClick(sel, Qt.Key.Key_W)
    settle()
    rows = menu_rows(sel.win_menu)
    check(rows and rows[0][0] == tr("selector.win_failed") and len(rows) == 1,
          "в меню одна понятная строка «Список окон не получен: выделите окно мышью»")
    sel.win_menu.close()
    settle()
    got = []
    sel.finished.connect(lambda pm, r: got.append(QRect(r)))
    QTest.keyClick(sel, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    check(wait(lambda: bool(got)) and got[0] == QRect(450, 420, 200, 120), "Alt+W работает как раньше: прошлая рамка снята")


def test_x11_covered_visible_only():
    """Проба p07: X11 без GNOME или GNOME со старым дополнением: окно под другими снимается видимой частью, и
    человеку это сказано (обещание «целиком» в CHANGELOG только для GNOME и Windows)."""
    sel, got = make_selector(source="ewmh", ext="", complete=True)
    sel.pick_window(next(w for w in sel.windows if w.id == "a"))
    plate = sel.findChild(hints.HintPlate, "clipsdHint")
    check(sel.kept == RA and sel._lift is None and plate is not None and plate.text == tr("selector.win_visible_only"),
          "X11: рамка на окне, подсказка «снимется только видимая часть»")
    QTest.keyClick(sel, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    check(wait(lambda: bool(got)) and pixel(got[0][0], 220, 70) == BLUE, "X11: в снимке видимая часть, как на экране")


def test_private_temp_dir():
    """Снимки стола и окон пишутся в личную папку ClipSD: XDG_RUNTIME_DIR только своя и закрытая (0700, не ссылка),
    иначе своя папка 0700; имя файла с непредсказуемой частью (проверка 1.33, замечание к методу Grab)."""
    import stat
    from clipshot import grab
    real_env = os.environ.get("XDG_RUNTIME_DIR")
    cases = []
    good = tempfile.mkdtemp(prefix="clipsd-run-")
    os.chmod(good, 0o700)
    open_dir = tempfile.mkdtemp(prefix="clipsd-open-")
    os.chmod(open_dir, 0o777)
    link = os.path.join(tempfile.mkdtemp(prefix="clipsd-ln-"), "run")
    os.symlink(good, link)
    try:
        for name, value in (("своя 0700", good), ("открытая всем", open_dir), ("ссылка", link), ("нет", None)):
            grab._private_dir = None
            if value is None:
                os.environ.pop("XDG_RUNTIME_DIR", None)
            else:
                os.environ["XDG_RUNTIME_DIR"] = value
            d = grab.private_dir()
            st = os.lstat(d)
            cases.append((name, d, stat.S_ISDIR(st.st_mode) and not st.st_mode & 0o077))
        check(cases[0][1] == good and cases[0][2], "XDG_RUNTIME_DIR своя и закрытая: снимки в ней")
        check(all(c[1] not in (open_dir, link) and c[2] for c in cases[1:]),
              f"XDG_RUNTIME_DIR открыта всем, ссылка или её нет: своя папка 0700 ({[c[0] for c in cases[1:]]})")
        a, b = grab._temp_png(), grab._temp_png()
        check(a != b and os.path.dirname(a) == grab.private_dir() and len(os.path.basename(a).split("-")) == 4,
              "имена временных файлов разные, в личной папке, со случайной частью")
    finally:
        grab._private_dir = None
        if real_env is None:
            os.environ.pop("XDG_RUNTIME_DIR", None)
        else:
            os.environ["XDG_RUNTIME_DIR"] = real_env


# =================================================================================== дополнение GNOME

def fake_run(state):
    def run(cmd, **_kw):
        state["calls"].append(cmd)
        out = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        if cmd[0] == "gsettings" and cmd[1] == "get":
            out.stdout = state["enabled"]
        elif cmd[0] == "gsettings" and cmd[1] == "set":
            state["enabled"] = cmd[-1]
        elif cmd[0] == "gsettings":
            out.returncode = 1
        if state.get("fail_get") and cmd[:2] == ["gsettings", "get"]:
            out.returncode, out.stderr = 1, "нет dconf"
        return out
    return run


def test_extension_update():
    src = Path(ROOT) / "packaging/gnome-extension" / gnome_ext.EXT_UUID
    base = Path(tempfile.mkdtemp(prefix="clipsd-ext-")) / "extensions"
    st = {"enabled": "@as []", "calls": []}
    state, _d = gnome_ext.update(src, base, fake_run(st), "1.33.0")
    target = base / gnome_ext.EXT_UUID
    check(state == gnome_ext.INSTALLED and (target / "extension.js").exists() and (target / gnome_ext.PKG_MARK).exists(),
          "дополнения не было: поставлено в папку пользователя с меткой пакета")
    check("ListWindows" in (target / "extension.js").read_text(encoding="utf-8") and gnome_ext.EXT_UUID in st["enabled"],
          "в нём ListWindows и GrabWindow, и оно включено в enabled-extensions")
    state, _d = gnome_ext.update(src, base, fake_run(st), "1.33.0")
    check(state == gnome_ext.UPDATED and not (base / f".{gnome_ext.EXT_UUID}.old").exists(),
          "повторно: обновлено, временных папок не осталось")

    base2 = Path(tempfile.mkdtemp(prefix="clipsd-ext-")) / "extensions"
    (base2 / gnome_ext.EXT_UUID).mkdir(parents=True)
    (base2 / gnome_ext.EXT_UUID / "extension.js").write_text("// рабочая копия разработчика", encoding="utf-8")
    state, _d = gnome_ext.update(src, base2, fake_run({"enabled": "['x@y']", "calls": []}))
    check(state == gnome_ext.FOREIGN and "рабочая копия" in (base2 / gnome_ext.EXT_UUID / "extension.js").read_text(encoding="utf-8"),
          "папка дополнения без метки пакета (рабочая копия): не трогается")

    base3 = Path(tempfile.mkdtemp(prefix="clipsd-ext-")) / "extensions"
    legacy = base3 / "clipsd@old"
    legacy.mkdir(parents=True)
    (legacy / "metadata.json").write_text(json.dumps({"settings-schema": gnome_ext.EXT_SCHEMA}), encoding="utf-8")
    st3 = {"enabled": "['clipsd@old']", "calls": []}
    state, detail = gnome_ext.update(src, base3, fake_run(st3))
    check(state == gnome_ext.FOREIGN and detail == "clipsd@old" and legacy.exists() and not (base3 / gnome_ext.EXT_UUID).exists(),
          "включено прежнее дополнение без метки (рабочая копия): второе не ставится, чтобы не спорили за Alt+W")
    (legacy / gnome_ext.PKG_MARK).write_text("installed by ClipSD 1.29\n", encoding="utf-8")
    state, _d = gnome_ext.update(src, base3, fake_run(st3))
    check(state == gnome_ext.UPDATED and not legacy.exists() and "clipsd@old" not in st3["enabled"]
          and gnome_ext.EXT_UUID in st3["enabled"], "прежнее дополнение от пакета заменено новым, как в install.sh")

    check(gnome_ext.installed_any(base) and gnome_ext.installed_any(base3) and not gnome_ext.installed_any(Path(tempfile.mkdtemp())),
          "дополнение в папке пользователя находится (новое и прежнее по схеме)")
    # проверка 1.33, О-М6 (проба p05)
    b_ln = Path(tempfile.mkdtemp(prefix="clipsd-ext-")) / "extensions"
    b_ln.mkdir(parents=True)
    devcopy = b_ln.parent / "dev-wc"
    devcopy.mkdir()
    (devcopy / "extension.js").write_text("// dev", encoding="utf-8")
    (b_ln / gnome_ext.EXT_UUID).symlink_to(devcopy)
    state, _d = gnome_ext.update(src, b_ln, fake_run({"enabled": "@as []", "calls": []}))
    check(state == gnome_ext.FOREIGN and (devcopy / "extension.js").read_text(encoding="utf-8") == "// dev"
          and (b_ln / gnome_ext.EXT_UUID).is_symlink(), "папка-ссылка на рабочую копию без метки: не трогается")
    base5 = Path(tempfile.mkdtemp(prefix="clipsd-ext-")) / "extensions"
    base5.mkdir(parents=True)
    elsewhere = base5.parent / "pkg-elsewhere"
    elsewhere.mkdir()
    (elsewhere / "metadata.json").write_text('{"version": 2}', encoding="utf-8")
    (elsewhere / gnome_ext.PKG_MARK).write_text("x", encoding="utf-8")
    (base5 / gnome_ext.EXT_UUID).symlink_to(elsewhere)
    state, _d = gnome_ext.update(src, base5, fake_run({"enabled": "@as []", "calls": []}))
    check(state == gnome_ext.UPDATED and sorted(p.name for p in base5.iterdir()) == [gnome_ext.EXT_UUID]
          and not (base5 / gnome_ext.EXT_UUID).is_symlink() and (elsewhere / "metadata.json").exists(),
          "папка-ссылка с меткой: заменена папкой, .old не осталось, то, на что вела ссылка, цело")
    base6 = Path(tempfile.mkdtemp(prefix="clipsd-ext-")) / "extensions"
    t6 = base6 / gnome_ext.EXT_UUID
    t6.mkdir(parents=True)
    (t6 / "metadata.json").write_text('{"version": 2}', encoding="utf-8")
    (t6 / gnome_ext.PKG_MARK).write_text("x", encoding="utf-8")
    st6 = {"enabled": "@as []", "calls": []}
    run6 = fake_run(st6)

    def failing_set(cmd, **kw):
        if cmd[:2] == ["gsettings", "set"]:
            return type("R", (), {"returncode": 1, "stdout": "", "stderr": "dconf: нет доступа"})()
        return run6(cmd, **kw)
    state, _d = gnome_ext.update(src, base6, failing_set)
    check(state == gnome_ext.FAILED and json.loads((t6 / "metadata.json").read_text(encoding="utf-8")).get("version") == 2
          and sorted(p.name for p in base6.iterdir()) == [gnome_ext.EXT_UUID],
          "включить не вышло: «не обновилось», прежнее дополнение и папка как были")
    base7 = Path(tempfile.mkdtemp(prefix="clipsd-ext-")) / "extensions"
    t7 = base7 / gnome_ext.EXT_UUID
    t7.mkdir(parents=True)
    (t7 / "metadata.json").write_text('{"version": 2}', encoding="utf-8")
    (t7 / gnome_ext.PKG_MARK).write_text("x", encoding="utf-8")
    os.chmod(base7, 0o555)
    try:
        state, _d = gnome_ext.update(src, base7, fake_run({"enabled": "['clipsd@clipsd.github.io']", "calls": []}))
    finally:
        os.chmod(base7, 0o755)
    check(state == gnome_ext.FAILED and (t7 / "metadata.json").read_text(encoding="utf-8") == '{"version": 2}',
          "нет прав на запись: «не обновилось», прежнее дополнение цело")

    def with_get(values, version_out=""):
        def run(cmd, **kw):
            r = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
            if cmd[:2] == ["gsettings", "get"]:
                r.stdout = values.get(cmd[-1], "")
            elif cmd[0] == "gnome-shell":
                r.stdout = version_out
            return r
        return run
    b8 = Path(tempfile.mkdtemp(prefix="clipsd-ext-")) / "extensions"
    state, _d = gnome_ext.update(src, b8, with_get({"enabled-extensions": "@as []", "disable-user-extensions": "true"}))
    check(state == gnome_ext.USER_EXT_OFF and not b8.exists(),
          "в GNOME выключены все дополнения: честный ответ, ничего не ставится (вход бы не помог)")
    state, detail = gnome_ext.update(src, b8, with_get({"enabled-extensions": "@as []", "disable-user-extensions": "false"},
                                                       "GNOME Shell 51.0"))
    check(state == gnome_ext.UNSUPPORTED and detail == "51" and not b8.exists(),
          "GNOME 51 вне списка версий дополнения: честный ответ с версией, ничего не ставится")
    state, _d = gnome_ext.update(src, b8, with_get({"enabled-extensions": "@as []", "disable-user-extensions": "false"},
                                                   "GNOME Shell 50.1"))
    check(state == gnome_ext.INSTALLED, "GNOME 50.1: ставится")
    check(gnome_ext.update(Path(tempfile.mkdtemp()), base, fake_run(st))[0] == gnome_ext.NO_SOURCE,
          "в сборке нет файлов дополнения: честный ответ, ничего не трогается")
    st4 = {"enabled": "@as []", "calls": [], "fail_get": True}
    check(gnome_ext.update(src, Path(tempfile.mkdtemp()) / "e", fake_run(st4))[0] == gnome_ext.FAILED,
          "gsettings не работает: «не обновилось», файлы не тронуты")


# =================================================================================== настоящий Clipshot

def alt_w(c):
    """Alt+W: та же команда, что от дополнения GNOME и меню значка (защита от двойного нажатия сброшена)."""
    c.last_trigger = 0.0
    c.capture_region()


class FakeLister(QObject):
    ready = pyqtSignal(object)
    result, delay, made = None, 0, []

    def __init__(self, parent=None, screens=None):
        super().__init__(parent)
        self.cancelled = False
        FakeLister.made.append(self)

    def start(self):
        QTimer.singleShot(FakeLister.delay, lambda: None if self.cancelled else self.ready.emit(FakeLister.result))

    def cancel(self):
        self.cancelled = True


def test_app_flow():
    appmod.CONFIG_PATH = Path(tempfile.mkdtemp(prefix="clipsd-okno-cfg-", dir=os.environ.get("TMPDIR"))) / "config.json"
    appmod.is_wayland = lambda: False
    appmod.grab_qt = desk
    appmod.virtual_geometry = lambda: QRect(0, 0, W, H)
    windows.WindowLister = FakeLister
    windows.supported = lambda: True
    windows.WindowGrab = lambda win, parent=None: FakeGrab(win, solid(RA, RED) if win.id == "a" else None)
    c = appmod.Clipshot(app)
    c.config.update(auto_save=False, theme_chosen=True, tour_done=True, tour_selector_done=True, remember_region=True,
                    last_region=[450, 420, 200, 120])
    copied = []
    c.copy_image = lambda img: copied.append(img)
    c.notify = lambda text: None

    FakeLister.result, FakeLister.delay = wl(), 0
    alt_w(c)
    check(wait(lambda: c.selector is not None and c.selector.isVisible() and c.selector.windows_state == "ready"),
          "Alt+W: окно выделения открыто, список окон пришёл")
    sel = c.selector
    QTest.keyClick(sel, Qt.Key.Key_W)
    settle()
    QTest.keyClick(sel.win_menu, Qt.Key.Key_Down)
    QTest.keyClick(sel.win_menu, Qt.Key.Key_Return)
    settle()
    QTest.keyClick(sel, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    check(wait(lambda: c.selector is None and bool(copied)), "W, стрелка, Enter, Ctrl+Enter: окно скопировано")
    check(c.config.get("last_region") == [RA.x(), RA.y(), RA.width(), RA.height()],
          f"следующий снимок с того же места: last_region = рамка окна ({c.config.get('last_region')})")
    check(copied and copied[0].pixelColor(RB.left() - RA.left() + 20, RB.top() - RA.top() + 20) == RED,
          "в буфер ушло окно целиком (закрытая часть своим содержимым)")
    c.save_config()
    text = appmod.CONFIG_PATH.read_text(encoding="utf-8")
    check("тайное название" not in text and "Документ А" not in text, "названия окон не попали в настройки")

    alt_w(c)
    check(wait(lambda: c.selector is not None and c.selector.isVisible()), "следующий Alt+W открыт")
    check(c.selector.kept == RA, "рамка предложена на том же месте, где было окно")
    QTest.keyClick(c.selector, Qt.Key.Key_Escape)
    wait(lambda: c.selector is None)

    # Esc во время запроса списка: дополнение отвечает через 300 мс, окно выделения уже закрыто
    FakeLister.delay = 300
    alt_w(c)
    check(wait(lambda: c.selector is not None and c.selector.isVisible()), "Alt+W при медленном дополнении: окно сразу")
    sel = c.selector
    check(sel.windows_state == "loading" and not sel.win_rect.isEmpty(), "список ещё идёт: чип уже есть")
    QTest.keyClick(sel, Qt.Key.Key_W)
    QTest.keyClick(sel, Qt.Key.Key_Escape)
    check(wait(lambda: c.selector is None), "Esc во время запроса списка закрывает окно выделения")
    QTest.qWait(450)
    settle()
    check(FakeLister.made[-1].cancelled and c.selector is None, "поздний ответ после Esc отброшен, ничего не открылось")
    settle(4)
    check(not c.findChildren(FakeLister), "объект списка удалён, хотя окно выделения закрыли до ответа (О-М4)")

    # дополнение обновлено кнопкой: напоминание о входе, после входа (список от нового дополнения) оно уходит
    cards = []
    c._show_ext_card = lambda title, text, icon, secondary=None: cards.append((title, text, icon, secondary)) or "close"
    gnome_ext.update = lambda version="": (gnome_ext.INSTALLED, "")
    # как в настоящем сеансе GNOME: Shell на шине есть, его имя запоминается до входа; окно «выйдите и войдите» то же
    windows.shell_owner = lambda: ":1.7"
    check(c.update_gnome_extension() == gnome_ext.INSTALLED and c.config.get("gnome_ext_relogin") == ":1.7"
          and cards and cards[0][1] == tr("app.ext_relogin_text") and cards[0][3] == tr("app.ext_logout"),
          "настоящий сеанс (Shell на шине): окно «выйдите и войдите», запомнено имя Shell")
    cards.clear()
    windows.shell_owner = lambda: ""   # Shell на шине не найден: запоминается просто «ждёт входа»
    check(c.update_gnome_extension() == gnome_ext.INSTALLED and c.config.get("gnome_ext_relogin") is True
          and cards and cards[0][1] == tr("app.ext_relogin_text") and cards[0][3] == tr("app.ext_logout"),
          "«Установить»: окно «выйдите из системы и войдите снова» с кнопкой «Выйти из системы…»")
    FakeLister.delay, FakeLister.result = 0, wl("ewmh", windows.EXT_OLD, False)
    alt_w(c)
    check(wait(lambda: c.selector is not None and c.selector.windows_state == "ready") and c.selector.window_ext_relogin,
          "до входа в систему список помнит, что дополнение уже обновлено")
    QTest.keyClick(c.selector, Qt.Key.Key_Escape)
    wait(lambda: c.selector is None)
    FakeLister.result = wl()
    alt_w(c)
    check(wait(lambda: c.selector is not None and c.selector.windows_state == "ready")
          and "gnome_ext_relogin" not in c.config, "после входа дополнение отвечает: напоминание убрано")
    QTest.keyClick(c.selector, Qt.Key.Key_Escape)
    wait(lambda: c.selector is None)
    gnome_ext.update = lambda version="": (gnome_ext.FOREIGN, "clipsd@old")
    cards.clear()
    c.update_gnome_extension()
    check(cards and cards[0][0] == tr("app.ext_foreign_title") and cards[0][3] is None, "рабочая копия: объяснение, одна кнопка")
    for state, detail, title in ((gnome_ext.USER_EXT_OFF, "", "app.ext_userext_off_title"),
                                 (gnome_ext.UNSUPPORTED, "51", "app.ext_unsupported_title")):
        gnome_ext.update = lambda version="", s=state, d=detail: (s, d)
        cards.clear()
        c.update_gnome_extension()
        check(cards and cards[0][0] == tr(title) and "gnome_ext_relogin" not in c.config,
              f"{state}: объяснение, напоминания о входе нет (вход ничего не даст)")
    check("51" in tr("app.ext_unsupported_text", version="51"), "в тексте про версию GNOME есть сама версия")

    # О-М6: напоминание о входе не висит вечно: вход был (у GNOME Shell другое имя на шине), а дополнение молчит
    owner = {"v": ":1.10"}
    windows.shell_owner = lambda: owner["v"]
    gnome_ext.update = lambda version="": (gnome_ext.UPDATED, "")
    c.update_gnome_extension()
    check(c.config.get("gnome_ext_relogin") == ":1.10", "после «Обновить» запомнено, какой GNOME Shell был до входа")
    FakeLister.result = wl("ewmh", windows.EXT_OLD, False)
    alt_w(c)
    check(wait(lambda: c.selector is not None and c.selector.windows_state == "ready") and c.selector.window_ext_relogin,
          "тот же сеанс: напоминание «выйдите и войдите»")
    QTest.keyClick(c.selector, Qt.Key.Key_Escape)
    wait(lambda: c.selector is None)
    owner["v"] = ":1.99"   # новый вход в систему
    alt_w(c)
    check(wait(lambda: c.selector is not None and c.selector.windows_state == "ready") and not c.selector.window_ext_relogin
          and "gnome_ext_relogin" not in c.config, "вход был, дополнение всё равно молчит: снова кнопка «Обновить»")
    QTest.keyClick(c.selector, Qt.Key.Key_Escape)
    wait(lambda: c.selector is None)


for name, fn in list(globals().items()):
    if name.startswith("test_") and callable(fn):
        try:
            fn()
        except Exception as exc:   # noqa: BLE001
            import traceback
            traceback.print_exc()
            check(False, f"{name}: {type(exc).__name__}: {exc}")
print(f"ИТОГ: проверок {checks[0]}, провалено: {len(failures)}")
sys.exit(1 if failures else 0)
