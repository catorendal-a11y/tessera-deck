// Native tests for the ESPHome native API (docs/design/esphome.md, B.8): the protobuf codec against golden
// bytes from tools/gen_api_fixtures.py, Noise against the Cacophony vector and RFC 7748, a full session with a
// test client in the same process, the entities and the press router. Crypto is TF-PSA-Crypto from ESP-IDF.
#undef NDEBUG
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <random>
#include <string>
#include <vector>

#include "api_crypto.h"
#include "api_entities.h"
#include "api_ha.h"
#include "api_messages.h"
#include "api_noise.h"
#include "api_proto.h"
#include "api_session.h"
#include "deck_ha.h"
#include "deck_model.h"
#include "press_router.h"

static int64_t tick_ms = 100000;
extern "C" int64_t esp_timer_get_time(void) { return tick_ms * 1000; }

using Bytes = std::vector<uint8_t>;

static Bytes hex(const std::string &text)
{
    Bytes out;
    for (size_t i = 0; i + 1 < text.size(); i += 2) out.push_back((uint8_t)std::stoi(text.substr(i, 2), nullptr, 16));
    return out;
}

static Bytes fixture(const char *name)
{
    std::ifstream file(std::string(FIXTURES) + "/" + name + ".hex");
    std::string text;
    file >> text;
    assert(!text.empty() && "missing fixture: run tools/gen_api_fixtures.py");
    return hex(text);
}

static Bytes written(const pb_writer_t &w) { return Bytes(w.buf, w.buf + w.len); }

