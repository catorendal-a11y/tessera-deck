#include "deck_ha.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cJSON.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

typedef struct {
    int step_count, follow_count;
    deck_ha_step_t steps[DECK_HA_STEPS_MAX];
    deck_ha_follow_t follows[DECK_HA_FOLLOWS_MAX];
    uint8_t pc[DECK_MAX_BUTTONS + 1]; /* per key: bit 0 press, 1 hold, 2 double also have PC steps */
} ha_table_t;

typedef struct {
    char entity_id[DECK_HA_ENTITY_MAX + 1];
    char attribute[DECK_HA_ATTRIBUTE_MAX + 1];
    char state[DECK_HA_STATE_MAX + 1];
    bool stale;
} ha_state_t;

/* About 100 KB, allocated on the first layout (malloc goes to PSRAM above 16 bytes on the panel): the live
 * table, the scratch one deck_model_ha_prepare fills, and the states. States are kept by pair, so a pair
 * subscribed on an earlier page still has its state when that page comes back: HA sends a state only when it
 * changes, and the panel subscribes each pair once per connection. */
static struct {
    ha_table_t tables[2];
    ha_state_t states[DECK_HA_STATES_MAX];
} *s_mem;
static ha_table_t *s_table, *s_next; /* s_table is NULL before the first commit */
static int s_state_count, s_state_next;
static uint32_t s_version = 1, s_steps_version = 1;
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
        if (v > -1e15 && v < 1e15 && v == (double)(long long)v) snprintf(out, size, "%lld", (long long)v);
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

static const char TRIGGERS[] = {'p', 'h', 'd'};

static int trigger_bit(char trigger)
{
    const char *at = trigger ? memchr(TRIGGERS, trigger, sizeof(TRIGGERS)) : NULL;
    return at ? 1 << (at - TRIGGERS) : 0;
}

static bool parse_steps(const cJSON *ha, int button_id, ha_table_t *table)
{
    if (!cJSON_IsObject(ha)) return false;
    /* "pc": the triggers that also have PC steps, for example "ph". The host then gives their feedback. */
    const cJSON *pc = cJSON_GetObjectItemCaseSensitive(ha, "pc");
    if (pc) {
        if (!cJSON_IsString(pc) || strlen(pc->valuestring) > sizeof(TRIGGERS)) return false;
        for (const char *c = pc->valuestring; *c; ++c) {
            const int bit = trigger_bit(*c);
            if (!bit || (table->pc[button_id] & bit)) return false;
            table->pc[button_id] |= (uint8_t)bit;
        }
    }
    const char *triggers = TRIGGERS;
    for (size_t t = 0; t < sizeof(TRIGGERS); ++t) {
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
                    parse_follow(hs, id->valueint, &table->follows[table->follow_count]);
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
                found = same_pair(&b->follows[j], a->follows[i].entity_id, a->follows[i].attribute);
            if (!found) return true;
        }
    }
    return false;
}

bool deck_model_ha_prepare(const char *layout_json)
{
    if (!s_mem) {
        s_mem = calloc(1, sizeof(*s_mem));
        if (!s_mem) return false;
        s_next = &s_mem->tables[0];
    }
    return parse_table(layout_json, s_next); /* s_next is never the live table, and only this writer uses it */
}

void deck_model_ha_commit(void)
{
    if (!s_next) return;
    lock();
    ha_table_t *old = s_table, *next = s_next;
    const bool changed_look = !old || old->follow_count != next->follow_count ||
                              memcmp(old->follows, next->follows, sizeof(next->follows[0]) * (size_t)next->follow_count);
    if (pairs_differ(old, next)) ++s_version;
    if (!old || old->step_count != next->step_count || memcmp(old->pc, next->pc, sizeof(next->pc)) ||
        memcmp(old->steps, next->steps, sizeof(next->steps[0]) * (size_t)next->step_count))
        ++s_steps_version;
    s_table = next;
    s_next = old ? old : &s_mem->tables[1];
    unlock();
    if (changed_look) deck_model_bump_live();
}

