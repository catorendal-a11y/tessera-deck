# Elecrow CrowPanel Advance 7.0 (ESP32-P4)

[Back to the README](../README.md)

The firmware also builds for the Elecrow CrowPanel Advance 7.0 (ESP32-P4, 1024 x 600, EK79007 screen, GT911 touch). It works on the contributor's board: the colors look right, touch works, and most of the hotkeys and actions they tried work. The panel reports the board id `tessera-p4-crowpanel7`, 1024 x 600, protocol 4; the GUITION build is unchanged and keeps `tessera-p4`. Pins, panel timing and power come from Elecrow's V1.2 example code. CI builds it, and the releases have its package from 1.2.0 on.

To build it yourself, from the repository root, with ESP-IDF 6.1:

```
idf.py -B build/crowpanel -DSDKCONFIG=build/crowpanel/sdkconfig -DSDKCONFIG_DEFAULTS="sdkconfig.defaults;boards/crowpanel-p4-7.defaults" build
python tools/package_firmware.py build/crowpanel dist --board tessera-p4-crowpanel7
```

`idf.py -B build/crowpanel -p COM5 flash` writes the build straight to the board (use your board's port). The package lands in `dist/` as `tessera-firmware-tessera-p4-crowpanel7-<version>.zip`; installing it from the editor's firmware dialog has not been tried on this board yet. A board that still runs Elecrow's own firmware does not answer the host, so the dialog offers a full install with Install anyway and leaves the package for you to choose. Pick the one that says `for tessera-p4-crowpanel7`: both boards use the same chip, so nothing else stops the GUITION package from being written to this board.

Differences from the GUITION board: backlight on GPIO31 (30 kHz), touch on I2C SDA 45 / SCL 46 with RST 40 and INT 42, LDO4 (3.3 V) switched on next to LDO3, DIO flash and PSRAM at 80 MHz as in Elecrow's examples (faster speeds have not been tried), and the host link on UART0 (GPIO37/38, 921600 baud) through the board's USB-UART bridge, not native USB. The MIPI DSI lanes run at 750 Mbit/s, as on the GUITION board; Elecrow's code uses 900. The code is behind `CONFIG_TESSERA_BOARD_P4_CROWPANEL7` in `components/espressif__esp32_p4_function_ev_board`.
