#!/bin/bash
# Проверка дополнения ClipSD («Снимок окна»: ListWindows, GrabWindow) в отдельной безэкранной сессии GNOME Shell.
# Сессия человека не трогается: своя шина D-Bus (dbus-run-session), свои HOME, XDG_*, dconf и папка дополнений,
# без X11 и без экрана (--headless), root не нужен. Ничего не ставится в систему и в сеанс пользователя.
#
#   bash tools/okno_vlozhennaya_proverka.sh [папка-для-проверки]
#   OKNO_EXT_SRC=<папка дополнения> или none: проверить старое дополнение (без ListWindows) или его отсутствие
#
# Что делает: ставит в свою папку дополнение ClipSD из packaging/ и маленькое проверочное дополнение (двигает и
# сворачивает окна по названию), запускает gnome-shell --headless, открывает три окна GTK 4 сплошного цвета
# (красное под синим, зелёное свёрнуто), вызывает ListWindows, GrabWindow и Grab, затем тот же путь из Python
# (windows.WindowLister, windows.WindowGrab) и пишет итог. В конце всё, что запустил, останавливает.
set -u
HERE="$(cd "$(dirname "$0")/.." && pwd)"
T="${1:-$HOME/.cache/clipsd-work/okno/nested/$(date +%H%M%S)}"
PY="${PY:-$HOME/.cache/clipsd-work/r130/venv/bin/python}"
mkdir -p "$T/home" "$T/cfg" "$T/cache" "$T/data/gnome-shell/extensions" "$T/run" "$T/out"
chmod 700 "$T/run"
EXT="$T/data/gnome-shell/extensions"
SRC="${OKNO_EXT_SRC:-$HERE/packaging/gnome-extension/clipsd@clipsd.github.io}"
if [ "$SRC" != none ]; then
  cp -r "$SRC" "$EXT/clipsd@clipsd.github.io"
  glib-compile-schemas "$EXT/clipsd@clipsd.github.io/schemas"
fi
mkdir -p "$EXT/okno-test@local"
cat > "$EXT/okno-test@local/metadata.json" <<'J'
{"uuid": "okno-test@local", "name": "okno test", "description": "test helper", "shell-version": ["45", "46", "47", "48", "49", "50"]}
J
cat > "$EXT/okno-test@local/extension.js" <<'J'
import Gio from 'gi://Gio';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
const IFACE = `<node><interface name="local.OknoTest">
  <method name="Place"><arg type="s" direction="in" name="title"/><arg type="i" direction="in" name="x"/>
    <arg type="i" direction="in" name="y"/><arg type="i" direction="in" name="w"/><arg type="i" direction="in" name="h"/>
    <arg type="b" direction="out" name="ok"/></method>
  <method name="Minimize"><arg type="s" direction="in" name="title"/><arg type="b" direction="out" name="ok"/></method>
  <method name="Close"><arg type="s" direction="in" name="title"/><arg type="b" direction="out" name="ok"/></method>
  <method name="HideOverview"/>
  <method name="ToWorkspace"><arg type="s" direction="in" name="title"/><arg type="i" direction="in" name="idx"/>
    <arg type="b" direction="out" name="ok"/></method>
</interface></node>`;
export default class OknoTest extends Extension {
    enable() {
        this._dbus = Gio.DBusExportedObject.wrapJSObject(IFACE, this);
        this._dbus.export(Gio.DBus.session, '/local/OknoTest');
    }
    disable() {
        this._dbus?.unexport();
        this._dbus = null;
    }
    _find(title) {
        return global.get_window_actors().map(a => a.meta_window).find(w => w.get_title() === title);
    }
    Place(title, x, y, w, h) {
        const win = this._find(title);
        if (!win)
            return false;
        win.move_resize_frame(true, x, y, w, h);
        win.raise();
        win.activate(global.get_current_time());
        return true;
    }
    Minimize(title) {
        const win = this._find(title);
        if (!win)
            return false;
        win.minimize();
        return true;
    }
    ToWorkspace(title, idx) {
        const win = this._find(title);
        if (!win)
            return false;
        const wm = global.workspace_manager;
        while (wm.get_n_workspaces() <= idx)
            wm.append_new_workspace(false, global.get_current_time());
        win.change_workspace_by_index(idx, false);
        return true;
    }
    HideOverview() {
        Main.overview.hide();   // GNOME начинает с обзора: для снимка стола нужен обычный вид
    }
    Close(title) {
        const win = this._find(title);
        if (!win)
            return false;
        win.delete(global.get_current_time());
        return true;
    }
}
J
cat > "$T/okno_app.py" <<'J'
import sys
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk
color, title = sys.argv[1], sys.argv[2]
app = Gtk.Application(application_id="local.okno." + title.replace("-", ""))
def activate(a):
    prov = Gtk.CssProvider()
    prov.load_from_string(".okno { background: %s; }" % color)
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov, 800)
    w = Gtk.ApplicationWindow(application=a, title=title)
    box = Gtk.Box()
    box.add_css_class("okno")
    w.set_child(box)
    w.set_default_size(500, 350)
    w.present()
