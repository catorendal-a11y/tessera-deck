#pragma once
/* The ESPHome native API messages Tessera uses, with the ids and field numbers of esphome/esphome
 * esphome/components/api/api.proto. Encoders write into a pb_writer_t and return false on overflow;
 * decoders fill fixed-size structs and return false on malformed data. Unknown fields are skipped.
 * docs/design/esphome.md, B.4. Pure C, compiled into tests/native. */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "api_proto.h"

#ifdef __cplusplus
extern "C" {
#endif

enum {
    API_HELLO_REQUEST = 1,
    API_HELLO_RESPONSE = 2,
    API_CONNECT_REQUEST = 3, /* AuthenticationRequest in current api.proto; legacy, always accepted */
    API_CONNECT_RESPONSE = 4,
    API_DISCONNECT_REQUEST = 5,
    API_DISCONNECT_RESPONSE = 6,
    API_PING_REQUEST = 7,
    API_PING_RESPONSE = 8,
    API_DEVICE_INFO_REQUEST = 9,
    API_DEVICE_INFO_RESPONSE = 10,
    API_LIST_ENTITIES_REQUEST = 11,
    API_LIST_BINARY_SENSOR = 12,
    API_LIST_LIGHT = 15,
    API_LIST_SENSOR = 16,
    API_LIST_DONE = 19,
    API_SUBSCRIBE_STATES = 20,
    API_BINARY_SENSOR_STATE = 21,
    API_LIGHT_STATE = 24,
    API_SENSOR_STATE = 25,
    API_SUBSCRIBE_LOGS = 28,
    API_LIGHT_COMMAND = 32,
    API_SUBSCRIBE_HA_SERVICES = 34,
    API_HA_ACTION_REQUEST = 35,
    API_GET_TIME_REQUEST = 36,
    API_GET_TIME_RESPONSE = 37,
    API_SUBSCRIBE_HA_STATES = 38,
    API_LIST_SELECT = 52,
    API_SELECT_STATE = 53,
    API_SELECT_COMMAND = 54,
    API_LIST_BUTTON = 61,
    API_BUTTON_COMMAND = 62,
    API_LIST_EVENT = 107,
    API_EVENT = 108,
};

enum { API_ENTITY_CATEGORY_NONE = 0, API_ENTITY_CATEGORY_CONFIG = 1, API_ENTITY_CATEGORY_DIAGNOSTIC = 2 };
enum { API_COLOR_MODE_BRIGHTNESS = 3 };
enum { API_STATE_CLASS_MEASUREMENT = 1 };

#define API_NAME_MAX 31
/* DeviceInfoResponse.esphome_version and the mDNS "version": a string HA accepts (it shows it, and some features
 * gate on it); the real firmware version is project_version. */
#define API_ESPHOME_VERSION "2026.11.0"
#define API_PROJECT_NAME "catorendal-a11y.tessera-deck"
#define API_TEXT_MAX 63

/* Server to client */
typedef struct {
    uint32_t major, minor;
    const char *server_info, *name;
} api_hello_response_t;

typedef struct {
    const char *name, *mac_address, *esphome_version, *compilation_time, *model, *project_name, *project_version,
        *manufacturer, *friendly_name, *suggested_area;
    bool api_encryption_supported;
} api_device_info_t;

/* The fields every ListEntities*Response shares; the field numbers differ per type and live in the encoders. */
typedef struct {
    const char *object_id, *name, *icon, *device_class;
    uint32_t key;
    bool disabled_by_default;
    uint32_t entity_category;
} api_entity_info_t;

bool api_encode_hello_response(pb_writer_t *w, const api_hello_response_t *m);
bool api_encode_connect_response(pb_writer_t *w, bool invalid_password);
bool api_encode_device_info(pb_writer_t *w, const api_device_info_t *m);
bool api_encode_list_binary_sensor(pb_writer_t *w, const api_entity_info_t *e);
bool api_encode_list_light(pb_writer_t *w, const api_entity_info_t *e, const uint32_t *color_modes, size_t count);
bool api_encode_list_sensor(pb_writer_t *w, const api_entity_info_t *e, const char *unit, int32_t accuracy_decimals,
                            uint32_t state_class);
bool api_encode_list_select(pb_writer_t *w, const api_entity_info_t *e, const char *const *options, size_t count);
bool api_encode_list_button(pb_writer_t *w, const api_entity_info_t *e);
bool api_encode_list_event(pb_writer_t *w, const api_entity_info_t *e, const char *const *types, size_t count);
bool api_encode_binary_sensor_state(pb_writer_t *w, uint32_t key, bool state, bool missing);
bool api_encode_light_state(pb_writer_t *w, uint32_t key, bool state, float brightness, uint32_t color_mode);
bool api_encode_sensor_state(pb_writer_t *w, uint32_t key, float state, bool missing);
bool api_encode_select_state(pb_writer_t *w, uint32_t key, const char *state, bool missing);
bool api_encode_event(pb_writer_t *w, uint32_t key, const char *event_type);

/* Client to server */
typedef struct {
    char client_info[API_TEXT_MAX + 1];
    uint32_t major, minor;
} api_hello_request_t;

typedef struct {
    uint32_t key;
    bool has_state, state, has_brightness;
    float brightness;
} api_light_command_t;

typedef struct {
    uint32_t key;
    char state[API_NAME_MAX + 1];
} api_select_command_t;

typedef struct {
    uint32_t epoch_seconds;
    /* POSIX TZ string: built from parsed_timezone (3) when present, else the deprecated string (2) when it has
     * a POSIX shape; "" when neither gives a usable zone (an IANA name, say). */
    char timezone[API_TEXT_MAX + 1];
} api_get_time_response_t;

bool api_decode_hello_request(const uint8_t *data, size_t len, api_hello_request_t *out);
bool api_decode_light_command(const uint8_t *data, size_t len, api_light_command_t *out);
bool api_decode_select_command(const uint8_t *data, size_t len, api_select_command_t *out);
bool api_decode_button_command(const uint8_t *data, size_t len, uint32_t *key);
bool api_decode_get_time_response(const uint8_t *data, size_t len, api_get_time_response_t *out);

#ifdef __cplusplus
}
#endif
