# Contributing to Tessera

Thanks for wanting to help. Bug reports, ideas, ports to other boards and pull requests are all welcome.

## Before you start

- **A bug or an idea:** open an [issue](https://github.com/catorendal-a11y/tessera-deck/issues). For a bug, say what you did, what you expected and what happened, and attach the file that **⋯ → Export diagnostics** in the editor makes (it leaves out your keys' contents and redacts secrets).
- **A larger change:** open an issue first, so we can agree on the approach before you write the code.
- **A security problem:** do not open a public issue. See [SECURITY.md](SECURITY.md).

## Setting up

You need Windows 10 or 11 and Python 3.11 or newer. `Tessera.cmd --setup` creates `host\.venv` with everything the host needs. The firmware builds with ESP-IDF 6.1; the native UI tests need CMake, Ninja and a C/C++ compiler such as MinGW. [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) describes the project layout and every tool.

## Checks to run

```powershell
host\.venv\Scripts\python.exe -m unittest discover -s tests -p test_*.py
host\.venv\Scripts\python.exe host\tessera_terminal.py --check
```

If you changed the panel's UI or its model, also build and run the native test:

```powershell
cmake -S tests/native -B build/native -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build/native
build\native\test_ui.exe build\previews
```

CI runs the same checks, a lint and the firmware build on every pull request and every push to main.

## What makes a pull request easy to merge

- One change per pull request, with a test that fails without it.
- The smallest change that solves the problem; reuse what is already there before adding a dependency.
- Text the user sees is plain English and says what to do next.
- A line in `CHANGELOG.md` under the next version, and the docs updated if behaviour changed.
- Nothing that sends data off the PC without the user asking for it. Tessera runs locally.

## Porting to another board

Tessera is made for the GUITION 7-inch ESP32-P4 board (JC1060P470C). A port needs a board support package for the display and touch, and the layout constants in `main/ui/ui.cpp` if the resolution differs. Open an issue with the board's name and resolution and we can work out what it takes.

By contributing you agree that your work is released under the [MIT License](LICENSE).
