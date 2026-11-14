#pragma once
/* The only file that calls crypto: PSA Crypto (mbedTLS 4 / TF-PSA-Crypto in ESP-IDF 6.1). tests/native builds
 * the same TF-PSA-Crypto sources from $IDF_PATH. Every call returns 0 on success, -1 on failure (for decrypt:
 * also a bad tag). docs/design/esphome.md, B.1. */
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define API_CRYPTO_TAG 16

int api_crypto_init(void); /* psa_crypto_init; safe to call more than once */
int api_crypto_random(uint8_t *out, size_t len);
int api_x25519_public(const uint8_t private_key[32], uint8_t public_key[32]);
int api_x25519(const uint8_t private_key[32], const uint8_t peer_public[32], uint8_t shared[32]);
/* ChaCha20-Poly1305 (IETF, 96-bit nonce). `out` holds len + API_CRYPTO_TAG bytes. ESP-IDF sets
 * MBEDTLS_PSA_ASSUME_EXCLUSIVE_BUFFERS, so `in` and `out` must never overlap. */
int api_aead_encrypt(const uint8_t key[32], const uint8_t nonce[12], const uint8_t *ad, size_t ad_len,
                     const uint8_t *in, size_t len, uint8_t *out);
/* `len` includes the tag; `out` gets len - API_CRYPTO_TAG bytes and must not overlap `in`. */
int api_aead_decrypt(const uint8_t key[32], const uint8_t nonce[12], const uint8_t *ad, size_t ad_len,
                     const uint8_t *in, size_t len, uint8_t *out);
/* SHA-256 of a || b (b may be NULL). */
int api_sha256(const uint8_t *a, size_t a_len, const uint8_t *b, size_t b_len, uint8_t out[32]);
int api_hmac_sha256(const uint8_t key[32], const uint8_t *data, size_t len, uint8_t out[32]);

#ifdef __cplusplus
}
#endif
