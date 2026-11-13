#pragma once
/* Version of the USB line protocol the firmware speaks; reported by get_info and checked by the host.
 * 1 = original firmware, 2 = adds the protocol field and long-press (hold) events,
 * 3 = adds per-key colors (bg, text_color, border), the ambient clock screen and the offline layout,
 * 4 = adds the cockpit screens,
 * 5 = adds Wi-Fi (AD_WIFI_SET, AD_WIFI_CLEAR, AD_WIFI_STATUS, {"type":"wifi"}) and the "wifi" field in get_info.
 * Later additions are capability fields in get_info, not new versions:
 * "reset" (why the panel last started), "ota":1 (AD_OTA_* over-USB update) and "layoutSaved";
 * stages B and C of docs/design/esphome.md add "api":1, "ha":1 and "cpOta":1 the same way. */
#define TESSERA_PROTOCOL 5
