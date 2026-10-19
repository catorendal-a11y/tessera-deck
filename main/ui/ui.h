#pragma once

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

void ui_init(void);
/* Compatibility entry point; the standalone product has one full-screen Deck. */
void ui_show_destination(int unused);

/* Read-only USB diagnostics: writes a JSON-ish summary of the current
 * screen and its main labels. Caller must hold the LVGL display lock.
 * Returns 0 on success, negative on truncation/being busy. */
int ui_debug_visible_text(char *out, size_t out_size);

#ifdef __cplusplus
}
#endif
