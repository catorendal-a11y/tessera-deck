#include "api_noise.h"

#include <string.h>

#include "api_crypto.h"

void noise_wipe(void *data, size_t len)
{
    volatile uint8_t *p = (volatile uint8_t *)data;
    while (len--) *p++ = 0;
}

static void nonce_bytes(uint64_t n, uint8_t out[12])
{
    memset(out, 0, 4);
    for (int i = 0; i < 8; ++i) out[4 + i] = (uint8_t)(n >> (8 * i));
}

static int mix_hash(noise_handshake_t *hs, const uint8_t *data, size_t len)
{
    return api_sha256(hs->h, sizeof(hs->h), data, len, hs->h);
}

/* HKDF(ck, ikm) with two or three outputs (Noise section 4.3). */
static int hkdf(const uint8_t ck[32], const uint8_t *ikm, size_t ikm_len, uint8_t *o1, uint8_t *o2, uint8_t *o3)
{
    uint8_t temp[32], block[33] = {0};
    int failed = api_hmac_sha256(ck, ikm_len ? ikm : block, ikm_len, temp);
    block[0] = 1;
    failed |= api_hmac_sha256(temp, block, 1, o1);
    memcpy(block, o1, 32);
    block[32] = 2;
    failed |= api_hmac_sha256(temp, block, 33, o2);
    if (o3) {
        memcpy(block, o2, 32);
        block[32] = 3;
        failed |= api_hmac_sha256(temp, block, 33, o3);
    }
    noise_wipe(temp, sizeof(temp));
    noise_wipe(block, sizeof(block));
    return failed ? -1 : 0;
}

static void set_key(noise_cipher_t *c, const uint8_t key[32])
{
    memcpy(c->k, key, NOISE_KEY);
    c->n = 0;
    c->has_key = true;
}

static int mix_key(noise_handshake_t *hs, const uint8_t *ikm, size_t len)
{
    uint8_t ck[32], k[32];
    const int failed = hkdf(hs->ck, ikm, len, ck, k, NULL);
    memcpy(hs->ck, ck, sizeof(ck));
    set_key(&hs->c, k);
    noise_wipe(ck, sizeof(ck));
    noise_wipe(k, sizeof(k));
    return failed;
}

static int mix_key_and_hash(noise_handshake_t *hs, const uint8_t *ikm, size_t len)
{
    uint8_t ck[32], th[32], k[32];
    int failed = hkdf(hs->ck, ikm, len, ck, th, k);
    memcpy(hs->ck, ck, sizeof(ck));
    failed |= mix_hash(hs, th, sizeof(th));
    set_key(&hs->c, k);
    noise_wipe(ck, sizeof(ck));
    noise_wipe(th, sizeof(th));
    noise_wipe(k, sizeof(k));
    return failed;
}

/* EncryptAndHash: out gets len + 16 bytes. */
static int encrypt_and_hash(noise_handshake_t *hs, const uint8_t *in, size_t len, uint8_t *out)
{
    uint8_t nonce[12];
    nonce_bytes(hs->c.n, nonce);
    if (api_aead_encrypt(hs->c.k, nonce, hs->h, sizeof(hs->h), in, len, out)) return -1;
    hs->c.n++;
    return mix_hash(hs, out, len + NOISE_TAG);
}

static int decrypt_and_hash(noise_handshake_t *hs, const uint8_t *in, size_t len, uint8_t *out)
{
    uint8_t nonce[12];
    nonce_bytes(hs->c.n, nonce);
    if (api_aead_decrypt(hs->c.k, nonce, hs->h, sizeof(hs->h), in, len, out)) return -1;
    hs->c.n++;
    return mix_hash(hs, in, len) ? -2 : 0;
}

int noise_init(noise_handshake_t *hs, bool initiator, const uint8_t *prologue, size_t prologue_len)
{
    memset(hs, 0, sizeof(*hs));
    hs->initiator = initiator;
    /* The name is longer than 32 bytes, so h = SHA-256(name). */
    if (api_sha256((const uint8_t *)NOISE_PROTOCOL_NAME, strlen(NOISE_PROTOCOL_NAME), NULL, 0, hs->h)) return -1;
    memcpy(hs->ck, hs->h, sizeof(hs->ck));
    return mix_hash(hs, prologue, prologue_len);
}

int noise_set_ephemeral(noise_handshake_t *hs, const uint8_t private_key[32])
{
    memcpy(hs->e_priv, private_key, 32);
    hs->has_e = true;
    return api_x25519_public(hs->e_priv, hs->e_pub);
}

static int make_ephemeral(noise_handshake_t *hs)
{
    if (hs->has_e) return 0;
    if (api_crypto_random(hs->e_priv, sizeof(hs->e_priv))) return -1;
    hs->has_e = true;
    return api_x25519_public(hs->e_priv, hs->e_pub);
}