#define ENCODE(var, call)                                                                                    \
    uint8_t var##_buf[1024];                                                                                 \
    pb_writer_t var;                                                                                         \
    pb_writer_init(&var, var##_buf, sizeof(var##_buf));                                                      \
    assert(call)

static api_entity_info_t entity(const char *object_id, const char *name)
{
    api_entity_info_t e{};
    e.object_id = object_id;
    e.name = name;
    e.key = api_fnv1(object_id);
    return e;
}

static void test_proto_basics()
{
    uint8_t buf[16];
    pb_writer_t w;
    pb_writer_init(&w, buf, sizeof(buf));
    pb_put_varint(&w, 300);
    assert(w.len == 2 && buf[0] == 0xAC && buf[1] == 0x02);
    pb_put_uint(&w, 1, 0); // proto3: zero is not written
    pb_put_string(&w, 2, "");
    assert(w.len == 2);
    pb_put_int32(&w, 7, -1); // ten-byte varint, as protobuf does
    assert(w.len == 2 + 1 + 10);
    pb_put_bytes(&w, 3, "xyz", 3); // does not fit
    assert(w.overflow);
    // Reader: truncated, over-long varints and groups are errors, not crashes.
    const uint8_t truncated[] = {0x0A, 0x05, 'a'};
    pb_reader_t r;
    pb_field_t f;
    pb_reader_init(&r, truncated, sizeof(truncated));
    assert(!pb_next(&r, &f) && r.error);
    const uint8_t group[] = {0x0B};
    pb_reader_init(&r, group, sizeof(group));
    assert(!pb_next(&r, &f) && r.error);
    const uint8_t field_zero[] = {0x00, 0x01};
    pb_reader_init(&r, field_zero, sizeof(field_zero));
    assert(!pb_next(&r, &f) && r.error);
    const uint8_t fixed64[] = {0x09, 1, 2, 3, 4, 5, 6, 7, 8, 0x10, 0x05};
    pb_reader_init(&r, fixed64, sizeof(fixed64));
    assert(pb_next(&r, &f) && f.wire == PB_FIXED64 && pb_next(&r, &f) && f.field == 2 && f.varint == 5);
    assert(!pb_next(&r, &f) && !r.error);
    assert(pb_zigzag32(0) == 0 && pb_zigzag32(1) == -1 && pb_zigzag32(2) == 1 && pb_zigzag32(7199) == -3600);
    assert(pb_zigzag32(0xFFFFFFFEu) == 2147483647 && pb_zigzag32(0xFFFFFFFFu) == (-2147483647 - 1));
}

static void test_encoders_match_golden_bytes()
{
    const api_hello_response_t hello = {1, 12, "Tessera 0.8.0", "tessera-deck"};
    ENCODE(w1, api_encode_hello_response(&w1, &hello));
    assert(written(w1) == fixture("hello_response"));

    api_device_info_t info{};
    info.name = "tessera-deck";
    info.mac_address = "AA:BB:CC:DD:EE:FF";
    info.esphome_version = API_ESPHOME_VERSION;
    info.compilation_time = "Nov 14 2026, 12:00:00";
    info.model = "Guition JC1060P470C";
    info.project_name = API_PROJECT_NAME;
    info.project_version = "0.8.0";
    info.manufacturer = "Tessera";
    info.friendly_name = "Tessera Deck";
    info.suggested_area = "Office";
    info.api_encryption_supported = true;
    ENCODE(w2, api_encode_device_info(&w2, &info));
    assert(written(w2) == fixture("device_info"));

    api_entity_info_t e = entity("pc_connected", "PC connected");
    e.device_class = "connectivity";
    ENCODE(w3, api_encode_list_binary_sensor(&w3, &e));
    assert(written(w3) == fixture("list_binary_sensor"));

    e = entity("backlight", "Backlight");
    const uint32_t modes[] = {API_COLOR_MODE_BRIGHTNESS};
    ENCODE(w4, api_encode_list_light(&w4, &e, modes, 1));
    assert(written(w4) == fixture("list_light"));

    e = entity("wifi_signal", "Wi-Fi signal");
    e.device_class = "signal_strength";
    e.entity_category = API_ENTITY_CATEGORY_DIAGNOSTIC;
    ENCODE(w5, api_encode_list_sensor(&w5, &e, "dBm", 0, API_STATE_CLASS_MEASUREMENT));
    assert(written(w5) == fixture("list_sensor"));

    e = entity("profile", "Profile");
    const char *const options[] = {"Main", "Chrome"};
    ENCODE(w6, api_encode_list_select(&w6, &e, options, 2));
    assert(written(w6) == fixture("list_select_profile"));

    e = entity("show_clock", "Show clock");
    e.icon = "mdi:clock-outline";
    ENCODE(w7, api_encode_list_button(&w7, &e));
    assert(written(w7) == fixture("list_button"));

    const char *const types[] = {"press", "hold", "double"};
    e = entity("key_13", "Key 13");
    e.device_class = "button";
    e.disabled_by_default = true;
    ENCODE(w8, api_encode_list_event(&w8, &e, types, 3));
    assert(written(w8) == fixture("list_event_13"));

    ENCODE(s1, api_encode_binary_sensor_state(&s1, api_fnv1("pc_connected"), true, false));
    assert(written(s1) == fixture("state_binary_sensor"));
    ENCODE(s2, api_encode_light_state(&s2, api_fnv1("backlight"), true, 0.5f, API_COLOR_MODE_BRIGHTNESS));
    assert(written(s2) == fixture("state_light"));
    ENCODE(s3, api_encode_sensor_state(&s3, api_fnv1("wifi_signal"), -58.0f, false));
    assert(written(s3) == fixture("state_sensor"));
    ENCODE(s4, api_encode_sensor_state(&s4, api_fnv1("wifi_signal"), 0.0f, true));
    assert(written(s4) == fixture("state_sensor_missing"));
    ENCODE(s5, api_encode_select_state(&s5, api_fnv1("profile"), "Main", false));
    assert(written(s5) == fixture("state_select"));
    ENCODE(s6, api_encode_event(&s6, api_fnv1("key_1"), "double"));
    assert(written(s6) == fixture("event_double"));
}

static void test_decoders_read_golden_bytes()
{
    Bytes b = fixture("hello_request");
    api_hello_request_t hello;
    assert(api_decode_hello_request(b.data(), b.size(), &hello));
    assert(!strcmp(hello.client_info, "aioesphomeapi") && hello.major == 1 && hello.minor == 10);

    b = fixture("light_command");
    api_light_command_t light;
    assert(api_decode_light_command(b.data(), b.size(), &light));
    assert(light.key == api_fnv1("backlight") && light.has_state && light.state && light.has_brightness);
    assert(light.brightness > 0.29f && light.brightness < 0.31f);

    b = fixture("select_command");
    api_select_command_t select;
    assert(api_decode_select_command(b.data(), b.size(), &select));
    assert(select.key == api_fnv1("profile") && !strcmp(select.state, "Chrome"));

    b = fixture("button_command");
    uint32_t key = 0;
    assert(api_decode_button_command(b.data(), b.size(), &key) && key == api_fnv1("show_clock"));

    // GetTimeResponse: parsed_timezone (field 3) wins over the deprecated string; the string counts only when it
    // has a POSIX shape.
    b = fixture("get_time_response");
    api_get_time_response_t time;
    assert(api_decode_get_time_response(b.data(), b.size(), &time));
    assert(time.epoch_seconds == 1763121600u && !strcmp(time.timezone, "STD-1DST-2,M3.5.0,M10.5.0/3"));
    b = fixture("get_time_parsed");
    assert(api_decode_get_time_response(b.data(), b.size(), &time) && !strcmp(time.timezone, "STD5DST4,M3.2.0,M11.1.0"));
    b = fixture("get_time_string");
    assert(api_decode_get_time_response(b.data(), b.size(), &time));
    assert(!strcmp(time.timezone, "CET-1CEST,M3.5.0,M10.5.0/3"));
    b = fixture("get_time_iana");
    assert(api_decode_get_time_response(b.data(), b.size(), &time) && time.epoch_seconds && !time.timezone[0]);
    // An empty parsed zone is UTC; India (UTC+5:30, no DST); a rule at midnight and one at 01:30.
    const Bytes utc = {0x0D, 0xC0, 0x19, 0x17, 0x69, 0x1A, 0x00};
    assert(api_decode_get_time_response(utc.data(), utc.size(), &time) && !strcmp(time.timezone, "UTC0"));
    const Bytes india = {0x1A, 0x04, 0x08, 0xAF, 0xB5, 0x02}; // std_offset -19800
    assert(api_decode_get_time_response(india.data(), india.size(), &time) && !strcmp(time.timezone, "STD-5:30"));
    const Bytes rules = {0x1A, 0x14, 0x08, 0x9F, 0x38, 0x1A, 0x06, 0x18, 0x01, 0x20, 0x03, 0x28, 0x05,
                         0x22, 0x07, 0x08, 0xB0, 0x54, 0x10, 0x01, 0x18, 0x02};
    assert(api_decode_get_time_response(rules.data(), rules.size(), &time));
    assert(!strcmp(time.timezone, "STD-1DST0,M3.5.0/0,J1/1:30"));
    // An unknown rule type or a bad month gives no zone (UTC), never a half-built string.
    const Bytes bad = {0x1A, 0x08, 0x08, 0x01, 0x1A, 0x04, 0x18, 0x01, 0x20, 0x0D};
    assert(api_decode_get_time_response(bad.data(), bad.size(), &time) && !time.timezone[0]);
}

static void test_fuzz_reader()
{
    std::mt19937 rng(1234);
    uint8_t data[64];
    for (int round = 0; round < 100000; ++round) {
        const size_t len = rng() % sizeof(data);
        for (size_t i = 0; i < len; ++i) data[i] = (uint8_t)rng();
        pb_reader_t r;
        pb_field_t f;
        pb_reader_init(&r, data, len);
        int fields = 0;
        while (pb_next(&r, &f)) {
            assert(f.wire != PB_LEN || (f.data >= data && f.data + f.len <= data + len));
            ++fields;
        }
        assert(fields <= (int)len);
        api_hello_request_t hello;
        api_light_command_t light;
        api_select_command_t select;
        api_get_time_response_t time;
        uint32_t key;
        api_decode_hello_request(data, len, &hello);
        assert(strlen(hello.client_info) <= API_TEXT_MAX);
        api_decode_light_command(data, len, &light);
        api_decode_select_command(data, len, &select);
        assert(strlen(select.state) <= API_NAME_MAX);
        api_decode_get_time_response(data, len, &time);
        api_decode_button_command(data, len, &key);
    }
}

static void test_crypto_known_answers()
{
    uint8_t out[32];
    assert(api_sha256((const uint8_t *)"abc", 3, nullptr, 0, out) == 0);
    assert(Bytes(out, out + 32) == hex("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"));
    // RFC 7748, 6.1
    const Bytes alice = hex("77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a");
    const Bytes bob_pub = hex("de9edb7d7b7dc1b4d35b61c2ece435373f8343c85b78674dadfc7e146f882b4f");
    assert(api_x25519_public(alice.data(), out) == 0);
    assert(Bytes(out, out + 32) == hex("8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a"));
    assert(api_x25519(alice.data(), bob_pub.data(), out) == 0);
    assert(Bytes(out, out + 32) == hex("4a5d9d5ba4ce2de1728e3bf480350f25e07e21c947d19e3376f09b3c1e161742"));
    const uint8_t zero[32] = {};
    assert(api_x25519(alice.data(), zero, out) != 0); // low-order point refused
}

// Cacophony vectors/cacophony.txt, protocol_name Noise_NNpsk0_25519_ChaChaPoly_SHA256.
static void test_noise_cacophony_vector()
{
    const Bytes prologue = hex("4a6f686e2047616c74");
    const Bytes psk = hex("54686973206973206d7920417573747269616e20706572737065637469766521");
    const Bytes init_e = hex("893e28b9dc6ca8d611ab664754b8ceb7bac5117349a4439a6b0569da977c464a");
    const Bytes resp_e = hex("bbdb4cdbd309f1a1f2e1456967fe288cadd6f712d65dc7b7793d5e63da6b375b");
    const char *msgs[][2] = {
        {"4c756477696720766f6e204d69736573", "ca35def5ae56cec33dc2036731ab14896bc4c75dbb07a61f879f8e3afa4c7944"
                                             "79b962b8aff8485742ac32f905ba45369e2465fb59e138a93d67a0d1266b6a54"},
        {"4d757272617920526f746862617264", "95ebc60d2b1fa672c1f46a8aa265ef51bfe38e7ccb39ec5be34069f144808843"
                                           "d6062704d5a9c422a8e834423f8c1feada7e8d0d910a1a2cd030fb584221e3"},
        {"462e20412e20486179656b", "e632c3763d7669067383433197a3baddf146e9e70ad4b4e9e59e0f"},
        {"4361726c204d656e676572", "64c6bee32ea91c8474bb4c21d7a700109ad45af77b29764ba5eb1e"},
        {"4a65616e2d426170746973746520536179", "e2fa0bed0603b62d3ccac2ecabbf3fe33f3e86514909b323361626266cb2471cc8"},
        {"457567656e2042f6686d20766f6e2042617765726b",
         "0c01dc9cec1fe4ddd692e8dd32188aa351088dc91183639a53b57aa4692b5ebdef8b8ca111"},
    };
    noise_handshake_t i, r;
    assert(noise_init(&i, true, prologue.data(), prologue.size()) == 0);
    assert(noise_init(&r, false, prologue.data(), prologue.size()) == 0);
    assert(noise_set_ephemeral(&i, init_e.data()) == 0 && noise_set_ephemeral(&r, resp_e.data()) == 0);
    uint8_t buf[256], payload[256];
    size_t len = 0, plen = 0;
    Bytes p = hex(msgs[0][0]);
    assert(noise_write_message1(&i, psk.data(), p.data(), p.size(), buf, sizeof(buf), &len) == 0);
    assert(Bytes(buf, buf + len) == hex(msgs[0][1]));
    assert(noise_read_message1(&r, psk.data(), buf, len, payload, sizeof(payload), &plen) == 0);
    assert(Bytes(payload, payload + plen) == p);
    p = hex(msgs[1][0]);
    assert(noise_write_message2(&r, p.data(), p.size(), buf, sizeof(buf), &len) == 0);
    assert(Bytes(buf, buf + len) == hex(msgs[1][1]));
    assert(noise_read_message2(&i, buf, len, payload, sizeof(payload), &plen) == 0);
    assert(Bytes(payload, payload + plen) == p);
    uint8_t hi[32], hr[32];
    noise_handshake_hash(&i, hi);
    noise_handshake_hash(&r, hr);
    assert(Bytes(hi, hi + 32) == hex("f4d03dc34495c95729ea6de9e1b59004b59733102488b3e24bc441e0be208eaf"));
    assert(!memcmp(hi, hr, 32));
    noise_cipher_t i_send, i_recv, r_send, r_recv;
    assert(noise_split(&i, &i_send, &i_recv) == 0 && noise_split(&r, &r_send, &r_recv) == 0);
    for (int m = 2; m < 6; ++m) {
        p = hex(msgs[m][0]);
        const bool from_initiator = m % 2 == 0;
        assert(noise_encrypt(from_initiator ? &i_send : &r_send, p.data(), p.size(), buf) == 0);
        assert(Bytes(buf, buf + p.size() + NOISE_TAG) == hex(msgs[m][1]));
        assert(noise_decrypt(from_initiator ? &r_recv : &i_recv, buf, p.size() + NOISE_TAG, payload) == 0);
        assert(Bytes(payload, payload + p.size()) == p);
    }
    // A flipped bit fails the tag, and the nonce does not move on a failure.
    assert(noise_encrypt(&i_send, p.data(), p.size(), buf) == 0);
    buf[0] ^= 1;
    const uint64_t n = r_recv.n;
    assert(noise_decrypt(&r_recv, buf, p.size() + NOISE_TAG, payload) != 0 && r_recv.n == n);
    r_recv.n = NOISE_MAX_NONCE; // B.2: a counter at 2^32 closes
    assert(noise_decrypt(&r_recv, buf, p.size() + NOISE_TAG, payload) != 0);
}

// ---- session with a test client ----

struct Server {
    api_session_t s{};
    uint8_t mem[4][API_BUFFER]{};
    Bytes out;
    std::vector<std::pair<uint16_t, Bytes>> unhandled;
    api_peer_t peer{};
    api_snapshot_t now{};
    bool route_entities = false;
};

static const api_device_t DEVICE = {"tessera-deck", "Tessera Deck", "Office", "AA:BB:CC:DD:EE:FF", "0.8.0",
                                    "Nov 14 2026, 12:00:00"};

static bool server_write(void *ctx, const uint8_t *data, size_t len)
{
    Server *sv = (Server *)ctx;
    sv->out.insert(sv->out.end(), data, data + len);
    return true;
}

static void server_message(api_session_t *s, uint16_t type, const uint8_t *data, size_t len, void *ctx)
{
    Server *sv = (Server *)ctx;
    if (sv->route_entities) api_entities_message(s, &sv->peer, &DEVICE, &sv->now, type, data, len, tick_ms);
    else sv->unhandled.emplace_back(type, Bytes(data, data + len));
}

static const uint8_t PSK[32] = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16,
                                17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32};

