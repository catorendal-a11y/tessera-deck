#include <lvgl.h>
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <vector>
#include "deck_model.h"
#include "ui/ui.h"
#include "ui/icon_pack.h"

static uint32_t tick=10000;static std::vector<uint8_t> pixels;static unsigned flushes=0;
uint32_t millis(){return tick;}
extern "C" int64_t esp_timer_get_time(){return static_cast<int64_t>(tick)*1000;}
extern "C" const char* time_service_time_text(){return "14:32";}
static void flush(lv_display_t* display,const lv_area_t* area,uint8_t* data){++flushes;const auto* source=reinterpret_cast<const uint32_t*>(data);int offset=0;for(int y=area->y1;y<=area->y2;++y)for(int x=area->x1;x<=area->x2;++x){const uint32_t v=source[offset++];const int at=(y*1024+x)*3;pixels[at]=v&255;pixels[at+1]=(v>>8)&255;pixels[at+2]=(v>>16)&255;}lv_display_flush_ready(display);}
static void updates(){for(int i=0;i<6;++i){lv_timer_handler();tick+=40;lv_tick_inc(40);}lv_refr_now(nullptr);}
static void capture(const std::filesystem::path& path){updates();std::ofstream out(path,std::ios::binary);out<<"P6\n1024 600\n255\n";assert(flushes);assert(*std::max_element(pixels.begin(),pixels.end())>128);for(size_t i=0;i<pixels.size();i+=3){out.put(pixels[i+2]);out.put(pixels[i+1]);out.put(pixels[i]);}}
static lv_obj_t* find(lv_obj_t* root,const char* text){if(lv_obj_check_type(root,&lv_label_class)&&!strcmp(lv_label_get_text(root),text))return root;for(uint32_t i=0;i<lv_obj_get_child_count(root);++i)if(auto* result=find(lv_obj_get_child(root,i),text))return result;return nullptr;}
int main(int argc,char** argv){const std::filesystem::path output=argc>1?argv[1]:".";std::filesystem::create_directories(output);lv_init();lv_tick_set_cb(millis);pixels.resize(1024*600*3);auto* display=lv_display_create(1024,600);lv_display_set_color_format(display,LV_COLOR_FORMAT_XRGB8888);alignas(64)static uint32_t buffer[1024*600];lv_display_set_buffers(display,buffer,nullptr,sizeof(buffer),LV_DISPLAY_RENDER_MODE_FULL);lv_display_set_flush_cb(display,flush);lv_tick_inc(tick);deck_model_init();
deck_button_t parsed[18]{};int count=0;assert(deck_model_buttons_from_json(R"({"buttons":[{"id":1,"label":"Bygg","icon":"lc:e064","color":"#35D07F","title":{"size":20,"position":"bottom","bold":true}},{"id":18,"label":"Mappe","icon":"folder","color":"#FFA868"}]})",parsed,18,&count));assert(count==2);assert(deck_model_replace_buttons(parsed,count));deck_model_set_context("KODING","PROSJEKT",true);ui_init();updates();assert(find(lv_screen_active(),"AGENT DECK"));assert(find(lv_screen_active(),"PROFIL  KODING"));assert(find(lv_screen_active(),"<  PROSJEKT"));assert(find(lv_screen_active(),"Bygg"));char status[256];assert(ui_debug_visible_text(status,sizeof(status))==0);assert(strstr(status,"\"screen\":\"deck\""));
char glyph[5];unsigned resolved=0;for(uint32_t code=DECK_LUCIDE_FIRST;code<=DECK_LUCIDE_LAST;++code){char name[16];snprintf(name,sizeof(name),"lc:%04x",code);if(deck_lucide_glyph(name,glyph))++resolved;}assert(resolved==DECK_LUCIDE_COUNT);capture(output/"deck.ppm");puts("Standalone Deck model, context and render checks passed.");}
