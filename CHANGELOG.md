# Changelog

## Unreleased

- A profile file made on the other system imports. The review drops script steps this PC cannot run, adds `.exe` to program names where Windows needs it, and lists what it changed. Before, one such step refused the whole file.
- The plugin consent dialog names the program the plugin runs, and asks again when that program changes. Before, it showed an empty program.
- A `profiles.json` saved with a BOM or as UTF-16, as some editors do, is read. Before, the host stopped at start, the tray and the config check refused the file, and an older backup could take its place. The panel's brightness slider also saves into such a file.
- The Claude Code and Codex keys in the Windows default profile open the terminal in your user folder instead of the Tessera folder, so Continue and Resume find your conversations.

- Closing the editor window on Windows saves an edit that was still waiting to be saved. If the save fails, the editor asks before it closes and drops the change. Before, a change made just before closing was lost without a word.
- Closing or reloading the editor in a browser warns while a key is still a draft.
- Closing the editor no longer cuts off a firmware install that is running. The window stays open until the install is done.
- A firmware install and a Tessera update can no longer run at the same time. The *Update Tessera* button is greyed out while the panel firmware installs, and a firmware install started during an update is refused with the update named as the reason.

- A *Hold to confirm* key is cancelled when the finger slides off it in any direction, or flicks up or down on it. Before, only a fast swipe to the side cancelled it, and sliding down still sent the press after 600 ms.
- A touch that wakes the clock presses nothing. The same goes for a finger that is down when the screen changes, for example to a permission question or when the PC shows the clock.
- Long status values such as `123.4M /s` and `12d 23h` fit their card. The value gets a smaller font when it needs one, also on 800 × 480 panels.
- A key pressed while the panel shows NO PC is not sent later. Before, the press waited in the USB buffer and ran when a sleeping PC woke up.
- A P4 panel whose touch controller does not answer still starts, without touch. Before, it restarted in a loop.

- While the panel is away, the host no longer opens every Espressif and CH340 port on each retry. A board that stays silent three times or answers as another board is left alone until it is plugged in again, and with `TESSERA_PORT` set only that port is opened. On Linux each of those opens restarted a UART board.
- A CrowPanel or Sunton panel that restarts without leaving USB gets its page, rail and lock again. The host asks the panel every 5 s and sets it up again after a restart.
- `deckctl press` and `POST /v1/press` answer that the panel is not connected and the key was not pressed. Before, they answered OK.
- A USB device that stopped responding, or was pulled out during the handshake on Windows, is reported with the advice to unplug it and plug it in again. Before, the editor said the port was busy or offered a firmware install.
- A new panel without Tessera firmware gets the firmware hint even when an Arduino or another board next to it is busy or needs a replug. Before, the message named the other port.
- On Linux the host locks the panel port, so esptool and a second host report it as busy instead of sharing it. A panel with firmware this host does not speak is opened once and its reason stays, instead of a restart every 10 s.

## 1.2.11

Two things that 1.2.10 called working were not, and both turned up the first time they were run on a real panel: installing on a blank board, and updating the firmware over USB. This release fixes them, and both fixes were run on a GUITION JC1060P470C. Not run on real hardware: the Radeon RX 7000 and RX 9000 power reading, FPS with a game in full screen, and anything on Linux.

