#include "network_service.h"

#ifndef FQ_SIMULATOR_CAPTURE

#include <wifi_manager.h>
#include <ssid_manager.h>

#include <cstring>
#include <string>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "nvs_flash.h"
#include "esp_wifi.h"
#include <stdio.h>

static const char *TAG = "fq_network";

static network_state_t s_state = NETWORK_STATE_OFF;
static char s_ssid[33];
static SemaphoreHandle_t s_lock;
static TaskHandle_t s_worker;
static network_status_t s_snapshot;
static constexpr uint32_t RETRY = 1, SETUP = 2, CONFIGURE = 4;
static char s_pending_ssid[33], s_pending_password[65];

static void state_lock(void)
{
    if (s_lock) {
        xSemaphoreTake(s_lock, portMAX_DELAY);
    }
}

static void state_unlock(void)
{
    if (s_lock) {
        xSemaphoreGive(s_lock);
    }
}

static void set_state(network_state_t state, const char *ssid)
{
    state_lock();
    s_state = state;
    s_snapshot.state = state;
    if (state != NETWORK_STATE_CONNECTED) {
        s_snapshot.rssi = 0;
        s_snapshot.address[0] = '\0';
    }
    if (ssid) {
        snprintf(s_ssid, sizeof(s_ssid), "%s", ssid);
        snprintf(s_snapshot.ssid, sizeof(s_snapshot.ssid), "%s", ssid);
    }
    state_unlock();
}

