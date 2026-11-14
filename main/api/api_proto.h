#pragma once
/* A small protobuf writer and reader: only what the ESPHome native API messages in api_messages.c need
 * (varint, fixed32, float, bool, length-delimited, packed varints). Pure C, compiled into tests/native.
 * docs/design/esphome.md, B.1. */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

enum { PB_VARINT = 0, PB_FIXED64 = 1, PB_LEN = 2, PB_FIXED32 = 5 };

typedef struct {
    uint8_t *buf;
    size_t cap;
    size_t len;
    bool overflow; /* set once a write did not fit; len then stops growing */
} pb_writer_t;

void pb_writer_init(pb_writer_t *w, uint8_t *buf, size_t cap);
/* proto3 rules: a zero number, false, an empty string or a 0.0f float is not written. */
void pb_put_varint(pb_writer_t *w, uint64_t value); /* raw varint, no tag */
void pb_put_uint(pb_writer_t *w, uint32_t field, uint64_t value);
void pb_put_int32(pb_writer_t *w, uint32_t field, int32_t value); /* negative values take 10 bytes, as protobuf does */
void pb_put_bool(pb_writer_t *w, uint32_t field, bool value);
void pb_put_fixed32(pb_writer_t *w, uint32_t field, uint32_t value);
void pb_put_float(pb_writer_t *w, uint32_t field, float value);
void pb_put_string(pb_writer_t *w, uint32_t field, const char *text);   /* NULL or "" writes nothing */
void pb_put_bytes(pb_writer_t *w, uint32_t field, const void *data, size_t len);
void pb_put_repeated_string(pb_writer_t *w, uint32_t field, const char *text); /* always written, "" too */
void pb_put_packed_uint(pb_writer_t *w, uint32_t field, const uint32_t *values, size_t count);

typedef struct {
    const uint8_t *p;
    const uint8_t *end;
    bool error; /* truncated data, an over-long varint, a bad wire type or field 0 */
} pb_reader_t;

typedef struct {
    uint32_t field;
    uint8_t wire;
    uint64_t varint;     /* PB_VARINT */
    uint32_t fixed32;    /* PB_FIXED32 (a float is these bits) */
    const uint8_t *data; /* PB_LEN */
    size_t len;
} pb_field_t;

void pb_reader_init(pb_reader_t *r, const uint8_t *data, size_t len);
/* The next field, or false at the end or on an error (then r->error is true). Fixed64 fields are skipped over
 * but still returned, with no value. */
bool pb_next(pb_reader_t *r, pb_field_t *out);
float pb_field_float(const pb_field_t *f);
int32_t pb_zigzag32(uint64_t varint); /* a sint32 field's value */
/* Copies a length-delimited field into a NUL-terminated buffer; false when it does not fit or holds a NUL. */
bool pb_field_string(const pb_field_t *f, char *out, size_t size);

#ifdef __cplusplus
}
#endif
