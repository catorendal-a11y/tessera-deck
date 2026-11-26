cmake_minimum_required(VERSION 3.5)

set(EXTRA_COMPONENT_DIRS
    "${CMAKE_CURRENT_LIST_DIR}/components"
)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)

# The ESP32-S3 boards (boards/*.defaults) use boards/tessera_s3_board in place of the P4 board support,
# and keep their own lock file so an S3 build never rewrites the P4 one.
if(IDF_TARGET STREQUAL "esp32s3")
    list(APPEND EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_LIST_DIR}/boards/tessera_s3_board")
    set(EXCLUDE_COMPONENTS espressif__esp32_p4_function_ev_board)
    idf_build_set_property(DEPENDENCIES_LOCK dependencies.lock.esp32s3)
endif()

add_compile_options(-Wno-ignored-qualifiers)
add_compile_options(-Wno-attributes)

# One version (../VERSION) for the firmware, the Windows host and the release packages.
file(STRINGS "${CMAKE_CURRENT_LIST_DIR}/../VERSION" PROJECT_VER LIMIT_COUNT 1)
# A new VERSION must reconfigure the build, or the firmware keeps reporting the old number.
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${CMAKE_CURRENT_LIST_DIR}/../VERSION")

project(tessera)
