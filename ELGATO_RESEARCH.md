# Elgato Stream Deck: research for Tessera

Researched 18-19 October 2026. Official product, help and SDK pages were used for
Elgato features. The status of Tessera was checked against the local source
code. This is a basis for comparison, not a claim of full compatibility.

## Update 26 October 2026: Stream Deck 7.x

Elgato's release notes (7.0, 12 August 2025, up to 7.4.x) add **Key Logic** (up to three actions on one key:
press, double press, press and hold), a **Virtual Stream Deck** (on-screen keys), hotkey presets, a running-app
indicator on *Open Application* and a weather plugin. Earlier releases added *Multi Action Switch* and
*Random Action* (4.4). Tessera now covers press, double press and hold, toggle states, multi-actions and weather
on the ambient screen. Still open: random action, an indicator that an opened program is running, hotkey presets
in the editor and running multi-action steps at the same time. Sources:
[7.0 release notes](https://help.elgato.com/hc/en-us/articles/38011940576273-Elgato-Stream-Deck-7-0-Release-Notes),
[Key Logic](https://www.elgato.com/us/de/explorer/products/stream-deck/key-logic-stream-deck/),
[4.4 release notes](https://help.elgato.com/hc/en-us/articles/5162934218637-Elgato-Stream-Deck-4-4-Release-Notes).

## Smart Profiles and switching programs (26 October 2026)

Elgato's [Smart Profiles](https://help.elgato.com/hc/en-us/articles/360053419071) link one profile to one program
and switch when that program is the focused window. Limits found in Elgato's guide and user threads: only one
program per profile, no window-title rule, no UWP/Store apps, no built-in way back to the previous profile (users
build macros for it), and the feature is off while the Stream Deck window is open
([forum thread](https://forum.keyboardmaestro.com/t/stream-deck-return-to-previous-profile/40931)).

Tessera already matched by process, child process or window title and returned to the previous profile. This
round added: transient Windows surfaces and Tessera's own windows are ignored, the page and folder you left are
restored, and Store apps are recognised through the window behind `ApplicationFrameHost`.

## What people actually use

Elgato's default profile includes screenshot, volume and app launching. The
Marketplace also highlights audio mixing, window placement, meetings, virtual
desktops, system status and app-specific profiles. Elgato's official ChatGPT &
Codex plugin prioritizes activity, new chat, prompt/steering, stop, model,
reasoning, usage and panel switching.

User setups repeat the same pattern: media control, opening apps and folders,
screenshots, clipboard history, virtual desktops, window placement, meeting
buttons, fixed home buttons and multi-actions that start a work session.
Developers especially use app-specific profiles, project commands, ready-made
text blocks and AI status.

Sources:

* [Elgato Stream Deck 6.6 – default profiles and pinned actions](https://help.elgato.com/hc/en-us/articles/26005306818701-Elgato-Stream-Deck-6-6-Release-Notes)
* [Elgato Marketplace – productivity and developer tools](https://marketplace.elgato.com/stream-deck)
* [Elgato's ChatGPT & Codex plugin](https://marketplace.elgato.com/product/chatgpt-codex-fb6a7052-2b1a-4500-ba2a-13996edf0b47)
* [Elgato Multi Actions](https://help.elgato.com/hc/en-us/articles/360027960912-Elgato-Stream-Deck-Multi-Actions)
* [Developer profiles for Stream Deck](https://github.com/mikeckennedy/streamdeck-developer-profiles)
* [Users' productivity setups](https://www.reddit.com/r/elgato/comments/1hhu8oj/are_stream_decks_good_for_work_productivity/)
* [Users' most useful single buttons](https://www.reddit.com/r/elgato/comments/1wh69jh/what_is_the_most_useful_stream_deck_button_you/)

This was turned into a new **Daily control** template, 119 ready-made actions and a
full 18-button main layout. Home is fixed in the bottom-right corner on all pages.
The main page is a program launcher based on installed and pinned apps: Chrome,
ChatGPT, ZCode, Claude, VS Code, GitHub Desktop, Terminal, Explorer, Discord,
Obsidian, LM Studio, Steam and Xbox. Screenshot, system, more apps and audio sit in
the last four slots.

## Deep dive: useful buttons in real work setups

A new review on 19 October included IT, QA and developer setups. The clearest
pattern is that users get the most value from actions that remove several manual
steps: moving a window to another monitor, starting terminal commands, opening the
right project tool, controlling meetings and running multi-actions. App-specific
profiles keep these features available without filling the global front page.

* IT and QA users describe terminal commands, VNC, ping, window moving and profiles
  that follow the active app. [IT thread with concrete workflows](https://www.reddit.com/r/elgato/comments/1vgbu8v/stream_deck_usage_tips_for_someone_working_in_it/)
* Developer setups keep returning to formatting, lint, Git pull, GitHub Desktop,
  terminals and their own global/contextual pages. [Developer and QA profiles](https://www.reddit.com/r/streamdeckprofiles/comments/y1xger)
* Microsoft documents direct Windows shortcuts for moving active windows between
  monitors, virtual desktops, clipboard history and snap layouts.
  [Windows shortcuts](https://support.microsoft.com/en-au/windows/keyboard-shortcuts-in-windows-dcc61a57-8ff0-cffe-9796-cb9706c75eec)
* PowerToys adds OCR, color picker, always on top, workspaces and advanced paste.
  [PowerToys](https://learn.microsoft.com/en-us/windows/powertoys/),
  [Advanced Paste](https://learn.microsoft.com/windows/powertoys/advanced-paste)
* Teams and Zoom have documented shortcuts for microphone, camera, sharing, hand,
  chat and leaving. [Teams shortcuts](https://support.microsoft.com/en-us/accessibility/teams/keyboard-shortcuts-for-microsoft-teams),
  [Zoom shortcuts](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0067050)
* GitHub Desktop has documented Windows shortcuts for changes, history, branches,
  pull, push, terminal, editor and pull requests.
  [GitHub Desktop shortcuts](https://docs.github.com/en/desktop/overview/github-desktop-keyboard-shortcuts?platform=windows)

These are now included as their own action groups and complete templates for
PowerToys and GitHub Desktop. The meeting template is extended to all 18 buttons.
The default front page is still simple; the new actions are chosen from the
library or enabled as their own profiles.

## The workflow that should be the reference

Elgato's quick-start guide describes actions in the right panel, the button grid on
the left and configuration of the selected button. Folders are created by dragging
Create Folder to a button; custom actions are then placed in the folder.
Right-click gives, among other things, copy, delete and move.
[Official quick-start guide](https://www.elgato.com/us/en/explorer/products/stream-deck/elgato-stream-deck-quick-start-guide/).

Tessera has the action list on the left and properties on the right. Drag and
drop exists, but this is its own layout. It is not an exact reproduction of
Elgato's editor. Putting a new action on an occupied button automatically adds a
step in the current implementation.

## Features and actual differences

| Area | Elgato | Tessera now |
|---|---|---|
| Visual button configuration | Drag actions to buttons; edit the selected action | Exists; mouse/touch, move/swap, choice of icon/color/name |
| Custom icons | Images from file, icon library and animated formats | 1,895 Lucide icons, real app icons and your own PNG, JPEG, GIF and WebP files |
| Text on buttons | Font settings and top/middle/bottom placement | Size, placement and bold; the host protocol limits the label to 24 UTF-8 bytes |
| Profiles | Separate setups with Smart Profiles by active program | Exists; rules based on process name, manual entry in the editor |
| Folders/pages | Its own folder action and pages; pinned actions can follow navigation | Folders with a folder stack, back button and pinned buttons |
| Multi-actions | Own Multi Action configuration with steps and delays | Sequential steps and delay exist; simplified editor |
| Toggle buttons | Hotkey Switch and Multi Action Switch | Buttons with 2-8 states |
| Dynamic buttons | The SDK can update icon, title and state from the app | Label variables and short success/failure color; no general app-status binding |
| Press/release | The SDK has separate key-down/key-up events | The Deck action triggers on click; a general hold/release stream is missing |
| App integrations | Marketplace plugins for OBS, Discord and more | Hotkeys, open, text, shell and HTTP; no equivalent plugin host |
| Sharing | Stream Deck profiles and sharing of actions | Its own JSON format; no .streamDeckProfile import |
| Program lifecycle | Established desktop app | Local Windows program with WebView2, Python host and terminal program |

Sources for the features above:

* [Icons and supported image formats](https://www.elgato.com/us/en/explorer/products/stream-deck/customize-stream-deck-with-icons-and-icon-packs/):
  own file, icon library and Key Creator. The general icon guide states
  144×144; the model's quick-start guide states 72×72. This should not be treated
  as one universal physical pixel size for all models.
* [Titles and font settings](https://help.elgato.com/hc/en-us/articles/360027958532-Elgato-Stream-Deck-Custom-Titles-for-Actions).
* [Smart Profiles](https://www.elgato.com/uk/en/explorer/products/stream-deck/smart-profiles-stream-deck/):
  the profile switches by the program in the foreground.
* [Multi Actions](https://help.elgato.com/hc/en-us/articles/360027960912-Elgato-Stream-Deck-Multi-Actions):
  created from the action list/right-click, ordered steps and delays.
* [Switching between hotkeys](https://www.elgato.com/eu/hu/explorer/products/stream-deck/how-to-set-up-stream-deck-hotkeys/)
  and [Multi Action Switch in the official release notes](https://help.elgato.com/hc/de/articles/360028242631-Elgato-Stream-Deck-Software-Release-Notes).
* [Pinned Actions](https://www.elgato.com/us/en/explorer/products/stream-deck/pinned-actions-stream-deck/):
  the same slot across pages and folders within one profile.
* [SDK: Keys](https://docs.elgato.com/streamdeck/sdk/guides/keys/):
  events, dynamic images/titles and states.
* [Marketplace](https://marketplace.elgato.com/): the plugin, profile and icon ecosystem.

## Can we use the original program directly?

The official plugin SDK is for extensions that run under the Stream Deck app.
Elgato describes that the app owns the communication with the hardware. There is
therefore no documentation that an ESP32-P4 with our existing serial protocol can
be registered as an original Stream Deck by installing an ordinary plugin.
[Plugin environment](https://docs.elgato.com/streamdeck/sdk/introduction/plugin-environment/).

Elgato's published [HID documentation](https://docs.elgato.com/streamdeck/hid/intro/)
describes control of Stream Deck hardware. [Stream Deck Module](https://www.elgato.com/us/en/p/stream-deck-module-6-keys)
is a physical Elgato module for embedding in your own products. None of these
sources directly confirms support for the existing ESP32-P4 solution.
Emulating a device would be a separate development and compatibility project, not
a verified shortcut. No USB identities or firmware were changed during this
research.

## An existing alternative worth trying before a custom plugin host

[OpenDeck](https://github.com/nekename/OpenDeck/blob/main/README.md) is a desktop
app for Windows, macOS and Linux. The project states support for many plugins made
for the Stream Deck SDK. Official hardware support is Elgato, while other vendors
may be supported by device plugins.

My assessment: OpenDeck is a concrete candidate for a limited compatibility test
with a dedicated P4 bridge. It is not confirmed that our device works. Such a
bridge must transfer button images and events through the existing USB owner.
Plugin support must be tested per actual plugin; "many" does not mean "all".

## Chosen direction

The project is now a pure Tessera. The Elgato-like workflow is built into the
local PC program with drag and drop, own images, 1,895 icons, real app icons,
multi-actions, folders, toggle buttons, profiles and confirmed USB status. A
possible compatibility bridge for third-party plugins is still separate, future
work and is not needed for ordinary use.
