#include "api_entities.h"

#include <math.h>
#include <stdio.h>
#include <string.h>

#include "api_messages.h"
#include "cJSON.h"

uint32_t api_fnv1(const char *object_id)
{
    uint32_t hash = 2166136261u;
    for (const unsigned char *c = (const unsigned char *)object_id; *c; ++c) {
        hash *= 16777619u;
        hash ^= *c;
    }
    return hash;
}

uint32_t api_key_slot_key(int slot)
{
    if (slot < 1 || slot > API_KEY_SLOTS) return 0;
    char object_id[8];
    snprintf(object_id, sizeof(object_id), "key_%d", slot);
    return api_fnv1(object_id);
}

#define OBJ_PC "pc_connected"
#define OBJ_LIGHT "backlight"
#define OBJ_RSSI "wifi_signal"
#define OBJ_PROFILE "profile"
#define OBJ_PAGE "page"
#define OBJ_CLOCK "show_clock"

/* 1 KB, so off the task stack. Only the tessera_api task calls into this file. */
static deck_api_options_t s_options;

void api_snapshot_read(api_snapshot_t *out, bool wifi_connected, int8_t rssi)
{
    memset(out, 0, sizeof(*out));
    out->pc_linked = deck_model_host_linked(API_PC_LINK_TIMEOUT_MS);
    out->dimmed = deck_model_dimmed();
    out->brightness = deck_model_brightness();
    out->wifi = wifi_connected;
    out->rssi = wifi_connected ? rssi : 0;
    deck_model_api_options(&s_options);
    out->has_profiles = s_options.profile_count > 0;
    out->has_pages = s_options.page_count > 0;
    const deck_context_t context = deck_model_context();
    memcpy(out->profile, context.profile, sizeof(out->profile));
    memcpy(out->page, context.page, sizeof(out->page));
}

/* ---- device info and the entity list ---- */

static void device_info(api_session_t *s, const api_device_t *d)
{
    pb_writer_t w = api_session_writer(s);
    const api_device_info_t info = {
        .name = d->name,
        .mac_address = d->mac_pretty,
        .esphome_version = API_ESPHOME_VERSION,
        .compilation_time = d->compilation_time,
        .model = "Guition JC1060P470C",
        .project_name = API_PROJECT_NAME,
        .project_version = d->project_version,
        .manufacturer = "Tessera",
        .friendly_name = d->friendly_name,
        .suggested_area = d->area,
        .api_encryption_supported = true,
    };
    api_encode_device_info(&w, &info);
    api_session_send(s, API_DEVICE_INFO_RESPONSE, &w);
}

static api_entity_info_t entity(const char *object_id, const char *name)
{
    api_entity_info_t e;
    memset(&e, 0, sizeof(e));
    e.object_id = object_id;
    e.name = name;
    e.key = api_fnv1(object_id);
    return e;
}

static void list_select(api_session_t *s, const char *object_id, const char *name, const deck_api_options_t *o)
{
    const bool profiles = !strcmp(object_id, OBJ_PROFILE);
    const char *options[DECK_API_OPTIONS_MAX] = {0};
    const int count = profiles ? o->profile_count : o->page_count;
    for (int i = 0; i < count; ++i) options[i] = profiles ? o->profiles[i] : o->pages[i];
    const api_entity_info_t e = entity(object_id, name);
    pb_writer_t w = api_session_writer(s);
    api_encode_list_select(&w, &e, options, (size_t)count);
    api_session_send(s, API_LIST_SELECT, &w);
}

