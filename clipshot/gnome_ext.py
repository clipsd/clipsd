# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Обновить или поставить дополнение ClipSD в GNOME кнопкой из программы (правило владельца 21.11.2026: если системе
не хватает возможностей, программа сама объясняет и предлагает кнопку; команды руками только запасной путь).

Делает то же, что install.sh (put_extension и включение): файлы дополнения из сборки в
~/.local/share/gnome-shell/extensions/clipsd@clipsd.github.io, метка пакета, схема настроек, включение в
org.gnome.shell enabled-extensions. Пароль не нужен: всё в папке пользователя.
Не трогает дополнение, поставленное не пакетом (рабочая копия разработчика): папка без метки или прежнее
дополнение с той же схемой, включённое и без метки. Под Wayland GNOME подхватывает новое дополнение только после
выхода из сеанса и входа: это говорится человеку, сама программа из сеанса не выводит."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .sysenv import child_env

EXT_UUID = "clipsd@clipsd.github.io"
EXT_SCHEMA = "org.gnome.shell.extensions.clipsd"
PKG_MARK = ".clipsd-package"   # тот же файл-метка, что пишет install.sh

INSTALLED, UPDATED, FOREIGN, NO_SOURCE, FAILED = "installed", "updated", "foreign", "no-source", "failed"
REPLACED = "replaced"   # со согласия человека: старое дополнение выключено и отложено, своё поставлено
USER_EXT_OFF, UNSUPPORTED = "user-extensions-off", "unsupported"   # проверка 1.33, О-М6: вход ничего бы не дал


def extensions_base() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "gnome-shell/extensions"


def bundled_dir() -> Path | None:
    """Файлы дополнения этой версии ClipSD: рядом с программой в готовой сборке (gnome-extension/ в папке версии)
    или в packaging/ при запуске из исходников."""
    here = Path(__file__).resolve().parent
    candidates = [here.parent / "packaging/gnome-extension" / EXT_UUID]
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve().parent
        candidates[:0] = [exe / "gnome-extension" / EXT_UUID, exe.parent / "gnome-extension" / EXT_UUID]
    return next((c for c in candidates if (c / "metadata.json").is_file()), None)


def _schema_of(folder: Path) -> str:
    try:
        meta = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return meta.get("settings-schema", "") if isinstance(meta, dict) else ""


def installed_any(base: Path = None) -> bool:
    """В папке пользователя есть дополнение ClipSD (новое или прежнее с той же схемой)."""
    base = Path(base) if base is not None else extensions_base()
    try:
        return any(p.is_dir() and (p.name == EXT_UUID or _schema_of(p) == EXT_SCHEMA) for p in base.iterdir())
    except OSError:
        return False


def _gsettings(run, *args) -> str:
    out = run(["gsettings", *args], capture_output=True, text=True, timeout=5, env=child_env())
    if out.returncode != 0:
        raise RuntimeError((out.stderr or "").strip() or "gsettings")
    return (out.stdout or "").strip()


def _parse_list(text: str) -> list:
    text = text.strip()
    if text.startswith("@as"):
        text = text[3:].strip()
    try:
        import ast
        value = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return []
    return [str(v) for v in value] if isinstance(value, (list, tuple)) else []


def _gvariant_list(items) -> str:
    return "[" + ", ".join("'" + i.replace("'", "") + "'" for i in items) + "]" if items else "@as []"


def _remove(path: Path):
    """Убрать папку или ссылку (ссылку саму, а не то, на что она указывает)."""
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _shell_major(run) -> str:
    """Главный номер версии GNOME Shell («50») или пусто, если узнать не вышло."""
    try:
        out = run(["gnome-shell", "--version"], capture_output=True, text=True, timeout=10, env=child_env())
    except (OSError, subprocess.SubprocessError):
        return ""
    words = (getattr(out, "stdout", "") or "").split()
    return words[-1].split(".")[0] if words and words[-1][:1].isdigit() else ""


