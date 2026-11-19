# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Подсказка в поле почты MyMemory (настройки, раздел «Перевод») видна целиком на 12 языках при ширине экрана
1280, 800 и 480, и даже если текст подсказки длиннее обычного (поле не уже подсказки).
Каждая ширина экрана: отдельный процесс (экран offscreen задаётся при старте Qt).
Запуск: python3 tests/email_hint_test.py"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LONG = "email: 50,000 characters a day instead of 5,000 (a much longer hint than usual)"


def child(width: int) -> int:
    cfg = os.path.join(tempfile.mkdtemp(prefix="clipsd-email-"), "screen.json")
    with open(cfg, "w", encoding="utf-8") as f:
        json.dump({"screens": [{"name": "d", "x": 0, "y": 0, "width": width, "height": 900,
                                "logicalDpi": 96, "logicalBaseDpi": 96}]}, f)
    os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + cfg
    os.environ.pop("CLIPSD_LANG", None)
    sys.path.insert(0, ROOT)
    from PyQt6.QtGui import QFontMetrics
    from PyQt6.QtWidgets import QApplication
    app = QApplication([])
    from clipshot import app as appmod, fonts, i18n, settings as st
    fonts.install(app)
    st.autostart_enabled = lambda: False
    st.GnomeHotkeys.available = staticmethod(lambda: False)
    bad = []
    for long_hint in (False, True):
        for lang in i18n.LANGUAGES:
            i18n.set_language(lang)
            if long_hint:
                i18n._load(lang)["settings.tr_email_ph"] = LONG
            dlg = st.SettingsDialog(dict(appmod.DEFAULTS))
            dlg.show()
            app.processEvents()
            need = QFontMetrics(dlg.tr_email.font()).horizontalAdvance(dlg.tr_email.placeholderText())
            ok = need < dlg.tr_email.width() - 20
            print(("OK   " if ok else "FAIL ") + f"{width} {lang}{' (длинная)' if long_hint else ''}: "
                  f"подсказка {need} в поле {dlg.tr_email.width()}")
            if not ok:
                bad.append(lang)
            dlg.close()
            dlg.deleteLater()
    return 1 if bad else 0


if __name__ == "__main__":
    if len(sys.argv) > 1:
        code = child(int(sys.argv[1]))
        from clipshot.exitutil import quick_exit   # no Qt teardown at exit
        quick_exit(code)
    failed = []
    for w in (1280, 800, 480):
        r = subprocess.run([sys.executable, os.path.abspath(__file__), str(w)], capture_output=True, text=True, timeout=600)
        lines = [ln for ln in r.stdout.splitlines() if ln.startswith(("OK", "FAIL"))]
        print("\n".join(ln for ln in lines if ln.startswith("FAIL")) or f"OK   ширина {w}: {len(lines)} проверок")
        if r.returncode != 0 or len(lines) != 24:
            failed.append(w)
            print(r.stderr[-800:])
    print("ИТОГ:", "все проверки пройдены" if not failed else f"провалено при ширине {failed}")
    sys.exit(1 if failed else 0)