app.connect("activate", activate)
app.run([])
J
cat > "$T/session.sh" <<J
#!/bin/bash
set -u
cd "$T"
gsettings set org.gnome.shell disable-user-extensions false
gsettings set org.gnome.shell enabled-extensions "['clipsd@clipsd.github.io', 'okno-test@local']"
gsettings set org.gnome.shell welcome-dialog-last-shown-version '999'
gsettings set org.gnome.desktop.interface enable-animations false
gnome-shell --headless --wayland --no-x11 --virtual-monitor 1600x1000 --wayland-display=wayland-okno > "$T/out/shell.log" 2>&1 &
SHELL_PID=\$!
for i in \$(seq 1 60); do
  gdbus introspect --session --dest org.gnome.Shell --object-path /local/OknoTest 2>/dev/null | grep -q Place && break
  sleep 0.5
done
export WAYLAND_DISPLAY=wayland-okno GDK_BACKEND=wayland
/usr/bin/python3 -I "$T/okno_app.py" '#e01b24' okno-red > /dev/null 2>&1 &
A1=\$!
sleep 1.5
/usr/bin/python3 -I "$T/okno_app.py" '#1c71d8' okno-blue > /dev/null 2>&1 &
A2=\$!
sleep 1.5
/usr/bin/python3 -I "$T/okno_app.py" '#2ec27e' okno-green > /dev/null 2>&1 &
A3=\$!
sleep 2.5
call() { gdbus call --session --dest org.gnome.Shell --object-path "\$1" --method "\$2" "\${@:3}"; }
call /local/OknoTest local.OknoTest.HideOverview > /dev/null
sleep 1
call /local/OknoTest local.OknoTest.Place okno-green 900 80 400 300
call /local/OknoTest local.OknoTest.Place okno-red 100 100 600 400
call /local/OknoTest local.OknoTest.Place okno-blue 400 250 600 400
call /local/OknoTest local.OknoTest.Minimize okno-green
sleep 1
call /org/gnome/Shell/Extensions/ClipSD org.gnome.Shell.Extensions.ClipSD.ListWindows > "$T/out/list.txt" 2>&1
call /org/gnome/Shell/Extensions/ClipSD org.gnome.Shell.Extensions.ClipSD.Grab "$T/out/stol.png" > "$T/out/grab.txt" 2>&1
/usr/bin/python3 -I - "$T" <<'PYX'
import ast, json, subprocess, sys, time
T = sys.argv[1]
raw = open(f"{T}/out/list.txt").read().strip()
data = json.loads(ast.literal_eval(raw)[0])
ids = {w["title"]: w["id"] for w in data["windows"]}
res = {"windows": [{k: w[k] for k in ("title", "x", "y", "w", "h", "minimized", "z", "monitor")} for w in data["windows"]],
       "monitors": data["monitors"]}
def grab(title, path):
    t = time.perf_counter()
    out = subprocess.run(["gdbus", "call", "--session", "--dest", "org.gnome.Shell", "--object-path",
                          "/org/gnome/Shell/Extensions/ClipSD", "--method", "org.gnome.Shell.Extensions.ClipSD.GrabWindow",
                          ids.get(title, "999999"), path], capture_output=True, text=True)
    return out.stdout.strip() or out.stderr.strip(), round((time.perf_counter() - t) * 1000)
for title in ("okno-red", "okno-green", "okno-blue", "net-takogo"):
    res[title] = grab(title, f"{T}/out/{title}.png")
json.dump(res, open(f"{T}/out/gnome.json", "w"), ensure_ascii=False, indent=1)
PYX
# тот же путь из Python ClipSD (асинхронный список и содержимое окна через QtDBus)
env XDG_CURRENT_DESKTOP=GNOME XDG_SESSION_TYPE=wayland QT_QPA_PLATFORM=offscreen:configfile=$T/screen.json \
  "$PY" -B "$HERE/tools/okno_vlozhennaya_proverka.py" "$T" > "$T/out/python.txt" 2>&1
