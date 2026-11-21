# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""«Снимок окна» через настоящий QtDBus: WindowLister и WindowGrab ClipSD против поддельного GNOME Shell
(tests/okno_fake_shell.py) на своей частной шине. Пробы независимой проверки 1.33 (prov133/probes/okno: p01, p02,
p03), ставшие постоянным тестом:
- состояние дополнения: новое, старое (нет ListWindows), нет объекта, нет Shell;
- дополнение медлит (2,6 с): сначала временный неполный список «медленно», потом полный; окно не замирает (О-М2);
- содержимое окна приходит, временный PNG убран;
- настоящий Clipshot: Esc до ответа списка (объект списка удалён, О-М4); Esc во время GrabWindow и ответ позже 4 с:
  PNG с содержимым окна не остаётся в XDG_RUNTIME_DIR (О-М1); Ctrl+Enter ждёт содержимое; выбранное окно, затем
  «Весь экран»: в снимке только то, что было на экране (В5).

Шина своя (dbus-run-session с конфигом без запуска служб), шина человека не используется. Нужны dbus-run-session и
системный python3 с PyGObject; нет их: тест пропускается (SKIP), а не падает.
Запуск: QT_QPA_PLATFORM=offscreen python3 tests/vybor_okna_dbus_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SYS_PY = "/usr/bin/python3"

if os.environ.get("OKNO_DBUS_INNER") != "1":
    if not shutil.which("dbus-run-session") or not os.path.exists(SYS_PY) or subprocess.run(
            [SYS_PY, "-I", "-c", "from gi.repository import Gio, GLib"], capture_output=True).returncode != 0:
        print("SKIP: нет dbus-run-session или системного python3 с PyGObject")
        sys.exit(0)
    base = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    work = tempfile.mkdtemp(prefix="okd-", dir=base if len(base) < 60 else tempfile.gettempdir())
    conf = os.path.join(work, "bus.conf")
    with open(conf, "w", encoding="utf-8") as f:
        f.write(f"""<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-Bus Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig><type>session</type><listen>unix:tmpdir={work}</listen><auth>EXTERNAL</auth>
<policy context="default"><allow send_destination="*" eavesdrop="true"/><allow eavesdrop="true"/><allow own="*"/></policy>
</busconfig>
""")
    env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS")}
    env.update(OKNO_DBUS_INNER="1", OKNO_WORK=work, XDG_CURRENT_DESKTOP="ubuntu:GNOME", XDG_SESSION_TYPE="wayland")
    # своя домашняя папка: иначе состояние дополнения («нет» или «старое») зависит от дополнений настоящего пользователя
    # и свой XDG_RUNTIME_DIR: временные снимки окон и проверка «PNG не остался» не смешиваются с файлами ClipSD человека
    for key, sub in (("HOME", "home"), ("XDG_DATA_HOME", "data"), ("XDG_CONFIG_HOME", "config"), ("XDG_CACHE_HOME", "cache"),
                     ("XDG_RUNTIME_DIR", "run")):
        os.makedirs(os.path.join(work, sub), exist_ok=True)
        env[key] = os.path.join(work, sub)
    os.chmod(env["XDG_RUNTIME_DIR"], 0o700)
    rc = subprocess.run(["dbus-run-session", f"--config-file={conf}", "--", sys.executable, os.path.abspath(__file__)],
                        env=env, timeout=300).returncode
    sys.exit(rc)

