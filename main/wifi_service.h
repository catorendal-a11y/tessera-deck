#pragma once
/* Wi-Fi through the ESP32-C6 (ESP-Hosted over SDIO). Off until AD_WIFI_SET stores credentials: without them
 * the hosted stack, the SDIO bus and the C6 reset pin are never touched. docs/design/esphome.md, A.2. */
#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"
#include "wifi_config.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    WIFI_SVC_OFF = 0,        /* no credentials, or cleared */
    WIFI_SVC_CONNECTING = 1, /* bringing up the C6, associating, or waiting for DHCP; also while retrying */
    WIFI_SVC_CONNECTED = 2,  /* has an IPv4 address */
    WIFI_SVC_FAILED = 3,     /* gave up for now; `reason` says why; may retry later (see backoff) */
} wifi_svc_state_t;

typedef enum {
    WIFI_REASON_NONE = 0,
    WIFI_REASON_NO_COPROCESSOR, /* no INIT from the C6 within 15 s, or esp_wifi_init failed on the transport */
    WIFI_REASON_INIT,           /* esp_netif/esp_wifi setup failed for another reason */
    WIFI_REASON_NO_AP,          /* SSID not found */
    WIFI_REASON_AUTH,           /* wrong password (3 auth failures in a row) */
    WIFI_REASON_NO_IP,          /* associated but no DHCP lease within 30 s */
    WIFI_REASON_LOST,           /* was connected; reconnecting (state CONNECTING) */
    WIFI_REASON_CRASHED,        /* the boot guard turned Wi-Fi off after a crash during bring-up */
    WIFI_REASON_STORAGE,        /* NVS could not be read or written */
} wifi_svc_reason_t;

typedef struct {
    wifi_svc_state_t state;
    wifi_svc_reason_t reason;
    char ssid[WIFI_SSID_MAX + 1]; /* configured SSID, "" when none; never the password */
    char ip[16];                  /* dotted IPv4 when CONNECTED, else "" */
    int8_t rssi;                  /* dBm when CONNECTED, else 0; refreshed every 30 s */
    uint8_t mac[6];               /* station MAC from the C6, zero until known */
    char cp_version[16];          /* C6 ESP-Hosted version "2.7.0", "" until known */
} wifi_svc_status_t;

esp_err_t wifi_service_init(void);  /* call once after nvs_flash_init(); never blocks, never aborts */
/* Validated credentials (see wifi_config_from_json). Stores them, then connects (or reconnects). */
esp_err_t wifi_service_set(const wifi_credentials_t *credentials);
esp_err_t wifi_service_clear(void); /* erase credentials, stop Wi-Fi, state OFF */
void wifi_service_status(wifi_svc_status_t *out);
uint32_t wifi_service_version(void); /* bumped on every change of state, reason, ip or ssid; not on RSSI */
const char *wifi_service_state_name(wifi_svc_state_t state);    /* "off" "connecting" "connected" "failed" */
const char *wifi_service_reason_name(wifi_svc_reason_t reason); /* "" "no_coprocessor" "init" "no_ap" ... */
/* Stage B uses this; stage A only defines it. */
bool wifi_service_connected(void);

#ifdef __cplusplus
}
#endif
