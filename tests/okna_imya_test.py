# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Список «Окна ▾»: понятно, какая это программа (замечание владельца 21.11.2026 по 1.33.0 на Windows).

Строка списка: значок программы и «Заголовок · Имя программы» (имя приглушённо), имя не повторяется, если оно уже
есть в заголовке. Проверяется без настоящего Windows, подменой:
- имя из описания файла программы (FileDescription, version.dll подменяется: перевод 0419, запасной 040904B0,
  ресурса версии нет);
- записи окон Windows: описание, имя exe с заглавной буквы, рамка магазинного приложения (ApplicationFrameHost)
  с найденной программой внутри и без неё;
- без дубля: «ClipSD - Google Chrome», «Отчёт.docx - Word», «Telegram (3)»; длинное имя обрезается;
- X11: имя и значок из файла .desktop по WM_CLASS (своя папка XDG_DATA_HOME), имя на языке ClipSD;
- меню: строки, хвост приглушённым цветом (свойство clipsd_tail), заголовок с именем не длиннее 72 знаков,
  значок из exe (подмена) и запасной квадрат с буквой; ширина меню на 12 языках;
- на настоящем Windows (CI windows.yml): описание и значок explorer.exe, список окон без ошибок.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/okna_imya_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import ctypes
import faulthandler
import json
import os
import sys
import tempfile
import traceback

