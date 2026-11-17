# Elecrow CrowPanel Advance 7.0 (ESP32-P4)

[Back to the README](../README.md)

The firmware also builds for the Elecrow CrowPanel Advance 7.0 (ESP32-P4, 1024 x 600, EK79007 screen, GT911 touch). It has **not been run on the board yet**: pins, panel timing and power come from Elecrow's V1.2 example code, and the build is only compile-checked.

From the repository root, with ESP-IDF 6.1:

```
idf.py -B build/crowpanel -DSDKCONFIG=build/crowpanel/sdkconfig -DSDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.esp32p4;boards/crowpanel-p4-7.defaults" build
python tools/package_firmware.py build/crowpanel dist --board tessera-p4-crowpanel7
```

The panel reports the board id `tessera-p4-crowpanel7`; the GUITION build is unchanged and keeps `tessera-p4`.

Differences from the GUITION board: backlight on GPIO31 (30 kHz), touch on I2C SDA 45 / SCL 46 with RST 40 and INT 42, LDO4 (3.3 V) switched on next to LDO3, DIO flash and PSRAM at 80 MHz as in Elecrow's examples, and the host link on UART0 (GPIO37/38, 921600 baud) through the board's USB-UART bridge, not native USB. The code is behind `CONFIG_TESSERA_BOARD_P4_CROWPANEL7` in `components/espressif__esp32_p4_function_ev_board`.

To check on hardware: colour byte order, touch orientation, the host link and the memory speeds.