static void list_entities(api_session_t *s, api_peer_t *peer)
{
    pb_writer_t w = api_session_writer(s);
    api_entity_info_t e = entity(OBJ_PC, "PC connected");
    e.device_class = "connectivity";
    api_encode_list_binary_sensor(&w, &e);
    api_session_send(s, API_LIST_BINARY_SENSOR, &w);

    w = api_session_writer(s);
    e = entity(OBJ_LIGHT, "Backlight");
    const uint32_t modes[] = {API_COLOR_MODE_BRIGHTNESS};
    api_encode_list_light(&w, &e, modes, 1);
    api_session_send(s, API_LIST_LIGHT, &w);

    w = api_session_writer(s);
    e = entity(OBJ_RSSI, "Wi-Fi signal");
    e.device_class = "signal_strength";
    e.entity_category = API_ENTITY_CATEGORY_DIAGNOSTIC;
    api_encode_list_sensor(&w, &e, "dBm", 0, API_STATE_CLASS_MEASUREMENT);
    api_session_send(s, API_LIST_SENSOR, &w);

    peer->options_version = deck_model_api_options_version(); /* read first: a change during the copy re-lists */
    deck_model_api_options(&s_options);
    list_select(s, OBJ_PROFILE, "Profile", &s_options);
    list_select(s, OBJ_PAGE, "Page", &s_options);

    w = api_session_writer(s);
    e = entity(OBJ_CLOCK, "Show clock");
    e.icon = "mdi:clock-outline";
    api_encode_list_button(&w, &e);
    api_session_send(s, API_LIST_BUTTON, &w);

    static const char *const types[] = {"press", "hold", "double"};
    for (int slot = 1; slot <= API_KEY_SLOTS; ++slot) {
        char object_id[8], name[8];
        snprintf(object_id, sizeof(object_id), "key_%d", slot);
        snprintf(name, sizeof(name), "Key %d", slot);
        w = api_session_writer(s);
        e = entity(object_id, name);
        e.device_class = "button";
        e.disabled_by_default = slot > 12;
        api_encode_list_event(&w, &e, types, 3);
        api_session_send(s, API_LIST_EVENT, &w);
    }
    api_session_send_empty(s, API_LIST_DONE);
}

/* ---- states ---- */

static void send_pc(api_session_t *s, const api_snapshot_t *now)
{
    pb_writer_t w = api_session_writer(s);
    api_encode_binary_sensor_state(&w, api_fnv1(OBJ_PC), now->pc_linked, false);
    api_session_send(s, API_BINARY_SENSOR_STATE, &w);
}

static void send_light(api_session_t *s, const api_snapshot_t *now)
{
    pb_writer_t w = api_session_writer(s);
    api_encode_light_state(&w, api_fnv1(OBJ_LIGHT), !now->dimmed, (float)now->brightness / 100.0f,
                           API_COLOR_MODE_BRIGHTNESS);
    api_session_send(s, API_LIGHT_STATE, &w);
}

static void send_rssi(api_session_t *s, const api_snapshot_t *now)
{
    pb_writer_t w = api_session_writer(s);
    api_encode_sensor_state(&w, api_fnv1(OBJ_RSSI), (float)now->rssi, !now->wifi);
    api_session_send(s, API_SENSOR_STATE, &w);
}

static void send_select(api_session_t *s, const api_snapshot_t *now, bool profile)
{
    pb_writer_t w = api_session_writer(s);
    if (profile) api_encode_select_state(&w, api_fnv1(OBJ_PROFILE), now->profile, !now->has_profiles);
    else api_encode_select_state(&w, api_fnv1(OBJ_PAGE), now->page, !now->has_pages);
    api_session_send(s, API_SELECT_STATE, &w);
}

static void send_all(api_session_t *s, api_peer_t *peer, const api_snapshot_t *now, int64_t now_ms)
{
    send_pc(s, now);
    send_light(s, now);
    send_rssi(s, now);
    send_select(s, now, true);
    send_select(s, now, false);
    peer->sent = *now;
    peer->rssi_sent_ms = now_ms;
}

