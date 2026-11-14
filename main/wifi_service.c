#include "wifi_service.h"

#include "api/api_server.h"

#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "esp_event.h"
#include "esp_heap_caps.h"
#include "esp_hosted.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_random.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "nvs.h"
#include "deck_model.h"

/* Every Wi-Fi and hosted call runs on this one task; event handlers and timers only post to its queue.
 * No ESP_ERROR_CHECK anywhere: a failing C6 only makes Wi-Fi unavailable, never the panel.
 * Never log the password, the line that carried it, or a wifi_config_t. */

static const char *TAG = "tessera_wifi";
static const char *NAMESPACE = "tessera_net";

#define START_DELAY_MS 3000
#define INIT_TIMEOUT_US (15LL * 1000000)
#define DHCP_TIMEOUT_US (30LL * 1000000)
#define RSSI_PERIOD_US (30LL * 1000000)
#define AUTH_RETRY_MS (5 * 60 * 1000)
#define BACKOFF_CAP_MS 60000
#define GIVE_UP_AFTER 3

typedef enum {
    EV_SET, EV_CLEAR, EV_STA_START, EV_STA_CONNECTED, EV_STA_DISCONNECTED, EV_GOT_IP,
    EV_RETRY, EV_DHCP_TIMEOUT, EV_RSSI, EV_TRANSPORT_FAILED,
} wifi_msg_type_t;

typedef struct {
    uint8_t type;
    uint16_t reason; /* wifi_err_reason_t for EV_STA_DISCONNECTED */
    uint32_t ip;     /* EV_GOT_IP, network byte order */
} wifi_msg_t;

static portMUX_TYPE s_lock = portMUX_INITIALIZER_UNLOCKED;
static wifi_svc_status_t s_status;
static uint32_t s_version = 1;
static QueueHandle_t s_queue;
static volatile bool s_wanted;      /* credentials stored and not cleared since; set by the caller's thread */
static volatile bool s_bringing_up; /* the task is inside esp_hosted_init / connect / esp_wifi_init */
static esp_timer_handle_t s_init_timer, s_retry_timer, s_dhcp_timer, s_rssi_timer;

/* Task-only state. */
static bool s_stack_up;        /* netif, event loop, hosted and esp_wifi_init done */
static volatile bool s_parked; /* the C6 did not answer: leave it alone until AD_WIFI_SET or a reboot */
static bool s_started;         /* esp_wifi_start called and not stopped */
static bool s_was_connected;   /* had an address since the last connect attempt began */
static int64_t s_own_disconnect_us; /* when this task last called esp_wifi_disconnect or esp_wifi_stop */
static int s_auth_fails, s_no_ap_fails, s_backoff_step;

/* ---- status ---- */

static void mirror_to_model(void)
{
    deck_network_t network;
    memset(&network, 0, sizeof(network));
    portENTER_CRITICAL(&s_lock);
    network.state = (uint8_t)s_status.state;
    network.reason = (uint8_t)s_status.reason;
    memcpy(network.ssid, s_status.ssid, sizeof(network.ssid));
    memcpy(network.ip, s_status.ip, sizeof(network.ip));
    network.rssi = s_status.rssi;
    portEXIT_CRITICAL(&s_lock);
    deck_model_set_network(&network);
}

static void set_state(wifi_svc_state_t state, wifi_svc_reason_t reason)
{
    bool changed;
    portENTER_CRITICAL(&s_lock);
    changed = s_status.state != state || s_status.reason != reason;
    s_status.state = state;
    s_status.reason = reason;
    if (state != WIFI_SVC_CONNECTED) {
        changed = changed || s_status.ip[0];
        s_status.ip[0] = '\0';
        s_status.rssi = 0;
    }
    if (changed) ++s_version;
    portEXIT_CRITICAL(&s_lock);
    if (changed) ESP_LOGI(TAG, "Wi-Fi %s%s%s", wifi_service_state_name(state), reason ? ": " : "",
                          wifi_service_reason_name(reason));
    mirror_to_model();
}

static void set_ssid(const char *ssid)
{
    portENTER_CRITICAL(&s_lock);
    if (strncmp(s_status.ssid, ssid, sizeof(s_status.ssid)) != 0) {
        strlcpy(s_status.ssid, ssid, sizeof(s_status.ssid));
        ++s_version;
    }
    portEXIT_CRITICAL(&s_lock);
    mirror_to_model();
}

