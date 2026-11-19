ClipSD: screenshots with an editor (Linux, ready-made build)
Copyright (C) 2026 Sergey Dayneko. Licence: GNU GPL v3 or later, official text in the file LICENSE
  (a plain-language Russian summary is in LICENSE.ru.txt). По-русски: README.txt.

Install (Ubuntu, Debian, Fedora, Mint and others; GNOME, KDE, XFCE; X11 or Wayland)
  1. Unpack the archive and open a terminal in the folder clipsd-<version>.
  2. Run:   bash install.sh
  No administrator rights (sudo) and no internet needed: Python and Qt are inside.
  The program goes to ~/.local/share/clipsd/versions/<version>, starts with the command clipsd
  and when you log in.

Updates
  Once a day ClipSD checks whether there is a new version (can be turned off in settings) and offers to install it;
  to check right away: icon menu, "Check for updates". The update is installed with the "Update" button.
  If the new version does not start within 60 seconds, the previous one comes back automatically.
  By hand: unpack the new archive and run bash install.sh.

Moving from ClipSD 1.29 and older
  Before installing, close the ClipSD editor (save or copy the screenshot): the old version is closed without asking.
  Settings from ~/.config/clipshot are copied to ~/.config/clipsd at the first start (the original stays).
  The old Python environment (~/.local/share/clipsd/venv) is removed, the clipsd.service service and Alt+W stay.

Uninstall
  bash ~/.local/share/clipsd/current/uninstall.sh
  Settings (~/.config/clipsd) and screenshots are removed only with --purge.

Hotkeys in GNOME
  Alt+W works at once (a fallback shortcut). The extension "ClipSD: hotkeys" (Alt+W on any keyboard layout)
  loads after you log out and back in.

Language
  12 languages, by default the system language. To change: tray icon menu "Language · Язык", the globe in the
  editor or Settings, section "Language". Messages of install.sh and uninstall.sh: Russian in a Russian terminal,
  English otherwise.
