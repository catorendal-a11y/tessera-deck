#include "deck_model.h"

#include <string.h>

#include "cJSON.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

static const char *TAG = "deck_model";

static SemaphoreHandle_t s_lock;
static deck_button_t s_buttons[DECK_MAX_BUTTONS];
static int s_button_count;
static uint32_t s_buttons_version = 1;
static uint32_t s_live_version = 1;
static deck_context_t s_context = {"LOCAL", "MAIN", false};
static uint32_t s_context_version = 1;

static deck_event_t s_events[DECK_EVENT_RING];
static int s_event_next; /* next write slot */
static int s_event_last_id;
static uint32_t s_events_total;

/* Pending key feedback: a small FIFO so two confirmations inside one UI
 * tick (a key that presses another key) both flash. */
#define DECK_FEEDBACK_QUEUE 8
static struct {
    int button_id;
    deck_feedback_t kind;
    uint32_t seq;
} s_feedback[DECK_FEEDBACK_QUEUE];
static int s_feedback_head, s_feedback_count;
static uint32_t s_feedback_seq;

static bool s_dimmed;
static uint32_t s_wake_seq;
static int64_t s_host_seen_ms = -1;

/* Copy at most dst_size-1 bytes and always NUL-terminate; returns false
 * when the source was truncated so callers can log it. */
static bool copy_text(char *dst, size_t dst_size, const char *src)
{
    if (!src) return false;
    size_t len = strlen(src);
    bool full = len < dst_size;
    if (!full) {
        len = dst_size - 1;
        while (len > 0 && ((unsigned char)src[len] & 0xC0) == 0x80) --len;
    }
    memcpy(dst, src, len);
    dst[len] = '\0';
    /* LVGL does not render control characters; flatten them. */
    for (size_t i = 0; i < len; ++i) {
        unsigned char c = (unsigned char)dst[i];
        if (c < 0x20) dst[i] = ' ';
    }
    return full;
}

static void model_lock(void)
{
    if (s_lock) xSemaphoreTake(s_lock, portMAX_DELAY);
}

static void model_unlock(void)
{
    if (s_lock) xSemaphoreGive(s_lock);
}

void deck_model_init(void)
{
    if (!s_lock) s_lock = xSemaphoreCreateMutex();
    model_lock();
    model_unlock();
    deck_model_defaults();
    ESP_LOGI(TAG, "model ready (%d buttons)", s_button_count);
}

void deck_model_defaults(void)
{
    /* A practical starter deck for a dev panel; the host script can
     * replace the whole set at runtime over POST /api/deck/config.
     * Colors use accent green, muted gray and error red. */
    static const deck_button_t defaults[] = {
        {1, "Build", "bolt", 0x35D07F},
        {2, "Run", "play", 0x35D07F},
        {3, "Test", "ok", 0x35D07F},
        {4, "Deploy", "upload", 0x35D07F},
        {5, "Git", "edit", 0x35D07F},
        {6, "Sync", "loop", 0x35D07F},
        {7, "Pause", "pause", 0xA3B2BC},
        {8, "Stop", "stop", 0xFF7070},
        {9, "Log", "list", 0x35D07F},
        {10, "Alert", "bell", 0xFF7070},
        {11, "Clean", "trash", 0xA3B2BC},
        {12, "Home", "home", 0x35D07F},
    };
    model_lock();
    s_button_count = (int)(sizeof(defaults) / sizeof(defaults[0]));
    memcpy(s_buttons, defaults, sizeof(defaults));
    s_buttons_version++;
    model_unlock();
}

int deck_model_button_count(void)
{
    model_lock();
    int count = s_button_count;
    model_unlock();
    return count;
}

bool deck_model_get_button(int index, deck_button_t *out)
{
    if (!out || index < 0) return false;
    model_lock();
    bool ok = index < s_button_count;
    if (ok) *out = s_buttons[index];
    model_unlock();
    return ok;
}

/* Same tile layout; label text, color and gauge values may differ. */
static bool same_structure(const deck_button_t *a, const deck_button_t *b)
{
    deck_button_t x = *a, y = *b;
    x.gauge_percent = y.gauge_percent = 0;
    memset(x.gauge_text, 0, sizeof(x.gauge_text));
    memset(y.gauge_text, 0, sizeof(y.gauge_text));
    memset(x.label, 0, sizeof(x.label));
    memset(y.label, 0, sizeof(y.label));
    x.color = y.color = 0;
    return memcmp(&x, &y, sizeof(x)) == 0;
}