static int8_t read_rssi(void)
{
    int rssi = 0;
    if (esp_wifi_sta_get_rssi(&rssi) != ESP_OK) return 0;
    return (int8_t)(rssi < -127 ? -127 : rssi > 0 ? 0 : rssi);
}

static void set_rssi(int8_t rssi)
{
    portENTER_CRITICAL(&s_lock);
    if (s_status.state == WIFI_SVC_CONNECTED) s_status.rssi = rssi; /* not a version bump */
    portEXIT_CRITICAL(&s_lock);
    mirror_to_model();
}

void wifi_service_status(wifi_svc_status_t *out)
{
    if (!out) return;
    portENTER_CRITICAL(&s_lock);
    *out = s_status;
    portEXIT_CRITICAL(&s_lock);
}

uint32_t wifi_service_version(void)
{
    portENTER_CRITICAL(&s_lock);
    const uint32_t version = s_version;
    portEXIT_CRITICAL(&s_lock);
    return version;
}

bool wifi_service_connected(void)
{
    portENTER_CRITICAL(&s_lock);
    const bool connected = s_status.state == WIFI_SVC_CONNECTED;
    portEXIT_CRITICAL(&s_lock);
    return connected;
}

const char *wifi_service_state_name(wifi_svc_state_t state)
{
    switch (state) {
    case WIFI_SVC_CONNECTING: return "connecting";
    case WIFI_SVC_CONNECTED: return "connected";
    case WIFI_SVC_FAILED: return "failed";
    default: return "off";
    }
}

const char *wifi_service_reason_name(wifi_svc_reason_t reason)
{
    switch (reason) {
    case WIFI_REASON_NO_COPROCESSOR: return "no_coprocessor";
    case WIFI_REASON_INIT: return "init";
    case WIFI_REASON_NO_AP: return "no_ap";
    case WIFI_REASON_AUTH: return "auth";
    case WIFI_REASON_NO_IP: return "no_ip";
    case WIFI_REASON_LOST: return "lost";
    case WIFI_REASON_CRASHED: return "crashed";
    case WIFI_REASON_STORAGE: return "storage";
    default: return "";
    }
}

/* ---- storage ---- */

static void wipe(void *data, size_t size)
{
    volatile unsigned char *bytes = (volatile unsigned char *)data;
    while (size--) *bytes++ = 0;
}

/* Writes a string key only when its value changed, so the same credentials do not wear the flash. */
static esp_err_t store_str(nvs_handle_t handle, const char *key, const char *value)
{
    char current[WIFI_PASSWORD_MAX + 1];
    size_t size = sizeof(current);
    const bool same = nvs_get_str(handle, key, current, &size) == ESP_OK && !strcmp(current, value);
    wipe(current, sizeof(current));
    return same ? ESP_OK : nvs_set_str(handle, key, value);
}

static void guard_write(uint8_t value)
{
    nvs_handle_t handle;
    if (nvs_open(NAMESPACE, NVS_READWRITE, &handle) != ESP_OK) return;
    uint8_t current = 0;
    if (nvs_get_u8(handle, "boot_guard", &current) != ESP_OK || current != value) {
        if (nvs_set_u8(handle, "boot_guard", value) == ESP_OK) nvs_commit(handle);
    }
    nvs_close(handle);
}

static bool load_credentials(wifi_credentials_t *out)
{
    nvs_handle_t handle;
    wifi_credentials_wipe(out);
    if (nvs_open(NAMESPACE, NVS_READONLY, &handle) != ESP_OK) return false;
    size_t ssid_size = sizeof(out->ssid), pass_size = sizeof(out->password);
    const bool ok = nvs_get_str(handle, "ssid", out->ssid, &ssid_size) == ESP_OK && out->ssid[0] &&
                    nvs_get_str(handle, "pass", out->password, &pass_size) == ESP_OK;
    nvs_close(handle);
    if (!ok) wifi_credentials_wipe(out);
    return ok;
}

/* ---- events, timers ---- */

static void post(wifi_msg_type_t type, uint16_t reason, uint32_t ip)
{
    const wifi_msg_t msg = {.type = (uint8_t)type, .reason = reason, .ip = ip};
    if (s_queue) xQueueSend(s_queue, &msg, 0);
}

