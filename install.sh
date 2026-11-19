#!/usr/bin/env bash
# Установка Clipshot для текущего пользователя: зависимости, команда clipshot,
# ярлык в меню, автозапуск и горячая клавиша Alt+W (в GNOME — через системные сочетания).
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/.local/share/clipshot"
BIN="$HOME/.local/bin/clipshot"
DESKTOP_ENV="${XDG_CURRENT_DESKTOP:-}"
SESSION="${XDG_SESSION_TYPE:-x11}"

echo "==> Окружение: ${DESKTOP_ENV:-неизвестно}, сессия: $SESSION"

install_deps() {
  if command -v apt-get >/dev/null; then
    local pkgs=(python3 python3-pyqt6 python3-xlib libxcb-cursor0)
    [[ "$SESSION" == wayland && "$DESKTOP_ENV" == *GNOME* ]] && pkgs+=(gnome-screenshot)
    [[ "$SESSION" == wayland && "$DESKTOP_ENV" == *KDE* ]] && pkgs+=(kde-spectacle)
    [[ "$SESSION" == wayland && "$DESKTOP_ENV" != *GNOME* && "$DESKTOP_ENV" != *KDE* ]] && pkgs+=(grim)
    sudo apt-get update && sudo apt-get install -y "${pkgs[@]}"
  elif command -v dnf >/dev/null; then
    sudo dnf install -y python3 python3-pyqt6 python3-xlib xcb-util-cursor
  elif command -v pacman >/dev/null; then
    sudo pacman -S --needed --noconfirm python python-pyqt6 python-xlib xcb-util-cursor
  else
    echo "!! Неизвестный менеджер пакетов. Установите вручную: Python 3, PyQt6, python-xlib."
  fi
}

check_python() {
  if ! python3 -c "import PyQt6.QtWidgets" 2>/dev/null; then
    echo "==> PyQt6 из пакетов не найден, ставлю через pip (--user)"
    python3 -m pip install --user PyQt6 python-xlib || \
      python3 -m pip install --user --break-system-packages PyQt6 python-xlib
  fi
}

install_files() {
  rm -rf "$DEST"
  mkdir -p "$DEST" "$(dirname "$BIN")"
  cp -r "$SRC/clipshot" "$DEST/"
  cat > "$BIN" <<EOF
#!/bin/sh
PYTHONPATH="$DEST\${PYTHONPATH:+:\$PYTHONPATH}" exec python3 -m clipshot "\$@"
EOF
  chmod +x "$BIN"

  local desktop_file="[Desktop Entry]
Type=Application
Name=Clipshot
Comment=Снимки экрана с редактором
Exec=$BIN
Icon=applets-screenshooter
Terminal=false
Categories=Utility;Graphics;"
  mkdir -p "$HOME/.local/share/applications" "$HOME/.config/autostart"
  printf '%s\n' "$desktop_file" > "$HOME/.local/share/applications/clipshot.desktop"
  printf '%s\nX-GNOME-Autostart-enabled=true\n' "$desktop_file" > "$HOME/.config/autostart/clipshot.desktop"
}

setup_gnome_shortcut() {
  [[ "$DESKTOP_ENV" == *GNOME* ]] || return 0
  command -v gsettings >/dev/null || return 0
  local base="org.gnome.settings-daemon.plugins.media-keys"
  local path="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/clipshot/"
  local schema="$base.custom-keybinding:$path"
  local current new
  current="$(gsettings get "$base" custom-keybindings)"
  if [[ "$current" != *"$path"* ]]; then
    if [[ "$current" == "@as []" || "$current" == "[]" ]]; then
      new="['$path']"
    else
      new="${current%]}, '$path']"
    fi
    gsettings set "$base" custom-keybindings "$new"
  fi
  gsettings set "$schema" name "Clipshot — снимок области"
  gsettings set "$schema" command "$BIN --region"
  gsettings set "$schema" binding "<Alt>w"
  echo "==> GNOME: назначено Alt+W → $BIN --region"
}

install_deps
check_python
install_files
setup_gnome_shortcut

if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
  echo "!! ~/.local/bin нет в PATH — команда clipshot доступна как $BIN"
fi
if [[ "$SESSION" == wayland && "$DESKTOP_ENV" != *GNOME* ]]; then
  echo "!! Wayland без GNOME: назначьте Alt+W вручную в настройках клавиатуры на команду: $BIN --region"
fi

"$BIN" --quit || true
nohup "$BIN" >/dev/null 2>&1 &
echo "==> Готово. Clipshot запущен в трее. Нажмите Alt+W, чтобы снять область экрана."
