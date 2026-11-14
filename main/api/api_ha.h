#pragma once
/* Stage C (docs/design/esphome.md, C.1 and C.2): the panel runs the layout's homeassistant steps itself, with or
 * without the PC, by sending HomeassistantActionRequest (35) to every client that sent
 * SubscribeHomeassistantServicesRequest (34); and it asks Home Assistant for the followed entities with
 * SubscribeHomeAssistantStateResponse (39) once a client sent SubscribeHomeAssistantStatesRequest (38), feeding
 * each HomeAssistantStateResponse (40) to deck_model_set_ha_state. Pure C, compiled into tests/native. */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "api_entities.h"
#include "api_session.h"

#ifdef __cplusplus
extern "C" {
#endif

/* HA keeps every subscription until the connection ends (there is no unsubscribe), and a layout change sends
 * them again. Past this many on one connection, the panel closes it so the client starts clean. */
#define API_HA_SUBSCRIPTIONS_MAX 72

typedef struct {
    api_session_t *session;
    api_peer_t *peer;
} api_ha_client_t;

/* A key event from press_router ("press", "hold" or "double") on key `slot`. Returns -1 when the key has no
 * homeassistant step for that trigger (nothing sent, no feedback). Otherwise it sends every step to every
 * subscribed client, asks for the key's feedback (ok when every step reached at least one client, alert when
 * one reached none: Wi-Fi down, API off, or no Home Assistant subscribed) and returns the steps delivered. */
int api_ha_press(const api_ha_client_t *clients, int count, int slot, const char *type);

/* Sends the followed entity/attribute pairs (each once) when the client asked for HA states and the layout's
 * pairs changed since it last got them. */
void api_ha_follow_tick(api_session_t *s, api_peer_t *peer);
/* Handles 34, 38 and 40; false for any other id. */
bool api_ha_message(api_session_t *s, api_peer_t *peer, uint16_t type, const uint8_t *data, size_t len);

#ifdef __cplusplus
}
#endif
