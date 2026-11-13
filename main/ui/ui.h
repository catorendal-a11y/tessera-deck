#pragma once

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

void ui_init(void);
/* The firmware version the about sheet shows; call before ui_init. */
void ui_set_firmware_version(const char *version);
/* Compatibility entry point; the standalone product has one full-screen Deck. */
/* Shows one of the four screens: 0 keys, 1 agents, 2 mixer, 3 status. */
void ui_show_view(int index);

/* Read-only USB diagnostics: writes a JSON-ish summary of the current
 * screen and its main labels. Caller must hold the LVGL display lock.
 * Returns 0 on success, negative on truncation/being busy. */
int ui_debug_visible_text(char *out, size_t out_size);

#ifdef __cplusplus
}
#endif
