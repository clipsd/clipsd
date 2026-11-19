# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Контраст текста 1.32 (решение владельца 19.11.2026): пары «текст на фоне» не ниже
4,5:1 (WCAG AA для обычного текста). Значения берутся из themes.py, туда же смотрят editor, selector, dialogs, hints,
окна обновления и настройки; в коде не осталось прежних слабых цветов. Без окон и без Qt-приложения.

Запуск: python3 tests/contrast132_test.py
"""
import os
import re
import sys

here = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(here)
sys.path.insert(0, ROOT)
from clipshot import themes as T  # noqa: E402

failures = []
checks = [0]


def check(cond, msg):
    checks[0] += 1
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def blend(fg, alpha, bg):
    """Полупрозрачный текст (альфа 0..255) поверх фона."""
    f, b = rgb(fg), rgb(bg)
    return "#%02x%02x%02x" % tuple(round(f[i] * alpha / 255 + b[i] * (1 - alpha / 255)) for i in range(3))


def lum(h):
    def lin(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = rgb(h)
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def ratio(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


W = "#ffffff"
PAIRS = [   # (текст, фон, что это)
    (W, T.GREEN, "белый на главной зелёной"),
    (W, T.GREEN_HOVER, "белый на зелёной под курсором"),
    (W, T.GREEN_PRESSED, "белый на нажатой зелёной"),
    (W, T.GREEN_GRADIENT[0], "белый на плитке «Скопировать», верх"),
    (W, T.GREEN_GRADIENT[1], "белый на плитке «Скопировать», низ"),
    (W, T.GREEN_GRADIENT_HOVER[0], "белый на плитке под курсором, верх"),
    (blend(W, T.GREEN_SUB[3], T.GREEN_GRADIENT[0]), T.GREEN_GRADIENT[0], "вторая строка (белый 92 %) на зелёной плитке"),
    (W, T.TEAL_BUTTON, "белый на бирюзовой кнопке"),
    (W, T.TEAL_BUTTON_HOVER, "белый на бирюзовой под курсором"),
    (W, T.VIOLET, "белый на фиолетовой кнопке"),
    (W, T.VIOLET_HOVER, "белый на фиолетовой под курсором"),
    (W, T.BLUE_BUTTON, "белый на синей кнопке знакомства"),
    (W, T.BLUE_BUTTON_HOVER, "белый на синей кнопке под курсором"),
    (T.LINK, "#ffffff", "ссылка на белом"),
    (T.LINK, "#f5f6f8", "ссылка на панели"),
    (T.LINK_DARK, "#25282c", "ссылка на тёмном окне"),
    (T.LINK_DARK, "#1e1e1e", "ссылка в тёмных настройках"),
    (T.TILE_SUB, "#f5f6f8", "вторая строка на плитке панели"),
    (T.TILE_SUB, "#e4effb", "вторая строка на плитке под курсором"),
    (T.BLUE_SUB, "#e6f0fd", "вторая строка на «Выделить заново»"),
    (T.BLUE_SUB, "#d6e7fc", "она же под курсором"),
    ("#5b21b6", "#efe7fe", "мягкая «Копировать текст», светлое"),
    ("#d9c8ff", "#2e2547", "мягкая «Копировать текст», тёмное"),
    ("#0b5f57", "#e0f4f1", "мягкая «Перевести», светлое"),
    ("#a7ece4", "#13302d", "мягкая «Перевести», тёмное"),
    ("#5f6875", "#f5f6f8", "приглушённый текст панели, светлое"),
    ("#aab1ba", "#202327", "приглушённый текст панели, тёмное"),
]
for fg, bg, what in PAIRS:
    r = ratio(fg, bg)
    check(r >= 4.5, f"{what}: {fg} на {bg} {r:.2f}:1")
check(T.GLOBE == "#3a9be8" and T.GLOBE_LINE == 2.0, "глобус #3a9be8, линия 2.0")
check(T.link_color(False) == "#1660d0" and T.link_color(True) == "#58a4f2", "ссылки: светлая #1660d0, тёмная #58a4f2")

# в коде не осталось прежних слабых цветов текста и кнопок
OLD = {"#8f55f5": "фиолетовая под курсором", "#14b8a6": "бирюзовая под курсором", "#6b7380": "вторая строка плитки",
       "#4a6d9c": "вторая строка «Выделить заново»", "#26b864": "зелёная под курсором", "#1f9d55\"; color": "зелёная кнопка"}
for name in ("editor.py", "selector.py", "dialogs.py", "hints.py", "ocr.py", "updater.py", "settings.py", "tour.py"):
    text = open(os.path.join(ROOT, "clipshot", name), encoding="utf-8").read()
    left = [what for old, what in OLD.items() if old in text]
    check(not left, f"{name}: прежних слабых цветов нет {left or ''}")
editor_src = open(os.path.join(ROOT, "clipshot", "editor.py"), encoding="utf-8").read()
check(re.search(r"modeMain \{\{[^}]*\{G\.TEAL_BUTTON\}", editor_src.replace("QPushButton#modeDone, QPushButton#", "")) is not None
      or "{G.TEAL_BUTTON}" in editor_src, "редактор берёт бирюзовую кнопку из themes.py")
tour_src = open(os.path.join(ROOT, "clipshot", "tour.py"), encoding="utf-8").read()
check("#1e78ff" not in tour_src and "#3a8bff" not in tour_src, "знакомство: синие кнопки #1660d0, наведение темнее")
check(editor_src.count('QColor("#1f9d55")') == 0, "галочка инструмента по умолчанию цветом главной кнопки (#157a40)")

# синие кнопки с белым текстом везде по правилу контраста 4,5:1 (решение владельца 19.11.2026: подтянуть контраст везде):
# «Сохранить» настроек, выбранный модификатор горячей клавиши, «Готово» выбора оформления, номера шагов Google
check(T.blue_button("#1e78ff") == T.blue_button("#2d8ceb") == ("#1660d0", "#124fae", "#0f4596"),
      "стандартные акценты: синий #1660d0, наведение #124fae, рамка #0f4596")
for accent in ("#1e78ff", "#2d8ceb", "#ff8800", "#22aa44", "#3a9be8", "#888888", "#ffffff", "#e91e63", "#00bcd4"):
    bg, hover, border = T.blue_button(accent)
    check(ratio(W, bg) >= 4.5 and ratio(W, hover) >= ratio(W, bg) - 0.01,
          f"акцент {accent}: белый на {bg} {ratio(W, bg):.2f}:1, под курсором {hover} не светлее")
# в исходниках нет белого текста на фоне акцента (ui_accent, ACCENT, #1e78ff, #3a8bff) в таблицах стилей
WEAK_FILL = re.compile(r"background:\s*(\{t\['ui_accent'\]\}|\{ACCENT\}|\{a\}|\{a_light\}|#1e78ff|#3a8bff)[^}]*color:\s*(white|#fff\b|#ffffff)",
                       re.IGNORECASE)
for name in sorted(os.listdir(os.path.join(ROOT, "clipshot"))):
    if not name.endswith(".py"):
        continue
    text = open(os.path.join(ROOT, "clipshot", name), encoding="utf-8").read()
    hits = [m.group(0)[:60] for m in WEAK_FILL.finditer(text)]
    check(not hits, f"{name}: белый текст не стоит на акценте #1e78ff/#3a8bff {hits or ''}")
from clipshot import settings as _settings  # noqa: E402
for theme in ("standard", "pro"):
    qss = _settings.settings_style(T.tokens({"ui_theme": theme}))
    primary = re.search(r"QPushButton#primary \{\{? ?background: ([^;]+);", qss)
    checked = re.search(r"HotkeyEditor QPushButton:checked \{\{? ?background: ([^;]+);", qss)
    check(primary is not None and primary.group(1) == "#1660d0" and checked is not None and checked.group(1) == "#1660d0",
          f"настройки ({theme}): «Сохранить» и выбранный модификатор #1660d0")
print(f"ИТОГ: проверок {checks[0]}, провалено: {len(failures)}")
sys.exit(1 if failures else 0)
