# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Чёткий жирный шрифт в Linux.

Ubuntu Sans в системе установлен только переменным файлом (все толщины в одном). Qt не умеет выбрать из
него настоящий жирный и утолщает обычный программно: буквы выглядят размазанными. Поэтому один раз делаем
из системного файла статические «ClipSD Sans» Regular и Bold (fontTools) и подключаем их в программу.
"""

import glob
import os
import sys
from pathlib import Path

FAMILY = "ClipSD Sans"
SOURCES = ("/usr/share/fonts/truetype/ubuntu/UbuntuSans[wdth,wght].ttf",
           "/usr/share/fonts/truetype/ubuntu/Ubuntu[wdth,wght].ttf")
STYLES = (("Regular", 400), ("Bold", 700))


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "clipsd" / "fonts"


def font_files():
    return [cache_dir() / f"ClipSDSans-{style}.ttf" for style, _w in STYLES]


def source_font():
    for path in SOURCES:
        if os.path.exists(path):
            return path
    found = glob.glob("/usr/share/fonts/**/UbuntuSans*wght*.ttf", recursive=True)
    return next((p for p in found if "Italic" not in p and "Mono" not in p), None)


def build(source: str = None) -> bool:
    """Сделать статические файлы шрифта. ~15–20 с, один раз. False — нет fontTools или исходного шрифта."""
    source = source or source_font()
    if source is None:
        return False
    try:
        from fontTools.ttLib import TTFont
        from fontTools.varLib.instancer import instantiateVariableFont
    except ImportError:
        return False
    folder = cache_dir()
    folder.mkdir(parents=True, exist_ok=True)
    for style, weight in STYLES:
        font = instantiateVariableFont(TTFont(source), {"wght": weight, "wdth": 100}, updateFontNames=True)
        for rec in font["name"].names:
            if rec.nameID in (1, 16):
                rec.string = FAMILY
            elif rec.nameID in (2, 17):
                rec.string = style
            elif rec.nameID == 4:
                rec.string = f"{FAMILY} {style}"
            elif rec.nameID == 6:
                rec.string = f"ClipSDSans-{style}"
        font["OS/2"].usWeightClass = weight
        tmp = folder / f"ClipSDSans-{style}.ttf.part"
        font.save(str(tmp))
        tmp.replace(folder / f"ClipSDSans-{style}.ttf")
    return True


CJK_FAMILIES = ["Noto Sans CJK SC", "Microsoft YaHei UI", "Microsoft YaHei", "Source Han Sans SC", "WenQuanYi Micro Hei"]


def add_cjk(qapp):
    """1.31: китайский интерфейс без квадратиков. Шрифт интерфейса остаётся прежним (его настоящее семейство
    берётся через QFontInfo); шрифты с иероглифами добавляются последними, только как запасные, и только когда
    язык интерфейса китайский: на остальных языках шрифт и знаки (например «→») те же, что в 1.29."""
    from PyQt6.QtGui import QFontInfo
    from . import i18n
    font = qapp.font()
    base = qapp.property("clipsd_base_families")
    if not base:
        base = list(font.families() or [font.family()])
        qapp.setProperty("clipsd_base_families", base)
    wanted = list(base)
    if i18n.current() == "zh":
        real = QFontInfo(font).family()   # настоящее семейство (не псевдоним «Sans Serif»): латиница и знаки из него
        wanted += [f for f in [real] + CJK_FAMILIES if f not in wanted]
    if (font.families() or [font.family()]) != wanted:
        font.setFamilies(wanted)
        qapp.setFont(font)
    if not qapp.property("clipsd_cjk_follow"):
        # любая смена языка (меню, настройки, знакомство, настройки 1.x при первом запуске) сразу меняет и запасные
        # шрифты: иначе при zh иероглифы и полноширинные 、。，：（） брал бы случайный шрифт системы (узкие, с пустотой)
        qapp.setProperty("clipsd_cjk_follow", True)
        i18n.on_change(lambda _lang: add_cjk(qapp))


def install(qapp) -> bool:
    """Подключить «ClipSD Sans» как шрифт программы. Если файлов ещё нет — сделать их в фоне к следующему запуску."""
    if sys.platform == "win32":
        add_cjk(qapp)
        return False   # Segoe UI в Windows и так со статическим жирным
    files = font_files()
    if not all(f.exists() for f in files):
        import threading
        threading.Thread(target=build, daemon=True).start()
        add_cjk(qapp)
        return False
    from PyQt6.QtGui import QFontDatabase
    for f in files:
        if QFontDatabase.addApplicationFont(str(f)) < 0:
            return False
    font = qapp.font()
    font.setFamilies([FAMILY, font.family()])
    qapp.setFont(font)
    add_cjk(qapp)
    return True


if __name__ == "__main__":   # python3 -m clipshot.fonts — сделать файлы шрифта (вызывает установщик)
    print("ClipSD: шрифт готов" if build() else "ClipSD: шрифт не собран (нет fontTools или Ubuntu Sans)")
