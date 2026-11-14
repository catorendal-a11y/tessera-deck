#pragma once
/* The entities Tessera shows in Home Assistant (docs/design/esphome.md, B.5): an event per key slot, selects
 * for profile and page, the backlight as a light, the Wi-Fi signal, the PC link and a button for the clock.
 * Reads and writes only deck_model accessors. Pure C (with cJSON), compiled into tests/native. */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "api_messages.h"
#include "api_session.h"
#include "deck_model.h"

#ifdef __cplusplus
extern "C" {
#endif

#define API_KEY_SLOTS 18
#define API_PC_LINK_TIMEOUT_MS 3500
#define API_RSSI_EVERY_MS 60000
#define API_OPTIONS_SETTLE_MS 1000 /* new select options: wait this long for more, then make the client re-list */
#define API_COMMAND_GAP_MS 250     /* select and button commands closer than this from one client are dropped */

/* Stage C: distinct entity/attribute pairs subscribed on one connection. Past this, the panel closes it so the
 * client starts clean; that takes more followed pairs than DECK_HA_STATES_MAX across the whole profile. */
#define API_HA_SUBSCRIPTIONS_MAX 72

/* What the states are made of, read once per loop. */
typedef struct {
    bool pc_linked;
    bool dimmed;
    int brightness; /* 1..100 */
    bool wifi;      /* connected, so rssi is real */
    int8_t rssi;
    bool has_profiles, has_pages;
    char profile[DECK_CONTEXT_TEXT_MAX + 1];
    char page[DECK_CONTEXT_TEXT_MAX + 1];
} api_snapshot_t;

/* Per connection: what this client has seen. */
typedef struct {
    bool subscribed;
    api_snapshot_t sent;
    int64_t rssi_sent_ms;
    uint32_t options_version; /* deck_model_api_options_version() at ListEntities; 0 before */
    uint32_t options_seen;    /* a newer version, and when it was first seen */
    int64_t options_seen_ms;
    int64_t command_ms;       /* the last select or button command acted on */
    /* Stage C (api_ha.c) */
    bool ha_services;         /* sent SubscribeHomeassistantServicesRequest (34): gets our action requests */
    bool ha_states;           /* sent SubscribeHomeAssistantStatesRequest (38): gets our state subscriptions */
    uint32_t ha_version_sent; /* deck_model_ha_version() of the pairs it got; 0 before */
    int ha_subscriptions;     /* distinct pairs subscribed on this connection (HA has no unsubscribe) */
    uint32_t ha_sent[API_HA_SUBSCRIPTIONS_MAX]; /* their hashes: a pair is subscribed once per connection */
} api_peer_t;

typedef struct {
    const char *name, *friendly_name, *area, *mac_pretty, *project_version, *compilation_time;
} api_device_t;

uint32_t api_fnv1(const char *object_id); /* FNV-1 32-bit: basis 2166136261, prime 16777619 */
uint32_t api_key_slot_key(int slot);      /* key of key_<slot>, slot 1..18; 0 otherwise */

void api_snapshot_read(api_snapshot_t *out, bool wifi_connected, int8_t rssi);
/* Handles DeviceInfo, ListEntities, SubscribeStates and the commands. Other ids are ignored (SubscribeLogs too). */
void api_entities_message(api_session_t *s, api_peer_t *peer, const api_device_t *device, const api_snapshot_t *now,
                          uint16_t type, const uint8_t *data, size_t len, int64_t now_ms);
/* Sends the states that changed since this client last saw them, and the Wi-Fi signal every 60 s. When the
 * select options changed after ListEntities (ESPHome has no "entity info changed" message), it sends
 * DisconnectRequest and closes, so the client reconnects and lists them again. */
void api_entities_tick(api_session_t *s, api_peer_t *peer, const api_snapshot_t *now, int64_t now_ms);
bool api_entities_send_event(api_session_t *s, const api_peer_t *peer, int slot, const char *event_type);

/* AD_API_SET {"enabled":true,"name":"tessera-deck","friendly":"Tessera Deck","area":""}. */
#define API_FRIENDLY_MAX 60 /* characters */
#define API_AREA_MAX 40
typedef struct {
    bool enabled;
    char name[API_NAME_MAX + 1];
    char friendly[API_FRIENDLY_MAX * 4 + 1]; /* UTF-8 */
    char area[API_AREA_MAX * 4 + 1];
} api_settings_t;
void api_settings_default(api_settings_t *out);
bool api_name_valid(const char *name); /* ^[a-z0-9-]{1,31}$ */
/* False with *field = "json", "enabled", "name", "friendly" or "area" on the first bad value. */
bool api_settings_from_json(const char *json, api_settings_t *out, const char **field);

#ifdef __cplusplus
}
#endif