bool deck_model_replace_buttons(const deck_button_t *buttons, int count)
{
    if (!buttons || count < 0 || count > DECK_MAX_BUTTONS) return false;
    model_lock();
    /* The host re-pushes the whole layout on every refresh (dynamic titles,
     * page switches). Identical content must not re-render the grid, and
     * changing gauge values must not tear down the tile under a finger. */
    if (count == s_button_count) {
        bool same = true;
        for (int i = 0; same && i < count; ++i) same = same_structure(&s_buttons[i], &buttons[i]);
        if (same) {
            if (memcmp(s_buttons, buttons, sizeof(deck_button_t) * (size_t)count) != 0) {
                memcpy(s_buttons, buttons, sizeof(deck_button_t) * (size_t)count);
                s_live_version++;
            }
            model_unlock();
            return true;
        }
    }
    s_button_count = count;
    memcpy(s_buttons, buttons, sizeof(deck_button_t) * (size_t)count);
    s_buttons_version++;
    model_unlock();
    return true;
}

uint32_t deck_model_buttons_version(void)
{
    return s_buttons_version; /* atomic-enough read of a uint32 */
}

uint32_t deck_model_live_version(void)
{
    return s_live_version;
}

void deck_model_set_context(const char *profile, const char *page, bool can_go_back)
{
    deck_context_t next = {};
    copy_text(next.profile, sizeof(next.profile), profile ? profile : "LOCAL");
    copy_text(next.page, sizeof(next.page), page ? page : "MAIN");
    next.can_go_back = can_go_back;
    model_lock();
    if (memcmp(&next, &s_context, sizeof(next)) != 0) {
        s_context = next;
        ++s_context_version;
    }
    model_unlock();
}

deck_context_t deck_model_context(void)
{
    model_lock(); deck_context_t copy=s_context; model_unlock(); return copy;
}

uint32_t deck_model_context_version(void) { return s_context_version; }

static uint32_t record_event(int button_id, bool hold)
{
    model_lock();
    deck_button_t *button = NULL;
    for (int i = 0; i < s_button_count; ++i) {
        if (s_buttons[i].id == button_id) {
            button = &s_buttons[i];
            break;
        }
    }
    if (!button) {
        model_unlock();
        ESP_LOGW(TAG, "press for unknown button id %d", button_id);
        return 0;
    }
    deck_event_t *slot = &s_events[s_event_next];
    s_event_next = (s_event_next + 1) % DECK_EVENT_RING;
    slot->id = ++s_event_last_id;
    slot->button_id = button_id;
    slot->hold = hold;
    copy_text(slot->label, sizeof(slot->label), button->label);
    slot->timestamp_ms = esp_timer_get_time() / 1000;
    s_events_total++;
    uint32_t id = (uint32_t)slot->id;
    char label[sizeof(slot->label)];
    memcpy(label, slot->label, sizeof(label));
    model_unlock();
    /* Log from the local copy: another task may recycle the ring slot once unlocked. */
    ESP_LOGI(TAG, "deck event #%u: %s (%d)", (unsigned)id, label, button_id);
    return id;
}

uint32_t deck_model_record_press(int button_id)
{
    return record_event(button_id, false);
}

uint32_t deck_model_record_hold(int button_id)
{
    return record_event(button_id, true);
}

int deck_model_events_since(int since_id, deck_event_t *out, int max_out)
{
    if (!out || max_out <= 0) return 0;
    model_lock();
    int written = 0;
    /* Ring holds the newest DECK_EVENT_RING events; walk oldest first. */
    for (int i = DECK_EVENT_RING; i > 0 && written < max_out; --i) {
        const deck_event_t *slot = &s_events[(s_event_next + DECK_EVENT_RING - i) % DECK_EVENT_RING];
        if (slot->id <= 0 || slot->id <= since_id) continue;
        out[written++] = *slot;
    }
    model_unlock();
    return written;
}

int deck_model_last_event_id(void)
{
    model_lock();
    int id = s_event_last_id;
    model_unlock();
    return id;
}

uint32_t deck_model_events_total(void)
{
    return s_events_total;
}

void deck_model_request_feedback(int button_id, deck_feedback_t kind)
{
    model_lock();
    if (s_feedback_count == DECK_FEEDBACK_QUEUE) { /* drop the oldest */
        s_feedback_head = (s_feedback_head + 1) % DECK_FEEDBACK_QUEUE;
        --s_feedback_count;
    }
    int at = (s_feedback_head + s_feedback_count) % DECK_FEEDBACK_QUEUE;
    s_feedback[at].button_id = button_id;
    s_feedback[at].kind = kind;
    s_feedback[at].seq = ++s_feedback_seq;
    ++s_feedback_count;
    model_unlock();
}

