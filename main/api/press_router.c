#include "press_router.h"

#include <string.h>

void press_router_init(press_router_t *r)
{
    memset(r, 0, sizeof(*r));
    r->cursor = deck_model_last_event_id();
}

static bool has_double(int button_id)
{
    const int count = deck_model_button_count();
    deck_button_t button;
    for (int i = 0; i < count; ++i)
        if (deck_model_get_button(i, &button) && button.id == button_id) return button.has_double;
    return false;
}

static int emit(press_out_t *out, int n, int max, int slot, const char *type)
{
    if (n >= max) return n;
    out[n].slot = slot;
    out[n].type = type;
    return n + 1;
}

int press_router_poll(press_router_t *r, int64_t now_ms, press_out_t *out, int max)
{
    int n = 0;
    /* A first tap that saw no second one in time is a plain press. */
    for (int slot = 1; slot <= DECK_MAX_BUTTONS; ++slot) {
        if (r->waiting_since[slot] && now_ms - r->waiting_since[slot] >= PRESS_DOUBLE_MS && n < max) {
            r->waiting_since[slot] = 0;
            n = emit(out, n, max, slot, "press");
        }
    }
    deck_event_t events[8];
    while (n < max) {
        const int count = deck_model_events_since(r->cursor, events, 8);
        if (count <= 0) break;
        if (events[0].id > r->cursor + 1) r->dropped += (uint32_t)(events[0].id - r->cursor - 1); /* ring wrapped */
        int used = 0;
        for (; used < count && n + 2 <= max; ++used) {
            const deck_event_t *e = &events[used];
            r->cursor = e->id;
            const int slot = e->button_id;
            if (slot < 1 || slot > DECK_MAX_BUTTONS) continue;
            if (r->waiting_since[slot]) { /* a second tap, or a hold after a tap */
                r->waiting_since[slot] = 0;
                if (!e->hold) {
                    n = emit(out, n, max, slot, "double");
                    continue;
                }
                n = emit(out, n, max, slot, "press");
            }
            if (e->hold) n = emit(out, n, max, slot, "hold");
            else if (has_double(slot)) r->waiting_since[slot] = now_ms ? now_ms : 1;
            else n = emit(out, n, max, slot, "press");
        }
        if (used < count) break; /* out is full: the rest waits for the next poll */
    }
    return n;
}