static void open(Server &sv)
{
    uint8_t *buffers[4] = {sv.mem[0], sv.mem[1], sv.mem[2], sv.mem[3]};
    const api_session_config_t config = {"tessera-deck", "aabbccddeeff", "Tessera 0.8.0", PSK, server_write,
                                         server_message, &sv};
    api_session_open(&sv.s, &config, buffers, tick_ms);
}

static Bytes frame(const Bytes &body)
{
    Bytes f = {0x01, (uint8_t)(body.size() >> 8), (uint8_t)body.size()};
    f.insert(f.end(), body.begin(), body.end());
    return f;
}

// Splits the server's output into frame bodies.
static std::vector<Bytes> frames(Bytes &out)
{
    std::vector<Bytes> list;
    size_t at = 0;
    while (out.size() - at >= 3) {
        assert(out[at] == 0x01);
        const size_t len = (size_t)out[at + 1] << 8 | out[at + 2];
        if (out.size() - at < 3 + len) break;
        list.emplace_back(out.begin() + (long)at + 3, out.begin() + (long)(at + 3 + len));
        at += 3 + len;
    }
    out.erase(out.begin(), out.begin() + (long)at);
    return list;
}

struct Client {
    noise_handshake_t hs{};
    noise_cipher_t send{}, recv{};

    Bytes hello_and_message1(const uint8_t *psk)
    {
        static const uint8_t prologue[] = {'N', 'o', 'i', 's', 'e', 'A', 'P', 'I', 'I', 'n', 'i', 't', 0, 0};
        assert(noise_init(&hs, true, prologue, sizeof(prologue)) == 0);
        uint8_t msg[128];
        size_t len = 0;
        assert(noise_write_message1(&hs, psk, nullptr, 0, msg, sizeof(msg), &len) == 0 && len == 48);
        Bytes body = {0x00};
        body.insert(body.end(), msg, msg + len);
        Bytes wire = {0x01, 0x00, 0x00}; // the client hello, empty
        const Bytes f = frame(body);
        wire.insert(wire.end(), f.begin(), f.end());
        return wire;
    }

    void finish(const Bytes &body)
    {
        assert(body.size() == 49 && body[0] == 0x00);
        uint8_t payload[8];
        size_t plen = 9;
        assert(noise_read_message2(&hs, body.data() + 1, body.size() - 1, payload, sizeof(payload), &plen) == 0);
        assert(plen == 0 && noise_split(&hs, &send, &recv) == 0);
    }

    Bytes message(uint16_t type, const Bytes &data)
    {
        Bytes plain = {(uint8_t)(type >> 8), (uint8_t)type, (uint8_t)(data.size() >> 8), (uint8_t)data.size()};
        plain.insert(plain.end(), data.begin(), data.end());
        Bytes cipher(plain.size() + NOISE_TAG);
        assert(noise_encrypt(&send, plain.data(), plain.size(), cipher.data()) == 0);
        return frame(cipher);
    }

    std::pair<uint16_t, Bytes> open_frame(const Bytes &body)
    {
        Bytes plain(body.size() - NOISE_TAG);
        assert(noise_decrypt(&recv, body.data(), body.size(), plain.data()) == 0);
        const size_t len = (size_t)plain[2] << 8 | plain[3];
        assert(len == plain.size() - 4);
        return {(uint16_t)(plain[0] << 8 | plain[1]), Bytes(plain.begin() + 4, plain.end())};
    }
};

static bool feed(Server &sv, const Bytes &data) { return api_session_feed(&sv.s, data.data(), data.size(), tick_ms); }

static std::vector<std::pair<uint16_t, Bytes>> replies(Server &sv, Client &c)
{
    std::vector<std::pair<uint16_t, Bytes>> list;
    for (const Bytes &body : frames(sv.out)) list.push_back(c.open_frame(body));
    return list;
}

