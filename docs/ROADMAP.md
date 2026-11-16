# Roadmap

[Back to the README](../README.md)

Not built yet, in order of value. Anything shipped is in the [changelog](../CHANGELOG.md).

1. **Finish the hardware checks.** Several things have not been tried on a panel yet, such as hold to confirm, the panel lock, swipe back, widgets and faders on the glass and a full install on a blank board. The offline layout, the watchdog and the rollback have been tried on a panel. [VERIFICATION.md](../VERIFICATION.md) has the list.
2. **Counters and timers on the panel.** They live in the Windows host today, so with the PC off they do not tick or change.
3. **Press and release actions**, for example push-to-talk. Today a long press runs a second action.
4. **More widgets.** There are nine (clock, date, processor, graphics card, memory, network, volume, AI agents, next meeting). Weather on a key and smart lights are not built. Keys taller than one row are not built either.
5. **Import of Stream Deck and OpenDeck profiles**, and OpenAction/OpenDeck plugin compatibility. Neither is built, so neither is claimed.
6. **A signed Windows installer.** Releases are not signed, so SmartScreen warns; [Install](INSTALL.md) explains how to check a download.
