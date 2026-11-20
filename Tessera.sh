#!/usr/bin/env bash
# Tessera launcher for Linux (X11, or Wayland on KDE Plasma or GNOME). With no arguments it starts the tray icon, which starts the USB host; the editor
# opens from the tray icon (a click) or with --editor. Starting it again changes nothing.
#   --app          the tray icon and the editor (what the *Tessera Editor* menu entry runs; the editor comes to the front)
#   --editor [options]   only the editor
#   --setup        first-run setup (dependencies and the application menu entries)
#   --uninstall    remove the autostart entry and the menu entries (add --purge to delete your data too)
#   --diagnostics  write a support bundle without button contents
#   --gnome-extension [remove]   install (or remove) the GNOME Shell extension that lets Tessera control windows on Wayland
#   --terminal     the terminal editor        --tray   only the tray icon
#   --check / --no-browser   run in this terminal
# Needs Python 3.12 or newer with venv, and for keys, text and the clipboard xdotool and xclip (X11), or ydotool,
# wl-clipboard and on KDE Plasma kdotool (Wayland; without ydotool keys and typing use the desktop's portal).
set -u
export PYTHONUTF8=1
cd "$(dirname "$(readlink -f "$0")")" || exit 1

if [ "${1:-}" = "--gnome-extension" ]; then  # needs no Python environment
  target="${XDG_DATA_HOME:-$HOME/.local/share}/gnome-shell/extensions/tessera-windows@tessera"
  if [ "${2:-}" = "remove" ]; then
    rm -rf "$target" && echo "Removed $target. Sign in again to unload it."
    exit 0
  fi
  mkdir -p "$(dirname "$target")" && rm -rf "$target" && cp -r host/linux/gnome-extension/tessera-windows@tessera "$target" || exit 1
  echo "Installed $target"
  echo "GNOME loads new extensions at sign-in. Sign out and in again, then run:"
  echo "  gnome-extensions enable tessera-windows@tessera"
  echo "While it is on, any program of your session can read window titles and focus, move or close windows. Turn it off with"
  echo "  gnome-extensions disable tessera-windows@tessera"
  exit 0
fi
PY="host/.venv/bin/python"

fail() {
  echo "Tessera could not start. See the message above." >&2
  exit 1
}

find_python() {
  local candidate
  for candidate in python3 python3.14 python3.13 python3.12 python3.11 python; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>/dev/null; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

create_environment() {
  local python
  python="$(find_python)" || {
    echo "Tessera needs Python 3.12 or newer. Install it with your package manager (python3, and python3-venv on Debian or Ubuntu)." >&2
    return 1
  }
  "$python" -m venv host/.venv || {
    echo "Python could not create host/.venv. On Debian or Ubuntu install python3-venv. Delete host/.venv if it is there, then start Tessera again." >&2
    return 1
  }
}

check_tools() {
  local missing=() tool
  if [ "${TESSERA_SESSION:-${XDG_SESSION_TYPE:-}}" = "wayland" ]; then
    if ! command -v ydotool >/dev/null 2>&1; then
      # without ydotool the host sends keys through the desktop's RemoteDesktop portal (host/platform_linux/portal.py)
      echo "Note: ydotool not found. Keys, typing and the mouse go through the desktop's RemoteDesktop portal instead: the desktop asks once to allow it." >&2
    elif ! ydotool key >/dev/null 2>&1; then
      echo "Note: ydotoold is not running. Start it with: systemctl --user enable --now ydotool" >&2
    fi
    command -v wl-copy >/dev/null 2>&1 || command -v qdbus6 >/dev/null 2>&1 ||
      echo "Note: wl-copy (wl-clipboard) not found. The clipboard needs it on Wayland." >&2
    case ":${XDG_CURRENT_DESKTOP:-}:" in
      *:KDE:*) command -v kdotool >/dev/null 2>&1 ||
                 echo "Note: kdotool not found. Smart profiles and window actions need it on Plasma (AUR: kdotool-bin)." >&2 ;;
      *:GNOME:*) [ -d "${XDG_DATA_HOME:-$HOME/.local/share}/gnome-shell/extensions/tessera-windows@tessera" ] ||
                 echo "Note: window actions and smart profiles on GNOME need the Tessera extension for GNOME Shell: ./Tessera.sh --gnome-extension" >&2 ;;
      *) echo "Note: window actions and smart profiles on Wayland need KDE Plasma or GNOME; keys and typing work." >&2 ;;
    esac
    return
  fi
  for tool in xdotool xclip; do
    command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
  done
  if [ "${#missing[@]}" -gt 0 ]; then
    echo "Note: ${missing[*]} not found. Keys, typing and the clipboard need them (install the packages of the same names)." >&2
  fi
}

background() {  # start a program that outlives this terminal
  setsid nohup "$@" >/dev/null 2>&1 &
}

FIRST_RUN=
if [ ! -x "$PY" ]; then
  echo "Setting up Tessera. The first start takes about a minute."
  echo "1/3 Finding Python ..."
  create_environment || fail
  FIRST_RUN=1
fi

if [ "${1:-}" = "--uninstall" ]; then
  "$PY" host/setup_tool.py uninstall ${2:+"$2"}
  status=$?
  rm -rf "${XDG_DATA_HOME:-$HOME/.local/share}/gnome-shell/extensions/tessera-windows@tessera"  # the GNOME extension, if it was installed
  exit $status
fi

[ -n "$FIRST_RUN" ] && echo "2/3 Installing packages ..."
"$PY" host/setup_tool.py ensure || fail
[ -n "$FIRST_RUN" ] && "$PY" host/setup_tool.py setup >/dev/null
[ -n "$FIRST_RUN" ] && echo "3/3 Starting Tessera. Look for the tray icon and click it to open the editor (or run ./Tessera.sh --editor)."
check_tools

case "${1:-}" in
  "")             background "$PY" host/tessera_tray.py ;;
  --app)
    background "$PY" host/tessera_tray.py
    background "$PY" host/tessera_app.py --editor
    ;;
  --editor)       background "$PY" host/tessera_app.py "$@" ;;
  --setup)        "$PY" host/setup_tool.py setup || fail ;;
  --diagnostics)  "$PY" host/setup_tool.py diagnostics ;;
  --terminal)     "$PY" host/tessera_terminal.py || fail ;;
  --tray)         background "$PY" host/tessera_tray.py ;;
  --sensors|--sensors-off)
    echo "The hardware sensors setup is for Windows. On Linux the readings come from the system." ;;
  --check|--no-browser)  "$PY" host/tessera_app.py "$@" || fail ;;
  *)              background "$PY" host/tessera_app.py "$@" ;;
esac
