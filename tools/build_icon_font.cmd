@echo off
setlocal
cd /d "%~dp0.."
call npx --yes --package lv_font_conv@1.5.3 lv_font_conv --font vendor/lucide/lucide.ttf --size 60 --bpp 4 --format lvgl --range 0xe038-0xe7b1 --no-kerning --lv-include lvgl.h --lv-font-name deck_lucide_60 -o main/ui/fonts/deck_lucide_60.c
if errorlevel 1 exit /b %errorlevel%
py -3 tools/stamp_icon_font.py
exit /b %errorlevel%