static void on_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) post(EV_STA_START, 0, 0);
    else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_CONNECTED) post(EV_STA_CONNECTED, 0, 0);
    else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED)
        post(EV_STA_DISCONNECTED, data ? ((wifi_event_sta_disconnected_t *)data)->reason : 0, 0);
    else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP)
        post(EV_GOT_IP, 0, data ? ((ip_event_got_ip_t *)data)->ip_info.ip.addr : 0);
    else if (base == ESP_HOSTED_EVENT && id == ESP_HOSTED_EVENT_TRANSPORT_FAILURE) post(EV_TRANSPORT_FAILED, 0, 0);
}

static void on_timer(void *arg) { post((wifi_msg_type_t)(uintptr_t)arg, 0, 0); }

/* The task may sit inside a hosted call that never returns; this timer reports it all the same. */
static void on_init_timeout(void *arg)
{
    (void)arg;
    if (s_bringing_up && s_wanted) set_state(WIFI_SVC_FAILED, WIFI_REASON_NO_COPROCESSOR);
}

static esp_timer_handle_t make_timer(esp_timer_cb_t callback, wifi_msg_type_t type, const char *name)
{
    const esp_timer_create_args_t args = {.callback = callback, .arg = (void *)(uintptr_t)type, .name = name};
    esp_timer_handle_t timer = NULL;
    return esp_timer_create(&args, &timer) == ESP_OK ? timer : NULL;
}

static void timer_once(esp_timer_handle_t timer, int64_t delay_us)
{
    if (!timer) return;
    esp_timer_stop(timer);
    esp_timer_start_once(timer, (uint64_t)delay_us);
}

static void timer_stop(esp_timer_handle_t timer)
{
    if (timer) esp_timer_stop(timer);
}

static void stop_timers(void)
{
    timer_stop(s_retry_timer);
    timer_stop(s_dhcp_timer);
    timer_stop(s_rssi_timer);
}

/* 2, 4, 8, 16, 32, then 60 s, each +-20 %. */
static void schedule_retry(int64_t fixed_ms)
{
    int64_t delay_ms = fixed_ms;
    if (!delay_ms) {
        delay_ms = 2000LL << (s_backoff_step < 5 ? s_backoff_step : 5);
        if (delay_ms > BACKOFF_CAP_MS) delay_ms = BACKOFF_CAP_MS;
        if (s_backoff_step < 6) ++s_backoff_step;
    }
    const int64_t span = delay_ms * 2 / 5; /* 40 % wide, centred on the delay */
    delay_ms += (int64_t)(esp_random() % (uint32_t)(span + 1)) - span / 2;
    timer_once(s_retry_timer, delay_ms * 1000);
}

/* ---- bring-up ---- */

static bool crashed_last_boot(void)
{
    const esp_reset_reason_t reset = esp_reset_reason();
    return reset == ESP_RST_PANIC || reset == ESP_RST_INT_WDT || reset == ESP_RST_TASK_WDT || reset == ESP_RST_WDT;
}

static void read_identity(void)
{
    uint8_t mac[6] = {0};
    esp_hosted_coprocessor_fwver_t version;
    memset(&version, 0, sizeof(version));
    const bool have_mac = esp_wifi_get_mac(WIFI_IF_STA, mac) == ESP_OK;
    const bool have_version = esp_hosted_get_coprocessor_fwversion(&version) == 0;
    char text[16] = "";
    if (have_version)
        snprintf(text, sizeof(text), "%u.%u.%u", (unsigned)(version.major1 % 1000), (unsigned)(version.minor1 % 1000),
                 (unsigned)(version.patch1 % 1000));
    portENTER_CRITICAL(&s_lock);
    if (have_mac) memcpy(s_status.mac, mac, sizeof(mac));
    if (have_version) strlcpy(s_status.cp_version, text, sizeof(s_status.cp_version));
    portEXIT_CRITICAL(&s_lock);
    if (have_version) {
        ESP_LOGI(TAG, "C6 ESP-Hosted %s, host %d.%d", text, ESP_HOSTED_VERSION_MAJOR_1, ESP_HOSTED_VERSION_MINOR_1);
        if (version.major1 != ESP_HOSTED_VERSION_MAJOR_1 || version.minor1 != ESP_HOSTED_VERSION_MINOR_1)
            ESP_LOGW(TAG, "C6 firmware %s does not match the host's ESP-Hosted %d.%d", text, ESP_HOSTED_VERSION_MAJOR_1,
                     ESP_HOSTED_VERSION_MINOR_1);
    }
    if (have_mac) {
        char hostname[32];
        /* Stage B: the API's device name while the API is on, so DHCP and mDNS agree. */
        if (!api_server_hostname(hostname, sizeof(hostname)))
            snprintf(hostname, sizeof(hostname), "tessera-%02x%02x%02x", mac[3], mac[4], mac[5]);
        esp_netif_t *netif = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
        if (netif) esp_netif_set_hostname(netif, hostname);
    }
}

