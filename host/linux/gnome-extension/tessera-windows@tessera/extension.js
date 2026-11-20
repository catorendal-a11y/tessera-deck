// SPDX-License-Identifier: GPL-3.0-or-later
//
// Tessera windows: the window functions the Tessera host needs on GNOME under Wayland. GNOME shows a program no other
// windows (Introspect is closed to it, and Shell.Eval is off), so the Shell itself answers on the session bus.
//
// Everything in the user's session can call org.tessera.Windows while this extension is enabled: it can read the
// titles of windows and focus, move or close them. That is what the host does for its keys; turn the extension off
// when you do not want it.
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const NAME = 'org.tessera.Windows';
const PATH = '/org/tessera/Windows';
const VERSION = 1;
const INTERFACE = `<node>
  <interface name="${NAME}">
    <method name="Active">
      <arg type="s" direction="out" name="window"/>
    </method>
    <method name="Find">
      <arg type="ai" direction="in" name="pids"/>
      <arg type="s" direction="out" name="window"/>
    </method>
    <method name="Operate">
      <arg type="s" direction="in" name="window"/>
      <arg type="s" direction="in" name="op"/>
      <arg type="b" direction="out" name="done"/>
    </method>
    <property name="Version" type="u" access="read"/>
  </interface>
</node>`;

const KINDS = [Meta.WindowType.NORMAL, Meta.WindowType.DIALOG, Meta.WindowType.MODAL_DIALOG];

function isAppWindow(window) {
    return KINDS.includes(window.get_window_type()) && !window.is_skip_taskbar();
}

function describe(window) {
    return JSON.stringify({
        id: String(window.get_stable_sequence()),
        pid: window.get_pid(),
        title: window.get_title() ?? '',
        class: window.get_wm_class() ?? '',
    });
}

function byId(id) {
    return global.display.list_all_windows().find(w => String(w.get_stable_sequence()) === id) ?? null;
}

class Service {
    get Version() {
        return VERSION;
    }

    // The window that has the focus, as JSON; '' when none has it.
    Active() {
        const window = global.display.focus_window;
        return window && isAppWindow(window) ? describe(window) : '';
    }

    // The id of the first window (minimised ones too) of one of the processes; '' when there is none.
    Find(pids) {
        const wanted = new Set(pids);
        const found = global.display.list_all_windows()
            .filter(w => isAppWindow(w) && wanted.has(w.get_pid()) && (w.get_title() ?? '') !== '');
        return found.length ? String(found[0].get_stable_sequence()) : '';
    }

    // window: an id from Find or Active, '' for the window that has the focus.
    Operate(id, op) {
        const window = id ? byId(id) : global.display.focus_window;
        if (!window)
            return false;
        const now = global.get_current_time();
        switch (op) {
        case 'focus':
            if (window.minimized)
                window.unminimize();
            window.activate(now);
            return true;
        case 'minimize':
            window.minimize();
            return true;
        case 'maximize':
            window.maximize();
            return true;
        case 'restore':
            window.unminimize();
            window.unmaximize();
            window.activate(now);
            return true;
        case 'close':
            window.delete(now);
            return true;
        case 'topmost':
            if (window.is_above())
                window.unmake_above();
            else
                window.make_above();
            return true;
        case 'next_monitor': {
            const monitors = global.display.get_n_monitors();
            if (monitors > 1)
                window.move_to_monitor((window.get_monitor() + 1) % monitors);
            return true;
        }
        default:
            throw new GLib.Error(Gio.DBusError, Gio.DBusError.INVALID_ARGS, `Unknown window operation: ${op}`);
        }
    }
}

export default class TesseraWindows extends Extension {
    enable() {
        this._export = Gio.DBusExportedObject.wrapJSObject(INTERFACE, new Service());
        this._export.export(Gio.DBus.session, PATH);
        this._owner = Gio.bus_own_name_on_connection(Gio.DBus.session, NAME, Gio.BusNameOwnerFlags.NONE, null, null);
    }

    disable() {
        if (this._owner) {
            Gio.bus_unown_name(this._owner);
            this._owner = 0;
        }
        this._export?.unexport();
        this._export = null;
    }
}
