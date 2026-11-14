#include "api_session.h"

#include <string.h>

#include "api_messages.h"

/* ESPHome Noise framing (esphome api_frame_helper_noise.cpp, aioesphomeapi _frame_helper/noise.py):
 * every frame is 0x01, a big-endian 16-bit length, then the body. */
#define FRAME_INDICATOR 0x01
#define FRAME_HEADER 3
#define PROLOGUE "NoiseAPIInit"

static const uint8_t *const NO_DATA = (const uint8_t *)"";

void api_session_open(api_session_t *s, const api_session_config_t *config, uint8_t *buffers[4], int64_t now_ms)
{
    memset(s, 0, sizeof(*s));
    s->config = *config;
    s->rx = buffers[0];
    s->in = buffers[1];
    s->out = buffers[2];
    s->wire = buffers[3];
    s->state = API_SESSION_HELLO;
    s->opened_ms = s->heard_ms = now_ms;
}

void api_session_close(api_session_t *s, const char *why)
{
    if (s->state == API_SESSION_CLOSED) return;
    s->state = API_SESSION_CLOSED;
    if (!s->why) s->why = why;
    noise_wipe(&s->hs, sizeof(s->hs));
    noise_wipe(&s->send, sizeof(s->send));
    noise_wipe(&s->recv, sizeof(s->recv));
    if (s->in) noise_wipe(s->in, API_BUFFER);
    s->rx_len = 0;
}

bool api_session_ready(const api_session_t *s)
{
    return s->state == API_SESSION_DATA && s->hello;
}

static bool write_frame(api_session_t *s, uint8_t *frame, size_t body_len)
{
    frame[0] = FRAME_INDICATOR;
    frame[1] = (uint8_t)(body_len >> 8);
    frame[2] = (uint8_t)body_len;
    if (s->config.write(s->config.ctx, frame, FRAME_HEADER + body_len)) return true;
    api_session_close(s, "write failed");
    return false;
}

/* The explicit handshake reject: a frame with 0x01 and the reason. aioesphomeapi turns "Handshake MAC failure"
 * into InvalidEncryptionKeyAPIError, and a plaintext client that reads a 0x01 indicator raises
 * RequiresEncryptionAPIError. */
static bool reject(api_session_t *s, const char *reason)
{
    const size_t len = strlen(reason);
    s->wire[FRAME_HEADER] = 0x01;
    memcpy(s->wire + FRAME_HEADER + 1, reason, len);
    write_frame(s, s->wire, 1 + len);
    api_session_close(s, reason);
    return false;
}

static bool server_hello(api_session_t *s, const uint8_t *client_hello, size_t len)
{
    /* The prologue is "NoiseAPIInit" plus each client hello as a big-endian length and its bytes; the
     * client hello aioesphomeapi sends is empty, which gives "NoiseAPIInit\0\0". */
    uint8_t prologue[sizeof(PROLOGUE) - 1 + 2 + API_HANDSHAKE_MAX];
    const size_t base = sizeof(PROLOGUE) - 1;
    memcpy(prologue, PROLOGUE, base);
    prologue[base] = (uint8_t)(len >> 8);
    prologue[base + 1] = (uint8_t)len;
    if (len) memcpy(prologue + base + 2, client_hello, len);
    if (noise_init(&s->hs, false, prologue, base + 2 + len)) {
        api_session_close(s, "noise init");
        return false;
    }
    const size_t name_len = strlen(s->config.name), mac_len = strlen(s->config.mac_hex);
    uint8_t *body = s->wire + FRAME_HEADER;
    if (name_len + mac_len + 3 > API_HANDSHAKE_MAX) {
        api_session_close(s, "name too long");
        return false;
    }
    body[0] = 0x01; /* the chosen protocol: Noise_NNpsk0_25519_ChaChaPoly_SHA256 */
    memcpy(body + 1, s->config.name, name_len + 1);
    memcpy(body + 2 + name_len, s->config.mac_hex, mac_len + 1);
    if (!write_frame(s, s->wire, name_len + mac_len + 3)) return false;
    s->state = API_SESSION_HANDSHAKE;
    return true;
}

