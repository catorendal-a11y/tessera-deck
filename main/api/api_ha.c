#include "api_ha.h"

#include <stdlib.h>
#include <string.h>

#include "api_messages.h"
#include "deck_ha.h"
#include "deck_model.h"

/* Only the tessera_api task calls into this file, so the copies (about 8 KB) live here instead of on its stack,
 * allocated once: malloc puts them in PSRAM on the panel, where internal RAM is scarce. */
static struct {
    deck_ha_step_t steps[DECK_HA_TRIGGER_STEPS];
    deck_ha_follow_t follows[DECK_HA_FOLLOWS_MAX];
} *s_copy;

static bool copies(void)
{
    if (!s_copy) s_copy = calloc(1, sizeof(*s_copy));
    return s_copy != NULL;
}

static char trigger_of(const char *type)
{
    if (!strcmp(type, "hold")) return 'h';
    if (!strcmp(type, "double")) return 'd';
    return 'p';
}

static bool send_step(api_session_t *s, const deck_ha_step_t *step)
{
    api_ha_pair_t data[DECK_HA_DATA_MAX + 1];
    size_t count = 0;
    if (step->entity_id[0]) data[count++] = (api_ha_pair_t){"entity_id", step->entity_id};
    for (int i = 0; i < step->data_count; ++i) data[count++] = (api_ha_pair_t){step->keys[i], step->values[i]};
    pb_writer_t w = api_session_writer(s);
    return api_encode_ha_action(&w, step->action, data, count) && api_session_send(s, API_HA_ACTION_REQUEST, &w);
}

int api_ha_press(const api_ha_client_t *clients, int count, int slot, const char *type)
{
    if (!deck_model_ha_has_steps(slot, trigger_of(type))) return -1;
    const int steps = copies() ? deck_model_ha_steps(slot, trigger_of(type), s_copy->steps, DECK_HA_TRIGGER_STEPS) : 0;
    if (steps <= 0) { /* no memory for the copy: say the press did nothing */
        deck_model_request_feedback(slot, DECK_FEEDBACK_ALERT);
        return 0;
    }
    deck_ha_step_t *list = s_copy->steps;
    int delivered = 0;
    for (int i = 0; i < steps; ++i) {
        bool sent = false;
        for (int c = 0; c < count; ++c) {
            api_session_t *s = clients[c].session;
            if (!clients[c].peer->ha_services || !api_session_ready(s)) continue;
            sent = send_step(s, &list[i]) || sent;
        }
        delivered += sent ? 1 : 0;
    }
    /* Green means "delivered": HA sends no reply without wants_response, and that would fail plain actions. */
    deck_model_request_feedback(slot, delivered == steps ? DECK_FEEDBACK_OK : DECK_FEEDBACK_ALERT);
    return delivered;
}

void api_ha_follow_tick(api_session_t *s, api_peer_t *peer)
{
    if (!peer->ha_states || !api_session_ready(s)) return;
    const uint32_t version = deck_model_ha_version(); /* read first: a change during the copy sends again */
    if (peer->ha_version_sent == version || !copies()) return;
    deck_ha_follow_t *pairs = s_copy->follows;
    const int count = deck_model_ha_follows(pairs, DECK_HA_FOLLOWS_MAX);
    int fresh = 0;
    for (int i = 0; i < count; ++i) {
        bool seen = false;
        for (int j = 0; !seen && j < i; ++j)
            seen = !strcmp(pairs[i].entity_id, pairs[j].entity_id) &&
                   !strcmp(pairs[i].attribute, pairs[j].attribute);
        if (!seen) pairs[fresh++] = pairs[i];
    }
    if (peer->ha_subscriptions + fresh > API_HA_SUBSCRIPTIONS_MAX) {
        api_session_send_empty(s, API_DISCONNECT_REQUEST);
        api_session_close(s, "too many HA state subscriptions, the client subscribes again");
        return;
    }
    for (int i = 0; i < fresh; ++i) {
        pb_writer_t w = api_session_writer(s);
        if (!api_encode_ha_state_subscription(&w, pairs[i].entity_id, pairs[i].attribute) ||
            !api_session_send(s, API_HA_STATE_SUBSCRIPTION, &w))
            return; /* closed, or it did not fit: tried again on the next tick */
        ++peer->ha_subscriptions;
    }
    peer->ha_version_sent = version;
}

bool api_ha_message(api_session_t *s, api_peer_t *peer, uint16_t type, const uint8_t *data, size_t len)
{
    switch (type) {
    case API_SUBSCRIBE_HA_SERVICES:
        peer->ha_services = true;
        return true;
    case API_SUBSCRIBE_HA_STATES:
        peer->ha_states = true;
        peer->ha_version_sent = 0;
        api_ha_follow_tick(s, peer);
        return true;
    case API_HA_STATE: {
        api_ha_state_t state;
        if (peer->ha_states && api_decode_ha_state(data, len, &state))
            deck_model_set_ha_state(state.entity_id, state.attribute, state.state);
        return true;
    }
    default:
        return false;
    }
}
