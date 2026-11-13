#pragma once
// Small Arduino compatibility types used by the ESP-IDF application.
#include <cstdint>
#include <esp_timer.h>
inline uint32_t millis() { return static_cast<uint32_t>(esp_timer_get_time() / 1000); }
