#pragma once
/* Wi-Fi credentials as AD_WIFI_SET carries them. Pure C plus cJSON, so tests/native compiles it too. */
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

#define WIFI_SSID_MAX 32
#define WIFI_PASSWORD_MAX 64

typedef struct {
    char ssid[WIFI_SSID_MAX + 1];
    char password[WIFI_PASSWORD_MAX + 1];
} wifi_credentials_t;

/* Parses {"ssid":"...","password":"..."}. On failure returns false, wipes *out and sets *field to "json",
 * "ssid" or "password". Wipes every copy of the password it made (also inside cJSON) before it returns.
 * ssid: 1-32 bytes of UTF-8 after JSON decoding, no control character. password: "" (open network),
 * 8-63 printable ASCII characters (0x20-0x7E), or exactly 64 hex digits (a raw PSK). */
bool wifi_config_from_json(const char *json, wifi_credentials_t *out, const char **field);
void wifi_credentials_wipe(wifi_credentials_t *credentials); /* volatile memset */

#ifdef __cplusplus
}
#endif
