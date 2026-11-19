ClipSD 1.31.0: screenshots with an editor
Copyright (C) 2026 Sergey Dayneko. Licence: GNU GPL v3 or later, official text in the file LICENSE
  (a plain-language Russian summary is in LICENSE.ru.txt). По-русски: README.md.

What it does
  Alt+W: the screen freezes, you select an area with the mouse, and the editor opens with the screenshot in the
  same place. Alt+W can be replaced with any shortcut: gear in the editor window (or Ctrl+,), section
  "Keyboard shortcuts". The default shortcut works on every keyboard layout (for example Alt+W and Alt+Ц);
  on Linux with GNOME the extension "ClipSD: hotkeys" does this, it starts after you log out and back in.
  Zoom in the editor: Ctrl+mouse wheel, the "−" and "+" buttons at the bottom, Ctrl+plus, Ctrl+minus, Ctrl+0 (100%),
  "Fit" (Ctrl+9). A screenshot larger than the window (for example two monitors) opens whole at once. Zoom is only
  for viewing: you can draw at any zoom, the final screenshot keeps its full size.
  Moving objects: hold the right mouse button on any drawn object (arrow, shape, number, text, callout) and drag,
  with any tool; a right click without moving opens the action menu. A single click on a text or a callout opens
  it for editing, dragging moves it.
  Crop in two steps: select an area with the "Crop" tool, adjust the frame (drag the corners and sides, drag inside
  to move it) and confirm with "Crop (Enter)", Enter or a double click inside the frame. Esc or "Cancel": undo.
  Copy text: the purple button when taking a screenshot (Ctrl+T) and "Copy text" in the editor (key I). The
  screenshot is recognised, the words found are lightly highlighted. Two ways, switch "Range / Marker" at the bottom.
  "Range" (as on a phone): press on a word and drag in any direction, all the text in between is selected.
  "Marker": go over the words you need, only what you went over is taken; Ctrl + stroke: add another piece.
  The selection goes straight to the clipboard ("Text copied to the clipboard") and into a window where you can
  correct it. Several columns are read in order, as on a phone: one column top to bottom, then the next; a title
  across the whole width first. Double click: one word, Ctrl+A: all the text. The modes "Copy text", "Crop" and
  "Translation" show a bar at the top of the editor; to leave and go on drawing: "Done (Esc)" on the right of the
  bar, Esc or any tool on the toolbar, the previous tool comes back. No recognition program installed: the window
  shows the install command and a link to instructions, each with a "Copy" button. In settings: on or off,
  "More accurate" or "Faster", languages. Linux: the tesseract program. Windows: the built-in Windows 10/11 recognition.
  Translate: two actions. When taking a screenshot, two teal buttons: "Translate selection" (Ctrl+L: if an area is
  already selected, it is translated; otherwise select a piece with the mouse) and "Translate whole screen"
  (Ctrl+Shift+L: the whole monitor with the frame or the pointer). Translation goes piece by piece: the mode stays on,
  outline the next piece and it is translated too; Esc ends the mode. In the editor a split button: "Translate all"
  (Shift+Y, the whole screenshot) and "Selection" (Y, select a piece with the mouse); the same items are in the
  right-click menu. If there is more text on the screen than free characters left and Google is not connected,
  ClipSD asks: "Translate as much as fits" or "Cancel". Esc cancels a long wait for a translation. The translation
  opens in a small window over the text, and the screen stays live (the browser scrolls). Drag the small window
  away from the original; it has "Copy", "Original", "More" (translate the next piece) and a cross at the top right.
  In the editor the translation lies over the screenshot and does not go into the saved file. Services: MyMemory
  (no registration, 5,000 characters a day; enter an email address with the "50,000 a day…" button on the mode
  bar or in settings and the limit becomes 50,000 a day, no confirmation needed) and Google Cloud (500,000
  characters free every month, a key is needed: the "Connect Google…" window with steps and a field for the key).
  When one runs out, the other is used. When the free limit without an email runs out, the window "Today's free
  translation has run out" opens in the middle of the screen with a field "Your email" and "Save and translate".
  The target language is the program's language by default; another one: the "To: … ▾" button on the mode bar,
  "→ … ▾" on the small window (it is translated again at once) or settings. The text is sent to the service over
  the internet.
  Until recognition and translation are needed they are not loaded and do nothing in the background: they start
  only on a button. While recognition or translation runs, dots go round in the middle.
  Tools: arrow, double arrow, free arrow, smooth line, line, rectangle, ellipse, free closed shape, marker, pencil,
  text, callout with a pointer, numbers 1, 2, 3 with a pointer, blur, eraser (whole object or part of it), crop,
  inserting a picture over the screenshot (Ctrl+V, from a file, as a new screenshot).
  "Copy" (Ctrl+C or Enter): the screenshot to the clipboard, the window stays open.
  "Copy and close" (Ctrl+Enter). "Save" (Ctrl+S): to a PNG or JPEG file.
  With the next Alt+W the previous area is highlighted: Enter or a click inside takes it again; the frame can be
  moved and resized by its corners and sides. Under the frame, a panel in two rows.
  Top: "Record video" (Ctrl+R: the system's own screen recording; GNOME: the screenshot window in video mode,
  Windows 11: Snipping Tool, Win+Shift+R), "Full-screen screenshot" (Ctrl+A), "Copy text" (Ctrl+T),
  "Translate selection" (Ctrl+L), "Translate whole screen" (Ctrl+Shift+L).
  Bottom: "Save" (Ctrl+S, to a file), "Edit" (Enter or a click inside the frame), "Select again" (Delete: the old
  frame goes away and you select the area again, or just draw on an empty place), the green "Copy and close"
  (Ctrl+C, to the clipboard).
  "Full-screen screenshot" and a simple click without dragging: the screen dims, a thick frame runs along the
  edge, "Full-screen screenshot" in the middle and the same buttons. The screenshot is taken only on a button,
  you can still select a normal area with the mouse. With two or more monitors a row "All monitors",
  "Monitor 1", "Monitor 2" with sizes stands above the buttons: the choice highlights the frame; keys 0 (all) and
  1..9 (monitor number). Close without a screenshot: the cross at the corner of the panel, the cross inside the
  area near its top right corner (it moves with the area) or Esc.
  Every screenshot is saved at once to the folder "Downloads/Screenshots", and the file is updated after changes
  in the editor. "Save" asks where to save (the window opens in "Downloads"). Both folders and the automatic saving
  are changed in settings, section "Saving".

