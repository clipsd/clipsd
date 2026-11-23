# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Колокольчик об обновлении загорается быстро (1.36, слова владельца 23.11.2026).

Проверка канала раз в 6 часов; при запуске, если прошло больше 6 часов; после сна (скачок часов); при открытии
колокольчика, если последняя проверка старше 30 минут. Точка горит, как только канал показал версию, независимо
от недельного правила окна-предложения; пропущенная версия точку не зажигает. Список в открытом колокольчике
дополняется без переоткрытия. Сеть подменена, часы подставные.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/kolokolchik_obnovlenie_test.py
"""
import tmpclean  # noqa: F401
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

here = os.path.dirname(os.path.abspath(__file__))
project = os.path.dirname(here)
tmp = Path(tempfile.mkdtemp(prefix="clipsd-kolok-"))
for name, sub in (("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"), ("XDG_STATE_HOME", "state"),
                  ("XDG_CACHE_HOME", "cache"), ("CLIPSD_DATA_DIR", "clipsd-data")):
    os.environ[name] = str(tmp / sub)
(tmp / "runtime").mkdir(mode=0o700)
os.environ["XDG_RUNTIME_DIR"] = str(tmp / "runtime")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, project)
sys.path.insert(0, os.path.join(project, "tools"))

from PyQt6.QtCore import QPoint, QTimer  # noqa: E402
from PyQt6.QtGui import QColor, QImage  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

qapp = QApplication(sys.argv)

import channel_sign as cs  # noqa: E402
from clipshot import __version__, app as appmod, i18n, notifications, themes  # noqa: E402
from clipshot import updater as up  # noqa: E402
from clipshot.editor import EditorWindow  # noqa: E402

i18n.set_language("ru")
failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


keys = tmp / "keys"
STABLE_PUB = cs.keygen(keys / "stable.k")
PRIV = cs.load_private(keys / "stable.k")
NOW = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
INSTALLED = "2.0.0"


def document(version):
    return cs.dump({"schema": 1, "channel": "stable", "version": version, "released": cs.utc(NOW - timedelta(days=1)),
                    "expires": cs.utc(NOW + timedelta(days=90)),
                    "files": {p: {"url": f"https://github.com/ClipSD/ClipSD/releases/download/v{version}/f-{p}",
                                  "size": 10, "sha256": "0" * 64} for p in ("windows", "linux")},
                    "notes": {"en": f"# {version}\n- notes", "ru": f"# {version}\n- заметки"}})


class Channel:
    def __init__(self, version="2.0.1"):
        self.requests = 0
        self.publish(version)

    def publish(self, version):
        self.doc = document(version)
        self.sig = cs.sign_bytes(PRIV, self.doc)

    def __call__(self, url, limit):
        if not url.endswith(".sig"):
            self.requests += 1   # запрос документа; подпись к нему не считается отдельным запросом
        return self.sig if url.endswith(".sig") else self.doc


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class UI:
    def __init__(self):
        self.offers = []

    def offer(self, manifest, installed, critical=False):
        self.offers.append(manifest.version)
        return "later"

    def manual_install(self, version):
        pass

    def whats_new(self, version, markdown):
        pass

    def info(self, text):
        pass

    def error(self, text):
        pass

    def progress_start(self, *a):
        pass

    def progress_update(self, *a):
        pass

    def progress_close(self):
        pass

    def open_url(self, url):
        pass


class Ctx:
    def __init__(self, **config):
        self.config = dict(config)
        self.saved = 0

    def save_config(self):
        self.saved += 1

    def notify(self, text):
        pass


def make(config=None, installed=INSTALLED, version="2.0.1"):
    ctx, ui, ch, clock = Ctx(**(config or {})), UI(), Channel(version), Clock(NOW)
    u = up.Updater(ctx, fetch=ch, clock=clock, kind="linux", installed=installed, ui=ui, sync=True,
                   stable_keys=[STABLE_PUB], test_keys=[])
    return u, ctx, ui, ch, clock


H = timedelta(hours=1)
# --- 1. интервал 6 часов -----------------------------------------------------------------------------------
check(up.CHECK_INTERVAL == timedelta(hours=6), "интервал тихой проверки: 6 часов")
cfg = {}
up.mark_checked(cfg, NOW)
check(not up.should_check(cfg, NOW + 5 * H + timedelta(minutes=59)), "через 5 ч 59 мин рано")
check(up.should_check(cfg, NOW + 6 * H), "через 6 часов пора")
check(up.next_check_delay_ms(cfg, NOW + 5 * H) <= H.total_seconds() * 1000 + 1, "таймер: до проверки не больше часа")

# --- 2. запуск: проверка, если прошло больше 6 часов, и не раньше ------------------------------------------
cfg_old = {"last_update_check": up.uc.format_utc(NOW - 7 * H)}
check(up.next_check_delay_ms(cfg_old, NOW) == up.STARTUP_DELAY_MS, "запуск после 7 часов: проверка через 60 с")
cfg_new = {"last_update_check": up.uc.format_utc(NOW - 5 * H)}
check(up.next_check_delay_ms(cfg_new, NOW) > up.STARTUP_DELAY_MS, "запуск после 5 часов: проверка позже")
u, ctx, ui, ch, clock = make(cfg_new)
u.tick()
check(ch.requests == 0, "тик через 5 часов: запроса нет")
clock.now = NOW + 2 * H   # с прошлой проверки 7 часов
u.tick()
check(ch.requests == 1, "тик через 7 часов: один запрос к каналу")

# --- 3. колокольчик: проверка при открытии после 30+ минут ------------------------------------------------
u, ctx, ui, ch, clock = make({"last_update_check": up.uc.format_utc(NOW - timedelta(minutes=29))})
check(not u.bell_check() and ch.requests == 0, "колокольчик через 29 минут: запроса нет")
clock.now = NOW + timedelta(minutes=2)   # 31 минута
check(u.bell_check() and ch.requests == 1, "колокольчик через 31 минуту: тихая проверка")
check(not u.bell_check() and ch.requests == 1, "сразу повторное открытие: запроса нет")
u, ctx, ui, ch, clock = make({"update_check": False})
check(not u.bell_check() and ch.requests == 0, "проверка выключена в настройках: колокольчик в сеть не ходит")
u, ctx, ui, ch, clock = make()
u.busy = True
check(not u.bell_check(), "идёт загрузка или проверка: второй запрос не начинается")

# --- 4. точка после ответа канала, несмотря на недельное правило окна ---------------------------------------
u, ctx, ui, ch, clock = make({"update_last_notified": up.uc.format_utc(NOW - timedelta(days=1))})
check(not notifications.unread(ctx.config, INSTALLED), "до проверки точки нет")
check(not up.should_notify(ctx.config, "2.0.1", NOW), "окно-предложение подавлено недельным правилом")
check(u.check_now(manual=False), "тихая проверка начата")
check(ctx.config.get("update_last_seen_version") == "2.0.1", "канал показал версию: она записана")
check(any(it["id"] == "update:2.0.1" for it in notifications.unread(ctx.config, INSTALLED)),
      "точка горит, пока окно подавлено")
check(ui.offers == [], "окно-предложение не показано: правила окна не тронуты")

u, ctx, ui, ch, clock = make({"update_skipped": ["2.0.1"]})
u.check_now(manual=False)
check(ctx.config.get("update_last_seen_version") == "2.0.1" and not notifications.unread(ctx.config, INSTALLED),
      "пропущенная версия: точка не зажигается")
u, ctx, ui, ch, clock = make({"update_skipped": ["2.0.1"]})
ch.publish("2.0.2")
u.check_now(manual=False)
check(any(it["id"] == "update:2.0.2" for it in notifications.unread(ctx.config, INSTALLED)),
      "пропущена 2.0.1, вышла 2.0.2: точка горит")

# слушатель колокольчика зовётся, когда пришёл ответ (в том числе при ручной проверке из меню значка)
calls = []


def on_change():
    calls.append(1)


notifications.listen(on_change)
u, ctx, ui, ch, clock = make()
u.check_now(manual=True)
check(len(calls) >= 1 and any(it["id"] == "update:2.0.1" for it in notifications.unread(ctx.config, INSTALLED)),
      "«Проверить обновления» из меню значка: колокольчик перерисован, точка горит")

# --- 5. после сна ------------------------------------------------------------------------------------------
fired = []
real_single = up.QTimer.singleShot
up.QTimer.singleShot = staticmethod(lambda ms, fn: fired.append((ms, fn)))
try:
    u, ctx, ui, ch, clock = make({"last_update_check": up.uc.format_utc(NOW)})
    u._wake_seen = clock()
    clock.now = NOW + 2 * H   # проспали 2 часа: сон замечен, но 6 часов с проверки ещё не прошло
    check(u.wake_tick() is True and not fired, "сон 2 часа: замечен, но с прошлой проверки меньше 6 часов, запроса нет")
    clock.now = NOW + 2 * H + timedelta(minutes=1)
    check(u.wake_tick() is False and not fired, "обычный ход часов: сна нет")
    clock.now = NOW + 9 * H   # проспали ещё 7 часов
    check(u.wake_tick() is True and len(fired) == 1 and fired[0][0] == up.WAKE_DELAY_MS,
          "сон, после которого прошло больше 6 часов: проверка запланирована с паузой на сеть")
    fired[0][1]()
    check(ch.requests == 1, "после паузы тик спрашивает канал")
finally:
    up.QTimer.singleShot = real_single


# --- 6. список обновляется в открытом колокольчике ---------------------------------------------------------
class ECtx(Ctx):
    def __init__(self, **kw):
        super().__init__(**dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True, **kw))
        self.icon = appmod.make_icon()


ectx = ECtx(last_update_check=up.uc.format_utc(datetime.now(timezone.utc) - timedelta(hours=1)))
themes.apply_app(qapp, ectx.config)
ech = Channel("99.0.0")
eu = up.Updater(ectx, fetch=ech, kind="linux", installed=__version__, ui=UI(), sync=True,
                stable_keys=[STABLE_PUB], test_keys=[])
ectx._updater = eu
img = QImage(300, 220, QImage.Format.Format_RGB32)
img.fill(QColor("#ffffff"))
ed = EditorWindow(img, ectx, QPoint(0, 0))
ed.present()
qapp.processEvents()
check(not any(it["kind"] == "update" for it in notifications.unread(ectx.config)), "редактор: об обновлении точки нет")
menu = ed.build_notifications_menu()
menu.popup(QPoint(50, 50))
qapp.processEvents()
check(menu.isVisible() and not any(k.startswith("update:") for k in ed.notice_rows),
      "колокольчик открыт, пункта «Доступна версия» нет")
check(eu.bell_check() and ech.requests == 1, "открытие колокольчика: проверка (последняя была час назад)")
qapp.processEvents()
check("update:99.0.0" in ed.notice_rows and ed.notice_rows["update:99.0.0"].action_button is not None,
      "в открытом списке появился пункт «Доступна версия 99.0.0» с кнопкой «Обновить»")
check(any(it["kind"] == "update" for it in notifications.unread(ectx.config)) and ed.bell_button.unread >= 1,
      "точка на колокольчике горит")
menu.close()
# show_notifications сам зовёт проверку: с прошлой прошло 45 минут
ectx.config["last_update_check"] = up.uc.format_utc(datetime.now(timezone.utc) - timedelta(minutes=45))
QTimer.singleShot(300, lambda: ed._notices_menu.close())
before = ech.requests
ed.show_notifications()
check(ech.requests == before + 1, "show_notifications: после 45 минут тихая проверка")
ed.canvas.modified, ed.exported = False, True
ed.close()

print(f"\nИТОГ: {'ВСЁ ХОРОШО' if not failures else 'ПРОВАЛОВ: ' + str(len(failures))}")
sys.exit(1 if failures else 0)