def update(src: Path = None, base: Path = None, run=subprocess.run, version: str = "", replace: bool = False,
           fallback=None, today: str = "") -> tuple:
    """Поставить или обновить дополнение. Возвращает (итог, подробность): INSTALLED, UPDATED, FOREIGN, NO_SOURCE,
    USER_EXT_OFF (в GNOME выключены все пользовательские дополнения), UNSUPPORTED (подробность: версия GNOME),
    FAILED. run: подмена subprocess.run в тестах (gsettings, gnome-shell --version, glib-compile-schemas).

    replace=True (человек согласился в окне «Найдено старое дополнение»): прежнее чужое дополнение с той же схемой
    или папка цели без метки не блокируют, а выключаются и откладываются в сторону (папка переименовывается в
    <имя>.disabled-by-clipsd-<дата>, ничего не удаляется), итог REPLACED. fallback: вызываемое без аргументов, оно
    включает запасные сочетания GNOME (обычное сочетание клавиш системы) ДО выключения старого дополнения, чтобы
    Alt+W не пропадал ни на минуту: новое дополнение загрузится только после выхода из системы и входа. Если
    fallback упал, ничего не выключается (FAILED).

    Порядок: сначала новые файлы собираются рядом (.new), потом включение в enabled-extensions, и только потом
    прежняя папка заменяется новой. Не удалось включить: новая папка убирается, прежнее дополнение не тронуто."""
    src = Path(src) if src is not None else bundled_dir()
    if src is None or not (src / "metadata.json").is_file():
        return NO_SOURCE, ""
    base = Path(base) if base is not None else extensions_base()
    target = base / EXT_UUID
    try:
        enabled = _parse_list(_gsettings(run, "get", "org.gnome.shell", "enabled-extensions"))
        user_off = _gsettings(run, "get", "org.gnome.shell", "disable-user-extensions").strip() == "true"
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        return FAILED, str(exc)
    if user_off:
        return USER_EXT_OFF, ""
    major = _shell_major(run)
    try:
        supported = json.loads((src / "metadata.json").read_text(encoding="utf-8")).get("shell-version") or []
    except (OSError, ValueError):
        supported = []
    if major and supported and major not in supported:
        return UNSUPPORTED, major
    # Прежнее дополнение ClipSD (другое имя, та же схема): чужое и включённое (рабочая копия) не трогаем совсем,
    # своё (с меткой пакета) выключаем, как install.sh, чтобы два дополнения не спорили за Alt+W.
    legacy_ours = []
    aside = []   # чужие (при replace): выключаются и откладываются, не удаляются
    try:
        folders = sorted(p for p in base.iterdir() if p.is_dir() and p.name != EXT_UUID) if base.is_dir() else []
    except OSError:
        folders = []
    for folder in folders:
        if _schema_of(folder) != EXT_SCHEMA:
            continue
        if (folder / PKG_MARK).exists():
            legacy_ours.append(folder)
        elif folder.name in enabled:
            if not replace:
                return FOREIGN, folder.name
            aside.append(folder)
    if target.exists() and not (target / PKG_MARK).exists() and any(target.iterdir()):
        if not replace:
            return FOREIGN, target.name
        aside.append(target)
    existed = (target.exists() or target.is_symlink()) and target not in aside
    fresh = base / f".{EXT_UUID}.new"
    old = base / f".{EXT_UUID}.old"
    try:
        base.mkdir(parents=True, exist_ok=True)
        for leftover in (fresh, old):
            _remove(leftover)
        shutil.copytree(src, fresh)
        (fresh / PKG_MARK).write_text(f"installed by ClipSD {version}".strip() + "\n", encoding="utf-8")
        if shutil.which("glib-compile-schemas") and (fresh / "schemas").is_dir():
            run(["glib-compile-schemas", str(fresh / "schemas")], capture_output=True, timeout=15, env=child_env())
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        try:
            _remove(fresh)
        except OSError:
            pass
        return FAILED, str(exc)
    wanted = [u for u in enabled if u not in {f.name for f in (*legacy_ours, *aside)}]
    if EXT_UUID not in wanted:
        wanted.append(EXT_UUID)
    if aside and fallback is not None:
        # Старое дополнение вот-вот перестанет держать Alt+W, а новое загрузится только после входа в систему:
        # запасное сочетание GNOME включается ПЕРВЫМ, пока старое ещё работает. Не вышло: ничего не выключаем.
        try:
            fallback()
        except Exception as exc:   # запасной путь не должен ронять замену неясным исключением
            _remove(fresh)
            return FAILED, str(exc)
    def _restore_enabled():
        try:
            if wanted != enabled:
                _gsettings(run, "set", "org.gnome.shell", "enabled-extensions", _gvariant_list(enabled))
        except (OSError, RuntimeError, subprocess.SubprocessError):
            pass
    try:
        if wanted != enabled:
            _gsettings(run, "set", "org.gnome.shell", "enabled-extensions", _gvariant_list(wanted))
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        try:
            _remove(fresh)   # включить не вышло: прежнее дополнение остаётся как было
        except OSError:
            pass
        return FAILED, str(exc)
    moved = []   # (отложенная папка, прежнее место): для отката
    try:
        stamp = today or __import__("datetime").date.today().strftime("%Y%m%d")
        for folder in aside:
            dest = folder.with_name(f"{folder.name}.disabled-by-clipsd-{stamp}")
            n = 2
            while dest.exists() or dest.is_symlink():
                dest = folder.with_name(f"{folder.name}.disabled-by-clipsd-{stamp}-{n}")
                n += 1
            folder.rename(dest)
            moved.append((dest, folder))
    except OSError as exc:
        for dest, orig in reversed(moved):
            try:
                dest.rename(orig)
            except OSError:
                pass
        _restore_enabled()
        try:
            _remove(fresh)
        except OSError:
            pass
        return FAILED, str(exc)
    try:
        if existed:
            target.rename(old)
        fresh.rename(target)
    except OSError as exc:
        if (old.exists() or old.is_symlink()) and not target.exists():
            try:
                old.rename(target)   # прежнее дополнение возвращается на место
            except OSError:
                pass
        for dest, orig in reversed(moved):
            try:
                dest.rename(orig)
            except OSError:
                pass
        if moved:
            _restore_enabled()
        return FAILED, str(exc)
    for leftover in (old, *legacy_ours):
        try:
            _remove(leftover)
        except OSError:
            pass
    return (REPLACED if aside else UPDATED if existed or legacy_ours else INSTALLED), ""


def open_folder() -> bool:
    """Папка дополнений пользователя в файловом менеджере (если замена не удалась)."""
    base = extensions_base()
    try:
        base.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["xdg-open", str(base)], env=child_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


def log_out():
    """Стандартное окно GNOME «Выйти из системы?» (с отсчётом и отменой); сам ClipSD никого не выводит."""
    try:
        subprocess.Popen(["gnome-session-quit", "--logout"], env=child_env(),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False
