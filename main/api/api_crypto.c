#include "api_crypto.h"

#include <string.h>

#include "psa/crypto.h"

int api_crypto_init(void)
{
    return psa_crypto_init() == PSA_SUCCESS ? 0 : -1;
}

int api_crypto_random(uint8_t *out, size_t len)
{
    return psa_generate_random(out, len) == PSA_SUCCESS ? 0 : -1;
}

/* A volatile key that lives for one call. */
static int import_key(psa_key_type_t type, size_t bits, psa_key_usage_t usage, psa_algorithm_t alg,
                      const uint8_t *data, size_t len, psa_key_id_t *id)
{
    psa_key_attributes_t attributes = PSA_KEY_ATTRIBUTES_INIT;
    psa_set_key_type(&attributes, type);
    psa_set_key_bits(&attributes, bits);
    psa_set_key_usage_flags(&attributes, usage);
    psa_set_key_algorithm(&attributes, alg);
    const psa_status_t status = psa_import_key(&attributes, data, len, id);
    psa_reset_key_attributes(&attributes);
    return status == PSA_SUCCESS ? 0 : -1;
}

static int import_x25519(const uint8_t private_key[32], psa_key_usage_t usage, psa_key_id_t *id)
{
    return import_key(PSA_KEY_TYPE_ECC_KEY_PAIR(PSA_ECC_FAMILY_MONTGOMERY), 255, usage, PSA_ALG_ECDH, private_key,
                      32, id);
}

int api_x25519_public(const uint8_t private_key[32], uint8_t public_key[32])
{
    psa_key_id_t id = 0;
    if (import_x25519(private_key, PSA_KEY_USAGE_EXPORT, &id)) return -1;
    size_t length = 0;
    const psa_status_t status = psa_export_public_key(id, public_key, 32, &length);
    psa_destroy_key(id);
    return status == PSA_SUCCESS && length == 32 ? 0 : -1;
}

int api_x25519(const uint8_t private_key[32], const uint8_t peer_public[32], uint8_t shared[32])
{
    psa_key_id_t id = 0;
    if (import_x25519(private_key, PSA_KEY_USAGE_DERIVE, &id)) return -1;
    size_t length = 0;
    const psa_status_t status = psa_raw_key_agreement(PSA_ALG_ECDH, id, peer_public, 32, shared, 32, &length);
    psa_destroy_key(id);
    if (status != PSA_SUCCESS || length != 32) return -1;
    /* A low-order peer key gives an all-zero secret (RFC 7748, 6.1): refuse it. */
    uint8_t any = 0;
    for (int i = 0; i < 32; ++i) any |= shared[i];
    return any ? 0 : -1;
}

static int import_chachapoly(const uint8_t key[32], psa_key_usage_t usage, psa_key_id_t *id)
{
    return import_key(PSA_KEY_TYPE_CHACHA20, 256, usage, PSA_ALG_CHACHA20_POLY1305, key, 32, id);
}

int api_aead_encrypt(const uint8_t key[32], const uint8_t nonce[12], const uint8_t *ad, size_t ad_len,
                     const uint8_t *in, size_t len, uint8_t *out)
{
    psa_key_id_t id = 0;
    if (import_chachapoly(key, PSA_KEY_USAGE_ENCRYPT, &id)) return -1;
    size_t written = 0;
    const psa_status_t status = psa_aead_encrypt(id, PSA_ALG_CHACHA20_POLY1305, nonce, 12, ad, ad_len, in, len, out,
                                                 len + API_CRYPTO_TAG, &written);
    psa_destroy_key(id);
    return status == PSA_SUCCESS && written == len + API_CRYPTO_TAG ? 0 : -1;
}

int api_aead_decrypt(const uint8_t key[32], const uint8_t nonce[12], const uint8_t *ad, size_t ad_len,
                     const uint8_t *in, size_t len, uint8_t *out)
{
    if (len < API_CRYPTO_TAG) return -1;
    psa_key_id_t id = 0;
    if (import_chachapoly(key, PSA_KEY_USAGE_DECRYPT, &id)) return -1;
    size_t written = 0;
    /* PSA wants a non-NULL output even for an empty plaintext. */
    uint8_t empty[1];
    const psa_status_t status = psa_aead_decrypt(id, PSA_ALG_CHACHA20_POLY1305, nonce, 12, ad, ad_len, in, len,
                                                 len > API_CRYPTO_TAG ? out : empty, len - API_CRYPTO_TAG, &written);
    psa_destroy_key(id);
    return status == PSA_SUCCESS && written == len - API_CRYPTO_TAG ? 0 : -1;
}

int api_sha256(const uint8_t *a, size_t a_len, const uint8_t *b, size_t b_len, uint8_t out[32])
{
    psa_hash_operation_t op = PSA_HASH_OPERATION_INIT;
    size_t length = 0;
    psa_status_t status = psa_hash_setup(&op, PSA_ALG_SHA_256);
    if (status == PSA_SUCCESS && a_len) status = psa_hash_update(&op, a, a_len);
    if (status == PSA_SUCCESS && b && b_len) status = psa_hash_update(&op, b, b_len);
    if (status == PSA_SUCCESS) status = psa_hash_finish(&op, out, 32, &length);
    if (status != PSA_SUCCESS) psa_hash_abort(&op);
    return status == PSA_SUCCESS && length == 32 ? 0 : -1;
}

int api_hmac_sha256(const uint8_t key[32], const uint8_t *data, size_t len, uint8_t out[32])
{
    psa_key_id_t id = 0;
    if (import_key(PSA_KEY_TYPE_HMAC, 256, PSA_KEY_USAGE_SIGN_MESSAGE, PSA_ALG_HMAC(PSA_ALG_SHA_256), key, 32, &id))
        return -1;
    size_t length = 0;
    const psa_status_t status = psa_mac_compute(id, PSA_ALG_HMAC(PSA_ALG_SHA_256), data, len, out, 32, &length);
    psa_destroy_key(id);
    return status == PSA_SUCCESS && length == 32 ? 0 : -1;
}
