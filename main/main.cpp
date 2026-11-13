#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "lvgl.h"
#include "bsp/esp-bsp.h"
#include "bsp/display.h"

#include <cstdint>
#include <cstdlib>
#include <cstdio>
#include <cstring>
#include <cerrno>
#include <fcntl.h>
#include "cJSON.h"
#include "esp_heap_caps.h"
#include "esp_app_desc.h"
#include "esp_timer.h"
#include "deck_images.h"
#include "protocol_version.h"
#include "driver/usb_serial_jtag.h"
#include "driver/usb_serial_jtag_vfs.h"
#include "esp_system.h"
#include "esp_random.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "esp_ota_ops.h"
#include "esp_spiffs.h"
#include "esp_task_wdt.h"
#include "psa/crypto.h"
#include <atomic>
#include <ctime>
#include <sys/stat.h>
#include <unistd.h>

extern "C" {
#include "deck_model.h"
#include "time_service.h"
#include "ui/ui.h"
}

static const char *TAG = "tessera";
/* Backlight level restored by AD_DISPLAY_WAKE; set by the host with AD_BRIGHTNESS
 * and kept in NVS so the panel boots at the chosen level, not at full power. */
static int s_brightness = 100;
static const char *SETTINGS_NAMESPACE = "tessera";

static void load_brightness(void)
{
    nvs_handle_t handle;
    uint8_t value = 0;
    if (nvs_open(SETTINGS_NAMESPACE, NVS_READONLY, &handle) != ESP_OK) return;
    if (nvs_get_u8(handle, "brightness", &value) == ESP_OK && value >= 1 && value <= 100) s_brightness = value;
    nvs_close(handle);
}

static void save_brightness(int level)
{
    nvs_handle_t handle;
    uint8_t stored = 0;
    if (nvs_open(SETTINGS_NAMESPACE, NVS_READWRITE, &handle) != ESP_OK) return;
    /* The host repeats the level on every connect; only write real changes. */
    if (nvs_get_u8(handle, "brightness", &stored) != ESP_OK || stored != level) {
        if (nvs_set_u8(handle, "brightness", static_cast<uint8_t>(level)) == ESP_OK) nvs_commit(handle);
    }
    nvs_close(handle);
}

/* Offline resilience: the last layout the host pushed is kept as a file on the storage partition, with the
 * previous good copy beside it, so a panel that boots without the PC shows its keys instead of the factory sample.
 * Flash is written rarely: only when the key structure changed (not for every live label) and at most once per
 * LAYOUT_SAVE_INTERVAL_US. */
static const char *STORE_PATH = "/store", *STORE_LABEL = "storage";
static const char *LAYOUT_FILE = "/store/layout.json", *LAYOUT_BACKUP = "/store/layout.bak",
                  *LAYOUT_TEMP = "/store/layout.tmp";
static constexpr size_t LAYOUT_MAX = 8192;  /* all one AD_CFG push can carry (cfg_buf), so every layout is kept */
static constexpr int64_t LAYOUT_SAVE_INTERVAL_US = 10LL * 60 * 1000000;
static std::string s_layout_pending;
static uint32_t s_layout_version_seen = 0, s_layout_version_saved = 0;
static int64_t s_layout_saved_at = -LAYOUT_SAVE_INTERVAL_US;
static int64_t s_layout_saved_unix = 0;  /* reported as layoutSaved; 0 while unknown */
static std::atomic<bool> s_store_ready{false};

static esp_err_t store_register(bool format)
{
    esp_vfs_spiffs_conf_t conf = {};
    conf.base_path = STORE_PATH;
    conf.partition_label = STORE_LABEL;
    conf.max_files = 4;
    conf.format_if_mount_failed = format;
    return esp_vfs_spiffs_register(&conf);
}

/* Formatting the empty 4 MB partition after a full install takes tens of seconds: do it off the boot path. */
static void store_format_task(void *)
{
    const esp_err_t result = store_register(true);
    s_store_ready = result == ESP_OK;
    if (result != ESP_OK) ESP_LOGW(TAG, "storage partition unavailable: %s", esp_err_to_name(result));
    vTaskDelete(nullptr);
}

static void store_mount(void)
{
    if (store_register(false) == ESP_OK) s_store_ready = true;
    else if (xTaskCreate(store_format_task, "ad_store_fmt", 4096, nullptr, 1, nullptr) != pdPASS)
        ESP_LOGW(TAG, "storage partition not mounted");
}

static int64_t unix_now(void)
{
    const time_t now = time(nullptr);
    return now > 1600000000 ? static_cast<int64_t>(now) : 0;  /* before the host set the clock it is 1970 */
}