void api_entities_tick(api_session_t *s, api_peer_t *peer, const api_snapshot_t *now, int64_t now_ms)
{
    if (!peer->subscribed || !api_session_ready(s)) return;
    const uint32_t options = deck_model_api_options_version();
    if (peer->options_version && options != peer->options_version) {
        if (options != peer->options_seen) { /* the host often sends several changes in a row */
            peer->options_seen = options;
            peer->options_seen_ms = now_ms;
        } else if (now_ms - peer->options_seen_ms >= API_OPTIONS_SETTLE_MS) {
            api_session_send_empty(s, API_DISCONNECT_REQUEST);
            api_session_close(s, "select options changed, the client lists them again");
            return;
        }
    }
    api_snapshot_t *sent = &peer->sent;
    if (now->pc_linked != sent->pc_linked) send_pc(s, now);
    if (now->dimmed != sent->dimmed || now->brightness != sent->brightness) send_light(s, now);
    if (now->wifi != sent->wifi || now_ms - peer->rssi_sent_ms >= API_RSSI_EVERY_MS) {
        send_rssi(s, now);
        peer->rssi_sent_ms = now_ms;
    }
    if (now->has_profiles != sent->has_profiles || strcmp(now->profile, sent->profile)) send_select(s, now, true);
    if (now->has_pages != sent->has_pages || strcmp(now->page, sent->page)) send_select(s, now, false);
    const int64_t rssi_at = peer->rssi_sent_ms;
    *sent = *now;
    peer->rssi_sent_ms = rssi_at;
}

bool api_entities_send_event(api_session_t *s, const api_peer_t *peer, int slot, const char *event_type)
{
    const uint32_t key = api_key_slot_key(slot);
    if (!key || !peer->subscribed || !api_session_ready(s)) return false;
    pb_writer_t w = api_session_writer(s);
    api_encode_event(&w, key, event_type);
    return api_session_send(s, API_EVENT, &w);
}

/* ---- commands ---- */

static void light_command(const uint8_t *data, size_t len, const api_snapshot_t *now)
{
    api_light_command_t command;
    if (!api_decode_light_command(data, len, &command) || command.key != api_fnv1(OBJ_LIGHT)) return;
    if (command.has_state && !command.state) {
        deck_model_request_backlight_off();
        return;
    }
    /* On: wake a dimmed panel (the console restores the level and tells the PC), then the new level. */
    if (now->dimmed) deck_model_request_wake();
    if (command.has_brightness && isfinite(command.brightness)) {
        const float b = command.brightness < 0.0f ? 0.0f : command.brightness > 1.0f ? 1.0f : command.brightness;
        long level = lroundf(b * 100.0f);
        if (level < 1) level = 1;
        if (level > 100) level = 100;
        deck_model_request_brightness((int)level, true);
    }
}

static bool option_known(const char *value, const char (*options)[DECK_API_OPTION_MAX + 1], int count)
{
    for (int i = 0; i < count; ++i)
        if (!strcmp(value, options[i])) return true;
    return false;
}

/* Valid only while the PC is linked: the host switches, as a rail shortcut does. Otherwise (and for a command
 * too soon after the last one) the current state goes back so HA's dropdown snaps back. The current value
 * queues nothing, so a flood cannot push the PC's touch lines out of the queue. */
static void select_command(api_session_t *s, const uint8_t *data, size_t len, const api_snapshot_t *now, bool soon)
{
    api_select_command_t command;
    const bool decoded = api_decode_select_command(data, len, &command);
    const bool profile = command.key == api_fnv1(OBJ_PROFILE);
    if (!profile && command.key != api_fnv1(OBJ_PAGE)) return;
    deck_model_api_options(&s_options);
    const bool known = decoded && (profile ? option_known(command.state, s_options.profiles, s_options.profile_count)
                                           : option_known(command.state, s_options.pages, s_options.page_count));
    const bool current = decoded && !strcmp(command.state, profile ? now->profile : now->page);
    if (soon || !known || current || !now->pc_linked) {
        send_select(s, now, profile);
        return;
    }
    cJSON *line = cJSON_CreateObject();
    if (!line) return;
    cJSON_AddStringToObject(line, "type", "ha_select");
    cJSON_AddStringToObject(line, "what", profile ? "profile" : "page");
    cJSON_AddStringToObject(line, "value", command.state);
    char *text = cJSON_PrintUnformatted(line);
    if (text) deck_model_queue_line(text);
    cJSON_free(text);
    cJSON_Delete(line);
}