uint32_t deck_model_take_feedback(int *button_id, deck_feedback_t *kind)
{
    model_lock();
    uint32_t seq = 0;
    if (s_feedback_count) {
        seq = s_feedback[s_feedback_head].seq;
        if (button_id) *button_id = s_feedback[s_feedback_head].button_id;
        if (kind) *kind = s_feedback[s_feedback_head].kind;
        s_feedback_head = (s_feedback_head + 1) % DECK_FEEDBACK_QUEUE;
        --s_feedback_count;
    }
    model_unlock();
    return seq;
}

void deck_model_set_dimmed(bool dimmed)
{
    model_lock(); s_dimmed = dimmed; model_unlock();
}

bool deck_model_dimmed(void)
{
    model_lock(); bool dimmed = s_dimmed; model_unlock(); return dimmed;
}

static int s_screen_request = -1;
static deck_screen_t s_screen = DECK_SCREEN_DECK;
static bool s_touch_return;
static char s_ambient[DECK_AMBIENT_MAX + 1];
static uint32_t s_ambient_version = 1;

void deck_model_request_screen(deck_screen_t screen)
{
    model_lock(); s_screen_request = screen; model_unlock();
}

int deck_model_take_screen_request(void)
{
    model_lock(); int request = s_screen_request; s_screen_request = -1; model_unlock();
    return request;
}

void deck_model_set_screen(deck_screen_t screen)
{
    model_lock(); s_screen = screen; model_unlock();
}

deck_screen_t deck_model_screen(void)
{
    model_lock(); deck_screen_t screen = s_screen; model_unlock(); return screen;
}

void deck_model_note_touch_return(void)
{
    model_lock(); s_touch_return = true; model_unlock();
}

bool deck_model_take_touch_return(void)
{
    model_lock(); bool value = s_touch_return; s_touch_return = false; model_unlock();
    return value;
}

void deck_model_set_ambient(const char *line)
{
    model_lock();
    if (strncmp(s_ambient, line ? line : "", sizeof(s_ambient)) != 0) {
        copy_text(s_ambient, sizeof(s_ambient), line ? line : "");
        ++s_ambient_version;
    }
    model_unlock();
}

void deck_model_ambient(char *out, size_t size)
{
    model_lock(); copy_text(out, size, s_ambient); model_unlock();
}

uint32_t deck_model_ambient_version(void)
{
    model_lock(); uint32_t version = s_ambient_version; model_unlock();
    return version;
}

void deck_model_request_wake(void)
{
    model_lock(); s_dimmed = false; ++s_wake_seq; model_unlock();
}

uint32_t deck_model_wake_sequence(void)
{
    model_lock(); uint32_t seq = s_wake_seq; model_unlock(); return seq;
}

void deck_model_note_host(void)
{
    int64_t now = esp_timer_get_time() / 1000;
    model_lock(); s_host_seen_ms = now; model_unlock();
}

bool deck_model_host_linked(int64_t timeout_ms)
{
    int64_t now = esp_timer_get_time() / 1000;
    model_lock(); int64_t seen = s_host_seen_ms; model_unlock();
    return seen >= 0 && now - seen <= timeout_ms;
}

static bool parse_color_hex(const char *text, uint32_t *out)
{
    if (!text) return false;
    while (*text == ' ') ++text;
    if (text[0] == '#') ++text;
    if (strlen(text) != 6) return false;
    uint32_t value = 0;
    for (int i = 0; i < 6; ++i) {
        char c = text[i];
        int digit = c >= '0' && c <= '9' ? c - '0' :
                    c >= 'a' && c <= 'f' ? c - 'a' + 10 :
                    c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
        if (digit < 0) return false;
        value = (value << 4) | (uint32_t)digit;
    }
    *out = value;
    return true;
}

