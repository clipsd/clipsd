# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""«Заменить» вместо тупика «Дополнение поставлено вручную» (1.35.x).

Старое дополнение clipsd@yugrost (та же схема, без метки пакета) включено: update() без согласия ничего не меняет
и возвращает FOREIGN; с replace=True старое выключается и откладывается (<имя>.disabled-by-clipsd-<дата>), своё
ставится с меткой и включается, а запасное сочетание Alt+W включается ДО выключения старого. Всё на временной папке
и подменённом run: настоящий GNOME не трогается.

Запуск: python3 tests/ext_zamenit_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
from clipshot import app as appmod, gnome_ext  # noqa: E402
from clipshot.i18n import tr  # noqa: E402

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


OLD = "clipsd@yugrost"
tmp = Path(tempfile.mkdtemp(prefix="u-", dir=Path.home()))
src = tmp / "src" / gnome_ext.EXT_UUID
(src / "schemas").mkdir(parents=True)
(src / "metadata.json").write_text(json.dumps({"uuid": gnome_ext.EXT_UUID, "shell-version": ["50"],
                                               "settings-schema": gnome_ext.EXT_SCHEMA}), encoding="utf-8")
(src / "extension.js").write_text("// new", encoding="utf-8")


class Fake:
    """gsettings с памятью: enabled-extensions, журнал вызовов; fail_set: упасть на записи enabled-extensions."""

    def __init__(self, enabled):
        self.enabled, self.log, self.fail_set = list(enabled), [], False

    def __call__(self, cmd, **kw):
        self.log.append(cmd)
        out = lambda text="", rc=0: SimpleNamespace(returncode=rc, stdout=text, stderr="" if rc == 0 else "boom")
        if cmd[0] == "gnome-shell":
            return out("GNOME Shell 50.1")
        if cmd[0] == "gsettings" and cmd[1] == "get" and cmd[3] == "enabled-extensions":
            return out(str(self.enabled))
        if cmd[0] == "gsettings" and cmd[1] == "get":
            return out("false")
        if cmd[0] == "gsettings" and cmd[1] == "set" and cmd[3] == "enabled-extensions":
            if self.fail_set:
                return out(rc=1)
            self.enabled = json.loads(cmd[4].replace("'", '"')) if cmd[4].startswith("[") else []
            return out()
        return out()


def make_base(name="a", enabled_old=True, mark_target=False):
    base = tmp / name / "ext"
    old = base / OLD
    old.mkdir(parents=True)
    (old / "metadata.json").write_text(json.dumps({"uuid": OLD, "settings-schema": gnome_ext.EXT_SCHEMA}), encoding="utf-8")
    (old / "extension.js").write_text("// old", encoding="utf-8")
    return base, Fake([OLD, "other@x"] if enabled_old else ["other@x"])


# 1. без согласия: тупика нет, но и изменений нет (update сообщает FOREIGN, окно предлагает «Заменить»)
base, run = make_base("a")
res = gnome_ext.update(src=src, base=base, run=run)
check(res == (gnome_ext.FOREIGN, OLD), "старое включено: update() просит согласия (FOREIGN)")
check(run.enabled == [OLD, "other@x"] and (base / OLD).is_dir() and not (base / gnome_ext.EXT_UUID).exists(),
      "без согласия ничего не изменено")

# 2. замена: порядок запасное -> выключить старое; старое отложено, новое с меткой и включено
order = []
base, run = make_base("b")
orig_call = run.__call__


def fallback():
    order.append(("fallback", list(run.enabled)))   # в этот миг старое ещё включено: Alt+W держит оно


res = gnome_ext.update(src=src, base=base, run=run, replace=True, fallback=fallback, today="20261123")
check(res == (gnome_ext.REPLACED, ""), "замена: итог REPLACED")
check(run.enabled == ["other@x", gnome_ext.EXT_UUID], "старое выключено, свои включено, чужое другое не тронуто")
check(not (base / OLD).exists() and (base / f"{OLD}.disabled-by-clipsd-20261123/extension.js").read_text() == "// old",
      "папка старого отложена, не удалена")
