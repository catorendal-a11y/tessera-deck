cmake_minimum_required(VERSION 3.5)

set(EXTRA_COMPONENT_DIRS
    "${CMAKE_CURRENT_LIST_DIR}/components"
)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)

add_compile_options(-Wno-ignored-qualifiers)
add_compile_options(-Wno-attributes)

# One version for the firmware, the Windows host and the release packages.
file(STRINGS "${CMAKE_CURRENT_LIST_DIR}/VERSION" PROJECT_VER LIMIT_COUNT 1)

project(tessera)
