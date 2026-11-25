#pragma once
#include "esp_err.h"
#include "sdkconfig.h"

#if CONFIG_TESSERA_BOARD_S3_WS7B
#define BSP_LCD_H_RES 1024
#define BSP_LCD_V_RES 600
#else
#define BSP_LCD_H_RES 800
#define BSP_LCD_V_RES 480
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* 0..100. On the Waveshare board the backlight can only be switched, so anything above 0 is full. */
esp_err_t bsp_display_brightness_set(int brightness_percent);

#ifdef __cplusplus
}
#endif
