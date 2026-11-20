# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Группы инструментов и узкое окно редактора (1.32).

Порядок: модель групп и перенос tool_order 1.31 (группа подряд на месте своего первого инструмента, порядок внутри
сохраняется); перетаскивание (инструмент внутри группы, группа целиком, отдельная кнопка не попадает внутрь группы).
Окно: ступени сворачивания по ширине (от «Рисования» до «Надписей», «Номер», выделение и обрезка не сворачиваются),
запас 15 px у порога, минимум ширины узкого окна, второй ряд без больших кнопок, внизу значки.
Горячие клавиши: все 19 работают при свёрнутых группах, инструмент встаёт на значок группы.
Меню группы, панель «Все инструменты», инструмент по умолчанию на значке группы, выключенные распознавание и перевод.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/groups132_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import json
import os
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
os.environ.pop("CLIPSD_LANG", None)
_cfg = os.path.join(tempfile.mkdtemp(prefix="clipsd-groups132-"), "screen.json")
with open(_cfg, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1600, "height": 1000,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _cfg

from PyQt6.QtCore import QMimeData, QPoint, QPointF, Qt
from PyQt6.QtGui import QColor, QDropEvent, QImage
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMenu

app = QApplication(sys.argv)
from clipshot import app as appmod, i18n
from clipshot import editor as em
from clipshot.editor import (ARROW, BLUR, CALLOUT, COLLAPSE_ORDER, COLLAPSE_SLACK, CROP, DARROW, ELLIPSE, ERASER, FARROW,
                             FLINE, FSHAPE, GROUP_TOOLS, LINE, MARKER, MOVE, NUMBER, OCR, PENCIL, RECT, TEXT, TOOL_GROUP,
                             TOOL_MIME, TRANSLATE, EditorWindow, move_in_order, normalize_order, order_entries, tool_order)

failures = []
checks = [0]


def check(cond, msg):
    checks[0] += 1
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def settle(n=5):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(10)


class Ctx:
    def __init__(self, **kw):
        self.config = dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True, **kw)
        self.icon = appmod.make_icon()
        self.saved = 0

    def save_config(self):
        self.saved += 1

    def notify(self, text):
        pass


def image(w, h=200):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor("#ffffff"))
    return img


def mk(w=300, **kw):
    ctx = Ctx(**kw)
    ed = EditorWindow(image(w), ctx, QPoint(0, 0))
    ed.present()
    settle()
    return ed, ctx


def done(ed):
    ed.canvas.modified, ed.exported = False, True
    ed.close()
    settle(2)


STANDARD = [t for t, _g, _tip, _k in em.TOOLS]

# --- 1. модель порядка ------------------------------------------------------------------------------------
check(normalize_order([]) == STANDARD, "пустой tool_order: стандартный порядок 1.31.1")
check(normalize_order(STANDARD) == STANDARD, "стандартный порядок уже в модели групп")
check(STANDARD.index(NUMBER) == STANDARD.index(TEXT) + 1, "номер сразу после надписей, отдельной кнопкой")
entries = order_entries(STANDARD)
check([e[1] for e in entries] == [MOVE, "arrows", "shapes", "labels", NUMBER, "draw", "hide", "ocr", CROP],
      f"элементы ряда: {[e[1] for e in entries]}")
check(GROUP_TOOLS["labels"] == (CALLOUT, TEXT) and TOOL_GROUP.get(NUMBER) is None and TOOL_GROUP.get(MOVE) is None
      and TOOL_GROUP.get(CROP) is None, "надписи: выноска и текст; номер, выделение и обрезка вне групп")
# порядок владельца из 1.31 (группы перемешаны): группа встаёт на место своего первого инструмента
old = [NUMBER, ELLIPSE, MOVE, ARROW, RECT, TEXT, "unknown", LINE, ELLIPSE, CROP, PENCIL, BLUR]
norm = normalize_order(old)
check(norm[:4] == [NUMBER, ELLIPSE, RECT, FSHAPE] and norm[4] == MOVE,
      f"1.31 → 1.32: фигуры на месте эллипса, порядок внутри сохранён, новые в конце группы: {norm[:6]}")
