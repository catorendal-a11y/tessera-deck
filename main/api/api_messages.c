#include "api_messages.h"

#include <stdio.h>
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

/* ParsedTimezone (GetTimeResponse field 3) and its DSTRule, as esphome's time/posix_tz.h reads them: offsets
 * are POSIX style (seconds, positive west of UTC), rule times are seconds after local midnight. */
typedef struct {
    int32_t time_seconds;
    uint32_t day, type, month, week, day_of_week;
} dst_rule_t;

typedef struct {
    int32_t std_offset, dst_offset;
    dst_rule_t start, end;
} parsed_tz_t;

enum { DST_NONE = 0, DST_MONTH_WEEK_DAY = 1, DST_JULIAN_NO_LEAP = 2, DST_DAY_OF_YEAR = 3 };

static bool decode_rule(const pb_field_t *outer, dst_rule_t *out)
{
    memset(out, 0, sizeof(*out)); /* proto3: an absent time_seconds is 0 (midnight), not 02:00 */
    pb_reader_t r;
    pb_field_t f;
    pb_reader_init(&r, outer->data, outer->len);
    while (pb_next(&r, &f)) {
        if (f.wire != PB_VARINT) continue;
        if (f.field == 1) out->time_seconds = pb_zigzag32(f.varint);
        else if (f.field == 2) out->day = (uint32_t)f.varint;
        else if (f.field == 3) out->type = (uint32_t)f.varint;
        else if (f.field == 4) out->month = (uint32_t)f.varint;
        else if (f.field == 5) out->week = (uint32_t)f.varint;
        else if (f.field == 6) out->day_of_week = (uint32_t)f.varint;
    }
    return !r.error;
}

static bool decode_parsed_tz(const pb_field_t *outer, parsed_tz_t *out)
{
    memset(out, 0, sizeof(*out));
    pb_reader_t r;
    pb_field_t f;
    pb_reader_init(&r, outer->data, outer->len);
    bool ok = true;
    while (ok && pb_next(&r, &f)) {
        if (f.field == 1 && f.wire == PB_VARINT) out->std_offset = pb_zigzag32(f.varint);
        else if (f.field == 2 && f.wire == PB_VARINT) out->dst_offset = pb_zigzag32(f.varint);
        else if (f.field == 3 && f.wire == PB_LEN) ok = decode_rule(&f, &out->start);
        else if (f.field == 4 && f.wire == PB_LEN) ok = decode_rule(&f, &out->end);
    }
    return ok && !r.error;
}

/* "[-]h[:mm[:ss]]", the POSIX offset and rule time form. False past 24 h, or below 0 when not allowed (newlib
 * reads a rule time as unsigned). */
static bool put_hms(char **at, char *end, int32_t seconds, bool sign_allowed)
{
    if (seconds < 0 && !sign_allowed) return false;
    const int64_t abs_s = seconds < 0 ? -(int64_t)seconds : seconds;
    if (abs_s > 24 * 3600) return false;
    const long h = (long)(abs_s / 3600), m = (long)(abs_s / 60 % 60), s = (long)(abs_s % 60);
    int n = s ? snprintf(*at, (size_t)(end - *at), "%s%ld:%02ld:%02ld", seconds < 0 ? "-" : "", h, m, s)
          : m ? snprintf(*at, (size_t)(end - *at), "%s%ld:%02ld", seconds < 0 ? "-" : "", h, m)
              : snprintf(*at, (size_t)(end - *at), "%s%ld", seconds < 0 ? "-" : "", h);
    if (n < 0 || n >= end - *at) return false;
    *at += n;
    return true;
}

static bool put_rule(char **at, char *end, const dst_rule_t *rule)
{
    int n;
    if (rule->type == DST_MONTH_WEEK_DAY) {
        if (rule->month < 1 || rule->month > 12 || rule->week < 1 || rule->week > 5 || rule->day_of_week > 6)
            return false;
        n = snprintf(*at, (size_t)(end - *at), ",M%u.%u.%u", (unsigned)rule->month, (unsigned)rule->week,
                     (unsigned)rule->day_of_week);
    } else if (rule->type == DST_JULIAN_NO_LEAP) {
        if (rule->day < 1 || rule->day > 365) return false;
        n = snprintf(*at, (size_t)(end - *at), ",J%u", (unsigned)rule->day);
    } else if (rule->type == DST_DAY_OF_YEAR) {
        if (rule->day > 365) return false;
        n = snprintf(*at, (size_t)(end - *at), ",%u", (unsigned)rule->day);
    } else {
        return false;
    }
    if (n < 0 || n >= end - *at) return false;
    *at += n;
    if (rule->time_seconds == 7200) return true; /* the POSIX default */
    if (end - *at < 2) return false;
    *(*at)++ = '/';
    **at = '\0';
    return put_hms(at, end, rule->time_seconds, false);
}

/* For example std -3600, dst -7200, M3.5.0/2 and M10.5.0/3 give "STD-1DST-2,M3.5.0,M10.5.0/3". */
static bool posix_from_parsed(const parsed_tz_t *tz, char *out, size_t size)
{
    char *at = out, *end = out + size;
    const bool dst = tz->start.type != DST_NONE;
    const char *name = !dst && tz->std_offset == 0 ? "UTC" : "STD";
    int n = snprintf(at, size, "%s", name);
    if (n < 0 || (size_t)n >= size) return false;
    at += n;
    if (!put_hms(&at, end, tz->std_offset, true)) return false;
    if (dst) {
        if (end - at < 4) return false;
        memcpy(at, "DST", 4);
        at += 3;
        if (!put_hms(&at, end, tz->dst_offset, true) || !put_rule(&at, end, &tz->start) ||
            !put_rule(&at, end, &tz->end))
            return false;
    }
    return true;
}

/* The deprecated string (field 2) counts only when it looks like POSIX: a name (letters or <...>), a digit
 * somewhere, and no '/' before the first ',' (so "Europe/Oslo" or "Etc/GMT+1" never pass). */
static bool posix_shaped(const char *tz)
{
    if (!((tz[0] >= 'A' && tz[0] <= 'Z') || (tz[0] >= 'a' && tz[0] <= 'z') || tz[0] == '<')) return false;
    const char *comma = strchr(tz, ',');
    const char *slash = strchr(tz, '/');
    if (slash && (!comma || slash < comma)) return false;
    return strpbrk(tz, "0123456789") != NULL;
}

bool api_decode_get_time_response(const uint8_t *data, size_t len, api_get_time_response_t *out)
{
    memset(out, 0, sizeof(*out));
    pb_reader_t r;
    pb_field_t f;
    pb_reader_init(&r, data, len);
    bool has_parsed = false, parsed_ok = false;
    parsed_tz_t parsed;
    while (pb_next(&r, &f)) {
        if (f.field == 1 && f.wire == PB_FIXED32) out->epoch_seconds = f.fixed32;
        else if (f.field == 2 && !pb_field_string(&f, out->timezone, sizeof(out->timezone))) out->timezone[0] = '\0';
        else if (f.field == 3 && f.wire == PB_LEN) {
            has_parsed = true; /* parsed_timezone (2026.9+); current ESPHome reads only this one */
            parsed_ok = decode_parsed_tz(&f, &parsed);
        }
    }
    char built[API_TEXT_MAX + 1];
    if (has_parsed && parsed_ok && posix_from_parsed(&parsed, built, sizeof(built))) strcpy(out->timezone, built);
    else if (!posix_shaped(out->timezone)) out->timezone[0] = '\0';
    return !r.error;
}
