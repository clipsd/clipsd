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
const WINDOW_TYPES = [Meta.WindowType.NORMAL, Meta.WindowType.DIALOG, Meta.WindowType.MODAL_DIALOG];

// Окно, которое ClipSD показывает в списке и может снять: обычное окно текущего рабочего стола (как Alt+Tab).
function listable(w, ws) {
    return !w.is_override_redirect() && !w.skip_taskbar && WINDOW_TYPES.includes(w.get_window_type()) &&
        w.located_on_workspace(ws);
}

// ClipSD вызывает OpenScreencast по кнопке «Запись видео»: открывается встроенная запись экрана GNOME
const IFACE = `<node>
  <interface name="org.gnome.Shell.Extensions.ClipSD">
    <method name="OpenScreencast"/>
    <method name="Grab">
      <arg type="s" direction="in" name="path"/>
      <arg type="b" direction="out" name="ok"/>
    </method>
    <method name="ListWindows">
      <arg type="s" direction="out" name="json"/>
    </method>
    <method name="GrabWindow">
      <arg type="s" direction="in" name="id"/>
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
    // Файл только новый (create: O_CREAT|O_EXCL, права 0600): существующий файл не перезаписывается, по ссылке
    // метод не идёт (O_EXCL на ссылке даёт «файл есть»), как и у GrabWindow (проверка 1.33).
    GrabAsync([path], invocation) {
        let stream;
        try {
            stream = Gio.File.new_for_path(path).create(Gio.FileCreateFlags.PRIVATE, null);
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

    // «Снимок окна» (1.33): окна текущего рабочего стола снизу вверх по наложению, видимая рамка без тени
    // (get_frame_rect), монитор, свёрнуто ли. Названия окон уходят только в ClipSD по запросу, дополнение их нигде
    // не хранит. Под Wayland этот список есть только у самого Shell.
    ListWindows() {
        const ws = global.workspace_manager.get_active_workspace();
        const focus = global.display.get_focus_window();
        const tracker = Shell.WindowTracker.get_default();
        const all = global.get_window_actors().map(a => a.meta_window);
        const windows = global.display.sort_windows_by_stacking(all)
            .filter(w => listable(w, ws))
            .map((w, z) => {
                const r = w.get_frame_rect();
                const app = tracker.get_window_app(w);
                return {
                    id: String(w.get_id()), title: w.get_title() ?? '', app: app?.get_name() ?? (w.get_wm_class() ?? ''),
                    icon: app?.get_icon()?.to_string() ?? '', pid: w.get_pid(),
                    x: r.x, y: r.y, w: r.width, h: r.height, monitor: w.get_monitor(),
                    minimized: w.minimized, focused: w === focus, z,
                };
            });
        const monitors = Main.layoutManager.monitors.map(m => ({index: m.index, x: m.x, y: m.y, w: m.width, h: m.height}));
        return JSON.stringify({windows, monitors});
    }

    // Содержимое одного окна в PNG, даже если окно закрыто другими: окно рисуется отдельно (paint_to_content),
    // как это делает окно снимков самого GNOME (ui/screenshot.js). Обрезается по видимой рамке, без тени.
    // Отдаётся только окно, которое сейчас вернул бы ListWindows: текущий рабочий стол, обычное окно, не свёрнутое
    // (проверка 1.33, В4: раньше по номеру отдавалось и окно с другого рабочего стола). Свёрнутое не отдаётся: его
    // актёр скрыт, вместо окна получается чёрный прямоугольник (tools/okno_vlozhennaya_proverka.sh).
    // Файл только новый (create, права 0600): существующий файл и ссылку на чужой файл метод не перезаписывает.
    GrabWindowAsync([id, path], invocation) {
        const done = ok => invocation.return_value(new GLib.Variant('(b)', [ok]));
        const ws = global.workspace_manager.get_active_workspace();
        const actor = global.get_window_actors().find(a => String(a.meta_window.get_id()) === id);
        const w = actor?.meta_window;
        if (!w || w.minimized || !listable(w, ws)) {
            done(false);
            return;
        }
        const texture = actor.paint_to_content(null)?.get_texture();
        if (!texture) {
            done(false);
            return;
        }
        const frame = w.get_frame_rect(), buffer = w.get_buffer_rect();
        const k = actor.get_resource_scale();
        let stream;
        try {
            stream = Gio.File.new_for_path(path).create(Gio.FileCreateFlags.PRIVATE, null);
        } catch (e) {
            logError(e, 'ClipSD: файл снимка окна не создан');
            done(false);
            return;
        }
        Shell.Screenshot.composite_to_stream(texture,
            Math.round((frame.x - buffer.x) * k), Math.round((frame.y - buffer.y) * k),
            Math.round(frame.width * k), Math.round(frame.height * k), k,
            null, 0, 0, 1, stream).then(() => {
            stream.close(null);
            done(true);
        }).catch(e => {
            logError(e, 'ClipSD: снимок окна не сделан');
            try {
                stream.close(null);
            } catch (e2) {
                // поток уже закрыт
            }
            done(false);
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