bool deck_model_ha_from_json(const char *layout_json)
{
    if (!deck_model_ha_prepare(layout_json)) return false;
    deck_model_ha_commit();
    return true;
}

static int steps_locked(int button_id, char trigger, deck_ha_step_t *out, int max)
{
    int n = 0;
    for (int i = 0; s_table && i < s_table->step_count && n < max; ++i) {
        const deck_ha_step_t *step = &s_table->steps[i];
        if (step->button_id == button_id && step->trigger == trigger) out[n++] = *step;
    }
    return n;
}

static bool pc_locked(int button_id, char trigger)
{
    return s_table && button_id >= 1 && button_id <= DECK_MAX_BUTTONS && (s_table->pc[button_id] & trigger_bit(trigger));
}

int deck_model_ha_steps(int button_id, char trigger, deck_ha_step_t *out, int max)
{
    lock();
    const int n = steps_locked(button_id, trigger, out, max);
    unlock();
    return n;
}

int deck_model_ha_press_steps(uint32_t version, int button_id, char trigger, deck_ha_step_t *out, int max, bool *pc)
{
    lock();
    const bool current = version == s_steps_version;
    const int n = current ? steps_locked(button_id, trigger, out, max) : -1;
    if (pc) *pc = current && pc_locked(button_id, trigger);
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

bool deck_model_ha_pc_steps(int button_id, char trigger)
{
    lock();
    const bool pc = pc_locked(button_id, trigger);
    unlock();
    return pc;
}

uint32_t deck_model_ha_steps_version(void)
{
    lock();
    const uint32_t version = s_steps_version;
    unlock();
    return version;
}

int deck_model_ha_follows(deck_ha_follow_t *out, int max)
{
    int n = 0;
    lock();
    for (int i = 0; s_table && i < s_table->follow_count && n < max; ++i) out[n++] = s_table->follows[i];
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

/* The length of the valid UTF-8 sequence at c (at most `left` bytes), 0 when it is not one. */
static size_t utf8_length(const unsigned char *c, size_t left)
{
    size_t n;
    unsigned min;
    if (*c < 0x80) return 1;
    if ((*c & 0xE0) == 0xC0) {
        n = 2;
        min = 0x80;
    } else if ((*c & 0xF0) == 0xE0) {
        n = 3;
        min = 0x800;
    } else if ((*c & 0xF8) == 0xF0) {
        n = 4;
        min = 0x10000;
    } else {
        return 0;
    }
    if (n > left) return 0;
    unsigned point = *c & (0x7Fu >> n);
    for (size_t i = 1; i < n; ++i) {
        if ((c[i] & 0xC0) != 0x80) return 0;
        point = point << 6 | (c[i] & 0x3Fu);
    }
    return point < min || point > 0x10FFFF || (point >= 0xD800 && point <= 0xDFFF) ? 0 : n;
}

/* Copies at most DECK_HA_STATE_MAX bytes of whole characters. Control characters, DEL and bytes that are not
 * valid UTF-8 become spaces, so nothing odd reaches LVGL. */
static void copy_state(char *out, const char *state)
{
    const unsigned char *in = (const unsigned char *)state;
    size_t len = 0, left = strlen(state);
    while (left) {
        const size_t n = utf8_length(in, left), step = n ? n : 1;
        if (len + step > DECK_HA_STATE_MAX) break;
        if (n > 1) memcpy(out + len, in, n);
        else out[len] = n == 0 || *in < 0x20 || *in == 0x7F ? ' ' : (char)*in;
        len += step;
        in += step;
        left -= step;
    }
    out[len] = '\0';
}

static bool followed_locked(const char *entity_id, const char *attribute)
{
    for (int i = 0; s_table && i < s_table->follow_count; ++i)
        if (same_pair(&s_table->follows[i], entity_id, attribute)) return true;
    return false;
}

static ha_state_t *state_locked(const char *entity_id, const char *attribute)
{
    for (int i = 0; s_mem && i < s_state_count; ++i)
        if (!strcmp(s_mem->states[i].entity_id, entity_id) && !strcmp(s_mem->states[i].attribute, attribute))
            return &s_mem->states[i];
    return NULL;
}

/* A slot for a new pair: a free one, else one no key follows now (stale first), else the next in turn. */
static ha_state_t *new_state_locked(void)
{
    if (s_state_count < DECK_HA_STATES_MAX) return &s_mem->states[s_state_count++];
    ha_state_t *unfollowed = NULL;
    for (int i = 0; i < DECK_HA_STATES_MAX; ++i) {
        ha_state_t *st = &s_mem->states[i];
        if (followed_locked(st->entity_id, st->attribute)) continue;
        if (st->stale) return st;
        if (!unfollowed) unfollowed = st;
    }
    if (unfollowed) return unfollowed;
    s_state_next = (s_state_next + 1) % DECK_HA_STATES_MAX;
    return &s_mem->states[s_state_next];
}

bool deck_model_set_ha_state(const char *entity_id, const char *attribute, const char *state)
{
    if (!entity_id || !state) return false;
    if (!attribute) attribute = "";
    if (strlen(entity_id) > DECK_HA_ENTITY_MAX || strlen(attribute) > DECK_HA_ATTRIBUTE_MAX) return false;
    char text[DECK_HA_STATE_MAX + 1];
    copy_state(text, state);
    lock();
    if (!s_mem) { /* no layout yet: nowhere to keep it */
        unlock();
        return false;
    }
    ha_state_t *st = state_locked(entity_id, attribute);
    bool changed = !st;
    if (!st) {
        st = new_state_locked();
        strcpy(st->entity_id, entity_id);
        strcpy(st->attribute, attribute);
    }
    changed = changed || st->stale || strcmp(st->state, text);
    strcpy(st->state, text);
    st->stale = false;
    const bool matched = followed_locked(entity_id, attribute);
    unlock();
    if (changed && matched) deck_model_bump_live();
    return matched;
}

void deck_model_ha_mark_stale(void)
{
    bool changed = false;
    lock();
    for (int i = 0; s_mem && i < s_state_count; ++i) {
        ha_state_t *st = &s_mem->states[i];
        if (!st->stale) st->stale = changed = true;
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

/* The state and unit into a key field of `size` bytes, cut at a UTF-8 boundary. */
static void put_text(char *target, size_t size, const char *state, const char *unit)
{
    const int n = snprintf(target, size, "%s%s%s", state, unit[0] ? " " : "", unit);
    if (n >= (int)size) {
        size_t len = size - 1;
        while (len > 0 && ((unsigned char)target[len] & 0xC0) == 0x80) --len;
        target[len] = '\0';
    }
}

void deck_ha_overlay(deck_button_t *button)
{
    lock();
    for (int i = 0; s_table && i < s_table->follow_count; ++i) {
        const deck_ha_follow_t *spec = &s_table->follows[i];
        if (spec->button_id != button->id) continue;
        /* A wide key shows the value as its second line; a 1-slot key has none, so the value is the label,
         * shown even when the title is hidden (empty there until a state arrives). */
        const bool value = spec->mode != 'a', wide = button->span > 1;
        if (value && !wide && button->title_position == 3) {
            button->title_position = 0;
            button->label[0] = '\0';
        }
        const ha_state_t *st = state_locked(spec->entity_id, spec->attribute);
        if (!st) break;
        const bool invalid = !strcmp(st->state, "unavailable") || !strcmp(st->state, "unknown");
        if (spec->mode != 'v') {
            const uint32_t color = !invalid && is_on(spec, st->state) ? button->color : DECK_HA_OFF_COLOR;
            button->color = st->stale || invalid ? faded(color) : color;
            button->ha_accent = true;
        }
        if (value && st->state[0])
            put_text(wide ? button->sub : button->label, wide ? sizeof(button->sub) : sizeof(button->label),
                     invalid ? "-" : st->state, invalid ? "" : spec->unit);
        break;
    }
    unlock();
}
