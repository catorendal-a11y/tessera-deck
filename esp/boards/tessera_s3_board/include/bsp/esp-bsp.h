#pragma once
/* The part of the P4 board support that main.cpp uses, for the 800 x 480 ESP32-S3 boards. */
#include <stdbool.h>
#include <stdint.h>
#include "esp_lvgl_port.h"
#include "bsp/display.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    lvgl_port_cfg_t lvgl_port_cfg;
    /* Kept for main.cpp. LVGL draws straight into the panel's two frame buffers, so these are not used. */
    uint32_t buffer_size;
    bool double_buffer;
    struct {
        unsigned int buff_dma: 1;
        unsigned int buff_spiram: 1;
        unsigned int sw_rotate: 1;
    } flags;
} bsp_display_cfg_t;

/* Starts the panel, LVGL and touch. Returns NULL if the panel does not start; a missing touch controller is only logged. */
lv_display_t *bsp_display_start_with_config(const bsp_display_cfg_t *cfg);
bool bsp_display_lock(uint32_t timeout_ms);
void bsp_display_unlock(void);

#ifdef __cplusplus
}
#endif
