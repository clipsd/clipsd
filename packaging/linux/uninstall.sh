#!/usr/bin/env bash
# ClipSD: uninstall for the current user. Settings and screenshots go only with --purge.
# Only what the package put there is removed: ~/.local/bin/clipsd if it links into the program folder, the GNOME
# extensions if marked by install.sh. A developer's working copy (~/.config/clipshot, clipshot.service) is never touched.
# The running ClipSD is asked first ("quit-for-update" over its socket): with unsaved work in the editor it answers
# "busy", and nothing is removed or stopped.
# ~/.local/state/clipsd and ~/.cache/clipsd are shared with ClipSD run from the sources (a developer's copy): when
# it has been there (mark .source-run, written by such a run, or its command / service), only the package's own
# files go (start marks, update results and log, the socket); otherwise the whole folders.
# Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко). SPDX-License-Identifier: GPL-3.0-or-later
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
# Env: CLIPSD_NO_SYSTEM=1  do not touch systemd and GNOME settings
set -uo pipefail

DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
CONF="${XDG_CONFIG_HOME:-$HOME/.config}"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}"
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/clipsd"
APP="$DATA/clipsd"
BIN="$HOME/.local/bin/clipsd"
KB_PATH="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/clipsd/"
KB_BASE="org.gnome.settings-daemon.plugins.media-keys"
NO_SYSTEM="${CLIPSD_NO_SYSTEM:-0}"
PKG_MARK=".clipsd-package"
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

PURGE=0
for a in "$@"; do
  case "$a" in
    --purge) PURGE=1 ;;
    *) echo "$(t "Использование: uninstall.sh [--purge]   (--purge: удалить и настройки ~/.config/clipsd, и снимки ClipSD)" "Usage: uninstall.sh [--purge]   (--purge: also delete the settings ~/.config/clipsd and the ClipSD screenshots)")" >&2; exit 2 ;;
  esac
done

list_del() {
  local v="$1"
  v="${v//, \'$2\'/}"; v="${v//\'$2\', /}"; v="${v//\'$2\'/}"
  [[ "$v" == "[]" ]] && v="@as []"
  printf '%s' "$v"
}

