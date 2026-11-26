"""Write the starting sdkconfig for the GUITION build for v3.x chips.

It is the sdkconfig of the v1.x build, which runs on the panel, without the options that depend on the chip
revision. idf.py takes those from boards/tessera-p4-v3.defaults, so the two builds differ only in what the
revision needs. Built from sdkconfig.defaults alone, about 60 other options (watchdog, LVGL, FreeRTOS) came out
different from the tested build.

    cd esp && python3 ../tools/v3_sdkconfig.py sdkconfig build/tessera-p4-v3/sdkconfig
"""
import re
import sys
from pathlib import Path

# The revision choice, what follows from it, and the options boards/tessera-p4-v3.defaults sets.
DROP = re.compile(r'^(# )?CONFIG_(ESP32P4_SELECTS_REV_LESS_V3|ESP32P4_REV_M(IN|AX)|ESP_REV_M(IN|AX)_FULL'
                  r'|ESP_DEFAULT_CPU_FREQ_MHZ|BOOTLOADER_CPU_CLK_FREQ_MHZ|BOOTLOADER_LOG_LEVEL|LOG_BOOTLOADER_LEVEL'
                  r'|TESSERA_BOARD_ID)')


def v3_sdkconfig(text):
    return ''.join(line for line in text.splitlines(keepends=True) if not DROP.match(line))


def main(source, target):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(v3_sdkconfig(Path(source).read_text(encoding='utf-8')), encoding='utf-8', newline='\n')


if __name__ == '__main__':
    main(*sys.argv[1:3])