Install on Linux (Ubuntu, Debian, Fedora, Mint and others; GNOME, KDE, X11 or Wayland)
  1. Unpack ClipSD-<version>-linux-x86_64.tar.gz.
  2. Open a terminal in the folder clipsd-<version> and run:   bash install.sh
  No administrator rights and no internet needed: Python and Qt are inside.
  Uninstall: bash ~/.local/share/clipsd/current/uninstall.sh (settings and screenshots stay; --purge removes them)

Install on Windows 10/11
  Run ClipSD-<version>-Setup.exe. No administrator rights and no internet needed.
  Reinstalls and updates go over the existing installation, settings and ticks are kept.
  If Windows shows "Windows protected your PC": "More info" -> "Run anyway" (the program has no digital
  signature yet).
  The ClipSD icon appears in the tray near the clock, and the program starts with Windows.
  If Alt+W does not work: close Clip2net, it takes the same shortcut.
  Uninstall: Start -> "Uninstall ClipSD", or Settings -> Apps.

Language
  12 languages: Russian, English, Bulgarian, Ukrainian, German, French, Spanish, Italian, Portuguese, Polish,
  Turkish, Chinese. To choose: the tray icon menu "Language · Язык", the globe in the editor window, the first step
  of the tour, or Settings, section "Language". The language changes at once, no restart.
  By default the system language; on Windows a new installation starts in the language of the installer.

Updates
  Once a day ClipSD checks clipsd.github.io for a new version and offers to install it ("Update", "Later",
  "Skip this version"). To check right away: tray icon menu, "Check for updates". To turn the automatic check off:
  Settings, section "Startup".
  Updates are verified with a digital signature and a checksum; if the new version does not start, the previous
  one comes back by itself. While the editor holds unsaved marks, the update waits.
  Settings of earlier versions (1.29 and older) are copied at the first start, the original stays.
  Moving from 1.29 and older is done once by hand. Before installing, close the ClipSD editor (save or copy the
  screenshot): the old version is closed without asking.

Settings (gear in the editor window, Ctrl+, or a right click on the tray icon)
  Keyboard shortcuts (area screenshot, full-screen screenshot), magnifier and size label while selecting,
  highlighting of the previous area, what a click on the icon does, screenshot folder and format (PNG or JPEG),
  saving with Ctrl+S without a file dialog, window frame colours and thickness, language, autostart,
  automatic update check.

At the first start you can choose the look: standard light or professional dark (as in video editing programs),
later in Settings, section "Appearance".
The program tour is shown at the first start; to repeat it: the "?" button in the editor window (F1),
  Settings or the tray icon menu.

Right click on an object in the screenshot: menu (colour, thickness, fill, duplicate, order, delete).
When an object is selected, the colour and thickness buttons change only that object; the choice for new objects
stays as it was.

The tool buttons can be reordered by dragging; a right click on the tool row restores the standard order.

Keys in the editor
  V select, K callout, T text, N number, A arrow, D double arrow, F free arrow,
  G smooth line, L line, R rectangle, E ellipse, O free shape, M marker, P pencil,
  B blur, X eraser, C crop, 1-5 thickness. Ctrl+D: duplicate, Ctrl+V: insert a picture.
  Shift: straight (45°, square, circle). Ctrl: filled shape; Ctrl+drag: copy.
  Delete: delete the selection. Ctrl+Z / Ctrl+Y: undo / redo. Esc: close.

Download: https://clipsd.github.io/ (Windows: ClipSD-<version>-Setup.exe, Linux: ClipSD-<version>-linux-x86_64.tar.gz).

For developers
  Run from the sources: python3 -m clipshot (needs PyQt6, python-xlib, cryptography; see requirements.txt).
  Builds: packaging/linux/build_linux.sh and packaging/windows-exe/build.ps1 (exact package versions with hashes
  in packaging/requirements-build-*.txt), cloud builds in .github/workflows. Release: tools/release.sh.
  Tests: each tests/*_test.py in its own process, QT_QPA_PLATFORM=offscreen.
