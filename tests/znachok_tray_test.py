# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""1.36: новый значок области уведомлений. Проверки: у трея набор 16-64, он не совпадает с логотипом программы,
логотип окон не изменился, файлы лежат в пакете (их берёт --collect-data clipshot) и в сборках.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/znachok_tray_test.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
from clipshot import icons  # noqa: E402

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


icon = icons.tray_icon()
sizes = {s.width() for s in icon.availableSizes()}
check(set(icons.TRAY_SIZES) <= sizes, f"в QIcon трея размеры {sorted(sizes)}")
for size in icons.TRAY_SIZES:
    pm = icon.pixmap(size, size)
    img = pm.toImage()
    check(pm.width() >= size and not img.isNull(), f"{size} px: картинка есть")
    corner = img.pixelColor(0, 0).alpha()
    mid = img.pixelColor(img.width() // 2, img.height() - 3)
    check(corner < 255 and mid.alpha() == 255, f"{size} px: скруглённый угол прозрачный, середина закрашена")
    check(mid.blue() > mid.red(), f"{size} px: синий/бирюзовый тон")

old = icons.app_icon().pixmap(32, 32).toImage()
new = icon.pixmap(32, 32).toImage()
check(old != new, "значок трея отличается от логотипа программы")
check(icons.app_icon().availableSizes() != [] and 256 in {s.width() for s in icons.app_icon().availableSizes()},
      "логотип программы (app_icon) прежний: размеры до 256")

# трей создаётся из tray_icon(), окна из make_icon()
src = (ROOT / "clipshot" / "app.py").read_text(encoding="utf-8")
check("QSystemTrayIcon(tray_icon()" in src, "app.py: QSystemTrayIcon получает tray_icon()")
check("qapp.setWindowIcon(make_icon())" in src, "app.py: значок окон остался make_icon()")

# файлы в ресурсах: папка внутри пакета clipshot, сборки берут пакет целиком
folder = icons.tray_icon_dir()
for size in icons.TRAY_SIZES:
    check((folder / f"tray-{size}.png").is_file(), f"файл tray-{size}.png в пакете")
check((folder / "tray.svg").is_file(), "мастер tray.svg в пакете")
check(folder.parent.name == "clipshot", "папка значка внутри пакета clipshot")
for script in ("packaging/linux/build_linux.sh", "packaging/windows-exe/build.ps1"):
    text = (ROOT / script).read_text(encoding="utf-8")
    check("--collect-data clipshot" in text, f"{script}: --collect-data clipshot забирает tray_icons")
stage = (ROOT / "packaging" / "stage_windows.py").read_text(encoding="utf-8")
check('ROOT / "clipshot", out / "clipshot"' in stage and "ignore_patterns(\"__pycache__\")" in stage,
      "stage_windows.py копирует пакет clipshot целиком (png не отсекаются)")
inst = (ROOT / "install.sh").read_text(encoding="utf-8")
check('cp -r "$SRC/clipshot"' in inst, "install.sh копирует пакет целиком")

print("ИТОГ:", "ВСЁ ХОРОШО" if not failures else f"провалено {len(failures)}")
sys.exit(1 if failures else 0)
