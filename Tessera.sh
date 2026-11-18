#!/usr/bin/env bash
# Tessera launcher for Linux (X11). With no arguments it starts everything: the tray icon, the USB host
# and the editor. Starting it again only brings up the existing editor.
#   --setup        first-run setup (dependencies and an application menu entry)
#   --uninstall    remove the autostart entry and the menu entry (add --purge to delete your data too)
#   --diagnostics  write a support bundle without button contents
#   --terminal     the terminal editor        --tray   only the tray icon
#   --check / --no-browser   run in this terminal
# Needs Python 3.12 or newer with venv, and xdotool and xclip for keys, text and the clipboard (X11 session).
set -u
export PYTHONUTF8=1
cd "$(dirname "$(readlink -f "$0")")" || exit 1
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
  for tool in xdotool xclip; do
    command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
  done
  if [ "${#missing[@]}" -gt 0 ]; then
    echo "Note: ${missing[*]} not found. Keys, typing and the clipboard need them (install the packages of the same names)." >&2
  fi
  case "${XDG_SESSION_TYPE:-}" in
    wayland) echo "Note: this is a Wayland session. Tessera supports X11 only for now: keys, typing and windows will not work." >&2 ;;
  esac
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
  exit $?
fi

[ -n "$FIRST_RUN" ] && echo "2/3 Installing packages ..."
"$PY" host/setup_tool.py ensure || fail
[ -n "$FIRST_RUN" ] && "$PY" host/setup_tool.py setup >/dev/null
[ -n "$FIRST_RUN" ] && echo "3/3 Starting Tessera. Look for the editor and the tray icon."
check_tools

case "${1:-}" in
  ""|--app)
    background "$PY" host/tessera_tray.py
    background "$PY" host/tessera_app.py --editor
    ;;
  --setup)        "$PY" host/setup_tool.py setup || fail ;;
  --diagnostics)  "$PY" host/setup_tool.py diagnostics ;;
  --terminal)     "$PY" host/tessera_terminal.py || fail ;;
  --tray)         background "$PY" host/tessera_tray.py ;;
  --sensors|--sensors-off)
    echo "The hardware sensors setup is for Windows. On Linux the readings come from the system." ;;
  --check|--no-browser)  "$PY" host/tessera_app.py "$@" || fail ;;
  *)              background "$PY" host/tessera_app.py "$@" ;;
esac