static void own_disconnect(bool stop)
{
    s_own_disconnect_us = esp_timer_get_time();
    if (stop) esp_wifi_stop();
    else esp_wifi_disconnect();
}

/* Netif, event loop, the C6 and esp_wifi_init. Sets FAILED and returns false when any of it fails. */
static bool bring_up(void)
{
    if (s_stack_up) return true;
    if (s_parked) {
        set_state(WIFI_SVC_FAILED, WIFI_REASON_NO_COPROCESSOR);
        return false;
    }
    ESP_LOGI(TAG, "Starting Wi-Fi; DMA heap free %u", (unsigned)heap_caps_get_free_size(MALLOC_CAP_DMA));
    static bool netif_ready = false;
    if (!netif_ready) {
        esp_err_t result = esp_netif_init();
        if (result == ESP_OK) {
            result = esp_event_loop_create_default();
            if (result == ESP_ERR_INVALID_STATE) result = ESP_OK;
        }
        if (result == ESP_OK && !esp_netif_create_default_wifi_sta()) result = ESP_FAIL;
        if (result == ESP_OK) {
            esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, on_event, NULL);
            esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, on_event, NULL);
            esp_event_handler_register(ESP_HOSTED_EVENT, ESP_HOSTED_EVENT_TRANSPORT_FAILURE, on_event, NULL);
        }
        if (result != ESP_OK) {
            ESP_LOGW(TAG, "Network setup failed: %s", esp_err_to_name(result));
            set_state(WIFI_SVC_FAILED, WIFI_REASON_INIT);
            return false;
        }
        netif_ready = true;
    }
    /* A crash from here to esp_wifi_init turns Wi-Fi off on the next boot (see crashed_last_boot). */
    guard_write(1);
    s_bringing_up = true;
    timer_once(s_init_timer, INIT_TIMEOUT_US);
    bool up = esp_hosted_init() == 0 && esp_hosted_connect_to_slave() == 0;
    const wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    const esp_err_t result = up ? esp_wifi_init(&init) : ESP_FAIL;
    up = up && result == ESP_OK;
    timer_stop(s_init_timer);
    s_bringing_up = false;
    guard_write(0);
    if (!up) {
        ESP_LOGW(TAG, "The Wi-Fi chip did not answer (%s); Wi-Fi stays off until new settings or a restart",
                 esp_err_to_name(result));
        s_parked = true;
        set_state(WIFI_SVC_FAILED, WIFI_REASON_NO_COPROCESSOR);
        return false;
    }
    s_stack_up = true;
    read_identity();
    ESP_LOGI(TAG, "Wi-Fi chip ready; DMA heap free %u, stack left %u",
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_DMA), (unsigned)uxTaskGetStackHighWaterMark(NULL));
    return true;
}