# Тест идёт и на настоящем Windows (CI windows.yml). Там вывод в канал копится в буфере, а сообщения Qt уходят
# в OutputDebugString: при падении процесса в журнале не оставалось ни строки (CI 1.34.0). Строки сразу,
# при падении внутри ctypes или Qt печатается стек Python.
sys.stdout.reconfigure(line_buffering=True)
faulthandler.enable()

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
_cfg = os.path.join(tempfile.mkdtemp(prefix="clipsd-oknaimya-"), "screen.json")
with open(_cfg, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1600, "height": 1000,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
_cwd = os.getcwd()
if os.name == "nt":
    # Qt делит аргументы платформы двоеточием: «configfile=C:\Users\…» стал бы «configfile=C», и offscreen
    # завершал программу (qFatal «Could not find platform config file») до первой строки теста (CI 1.34.0).
    # Путь без буквы диска: папка файла текущая, пока создаётся QApplication.
    os.chdir(os.path.dirname(_cfg))
    os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + os.path.basename(_cfg)
else:
    os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _cfg
os.environ.pop("CLIPSD_LANG", None)   # тест сам перебирает языки
os.environ.pop("DBUS_SESSION_BUS_ADDRESS", None)   # никакой настоящей шины сеанса

from PyQt6.QtCore import QRect  # noqa: E402
from PyQt6.QtGui import QColor, QIcon, QPixmap  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
os.chdir(_cwd)
from clipshot import app as appmod, i18n, selector, windows  # noqa: E402
from clipshot.i18n import tr  # noqa: E402
from clipshot.selector import RegionSelector  # noqa: E402
from clipshot.windows import WindowList, WinInfo  # noqa: E402

i18n.set_language("ru", notify=False)

failures = []
checks = [0]


def check(cond, msg):
    checks[0] += 1
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def settle(n=3):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(10)


class FakeScreen:
    def __init__(self, x, y, w, h, dpr=1.0):
        self._g, self._d = QRect(x, y, w, h), dpr

    def geometry(self):
        return QRect(self._g)

    def devicePixelRatio(self):
        return self._d


# =================================================================================== FileDescription

class FakeVersionApi:
    """version.dll понарошку: ресурс версии с таблицами строк {"041904B0": "Проводник"} и списком переводов.
    Ответы VerQueryValueW лежат в настоящей памяти ctypes (как у Windows: указатель внутрь буфера и длина)."""

    def __init__(self, tables, translations=(), size=4096):
        self.tables, self.translations, self.size = tables, list(translations), size
        self.keep = []
        self.calls = []

    def GetFileVersionInfoSizeExW(self, flags, path, handle):
        self.calls.append(("size", flags, path))
        return self.size

    def GetFileVersionInfoExW(self, flags, path, _handle, size, buf):
        self.calls.append(("info", flags, path))
        return bool(self.size) and size == self.size

    def VerQueryValueW(self, _buf, sub, pptr, plen):
        if sub == "\\VarFileInfo\\Translation":
            if not self.translations:
                return False
            arr = (ctypes.c_uint16 * (2 * len(self.translations)))(*[x for pair in self.translations for x in pair])
            self.keep.append(arr)
            pptr._obj.value, plen._obj.value = ctypes.addressof(arr), ctypes.sizeof(arr)
            return True
        prefix, name = "\\StringFileInfo\\", "\\FileDescription"
        if sub.startswith(prefix) and sub.endswith(name):
            text = self.tables.get(sub[len(prefix):-len(name)].upper())
            if text is None:
                return False
            s = ctypes.create_unicode_buffer(text)
            self.keep.append(s)
            pptr._obj.value, plen._obj.value = ctypes.addressof(s), len(text) + 1
            return True
        return False


def fixed_drives(root):
    return windows.DRIVE_FIXED


def test_file_description():
    real_drive = windows._drive_type_win
    windows._drive_type_win = fixed_drives   # подмена GetDriveTypeW: все диски встроенные
    windows._drive_cache.clear()
    try:
        _file_description()
    finally:
        windows._drive_type_win = real_drive
        windows._drive_cache.clear()


def _file_description():
    windows._desc_cache.clear()
    api = FakeVersionApi({"041904B0": "Проводник", "040904B0": "Windows Explorer"}, [(0x0419, 0x04B0)])
    check(windows.file_description("C:\\Windows\\explorer.exe", api) == "Проводник",
          "описание exe: перевод из \\VarFileInfo\\Translation (0419 04B0), а не английский запасной")
    check(api.calls and all(c[1] == windows.FILE_VER_GET_LOCALISED for c in api.calls),
          "описание на языке Windows (FILE_VER_GET_LOCALISED)")
    n = len(api.calls)
    check(windows.file_description("c:\\windows\\EXPLORER.EXE", api) == "Проводник" and len(api.calls) == n,
          "второй раз из памяти (по пути без учёта регистра), файл не читается")
    windows._desc_cache.clear()
    api = FakeVersionApi({"040904B0": "  Microsoft   Word  "})
    check(windows.file_description("C:\\Office\\WINWORD.EXE", api) == "Microsoft Word",
          "нет списка переводов: запасной 040904B0, лишние пробелы убраны")
    windows._desc_cache.clear()
    check(windows.file_description("C:\\x\\noversion.exe", FakeVersionApi({}, size=0)) == "",
          "ресурса версии нет: пусто (покажется имя exe)")

    class Broken:
        def __getattr__(self, name):
            raise OSError("version.dll")
    windows._desc_cache.clear()
    check(windows.file_description("C:\\x\\broken.exe", Broken()) == "", "ошибка version.dll: пусто, без падения")
    check(windows.file_description("", api) == "", "пустой путь: пусто")
    windows._desc_cache.clear()


# =================================================================================== сетевые диски (В2 проверки 1.34.0)

def test_local_path():
    """Описание и значок exe читаются в потоке интерфейса: только с дисков этого компьютера. GetDriveTypeW подменён
    (Z: подключённый сетевой диск, D: CD, E: флешка), version.dll и QFileIconProvider с сетевого пути не вызываются."""
    types = {"C:\\": windows.DRIVE_FIXED, "Z:\\": windows.DRIVE_REMOTE, "D:\\": windows.DRIVE_CDROM,
             "E:\\": windows.DRIVE_REMOVABLE, "R:\\": windows.DRIVE_RAMDISK}
    asked = []

    def drive_type(root):
        asked.append(root)
        return types.get(root, 1)   # DRIVE_NO_ROOT_DIR

    def broken(root):
        raise OSError("kernel32")

    real_drive = windows._drive_type_win
    windows._drive_type_win = drive_type
    windows._drive_cache.clear()
    try:
        cases = [("C:\\Windows\\explorer.exe", True), ("c:/Program Files/x.exe", True), ("Z:\\apps\\tool.exe", False),
                 ("D:\\setup.exe", False), ("E:\\portable\\app.exe", True), ("R:\\x.exe", True),
                 ("Q:\\nodrive.exe", False), ("\\\\server\\share\\app.exe", False), ("//server/share/app.exe", False),
                 ("\\\\?\\UNC\\server\\share\\app.exe", False), ("\\\\?\\C:\\Windows\\notepad.exe", True),
                 ("app.exe", False), ("", False), ("C:app.exe", False)]
        for path, want in cases:
            got = windows.is_local_path(path)
            check(got == want, f"путь {path!r}: {'локальный' if want else 'не локальный'} ({got})")
        n = len(asked)
        windows.is_local_path("C:\\Other\\b.exe")
        check(len(asked) == n, "тип диска запоминается (GetDriveTypeW один раз на диск в минуту)")
        windows.is_local_path("C:\\Other\\b.exe", now=10 ** 9)
        check(len(asked) == n + 1, "через минуту тип диска спрашивается снова (диск могли переподключить)")

        windows._desc_cache.clear()
        api = FakeVersionApi({"040904B0": "Tool"})
        check(windows.file_description("Z:\\apps\\tool.exe", api) == "" and not api.calls,
              "сетевой диск Z:: описание не читается (version.dll не вызван), покажется имя exe")
        check(windows.file_description("\\\\server\\share\\tool.exe", api) == "" and not api.calls,
              "путь UNC: описание не читается")
        check(windows.file_description("C:\\apps\\tool.exe", api) == "Tool" and api.calls, "встроенный диск: описание читается")

        real_sys = selector.sys.platform   # _exe_icon работает только на Windows: на время проверки «Windows»
        touched = []
        import os.path as osp
        orig_isfile = osp.isfile
        osp.isfile = lambda p: touched.append(p) or False
        selector.sys.platform = "win32"
        try:
            selector._exe_icons.clear()
            check(selector._exe_icon("Z:\\apps\\tool.exe") is None and not touched,
                  "сетевой диск: значок не читается (файл не трогается), запасной квадрат с буквой")
            check(selector._exe_icon("\\\\server\\share\\tool.exe") is None and not touched, "UNC: значок не читается")
            selector._exe_icon("C:\\apps\\tool.exe")
            check(touched == ["C:\\apps\\tool.exe"], f"встроенный диск: значок из файла ({touched})")
        finally:
            selector.sys.platform = real_sys
            osp.isfile = orig_isfile
            selector._exe_icons.clear()

        windows._drive_type_win = broken
        windows._drive_cache.clear()
        check(windows.is_local_path("C:\\x.exe") is False, "ошибка GetDriveTypeW: как сетевой, без падения")
    finally:
        windows._drive_type_win = real_drive
        windows._drive_cache.clear()
        windows._desc_cache.clear()


# =================================================================================== записи Windows

def rec(hwnd, title, exe, **kw):
    r = {"hwnd": hwnd, "title": title, "exe": exe, "pid": hwnd, "visible": True, "exstyle": 0, "owner": False,
         "cloaked": False, "iconic": False, "foreground": False, "frame": (100, 100, 800, 600)}
    r.update(kw)
    return r


def test_win32_names():
    screens = [FakeScreen(0, 0, 1920, 1080)]
    recs = [rec(1, "Отчёт за ноябрь.docx - Word", "C:\\Office\\WINWORD.EXE", app_exe="C:\\Office\\WINWORD.EXE",
                desc="Microsoft Word"),
            rec(2, "Загрузки", "C:\\Windows\\explorer.exe", app_exe="C:\\Windows\\explorer.exe", desc="Проводник"),
            rec(3, "Telegram", "C:\\Users\\u\\AppData\\Roaming\\Telegram Desktop\\telegram.exe"),
            rec(4, "Калькулятор", "C:\\Windows\\System32\\ApplicationFrameHost.exe",
                app_exe="C:\\Program Files\\WindowsApps\\Calc\\CalculatorApp.exe", desc="Калькулятор Windows"),
            rec(5, "Параметры", "C:\\Windows\\System32\\ApplicationFrameHost.exe", app_exe="",
                desc="Application Frame Host"),
            rec(6, "Фото", "C:\\Windows\\System32\\ApplicationFrameHost.exe")]
    out = {w.id: w for w in windows.win32_records_to_list(recs, screens)}
    check(out["1"].app_name == "Microsoft Word" and out["1"].icon == "C:\\Office\\WINWORD.EXE",
          "Windows: имя из описания exe, значок из того же exe")
    check(windows.display_app(out["3"]) == "Telegram" and out["3"].app == "telegram",
          "Windows: описания нет: имя exe без расширения с заглавной буквы")
    check(out["4"].app_name == "Калькулятор Windows" and out["4"].icon.endswith("CalculatorApp.exe")
          and out["4"].app == "CalculatorApp", "рамка магазинного приложения: программа изнутри (CoreWindow)")
    check(out["5"].app_name == "" and out["5"].icon == "" and windows.display_app(out["5"]) == "",
          "рамка без найденной программы: ни «Application Frame Host», ни имени exe рамки")
    check(windows.display_app(out["6"]) == "" and out["6"].icon == "",
          "запись без app_exe (рамка): тоже без имени рамки")
    check(windows.display_app(WinInfo("x", "t", "WINWORD")) == "WINWORD", "имя exe с заглавными не меняется")


# =================================================================================== без дубля

def test_no_duplicate():
    cases = [("ClipSD - Google Chrome", "Google Chrome", ""),
             ("Отчёт за ноябрь.docx - Word", "Microsoft Word", ""),
             ("Telegram (3)", "Telegram Desktop", ""),
             ("Входящие - sergey@example.com - Outlook", "Microsoft Outlook", ""),
             ("Загрузки", "Проводник", "Проводник"),
             ("Новая вкладка", "Microsoft Edge", "Microsoft Edge"),
             ("Windows PowerShell", "Windows Terminal", "Windows Terminal"),
             ("Документ", "", ""),
             ("Документ", "Очень длинное имя программы для проверки обрезки",
              "Очень длинное имя программы для проверки обрезки"[:windows.APP_NAME_MAX - 1].rstrip() + "…")]
    for title, app_name, want in cases:
        got = windows.menu_app_name(title, app_name)
        check(got == want, f"«{title}» + «{app_name}» -> «{got}» (ждали «{want}»)")
    check(len(windows.menu_app_name("x", "Очень длинное имя программы для проверки обрезки")) <= windows.APP_NAME_MAX,
          "длинное имя программы не длиннее APP_NAME_MAX")


# =================================================================================== X11: .desktop

def test_desktop_lookup():
    data = tempfile.mkdtemp(prefix="clipsd-desk-")
    appdir = os.path.join(data, "applications")
    os.makedirs(appdir)
    with open(os.path.join(appdir, "org.example.Notes.desktop"), "w", encoding="utf-8") as f:
        f.write("[Desktop Entry]\nType=Application\nName=Notes\nName[ru]=Заметки\nName[de_DE]=Notizen\n"
                "Icon=org.example.Notes\nStartupWMClass=notes-app\n\n[Desktop Action new]\nName=New note\n")
    with open(os.path.join(appdir, "gimp.desktop"), "w", encoding="utf-8") as f:
        f.write("[Desktop Entry]\nType=Application\nName=GNU Image Manipulation Program\nIcon=/opt/gimp.png\n")
    with open(os.path.join(appdir, "hidden.desktop"), "w", encoding="utf-8") as f:
        f.write("[Desktop Entry]\nType=Application\nName=Hidden\nHidden=true\nStartupWMClass=hiddenapp\n")
    old = {k: os.environ.get(k) for k in ("XDG_DATA_HOME", "XDG_DATA_DIRS")}
    os.environ["XDG_DATA_HOME"] = data
    os.environ["XDG_DATA_DIRS"] = os.path.join(data, "none")
    windows._desktop_cache["key"] = None
    try:
        i18n.set_language("ru")
        check(windows.desktop_app(("notes-app", "Notes-app")) == ("Заметки", "org.example.Notes"),
              "X11: по StartupWMClass имя на языке ClipSD и значок")
        i18n.set_language("de")
        check(windows.desktop_app(("notes-app", "Notes-app"))[0] == "Notizen", "X11: Name[de_DE] для немецкого")
        i18n.set_language("fr")
        check(windows.desktop_app(("notes-app", "Notes-app"))[0] == "Notes", "X11: перевода нет: Name")
        i18n.set_language("ru")
        check(windows.desktop_app(("gimp-2.10", "Gimp"))[0] == "GNU Image Manipulation Program",
              "X11: по имени файла .desktop (WM_CLASS class)")
        check(windows.desktop_app(("org.example.notes", ""))[0] == "Заметки", "X11: по имени файла целиком")
        check(windows.desktop_app(("hiddenapp", "Hiddenapp")) == ("", ""), "X11: скрытый .desktop не берётся")
        check(windows.desktop_app(("xterm", "XTerm")) == ("", ""), "X11: нет файла: пусто (покажется WM_CLASS)")
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        windows._desktop_cache["key"] = None
        i18n.set_language("ru")


# =================================================================================== меню

W, H = 1600, 1000


def make_selector(wins, source="win32"):
    pm = QPixmap(W, H)
    pm.fill(QColor("#7fb2e5"))
    sel = RegionSelector(pm, QRect(0, 0, W, H), show_zoom=False, show_size=True)
    cfg = dict(appmod.DEFAULTS)
    sel.tr_cfg, sel.tr_save = cfg, (lambda: None)
    sel.lang_ctx = type("C", (), {"config": cfg, "set_language": lambda *a: None})()
    sel.windows_state = "loading"
    sel.window_grab = None
    sel.set_windows(WindowList(wins, source, True))
    sel.resize(W, H)
    return sel


def sample_windows(long_title=False):
    t = "Квартальный отчёт по продажам тёплых полов в Варне и по всей Болгарии, версия для бухгалтерии и склада.docx"
    return [WinInfo("1", (t if long_title else "Отчёт за ноябрь.docx") + " - Word", "WINWORD",
                    icon="C:\\Office\\WINWORD.EXE", rect=QRect(100, 100, 900, 600), z=5, source="win32",
                    app_name="Microsoft Word"),
            WinInfo("2", "ClipSD - Google Chrome", "chrome", icon="C:\\Chrome\\chrome.exe",
                    rect=QRect(300, 120, 900, 600), z=4, source="win32", app_name="Google Chrome"),
            WinInfo("3", "Загрузки", "explorer", icon="C:\\Windows\\explorer.exe", rect=QRect(200, 200, 700, 500),
                    z=3, source="win32", app_name="Проводник"),
            WinInfo("4", t if long_title else "Квартальный отчёт", "telegram", icon="C:\\T\\telegram.exe",
                    rect=QRect(1000, 300, 500, 600), z=2, source="win32", monitor=1 if long_title else 0),
            WinInfo("5", "Калькулятор", "", rect=QRect(50, 50, 300, 400), z=1, source="win32")]


def placeholder(color):
    pm = QPixmap(48, 48)
    pm.fill(QColor(color))
    return QIcon(pm)


def test_menu_rows():
    real = selector._exe_icon
    icons = {"C:\\Office\\WINWORD.EXE": placeholder("#2b579a"), "C:\\Chrome\\chrome.exe": placeholder("#34a853")}
    selector._exe_icon = lambda path: icons.get(path)
    try:
        sel = make_selector(sample_windows())
        menu = sel._window_menu()
        acts = [a for a in menu.actions() if a.data() is not None]
        texts = [a.text() for a in acts]
        want = ["Отчёт за ноябрь.docx - Word", "ClipSD - Google Chrome", "Загрузки · Проводник",
                "Квартальный отчёт · Telegram", "Калькулятор"]
        check(texts == want, f"строки меню: имя программы после заголовка, без дублей ({texts})")
        check([a.property("clipsd_tail") for a in acts] == [None, None, " · Проводник", " · Telegram", None],
              "хвост с именем программы отмечен для приглушённого цвета")
        word = acts[0].icon().pixmap(40, 40).toImage().pixelColor(20, 20)
        check(word == QColor("#2b579a"), f"значок из exe (подмена QFileIconProvider): {word.name()}")
        letter = acts[2].icon().pixmap(40, 40).toImage().pixelColor(4, 20)
        check(letter == QColor("#eceef2"), f"значка нет: серый квадрат с буквой ({letter.name()})")
        menu.deleteLater()
        sel.deleteLater()
    finally:
        selector._exe_icon = real

    sel = make_selector(sample_windows(long_title=True))
    menu = sel._window_menu()
    acts = [a for a in menu.actions() if a.data() is not None]
    labels = [a.text().split("\t")[0].replace("&&", "&") for a in acts]
    check(all(len(t) <= 72 for t in labels), f"заголовок с именем программы не длиннее 72 знаков ({[len(t) for t in labels]})")
    tg = labels[[x.data() for x in acts].index("4")]
    check(tg.endswith(" · Telegram") and "…" in tg, f"длинный заголовок обрезан, имя программы осталось ({tg})")
    check(acts[0].text().split("\t")[0].endswith("…"), "длинный заголовок без имени программы тоже обрезан")
    menu.deleteLater()
    sel.deleteLater()


def test_menu_tail_paint():
    """Хвост рисуется приглушённым цветом пункта-пояснения, заголовок обычным."""
    from clipshot.menus import ClipMenuStyle
    sel = make_selector([WinInfo("3", "Загрузки", "explorer", rect=QRect(200, 200, 700, 500), z=3, source="win32",
                                 app_name="Проводник")])
    menu = sel._window_menu()
    menu.ensurePolished()
    menu.adjustSize()
    menu.show()
    settle()
    img = menu.grab().toImage()
    style = menu.style()
    colors = set()
    for x in range(img.width()):
        for y in range(img.height()):
            c = img.pixelColor(x, y)
            if c.alpha() == 255:
                colors.add((c.red(), c.green(), c.blue()))
    note = style.note if isinstance(style, ClipMenuStyle) else None
    text = style.text if isinstance(style, ClipMenuStyle) else None
    check(note is not None and (note.red(), note.green(), note.blue()) in colors,
          "хвост нарисован цветом пояснения (приглушённо, читаемо)")
    check(text is not None and (text.red(), text.green(), text.blue()) in colors, "заголовок обычным цветом текста")
    menu.close()
    menu.deleteLater()
    sel.deleteLater()


def test_menu_width_languages():
    worst, wide_rows, bound, scale = {}, {}, {}, {}
    for lang in i18n.LANGUAGES:
        i18n.set_language(lang)
        sel = make_selector(sample_windows(long_title=True))
        menu = sel._window_menu()
        menu.ensurePolished()
        worst[lang] = menu.sizeHint().width()
        # ширина каждой строки тем шрифтом, которым рисует меню (ClipMenuStyle), и самая длинная строка
        from PyQt6.QtGui import QFont, QFontMetrics
        from clipshot.menus import FONT_PX
        f = QFont(menu.font())
        f.setPixelSize(FONT_PX)
        fm = QFontMetrics(f)
        rows = [(fm.horizontalAdvance(a.text().split("\t")[0].replace("&&", "&")), a.text()) for a in menu.actions()
                if a.data() is not None]
        widest = max(rows) if rows else (0, "")
        wide_rows[lang] = widest[0]
        # ширина меню по тем же меркам шрифта, как её считает ClipMenuStyle.sizeFromContents: подпись, правая
        # колонка («Экран 2», «свёрнуто»), значок и поля. Не шире этого: меню не добавляет ничего своего
        from clipshot.menus import MARGIN, PAD_H
        expect = 0
        for a in menu.actions():
            if a.data() is None:
                continue
            label, _sep, right = a.text().replace("&&", "&").partition("\t")
            expect = max(expect, 2 * PAD_H + 48 + 14 + fm.horizontalAdvance(label)
                         + (28 + fm.horizontalAdvance(right) if right else 0))
        # и колонка сочетаний самого QMenu (tabWidth): Qt прибавляет её к ширине пункта шрифтом меню
        tab = max((QFontMetrics(menu.font()).horizontalAdvance(a.text().partition("\t")[2]) for a in menu.actions()
                   if a.data() is not None), default=0)
        bound[lang] = expect + tab + 2 * MARGIN + 2
        scale[lang] = fm.horizontalAdvance("x" * 10)
        print(f"     {lang}: меню {worst[lang]} (по меркам шрифта {bound[lang]}, «x»*10 = {scale[lang]}), "
              f"строки {[w for w, _t in rows]}, самая длинная {widest[0]}: {widest[1]!r}")
        menu.deleteLater()
        sel.deleteLater()
    i18n.set_language("ru")
    from PyQt6.QtGui import QFontInfo
    print(f"     шрифт меню: {QFontInfo(QApplication.font()).family()}")
    check(all(w <= 480 for w in wide_rows.values()), f"строка меню не шире 480 точек тем же шрифтом ({wide_rows})")
    check(all(worst[k] <= bound[k] for k in worst), f"меню не шире, чем дают подпись и правая колонка ({worst} / {bound})")
    # 900 точек: при обычных шрифтах (десять «x» не шире 100 точек при 14 px). На CI Windows offscreen идёт без
    # шрифтов Qt («Cannot find font directory»), буквы там вдвое шире, и абсолютный предел ничего не говорит
    normal = [k for k in worst if scale[k] <= 100]
    if len(normal) < len(worst):
        print(f"SKIP меню не шире 900 точек: шрифт без настоящих мерок (десять «x» = {max(scale.values())} точек)")
    check(all(worst[k] <= 900 for k in normal), f"меню не шире 900 точек на 12 языках ({worst})")
    check(len(worst) == 12, "12 языков")


# =================================================================================== настоящий Windows

def test_real_windows():
    if sys.platform != "win32":
        print("SKIP настоящий Windows: только в CI windows.yml")
        return
    explorer = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "explorer.exe")
    windows._desc_cache.clear()
    desc = windows.file_description(explorer)
    check(bool(desc) and desc.lower() != "explorer", f"Windows: описание explorer.exe ({desc!r})")
    # значок файла даёт тема платформы windows (SHGetFileInfo); у offscreen её нет: значок в отдельном процессе
    import subprocess
    code = ("import sys; from PyQt6.QtWidgets import QApplication; a = QApplication(sys.argv); "
            "from clipshot import selector; i = selector._exe_icon(sys.argv[1]); "
            "print('ICON', i is not None and not i.isNull() and not i.pixmap(32, 32).isNull())")
    env = dict(os.environ, QT_QPA_PLATFORM="windows", PYTHONPATH=os.path.dirname(here))
    try:
        r = subprocess.run([sys.executable, "-c", code, explorer], env=env, capture_output=True, text=True,
                           timeout=60)
        out = r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        out = "timeout"
    if "ICON" not in out and "platform plugin" in out:
        print(f"SKIP значок explorer.exe: платформа windows не запустилась ({out.strip()[-200:]})")
    else:
        check("ICON True" in out, f"Windows: значок explorer.exe из exe ({out.strip()[-200:]})")
    try:
        wins = windows.from_win32() or []
        check(True, f"Windows: список окон получен ({len(wins)} окон)")
        for w in wins:
            selector.RegionSelector._app_badge(w)
        check(True, "Windows: значки всех окон списка без ошибок")
    except Exception as exc:   # noqa: BLE001
        check(False, f"Windows: список окон упал: {type(exc).__name__}: {exc}")


print(f"платформа Qt: {app.platformName()}, экран {app.primaryScreen().geometry().width()}x"
      f"{app.primaryScreen().geometry().height()}, {sys.platform}")
for part in (test_file_description, test_local_path, test_win32_names, test_no_duplicate, test_desktop_lookup, test_menu_rows,
             test_menu_tail_paint, test_menu_width_languages, test_real_windows):
    try:
        part()
    except Exception as exc:   # noqa: BLE001 (исключение видно в журнале CI, остальные части идут дальше)
        traceback.print_exc(file=sys.stdout)
        check(False, f"{part.__name__}: исключение {type(exc).__name__}: {exc}")
check(app.primaryScreen().geometry().width() == 1600, "экран теста из файла настроек offscreen (1600 точек)")
faulthandler.disable()   # на Windows он печатает и обработанные исключения при выгрузке Qt: не при выходе
print(f"ИТОГ: проверок {checks[0]}, провалено: {len(failures)}")
sys.exit(1 if failures else 0)
