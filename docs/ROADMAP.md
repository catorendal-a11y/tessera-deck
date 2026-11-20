# Roadmap

[Back to the README](../README.md)

Not built yet, in order of value. Anything shipped is in the [changelog](../CHANGELOG.md).

1. **Finish the hardware checks.** Swipe back has not been tried on a panel. The time from a finger on the glass to the pressed look, touch accuracy over many taps and memory use over days have no numbers yet. [VERIFICATION.md](../VERIFICATION.md) has the list.
2. **Counters and timers on the panel.** They live in the host on the PC today, so with the PC off they do not tick or change.
3. **Press and release actions**, for example push-to-talk. Today a long press runs a second action.
4. **More widgets.** There are nine (clock, date, processor, graphics card, memory, network, volume, AI agents, next meeting). Weather on a key and smart lights are not built. Keys taller than one row are not built either.
5. **Import of Stream Deck and OpenDeck profiles**, and OpenAction/OpenDeck plugin compatibility. Neither is built, so neither is claimed.
6. **A signed Windows installer.** Releases are not signed, so SmartScreen warns; [Install](INSTALL.md) explains how to check a download.
7. **Wayland beyond KDE Plasma and GNOME.** Plasma works, and GNOME has a Shell extension for the window in front and window actions. On sway and Hyprland keys and typing work, but the window in front and window actions have no reader yet. [Tessera on Linux](LINUX.md#wayland) says where it goes.
8. **Home Assistant over Wi-Fi in a release.** It is a beta on the `esphome-beta` branch. The [README](../README.md#home-assistant-beta) says what it does and how to try it.
9. **The panel talks to the PC over Wi-Fi** as an option beside USB ([#18](https://github.com/catorendal-a11y/tessera-deck/issues/18)). It builds on the Wi-Fi of the `esphome-beta` branch, so that comes first. Pairing is approved on the PC, the link is encrypted, and nothing on the network can send commands without it.