static void connect(Server &sv, Client &c)
{
    open(sv);
    assert(feed(sv, c.hello_and_message1(PSK)));
    std::vector<Bytes> f = frames(sv.out);
    assert(f.size() == 2);
    const Bytes server_hello = f[0];
    const char expected[] = "\x01tessera-deck\0aabbccddeeff"; // protocol, name, NUL, MAC, NUL
    assert(server_hello == Bytes(expected, expected + sizeof(expected)));
    c.finish(f[1]);
    assert(sv.s.state == API_SESSION_DATA && !api_session_ready(&sv.s));
    const Bytes hello = fixture("hello_request");
    assert(feed(sv, c.message(API_HELLO_REQUEST, hello)));
    auto r = replies(sv, c);
    assert(r.size() == 1 && r[0].first == API_HELLO_RESPONSE);
    api_hello_response_t expect = {API_VERSION_MAJOR, API_VERSION_MINOR, "Tessera 0.8.0", "tessera-deck"};
    ENCODE(w, api_encode_hello_response(&w, &expect));
    assert(r[0].second == written(w) && api_session_ready(&sv.s));
}

static void test_session_handshake_and_basics()
{
    Server sv;
    Client c;
    connect(sv, c);
    assert(feed(sv, c.message(API_CONNECT_REQUEST, {})));
    assert(feed(sv, c.message(API_PING_REQUEST, {})));
    auto r = replies(sv, c);
    assert(r.size() == 2 && r[0].first == API_CONNECT_RESPONSE && r[0].second.empty() && r[1].first == API_PING_RESPONSE);
    assert(feed(sv, c.message(999, {1, 2, 3})) && sv.unhandled.size() == 1 && sv.unhandled[0].first == 999);
    // Keepalive: a ping after 20 s of silence, a close after 50 s.
    tick_ms += API_PING_AFTER_MS + 1;
    assert(api_session_tick(&sv.s, tick_ms));
    r = replies(sv, c);
    assert(r.size() == 1 && r[0].first == API_PING_REQUEST);
    assert(api_session_tick(&sv.s, tick_ms + 100) && sv.out.empty()); // only one ping
    tick_ms += API_DEAD_AFTER_MS;
    assert(!api_session_tick(&sv.s, tick_ms) && sv.s.state == API_SESSION_CLOSED);
    // Disconnect is answered, then closed.
    Server sv2;
    Client c2;
    connect(sv2, c2);
    assert(!feed(sv2, c2.message(API_DISCONNECT_REQUEST, {})));
    r = replies(sv2, c2);
    assert(r.size() == 1 && r[0].first == API_DISCONNECT_RESPONSE);
}

static void test_session_rejects()
{
    // A wrong PSK gets the exact reject frame that aioesphomeapi reads as "invalid encryption key".
    Server sv;
    Client c;
    open(sv);
    uint8_t wrong[32];
    memcpy(wrong, PSK, 32);
    wrong[0] ^= 0xFF;
    assert(!feed(sv, c.hello_and_message1(wrong)));
    std::vector<Bytes> f = frames(sv.out);
    assert(f.size() == 2);
    const char mac_failure[] = "\x01Handshake MAC failure";
    assert(f[1] == Bytes(mac_failure, mac_failure + sizeof(mac_failure) - 1));
    // A plaintext client (first byte 0x00): a 0x01 frame, so aioesphomeapi raises RequiresEncryptionAPIError.
    Server plain;
    open(plain);
    const Bytes plaintext_hello = {0x00, 0x05, 0x01, 0x0A, 0x01, 'x', 0x10};
    assert(!feed(plain, plaintext_hello));
    const Bytes expected = frame(Bytes{0x01, 'B', 'a', 'd', ' ', 'i', 'n', 'd', 'i', 'c', 'a', 't', 'o', 'r', ' ',
                                       'b', 'y', 't', 'e'});
    assert(plain.out == expected);
    // Another first byte closes at once, with nothing sent.
    Server odd;
    open(odd);
    assert(!feed(odd, Bytes{0x17, 0x03, 0x03}) && odd.out.empty());
    // An oversized handshake frame.
    Server big;
    open(big);
    assert(!feed(big, Bytes{0x01, 0x00, 0xC8}));
    // An oversized data frame closes; so does a handshake that takes more than 10 s.
    Server sv2;
    Client c2;
    connect(sv2, c2);
    assert(!feed(sv2, Bytes{0x01, 0x05, 0x00}) && sv2.s.state == API_SESSION_CLOSED);
    Server slow;
    open(slow);
    assert(api_session_tick(&slow.s, tick_ms + 9000));
    assert(!api_session_tick(&slow.s, tick_ms + API_HELLO_TIMEOUT_MS + 1));
    // A message before Hello closes.
    Server early;
    Client c3;
    open(early);
    assert(feed(early, c3.hello_and_message1(PSK)));
    std::vector<Bytes> hf = frames(early.out);
    c3.finish(hf[1]);
    assert(!feed(early, c3.message(API_DEVICE_INFO_REQUEST, {})));
    // Byte by byte works the same as all at once.
    Server slowly;
    Client c4;
    open(slowly);
    const Bytes wire = c4.hello_and_message1(PSK);
    for (uint8_t b : wire) assert(api_session_feed(&slowly.s, &b, 1, tick_ms));
    assert(slowly.s.state == API_SESSION_DATA);
}

// Random bytes into the session from a LAN host with no key: before the hello, inside the handshake, and as
// encrypted frames after a real handshake. Only "no crash, no overrun" is checked (ASAN/UBSAN in CI).
static void fuzz_feed(Server &sv, std::mt19937 &rng, Bytes data)
{
    size_t at = 0;
    while (at < data.size()) {
        const size_t chunk = 1 + rng() % (data.size() - at);
        const bool alive = api_session_feed(&sv.s, data.data() + at, chunk, tick_ms);
        assert(sv.s.rx_len <= API_BUFFER);
        at += chunk;
        if (!alive) {
            assert(sv.s.state == API_SESSION_CLOSED);
            return;
        }
    }
    api_session_tick(&sv.s, tick_ms);
}

static void test_fuzz_session()
{
    std::mt19937 rng(4321);
    for (int round = 0; round < 100000; ++round) {
        Server sv;
        open(sv);
        Bytes data(1 + rng() % 600);
        for (uint8_t &b : data) b = (uint8_t)rng();
        const int start = round % 4; // a random frame, a 0x01 frame, a 0x00 plaintext start, or a client hello first
        if (start == 1) data[0] = 0x01;
        if (start == 2) data[0] = 0x00;
        if (start == 3) {
            const Bytes hello = {0x01, 0x00, 0x00, 0x01};
            data.insert(data.begin(), hello.begin(), hello.end());
        }
        fuzz_feed(sv, rng, data);
    }
    for (int round = 0; round < 2000; ++round) {
        Server sv;
        Client c;
        connect(sv, c);
        Bytes body(20 + rng() % 1081);
        for (uint8_t &b : body) b = (uint8_t)rng();
        Bytes data = frame(body);
        if (round % 3 == 0) data[1] = (uint8_t)rng(), data[2] = (uint8_t)rng(); // a random length too
        fuzz_feed(sv, rng, data);
    }
}

// ---- entities ----

static void set_layout_with_double_on_3()
{
    deck_button_t buttons[3]{};
    for (int i = 0; i < 3; ++i) {
        buttons[i].id = i + 1;
        snprintf(buttons[i].label, sizeof(buttons[i].label), "K%d", i + 1);
        buttons[i].span = 1;
    }
    buttons[2].has_double = true;
    assert(deck_model_replace_buttons(buttons, 3));
}

static void test_fnv_keys()
{
    assert(api_fnv1("pc_connected") == 0xf5fb26f6u && api_fnv1("backlight") == 0x3460f724u);
    assert(api_fnv1("wifi_signal") == 0x2fa52175u && api_fnv1("profile") == 0xf5f2d170u);
    assert(api_fnv1("page") == 0x6cfa9b2cu && api_fnv1("show_clock") == 0x146ecd61u);
    assert(api_key_slot_key(1) == 0xe66589cau && api_key_slot_key(18) == 0x7bd7e8c6u);
    assert(api_key_slot_key(0) == 0 && api_key_slot_key(19) == 0);
}

