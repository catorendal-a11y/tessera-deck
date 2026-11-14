#include "api_server.h"

#include <errno.h>
#include <stdio.h>
#include <string.h>

#include "api_crypto.h"
#include "api_entities.h"
#include "api_mdns.h"
#include "api_messages.h"
#include "api_session.h"
#include "cJSON.h"
#include "deck_model.h"
#include "esp_app_desc.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "lwip/sockets.h"
#include "nvs.h"
#include "press_router.h"
#include "time_service.h"
#include "wifi_service.h"

static const char *TAG = "api";
static const char *NAMESPACE = "tessera_net"; /* shared with wifi_service: AD_WIFI_CLEAR erases it whole */

#define SLOTS 2
#define TASK_STACK 8192
#define TASK_PRIORITY 3
#define TASK_CORE 1
#define LOOP_MS 20
#define TIME_EVERY_MS (6LL * 3600 * 1000)

/* ---- settings and key, shared by the console task and tessera_api ---- */

static portMUX_TYPE s_lock = portMUX_INITIALIZER_UNLOCKED;
static api_settings_t s_settings;
static uint32_t s_generation = 1; /* settings or key changed: the task closes everything and starts again */
static uint32_t s_status_version = 1;
static int s_clients;
static bool s_ha;
static TaskHandle_t s_task;

static api_settings_t settings_copy(uint32_t *generation)
{
    portENTER_CRITICAL(&s_lock);
    const api_settings_t copy = s_settings;
    if (generation) *generation = s_generation;
    portEXIT_CRITICAL(&s_lock);
    return copy;
}

static void bump(bool settings)
{
    portENTER_CRITICAL(&s_lock);
    if (settings) ++s_generation;
    ++s_status_version;
    portEXIT_CRITICAL(&s_lock);
}

static void read_str(nvs_handle_t handle, const char *key, char *out, size_t size)
{
    char value[API_FRIENDLY_MAX * 4 + 1];
    size_t length = sizeof(value);
    if (nvs_get_str(handle, key, value, &length) == ESP_OK && length <= size) memcpy(out, value, length);
}

static void load_settings(void)
{
    api_settings_t loaded;
    api_settings_default(&loaded);
    nvs_handle_t handle;
    if (nvs_open(NAMESPACE, NVS_READONLY, &handle) == ESP_OK) {
        uint8_t on = 0;
        if (nvs_get_u8(handle, "api_on", &on) == ESP_OK) loaded.enabled = on == 1;
        read_str(handle, "api_name", loaded.name, sizeof(loaded.name));
        read_str(handle, "api_friendly", loaded.friendly, sizeof(loaded.friendly));
        read_str(handle, "api_area", loaded.area, sizeof(loaded.area));
        nvs_close(handle);
    }
    if (!api_name_valid(loaded.name)) strcpy(loaded.name, "tessera-deck");
    portENTER_CRITICAL(&s_lock);
    s_settings = loaded;
    portEXIT_CRITICAL(&s_lock);
}

static esp_err_t store_str(nvs_handle_t handle, const char *key, const char *value)
{
    char stored[API_FRIENDLY_MAX * 4 + 1];
    size_t length = sizeof(stored);
    if (nvs_get_str(handle, key, stored, &length) == ESP_OK && !strcmp(stored, value)) return ESP_OK;
    return nvs_set_str(handle, key, value);
}

static esp_err_t save_settings(const api_settings_t *settings)
{
    nvs_handle_t handle;
    esp_err_t result = nvs_open(NAMESPACE, NVS_READWRITE, &handle);
    if (result != ESP_OK) return result;
    uint8_t on = 0;
    if (nvs_get_u8(handle, "api_on", &on) != ESP_OK || on != settings->enabled)
        result = nvs_set_u8(handle, "api_on", settings->enabled ? 1 : 0);
    if (result == ESP_OK) result = store_str(handle, "api_name", settings->name);
    if (result == ESP_OK) result = store_str(handle, "api_friendly", settings->friendly);
    if (result == ESP_OK) result = store_str(handle, "api_area", settings->area);
    if (result == ESP_OK) result = nvs_commit(handle);
    nvs_close(handle);
    return result;
}

/* The 32-byte PSK (NVS blob api_psk): made with esp_fill_random the first time it is needed, or anew. Read
 * from NVS every time, so it can never differ from what survives a reboot. */
