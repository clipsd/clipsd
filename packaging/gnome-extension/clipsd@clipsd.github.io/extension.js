// ClipSD: горячие клавиши. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко). SPDX-License-Identifier: GPL-3.0-or-later
// Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
//
// Обычное сочетание GNOME хранит одну клавишу, и Alt+W при русской раскладке не срабатывает, если раскладку
// переключает не GNOME (Alt+Shift через xkb). Два отдельных сочетания на одну клавишу перебивают друг друга.
// Поэтому ClipSD пишет сюда сочетание кодом физической клавиши («<Alt>0x19» = клавиша W), оно не зависит от раскладки.
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const KEYS = [['region-hotkey', '--region'], ['full-hotkey', '--full']];
const SCREENCAST = 1;   // UIMode.SCREENCAST в ui/screenshot.js (GNOME 44+)

// ClipSD вызывает OpenScreencast по кнопке «Запись видео»: открывается встроенная запись экрана GNOME
const IFACE = `<node>
  <interface name="org.gnome.Shell.Extensions.ClipSD">
    <method name="OpenScreencast"/>
    <method name="Grab">
      <arg type="s" direction="in" name="path"/>
      <arg type="b" direction="out" name="ok"/>
    </method>
  </interface>
</node>`;

export default class ClipSDHotkeys extends Extension {
    enable() {
        this._settings = this.getSettings();
        for (const [key, flag] of KEYS) {
            Main.wm.addKeybinding(key, this._settings, Meta.KeyBindingFlags.IGNORE_AUTOREPEAT,
                Shell.ActionMode.NORMAL | Shell.ActionMode.OVERVIEW | Shell.ActionMode.POPUP,
                () => this._run(flag));
        }
        this._dbus = Gio.DBusExportedObject.wrapJSObject(IFACE, this);
        this._dbus.export(Gio.DBus.session, '/org/gnome/Shell/Extensions/ClipSD');
    }

    OpenScreencast() {
        Main.screenshotUI.open(SCREENCAST).catch(e => logError(e, 'ClipSD: запись экрана не открылась'));
    }

    // GNOME 50 больше не пускает org.gnome.Screenshot к org.gnome.Shell.Screenshot, а портал без фокуса
    // не показывает запрос доступа. Снимок всего стола делает само расширение (оно внутри Shell) в PNG-файл.
    GrabAsync([path], invocation) {
        let stream;
        try {
            stream = Gio.File.new_for_path(path).replace(null, false, Gio.FileCreateFlags.NONE, null);
        } catch (e) {
            logError(e, 'ClipSD: файл снимка не создан');
            invocation.return_value(new GLib.Variant('(b)', [false]));
            return;
        }
        new Shell.Screenshot().screenshot(false, stream).then(() => {
            stream.close(null);
            invocation.return_value(new GLib.Variant('(b)', [true]));
        }).catch(e => {
            logError(e, 'ClipSD: снимок не сделан');
            try {
                stream.close(null);
            } catch (e2) {
                // поток уже закрыт
            }
            invocation.return_value(new GLib.Variant('(b)', [false]));
        });
    }

    _run(flag) {
        const cmd = this._settings.get_string('command') || `${GLib.get_home_dir()}/.local/bin/clipsd`;
        try {
            GLib.spawn_async(null, [cmd, flag], null, GLib.SpawnFlags.SEARCH_PATH, null);
        } catch (e) {
            logError(e, 'ClipSD: не удалось запустить снимок');
        }
    }

    disable() {
        this._dbus?.unexport();
        this._dbus = null;
        for (const [key] of KEYS)
            Main.wm.removeKeybinding(key);
        this._settings = null;
    }
}
