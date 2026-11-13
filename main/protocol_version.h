#pragma once
/* Version of the USB line protocol the firmware speaks; reported by get_info and checked by the host.
 * 1 = original firmware, 2 = adds the protocol field and long-press (hold) events,
 * 3 = adds per-key colors (bg, text_color, border), the ambient clock screen and the offline layout,
 * 4 = adds the cockpit screens. Later additions are capability fields in get_info, not new versions:
 * "reset" (why the panel last started), "ota":1 (AD_OTA_* over-USB update) and "layoutSaved". */
#define TESSERA_PROTOCOL 4
