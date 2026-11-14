#include "api_proto.h"

#include <string.h>

void pb_writer_init(pb_writer_t *w, uint8_t *buf, size_t cap)
{
    w->buf = buf;
    w->cap = cap;
    w->len = 0;
    w->overflow = false;
}

static void put_raw(pb_writer_t *w, const void *data, size_t len)
{
    if (w->overflow || len > w->cap - w->len) {
        w->overflow = true;
        return;
    }
    if (len) memcpy(w->buf + w->len, data, len);
    w->len += len;
}

void pb_put_varint(pb_writer_t *w, uint64_t value)
{
    uint8_t bytes[10];
    size_t n = 0;
    do {
        uint8_t b = (uint8_t)(value & 0x7F);
        value >>= 7;
        if (value) b |= 0x80;
        bytes[n++] = b;
    } while (value);
    put_raw(w, bytes, n);
}

static void put_tag(pb_writer_t *w, uint32_t field, uint8_t wire)
{
    pb_put_varint(w, ((uint64_t)field << 3) | wire);
}

void pb_put_uint(pb_writer_t *w, uint32_t field, uint64_t value)
{
    if (!value) return;
    put_tag(w, field, PB_VARINT);
    pb_put_varint(w, value);
}

void pb_put_int32(pb_writer_t *w, uint32_t field, int32_t value)
{
    if (!value) return;
    put_tag(w, field, PB_VARINT);
    pb_put_varint(w, (uint64_t)(int64_t)value); /* sign-extended, as protobuf encodes int32 */
}

void pb_put_bool(pb_writer_t *w, uint32_t field, bool value)
{
    if (value) pb_put_uint(w, field, 1);
}

void pb_put_fixed32(pb_writer_t *w, uint32_t field, uint32_t value)
{
    if (!value) return;
    const uint8_t b[4] = {(uint8_t)value, (uint8_t)(value >> 8), (uint8_t)(value >> 16), (uint8_t)(value >> 24)};
    put_tag(w, field, PB_FIXED32);
    put_raw(w, b, sizeof(b));
}

void pb_put_float(pb_writer_t *w, uint32_t field, float value)
{
    uint32_t bits;
    memcpy(&bits, &value, sizeof(bits));
    pb_put_fixed32(w, field, bits);
}

void pb_put_bytes(pb_writer_t *w, uint32_t field, const void *data, size_t len)
{
    put_tag(w, field, PB_LEN);
    pb_put_varint(w, len);
    put_raw(w, data, len);
}

void pb_put_string(pb_writer_t *w, uint32_t field, const char *text)
{
    if (text && text[0]) pb_put_bytes(w, field, text, strlen(text));
}

void pb_put_repeated_string(pb_writer_t *w, uint32_t field, const char *text)
{
    pb_put_bytes(w, field, text ? text : "", text ? strlen(text) : 0);
}

void pb_put_packed_uint(pb_writer_t *w, uint32_t field, const uint32_t *values, size_t count)
{
    if (!count) return;
    size_t len = 0;
    for (size_t i = 0; i < count; ++i) {
        uint32_t v = values[i];
        do { ++len; v >>= 7; } while (v);
    }
    put_tag(w, field, PB_LEN);
    pb_put_varint(w, len);
    for (size_t i = 0; i < count; ++i) pb_put_varint(w, values[i]);
}

void pb_reader_init(pb_reader_t *r, const uint8_t *data, size_t len)
{
    r->p = data;
    r->end = data ? data + len : data;
    r->error = false;
}

static bool get_varint(pb_reader_t *r, uint64_t *out)
{
    uint64_t value = 0;
    for (unsigned shift = 0; shift < 64; shift += 7) {
        if (r->p >= r->end) return false;
        const uint8_t b = *r->p++;
        if (shift == 63 && b > 1) return false; /* would not fit in 64 bits */
        value |= (uint64_t)(b & 0x7F) << shift;
        if (!(b & 0x80)) {
            *out = value;
            return true;
        }
    }
    return false;
}

static bool fail(pb_reader_t *r)
{
    r->error = true;
    r->p = r->end;
    return false;
}

bool pb_next(pb_reader_t *r, pb_field_t *out)
{
    if (r->error || r->p >= r->end) return false;
    memset(out, 0, sizeof(*out));
    uint64_t tag;
    if (!get_varint(r, &tag) || tag >> 3 == 0 || tag >> 3 > 0x1FFFFFFF) return fail(r);
    out->field = (uint32_t)(tag >> 3);
    out->wire = (uint8_t)(tag & 7);
    const size_t left = (size_t)(r->end - r->p);
    switch (out->wire) {
    case PB_VARINT:
        if (!get_varint(r, &out->varint)) return fail(r);
        return true;
    case PB_FIXED64:
        if (left < 8) return fail(r);
        r->p += 8;
        return true;
    case PB_FIXED32:
        if (left < 4) return fail(r);
        out->fixed32 = (uint32_t)r->p[0] | (uint32_t)r->p[1] << 8 | (uint32_t)r->p[2] << 16 | (uint32_t)r->p[3] << 24;
        r->p += 4;
        return true;
    case PB_LEN: {
        uint64_t len;
        if (!get_varint(r, &len) || len > (uint64_t)(r->end - r->p)) return fail(r);
        out->data = r->p;
        out->len = (size_t)len;
        r->p += len;
        return true;
    }
    default:
        return fail(r); /* groups (3, 4) and unknown types */
    }
}

int32_t pb_zigzag32(uint64_t varint)
{
    const uint32_t v = (uint32_t)varint;
    return (int32_t)((v >> 1) ^ (0u - (v & 1u)));
}

float pb_field_float(const pb_field_t *f)
{
    float value = 0.0f;
    if (f->wire == PB_FIXED32) memcpy(&value, &f->fixed32, sizeof(value));
    return value;
}

bool pb_field_string(const pb_field_t *f, char *out, size_t size)
{
    if (!size) return false;
    out[0] = '\0';
    if (f->wire != PB_LEN || f->len >= size || memchr(f->data, 0, f->len)) return false;
    memcpy(out, f->data, f->len);
    out[f->len] = '\0';
    return true;
}
