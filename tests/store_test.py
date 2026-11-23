# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Microsoft Store build (MSIX): kind of the build, no self-updates, Store page, start at login (StartupTask),
settings window, texts in 12 languages, the package layout (manifest, images, strings), staging, release check.

Runs on Linux and Windows without a package: the package identity and the StartupTask are replaced by fakes
(store.package_full_name, store._backend). Inside a real package: packaging/windows-store/store_test.ps1 (CI).
Nothing outside temporary folders is written.

Run: QT_QPA_PLATFORM=offscreen python3 tests/store_test.py [project] [output folder]
"""

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

here = os.path.dirname(os.path.abspath(__file__))
project = Path(sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(here)).resolve()
out = Path(sys.argv[2] if len(sys.argv) > 2 else os.path.join(here, "output", "store"))
out.mkdir(parents=True, exist_ok=True)
tmp = Path(tempfile.mkdtemp(prefix="clipsd-store-test-"))
for var, sub in (("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"), ("XDG_STATE_HOME", "state"),
                 ("XDG_CACHE_HOME", "cache"), ("LOCALAPPDATA", "localappdata"), ("APPDATA", "appdata")):
    os.environ[var] = str(tmp / sub)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(project))
sys.path.insert(0, str(project / "tools"))
sys.path.insert(0, str(project / "packaging"))
sys.path.insert(0, str(project / "packaging" / "windows-store"))

from PyQt6.QtGui import QImage  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

qapp = QApplication(sys.argv)

from clipshot import __version__, build_info, store, updater  # noqa: E402
from clipshot import i18n  # noqa: E402
from clipshot.i18n import tr  # noqa: E402

failures = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


class Backend:
    """StartupTask stand-in: state, and what RequestEnableAsync / Disable lead to."""

    def __init__(self, state="disabled", on_enable="enabled"):
        self.current, self.on_enable, self.calls = state, on_enable, []

    def state(self):
        self.calls.append("state")
        return self.current

    def enable(self):
        self.calls.append("enable")
        if self.current not in ("disabled_by_user", "disabled_by_policy", "enabled_by_policy"):
            self.current = self.on_enable
        return self.current

    def disable(self):
        self.calls.append("disable")
        if self.current not in ("disabled_by_policy", "enabled_by_policy"):
            self.current = "disabled" if self.current != "disabled_by_user" else self.current
        return self.current


real_full_name, real_family_name = store.package_full_name, store.package_family_name


def set_store(on: bool, product: str = "", packaged: bool = False, backend=None):
    build_info.STORE = on
    build_info.STORE_PRODUCT_ID = product if on else ""
    store.package_full_name = (lambda: "ClipSD.Test_1.31.2.0_x64__abcdefghjkmnp") if packaged else (lambda: "")
    store.package_family_name = (lambda: "ClipSD.Test_abcdefghjkmnp") if packaged else (lambda: "")
    store._backend = backend


# --- 1. kind of the build -------------------------------------------------------------------------------
check(build_info.STORE is False and build_info.kind() == "release", "репозиторий: обычная сборка (нет _store_build.py)")
check(not (project / "clipshot" / "_store_build.py").exists(), "clipshot/_store_build.py не лежит в исходниках")
set_store(True, "9NABCDEF1234")
check(build_info.is_store() and build_info.kind() == "store", "Store: вид сборки store")
check(build_info.version_label("1.31.2") == "1.31.2 · Microsoft Store", "Store: версия с пометкой Microsoft Store")
check(build_info.store_product_id() == "9NABCDEF1234", "Store: Store ID из модуля сборки")
set_store(False)
check(build_info.version_label("1.31.2") == "1.31.2", "обычная сборка: версия без пометки")

# --- 2. package identity outside a package (real API on Windows, nothing elsewhere) --------------------------
check(real_full_name() == "" and real_family_name() == "", "без пакета: нет имени пакета (GetCurrentPackageFullName)")
check(not store.has_package_identity(), "без пакета: has_package_identity() = False")
check(store.startup_state() == store.UNAVAILABLE, "без пакета: StartupTask недоступна")
try:
    store.set_startup(True)
    check(False, "без пакета: set_startup отказывает")
except store.StartupError as exc:
    check(exc.state == store.UNAVAILABLE, "без пакета: set_startup отказывает (unavailable)")
check(store.selfcheck_lines() == ["package: none"], "selfcheck без пакета: 'package: none'")
check(updater.install_kind() == "dev", "из исходников и без пакета: вид установки dev, как раньше")

# --- 3. Store page ----------------------------------------------------------------------------------------
set_store(True, "9NABCDEF1234")
check(store.store_url() == "ms-windows-store://pdp/?productid=9NABCDEF1234", "страница в Store по Store ID")
set_store(True, "", packaged=True)
check(store.store_url() == "ms-windows-store://pdp/?PFN=ClipSD.Test_abcdefghjkmnp",
      "Store ID ещё нет: страница по имени семейства пакета")
set_store(True, "")
check(store.store_url() == "", "ни Store ID, ни пакета: адреса нет (кнопка откроет сайт)")
set_store(False, packaged=True, backend=Backend())
check(store.is_store_build() and updater.install_kind() == "store", "пакет без пометки сборки: всё равно store")
check(store.selfcheck_lines() == ["package: ClipSD.Test_1.31.2.0_x64__abcdefghjkmnp", "startup task: disabled"],
      "selfcheck в пакете: имя пакета и состояние автозапуска")
set_store(False)


# --- 4. updater: no channel, no install, the button opens the Store ----------------------------------------
class Ctx:
    def __init__(self, config=None):
        self.config = dict(config or {})
        self.saved = 0

    def save_config(self):
        self.saved += 1


class UI:
    def __init__(self):
        self.urls, self.infos, self.errors, self.offers = [], [], [], []

    def open_url(self, url):
        self.urls.append(url)

    def info(self, text):
        self.infos.append(text)

    def error(self, text):
        self.errors.append(text)

    def offer(self, *a, **k):
        self.offers.append(a)
        return "later"

    def whats_new(self, *a):
        self.infos.append(("whats_new",) + a)

    def __getattr__(self, name):   # any other window: recorded as an info
        return lambda *a, **k: self.infos.append((name,) + a)


def no_fetch(*a, **k):
    raise AssertionError("Store build asked the update channel")


set_store(True, "9NABCDEF1234")
check(updater.install_kind() == "store", "Store-сборка: вид установки store")
ctx, ui = Ctx({"update_check": True, "last_update_check": ""}), UI()
u = updater.Updater(ctx, fetch=no_fetch, ui=ui, sync=True)
check(u.kind == "store", "Updater сам берёт вид store")
u.tick()
check(not ui.urls and not ui.offers and not ui.errors, "Store: проверка по расписанию ничего не делает")
check(u.check_now(manual=False) is False and not ui.urls, "Store: автопроверка не идёт в канал")
check(u.check_now(manual=True) is False and ui.urls == ["ms-windows-store://pdp/?productid=9NABCDEF1234"],
      "Store: «Проверить обновления» открывает страницу ClipSD в Store")
check(ctx.config.get("last_update_check", "") == "", "Store: время проверки канала не пишется")
set_store(True, "")
ui.urls.clear()
u.check_now(manual=True)
check(ui.urls == [updater.SITE_URL], "Store без Store ID и вне пакета: кнопка открывает сайт")
# an update attempt of a Setup.exe copy on the same computer: not shown, not finished, not deleted
attempt = updater.attempt_path()
attempt.parent.mkdir(parents=True, exist_ok=True)
attempt.write_text(json.dumps({"trace_id": "t", "attempt_id": "a", "from": "1.31.1", "to": __version__,
                               "time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                               "platform": "windows", "channel": "stable"}), encoding="utf-8")
check(u.check_previous_attempt() == "none" and attempt.exists() and not ui.infos,
      "Store: попытку обновления другой копии ClipSD не трогает")
u.mark_started()
marks = list(updater.mark_dir().glob("started-*")) if updater.mark_dir().exists() else []
check(not marks, "Store: метку запуска для запускателя не пишет")
# the editor bell (1.32): no "Version N is available" in a Store build, even when ClipSD from the website on the
# same computer wrote a newer version seen in its channel into the shared settings
from clipshot import notifications  # noqa: E402
seen = {"update_last_seen_version": "9.9.9", "update_skipped": []}
check(notifications.available_update(seen, __version__) == ""
      and not [i for i in notifications.items(seen, __version__) if i["kind"] == "update"],
      "Store: колокольчик не предлагает версию из канала сайта (обновляет Store)")
from clipshot import update_prompt  # noqa: E402
ctx_prompt = Ctx({"update_prompt": {"version": "9.9.9", "since": "2026-11-01T00:00:00Z", "shots": 99}})
u_prompt = updater.Updater(ctx_prompt, fetch=no_fetch, ui=UI(), sync=True)
update_prompt.start(u_prompt)
check(getattr(u_prompt, "_prompt_timer", None) is None,
      "Store: отложенное окно «Доступна новая версия» не ждёт своего часа (нет таймера)")
set_store(False)
check(notifications.available_update(seen, __version__) == "9.9.9",
      "сборка с сайта: колокольчик предлагает версию из канала, как в 1.32")

# --- 5. settings window -------------------------------------------------------------------------------
from clipshot import settings as st  # noqa: E402
from clipshot.app import DEFAULTS  # noqa: E402

config = dict(DEFAULTS, update_check=False)
set_store(False)
dlg = st.SettingsDialog(config)
check(not dlg.store_build and dlg.update_check is not None and not dlg.update_check.isChecked(),
      "обычная сборка: галочка автопроверки на месте")
check(not hasattr(dlg, "startup_settings"), "обычная сборка: кнопки автозагрузки Windows нет")
dlg.deleteLater()

set_store(True, "9NABCDEF1234", packaged=True, backend=Backend("enabled"))
dlg = st.SettingsDialog(config)
check(dlg.store_build and dlg.update_check is None, "Store: галочки автопроверки нет")
check(dlg.store_note.text() == tr("settings.store_updates"), "Store: «Обновления приходят через Microsoft Store»")
check(dlg.values()["update_check"] is False, "Store: значение update_check в настройках не меняется")
check(dlg.check_updates.text() == tr("updater.menu.check"), "Store: кнопка «Проверить обновления» на месте")
check(dlg.autostart.isChecked() and dlg.autostart_state == "enabled", "Store: автозапуск читается из StartupTask")
check(isinstance(getattr(dlg, "startup_settings", None), QPushButton)
      and dlg.startup_settings.text() == tr("settings.autostart_store_open"),
      "Store: кнопка «Открыть автозагрузку Windows»")
opened = []
real_open = store.open_startup_settings
store.open_startup_settings = lambda: opened.append(store.STARTUP_SETTINGS_URL) or True
dlg.deleteLater()

for state, key, enabled in (("disabled_by_user", "settings.autostart_store_user", True),
                            ("disabled_by_policy", "settings.autostart_store_policy", False),
                            ("enabled_by_policy", "settings.autostart_store_policy", False)):
    set_store(True, "", packaged=True, backend=Backend(state))
    dlg = st.SettingsDialog(config)
    hints = [w.text() for w in dlg.findChildren(QLabel)]
    check(tr(key) in hints and dlg.autostart.isEnabled() == enabled
          and dlg.autostart.isChecked() == (state == "enabled_by_policy"),
          f"Store, {state}: подсказка и галочка ({'можно' if enabled else 'нельзя'} менять)")
    dlg.deleteLater()

# set_autostart through the StartupTask
backend = Backend("disabled")
set_store(True, "", packaged=True, backend=backend)
st.set_autostart(True)
check(backend.current == "enabled" and st.autostart_enabled(), "Store: включение автозапуска через StartupTask")
st.set_autostart(False)
check(backend.current == "disabled" and not st.autostart_enabled(), "Store: выключение автозапуска через StartupTask")
check(not (Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup/ClipSD.lnk").exists(),
      "Store: ярлык в папке «Автозагрузка» не создаётся")
set_store(True, "", packaged=True, backend=Backend("disabled_by_user"))
try:
    st.set_autostart(True)
    check(False, "Store, выключено человеком: включить нельзя")
except store.StartupError as exc:
    check(exc.state == "disabled_by_user", "Store, выключено человеком: StartupError(disabled_by_user)")

# apply_settings: turned off in Windows Settings -> message and the Startup page of Windows
from clipshot.app import Clipshot  # noqa: E402


class FakeApp:
    def __init__(self):
        self.config = dict(DEFAULTS)
        self.notes, self.qapp, self.tray, self.editors = [], qapp, None, []

    def save_config(self):
        pass

    def notify(self, text):
        self.notes.append(text)

    def set_language(self, _c):
        pass


# after installation the task is off (Enabled="false"): the checkbox is empty, ticking it turns the start on
backend = Backend("disabled")
set_store(True, "", packaged=True, backend=backend)
dlg = st.SettingsDialog(config)
check(not dlg.autostart.isChecked() and dlg.autostart.isEnabled() and dlg.autostart_state == "disabled",
      "Store после установки: галочка автозапуска пустая, её можно поставить")
dlg.deleteLater()
fake = FakeApp()
Clipshot.apply_settings(fake, {"hotkey_region": fake.config["hotkey_region"],
                               "hotkey_fullscreen": fake.config["hotkey_fullscreen"],
                               "hotkey_both_layouts": True, "autostart": True})
check(backend.current == "enabled" and "enable" in backend.calls and not fake.notes,
      "Store: галочка «Запускать вместе с системой» + «Сохранить» включает StartupTask (согласие человека)")

for state, note_key, opens in (("disabled_by_user", "app.autostart_store_user", True),
                               ("disabled_by_policy", "settings.autostart_store_policy", False)):
    opened.clear()
    set_store(True, "", packaged=True, backend=Backend(state))
    fake = FakeApp()
    values = {"hotkey_region": fake.config["hotkey_region"], "hotkey_fullscreen": fake.config["hotkey_fullscreen"],
              "hotkey_both_layouts": True, "autostart": True}
    Clipshot.apply_settings(fake, values)
    check(fake.notes == [tr(note_key)] and bool(opened) == opens,
          f"Store, {state}: сообщение{' и раздел «Автозагрузка» Windows' if opens else ''}")
store.open_startup_settings = real_open

# first start of the Store build: card "Start ClipSD with Windows", ticked (owner's decision 19.11.2026)
from PyQt6.QtCore import QEvent, Qt  # noqa: E402
from PyQt6.QtGui import QKeyEvent  # noqa: E402
from clipshot import store_welcome as sw  # noqa: E402


def first_run(state, offered=None, packaged=True):
    backend = Backend(state)
    set_store(True, "", packaged=packaged, backend=backend)
    fake = FakeApp()
    fake.saved = 0
    fake.save_config = lambda: setattr(fake, "saved", fake.saved + 1)
    if offered is not None:
        fake.config[sw.OFFERED_KEY] = offered
    Clipshot._store_first_run(fake)
    return fake, backend, fake._store_offer


fake, backend, card = first_run("disabled")
check(isinstance(card, sw.StartupOfferDialog) and card.isVisible() and card.startup.isChecked()
      and card.startup.text() == tr("app.store_startup_check")
      and tr("app.store_startup_note", section=tr("settings.sec_start")) in [w.text() for w in card.findChildren(QLabel)],
      "первый запуск Store: карточка, галочка «Запускать ClipSD вместе с Windows» отмечена, пояснение")
check(backend.current == "disabled" and not fake.config.get(sw.OFFERED_KEY), "пока карточка открыта, ничего не включено")
card.grab().save(str(out / "store-first-run-card.png"))
card.done_b.click()
check(backend.current == "enabled" and fake.config.get(sw.OFFERED_KEY) is True and fake.saved >= 1,
      "галочка отмечена, «Готово»: автозапуск включён, решение запомнено")

fake, backend, card = first_run("disabled")
card.startup.setChecked(False)
card.done_b.click()
check(backend.current == "disabled" and "enable" not in backend.calls and fake.config.get(sw.OFFERED_KEY) is True,
      "галочку сняли, «Готово»: автозапуск не включён, больше не спрашиваем")

fake, backend, card = first_run("disabled")
card.close_b.click()
check(backend.current == "enabled" and fake.config.get(sw.OFFERED_KEY) is True,
      "закрыли крестиком: согласие по умолчанию, автозапуск включён")

fake, backend, card = first_run("disabled")
card.startup.setChecked(False)
card.close_b.click()
check(backend.current == "disabled" and fake.config.get(sw.OFFERED_KEY) is True,
      "сняли галочку и закрыли крестиком: не включён")

fake, backend, card = first_run("disabled")
QApplication.sendEvent(card, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
check(backend.current == "enabled" and fake.config.get(sw.OFFERED_KEY) is True and not card.isVisible(),
      "закрыли клавишей Esc: как крестик, автозапуск включён")

fake, backend, card = first_run("disabled")
card.close()   # the program closes it (quit while the card is open): no answer
check(backend.current == "disabled" and not fake.config.get(sw.OFFERED_KEY),
      "карточка закрылась сама (выход программы): решения нет, спросим при следующем запуске")

fake, backend, card = first_run("disabled_by_user")
check(card is None and backend.current == "disabled_by_user" and "enable" not in backend.calls
      and fake.config.get(sw.OFFERED_KEY) is True,
      "уже выключено человеком в параметрах Windows: карточки нет, ничего не включаем")
fake, backend, card = first_run("disabled_by_policy")
check(card is None and "enable" not in backend.calls, "запрещено политикой: карточки нет")
fake, backend, card = first_run("enabled")
check(card is None and fake.config.get(sw.OFFERED_KEY) is True, "уже включено: карточки нет")
fake, backend, card = first_run("disabled", offered=True)
check(card is None and backend.current == "disabled", "решение уже было: карточка больше не показывается")
fake, backend, card = first_run("disabled", packaged=False)
check(card is None and not fake.config.get(sw.OFFERED_KEY), "не пакет Store (сборка с сайта): карточки нет")
fake, backend, card = first_run("disabled")
backend.on_enable = "disabled_by_user"   # Windows refused at the last moment
backend.current = "disabled_by_user"
card.done_b.click()
check(fake.notes == [tr("app.autostart_failed", error=store.StartupError("disabled_by_user"))],
      "Windows не дала включить: сообщение «Не удалось изменить автозапуск»")

# internal --selfcheck-startup of ClipSD-app.exe (store_test.ps1 runs it inside the real package)
spec = importlib.util.spec_from_file_location("clipsd_app_entry", project / "packaging" / "windows-exe" / "clipsd_app_entry.py")
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)
backend = Backend("disabled")
set_store(True, "", packaged=True, backend=backend)
report = tmp / "startup-toggle.txt"
code = entry._selfcheck_startup(str(report))
lines = report.read_text(encoding="utf-8").splitlines()
check(code == 0 and lines[1:] == ["before: disabled", "enable: enabled", "disable: disabled", "after: disabled"],
      "--selfcheck-startup: включить и выключить, итог как до проверки")
set_store(True, "", packaged=True, backend=Backend("disabled_by_policy"))
code = entry._selfcheck_startup(str(report))
check(code == 1 and "enable: refused disabled_by_policy" in report.read_text(encoding="utf-8"),
      "--selfcheck-startup: отказ Windows виден в отчёте, код 1")
set_store(False)

# --- 6. settings: from Microsoft Store back to the Setup.exe build ------------------------------------------
from clipshot import paths  # noqa: E402

check(paths.migrate_store() == [], "вне Windows-сборки настройки Store не ищутся")
packages = tmp / "Packages"
newer = packages / "12345SergeyDayneko.ClipSD_8wekyb3d8bbwe" / "LocalCache" / "Roaming" / "ClipSD"
older = packages / "ClipSD.Placeholder_1a2b3c4d5e6f7" / "LocalCache" / "Roaming" / "ClipSD"
other = packages / "Contoso.Paint_8wekyb3d8bbwe" / "LocalCache" / "Roaming" / "ClipSD"
for folder, marker in ((older, "older"), (other, "other"), (newer, "newer")):
    folder.mkdir(parents=True)
    (folder / "config.json").write_text(json.dumps({"store_probe": marker}), encoding="utf-8")
(newer / "google-translate.key").write_text("AIza" + "x" * 35, encoding="utf-8")
os.utime(older / "config.json", (1_700_000_000, 1_700_000_000))
os.utime(other / "config.json", (1_800_000_000, 1_800_000_000))
check(paths.store_settings_dirs(packages) == [newer, older], "папки настроек пакетов ClipSD, свежая первой (чужие не берутся)")
target = tmp / "setup-config"
copied = paths.migrate_store(target, packages)
check(sorted(copied) == ["config.json", "google-translate.key"]
      and json.loads((target / "config.json").read_text(encoding="utf-8"))["store_probe"] == "newer",
      "из Store на сайт: настройки и ключ Google скопированы из самой свежей Store-копии")
(newer / "config.json").write_text(json.dumps({"store_probe": "changed"}), encoding="utf-8")
check(paths.migrate_store(target, packages) == []
      and json.loads((target / "config.json").read_text(encoding="utf-8"))["store_probe"] == "newer",
      "свои настройки уже есть: ничего не перетирается")

# --- 7. texts in 12 languages ---------------------------------------------------------------------------
KEYS = ("settings.store_updates", "settings.autostart_store_open", "settings.autostart_store_user",
        "settings.autostart_store_policy", "app.autostart_store_user", "app.store_description",
        "app.store_welcome_title", "app.store_welcome_sub", "app.store_startup_check", "app.store_startup_note")
for lang in i18n.LANGUAGES:
    cat = i18n._load(lang)
    missing = [k for k in KEYS if not str(cat.get(k, "")).strip()]
    check(not missing, f"{lang}: тексты Store на месте {missing or ''}")
ru = i18n._load("ru")
check(not any("—" in ru[k] for k in KEYS), "ru: без длинных тире")
check(all("Microsoft Store" in i18n._load(lang)["settings.store_updates"] for lang in i18n.LANGUAGES),
      "все языки: название Microsoft Store не переведено")

# --- 8. package layout ----------------------------------------------------------------------------------
import make_msix_layout as ml  # noqa: E402

check(ml.package_version("1.31.2") == "1.31.2.0" and ml.package_version(__version__) == __version__ + ".0",
      "версия пакета: N.N.N.0 (четвёртая часть за Store)")
for bad in ("0.1.2", "1.2", "1.2.3.4", "1.70000.0", "1.2.x"):
    try:
        ml.package_version(bad)
        check(False, f"версия {bad} отвергается")
    except ml.LayoutError:
        pass
ident = ml.read_identity(require=True)
check(not ident["placeholder"] and ident["name"] == "ClipSD.ClipSD"
      and ident["publisher"] == "CN=079DE278-715A-4263-8FDC-88C654643F05"
      and ident["publisher_display_name"] == "ClipSD" and ident["store_product_id"] == "9NSWT4W953L9",
      "store-identity.json: имена из Partner Center (19.11.2026), без заглушек")


def publisher_id(publisher: str) -> str:
    """Publisher part of a package family name: the first 8 bytes of SHA-256 of the UTF-16LE publisher, base32."""
    import hashlib
    bits = int.from_bytes(hashlib.sha256(publisher.encode("utf-16-le")).digest()[:8], "big") << 1
    return "".join("0123456789abcdefghjkmnpqrstvwxyz"[(bits >> (60 - 5 * i)) & 31] for i in range(13))


check(publisher_id("CN=ClipSD-Placeholder") == "1ncvrnmmrpwnr",
      "проверка расчёта: заглушка даёт семейство из прогона CI (ClipSD.Placeholder_1ncvrnmmrpwnr)")
check(f"{ident['name']}_{publisher_id(ident['publisher'])}" == "ClipSD.ClipSD_ynnabdvwaxkfc",
      "Name и Publisher дают Package Family Name из Partner Center ClipSD.ClipSD_ynnabdvwaxkfc")
placeholder_identity = tmp / "placeholder-identity.json"
placeholder_identity.write_text(json.dumps({"name": "ClipSD.Placeholder", "publisher": "CN=ClipSD-Placeholder",
                                            "publisher_display_name": "Sergey Dayneko"}), encoding="utf-8")
check(ml.read_identity(placeholder_identity)["placeholder"], "заглушки распознаются")
try:
    ml.read_identity(placeholder_identity, require=True)
    check(False, "--require-identity: заглушки отвергаются")
except ml.LayoutError:
    check(True, "--require-identity: заглушки отвергаются")
bad_identity = tmp / "bad-identity.json"
for broken in ({"name": "x", "publisher": "CN=A", "publisher_display_name": "A"},
               {"name": "Good.Name", "publisher": "A", "publisher_display_name": "A"},
               {"name": "Good.Name", "publisher": "CN=A", "publisher_display_name": " A"},
               {"name": "Good.Name", "publisher": "CN=A", "publisher_display_name": "A", "store_product_id": "123"}):
    bad_identity.write_text(json.dumps(broken), encoding="utf-8")
    try:
        ml.read_identity(bad_identity)
        check(False, f"неверная identity отвергается: {broken}")
    except ml.LayoutError:
        pass
text = ml.manifest_text({"name": "A.B", "publisher": 'CN="X & Y", O=Z', "publisher_display_name": "Tom & <Jerry>"},
                        "1.2.3.0")
root = ET.fromstring(text.encode("utf-8"))
NS = {"m": "http://schemas.microsoft.com/appx/manifest/foundation/windows10"}
check(root.find("m:Identity", NS).get("Publisher") == 'CN="X & Y", O=Z'
      and root.find("m:Properties/m:PublisherDisplayName", NS).text == "Tom & <Jerry>",
      "манифест: значения Partner Center с &, <, \" экранируются")

app_dir, docs = tmp / "dist" / "ClipSD-app", tmp / "docs"
(app_dir / "_internal").mkdir(parents=True)
(app_dir / "ClipSD-app.exe").write_bytes(b"MZ fake")
(app_dir / "_internal" / "python312.dll").write_bytes(b"MZ fake")
docs.mkdir()
for name in ml.DOCS:
    (docs / name).write_text(name, encoding="utf-8")
msix = tmp / "msix"
result = ml.make(app_dir, msix, docs)
layout, pri = msix / "layout", msix / "pri"
manifest = layout / "AppxManifest.xml"
check(manifest.is_file(), "раскладка: AppxManifest.xml")
shutil.copy2(manifest, out / "AppxManifest.xml")
root = ET.parse(manifest).getroot()
NS = {"m": "http://schemas.microsoft.com/appx/manifest/foundation/windows10",
      "uap": "http://schemas.microsoft.com/appx/manifest/uap/windows10",
      "uap3": "http://schemas.microsoft.com/appx/manifest/uap/windows10/3",
      "uap5": "http://schemas.microsoft.com/appx/manifest/uap/windows10/5",
      "desktop": "http://schemas.microsoft.com/appx/manifest/desktop/windows10",
      "rescap": "http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"}
identity = root.find("m:Identity", NS)
check(identity.get("Name") == ident["name"] and identity.get("Publisher") == ident["publisher"]
      and identity.get("Version") == __version__ + ".0" and identity.get("ProcessorArchitecture") == "x64",
      "манифест: Identity из store-identity.json, версия программы, x64")
check(root.find("m:Properties/m:DisplayName", NS).text == "ClipSD", "манифест: DisplayName ClipSD")
langs = [r.get("Language") for r in root.findall("m:Resources/m:Resource", NS)]
check(langs == list(ml.LANGUAGE_TAGS.values()) and len(langs) == 12 and langs[0] == "en-US",
      f"манифест: 12 языков, первый en-US ({', '.join(langs)})")
family = root.find("m:Dependencies/m:TargetDeviceFamily", NS)
check(family.get("Name") == "Windows.Desktop" and family.get("MinVersion") == "10.0.19041.0",
      "манифест: Windows 10 2004 и новее")
apps = root.findall("m:Applications/m:Application", NS)
check(len(apps) == 1 and apps[0].get("Executable") == "ClipSD-app.exe"
      and apps[0].get("EntryPoint") == "Windows.FullTrustApplication",
      "манифест: одно приложение, ClipSD-app.exe, полное доверие")
visual = apps[0].find("uap:VisualElements", NS)
check(visual.get("Description") == "ms-resource:AppDescription" and visual.get("BackgroundColor") == "transparent",
      "манифест: описание из resources.pri, прозрачный фон значков")
task = apps[0].find("m:Extensions/uap5:Extension/uap5:StartupTask", NS)
check(task is not None and task.get("TaskId") == store.STARTUP_TASK_ID,
      "манифест: StartupTask с тем же TaskId, что в программе")
check(task is not None and task.get("Enabled") == "false",
      "манифест: Enabled=false, автозапуск включает программа после согласия (карточка первого запуска)")
alias = apps[0].find("m:Extensions/uap3:Extension/uap3:AppExecutionAlias/desktop:ExecutionAlias", NS)
check(alias is not None and alias.get("Alias") == "clipsd.exe", "манифест: короткое имя clipsd.exe")
caps = [c.get("Name") for c in root.find("m:Capabilities", NS)]
check(caps == ["runFullTrust"], "манифест: из ограниченных возможностей только runFullTrust (без unvirtualizedResources)")
check(not root.findall(".//{http://schemas.microsoft.com/appx/manifest/desktop/windows10/6}FileSystemWriteVirtualization"),
      "манифест: виртуализация AppData не выключена")

# images: every logo of the manifest at every scale, the right pixel size, under 200 KB
refs = {"StoreLogo": root.find("m:Properties/m:Logo", NS).text,
        "Square44x44Logo": visual.get("Square44x44Logo"), "Square150x150Logo": visual.get("Square150x150Logo"),
        "Wide310x150Logo": visual.find("uap:DefaultTile", NS).get("Wide310x150Logo")}
check(all(v == f"Assets\\{k}.png" for k, v in refs.items()), "манифест: значки Assets\\<имя>.png")
bad = []
for name, w, h, _logo in ml.image_plan():
    for folder in (layout / "Assets", pri / "Assets"):
        img = QImage(str(folder / name))
        if img.isNull() or (img.width(), img.height()) != (w, h) or (folder / name).stat().st_size >= 204_800:
            bad.append(f"{folder.parent.name}/{name}")
check(not bad, f"значки: {len(ml.image_plan())} файлов нужного размера и меньше 200 КБ {bad[:5] or ''}")
for base, (w, h, _s) in ml.LOGOS.items():
    sizes = {s: QImage(str(layout / "Assets" / f"{base}.scale-{s}.png")).size() for s in ml.SCALES}
    check(all((sz.width(), sz.height()) == (w * s // 100, h * s // 100) for s, sz in sizes.items()),
          f"{base}: масштабы {', '.join(map(str, ml.SCALES))}")
check(all((layout / "Assets" / f"Square44x44Logo.targetsize-{n}_altform-unplated.png").is_file()
          for n in ml.TARGET_SIZES), "значки панели задач без подложки (altform-unplated)")
img = QImage(str(layout / "Assets" / "Square44x44Logo.targetsize-48.png"))
check(img.pixelColor(24, 24).alpha() == 255 and img.pixelColor(0, 0).alpha() == 0,
      "значок 48: логотип в центре, прозрачные углы")
shutil.copy2(layout / "Assets" / "Square150x150Logo.scale-200.png", out / "Square150x150Logo.scale-200.png")

# the images are ready files of the repository (1.31.2 drew them during the build on Windows: boxes instead of
# "Clip" and "SD"); the tile is compared with the logo of the program and the website
import logo_assets as la  # noqa: E402

check(all((ml.ASSETS / name).read_bytes() == (layout / "Assets" / name).read_bytes() for name, *_ in ml.image_plan()),
      "раскладка: значки скопированы из packaging/windows-store/Assets без перерисовки")
good = la.check_folder(ml.ASSETS)
broken = la.difference(la.BROKEN_SAMPLE)
check(good <= la.THRESHOLD, f"значок 150x150 похож на логотип ClipSD (разница {good:.1f}, предел {la.THRESHOLD})")
check(broken > la.THRESHOLD, f"значок 1.31.2 с квадратиками вместо букв проверка ловит (разница {broken:.1f})")
listing_tile = QImage(str(la.LISTING / la.LISTING_TILE))
check((listing_tile.width(), listing_tile.height()) == (300, 300) and listing_tile.pixelColor(150, 150).alpha() == 255,
      "плитка для карточки Store 300x300 на месте")
broken_assets = tmp / "broken-assets"
shutil.copytree(ml.ASSETS, broken_assets)
(broken_assets / "StoreLogo.scale-100.png").write_bytes((ml.ASSETS / "StoreLogo.scale-200.png").read_bytes())
try:
    ml.copy_images(tmp / "copy-check", broken_assets)
    check(False, "значок не того размера раскладка не берёт")
except ml.LayoutError:
    check(True, "значок не того размера раскладка не берёт")
shutil.copy2(layout / "Assets" / "Wide310x150Logo.scale-200.png", out / "Wide310x150Logo.scale-200.png")

# strings: description of the app in 12 languages
for lang, tag in ml.LANGUAGE_TAGS.items():
    resw = ET.parse(pri / "Strings" / tag / "Resources.resw").getroot()
    value = resw.find("data[@name='AppDescription']/value")
    check(value is not None and value.text == i18n._load(lang)["app.store_description"]
          and (layout / "Strings" / tag / "Resources.resw").is_file(),
          f"Strings/{tag}/Resources.resw: описание на языке {lang}")
check(all((layout / d).is_file() for d in ml.DOCS) and (layout / "ClipSD-app.exe").is_file()
      and (layout / "_internal" / "python312.dll").is_file(), "раскладка: программа и лицензии")
check(not list(layout.rglob("*.pfx")) and not list(layout.rglob("*.snk")), "раскладка: нет закрытых ключей (.pfx, .snk)")
try:
    ml.make(tmp / "nowhere", tmp / "msix2", docs)
    check(False, "без ClipSD-app.exe раскладка не делается")
except ml.LayoutError:
    check(True, "без ClipSD-app.exe раскладка не делается")

# --- 9. staging for the Store and the release check ------------------------------------------------------
import release_check  # noqa: E402
import stage_windows  # noqa: E402

staged = tmp / "stage" / "store"
stage_windows.stage(staged, store=True)
module = staged / "clipshot" / "_store_build.py"
check(module.is_file() and "STORE = True" in module.read_text(encoding="utf-8"),
      "stage_windows --store: модуль Store-сборки в разложенной копии")
check((staged / "packaging" / "store" / "AppxManifest.xml.in").is_file()
      and (staged / "packaging" / "store" / "make_msix_layout.py").is_file(),
      "stage_windows --store: файлы пакета в packaging/store")
check(not (project / "clipshot" / "_store_build.py").exists(), "stage_windows --store: репозиторий не тронут")
sys.path.insert(0, str(staged))
spec = importlib.util.spec_from_file_location("staged_store_build", module)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
check(mod.STORE is True and mod.STORE_PRODUCT_ID == ident["store_product_id"] == "9NSWT4W953L9",
      "модуль Store-сборки: STORE = True, Store ID 9NSWT4W953L9 из store-identity.json")
# the Store build made from it: "Check for updates" opens exactly the ClipSD page in the Store app
set_store(True, mod.STORE_PRODUCT_ID)
check(store.store_url() == "ms-windows-store://pdp/?productid=9NSWT4W953L9",
      "Store-сборка: страница ms-windows-store://pdp/?productid=9NSWT4W953L9")
ui = UI()
updater.Updater(Ctx(), fetch=no_fetch, ui=ui, sync=True).check_now(manual=True)
check(ui.urls == ["ms-windows-store://pdp/?productid=9NSWT4W953L9"],
      "Store-сборка: «Проверить обновления» открывает https://apps.microsoft.com/detail/9NSWT4W953L9 в приложении Store")
set_store(True, mod.STORE_PRODUCT_ID, packaged=True)
check(store.store_url() == "ms-windows-store://pdp/?productid=9NSWT4W953L9", "в пакете тоже по Store ID, а не по семейству")
set_store(False)
plain = tmp / "stage" / "plain"
stage_windows.stage(plain)
check(not (plain / "clipshot" / "_store_build.py").exists() and not (plain / "packaging" / "store").exists(),
      "обычная раскладка: без модуля и файлов Store")
check(any("_store_build.py" in p for p in release_check.preview_problems(staged)),
      "release_check: дерево с _store_build.py не выпуск")
check(not any("_store_build.py" in p for p in release_check.preview_problems(project)),
      "release_check: репозиторий чистый")
fake_root = tmp / "fake-root"
(fake_root / "clipshot").mkdir(parents=True)
(fake_root / "clipshot" / "_preview_build.py").write_text("PREVIEW = True\n", encoding="utf-8")
shutil.copytree(project / "packaging" / "windows-store", fake_root / "packaging" / "windows-store")
real_root = stage_windows.ROOT
stage_windows.ROOT = fake_root
try:
    stage_windows.stage_store(tmp / "stage" / "never")
    check(False, "пробная сборка не становится Store-сборкой")
except stage_windows.StageError:
    check(True, "пробная сборка не становится Store-сборкой")
finally:
    stage_windows.ROOT = real_root

print()
print(f"store_test: {len(failures)} failure(s)" if failures else "store_test: all checks passed")
sys.exit(1 if failures else 0)
