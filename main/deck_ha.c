#include "deck_ha.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cJSON.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

typedef struct {
    deck_ha_follow_t spec;
    bool has_state, stale;
    char state[DECK_HA_STATE_MAX + 1];
} follow_t;

typedef struct {
    int step_count, follow_count;
    deck_ha_step_t steps[DECK_HA_STEPS_MAX];
    follow_t follows[DECK_HA_FOLLOWS_MAX];
} ha_table_t;

/* About 40 KB: allocated on the first layout (malloc goes to PSRAM above 16 bytes on the panel). */
static ha_table_t *s_table;
static uint32_t s_version = 1;
static SemaphoreHandle_t s_lock;

static void lock(void)
{
    if (s_lock) xSemaphoreTake(s_lock, portMAX_DELAY);
}

static void unlock(void)
{
    if (s_lock) xSemaphoreGive(s_lock);
}

void deck_ha_init(void)
{
    if (!s_lock) s_lock = xSemaphoreCreateMutex();
}

/* ---- validation ---- */

bool deck_ha_id_valid(const char *text, size_t len)
{
    size_t dot = 0;
    for (size_t i = 0; i < len; ++i) {
        const char c = text[i];
        if (c == '.') {
            if (dot || i == 0) return false;
            dot = i;
        } else if (!((c >= 'a' && c <= 'z') || c == '_' || (c >= '0' && c <= '9' && i > 0))) {
            return false;
        }
    }
    return dot && dot + 1 < len;
}

/* UTF-8 text without control characters, at most max code points (cJSON already checked the encoding). */
static bool text_ok(const char *text, size_t max)
{
    size_t points = 0;
    for (const unsigned char *c = (const unsigned char *)text; *c; ++c) {
        if (*c < 0x20 || *c == 0x7F) return false;
        if ((*c & 0xC0) != 0x80) ++points;
    }
    return points <= max;
}

/* One id, or (list) up to 4 comma-separated ids, at most 128 characters in all. */
static bool entities_ok(const char *text, bool list)
{
    const size_t len = strlen(text);
    if (!len || len > DECK_HA_ENTITY_MAX) return false;
    int count = 0;
    for (const char *start = text;;) {
        const char *comma = strchr(start, ',');
        const size_t part = comma ? (size_t)(comma - start) : strlen(start);
        if (++count > (list ? DECK_HA_ENTITIES : 1) || !deck_ha_id_valid(start, part)) return false;
        if (!comma) return true;
        start = comma + 1;
    }
}

static bool key_ok(const char *text)
{
    const size_t len = strlen(text);
    if (len < 1 || len > DECK_HA_KEY_MAX) return false;
    for (size_t i = 0; i < len; ++i)
        if (!((text[i] >= 'a' && text[i] <= 'z') || (text[i] >= '0' && text[i] <= '9') || text[i] == '_')) return false;
    return true;
}

static bool attribute_ok(const char *text)
{
    return !text[0] || key_ok(text);
}

/* A data value: a string, a number or a boolean, sent as text ("true"/"false" lowercase). */
static bool value_text(const cJSON *item, char *out, size_t size)
{
    if (cJSON_IsString(item)) {
        if (strlen(item->valuestring) >= size || !text_ok(item->valuestring, DECK_HA_VALUE_MAX)) return false;
        strcpy(out, item->valuestring);
        return true;
    }
    if (cJSON_IsBool(item)) return snprintf(out, size, "%s", cJSON_IsTrue(item) ? "true" : "false") > 0;
    if (cJSON_IsNumber(item)) {
        const double v = item->valuedouble;
        if (v == (double)(long long)v && v > -1e15 && v < 1e15) snprintf(out, size, "%lld", (long long)v);
        else snprintf(out, size, "%.15g", v);
        return strlen(out) <= DECK_HA_VALUE_MAX;
    }
    return false;
}

static bool string_into(const cJSON *item, char *out, size_t size)
{
    if (!cJSON_IsString(item) || strlen(item->valuestring) >= size) return false;
    strcpy(out, item->valuestring);
    return true;
}