static bool handshake(api_session_t *s, const uint8_t *body, size_t len)
{
    if (!len) return reject(s, "Empty handshake message");
    if (body[0] != 0x00) return reject(s, "Bad handshake error byte");
    size_t payload_len = 0;
    const int read = noise_read_message1(&s->hs, s->config.psk, body + 1, len - 1, s->in, API_BUFFER, &payload_len);
    if (read == -1) return reject(s, "Handshake MAC failure");
    if (read) return reject(s, "Handshake error");
    uint8_t *reply = s->wire + FRAME_HEADER;
    size_t reply_len = 0;
    reply[0] = 0x00; /* status OK, then Noise message 2 (e, ee) */
    if (noise_write_message2(&s->hs, NULL, 0, reply + 1, API_HANDSHAKE_MAX - 1, &reply_len) ||
        noise_split(&s->hs, &s->send, &s->recv))
        return reject(s, "Handshake error");
    if (!write_frame(s, s->wire, 1 + reply_len)) return false;
    s->state = API_SESSION_DATA;
    return true;
}

pb_writer_t api_session_writer(api_session_t *s)
{
    pb_writer_t w;
    pb_writer_init(&w, s->out + 4, API_MESSAGE_MAX);
    return w;
}

bool api_session_send(api_session_t *s, uint16_t type, const pb_writer_t *w)
{
    if (s->state != API_SESSION_DATA || w->overflow || w->buf != s->out + 4) return false;
    const size_t len = w->len;
    s->out[0] = (uint8_t)(type >> 8);
    s->out[1] = (uint8_t)type;
    s->out[2] = (uint8_t)(len >> 8);
    s->out[3] = (uint8_t)len;
    if (noise_encrypt(&s->send, s->out, 4 + len, s->wire + FRAME_HEADER)) {
        api_session_close(s, "nonce exhausted");
        return false;
    }
    return write_frame(s, s->wire, 4 + len + NOISE_TAG);
}

bool api_session_send_empty(api_session_t *s, uint16_t type)
{
    pb_writer_t w = api_session_writer(s);
    return api_session_send(s, type, &w);
}

static bool message(api_session_t *s, uint16_t type, const uint8_t *data, size_t len)
{
    if (!s->hello && type != API_HELLO_REQUEST) {
        api_session_close(s, "message before hello");
        return false;
    }
    switch (type) {
    case API_HELLO_REQUEST: {
        api_hello_request_t hello;
        if (!api_decode_hello_request(data, len, &hello)) {
            api_session_close(s, "bad hello");
            return false;
        }
        pb_writer_t w = api_session_writer(s);
        const api_hello_response_t response = {API_VERSION_MAJOR, API_VERSION_MINOR, s->config.server_info,
                                               s->config.name};
        api_encode_hello_response(&w, &response);
        if (!api_session_send(s, API_HELLO_RESPONSE, &w)) return false;
        s->hello = true;
        break;
    }
    case API_CONNECT_REQUEST: {
        pb_writer_t w = api_session_writer(s);
        api_encode_connect_response(&w, false);
        return api_session_send(s, API_CONNECT_RESPONSE, &w);
    }
    case API_DISCONNECT_REQUEST:
        api_session_send_empty(s, API_DISCONNECT_RESPONSE);
        api_session_close(s, "client disconnected");
        return false;
    case API_DISCONNECT_RESPONSE:
        api_session_close(s, "disconnect answered");
        return false;
    case API_PING_REQUEST:
        return api_session_send_empty(s, API_PING_RESPONSE);
    case API_PING_RESPONSE:
        break;
    default:
        if (s->config.on_message) s->config.on_message(s, type, len ? data : NO_DATA, len, s->config.ctx);
        break;
    }
    return s->state != API_SESSION_CLOSED;
}