check((base / gnome_ext.EXT_UUID / gnome_ext.PKG_MARK).is_file() and (base / gnome_ext.EXT_UUID / "extension.js").read_text() == "// new",
      "новое дополнение стоит с меткой пакета")
check(len(order) == 1, "запасное сочетание Alt+W включено один раз")
check(not any(p.name.startswith(".") for p in base.iterdir()), "временных папок не осталось")

# 3. повторный запуск после замены: отложенная папка не мешает, обычное обновление
res = gnome_ext.update(src=src, base=base, run=run, version="9")
check(res[0] == gnome_ext.UPDATED and run.enabled == ["other@x", gnome_ext.EXT_UUID], "повтор: обычное обновление, не FOREIGN")
check((base / f"{OLD}.disabled-by-clipsd-20261123").is_dir(), "отложенная папка на месте после повтора")

# 4. та же дата второй раз: имя не затирается
base2, run2 = make_base("c")
(base2 / f"{OLD}.disabled-by-clipsd-20261123").mkdir()
gnome_ext.update(src=src, base=base2, run=run2, replace=True, today="20261123")
check((base2 / f"{OLD}.disabled-by-clipsd-20261123-2").is_dir(), "занятое имя отложенной папки: добавляется -2")

# 5. папка цели есть без метки (не включена): тоже тупик без согласия, замена откладывает её
base3, run3 = make_base("d", enabled_old=False)
(base3 / OLD).rename(base3 / gnome_ext.EXT_UUID)
(base3 / gnome_ext.EXT_UUID / "extension.js").write_text("// hand", encoding="utf-8")
check(gnome_ext.update(src=src, base=base3, run=run3)[0] == gnome_ext.FOREIGN, "папка цели без метки: FOREIGN")
res = gnome_ext.update(src=src, base=base3, run=run3, replace=True, today="20261123")
check(res[0] == gnome_ext.REPLACED and (base3 / f"{gnome_ext.EXT_UUID}.disabled-by-clipsd-20261123/extension.js").read_text() == "// hand"
      and (base3 / gnome_ext.EXT_UUID / gnome_ext.PKG_MARK).is_file(), "папка цели без метки отложена, своё поставлено")

# 6. ошибки: запасной способ не включился -> старое не выключено, всё как было
base4, run4 = make_base("e")


def bad_fallback():
    raise RuntimeError("нет gsettings")


res = gnome_ext.update(src=src, base=base4, run=run4, replace=True, fallback=bad_fallback)
check(res[0] == gnome_ext.FAILED and "нет gsettings" in res[1] and run4.enabled == [OLD, "other@x"]
      and (base4 / OLD / "extension.js").read_text() == "// old" and not (base4 / gnome_ext.EXT_UUID).exists(),
      "запасное сочетание не включилось: ничего не выключено и не отложено")
base5, run5 = make_base("f")
run5.fail_set = True
res = gnome_ext.update(src=src, base=base5, run=run5, replace=True)
check(res[0] == gnome_ext.FAILED and (base5 / OLD).is_dir() and not any(p.name.startswith(".") for p in base5.iterdir()),
      "не удалось записать enabled-extensions: старое на месте, мусора нет")

# 7. окно: «Заменить», «Не сейчас», ошибка с «Открыть папку дополнений»
cards, state_calls = [], []
answers = []


class Dummy:
    config = {"hotkey_region": "Alt+W", "hotkey_fullscreen": "", "hotkey_both_layouts": True}
    save_config = lambda self: None
    _report_ext_state = appmod.Clipshot._report_ext_state
    update_gnome_extension = appmod.Clipshot.update_gnome_extension
    _ext_hotkey_fallback = appmod.Clipshot._ext_hotkey_fallback

    def _sync_gnome_hotkeys(self):
        state_calls.append("sync")

    def _show_ext_card(self, title, text, icon, secondary=None, primary=None):
        cards.append((title, text, icon, secondary, primary))
        return answers.pop(0) if answers else "close"