# --- внутри частной шины -----------------------------------------------------------------------------------------
sys.path.insert(0, ROOT)
WORK = os.environ["OKNO_WORK"]
_cfg = os.path.join(WORK, "screen.json")
with open(_cfg, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "d", "x": 0, "y": 0, "width": 800, "height": 600, "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _cfg
os.environ.setdefault("CLIPSD_LANG", "ru")
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()

from pathlib import Path  # noqa: E402

from PyQt6.QtCore import QRect, Qt, QTimer  # noqa: E402
from PyQt6.QtDBus import QDBusConnection  # noqa: E402
from PyQt6.QtGui import QColor, QPainter, QPixmap  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
from clipshot import app as appmod, windows  # noqa: E402

failures = []
checks = [0]
RA, RB = QRect(100, 100, 300, 200), QRect(300, 150, 300, 220)
RED, BLUE = QColor("#d92d20"), QColor("#2a6df4")
SHELL = json.dumps({"monitors": [{"index": 0, "x": 0, "y": 0, "w": 800, "h": 600}],
                    "windows": [{"id": "a", "title": "Документ А", "app": "Редактор", "x": 100, "y": 100, "w": 300, "h": 200,
                                 "monitor": 0, "z": 0},
                                {"id": "b", "title": "Окно Б", "app": "Почта", "x": 300, "y": 150, "w": 300, "h": 220,
                                 "monitor": 0, "z": 1, "focused": True}]})


def check(cond, msg):
    checks[0] += 1
    print(("OK   " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


def wait(cond, seconds=5):
    end = time.monotonic() + seconds
    while not cond() and time.monotonic() < end:
        app.processEvents()
        QTest.qWait(10)
    return cond()


def solid(w, h, color):
    pm = QPixmap(w, h)
    pm.fill(color)
    return pm


PNG = os.path.join(WORK, "png")
os.makedirs(PNG, exist_ok=True)
solid(300, 200, RED).save(os.path.join(PNG, "a.png"))
solid(300, 220, BLUE).save(os.path.join(PNG, "b.png"))
solid(800, 600, QColor("#7fb2e5")).save(os.path.join(PNG, "desk.png"))


def desk():
    pm = QPixmap(800, 600)
    pm.fill(QColor("#7fb2e5"))
    p = QPainter(pm)
    p.fillRect(RA, RED)
    p.fillRect(RB, BLUE)
    p.end()
    return pm


def runtime_pngs():
    return sorted(n for n in os.listdir(RUNTIME) if n.startswith("clipshot-") and n.endswith(".png"))


class FakeShell:
    def __init__(self, mode="new", list_ms=0, grab_ms=None):
        env = dict(os.environ, FAKE_MODE=mode, FAKE_LIST_MS=str(list_ms), FAKE_GRAB_MS=json.dumps(grab_ms or {}),
                   FAKE_PNG_DIR=PNG, FAKE_WINDOWS=SHELL, FAKE_LOG=os.path.join(WORK, "fake.log"))
        self.proc = subprocess.Popen([SYS_PY, "-I", os.path.join(HERE, "okno_fake_shell.py")], env=env,
                                     stdout=subprocess.PIPE, text=True)
        line = self.proc.stdout.readline()
        if "READY" not in line:
            raise RuntimeError("поддельный Shell не поднялся")

    def stop(self):
        self.proc.terminate()
        self.proc.wait(5)
        bus = QDBusConnection.sessionBus().interface()
        wait(lambda: not bus.isServiceRegistered("org.gnome.Shell").value(), 3)


def lister_result(seconds=8):
    got = []
    lister = windows.WindowLister()
    lister.ready.connect(got.append)
    t0 = time.monotonic()
    lister.start()
    wait(lambda: bool(got) and got[-1].final, seconds)
    return got, time.monotonic() - t0


def test_states():
    for mode, want in (("new", windows.EXT_OK), ("old", windows.EXT_OLD), ("noobj", windows.EXT_MISSING),
                       ("none", windows.EXT_MISSING)):
        shell = FakeShell(mode)
        try:
            got, _t = lister_result()
            wl = got[-1] if got else None
            check(wl is not None and wl.ext_state == want, f"дополнение «{mode}»: состояние {wl and wl.ext_state}, ждали {want}")
            if mode == "new":
                check([w.id for w in wl.windows] == ["b", "a"] and wl.complete and wl.source == "gnome-ext",
                      "новое дополнение: полный список сверху вниз")
                res = []
                job = windows.WindowGrab(next(w for w in wl.windows if w.id == "a"))
                job.done.connect(res.append)
                job.start()
                wait(lambda: bool(res))
                pm = res[0] if res else None
                check(pm is not None and pm.width() == 300 and pm.toImage().pixelColor(5, 5) == RED and not runtime_pngs(),
                      "GrabWindow: содержимое окна пришло, временный PNG убран")
        finally:
            shell.stop()


def test_slow_list():
    shell = FakeShell("new", list_ms=2600)
    try:
        ticks = [0]
        tm = QTimer()
        tm.timeout.connect(lambda: ticks.__setitem__(0, ticks[0] + 1))
        tm.start(10)
        got, el = lister_result()
        tm.stop()
        check(len(got) == 2 and not got[0].final and got[0].ext_state == windows.EXT_SLOW,
              f"дополнение медлит: сначала временный список «медленно» ({[(w.final, w.ext_state) for w in got]})")
        check(got and got[-1].final and got[-1].ext_state == windows.EXT_OK and len(got[-1].windows) == 2,
              f"потом полный список от дополнения, через {el:.1f} с")
        check(ticks[0] > 100, f"окно не замирало, пока ждали ответ (тиков таймера {ticks[0]})")
    finally:
        shell.stop()


def test_desktop_grab_private_path():
    """Снимок стола через метод Grab дополнения: ClipSD просит записать файл в своей личной папке (XDG_RUNTIME_DIR 0700),
    имя с непредсказуемой частью; после чтения файла нет."""
    import re
    import stat
    from clipshot import grab
    log = os.path.join(WORK, "fake.log")
    start = os.path.getsize(log) if os.path.exists(log) else 0
    shell = FakeShell("new")
    try:
        res = []
        g = grab.DesktopGrabber()
        g.ready.connect(lambda pm: res.append(pm))
        g.failed.connect(lambda text: res.append(None))
        g.start()
        wait(lambda: bool(res), 6)
        with open(log, encoding="utf-8") as f:
            f.seek(start)
            paths = [ln.split("grab-path ", 1)[1].strip() for ln in f if "grab-path " in ln]
        path = paths[0] if paths else ""
        st = os.lstat(os.path.dirname(path)) if path else None
        check(res and res[0] is not None and res[0].width() == 800, "снимок стола пришёл через Grab дополнения")
        check(bool(path) and os.path.dirname(path) == RUNTIME and st is not None and not st.st_mode & 0o077
              and stat.S_ISDIR(st.st_mode), f"путь снимка в личной папке 0700 ({os.path.dirname(path)})")
        check(bool(re.fullmatch(r"clipshot-\d+-\d+-[0-9a-f]{8}\.png", os.path.basename(path))),
              f"в имени файла случайная часть ({os.path.basename(path)})")
        check(bool(path) and not os.path.exists(path), "после чтения временный файл снимка убран")
    finally:
        shell.stop()


def make_app():
    appmod.CONFIG_PATH = Path(tempfile.mkdtemp(prefix="okd-cfg-", dir=WORK)) / "config.json"
    appmod.is_wayland = lambda: False   # путь X11: кадр стола сразу (кадр подменён)
    appmod.grab_qt = desk
    appmod.virtual_geometry = lambda: QRect(0, 0, 800, 600)
    c = appmod.Clipshot(app)
    c.config.update(auto_save=False, theme_chosen=True, tour_done=True, tour_selector_done=True, remember_region=True,
                    last_region=[500, 450, 200, 100])
    copied = []
    c.copy_image = lambda img: copied.append(img)
    c.notify = lambda text: None
    return c, copied


def alt_w(c):
    c.last_trigger = 0.0
    c.capture_region()
    wait(lambda: c.selector is not None and c.selector.isVisible(), 3)
    return c.selector


def win(sel, i):
    return next(w for w in sel.windows if w.id == i)


def test_app_races():
    c, copied = make_app()
    # Esc до ответа списка (проба p03 esc_before_list)
    shell = FakeShell("new", list_ms=800)
    try:
        sel = alt_w(c)
        QTest.qWait(200)
        QTest.keyClick(sel, Qt.Key.Key_Escape)
        check(wait(lambda: c.selector is None, 2), "Esc до ответа списка: окно выделения закрыто")
        QTest.qWait(1200)
        app.processEvents()
        QTest.qWait(50)
        check(c.selector is None and not c.findChildren(windows.WindowLister),
              "поздний ответ отброшен, объект списка удалён (О-М4)")
    finally:
        shell.stop()

    # Esc во время GrabWindow (600 мс): PNG не остаётся (О-М1)
    shell = FakeShell("new", grab_ms={"a": 600})
    try:
        sel = alt_w(c)
        wait(lambda: sel.windows_state == "ready" and sel.window_grab is not None, 3)
        sel.pick_window(win(sel, "a"))
        QTest.qWait(100)
        QTest.keyClick(sel, Qt.Key.Key_Escape)
        wait(lambda: c.selector is None, 2)
        QTest.qWait(1200)
        app.processEvents()
        check(not runtime_pngs(), f"Esc во время GrabWindow: PNG с содержимым окна не остался ({runtime_pngs()})")
    finally:
        shell.stop()

    # GrabWindow дольше 4 с: Ctrl+Enter ждёт, снимок из кадра, файл, дописанный Shell позже, убран (О-М1)
    shell = FakeShell("new", grab_ms={"a": 5000})
    try:
        sel = alt_w(c)
        wait(lambda: sel.windows_state == "ready", 3)
        sel.pick_window(win(sel, "a"))
        t0 = time.monotonic()
        QTest.qWait(100)
        QTest.keyClick(sel, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        check(sel.pending is not None, "Ctrl+Enter до прихода содержимого: снимок ждёт его")
        wait(lambda: bool(copied), 7)
        el = time.monotonic() - t0
        check(copied and 3.5 < el < 5.5 and copied[-1].pixelColor(RB.left() - RA.left() + 20, RB.top() - RA.top() + 20) == BLUE,
              f"ответа нет 4 с: снимок из кадра, как на экране, через {el:.1f} с")
        QTest.qWait(3000)
        app.processEvents()
        check(not runtime_pngs(), f"файл, который Shell дописал позже, убран ({runtime_pngs()})")
    finally:
        shell.stop()

    # Обычный путь: окно А под окном Б снято целиком; затем «Весь экран»: в снимке как на экране (В5)
    shell = FakeShell("new")
    try:
        copied.clear()
        sel = alt_w(c)
        wait(lambda: sel.windows_state == "ready", 3)
        sel.pick_window(win(sel, "a"))
        wait(lambda: sel._lift is None, 3)
        QTest.keyClick(sel, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        check(wait(lambda: bool(copied), 3)
              and copied[-1].pixelColor(RB.left() - RA.left() + 20, RB.top() - RA.top() + 20) == RED and not runtime_pngs(),
              "окно А снято целиком (под окном Б его красное), PNG убран")
        copied.clear()
        sel = alt_w(c)
        wait(lambda: sel.windows_state == "ready", 3)
        sel.pick_window(win(sel, "a"))
        wait(lambda: sel._lift is None, 3)
        sel._do("full")
        QTest.keyClick(sel, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        check(wait(lambda: bool(copied), 3) and copied[-1].pixelColor(350, 250) == BLUE,
              "выбранное окно, затем «Весь экран»: в снимке окно Б сверху, как было на экране (В5)")
    finally:
        shell.stop()


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