static bool parse_step(const cJSON *item, int button_id, char trigger, deck_ha_step_t *out)
{
    memset(out, 0, sizeof(*out));
    out->button_id = button_id;
    out->trigger = trigger;
    if (!cJSON_IsObject(item)) return false;
    const cJSON *action = cJSON_GetObjectItemCaseSensitive(item, "a");
    if (!string_into(action, out->action, sizeof(out->action)) || !deck_ha_id_valid(out->action, strlen(out->action)))
        return false;
    const cJSON *entity = cJSON_GetObjectItemCaseSensitive(item, "e");
    if (entity && !(string_into(entity, out->entity_id, sizeof(out->entity_id)) &&
                    (!out->entity_id[0] || entities_ok(out->entity_id, true))))
        return false;
    const cJSON *data = cJSON_GetObjectItemCaseSensitive(item, "d");
    if (!data) return true;
    if (!cJSON_IsObject(data) || cJSON_GetArraySize(data) > DECK_HA_DATA_MAX) return false;
    for (const cJSON *pair = data->child; pair; pair = pair->next) {
        const int n = out->data_count;
        if (!pair->string || !key_ok(pair->string) || !strcmp(pair->string, "entity_id") ||
            !value_text(pair, out->values[n], sizeof(out->values[n])))
            return false;
        strcpy(out->keys[n], pair->string);
        for (int previous = 0; previous < n; ++previous)
            if (!strcmp(out->keys[previous], pair->string)) return false;
        ++out->data_count;
    }
    return true;
}

static bool parse_follow(const cJSON *item, int button_id, deck_ha_follow_t *out)
{
    memset(out, 0, sizeof(*out));
    out->button_id = button_id;
    out->mode = 'a';
    if (!cJSON_IsObject(item)) return false;
    if (!string_into(cJSON_GetObjectItemCaseSensitive(item, "e"), out->entity_id, sizeof(out->entity_id)) ||
        !entities_ok(out->entity_id, false))
        return false;
    const cJSON *attribute = cJSON_GetObjectItemCaseSensitive(item, "a");
    if (attribute && !(string_into(attribute, out->attribute, sizeof(out->attribute)) && attribute_ok(out->attribute)))
        return false;
    const cJSON *mode = cJSON_GetObjectItemCaseSensitive(item, "m");
    if (mode) {
        if (!cJSON_IsString(mode) || strlen(mode->valuestring) != 1 || !strchr("avb", mode->valuestring[0])) return false;
        out->mode = mode->valuestring[0];
    }
    const cJSON *on = cJSON_GetObjectItemCaseSensitive(item, "on");
    if (on) {
        const int count = cJSON_GetArraySize(on);
        if (!cJSON_IsArray(on) || count < 1 || count > DECK_HA_ON_MAX) return false;
        for (const cJSON *text = on->child; text; text = text->next) {
            char *target = out->on[out->on_count];
            if (!string_into(text, target, sizeof(out->on[0])) || !target[0] || !text_ok(target, DECK_HA_ON_TEXT_MAX))
                return false;
            ++out->on_count;
        }
    } else {
        strcpy(out->on[0], "on");
        out->on_count = 1;
    }
    const cJSON *unit = cJSON_GetObjectItemCaseSensitive(item, "u");
    if (unit && !(string_into(unit, out->unit, sizeof(out->unit)) && text_ok(out->unit, DECK_HA_UNIT_MAX))) return false;
    return true;
}

static bool parse_steps(const cJSON *ha, int button_id, ha_table_t *table)
{
    if (!cJSON_IsObject(ha)) return false;
    static const char triggers[] = {'p', 'h', 'd'};
    for (size_t t = 0; t < sizeof(triggers); ++t) {
        const char name[2] = {triggers[t], '\0'};
        const cJSON *list = cJSON_GetObjectItemCaseSensitive(ha, name);
        if (!list) continue;
        if (!cJSON_IsArray(list) || cJSON_GetArraySize(list) > DECK_HA_TRIGGER_STEPS) return false;
        for (const cJSON *step = list->child; step; step = step->next) {
            if (table->step_count >= DECK_HA_STEPS_MAX ||
                !parse_step(step, button_id, triggers[t], &table->steps[table->step_count]))
                return false;
            ++table->step_count;
        }
    }
    return true;
}

