"""Shows the tray menu with GTK3 and prints which entry was chosen. Run with the SYSTEM Python (the one that has `gi`).

Standalone on purpose: it imports nothing from Tessera, so it works under any interpreter that has PyGObject, and the host's
virtual environment needs no GTK. The menu is a normal GTK menu, so it follows the user's GTK theme and does its own
grabbing, keyboard navigation and closing (Esc, a click elsewhere).

stdin: {"x": 100, "y": 200 (where the icon was clicked, in X11 pixels), "rows": [{"separator": true} |
        {"text", "enabled", "checked" (null|bool), "radio", "default", "submenu": null|rows}, ...]}
stdout: the path of the chosen entry ("3", or "5.1" for the second entry of the sixth item's submenu); nothing when the
        menu was closed without a choice.
exit code 3: GTK is not available here.
"""
import json
import sys

try:
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('Gdk', '3.0')
    from gi.repository import Gdk, GLib, Gtk
except (ImportError, ValueError):
    sys.exit(3)

TIMEOUT_SECONDS = 30  # an unanswered menu closes by itself: POPUP_SECONDS in x11_tray_menu.py, which waits 15 s longer


def build(rows, prefix, on_choose):
    menu = Gtk.Menu()
    radio_group = None
    for index, row in enumerate(rows):
        path = f'{prefix}{index}'
        if row.get('separator'):
            menu.append(Gtk.SeparatorMenuItem())
            continue
        checked = row.get('checked')
        if row.get('submenu') is not None:
            item = Gtk.MenuItem(label=row['text'])
            item.set_submenu(build(row['submenu'], path + '.', on_choose))
        elif checked is None:
            item = Gtk.MenuItem(label=row['text'])
        elif row.get('radio'):
            item = Gtk.RadioMenuItem.new_with_label_from_widget(radio_group, row['text'])
            radio_group = item
            item.set_active(bool(checked))
        else:
            item = Gtk.CheckMenuItem(label=row['text'])
            item.set_active(bool(checked))
        if row.get('default'):
            item.get_child().set_markup('<b>%s</b>' % GLib.markup_escape_text(row['text']))
        item.set_sensitive(bool(row.get('enabled', True)))
        if row.get('submenu') is None:
            item.connect('activate', lambda _item, chosen=path: on_choose(chosen))
        menu.append(item)
    return menu


def to_logical(display, x, y):
    """X11 reports the click in device pixels; GTK places windows in logical pixels (device / scale of the monitor).

    With a scale of 2 on a 4K or 5K screen the two differ by a factor of two, and a menu opened at the device position
    lands past the last monitor, which is then where GTK puts it. The live pointer is the fallback."""
    for index in range(display.get_n_monitors()):
        monitor = display.get_monitor(index)
        area, scale = monitor.get_geometry(), monitor.get_scale_factor()
        if area.x * scale <= x < (area.x + area.width) * scale and area.y * scale <= y < (area.y + area.height) * scale:
            return x // scale, y // scale
    try:
        _screen, px, py = display.get_default_seat().get_pointer().get_position()
        return px, py
    except Exception:
        return x, y


def main():
    request = json.load(sys.stdin)
    x, y = int(request['x']), int(request['y'])
    x, y = to_logical(Gdk.Display.get_default(), x, y)
    chosen = []
    shown = []  # set_active() on a check or radio item emits "activate": entries count only once the menu is up

    def on_choose(path):
        if not shown or chosen:
            return
        chosen.append(path)
        sys.stdout.write(path + '\n')
        sys.stdout.flush()
        GLib.timeout_add(80, Gtk.main_quit)

    menu = build(request['rows'], '', on_choose)
    menu.show_all()
    menu.connect('selection-done', lambda *_: GLib.timeout_add(250, Gtk.main_quit))  # after a chosen entry has run
    GLib.timeout_add_seconds(TIMEOUT_SECONDS, Gtk.main_quit)
    display = Gdk.Display.get_default()
    monitor = display.get_monitor_at_point(x, y)
    area = monitor.get_geometry() if monitor else None
    # open upward when the pointer is in the lower half of its screen (a bottom panel), downward otherwise
    upward = bool(area) and y > area.y + area.height / 2
    rect = Gdk.Rectangle()
    rect.x, rect.y, rect.width, rect.height = x, y, 1, 1
    root = Gdk.get_default_root_window()
    menu.popup_at_rect(root, rect, Gdk.Gravity.NORTH_WEST,
                       Gdk.Gravity.SOUTH_WEST if upward else Gdk.Gravity.NORTH_WEST,
                       None)  # no trigger event: GTK warns on stderr, but a made-up one would close the menu at once
    shown.append(True)
    Gtk.main()


if __name__ == '__main__':
    main()
