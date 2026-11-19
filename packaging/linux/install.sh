#!/usr/bin/env bash
# ClipSD: install for the current Linux user. No sudo, no internet, no Python on the machine needed.
# Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко). SPDX-License-Identifier: GPL-3.0-or-later
#
# Layout:  ~/.local/share/clipsd/versions/<version>/   program folder (this archive)
#          ~/.local/share/clipsd/current -> versions/<version>
#          ~/.local/bin/clipsd -> ~/.local/share/clipsd/current/clipsd   (constant path for autostart and service)
# Flags:   --force-replace-dev  install even if ~/.local/bin/clipsd belongs to another installation (a developer's
#                                working copy); the old command is kept as ~/.local/bin/clipsd.dev-backup
#          --refresh-integration  only the menu entry, the icons and the files of a GNOME extension that this
#                                package put there, from this folder (clipsd-switch runs it after an update
#                                from the program); nothing else: no service, no keys, no gsettings
# The running ClipSD is asked first ("quit-for-update" over its socket): with unsaved work in the editor
# it answers "busy", and the script stops without changing or stopping anything.
# Env:     CLIPSD_NO_SYSTEM=1  do not touch systemd, GNOME settings and do not start the program (checks)
set -euo pipefail

# Messages: Russian when the terminal language is Russian, else English. CLIPSD_LANG wins; then as gettext does:
# LANGUAGE (its first entry) unless the locale (LC_ALL, LC_MESSAGES, LANG) is C/POSIX, then the locale itself.
_lang_ru() {
  local loc="${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}" l
  case "$loc" in ""|C|C.*|POSIX) l="${CLIPSD_LANG:-$loc}" ;; *) l="${CLIPSD_LANG:-${LANGUAGE:-$loc}}" ;; esac
  l="${l%%:*}"
  case "$l" in ru|ru_*|ru.*) return 0 ;; *) return 1 ;; esac
}
if _lang_ru; then RU=1; else RU=0; fi
t() { if [ "$RU" = 1 ]; then printf '%s' "$1"; else printf '%s' "$2"; fi; }   # t "по-русски" "in English"

FORCE_DEV=0 REFRESH=0
for a in "$@"; do
  case "$a" in
    --force-replace-dev) FORCE_DEV=1 ;;
    --refresh-integration) REFRESH=1 ;;
    *) echo "$(t "Использование" "Usage"): install.sh [--force-replace-dev]" >&2; exit 2 ;;
  esac
done

SRC="$(cd "$(dirname "$0")" && pwd)"
VER="$(tr -d '[:space:]' < "$SRC/VERSION" 2>/dev/null || true)"
[ -n "$VER" ] || { echo "!!  $(t "Нет файла VERSION рядом с install.sh: запустите install.sh из распакованной папки clipsd-<версия>" "No file VERSION next to install.sh: run install.sh from the unpacked folder clipsd-<version>")" >&2; exit 1; }
[ -x "$SRC/clipsd" ] || { echo "!!  $(t "Нет исполняемого файла clipsd рядом с install.sh" "No executable file clipsd next to install.sh")" >&2; exit 1; }

DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
CONF="${XDG_CONFIG_HOME:-$HOME/.config}"
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/clipsd"
APP="$DATA/clipsd"
BIN="$HOME/.local/bin/clipsd"
UNIT_FILE="$CONF/systemd/user/clipsd.service"
AUTOSTART="$CONF/autostart/clipsd.desktop"
KB_PATH="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/clipsd/"
KB_BASE="org.gnome.settings-daemon.plugins.media-keys"
EXT_UUID="clipsd@clipsd.github.io"
EXT_SCHEMA="org.gnome.shell.extensions.clipsd"   # every ClipSD extension, old or new, declares this schema
PKG_MARK=".clipsd-package"   # file inside an extension folder that this script put there
NO_SYSTEM="${CLIPSD_NO_SYSTEM:-0}"