static bool data_frame(api_session_t *s, const uint8_t *body, size_t len)
{
    if (len < 4 + NOISE_TAG || noise_decrypt(&s->recv, body, len, s->in)) {
        api_session_close(s, "bad data frame");
        return false;
    }
    const size_t plain = len - NOISE_TAG;
    const uint16_t type = (uint16_t)(s->in[0] << 8 | s->in[1]);
    const size_t data_len = (size_t)(s->in[2] << 8 | s->in[3]);
    if (data_len > plain - 4) {
        api_session_close(s, "bad data length");
        return false;
    }
    return message(s, type, s->in + 4, data_len);
}

/* One complete frame in rx: returns its size, 0 while incomplete, -1 when the connection is closed. */
static int next_frame(api_session_t *s)
{
    if (!s->rx_len) return 0;
    if (s->rx[0] != FRAME_INDICATOR) {
        /* A plaintext client starts with 0x00; it gets the reject so aioesphomeapi can say "requires
         * encryption". Anything else closes at once. */
        if (s->rx[0] == 0x00 && s->state != API_SESSION_DATA) reject(s, "Bad indicator byte");
        else api_session_close(s, "bad indicator");
        return -1;
    }
    if (s->rx_len < FRAME_HEADER) return 0;
    const size_t body = (size_t)(s->rx[1] << 8 | s->rx[2]);
    if (s->state != API_SESSION_DATA && body > API_HANDSHAKE_MAX) {
        reject(s, "Bad handshake packet len");
        return -1;
    }
    if (body > 4 + API_MESSAGE_MAX + NOISE_TAG) {
        api_session_close(s, "frame too large");
        return -1;
    }
    return s->rx_len >= FRAME_HEADER + body ? (int)(FRAME_HEADER + body) : 0;
}

bool api_session_feed(api_session_t *s, const uint8_t *data, size_t len, int64_t now_ms)
{
    if (s->state == API_SESSION_CLOSED) return false;
    s->heard_ms = now_ms;
    s->pinged = false;
    while (len || s->rx_len) {
        const size_t room = API_BUFFER - s->rx_len, take = len < room ? len : room;
        if (take) memcpy(s->rx + s->rx_len, data, take);
        s->rx_len += take;
        data += take;
        len -= take;
        const int frame = next_frame(s);
        if (frame < 0) return false;
        if (frame == 0) {
            if (len) { /* cannot happen: every allowed frame fits in rx */
                api_session_close(s, "rx overflow");
                return false;
            }
            break;
        }
        const uint8_t *body = s->rx + FRAME_HEADER;
        const size_t body_len = (size_t)frame - FRAME_HEADER;
        bool alive;
        if (s->state == API_SESSION_HELLO) alive = server_hello(s, body, body_len);
        else if (s->state == API_SESSION_HANDSHAKE) alive = handshake(s, body, body_len);
        else alive = data_frame(s, body, body_len);
        if (!alive) return false;
        memmove(s->rx, s->rx + frame, s->rx_len - (size_t)frame);
        s->rx_len -= (size_t)frame;
    }
    return true;
}

bool api_session_tick(api_session_t *s, int64_t now_ms)
{
    if (s->state == API_SESSION_CLOSED) return false;
    if (!api_session_ready(s)) {
        if (now_ms - s->opened_ms > API_HELLO_TIMEOUT_MS) api_session_close(s, "handshake timeout");
        return s->state != API_SESSION_CLOSED;
    }
    const int64_t quiet = now_ms - s->heard_ms;
    if (quiet > API_DEAD_AFTER_MS) {
        api_session_close(s, "keepalive timeout");
        return false;
    }
    if (quiet > API_PING_AFTER_MS && !s->pinged) {
        s->pinged = true;
        return api_session_send_empty(s, API_PING_REQUEST);
    }
    return true;
}
