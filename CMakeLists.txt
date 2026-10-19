cmake_minimum_required(VERSION 3.5)

set(EXTRA_COMPONENT_DIRS
    "${CMAKE_CURRENT_LIST_DIR}/components"
)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)

add_compile_options(-Wno-ignored-qualifiers)
add_compile_options(-Wno-attributes)

project(agent_deck)