from clipshot import windows  # noqa: E402
windows.shell_owner = lambda: ":1.5"
opened = []
gnome_ext.open_folder = lambda: opened.append(1) or True
logouts = []
gnome_ext.log_out = lambda: logouts.append(1) or True
real_update = gnome_ext.update
d = Dummy()


def run_flow(name, **kw):
    base_, run_ = make_base(name)
    gnome_ext.update = lambda version="", **k: real_update(src=src, base=base_, run=run_, version=version, today="20261123", **k)
    return base_, run_


base6, run6 = run_flow("g")
answers[:] = ["secondary"]
check(d.update_gnome_extension() == gnome_ext.FOREIGN and cards[0][0] == tr("app.ext_old_title")
      and cards[0][4] == tr("app.ext_old_replace") and cards[0][3] == tr("app.ext_old_later"),
      "окно «Найдено старое дополнение» с «Заменить» и «Не сейчас»")
check(run6.enabled == [OLD, "other@x"] and (base6 / OLD).is_dir() and len(cards) == 1 and "gnome_ext_relogin" not in d.config,
      "«Не сейчас»: ничего не изменилось")

cards.clear()
d.config["hotkey_region"] = "Alt+W"
fb = []
Dummy._ext_hotkey_fallback = lambda self: fb.append(list(run6.enabled))
answers[:] = ["primary", "secondary"]
check(d.update_gnome_extension() == gnome_ext.REPLACED, "«Заменить»: итог REPLACED")
check(cards[1][0] == tr("app.ext_replaced_title") and cards[1][1] == tr("app.ext_replaced_text")
      and cards[1][3] == tr("app.ext_logout"), "после замены: «Выйдите из системы и войдите снова», кнопка выхода")
check("запасн" in tr("app.ext_replaced_text") and logouts == [1], "текст честно говорит про запасной способ; выход по кнопке")
check(d.config.get("gnome_ext_relogin") == ":1.5", "запомнено ожидание входа в систему")
check(fb == [[OLD, "other@x"]], "запасное Alt+W включено до выключения старого")
check(run6.enabled == ["other@x", gnome_ext.EXT_UUID] and (base6 / f"{OLD}.disabled-by-clipsd-20261123").is_dir(),
      "старое выключено и отложено, новое включено")

# 8. сбой замены: понятная причина и «Открыть папку дополнений»
cards.clear()
base7, run7 = run_flow("h")
run7.fail_set = True
answers[:] = ["primary", "secondary"]
check(d.update_gnome_extension() == gnome_ext.FAILED and cards[1][0] == tr("app.ext_failed_title")
      and "boom" in cards[1][1] and cards[1][3] == tr("app.ext_open_folder"), "сбой: причина и кнопка «Открыть папку дополнений»")
check(opened == [1] and state_calls == ["sync"], "кнопка открывает папку; сочетания возвращены по состоянию дополнения")
check((base7 / OLD).is_dir(), "после сбоя старое на месте")

# 9. 12 языков, строки не пустые и подстановок нет лишних
from clipshot import i18n  # noqa: E402
keys = ["app.ext_old_title", "app.ext_old_text", "app.ext_old_later", "app.ext_old_replace", "app.ext_replaced_title",
        "app.ext_replaced_text", "app.ext_open_folder"]
langs = sorted(p.name for p in (ROOT / "clipshot/i18n").iterdir() if p.is_dir() and (p / "app.json").exists())
bad = []
for lang in langs:
    data = json.loads((ROOT / f"clipshot/i18n/{lang}/app.json").read_text(encoding="utf-8"))
    bad += [(lang, k) for k in keys if not data.get(k, "").strip()]
check(len(langs) == 12 and not bad, f"12 языков, все новые строки заполнены {bad}")
check(all(len(tr(k)) < 400 for k in keys), "тексты не длиннее окна")

import shutil  # noqa: E402
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if failures else 0)
