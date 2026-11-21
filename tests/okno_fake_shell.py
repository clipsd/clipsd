# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Поддельный GNOME Shell с дополнением ClipSD для tests/vybor_okna_dbus_test.py (не тест сам по себе).

Работает только на частной шине проверки (dbus-run-session теста), шину человека не видит. Запускается системным
python3 с PyGObject. По образцу пробы независимой проверки 1.33 (prov133/probes/okno/fake_shell.py).
FAKE_MODE: new (ListWindows, GrabWindow, Grab) | old (только Grab, как дополнение 1.32) | noobj (имя есть, объекта
нет) | none (имя не занято). FAKE_LIST_MS: задержка ответа ListWindows. FAKE_GRAB_MS: JSON {id: мс, "*": мс}.
FAKE_PNG_DIR: <id>.png и desk.png (снимок стола для Grab). FAKE_WINDOWS: ответ ListWindows. FAKE_LOG: журнал вызовов."""
import json
import os
import time

from gi.repository import Gio, GLib

mode = os.environ.get("FAKE_MODE", "new")
list_ms = int(os.environ.get("FAKE_LIST_MS", "0"))
grab_ms = json.loads(os.environ.get("FAKE_GRAB_MS", "{}"))
pngdir = os.environ.get("FAKE_PNG_DIR", "")
log = open(os.environ.get("FAKE_LOG", os.devnull), "a", buffering=1, encoding="utf-8")
answer = os.environ.get("FAKE_WINDOWS", '{"windows": [], "monitors": []}')


def note(s):
    log.write(f"{time.monotonic():.3f} {s}\n")


OLD = """<method name="OpenScreencast"/>
<method name="Grab"><arg type="s" direction="in" name="path"/><arg type="b" direction="out" name="ok"/></method>"""
NEW = OLD + """
<method name="ListWindows"><arg type="s" direction="out" name="json"/></method>
<method name="GrabWindow"><arg type="s" direction="in" name="id"/><arg type="s" direction="in" name="path"/>
<arg type="b" direction="out" name="ok"/></method>"""
XML = f'<node><interface name="org.gnome.Shell.Extensions.ClipSD">{NEW if mode == "new" else OLD}</interface></node>'


def write(path, name):
    src = os.path.join(pngdir, name + ".png")
    if not os.path.exists(src):
        return False
    with open(src, "rb") as f_in, open(path, "wb") as f_out:
        f_out.write(f_in.read())
    return True


def on_call(_conn, _sender, _path, _iface, method, params, inv):
    args = params.unpack()
    note(f"call {method}")
    if method == "ListWindows":
        def reply():
            inv.return_value(GLib.Variant("(s)", (answer,)))
            note("reply ListWindows")
            return False
        GLib.timeout_add(list_ms, reply) if list_ms else reply()
    elif method == "GrabWindow":
        wid, out = args
        delay = grab_ms.get(wid, grab_ms.get("*", 0))

        def reply():
            ok = write(out, wid)
            inv.return_value(GLib.Variant("(b)", (ok,)))
            note(f"reply GrabWindow {wid} ok={ok}")
            return False
        GLib.timeout_add(delay, reply) if delay else reply()
    elif method == "Grab":
        (out,) = args
        note(f"grab-path {out}")   # тест проверяет, в какую папку ClipSD просит записать снимок стола
        inv.return_value(GLib.Variant("(b)", (write(out, "desk"),)))
    else:
        inv.return_value(None)


def on_bus(conn, _name):
    if mode != "noobj":
        info = Gio.DBusNodeInfo.new_for_xml(XML)
        conn.register_object("/org/gnome/Shell/Extensions/ClipSD", info.interfaces[0], on_call, None, None)


def on_name(_conn, _name):
    print("READY", flush=True)


if mode == "none":
    print("READY", flush=True)
else:
    Gio.bus_own_name(Gio.BusType.SESSION, "org.gnome.Shell", Gio.BusNameOwnerFlags.NONE, on_bus, on_name, None)
GLib.MainLoop().run()