check(norm.index(ARROW) < norm.index(LINE) and set(norm[norm.index(ARROW):norm.index(ARROW) + 5]) == set(GROUP_TOOLS["arrows"]),
      "стрелки подряд, начиная со стрелки")
check(sorted(norm) == sorted(STANDARD) and len(norm) == len(STANDARD), "все 19 инструментов, без повторов и неизвестных")
for code, tools in GROUP_TOOLS.items():
    idx = [norm.index(t) for t in tools]
    check(max(idx) - min(idx) == len(tools) - 1, f"группа {code} идёт подряд")
check(tool_order({"tool_order": old}) == norm, "tool_order(cfg) переносит сохранённый порядок")
# перетаскивание
o = list(STANDARD)
moved = move_in_order(o, LINE, o.index(ARROW))
check(moved[o.index(ARROW)] == LINE and moved[o.index(ARROW) + 1] == ARROW, "линия переставлена в начало своей группы")
moved = move_in_order(o, ELLIPSE, o.index(MOVE))
check(moved[:3] == [RECT, ELLIPSE, FSHAPE] and moved[3] == MOVE, f"эллипс вынесен за группу: переехали все фигуры {moved[:4]}")
moved = move_in_order(o, NUMBER, o.index(DARROW))
i = moved.index(NUMBER)
check(TOOL_GROUP.get(moved[i - 1]) != TOOL_GROUP.get(moved[i + 1]) or TOOL_GROUP.get(moved[i - 1]) is None,
      f"номер не попадает внутрь группы стрелок: {moved[:8]}")
moved = move_in_order(o, ARROW, o.index(CROP) + 1, whole=True)
check(moved[-5:] == list(GROUP_TOOLS["arrows"]), "кнопка группы перетащена в конец: вся группа в конце")
moved = move_in_order(o, NUMBER, 1)
check(moved[:3] == [MOVE, NUMBER, ARROW], "номер между выделением и стрелками")

# --- 2. ступени по ширине ------------------------------------------------------------------------------------
i18n.set_language("ru")
ed, ctx = mk(300)
stages = ed._stages()
need = ed._need_row1
check(all(a >= b for a, b in zip(need, need[1:])), f"каждая ступень не шире предыдущей: {need}")
check([sorted(c) for c, _l in stages][-1] == sorted(COLLAPSE_ORDER), "последняя ступень: свёрнуты все 6 групп")
check([c for c, _l in stages][1] == {"draw"} and [c for c, _l in stages][2] == {"draw", "ocr"},
      "первой сворачивается «Рисование», второй «Текст с картинки»")
rim = ed._rim()[0]
check(ed._stage == len(stages) - 1 and ed._row2_compact and ed._bottom_compact,
      f"снимок 300 px: всё свёрнуто, второй ряд и низ узкие (ступень {ed._stage})")
min_w = ed.min_content_width() + rim
check(ed.width() == min_w and ed.minimumWidth() == min_w, f"окно для узкого снимка по минимуму панелей: {ed.width()} = {min_w}")
check(ed.width() <= 800, f"узкое окно по-русски не шире 800 ({ed.width()}, было 1029)")
check(not ed.ocr_button.isVisible() and not ed.tr_block.isVisible(), "узкое окно: без больших «Копировать текст» и «Перевести»")
check(ed.save_button.text() == "" and ed.copy_button.text() == "" and ed.zoom_fit_button.text() == ""
      and ed.copy_close_button.text().strip() == "Скопировать и закрыть", "внизу значки, «Скопировать и закрыть» с подписью")
check(ed.save_button.toolTip().startswith("Сохранить") and ed.zoom_fit_button.toolTip().startswith("Показать весь снимок"),
      "у значков подсказки")