static esp_err_t load_key(uint8_t key[32], bool fresh)
{
    nvs_handle_t handle;
    esp_err_t result = nvs_open(NAMESPACE, NVS_READWRITE, &handle);
    if (result != ESP_OK) return result;
    size_t length = 32;
    if (fresh || nvs_get_blob(handle, "api_psk", key, &length) != ESP_OK || length != 32) {
        esp_fill_random(key, 32);
        result = nvs_set_blob(handle, "api_psk", key, 32);
        if (result == ESP_OK) result = nvs_commit(handle);
        if (result == ESP_OK) ESP_LOGI(TAG, "Made a new API encryption key");
    }
    nvs_close(handle);
    if (result != ESP_OK) noise_wipe(key, 32);
    return result;
}

esp_err_t api_server_init(void)
{
    load_settings();
    const api_settings_t settings = settings_copy(NULL);
    ESP_LOGI(TAG, "Home Assistant API %s (%s)", settings.enabled ? "on" : "off", settings.name);
    return ESP_OK;
}

void api_server_reload(void)
{
    load_settings();
    bump(true);
}

bool api_server_hostname(char *out, size_t size)
{
    const api_settings_t settings = settings_copy(NULL);
    if (!settings.enabled || strlen(settings.name) >= size) return false;
    strcpy(out, settings.name);
    return true;
}

uint32_t api_server_status_version(void)
{
    portENTER_CRITICAL(&s_lock);
    const uint32_t version = s_status_version;
    portEXIT_CRITICAL(&s_lock);
    return version;
}

void api_server_status_line(void)
{
    const api_settings_t settings = settings_copy(NULL);
    portENTER_CRITICAL(&s_lock);
    const int clients = s_clients;
    const bool ha = s_ha;
    portEXIT_CRITICAL(&s_lock);
    cJSON *line = cJSON_CreateObject();
    if (!line) return;
    cJSON_AddStringToObject(line, "type", "api");
    cJSON_AddBoolToObject(line, "enabled", settings.enabled);
    cJSON_AddNumberToObject(line, "clients", clients);
    cJSON_AddBoolToObject(line, "ha", ha);
    cJSON_AddStringToObject(line, "name", settings.name);
    char *text = cJSON_PrintUnformatted(line);
    if (text) printf("%s\n", text);
    cJSON_free(text);
    cJSON_Delete(line);
    fflush(stdout);
}

/* ---- the serial commands (USB console task) ---- */

