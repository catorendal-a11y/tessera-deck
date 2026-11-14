#pragma once
/* One ESPHome native API connection over Noise: framing, the handshake, Hello, Connect, Ping and Disconnect,
 * timeouts and keepalive. Every other message goes to `on_message`. Bytes in through api_session_feed, bytes
 * out through `write`. No sockets and no clock of its own, so tests/native drives it directly.
 * docs/design/esphome.md, B.2. */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "api_noise.h"
#include "api_proto.h"

#ifdef __cplusplus
extern "C" {
#endif

#define API_BUFFER 1536        /* each of rx, in, out and wire, per connection (PSRAM on the panel) */
#define API_MESSAGE_MAX 1024   /* the largest protobuf message accepted; a larger frame closes */
#define API_HANDSHAKE_MAX 128  /* handshake frames */
#define API_HELLO_TIMEOUT_MS 10000
#define API_PING_AFTER_MS 20000
#define API_DEAD_AFTER_MS 50000
#define API_VERSION_MAJOR 1
#define API_VERSION_MINOR 12

typedef enum {
    API_SESSION_HELLO = 0,     /* waiting for the client's Noise hello frame */
    API_SESSION_HANDSHAKE = 1, /* waiting for Noise message 1 */
    API_SESSION_DATA = 2,      /* encrypted frames */
    API_SESSION_CLOSED = 3,
} api_session_state_t;

typedef struct api_session api_session_t;
typedef bool (*api_write_fn)(void *ctx, const uint8_t *data, size_t len);
typedef void (*api_message_fn)(api_session_t *s, uint16_t type, const uint8_t *data, size_t len, void *ctx);

typedef struct {
    const char *name;        /* device name: server hello and HelloResponse */
    const char *mac_hex;     /* 12 lowercase hex digits, as ESPHome puts it in the server hello */
    const char *server_info; /* "Tessera <firmware version>" */
    const uint8_t *psk;      /* 32 bytes */
    api_write_fn write;
    api_message_fn on_message;
    void *ctx;
} api_session_config_t;

struct api_session {
    api_session_config_t config;
    api_session_state_t state;
    /* API_BUFFER bytes each, owned by the caller: received bytes, the decrypted message, the message being
     * encoded and its encrypted frame (PSA must not encrypt in place on ESP-IDF). */
    uint8_t *rx, *in, *out, *wire;
    size_t rx_len;
    noise_handshake_t hs;
    noise_cipher_t send, recv;
    int64_t opened_ms, heard_ms;
    bool hello;     /* HelloRequest answered */
    bool pinged;    /* our PingRequest is out */
    const char *why; /* the reason for the close, for the log */
};

void api_session_open(api_session_t *s, const api_session_config_t *config, uint8_t *buffers[4],
                      int64_t now_ms);
/* Returns false once the connection must be closed (s->why says why). */
bool api_session_feed(api_session_t *s, const uint8_t *data, size_t len, int64_t now_ms);
bool api_session_tick(api_session_t *s, int64_t now_ms);
void api_session_close(api_session_t *s, const char *why); /* wipes the keys */
bool api_session_ready(const api_session_t *s);            /* encrypted and HelloRequest answered */

/* Sending: encode the protobuf into the writer, then send it. Both return false when the connection is not
 * ready, the message does not fit, or the write failed (the session is then closed). */
pb_writer_t api_session_writer(api_session_t *s);
bool api_session_send(api_session_t *s, uint16_t type, const pb_writer_t *w);
bool api_session_send_empty(api_session_t *s, uint16_t type);

#ifdef __cplusplus
}
#endif
