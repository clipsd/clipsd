# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Колокольчик редактора (1.32): уведомления программы одним списком.

Что бывает в списке (сверху вниз):
- update: «Доступна версия X». Канал обновлений уже видел эту версию (config update_last_seen_version*, её пишет
  updater при проверке), она новее установленной и человек её не пропустил. Кнопка «Обновить» запускает проверку
  с окном предложения (updater.check_now). В сборке из Microsoft Store этого пункта нет: её обновляет Store.
- whatsnew: «Что нового в X» для установленной версии и прошлых обновлений. Заметки берутся из
  CHANGELOG/<версия>/<язык>.md (программа из исходников или сборка, куда папка положена рядом с пакетом) или из записи
  обновления (config notices_whatsnew: её пишет updater, когда обновление установилось).
- message: короткие сообщения программы, например «Перевод: дневной лимит исчерпан» (post() из любого места).

Прочитанное хранится в config notices_read (список id). Точка на колокольчике: есть непрочитанное.
Модуль ничего не отправляет в сеть: он только читает настройки, файлы CHANGELOG и записи обновления.
Тексты: ключи clipshot/i18n/<язык>/notifications.json, читаются при показе (tr())."""

import weakref
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import __version__
from .i18n import current, tr

MAX_MESSAGES = 10                 # коротких сообщений храним не больше
MESSAGE_DAYS = 7                  # и не старше недели
MAX_WHATSNEW = 3                  # «Что нового»: установленная версия и две прошлые
MAX_READ = 60                     # список прочитанного не растёт бесконечно
MESSAGE_KEYS = {                  # код сообщения -> (ключ заголовка, ключ пояснения)
    "translate_quota": ("notifications.translate_quota", "notifications.translate_quota_sub"),
    "translate_quota_month": ("notifications.translate_quota_month", "notifications.translate_quota_month_sub"),
}

_ctx = None          # приложение (Clipshot) или окно с ctx: post() пишет в его config
_listeners = []      # слабые ссылки на функции «список изменился» (колокольчики открытых редакторов)


def register(ctx):
    """Запомнить приложение: post() из мест без ctx (перевод) пишет в его настройки."""
    global _ctx
    _ctx = weakref.ref(ctx) if ctx is not None else None


def _app():
    return _ctx() if _ctx is not None else None


def listen(callback):
    """callback() вызывается, когда список изменился (новое сообщение, прочитано)."""
    try:
        ref = weakref.WeakMethod(callback)
    except TypeError:
        ref = (lambda cb=callback: cb)
    _listeners.append(ref)


def _changed():
    alive = []
    for ref in _listeners:
        cb = ref()
        if cb is None:
            continue
        alive.append(ref)
        try:
            cb()
        except RuntimeError:   # окно уже удалено Qt
            continue
    _listeners[:] = alive


def refresh():
    """Список мог измениться (например, обновление нашлось): колокольчики перерисовываются."""
    _changed()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(text):
    try:
        return datetime.strptime(str(text), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _version_key(v: str):
    out = []
    for part in str(v).split("."):
        num = "".join(ch for ch in part if ch.isdigit())
        out.append(int(num) if num else 0)
    return tuple(out)


# --- сообщения программы ------------------------------------------------------------------------------

def post(kind: str, cfg=None, save=None, now=None) -> bool:
    """Короткое сообщение в колокольчик (MESSAGE_KEYS). Одно и то же сообщение за день не повторяется.
    cfg и save: настройки и запись; без них берутся у зарегистрированного приложения. True: добавлено."""
    app = _app()
    if cfg is None and app is not None:
        cfg = app.config
        save = getattr(app, "save_config", None)
    if cfg is None or kind not in MESSAGE_KEYS:
        return False
    now = now or _now()
    day = now.strftime("%Y-%m-%d")
    msgs = [m for m in (cfg.get("notices_messages") or []) if isinstance(m, dict)]
    ident = f"msg:{kind}:{day}"
    if any(m.get("id") == ident for m in msgs):
        return False
    old = now - timedelta(days=MESSAGE_DAYS)
    msgs = [m for m in msgs if (_parse(m.get("time")) or now) >= old]
    msgs.append({"id": ident, "kind": kind, "time": _iso(now)})
    cfg["notices_messages"] = msgs[-MAX_MESSAGES:]
    if save is not None:
        save()
    _changed()
    return True


# --- «Что нового» -------------------------------------------------------------------------------------

def _changelog_dirs():
    """Где лежат заметки версий: CHANGELOG рядом с пакетом (исходники) или внутри сборки."""
    here = Path(__file__).resolve().parent
    import sys
    out = [here.parent / "CHANGELOG", here / "CHANGELOG"]
    base = getattr(sys, "_MEIPASS", None)
    if base:
        out.append(Path(base) / "CHANGELOG")
    return out


def changelog_versions() -> list:
    """Версии с заметками в CHANGELOG (по убыванию)."""
    found = set()
    for d in _changelog_dirs():
        if d.is_dir():
            found.update(p.name for p in d.iterdir() if p.is_dir() and any(p.glob("*.md")))
    return sorted(found, key=_version_key, reverse=True)


def changelog_notes(version: str, lang: str = None) -> str:
    """Заметки версии на языке интерфейса (запасной английский, потом русский); пусто, если файлов нет."""
    lang = lang or current()
    for d in _changelog_dirs():
        folder = d / version
        for code in (lang, "en", "ru"):
            f = folder / f"{code}.md"
            if f.is_file():
                try:
                    text = f.read_text(encoding="utf-8").strip()
                except OSError:
                    continue
                if text:
                    return text
    return ""


def remember_whats_new(cfg: dict, version: str, notes, now=None) -> None:
    """Обновление установилось (updater): заметки этой версии на всех языках остаются в колокольчике."""
    if not version:
        return
    items = [w for w in (cfg.get("notices_whatsnew") or []) if isinstance(w, dict) and w.get("version") != version]
    items.append({"version": version, "notes": notes if isinstance(notes, dict) else {}, "time": _iso(now or _now())})
    items.sort(key=lambda w: _version_key(w.get("version", "")))
    cfg["notices_whatsnew"] = items[-MAX_WHATSNEW:]
    _changed()


def whats_new_notes(cfg: dict, version: str, lang: str = None) -> str:
    """Заметки версии: CHANGELOG, иначе запись обновления."""
    text = changelog_notes(version, lang)
    if text:
        return text
    lang = lang or current()
    for w in cfg.get("notices_whatsnew") or []:
        if isinstance(w, dict) and w.get("version") == version and isinstance(w.get("notes"), dict):
            notes = w["notes"]
            return str(notes.get(lang) or notes.get("en") or notes.get("ru") or "").strip()
    return ""


def _whatsnew_versions(cfg: dict, installed: str) -> list:
    versions = set(changelog_versions())
    versions.update(w.get("version") for w in cfg.get("notices_whatsnew") or [] if isinstance(w, dict) and w.get("version"))
    ok = [v for v in versions if v and _version_key(v) <= _version_key(installed) and whats_new_notes(cfg, v)]
    return sorted(ok, key=_version_key, reverse=True)[:MAX_WHATSNEW]


# --- обновление ---------------------------------------------------------------------------------------

def available_update(cfg: dict, installed: str = None) -> str:
    """Версия новее установленной, которую канал уже показал и которую человек не пропустил; иначе пусто.
    Сборка из Microsoft Store: всегда пусто. Её обновляет Store, канал ClipSD она не спрашивает; номер в настройках
    мог записать ClipSD с сайта на том же компьютере (общий %APPDATA%\\ClipSD), а в Store этой версии может ещё
    не быть: колокольчик не предлагает обновление, которого Store не даст (и не ведёт на скачивание с GitHub)."""
    from . import store
    if store.is_store_build():
        return ""
    installed = installed or __version__
    # без импорта updater: он тянет сетевые модули, а обычный снимок и редактор их не загружают (light_test).
    # Ключи те же, что у updater.seen_key: предварительная сборка смотрит канал proba, обычная stable
    from . import build_info
    key = "update_last_seen_version_proba" if build_info.is_preview() else "update_last_seen_version"
    seen = cfg.get(key) or ""
    skipped = cfg.get("update_skipped") or []
    if seen and _version_key(seen) > _version_key(installed) and seen not in skipped:
        return str(seen)
    return ""


# --- список -------------------------------------------------------------------------------------------

def items(cfg: dict, installed: str = None) -> list:
    """[{id, kind, title, sub, version?}] сверху вниз: обновление, «Что нового», сообщения (новые выше)."""
    installed = installed or __version__
    out = []
    new = available_update(cfg, installed)
    if new:
        out.append({"id": f"update:{new}", "kind": "update", "version": new,
                    "title": tr("notifications.update_title", version=new), "sub": tr("notifications.update_sub")})
    for v in _whatsnew_versions(cfg, installed):
        sub = tr("notifications.whatsnew_installed") if v == installed else tr("notifications.whatsnew_past")
        out.append({"id": f"whatsnew:{v}", "kind": "whatsnew", "version": v, "history": v != installed,   # прошлые: справка, без точки
                    "title": tr("notifications.whatsnew_title", version=v), "sub": sub})
    msgs = [m for m in (cfg.get("notices_messages") or []) if isinstance(m, dict) and m.get("kind") in MESSAGE_KEYS]
    for m in reversed(msgs):
        title_key, sub_key = MESSAGE_KEYS[m["kind"]]
        when = _parse(m.get("time"))
        stamp = when.astimezone().strftime("%d.%m %H:%M") if when else ""
        out.append({"id": m.get("id", ""), "kind": "message", "title": tr(title_key),
                    "sub": tr(sub_key) + (f" · {stamp}" if stamp else "")})
    return out


def read_ids(cfg: dict) -> set:
    return {str(x) for x in (cfg.get("notices_read") or [])}


def unread(cfg: dict, installed: str = None) -> list:
    """Непрочитанное (точка на колокольчике). «Что нового» прошлых версий это справка: непрочитанным не считается."""
    done = read_ids(cfg)
    return [it for it in items(cfg, installed) if it["id"] not in done and not it.get("history")]


def mark_read(cfg: dict, ids, save=None) -> None:
    have = [str(x) for x in (cfg.get("notices_read") or [])]
    for i in ids:
        if i and i not in have:
            have.append(i)
    cfg["notices_read"] = have[-MAX_READ:]
    if save is not None:
        save()
    _changed()


def first_run_seen(cfg: dict, installed: str = None) -> None:
    """Новая установка (знакомство ещё не пройдено): «Что нового» этой версии не считается непрочитанным."""
    installed = installed or __version__
    if not cfg.get("tour_done") and f"whatsnew:{installed}" not in read_ids(cfg):
        have = [str(x) for x in (cfg.get("notices_read") or [])]
        cfg["notices_read"] = (have + [f"whatsnew:{installed}"])[-MAX_READ:]
