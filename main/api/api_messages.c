#include "api_messages.h"

#include <string.h>

/* Field numbers from esphome api.proto (dev branch, checked 2026-11). Field 4 of every ListEntities message is
 * reserved (the old unique_id). */

bool api_encode_hello_response(pb_writer_t *w, const api_hello_response_t *m)
{
    pb_put_uint(w, 1, m->major);
    pb_put_uint(w, 2, m->minor);
    pb_put_string(w, 3, m->server_info);
    pb_put_string(w, 4, m->name);
    return !w->overflow;
}

bool api_encode_connect_response(pb_writer_t *w, bool invalid_password)
{
    pb_put_bool(w, 1, invalid_password);
    return !w->overflow;
}

bool api_encode_device_info(pb_writer_t *w, const api_device_info_t *m)
{
    /* 1 uses_password stays false and is therefore not written. */
    pb_put_string(w, 2, m->name);
    pb_put_string(w, 3, m->mac_address);
    pb_put_string(w, 4, m->esphome_version);
    pb_put_string(w, 5, m->compilation_time);
    pb_put_string(w, 6, m->model);
    pb_put_string(w, 8, m->project_name);
    pb_put_string(w, 9, m->project_version);
    /* 10 webserver_port = 0 */
    pb_put_string(w, 12, m->manufacturer);
    pb_put_string(w, 13, m->friendly_name);
    pb_put_string(w, 16, m->suggested_area);
    pb_put_bool(w, 19, m->api_encryption_supported);
    return !w->overflow;
}

static void put_head(pb_writer_t *w, const api_entity_info_t *e)
{
    pb_put_string(w, 1, e->object_id);
    pb_put_fixed32(w, 2, e->key);
    pb_put_string(w, 3, e->name);
}

bool api_encode_list_binary_sensor(pb_writer_t *w, const api_entity_info_t *e)
{
    put_head(w, e);
    pb_put_string(w, 5, e->device_class);
    pb_put_bool(w, 7, e->disabled_by_default);
    pb_put_string(w, 8, e->icon);
    pb_put_uint(w, 9, e->entity_category);
    return !w->overflow;
}

bool api_encode_list_light(pb_writer_t *w, const api_entity_info_t *e, const uint32_t *color_modes, size_t count)
{
    put_head(w, e);
    pb_put_packed_uint(w, 12, color_modes, count);
    pb_put_bool(w, 13, e->disabled_by_default);
    pb_put_string(w, 14, e->icon);
    pb_put_uint(w, 15, e->entity_category);
    return !w->overflow;
}

bool api_encode_list_sensor(pb_writer_t *w, const api_entity_info_t *e, const char *unit, int32_t accuracy_decimals,
                            uint32_t state_class)
{
    put_head(w, e);
    pb_put_string(w, 5, e->icon);
    pb_put_string(w, 6, unit);
    pb_put_int32(w, 7, accuracy_decimals);
    pb_put_string(w, 9, e->device_class);
    pb_put_uint(w, 10, state_class);
    pb_put_bool(w, 12, e->disabled_by_default);
    pb_put_uint(w, 13, e->entity_category);
    return !w->overflow;
}

bool api_encode_list_select(pb_writer_t *w, const api_entity_info_t *e, const char *const *options, size_t count)
{
    put_head(w, e);
    pb_put_string(w, 5, e->icon);
    for (size_t i = 0; i < count; ++i) pb_put_repeated_string(w, 6, options[i]);
    pb_put_bool(w, 7, e->disabled_by_default);
    pb_put_uint(w, 8, e->entity_category);
    return !w->overflow;
}

bool api_encode_list_button(pb_writer_t *w, const api_entity_info_t *e)
{
    put_head(w, e);
    pb_put_string(w, 5, e->icon);
    pb_put_bool(w, 6, e->disabled_by_default);
    pb_put_uint(w, 7, e->entity_category);
    pb_put_string(w, 8, e->device_class);
    return !w->overflow;
}

bool api_encode_list_event(pb_writer_t *w, const api_entity_info_t *e, const char *const *types, size_t count)
{
    put_head(w, e);
    pb_put_string(w, 5, e->icon);
    pb_put_bool(w, 6, e->disabled_by_default);
    pb_put_uint(w, 7, e->entity_category);
    pb_put_string(w, 8, e->device_class);
    for (size_t i = 0; i < count; ++i) pb_put_repeated_string(w, 9, types[i]);
    return !w->overflow;
}

bool api_encode_binary_sensor_state(pb_writer_t *w, uint32_t key, bool state, bool missing)
{
    pb_put_fixed32(w, 1, key);
    pb_put_bool(w, 2, state);
    pb_put_bool(w, 3, missing);
    return !w->overflow;
}

