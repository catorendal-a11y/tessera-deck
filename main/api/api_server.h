#pragma once
/* ESPHome-compatible native API server on TCP 6053 (Noise only), with mDNS _esphomelib._tcp.
 * Off until AD_API_SET turns it on, and then it works only while Wi-Fi is connected: with Wi-Fi off it opens
 * no socket, starts no mDNS and does no crypto. docs/design/esphome.md, stage B. */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

#define API_PORT 6053

/* Loads the settings from NVS (tessera_net). Never starts a task or touches the network. */
esp_err_t api_server_init(void);
/* The USB console calls this every pass: it starts the tessera_api task once the API is on and Wi-Fi is up. */
void api_server_poll(void);
/* AD_API_SET, AD_API_KEY [NEW], AD_API_OPTIONS, AD_API_STATUS: answers on the console (printf). */
void api_server_command(const char *line);
/* Bumped when enabled, the name, the client count or "ha" changes; the console then prints the status line. */
uint32_t api_server_status_version(void);
void api_server_status_line(void);
/* The DHCP and mDNS hostname: the device name while the API is on; false when it is off. */
bool api_server_hostname(char *out, size_t size);

#ifdef __cplusplus
}
#endif