# проверка 1.33 (В4): окно с другого рабочего стола не отдаётся; существующий файл и ссылка не перезаписываются
BLUE_ID=\$(/usr/bin/python3 -I -c "import ast,json; d=json.loads(ast.literal_eval(open('$T/out/list.txt').read().strip())[0]); print(next(w['id'] for w in d['windows'] if w['title']=='okno-blue'))")
RED_ID=\$(/usr/bin/python3 -I -c "import ast,json; d=json.loads(ast.literal_eval(open('$T/out/list.txt').read().strip())[0]); print(next(w['id'] for w in d['windows'] if w['title']=='okno-red'))")
echo VICTIM > "$T/out/victim.txt"; ln -sf "$T/out/victim.txt" "$T/out/link.png"
call /org/gnome/Shell/Extensions/ClipSD org.gnome.Shell.Extensions.ClipSD.GrabWindow "\$RED_ID" "$T/out/link.png" > "$T/out/grab-link.txt" 2>&1
echo OLD > "$T/out/exists.png"
call /org/gnome/Shell/Extensions/ClipSD org.gnome.Shell.Extensions.ClipSD.GrabWindow "\$RED_ID" "$T/out/exists.png" > "$T/out/grab-exists.txt" 2>&1
call /org/gnome/Shell/Extensions/ClipSD org.gnome.Shell.Extensions.ClipSD.GrabWindow "\$RED_ID" "$T/out/red-new.png" > "$T/out/grab-new.txt" 2>&1
stat -c '%a' "$T/out/red-new.png" > "$T/out/red-new-mode.txt" 2>&1
echo VICTIM3 > "$T/out/victim3.txt"; ln -sf "$T/out/victim3.txt" "$T/out/link3.png"
call /org/gnome/Shell/Extensions/ClipSD org.gnome.Shell.Extensions.ClipSD.Grab "$T/out/link3.png" > "$T/out/grab3-link.txt" 2>&1
echo OLD > "$T/out/exists3.png"
call /org/gnome/Shell/Extensions/ClipSD org.gnome.Shell.Extensions.ClipSD.Grab "$T/out/exists3.png" > "$T/out/grab3-exists.txt" 2>&1
call /org/gnome/Shell/Extensions/ClipSD org.gnome.Shell.Extensions.ClipSD.Grab "$T/out/stol-new.png" > "$T/out/grab3-new.txt" 2>&1
stat -c '%a' "$T/out/stol-new.png" > "$T/out/stol-new-mode.txt" 2>&1
call /local/OknoTest local.OknoTest.ToWorkspace okno-blue 1 > /dev/null 2>&1
sleep 1
call /org/gnome/Shell/Extensions/ClipSD org.gnome.Shell.Extensions.ClipSD.ListWindows > "$T/out/list-ws.txt" 2>&1
call /org/gnome/Shell/Extensions/ClipSD org.gnome.Shell.Extensions.ClipSD.GrabWindow "\$BLUE_ID" "$T/out/blue-other-ws.png" > "$T/out/grab-other-ws.txt" 2>&1
/usr/bin/python3 -I - "$T" > "$T/out/v4.txt" 2>&1 <<'PYV'
import ast, json, os, sys
T = sys.argv[1]
def r(n): return open(f"{T}/out/{n}").read().strip()
ws = [w["title"] for w in json.loads(ast.literal_eval(r("list-ws.txt"))[0])["windows"]]
print("В4: список после переноса синего на другой стол:", ws)
print("В4: GrabWindow синего с другого стола:", r("grab-other-ws.txt"), "файл есть:", os.path.exists(f"{T}/out/blue-other-ws.png"))
print("ссылка на чужой файл:", r("grab-link.txt"), "чужой файл цел:", r("victim.txt") == "VICTIM")
print("существующий файл:", r("grab-exists.txt"), "не перезаписан:", r("exists.png") == "OLD")
print("новый файл:", r("grab-new.txt"), "права:", r("red-new-mode.txt"))
print("Grab (снимок стола): ссылка:", r("grab3-link.txt"), "чужой файл цел:", r("victim3.txt") == "VICTIM3",
      "| существующий:", r("grab3-exists.txt"), "не перезаписан:", r("exists3.png") == "OLD",
      "| новый:", r("grab3-new.txt"), "права:", r("stol-new-mode.txt"))
PYV
call /local/OknoTest local.OknoTest.Close okno-red > /dev/null 2>&1
sleep 1
call /org/gnome/Shell/Extensions/ClipSD org.gnome.Shell.Extensions.ClipSD.ListWindows > "$T/out/list-after-close.txt" 2>&1
kill \$A1 \$A2 \$A3 2>/dev/null
kill \$SHELL_PID 2>/dev/null
wait \$SHELL_PID 2>/dev/null
J
chmod +x "$T/session.sh"
printf '{"screens": [{"name": "virt", "x": 0, "y": 0, "width": 1600, "height": 1000, "logicalDpi": 96, "logicalBaseDpi": 96}]}\n' > "$T/screen.json"
env -i PATH=/usr/bin:/bin HOME="$T/home" XDG_CONFIG_HOME="$T/cfg" XDG_CACHE_HOME="$T/cache" XDG_DATA_HOME="$T/data" \
    XDG_RUNTIME_DIR="$T/run" LANG=C.UTF-8 \
    timeout 180 dbus-run-session -- "$T/session.sh"
/usr/bin/python3 -I - "$T" <<'PYX' > "$T/out/stol.txt" 2>&1
import sys
from PIL import Image
T = sys.argv[1]
st, red = Image.open(f"{T}/out/stol.png"), Image.open(f"{T}/out/okno-red.png")
# точка перекрытия (550, 400): на столе сверху синее окно, в содержимом красного (100, 100) там красное
print("стол, точка перекрытия:", st.getpixel((550, 400))[:3], " содержимое красного там же:", red.getpixel((450, 300))[:3])
PYX
echo "== итог: $T/out"
cat "$T/out/v4.txt" 2>/dev/null
cat "$T/out/stol.txt" 2>/dev/null
cat "$T/out/gnome.json" 2>/dev/null
echo
cat "$T/out/python.txt" 2>/dev/null
