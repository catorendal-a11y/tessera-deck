cmake_minimum_required(VERSION 3.20)
project(tessera_native LANGUAGES C CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_C_STANDARD 11)
get_filename_component(ROOT "../.." ABSOLUTE)
set(LVGL "${ROOT}/managed_components/lvgl__lvgl")
file(GLOB_RECURSE LV_SOURCES "${LVGL}/src/*.c")
add_library(lvgl_native STATIC ${LV_SOURCES})
target_include_directories(lvgl_native PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}" "${LVGL}" "${LVGL}/include")
target_compile_definitions(lvgl_native PUBLIC LV_CONF_INCLUDE_SIMPLE=1 LV_USE_LZ4_INTERNAL=1)
add_executable(test_ui test_ui.cpp "${ROOT}/main/deck_model.c" "${ROOT}/main/deck_images.cpp"
  "${ROOT}/managed_components/espressif__cjson/cJSON/cJSON.c" "${ROOT}/main/ui/ui.cpp"
  "${ROOT}/main/ui/fonts/deck_lucide_60.c" "${ROOT}/main/ui/fonts/fq_dejavu_16.c"
  "${ROOT}/main/ui/fonts/fq_dejavu_20.c" "${ROOT}/main/ui/fonts/fq_dejavu_24.c"
  "${ROOT}/main/ui/fonts/fq_dejavu_28.c" "${ROOT}/main/ui/fonts/fq_dejavu_bold_20.c"
  "${ROOT}/main/ui/fonts/fq_dejavu_bold_24.c" "${ROOT}/main/ui/fonts/fq_dejavu_bold_28.c")
target_include_directories(test_ui PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}" "${ROOT}/main"
  "${ROOT}/managed_components/espressif__cjson/cJSON")
target_link_libraries(test_ui PRIVATE lvgl_native)
target_compile_options(test_ui PRIVATE -UNDEBUG)
