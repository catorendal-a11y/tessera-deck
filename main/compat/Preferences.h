#pragma once
// Checked ESP-IDF NVS implementation of the Preferences calls used upstream.
#include <cstddef>
#include <cstdint>
#include <nvs.h>
enum PreferenceType { PT_INVALID, PT_U8, PT_U16, PT_BLOB };
class Preferences {
 public:
  ~Preferences() { end(); }
  bool begin(const char* name, bool readonly) {
    end(); opened_ = nvs_open(name, readonly ? NVS_READONLY : NVS_READWRITE, &handle_) == ESP_OK;
    return opened_;
  }
  void end() { if (opened_) nvs_close(handle_); opened_ = false; }
  bool isKey(const char* key) { nvs_type_t type; return opened_ && nvs_find_key(handle_, key, &type) == ESP_OK; }
  PreferenceType getType(const char* key) {
    nvs_type_t type;
    if (!opened_ || nvs_find_key(handle_, key, &type) != ESP_OK) return PT_INVALID;
    return type == NVS_TYPE_U8 ? PT_U8 : type == NVS_TYPE_U16 ? PT_U16 : type == NVS_TYPE_BLOB ? PT_BLOB : PT_INVALID;
  }
  uint8_t getUChar(const char* key, uint8_t fallback) {
    uint8_t value; return opened_ && nvs_get_u8(handle_, key, &value) == ESP_OK ? value : fallback;
  }
  uint16_t getUShort(const char* key, uint16_t fallback) {
    uint16_t value; return opened_ && nvs_get_u16(handle_, key, &value) == ESP_OK ? value : fallback;
  }
  size_t getBytesLength(const char* key) {
    size_t bytes = 0; return opened_ && nvs_get_blob(handle_, key, nullptr, &bytes) == ESP_OK ? bytes : 0;
  }
  size_t getBytes(const char* key, void* target, size_t size) {
    return opened_ && nvs_get_blob(handle_, key, target, &size) == ESP_OK ? size : 0;
  }
  size_t putBytes(const char* key, const void* value, size_t bytes) {
    return opened_ && nvs_set_blob(handle_, key, value, bytes) == ESP_OK && nvs_commit(handle_) == ESP_OK ? bytes : 0;
  }
  size_t putUChar(const char* key, uint8_t value) {
    return opened_ && nvs_set_u8(handle_, key, value) == ESP_OK && nvs_commit(handle_) == ESP_OK ? sizeof(value) : 0;
  }
 private:
  nvs_handle_t handle_ = 0;
  bool opened_ = false;
};