/* Loads the stored credentials into the C6 (RAM only), then starts or reconnects. */
static void apply_and_connect(void)
{
    wifi_credentials_t credentials;
    if (!load_credentials(&credentials)) {
        set_state(WIFI_SVC_FAILED, WIFI_REASON_STORAGE);
        return;
    }
    set_ssid(credentials.ssid);
    if (!bring_up()) {
        wifi_credentials_wipe(&credentials);
        return;
    }
    wifi_config_t config;
    memset(&config, 0, sizeof(config));
    memcpy(config.sta.ssid, credentials.ssid, strlen(credentials.ssid));
    memcpy(config.sta.password, credentials.password, strlen(credentials.password));
    config.sta.threshold.authmode = credentials.password[0] ? WIFI_AUTH_WPA2_PSK : WIFI_AUTH_OPEN;
    config.sta.pmf_cfg.capable = true;
    wifi_credentials_wipe(&credentials);
    if (s_started) own_disconnect(false);
    esp_err_t result = esp_wifi_set_storage(WIFI_STORAGE_RAM);
    if (result == ESP_OK) result = esp_wifi_set_mode(WIFI_MODE_STA);
    if (result == ESP_OK) result = esp_wifi_set_config(WIFI_IF_STA, &config);
    wipe(&config, sizeof(config));
    if (result == ESP_OK) esp_wifi_set_ps(WIFI_PS_NONE); /* reported to fix boot delays on this board */
    if (result == ESP_OK && !s_started) {
        result = esp_wifi_start(); /* connects on WIFI_EVENT_STA_START */
        s_started = result == ESP_OK;
    } else if (result == ESP_OK) {
        result = esp_wifi_connect();
    }
    if (result != ESP_OK) {
        ESP_LOGW(TAG, "Wi-Fi start failed: %s", esp_err_to_name(result));
        set_state(WIFI_SVC_FAILED, WIFI_REASON_INIT);
    }
}

/* ---- the task ---- */

static bool is_auth_reason(uint16_t reason)
{
    return reason == WIFI_REASON_AUTH_FAIL || reason == WIFI_REASON_4WAY_HANDSHAKE_TIMEOUT ||
           reason == WIFI_REASON_HANDSHAKE_TIMEOUT || reason == WIFI_REASON_AUTH_EXPIRE ||
           reason == WIFI_REASON_ASSOC_FAIL || reason == WIFI_REASON_MIC_FAILURE;
}

static bool is_no_ap_reason(uint16_t reason)
{
    return reason == WIFI_REASON_NO_AP_FOUND || reason == WIFI_REASON_NO_AP_FOUND_W_COMPATIBLE_SECURITY ||
           reason == WIFI_REASON_NO_AP_FOUND_IN_AUTHMODE_THRESHOLD ||
           reason == WIFI_REASON_NO_AP_FOUND_IN_RSSI_THRESHOLD;
}

static void on_disconnected(uint16_t reason)
{
    timer_stop(s_dhcp_timer);
    timer_stop(s_rssi_timer);
    /* Our own disconnect (new settings, the DHCP timeout, AD_WIFI_CLEAR): whoever called it goes on. */
    if (reason == WIFI_REASON_ASSOC_LEAVE && esp_timer_get_time() - s_own_disconnect_us < 5LL * 1000000) return;
    ESP_LOGI(TAG, "Disconnected (reason %u)", (unsigned)reason);
    wifi_svc_status_t now;
    wifi_service_status(&now);
    if (is_auth_reason(reason)) {
        s_no_ap_fails = 0;
        if (++s_auth_fails >= GIVE_UP_AFTER) {
            s_auth_fails = GIVE_UP_AFTER;
            set_state(WIFI_SVC_FAILED, WIFI_REASON_AUTH);
            schedule_retry(AUTH_RETRY_MS); /* a router may block a client that keeps guessing */
            return;
        }
    } else if (is_no_ap_reason(reason)) {
        s_auth_fails = 0;
        if (++s_no_ap_fails >= GIVE_UP_AFTER) {
            s_no_ap_fails = GIVE_UP_AFTER;
            set_state(WIFI_SVC_FAILED, WIFI_REASON_NO_AP);
            schedule_retry(BACKOFF_CAP_MS);
            return;
        }
    } else {
        s_auth_fails = s_no_ap_fails = 0;
    }
    if (s_was_connected) set_state(WIFI_SVC_CONNECTING, WIFI_REASON_LOST);
    else if (now.state != WIFI_SVC_FAILED) set_state(WIFI_SVC_CONNECTING, now.reason);
    schedule_retry(0);
}

