#pragma once
/* Key presses for the API: reads deck_model events with its own cursor (the USB console keeps its own, and is
 * not changed) and turns them into "press", "hold" or "double". docs/design/esphome.md, B.7. Pure C. */
#include <stdbool.h>
#include <stdint.h>

#include "deck_model.h"

#ifdef __cplusplus
extern "C" {
#endif

#define PRESS_DOUBLE_MS 350

typedef struct {
    int slot;         /* the key's id, 1..18 */
    const char *type; /* "press", "hold" or "double" */
    uint32_t ha_version; /* the HA steps the press belongs to (deck_event_t.ha_version of its first tap) */
} press_out_t;

typedef struct {
    int cursor;
    int64_t waiting_since[DECK_MAX_BUTTONS + 1]; /* a first tap on a double key; 0 when none */
    uint32_t waiting_version[DECK_MAX_BUTTONS + 1]; /* that tap's ha_version */
    uint32_t dropped;                            /* events lost to a ring wrap */
} press_router_t;

void press_router_init(press_router_t *r); /* starts after the newest event: nothing old is replayed */
/* Call every ~20 ms. Fills at most max results and returns their count. */
int press_router_poll(press_router_t *r, int64_t now_ms, press_out_t *out, int max);

#ifdef __cplusplus
}
#endif
