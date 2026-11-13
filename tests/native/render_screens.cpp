// Draws screens with the real panel UI. tools/render_screens.py writes the manifest this reads.
// Each manifest line is tab separated: "image id crc path" or "screen out-file json-file profile page back(0/1)".
#include <lvgl.h>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <sstream>
#include <string>
#include <vector>
#include "deck_images.h"
#include "deck_model.h"
#include "ui/ui.h"

static uint32_t tick = 10000;
static std::vector<uint8_t> pixels;
uint32_t millis() { return tick; }
extern "C" int64_t esp_timer_get_time() { return static_cast<int64_t>(tick) * 1000; }
extern "C" const char* time_service_time_text() { return "14:32"; }
extern "C" const char* time_service_date_text() { return "Tue 20 Oct 2026"; }
extern "C" const char* time_service_meridiem() { return ""; }

static void flush(lv_display_t* display, const lv_area_t* area, uint8_t* data) {
    const auto* source = reinterpret_cast<const uint32_t*>(data);
    int offset = 0;
    for (int y = area->y1; y <= area->y2; ++y)
        for (int x = area->x1; x <= area->x2; ++x) {
            const uint32_t value = source[offset++];
            uint8_t* to = &pixels[(static_cast<size_t>(y) * 1024 + x) * 3];
            to[0] = (value >> 16) & 255; to[1] = (value >> 8) & 255; to[2] = value & 255;
        }
    lv_display_flush_ready(display);
}

static void updates() {
    for (int i = 0; i < 6; ++i) { lv_timer_handler(); tick += 40; lv_tick_inc(40); }
    lv_refr_now(nullptr);
}

static std::string read_file(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    return {std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>()};
}

static bool upload(const std::string& id, const std::string& crc, const std::string& blob) {
    std::string reply;
    deck_image_command(("AD_IMG_BEGIN " + id + " " + std::to_string(blob.size()) + " " + crc).c_str(), reply);
    for (size_t at = 0; at < blob.size(); at += 160) {
        std::string hexed;
        for (size_t i = at; i < blob.size() && i < at + 160; ++i) {
            char two[3];
            snprintf(two, sizeof(two), "%02x", static_cast<uint8_t>(blob[i]));
            hexed += two;
        }
        deck_image_command(("AD_IMG_DATA " + std::to_string(at) + " " + hexed).c_str(), reply);
    }
    reply.clear();
    deck_image_command("AD_IMG_END", reply);
    return reply == "AD_IMG_END OK " + id;
}

static bool show(const std::string& json, const std::string& profile, const std::string& page, bool back) {
    static deck_button_t buttons[DECK_MAX_BUTTONS];
    int count = 0;
    memset(buttons, 0, sizeof(buttons));
    if (!deck_model_buttons_from_json(json.c_str(), buttons, DECK_MAX_BUTTONS, &count)) return false;
    if (!deck_model_replace_buttons(buttons, count)) return false;
    deck_model_set_context(profile.c_str(), page.c_str(), back);
    return true;
}

int main(int argc, char** argv) {
    if (argc != 2) { fprintf(stderr, "usage: render_screens manifest\n"); return 2; }
    lv_init();
    lv_tick_set_cb(millis);
    pixels.resize(1024 * 600 * 3);
    auto* display = lv_display_create(1024, 600);
    lv_display_set_color_format(display, LV_COLOR_FORMAT_XRGB8888);
    alignas(64) static uint32_t buffer[1024 * 600];
    lv_display_set_buffers(display, buffer, nullptr, sizeof(buffer), LV_DISPLAY_RENDER_MODE_FULL);
    lv_display_set_flush_cb(display, flush);
    lv_tick_inc(tick);
    deck_model_init();
    deck_model_note_host();
    ui_init();

    std::ifstream manifest(argv[1]);
    std::string line;
    int failures = 0;
    while (std::getline(manifest, line)) {
        std::vector<std::string> field;
        std::stringstream split(line);
        for (std::string part; std::getline(split, part, '\t');) field.push_back(part);
        if (field.size() == 4 && field[0] == "image") {
            if (!upload(field[1], field[2], read_file(field[3]))) { fprintf(stderr, "image refused: %s\n", field[1].c_str()); ++failures; }
        } else if (field.size() == 6 && field[0] == "screen") {
            if (!show(read_file(field[2]), field[3], field[4], field[5] == "1")) { fprintf(stderr, "layout refused: %s\n", field[2].c_str()); ++failures; continue; }
            deck_model_note_host();
            updates();
            std::ofstream out(field[1], std::ios::binary);
            out << "P6\n1024 600\n255\n";
            out.write(reinterpret_cast<const char*>(pixels.data()), static_cast<std::streamsize>(pixels.size()));
        }
    }
    return failures ? 1 : 0;
}
