# Contributing to Tessera

Thanks for wanting to help. Bug reports, ideas, ports to other boards and pull requests are all welcome.

## Propose a change

| You have | Do this |
|---|---|
| A bug | Open an [issue](https://github.com/catorendal-a11y/tessera-deck/issues). Say what you did, what you expected and what happened. Attach the file from **More → Save diagnostics** in the editor. It leaves out your keys' contents and redacts secrets. |
| An idea | Open an issue and describe the problem it solves. |
| A first contribution | Pick an issue marked [good first issue](https://github.com/catorendal-a11y/tessera-deck/labels/good%20first%20issue). Issues marked [help wanted](https://github.com/catorendal-a11y/tessera-deck/labels/help%20wanted) need the hardware or special skills. |
| A larger change | Open an issue first, so we agree on the approach before you write code. |
| A security problem | Do not open a public issue. Follow [SECURITY.md](SECURITY.md). |

## Set up

You need Windows 10 or 11 and Python 3.11 or newer. `Tessera.cmd --setup` creates `host\.venv` with the host's packages. On Linux you need an X11 session and Python 3.12 or newer, and `./Tessera.sh --setup` creates `host/.venv` ([Tessera on Linux](docs/LINUX.md)). For firmware work you also need ESP-IDF 6.1. For the native UI tests you need CMake and a C/C++ compiler such as MinGW. [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) describes the project layout and every tool.

## Run the checks

CI runs these on every pull request and every push to main. The tool versions are pinned in `.github/workflows/ci.yml`. Run them from the repository root:

```powershell
host\.venv\Scripts\python.exe -m pip install ruff==0.17.2 coverage==7.17.0
host\.venv\Scripts\python.exe -m ruff check host tests tools plugins hardware --select E9,F,B --exclude host/.venv
host\.venv\Scripts\python.exe -m coverage run --source=host --omit="host/.venv/*,host/tessera_terminal.py" -m unittest discover -s tests -v
host\.venv\Scripts\python.exe -m coverage report --fail-under=73
host\.venv\Scripts\python.exe host\tessera_terminal.py --check
```

CI also audits `host/requirements.txt` with `pip-audit`, runs the tests from the lock file, builds the firmware, runs `cppcheck` on it and runs the native UI tests. After an editor change, `foreach ($f in 'core','app','dialogs') { node --check host/editor/$f.js }` in PowerShell catches a syntax error early (`node --check` reads only its first file).

**UI changes without a board.** If you change `main/ui/ui.cpp` or `main/deck_model.c`, build and run the native tests. They need `managed_components/`, which is not in git: run `idf.py -B build/idf6 build` or `idf.py reconfigure` once. Then:

```powershell
cmake -S tests/native -B build/native -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build/native
build\native\test_ui.exe build\previews
```

The editor smoke test and the hardware smoke test are explained in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Change the dependencies

`host/requirements.txt` names the packages. `host/requirements.lock` pins every package with its hashes, and `Tessera.cmd` installs from it with `--require-hashes`. After you change `requirements.txt`, make the lock file again with Python 3.12, the version `Tessera.cmd` installs:

```powershell
py -3.12 -m venv build\piptools
build\piptools\Scripts\python.exe -m pip install pip-tools
cd host
..\build\piptools\Scripts\pip-compile --generate-hashes --strip-extras --no-emit-index-url -o requirements.lock requirements.txt
```

Commit both files. CI installs from the lock file on Python 3.11 and 3.14, so a lock that does not install fails there.

**Linux entries in the lock.** `pip-compile` on Windows does not list the Linux-only packages (`keyring`, `jeepney`, `secretstorage`, `python-xlib` and what they need). They are appended at the end of `requirements.lock` with `; sys_platform == "linux"`, and the Windows-only packages carry `; sys_platform == "win32"`, so that `pip install --require-hashes` works on both. To refresh them, run `pip-compile --generate-hashes --strip-extras -c <the Windows lock without hashes> requirements.txt` on Linux and copy the new Linux-only blocks over.

## What makes a pull request easy to merge

- One change per pull request, with a test that fails without it.
- The smallest change that solves the problem. Reuse what exists before you add a dependency.
- User-facing text is plain English and says what to do next.
- A line in `CHANGELOG.md` under `## Unreleased`, and updated docs if behavior changed.
- Nothing that sends data off the PC unless the user asks for it, since Tessera runs locally.
- The pull request template's test list filled in. Say which firmware you tried it on, or that you did not try it on a panel.

## Port to another board

Tessera is made for the GUITION 7-inch ESP32-P4 board (JC1060P470C). A port needs a board support package for the display and touch, and a board id of its own. The UI scales its 1024 x 600 layout to the screen size at start. The [CrowPanel Advance 7.0 port](docs/CROWPANEL.md) shows what that takes for another ESP32-P4 board. It adds a board choice and its id to `main/Kconfig.projbuild`, puts its pins, power and screen setup behind `CONFIG_TESSERA_BOARD_P4_CROWPANEL7` in `components/espressif__esp32_p4_function_ev_board`, keeps its build settings in `boards/crowpanel-p4-7.defaults` and adds the id to `BOARD_IDS` in `host/panel_serial.py` and `BOARD_CHIPS` in `host/firmware_update.py`. `tests/test_boards.py` checks that the two lists match. Open an issue with the board's name and resolution and we can work out what it takes.

By contributing you agree that your work is released under the [MIT License](LICENSE).