/* "e" with a PSK in the pattern: MixHash(e) and MixKey(e). */
static int mix_ephemeral(noise_handshake_t *hs, const uint8_t e[32])
{
    return mix_hash(hs, e, 32) || mix_key(hs, e, 32) ? -1 : 0;
}

int noise_write_message1(noise_handshake_t *hs, const uint8_t psk[32], const uint8_t *payload, size_t len,
                         uint8_t *out, size_t cap, size_t *out_len)
{
    if (!hs->initiator || hs->step != 0 || cap < 32 + len + NOISE_TAG) return -2;
    if (mix_key_and_hash(hs, psk, 32) || make_ephemeral(hs) || mix_ephemeral(hs, hs->e_pub)) return -2;
    memcpy(out, hs->e_pub, 32);
    if (encrypt_and_hash(hs, payload, len, out + 32)) return -2;
    *out_len = 32 + len + NOISE_TAG;
    hs->step = 1;
    return 0;
}

int noise_read_message1(noise_handshake_t *hs, const uint8_t psk[32], const uint8_t *msg, size_t len,
                        uint8_t *payload, size_t cap, size_t *payload_len)
{
    if (hs->initiator || hs->step != 0 || len < 32 + NOISE_TAG || cap < len - 32 - NOISE_TAG) return -2;
    memcpy(hs->re, msg, 32);
    if (mix_key_and_hash(hs, psk, 32) || mix_ephemeral(hs, hs->re)) return -2;
    const int result = decrypt_and_hash(hs, msg + 32, len - 32, payload);
    if (result) return result;
    *payload_len = len - 32 - NOISE_TAG;
    hs->step = 1;
    return 0;
}

/* e, ee: the writer adds its ephemeral, both sides mix DH(e, re). */
static int mix_ee(noise_handshake_t *hs)
{
    uint8_t shared[32];
    const int failed = api_x25519(hs->e_priv, hs->re, shared) || mix_key(hs, shared, sizeof(shared));
    noise_wipe(shared, sizeof(shared));
    return failed ? -1 : 0;
}

int noise_write_message2(noise_handshake_t *hs, const uint8_t *payload, size_t len, uint8_t *out, size_t cap,
                         size_t *out_len)
{
    if (hs->initiator || hs->step != 1 || cap < 32 + len + NOISE_TAG) return -2;
    if (make_ephemeral(hs) || mix_ephemeral(hs, hs->e_pub) || mix_ee(hs)) return -2;
    memcpy(out, hs->e_pub, 32);
    if (encrypt_and_hash(hs, payload, len, out + 32)) return -2;
    *out_len = 32 + len + NOISE_TAG;
    hs->step = 2;
    return 0;
}

int noise_read_message2(noise_handshake_t *hs, const uint8_t *msg, size_t len, uint8_t *payload, size_t cap,
                        size_t *payload_len)
{
    if (!hs->initiator || hs->step != 1 || len < 32 + NOISE_TAG || cap < len - 32 - NOISE_TAG) return -2;
    memcpy(hs->re, msg, 32);
    if (mix_ephemeral(hs, hs->re) || mix_ee(hs)) return -2;
    const int result = decrypt_and_hash(hs, msg + 32, len - 32, payload);
    if (result) return result;
    *payload_len = len - 32 - NOISE_TAG;
    hs->step = 2;
    return 0;
}

void noise_handshake_hash(const noise_handshake_t *hs, uint8_t out[32])
{
    memcpy(out, hs->h, 32);
}

int noise_split(noise_handshake_t *hs, noise_cipher_t *send, noise_cipher_t *recv)
{
    if (hs->step != 2) return -1;
    uint8_t k1[32], k2[32];
    const int failed = hkdf(hs->ck, NULL, 0, k1, k2, NULL);
    memset(send, 0, sizeof(*send));
    memset(recv, 0, sizeof(*recv));
    if (!failed) {
        set_key(hs->initiator ? send : recv, k1);
        set_key(hs->initiator ? recv : send, k2);
    }
    noise_wipe(k1, sizeof(k1));
    noise_wipe(k2, sizeof(k2));
    noise_wipe(hs, sizeof(*hs));
    return failed;
}

int noise_encrypt(noise_cipher_t *c, const uint8_t *in, size_t len, uint8_t *out)
{
    if (!c->has_key || c->n >= NOISE_MAX_NONCE) return -1;
    uint8_t nonce[12];
    nonce_bytes(c->n, nonce);
    if (api_aead_encrypt(c->k, nonce, NULL, 0, in, len, out)) return -1;
    c->n++;
    return 0;
}

int noise_decrypt(noise_cipher_t *c, const uint8_t *in, size_t len, uint8_t *out)
{
    if (!c->has_key || c->n >= NOISE_MAX_NONCE) return -1;
    uint8_t nonce[12];
    nonce_bytes(c->n, nonce);
    if (api_aead_decrypt(c->k, nonce, NULL, 0, in, len, out)) return -1;
    c->n++;
    return 0;
}