static void network_worker(void *)
{
    auto &wifi_manager = WifiManager::GetInstance();
    WifiManagerConfig config;
    config.ssid_prefix = "FamilyQuest";
    config.language = "en-US";
    config.station_hostname = "family-quest";
    wifi_manager.SetEventCallback([](WifiEvent event, const std::string &data) {
        switch (event) {
        case WifiEvent::Connected:
            set_state(NETWORK_STATE_CONNECTED, data.empty() ? nullptr : data.c_str());
            {
                uint8_t mac[6] = {0};
                if (esp_wifi_get_mac(WIFI_IF_STA, mac) == ESP_OK) {
                    ESP_LOGI(TAG, "Station MAC %02x:%02x:%02x:%02x:%02x:%02x",
                             mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
                }
                /* Marginal uplink: force maximum TX power once the radio
                 * is up (before start the call returns NOT_STARTED). */
                int8_t power_before = 0;
                esp_wifi_get_max_tx_power(&power_before);
                esp_err_t power_err = esp_wifi_set_max_tx_power(84);
                int8_t power_after = 0;
                esp_wifi_get_max_tx_power(&power_after);
                ESP_LOGI(TAG, "Wi-Fi TX effekt: %d -> %d (0.25 dBm), %s",
                         power_before, power_after, esp_err_to_name(power_err));
            }
            break;
        case WifiEvent::Connecting:
            set_state(NETWORK_STATE_CONNECTING, data.c_str());
            break;
        case WifiEvent::Disconnected:
            set_state(NETWORK_STATE_CONNECTING, nullptr);
            break;
        case WifiEvent::ConfigModeEnter:
            set_state(NETWORK_STATE_PROVISIONING, nullptr);
            break;
        case WifiEvent::ConfigModeExit:
            set_state(NETWORK_STATE_CONNECTING, nullptr);
            break;
        case WifiEvent::Scanning:
            break;
        }
    });

    uint32_t pending_command = 0;
    for (;;) {
        /* Preflight NVS: Initialize otherwise erases a full/incompatible NVS. */
        esp_err_t err = nvs_flash_init();
        if (err == ESP_OK && wifi_manager.Initialize(config)) {
            /* Mains-powered panel: disable modem power save. With the
             * default MIN_MODEM the station sleeps between beacons and
             * large TX bursts (the 19 KB dashboard) stall against weak RF
             * while small responses squeak through — httpd ends with
             * EAGAIN on send and the phone never loads the page. */
            esp_err_t ps_err = esp_wifi_set_ps(WIFI_PS_NONE);
            ESP_LOGI(TAG, "Wi-Fi power save off: %s", esp_err_to_name(ps_err));
            break;
        }
        set_state(NETWORK_STATE_ERROR, "");
        ESP_LOGE(TAG, "Network initialization failed; local UI remains available");
        uint32_t command;
        xTaskNotifyWait(0, UINT32_MAX, &command, portMAX_DELAY);
        pending_command |= command;
    }

    auto &wifi_manager2 = WifiManager::GetInstance();
    if (wifi_manager2.IsConnected()) {
        set_state(NETWORK_STATE_CONNECTED, wifi_manager2.GetSsid().c_str());
        ESP_LOGI(TAG, "WiFi already connected");
    } else if (!SsidManager::GetInstance().GetSsidList().empty()) {
        ESP_LOGI(TAG, "WiFi credentials found; connecting");
        set_state(NETWORK_STATE_CONNECTING, SsidManager::GetInstance().GetSsidList().front().ssid.c_str());
        wifi_manager.StartStation();
    } else {
        ESP_LOGI(TAG, "No WiFi credentials; starting phone provisioning AP");
        set_state(NETWORK_STATE_PROVISIONING, nullptr);
        wifi_manager.StartConfigAp();
    }
    bool was_config_mode = wifi_manager.IsConfigMode();
    bool was_connected = false;
    for (;;) {
        uint32_t command = pending_command;
        pending_command = 0;
        if (!command) xTaskNotifyWait(0, UINT32_MAX, &command, pdMS_TO_TICKS(2000));
        if (command & CONFIGURE) {
            char ssid[33], password[65];
            state_lock();
            memcpy(ssid, s_pending_ssid, sizeof(ssid));
            memcpy(password, s_pending_password, sizeof(password));
            memset(s_pending_password, 0, sizeof(s_pending_password));
            state_unlock();
            SsidManager::GetInstance().AddSsid(ssid, password);
            memset(password, 0, sizeof(password));
            wifi_manager.StopStation();
            set_state(NETWORK_STATE_CONNECTING, ssid);
            wifi_manager.StartStation();
            ESP_LOGI(TAG, "Provisioning credentials accepted");
        } else if (command & SETUP) wifi_manager.StartConfigAp();
        else if (command & RETRY) {
            if (SsidManager::GetInstance().GetSsidList().empty()) wifi_manager.StartConfigAp();
            else { wifi_manager.StopStation(); wifi_manager.StartStation(); }
        } else if (was_config_mode && !wifi_manager.IsConfigMode() && !wifi_manager.IsConnected()) {
            /* Portal completion only stops AP; explicitly start the station. */
            wifi_manager.StartStation();
        }
        was_config_mode = wifi_manager.IsConfigMode();
        network_status_t snapshot = {};
        state_lock();
        snapshot.state = s_state;
        snprintf(snapshot.ssid, sizeof(snapshot.ssid), "%s", s_ssid);
        state_unlock();
        if (wifi_manager.IsConfigMode()) {
            was_connected = false;
            snapshot.state = NETWORK_STATE_PROVISIONING;
            auto ssid = wifi_manager.GetApSsid();
            auto url = wifi_manager.GetApWebUrl();
            snprintf(snapshot.ssid, sizeof(snapshot.ssid), "%s", ssid.c_str());
            snprintf(snapshot.address, sizeof(snapshot.address), "%s", url.c_str());
        } else if (wifi_manager.IsConnected()) {
            snapshot.state = NETWORK_STATE_CONNECTED;
            auto ssid = wifi_manager.GetSsid();
            auto ip = wifi_manager.GetIpAddress();
            if (ssid.empty()) {
                wifi_ap_record_t ap = {};
                if (esp_wifi_sta_get_ap_info(&ap) == ESP_OK)
                    ssid.assign(reinterpret_cast<const char *>(ap.ssid), strnlen(reinterpret_cast<const char *>(ap.ssid), sizeof(ap.ssid)));
            }
            snprintf(snapshot.ssid, sizeof(snapshot.ssid), "%s", ssid.c_str());
            snprintf(snapshot.address, sizeof(snapshot.address), "%s", ip.c_str());
            /* RSSI costs an RPC round-trip to the co-processor; polling it
             * every loop wedged the hosted control channel (each timed-out
             * request blocks 5 s and the channel never recovers). Read it
             * once per connection instead. */
            state_lock();
            snapshot.rssi = s_snapshot.rssi;
            state_unlock();
            /* Never hold the UI snapshot mutex across a blocking radio RPC. */
            if (!was_connected) snapshot.rssi = wifi_manager.GetRssi();
            was_connected = true;
        } else {
            was_connected = false;
            state_lock();
            snapshot.rssi = s_snapshot.rssi; /* keep last known */
            state_unlock();
        }
        state_lock();
        if (s_state == snapshot.state) s_snapshot = snapshot;
        state_unlock();
    }
}

void network_service_init(void)
{
    if (s_worker) return;
    if (!s_lock) s_lock = xSemaphoreCreateMutex();
    if (!s_lock) { s_snapshot.state = NETWORK_STATE_ERROR; return; }
    set_state(NETWORK_STATE_CONNECTING, "");
    if (xTaskCreate(network_worker, "fq_network", 8192, nullptr, 3, &s_worker) != pdPASS) {
        s_worker = nullptr;
        set_state(NETWORK_STATE_ERROR, "");
    }
}

network_status_t network_service_status(void)
{
    /* No radio RPC or WifiManager mutex on the LVGL/main task. */
    state_lock();
    network_status_t snapshot = s_snapshot;
    state_unlock();
    return snapshot;
}

network_state_t network_service_state(void)
{
    return network_service_status().state;
}

void network_service_ssid(char *out, size_t out_size)
{
    if (!out || out_size == 0) {
        return;
    }
    network_status_t snapshot = network_service_status();
    snprintf(out, out_size, "%s", snapshot.ssid);
}

int network_service_rssi(void)
{
    return network_service_status().rssi;
}

void network_service_retry(void)
{
    if (!s_worker) network_service_init();
    else xTaskNotify(s_worker, RETRY, eSetBits);
}

void network_service_start_setup(void)
{
    if (!s_worker) network_service_init();
    if (s_worker) xTaskNotify(s_worker, SETUP, eSetBits);
}

const char *network_service_state_text(network_state_t state)
{
    switch (state) {
    case NETWORK_STATE_CONNECTED: return "Tilkoblet";
    case NETWORK_STATE_CONNECTING: return "Kobler til";
    case NETWORK_STATE_PROVISIONING: return "Venter på oppsett";
    case NETWORK_STATE_ERROR: return "Nettverksfeil";
    case NETWORK_STATE_OFF: break;
    }
    return "Av";
}

bool network_service_configure(const char *ssid, const char *password)
{
    if (!ssid || !ssid[0] || strlen(ssid) > 32 || !password || strlen(password) > 64 ||
        (password[0] && strlen(password) < 8) || !s_worker || !s_lock) return false;
    state_lock();
    snprintf(s_pending_ssid, sizeof(s_pending_ssid), "%s", ssid);
    snprintf(s_pending_password, sizeof(s_pending_password), "%s", password);
    state_unlock();
    xTaskNotify(s_worker, CONFIGURE, eSetBits);
    return true;
}

#else /* FQ_SIMULATOR_CAPTURE */

/* Simulator: static state so screens and audits can exercise all views. */
#include <stdio.h>
#include <string.h>

static network_state_t s_state = NETWORK_STATE_CONNECTED;
static const char *s_ssid = "Hjemmenett";
static bool s_ip_ready = true;

void network_service_sim_set_ip_ready(bool ready) { s_ip_ready = ready; }

void network_service_sim_set_state(network_state_t state)
{
    s_state = state;
}

void network_service_init(void)
{
}

network_status_t network_service_status(void)
{
    network_status_t snapshot = {};
    snapshot.state = s_state;
    snprintf(snapshot.ssid, sizeof(snapshot.ssid), "%s", s_state == NETWORK_STATE_PROVISIONING ? "FamilyQuest-Setup" :
             s_state == NETWORK_STATE_OFF || s_state == NETWORK_STATE_ERROR ? "" : s_ssid);
    snprintf(snapshot.address, sizeof(snapshot.address), "%s", s_state == NETWORK_STATE_PROVISIONING ? "http://192.168.4.1" :
             s_state == NETWORK_STATE_CONNECTED && s_ip_ready ? "192.168.1.50" : "");
    snapshot.rssi = s_state == NETWORK_STATE_CONNECTED ? -45 : 0;
    return snapshot;
}

network_state_t network_service_state(void)
{
    return network_service_status().state;
}

void network_service_ssid(char *out, size_t out_size)
{
    if (!out || out_size == 0) {
        return;
    }
    network_status_t snapshot = network_service_status();
    snprintf(out, out_size, "%s", snapshot.ssid);
}

int network_service_rssi(void)
{
    return network_service_status().rssi;
}

void network_service_retry(void)
{
    if (s_state != NETWORK_STATE_CONNECTED) {
        s_state = NETWORK_STATE_PROVISIONING;
    }
}

void network_service_start_setup(void) { s_state = NETWORK_STATE_PROVISIONING; }
bool network_service_configure(const char *, const char *) { return false; }

const char *network_service_state_text(network_state_t state)
{
    switch (state) {
    case NETWORK_STATE_CONNECTED: return "Tilkoblet";
    case NETWORK_STATE_CONNECTING: return "Kobler til";
    case NETWORK_STATE_PROVISIONING: return "Venter på oppsett";
    case NETWORK_STATE_ERROR: return "Nettverksfeil";
    case NETWORK_STATE_OFF: break;
    }
    return "Av";
}

#endif