static bool layout_write(const std::string &json)
{
    FILE *file = fopen(LAYOUT_TEMP, "wb");
    if (!file) return false;
    bool ok = fwrite(json.data(), 1, json.size(), file) == json.size();
    ok = fclose(file) == 0 && ok;
    if (!ok) { unlink(LAYOUT_TEMP); return false; }
    /* The current file was a layout the panel accepted: it becomes the previous good copy. */
    unlink(LAYOUT_BACKUP);
    rename(LAYOUT_FILE, LAYOUT_BACKUP);  /* fails harmlessly when nothing was saved yet */
    return rename(LAYOUT_TEMP, LAYOUT_FILE) == 0;
}

static void layout_remember(const char *json)
{
    const uint32_t version = deck_model_buttons_version();
    if (version == s_layout_version_saved) return;  /* only live values changed */
    s_layout_pending = json;
    s_layout_version_seen = version;
}

static void layout_flush_if_due(void)
{
    if (s_layout_pending.empty() || s_layout_version_seen == s_layout_version_saved || !s_store_ready) return;
    const int64_t now = esp_timer_get_time();
    if (now - s_layout_saved_at < LAYOUT_SAVE_INTERVAL_US) return;
    s_layout_saved_at = now;  /* a failed save is tried again next interval */
    if (layout_write(s_layout_pending)) {
        s_layout_version_saved = s_layout_version_seen;
        s_layout_saved_unix = unix_now();
    } else {
        ESP_LOGW(TAG, "could not save the layout for offline use");
    }
}

static bool layout_load(const char *path)
{
    FILE *file = fopen(path, "rb");
    if (!file) return false;
    std::string json(LAYOUT_MAX + 1, '\0');
    const size_t size = fread(json.data(), 1, LAYOUT_MAX + 1, file);
    fclose(file);
    if (size == 0 || size > LAYOUT_MAX) return false;
    json.resize(size);
    deck_button_t buttons[DECK_MAX_BUTTONS];
    int count = 0;
    if (!deck_model_buttons_from_json(json.c_str(), buttons, DECK_MAX_BUTTONS, &count) ||
        !deck_model_replace_buttons(buttons, count)) return false;
    struct stat info = {};
    if (stat(path, &info) == 0 && info.st_mtime > 1600000000) s_layout_saved_unix = info.st_mtime;
    ESP_LOGI(TAG, "restored the last layout from %s: %d buttons", path, count);
    s_layout_version_saved = deck_model_buttons_version();
    return true;
}

static void layout_restore(void)
{
    if (s_store_ready && !layout_load(LAYOUT_FILE)) layout_load(LAYOUT_BACKUP);  /* a torn save falls back */
}

/* esp_reset_reason() as the handshake's "reset" word; the host warns about the crash-like ones. */
static const char *reset_reason_name(void)
{
    switch (esp_reset_reason()) {
    case ESP_RST_POWERON: return "poweron";
    case ESP_RST_SW: return "sw";
    case ESP_RST_PANIC: case ESP_RST_CPU_LOCKUP: return "panic";
    case ESP_RST_INT_WDT: return "int_wdt";
    case ESP_RST_TASK_WDT: return "task_wdt";
    case ESP_RST_WDT: return "wdt";
    case ESP_RST_BROWNOUT: case ESP_RST_PWR_GLITCH: return "brownout";
    case ESP_RST_DEEPSLEEP: return "deepsleep";
    case ESP_RST_EXT: case ESP_RST_USB: case ESP_RST_JTAG: return "ext";  /* esptool resets over USB */
    default: return "unknown";
    }
}

/* A firmware booted from a fresh OTA slot is on probation: confirm it once the host talked to it (or it ran for
 * a minute), otherwise the bootloader returns to the previous slot on the next reset. */
static bool s_app_confirmed = false;
static void app_confirm(void)
{
    if (s_app_confirmed) return;
    s_app_confirmed = true;
    const esp_err_t result = esp_ota_mark_app_valid_cancel_rollback();
    if (result != ESP_OK) ESP_LOGW(TAG, "could not confirm this firmware: %s", esp_err_to_name(result));
}

/* Over-USB update: AD_OTA_BEGIN <size> <sha256hex>, AD_OTA_DATA <offset> <hex> (in order, at most OTA_CHUNK bytes),
 * AD_OTA_END. The image goes into the idle slot; only a complete image with the right SHA-256 that ESP-IDF also
 * verifies becomes the boot slot. Data is acknowledged every OTA_ACK_BYTES, which paces the host. */
