# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Когда показывать окно «Доступна версия N» (1.32, решение владельца 19.11.2026). Вся логика здесь.

Обычное обновление, найденное автоматической проверкой, окно сразу не показывает: загорается колокольчик редактора
(точка и пункт «Доступна версия N» с кнопкой «Обновить», см. notifications.available_update). Окно-предложение
появляется позже, только если человек не обновился сам: через SHOTS снимков с момента обнаружения или через DELAY,
что раньше, и не во время работы: после спокойной минуты (QUIET), когда нет окна выделения, нет открытого редактора
и ничего не мешает выйти (Clipshot.quit_blocker). «Позже» откладывает ещё на DELAY и SHOTS. «Пропустить эту версию»
гасит и окно, и колокольчик для этой версии (updater.skip_version, notifications не показывает пропущенные).
Срочное исправление безопасности и ручная «Проверить обновления» показывают окно сразу, как раньше.

Счётчики в config["update_prompt"] = {"version", "since" (UTC ISO), "shots"}. Updater зовёт hold() из _on_checked,
after_offer() после окна и start() при запуске; app зовёт note_shot() на каждый снимок."""

from datetime import timedelta

DELAY = timedelta(days=3)        # окно не раньше чем через 3 дня после обнаружения (или после «Позже»)
SHOTS = 20                       # или после 20 снимков, что раньше
QUIET = timedelta(seconds=60)    # «спокойная минута»: столько подряд нет выделения, редактора и окон
POLL_MS = 30_000                 # как часто смотреть, не пора ли (пока есть отложенное предложение)
KEY = "update_prompt"


def _uc():
    from . import update_channel as uc
    return uc


def state(cfg: dict) -> dict:
    s = cfg.get(KEY)
    return s if isinstance(s, dict) and s.get("version") else {}


def note_found(cfg: dict, version: str, now) -> None:
    """Найдена версия новее установленной. Отсчёт идёт с первого обнаружения: более новая версия, найденная пока
    ждём, только заменяет номер (человек уже знает, что обновление есть)."""
    s = state(cfg)
    if s:
        if s.get("version") != version:
            s = dict(s, version=version)
            cfg[KEY] = s
        return
    cfg[KEY] = {"version": version, "since": _uc().format_utc(now), "shots": 0}


def note_shot(cfg: dict) -> None:
    """Сделан снимок: шаг счётчика, если предложение ждёт."""
    s = state(cfg)
    if s:
        cfg[KEY] = dict(s, shots=int(s.get("shots", 0)) + 1)


def postpone(cfg: dict, now) -> None:
    """«Позже»: ещё DELAY и SHOTS с этой минуты."""
    s = state(cfg)
    if s:
        cfg[KEY] = dict(s, since=_uc().format_utc(now), shots=0)


def clear(cfg: dict) -> None:
    cfg.pop(KEY, None)


def due(cfg: dict, now) -> bool:
    """Пора показать окно: прошло DELAY с обнаружения (или с «Позже») или сделано SHOTS снимков."""
    s = state(cfg)
    if not s:
        return False
    if int(s.get("shots", 0)) >= SHOTS:
        return True
    try:
        since = _uc().parse_utc(s.get("since", ""))
    except (TypeError, ValueError):
        return True
    if since > now + _uc().CLOCK_TOLERANCE:   # часы перевели назад: отсчёт заново
        cfg[KEY] = dict(s, since=_uc().format_utc(now))
        return False
    return now - since >= DELAY


def busy_reason(ctx) -> str:
    """Почему сейчас не время для окна ("" = спокойно): окно выделения, открытый редактор, набор текста,
    несохранённые пометки, открытое модальное окно (Clipshot.quit_blocker)."""
    if getattr(ctx, "selector", None) is not None or getattr(ctx, "insert_target", None) is not None:
        return "selector"
    if getattr(ctx, "editors", None):
        return "editor"
    blocker = getattr(ctx, "quit_blocker", None)
    return blocker() if blocker is not None else ""


# --- связка с Updater ---------------------------------------------------------------------------------------

def hold(updater, manifest, now, manual: bool, critical: bool) -> bool:
    """Из Updater._on_checked: True, если окно сейчас не показывать (обычное обновление при автоматической проверке).
    Колокольчик уже знает о версии (remember_seen); здесь только отсчёт и наблюдение за спокойной минутой."""
    if manual or critical:
        return False
    cfg = updater.config
    uc = _uc()
    if not uc.is_newer(manifest, updater.installed):
        clear(cfg)   # установленная версия не старше найденной: ждать нечего
        return False
    from . import updater as up
    if manifest.version in (up.cfg(cfg, "update_skipped") or []):
        return True   # пропущена: ни окна, ни колокольчика
    note_found(cfg, manifest.version, now)
    updater._prompt_manifest = manifest
    _refresh_bell()
    start(updater)
    return True


def after_offer(updater, version: str, choice: str, now) -> None:
    """После окна-предложения (любого: отложенного, ручного): «Позже» откладывает, «Пропустить» и «Обновить» гасят."""
    cfg = updater.config
    if choice == "later":
        if state(cfg):
            postpone(cfg, now)
        else:
            note_found(cfg, version, now)   # ручная проверка, «Позже»: дальше как обычное отложенное
    elif choice in ("skip", "update"):
        clear(cfg)
    _refresh_bell()


def poll(updater) -> bool:
    """Таймер наблюдения: пора и спокойно уже минуту, значит окно. True, если окно показано."""
    cfg = updater.config
    s = state(cfg)
    if not s:
        _stop(updater)
        return False
    uc = _uc()
    try:
        if uc.compare_versions(s["version"], updater.installed) <= 0:
            clear(cfg)   # уже обновились (сами или по кнопке колокольчика)
            _stop(updater)
            return False
    except ValueError:
        pass
    now = updater.clock()
    if updater.busy or not due(cfg, now):
        updater._prompt_quiet_since = None
        return False
    if busy_reason(updater.ctx):
        updater._prompt_quiet_since = None
        return False
    quiet = getattr(updater, "_prompt_quiet_since", None)
    if quiet is None or quiet > now:
        updater._prompt_quiet_since = now
        return False
    if now - quiet < QUIET:
        return False
    manifest = getattr(updater, "_prompt_manifest", None)
    if manifest is None or manifest.version != s["version"]:
        return False   # после перезапуска документа канала в памяти нет: окно покажет следующая проверка канала
    updater._prompt_quiet_since = None
    from . import updater as up
    action = up.decide(manifest, cfg, updater.installed, now, manual=True)   # отсчёт уже прошёл: без недельного окна
    if action not in ("notify", "manual_install"):
        clear(cfg)
        return False
    updater.busy = True
    updater._present(manifest, action, False, now)   # выбор человека: after_offer (из _present)
    if action == "manual_install" and state(cfg):
        postpone(cfg, now)   # «установите вручную» тоже не чаще, чем раз в 3 дня или 20 снимков
    return True


def start(updater) -> None:
    """Таймер наблюдения, пока есть отложенное предложение (при запуске и после hold)."""
    if not state(updater.config) or updater.kind not in ("windows", "linux"):
        return
    timer = getattr(updater, "_prompt_timer", None)
    if timer is None:
        from PyQt6.QtCore import QTimer
        timer = QTimer(updater)
        timer.setInterval(POLL_MS)
        timer.timeout.connect(lambda: poll(updater))
        updater._prompt_timer = timer
    if not timer.isActive():
        timer.start()


def _stop(updater) -> None:
    timer = getattr(updater, "_prompt_timer", None)
    if timer is not None:
        timer.stop()


def _refresh_bell() -> None:
    try:
        from . import notifications
        notifications.refresh()
    except Exception:   # noqa: BLE001 — колокольчик не должен ломать обновление
        pass
