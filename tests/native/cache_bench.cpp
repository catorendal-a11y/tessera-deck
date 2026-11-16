// Stands in for the panel in tests/cache_bench.py. It reads the host's lines on stdin and handles images and
// layouts, AD_CONTEXT and AD_FEEDBACK as main/main.cpp does, with the real image cache, model and UI; other lines
// are ignored. After each layout and the AD_CONTEXT that follows it, it draws and prints one line (a refused layout
// gets it at once, with paint_us 0):
//   BENCH {"paint_us":1234,"bytes":..,"count":..,"missing":[..],"evicted":[..]}
// paint_us is PC time, "missing" the layout's images the cache lacks (one per blank key), "evicted" the stored
// images the cache has dropped since the last report. "BENCH_TAP <id>" taps that key through the LVGL touch path
// and prints the press as the panel sends it, then BENCH {"tap":<id>}.
// Its get_info answer has "imgAck":1, so the host waits for image acknowledgements; --old-firmware leaves it out and
// the host paces image lines as it does for firmware without them.
#include <lvgl.h>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <set>
#include <string>
#include <vector>
#include "cJSON.h"
#include "deck_images.h"
#include "deck_model.h"
#include "protocol_version.h"
#include "ui/ui.h"

static uint32_t tick = 10000;
uint32_t millis() { return tick; }
extern "C" int64_t esp_timer_get_time() { return static_cast<int64_t>(tick) * 1000; }
extern "C" const char* time_service_time_text() { return "14:32"; }
extern "C" const char* time_service_date_text() { return "Tue 20 Oct 2026"; }
extern "C" const char* time_service_meridiem() { return ""; }

static void flush(lv_display_t* display, const lv_area_t*, uint8_t*) { lv_display_flush_ready(display); }
static void step() { lv_timer_handler(); tick += 40; lv_tick_inc(40); }

static bool touching = false;
static lv_point_t touch_at{};
static void touch_read(lv_indev_t*, lv_indev_data_t* data) {
    data->point = touch_at;
    data->state = touching ? LV_INDEV_STATE_PRESSED : LV_INDEV_STATE_RELEASED;
}

static void say(const std::string& line) { fputs((line + "\n").c_str(), stdout); fflush(stdout); }

// What the UI queued for the host (image requests among them) and the presses, as main.cpp sends them.
static int events_sent = 0;
static void send_queued() {
    char line[128];
    while (deck_model_take_line(line, sizeof(line))) say(line);
    deck_event_t events[8];
    const int count = deck_model_events_since(events_sent, events, 8);
    for (int i = 0; i < count; ++i) {
        cJSON* event = cJSON_CreateObject();
        cJSON_AddStringToObject(event, "type", "deck_event");
        cJSON_AddNumberToObject(event, "id", events[i].id);
        cJSON_AddNumberToObject(event, "button", events[i].button_id);
        cJSON_AddStringToObject(event, "label", events[i].label);
        if (events[i].hold) cJSON_AddTrueToObject(event, "hold");
        char* text = cJSON_PrintUnformatted(event);
        if (text) { say(text); cJSON_free(text); }
        cJSON_Delete(event);
        events_sent = events[i].id;
    }
}

static std::set<std::string> stored;  // images the cache took since they were last reported dropped
static std::string id_list(const std::vector<std::string>& ids) {
    std::string out;
    for (const auto& id : ids) out += (out.empty() ? "\"" : ",\"") + id + "\"";
    return "[" + out + "]";
}

static void report(long long paint_us, const std::vector<std::string>& icons) {
    size_t bytes = 0, count = 0;
    deck_image_cache_stats(&bytes, &count);
    std::vector<std::string> missing, evicted;
    for (const auto& id : icons)
        if (!id.compare(0, 3, "im:") && !deck_image_get(id.c_str())) missing.push_back(id);
    for (auto it = stored.begin(); it != stored.end();) {
        if (deck_image_get(it->c_str())) { ++it; continue; }
        evicted.push_back(*it);
        it = stored.erase(it);
    }
    say("BENCH {\"paint_us\":" + std::to_string(paint_us) + ",\"bytes\":" + std::to_string(bytes) + ",\"count\":" +
        std::to_string(count) + ",\"missing\":" + id_list(missing) + ",\"evicted\":" + id_list(evicted) + "}");
}

// AD_CFG_END: the calls main.cpp makes. The host sends AD_CONTEXT right after, and draw() runs then.
static std::vector<std::string> waiting;  // the icons of a layout the panel took and has not drawn yet
static bool layout_waiting = false;
static void layout(const std::string& json) {
    static deck_button_t buttons[DECK_MAX_BUTTONS];
    int count = 0;
    memset(buttons, 0, sizeof(buttons));
    if (!deck_model_buttons_from_json(json.c_str(), buttons, DECK_MAX_BUTTONS, &count) ||
        !deck_model_replace_buttons(buttons, count)) {
        say("AD_CFG_END INVALID");
        report(0, {});  // the host sees the refusal and logs it
        return;
    }
    std::vector<std::string> icons;
    for (int n = 0; n < count; ++n) icons.emplace_back(buttons[n].icon);
    deck_image_keep(icons);
    say("AD_CFG_END OK " + std::to_string(count));
    waiting = icons;
    layout_waiting = true;
}

