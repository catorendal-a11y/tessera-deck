/* Display, touch and backlight for the 800 x 480 ESP32-S3 boards: a 16-bit RGB565 panel, a GT911 on I2C, and a
 * backlight that is a CH422G expander pin (Waveshare), an LEDC pin (Sunton) or a command to a helper MCU (CrowPanel). */
#include "bsp/esp-bsp.h"
#include "driver/gpio.h"
#include "driver/i2c_master.h"
#include "driver/ledc.h"
#include "esp_check.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_panel_rgb.h"
#include "esp_lcd_touch_gt911.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"

static const char *TAG = "board";
static i2c_master_bus_handle_t s_i2c;

static esp_err_t i2c_start(gpio_num_t sda, gpio_num_t scl)
{
    const i2c_master_bus_config_t bus = {
        .i2c_port = I2C_NUM_0,
        .sda_io_num = sda,
        .scl_io_num = scl,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    return i2c_new_master_bus(&bus, &s_i2c);
}

/* The GT911 takes address 0x5D when INT is low while its reset is released. */
static void touch_int_low(gpio_num_t pin)
{
    const gpio_config_t out = {.pin_bit_mask = BIT64(pin), .mode = GPIO_MODE_OUTPUT};
    gpio_config(&out);
    gpio_set_level(pin, 0);
}

static void touch_int_release(gpio_num_t pin)
{
    vTaskDelay(pdMS_TO_TICKS(10));
    gpio_set_direction(pin, GPIO_MODE_INPUT);
    vTaskDelay(pdMS_TO_TICKS(50));
}

#if CONFIG_TESSERA_BOARD_S3_WS7
/* Waveshare ESP32-S3-Touch-LCD-7. The CH422G takes its commands as I2C addresses: 0x24 sets the mode (0x01 makes
 * EXIO0..7 outputs), 0x38 sets the outputs. EXIO5 (USB_SEL) stays low, high would move GPIO19/20 from the USB socket
 * to the CAN transceiver. */
#define EXIO_TOUCH_RST (1 << 1)
#define EXIO_BACKLIGHT (1 << 2)
#define EXIO_LCD_RST (1 << 3)
#define EXIO_SD_CS (1 << 4)
#define TOUCH_INT GPIO_NUM_4
static i2c_master_dev_handle_t s_exio;
static uint8_t s_exio_out;

static esp_err_t exio_write(uint8_t out)
{
    s_exio_out = out;
    return i2c_master_transmit(s_exio, &out, 1, 100);
}

static esp_err_t board_io_start(void)
{
    ESP_RETURN_ON_ERROR(i2c_start(GPIO_NUM_8, GPIO_NUM_9), TAG, "I2C");
    i2c_device_config_t dev = {.dev_addr_length = I2C_ADDR_BIT_LEN_7, .device_address = 0x24, .scl_speed_hz = 400000};
    i2c_master_dev_handle_t mode;
    ESP_RETURN_ON_ERROR(i2c_master_bus_add_device(s_i2c, &dev, &mode), TAG, "CH422G");
    const uint8_t outputs = 0x01;
    ESP_RETURN_ON_ERROR(i2c_master_transmit(mode, &outputs, 1, 100), TAG, "CH422G mode");
    dev.device_address = 0x38;
    ESP_RETURN_ON_ERROR(i2c_master_bus_add_device(s_i2c, &dev, &s_exio), TAG, "CH422G");
    /* Backlight off until main sets the brightness, as on the P4. */
    touch_int_low(TOUCH_INT);
    ESP_RETURN_ON_ERROR(exio_write(EXIO_LCD_RST | EXIO_SD_CS), TAG, "CH422G outputs");
    vTaskDelay(pdMS_TO_TICKS(10));
    ESP_RETURN_ON_ERROR(exio_write(s_exio_out | EXIO_TOUCH_RST), TAG, "CH422G outputs");
    touch_int_release(TOUCH_INT);
    return ESP_OK;
}

esp_err_t bsp_display_brightness_set(int brightness_percent)
{
    if (!s_exio) return ESP_ERR_INVALID_STATE;
    return exio_write(brightness_percent > 0 ? (s_exio_out | EXIO_BACKLIGHT) : (s_exio_out & ~EXIO_BACKLIGHT));
}

#elif CONFIG_TESSERA_BOARD_S3_8048S070
/* Sunton/Guition ESP32-8048S070. */
#define TOUCH_INT GPIO_NUM_18
#define TOUCH_RST GPIO_NUM_38
#define BACKLIGHT GPIO_NUM_2
#define BACKLIGHT_CHANNEL LEDC_CHANNEL_0

static esp_err_t board_io_start(void)
{
    ESP_RETURN_ON_ERROR(i2c_start(GPIO_NUM_19, GPIO_NUM_20), TAG, "I2C");
    touch_int_low(TOUCH_INT);
    const gpio_config_t rst = {.pin_bit_mask = BIT64(TOUCH_RST), .mode = GPIO_MODE_OUTPUT};
    ESP_RETURN_ON_ERROR(gpio_config(&rst), TAG, "touch reset");
    gpio_set_level(TOUCH_RST, 0);
    vTaskDelay(pdMS_TO_TICKS(10));
    gpio_set_level(TOUCH_RST, 1);
    touch_int_release(TOUCH_INT);
    /* 10-bit PWM like the P4, at 0 until main sets the brightness. */
    const ledc_timer_config_t timer = {
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .duty_resolution = LEDC_TIMER_10_BIT,
        .timer_num = LEDC_TIMER_0,
        .freq_hz = 5000,
        .clk_cfg = LEDC_AUTO_CLK,
    };
    ESP_RETURN_ON_ERROR(ledc_timer_config(&timer), TAG, "backlight");
    const ledc_channel_config_t channel = {
        .gpio_num = BACKLIGHT,
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .channel = BACKLIGHT_CHANNEL,
        .timer_sel = LEDC_TIMER_0,
        .duty = 0,
    };
    return ledc_channel_config(&channel);
}

esp_err_t bsp_display_brightness_set(int brightness_percent)
{
    if (brightness_percent > 100) brightness_percent = 100;
    if (brightness_percent < 0) brightness_percent = 0;
    ESP_RETURN_ON_ERROR(ledc_set_duty(LEDC_LOW_SPEED_MODE, BACKLIGHT_CHANNEL, 1023 * brightness_percent / 100), TAG, "backlight");
    return ledc_update_duty(LEDC_LOW_SPEED_MODE, BACKLIGHT_CHANNEL);
}

#elif CONFIG_TESSERA_BOARD_S3_CROWPANEL7
/* Elecrow CrowPanel Advance 7.0 ESP32-S3, hardware V1.3 to V1.5, from Elecrow's factory code and V1.3 schematic. An
 * STC8H1K28 at I2C 0x30 drives the backlight and holds the GT911 reset (its P1.7); GPIO1 is the touch INT line. One
 * byte to 0x30 sets the backlight: 0 is full, 244 the dimmest, 245 off. V1.2 boards take other values. */
#define TOUCH_INT GPIO_NUM_1
#define BACKLIGHT_MCU 0x30
#define BACKLIGHT_OFF 245
#define TOUCH_ON 250 /* the MCU lets the GT911 out of reset */
static i2c_master_dev_handle_t s_backlight;

static esp_err_t board_io_start(void)
{
    ESP_RETURN_ON_ERROR(i2c_start(GPIO_NUM_15, GPIO_NUM_16), TAG, "I2C");
    /* The MCU can start after the ESP32; Elecrow's code waits until it answers. */
    int tries = 40;
    while (i2c_master_probe(s_i2c, BACKLIGHT_MCU, 50) != ESP_OK && --tries) vTaskDelay(pdMS_TO_TICKS(50));
    if (!tries) {
        ESP_LOGW(TAG, "No backlight MCU at 0x30: no touch, and the brightness will not change");
        return ESP_OK;
    }
    const i2c_device_config_t dev = {.dev_addr_length = I2C_ADDR_BIT_LEN_7, .device_address = BACKLIGHT_MCU, .scl_speed_hz = 100000};
    ESP_RETURN_ON_ERROR(i2c_master_bus_add_device(s_i2c, &dev, &s_backlight), TAG, "backlight MCU");
    /* Elecrow's sequence: command 250, then INT low for 120 ms while the GT911 leaves reset, so it takes 0x5D. */
    const uint8_t on = TOUCH_ON;
    if (i2c_master_transmit(s_backlight, &on, 1, 100) != ESP_OK) ESP_LOGW(TAG, "Touch enable command not taken");
    touch_int_low(TOUCH_INT);
    vTaskDelay(pdMS_TO_TICKS(110));
    touch_int_release(TOUCH_INT);
    /* Backlight off until main sets the brightness, as on the P4. */
    bsp_display_brightness_set(0);
    return ESP_OK;
}

esp_err_t bsp_display_brightness_set(int brightness_percent)
{
    if (!s_backlight) return ESP_ERR_INVALID_STATE;
    if (brightness_percent > 100) brightness_percent = 100;
    const uint8_t level = brightness_percent <= 0 ? BACKLIGHT_OFF : 244 - 244 * brightness_percent / 100;
    return i2c_master_transmit(s_backlight, &level, 1, 100);
}
#endif

static esp_lcd_panel_handle_t panel_start(void)
{
    esp_lcd_rgb_panel_config_t cfg = {
        .clk_src = LCD_CLK_SRC_DEFAULT,
        .timings = {.h_res = BSP_LCD_H_RES, .v_res = BSP_LCD_V_RES},
        .data_width = 16,
        .num_fbs = 2,  /* LVGL draws into one while the other is shown; they swap at vsync */
        .bounce_buffer_size_px = 10 * BSP_LCD_H_RES,  /* the panel reads from internal RAM, PSRAM alone is too slow */
        .dma_burst_size = 64,
        .disp_gpio_num = GPIO_NUM_NC,
        .flags.fb_in_psram = 1,
    };
#if CONFIG_TESSERA_BOARD_S3_WS7
    /* Pins and porches from Waveshare's 09_lvgl_v9_demo. The demo clocks the panel at 16 MHz; 12 MHz (29 Hz instead
     * of 39) ran stable on a real board, and 16 has made the picture jump on this board while PSRAM was busy. */
    static const gpio_num_t data[16] = {14, 38, 18, 17, 10, 39, 0, 45, 48, 47, 21, 1, 2, 42, 41, 40};
    cfg.hsync_gpio_num = GPIO_NUM_46;
    cfg.vsync_gpio_num = GPIO_NUM_3;
    cfg.de_gpio_num = GPIO_NUM_5;
    cfg.pclk_gpio_num = GPIO_NUM_7;
    cfg.timings.pclk_hz = 12 * 1000 * 1000;
    cfg.timings.hsync_pulse_width = 4;
    cfg.timings.hsync_back_porch = 8;
    cfg.timings.hsync_front_porch = 8;
    cfg.timings.vsync_pulse_width = 4;
    cfg.timings.vsync_back_porch = 8;
    cfg.timings.vsync_front_porch = 8;
    cfg.timings.flags.pclk_active_neg = 1;
#elif CONFIG_TESSERA_BOARD_S3_CROWPANEL7
    /* Pins, porches and clock edge from Elecrow's factory code; data0..15 are B0-4, G0-5, R0-4. Elecrow's IDF example
     * clocks the panel at 16 MHz with PSRAM at 80 MHz. This build starts at the 12 MHz that ran stable on the Waveshare
     * board. LovyanGFX's pclk_idle_high in Elecrow's config sets the output edge, which is pclk_active_neg here. */
    static const gpio_num_t data[16] = {21, 47, 48, 45, 38, 9, 10, 11, 12, 13, 14, 7, 17, 18, 3, 46};
    cfg.hsync_gpio_num = GPIO_NUM_40;
    cfg.vsync_gpio_num = GPIO_NUM_41;
    cfg.de_gpio_num = GPIO_NUM_42;
    cfg.pclk_gpio_num = GPIO_NUM_39;
    cfg.timings.pclk_hz = 12 * 1000 * 1000;
    cfg.timings.hsync_pulse_width = 4;
    cfg.timings.hsync_back_porch = 8;
    cfg.timings.hsync_front_porch = 8;
    cfg.timings.vsync_pulse_width = 4;
    cfg.timings.vsync_back_porch = 8;
    cfg.timings.vsync_front_porch = 8;
    cfg.timings.flags.pclk_active_neg = 1;
#else
    /* Pins and timings from the vendor board file (esp32-8048S070C). It names 15,7,6,5,4 R0..R4 and 14,21,47,48,45
     * B0..B4, but hands them to the driver in this order, where data0..4 is blue; ESP3D lists them as blue too. If red
     * and blue come out swapped, swap the first and last five. */
    static const gpio_num_t data[16] = {15, 7, 6, 5, 4, 9, 46, 3, 8, 16, 1, 14, 21, 47, 48, 45};
    cfg.hsync_gpio_num = GPIO_NUM_39;
    cfg.vsync_gpio_num = GPIO_NUM_40;
    cfg.de_gpio_num = GPIO_NUM_41;
    cfg.pclk_gpio_num = GPIO_NUM_42;
    cfg.timings.pclk_hz = 12500000;
    cfg.timings.hsync_pulse_width = 30;
    cfg.timings.hsync_back_porch = 16;
    cfg.timings.hsync_front_porch = 210;
    cfg.timings.vsync_pulse_width = 13;
    cfg.timings.vsync_back_porch = 10;
    cfg.timings.vsync_front_porch = 22;
    cfg.timings.flags.hsync_idle_low = 1;
    cfg.timings.flags.vsync_idle_low = 1;
    cfg.timings.flags.pclk_active_neg = 1;
#endif
    for (int i = 0; i < 16; ++i) cfg.data_gpio_nums[i] = data[i];
    esp_lcd_panel_handle_t panel = NULL;
    if (esp_lcd_new_rgb_panel(&cfg, &panel) != ESP_OK || esp_lcd_panel_reset(panel) != ESP_OK ||
        esp_lcd_panel_init(panel) != ESP_OK) {
        ESP_LOGE(TAG, "RGB panel did not start");
        return NULL;
    }
    return panel;
}

/* Polled, as on the P4: reset and address were set in board_io_start. 0x14 is the GT911's other address. */
static esp_lcd_touch_handle_t touch_start(void)
{
    uint16_t address = ESP_LCD_TOUCH_IO_I2C_GT911_ADDRESS;
    if (i2c_master_probe(s_i2c, address, 50) != ESP_OK) address = ESP_LCD_TOUCH_IO_I2C_GT911_ADDRESS_BACKUP;
    esp_lcd_panel_io_i2c_config_t io_cfg = ESP_LCD_TOUCH_IO_I2C_GT911_CONFIG();
    io_cfg.dev_addr = address;
    io_cfg.scl_speed_hz = 400000;
    const esp_lcd_touch_config_t cfg = {
        .x_max = BSP_LCD_H_RES,
        .y_max = BSP_LCD_V_RES,
        .rst_gpio_num = GPIO_NUM_NC,
        .int_gpio_num = GPIO_NUM_NC,
    };
    esp_lcd_panel_io_handle_t io = NULL;
    esp_lcd_touch_handle_t touch = NULL;
    if (esp_lcd_new_panel_io_i2c(s_i2c, &io_cfg, &io) != ESP_OK) return NULL;
    if (esp_lcd_touch_new_i2c_gt911(io, &cfg, &touch) != ESP_OK) {
        esp_lcd_panel_io_del(io);
        return NULL;
    }
    return touch;
}

lv_display_t *bsp_display_start_with_config(const bsp_display_cfg_t *cfg)
{
    if (lvgl_port_init(&cfg->lvgl_port_cfg) != ESP_OK || board_io_start() != ESP_OK) return NULL;
    esp_lcd_panel_handle_t panel = panel_start();
    if (!panel) return NULL;
    const lvgl_port_display_cfg_t disp_cfg = {
        .panel_handle = panel,
        .buffer_size = BSP_LCD_H_RES * BSP_LCD_V_RES,
        .double_buffer = true,
        .hres = BSP_LCD_H_RES,
        .vres = BSP_LCD_V_RES,
        .color_format = LV_COLOR_FORMAT_RGB565,
        .flags.direct_mode = 1,
    };
    const lvgl_port_display_rgb_cfg_t rgb_cfg = {.flags = {.bb_mode = 1, .avoid_tearing = 1}};
    lv_display_t *disp = lvgl_port_add_disp_rgb(&disp_cfg, &rgb_cfg);
    if (!disp) return NULL;
    esp_lcd_touch_handle_t touch = touch_start();
    const lvgl_port_touch_cfg_t touch_cfg = {.disp = disp, .handle = touch};
    if (!touch || !lvgl_port_add_touch(&touch_cfg)) ESP_LOGE(TAG, "No GT911 touch controller; the screen runs without touch");
    return disp;
}

bool bsp_display_lock(uint32_t timeout_ms)
{
    return lvgl_port_lock(timeout_ms);
}

void bsp_display_unlock(void)
{
    lvgl_port_unlock();
}