# 0 (true) if the command is a link into the program folder or the wrapper of the 1.x package
bin_is_ours() {
  [ -e "$BIN" ] || [ -L "$BIN" ] || return 0   # nothing there: nothing foreign either
  if [ -L "$BIN" ]; then
    case "$(readlink "$BIN")" in "$APP"/*) return 0 ;; esac
    case "$(readlink -f "$BIN" 2>/dev/null)" in "$(readlink -f "$APP")"/*) return 0 ;; esac
    return 1
  fi
  [ -f "$BIN" ] && { [ -d "$APP/venv" ] || [ -d "$APP/app" ] || grep -qE 'share/clipsd(/|"|$)' "$BIN" 2>/dev/null; }
}

# 0 (true) if the extension folder was put there by the package (mark, or a link into the program folder)
ext_is_ours() {
  [ -e "$1/$PKG_MARK" ] && return 0
  [ -L "$1" ] && [[ "$(readlink "$1")" == "$APP"/* ]]
}

# Traces of ClipSD run from the sources on this machine (it shares the state and cache folders)
source_run_traces() {
  [ -e "$STATE/.source-run" ] || [ -e "$HOME/.local/bin/clipshot" ] || [ -e "$CONF/systemd/user/clipshot.service" ]
}

# Only what the package and its update helper write there
remove_package_state() {
  rm -rf "$STATE/update.lock"
  rm -f "$STATE"/started-* "$STATE"/update-* "$STATE"/.update-result.* "$STATE/update.log"
  [ -S "$CACHE/clipsd/clipsd.sock" ] && rm -f "$CACHE/clipsd/clipsd.sock"
  rmdir "$STATE" "$CACHE/clipsd" 2>/dev/null
  return 0
}

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
  local helper="$(dirname "$0")/clipsd-switch"
  [ -x "$helper" ] || helper="$APP/current/clipsd-switch"
  [ -x "$helper" ] || { echo none; return; }
  "$helper" --ask-quit 2>/dev/null | tail -n 1
}

main() {
  OURS=0; bin_is_ours && OURS=1
  if [ "$OURS" = 1 ]; then
    answer="$(ask_running)"
    case "$answer" in busy*)
      echo "!!  $(t "ClipSD сейчас нельзя закрыть" "ClipSD cannot be closed now"): $(busy_text "$answer")." >&2
      echo "!!  $(t "Потом повторите удаление. Ничего не изменено." "Then run the uninstallation again. Nothing was changed.")" >&2
      return 4 ;;
    esac
  fi
  EXT_OWN=()
  # the package's extension and earlier ClipSD extensions (recognised by the settings schema, not by name)
  for d in "$DATA"/gnome-shell/extensions/*/; do
    d="${d%/}"; uuid="$(basename "$d")"
    [ "$uuid" = clipsd@clipsd.github.io ] || grep -q '"settings-schema": *"org.gnome.shell.extensions.clipsd"' "$d/metadata.json" 2>/dev/null || continue
    ext_is_ours "$d" && EXT_OWN+=("$uuid")
  done
  [ "$OURS" = 1 ] && [ -e "$BIN" ] && timeout 10 "$BIN" --quit >/dev/null 2>&1
  if [ "$NO_SYSTEM" != 1 ]; then
    systemctl --user disable --now clipsd.service >/dev/null 2>&1
    systemctl --user stop 'clipsd-update-*' 'clipsd-app-*' >/dev/null 2>&1
  fi
  rm -f "$CONF/systemd/user/clipsd.service" "$CONF/autostart/clipsd.desktop"
  # menu entry and icons share their names with a working copy: removed only when the command is the package's
  [ "$OURS" = 1 ] && rm -f "$BIN" "$DATA/applications/clipsd.desktop"
  [ "$NO_SYSTEM" = 1 ] || systemctl --user daemon-reload >/dev/null 2>&1
  [ "$OURS" = 1 ] && rm -f "$DATA"/icons/hicolor/*/apps/clipsd.png

  # The Alt+W binding is ClipSD's only when the command ~/.local/bin/clipsd is ours (a working copy may use the same path)
  if [ "$NO_SYSTEM" != 1 ] && command -v gsettings >/dev/null &&
     grep -qx "$KB_BASE" <<< "$(gsettings list-schemas 2>/dev/null)"; then
    if [ "$OURS" = 1 ]; then
      gsettings set $KB_BASE custom-keybindings "$(list_del "$(gsettings get $KB_BASE custom-keybindings)" "$KB_PATH")"
      gsettings reset-recursively "$KB_BASE.custom-keybinding:$KB_PATH" 2>/dev/null
      [ -f "$APP/gnome-screenshot-keys.bak" ] &&
        gsettings set org.gnome.shell.keybindings show-screenshot-ui "$(cat "$APP/gnome-screenshot-keys.bak")"
    fi
    enabled="$(gsettings get org.gnome.shell enabled-extensions 2>/dev/null || echo '@as []')"
    for uuid in ${EXT_OWN[@]+"${EXT_OWN[@]}"}; do
      [[ "$enabled" == *"'$uuid'"* ]] && enabled="$(list_del "$enabled" "$uuid")"
      command -v gnome-extensions >/dev/null && gnome-extensions disable "$uuid" >/dev/null 2>&1
    done
    gsettings set org.gnome.shell enabled-extensions "$enabled"
  fi
  for uuid in ${EXT_OWN[@]+"${EXT_OWN[@]}"}; do
    rm -rf "$DATA/gnome-shell/extensions/$uuid"
  done

  rm -rf "$APP"
  if source_run_traces; then
    remove_package_state
  else
    rm -rf "$STATE" "$CACHE/clipsd"
  fi

  if [ "$PURGE" = 1 ]; then
    # Settings of the package live in ~/.config/clipsd; ~/.config/clipshot belongs to the working copy and is never removed
    cfg="$CONF/clipsd/config.json"
    if [ -f "$cfg" ]; then
      dir="$(sed -n 's/.*"auto_save_dir": *"\([^"]*\)".*/\1/p' "$cfg" | head -1)"
      dir="${dir/#\~/$HOME}"
      # Only files named by ClipSD autosave, in a dedicated folder deeper than one level under HOME;
      # the folder goes only if it becomes empty
      case "$dir" in
        "$HOME"/*/*)
          if [ -d "$dir" ]; then
            find "$dir" -maxdepth 1 -type f -regextype posix-extended \
              -regex '.*/Screenshot_[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}-[0-9]{2}-[0-9]{2}(_[0-9]+)?\.(png|jpg)' -delete
            rmdir "$dir" 2>/dev/null
          fi ;;
      esac
    fi
    rm -rf "$CONF/clipsd"
    echo "$(t "ClipSD удалён вместе с настройками и снимками ClipSD (--purge)." "ClipSD, its settings, and its screenshots were removed (--purge).")"
  else
    echo "$(t "ClipSD удалён. Настройки (~/.config/clipsd) и снимки сохранены; удалить и их: uninstall.sh --purge" "ClipSD was removed. Settings (~/.config/clipsd) and screenshots were kept; to delete them too, run: uninstall.sh --purge")"
  fi
}
main "$@"; exit $?
