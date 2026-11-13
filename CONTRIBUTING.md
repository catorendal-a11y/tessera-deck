# Contributing to Tessera

Thanks for wanting to help. Bug reports, ideas, ports to other boards and pull requests are all welcome.

## Before you start

- **A bug or an idea:** open an [issue](https://github.com/catorendal-a11y/tessera-deck/issues). For a bug, say what you did, what you expected and what happened, and attach the file that **More → Save diagnostics** in the editor makes (it leaves out your keys' contents and redacts secrets).
- **A first contribution:** issues marked [good first issue](https://github.com/catorendal-a11y/tessera-deck/labels/good%20first%20issue) are small and well described; [help wanted](https://github.com/catorendal-a11y/tessera-deck/labels/help%20wanted) needs someone with the hardware or the skills.
- **A larger change:** open an issue first, so we can agree on the approach before you write the code.
- **A security problem:** do not open a public issue. See [SECURITY.md](SECURITY.md).

## Setting up

You need Windows 10 or 11 and Python 3.11 or newer. `Tessera.cmd --setup` creates `host\.venv` with everything the host needs. The firmware builds with ESP-IDF 6.1; the native UI tests need CMake, Ninja and a C/C++ compiler such as MinGW. [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) describes the project layout and every tool.

## Checks to run

CI runs these on every pull request and every push to main; the versions are pinned there (`.github/workflows/ci.yml`):

```powershell
host\.venv\Scripts\python.exe -m pip install ruff==0.17.2 coverage==7.17.0
host\.venv\Scripts\python.exe -m ruff check host tests tools plugins --select E9,F,B --exclude host/.venv
host\.venv\Scripts\python.exe -m coverage run --source=host --omit="host/.venv/*,host/tessera_terminal.py" -m unittest discover -s tests -v
host\.venv\Scripts\python.exe -m coverage report --fail-under=73
host\.venv\Scripts\python.exe host\tessera_terminal.py --check
```

If you changed the editor, `node --check host/editor/core.js host/editor/app.js host/editor/dialogs.js` catches a
syntax error before the tests load the page.

**UI changes without a board.** The panel's LVGL UI and its model build natively from `tests/native` and draw every
screen to PNG files, so you can check a change to `main/ui/ui.cpp` or `main/deck_model.c` without hardware. The
build needs the LVGL sources in `managed_components/`, which are not in git: run `idf.py reconfigure` once (or link
the folder from a checkout where ESP-IDF already fetched it), then:

```powershell
cmake -S tests/native -B build/native -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build/native
build\native\test_ui.exe build\previews
```

CI also builds the firmware and runs `cppcheck` on it.

**Dependencies.** `host/requirements.txt` names the packages; `host/requirements.lock` pins every package with its
hashes, and `Tessera.cmd` installs from the lock file with `--require-hashes`. After changing `requirements.txt`,
make the lock file again with Python 3.12 (the version `Tessera.cmd` installs):

```powershell
py -3.12 -m venv build\piptools
build\piptools\Scripts\python.exe -m pip install pip-tools
cd host; ..\build\piptools\Scripts\pip-compile --generate-hashes --strip-extras --no-emit-index-url -o requirements.lock requirements.txt
```

## What makes a pull request easy to merge

- One change per pull request, with a test that fails without it.
- The smallest change that solves the problem; reuse what is already there before adding a dependency.
- Text the user sees is plain English and says what to do next.
- A line in `CHANGELOG.md` under the next version, and the docs updated if behaviour changed.
- Nothing that sends data off the PC without the user asking for it. Tessera runs locally.

## Porting to another board

Tessera is made for the GUITION 7-inch ESP32-P4 board (JC1060P470C). A port needs a board support package for the display and touch, and the layout constants in `main/ui/ui.cpp` if the resolution differs. Open an issue with the board's name and resolution and we can work out what it takes.

By contributing you agree that your work is released under the [MIT License](LICENSE).