static void test_entities_list_and_states()
{
    assert(deck_model_api_options_from_json(R"({"profiles":["Main","Chrome"],"pages":["main"]})"));
    deck_model_set_context("Main", "main", false);
    deck_model_set_brightness(50);
    deck_model_set_dimmed(false);
    deck_model_note_host();
    Server sv;
    sv.route_entities = true;
    Client c;
    connect(sv, c);
    api_snapshot_read(&sv.now, true, -58);
    assert(sv.now.pc_linked && sv.now.brightness == 50 && sv.now.has_profiles);

    assert(feed(sv, c.message(API_DEVICE_INFO_REQUEST, {})));
    auto r = replies(sv, c);
    assert(r.size() == 1 && r[0].first == API_DEVICE_INFO_RESPONSE && r[0].second == fixture("device_info"));

    assert(feed(sv, c.message(API_LIST_ENTITIES_REQUEST, {})));
    r = replies(sv, c);
    assert(r.size() == 1 + 1 + 1 + 2 + 1 + API_KEY_SLOTS + 1);
    assert(r[0].first == API_LIST_BINARY_SENSOR && r[0].second == fixture("list_binary_sensor"));
    assert(r[1].first == API_LIST_LIGHT && r[1].second == fixture("list_light"));
    assert(r[2].first == API_LIST_SENSOR && r[2].second == fixture("list_sensor"));
    assert(r[3].first == API_LIST_SELECT && r[3].second == fixture("list_select_profile"));
    assert(r[4].first == API_LIST_SELECT && r[4].second == fixture("list_select_page"));
    assert(r[5].first == API_LIST_BUTTON && r[5].second == fixture("list_button"));
    assert(r[6].first == API_LIST_EVENT && r[6].second == fixture("list_event_1"));
    assert(r[6 + 12].second == fixture("list_event_13"));
    assert(r.back().first == API_LIST_DONE && r.back().second.empty());

    assert(feed(sv, c.message(API_SUBSCRIBE_LOGS, {0x08, 0x05}))); // ignored: logs never leave over Wi-Fi
    assert(replies(sv, c).empty());

    assert(feed(sv, c.message(API_SUBSCRIBE_STATES, {})));
    r = replies(sv, c);
    assert(r.size() == 5); // one per stateful entity
    assert(r[0].first == API_BINARY_SENSOR_STATE && r[0].second == fixture("state_binary_sensor"));
    assert(r[1].first == API_LIGHT_STATE && r[1].second == fixture("state_light"));
    assert(r[2].first == API_SENSOR_STATE && r[2].second == fixture("state_sensor"));
    assert(r[3].first == API_SELECT_STATE && r[3].second == fixture("state_select"));
    assert(r[4].first == API_SELECT_STATE);

    // Nothing changed: nothing sent. A brightness change sends the light only.
    api_entities_tick(&sv.s, &sv.peer, &sv.now, tick_ms);
    assert(replies(sv, c).empty());
    deck_model_set_brightness(30);
    api_snapshot_read(&sv.now, true, -58);
    api_entities_tick(&sv.s, &sv.peer, &sv.now, tick_ms);
    r = replies(sv, c);
    assert(r.size() == 1 && r[0].first == API_LIGHT_STATE);
    // The Wi-Fi signal again after 60 s.
    api_entities_tick(&sv.s, &sv.peer, &sv.now, tick_ms + API_RSSI_EVERY_MS);
    r = replies(sv, c);
    assert(r.size() == 1 && r[0].first == API_SENSOR_STATE);
    // Events.
    assert(api_entities_send_event(&sv.s, &sv.peer, 1, "double"));
    r = replies(sv, c);
    assert(r.size() == 1 && r[0].first == API_EVENT && r[0].second == fixture("event_double"));
    assert(!api_entities_send_event(&sv.s, &sv.peer, 19, "press"));

    // Commands: backlight off, then on at 30 %.
    assert(feed(sv, c.message(API_LIGHT_COMMAND, fixture("light_off"))));
    assert(deck_model_take_backlight_off() && !deck_model_take_backlight_off());
    sv.now.dimmed = true;
    const uint32_t wake = deck_model_wake_sequence();
    assert(feed(sv, c.message(API_LIGHT_COMMAND, fixture("light_command"))));
    int level = 0;
    bool save = false;
    assert(deck_model_wake_sequence() == wake + 1);
    assert(deck_model_take_brightness_request(&level, &save) && level == 30 && save);
    // Show clock.
    while (deck_model_take_screen_request() >= 0) {}
    assert(feed(sv, c.message(API_BUTTON_COMMAND, fixture("button_command"))));
    assert(deck_model_take_screen_request() == DECK_SCREEN_AMBIENT);
    // Select: a known profile with the PC linked goes to the host; anything else snaps back.
    char line[160];
    while (deck_model_take_line(line, sizeof(line))) {}
    tick_ms += API_COMMAND_GAP_MS;
    assert(feed(sv, c.message(API_SELECT_COMMAND, fixture("select_command"))));
    assert(deck_model_take_line(line, sizeof(line)));
    assert(!strcmp(line, R"({"type":"ha_select","what":"profile","value":"Chrome"})"));
    assert(replies(sv, c).empty());
    // Too soon after the last command: dropped, and the state goes back.
    assert(feed(sv, c.message(API_SELECT_COMMAND, fixture("select_command"))));
    assert(!deck_model_take_line(line, sizeof(line)));
    r = replies(sv, c);
    assert(r.size() == 1 && r[0].first == API_SELECT_STATE && r[0].second == fixture("state_select"));
    // The current value queues nothing either.
    tick_ms += API_COMMAND_GAP_MS;
    ENCODE(cur, (pb_put_fixed32(&cur, 1, api_fnv1("profile")), pb_put_string(&cur, 2, "Main"), true));
    assert(feed(sv, c.message(API_SELECT_COMMAND, written(cur))));
    assert(!deck_model_take_line(line, sizeof(line)) && replies(sv, c).size() == 1);
    tick_ms += API_COMMAND_GAP_MS;
    ENCODE(w, (pb_put_fixed32(&w, 1, api_fnv1("profile")), pb_put_string(&w, 2, "Nope"), true));
    assert(feed(sv, c.message(API_SELECT_COMMAND, written(w))));
    assert(!deck_model_take_line(line, sizeof(line)));
    r = replies(sv, c);
    assert(r.size() == 1 && r[0].first == API_SELECT_STATE && r[0].second == fixture("state_select"));
    sv.now.pc_linked = false;
    assert(feed(sv, c.message(API_SELECT_COMMAND, fixture("select_command"))));
    assert(!deck_model_take_line(line, sizeof(line)) && replies(sv, c).size() == 1);
    // New options after ListEntities: after a quiet second the client is told to disconnect, and re-lists.
    api_entities_tick(&sv.s, &sv.peer, &sv.now, tick_ms); // sends the PC link that just went away
    replies(sv, c);
    assert(deck_model_api_options_from_json(R"({"profiles":["Main","Chrome","Games"],"pages":["main"]})"));
    api_entities_tick(&sv.s, &sv.peer, &sv.now, tick_ms);
    assert(api_session_ready(&sv.s) && replies(sv, c).empty());
    assert(deck_model_api_options_from_json(R"({"profiles":["Main","Chrome","Games","Work"],"pages":["main"]})"));
    api_entities_tick(&sv.s, &sv.peer, &sv.now, tick_ms + 600);
    api_entities_tick(&sv.s, &sv.peer, &sv.now, tick_ms + 1200); // the second change restarted the second
    assert(api_session_ready(&sv.s) && replies(sv, c).empty());
    api_entities_tick(&sv.s, &sv.peer, &sv.now, tick_ms + 1600);
    r = replies(sv, c);
    assert(r.size() == 1 && r[0].first == API_DISCONNECT_REQUEST && sv.s.state == API_SESSION_CLOSED);
    // Brightness out of range is clamped before rounding.
    Server sv3;
    sv3.route_entities = true;
    Client c5;
    connect(sv3, c5);
    ENCODE(huge, (pb_put_fixed32(&huge, 1, api_fnv1("backlight")), pb_put_bool(&huge, 4, true),
                  pb_put_float(&huge, 5, 3e38f), true));
    assert(feed(sv3, c5.message(API_LIGHT_COMMAND, written(huge))));
    assert(deck_model_take_brightness_request(&level, &save) && level == 100);
    // Options validation.
    assert(!deck_model_api_options_from_json(R"({"profiles":["a"]})"));
    assert(!deck_model_api_options_from_json(R"({"profiles":["0123456789012345678901234567890123"],"pages":[]})"));
    assert(!deck_model_api_options_from_json(
        R"({"profiles":["1","2","3","4","5","6","7","8","9","10","11","12","13","14","15","16","17"],"pages":[]})"));
    assert(deck_model_api_options_from_json(R"({"profiles":[],"pages":[]})"));
    api_snapshot_read(&sv.now, false, 0);
    assert(!sv.now.has_profiles && !sv.now.wifi && sv.now.rssi == 0);
}

