#include "api_mdns.h"

#include <stdbool.h>

#include "api_messages.h"
#include "api_noise.h"
#include "api_server.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "mdns.h"

static const char *TAG = "api_mdns";
static bool s_running;

esp_err_t api_mdns_start(const api_mdns_info_t *info)
{
    api_mdns_stop();
    esp_err_t result = mdns_init();
    if (result != ESP_OK) {
        ESP_LOGW(TAG, "mDNS init failed: %s", esp_err_to_name(result));
        return result;
    }
    s_running = true;
    /* mdns_init came after GOT_IP, so the predefined STA netif has to be told it is up. */
    esp_netif_t *sta = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    if (sta) mdns_netif_action(sta, (mdns_event_actions_t)(MDNS_EVENT_ENABLE_IP4 | MDNS_EVENT_ANNOUNCE_IP4));
    mdns_txt_item_t txt[] = {
        {"friendly_name", info->friendly_name},
        {"version", API_ESPHOME_VERSION},
        {"mac", info->mac_hex}, /* 12 lowercase hex digits; HA needs it */
        {"platform", "ESP32"},
        {"board", "esp32-p4"},
        {"network", "wifi"},
        {"project_name", API_PROJECT_NAME},
        {"project_version", info->project_version},
        {"api_encryption", NOISE_PROTOCOL_NAME},
    };
    result = mdns_hostname_set(info->name);
    if (result == ESP_OK) result = mdns_instance_name_set(info->name);
    if (result == ESP_OK)
        result = mdns_service_add(info->name, "_esphomelib", "_tcp", API_PORT, txt, sizeof(txt) / sizeof(txt[0]));
    if (result != ESP_OK) {
        ESP_LOGW(TAG, "mDNS service not announced: %s", esp_err_to_name(result));
        api_mdns_stop();
        return result;
    }
    ESP_LOGI(TAG, "Announcing %s._esphomelib._tcp on port %d", info->name, API_PORT);
    return ESP_OK;
}

void api_mdns_stop(void)
{
    if (!s_running) return;
    mdns_free();
    s_running = false;
}
