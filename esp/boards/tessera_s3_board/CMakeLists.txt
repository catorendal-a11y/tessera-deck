idf_component_register(
    SRCS "tessera_s3_board.c"
    INCLUDE_DIRS "include"
    REQUIRES esp_lcd
    PRIV_REQUIRES esp_driver_gpio esp_driver_i2c esp_driver_ledc
)
