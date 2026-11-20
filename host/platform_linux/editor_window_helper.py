"""The editor's own window on Linux: GTK 3 with WebKitGTK, run by editor_window.py under the system Python.

The project's virtual environment has no PyGObject, so this file imports nothing from the host and runs under the
Python that has GTK (like x11_menu_helper.py does for the tray menu).

    --screen   print the work area of the monitor as {"x", "y", "width", "height"} and exit
    (no flag)  read {"url", "width", "height", "x", "y", "min_width", "min_height", "icon"} from stdin, show the window
               until it is closed, then print its last size and place as {"width", "height", "x", "y"}

Exit status 3: GTK or WebKitGTK is missing here (the caller opens a browser tab instead).
"""
import json
import os
import subprocess
import sys
from urllib.parse import urlsplit

NO_GTK = 3
BACKGROUND = '#0A0E10'


def load():
    """GLib, Gdk, Gtk and WebKit2, or None. The program name is set first: on Wayland it is the window's app id, and
    the menu entry tessera-editor.desktop (host/linux/) of the same name gives the window its icon and name in the task bar.
    WebKitGTK's DMA-BUF renderer draws an empty window with some GPU drivers (NVIDIA among them), and the helper cannot tell
    that from a page that works, so the browser fallback would never come. The editor draws fine without it; set
    WEBKIT_DISABLE_DMABUF_RENDERER=0 to have it back."""
    os.environ.setdefault('WEBKIT_DISABLE_DMABUF_RENDERER', '1')
    try:
        import gi
        from gi.repository import GLib
        GLib.set_prgname('tessera-editor')
        GLib.set_application_name('Tessera')
        gi.require_version('Gtk', '3.0')
        gi.require_version('Gdk', '3.0')
        for version in ('4.1', '4.0'):
            try:
                gi.require_version('WebKit2', version)
                break
            except ValueError:
                continue
        from gi.repository import Gdk, Gtk, WebKit2
    except (ImportError, ValueError):
        return None
    if not Gtk.init_check(sys.argv)[0]:
        return None
    return GLib, Gdk, Gtk, WebKit2


def work_area(Gdk):
    display = Gdk.Display.get_default()
    monitor = display.get_primary_monitor() or display.get_monitor(0)
    area = monitor.get_workarea()
    return {'x': area.x, 'y': area.y, 'width': area.width, 'height': area.height}


def open_outside(url):
    """A link to another site opens in the default browser, not in the editor's window."""
    try:
        subprocess.Popen(['xdg-open', url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass


def show(modules, request):
    GLib, Gdk, Gtk, WebKit2 = modules
    origin = urlsplit(request['url'])[:2]
    window = Gtk.Window(title='Tessera')
    window.set_default_size(request['width'], request['height'])
    window.set_size_request(min(request['min_width'], request['width']), min(request['min_height'], request['height']))
    if request.get('x') is not None:
        window.move(request['x'], request['y'])  # Wayland leaves the place to the compositor
    else:
        window.maximize()  # nothing saved yet: fill the work area, as on Windows
    if request.get('icon') and os.path.isfile(request['icon']):
        try:
            window.set_icon_from_file(request['icon'])
        except GLib.Error:
            pass

    context = WebKit2.WebContext.new_ephemeral()  # nothing is kept between starts, like the private WebView2 on Windows
    view = WebKit2.WebView.new_with_context(context)
    settings = view.get_settings()
    settings.set_javascript_can_access_clipboard(True)
    settings.set_enable_developer_extras(False)
    colour = Gdk.RGBA()
    colour.parse(BACKGROUND)
    view.set_background_color(colour)

    def decide(_view, decision, kind):
        if kind not in (WebKit2.PolicyDecisionType.NAVIGATION_ACTION, WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION):
            return False
        uri = decision.get_navigation_action().get_request().get_uri()
        # Export saves a blob the page made: its address is "blob:" and then the editor's own
        own = urlsplit(uri.removeprefix('blob:'))[:2] == origin
        if own and kind == WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
            return False
        if uri.startswith(('http:', 'https:', 'mailto:')):
            open_outside(uri)
        decision.ignore()
        return True

    def download_started(_context, download):
        # Export saves through a download: ask where, as a browser would
        def destination(download, suggested):
            dialog = Gtk.FileChooserNative.new('Save', window, Gtk.FileChooserAction.SAVE, '_Save', '_Cancel')
            dialog.set_current_name(suggested)
            dialog.set_do_overwrite_confirmation(True)
            folder = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD)
            if folder:
                dialog.set_current_folder(folder)
            if dialog.run() == Gtk.ResponseType.ACCEPT:
                download.set_allow_overwrite(True)  # the dialog asked before replacing a file; WebKit refuses by default
                download.set_destination(dialog.get_uri())
            else:
                download.cancel()
            return True
        download.connect('decide-destination', destination)

    view.connect('decide-policy', decide)
    context.connect('download-started', download_started)
    view.load_uri(request['url'])

    geometry = {}

    gone = []  # the page's process ended: nothing is left to ask

    def closing(*_):
        if not window.is_maximized():
            width, height = window.get_size()
            x, y = window.get_position()
            geometry.update(width=width, height=height, x=x, y=y)
        if gone or not view.get_is_web_process_responsive():
            return False  # GTK closes the window
        # the page is asked first: with unsaved changes its beforeunload shows "Leave page?", and Stay keeps the window
        view.try_close()
        return True

    window.connect('delete-event', closing)
    view.connect('close', lambda *_: window.destroy())
    view.connect('web-process-terminated', lambda *_: gone.append(True))
    window.connect('destroy', lambda *_: Gtk.main_quit())
    window.add(view)
    window.show_all()
    Gtk.main()
    return geometry


def main():
    modules = load()
    if modules is None:
        return NO_GTK
    if '--screen' in sys.argv[1:]:
        print(json.dumps(work_area(modules[1])))
        return 0
    print(json.dumps(show(modules, json.loads(sys.stdin.read()))), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