bool deck_model_buttons_from_json(const char *json_text, deck_button_t *out,
                                  int max_out, int *count)
{
    if (!json_text || !out || max_out <= 0 || !count) return false;
    cJSON *json = cJSON_Parse(json_text);
    if (!json) return false;
    const cJSON *buttons = cJSON_GetObjectItemCaseSensitive(json, "buttons");
    bool valid = cJSON_IsArray(buttons) && cJSON_GetArraySize(buttons) <= max_out;
    int parsed = 0;
    for (cJSON *item = valid ? buttons->child : NULL; item && parsed < max_out;
         item = item->next) {
        const cJSON *id = cJSON_GetObjectItemCaseSensitive(item, "id");
        const cJSON *label = cJSON_GetObjectItemCaseSensitive(item, "label");
        const cJSON *icon = cJSON_GetObjectItemCaseSensitive(item, "icon");
        const cJSON *color = cJSON_GetObjectItemCaseSensitive(item, "color");
        if (!cJSON_IsNumber(id) || id->valuedouble < 1 || id->valuedouble > DECK_MAX_BUTTONS ||
            id->valuedouble != (int)id->valuedouble ||
            !cJSON_IsString(label) || label->valuestring[0] == '\0') {
            valid = false;
            break;
        }
        for (int previous = 0; previous < parsed; ++previous)
            if (out[previous].id == (int)id->valuedouble) valid = false;
        if (!valid) break;
        memset(&out[parsed], 0, sizeof(out[parsed]));
        out[parsed].id = (int)id->valuedouble;
        copy_text(out[parsed].label, sizeof(out[parsed].label), label->valuestring);
        snprintf(out[parsed].icon, sizeof(out[parsed].icon), "%s",
                 cJSON_IsString(icon) && icon->valuestring[0] ? icon->valuestring : "ok");
        uint32_t color_value = 0x35D07F;
        if (color && (!cJSON_IsString(color) || !parse_color_hex(color->valuestring, &color_value))) {
            valid = false;
            break;
        }
        out[parsed].color = color_value;
        const cJSON *gauge = cJSON_GetObjectItemCaseSensitive(item, "gauge");
        if (cJSON_IsObject(gauge)) {
            const cJSON *percent = cJSON_GetObjectItemCaseSensitive(gauge, "p");
            const cJSON *gauge_text = cJSON_GetObjectItemCaseSensitive(gauge, "t");
            if (!cJSON_IsNumber(percent) || !cJSON_IsString(gauge_text)) {valid = false; break;}
            out[parsed].has_gauge = true;
            out[parsed].gauge_percent = (uint8_t)(percent->valuedouble < 0 ? 0 : percent->valuedouble > 100 ? 100 : percent->valuedouble);
            copy_text(out[parsed].gauge_text, sizeof(out[parsed].gauge_text), gauge_text->valuestring);
            const cJSON *badge = cJSON_GetObjectItemCaseSensitive(gauge, "b");
            if (cJSON_IsString(badge)) snprintf(out[parsed].gauge_badge, sizeof(out[parsed].gauge_badge), "%s", badge->valuestring);
        }
        const cJSON *title = cJSON_GetObjectItemCaseSensitive(item, "title");
        const cJSON *size = cJSON_GetObjectItemCaseSensitive(title, "size");
        const cJSON *position = cJSON_GetObjectItemCaseSensitive(title, "position");
        if (cJSON_IsNumber(size)) {
            if (size->valueint != 16 && size->valueint != 20 && size->valueint != 24 && size->valueint != 28) {valid=false;break;}
            out[parsed].title_size=size->valueint;
        }
        out[parsed].title_bold=cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(title,"bold"));
        out[parsed].has_hold=cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(item,"hold"));
        out[parsed].has_double=cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(item,"double"));
        {
            const struct {const char *key; uint8_t bit; uint32_t *target;} styles[] = {
                {"bg", DECK_STYLE_BG, &out[parsed].bg}, {"text_color", DECK_STYLE_TEXT, &out[parsed].text},
                {"border", DECK_STYLE_BORDER, &out[parsed].border}};
            for (size_t s = 0; s < sizeof(styles) / sizeof(styles[0]); ++s) {
                const cJSON *value = cJSON_GetObjectItemCaseSensitive(item, styles[s].key);
                if (!value) continue;
                if (!cJSON_IsString(value) || !parse_color_hex(value->valuestring, styles[s].target)) {valid = false; break;}
                out[parsed].style |= styles[s].bit;
            }
            if (!valid) break;
        }
        if (cJSON_IsString(position)) {
            if (!strcmp(position->valuestring,"top")) out[parsed].title_position=1;
            else if (!strcmp(position->valuestring,"middle")) out[parsed].title_position=2;
            else if (!strcmp(position->valuestring,"hidden")) out[parsed].title_position=3;
            else if (strcmp(position->valuestring,"bottom")) {valid=false;break;}
        }
        ++parsed;
    }
    cJSON_Delete(json);
    if (!valid) return false;
    *count = parsed;
    return true;
}