static void test_settings_json()
{
    api_settings_t s;
    const char *field = nullptr;
    assert(api_settings_from_json(R"({"enabled":true,"name":"tessera-deck","friendly":"Tessera Deck","area":""})", &s,
                                  &field));
    assert(s.enabled && !strcmp(s.name, "tessera-deck") && !strcmp(s.friendly, "Tessera Deck") && !s.area[0]);
    assert(api_settings_from_json(R"({"enabled":false,"name":"a","friendly":"Kjøkken","area":"Stue"})", &s, &field));
    const struct { const char *json, *field; } bad[] = {
        {"[]", "json"},
        {"{", "json"},
        {R"({"name":"x","friendly":"X","area":""})", "enabled"},
        {R"({"enabled":1,"name":"x","friendly":"X","area":""})", "enabled"},
        {R"({"enabled":true,"name":"Tessera","friendly":"X","area":""})", "name"},
        {R"({"enabled":true,"name":"","friendly":"X","area":""})", "name"},
        {R"({"enabled":true,"name":"abcdefghijabcdefghijabcdefghij12","friendly":"X","area":""})", "name"},
        {R"({"enabled":true,"name":"x","friendly":"","area":""})", "friendly"},
        {R"({"enabled":true,"name":"x","friendly":"a\nb","area":""})", "friendly"},
        {R"({"enabled":true,"name":"x","friendly":"X"})", "area"},
        {R"({"enabled":true,"name":"x","friendly":"X","area":"0123456789012345678901234567890123456789x"})", "area"},
    };
    for (const auto &b : bad) {
        field = nullptr;
        assert(!api_settings_from_json(b.json, &s, &field) && field && !strcmp(field, b.field));
    }
    std::string friendly60(60, 'x'), friendly61(61, 'x');
    assert(api_settings_from_json(("{\"enabled\":true,\"name\":\"x\",\"friendly\":\"" + friendly60 + "\",\"area\":\"\"}").c_str(), &s, &field));
    assert(!api_settings_from_json(("{\"enabled\":true,\"name\":\"x\",\"friendly\":\"" + friendly61 + "\",\"area\":\"\"}").c_str(), &s, &field));
    api_settings_default(&s);
    assert(!s.enabled && !strcmp(s.name, "tessera-deck") && !strcmp(s.friendly, "Tessera Deck"));
}

// ---- press router ----

static void test_press_router()
{
    set_layout_with_double_on_3();
    press_router_t r;
    deck_model_record_press(1); // before init: never replayed
    press_router_init(&r);
    press_out_t out[8];
    assert(press_router_poll(&r, 1000, out, 8) == 0);
    deck_model_record_press(1);
    deck_model_record_hold(2);
    int n = press_router_poll(&r, 1000, out, 8);
    assert(n == 2 && out[0].slot == 1 && !strcmp(out[0].type, "press") && out[1].slot == 2 &&
           !strcmp(out[1].type, "hold"));
    // A double key waits 350 ms: two taps give one double, one tap gives a press after the window.
    deck_model_record_press(3);
    assert(press_router_poll(&r, 2000, out, 8) == 0);
    deck_model_record_press(3);
    n = press_router_poll(&r, 2200, out, 8);
    assert(n == 1 && out[0].slot == 3 && !strcmp(out[0].type, "double"));
    deck_model_record_press(3);
    assert(press_router_poll(&r, 3000, out, 8) == 0);
    assert(press_router_poll(&r, 3000 + PRESS_DOUBLE_MS - 1, out, 8) == 0);
    n = press_router_poll(&r, 3000 + PRESS_DOUBLE_MS, out, 8);
    assert(n == 1 && !strcmp(out[0].type, "press"));
    // A hold after a tap: the tap is a press, then the hold.
    deck_model_record_press(3);
    assert(press_router_poll(&r, 4000, out, 8) == 0);
    deck_model_record_hold(3);
    n = press_router_poll(&r, 4100, out, 8);
    assert(n == 2 && !strcmp(out[0].type, "press") && !strcmp(out[1].type, "hold"));
    // More than the ring holds between two polls: the rest is dropped and counted.
    for (int i = 0; i < DECK_EVENT_RING + 5; ++i) deck_model_record_press(1);
    int total = 0;
    while ((n = press_router_poll(&r, 5000, out, 8)) > 0) total += n;
    assert(total == DECK_EVENT_RING && r.dropped == 5);
}

// ---- stage C: Home Assistant keys ----

static void test_ha_codec_golden_bytes()
{
    const api_ha_pair_t data[] = {{"entity_id", "light.kitchen"}, {"brightness_pct", "50"}};
    ENCODE(a, api_encode_ha_action(&a, "light.turn_on", data, 2));
    assert(written(a) == fixture("ha_action"));
    const api_ha_pair_t scene[] = {{"entity_id", "scene.evening"}};
    ENCODE(c, api_encode_ha_action(&c, "scene.turn_on", scene, 1));
    assert(written(c) == fixture("ha_action_bare"));
    ENCODE(s, api_encode_ha_state_subscription(&s, "light.kitchen", ""));
    assert(written(s) == fixture("ha_subscribe_state"));
    ENCODE(t, api_encode_ha_state_subscription(&t, "climate.living_room", "current_temperature"));
    assert(written(t) == fixture("ha_subscribe_attribute"));

    api_ha_state_t state;
    Bytes m = fixture("ha_state");
    assert(api_decode_ha_state(m.data(), m.size(), &state));
    assert(!strcmp(state.entity_id, "light.kitchen") && !strcmp(state.state, "on") && !state.attribute[0]);
    m = fixture("ha_state_attribute");
    assert(api_decode_ha_state(m.data(), m.size(), &state));
    assert(!strcmp(state.attribute, "current_temperature") && !strcmp(state.state, "21.5"));
    // A long state is cut at a UTF-8 boundary; an entity id that does not fit, or none at all, is an error.
    std::string long_state;
    for (int i = 0; i < 40; ++i) long_state += "\xC3\xA6"; // 80 bytes of 'ae'
    Bytes big = {0x0A, 0x05, 's', '.', 'x', 'y', 'z', 0x12, (uint8_t)long_state.size()};
    big.insert(big.end(), long_state.begin(), long_state.end());
    assert(api_decode_ha_state(big.data(), big.size(), &state) && strlen(state.state) == 62);
    Bytes none = {0x12, 0x02, 'o', 'n'};
    assert(!api_decode_ha_state(none.data(), none.size(), &state));
    Bytes huge = {0x0A, 0x81, 0x01};
    huge.insert(huge.end(), 129, 'a');
    assert(!api_decode_ha_state(huge.data(), huge.size(), &state));
}

