idf_build_get_property(target IDF_TARGET)
if(target STREQUAL "esp32s3")
    set(board tessera_s3_board)
else()
    set(board espressif__esp32_p4_function_ev_board)
endif()

idf_component_register(
    SRCS
        "main.cpp"
        "time_service.c"
        "deck_model.c"
        "deck_images.cpp"
        "ui/ui.cpp"
        "ui/fonts/deck_lucide_60.c"
        "ui/fonts/fq_dejavu_16.c"
        "ui/fonts/fq_dejavu_20.c"
        "ui/fonts/fq_dejavu_24.c"
        "ui/fonts/fq_dejavu_28.c"
        "ui/fonts/fq_dejavu_bold_20.c"
        "ui/fonts/fq_dejavu_bold_24.c"
        "ui/fonts/fq_dejavu_bold_28.c"
        "ui/fonts/fq_dejavu_bold_40.c"
    INCLUDE_DIRS
        "."
        "ui"
        "compat"
        "../managed_components/lvgl__lvgl"
    REQUIRES
        ${board}
        lvgl__lvgl
        espressif__cjson
        esp_timer
        esp_app_format
        nvs_flash
        mbedtls
        bootloader_support
        app_update
        spiffs
        esp_driver_usb_serial_jtag
        esp_driver_uart
)

# The USB console's "is a host connected?" goes through main.cpp, which does not believe a millisecond of "no".
if(NOT CONFIG_ESP_CONSOLE_UART)
    target_link_libraries(${COMPONENT_LIB} INTERFACE "-Wl,--wrap=usb_serial_jtag_is_connected")
endif()