for code, gb in ed.group_buttons.items():
    check(gb.isVisible() and not any(ed.tool_buttons[t].isVisible() for t in GROUP_TOOLS[code]), f"группа {code} свёрнута в одну кнопку")
check(all(ed.tool_buttons[t].isVisible() for t in (MOVE, NUMBER, CROP)), "выделение, номер, обрезка всегда отдельными кнопками")
check(ed.more_button.isVisible() and ed.more_button.text() == "" and ed.more_button.accessibleName() == "Все инструменты"
      and ed.more_button.toolTip().startswith("Все инструменты\n") and ed.more_button.width() == em.TOOL_W,
      "«⋯ Все инструменты» видна и в узком окне (значком, название в подсказке)")


def row1_fits(ed):
    """Ничего в первом ряду не налезает: кнопки слева кончаются до кнопок справа, всё внутри панели."""
    left = max(w.geometry().right() for w in (ed.more_button,))
    right_start = min(w.geometry().left() for w in (ed.help_button, ed.settings_button, ed.language_button)
                      if w.isVisibleTo(ed.panel) and w.parentWidget() is ed.panel) if ed.help_button.parentWidget() is ed.panel else ed.panel.width()
    return left < right_start and ed.panel.layout().minimumSize().width() <= ed.panel.width()


check(row1_fits(ed), "узкое окно: первый ряд помещается")
# каждая ступень помещается ровно на своей ширине и сворачивается, если на 1 px уже
for k, (collapsed, label) in enumerate(stages):
    w = need[k]
    ed._stage = None
    ed.resize(w + rim, ed.height())
    settle(2)
    check(ed._stage == min(k, next(i for i, n in enumerate(need) if n <= w)), f"ширина {w}: ступень {ed._stage} (ожидалась {k})")
    check(row1_fits(ed), f"ступень {k}: ряд помещается")
    if k + 1 < len(stages) and need[k + 1] < need[k]:
        ed.resize(w - 1 + rim, ed.height())
        settle(2)
        check(ed._stage > k, f"на 1 px уже ступени {k}: свернулось больше ({ed._stage})")
# запас у порога: свернулось на need[3]-1, разворачивается только после need[3]+15
ed._stage = None
ed.resize(need[3] - 1 + rim, ed.height())
settle(2)
s_low = ed._stage
ed.resize(need[3] + 5 + rim, ed.height())
settle(2)
check(ed._stage == s_low, f"у порога (+5 px) группа не разворачивается обратно ({ed._stage})")
ed.resize(need[3] + COLLAPSE_SLACK + rim, ed.height())
settle(2)
check(ed._stage <= 3, f"с запасом 15 px развернулась ({ed._stage})")
ed.resize(need[0] + 40 + rim, ed.height())
settle(2)
check(ed._stage == 0 and all(ed.tool_buttons[t].isVisible() for t in STANDARD) and not any(g.isVisible() for g in ed.group_buttons.values()),
      "широкое окно: все 19 кнопок, групп нет")
check(ed.more_button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon, "широкое окно: «Все инструменты» с подписью")
done(ed)

# снимок средней ширины: окно по снимку, часть групп свёрнута
ed, ctx = mk(900)
check(ed.width() == 900 + 2 * em.FRAME_WIDTH + ed._rim()[0], f"снимок 900: окно по снимку ({ed.width()})")
check(0 < ed._stage < len(ed._stages()) - 1, f"снимок 900: свёрнута часть групп (ступень {ed._stage})")
done(ed)
ed, ctx = mk(1500)
check(ed._stage == 0 and not ed._row2_compact and not ed._bottom_compact and ed.ocr_button.isVisible(),
      "широкий снимок: всё развёрнуто, большие кнопки и подписи на месте")
done(ed)