static bool parse_table(const char *layout_json, ha_table_t *table)
{
    memset(table, 0, sizeof(*table));
    cJSON *json = layout_json ? cJSON_Parse(layout_json) : NULL;
    const cJSON *buttons = cJSON_GetObjectItemCaseSensitive(json, "buttons");
    bool valid = cJSON_IsArray(buttons) && cJSON_GetArraySize(buttons) <= DECK_MAX_BUTTONS;
    for (const cJSON *item = valid ? buttons->child : NULL; valid && item; item = item->next) {
        const cJSON *ha = cJSON_GetObjectItemCaseSensitive(item, "ha");
        const cJSON *hs = cJSON_GetObjectItemCaseSensitive(item, "hs");
        if (!ha && !hs) continue;
        const cJSON *id = cJSON_GetObjectItemCaseSensitive(item, "id");
        if (!cJSON_IsNumber(id) || id->valuedouble < 1 || id->valuedouble > DECK_MAX_BUTTONS ||
            id->valuedouble != (int)id->valuedouble) {
            valid = false;
            break;
        }
        if (ha && !parse_steps(ha, id->valueint, table)) valid = false;
        if (valid && hs) {
            /* ids are unique (deck_model_buttons_from_json), so 18 keys give at most 18 follows and pairs */
            valid = table->follow_count < DECK_HA_FOLLOWS_MAX &&
                    parse_follow(hs, id->valueint, &table->follows[table->follow_count].spec);
            if (valid) ++table->follow_count;
        }
    }
    cJSON_Delete(json);
    return valid;
}

/* ---- the live table ---- */

static bool same_pair(const deck_ha_follow_t *a, const char *entity_id, const char *attribute)
{
    return !strcmp(a->entity_id, entity_id) && !strcmp(a->attribute, attribute);
}

/* True when the new table follows a different set of entity/attribute pairs than the old one. */
static bool pairs_differ(const ha_table_t *old, const ha_table_t *next)
{
    for (int pass = 0; pass < 2; ++pass) {
        const ha_table_t *a = pass ? next : old, *b = pass ? old : next;
        const int a_count = a ? a->follow_count : 0, b_count = b ? b->follow_count : 0;
        for (int i = 0; i < a_count; ++i) {
            bool found = false;
            for (int j = 0; !found && j < b_count; ++j)
                found = same_pair(&b->follows[j].spec, a->follows[i].spec.entity_id, a->follows[i].spec.attribute);
            if (!found) return true;
        }
    }
    return false;
}

bool deck_model_ha_from_json(const char *layout_json)
{
    ha_table_t *next = calloc(1, sizeof(*next));
    if (!next) return false;
    if (!parse_table(layout_json, next)) {
        free(next);
        return false;
    }
    lock();
    const ha_table_t *old = s_table;
    bool changed_look = !old || old->follow_count != next->follow_count;
    for (int i = 0; i < next->follow_count; ++i) { /* carry the known states over */
        follow_t *f = &next->follows[i];
        for (int j = 0; old && j < old->follow_count; ++j) {
            if (!same_pair(&old->follows[j].spec, f->spec.entity_id, f->spec.attribute)) continue;
            f->has_state = old->follows[j].has_state;
            f->stale = old->follows[j].stale;
            memcpy(f->state, old->follows[j].state, sizeof(f->state));
            break;
        }
        if (!changed_look && i < old->follow_count)
            changed_look = memcmp(&f->spec, &old->follows[i].spec, sizeof(f->spec)) != 0 ||
                           f->has_state != old->follows[i].has_state;
    }
    if (pairs_differ(old, next)) ++s_version;
    if (!old) {
        s_table = next;
        next = NULL;
    } else {
        memcpy(s_table, next, sizeof(*next));
    }
    unlock();
    free(next);
    if (changed_look) deck_model_bump_live();
    return true;
}

int deck_model_ha_steps(int button_id, char trigger, deck_ha_step_t *out, int max)
{
    int n = 0;
    lock();
    for (int i = 0; s_table && i < s_table->step_count && n < max; ++i) {
        const deck_ha_step_t *step = &s_table->steps[i];
        if (step->button_id == button_id && step->trigger == trigger) out[n++] = *step;
    }
    unlock();
    return n;
}