static const char *HA_LAYOUT = R"({"buttons":[
 {"id":1,"label":"Kitchen","color":"#FFB74D","ha":{"p":[{"a":"light.toggle","e":"light.kitchen","d":{"brightness_pct":"50","transition":2,"flash":true}}],
  "h":[{"a":"scene.turn_on","e":"scene.evening"},{"a":"script.turn_on","e":"script.a,script.b"}]},
  "hs":{"e":"light.kitchen","a":"","m":"a","on":["on"],"u":""}},
 {"id":2,"label":"Temp","span":2,"hs":{"e":"climate.living_room","a":"current_temperature","m":"v","u":"°C"}},
 {"id":3,"label":"Kitchen 2","hs":{"e":"light.kitchen","m":"b","on":["on","heat"]}},
 {"id":4,"label":"PC only"}]})";

static void test_ha_layout_json()
{
    assert(deck_model_ha_from_json(HA_LAYOUT));
    deck_ha_step_t steps[4];
    assert(deck_model_ha_steps(1, 'p', steps, 4) == 1);
    assert(!strcmp(steps[0].action, "light.toggle") && !strcmp(steps[0].entity_id, "light.kitchen"));
    assert(steps[0].data_count == 3 && !strcmp(steps[0].keys[1], "transition") && !strcmp(steps[0].values[1], "2"));
    assert(!strcmp(steps[0].values[2], "true"));
    assert(deck_model_ha_steps(1, 'h', steps, 4) == 2 && deck_model_ha_steps(1, 'd', steps, 4) == 0);
    assert(deck_model_ha_has_steps(1, 'p') && !deck_model_ha_has_steps(4, 'p'));
    deck_ha_follow_t follows[DECK_HA_FOLLOWS_MAX];
    assert(deck_model_ha_follows(follows, DECK_HA_FOLLOWS_MAX) == 3);
    assert(follows[1].mode == 'v' && !strcmp(follows[1].unit, "\xC2\xB0" "C") && follows[1].on_count == 1);
    assert(follows[2].on_count == 2 && follows[2].mode == 'b');

    // Each bad field makes the layout invalid and leaves the table as it was.
    const uint32_t version = deck_model_ha_version();
    const char *bad[] = {
        R"({"buttons":[{"id":1,"label":"x","ha":[]}]})",
        R"({"buttons":[{"id":1,"label":"x","ha":{"p":{}}}]})",
        R"({"buttons":[{"id":1,"label":"x","ha":{"p":[{"e":"light.a"}]}}]})",
        R"({"buttons":[{"id":1,"label":"x","ha":{"p":[{"a":"toggle"}]}}]})",
        R"({"buttons":[{"id":1,"label":"x","ha":{"p":[{"a":"Light.toggle"}]}}]})",
        R"({"buttons":[{"id":1,"label":"x","ha":{"p":[{"a":"light.toggle","e":"light.a,light.b,light.c,light.d,light.e"}]}}]})",
        R"({"buttons":[{"id":1,"label":"x","ha":{"p":[{"a":"light.toggle","e":"light."}]}}]})",
        R"({"buttons":[{"id":1,"label":"x","ha":{"p":[{"a":"light.toggle","d":{"a":"1","b":"2","c":"3","d":"4","e":"5"}}]}}]})",
        R"({"buttons":[{"id":1,"label":"x","ha":{"p":[{"a":"light.toggle","d":{"Bad":"1"}}]}}]})",
        R"({"buttons":[{"id":1,"label":"x","ha":{"p":[{"a":"light.toggle","d":{"x":[1]}}]}}]})",
        R"({"buttons":[{"id":1,"label":"x","ha":{"p":[{"a":"light.toggle","d":{"entity_id":"light.b"}}]}}]})",
        R"({"buttons":[{"id":1,"label":"x","ha":{"p":[{"a":"a.b"},{"a":"a.c"},{"a":"a.d"}]}}]})",
        R"({"buttons":[{"id":1,"label":"x","hs":{"e":"light.a,light.b"}}]})",
        R"({"buttons":[{"id":1,"label":"x","hs":{"a":"x"}}]})",
        R"({"buttons":[{"id":1,"label":"x","hs":{"e":"light.a","m":"x"}}]})",
        R"({"buttons":[{"id":1,"label":"x","hs":{"e":"light.a","a":"Bad-name"}}]})",
        R"({"buttons":[{"id":1,"label":"x","hs":{"e":"light.a","on":[]}}]})",
        R"({"buttons":[{"id":1,"label":"x","hs":{"e":"light.a","on":["a","b","c","d","e"]}}]})",
        R"({"buttons":[{"id":1,"label":"x","hs":{"e":"light.a","on":["seventeen chars!!"]}}]})",
        R"({"buttons":[{"id":1,"label":"x","hs":{"e":"light.a","u":"seven c"}}]})",
        R"({"buttons":[{"id":1,"label":"x","hs":"light.a"}]})",
        R"({"buttons":[{"id":"1","label":"x","hs":{"e":"light.a"}}]})",
        "not json",
    };
    for (const char *json : bad) assert(!deck_model_ha_from_json(json));
    assert(deck_model_ha_version() == version && deck_model_ha_follows(follows, DECK_HA_FOLLOWS_MAX) == 3);

    // 24 steps in a page at most: 12 keys with 2 press steps fit, a 13th key's steps do not.
    auto keys_with_two_steps = [](int keys) {
        std::string json = R"({"buttons":[)";
        for (int id = 1; id <= keys; ++id)
            json += (id > 1 ? "," : "") + std::string(R"({"id":)") + std::to_string(id) +
                    R"(,"label":"k","ha":{"p":[{"a":"a.b"},{"a":"a.c"}]}})";
        return json + "]}";
    };
    assert(!deck_model_ha_from_json(keys_with_two_steps(13).c_str()));
    assert(deck_model_ha_from_json(keys_with_two_steps(12).c_str()) && deck_model_ha_steps(12, 'p', steps, 4) == 2);
    // Within the 16-deep nesting of the panel's cJSON: the deepest HA field (data) is 7 levels down.
    assert(deck_model_ha_from_json(HA_LAYOUT) && deck_model_ha_version() != version);
}

static void set_ha_buttons()
{
    deck_button_t buttons[4]{};
    const char *labels[] = {"Kitchen", "Temp", "Kitchen 2", "PC only"};
    for (int i = 0; i < 4; ++i) {
        buttons[i].id = i + 1;
        snprintf(buttons[i].label, sizeof(buttons[i].label), "%s", labels[i]);
        buttons[i].span = i == 1 ? 2 : 1;
        buttons[i].color = 0xFFB74D;
    }
    assert(deck_model_replace_buttons(buttons, 4));
}

static deck_button_t button(int index)
{
    deck_button_t b{};
    assert(deck_model_get_button(index, &b));
    return b;
}