# --- 3. горячие клавиши при свёрнутых группах ----------------------------------------------------------------
ed, ctx = mk(300)
keys = {t: k for t, _g, _tip, k in em.TOOLS}
for tool, key in keys.items():
    if tool in (OCR, TRANSLATE):
        continue   # режимы с распознаванием (своя проверка в ui1291_test)
    QTest.keyClick(ed, key.lower())
    settle(1)
    g = TOOL_GROUP.get(tool)
    ok = ed.canvas.tool == tool
    if g is not None:
        gb = ed.group_buttons[g]
        ok = ok and gb.current == tool and gb.isChecked() and gb.isVisible()
        ok = ok and not any(b.isChecked() for c, b in ed.group_buttons.items() if c != g)
    else:
        ok = ok and ed.tool_buttons[tool].isChecked()
    if tool == ERASER:
        QTest.keyClick(ed, Qt.Key.Key_Escape)
        settle(1)
    check(ok, f"клавиша {key}: {tool}" + (f", на значке группы {g}" if g else ""))
check(ctx.config.get("tool_group_last", {}).get("shapes") == FSHAPE, "последний инструмент группы запомнен в config")
# щелчок по значку группы включает её последний инструмент
ed.select_tool(ELLIPSE)
ed.select_tool(ARROW)
gb = ed.group_buttons["shapes"]
QTest.mouseClick(gb, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(12, 18))
settle(1)
check(ed.canvas.tool == ELLIPSE and gb.isChecked(), "щелчок по значку «Фигур»: эллипс, последний выбранный в группе")
# стрелка ▾ открывает меню группы
shown = []
real_exec = QMenu.exec
QMenu.exec = lambda self, *a, **k: (shown.append([(x.text(), x.font().bold(), x.isEnabled()) for x in self.actions()]), None)[1]
QTest.mouseClick(gb, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(gb.width() - 5, 18))
QMenu.exec = real_exec
check(shown and shown[0][0] == ("Фигуры", False, False), f"▾: меню группы с заголовком: {shown[:1]}")
check(shown and [t for t, _b, _e in shown[0][1:]] == ["Прямоугольник\tR", "Эллипс\tE", "Свободная фигура\tO"],
      "в меню значок, название и клавиша каждого инструмента")
check(shown and [b for _t, b, _e in shown[0][1:]] == [False, True, False], "текущий (эллипс) выделен")
menu = ed.build_group_menu("ocr")
texts = [a.text() for a in menu.actions()]
check(texts[-1] == "Перевести всё\tShift+Y" and "Копировать текст\tI" in texts, f"меню «Текст с картинки»: {texts}")
next(a for a in ed.build_group_menu("arrows").actions() if a.text().startswith("Линия")).trigger()
check(ed.canvas.tool == LINE and ed.group_buttons["arrows"].current == LINE, "пункт меню включает инструмент и ставит его на значок")
done(ed)

# --- 4. инструмент по умолчанию в свёрнутой группе ----------------------------------------------------------
ed, ctx = mk(300, tool="arrow", default_tool="ellipse", tool_group_last={"shapes": "rect"})
gb = ed.group_buttons["shapes"]
check(ed.canvas.tool == ELLIPSE and gb.current == ELLIPSE and gb.default_mark, "по умолчанию эллипс: на значке «Фигур» он, с галочкой")
ed.select_tool(RECT)
check(not gb.default_mark and gb.current == RECT, "выбран прямоугольник: галочки на значке нет")
ed2_ctx = Ctx(tool="arrow", tool_group_last={"shapes": "fshape"})
ed2 = EditorWindow(image(300), ed2_ctx, QPoint(0, 0))
check(ed2.group_buttons["shapes"].current == FSHAPE and ed2.group_buttons["labels"].current == TEXT,
      "новое окно: на значке последний инструмент группы; надписи по умолчанию «Текст»")
done(ed2)
menu = ed.build_group_menu("shapes")
default_act = next(a for a in menu.actions() if a.data() == ELLIPSE)
check(not default_act.icon().isNull(), "у инструмента по умолчанию значок с галочкой")
done(ed)