bool deck_model_ha_has_steps(int button_id, char trigger)
{
    bool found = false;
    lock();
    for (int i = 0; s_table && !found && i < s_table->step_count; ++i)
        found = s_table->steps[i].button_id == button_id && s_table->steps[i].trigger == trigger;
    unlock();
    return found;
}

int deck_model_ha_follows(deck_ha_follow_t *out, int max)
{
    int n = 0;
    lock();
    for (int i = 0; s_table && i < s_table->follow_count && n < max; ++i) out[n++] = s_table->follows[i].spec;
    unlock();
    return n;
}

uint32_t deck_model_ha_version(void)
{
    lock();
    const uint32_t version = s_version;
    unlock();
    return version;
}

/* Copies at most DECK_HA_STATE_MAX bytes, cut at a UTF-8 boundary, with control characters flattened. */
static void copy_state(char *out, const char *state)
{
    size_t len = strlen(state);
    if (len > DECK_HA_STATE_MAX) {
        len = DECK_HA_STATE_MAX;
        while (len > 0 && ((unsigned char)state[len] & 0xC0) == 0x80) --len;
    }
    for (size_t i = 0; i < len; ++i) out[i] = (unsigned char)state[i] < 0x20 ? ' ' : state[i];
    out[len] = '\0';
}

bool deck_model_set_ha_state(const char *entity_id, const char *attribute, const char *state)
{
    if (!entity_id || !state) return false;
    if (!attribute) attribute = "";
    char text[DECK_HA_STATE_MAX + 1];
    copy_state(text, state);
    bool matched = false, changed = false;
    lock();
    for (int i = 0; s_table && i < s_table->follow_count; ++i) {
        follow_t *f = &s_table->follows[i];
        if (!same_pair(&f->spec, entity_id, attribute)) continue;
        matched = true;
        changed = changed || !f->has_state || f->stale || strcmp(f->state, text);
        f->has_state = true;
        f->stale = false;
        strcpy(f->state, text);
    }
    unlock();
    if (changed) deck_model_bump_live();
    return matched;
}

void deck_model_ha_mark_stale(void)
{
    bool changed = false;
    lock();
    for (int i = 0; s_table && i < s_table->follow_count; ++i) {
        follow_t *f = &s_table->follows[i];
        if (f->has_state && !f->stale) f->stale = changed = true;
    }
    unlock();
    if (changed) deck_model_bump_live();
}

/* 60 % of the color over the card, so a state from before an HA disconnect reads as old. */
static uint32_t faded(uint32_t color)
{
    uint32_t out = 0;
    for (int shift = 0; shift <= 16; shift += 8) {
        const uint32_t c = color >> shift & 0xFF, bg = DECK_HA_STALE_BG >> shift & 0xFF;
        out |= ((c * 60 + bg * 40) / 100) << shift;
    }
    return out;
}

static bool is_on(const deck_ha_follow_t *spec, const char *state)
{
    for (int i = 0; i < spec->on_count; ++i)
        if (!strcmp(spec->on[i], state)) return true;
    return false;
}

void deck_ha_overlay(deck_button_t *button)
{
    lock();
    for (int i = 0; s_table && i < s_table->follow_count; ++i) {
        const follow_t *f = &s_table->follows[i];
        if (f->spec.button_id != button->id || !f->has_state) continue;
        if (f->spec.mode != 'v') {
            const uint32_t color = is_on(&f->spec, f->state) ? button->color : DECK_HA_OFF_COLOR;
            button->color = f->stale ? faded(color) : color;
        }
        if (f->spec.mode != 'a' && f->state[0]) {
            /* A wide key shows the value as its second line; a 1-slot key has none, so the value is the label. */
            const bool wide = button->span > 1;
            char *target = wide ? button->sub : button->label;
            const size_t size = wide ? sizeof(button->sub) : sizeof(button->label);
            int n = snprintf(target, size, "%s%s%s", f->state, f->spec.unit[0] ? " " : "", f->spec.unit);
            if (n >= (int)size) { /* cut at a UTF-8 boundary */
                size_t len = size - 1;
                while (len > 0 && ((unsigned char)target[len] & 0xC0) == 0x80) --len;
                target[len] = '\0';
            }
        }
        break;
    }
    unlock();
}