static constexpr size_t OTA_CHUNK = 512, OTA_ACK_BYTES = 2048;  /* OTA_CHUNK, OTA_WINDOW in host/panel_serial.py */
struct OtaJob {
    esp_ota_handle_t handle = 0;
    const esp_partition_t *slot = nullptr;
    size_t size = 0, received = 0;
    uint8_t sha[32] = {};
    psa_hash_operation_t hash = PSA_HASH_OPERATION_INIT;
    bool active = false;
};
static OtaJob s_ota;

static void ota_abort(void)
{
    if (s_ota.active) {
        esp_ota_abort(s_ota.handle);
        psa_hash_abort(&s_ota.hash);
    }
    s_ota.active = false;
}

static int hex_value(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

/* Decodes exactly strlen(hex)/2 bytes into out; false for odd length, too much data or a non-hex digit. */
static bool hex_decode(const char *hex, uint8_t *out, size_t capacity, size_t *length)
{
    const size_t digits = strlen(hex);
    if (digits % 2 || digits / 2 > capacity) return false;
    for (size_t i = 0; i < digits / 2; ++i) {
        const int high = hex_value(hex[2 * i]), low = hex_value(hex[2 * i + 1]);
        if (high < 0 || low < 0) return false;
        out[i] = static_cast<uint8_t>(high << 4 | low);
    }
    *length = digits / 2;
    return true;
}

static void ota_reply(const char *command, const char *result)
{
    printf("%s %s\n", command, result);
    fflush(stdout);
}

static void ota_begin(const char *args)
{
    unsigned size = 0;
    char digest[65] = {};
    char extra = 0;
    ota_abort();
    s_ota.slot = esp_ota_get_next_update_partition(nullptr);
    size_t sha_length = 0;
    if (sscanf(args, "%u %64s %c", &size, digest, &extra) != 2 || strlen(digest) != 64 ||
        !hex_decode(digest, s_ota.sha, sizeof(s_ota.sha), &sha_length)) return ota_reply("AD_OTA_BEGIN", "FAIL usage");
    if (!s_ota.slot) return ota_reply("AD_OTA_BEGIN", "FAIL no_slot");
    if (size == 0 || size > s_ota.slot->size) return ota_reply("AD_OTA_BEGIN", "FAIL too_big");
    /* Sequential writes erase one sector at a time, so no single call blocks the task for seconds. */
    esp_err_t result = esp_ota_begin(s_ota.slot, OTA_WITH_SEQUENTIAL_WRITES, &s_ota.handle);
    if (result != ESP_OK) return ota_reply("AD_OTA_BEGIN", "FAIL begin");
    s_ota.hash = PSA_HASH_OPERATION_INIT;
    if (psa_hash_setup(&s_ota.hash, PSA_ALG_SHA_256) != PSA_SUCCESS) {
        esp_ota_abort(s_ota.handle);
        return ota_reply("AD_OTA_BEGIN", "FAIL hash");
    }
    s_ota.size = size;
    s_ota.received = 0;
    s_ota.active = true;
    ESP_LOGI(TAG, "receiving %u bytes of firmware into %s", size, s_ota.slot->label);
    ota_reply("AD_OTA_BEGIN", "OK");
}

static void ota_data(char *args)
{
    if (!s_ota.active) return ota_reply("AD_OTA_DATA", "FAIL not_started");
    char *end = nullptr;
    const unsigned long offset = strtoul(args, &end, 10);
    if (end == args || *end != ' ') { ota_abort(); return ota_reply("AD_OTA_DATA", "FAIL usage"); }
    if (offset != s_ota.received) { ota_abort(); return ota_reply("AD_OTA_DATA", "FAIL offset"); }
    uint8_t chunk[OTA_CHUNK];
    size_t length = 0;
    if (!hex_decode(end + 1, chunk, sizeof(chunk), &length) || length == 0) {
        ota_abort();
        return ota_reply("AD_OTA_DATA", "FAIL data");
    }
    if (s_ota.received + length > s_ota.size) { ota_abort(); return ota_reply("AD_OTA_DATA", "FAIL too_long"); }
    if (esp_ota_write(s_ota.handle, chunk, length) != ESP_OK ||
        psa_hash_update(&s_ota.hash, chunk, length) != PSA_SUCCESS) {
        ota_abort();
        return ota_reply("AD_OTA_DATA", "FAIL write");
    }
    s_ota.received += length;
    if (s_ota.received % OTA_ACK_BYTES == 0 || s_ota.received == s_ota.size) {
        printf("AD_OTA_DATA OK %u\n", static_cast<unsigned>(s_ota.received));
        fflush(stdout);
    }
}

static void ota_end(void)
{
    if (!s_ota.active || s_ota.received != s_ota.size) { ota_abort(); return ota_reply("AD_OTA_END", "FAIL incomplete"); }
    uint8_t digest[32];
    size_t digest_length = 0;
    const bool hashed = psa_hash_finish(&s_ota.hash, digest, sizeof(digest), &digest_length) == PSA_SUCCESS;
    s_ota.active = false;
    if (!hashed || digest_length != sizeof(digest) || memcmp(digest, s_ota.sha, sizeof(digest))) {
        esp_ota_abort(s_ota.handle);
        return ota_reply("AD_OTA_END", "FAIL checksum");
    }
    if (esp_ota_end(s_ota.handle) != ESP_OK) return ota_reply("AD_OTA_END", "FAIL invalid_image");
    if (esp_ota_set_boot_partition(s_ota.slot) != ESP_OK) return ota_reply("AD_OTA_END", "FAIL boot_slot");
    ota_reply("AD_OTA_END", "OK");
    ESP_LOGI(TAG, "firmware update written to %s; restarting", s_ota.slot->label);
    vTaskDelay(pdMS_TO_TICKS(300));  /* let the answer leave over USB */
    esp_restart();
}

static void ota_command(char *line)
{
    if (!strncmp(line, "AD_OTA_BEGIN ", 13)) ota_begin(line + 13);
    else if (!strncmp(line, "AD_OTA_DATA ", 12)) ota_data(line + 12);
    else if (!strcmp(line, "AD_OTA_END")) ota_end();
    else if (!strcmp(line, "AD_OTA_ABORT")) { ota_abort(); ota_reply("AD_OTA_ABORT", "OK"); }
    else ota_reply(line, "INVALID");
}

/* The LVGL task belongs to esp_lvgl_port, so it is watched from a timer that runs in it: a UI stuck for
 * CONFIG_ESP_TASK_WDT_TIMEOUT_S restarts the panel. */
static void lvgl_watchdog(lv_timer_t *)
{
    static bool subscribed = false;
    if (!subscribed) subscribed = esp_task_wdt_add(nullptr) == ESP_OK;
    if (subscribed) esp_task_wdt_reset();
}

/* Parse "<digits>" within [low, high]; returns false for anything else. */
static bool parse_percent(const char *text, long low, long high, int *out)
{
    char *end = nullptr;
    long value = strtol(text, &end, 10);
    if (end == text || *end != '\0' || value < low || value > high) return false;
    *out = static_cast<int>(value);
    return true;
}
/* USB console: line protocol with the Windows host. The panel has no network
 * stack; USB is the only transport. */
static void usb_console_task(void *)
{
    static uint8_t received[2048];
    int rx_size = 0, rx_at = 0;
    char line[1100];
    size_t used = 0;
    bool overflow = false;
    int deck_events_emitted = 0;
    /* Accumulator for the chunked AD_CFG_BEGIN/DATA/END config push. */
    static char *cfg_buf = static_cast<char *>(heap_caps_calloc(1, LAYOUT_MAX + 1, MALLOC_CAP_SPIRAM));
    size_t cfg_len = 0;
    bool cfg_active = false;
    bool cfg_too_big = false;
    const uint32_t boot_id = esp_random();
    const char *const reset_reason = reset_reason_name();
    uint32_t wake_seen = deck_model_wake_sequence();
    /* A hung loop restarts the panel (CONFIG_ESP_TASK_WDT_TIMEOUT_S); every read below returns within 20 ms. */
    const bool watched = esp_task_wdt_add(nullptr) == ESP_OK;
    for (;;) {
        /* Housekeeping once per read, not once per byte: an image upload is hundreds of KB. */
        if (rx_at >= rx_size) {
        if (watched) esp_task_wdt_reset();
        if (!s_app_confirmed && esp_timer_get_time() > 60LL * 1000000) app_confirm();
        /* A touch on the dimmed panel: restore the backlight here and tell the
         * host, which resets its idle timer instead of seeing a key press. */
        const uint32_t wake = deck_model_wake_sequence();
        if (wake != wake_seen) {
            wake_seen = wake;
            bsp_display_brightness_set(s_brightness);
            printf("{\"type\":\"wake\"}\n");
            fflush(stdout);
        }
        layout_flush_if_due();
        /* The about sheet's slider: apply at once, save and tell the host when the finger lifts. */
        int wanted_level = 0;
        bool save_level = false;
        if (deck_model_take_brightness_request(&wanted_level, &save_level)) {
            s_brightness = wanted_level;
            if (!deck_model_dimmed()) bsp_display_brightness_set(s_brightness);
            if (save_level) {
                save_brightness(s_brightness);
                printf("{\"type\":\"brightness\",\"level\":%d}\n", s_brightness);
                fflush(stdout);
            }
        }
        if (deck_model_take_touch_return()) {
            printf("{\"type\":\"screen\",\"name\":\"deck\",\"by\":\"touch\"}\n");
            fflush(stdout);
        }
        /* Touches on the agents and mixer screens: the UI wrote each one as a finished JSON line. */
        char touched[128];
        while (deck_model_take_line(touched, sizeof(touched))) {
            printf("%s\n", touched);
            fflush(stdout);
        }
        /* Stream Deck behaviour: every physical key press is pushed to the
         * connected host immediately as a JSON line on this console, so no
         * network path is needed for the deck to act. */
        int last_event = deck_model_last_event_id();
        if (last_event > deck_events_emitted) {
            deck_event_t events[8];
            int count = deck_model_events_since(deck_events_emitted, events, 8);
            for (int i = 0; i < count; ++i) {
                cJSON *event = cJSON_CreateObject();
                cJSON_AddStringToObject(event, "type", "deck_event");
                cJSON_AddNumberToObject(event, "id", events[i].id);
                cJSON_AddNumberToObject(event, "button", events[i].button_id);
                cJSON_AddStringToObject(event, "label", events[i].label);
                if (events[i].hold) cJSON_AddTrueToObject(event, "hold");
                char *text = cJSON_PrintUnformatted(event);
                if (text) { printf("%s\n", text); cJSON_free(text); }
                cJSON_Delete(event);
                deck_events_emitted = events[i].id;
            }
            fflush(stdout);
        }
            rx_size = usb_serial_jtag_read_bytes(received, sizeof(received), pdMS_TO_TICKS(20));
            rx_at = 0;
            if (rx_size <= 0) continue;
        }
        int ch = received[rx_at++];
        if (ch == '\r') continue;
        if (ch != '\n') {
            if (used + 1 < sizeof(line)) line[used++] = (char)ch;
            else overflow = true;
            continue;
        }
        line[used] = '\0';
        if (!overflow && used) deck_model_note_host();
        std::string image_reply;
        if (!overflow && strncmp(line, "AD_OTA_", 7) == 0) {
            ota_command(line);
            used = 0;
            continue;
        }
        if (!overflow && deck_image_command(line, image_reply)) {
            if (!image_reply.empty()) {printf("%s\n", image_reply.c_str());fflush(stdout);}
            used=0;overflow=false;
            continue;
        }
        if (!overflow && line[0] == '{') {
            cJSON *request=cJSON_Parse(line);
            const cJSON *cmd=cJSON_GetObjectItemCaseSensitive(request,"cmd");
            if(cJSON_IsString(cmd)&&!strcmp(cmd->valuestring,"get_info")) {
                cJSON *reply=cJSON_CreateObject();const esp_app_desc_t *app=esp_app_get_description();
                cJSON_AddStringToObject(reply,"type","info");cJSON_AddStringToObject(reply,"boardId","tessera-p4");
                cJSON_AddStringToObject(reply,"firmwareVersion",app->version);cJSON_AddNumberToObject(reply,"protocol",TESSERA_PROTOCOL);cJSON_AddNumberToObject(reply,"bootId",boot_id);
                cJSON_AddNumberToObject(reply,"uptime",esp_timer_get_time()/1000000);cJSON_AddNumberToObject(reply,"heap",heap_caps_get_free_size(MALLOC_CAP_INTERNAL));
                cJSON_AddNumberToObject(reply,"psramFree",heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
                cJSON_AddStringToObject(reply,"reset",reset_reason);cJSON_AddNumberToObject(reply,"ota",1);
                cJSON_AddNumberToObject(reply,"layoutSaved",static_cast<double>(s_layout_saved_unix));
                app_confirm();  /* the host can talk to this firmware: keep it */
                char *text=cJSON_PrintUnformatted(reply);
                if(text){printf("%s\n",text);cJSON_free(text);}cJSON_Delete(reply);fflush(stdout);
            }
            cJSON_Delete(request);
            memset(line, 0, sizeof(line));
            used = 0;
            overflow = false;
            continue;
        }
        /* Cockpit screens (protocol 4): one JSON line each for the agents, the mixer and the PC's readings. */
        if (!overflow && strncmp(line, "AD_AGENTS ", 10) == 0) {
            printf("AD_AGENTS %s\n", deck_model_agents_from_json(line + 10) ? "OK" : "INVALID");
            fflush(stdout);
        }
        if (!overflow && strncmp(line, "AD_RAIL ", 8) == 0) {
            printf("AD_RAIL %s\n", deck_model_rail_from_json(line + 8) ? "OK" : "INVALID");
            fflush(stdout);
        }
        if (!overflow && strncmp(line, "AD_VIEW ", 8) == 0) {
            static const char *const names[] = {"keys", "agents", "mixer", "status"};
            int view = -1;
            for (int i = 0; i < 4; ++i) if (!strcmp(line + 8, names[i])) view = i;
            if (view >= 0) deck_model_request_view(view);
            printf("AD_VIEW %s\n", view >= 0 ? "OK" : "INVALID");
            fflush(stdout);
        }
        if (!overflow && strncmp(line, "AD_MIXER ", 9) == 0) {
            printf("AD_MIXER %s\n", deck_model_faders_from_json(line + 9) ? "OK" : "INVALID");
            fflush(stdout);
        }
        if (!overflow && strncmp(line, "AD_STATS ", 9) == 0) {
            printf("AD_STATS %s\n", deck_model_stats_from_json(line + 9) ? "OK" : "INVALID");
            fflush(stdout);
        }
        if (!overflow && strcmp(line, "FQ_UI_STATUS") == 0) {
            char *labels = static_cast<char *>(heap_caps_malloc(4096, MALLOC_CAP_SPIRAM));
            int screen = -1;
            if (labels && bsp_display_lock(200)) {
                screen = ui_debug_visible_text(labels, 4096);
                bsp_display_unlock();
            }
            cJSON *status = cJSON_CreateObject();
            if (status) {
                cJSON_AddNumberToObject(status, "screen", screen);
                cJSON_AddStringToObject(status, "labels", screen >= 0 ? labels : "UI busy");
                char *text = cJSON_PrintUnformatted(status);
                if (text) { printf("FQ_UI_STATUS %s\n", text); cJSON_free(text); }
                cJSON_Delete(status);
                fflush(stdout);
            }
            heap_caps_free(labels);
        }
        if (!overflow && strcmp(line, "AD_CFG_BEGIN") == 0) {
            cfg_active = true;
            cfg_too_big = false;
            cfg_len = 0;
            if (cfg_buf) cfg_buf[0] = '\0';
            printf("AD_CFG_BEGIN OK\n");
            fflush(stdout);
        }
        if (!overflow && strncmp(line, "AD_CFG_DATA ", 12) == 0 && cfg_active) {
            size_t chunk = strlen(line + 12);
            if (!cfg_buf || cfg_len + chunk > LAYOUT_MAX) {
                cfg_active = false;
                cfg_too_big = true;  /* answered once, at AD_CFG_END, so the host gets exactly one reply */
            } else {
                memcpy(cfg_buf + cfg_len, line + 12, chunk);
                cfg_len += chunk;
                cfg_buf[cfg_len] = '\0';
            }
        }
        if (!overflow && strcmp(line, "AD_CFG_END") == 0) {
            if (cfg_active && cfg_buf) {
                deck_button_t buttons[DECK_MAX_BUTTONS];
                int count = 0;
                if (deck_model_buttons_from_json(cfg_buf, buttons, DECK_MAX_BUTTONS, &count) &&
                    deck_model_replace_buttons(buttons, count)) {
                    ESP_LOGI(TAG, "deck reprogrammed over USB: %d buttons", count);
                    layout_remember(cfg_buf);
                    std::vector<std::string> icons;
                    for (int n = 0; n < count; ++n) icons.emplace_back(buttons[n].icon);
                    deck_image_keep(icons);  /* trims the image cache as the host trims its record of it */
                    printf("AD_CFG_END OK %d\n", count);
                } else {
                    printf("AD_CFG_END INVALID\n");
                }
            } else if (cfg_too_big) {
                printf("AD_CFG_END TOO_BIG %u\n", static_cast<unsigned>(LAYOUT_MAX));
            } else {
                printf("AD_CFG_END INVALID\n");
            }
            cfg_active = false;
            cfg_too_big = false;
            cfg_len = 0;
            fflush(stdout);
        }
        if (!overflow && strncmp(line,"AD_CONTEXT ",11)==0) {
            cJSON *context = cJSON_Parse(line + 11);
            const cJSON *profile = cJSON_GetObjectItemCaseSensitive(context, "profile");
            const cJSON *page = cJSON_GetObjectItemCaseSensitive(context, "page");
            const cJSON *back = cJSON_GetObjectItemCaseSensitive(context, "canBack");
            if (cJSON_IsString(profile) && cJSON_IsString(page)) {
                deck_model_set_context(profile->valuestring, page->valuestring, cJSON_IsTrue(back));
                printf("AD_CONTEXT OK\n");
            } else {
                printf("AD_CONTEXT INVALID\n");
            }
            cJSON_Delete(context);
            fflush(stdout);
        }
        if (!overflow && strncmp(line, "AD_FEEDBACK ", 12) == 0) {
            /* Host confirms a key action: "AD_FEEDBACK ok|alert <id>" */
            char kind[8] = {};
            int id = 0;
            if (sscanf(line + 12, "%7s %d", kind, &id) == 2 && id > 0) {
                deck_model_request_feedback(id, strcmp(kind, "alert") == 0
                                                   ? DECK_FEEDBACK_ALERT
                                                   : DECK_FEEDBACK_OK);
                printf("AD_FEEDBACK OK\n");
            } else {
                printf("AD_FEEDBACK INVALID\n");
            }
            fflush(stdout);
        }
        if (!overflow && strncmp(line, "AD_PRESS ", 9) == 0) {
            /* Simulate a key press from the host (deck testing over USB). */
            int id = atoi(line + 9);
            uint32_t event = deck_model_record_press(id);
            printf("AD_PRESS %s\n", event ? "OK" : "UNKNOWN");
            fflush(stdout);
        }
        if (!overflow && (!strcmp(line,"AD_SCREEN deck") || !strcmp(line,"AD_SCREEN ambient"))) {
            deck_model_request_screen(line[10] == 'd' ? DECK_SCREEN_DECK : DECK_SCREEN_AMBIENT);
            printf("{\"type\":\"screen\",\"queued\":true}\n");
            fflush(stdout);
        }
        if (!overflow && strncmp(line, "AD_AMBIENT", 10) == 0 && (line[10] == '\0' || line[10] == ' ')) {
            deck_model_set_ambient(line[10] == ' ' ? line + 11 : "");
            printf("AD_AMBIENT OK\n");
            fflush(stdout);
        }
        if (!overflow && strncmp(line, "AD_BRIGHTNESS ", 14) == 0) {
            int level = 0;
            if (parse_percent(line + 14, 1, 100, &level)) {
                s_brightness = level;
                save_brightness(level);
                deck_model_set_brightness(level);
                deck_model_set_dimmed(false);
                esp_err_t result = bsp_display_brightness_set(s_brightness);
                printf("AD_BRIGHTNESS %s %d\n", result == ESP_OK ? "OK" : "FAILED", s_brightness);
            } else {
                printf("AD_BRIGHTNESS INVALID\n");
            }
            fflush(stdout);
        }
        if (!overflow && (!strcmp(line, "AD_PANEL_LOCK 1") || !strcmp(line, "AD_PANEL_LOCK 0"))) {
            deck_model_set_locked(line[14] == '1');
            printf("AD_PANEL_LOCK OK %c\n", line[14]);
            fflush(stdout);
        }
        if (!overflow && strncmp(line, "AD_DISPLAY_DIM ", 15) == 0) {
            int level = 0;
            if (parse_percent(line + 15, 0, 100, &level)) {
                esp_err_t result = bsp_display_brightness_set(level);
                if (result == ESP_OK) deck_model_set_dimmed(true);
                printf("AD_DISPLAY_DIM %s %d\n", result == ESP_OK ? "OK" : "FAILED", level);
            } else {
                printf("AD_DISPLAY_DIM INVALID\n");
            }
            fflush(stdout);
        }
        if (!overflow && strcmp(line, "AD_DISPLAY_WAKE") == 0) {
            esp_err_t result = bsp_display_brightness_set(s_brightness);
            deck_model_set_dimmed(false);
            bool queued = false;
            if (result == ESP_OK && bsp_display_lock(200)) {
                queued = lv_async_call([](void *) {
                    if (lv_screen_active()) lv_obj_invalidate(lv_screen_active());
                }, nullptr) == LV_RESULT_OK;
                bsp_display_unlock();
            }
            printf("AD_DISPLAY_WAKE %s %s\n", esp_err_to_name(result), queued ? "QUEUED" : "NO_REDRAW");
            fflush(stdout);
        }
        if (!overflow && strncmp(line, "AD_TIME ", 8) == 0) {
            /* Local PC time "YYYY-MM-DDTHH:MM:SS": the clock works without Wi-Fi. */
            int year = 0, month = 0, day = 0, hour = 0, minute = 0, second = 0;
            const bool parsed = sscanf(line + 8, "%4d-%2d-%2dT%2d:%2d:%2d", &year, &month, &day,
                                       &hour, &minute, &second) == 6;
            const bool set = parsed && time_service_set_from_host(year, month, day, hour, minute, second);
            /* An optional " 12h" or " 24h" after the time; an older host sends none and the clock stays as it is. */
            const char *format = strchr(line + 8, ' ');
            if (set && format && (!strcmp(format, " 12h") || !strcmp(format, " 24h"))) time_service_set_12h(format[1] == '1');
            printf("AD_TIME %s\n", set ? "OK" : "INVALID");
            fflush(stdout);
        }
        memset(line, 0, sizeof(line));
        used = 0;
        overflow = false;
    }
}

extern "C" void app_main(void)
{
    // Keep the scarce internal/DMA heap for the panel and SDIO driver.
    heap_caps_malloc_extmem_enable(16);
    usb_serial_jtag_driver_config_t usb = {};
    usb.rx_buffer_size = 8192;
    usb.tx_buffer_size = 8192;
    ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&usb));
    usb_serial_jtag_vfs_use_driver();
    deck_model_init();
    /* Idempotent; the stored brightness must be readable before the display starts. A full or newer-format
       partition is erased and set up again (the usual ESP-IDF recovery): otherwise nothing is ever stored again. */
    esp_err_t nvs = nvs_flash_init();
    if (nvs == ESP_ERR_NVS_NO_FREE_PAGES || nvs == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_LOGW(TAG, "Settings storage was reset (%s)", esp_err_to_name(nvs));
        nvs = nvs_flash_erase() == ESP_OK ? nvs_flash_init() : nvs;
    }
    if (nvs != ESP_OK) ESP_LOGW(TAG, "Settings storage is not available (%s)", esp_err_to_name(nvs));
    if (nvs == ESP_OK) {
        load_brightness();
        nvs_handle_t handle;  /* older firmware kept the layout in NVS: free that space, the file replaces it */
        if (nvs_open(SETTINGS_NAMESPACE, NVS_READWRITE, &handle) == ESP_OK) {
            if (nvs_erase_key(handle, "layout") == ESP_OK) nvs_commit(handle);
            nvs_close(handle);
        }
    }
    store_mount();
    layout_restore();
    deck_model_set_brightness(s_brightness);
    ui_set_firmware_version(esp_app_get_description()->version);
    (void)time_service_init();

    bsp_display_cfg_t cfg = {};
    cfg.lvgl_port_cfg = ESP_LVGL_PORT_INIT_CONFIG();
    // CSI and PPA share DW-GDMA's private interrupt group. Allocate/start
    // their channels on the same core in UI, capture and USB maintenance.
    cfg.lvgl_port_cfg.task_affinity = 0;
    cfg.buffer_size = 1024 * 240;
    /* The vendor BSP's BSP_LCD_DRAW_BUFF_DOUBLE is misleadingly defined as
     * (0), so asking for it explicitly still selects single buffering; the
     * double_buffer flag below is what actually enables the second buffer. */
    cfg.double_buffer = true;
    cfg.flags.buff_dma = false;
    cfg.flags.buff_spiram = true;
    cfg.flags.sw_rotate = true;
    cfg.lvgl_port_cfg.task_stack = 65536;
    cfg.lvgl_port_cfg.task_stack_caps = MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT;

    lv_display_t *display = bsp_display_start_with_config(&cfg);
    if (!display) {
        /* Returning would leave the panel silent on USB until a power cycle, with no console for an OTA fix.
         * A restart lets the bootloader roll back an unconfirmed image, and gives a flaky panel another try. */
        ESP_LOGE(TAG, "Display init failed; restarting");
        vTaskDelay(pdMS_TO_TICKS(2000));
        esp_restart();
    }


    bool ui_loaded = false;
    for (int attempt = 0; attempt < 20; ++attempt) {
        if (!bsp_display_lock(pdMS_TO_TICKS(100))) {
            vTaskDelay(pdMS_TO_TICKS(25));
            continue;
        }
        // Build the original application on the LVGL owner's 64 KiB stack.
        // app_main retains its small housekeeping stack and never builds widgets.
        const lv_result_t queued = lv_async_call([](void *) {
            ui_init();
            lv_timer_create(lvgl_watchdog, 1000, nullptr);
        }, nullptr);
        bsp_display_unlock();
        if (queued != LV_RESULT_OK) {
            vTaskDelay(pdMS_TO_TICKS(25));
            continue;
        }
        ui_loaded = true;
        break;
    }
    if (!ui_loaded) {
        ESP_LOGE(TAG, "LVGL lock failed; UI not loaded");
    }

    /* The BSP intentionally initializes PWM at 0% and requires applications
     * to enable the backlight. Touch and USB can otherwise keep working while
     * the physical panel looks completely black. */
    ESP_ERROR_CHECK(bsp_display_brightness_set(s_brightness));

    ESP_LOGI(TAG, "Tessera UI running");
    if (xTaskCreatePinnedToCore(usb_console_task, "ad_usb_console", 24576, nullptr, 1, nullptr, 0) != pdPASS)
        ESP_LOGW(TAG, "USB console unavailable");

    while (true) {
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}
