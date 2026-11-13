#include "wifi_config.h"

#include <stddef.h>
#include <string.h>
#include "cJSON.h"

static void wipe_bytes(void *data, size_t size)
{
    volatile unsigned char *bytes = (volatile unsigned char *)data;
    while (size--) *bytes++ = 0;
}

void wifi_credentials_wipe(wifi_credentials_t *credentials)
{
    if (credentials) wipe_bytes(credentials, sizeof(*credentials));
}

/* A "\u0000" escape would end the C string early and hide the rest of the value: refuse it outright.
 * It is a real escape only when an even number of backslashes stands before its own backslash. */
static bool has_nul_escape(const char *json)
{
    for (const char *at = strstr(json, "\\u0000"); at; at = strstr(at + 1, "\\u0000")) {
        size_t before = 0;
        while (at - before > json && *(at - before - 1) == '\\') ++before;
        if (before % 2 == 0) return true;
    }
    return false;
}

/* Well-formed UTF-8 (no overlong forms, no surrogates), and no control character (C0, DEL or C1). */
static bool ssid_valid(const char *ssid)
{
    const size_t length = strlen(ssid);
    if (length < 1 || length > WIFI_SSID_MAX) return false;
    for (size_t i = 0; i < length;) {
        const unsigned char c = (unsigned char)ssid[i];
        size_t extra = 0;
        unsigned long code = 0;
        if (c < 0x20 || c == 0x7F) return false;
        if (c < 0x80) { ++i; continue; }
        if (c >= 0xC2 && c <= 0xDF) { extra = 1; code = c & 0x1F; }
        else if (c >= 0xE0 && c <= 0xEF) { extra = 2; code = c & 0x0F; }
        else if (c >= 0xF0 && c <= 0xF4) { extra = 3; code = c & 0x07; }
        else return false;
        if (i + extra >= length) return false;
        for (size_t k = 1; k <= extra; ++k) {
            const unsigned char next = (unsigned char)ssid[i + k];
            if ((next & 0xC0) != 0x80) return false;
            code = (code << 6) | (next & 0x3F);
        }
        if (code <= 0x9F) return false; /* C1 control */
        if (extra == 2 && (code < 0x800 || (code >= 0xD800 && code <= 0xDFFF))) return false;
        if (extra == 3 && (code < 0x10000 || code > 0x10FFFF)) return false;
        i += extra + 1;
    }
    return true;
}

static bool is_hex(char c)
{
    return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F');
}

static bool password_valid(const char *password)
{
    const size_t length = strlen(password);
    if (length == 0) return true; /* an open network */
    if (length == WIFI_PASSWORD_MAX) {
        for (size_t i = 0; i < length; ++i) if (!is_hex(password[i])) return false;
        return true;
    }
    if (length < 8 || length > 63) return false;
    for (size_t i = 0; i < length; ++i) {
        const unsigned char c = (unsigned char)password[i];
        if (c < 0x20 || c > 0x7E) return false;
    }
    return true;
}

bool wifi_config_from_json(const char *json, wifi_credentials_t *out, const char **field)
{
    const char *failed = "json";
    bool ok = false;
    cJSON *root = NULL;
    const cJSON *ssid = NULL;
    cJSON *password = NULL;
    if (out) wifi_credentials_wipe(out);
    if (!json || !out || has_nul_escape(json)) goto done;
    root = cJSON_Parse(json);
    if (!cJSON_IsObject(root)) goto done;
    ssid = cJSON_GetObjectItemCaseSensitive(root, "ssid");
    password = cJSON_GetObjectItemCaseSensitive(root, "password");
    failed = "ssid";
    if (!cJSON_IsString(ssid) || !ssid->valuestring || !ssid_valid(ssid->valuestring)) goto done;
    failed = "password";
    if (!cJSON_IsString(password) || !password->valuestring || !password_valid(password->valuestring)) goto done;
    memcpy(out->ssid, ssid->valuestring, strlen(ssid->valuestring) + 1);
    memcpy(out->password, password->valuestring, strlen(password->valuestring) + 1);
    ok = true;
done:
    /* The decoded password lives in cJSON's heap copy: zero it (every "password" key, should one repeat)
     * before cJSON frees it. */
    for (cJSON *item = cJSON_IsObject(root) ? root->child : NULL; item; item = item->next)
        if (item->string && !strcmp(item->string, "password") && cJSON_IsString(item) && item->valuestring)
            wipe_bytes(item->valuestring, strlen(item->valuestring));
    cJSON_Delete(root);
    if (!ok && out) wifi_credentials_wipe(out);
    if (field) *field = ok ? "" : failed;
    return ok;
}
