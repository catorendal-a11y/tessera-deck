#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    NETWORK_STATE_OFF = 0,
    NETWORK_STATE_PROVISIONING,  /* config AP active; waiting for phone setup */
    NETWORK_STATE_CONNECTING,
    NETWORK_STATE_CONNECTED,
    NETWORK_STATE_ERROR,
} network_state_t;

/* Coherent status snapshot: state, SSID and RSSI captured together so UI
 * consumers never mix values observed at different moments. */
typedef struct {
    network_state_t state;
    char ssid[33];
    int8_t rssi;
    char address[64]; /* Station IP or provisioning portal URL. */
} network_status_t;

void network_service_init(void);
network_status_t network_service_status(void);
network_state_t network_service_state(void);
void network_service_ssid(char *out, size_t out_size);
int network_service_rssi(void);
void network_service_retry(void);
void network_service_start_setup(void);
/* USB/phone provisioning; credentials are never included in status/logs. */
bool network_service_configure(const char *ssid, const char *password);
const char *network_service_state_text(network_state_t state);

#ifdef FQ_SIMULATOR_CAPTURE
/* Deterministic network transitions for native UI regression checks. */
void network_service_sim_set_state(network_state_t state);
void network_service_sim_set_ip_ready(bool ready);
#endif

#ifdef __cplusplus
}
#endif