static void on_got_ip(uint32_t address)
{
    timer_stop(s_dhcp_timer);
    timer_stop(s_retry_timer);
    s_was_connected = true;
    s_auth_fails = s_no_ap_fails = s_backoff_step = 0;
    char ip[16];
    const uint8_t *octet = (const uint8_t *)&address;
    snprintf(ip, sizeof(ip), "%u.%u.%u.%u", octet[0], octet[1], octet[2], octet[3]);
    const int8_t rssi = read_rssi();
    portENTER_CRITICAL(&s_lock);
    const bool changed = s_status.state != WIFI_SVC_CONNECTED || s_status.reason != WIFI_REASON_NONE ||
                         strcmp(s_status.ip, ip) != 0;
    s_status.state = WIFI_SVC_CONNECTED;
    s_status.reason = WIFI_REASON_NONE;
    strlcpy(s_status.ip, ip, sizeof(s_status.ip));
    s_status.rssi = rssi;
    if (changed) ++s_version;
    portEXIT_CRITICAL(&s_lock);
    ESP_LOGI(TAG, "Wi-Fi connected: %s, %d dBm", ip, rssi);
    mirror_to_model();
    if (s_rssi_timer) {
        esp_timer_stop(s_rssi_timer);
        esp_timer_start_periodic(s_rssi_timer, RSSI_PERIOD_US);
    }
}

static void handle(const wifi_msg_t *msg)
{
    if (msg->type == EV_CLEAR) {
        stop_timers();
        if (s_started && !s_wanted) {
            own_disconnect(true); /* the stack stays initialized: a deinit/init cycle over hosted is not trusted */
            s_started = false;
        }
        if (!s_wanted) set_state(WIFI_SVC_OFF, WIFI_REASON_NONE);
        return;
    }
    if (msg->type == EV_SET) {
        stop_timers();
        s_auth_fails = s_no_ap_fails = s_backoff_step = 0;
        s_was_connected = false;
        if (s_wanted) apply_and_connect();
        return;
    }
    if (!s_wanted || !s_started) return; /* left over from before AD_WIFI_CLEAR */
    switch (msg->type) {
    case EV_STA_START:
    case EV_RETRY:
        if (wifi_service_connected()) break;
        s_was_connected = false;
        esp_wifi_connect();
        break;
    case EV_STA_CONNECTED:
        timer_once(s_dhcp_timer, DHCP_TIMEOUT_US);
        break;
    case EV_STA_DISCONNECTED:
        on_disconnected(msg->reason);
        break;
    case EV_GOT_IP:
        on_got_ip(msg->ip);
        break;
    case EV_DHCP_TIMEOUT:
        set_state(WIFI_SVC_FAILED, WIFI_REASON_NO_IP);
        own_disconnect(false);
        schedule_retry(0);
        break;
    case EV_RSSI:
        if (wifi_service_connected()) set_rssi(read_rssi());
        break;
    case EV_TRANSPORT_FAILED:
        ESP_LOGW(TAG, "The link to the Wi-Fi chip failed; Wi-Fi stays off until new settings or a restart");
        stop_timers();
        s_parked = true;
        set_state(WIFI_SVC_FAILED, WIFI_REASON_NO_COPROCESSOR);
        break;
    default:
        break;
    }
}

static void wifi_task(void *arg)
{
    (void)arg;
    const int64_t uptime_ms = esp_timer_get_time() / 1000;
    if (uptime_ms < START_DELAY_MS) vTaskDelay(pdMS_TO_TICKS(START_DELAY_MS - uptime_ms));
    if (s_wanted) {
        nvs_handle_t handle;
        uint8_t guard = 0;
        if (nvs_open(NAMESPACE, NVS_READONLY, &handle) == ESP_OK) {
            nvs_get_u8(handle, "boot_guard", &guard);
            nvs_close(handle);
        }
        if (guard == 1 && crashed_last_boot()) {
            ESP_LOGW(TAG, "The last Wi-Fi start crashed the panel; Wi-Fi stays off until new settings");
            guard_write(0);
            set_state(WIFI_SVC_FAILED, WIFI_REASON_CRASHED);
        } else {
            post(EV_SET, 0, 0);
        }
    }
    for (;;) {
        wifi_msg_t msg;
        if (xQueueReceive(s_queue, &msg, portMAX_DELAY) == pdTRUE) handle(&msg);
    }
}

/* ---- public ---- */

