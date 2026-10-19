#pragma once
// Mbed TLS 4 / PSA adapter for upstream's one-shot SHA-256 call.
#include <psa/crypto.h>
inline int mbedtls_sha256(const unsigned char* data,size_t bytes,unsigned char* out,int is224) {
    if(is224 || psa_crypto_init()!=PSA_SUCCESS)return -1;
    size_t length=0;
    return psa_hash_compute(PSA_ALG_SHA_256,data,bytes,out,32,&length)==PSA_SUCCESS && length==32 ? 0 : -1;
}
