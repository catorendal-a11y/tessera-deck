#pragma once
// Small Arduino compatibility types used by the ESP-IDF application.
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <esp_timer.h>
inline uint32_t millis() { return static_cast<uint32_t>(esp_timer_get_time() / 1000); }
inline uint32_t micros() { return static_cast<uint32_t>(esp_timer_get_time()); }
struct ConsoleLog {
  template<typename... Args> int printf(const char* format, Args... args) {
    return std::printf(format, args...);
  }
};
inline ConsoleLog Serial;
