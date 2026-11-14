#pragma once
/* mDNS for the API (espressif/mdns): hostname = device name, service _esphomelib._tcp on 6053 with the TXT
 * records Home Assistant's ESPHome discovery reads. Started on Wi-Fi up, stopped on Wi-Fi down or API off. */
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    const char *name, *friendly_name, *mac_hex, *project_version;
} api_mdns_info_t;

esp_err_t api_mdns_start(const api_mdns_info_t *info);
void api_mdns_stop(void);

#ifdef __cplusplus
}
#endif
