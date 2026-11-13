#pragma once
#include <cstdint>
#include <memory>
#include <vector>
#include <string>

struct DeckImage {
    int width=0, height=0;
    std::vector<std::vector<uint8_t>> frames;
    std::vector<uint16_t> durations;
};
std::shared_ptr<const DeckImage> deck_image_get(const char* id);
// Decoded bytes and number of cached images (diagnostics and tests); 8 MiB between pages, one page more while its images upload.
void deck_image_cache_stats(size_t* bytes, size_t* count);
// After a layout is accepted: renews the images it names and trims the cache to 8 MiB by dropping the oldest
// others, the same rule host/panel_serial.py push_assets applies, so the host resends whatever the panel dropped.
void deck_image_keep(const std::vector<std::string>& ids);
// Changes whenever an image is stored, so a key waiting for one can tell it has arrived.
uint32_t deck_image_generation();
// USB task only; publishes immutable decoded frames after complete validation.
bool deck_image_command(const char* line, std::string& response);