static void test_ha_states_on_keys()
{
    assert(deck_model_ha_from_json(HA_LAYOUT));
    set_ha_buttons();
    assert(button(0).color == 0xFFB74D && !strcmp(button(1).sub, "")); // no state yet: the host's look
    uint32_t live = deck_model_live_version();
    assert(deck_model_set_ha_state("light.kitchen", "", "off"));
    assert(deck_model_live_version() != live);
    assert(button(0).color == DECK_HA_OFF_COLOR && !strcmp(button(0).label, "Kitchen"));
    assert(button(2).color == DECK_HA_OFF_COLOR && !strcmp(button(2).label, "off")); // both: color and label
    assert(deck_model_set_ha_state("light.kitchen", "", "on"));
    assert(button(0).color == 0xFFB74D && !strcmp(button(2).label, "on"));
    live = deck_model_live_version();
    assert(deck_model_set_ha_state("light.kitchen", "", "on") && deck_model_live_version() == live); // no change
    assert(!deck_model_set_ha_state("light.kitchen", "brightness", "255")); // a pair nobody follows
    assert(deck_model_set_ha_state("climate.living_room", "current_temperature", "21.5"));
    assert(!strcmp(button(1).sub, "21.5 \xC2\xB0" "C") && !strcmp(button(1).label, "Temp")); // wide: the sub line
    // The host re-pushes the same layout: the states stay, and nothing is rebuilt.
    const uint32_t version = deck_model_ha_version(), buttons = deck_model_buttons_version();
    assert(deck_model_ha_from_json(HA_LAYOUT));
    set_ha_buttons();
    assert(deck_model_ha_version() == version && deck_model_buttons_version() == buttons);
    assert(!strcmp(button(1).sub, "21.5 \xC2\xB0" "C"));
    // HA goes away: the states stay, faded; a new state brings the color back.
    deck_model_set_api_client(true);
    deck_model_set_api_client(false);
    const uint32_t faded = button(0).color;
    assert(faded != 0xFFB74D && faded != DECK_HA_OFF_COLOR && !strcmp(button(1).sub, "21.5 \xC2\xB0" "C"));
    assert(deck_model_set_ha_state("light.kitchen", "", "on") && button(0).color == 0xFFB74D);
}

static int drain_feedback(deck_feedback_t *last)
{
    int id = 0, n = 0, last_id = 0;
    deck_feedback_t kind;
    while (deck_model_take_feedback(&id, &kind)) {
        ++n;
        last_id = id;
        *last = kind;
    }
    return n ? last_id : 0;
}

static void test_ha_press_and_follow_session()
{
    assert(deck_model_ha_from_json(HA_LAYOUT));
    set_ha_buttons();
    deck_feedback_t kind;
    drain_feedback(&kind);
    Server sv;
    sv.route_entities = true;
    Client c;
    connect(sv, c);
    api_ha_client_t clients[] = {{&sv.s, &sv.peer}};

    // Not subscribed to HA actions: nothing is sent and the key turns red.
    assert(api_ha_press(clients, 1, 1, "press") == 0);
    assert(replies(sv, c).empty() && drain_feedback(&kind) == 1 && kind == DECK_FEEDBACK_ALERT);
    // No homeassistant step for that trigger: nothing at all (the PC's feedback, if any, decides).
    assert(api_ha_press(clients, 1, 4, "press") == -1 && api_ha_press(clients, 1, 1, "double") == -1);
    assert(drain_feedback(&kind) == 0);

    assert(feed(sv, c.message(API_SUBSCRIBE_HA_SERVICES, {})));
    assert(sv.peer.ha_services && replies(sv, c).empty());
    assert(api_ha_press(clients, 1, 1, "press") == 1);
    auto r = replies(sv, c);
    assert(r.size() == 1 && r[0].first == API_HA_ACTION_REQUEST);
    const api_ha_pair_t data[] = {{"entity_id", "light.kitchen"}, {"brightness_pct", "50"}, {"transition", "2"},
                                  {"flash", "true"}};
    ENCODE(w, api_encode_ha_action(&w, "light.toggle", data, 4));
    assert(r[0].second == written(w));
    assert(drain_feedback(&kind) == 1 && kind == DECK_FEEDBACK_OK);
    assert(api_ha_press(clients, 1, 1, "hold") == 2 && replies(sv, c).size() == 2);
    assert(drain_feedback(&kind) == 1 && kind == DECK_FEEDBACK_OK);

    // States: after 38 the panel subscribes each followed pair once (light.kitchen is followed by two keys).
    assert(feed(sv, c.message(API_SUBSCRIBE_HA_STATES, {})));
    r = replies(sv, c);
    assert(r.size() == 2 && r[0].first == API_HA_STATE_SUBSCRIPTION && r[0].second == fixture("ha_subscribe_state"));
    assert(r[1].second == fixture("ha_subscribe_attribute"));
    api_entities_tick(&sv.s, &sv.peer, &sv.now, tick_ms); // nothing new
    assert(replies(sv, c).empty());
    assert(feed(sv, c.message(API_HA_STATE, fixture("ha_state_attribute"))));
    assert(!strcmp(button(1).sub, "21.5 \xC2\xB0" "C"));
    // A layout change with a new pair: the pairs go out again on the next tick.
    const std::string next = std::string(HA_LAYOUT).replace(std::string(HA_LAYOUT).find("PC only\"}"), 9,
                                                            R"(PC only","hs":{"e":"switch.fan"}})");
    assert(deck_model_ha_from_json(next.c_str()));
    api_entities_tick(&sv.s, &sv.peer, &sv.now, tick_ms);
    r = replies(sv, c);
    assert(r.size() == 3 && r[2].first == API_HA_STATE_SUBSCRIPTION);
    assert(sv.peer.ha_subscriptions == 5);
    // Too many subscriptions on one connection: the panel closes it, and the client starts clean.
    sv.peer.ha_subscriptions = API_HA_SUBSCRIPTIONS_MAX - 1;
    assert(deck_model_ha_from_json(HA_LAYOUT));
    api_entities_tick(&sv.s, &sv.peer, &sv.now, tick_ms);
    assert(sv.s.state == API_SESSION_CLOSED);
    // Closed: a press finds no client and turns the key red.
    assert(api_ha_press(clients, 1, 1, "press") == 0 && drain_feedback(&kind) == 1 && kind == DECK_FEEDBACK_ALERT);
}

static void test_ha_press_routing_from_events()
{
    // The real path: a deck event goes through press_router, then api_ha_press (as api_server's serve() does).
    assert(deck_model_ha_from_json(R"({"buttons":[{"id":3,"label":"K3","double":true,"ha":{"d":[{"a":"a.b"}]}}]})"));
    set_layout_with_double_on_3();
    deck_feedback_t kind;
    drain_feedback(&kind);
    press_router_t r;
    press_router_init(&r);
    press_out_t out[8];
    api_ha_client_t none[1] = {};
    deck_model_record_press(3);
    assert(press_router_poll(&r, 1000, out, 8) == 0); // waits for a second tap
    deck_model_record_press(3);
    const int n = press_router_poll(&r, 1100, out, 8);
    assert(n == 1 && !strcmp(out[0].type, "double"));
    assert(api_ha_press(none, 0, out[0].slot, out[0].type) == 0); // no client at all
    assert(drain_feedback(&kind) == 3 && kind == DECK_FEEDBACK_ALERT);
}

int main()
{
    deck_model_init();
    assert(api_crypto_init() == 0);
    test_proto_basics();
    test_encoders_match_golden_bytes();
    test_decoders_read_golden_bytes();
    test_fuzz_reader();
    test_fuzz_session();
    test_crypto_known_answers();
    test_noise_cacophony_vector();
    test_session_handshake_and_basics();
    test_session_rejects();
    test_fnv_keys();
    test_entities_list_and_states();
    test_settings_json();
    test_press_router();
    test_ha_codec_golden_bytes();
    test_ha_layout_json();
    test_ha_states_on_keys();
    test_ha_press_and_follow_session();
    test_ha_press_routing_from_events();
    std::puts("test_api: all passed");
    return 0;
}
