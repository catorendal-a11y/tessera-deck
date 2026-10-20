#include <lvgl.h>
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <string>
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
static bool touching=false;static lv_point_t touch_at{};
static void touch_read(lv_indev_t*,lv_indev_data_t* data){data->point=touch_at;data->state=touching?LV_INDEV_STATE_PRESSED:LV_INDEV_STATE_RELEASED;}
static void tap(int x,int y){touch_at={x,y};touching=true;updates();touching=false;updates();}
static lv_obj_t* find(lv_obj_t* root,const char* text){if(lv_obj_check_type(root,&lv_label_class)&&!strcmp(lv_label_get_text(root),text))return root;for(uint32_t i=0;i<lv_obj_get_child_count(root);++i)if(auto* result=find(lv_obj_get_child(root,i),text))return result;return nullptr;}
int main(int argc,char** argv){const std::filesystem::path output=argc>1?argv[1]:".";std::filesystem::create_directories(output);lv_init();lv_tick_set_cb(millis);pixels.resize(1024*600*3);auto* display=lv_display_create(1024,600);lv_display_set_color_format(display,LV_COLOR_FORMAT_XRGB8888);alignas(64)static uint32_t buffer[1024*600];lv_display_set_buffers(display,buffer,nullptr,sizeof(buffer),LV_DISPLAY_RENDER_MODE_FULL);lv_display_set_flush_cb(display,flush);lv_tick_inc(tick);deck_model_init();
auto* touch=lv_indev_create();lv_indev_set_type(touch,LV_INDEV_TYPE_POINTER);lv_indev_set_read_cb(touch,touch_read);deck_model_note_host();
deck_button_t parsed[18]{};int count=0;assert(deck_model_buttons_from_json(R"({"buttons":[{"id":1,"label":"Build","icon":"lc:e064","color":"#35D07F","title":{"size":20,"position":"bottom","bold":true}},{"id":18,"label":"Folder","icon":"folder","color":"#FFA868"}]})",parsed,18,&count));assert(count==2);assert(deck_model_replace_buttons(parsed,count));deck_model_set_context("CODING","PROJECT",true);ui_init();updates();assert(find(lv_screen_active(),"TESSERA"));assert(find(lv_screen_active(),"PROFILE  CODING"));assert(find(lv_screen_active(),"<  PROJECT"));assert(find(lv_screen_active(),"Build"));char status[256];assert(ui_debug_visible_text(status,sizeof(status))==0);assert(strstr(status,"\"screen\":\"deck\""));
assert(find(lv_screen_active(),"PC CONNECTED")&&strstr(status,"\"pc\":true"));
{/* A touch on a dimmed panel only wakes it, even on a key; the next touch presses. */
const int before=deck_model_last_event_id();const uint32_t wake=deck_model_wake_sequence();deck_model_set_dimmed(true);
tap(94,168);assert(!deck_model_dimmed()&&deck_model_wake_sequence()==wake+1&&deck_model_last_event_id()==before);
tap(94,168);assert(deck_model_last_event_id()==before+1&&deck_model_wake_sequence()==wake+1);
deck_model_set_dimmed(true);tap(600,40);assert(!deck_model_dimmed()&&deck_model_wake_sequence()==wake+2&&deck_model_last_event_id()==before+1);
tap(600,40);assert(deck_model_wake_sequence()==wake+2);}
{/* A new label or status color updates the key in place: a rebuild would drop a touch in progress. */
deck_button_t live[18]{};int live_count=0;for(int n=0;n<deck_model_button_count();++n)deck_model_get_button(n,&live[live_count++]);
lv_obj_t* tile=find(lv_screen_active(),"Build");assert(tile);tile=lv_obj_get_parent(tile);
const uint32_t structure=deck_model_buttons_version();strcpy(live[0].label,"Build 14:33");live[0].color=0xFFB74D;
assert(deck_model_replace_buttons(live,live_count)&&deck_model_buttons_version()==structure);updates();
lv_obj_t* renamed=find(lv_screen_active(),"Build 14:33");assert(renamed&&lv_obj_get_parent(renamed)==tile&&!find(lv_screen_active(),"Build"));
const int before=deck_model_last_event_id();tap(94,168);deck_event_t event{};
assert(deck_model_events_since(before,&event,1)==1&&!strcmp(event.label,"Build 14:33"));
strcpy(live[0].label,"Build");live[0].color=0x35D07F;assert(deck_model_replace_buttons(live,live_count));updates();assert(find(lv_screen_active(),"Build"));}
{/* Confirmations queue in order instead of overwriting each other. */
int id=0;deck_feedback_t kind;deck_model_request_feedback(1,DECK_FEEDBACK_OK);deck_model_request_feedback(18,DECK_FEEDBACK_ALERT);
const uint32_t first=deck_model_take_feedback(&id,&kind);assert(first&&id==1&&kind==DECK_FEEDBACK_OK);
assert(deck_model_take_feedback(&id,&kind)==first+1&&id==18&&kind==DECK_FEEDBACK_ALERT);assert(!deck_model_take_feedback(&id,&kind));}
{/* Without host pings the header says so, and a press flashes red at once. */
tick+=4000;lv_tick_inc(4000);updates();assert(find(lv_screen_active(),"NO PC")&&!find(lv_screen_active(),"PC CONNECTED"));
const int before=deck_model_last_event_id();tap(94,168);assert(deck_model_last_event_id()==before+1);
deck_model_note_host();updates();assert(find(lv_screen_active(),"PC CONNECTED"));}
{deck_button_t g[3]{};int gc=0;
assert(deck_model_buttons_from_json(R"({"buttons":[{"id":1,"label":"CPU","icon":"ok","color":"#35D07F","gauge":{"p":45,"t":"45%"}},{"id":2,"label":"RAM","icon":"ok","color":"#35D07F","gauge":{"p":150,"t":"69%"}}]})",g,3,&gc));
assert(gc==2&&g[0].has_gauge&&g[0].gauge_percent==45&&g[1].gauge_percent==100);
assert(deck_model_replace_buttons(g,gc));updates();assert(find(lv_screen_active(),"45%"));
const uint32_t structure=deck_model_buttons_version(),live=deck_model_live_version();
g[0].gauge_percent=80;strcpy(g[0].gauge_text,"80%");g[0].color=0xFF7070;
assert(deck_model_replace_buttons(g,gc));
assert(deck_model_buttons_version()==structure&&deck_model_live_version()==live+1);
updates();assert(find(lv_screen_active(),"80%")&&!find(lv_screen_active(),"45%"));
assert(deck_model_replace_buttons(g,gc));assert(deck_model_live_version()==live+1);
g[0].has_gauge=false;assert(deck_model_replace_buttons(g,gc));assert(deck_model_buttons_version()==structure+1);
assert(!deck_model_buttons_from_json(R"({"buttons":[{"id":1,"label":"X","gauge":{"p":"no","t":"1"}}]})",g,3,&gc));
assert(deck_model_replace_buttons(parsed,count));updates();}
{deck_button_t s[18]{};const char* names[]={"CPU TEMP","CPU LOAD","CPU POWER","CPU CLOCK","RAM","DISK","GPU TEMP","GPU LOAD","GPU POWER","GPU CLOCK","VRAM","FAN","DOWN","UP","UPTIME","SENSORS","--"};
const char* texts[]={"58C","11%","72W","4.2G","69%","79%","81C","97%","301W","2.5G","12.1G","1450","8K","4K","4d","LIVE","--"};
const int pct[]={58,11,40,84,69,79,81,97,86,95,75,48,8,4,22,100,0};const uint32_t cols[]={0x35D07F,0x35D07F,0x35D07F,0x4DD0E1,0xFFB74D,0xFFB74D,0xFF7070,0xFF7070,0xFFB74D,0x4DD0E1,0xFFB74D,0x35D07F,0x64B5F6,0x64B5F6,0x90A4AE,0x35D07F,0x4A5A63};
for(int i=0;i<17;++i){s[i].id=i+1;snprintf(s[i].label,sizeof(s[i].label),"%s",names[i]);snprintf(s[i].icon,sizeof(s[i].icon),"ok");s[i].color=cols[i];s[i].has_gauge=true;s[i].gauge_percent=pct[i];snprintf(s[i].gauge_text,sizeof(s[i].gauge_text),"%s",texts[i]);}
s[17].id=18;snprintf(s[17].label,sizeof(s[17].label),"Home");snprintf(s[17].icon,sizeof(s[17].icon),"lc:e0f5");s[17].color=0x64B5F6;
assert(deck_model_replace_buttons(s,18));deck_model_set_context("MAIN","STATUS",true);capture(output/"gauges.ppm");}
if(argc>4){std::ifstream in(argv[2],std::ios::binary);std::string text((std::istreambuf_iterator<char>(in)),std::istreambuf_iterator<char>());deck_button_t custom[18]{};int custom_count=0;
assert(deck_model_buttons_from_json(text.c_str(),custom,18,&custom_count));assert(deck_model_replace_buttons(custom,custom_count));deck_model_set_context(argv[3],argv[4],argc>5);capture(output/"custom.ppm");}
char glyph[5];unsigned resolved=0;for(uint32_t code=DECK_LUCIDE_FIRST;code<=DECK_LUCIDE_LAST;++code){char name[16];snprintf(name,sizeof(name),"lc:%04x",code);if(deck_lucide_glyph(name,glyph))++resolved;}assert(resolved==DECK_LUCIDE_COUNT);capture(output/"deck.ppm");puts("Standalone Deck model, context and render checks passed.");}
