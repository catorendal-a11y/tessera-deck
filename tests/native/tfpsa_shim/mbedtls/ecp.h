#pragma once
/* ESP-IDF patched bignum.c and ecp.c to include its port shim (components/mbedtls/port/include); the native
 * build has no ESP port, so this shim does what that one does without the hardware parts. */
#define MBEDTLS_DECLARE_PRIVATE_IDENTIFIERS
#include "mbedtls/private/ecp.h"