/* True for a select or button command less than 250 ms after the last one this client got acted on. */
static bool too_soon(api_peer_t *peer, int64_t now_ms)
{
    if (peer->command_ms && now_ms - peer->command_ms < API_COMMAND_GAP_MS) return true;
    peer->command_ms = now_ms;
    return false;
}

void api_entities_message(api_session_t *s, api_peer_t *peer, const api_device_t *device, const api_snapshot_t *now,
                          uint16_t type, const uint8_t *data, size_t len, int64_t now_ms)
{
    switch (type) {
    case API_DEVICE_INFO_REQUEST:
        device_info(s, device);
        break;
    case API_LIST_ENTITIES_REQUEST:
        list_entities(s, peer);
        break;
    case API_SUBSCRIBE_STATES:
        peer->subscribed = true;
        send_all(s, peer, now, now_ms);
        break;
    case API_LIGHT_COMMAND:
        light_command(data, len, now);
        break;
    case API_SELECT_COMMAND:
        select_command(s, data, len, now, too_soon(peer, now_ms));
        break;
    case API_BUTTON_COMMAND: {
        uint32_t key = 0;
        if (api_decode_button_command(data, len, &key) && key == api_fnv1(OBJ_CLOCK) && !too_soon(peer, now_ms))
            deck_model_request_screen(DECK_SCREEN_AMBIENT);
        break;
    }
    default:
        break; /* SubscribeLogs (28) included: logs never leave over Wi-Fi */
    }
}

/* ---- settings ---- */

void api_settings_default(api_settings_t *out)
{
    memset(out, 0, sizeof(*out));
    strcpy(out->name, "tessera-deck");
    strcpy(out->friendly, "Tessera Deck");
}

bool api_name_valid(const char *name)
{
    const size_t len = name ? strlen(name) : 0;
    if (len < 1 || len > API_NAME_MAX) return false;
    for (size_t i = 0; i < len; ++i) {
        const char c = name[i];
        if (!((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-')) return false;
    }
    return true;
}

/* UTF-8 text without control characters, min..max code points (cJSON already checked the encoding). */
static bool text_valid(const char *text, size_t min, size_t max)
{
    size_t points = 0;
    for (const unsigned char *c = (const unsigned char *)text; *c; ++c) {
        if (*c < 0x20 || *c == 0x7F) return false;
        if ((*c & 0xC0) != 0x80) ++points;
    }
    return points >= min && points <= max;
}

static bool string_field(const cJSON *root, const char *key, char *out, size_t size, size_t min, size_t max)
{
    const cJSON *item = cJSON_GetObjectItemCaseSensitive(root, key);
    if (!cJSON_IsString(item) || strlen(item->valuestring) >= size || !text_valid(item->valuestring, min, max))
        return false;
    strcpy(out, item->valuestring);
    return true;
}

bool api_settings_from_json(const char *json, api_settings_t *out, const char **field)
{
    api_settings_t next;
    memset(&next, 0, sizeof(next));
    cJSON *root = json ? cJSON_Parse(json) : NULL;
    const cJSON *enabled = cJSON_GetObjectItemCaseSensitive(root, "enabled");
    const char *bad = NULL;
    if (!cJSON_IsObject(root)) bad = "json";
    else if (!cJSON_IsBool(enabled)) bad = "enabled";
    else if (!string_field(root, "name", next.name, sizeof(next.name), 1, API_NAME_MAX) || !api_name_valid(next.name))
        bad = "name";
    else if (!string_field(root, "friendly", next.friendly, sizeof(next.friendly), 1, API_FRIENDLY_MAX))
        bad = "friendly";
    else if (!string_field(root, "area", next.area, sizeof(next.area), 0, API_AREA_MAX))
        bad = "area";
    if (!bad) next.enabled = cJSON_IsTrue(enabled);
    cJSON_Delete(root);
    if (bad) {
        if (field) *field = bad;
        return false;
    }
    *out = next;
    return true;
}
