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
static deck_context_t s_context = {"LOKAL", "HOVED", false};
static uint32_t s_context_version = 1;

static deck_event_t s_events[DECK_EVENT_RING];
static int s_event_next; /* next write slot */
static int s_event_last_id;
static uint32_t s_events_total;

/* Pending key feedback: one slot, sequence-numbered so the UI can tell a
 * new request from one it already consumed. */
static struct {
    int button_id;
    deck_feedback_t kind;
    uint32_t seq;
} s_feedback;


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
        {1, "Bygg", "bolt", 0x35D07F},
        {2, "Kjør", "play", 0x35D07F},
        {3, "Test", "ok", 0x35D07F},
        {4, "Deploy", "upload", 0x35D07F},
        {5, "Git", "edit", 0x35D07F},
        {6, "Synk", "loop", 0x35D07F},
        {7, "Pause", "pause", 0xA3B2BC},
        {8, "Stopp", "stop", 0xFF7070},
        {9, "Logg", "list", 0x35D07F},
        {10, "Varsel", "bell", 0xFF7070},
        {11, "Rydd", "trash", 0xA3B2BC},
        {12, "Hjem", "home", 0x35D07F},
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

bool deck_model_replace_buttons(const deck_button_t *buttons, int count)
{
    if (!buttons || count < 0 || count > DECK_MAX_BUTTONS) return false;
    model_lock();
    /* The host re-pushes the whole layout on every refresh (dynamic titles,
     * page switches). Identical content must not re-render the grid. */
    if (count == s_button_count &&
        memcmp(s_buttons, buttons, sizeof(deck_button_t) * (size_t)count) == 0) {
        model_unlock();
        return true;
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

void deck_model_set_context(const char *profile, const char *page, bool can_go_back)
{
    deck_context_t next = {};
    copy_text(next.profile, sizeof(next.profile), profile ? profile : "LOKAL");
    copy_text(next.page, sizeof(next.page), page ? page : "HOVED");
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

uint32_t deck_model_record_press(int button_id)
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
    copy_text(slot->label, sizeof(slot->label), button->label);
    slot->timestamp_ms = esp_timer_get_time() / 1000;
    s_events_total++;
    uint32_t id = (uint32_t)slot->id;
    model_unlock();
    ESP_LOGI(TAG, "deck event #%d: %s (%d)", slot->id, slot->label, button_id);
    return id;
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
    s_feedback.button_id = button_id;
    s_feedback.kind = kind;
    s_feedback.seq++;
    model_unlock();
}

uint32_t deck_model_take_feedback(int *button_id, deck_feedback_t *kind)
{
    model_lock();
    uint32_t seq = s_feedback.seq;
    if (seq) {
        if (button_id) *button_id = s_feedback.button_id;
        if (kind) *kind = s_feedback.kind;
    }
    model_unlock();
    return seq;
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
        const cJSON *title = cJSON_GetObjectItemCaseSensitive(item, "title");
        const cJSON *size = cJSON_GetObjectItemCaseSensitive(title, "size");
        const cJSON *position = cJSON_GetObjectItemCaseSensitive(title, "position");
        if (cJSON_IsNumber(size)) {
            if (size->valueint != 16 && size->valueint != 20 && size->valueint != 24 && size->valueint != 28) {valid=false;break;}
            out[parsed].title_size=size->valueint;
        }
        out[parsed].title_bold=cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(title,"bold"));
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

