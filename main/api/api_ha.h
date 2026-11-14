#pragma once
/* Stage C (docs/design/esphome.md, C.1 and C.2): the panel runs the layout's homeassistant steps itself, with or
 * without the PC, by sending HomeassistantActionRequest (35) to one client that sent
 * SubscribeHomeassistantServicesRequest (34); and it asks Home Assistant for the followed entities with
 * SubscribeHomeAssistantStateResponse (39) once a client sent SubscribeHomeAssistantStatesRequest (38), feeding
 * each HomeAssistantStateResponse (40) to deck_model_set_ha_state. Pure C, compiled into tests/native. */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "api_entities.h"
#include "api_session.h"
#include "press_router.h"

#ifdef __cplusplus
extern "C" {
#endif

#define API_HA_CLIENTS_MAX 4                        /* api_server's SLOTS */
#define API_HA_LIVE_MS (API_PING_AFTER_MS + 10000) /* a client quiet longer than this does not get actions */

typedef struct {
    api_session_t *session;
    api_peer_t *peer;
} api_ha_client_t;

/* A key event from press_router. Returns -1 when the key has no homeassistant step for that trigger, or the
 * steps changed since the press was recorded (nothing sent, no feedback). Otherwise it sends each step to one
 * client: the live subscribed one heard from most recently, the next only when that write fails. It asks for
 * the key's feedback (ok when every step went out, alert when one did not: Wi-Fi down, API off, or no Home
 * Assistant subscribed), except for a trigger that also has PC steps, and returns the steps delivered.
 * "Delivered" is not "done": HA may still refuse it (device not allowed to perform actions). */
int api_ha_press(const api_ha_client_t *clients, int count, const press_out_t *press, int64_t now_ms);

/* Subscribes the followed entity/attribute pairs this connection has not subscribed yet, when the client asked
 * for HA states and the layout's pairs changed since. */
void api_ha_follow_tick(api_session_t *s, api_peer_t *peer);
/* Handles 34, 38 and 40; false for any other id. */
bool api_ha_message(api_session_t *s, api_peer_t *peer, uint16_t type, const uint8_t *data, size_t len);

#ifdef __cplusplus
}
#endif
