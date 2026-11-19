# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Канал Telegram программы (1.32): https://t.me/clipsdapp в окне «О программе» и в меню «?» редактора, подпись на
12 языках, открытие через sysenv.open_url (в пакете для Linux xdg-open без библиотек сборки). Адрес t.me/clipsd
чужой и нигде не встречается.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/links132_test.py
"""
import json
import os
import re
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(here)
sys.path.insert(0, ROOT)
os.environ.pop("CLIPSD_LANG", None)
_cfg = os.path.join(tempfile.mkdtemp(prefix="clipsd-links132-"), "screen.json")
with open(_cfg, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1600, "height": 1000,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _cfg

from PyQt6.QtCore import QPoint  # noqa: E402
from PyQt6.QtGui import QColor, QImage  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel  # noqa: E402

app = QApplication(sys.argv)
from clipshot import app as appmod, i18n, links, sysenv  # noqa: E402
from clipshot.editor import EditorWindow  # noqa: E402

failures = []
checks = [0]


def check(cond, msg):
    checks[0] += 1
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


class Ctx:
    def __init__(self):
        self.config = dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True)
        self.icon = appmod.make_icon()

    def save_config(self):
        pass

    def notify(self, text):
        pass


opened = []
real_open = sysenv.open_url
sysenv.open_url = lambda url: opened.append(url.toString() if hasattr(url, "toString") else str(url)) or True
appmod.open_url = sysenv.open_url   # окно «О программе» берёт open_url из sysenv при импорте app

check(links.TELEGRAM_URL == "https://t.me/clipsdapp", "адрес канала https://t.me/clipsdapp")
i18n.set_language("ru")
img = QImage(300, 200, QImage.Format.Format_RGB32)
img.fill(QColor("#ffffff"))
ed = EditorWindow(img, Ctx(), QPoint(0, 0))
ed.present()
texts = [a.text() for a in ed.help_menu.actions() if not a.isSeparator()]
check(texts[-2:] == ["О программе", "Новости в Telegram"], f"меню «?»: «Новости в Telegram» после «О программе» ({texts})")
ed.telegram_action.trigger()
check(opened == ["https://t.me/clipsdapp"], f"пункт меню открывает канал через sysenv.open_url ({opened})")
check(ed.telegram_action.toolTip().startswith("Канал ClipSD"), "у пункта пояснение")
ed.canvas.modified, ed.exported = False, True
ed.close()

about = appmod.Clipshot.build_about(type("Shim", (), {"icon": appmod.make_icon()})())
about.show()
for _ in range(3):
    app.processEvents()
    QTest.qWait(10)
labels = [lbl for lbl in about.findChildren(QLabel) if "t.me/clipsdapp" in lbl.text()]
check(len(labels) == 1 and 'href="https://t.me/clipsdapp"' in labels[0].text()
      and "Новости и обновления в Telegram: t.me/clipsdapp" in labels[0].text(), "«О программе»: ссылка «Новости и обновления в Telegram»")
opened.clear()
labels[0].linkActivated.emit("https://t.me/clipsdapp")
check(opened == ["https://t.me/clipsdapp"] and not labels[0].openExternalLinks(), "ссылка открывается через sysenv.open_url, не своим средством Qt")
about.close()

# 12 языков: подписи есть и разные у разных языков, в каждой адрес канала подставлен
seen = set()
for lang in i18n.LANGUAGES:
    menu = i18n.tr_in(lang, "links.telegram_menu")
    about_text = i18n.tr_in(lang, "links.telegram_about", url=links.TELEGRAM_SHORT)
    check("Telegram" in menu and "t.me/clipsdapp" in about_text and menu != "links.telegram_menu", f"{lang}: «{menu}»")
    seen.add(menu)
check(len(seen) >= 10, "подписи переведены, а не одинаковые")
# чужой адрес t.me/clipsd нигде не встречается
bad = []
for folder, _dirs, files in os.walk(os.path.join(ROOT, "clipshot")):
    for name in files:
        if name.endswith((".py", ".json")):
            text = open(os.path.join(folder, name), encoding="utf-8").read()
            if re.search(r"t\.me/clipsd(?!app)", text):
                bad.append(name)
check(not bad, f"чужой адрес t.me/clipsd нигде не встречается {bad}")
sysenv.open_url = real_open
print(f"ИТОГ: проверок {checks[0]}, провалено: {len(failures)}")
sys.exit(1 if failures else 0)
