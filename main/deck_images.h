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
// Decoded bytes and number of cached images (diagnostics and tests); the cache never exceeds 8 MiB.
void deck_image_cache_stats(size_t* bytes, size_t* count);
// USB task only; publishes immutable decoded frames after complete validation.
bool deck_image_command(const char* line, std::string& response);