esp_err_t wifi_service_init(void)
{
    if (s_queue) return ESP_OK;
    s_queue = xQueueCreate(16, sizeof(wifi_msg_t));
    if (!s_queue) return ESP_ERR_NO_MEM;
    s_init_timer = make_timer(on_init_timeout, EV_RETRY, "wifi_init");
    s_retry_timer = make_timer(on_timer, EV_RETRY, "wifi_retry");
    s_dhcp_timer = make_timer(on_timer, EV_DHCP_TIMEOUT, "wifi_dhcp");
    s_rssi_timer = make_timer(on_timer, EV_RSSI, "wifi_rssi");

    nvs_handle_t handle;
    char ssid[WIFI_SSID_MAX + 1] = "";
    const esp_err_t opened = nvs_open(NAMESPACE, NVS_READONLY, &handle);
    if (opened == ESP_OK) {
        size_t size = sizeof(ssid);
        size_t pass_size = 0;
        if (nvs_get_str(handle, "ssid", ssid, &size) != ESP_OK) ssid[0] = '\0';
        s_wanted = ssid[0] && nvs_get_str(handle, "pass", NULL, &pass_size) == ESP_OK;
        nvs_close(handle);
    }
    if (s_wanted) {
        strlcpy(s_status.ssid, ssid, sizeof(s_status.ssid));
        s_status.state = WIFI_SVC_CONNECTING;
        ESP_LOGI(TAG, "Wi-Fi network \"%s\" stored; starting in %d s", ssid, START_DELAY_MS / 1000);
    } else if (opened != ESP_OK && opened != ESP_ERR_NVS_NOT_FOUND) {
        s_status.state = WIFI_SVC_FAILED;
        s_status.reason = WIFI_REASON_STORAGE;
    }
    mirror_to_model();
    /* Internal stack (the default for xTaskCreate): hosted and flash calls must not run on PSRAM stacks. */
    if (xTaskCreatePinnedToCore(wifi_task, "tessera_wifi", 4096, NULL, 2, NULL, 1) != pdPASS) {
        ESP_LOGW(TAG, "Wi-Fi task not started");
        return ESP_ERR_NO_MEM;
    }
    return ESP_OK;
}

esp_err_t wifi_service_set(const wifi_credentials_t *credentials)
{
    if (!credentials || !credentials->ssid[0] || !s_queue) return ESP_ERR_INVALID_ARG;
    nvs_handle_t handle;
    esp_err_t result = nvs_open(NAMESPACE, NVS_READWRITE, &handle);
    if (result == ESP_OK) {
        result = store_str(handle, "ssid", credentials->ssid);
        if (result == ESP_OK) result = store_str(handle, "pass", credentials->password);
        if (result == ESP_OK) result = nvs_commit(handle);
        nvs_close(handle);
    }
    if (result != ESP_OK) {
        ESP_LOGW(TAG, "Wi-Fi settings not saved: %s", esp_err_to_name(result));
        return result;
    }
    s_wanted = true;
    s_parked = false; /* a new AD_WIFI_SET gives the C6 another chance (also after a crash) */
    set_ssid(credentials->ssid);
    set_state(WIFI_SVC_CONNECTING, WIFI_REASON_NONE);
    post(EV_SET, 0, 0);
    return ESP_OK;
}

esp_err_t wifi_service_clear(void)
{
    if (!s_queue) return ESP_ERR_INVALID_STATE;
    nvs_handle_t handle;
    esp_err_t result = nvs_open(NAMESPACE, NVS_READWRITE, &handle);
    if (result == ESP_OK) {
        /* Only Wi-Fi's own keys: the Home Assistant settings and key (api_*) share the namespace and stay. */
        static const char *const keys[] = {"ssid", "pass", "boot_guard"};
        for (size_t i = 0; i < sizeof(keys) / sizeof(keys[0]) && result == ESP_OK; ++i) {
            result = nvs_erase_key(handle, keys[i]);
            if (result == ESP_ERR_NVS_NOT_FOUND) result = ESP_OK;
        }
        if (result == ESP_OK) result = nvs_commit(handle);
        nvs_close(handle);
    }
    if (result != ESP_OK) {
        ESP_LOGW(TAG, "Wi-Fi settings not erased: %s", esp_err_to_name(result));
        return result;
    }
    s_wanted = false;
    set_ssid("");
    set_state(WIFI_SVC_OFF, WIFI_REASON_NONE);
    post(EV_CLEAR, 0, 0);
    return ESP_OK;
}