# --- 5. «Все инструменты» --------------------------------------------------------------------------------
ed, ctx = mk(300)
menu = ed.build_all_tools_menu()
rows = ed.all_tools_rows
check(set(rows) == set(STANDARD) | {"translate_all"}, f"все 19 инструментов и «Перевести всё»: {len(rows)}")
check(rows[ELLIPSE].key == "E" and rows["translate_all"].key == "Shift+Y" and rows[MOVE].text() == "Выделение и перемещение",
      "у строк название и клавиша")
sections = ed.all_tools_sections()
check(sections[0][0] == "Основные" and sections[0][1] == [MOVE, NUMBER, CROP] and len(sections) == 7, "разделы: основные и 6 групп")
check(len(em.split_columns(sections, 3)) == 3, "три столбца")
rows[BLUR].click()
check(ed.canvas.tool == BLUR and ed.group_buttons["hide"].current == BLUR, "щелчок по строке включает инструмент")
done(ed)

# --- 6. перетаскивание в окне -----------------------------------------------------------------------------
ed, ctx = mk(1500)
strip = ed.tool_strip


def drop(payload, x):
    mime = QMimeData()
    mime.setData(TOOL_MIME, payload.encode())
    ev = QDropEvent(QPointF(x, 10), Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    strip.dropEvent(ev)
    settle(1)


rect_x = ed.tool_buttons[RECT].geometry().left() + 2
drop(FSHAPE, rect_x)
check(strip.order()[strip.order().index(FSHAPE) + 1] == RECT and ctx.config["tool_order"] == strip.order(),
      "свободная фигура переставлена внутри «Фигур» и записана в tool_order")
drop(ELLIPSE, ed.tool_buttons[MOVE].geometry().left() + 2)
check(strip.order()[:3] == [FSHAPE, RECT, ELLIPSE] and strip.order()[3] == MOVE, f"эллипс вынесли за группу: все фигуры в начале {strip.order()[:4]}")
ed.resize(ed._need_row1[-1] + ed._rim()[0], ed.height())
settle(2)
drop("group:arrows", ed.tool_buttons[CROP].geometry().right() + 5)
check(strip.order()[-5:] == [ARROW, DARROW, FARROW, FLINE, LINE], "кнопку свёрнутой группы тащили: стрелки целиком в конце")
next(a for a in ed.build_tool_menu(RECT).actions() if a.text().startswith("Вернуть")).trigger()
check(strip.order() == STANDARD, "«Вернуть стандартный порядок»")
done(ed)

# --- 7. распознавание и перевод выключены ---------------------------------------------------------------------
ed, ctx = mk(300, translate_enabled=False)
check(not ed.group_buttons["ocr"].isVisible() and ed.tool_buttons[OCR].isVisible() and not ed.tool_buttons[TRANSLATE].isVisible(),
      "перевод выключен: «Текст с картинки» одной кнопкой распознавания")
check("Перевести всё\tShift+Y" not in [a.text() for a in ed.build_group_menu("ocr").actions()], "в меню нет «Перевести всё»")
done(ed)
ed, ctx = mk(300, translate_enabled=False, ocr_enabled=False)
check(not ed.group_buttons["ocr"].isVisible() and not ed.tool_buttons[OCR].isVisible(), "оба выключены: группы нет")
check([s for s, _t in ed.all_tools_sections()][-1] != "Текст с картинки", "в «Все инструменты» раздела нет")
done(ed)

# --- 8. ластик в узком окне: «Целиком / Частично» помещаются ------------------------------------------------
ed, ctx = mk(300)
w0 = ed.width()
ed.select_tool(ERASER)
settle(3)
ok = all(b.width() >= b.fontMetrics().horizontalAdvance(b.text()) for b in ed.eraser_group.buttons())
check(ok and ed.panel.layout().minimumSize().width() <= ed.panel.width(), f"ластик: подписи режима не обрезаны (окно {w0} → {ed.width()})")
done(ed)

# --- 9. 12 языков: узкое окно и ни одна подпись не обрезана -----------------------------------------------------
from PyQt6.QtWidgets import QAbstractButton  # noqa: E402
widths = {}
for lang in i18n.LANGUAGES:
    i18n.set_language(lang)
    ed, ctx = mk(300)
    widths[lang] = ed.width()
    check(ed.width() <= 900, f"{lang}: окно для снимка 300 px не шире 900 ({ed.width()})")
    check(row1_fits(ed), f"{lang}: первый ряд помещается")
    for host in (ed.panel, ed.bottom):
        for w in host.findChildren(QAbstractButton):
            if w.isVisible() and w.text().strip() and not isinstance(w, em.ToolRow):
                need_w = w.fontMetrics().horizontalAdvance(w.text().replace("&", ""))
                check(w.width() >= need_w, f"{lang}: «{w.text().strip()}» не обрезана ({w.width()} < {need_w})")
    done(ed)
i18n.set_language("ru")
print("Ширина окна для снимка 300 px:", widths)

# --- 10. метрики шрифтов Windows (эмуляция: Liberation Sans с шириной Arial и DejaVu Sans как худший случай, 9 pt):
# узкое окно, ластик (нижняя строка после пересчёта не шире окна), смена языка ru → bg в окне 780 px (замечание
# владельца на Windows 1.31.1: правые кнопки срезаны) --------------------------------------------------------------
from PyQt6.QtGui import QFont, QFontDatabase, QFontMetrics  # noqa: E402
base_font = app.font()


def fits_all(ed, tag):
    ok = True
    for host in (ed.panel, ed.bottom, ed.top_icons):
        for b in host.findChildren(QAbstractButton):
            if b.isVisible() and b.text().strip() and not isinstance(b, em.ToolRow):
                f = QFont(b.font())
                if b.objectName() in ("ocrButton", "trAllButton", "trButton", "finish"):
                    f.setBold(True)
                need_w = QFontMetrics(f).horizontalAdvance(b.text().replace("&", "").strip())
                if b.width() < need_w:
                    ok = False
                    print(f"   {tag}: «{b.text().strip()}» {b.width()} < {need_w}")
    width = ed.content.width()
    for row, side in ((ed.panel_row1, 16), (ed.panel_row2, 16), (ed.bottom.layout(), 0)):
        if row.minimumSize().width() > width - side:
            ok = False
            print(f"   {tag}: ряд {row.minimumSize().width()} шире места {width - side}")
    return ok


for family in ("Liberation Sans", "DejaVu Sans"):
    if family not in QFontDatabase.families():
        print(f"skip: нет шрифта {family}")
        continue
    app.setFont(QFont(family, 9))
    mins = {}
    for lang in ("ru", "de", "bg", "uk"):
        i18n.set_language(lang)
        ed, ctx = mk(300)
        mins[lang] = ed.width()
        check(fits_all(ed, f"{family} {lang}"), f"{family} 9 pt, {lang}: узкое окно {ed.width()} px, ничего не срезано")
        ed.resize(400, ed.height())
        settle(2)
        check(ed.width() == ed.minimumWidth() and fits_all(ed, f"{family} {lang} min"), f"{family} {lang}: сжимается до минимума {ed.width()}")
        ed.select_tool(ERASER)
        settle(2)
        check(fits_all(ed, f"{family} {lang} ластик"), f"{family} {lang}: ластик, нижняя строка и палитра помещаются ({ed.width()})")
        done(ed)
    i18n.set_language("ru")
    ed, ctx = mk(300)
    i18n.set_language("bg")
    ed.retranslate()
    settle(3)
    ed.resize(780, ed.height())
    settle(2)
    check(fits_all(ed, f"{family} ru→bg 780"), f"{family}: смена языка ru → bg в окне 780 px, правые кнопки не срезаны")
    done(ed)
    print(f"{family} 9 pt, минимальная ширина окна:", mins)
app.setFont(base_font)
i18n.set_language("ru")
print(f"ИТОГ: проверок {checks[0]}, провалено: {len(failures)}")
sys.exit(1 if failures else 0)