// The time LVGL takes to rebuild (or update) the keys, show the page name and draw.
static void draw() {
    const auto start = std::chrono::steady_clock::now();
    step();  // the UI timer runs every 40 ms: one step takes up the new layout and context
    lv_refr_now(nullptr);
    const auto paint = std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now() - start);
    send_queued();
    report(paint.count(), waiting);
    layout_waiting = false;
}

static void tap(int id) {
    touch_at = {110 + ((id - 1) % 6) * 150 + 69, 72 + ((id - 1) / 6) * 172 + 80};  // the key's slot centre
    touching = true;
    for (int i = 0; i < 6; ++i) step();
    touching = false;
    for (int i = 0; i < 6; ++i) step();
    send_queued();
    say("BENCH {\"tap\":" + std::to_string(id) + "}");
}

int main(int argc, char** argv) {
    const bool old_firmware = argc > 1 && !strcmp(argv[1], "--old-firmware");
    lv_init();
    lv_tick_set_cb(millis);
    auto* display = lv_display_create(1024, 600);
    lv_display_set_color_format(display, LV_COLOR_FORMAT_XRGB8888);
    alignas(64) static uint32_t buffer[1024 * 600];
    lv_display_set_buffers(display, buffer, nullptr, sizeof(buffer), LV_DISPLAY_RENDER_MODE_FULL);
    lv_display_set_flush_cb(display, flush);
    lv_tick_inc(tick);
    deck_model_init();
    auto* touch = lv_indev_create();
    lv_indev_set_type(touch, LV_INDEV_TYPE_POINTER);
    lv_indev_set_read_cb(touch, touch_read);
    deck_model_note_host();
    ui_init();
    for (int i = 0; i < 6; ++i) step();

    std::string line, cfg;
    bool cfg_active = false;
    while (std::getline(std::cin, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        if (line.empty()) continue;
        deck_model_note_host();
        std::string reply;
        if (deck_image_command(line.c_str(), reply)) {
            if (!reply.compare(0, 14, "AD_IMG_END OK ")) stored.insert(reply.substr(14));
            if (!reply.empty()) say(reply);
        } else if (line == "{\"cmd\":\"get_info\"}") {
            say("{\"type\":\"info\",\"boardId\":\"tessera-p4\",\"firmwareVersion\":\"cache-bench\",\"protocol\":" +
                std::to_string(TESSERA_PROTOCOL) + ",\"bootId\":1" + (old_firmware ? "}" : ",\"imgAck\":1}"));
        } else if (line == "AD_CFG_BEGIN") {
            cfg_active = true;
            cfg.clear();
            say("AD_CFG_BEGIN OK");
        } else if (!line.compare(0, 12, "AD_CFG_DATA ") && cfg_active) {
            cfg += line.substr(12);
        } else if (line == "AD_CFG_END") {
            if (cfg_active) layout(cfg);
            else { say("AD_CFG_END INVALID"); report(0, {}); }
            cfg_active = false;
        } else if (!line.compare(0, 11, "AD_CONTEXT ")) {
            cJSON* context = cJSON_Parse(line.c_str() + 11);
            const cJSON* profile = cJSON_GetObjectItemCaseSensitive(context, "profile");
            const cJSON* page = cJSON_GetObjectItemCaseSensitive(context, "page");
            const cJSON* back = cJSON_GetObjectItemCaseSensitive(context, "canBack");
            if (cJSON_IsString(profile) && cJSON_IsString(page)) {
                deck_model_set_context(profile->valuestring, page->valuestring, cJSON_IsTrue(back));
                say("AD_CONTEXT OK");
            } else {
                say("AD_CONTEXT INVALID");
            }
            cJSON_Delete(context);
            if (layout_waiting) draw();
        } else if (!line.compare(0, 12, "AD_FEEDBACK ")) {
            char kind[8] = {};
            int id = 0;
            if (sscanf(line.c_str() + 12, "%7s %d", kind, &id) == 2 && id > 0) {
                deck_model_request_feedback(id, strcmp(kind, "alert") == 0 ? DECK_FEEDBACK_ALERT : DECK_FEEDBACK_OK);
                say("AD_FEEDBACK OK");
            } else {
                say("AD_FEEDBACK INVALID");
            }
        } else if (!line.compare(0, 10, "BENCH_TAP ")) {
            tap(atoi(line.c_str() + 10));
        }
    }
    return 0;
}
