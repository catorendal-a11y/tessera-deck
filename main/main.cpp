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
#include "eh_host_cp_ota.h"
#include "eh_host_sys.h"
#include "lwip/sockets.h"
#include "driver/usb_serial_jtag.h"
#include "driver/usb_serial_jtag_vfs.h"
#include "esp_system.h"

extern "C" {
#include "deck_model.h"
#include "network_service.h"
#include "time_service.h"
#include "ui/ui.h"
}

static const char *TAG = "tessera";
/* Backlight level restored by AD_DISPLAY_WAKE; set by the host with AD_BRIGHTNESS. */
static int s_brightness = 100;

/* Parse "<digits>" within [low, high]; returns false for anything else. */
static bool parse_percent(const char *text, long low, long high, int *out)
{
    char *end = nullptr;
    long value = strtol(text, &end, 10);
    if (end == text || *end != '\0' || value < low || value > high) return false;
    *out = static_cast<int>(value);
    return true;
}
/* USB console. The FQ_C6_x and FQ_WIFI commands keep the exact protocol of the
 * previous panel firmware so tools/update_network_coprocessor.py and the
 * scripted Wi-Fi provisioning keep working across both firmwares. */
static void usb_console_task(void *)
{
    uint8_t received[256];
    int rx_size = 0, rx_at = 0;
    char line[1100];
    size_t used = 0;
    bool overflow = false;
    bool updating_c6 = false, legacy_c6 = false;
    size_t c6_bytes = 0;
    int deck_events_emitted = 0;
    /* Accumulator for the chunked AD_CFG_BEGIN/DATA/END config push. */
    static char *cfg_buf = static_cast<char *>(heap_caps_calloc(1, 8192 + 1, MALLOC_CAP_SPIRAM));
    size_t cfg_len = 0;
    bool cfg_active = false;
    const uint32_t boot_id = esp_random();
    for (;;) {
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
                char *text = cJSON_PrintUnformatted(event);
                if (text) { printf("%s\n", text); cJSON_free(text); }
                cJSON_Delete(event);
                deck_events_emitted = events[i].id;
            }
            fflush(stdout);
        }
        if (rx_at >= rx_size) {
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
        std::string image_reply;
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
                cJSON_AddStringToObject(reply,"firmwareVersion",app->version);cJSON_AddNumberToObject(reply,"bootId",boot_id);
                cJSON_AddNumberToObject(reply,"uptime",esp_timer_get_time()/1000000);cJSON_AddNumberToObject(reply,"heap",heap_caps_get_free_size(MALLOC_CAP_INTERNAL));
                cJSON_AddNumberToObject(reply,"psramFree",heap_caps_get_free_size(MALLOC_CAP_SPIRAM));char *text=cJSON_PrintUnformatted(reply);
                if(text){printf("%s\n",text);cJSON_free(text);}cJSON_Delete(reply);fflush(stdout);
            }
            cJSON_Delete(request);
            memset(line, 0, sizeof(line));
            used = 0;
            overflow = false;
            continue;
        }
        if (!overflow && strcmp(line, "FQ_C6_BEGIN") == 0) {
            eh_host_coprocessor_fwver_t version = {};
            esp_err_t err = eh_host_sys_get_cp_fw_version(&version);
            if (err == ESP_OK) {
                legacy_c6 = version.major1 < 2 || (version.major1 == 2 && version.minor1 < 6);
                err = eh_host_cp_ota_begin();
            }
            updating_c6 = err == ESP_OK;
            c6_bytes = 0;
            printf("FQ_C6_BEGIN %s\n", esp_err_to_name(err));
            fflush(stdout);
        }
        if (!overflow && strncmp(line, "FQ_C6_DATA ", 11) == 0) {
            uint8_t bytes[512];
            size_t hex_size = strlen(line + 11);
            bool valid = updating_c6 && hex_size > 0 && hex_size <= sizeof(bytes) * 2 && !(hex_size & 1) &&
                         c6_bytes + hex_size / 2 <= 0x180000;
            for (size_t i = 0; valid && i < hex_size; ++i) {
                char digit = line[11 + i];
                int value = digit >= '0' && digit <= '9' ? digit - '0' :
                            digit >= 'a' && digit <= 'f' ? digit - 'a' + 10 : -1;
                if (value < 0) valid = false;
                else if (!(i & 1)) bytes[i / 2] = (uint8_t)(value << 4);
                else bytes[i / 2] |= (uint8_t)value;
            }
            esp_err_t err = valid ? eh_host_cp_ota_write(bytes, hex_size / 2) : ESP_ERR_INVALID_ARG;
            if (err == ESP_OK) c6_bytes += hex_size / 2;
            else updating_c6 = false;
            printf("FQ_C6_DATA %s\n", esp_err_to_name(err));
            fflush(stdout);
        }
        if (!overflow && strcmp(line, "FQ_C6_END") == 0) {
            esp_err_t err = updating_c6 && c6_bytes > 0 ? eh_host_cp_ota_end() : ESP_ERR_INVALID_STATE;
            if (err == ESP_OK && !legacy_c6) err = eh_host_cp_ota_activate();
            updating_c6 = false;
            printf("FQ_C6_END %s\n", esp_err_to_name(err));
            fflush(stdout);
        }
        if (!overflow && strcmp(line, "FQ_STATUS") == 0) {
            network_status_t net = network_service_status();
            cJSON *status = cJSON_CreateObject();
            if (status) {
                cJSON_AddNumberToObject(status, "network", net.state);
                cJSON_AddBoolToObject(status, "deck_ready", true);
                const esp_app_desc_t *application = esp_app_get_description();
                cJSON_AddStringToObject(status, "project", application->project_name);
                cJSON_AddStringToObject(status, "firmware", application->version);
                cJSON_AddStringToObject(status, "built_date", application->date);
                cJSON_AddStringToObject(status, "built_time", application->time);
                cJSON_AddStringToObject(status, "ssid", net.ssid);
                cJSON_AddStringToObject(status, "ip", net.address);
                cJSON_AddNumberToObject(status, "rssi", net.rssi);
                cJSON_AddNumberToObject(status, "clock_quality", time_service_time_quality());
                cJSON_AddNumberToObject(status, "internal_free", heap_caps_get_free_size(MALLOC_CAP_INTERNAL));
                char *text = cJSON_PrintUnformatted(status);
                if (text) { printf("FQ_STATUS %s\n", text); cJSON_free(text); }
                cJSON_Delete(status);
                fflush(stdout);
            }
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
        if (!overflow && strcmp(line, "AD_NET_CHECK") == 0) {
            /* Loopback probe: proves the HTTP server answers without
             * needing a client on the station LAN. */
            int status = 0;
            int fd = socket(AF_INET, SOCK_STREAM, 0);
            if (fd >= 0) {
                struct timeval timeout = {2, 0};
                setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
                setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
                struct sockaddr_in local = {};
                local.sin_family = AF_INET;
                local.sin_port = htons(80);
                local.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
                if (connect(fd, reinterpret_cast<struct sockaddr *>(&local), sizeof(local)) == 0) {
                    const char request[] = "GET /api/status HTTP/1.0\r\nHost: localhost\r\nConnection: close\r\n\r\n";
                    send(fd, request, sizeof(request) - 1, 0);
                    char response[256] = {};
                    int n = recv(fd, response, sizeof(response) - 1, 0);
                    if (n > 0) {
                        response[n] = '\0';
                        sscanf(response, "HTTP/%*s %d", &status);
                    }
                }
                close(fd);
            }
            printf("AD_NET_CHECK http_local=%d\n", status);
            fflush(stdout);
        }
        if (!overflow && strncmp(line, "FQ_WIFI ", 8) == 0) {
            cJSON *json = cJSON_Parse(line + 8);
            const cJSON *ssid = cJSON_GetObjectItemCaseSensitive(json, "ssid");
            const cJSON *password = cJSON_GetObjectItemCaseSensitive(json, "password");
            bool ok = cJSON_IsString(ssid) && cJSON_IsString(password) &&
                      network_service_configure(ssid->valuestring, password->valuestring);
            if (cJSON_IsString(password)) memset(password->valuestring, 0, strlen(password->valuestring));
            cJSON_Delete(json);
            printf("FQ_WIFI_%s\n", ok ? "ACCEPTED" : "REJECTED");
            fflush(stdout);
        }
        if (!overflow && strcmp(line, "AD_CFG_BEGIN") == 0) {
            cfg_active = true;
            cfg_len = 0;
            if (cfg_buf) cfg_buf[0] = '\0';
            printf("AD_CFG_BEGIN OK\n");
            fflush(stdout);
        }
        if (!overflow && strncmp(line, "AD_CFG_DATA ", 12) == 0 && cfg_active) {
            size_t chunk = strlen(line + 12);
            if (!cfg_buf || cfg_len + chunk > 8192) {
                cfg_active = false;
                printf("AD_CFG_END TOO_BIG\n");
                fflush(stdout);
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
                    printf("AD_CFG_END OK %d\n", count);
                } else {
                    printf("AD_CFG_END INVALID\n");
                }
            } else {
                printf("AD_CFG_END INVALID\n");
            }
            cfg_active = false;
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
        if (!overflow && !strcmp(line,"AD_SCREEN deck")) {
            bool queued = false;
            if (bsp_display_lock(200)) {
                queued = lv_async_call([](void* destination) {
                    ui_show_destination(static_cast<int>(reinterpret_cast<intptr_t>(destination)));
                },nullptr) == LV_RESULT_OK;
                bsp_display_unlock();
            }
            printf("{\"type\":\"screen\",\"queued\":%s}\n",queued?"true":"false");
            fflush(stdout);
        }
        if (!overflow && strncmp(line, "AD_BRIGHTNESS ", 14) == 0) {
            int level = 0;
            if (parse_percent(line + 14, 1, 100, &level)) {
                s_brightness = level;
                esp_err_t result = bsp_display_brightness_set(s_brightness);
                printf("AD_BRIGHTNESS %s %d\n", result == ESP_OK ? "OK" : "FAILED", s_brightness);
            } else {
                printf("AD_BRIGHTNESS INVALID\n");
            }
            fflush(stdout);
        }
        if (!overflow && strncmp(line, "AD_DISPLAY_DIM ", 15) == 0) {
            int level = 0;
            if (parse_percent(line + 15, 0, 100, &level)) {
                esp_err_t result = bsp_display_brightness_set(level);
                printf("AD_DISPLAY_DIM %s %d\n", result == ESP_OK ? "OK" : "FAILED", level);
            } else {
                printf("AD_DISPLAY_DIM INVALID\n");
            }
            fflush(stdout);
        }
        if (!overflow && strcmp(line, "AD_DISPLAY_WAKE") == 0) {
            esp_err_t result = bsp_display_brightness_set(s_brightness);
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
        if (!overflow && strcmp(line, "AD_SETUP") == 0) {
            network_service_start_setup();
            printf("AD_SETUP OK\n");
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
    (void)time_service_init();
    time_service_start_sntp();
    network_service_init();

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
        ESP_LOGE(TAG, "Display init failed");
        return;
    }


    bool ui_loaded = false;
    for (int attempt = 0; attempt < 20; ++attempt) {
        if (!bsp_display_lock(pdMS_TO_TICKS(100))) {
            vTaskDelay(pdMS_TO_TICKS(25));
            continue;
        }
        // Build the original application on the LVGL owner's 64 KiB stack.
        // app_main retains its small housekeeping stack and never builds widgets.
        const lv_result_t queued = lv_async_call([](void *) { ui_init(); }, nullptr);
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