- Installing on a blank panel works on the real board. A board without firmware takes no data on its USB port, and the editor read that as a port it could not open, so it never got as far as asking the chip. It now asks the chip and offers the package. Tried on a GUITION JC1060P470C that was erased first: found as ESP32-P4 v1.3, installed, and running 1.2.10.
- The log says what to do when a port takes no data, instead of "Write timeout".
- Updating the panel over USB ("Update (keeps settings)") no longer stops with "The panel did not answer AD_OTA_DATA". The panel had all the data; its answer got lost on the way and Tessera gave up, or started over and gave up the second time. Tessera now goes on when an answer stays away, since the next answer tells how much the panel holds, and a panel that really missed data still refuses the next line. This works with the firmware that is on panels today. Tried on a GUITION JC1060P470C: seven updates in a row between 1.2.9 and 1.2.10 went through, two of them past a lost answer.
- The firmware no longer loses such a line. On boards whose USB port is the chip's own (GUITION, Waveshare ESP32-S3-Touch-LCD-7), the USB driver of ESP-IDF throws away what the firmware prints while it takes the PC for unplugged, and with a 1000 Hz tick it does that for a millisecond now and then, most often right after a flash write. Measured on the GUITION panel: 1 answer in 12,216 lost before, none in 15,270 after. `get_info` has a new field `usbGaps` that counts how often this was caught.
- When the answer to the last step of an update is the one that gets lost, Tessera asks the restarted panel which firmware it runs instead of sending the whole image a second time.
- The GPU power gauge works on Radeon RX 7000 and RX 9000 cards without extra software. These cards report the power of the whole board in another place than older cards, and Tessera only read the old one, so the gauge showed `--` (#47). Checked against AMD's own list of readings and against a card of the older kind (RX 6950 XT); no RX 7000 or RX 9000 card was at hand, so a report from one is welcome.
- The FPS gauge also works with Libre Hardware Monitor on a Radeon card: it reads the frame rate the Radeon driver reports for a game in full screen. Before, FPS needed HWiNFO with PresentMon. The selection was checked against the real readings of an idle PC; no game was running for the test, so tell me if the gauge stays at `--` in a game.
- The docs and the hint in the editor say how to use a Libre Hardware Monitor you already run: switch on its Remote Web Server (port 8085). Before, they only described installing a second copy.
- The CrowPanel Advance 7.0 (ESP32-S3) build runs on a tester's V1.5 board: picture, colours, touch and brightness. The docs no longer call it untried.

## 1.2.10

The new way to install on a blank panel was tried against a simulated USB port, not a real blank board, and the changes for Linux were not run on Linux. If you install on a new board or update on Linux, a report in the issues on how it went helps.

- Installing firmware on a new panel takes fewer steps. When no panel answers, the firmware dialog reads the chip and its revision from the USB port, says what it found and lists only the packages for boards with that chip. A GUITION board with a v3.x chip gets its package chosen for it. The *Install anyway* box is gone: *Install* asks once before it writes everything.
- The package list names the boards (GUITION JC1060P470C, Elecrow CrowPanel Advance 7.0 and so on) instead of their internal ids.
- *Check for updates* downloads the package for the board the dialog found, not always the one for the GUITION v1.x board.
- Editor fixes:
  - Adding a Held or Double-press step to a key with *Hold to confirm* no longer blocks saving. *Hold to confirm* is turned off and a notice says so, with undo.
  - *Move to slot* shows the key's real slot again when the move is refused.
  - A timer length the editor cannot read gets a message instead of being dropped in silence.
  - Changing a toggle key back to a normal key says that state 2 was removed, with undo.
  - Cancelling *Create a subpage* takes the half-made folder key back.
  - *Run now on this PC* is greyed out while no panel is connected, and *Hold to confirm* says why it is greyed out.
  - Keyboard focus stays where it was after a favorite, a kept backup, a screen setting or closing the Getting started card. The step buttons ↑ ↓ × have names for screen readers.
- The tray's *Check for updates* notice says how to update from the editor. It still pointed to the Releases page, from before the editor could update Tessera itself.
- The tray can look for a new version once a day and tell you once when one is out. It is your choice: on Windows the tray asks once, and **Help → Check for updates automatically** in the tray menu switches it on or off (on Linux it is off until you tick it). The look asks GitHub for the latest release and sends nothing about you or your setup. A Tessera from a package manager and a source checkout do not run it.
- Updating Tessera from the editor is safer:
  - The new version's packages are installed before Tessera closes. If that fails (no network), the dialog says so. Before, Tessera closed and never came back.
  - Every file of the new version is written first and swapped in at the end, with `VERSION` last. A file that is in use no longer leaves a folder with two versions mixed, and the update can be tried again.
  - On Linux the editor opens again after the update. Only the tray did.
- A first start that failed while it installed the packages repeats the first-run steps the next time, so the Desktop shortcut is made (Windows).
- A host that was started again after *Stop host* in the tray (from the editor, the terminal or a firmware install) is restarted automatically again if it dies.
- `--uninstall --purge` also deletes the logs and the other `*.local.*` files in `host/`. The uninstall names the autostart entry only when there was one.
- The host no longer stops when something unexpected goes wrong while it connects to the panel. It writes the reason to the log and tries again, as it does for a missing panel.
- A USB port that does not open is explained in plain words: in use by another program, not there, or (on Linux) not allowed for your user. The log used to show pyserial's own text, such as `PermissionError(13, 'Access is denied.')`.
- A request to the control API that fails inside the host gets an answer and a line in the host log. The connection used to close without either.
- A heartbeat thread that fails now makes the host reconnect instead of leaving the panel on its lost-PC screen.

## 1.2.9

- GUITION boards with a v3.x chip work now. A user tested the firmware on a v3.2 board: the picture is clean and touch and keys work (#21). It took four fixes:
  - The firmware restarted at every startup and the screen stayed black. The display code asked for the DSI clock source of the v1.x chips, which v3.x does not have. IDF now picks the clock source for the chip.
  - These boards have a newer screen panel. The v3 firmware sends it the matching start-up sequence and timing and resets it on GPIO0. Before, the screen showed only vertical stripes.
  - The screen runs at 48 MHz, a clock the chip can make exactly, with a line length the DSI host can count exactly (59 Hz), and its reads from PSRAM get the highest priority. Before, the picture had light vertical bands over it and flashed faintly.
  - The v3 firmware is built from the same settings as the tested v1.x build, with only the chip revision options changed. Before, it started from a shorter base config and about 60 settings (watchdog, LVGL, FreeRTOS) differed.
- When a port does not answer as a Tessera panel, the error now ends with the last lines it printed, so a crash at startup shows up in the diagnostics.
- Discussions has forms for questions, ideas and setups. The README, the website and the new-issue page link to it.

## 1.2.8

- AUR package: `tessera --gnome-extension` installs the GNOME Shell extension (`remove` takes it out), and `tessera --uninstall` removes the autostart entry and the extension. Before, the first did nothing and the second only printed a message. The editor no longer offers to update a packaged Tessera in place, which the next start undid; update it with your package manager.
- README: the terminal install for Windows uses `curl.exe`, so it also works in Windows PowerShell 5.1.

The AUR launcher changes have not been run on Arch yet. If you use the AUR package, a report in the issues on whether they work helps.

## 1.2.7

- Firmware for GUITION JC1060P470C boards with a v3.x ESP32-P4 chip, which newer boards have (#21). The firmware so far was built for v1.x chips only, so on these boards esptool refused it, and with the check skipped the screen stayed black. The new package is `tessera-firmware-tessera-p4-v3-<version>.zip` and the panel reports the board id `tessera-p4-v3`. It has not run on a v3.x board yet. When esptool refuses a package for the chip's revision, the editor now says which package to take.

## 1.2.6

- Experimental firmware for the Elecrow CrowPanel Advance 7.0 with the ESP32-S3 (800 × 480, hardware V1.3 to V1.5), asked for in #20. It has not run on the board yet. The cable goes to the UART port, as on the P4 CrowPanel.
- Wayland without `ydotool`: keys, typing, mouse buttons, the wheel and relative moves go through the desktop's RemoteDesktop portal. The desktop asks once and the permission is kept. `ydotool` is used whenever it is installed.
- Window actions and smart profiles on GNOME Wayland, through a small extension for GNOME Shell that `./Tessera.sh --gnome-extension` installs. While it is on, any program of your session can read window titles and focus, move or close windows. `./Tessera.sh --gnome-extension remove` takes it out again, and so does `--uninstall`.
- The tray icon on GNOME and other Wayland desktops without an X11 tray is a StatusNotifier one (on GNOME with the *AppIndicator and KStatusNotifierItem Support* extension): it has the desktop's own menu, and a click opens that menu. It needs `libayatana-appindicator` and PyGObject. Plasma keeps the X11 icon through XWayland, where a left click opens the editor; `PYSTRAY_BACKEND=appindicator` gives it the StatusNotifier icon. A desktop that shows no tray icon gets a notification that says why, and Tessera keeps running.

## 1.2.5

- Volume and media keys for devices paired with KDE Connect, a phone for example: play and pause with the state shown, next, previous and volume, on Linux and Windows. By joern-h.
- The host runs in a Wayland session on KDE Plasma. Keys, typing and the mouse go through `ydotool`, the window in front (smart profiles) and window actions through `kdotool`, and the clipboard through `wl-copy` or Klipper. Text is typed with your own keyboard layout, so `@`, `/`, `~` and `æøå` come out right on a Norwegian keyboard; a character the layout has no key for is refused before anything is typed. On other Wayland desktops keys and typing work and window actions say why they cannot. [LINUX.md](docs/LINUX.md#wayland) has the tools.
- On Linux the editor opens in a window of its own (WebKitGTK), like the Windows app, instead of a browser tab. Without WebKitGTK it still opens in the browser. WebKitGTK's DMA-BUF renderer is off in that window, because it draws an empty window with some GPU drivers.
- The tray icon has its right-click menu on Plasma Wayland too: pystray uses the X11 tray there, through XWayland.
- Linux: installing panel firmware from the editor stopped with "Host did not stop; no new owner was started" although the host had stopped. The tray did not collect a host that had ended, and the editor took the leftover process for a running one. Fixed by joern-h.
- A release also has its program zip as `tessera-host.zip`, so `releases/latest/download/tessera-host.zip` always gives the latest. The README has the three commands that install Tessera from a terminal with it.
- A *Farming Simulator* page template: enter and exit, attach, lower, tool on and off, fold, cruise control, lights, worker, unload, refill, next vehicle, camera, map and shop on the FS25 default keys. Change a key on the page if you have rebound it in the game.

## 1.2.4

The host and the editor change. The panel firmware is the same as 1.2.3 apart from its version number, so a panel on 1.2.3 works with this host as it is.

- The editor can update Tessera itself. After *Check for updates*, *Update Tessera to …* downloads the release's program zip, checks it against `SHA256SUMS` and unpacks it over the program folder. Profiles, icons and backups stay, and the firmware for every board comes with it, so the panel's update needs no second download. Tessera then starts again by itself. A source checkout is left to `git pull`.
- *Switch profile* can go straight to a page of the other profile. The page follows when it is renamed, and the step goes back to the first page when it is deleted.
- A daily automatic action can run on chosen weekdays only (*Only on*).
- A backup can be kept: *Keep* in **Restore a backup** holds on to it when newer ones come.
- The status screen can show eight of sixteen readings: upload speed, uptime, CPU clock, CPU power, GPU power, GPU clock, GPU fan and FPS are new.
- Ready-made keys that show state: *Mic mute (shows state)*, *Speaker mute (shows state)* and *Pomodoro 25 min*.
- The HTTP request step has *Headers* and *Timeout* fields, and *Run command* has *Timeout*. Before, both could only be set in `profiles.json`.
- Quiet hours take any two times. Before, the editor offered four fixed windows.
- *Move to page …* in the key menu moves a key to another page without the mouse.
- The firmware dialog says when the chosen package is older than the firmware on the panel, when the panel already has it, and when no package for this Tessera version is in the folder. Before, it preselected an older package and *Install* went back to it without a word. The line at the top shows the new firmware after an install, and the download message stays in view.

## 1.2.3

A panel with 0.7.0 or later takes this version with *Update*. The host works with a panel on 1.2.0 to 1.2.2 as it is; the two firmware fixes at the end of the list need the new firmware.

- The default profiles: hold Home to lock the profile. The panel then stays on it while you switch programs, and Home turns orange. Hold Home again to unlock. An existing setup gets the same with a *Lock profile* step under Held on its Home key.
- The editor's profile settings say how to keep the panel on one profile.
- A failed key says more. A macro names the step that failed ("Step 3: There is no such window"). A web request whose `$(env:NAME)` is not set names the variable; before, it failed as a bad address or as HTTP 404. A crashed plugin shows its own last line, such as the port it could not reach.
- The editor holds a step back with a reason when the host would refuse the whole file for it: a hotkey with a misspelled key name, *Bring a program to the front* without a program, and *Move the pointer to* without a position. On Linux it accepts `.sh` scripts and `/home/...` paths, which it used to refuse.
- Deleting a page or a profile says which keys lost the step that went there. A full page says to add a page. A file that is not an export, or one the host refuses, says that nothing was changed.
- *Test* on a key says when a plugin step cannot run because the plugin is not installed, off or stopped.
- A new counter or timer key shows `0` or `00:00` until its first use; before, it showed the text `$(counter:name)`. The music key says *Nothing playing*. Uptime under an hour is in minutes. The *Next meeting* key follows the 12-hour clock setting.
- Dimming never makes the panel brighter: with quiet hours at 5 % and a dim level of 10 %, the panel got brighter when it dimmed. Weather that cannot be refreshed for an hour is no longer shown as the weather now.
- `deckctl get NAME` prints one variable. Every `deckctl` command has help text, and a stopped host is answered with how to start it. `GET /v1/state` lists the profiles with their pages and whether the profile is locked, and an unknown profile or page is answered with the names that exist.
- Automatic actions: the host log says when one ran, and a file rule takes a path that starts with `~` or an environment variable.
- A profile rule `title:` with nothing after it matched every window; it now matches none.
- *Check for updates* says what went wrong: no connection, GitHub limiting requests, or an error from GitHub.
- Uninstall takes Tessera's hooks out of Claude Code's settings; before, Claude Code went on starting `deckctl` from a folder that was gone.
- Save diagnostics names the board, the panel's last reset reason and the state of each plugin.
- Ready-made keys: *Fetch (pull)* and *Send (push)* for GitHub Desktop are named *Pull* and *Push*, and in the Daily control template the `Win+V` key is *Clipboard history* and the `Win+A` key is *Quick settings*.
- Docs: NVIDIA cards give no fan speed without Libre Hardware Monitor or HWiNFO, and the Date widget shows the weekday and the week number.
- Fixed: a calendar with an event from before 1970, or with an impossible length, took down every page that has the *Next meeting* widget and made the host reconnect in a loop. Such an event is now skipped.
- Fixed: a page the panel refuses when it connects (too large, or a picture it cannot hold) made the host close and reopen the USB port for ever. The host now stays connected and logs the page. A profile whose first page is refused leaves the host on the profile it had.
- Fixed: a permission question could fail to come up on the panel. The host asked for the agents screen before it sent the question, and a panel that drew in between went back to the keys. A question that is open while the panel reconnects now comes up too.
- Fixed: a panel that reconnects while Windows is locked stayed lit until the idle timer dimmed it.
- Import: a file with more than 200 flagged actions showed only the first 200, and *Keep these actions* kept all of them. The list now shows the commands first and says how many it leaves out.
- Editor: deleting a page or a profile could leave a rail shortcut without steps, and the host then refused every save. Such a shortcut is removed with the page.
- Editor: a save made while another save was merging a change from the tray no longer says the configuration is in conflict.
- Editor: a key made right after *Clear* with the Held or Double-press tab open got its step there, so a tap did nothing. A new key always gets its step on Pressed, in its first state.
- Editor: *Undo* in a toast takes back the change the toast is about, not a later edit. *Record* on a hotkey ends when you click elsewhere; before, the next letter typed in any field replaced the hotkey. Typing a new plugin password replaces the stored one; before, it was added to its end.
- Linux: *Start with the desktop* in the tray failed with "only supported on Windows". The idle clock failed once a second in the host log. *Save diagnostics* in the tray tried to start Windows Explorer. Shuffle and repeat never showed the player's state. *Volume up* lowered a level above 100 %. An autostart entry left by a copy in another folder counted as on. The diagnostics file kept the user's name in `/home` paths.
- Windows tray: the question *Start with Windows starts Tessera from another folder* never came when the first-run record was copied over with the other files.
- The files that hold the editor's and the control API's tokens are made private before the token is written. Claude Code's settings file and its backups keep the permissions the file had.
- Home Assistant plugin: entity values become *unknown* when Home Assistant cannot be reached; before, a key went on showing the last state.
- Control API: `GET /v1/events` with a `since` from before a host restart returns the new events; before, it returned nothing until the ids caught up.
- Firmware: a hold on a *Hold to confirm* key is cancelled when another screen comes up under the finger. A touch that wakes the panel while a dim command is on its way no longer leaves the next tap swallowed. Both need this firmware on the panel and have run only in the native tests.
- Desk consoles: the print files are also on [Printables](https://www.printables.com/model/1921087-tessera-desk-console-for-7-inch-esp32-p4-panels-gu) and [MakerWorld](https://makerworld.com/en/models/3640174-tessera-desk-console-for-7-inch-esp32-p4-panels), and MakerWorld has sliced print profiles for Bambu printers.
- Docs: the website shows the four screens, the agents screen, scripts and a comparison with Stream Deck. The guides say what differs on Linux and on the other boards, the protocol page lists the `w`, `h` and `imgCache` handshake fields, and the hardware notes have print times and weights from the slicer. VERIFICATION.md lists hold to confirm, the panel lock, the about sheet, the widgets, the faders and the ambient screen as tried by hand on a panel.

## 1.2.2

The host now also runs on Linux. The panel firmware is the same as 1.2.1 apart from its version number, so a panel on 1.2.0 or 1.2.1 works with this host as it is.

- The host runs on Linux in an X11 session, contributed by joern-h. `Tessera.sh` sets it up and starts the tray, the host and the editor, which opens in the browser. Keys, typing, the mixer, media, sensors, plugin secrets in the system keyring, the program list and autostart all have a Linux side. It is tested by hand with the CrowPanel on Arch Linux with Cinnamon; keys, sound and sensors have had less hand testing than the panel link and the tray. Wayland is not supported yet. [LINUX.md](docs/LINUX.md) has the tools to install and what stays Windows-only.
- The idle clock no longer comes on while you work on the PC: typing or moving the mouse counts as activity, as a press on the panel does, and takes the clock away again. A clock shown by a *Switch screen* key stays.
- Desk console: it has been printed, and the GUITION JC1060P470C (the `_Y` variant, in its factory housing) fits it perfectly. An upright wall carries the shelf under the screen from the bed, the rim over the back opening grows out of the back wall, and all four foot pads reach into the walls. The outside and the fit round the panel are unchanged.

## 1.2.1

Fixes in the host, the editor and the OBS plugin. The panel firmware is the same as 1.2.0 apart from its version number, so a panel on 1.2.0 works with this host as it is.

- OBS plugin: a volume or source key that OBS refused kept waiting for an answer, so the next press did nothing for five seconds. A refusal now ends the wait, and a late answer to an older press no longer ends the wait of a newer one. A pause key while OBS is not recording now flashes red and says so; OBS 33 accepts that pause without a word.
- Run script: quotes around the path (as from Explorer's *Copy as path*) and spaces around it are ignored. Only `%NAME%` is read as a variable, so a folder named `$NAME` works. A variable that is not set fails the key and names the variable; before, a `.bat` path with one made the whole configuration invalid.
- The editor's firmware dialog preselects a package only for the connected board. With packages for one board and a panel that does not say which board it is, it used to preselect that package.
- A `warn` or `error` message from `deckctl say` or a plugin wakes a dimmed panel, except while Windows is locked.
- Run now in the editor asks first when the key sends a plugin command.

## 1.2.0

A panel with 0.7.0 or later takes this version with *Update*. An older panel, or one with the Wi-Fi beta firmware, needs *Full install* once, and so does a CrowPanel the first time. *Update* from 1.1.0 has not been tried on the S3 boards.

- Firmware, Waveshare ESP32-S3-Touch-LCD-7: the pixel clock is 12 MHz instead of 16, so the screen refreshes 29 times a second instead of 39. The first test on a real board ran at 12 MHz and was stable; on this board 16 MHz has made the picture jump in other projects while PSRAM was busy. The same test found the display, touch, keys, PC actions and the native USB link working.
- Firmware: a build for the Elecrow CrowPanel Advance 7.0 (ESP32-P4), contributed by joern-h. The panel reports the board id `tessera-p4-crowpanel7`, which the host now accepts. CI builds it, and the release has its package, `tessera-firmware-tessera-p4-crowpanel7-<version>.zip`. It works on the contributor's board, colors and touch included; [CROWPANEL.md](docs/CROWPANEL.md) has the details.
- The update check offers the firmware package for the connected board. The board id never reached it before, so an S3 or CrowPanel panel was offered the GUITION P4 package. The editor's firmware dialog names the board of each package and preselects the one for the connected board. When the panel does not say which board it is, you choose, since nothing refuses the GUITION package on a CrowPanel. `tools/package_firmware.py` refuses a `--board` that does not match the build.
- Firmware: the panel opens with a boot screen. The logo builds itself tile by tile and the wordmark switches on column by column, then the logo fades out and the keys appear, 1.4 s in all. The backlight now comes on with the first boot frame, so the panel no longer flashes grey at power-on.
- Ready-made keys for Shut down, Restart, Sleep and Sign out, which ask you to hold to confirm, and for Game Bar, New folder, Rename, System info and new or private browser windows.
- Shuffle and repeat keys for players that offer them in the Windows media session, and $(pc:shuffle) and $(pc:repeat) for labels. Without a player, or with one that does not offer it, the key flashes red and the panel says why.
- Discord, Telegram and ntfy message keys. The webhook address or bot token comes from an environment variable, so it is not stored in the profile.
- A Run script step for .py, .pyw, .ps1, .bat, .cmd, .ahk and .js files. It runs the script without a window, and the editor has a file picker, an Edit button and a dry run check for it.
- HTTP requests from keys send Tessera-Deck as the User-Agent unless the key sets its own.
- OBS plugin: show, hide or toggle a source, pause and resume recording, save the replay buffer, toggle the virtual camera, run the studio mode transition and change input volume in dB steps. New variables follow recording pause, input mute and OBS errors.
- A Plugin command step in the editor: choose an installed plugin, type the command and give its arguments as JSON, so plugin keys no longer have to be written into `profiles.json` by hand. A new OBS page template has Record, Stream, Pause, Save replay, Virtual cam, Transition and the current scene.
- OBS plugin: while OBS is not running, or when it refuses a key (studio mode off, no replay buffer, a scene that does not exist), the key flashes red and the panel says why for three seconds, instead of doing nothing. For this the plugin also asks for the `notify` and `feedback` permissions. If it is already on, it gets them at its next start without asking again.
- `deckctl say` and `POST /v1/notify` show a short message as a banner across the top of the panel, with a new `notify` permission for plugins. Older panel firmware gets a tray notification instead.
- When a key fails, the panel shows the reason on its banner for six seconds (firmware with the banner only). A key that presses another key reports that key's reason, and a plugin step fails when its plugin is not installed, off or stopped.
- Windows: after an update unpacked to a new folder, Start with Windows kept starting the old version. When the panel first connects, the new copy's tray now asks whether to start this copy instead, and the tray menu ticks Start with Windows only when the entry starts this copy.

## 1.1.0

A panel with 0.7.0 or later takes this version with *Update*. An older panel, or one with the Wi-Fi beta firmware, needs *Full install* once. The two ESP32-S3 boards need *Full install* the first time, and their firmware has not been tested on S3 hardware.

- Experimental firmware for two ESP32-S3 boards with an 800 x 480 screen, the Waveshare ESP32-S3-Touch-LCD-7 and the Sunton ESP32-8048S070. It has not run on real S3 hardware. [S3.md](docs/S3.md) has the build commands and the open points. The P4 firmware and its screen are unchanged.
- Firmware: the screen layout is scaled to the display size at start. 1024 x 600 draws as before.
- Firmware: `get_info` reports the screen size and the image cache size (`w`, `h`, `imgCache`). The host assumes 1024 x 600 and 8 MiB when firmware does not send them.
- Host: the firmware dialog and the update check pick the package for the connected board. S3 packages are named `tessera-firmware-<board>-<version>.zip`, and a package for another board is refused.
- Host: a CH340 serial port is found as a panel and opened at 921600 baud with DTR and RTS low.

## 1.0.0

A panel with 0.7.0 or later takes this version with *Update*. An older panel, or one with the Wi-Fi beta firmware, needs *Full install* once.

- Firmware: *Update* on a panel with the Wi-Fi beta firmware now says to use *Full install* because this version cannot talk to the beta. Before, the message blamed the A/B flash layout.
- Firmware: a page change draws the screen once. Before, the panel drew the whole screen again for every wake the host sends with a page and with a key's feedback, so going to a page and back showed it redrawn three or four times in a row.
- A rail shortcut or Home into another profile goes straight to its page. Before, the panel showed that profile's first page for a moment on the way.
- Firmware: a picture that arrives after its page goes into its own key. Before, each one redrew every key and could drop a press that was still held.
- Firmware: when an agent's text changes, only that text is redrawn on the Agents screen. Before, the whole list was rebuilt every few seconds and a tap on Open or Stop could get lost.
- Firmware: `get_info` reports how many screen updates there were since the last `get_info` and how long the slowest took (`draws`, `drawMaxMs`). [VERIFICATION.md](VERIFICATION.md#screen-speed) has the numbers measured with it.
- Host: an HTTP action no longer follows a redirect from https to http. A redirect to another host goes there without the action's headers. Before, urllib sent every header, an `Authorization` header too, to wherever the redirect pointed.
- Host: an *Open* step with an address no longer fills in `%NAME%` from the PC's environment. Paths still do.
- Import: a web request that sends `$(env:NAME)` in its address, headers or body is marked high risk and names the variable. Before, it was medium.
- Docs: the README links [VERIFICATION.md](VERIFICATION.md). The watchdog, the rollback and the offline layout were tried on a panel, and VERIFICATION.md has the results.
- Docs: the panel images and the demo animation are drawn again with the current firmware UI, from a demo profile built on the default one.

## 0.10.1

- A profile file saved by the Wi-Fi beta now loads on this version. Before, the host replaced it with an older backup when it started. Its Wi-Fi and Home Assistant settings and steps stay in the file, and a key skips its Home Assistant steps and runs the rest.
- Export leaves out a code or password in the data of a Home Assistant step, as the beta does.
- Import lists the Home Assistant steps in a file and leaves them out unless you keep them, as the beta does.

## 0.10.0

- Editor: **More → Automatic actions …** lists, adds and orders the rules in `triggers` (at startup, every so often, every day at a time, when a file or a variable changes). Each copies its steps from a key.
- Automatic actions: a variable rule can have a `value`, so it runs only when the variable becomes that value (`"claude"` becomes `waiting`), not on every change.
- Automatic actions: moving or removing a rule no longer makes the variable rules after it run once at the next save. Each rule keeps its state by what it watches, not by its place in the list.
- Automatic actions: a rule set to run when the host starts now runs even when no panel is connected, instead of waiting for the panel. A daily rule that could not be queued because the host was busy now runs as soon as there is room, instead of being skipped for the day, and a *file changes* rule runs the first time its file is created, not only from the second write.
- Automatic actions: steps copied from a key that is not finished yet are refused when you save, instead of making every later save fail.
- Editor: *Color follows a variable* on a key's **Live** tab sets `status`, a color per value, and the tile shows the color for the current value.
- Panel: the agents screen shows each tool's icon, since when it has worked or waited (*working since 14:12*), its project behind a folder icon, *Open* beside *Stop* while it works, and a clearer screen when no agent runs. The host sends the start time as `at` in `AD_AGENTS`.
- Editor: a page over 8 KB now says it is too big to send to the panel, and that the panel keeps the last layout that fit.
- CI: a failing host test now turns the main CI check red, and a release is only published when the full CI run (host tests, lint, firmware static analysis, firmware build and native tests) passes on the tagged commit.
- Firmware: the comment on `CONFIG_LWIP_TCP_MSS` in `sdkconfig.defaults` now says that 400 is below lwIP's minimum of 536 and is ignored, and that the build uses 1440.
- Calendar: alarms inside an event no longer change its title, length or moved instances. Weekly or daily UTC events keep the right local time after the clocks change, and moved or cancelled instances match again.
- Control API: the host disconnects clients that send a request too slowly, limits open connections and no longer lets unauthenticated requests flood the log.
- Shell commands: a variable value with spaces stays one argument. A value that starts with `-` or `/` where an argument begins is refused, so a variable cannot add options to the command. Such a value is allowed inside a double-quoted string when it does not start the argument (`"Now playing: $(t)"`).
- A web link ending in `.exe`, `.bat` or `.cmd` now opens in the browser and not a local program with the same name.
- Export now replaces every header named like a credential (`Private-Token`, `X-Access-Token` and similar) and address fields such as `?token=` or `?api_key=` with `$(env:...)` references. Exporting a profile works even when an image file is missing; that image is left out.
- SECURITY.md now says that single variable updates are logged and only bulk updates are left out, and that Replace-mode imports can carry plugin settings.
- Docs: the plugin docs now give the real restart schedule (1, 2, 4 and 8 seconds, then the plugin gives up after the fifth crash), and the website no longer claims that keys run only when pressed on the panel.
- Panel: an Allow or Deny tap on the agents screen now answers only the request shown when you tapped, never a later one that appeared while the host was busy.
- Panel: a tap that lands just as the PC switches pages no longer runs the key that the new page has in that spot.
- Panel: a key's live value (label, color or gauge) that changes while the keys are being redrawn now shows straight away, instead of waiting for the next change.
- Panel: an image that arrives while you hold a key no longer redraws the keys under your finger. The hold or the confirm ring finishes, and the image appears when you lift.
- Panel: feedback a plugin sends to a dimmed panel only flashes the key; the panel stays dim and the next tap runs its action.
- Panel: pressing a wide calendar or media key whose title contains a tab now runs its action instead of being rejected as a different key.
- Plugins: logs are rotated at 1 MB while the plugin runs, not only when it starts. A running plugin whose log passes 1 MB is restarted, so the log is rotated with `os.replace` instead of being truncated while the plugin still has it open.
- Plugins: settings that show a default, such as the Home Assistant address, are now saved, so the plugin gets them when you only fill in the token.
- Host: a configuration save that the host could not read for a moment, for example while a scanner held the file, is now read again instead of being ignored until the next save.
- Saving no longer fails with "Access is denied" when the host happens to be reading the profile file at that moment; Tessera tries again for up to a second.
- A brightness or notification change from the tray while the editor is saving is no longer overwritten. Any other change saved elsewhere at that moment shows up as a conflict instead of being lost.
- Backups: if Tessera has to restore a backup over a broken profile file a second time, the earlier broken copy is kept as profiles-unreadable-1.local.json instead of being overwritten.
- Host: a plugin or script that sends a variable with a broken emoji no longer stops the host or freezes the status the editor shows.
- Host: a virus scanner that has the editor's or tray's *Show on panel* command file open no longer stops the host, and a second command sent right after the first is no longer lost.
- Host: a profile chosen with `deckctl page` or the control API stays on the panel instead of being switched back by the focus rules within a second.
- Host: when sending a new page to the panel fails, the host goes back to the page and folder it had and still reports the error; the page event is logged only after a successful send.
- Host: a program icon that could not be read at start is tried again after a minute instead of staying the default icon until restart.
- Diagnostics: *Save diagnostics* now works when profiles.json cannot be read, from the tray, the editor and `Tessera.cmd --diagnostics`.
- Uninstall with `--purge` now also deletes the previous and unreadable copies of your profiles. If it cannot delete a file, it names the file and exits with code 1 instead of reporting success.
- Dry run no longer calls working keys broken: it accepts URI links such as `spotify:...` and program names such as `winword`, and it reports a bad delay or key combination on that step instead of failing the whole check.
- Terminal UI: a page rename or import that cannot be saved says so and leaves everything as it was; before, the terminal closed or showed "Imported".
- Terminal UI: changes saved in the editor while the terminal UI is open are kept. The terminal UI loads them and asks you to make your change again.
- Terminal UI: renaming a page keeps the page in its place and keeps press, hold and double-press actions and rail shortcuts pointing at it.
- Terminal UI: importing a file lists its commands, web requests, plugins and automatic rules, and leaves them out unless you choose to keep them, as the editor does. Export leaves out the calendar address and plugin secrets, and writes credentials in web requests as `$(env:NAME)` references, as the editor's export does.
- Terminal UI: *Stop host* keeps the host stopped while the tray runs, and the tray no longer reports it as a crash.
- Editor: undo and redo no longer bring back old settings after the editor merged a change saved elsewhere, such as the tray's brightness.
- Tests: `tests/cache_bench.py` switches between pages that share almost no icons while live keys change, and reports hit rate, evictions, USB traffic and tap-to-paint time. It runs the real host against the panel's image cache and UI built for the PC (docs/DEVELOPMENT.md).
- Images (firmware and host): a panel that reports `"imgAck":1` answers every 2 KB of an image upload, as it does for a firmware update, and the host waits for that answer and sends 512 bytes a line instead of 160 bytes with a 10 ms pause after every 4. On a panel a 12-frame icon now takes 0.65 s to send instead of 2.8 s, and a still icon 86 ms instead of 0.22 s. In the benchmark a page switch that sends fifteen 12-frame icons drops from 40 s to 10 s. Older firmware and older hosts keep the paced upload.
- Tests: `tests/cache_bench.py --old-firmware` measures the paced upload, and `--ack-ms` sets the round trip counted for each answer the host waits for.
- CI: the firmware job runs `tests/cache_bench.py --check` with and without `--old-firmware`. A key left blank after a page switch, or a host and panel that disagree about which images the panel has, now turns CI red.

## 0.9.0

- Panel: a long gauge value (3.8GHz, 302rpm) steps down a font size and stays inside its ring.
- Editor: everything is drawn 15 % and then another 10 % smaller, and the panel preview stops growing at its real width (1024 px).
- Editor: a rail shortcut opens its page like a page tab, so clicking Keys and the shortcut again no longer flips the panel through other pages.
- Host: a page picked in the editor reaches the panel in one step, without the profile's first page in between, and live gauge values no longer land on the wrong keys during a page change.
- Host: the window's own program wins over its child processes when picking a profile, so Chrome running claude.exe for an extension still shows the Chrome profile.
- Import: *Without commands* also removes text typed after a hotkey (Win+R, a command and Enter runs it), and the review lists such keys.
- Images: a dropped image is only read as PNG, JPEG, GIF or WebP, so Pillow's other decoders never see it.
- CI: every GitHub Action is pinned to a commit SHA, and a test keeps it that way.
- Sensors: Libre Hardware Monitor now runs with administrator rights only from a verified copy in `%ProgramFiles%\Tessera`, which other programs cannot change, and a firewall rule keeps its port 8085 off the network. Run `Tessera.cmd --sensors` again to move the sign-in task there.
- Panel: a brightness change is saved to the panel's flash at most once a minute (it still applies at once), and the panel refuses JSON nested more than 16 levels deep, so a bad message can no longer crash it or make it restart in a loop.
- Security: a key whose program is on a network share (`\\server\…`) or a web address no longer reads its *app* icon from there, which sent your Windows sign-in to that server without a key press. The key shows the default icon.
- Security: a calendar with hostile repeat rules can no longer keep the host busy for minutes; an old monthly or yearly meeting now also shows up.

- Security: the Claude Code permission hook and deckctl only talk to a running Tessera host. A program that answers on the port of a host that crashed can no longer approve a tool call or receive the token, and the editor and control API drop a connection that stalls for 10 seconds.
- Security: the editor's address holds a one-time code instead of its session key, so a copy in the browser's history no longer opens the editor, and the session key no longer travels in a cookie that other programs on 127.0.0.1 could receive. A second editor tab opened from an old address asks you to start Tessera again.
- Panel: the idle clock is bigger, in deeper colors, with a larger date and weather line, and an icon for the weather (sun, or a moon after sunset at the place, cloud, fog, drizzle, rain, snow or thunder).
- Panel: a 12-hour clock with AM/PM. *Clock format* in Panel → Display is *Same as Windows* by default, or 24-hour or 12-hour.
- Windows notifications can be switched off: *Show Windows notifications* in Program settings, or *Show notifications* in the tray menu. Answers to a tray click still show, and switching it in the tray while the editor is open no longer makes the next save conflict.
- Panel: a locked panel also ignores Allow, Deny, Stop and Open on the agents screen and the faders and mute on the mixer. A question still shows.
- Panel: Allow, Deny and Stop answer the agent the lane showed, and do nothing if that agent's state changed before the screen caught up.
- Panel: gauge keys draw a ring filled to the percentage, and the badge icon in the corner.
- Panel: a key's confirmation no longer flashes the key that took its place after a page change.
- Panel: the idle screen's line is no longer missed when it changes at the moment it is drawn.
- Panel firmware: when the display fails to start, the panel restarts instead of going silent on USB, so an unconfirmed update rolls back.
- Host: moving the panel's brightness slider (or any save that leaves the keys as they were) no longer resets toggle keys, leaves the open folder or wakes a dimmed panel.
- Host: a plugin whose log file cannot be opened is marked as failed and backs off instead of retrying every few seconds.
- Host: a weather place name can no longer break the idle clock line, and a long non-English name is cut on a whole character.
- Host: a wide pinned key that would cover a page key (or the reverse) is rejected when the configuration is checked.
- Host: a profiles.json that is briefly locked at start (antivirus, an editor saving) is no longer replaced by an older backup.
- Host: the panel's audio and media state keeps updating after an unexpected error from the audio or media library.
- Host: the control API answers 401 to a token with non-ASCII characters instead of dropping the connection.
- Firmware update: the message for a single-slot package names *Full install*, the option the editor has.
- Diagnostics: the support bundle masks key labels in the log ("Button 3: <label>"), as the editor promises. The live host log on your PC still shows them.
- Home Assistant plugin: a refused key command shows "HA error 404" (or the code it got) instead of "not reachable".
- Terminal UI: a new profile, page or template that cannot be saved shows "Not saved" and no longer closes the app.
- Editor: a step the host would refuse (key number outside 1-18, an unfinished hotkey like `ctrl+`, an address without http://, a counter, timer or variable name with spaces, Lowest above Highest, a wait over 60000 ms) stays a draft with a *Finish key* link, so the other keys still save.
- Editor: switching a toggle key back to a normal key clears *Follow PC state*; before, every later save was refused.
- Editor: renaming or deleting a page fixes triggers in every profile, and leaves triggers alone while another profile still has a page with that name.
- Editor: a pinned key can only be made wide when the slots are free on every page.
- Editor: profile and page names stop at 100 characters, the host's limit, also for copies of copies.
- Editor: a plugin asks again when its command or permissions change, even under the same version.
- Editor: a failed online icon search shows the error in the results instead of *Searching …*; Ctrl+C with text selected copies the text, not the key.
- Editor: no false "changed in another window" after restoring a backup, and no second save with an old revision while a merge retry is running.
- Host: a *Set variable* step needs a name of letters, digits, `_ . -` (the only names `$(var:…)` can read) and a value of at most 1000 characters.

## 0.8.0

- Firmware update over USB: when the panel stops acknowledging partway, the host aborts and starts the upload once more by itself. The panel keeps its running firmware either way.
- Editor: the Panel menu starts with *Display …* (brightness, dimming, quiet hours and the idle clock, which used to sit in Program settings and *Clock when idle …*) and *Panel firmware and updates …*. Program settings keeps only what the PC does: autostart, automatic profiles and the calendar.
- Editor: *Panel screens …* is gone from the Panel menu; choose what the agents, mixer and status screens show on those screens in the rail, as the Rail dialog now says.
- Editor: the Page menu has *New page*, and the Page and Profile menus each have *Delete this page* / *Delete this profile* with Undo in the toast. The settings dialogs no longer have a delete checkbox.
- Editor: the More menu starts with *Getting started* and no longer repeats *Keyboard shortcuts* (the app bar has it).
- Editor: every place that talks about safe editing uses the same sentence: "Nothing runs in the editor. Keys run only when you press them on the panel." *Run now* in Test stays the one exception.
- Editor: the action list hint and the Getting started step say what a click does (a new key on the selected empty slot or the first free one) and that a drop on a key adds a step.
- Docs: USING.md and INSTALL.md use the editor's names (Profile, Page, Panel and More menus, Look, Actions and Live tabs, the action list on the right, Program settings, Panel firmware and updates). INSTALL.md has a *First 5 minutes* section and no fixed COM port; USING.md troubleshooting starts at More → Host log.

- Editor: text is no longer scaled down in smaller windows. Body text is at least 14 px and labels at least 13 px; the app bar, rail, status bar and messages now share one scale.
- Editor: from 1280 px wide, the key's settings sit in their own column beside the deck instead of below it, and the deck preview grows with the space.
- Editor: the action list on the right folds into a narrow strip with its Actions button; the editor remembers your choice, and / opens it again.
- Editor: dim and secondary text has more contrast, and Windows' high-contrast setting raises lines and text further.
- Editor: long profile and page names and tab labels are cut with an ellipsis instead of wrapping; many pages scroll sideways.
- Editor window: the first window fits the screen, including a 1366x768 laptop, and the editor reopens at the size and place you left it.
- Getting started: on a first run the editor shows a live checklist (Host running, Panel connected, Firmware up to date, Put an action on a key, Press it on the panel) that ticks itself off from the host status. *Install firmware …* sits on the panel step, and closing the card is remembered by the host (`host/setup.local.json`).
- The first key press that reaches the PC says "It works" and lights up that key in the editor.
- New installs start with a lean home page (volume, mute, play/pause, Explorer, Terminal, screenshot, calculator, show desktop, lock) and the Status, Desktop, Audio and Tools folders, without the author's own apps.
- `Tessera.cmd` shows numbered progress lines (1/3 … 3/3) on the first start.
- The tray asks about *Start with Windows* only after the panel first connects, and that first connection says to open the editor to set up your keys.
- Editor: when no panel connects, the status bar names the cause (another program holds the USB port, firmware too old, not a Tessera panel, or no answer) and shows the host's own error on a second line.
- Editor: connection problems in the status bar have a *Show the host log* button.
- Editor: a panel with older firmware than Tessera gets a status bar notice with *Update firmware …*; *Not now* hides it until the next Tessera version.
- Editor: *Start host* in the status bar shows "Starting the host …" and keeps a failure in the bar.
- Editor: the LED and connection text open a *Panel status* window with the port, firmware, Tessera version, the next step and *Panel firmware …*.
- Panel firmware: with no panel connected the dialog chooses the full install and shows *Install anyway* at once; the choices are now *Update (keeps settings)* and *Full install (new or blank panel)*, and the protocol number shows only when it does not match.
- Panel firmware: a panel that does not answer is told to choose *Full install* and tick *Install anyway*.
- Editor: a click on an action in the list always makes a new key, on the selected slot when it is empty or else on the first free slot; drop an action on a key to add a step to it. A toast says which key got it.
- Editor: a new key opens on the Look tab with the cursor in Title, so you name it first.
- Editor: pasting a key or placing a program on a key that is in use says "Replaced key N" with an Undo button.
- Editor: an unfinished key gets a yellow dot and a tooltip, and the sync line links to it. The other keys keep saving; the panel gets the unfinished key without its unfinished part.
- Editor: adding Open folder opens Create a subpage with the key name filled in. The key gets the page as its name and target, the editor opens the new page, and a toast says Back is on slot 17. The list names are now "Open folder (with Back key)" and "Go to page (no Back key)".
- Editor: a step's action type is a menu in the step title, so a wrong pick changes in place.
- Editor and host: a key with Position set to Hide text may have an empty name (icon only).
- Editor: drag a key onto a page tab to move it to that page. Each page remembers its selected key.
- Editor: the sync line has a "Show this page on the panel" button when the panel shows another page, and says "✓ On the panel" after a save. The checkbox is now "Panel follows the page I edit".
- Editor: the Look tab has an **Action** row with the field a key needs most: **Record** for a hotkey, **Choose program …** for an open action, or a summary that opens the steps.
- Editor: **Test**, **Copy**, **Paste**, **Clear** and **Move to slot** sit in a footer under the inspector tabs, so they show on every tab. *Hold to confirm* moved to the Actions tab, and *Add action …* is now **＋ Step …**.
- Editor: the inspector tab *Gauge* is now **Live**.
- Editor: the icon library stays open after you pick an icon, so you can try a few. Icon color has 8 swatches, *Key colors* is a row in the Look tab, and *Quick icons* are gone.
- Editor: **Test** is also in the Look header, and the test dialog has **Run now on this PC**. It shows the page on the panel and presses the key there, and asks first when the key runs a command, sends a web request or types text.
- Editor: a widget key shows *Widget: Clock · Change …* instead of title, icon and text rows that did nothing, and its tile shows the same text as the panel.

## 0.7.0

- Install: `Tessera.cmd` installs the host packages from `host/requirements.lock`, where every package is pinned with its SHA-256 hash (`--require-hashes`), and says clearly when Python is missing or older than 3.11.
- Releases: the notes are the matching `CHANGELOG.md` section, the host tests run before publishing, and the zips carry a build attestation (`gh attestation verify`). [Install](docs/INSTALL.md) explains the SmartScreen warning and how to check a download against `SHA256SUMS`.
- Desk console and dock: a print table (orientation, layer height, supports, infill, walls, screws) in `hardware/README.md`, and the console in the README.
- Bug reports ask for the Windows version and the *Save diagnostics* file; blank issues are off. Dependabot proposes weekly grouped updates for GitHub Actions and the host packages.
- Tray: a host that dies without you pressing Stop starts again by itself (after 5 s, 15 s, 60 s, then every 5 minutes), with one notice per burst instead of one per attempt.
- Host log: three older logs are kept (deck.local.log.1 to .3), both at start and while the host runs. **Help → Recent problems** in the tray lists the last 20 failures from the log, and diagnostics include them.
- HTTP actions: an answer with an error status (4xx or 5xx) now fails the action with its code. The import review names the host each web request goes to.
- Backups: a profiles file the host cannot use is never backed up, so it cannot push good copies out. If profiles.json is broken at start, the newest good backup is restored, the broken file is kept as profiles-unreadable.local.json, and the tray says so.
- Updates: the tray's check says *Update available: <version>* with the first lines of the release notes; the editor's check gets the same excerpt.
- Plugins: the editor asks before a plugin first runs (and again for a new version), listing what it may do and the program it runs; secret settings (tokens, passwords, API keys) are stored encrypted for your Windows account, so profiles.json and backups no longer hold them in plain text (existing ones are encrypted on the next save).
- Control API: each token is limited to 20 calls a second (bursts of 40, then `429`), and every change is logged with the caller's name.
- New actions: *Copy to clipboard* puts a text (with $(...) variables) on the clipboard and can paste it; *Window* minimizes, maximizes, restores or closes the window in front or a named program's, toggles always on top, moves it to the next monitor or brings a program to the front; *Toggle variable* switches a variable between two values on each press. The library has Always on top, Close window and Paste date keys.
- Firmware updates over USB with rollback: the flash now has two 6 MB app slots, *Application only* goes over the panel's own USB connection and the bootloader goes back to the previous firmware if a new one never reaches the host. The first install of this firmware must use *Everything* (the installer says so).
- A hung screen or USB loop now restarts the panel by itself (task watchdog on both).
- The host logs when the panel restarted and why, and shows a notice after a crash, hang or power dip.
- The panel keeps every layout up to 8 KB for use without the PC (was 3,800 bytes), with the previous one as a backup; a layout over 8 KB gets a clear "too big" answer.
- Panel contrast: secondary text is brighter (#8FA0A8) and larger (20 px) for headings' summaries, agent states and projects, fader and reading names; a native test keeps every text colour at WCAG 4.5:1 or better.
- Hold to confirm: a key marked *Hold to confirm* in the editor runs only after a 0.6 s hold while a ring fills on it; lifting the finger or sliding off earlier does nothing (panel firmware and host).
- Panel lock: a new *Lock panel* step (lock, unlock or toggle) makes the panel ignore taps on keys and the rail; the logo becomes a lock badge, and holding it for 2 s unlocks the panel and tells the PC.
- Swipe right on the keys goes back, like Keys on the rail after a shortcut (there are no next or previous pages, so a swipe left does nothing); a swipe never presses the key it starts on.
- About sheet: a long press on the panel's logo shows the firmware version, whether the PC is connected and a brightness slider; the level is saved on the panel and in the settings, so the PC keeps it. Tap outside to close.
- Editor: questions and name prompts open in the editor's own dialog instead of the browser's; deleting a profile or a page no longer asks first and offers Undo instead.
- Editor: a bar at the bottom stays while something blocks you (host stopped, no panel, a save conflict, an unreadable configuration file) and has the button that fixes it (Start host, Reload, Restore a backup).
- Editor: a Getting started card (choose a template, drag an action onto a key, test it) shows while no key is set up, and More → Getting started opens it again.
- Editor: importing a file first shows its profiles, pages and keys and the risky actions it holds, then adds them as new profiles or replaces the configuration; an export says what it left out (calendar address, plugin passwords, web request credentials).
- Editor keyboard: the action tabs, the key-settings tabs and the page chips are one Tab stop each (the arrow keys, Home and End move along them); every dialog gives the focus back to what opened it; every control shows where the focus is; the panel screens are no longer read out on each update.
- Editor: **Alt+arrow** moves the selected key to the next slot (a key there changes places with it), and the key menu has **Move to slot …**; while dragging, the label says what the drop does (move, swap, add as the next step, replace).
- Editor wording: *Test (nothing runs)* everywhere, *Show on panel* instead of *Mirror on panel*, **Program settings** in the app bar, a visible **Keyboard shortcuts** button, and the Redo tooltip names Ctrl+Y and Ctrl+Shift+Z.
- CI: a smoke test opens the editor in a real browser and checks the deck, two dialogs, the focus and axe accessibility rules. `--no-browser` prints the editor's address.
- Docs: new panel and editor images, and a longer demo animation (17 scenes: folders, window and meeting keys, pages that follow the app, the idle clock and the editor). In the editor a long widget description no longer runs past the settings panel.
- Long runs: the panel tells the host which screen shows, so the sound mixer is read every second only on its screen (otherwise every 5 s). Plugin folders are read again only when they change, the AI session history is walked every 10 s instead of 2 s, an unchanged status file is not rewritten, and the host log is kept under 5 MB while the host runs.
- Performance: images reach the panel about 4 times faster, and the panel reads USB in 2 KB blocks instead of locking per byte. Hidden screens, a dark screen and the clock no longer redraw or animate keys. The host stops refreshing keys under a dark screen, skips nvidia-smi when a sensor tool has the GPU, and caches the program list. The editor stops polling in a hidden tab and redraws the rail only when it changes.
- Screen switching: a waiting permission question is never covered by the clock or a dark screen, after a reconnect it pulls the panel to Agents again, and once answered the panel goes back to the screen you had; waking and leaving the clock always show the keys; switching screens on the rail counts as use; a shortcut to the page you are in leaves a folder. Allow and Deny show only for a real question. The editor merges a save made elsewhere (tray brightness) instead of refusing; the panel asks the PC again for icons it lost; *Import without commands* drops step shortcuts left empty.
- A full logic review fixed 51 problems, among them: a slow key could run whatever key was at its place after a page change; slow typing froze every other key; a PowerShell variable could inject code; firmware install could flash the wrong board; the host could be started during a flash; daily triggers ran again after every restart; agent states stuck after a tool was killed; Outlook calendars with quoted time zones were unreadable; dropped actions could land in a Held list; an online icon picked for a rail shortcut went onto a key; a Claude notice showed Allow and Deny that answered nothing; a broken profiles file now says so in the editor.
- Rail fixes: Keys goes back only after a shortcut and keeps your page otherwise; a shortcut is forgotten once you move on your own; a tap on a dimmed panel only wakes it; without the PC a shortcut does nothing instead of flashing; the steps of rail shortcuts are reviewed on import, stripped by *Import without commands* and follow renamed or deleted pages and profiles; long page names no longer push the rail past the panel's line limit.
- Rail shortcuts can run steps like a key (copy them from one of your keys, give the shortcut a name) without leaving the screen, and any icon from the library can be used (panel firmware 0.6.3; an older panel simply leaves such shortcuts out).
- Rail dialog: the preview names every place and shows the free ones, a shortcut shows its profile and page, shortcuts are numbered and can be moved, the icon row is labelled, and a line says what a shortcut does and how Keys brings you back.
- Editor: on a large screen the deck grows with the window (bounded by its height) instead of stopping at a fixed width.
- Editor: the bare ⋯ button is now four named buttons above the deck, **Profile**, **Page**, **Panel** and **More**, each with a short menu where every entry says in one line what it does; a menu opens right under its button, fits the window, and the arrow keys move through it. Clearer names: *Profile from a template*, *Page from a template*, *Clock when idle*, *Key colors*, *Save diagnostics*.
- Rail: after a shortcut, the Keys button on the panel seemed dead (the keys already showed, so nothing changed). A tap on Keys while the keys show now goes back to the page you came from, or to the profile's first page (panel firmware and host).
- Panel (new firmware): a key sinks under the finger and pulses while the PC runs its action; the second line of a wide key, the corner marks, the clock and *NO PC* are larger; the mixer has bigger mute buttons and knobs; without the PC the agents, mixer and status screens show a clear *PC not connected* card; a task that hangs the panel for 5 s restarts it.
- Editor: `/` jumps to the action search, Enter adds the first match and the arrow keys walk the list; a cleared key comes back with the Undo button in the message; the key menu shows its shortcuts, and `?` (or **More → Keyboard shortcuts**) lists them all.
- Tray: the Tessera and panel versions in the menu; **Help** opens the host log, saves diagnostics for a bug report, opens the data folder and checks for updates when you ask; a problem that lasts 30 seconds (a port held by another program, a stopped host) gets a notice; the first start asks whether Tessera should start with Windows.
- README: build it or buy one, with prices; CONTRIBUTING points to first issues. CI runs cppcheck on the firmware.
- New widget *Next meeting*: the meeting that runs now or comes next, read from the iCal address of your Google, Outlook or iCloud calendar (Program settings); repeating, cancelled and moved meetings are followed, and the address is left out of exports.
- New plugins: **Home Assistant** (show and switch lights and sensors, run scenes) and **OBS Studio** (scenes, recording, streaming, mute). Plugin settings named like a secret are left out of exports.

## 0.6.2

- Permission questions: a touch on Allow within 0.8 s of a new question no longer answers it (it was meant for what stood there before); a question too long to show in full offers Deny only (panel firmware); a lane hidden from the agents screen is not asked; a question is never shortened to fit.
- Import review and *Import without commands* also find commands inside a timer's end actions.
- Export works in the editor window (the window cancelled every download).
- Terminal editor: a backup is kept before each save (always before an import or a delete), and a step type it cannot edit no longer crashes it.
- Values of variables are no longer searched for `$(env:NAME)` in HTTP headers and bodies, so a variable cannot pull in a secret.
- A shell action that starts a program with `start` no longer waits 30 seconds and reports a failure.
- Speaker volume, mute and the mixer work on a PC without a microphone.
- Typing text with a delay no longer freezes the other keys while it types.
- Mouse *move to* lands in the right place with more than one monitor.
- A wide music key with a non-ASCII song title reacts to presses again.
- `$(profile_lock)` shows LOCKED instead of the Norwegian LÅST.
- *Test* (dry run) knows *Lock profile* and plugin actions and finds programs on PATH.
- Connect Claude Code keeps your own hook when it shares a group with Tessera's.
- Template keys no longer use arrow characters the panel font cannot draw.
- A damaged image, or a toggle state with a non-text label, gives a clear error instead of stopping the upload or the host.
- Docs: the native build's tools, which commands the panel answers, the weather city search host, flashing steps.
- Editor: Enter saves a dialog (it cancelled); keyboard focus stays where it was after a change; messages show above an open dialog; arrow keys step over a wide key; recorded hotkeys use names the host knows (punctuation, digits, media keys); Ctrl+C copies text in the host log; deck shortcuts no longer fire in other screens and dialogs; a plugin switch no longer flips back; renaming or deleting a page or profile also updates long-press and double-press steps and rail shortcuts; after a save conflict the editor says *Not saved · press Reload*; only a failed save marks the configuration *Not saved*.
- Editor: a deck position is called a *key* everywhere; key colors and quick icons are under *Look*; *Show on device* is gone (*Mirror on panel* does it).
- Firmware install: the dialog says the host started again only when it did, and a stalled esptool is stopped after five minutes.
- Panel (new firmware): long titles end in dots instead of running into the line below; the fader knob stays inside its track; a fader you touched follows the PC again afterwards (also after 25 days of uptime); picture keys appear once the images arrive after a panel restart; the corner marks sit in the corner of a wide key; without the PC the agents and status screens say *PC not connected* and Allow and Deny do nothing; a full settings partition is reset instead of disabling stored settings.
- Host: the reason a host could not start reaches the editor; start with Windows and the file picker work with æ, ø or å in the path; the tray shows why the panel is not connected and follows brightness and profile changes; the editor's token file is private to your account; a damaged firmware zip no longer breaks the firmware list, which is sorted by version; a timer restarted without seconds keeps its notice and actions; a key that presses a slow key runs on the slow lane; a dropped press flashes red at once; the log gets one line per page instead of one per refresh; validation errors name the page and the key; widget titles fit a two-slot key.
- Docs: actions, bind values, automatic triggers, Connect Claude Code, gauges and *NO PC* described as they are.
- Panel (new firmware): a key's text size, position (top, middle, bottom or hidden) and bold from the editor now show on the panel; with the title on top the icon moves down.
- The host sends an image again when the panel has dropped it from its 8 MiB cache, instead of leaving the key without its picture until the cable is reconnected.
- `Tessera.cmd --sensors` and `--sensors-off` also work when Tessera was unpacked from a downloaded zip (Tessera's own script runs with `-ExecutionPolicy Bypass`).
- Smaller firmware: the unused ArduinoJson library, a 14 px font, old compatibility headers and the calendar code of an earlier project are gone. `AD_TIME` answers `OK` or `INVALID`.
- Tests no longer write icons or state into `host/`, the host's dependencies have upper version bounds, the CI tools are pinned, a release runs the native UI tests first, and the README panel images show one time.

## 0.6.1

- One editor window: a double click on the tray icon, or a click while the editor was still starting, opened two or three. A second start now waits for the first and brings its window forward.
- Tray: the menu follows the status (it kept the old status line, ticks and greyed-out items), a second click on Start or Restart no longer starts a second host, and the icon shows the real state at once.
- README: a short animated tour of the panel, drawn by the firmware UI (`tools/make_demo_gif.py`); a contributing guide and issue templates.

## 0.6.0

- New panel layout (firmware protocol 4): a rail with four screens. The keys keep their six-by-three deck; the agents, mixer and status screens are new.
- Agents: one lane per AI tool with its state and last message. Allow and Deny on the panel answer Claude Code's permission questions through a hook (`deckctl hooks claude-permission`); anything unclear falls back to Claude's own dialog.
- Mixer: drag faders for the speakers, up to three programs and the microphone; mute with a tap.
- Status: eight readings with bars, and the first one over its limit is named.
- Agents screen works without any setup: working and idle, the project and the last tool come from the session files Claude Code and Codex already write. **Connect Claude Code** (⋯ menu) adds the hooks for "waiting for you" and for answering permission questions on the panel; it keeps your other hooks and makes a backup.
- A Windows notice when an agent starts waiting for you or finishes more than a minute of work; the tray says who is waiting.
- Widgets: ready-made wide keys (2 or 3 slots) for the clock, the date, the processor, the graphics card, memory, network speed, volume and the AI agents. Drag one from **Widgets** in the action list, or pick it under **Shows** on a wide key. No new firmware is needed.
- Editor tidied: the profile is the title, the page tabs sit above a larger deck, and a key's settings are three tabs (Look, Actions, Gauge) instead of a stack of folded sections.
- Editor: the action list is four tabs (Basics, Widgets, Ready-made, Apps) instead of eighteen groups in one column; a search still looks in all of them.
- A host started outside the editor (a terminal, a script) is recognised from its runtime file, so the editor no longer says "The host has stopped" while one holds the USB port.
- A key that opens a running program now brings its window to the front even when Windows refuses a background program the focus; before, the taskbar button only flashed.
- Rail dialog: the switches and the up/down buttons work (every one of them was disabled).
- New screenshots in the README and the feature list: widgets, the agents and mixer screens and the tidied editor.
- Editor: everything is drawn 15% smaller.
- Editor: the key card has room for everything (the preview beside the title and icon, every other setting full width), and the key's size is picked with three buttons: Normal, Wide, Extra wide.
- Editor: moving, pasting or duplicating a wide key checks that it fits on its row without covering another key; otherwise it is refused (move) or pasted as a normal key. Heights follow the editor's zoom, so the rail's + and the bottom of every column stay in view; on wide windows the key's settings sit in their own column.
- The editor's status line shows the panel's firmware version and says when an update is available.
- Editor: a key's steps are listed in order ("1 Open program → 2 Hotkey"), hold and double-press steps show under it, the profile rules are explained in plain words, and a meter shows how much of the panel's offline memory the page uses.
- Fixed: a changed VERSION did not reach the firmware build, so a rebuilt panel could keep reporting the old version.
- Editor: a rail on the left with the panel's four screens. Keys is the editor you know; Agents, Mixer and Status show what the panel shows right now and let you choose what goes on them, with the Claude Code connection on the Agents screen.
- Wide keys: a key can cover 2 or 3 slots (Width in the key's settings) and show the music that plays (title, artist, progress bar) or a timer (time left in a ring). Needs the new firmware.
- The editor now looks like the panel: the same dark colors, flat rounded cards, mint/cyan/purple accents and a green accent line, instead of the grey Stream Deck look.
- You choose the panel's rail: **Rail …** (⋯ menu) turns Agents, Mixer and Status on or off and adds up to three shortcuts to a page of any profile. The editor's rail follows the same choice. Needs the new firmware (at most seven buttons).
- Editor layout tidied: the title, the deck, the pages, the sync bar and the key's settings share one column and scroll together; the three settings sections stack instead of floating; the action library uses one icon family and no mismatched glyphs.
- The rail dialog is rebuilt: a live preview of the rail beside the screens (switch on or off, move up or down) and the shortcuts (page from a grouped list, icon picker), with a count of the seven buttons the panel fits. The editor's rail follows the chosen order.
- Fixed: Cancel in a dialog with a required field (new page, new profile, page settings) did nothing, because the empty field blocked it.
- Fixed: the editor window could end up under the Windows taskbar; it now fills the screen minus the taskbar.
- Editor: **Panel screens** chooses the agents, mixer programs and readings.
- Editor: **Page templates** (⋯ menu) adds a ready-made page (Meetings, Coding, Media, Browser or empty) after showing how it will look.

## 0.5.2

- Fixed: a key that brings a running program to the front (for example Chrome) shrank a maximized window. Only a minimized window is restored now.
- The panel clock follows the PC in every time zone; it no longer applies Central European daylight-saving time on its own.
- The control API token file can only be read by the Windows account that runs Tessera.
- Triggers, timers, plugins and configuration reloads keep running while no panel is connected.
- Fixed: the host could stop when the USB cable dropped out at the moment the panel was dimmed (for example after sleep).
- Fixed: saving the configuration ran today's daily triggers a second time.
- Fixed: a trigger with a slow command, HTTP call or delay made the keys unresponsive until it finished. It now runs beside the keys; a trigger that is still running is skipped.
- Fixed: a firmware installation that hit an unexpected error stayed "running" forever.
- Fixed: stopping a plugin left the programs it had started running.
- The host log and plugin logs are rotated instead of growing without limit.

## 0.5.1

- Easier first start: `Tessera.cmd` installs Python with winget if it is missing and adds a Desktop shortcut, and the release zip includes the panel firmware.
- *Download firmware* is offered even when you already have the latest version, so a new panel can get it.
- The editor says when no panel answers.

## 0.5.0

- Fixed: in large windows the right-click menu of a key and the drag label appeared far from the pointer, and dialogs could reach past the screen edge. Only the main view scales with the window now.
- Fixed: on pages with live gauges a press or drag could lose its key when the editor refreshed the keys at that moment. The editor waits for the press to finish and leaves unchanged keys alone.
- Fixed: the *Lock profile* key only turned orange when the lock was on its long press.
- Fixed: *Settings* was hidden in windows narrower than 900 px, and the editor's hints still pointed at the old layout. A draft that cannot be saved now names the key.
- Fixed: a gauge without a unit (such as `301` or `LIVE`) sat slightly off centre on the panel.
- New action *Lock profile* (`profile_lock`): keeps the current profile while another program is in front; `$(profile_lock)` shows the state and the key turns orange while locked.
- New FPS gauge (`fps`) from HWiNFO's PresentMon sensor.
- Gauges say what they measure: `GHz`, `MHz`, `GB` and `rpm`. The size of a gauge's number now depends on the number alone, not on its unit.
- `$(pc:track)` shows *No music* when nothing is playing, so the music key is no longer blank.
- First-start fix: the editor creates `profiles.json` itself if it opens before the host. *Check for updates* says when nothing is published instead of blaming the network.
- `tools/render_screens.py` draws every page of every profile with the real panel UI into `build/screens`, without touching the panel.
- Faster status page: the host keeps one connection to Libre Hardware Monitor and lists the child processes of the window in front at most every 3 seconds, instead of both every second.

- Fixed: the VRAM, GPU load and CPU clock gauges blinked to "--" for one second every 15 seconds while the Windows counters were listed again; they now keep their last values meanwhile.
- GPU temperature, power, fan speed and clock now show without administrator rights or extra software: AMD cards through the driver's ADL library (checked on an RX 6950 XT), NVIDIA through `nvidia-smi`. Libre Hardware Monitor and HWiNFO still win when they run.
- `Tessera.cmd --sensors` registers a scheduled task that starts Libre Hardware Monitor at every sign-in with administrator rights (one Windows prompt), so the CPU temperature and power are always there; `--sensors-off` removes it. The editor's connection tooltip says what is missing when the CPU sensors are not available.

- Panel and editor: keys with a long-press action get a small ring in the top-right corner, keys with a double-press get two dots (layout field `double`, firmware `has_double`). The firmware builds with ESP-IDF 6.1 (1.93 MB) and the native LVGL test passes and renders the new marks; not yet flashed to a panel.

- New **Chrome** screen (profile): shown automatically when Chrome is in front. Main page: tabs, address bar, back/forward, refresh, find, bookmark, incognito, history, downloads and play/pause; a *Developer* folder with DevTools, inspect, console, view source, zoom, full screen, print, task manager and clear data. Home is pinned in slot 18. The *Browser* profile template now has the same keys (Chrome, Edge, Firefox) with proper icons.
- Editor: no sideways scrolling in windows narrower than 1280 px (the columns shrink and the key inspector moves under the deck below 1000 px); no more "undefined / undefined" when the panel has not reported its page yet.

- New action *Switch screen* (`screen`): show the clock, the keys, or switch between them, from any key. It works even when the idle clock is off; a touch on the clock returns to the keys.
- Quiet hours (`display.night`, in *Program settings*): between two times the panel uses a lower brightness, also across midnight, and returns to normal afterwards.

- Switching profiles by the program in front: Windows surfaces that only take focus for a moment (search, Start, notifications, Alt+Tab, the lock screen, taskbar) and Tessera's own windows no longer end or start an automatic switch; when the program loses focus you return to the page and folder you left, not the first page; Store (UWP) apps such as Calculator are recognised by their real program instead of `applicationframehost.exe`.

- USB reconnects wait 2, 5, then 10 seconds and log an outage once instead of every attempt; the panel layout is sent a second time if the first is not acknowledged; the heartbeat thread also ends quietly when the port disappears.
- The editor shows *too big to keep offline* when the page layout exceeds what the panel stores for use without the PC (3,800 bytes).
- The editor edits the full action list for normal, long and double press (tabs *Pressed / Held / Double-press*), replacing the hotkey-only fields.
- CI: ruff `B` rules, Python 3.12 and 3.14, host coverage gate (73 %). Terminal form said "Ja" instead of "Yes".
- Double press: `double_actions` on a key (editor field *Double-press hotkey*), checked, previewed and listed in import review like long press.
- HTTP actions only accept `http://` and `https://`, when the profile is saved and again after variables are filled in; the address may use `$(env:NAME)`.
- Variable substitution is a single pass: a value that looks like `$(other)` is no longer expanded a second time.
- Fixed: the Desktop shortcut (setup) and shortcut targets in the editor failed because PowerShell ignores `$args` with `-Command`.
- Panel: a layout that is too large for flash, or a failed flash write, is logged and retried instead of being marked as saved.

Firmware protocol 3, configuration version 2. Existing profiles load unchanged and are stamped with the new
version on the next save; the old file is kept in `host/backups`.

### Reliability and security

- The panel firmware no longer contains Wi-Fi, provisioning, SNTP or the ESP-Hosted stack; USB is the only
  transport (binary 2.43 MB → 1.92 MB). Not yet run on a physical panel.
- Verified device identity: the host asks `get_info` and checks the board id and protocol before it configures a
  port, tries other Espressif USB devices only after the remembered one, and discards key presses that arrive
  before the handshake.
- The action queue is bounded and reports a full queue (`503`) instead of dropping silently; multi-job requests
  are all-or-nothing; stale presses and presses queued before a reconnect are never replayed.
- Shell commands, HTTP requests and delays run on a bounded slow lane, so a long command no longer blocks other
  keys or the host; a button that is still running ignores a second press; commands are killed as a process
  tree on timeout or shutdown.
- Imports show every command, web request, program launch and automatic rule for approval and can be imported
  without them; variable values with shell metacharacters are refused in shell commands and percent-encoded in
  URLs; HTTP credentials can come from `$(env:NAME)` and exports replace them with such references.
- The firmware image cache counts the incoming image, evicts the least recently used images and refuses what
  cannot fit (`AD_IMG_END FULL`).
- Dependency audit in CI found eight known vulnerabilities in Pillow 12.3 (which decodes user images); Tessera now requires Pillow 13.
- Fixed: the diagnostics redaction leaked user names containing a space and `Bearer` tokens (found by its test).

### Product

- Counters and timers (saved, with labels, rings, bindings, tray notifications and end actions).
- Keys follow Windows state: microphone, speakers, media; `audio` action; `$(pc:…)` labels.
- Long-press actions; return to the previous profile after an automatic switch.
- Per-key background, label and outline colors; ambient clock screen with optional weather; the panel keeps its
  last layout without the PC.
- Editor: test (dry run), image cropper, online icon search, backups and restore, plugins, ambient settings,
  panel firmware installer with update check, diagnostics export.
- Per-app and device volume (`audio` targets `app:NAME.exe`, volume set/up/down), typing speed for `text`, a choice between matching cities, and a live *Host log* view.
- Key theme (default look for all keys, five presets), mouse actions (click, double, scroll, move).
- Plugins with scoped tokens and an event stream; AI tool adapters for Claude Code hooks and Codex notify.
- Portable defaults: programs are found when installed elsewhere, GPU sensors prefer the discrete card on any
  vendor.
- `Tessera.cmd --setup`, `--uninstall [--purge]`, `--diagnostics`; dependencies are synced only when
  `requirements.txt` changes.
- CI for the Windows host, firmware build and native LVGL tests; tag-driven release workflow.
