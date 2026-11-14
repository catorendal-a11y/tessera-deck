#pragma once
/* Noise_NNpsk0_25519_ChaChaPoly_SHA256 (noiseprotocol.org rev 34), as ESPHome's native API uses it:
 *   -> psk, e
 *   <- e, ee
 * The panel is the responder. The initiator half exists for the native tests (a test client in the same
 * process). Pure C on top of api_crypto.h. docs/design/esphome.md, B.1 and B.2. */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define NOISE_PROTOCOL_NAME "Noise_NNpsk0_25519_ChaChaPoly_SHA256"
#define NOISE_KEY 32
#define NOISE_TAG 16
#define NOISE_MAX_NONCE 0xFFFFFFFFULL /* B.2: a counter reaching 2^32 closes the connection */

typedef struct {
    uint8_t k[NOISE_KEY];
    uint64_t n;
    bool has_key;
} noise_cipher_t;

typedef struct {
    uint8_t ck[32];
    uint8_t h[32];
    noise_cipher_t c;
    uint8_t e_priv[32];
    uint8_t e_pub[32];
    uint8_t re[32];
    bool initiator;
    bool has_e; /* an ephemeral was set (tests) or made */
    int step;   /* 0: message 1 next, 1: message 2 next, 2: done */
} noise_handshake_t;

/* Hash the protocol name, MixHash(prologue). The PSK goes in with message 1 (psk0). */
int noise_init(noise_handshake_t *hs, bool initiator, const uint8_t *prologue, size_t prologue_len);
/* Tests only: a fixed ephemeral private key instead of a random one. */
int noise_set_ephemeral(noise_handshake_t *hs, const uint8_t private_key[32]);
/* Message 1 (initiator writes, responder reads): 32 bytes e + payload + 16-byte tag. */
int noise_write_message1(noise_handshake_t *hs, const uint8_t psk[32], const uint8_t *payload, size_t len,
                         uint8_t *out, size_t cap, size_t *out_len);
/* Returns 0, -1 for a bad tag (wrong PSK: "Handshake MAC failure"), -2 for a malformed message. */
int noise_read_message1(noise_handshake_t *hs, const uint8_t psk[32], const uint8_t *msg, size_t len,
                        uint8_t *payload, size_t cap, size_t *payload_len);
/* Message 2 (responder writes, initiator reads): 32 bytes e + payload + tag. Same return codes. */
int noise_write_message2(noise_handshake_t *hs, const uint8_t *payload, size_t len, uint8_t *out, size_t cap,
                         size_t *out_len);
int noise_read_message2(noise_handshake_t *hs, const uint8_t *msg, size_t len, uint8_t *payload, size_t cap,
                        size_t *payload_len);
/* After message 2: the initiator sends with c1 and the responder with c2. Wipes the handshake state. */
int noise_split(noise_handshake_t *hs, noise_cipher_t *send, noise_cipher_t *recv);
void noise_handshake_hash(const noise_handshake_t *hs, uint8_t out[32]); /* valid before noise_split */

/* Transport messages (no associated data). -1 on a bad tag or an exhausted nonce. in and out never overlap. */
int noise_encrypt(noise_cipher_t *c, const uint8_t *in, size_t len, uint8_t *out);
int noise_decrypt(noise_cipher_t *c, const uint8_t *in, size_t len, uint8_t *out);
void noise_wipe(void *data, size_t len);

#ifdef __cplusplus
}
#endif
