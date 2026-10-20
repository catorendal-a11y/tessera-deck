#pragma once
/* Version of the USB line protocol the firmware speaks; reported by get_info and checked by the host.
 * 1 = original firmware, 2 = adds the protocol field and long-press (hold) events,
 * 3 = adds per-key colors (bg, text_color, border), the ambient clock screen and the offline layout. */
#define TESSERA_PROTOCOL 3