static void base64(const uint8_t *in, size_t len, char *out)
{
    static const char table[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    size_t o = 0;
    for (size_t i = 0; i < len; i += 3) {
        const uint32_t v = (uint32_t)in[i] << 16 | (i + 1 < len ? (uint32_t)in[i + 1] << 8 : 0) |
                           (i + 2 < len ? in[i + 2] : 0);
        out[o++] = table[v >> 18 & 63];
        out[o++] = table[v >> 12 & 63];
        out[o++] = i + 1 < len ? table[v >> 6 & 63] : '=';
        out[o++] = i + 2 < len ? table[v & 63] : '=';
    }
    out[o] = '\0';
}

static void key_command(bool fresh)
{
    uint8_t key[32];
    char text[45];
    if (load_key(key, fresh) != ESP_OK) {
        printf("AD_API_KEY FAILED storage\n");
        return;
    }
    base64(key, sizeof(key), text);
    printf("AD_API_KEY %s\n", text); /* the only place the key leaves the panel: USB, on request */
    noise_wipe(key, sizeof(key));
    noise_wipe(text, sizeof(text));
    if (fresh) bump(true); /* every connection made with the old key closes */
}

static void set_command(const char *json)
{
    api_settings_t next;
    const char *field = "json";
    if (!api_settings_from_json(json, &next, &field)) {
        printf("AD_API_SET INVALID %s\n", field);
        return;
    }
    if (save_settings(&next) != ESP_OK) {
        printf("AD_API_SET FAILED storage\n");
        return;
    }
    const api_settings_t before = settings_copy(NULL);
    portENTER_CRITICAL(&s_lock);
    s_settings = next;
    portEXIT_CRITICAL(&s_lock);
    if (memcmp(&before, &next, sizeof(next)) != 0) bump(true);
    printf("AD_API_SET OK\n");
}

void api_server_command(const char *line)
{
    if (!strncmp(line, "AD_API_SET ", 11)) set_command(line + 11);
    else if (!strcmp(line, "AD_API_KEY")) key_command(false);
    else if (!strcmp(line, "AD_API_KEY NEW")) key_command(true);
    else if (!strncmp(line, "AD_API_OPTIONS ", 15))
        printf("AD_API_OPTIONS %s\n", deck_model_api_options_from_json(line + 15) ? "OK" : "INVALID");
    else if (!strcmp(line, "AD_API_STATUS")) api_server_status_line();
    else return; /* unknown AD_API_ lines get no answer, as other unknown lines */
    fflush(stdout);
}

/* ---- the tessera_api task ---- */

typedef struct {
    int fd;
    api_session_t session;
    api_peer_t peer;
    uint8_t *buffers[4];
    int64_t opened_ms;
    int64_t time_asked_ms;
} slot_t;

static slot_t s_slots[SLOTS];
static int s_listen = -1;
static uint8_t s_psk[32];
static char s_name[API_NAME_MAX + 1], s_friendly[API_FRIENDLY_MAX * 4 + 1], s_area[API_AREA_MAX * 4 + 1];
static char s_mac_hex[13], s_mac_pretty[18], s_server_info[48], s_version[32], s_compiled[40];
static api_device_t s_device;
static api_snapshot_t s_now;
static press_router_t s_router;
static bool s_watermark_logged;

static int64_t now_ms(void)
{
    return esp_timer_get_time() / 1000;
}

static bool slot_write(void *ctx, const uint8_t *data, size_t len)
{
    const slot_t *slot = (const slot_t *)ctx;
    while (len) {
        /* Blocking with SO_SNDTIMEO: a client that stops reading is dropped within a second. */
        const ssize_t sent = send(slot->fd, data, len, 0);
        if (sent <= 0) return false;
        data += sent;
        len -= (size_t)sent;
    }
    return true;
}

static void slot_close(slot_t *slot)
{
    if (slot->fd < 0) return;
    if (slot->session.why) ESP_LOGI(TAG, "Client closed: %s", slot->session.why);
    api_session_close(&slot->session, "closed");
    shutdown(slot->fd, SHUT_RDWR);
    close(slot->fd);
    slot->fd = -1;
    memset(&slot->peer, 0, sizeof(slot->peer));
}

static void on_message(api_session_t *s, uint16_t type, const uint8_t *data, size_t len, void *ctx)
{
    slot_t *slot = (slot_t *)ctx;
    if (type == API_GET_TIME_RESPONSE) {
        api_get_time_response_t time;
        /* AD_TIME from the PC always wins. */
        if (api_decode_get_time_response(data, len, &time) && !(time_service_host_set() && s_now.pc_linked))
            time_service_set_unix(time.epoch_seconds, time.timezone);
        return;
    }
    api_entities_message(s, &slot->peer, &s_device, &s_now, type, data, len, now_ms());
    if (!s_watermark_logged && slot->peer.subscribed) {
        s_watermark_logged = true;
        ESP_LOGI(TAG, "tessera_api stack: %u bytes left", (unsigned)uxTaskGetStackHighWaterMark(NULL));
    }
}

static void slot_open(slot_t *slot, int fd)
{
    const api_session_config_t config = {
        .name = s_name,
        .mac_hex = s_mac_hex,
        .server_info = s_server_info,
        .psk = s_psk,
        .write = slot_write,
        .on_message = on_message,
        .ctx = slot,
    };
    slot->fd = fd;
    slot->opened_ms = now_ms();
    slot->time_asked_ms = 0;
    memset(&slot->peer, 0, sizeof(slot->peer));
    api_session_open(&slot->session, &config, slot->buffers, slot->opened_ms);
}

/* Two slots. A third client replaces the oldest slot still in its handshake, or else the oldest slot. */
static slot_t *pick_slot(void)
{
    slot_t *oldest = NULL, *oldest_pending = NULL;
    for (int i = 0; i < SLOTS; ++i) {
        slot_t *slot = &s_slots[i];
        if (slot->fd < 0) return slot;
        if (!oldest || slot->opened_ms < oldest->opened_ms) oldest = slot;
        if (!api_session_ready(&slot->session) && (!oldest_pending || slot->opened_ms < oldest_pending->opened_ms))
            oldest_pending = slot;
    }
    slot_t *victim = oldest_pending ? oldest_pending : oldest;
    victim->session.why = "replaced by a new client";
    slot_close(victim);
    return victim;
}

static void accept_client(void)
{
    struct sockaddr_in from;
    socklen_t from_len = sizeof(from);
    const int fd = accept(s_listen, (struct sockaddr *)&from, &from_len);
    if (fd < 0) return;
    const struct timeval timeout = {.tv_sec = 1, .tv_usec = 0};
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
    const int one = 1;
    setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
    slot_open(pick_slot(), fd);
}

static bool make_identity(const api_settings_t *settings)
{
    wifi_svc_status_t wifi;
    wifi_service_status(&wifi);
    const uint8_t *m = wifi.mac;
    snprintf(s_mac_hex, sizeof(s_mac_hex), "%02x%02x%02x%02x%02x%02x", m[0], m[1], m[2], m[3], m[4], m[5]);
    snprintf(s_mac_pretty, sizeof(s_mac_pretty), "%02X:%02X:%02X:%02X:%02X:%02X", m[0], m[1], m[2], m[3], m[4],
             m[5]);
    const esp_app_desc_t *app = esp_app_get_description();
    strlcpy(s_version, app->version, sizeof(s_version));
    snprintf(s_server_info, sizeof(s_server_info), "Tessera %s", s_version);
    snprintf(s_compiled, sizeof(s_compiled), "%s, %s", app->date, app->time);
    strlcpy(s_name, settings->name, sizeof(s_name));
    strlcpy(s_friendly, settings->friendly, sizeof(s_friendly));
    strlcpy(s_area, settings->area, sizeof(s_area));
    s_device = (api_device_t){s_name, s_friendly, s_area, s_mac_pretty, s_version, s_compiled};
    esp_netif_t *netif = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    if (netif) esp_netif_set_hostname(netif, s_name); /* used from the next DHCP request on */
    return load_key(s_psk, false) == ESP_OK;
}

static bool start(const api_settings_t *settings)
{
    if (!make_identity(settings)) {
        ESP_LOGW(TAG, "No API key: NVS not writable");
        return false;
    }
    const int fd = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (fd < 0) return false;
    const int one = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    struct sockaddr_in address = {0};
    address.sin_family = AF_INET;
    address.sin_port = htons(API_PORT);
    address.sin_addr.s_addr = htonl(INADDR_ANY);
    if (bind(fd, (struct sockaddr *)&address, sizeof(address)) || listen(fd, SLOTS)) {
        ESP_LOGW(TAG, "Port %d not available (errno %d)", API_PORT, errno);
        close(fd);
        return false;
    }
    s_listen = fd;
    const api_mdns_info_t mdns = {s_name, s_friendly, s_mac_hex, s_version};
    api_mdns_start(&mdns); /* without multicast HA can still add the panel by IP */
    press_router_init(&s_router);
    ESP_LOGI(TAG, "Listening on port %d as %s", API_PORT, s_name);
    return true;
}

static void stop(void)
{
    for (int i = 0; i < SLOTS; ++i) slot_close(&s_slots[i]);
    if (s_listen >= 0) {
        close(s_listen);
        s_listen = -1;
        ESP_LOGI(TAG, "Stopped");
    }
    api_mdns_stop();
    noise_wipe(s_psk, sizeof(s_psk));
}

static void publish_status(void)
{
    int clients = 0;
    bool ha = false;
    for (int i = 0; i < SLOTS; ++i) {
        if (s_slots[i].fd < 0 || !api_session_ready(&s_slots[i].session)) continue;
        ++clients;
        ha = ha || s_slots[i].peer.subscribed;
    }
    portENTER_CRITICAL(&s_lock);
    const bool changed = clients != s_clients || ha != s_ha;
    s_clients = clients;
    s_ha = ha;
    if (changed) ++s_status_version;
    portEXIT_CRITICAL(&s_lock);
    deck_model_set_api_client(ha);
}

/* GetTimeRequest after SubscribeStates when the PC has not set the clock, then every 6 h while it is away. */
static void ask_time(slot_t *slot, int64_t now)
{
    if (!slot->peer.subscribed || (time_service_host_set() && s_now.pc_linked)) return;
    if (slot->time_asked_ms && now - slot->time_asked_ms < TIME_EVERY_MS) return;
    slot->time_asked_ms = now;
    api_session_send_empty(&slot->session, API_GET_TIME_REQUEST);
}

static void serve(void)
{
    fd_set readable;
    FD_ZERO(&readable);
    FD_SET(s_listen, &readable);
    int top = s_listen;
    for (int i = 0; i < SLOTS; ++i) {
        if (s_slots[i].fd < 0) continue;
        FD_SET(s_slots[i].fd, &readable);
        if (s_slots[i].fd > top) top = s_slots[i].fd;
    }
    struct timeval wait = {.tv_sec = 0, .tv_usec = LOOP_MS * 1000};
    const int ready = select(top + 1, &readable, NULL, NULL, &wait);
    const int64_t now = now_ms();
    wifi_svc_status_t wifi;
    wifi_service_status(&wifi);
    api_snapshot_read(&s_now, wifi.state == WIFI_SVC_CONNECTED, wifi.rssi);
    if (ready > 0 && FD_ISSET(s_listen, &readable)) accept_client();
    press_out_t presses[8];
    const int pressed = press_router_poll(&s_router, now, presses, 8);
    for (int i = 0; i < SLOTS; ++i) {
        slot_t *slot = &s_slots[i];
        if (slot->fd < 0) continue;
        bool alive = true;
        if (ready > 0 && FD_ISSET(slot->fd, &readable)) {
            uint8_t data[512];
            const ssize_t got = recv(slot->fd, data, sizeof(data), MSG_DONTWAIT);
            if (got > 0) alive = api_session_feed(&slot->session, data, (size_t)got, now);
            else if (got == 0 || (errno != EAGAIN && errno != EWOULDBLOCK)) {
                slot->session.why = "connection closed by the client";
                alive = false;
            }
        }
        if (alive) alive = api_session_tick(&slot->session, now);
        if (alive) {
            api_entities_tick(&slot->session, &slot->peer, &s_now, now);
            for (int p = 0; p < pressed; ++p)
                api_entities_send_event(&slot->session, &slot->peer, presses[p].slot, presses[p].type);
            ask_time(slot, now);
            alive = slot->session.state != API_SESSION_CLOSED;
        }
        if (!alive) slot_close(slot);
    }
    if (s_router.dropped) {
        ESP_LOGW(TAG, "%u key events were missed (event ring wrapped)", (unsigned)s_router.dropped);
        s_router.dropped = 0;
    }
    publish_status();
}

static bool allocate_buffers(void)
{
    for (int i = 0; i < SLOTS; ++i) {
        s_slots[i].fd = -1;
        for (int b = 0; b < 4; ++b) {
            if (!s_slots[i].buffers[b])
                s_slots[i].buffers[b] = heap_caps_calloc(1, API_BUFFER, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
            if (!s_slots[i].buffers[b]) return false; /* the next poll tries again; kept buffers are reused */
        }
    }
    return true;
}

static void api_task(void *arg)
{
    (void)arg;
    if (api_crypto_init() != 0) ESP_LOGW(TAG, "PSA crypto init failed");
    uint32_t running_generation = 0;
    for (;;) {
        uint32_t generation = 0;
        const api_settings_t settings = settings_copy(&generation);
        const bool wanted = settings.enabled && wifi_service_connected();
        if (s_listen >= 0 && (!wanted || generation != running_generation)) {
            stop();
            publish_status();
        }
        if (!wanted) { /* Wi-Fi off or API off: no socket, no mDNS, no crypto */
            vTaskDelay(pdMS_TO_TICKS(500));
            continue;
        }
        if (s_listen < 0) {
            if (!start(&settings)) {
                vTaskDelay(pdMS_TO_TICKS(5000));
                continue;
            }
            running_generation = generation;
        }
        serve();
    }
}

void api_server_poll(void)
{
    if (s_task) return;
    const api_settings_t settings = settings_copy(NULL);
    if (!settings.enabled || !wifi_service_connected()) return;
    if (!allocate_buffers()) {
        ESP_LOGW(TAG, "No PSRAM for the API buffers");
        return;
    }
    /* Core 1, priority 3, 8 KB internal stack (X25519 and HKDF run here). */
    if (xTaskCreatePinnedToCore(api_task, "tessera_api", TASK_STACK, NULL, TASK_PRIORITY, &s_task, TASK_CORE) != pdPASS) {
        s_task = NULL;
        ESP_LOGW(TAG, "API task not started");
    }
}
