# Local verification

Tessera is now a pure Deck product. The firmware contains one full-screen
6 × 3 surface, and the Windows terminal is the main program. The local graphical
editor opens from the terminal with F8.

The verification covers:

- validation, saving and editing of profiles and empty pages
- folders and back navigation
- pinned buttons and toggle buttons
- multiple actions, hotkeys and protection against recursion
- 1,895 built-in Lucide icons
- import and normalization of custom images
- real program icons rendered at 256 px by the Windows shell
- native LVGL rendering at 1024 × 600
- ESP-IDF 6.1 build
- COM4 protocol, 21 synthetic button presses and a stable boot ID
- explicit LCD backlight on boot and on recovery over USB

The hardware test sends no hotkeys, shell commands or other actions to Windows.
COM6 is not touched. Detailed logs and screenshots are stored locally under
`build/`.
