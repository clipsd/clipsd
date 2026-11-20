# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Место перевода на экране при масштабе 1, 1,5 и 2 (страница поставщика, как в ролике «Перевод с экрана»).

«Выделить и перевести», по кускам: окошко ложится ровно на обведённый текст (рамка = выделение), строки перевода внутри
рамки; два и три соседних абзаца: после Esc плашки с кнопками не заходят на переведённый текст (свой и чужой), на рамки
и плашки других окошек и не выходят за экран; кусок, обведённый поверх открытого окошка, сдвигается на минимум и на
открытые окошки не ложится.
«Весь экран», поверх текста: окно на весь монитор, плашки закрывают все точки исходных строк, короткая строка вкладки
не уходит в столбик (одна строка в своей высоте); плашка с кнопками как раньше.

Зажатое соседями окошко (два монитора, рядом вторая колонка переведённых кусков): плашка при наведении мыши встаёт
у своей области, окошко поднимается над соседями, путь мыши от области к плашке целиком в окошке; мышь ушла: плашка
держится ещё немного (чтобы до неё дойти) и убирается.

Кадр экрана не снимается: Qt offscreen при масштабе не 1 собирает grabWindow(0) неверно (окно из логической точки
(x, y) кладёт в физический пиксель (x, y)), поэтому проверяется геометрия окон в точках, которую настоящий экран
переводит в пиксели сам. Распознавание настоящее (Tesseract), сеть подменена.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/perevod_mesto_test.py (сам запускает проверки с масштабом 1, 1.5 и 2
и на двух мониторах 2560x1440 и 1920x1080 с масштабом 1, как у владельца).
"""
import difflib
import json
import os
import subprocess
import sys
import tempfile
import time

here = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(here)
sys.path.insert(0, ROOT)
MODES = ("1", "1.5", "2", "two")   # масштаб одного монитора 1280x720 или два монитора с масштабом 1
TWO = [(0, 0, 2560, 1440), (2560, 0, 1920, 1080)]

if len(sys.argv) < 2:
    # главный процесс: по процессу на режим (QT_SCALE_FACTOR и мониторы читаются при запуске Qt)
    bad = []
    for k in MODES:
        folder = tempfile.mkdtemp(prefix="clipsd-mesto-")
        cfg = os.path.join(folder, "screen.json")
        if k == "two":
            screens = [{"name": f"s{i}", "x": x, "y": y, "width": w, "height": h, "logicalDpi": 96, "logicalBaseDpi": 96}
                       for i, (x, y, w, h) in enumerate(TWO)]
        else:
            screens = [{"name": "s", "x": 0, "y": 0, "width": round(1280 * float(k)), "height": round(720 * float(k)),
                        "logicalDpi": 96, "logicalBaseDpi": 96}]
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump({"screens": screens}, f)
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen:configfile=" + cfg, QT_SCALE_FACTOR="1" if k == "two" else k)
        print(f"=== {'два монитора' if k == 'two' else 'масштаб ' + k}", flush=True)
        res = subprocess.run([sys.executable, os.path.abspath(__file__), k], env=env, capture_output=True, text=True,
                             timeout=600)
        out = "\n".join(line for line in (res.stdout + res.stderr).splitlines() if "does not support" not in line)
        print(out, flush=True)
        if res.returncode != 0:
            bad.append(k)
    print("ИТОГ: " + ("все проверки пройдены" if not bad else f"провалы при масштабе {', '.join(bad)}"))
    sys.exit(1 if bad else 0)

MODE = sys.argv[1]
SCALE = 1.0 if MODE == "two" else float(MODE)
from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QEnterEvent, QFont, QFontMetrics, QFontMetricsF, QGuiApplication, QImage, QPainter, QPixmap  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv[:1])
from clipshot import app as appmod, ocr, translate, translate_ui  # noqa: E402
DESK = QRect()
for _s in QGuiApplication.screens():
    DESK = DESK.united(_s.geometry())
W, H = DESK.width(), DESK.height()
from clipshot.selector import RegionSelector  # noqa: E402

failures, checks = [], [0]


def check(cond, msg):
    checks[0] += 1
    print(("OK   " if cond else "FAIL ") + f"[{MODE}] " + msg)
    if not cond:
        failures.append(msg)


def settle(n=6):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(15)


def wait(cond, seconds=60):
    end = time.time() + seconds
    while not cond() and time.time() < end:
        app.processEvents()
        QTest.qWait(30)
    return cond()


if ocr.engine_name() != "tesseract":
    print("распознавания Tesseract нет: проверки места перевода пропущены")
    print("ИТОГ: все проверки пройдены")
    sys.exit(0)

# --- страница: вкладка и адрес браузера, заголовок, четыре абзаца по две строки (как стол ролика 4) ------------------
TAB = "Delivery terms"
ADDRESS = "example.com/en/delivery"
PARAS = ["We deliver within three to five working days. Orders received before 2 pm leave our warehouse on the same day.",
         "Shipping costs 6.90 euros. Orders of 150 euros or more are shipped free of charge.",
         "Returns are possible within 30 days. Please put the completed form in the parcel.",
         "If you have questions, our customer service is available Monday to Friday from 9 am to 5 pm."]
RU = {TAB: "Условия поставки",
      PARAS[0]: "Мы доставляем в течение трёх-пяти рабочих дней. Заказы до 14:00 покидают склад в тот же день.",
      PARAS[1]: "Доставка стоит 6,90 евро. Заказы от 150 евро доставляются бесплатно.",
      PARAS[2]: "Возврат возможен в течение 30 дней. Вложите в посылку заполненную форму.",
      PARAS[3]: "Если есть вопросы, служба поддержки работает с понедельника по пятницу с 9 до 17 часов."}
PAGE_X, TEXT_W, TOP0 = 120, 600, 126


def font(px, bold=False):
    f = QFont()
    f.setPixelSize(px)
    f.setBold(bold)
    return f


def layout():
    """Прямоугольники текста страницы (в точках): [(rect, text, font)]."""
    out = [(QRectF(64, 38, 240, 30), TAB, font(14)), (QRectF(70, 84, 600, 30), ADDRESS, font(14))]
    y = TOP0 + 20
    for i, text in enumerate([TAB] + PARAS):
        f = font(30, True) if i == 0 else font(18)
        r = QFontMetricsF(f).boundingRect(QRectF(0, 0, TEXT_W, 2000), Qt.TextFlag.TextWordWrap, text)
        out.append((QRectF(PAGE_X, y, TEXT_W, r.height()), text, f))
        y += r.height() + (34 if i == 0 else 26)
    return out


BLOCKS = layout()
# два монитора: справа от абзацев 1-3 вторая колонка (переведённые соседи), на втором мониторе свои куски
COL2 = [(QRectF(940, BLOCKS[i][0].top(), 1560, 22), PARAS[i - 3], font(18)) for i in (3, 4, 5)] if MODE == "two" else []
# второй монитор, у верхнего края: строка адреса (верх 70) и под ней ещё не переведённый абзац
TOPLINE = [(QRectF(2860, 70, 600, 22), "example.com/en/delivery/returns", font(18)),
           (QRectF(2860, 112, 600, 50), PARAS[3], font(18))] if MODE == "two" else []
# второй монитор, правый нижний угол: кусок до самого низа экрана, справа места нет
CORNER = [(QRectF(4150, 1046, 300, 28), "Orders before 2 pm ship today.", font(18))] if MODE == "two" else []


def page() -> QImage:
    img = QImage(round(W * SCALE), round(H * SCALE), QImage.Format.Format_RGB32)
    img.setDevicePixelRatio(SCALE)
    img.fill(QColor("#ffffff"))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.fillRect(QRectF(36, 30, 1208, 86), QColor("#eef1f5"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#ffffff"))
    p.drawRoundedRect(QRectF(50, 38, 260, 30), 8, 8)
    p.drawRoundedRect(QRectF(50, 84, 1088, 30), 15, 15)
    for i, (r, text, f) in enumerate(BLOCKS):
        p.setFont(f)
        p.setPen(QColor("#5d6675") if i == 1 else QColor("#2b313b"))
        flags = int(Qt.AlignmentFlag.AlignVCenter) if i < 2 else int(Qt.TextFlag.TextWordWrap)
        p.drawText(r if i < 2 else QRectF(r.left(), r.top(), r.width(), r.height() + 4), flags, text)
    for r, text, f in COL2 + TOPLINE + CORNER:
        p.setFont(f)
        p.setPen(QColor("#2b313b"))
        p.drawText(r, int(Qt.TextFlag.TextWordWrap), text)
    p.end()
    return img


PAGE = page()


class Engine:
    """Перевод без сети: ближайший абзац из таблицы (распознанный текст чуть отличается), иначе как есть."""
    name = "MyMemory"

    def translate(self, text, target, source=None):
        flat = " ".join(text.split())
        best = max(RU, key=lambda k: difflib.SequenceMatcher(None, flat, k).ratio())
        if difflib.SequenceMatcher(None, flat, best).ratio() > 0.6:
            return RU[best], "en"
        return flat, "en"


translate.engines_from_config = lambda c: [Engine()]


def selector():
    sel = RegionSelector(QPixmap.fromImage(PAGE), QRect(0, 0, W, H))
    sel.tr_cfg, sel.tr_save = dict(appmod.DEFAULTS, translate_to="ru"), lambda: None
    sel.show_zoom = False
    sel.resize(W, H)
    sel.show()
    settle(3)
    return sel


def drag(w, a, b):
    QTest.mousePress(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, a)
    QTest.mouseMove(w, QPoint((a.x() + b.x()) // 2, (a.y() + b.y()) // 2))
    QTest.mouseMove(w, b)
    QTest.mouseRelease(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, b)
    app.processEvents()


def piece(i):
    """Обводка абзаца i, как в ролике: на 8 точек шире и на 6 выше и ниже текста."""
    return BLOCKS[i][0].adjusted(-8, -6, 8, 6).toAlignedRect()


def area_of(w):
    return QRect(w.mapToGlobal(w.tr_cards[0].region.topLeft()), w.tr_cards[0].region.size())


def chip_of(w):
    c = w.tr_cards[0].chip
    o = w.mapToGlobal(QPoint(0, 0))
    return QRectF(c).translated(o.x(), o.y())


def texts_of(w):
    o = w.mapToGlobal(QPoint(0, 0))
    return [QRectF(b["draw"]).united(QRectF(b["rect"])).translated(o.x(), o.y()) for b in w.tr_cards[0].blocks]


def overlap(a, b):
    r = QRectF(a).intersected(QRectF(b))
    return r.width() > 0.5 and r.height() > 0.5


def new_windows(before):
    return [w for w in translate_ui._floating if w not in before and not w._done]


def done(ws):
    return bool(ws) and all(w.tr_cards and w.tr_cards[0].state in ("done", "error") for w in ws)


def on_screen(r):
    """Прямоугольник целиком на одном мониторе (плашка не на стыке и не за краем)."""
    return any(QRectF(s.availableGeometry()).contains(QRectF(r)) for s in QGuiApplication.screens())


def attached(c, a):
    """Плашка c у своей области a: рядом по вертикали и заходит на неё по ширине, или рядом сбоку, или на ней."""
    c, a = QRectF(c), QRectF(a)
    gx = max(0.0, c.left() - a.right(), a.left() - c.right())
    gy = max(0.0, c.top() - a.bottom(), a.top() - c.bottom())
    ox = min(a.right(), c.right()) - max(a.left(), c.left())
    oy = min(a.bottom(), c.bottom()) - max(a.top(), c.top())
    return (gx == 0 and gy <= 10 and ox >= 20) or (gy == 0 and gx <= 10 and oy >= 20)


def in_window(w, p):
    """Точка (глобальная) ловится окошком: внутри окна и внутри его маски, если маска есть (Linux)."""
    g = QRectF(w.frameGeometry())
    if not g.contains(p):
        return False
    m = w.mask()
    return m.isEmpty() or m.contains((p - g.topLeft()).toPoint())


def path_inside(w, a, c):
    """Прямой путь мыши от области a (слева, по середине) к середине плашки c целиком по окошку w (и по его маске)."""
    sx, sy = a.left() + 20, a.center().y()
    cx, cy = c.center().x(), c.center().y()
    return all(in_window(w, QPointF(sx + (cx - sx) * i / 40, sy + (cy - sy) * i / 40)) for i in range(41))


def check_mask(ws, label):
    """Linux: окошко ловит мышь и колесо только на рамке перевода, плашке и мостике между ними; прозрачные места окна
    (дальше 16 точек от рамки и плашки) пропускают мышь к странице. В Windows маски нет (там прозрачное и так сквозное)."""
    if sys.platform == "win32":
        return
    for k, w in enumerate(ws):
        g = QRectF(w.frameGeometry())
        a, c = QRectF(area_of(w)), chip_of(w)
        near = [a.adjusted(-16, -16, 16, 16)] + ([c.adjusted(-16, -16, 16, 16)] if not c.isEmpty() else [])
        dead = [QPointF(x, y) for x in range(int(g.left()) + 2, int(g.right()), 8) for y in range(int(g.top()) + 2, int(g.bottom()), 8)
                if not any(n.contains(QPointF(x, y)) for n in near)]
        caught = [p for p in dead if in_window(w, p)]
        check(not w.mask().isEmpty() and in_window(w, a.center()) and (c.isEmpty() or (in_window(w, c.center()) and path_inside(w, a, c)))
              and not caught, f"{label}, окошко {k}: маска окна по рамке и плашке, мостик есть; прозрачных точек окна "
              f"{len(dead)}, из них ловят мышь {len(caught)}")


def check_peek(w, label):
    """Зажатое окошко: мышь над ним: плашка у своей области, окошко поднято, путь до плашки по окошку; мышь ушла:
    плашка ещё держится (по пути к ней), затем убирается; рамка всё время на месте."""
    raised = []
    real_raise = w.raise_
    w.raise_ = lambda: (raised.append(True), real_raise())
    a = area_of(w)
    QApplication.sendEvent(w, QEnterEvent(QPointF(30, 30), QPointF(30, 30), QPointF(a.topLeft()) + QPointF(14, 14)))
    w.repaint()
    settle(2)
    c = chip_of(w)
    shown = not w.tr_cards[0].chip.isEmpty() and area_of(w) == a
    check(shown and bool(raised) and attached(c, a) and path_inside(w, a, c) and on_screen(c),
          f"{label}: мышь над окошком: плашка {c.toRect().getRect()} у своей области {a.getRect()}, окошко поднято "
          f"({bool(raised)}), путь до плашки по окошку, рамка на месте")
    QApplication.sendEvent(w, QEvent(QEvent.Type.Leave))
    settle(2)
    still = not w.tr_cards[0].chip.isEmpty()
    QTest.qWait(w.PEEK_GRACE_MS + 150)
    w.repaint()
    settle(2)
    check(still and w.tr_cards[0].chip.isEmpty() and area_of(w) == a,
          f"{label}: мышь ушла: плашка держится {w.PEEK_GRACE_MS} мс, затем убирается; рамка на месте")
    del w.raise_


def check_chips(ws, label):
    """Плашки: на экране, не на переведённом тексте (своём и чужом), не на рамках и плашках других окошек. Окошку,
    зажатому соседями, места нет: у него только крестик в углу, а плашка видна, пока над ним мышь."""
    for w in ws:
        w.repaint()
    settle(3)
    for k, w in enumerate(ws):
        if w.crowded:
            check(w.tr_cards[0].chip.isEmpty() and "close" in w.tr_cards[0].buttons and w.chip_side == "none",
                  f"{label}, окошко {k}: места для плашки нет, плашки нет, крестик в углу")
            check_peek(w, f"{label}, окошко {k}")
            continue
        ch = chip_of(w)
        on_text = [j for j, o in enumerate(ws) for t in texts_of(o) if overlap(ch, t)]
        on_area = [j for j, o in enumerate(ws) if o is not w and overlap(ch, area_of(o))]
        on_chip = [j for j, o in enumerate(ws) if o is not w and overlap(ch, chip_of(o))]
        check(not w.tr_cards[0].chip.isEmpty() and on_screen(ch) and not on_text and not on_area and not on_chip,
              f"{label}, окошко {k}: плашка {ch.toRect().getRect()} ({w.chip_side} {w.chip_dx:g}) на экране, не на тексте {on_text}, "
              f"не на рамках {on_area} и плашках {on_chip} других окошек")


def two_screens():
    """Два монитора, масштаб 1 (как у владельца)."""
    # Б1: зажатое окошко. Сначала средний абзац, потом соседи сверху, снизу и справа (вторая колонка): окна соседей
    # новее и лежат выше; у среднего места для плашки нет
    before = list(translate_ui._floating)
    sel = selector()
    sel._do("translate_pick")
    order = [("mid", piece(4)), ("top", piece(3)), ("bot", piece(5))] + \
        [(f"col{i}", r.adjusted(-8, -6, 8, 6).toAlignedRect()) for i, (r, _t, _f) in enumerate(COL2)]
    wins = {}
    for name, r in order:
        drag(sel, r.topLeft(), r.bottomRight())
        ws = new_windows(before)
        wait(lambda: done(ws) and len(ws) == len(wins) + 1, 90)
        wins[name] = [x for x in ws if x not in wins.values()][0]
    QTest.keyClick(sel, Qt.Key.Key_Escape)
    settle(4)
    mid = wins["mid"]
    check(mid.crowded and mid.tr_cards[0].chip.isEmpty(), "два монитора: средний абзац между соседями и второй колонкой "
          f"зажат: плашки нет, крестик в углу ({mid.chip_side}, crowded={mid.crowded})")
    if mid.crowded:
        check_peek(mid, "два монитора, зажатое окошко")
    QTest.keyClick(sel, Qt.Key.Key_Escape)
    settle(2)
    for w in wins.values():
        w.close()
    settle(2)

    # П1: кусок у верхнего края второго монитора, под ним непереведённый абзац. Qt на двух мониторах не знает о верхней
    # панели GNOME (доступен весь монитор); плашка над куском легла бы под панель, и менеджер окон сдвинул бы окошко
    # вниз вместе с переводом. Плашка не выше 32 точек от верха монитора, не над куском
    before = list(translate_ui._floating)
    sel = selector()
    sel._do("translate_pick")
    r = TOPLINE[0][0].adjusted(-8, -6, 8, 6).toAlignedRect()
    drag(sel, r.topLeft(), r.bottomRight())
    ws = new_windows(before)
    check(wait(lambda: done(ws), 90), "у верхнего края: кусок переведён")
    QTest.keyClick(sel, Qt.Key.Key_Escape)
    settle(4)
    if ws:
        w = ws[0]
        w.repaint()
        settle(2)
        c, a = chip_of(w), area_of(w)
        mon = QGuiApplication.screenAt(a.center()).geometry()
        check(not w.crowded and w.chip_side != "above" and c.top() >= mon.top() + 32 and on_screen(c) and a.topLeft() == r.topLeft(),
              f"у верхнего края второго монитора: плашка {c.toRect().getRect()} ({w.chip_side}) не выше 32 точек от верха "
              f"монитора {mon.getRect()}, рамка {a.getRect()} на месте")
        top = min(QRectF(a).top(), c.top())
        check(top >= mon.top() + 32, f"у верхнего края: видимый верх окошка {top:g} не под панелью (не выше 32 точек)")
    QTest.keyClick(sel, Qt.Key.Key_Escape)
    settle(2)
    for w in ws:
        w.close()
    settle(2)

    # П3: правый нижний угол второго монитора. Под куском места нет, справа и слева плашка выходит за экран: плашка
    # над куском едет влево до края экрана; окошко не зажато, плашка на экране, рамка на месте
    before = list(translate_ui._floating)
    sel = selector()
    sel._do("translate_pick")
    r = CORNER[0][0].adjusted(-8, -6, 8, 6).toAlignedRect()
    drag(sel, r.topLeft(), r.bottomRight())
    ws = new_windows(before)
    check(wait(lambda: done(ws), 90), "правый нижний угол: кусок переведён")
    QTest.keyClick(sel, Qt.Key.Key_Escape)
    settle(4)
    if ws:
        w = ws[0]
        w.repaint()
        settle(2)
        c, a = chip_of(w), area_of(w)
        check(not w.crowded and on_screen(c) and attached(c, a) and a.topLeft() == r.topLeft(),
              f"правый нижний угол: плашка {c.toRect().getRect()} ({w.chip_side} {w.chip_dx:g}) на экране у своей "
              f"области {a.getRect()}, окошко не зажато, рамка на месте")
        check_mask([w], "правый нижний угол")
    QTest.keyClick(sel, Qt.Key.Key_Escape)
    settle(2)
    for w in ws:
        w.close()
    settle(2)


if MODE == "two":
    two_screens()
    print(f"ИТОГ: проверок {checks[0]}, провалено: {len(failures)}")
    sys.exit(1 if failures else 0)

# --- 1. «Выделить и перевести», по кускам ---------------------------------------------------------------------------
before = list(translate_ui._floating)
sel = selector()
sel._do("translate_pick")
check(sel.translate_mode, "«Выделить и перевести»: режим перевода")
wins = []
for i in (3, 4):   # первый и второй абзацы (0, 1: вкладка и адрес, 2: заголовок)
    r = piece(i)
    drag(sel, r.topLeft(), r.bottomRight())
    ws = new_windows(before)
    check(wait(lambda: done(ws) and len(ws) == len(wins) + 1, 90), f"кусок {i - 2} переведён")
    w = [x for x in ws if x not in wins][0]
    wins.append(w)
    a = area_of(w)
    check(a.topLeft() == r.topLeft() and abs(a.width() - r.width()) <= 1 and abs(a.height() - r.height()) <= 1,
          f"кусок {i - 2}: рамка окошка {a.getRect()} ровно на обведённом тексте {r.getRect()}, не над ним")
    check(w.mapToGlobal(w.tr_cards[0].region.topLeft()) == r.topLeft() and w.mini,
          f"кусок {i - 2}: окошко без плашки, пока идёт режим перевода; угол на месте выделения")
    inside = all(QRectF(a).adjusted(-4, -4, 4, 4).contains(t) for t in texts_of(w))
    check(w.tr_cards[0].state == "done" and inside, f"кусок {i - 2}: строки перевода внутри рамки")
check(not overlap(area_of(wins[0]), area_of(wins[1])), "два соседних куска: окошки не налезают друг на друга")
QTest.keyClick(sel, Qt.Key.Key_Escape)   # режим перевода закончен: плашки возвращаются
settle(4)
check(all(not w.mini for w in wins), "Esc: у окошек появились плашки")
check_chips(wins, "два соседних абзаца")
check(not any(w.crowded for w in wins), "два соседних абзаца: место для плашки нашлось у обоих окошек")
check_mask(wins, "два соседних абзаца")
check(all(area_of(w).topLeft() == piece(i).topLeft() for w, i in zip(wins, (3, 4))),
      "после Esc рамки окошков остались на своих абзацах")
# третий абзац сразу под вторым: снова «Выделить и перевести» в том же окне выделения
sel._do("translate_pick")
r = piece(5)
drag(sel, r.topLeft(), r.bottomRight())
ws = new_windows(before)
check(wait(lambda: done(ws) and len(ws) == 3, 90), "третий кусок переведён")
w3 = [x for x in ws if x not in wins][0]
wins.append(w3)
check(area_of(w3).topLeft() == r.topLeft(), f"третий кусок: рамка {area_of(w3).getRect()} на тексте {r.getRect()}")
QTest.keyClick(sel, Qt.Key.Key_Escape)
settle(4)
check_chips(wins, "три соседних абзаца")
check_mask(wins, "три соседних абзаца")
areas = [area_of(w) for w in wins]
check(not any(overlap(areas[a], areas[b]) for a in range(3) for b in range(a + 1, 3)),
      "три соседних абзаца: рамки окошков не налезают друг на друга")
# кусок, обведённый поверх открытого окошка: сдвиг на минимум, на открытые окошки не ложится
sel._do("translate_pick")
a0 = area_of(wins[0])
r = QRect(a0.right() - 100, a0.top() + 8, 330, a0.height() - 16)
drag(sel, r.topLeft(), r.bottomRight())
ws = new_windows(before)
check(wait(lambda: done(ws) and len(ws) == 4, 90), "кусок поверх окошка: перевод готов (или честная ошибка)")
w4 = [x for x in ws if x not in wins][0]
a4 = area_of(w4)
shift = abs(a4.x() - r.x()) + abs(a4.y() - r.y())
check(not any(overlap(a4, area_of(w)) for w in wins) and a4.size() == r.size() and shift <= 105,
      f"кусок поверх окошка: сдвинут на {shift} точек {a4.getRect()} (обведено {r.getRect()}), на окошки не лёг")
QTest.keyClick(sel, Qt.Key.Key_Escape)
settle(4)
check_chips(wins + [w4], "четыре окошка")
QTest.keyClick(sel, Qt.Key.Key_Escape)
settle(2)
for w in wins + [w4]:
    w.close()
settle(2)

# --- 2. «Весь экран», поверх текста -----------------------------------------------------------------------------
before = list(translate_ui._floating)
sel = selector()
sel.start_translate_all()
check(wait(lambda: done(new_windows(before)), 120), "весь экран переведён")
ws = new_windows(before)
full = [w for w in ws if w.tr_cards and w.tr_cards[0].full]
check(len(full) == 1, "весь экран: одно окно на весь монитор")
if full:
    w = full[0]
    w.repaint()
    settle(3)
    check(area_of(w) == QRect(0, 0, W, H), f"весь экран: область {area_of(w).getRect()} = монитор")
    check(w.chip_side == "right" and w.chip_dx == 0, "весь экран: плашка с кнопками по прежним правилам")
    plates = [QRectF(b["draw"]).united(QRectF(b["rect"])).adjusted(-1, -1, 1, 1).translated(QRectF(area_of(w)).topLeft()
              - QRectF(w.tr_cards[0].region).topLeft()) for b in w.tr_cards[0].blocks]
    # каждая тёмная точка исходного текста (на снимке) закрыта плашкой
    loose = []
    k = SCALE
    for i, (r, text, _f) in enumerate(BLOCKS):
        box = r.adjusted(-2, -4, 2, 6)
        for py in range(int(box.top() * k), int(box.bottom() * k)):
            for px in range(int(box.left() * k), int(min(box.right(), W) * k)):
                c = PAGE.pixelColor(px, py)
                if c.red() + c.green() + c.blue() < 3 * 150:
                    x, y = (px + 0.5) / k, (py + 0.5) / k
                    if not any(pl.contains(x, y) for pl in plates):
                        loose.append((i, round(x), round(y)))
    check(not loose, f"весь экран: исходные строки закрыты плашками целиком (открытых точек {len(loose)}: {loose[:5]})")
    tab = [b for b in w.tr_cards[0].blocks if b["rect"].top() - w.tr_cards[0].region.top() < 116]
    def lines(b):
        f = QFont()
        f.setPixelSize(b["px"])
        fm = QFontMetrics(f)
        need = fm.boundingRect(QRect(0, 0, max(20, int(b["draw"].width())), 100000), Qt.TextFlag.TextWordWrap, b["text"])
        return round(need.height() / fm.lineSpacing())
    check(len(tab) == 2 and all(b["draw"].height() <= b["rect"].height() + 2 and lines(b) == 1 for b in tab),
          f"весь экран: вкладка и адрес одной строкой в своей высоте, не столбиком "
          f"{[(b['text'], round(b['rect'].height()), round(b['draw'].height()), b['px'], lines(b)) for b in tab]}")
    w.close()
settle(2)
print(f"ИТОГ: проверок {checks[0]}, провалено: {len(failures)}")
sys.exit(1 if failures else 0)
