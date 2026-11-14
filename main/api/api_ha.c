#include "api_ha.h"

#include <stdlib.h>
#include <string.h>

#include "api_messages.h"
#include "deck_ha.h"
#include "deck_model.h"
#include "esp_log.h"

static const char *TAG = "api_ha";

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

/* The clients that may get an action, most recently heard first: subscribed with 34, ready, and heard from
 * within API_HA_LIVE_MS (a link that went silent is not counted as delivered). */
static int live_clients(const api_ha_client_t *clients, int count, int64_t now_ms, int *order)
{
    int n = 0;
    for (int c = 0; c < count && n < API_HA_CLIENTS_MAX; ++c) {
        const api_session_t *s = clients[c].session;
        if (!clients[c].peer->ha_services || !api_session_ready(s) || now_ms - s->heard_ms > API_HA_LIVE_MS) continue;
        int at = n++;
        for (; at > 0 && clients[order[at - 1]].session->heard_ms < s->heard_ms; --at) order[at] = order[at - 1];
        order[at] = c;
    }
    return n;
}

int api_ha_press(const api_ha_client_t *clients, int count, const press_out_t *press, int64_t now_ms)
{
    const char trigger = trigger_of(press->type);
    if (!copies()) { /* no memory for the copy: say the press did nothing */
        if (!deck_model_ha_has_steps(press->slot, trigger)) return -1;
        deck_model_request_feedback(press->slot, DECK_FEEDBACK_ALERT);
        return 0;
    }
    bool pc = false;
    const int steps = deck_model_ha_press_steps(press->ha_version, press->slot, trigger, s_copy->steps,
                                                DECK_HA_TRIGGER_STEPS, &pc);
    if (steps <= 0) return -1; /* none, or the layout's steps changed since the press: never another key's */
    int order[API_HA_CLIENTS_MAX];
    const int live = live_clients(clients, count, now_ms, order);
    int delivered = 0;
    for (int i = 0; i < steps; ++i) {
        /* One client runs it, the next only when the write failed: two HA instances must not toggle twice. */
        bool sent = false;
        for (int c = 0; c < live && !sent; ++c) sent = send_step(clients[order[c]].session, &s_copy->steps[i]);
        delivered += sent ? 1 : 0;
    }
    /* Green means "delivered": HA sends no reply without wants_response, and that would fail plain actions.
     * A trigger that also has PC steps gets the host's feedback instead. */
    if (!pc) deck_model_request_feedback(press->slot, delivered == steps ? DECK_FEEDBACK_OK : DECK_FEEDBACK_ALERT);
    else if (delivered < steps) ESP_LOGW(TAG, "key %d: %d of %d Home Assistant steps not delivered", press->slot,
                                         steps - delivered, steps);
    return delivered;
}

/* FNV-1a over "entity\0attribute". */
static uint32_t pair_hash(const deck_ha_follow_t *pair)
{
    uint32_t h = 2166136261u;
    for (const char *c = pair->entity_id;; ++c) {
        h = (h ^ (uint8_t)*c) * 16777619u;
        if (!*c) break;
    }
    for (const char *c = pair->attribute; *c; ++c) h = (h ^ (uint8_t)*c) * 16777619u;
    return h;
}

static bool subscribed(const api_peer_t *peer, uint32_t hash)
{
    for (int i = 0; i < peer->ha_subscriptions; ++i)
        if (peer->ha_sent[i] == hash) return true;
    return false;
}

void api_ha_follow_tick(api_session_t *s, api_peer_t *peer)
{
    if (!peer->ha_states || !api_session_ready(s)) return;
    const uint32_t version = deck_model_ha_version(); /* read first: a change during the copy sends again */
    if (peer->ha_version_sent == version || !copies()) return;
    deck_ha_follow_t *pairs = s_copy->follows;
    const int count = deck_model_ha_follows(pairs, DECK_HA_FOLLOWS_MAX);
    /* Only pairs this connection has not subscribed yet: HA keeps every subscription (it has no unsubscribe)
     * and the panel keeps their states, so a page that comes back needs nothing new. */
    for (int i = 0; i < count; ++i) {
        const uint32_t hash = pair_hash(&pairs[i]);
        if (subscribed(peer, hash)) continue;
        if (peer->ha_subscriptions >= API_HA_SUBSCRIPTIONS_MAX) {
            api_session_send_empty(s, API_DISCONNECT_REQUEST);
            api_session_close(s, "too many HA state subscriptions, the client subscribes again");
            return;
        }
        pb_writer_t w = api_session_writer(s);
        if (!api_encode_ha_state_subscription(&w, pairs[i].entity_id, pairs[i].attribute) ||
            !api_session_send(s, API_HA_STATE_SUBSCRIPTION, &w))
            return; /* closed, or it did not fit: tried again on the next tick */
        peer->ha_sent[peer->ha_subscriptions++] = hash;
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