bool api_encode_light_state(pb_writer_t *w, uint32_t key, bool state, float brightness, uint32_t color_mode)
{
    pb_put_fixed32(w, 1, key);
    pb_put_bool(w, 2, state);
    pb_put_float(w, 3, brightness);
    pb_put_uint(w, 11, color_mode);
    return !w->overflow;
}

bool api_encode_sensor_state(pb_writer_t *w, uint32_t key, float state, bool missing)
{
    pb_put_fixed32(w, 1, key);
    pb_put_float(w, 2, state);
    pb_put_bool(w, 3, missing);
    return !w->overflow;
}

bool api_encode_select_state(pb_writer_t *w, uint32_t key, const char *state, bool missing)
{
    pb_put_fixed32(w, 1, key);
    pb_put_string(w, 2, missing ? "" : state);
    pb_put_bool(w, 3, missing);
    return !w->overflow;
}

bool api_encode_event(pb_writer_t *w, uint32_t key, const char *event_type)
{
    pb_put_fixed32(w, 1, key);
    pb_put_string(w, 2, event_type);
    return !w->overflow;
}

/* ---- decoders ---- */

static bool as_varint(const pb_field_t *f, uint64_t *out)
{
    if (f->wire != PB_VARINT) return false;
    *out = f->varint;
    return true;
}

bool api_decode_hello_request(const uint8_t *data, size_t len, api_hello_request_t *out)
{
    memset(out, 0, sizeof(*out));
    pb_reader_t r;
    pb_field_t f;
    pb_reader_init(&r, data, len);
    while (pb_next(&r, &f)) {
        uint64_t v = 0;
        if (f.field == 1 && f.wire == PB_LEN) {
            /* A long client name is cut, not refused: it is only logged. */
            const size_t n = f.len < API_TEXT_MAX ? f.len : API_TEXT_MAX;
            memcpy(out->client_info, f.data, n);
            out->client_info[n] = '\0';
            for (size_t i = 0; i < n; ++i)
                if ((unsigned char)out->client_info[i] < 0x20) out->client_info[i] = '?';
        } else if (f.field == 2 && as_varint(&f, &v)) {
            out->major = (uint32_t)v;
        } else if (f.field == 3 && as_varint(&f, &v)) {
            out->minor = (uint32_t)v;
        }
    }
    return !r.error;
}

bool api_decode_light_command(const uint8_t *data, size_t len, api_light_command_t *out)
{
    memset(out, 0, sizeof(*out));
    pb_reader_t r;
    pb_field_t f;
    pb_reader_init(&r, data, len);
    while (pb_next(&r, &f)) {
        uint64_t v = 0;
        if (f.field == 1 && f.wire == PB_FIXED32) out->key = f.fixed32;
        else if (f.field == 2 && as_varint(&f, &v)) out->has_state = v != 0;
        else if (f.field == 3 && as_varint(&f, &v)) out->state = v != 0;
        else if (f.field == 4 && as_varint(&f, &v)) out->has_brightness = v != 0;
        else if (f.field == 5 && f.wire == PB_FIXED32) out->brightness = pb_field_float(&f);
    }
    return !r.error;
}

bool api_decode_select_command(const uint8_t *data, size_t len, api_select_command_t *out)
{
    memset(out, 0, sizeof(*out));
    pb_reader_t r;
    pb_field_t f;
    bool ok = true;
    pb_reader_init(&r, data, len);
    while (pb_next(&r, &f)) {
        if (f.field == 1 && f.wire == PB_FIXED32) out->key = f.fixed32;
        else if (f.field == 2) ok = pb_field_string(&f, out->state, sizeof(out->state)) && ok;
    }
    return ok && !r.error;
}

bool api_decode_button_command(const uint8_t *data, size_t len, uint32_t *key)
{
    *key = 0;
    pb_reader_t r;
    pb_field_t f;
    pb_reader_init(&r, data, len);
    while (pb_next(&r, &f))
        if (f.field == 1 && f.wire == PB_FIXED32) *key = f.fixed32;
    return !r.error;
}

bool api_decode_get_time_response(const uint8_t *data, size_t len, api_get_time_response_t *out)
{
    memset(out, 0, sizeof(*out));
    pb_reader_t r;
    pb_field_t f;
    pb_reader_init(&r, data, len);
    while (pb_next(&r, &f)) {
        if (f.field == 1 && f.wire == PB_FIXED32) out->epoch_seconds = f.fixed32;
        else if (f.field == 2 && !pb_field_string(&f, out->timezone, sizeof(out->timezone))) out->timezone[0] = '\0';
        /* 3 parsed_timezone (2026.9+) is not used: the POSIX string covers the same rules. */
    }
    return !r.error;
}