say() { printf '==> %s\n' "$*"; }
warn() { printf '!!  %s\n' "$*"; }
# uuids of earlier ClipSD extensions (another uuid, the same settings schema): recognised by the schema, not by name
old_ext_uuids() {
  local d m
  for d in "$DATA"/gnome-shell/extensions/*/; do
    d="${d%/}"; m="$d/metadata.json"
    [ -f "$m" ] && [ "$(basename "$d")" != "$EXT_UUID" ] && grep -q "\"settings-schema\": *\"$EXT_SCHEMA\"" "$m" 2>/dev/null \
      && basename "$d"
  done
  return 0
}
sysd() { [ "$NO_SYSTEM" = 1 ] || systemctl --user "$@" >/dev/null 2>&1; }

# schemas are read into a variable first: `grep -q` closing the pipe early would fail the pipeline under pipefail
has_schema() { local all; all="$(gsettings list-schemas 2>/dev/null)" || return 1; grep -qx "$1" <<< "$all"; }
has_gnome() { [ "$NO_SYSTEM" != 1 ] && command -v gsettings >/dev/null && has_schema "$KB_BASE"; }
list_has() { [[ "$1" == *"'$2'"* ]]; }
list_add() {  # $1 current gsettings array, $2 item
  if list_has "$1" "$2"; then printf '%s' "$1"
  elif [[ "$1" =~ ^(@as )?\[\]$ ]]; then printf "['%s']" "$2"
  else printf "%s, '%s']" "${1%]}" "$2"; fi
}
list_del() {  # $1 current gsettings array, $2 item
  local v="$1"
  v="${v//, \'$2\'/}"; v="${v//\'$2\', /}"; v="${v//\'$2\'/}"
  [[ "$v" == "[]" ]] && v="@as []"
  printf '%s' "$v"
}

# Menu entry and icons; the program command is always the constant path $BIN
write_menu_entry() {
  "$1/clipsd" --make-icons "$DATA/icons/hicolor" >/dev/null 2>&1 || warn "$(t "Значки не созданы (не критично)" "Icons were not created (not critical)")"
  command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -f -t "$DATA/icons/hicolor" >/dev/null 2>&1 || true
  mkdir -p "$DATA/applications"
  cat > "$DATA/applications/clipsd.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=ClipSD
GenericName=Screenshot
GenericName[ru]=Снимок экрана
Comment=Screenshots with an editor: arrows, numbers, callouts, blur (Alt+W)
Comment[ru]=Снимки экрана с редактором: стрелки, номера, сноски, размытие (Alt+W)
Exec=$BIN --region
Icon=clipsd
Terminal=false
Categories=Utility;Graphics;
Keywords=screenshot;скриншот;снимок;
StartupWMClass=ClipSD
DESK
}

# Files of the package's GNOME extension into $1 (the folder is replaced, the mark written)
put_extension() {
  rm -rf "$1"; mkdir -p "$1"
  cp -r "$SRC/gnome-extension/$EXT_UUID/." "$1/"
  printf 'installed by ClipSD package %s\n' "$VER" > "$1/$PKG_MARK"
  command -v glib-compile-schemas >/dev/null && glib-compile-schemas "$1/schemas" || true
}

if [ "$REFRESH" = 1 ]; then
  # After an update from the program: the new version's menu entry, icons and extension files. The menu
  # entry only if the package made one, the extension only if its folder carries the package mark.
  [ -f "$DATA/applications/clipsd.desktop" ] && write_menu_entry "$SRC"
  EXT="$DATA/gnome-shell/extensions/$EXT_UUID"
  if [ -e "$EXT/$PKG_MARK" ] && [ -d "$SRC/gnome-extension/$EXT_UUID" ]; then
    put_extension "$EXT"
    say "$(t "Расширение GNOME обновлено до $VER (заработает после повторного входа в систему)" "GNOME extension updated to $VER (it will work after you log out and back in)")"
  fi
  exit 0
fi

# libxcb-cursor travels inside the build; only the Qt platform libraries of the system are required.
[ "$(uname -m)" = x86_64 ] || { warn "$(t "Сборка только для x86_64, у вас $(uname -m)" "This build is for x86_64 only; your system is $(uname -m)")"; exit 1; }

# 0. The command ~/.local/bin/clipsd must be ours: a link into $APP, or the wrapper of the 1.x package.
#    Anything else is another installation (a developer's working copy): it is not touched without the flag.
IS_1X=0
{ [ -d "$APP/venv" ] || [ -d "$APP/app" ]; } && IS_1X=1
bin_is_ours() {
  [ -e "$BIN" ] || [ -L "$BIN" ] || return 0
  if [ -L "$BIN" ]; then
    case "$(readlink "$BIN")" in "$APP"/*) return 0 ;; esac
    case "$(readlink -f "$BIN" 2>/dev/null)" in "$(readlink -f "$APP")"/*) return 0 ;; esac
    return 1
  fi
  [ "$IS_1X" = 1 ] && return 0
  grep -qE 'share/clipsd(/|"|$)' "$BIN" 2>/dev/null
}
BIN_OURS=1
if ! bin_is_ours; then
  BIN_OURS=0
  if [ "$FORCE_DEV" != 1 ]; then
    warn "$(t "Найдена другая установка ClipSD (рабочая копия): $BIN не ссылается на $APP. Пакет не поставлен." "Another ClipSD installation found (a working copy): $BIN does not point to $APP. The package was not installed.")"
    warn "$(t "Чтобы всё же поставить пакет, сохранив прежнюю команду как $BIN.dev-backup: install.sh --force-replace-dev" "To install the package anyway and save the existing command as $BIN.dev-backup: install.sh --force-replace-dev")"
    exit 3
  fi
fi

# 0b. The running ClipSD (2.x) is asked to quit before anything changes: "busy" means an editor with
#     unsaved work or text being typed; then nothing is copied, switched or stopped.
# Why ClipSD cannot quit now (reply busy:<reason> of the running program), in words
busy_text() {
  case "$1" in
    busy:selector) t "открыто окно выделения области. Закройте его (Esc)" \
                      "the area selection is open. Close it (Esc)" ;;
    busy:dialog) t "открыто окно ClipSD (например, настройки). Закройте его" \
                    "a ClipSD window is open (for example, settings). Close it" ;;
    busy:text) t "в редакторе идёт ввод текста. Закончите ввод и закройте редактор (сохраните или скопируйте снимок)" \
                  "text input is active in the editor. Finish entering the text and close the editor (save or copy the screenshot)" ;;
    *) t "в редакторе есть несохранённые пометки. Закройте редактор ClipSD (сохраните или скопируйте снимок)" \
          "the editor has unsaved marks. Close the ClipSD editor (save or copy the screenshot)" ;;
  esac
}
ask_running() {  # prints ok | busy:<reason> | none
  local helper="$SRC/clipsd-switch"
  [ -x "$helper" ] || helper="$APP/current/clipsd-switch"
  [ -x "$helper" ] || { echo none; return; }
  "$helper" --ask-quit 2>/dev/null | tail -n 1
}
if [ "$NO_SYSTEM" != 1 ] && [ "$BIN_OURS" = 1 ]; then
  answer="$(ask_running)" || answer=none
  case "$answer" in busy*)
    warn "$(t "ClipSD сейчас нельзя закрыть" "ClipSD cannot be closed now"): $(busy_text "$answer")."
    warn "$(t "Потом повторите установку. Ничего не изменено." "Then run the installation again. Nothing was changed.")"
    exit 4 ;;
  esac
  [ "$answer" = ok ] && say "$(t "ClipSD закрыт для обновления, настройки сохранены" "ClipSD was closed for the update; settings were saved")"
fi
# ClipSD 1.x cannot answer "busy": it is simply closed below. Unsaved marks in its editor would be lost.
if [ "$IS_1X" = 1 ] && [ "$NO_SYSTEM" != 1 ]; then
  warn "$(t "Найдена ClipSD 1.x. Она будет закрыта без вопроса: если в её редакторе есть несохранённые пометки," "ClipSD 1.x found. It will be closed without asking: if its editor has unsaved marks,")"
  warn "$(t "сохраните или скопируйте снимок и закройте редактор." "save or copy the screenshot and close the editor.")"
  if [ -t 0 ]; then read -r -p "$(t "Нажмите Enter, чтобы продолжить (Ctrl+C: отменить) " "Press Enter to continue (Ctrl+C: cancel) ")" _ || true; fi
fi

# 1. Copy the new version next to the others first: a failure here leaves the old program untouched.
say "$(t "Копирую программу в $APP/versions/$VER" "Copying the program to $APP/versions/$VER")"
mkdir -p "$APP/versions" "$STATE" "$(dirname "$BIN")"
STAGE="$APP/versions/.stage-$VER.$$"
trap 'rm -rf "$STAGE"' EXIT
rm -rf "$STAGE"
cp -a "$SRC/." "$STAGE/"

# 2. Stop the running copy (any version, including 1.x); a foreign command is never asked to quit
if [ "$NO_SYSTEM" != 1 ]; then
  [ "$BIN_OURS" = 1 ] && [ -e "$BIN" ] && timeout 10 "$BIN" --quit >/dev/null 2>&1 || true
  sysd stop clipsd.service
  sleep 1
fi

# 3a. Forced replacement: keep the foreign command
if [ "$BIN_OURS" = 0 ]; then
  mv -f "$BIN" "$BIN.dev-backup"
  warn "$(t "Прежняя команда сохранена как $BIN.dev-backup" "The previous command was saved as $BIN.dev-backup")"
fi

# 3. Move from 1.x: venv and the old wrapper go, settings (~/.config/clipshot) stay where the program reads them
if [ -d "$APP/venv" ] || [ -d "$APP/app" ]; then
  say "$(t "Найдена версия 1.x: настройки сохранены, прежнее окружение Python удаляю" "Version 1.x found: settings kept, removing its old Python environment")"
  rm -rf "$APP/venv" "$APP/app"
fi

# 4. Put the version in place and switch atomically
rm -rf "$APP/versions/$VER"
mv "$STAGE" "$APP/versions/$VER"
ln -sfn "versions/$VER" "$APP/.current.$$" && mv -T "$APP/.current.$$" "$APP/current"
ln -sfn "$APP/current/clipsd" "$HOME/.local/bin/.clipsd.$$" && mv -T "$HOME/.local/bin/.clipsd.$$" "$BIN"
rm -f "$STATE/started-$VER"

# 5. Icons and menu entry
say "$(t "Значки и ярлык в меню приложений" "Icons and the application menu entry")"
write_menu_entry "$APP/current"

if [ "$NO_SYSTEM" = 1 ]; then
  say "$(t "Проверочный режим: службу, клавиши и запуск не настраиваю" "Check mode: the service, keyboard shortcuts, and startup will not be configured")"
  exit 0
fi

# 6. Autostart: systemd user service if the session has one, otherwise the desktop autostart.
#    Both always point at the constant path ~/.local/bin/clipsd.
if systemctl --user is-active --quiet graphical-session.target 2>/dev/null; then
  mkdir -p "$(dirname "$UNIT_FILE")"
  cat > "$UNIT_FILE" <<UNIT
[Unit]
Description=ClipSD: screenshots with an editor (Alt+W)
PartOf=graphical-session.target
After=graphical-session.target

[Service]
ExecStart=$BIN
Restart=on-failure
RestartSec=2

[Install]
WantedBy=graphical-session.target
UNIT
  rm -f "$AUTOSTART"
  sysd daemon-reload
  sysd enable clipsd.service
  sysd restart clipsd.service || warn "$(t "Служба не запустилась" "The service did not start"): $BIN"
  say "$(t "ClipSD запущен как служба и будет стартовать при входе в систему" "ClipSD is running as a service and will start when you log in")"
else
  rm -f "$UNIT_FILE"
  mkdir -p "$(dirname "$AUTOSTART")"
  sed 's#^Exec=.*#Exec='"$BIN"'#' "$DATA/applications/clipsd.desktop" > "$AUTOSTART"
  echo "X-GNOME-Autostart-enabled=true" >> "$AUTOSTART"
  setsid nohup "$BIN" >/dev/null 2>&1 </dev/null &
  say "$(t "ClipSD запущен и будет стартовать при входе в систему (автозапуск рабочего стола)" "ClipSD is running and will start when you log in (desktop autostart)")"
fi

# 7. The new version must confirm the start; only then old versions are removed
for _ in $(seq 1 40); do [ -f "$STATE/started-$VER" ] && break; sleep 0.5; done
if [ -f "$STATE/started-$VER" ]; then
  for d in "$APP"/versions/*/; do
    [ -d "$d" ] && [ "$(basename "$d")" != "$VER" ] && rm -rf "$d"
  done
else
  warn "$(t "Программа не подтвердила запуск за 20 с (нет $STATE/started-$VER); прежние версии оставлены" "The program did not confirm that it started within 20 s (no $STATE/started-$VER); older versions were kept")"
fi

# 8. Alt+W and the GNOME extension
if has_gnome; then
  # Alt+W of the built-in GNOME screenshot tool goes to ClipSD; the previous value is saved for uninstall.
  if has_schema org.gnome.shell.keybindings; then
    current="$(gsettings get org.gnome.shell.keybindings show-screenshot-ui)"
    [ -f "$APP/gnome-screenshot-keys.bak" ] || printf '%s\n' "$current" > "$APP/gnome-screenshot-keys.bak"
    cleaned="$(printf '%s' "$current" | sed -E "s/'<[Aa]lt>([Ww]|[Cc]yrillic_tse)'(, )?//g; s/, \]/]/")"
    gsettings set org.gnome.shell.keybindings show-screenshot-ui "$cleaned"
  fi
  gsettings set $KB_BASE custom-keybindings "$(list_add "$(gsettings get $KB_BASE custom-keybindings)" "$KB_PATH")"
  gsettings set "$KB_BASE.custom-keybinding:$KB_PATH" name "$(t "ClipSD: снимок области" "ClipSD: area screenshot")"
  gsettings set "$KB_BASE.custom-keybinding:$KB_PATH" command "$BIN --region"
  gsettings set "$KB_BASE.custom-keybinding:$KB_PATH" binding "<Alt>w"
  say "$(t "Alt+W назначен на ClipSD (запасное сочетание, работает сразу на латинской раскладке)" "Alt+W now opens ClipSD (a fallback shortcut, works right away with a Latin layout)")"

  # Extension: the old one (1.x) goes if it is ours, the new one is put in place and switched on.
  enabled="$(gsettings get org.gnome.shell enabled-extensions 2>/dev/null || echo '@as []')"
  # The old extension (1.x) is switched off and removed only if it is ours: marked by this script, a link into $APP,
  # or left by the 1.x package. A real folder without the mark (a developer's working copy) stays untouched.
  KEEP_OLD=""
  for OLD_EXT_UUID in $(old_ext_uuids); do
    OLD_EXT="$DATA/gnome-shell/extensions/$OLD_EXT_UUID"
    if [ -e "$OLD_EXT/$PKG_MARK" ] || [ "$IS_1X" = 1 ] || { [ -L "$OLD_EXT" ] && [[ "$(readlink "$OLD_EXT")" == "$APP"/* ]]; }; then
      if list_has "$enabled" "$OLD_EXT_UUID"; then
        command -v gnome-extensions >/dev/null && gnome-extensions disable "$OLD_EXT_UUID" >/dev/null 2>&1 || true
        enabled="$(list_del "$enabled" "$OLD_EXT_UUID")"
      fi
      rm -rf "$OLD_EXT"
    elif list_has "$enabled" "$OLD_EXT_UUID"; then
      KEEP_OLD="$OLD_EXT_UUID"
    fi
  done
  EXT="$DATA/gnome-shell/extensions/$EXT_UUID"
  if [ -n "$KEEP_OLD" ]; then
    # The working copy's extension (same keys, same D-Bus object) stays on; a second one would fight it for Alt+W.
    # ClipSD finds the old one too (settings.py legacy_ext_uuids, by the same schema), so both layouts keep working.
    warn "$(t "Включено прежнее расширение $KEEP_OLD (рабочая копия): оставляю его, новое $EXT_UUID не ставлю" "The older extension $KEEP_OLD (a working copy) is enabled: keeping it, not installing the new $EXT_UUID")"
  elif [ -e "$EXT" ] && [ ! -e "$EXT/$PKG_MARK" ] && [ "$IS_1X" != 1 ] && [ -d "$EXT" ] && [ -n "$(ls -A "$EXT" 2>/dev/null)" ]; then
    warn "$(t "Папка расширения $EXT создана не этим пакетом, не трогаю" "The extension folder $EXT was not made by this package, leaving it alone")"
  elif [ -d "$SRC/gnome-extension/$EXT_UUID" ]; then
    put_extension "$EXT"
    enabled="$(list_add "$enabled" "$EXT_UUID")"
    say "$(t "Расширение «ClipSD: hotkeys» (Alt+W на любой раскладке, например Alt+Ц) включится после выхода из системы и повторного входа" "The extension \"ClipSD: hotkeys\" (Alt+W on any keyboard layout, for example Alt+Ц) will be enabled after you log out and back in")"
  fi
  gsettings set org.gnome.shell enabled-extensions "$enabled"
else
  warn "$(t "Не GNOME: назначьте Alt+W в настройках клавиатуры на команду" "Not running GNOME: assign Alt+W to the following command in the keyboard settings"): $BIN --region"
  warn "$(t "(в сеансе X11 ClipSD перехватывает Alt+W сам, ничего делать не нужно)" "(in an X11 session, ClipSD handles Alt+W itself, so no action is needed)")"
fi

if command -v systemctl >/dev/null && { systemctl --user is-enabled --quiet clipshot.service 2>/dev/null || systemctl --user is-active --quiet clipshot.service 2>/dev/null; }; then
  warn "$(t "Работает ещё и clipshot.service (рабочая копия): две программы делят Alt+W и значок. Отключите" "clipshot.service (a working copy) is running too: two programs share Alt+W and the icon. Turn it off"): systemctl --user disable --now clipshot.service"
fi
[[ ":$PATH:" == *":$HOME/.local/bin:"* ]] || warn "$(t "Папки ~/.local/bin нет в PATH: команда доступна как" "~/.local/bin is not in PATH: the command is") $BIN"
say "$(t "Готово. Нажмите Alt+W и выделите область экрана." "Done. Press Alt+W and select an area of the screen.")"
