# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""1.32, Б1 независимой проверки: Alt+W работает всегда.

Окно оценки и окна обновления модальные: под ними окно выделения не получало ни мыши, ни клавиш (затемнение без
выхода). Теперь перед выделением они закрываются как «Позже», выделение работает: Esc закрывает, мышь делает снимок.
Проверяется на настоящем Clipshot: окно оценки по правилам и из меню; предложение обновления (обычное и срочное,
настоящий OfferDialog в exec()); окно сбоя обновления с открытым отчётом (окно в окне); сведения обновления
(QMessageBox). Модальное окно, которое закрывать нельзя («О программе»): выделение не открывается застывшим,
поднимается это окно. Окно оценки само приходит только после спокойной минуты (60 с подряд нет выделения,
редактора и других окон), а не через 2,5 с после закрытия редактора.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/altw132_test.py
"""
import json
import os
import sys
import tempfile
import time
from datetime import timedelta
from pathlib import Path

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
_cfg = os.path.join(tempfile.mkdtemp(prefix="clipsd-altw-"), "screen.json")
with open(_cfg, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1600, "height": 1000,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _cfg
os.environ.setdefault("CLIPSD_LANG", "ru")

from PyQt6.QtCore import QPoint, QRect, Qt, QTimer
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
from clipshot import app as appmod, feedback, update_prompt, updater as up  # noqa: E402
from clipshot.update_channel import Manifest  # noqa: E402

failures = []
checks = [0]
DAY = 86400
LEFT, NOMOD = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier


def check(cond, msg):
    checks[0] += 1
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def settle(n=4):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(15)


def wait(cond, seconds=5):
    end = time.time() + seconds
    while not cond() and time.time() < end:
        app.processEvents()
        QTest.qWait(20)
    return cond()


feedback.RATE_URL = "http://127.0.0.1:9/rate"       # оценки в этом тесте не отправляются
appmod.CONFIG_PATH = Path(tempfile.mkdtemp(prefix="clipsd-altw-cfg-", dir=os.environ.get("TMPDIR"))) / "config.json"
appmod.is_wayland = lambda: False                    # X11: снимок сразу, окно выделения захватывает клавиатуру


def fake_grab():
    pm = QPixmap(800, 600)
    pm.fill(QColor("white"))
    return pm


appmod.grab_qt = fake_grab
appmod.virtual_geometry = lambda: QRect(0, 0, 800, 600)

c = appmod.Clipshot(app)
c.config.update(auto_save=False, usage_days=7, capture_count=20, theme_chosen=True, tour_done=True,
                tour_selector_done=True, remember_region=False)   # каждое выделение с чистого экрана, без прошлой рамки


def active_modal():
    w = QApplication.activeModalWidget()
    return type(w).__name__ if w is not None else None


def alt_w():
    """Alt+W: та же команда, что приходит от расширения GNOME, своих горячих клавиш и меню значка."""
    c.last_trigger = 0.0
    c.capture_region()


def selector_open():
    return wait(lambda: c.selector is not None and c.selector.isVisible(), 3)


def esc_closes_selector():
    QTest.keyClick(c.selector.windowHandle(), Qt.Key.Key_Escape)
    return wait(lambda: c.selector is None, 3)


def drag_makes_shot():
    """Мышью выделить 200x160: окно выделения закрывается, открывается редактор со снимком; редактор закрывается."""
    n = len(c.editors)
    w = c.selector.windowHandle()
    QTest.mousePress(w, LEFT, NOMOD, QPoint(100, 100))
    QTest.mouseMove(w, QPoint(200, 180))
    QTest.mouseMove(w, QPoint(300, 260))
    settle(2)
    QTest.mouseRelease(w, LEFT, NOMOD, QPoint(300, 260))
    ok = wait(lambda: c.selector is None and len(c.editors) == n + 1, 3)
    if ok:
        ed = c.editors[-1]
        size = ed.canvas.base.size()
        ok = (size.width(), size.height()) == (200, 160)
        ed.close()
        wait(lambda: len(c.editors) == n, 3)
    return ok


def offer_rating_now():
    c.config.update(rating_next_ts=0, rating_shown=0)
    return c.maybe_offer_rating() and wait(lambda: feedback.is_open(c._rating), 2)


# ---------------------------------------------------------------- окно оценки

def test_rating_window():
    check(offer_rating_now() and active_modal() == "RatingDialog", "окно оценки по правилам открыто, оно модальное")
    t0 = time.time()
    alt_w()
    check(selector_open(), "Alt+W: окно выделения открыто")
    check(not feedback.is_open(c._rating) and active_modal() is None, "окно оценки закрыто, модальных окон нет")
    check(c.config.get("rating_next_ts", 0) >= t0 + 29 * DAY and c._rating.outcome == "later",
          "окно оценки закрыто как «Позже»: снова через 30 дней")
    check(esc_closes_selector(), "Esc закрывает окно выделения")

    check(offer_rating_now(), "окно оценки снова открыто")
    alt_w()
    check(selector_open() and drag_makes_shot(), "Alt+W при окне оценки: выделение мышью делает снимок 200x160")

    # окно из меню «Оценить ClipSD»: закрывается как крестиком, правила показа не трогаются;
    # 1.32.1: звёзды и набранный отзыв не теряются, а возвращаются при следующем открытии окна
    c.config.update(rating_next_ts=0)
    c.show_rating()
    check(wait(lambda: feedback.is_open(c._rating)) and not c._rating.auto, "окно оценки из меню открыто")
    review = "Удобно, но хочется\nвыбор формата файла"
    c._rating.dialog.set_stars(4)
    c._rating.dialog.text_edit.setPlainText(review)
    alt_w()
    check(selector_open() and not feedback.is_open(c._rating), "Alt+W: окно из меню закрыто, выделение открыто")
    check(c.config.get("rating_next_ts") == 0 and c._rating.outcome == "closed", "окно из меню: правила показа не тронуты")
    check(c.rating_draft == {"stars": 4, "text": review}, "набранный отзыв и звёзды сохранены черновиком (в памяти)")
    check("rating_draft" not in json.dumps(c.config) and review not in json.dumps(c.config),
          "черновик не попадает в настройки на диске")
    check(esc_closes_selector(), "Esc закрывает окно выделения")
    c.show_rating()
    d = c._rating.dialog
    check(wait(lambda: feedback.is_open(c._rating)) and d.text_edit.toPlainText() == review and d.stars == 4
          and d.send_btn.isEnabled(), "следующее открытие: черновик на месте, «Отправить» доступна")
    check(c.rating_draft is None, "черновик возвращён один раз")
    d.close()
    settle()
    c.show_rating()
    d = c._rating.dialog
    check(wait(lambda: feedback.is_open(c._rating)) and d.text_edit.toPlainText() == "" and d.stars == 0,
          "окно закрыли крестиком: в следующий раз чистое")
    alt_w()
    check(selector_open() and c.rating_draft is None, "пустое окно и Alt+W: черновика нет")
    check(esc_closes_selector(), "Esc закрывает окно выделения")

    # без открытых окон Alt+W как раньше: без задержки на закрытие окон
    check(c.clear_way_for_capture() == 0, "нечего закрывать: снимок без задержки")


# ---------------------------------------------------------------- окна обновления

NOW = up.utcnow()


def manifest(critical=False):
    return Manifest(channel="stable", version="2.0.1", released=NOW - timedelta(days=4), expires=NOW + timedelta(days=30),
                    files={"linux": {"url": "https://example.invalid/clipsd-2.0.1.tar.gz", "size": 1, "sha256": "0" * 64}},
                    notes={"ru": "Исправления."}, critical=critical)


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


def make_updater(clock=None):
    u = up.Updater(c, kind="linux", installed="1.0.0", clock=clock or (lambda: NOW))   # настоящие окна (UpdaterUI)
    c._updater = u
    return u


def run_modal(start, inside, seconds=8):
    """start() открывает окно через exec() (вложенный цикл событий), inside() вызывается внутри этого цикла.
    Сторож закрывает всё через seconds, если окно так и не закрылось (иначе тест повис бы)."""
    seen = {}

    def guard():
        stuck = [w for w in QApplication.topLevelWidgets() if w.isVisible() and w.isModal()]
        seen["stuck"] = [type(w).__name__ for w in stuck]
        for w in stuck:
            w.reject() if hasattr(w, "reject") else w.close()

    def go():
        QTimer.singleShot(200, inside)
        QTimer.singleShot(seconds * 1000, guard)
        seen["result"] = start()

    QTimer.singleShot(0, go)
    wait(lambda: "result" in seen, seconds + 2)
    return seen


def test_update_offer():
    u = make_updater()
    c.config["update_prompt"] = {"version": "2.0.1", "since": up.uc.format_utc(NOW - timedelta(days=4)), "shots": 3}
    state = {}

    def inside():
        state["modal"] = active_modal()
        alt_w()

    def start():
        u.busy = True
        u._present(manifest(), "notify", False, NOW)
        return "returned"

    seen = run_modal(start, inside)
    check(state.get("modal") == "OfferDialog", "предложение обновления открыто (exec), оно модальное")
    check(seen.get("result") == "returned" and not seen.get("stuck"), "Alt+W закрыл предложение обновления")
    check(selector_open() and active_modal() is None, "окно выделения открыто, модальных окон нет")
    st = update_prompt.state(c.config)
    check(st.get("version") == "2.0.1" and st.get("since") == up.uc.format_utc(NOW) and st.get("shots") == 0,
          "как «Позже»: отсчёт отложенного окна сохранён и начат заново (3 дня или 20 снимков)")
    check("2.0.1" not in (up.cfg(c.config, "update_skipped") or []) and not u.busy, "версия не пропущена, загрузки нет")
    check(not getattr(u, "_critical_recall", False), "обычное обновление: срочного повтора нет, ждёт отложенное окно")
    check(esc_closes_selector(), "Esc закрывает окно выделения")

    seen = run_modal(start, alt_w)
    check(not seen.get("stuck") and selector_open() and drag_makes_shot(),
          "Alt+W при предложении обновления: выделение мышью делает снимок")

    # срочное исправление: Alt+W закрывает его (пропустить нельзя), выделение не блокирует; 1.32.1: окно приходит
    # снова после снимка в спокойную минуту, а не через сутки
    c.config.pop("update_prompt", None)
    clock = Clock()
    u2 = make_updater(clock)
    u2._pending_critical = lambda now, fresh=True: manifest(critical=True)   # проверенная сохранённая копия

    def start_critical():
        u2.busy = True
        u2._present(manifest(critical=True), "notify", True, clock.now)
        return "returned"

    seen = run_modal(start_critical, inside)
    check(state.get("modal") == "OfferDialog" and not seen.get("stuck"), "срочное обновление: Alt+W закрыл окно")
    check(u2._critical_recall and u2._recall_timer.isActive()
          and u2._recall_timer.interval() == update_prompt.RECALL_POLL_MS, "срочное: ждёт спокойной минуты после снимка")
    check(selector_open(), "срочное обновление: выделение открыто")
    check(not update_prompt.recall_poll(u2) and u2._recall_quiet_since is None, "идёт выделение: срочного окна нет")
    check(esc_closes_selector(), "срочное обновление: Esc закрывает выделение")
    check(not update_prompt.state(c.config) and "2.0.1" not in (up.cfg(c.config, "update_skipped") or []),
          "срочное не пропущено и не попало в отложенные")
    check(not update_prompt.recall_poll(u2), "спокойно с этой секунды")
    clock.now += timedelta(seconds=30)
    check(not update_prompt.recall_poll(u2), "спокойно 30 с: ещё ждём")
    c._note_activity()             # короткий снимок между проверками таймера
    clock.now += timedelta(seconds=31)
    check(not update_prompt.recall_poll(u2), "был снимок: минута считается заново")
    c.editors.append("editor")
    clock.now += timedelta(seconds=61)
    check(not update_prompt.recall_poll(u2), "открыт редактор: срочного окна нет")
    c.editors.remove("editor")
    check(not update_prompt.recall_poll(u2), "редактор закрыт: спокойно с этой секунды")
    clock.now += timedelta(seconds=61)
    again = {}

    def answer_later():
        again["modal"] = active_modal()
        w = QApplication.activeModalWidget()
        again["critical"] = getattr(w, "critical", None)
        w.later_button.click()

    seen = run_modal(lambda: update_prompt.recall_poll(u2), answer_later)
    check(seen.get("result") is True and again.get("modal") == "OfferDialog" and again.get("critical") is True,
          "спокойная минута после снимка: срочное окно снова, а не через сутки")
    check(not u2._critical_recall and not u2._recall_timer.isActive() and u2._critical_offered_at == clock.now,
          "срочное показано: повтор снят")
    check(not u2._critical_due(clock.now + timedelta(hours=1)) and u2._critical_due(clock.now + timedelta(days=1)),
          "ответ «Позже» кнопкой: дальше как раньше, раз в сутки")

    # П4 проверки 1.32.1: Alt+W закрыл срочное окно, потом человек сам открыл проверку и ответил «Позже»:
    # отложенный повтор снят, окно второй раз не приходит
    update_prompt.recall_critical(u2)
    check(u2._critical_recall, "после Alt+W повтор срочного окна взведён")

    def manual_later():
        u2.busy = True
        u2._present(manifest(critical=True), "notify", True, clock.now)

    seen = run_modal(manual_later, answer_later)
    check(again.get("critical") is True and not u2._critical_recall, "срочное окно показано вручную, ответ «Позже»: повтор снят")
    clock.now += timedelta(seconds=200)
    check(not update_prompt.recall_poll(u2) and not update_prompt.recall_poll(u2), "спокойная минута: второго срочного окна нет")


def test_other_update_windows():
    u = make_updater()
    # окно сбоя обновления, в нём открыт отчёт: окно в окне, оба в exec()
    state = {}

    def open_report():
        failed = next(w for w in QApplication.topLevelWidgets() if isinstance(w, up.FailedDialog) and w.isVisible())
        QTimer.singleShot(200, inside_report)
        failed.report_button.click()       # ReportDialog.exec(): ещё один вложенный цикл

    def inside_report():
        state["modal"] = active_modal()
        alt_w()

    seen = run_modal(lambda: u.ui.failed("2.0.1", "отчёт", "Обновление не установлено"), open_report)
    check(state.get("modal") == "ReportDialog", "сбой обновления: открыт отчёт поверх окна сбоя")
    check(seen.get("result") == "close" and not seen.get("stuck"), "Alt+W закрыл оба окна, выбор «Закрыть»")
    check(selector_open() and esc_closes_selector(), "выделение работает, Esc закрывает")

    seen = run_modal(lambda: u.ui.info("Сведения об обновлении") or "returned", alt_w)
    check(seen.get("result") == "returned" and not seen.get("stuck"), "сведения обновления (QMessageBox): закрыты")
    check(selector_open() and esc_closes_selector(), "выделение работает, Esc закрывает")


def test_modal_that_stays():
    """«О программе» (модальное, закрывать его программа не должна): выделение не открывается застывшим."""
    c.show_about()
    about = c._about
    check(wait(about.isVisible) and active_modal() is not None, "«О программе» открыто, оно модальное")
    alt_w()
    settle(10)
    check(c.selector is None and about.isVisible(), "Alt+W: застывшего выделения нет, окно «О программе» на месте")
    about.close()
    settle(4)
    alt_w()
    check(selector_open() and esc_closes_selector(), "«О программе» закрыто: Alt+W работает")


# ---------------------------------------------------------------- спокойная минута

def test_quiet_minute():
    c.config.update(rating_next_ts=0, rating_shown=0)
    c._stop_rating_quiet()
    check(not feedback.is_open(c._rating) and feedback.should_show_rating(c.config), "правила показа выполнены")
    # редактор закрыт: окна нет ни сразу, ни через 2,5 с (так было до исправления)
    c._editor_closed(None)
    QTest.qWait(3000)
    settle(2)
    check(not feedback.is_open(c._rating), "закрыт редактор: через 3 с окна оценки нет")
    check(c._rating_quiet_timer is not None and c._rating_quiet_timer.isActive()
          and c._rating_quiet_timer.interval() == c.RATING_POLL_MS, "таймер ждёт спокойной минуты")
    q = update_prompt.QUIET.total_seconds()
    check(q == 60, "спокойная минута: 60 с, как у отложенного окна обновления")
    t = 1000.0
    check(not c.rating_quiet_poll(t), "спокойно с этой секунды")
    check(not c.rating_quiet_poll(t + 30), "спокойно 30 с: ещё ждём")
    c._note_activity()      # короткий снимок между двумя проверками таймера
    check(not c.rating_quiet_poll(t + 61), "был снимок: минута считается заново")
    check(not c.rating_quiet_poll(t + 61 + 59), "после снимка 59 с: ещё ждём")
    c.selector = object()
    check(not c.rating_quiet_poll(t + 200) and c._rating_quiet_since is None, "идёт выделение: не спокойно")
    c.selector = None
    c.editors.append("editor")
    check(not c.rating_quiet_poll(t + 300) and c._rating_quiet_since is None, "открыт редактор: не спокойно")
    c.editors.remove("editor")
    c.show_about()
    check(not c.rating_quiet_poll(t + 400) and c._rating_quiet_since is None, "открыто другое окно ClipSD: не спокойно")
    c._about.close()
    settle(2)
    check(not c.rating_quiet_poll(t + 500), "снова спокойно")
    check(not feedback.is_open(c._rating) and c.rating_quiet_poll(t + 561), "60 с подряд спокойно: окно оценки")
    check(feedback.is_open(c._rating) and not c._rating_quiet_timer.isActive(), "окно открыто, таймер остановлен")
    alt_w()
    check(selector_open() and not feedback.is_open(c._rating) and esc_closes_selector(), "и Alt+W тут же работает")
    c.watch_rating_quiet()
    check(not c._rating_quiet_timer.isActive(), "«Позже» на 30 дней: таймер не идёт")

    # настоящий таймер (короткие интервалы): окно приходит само, когда спокойно
    c.config.update(rating_next_ts=0, rating_shown=0)
    saved = update_prompt.QUIET, c.RATING_POLL_MS
    update_prompt.QUIET, c.RATING_POLL_MS = timedelta(seconds=0.4), 100
    c._rating_quiet_timer = None
    c.watch_rating_quiet()
    check(wait(lambda: feedback.is_open(c._rating), 5), "таймер: окно оценки после спокойной минуты")
    update_prompt.QUIET, c.RATING_POLL_MS = saved
    c._rating.close_for_capture()
    settle(4)
    # пока рано по правилам, таймер не запускается
    c.watch_rating_quiet()
    check(not c._rating_quiet_timer.isActive(), "рано по правилам: таймер не запускается")


for fn in (test_rating_window, test_update_offer, test_other_update_windows, test_modal_that_stays, test_quiet_minute):
    try:
        fn()
    except Exception as exc:     # noqa: BLE001
        import traceback
        traceback.print_exc()
        check(False, f"{fn.__name__}: исключение {exc!r}")
    for w in QApplication.topLevelWidgets():   # следующая часть с чистого экрана
        if w.isVisible() and w.isModal():
            w.close()
    if c.selector is not None:
        c.selector.close()
        c.selector = None
    settle(2)

print(f"ИТОГ: проверок {checks[0]}, провалено: {len(failures)}")
sys.exit(1 if failures else 0)
