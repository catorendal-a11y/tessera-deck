idf_build_get_property(target IDF_TARGET)
if(target STREQUAL "esp32s3")
    set(board tessera_s3_board)
else()
    set(board espressif__esp32_p4_function_ev_board)
endif()

set(srcs
    "main.cpp"
    "time_service.c"
    "deck_model.c"
    "deck_ha.c"
    "wifi_config.c"
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
)
set(requires
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
# Wi-Fi and the Home Assistant API go through the ESP32-C6 of the GUITION board (CONFIG_TESSERA_WIFI, see
# Kconfig.projbuild). The other boards build without them. The hosted Wi-Fi components exist only for the P4
# (idf_component.yml), and requirements cannot depend on sdkconfig, so they follow the target.
if(CONFIG_TESSERA_WIFI)
    list(APPEND srcs
        "wifi_service.c"
        "api/api_proto.c"
        "api/api_messages.c"
        "api/api_crypto.c"
        "api/api_noise.c"
        "api/api_session.c"
        "api/api_entities.c"
        "api/api_ha.c"
        "api/api_server.c"
        "api/api_mdns.c"
        "api/press_router.c"
    )
endif()
if(target STREQUAL "esp32p4")
    list(APPEND requires
        esp_wifi
        esp_netif
        esp_event
        espressif__esp_wifi_remote
        espressif__esp_hosted
        espressif__mdns
        lwip
    )
endif()

idf_component_register(
    SRCS ${srcs}
    INCLUDE_DIRS
        "."
        "ui"
        "api"
        "compat"
        "../managed_components/lvgl__lvgl"
    REQUIRES ${requires}
)
