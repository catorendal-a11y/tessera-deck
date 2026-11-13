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
#include "deck_images.h"
#include "deck_model.h"
#include "ui/ui.h"
#include "ui/icon_pack.h"

static uint32_t tick=10000;static std::vector<uint8_t> pixels;static unsigned flushes=0;
uint32_t millis(){return tick;}
extern "C" int64_t esp_timer_get_time(){return static_cast<int64_t>(tick)*1000;}
extern "C" const char* time_service_time_text(){return "14:32";}
extern "C" const char* time_service_date_text(){return "Tue 20 Oct 2026";}
static void flush(lv_display_t* display,const lv_area_t* area,uint8_t* data){++flushes;const auto* source=reinterpret_cast<const uint32_t*>(data);int offset=0;for(int y=area->y1;y<=area->y2;++y)for(int x=area->x1;x<=area->x2;++x){const uint32_t v=source[offset++];const int at=(y*1024+x)*3;pixels[at]=v&255;pixels[at+1]=(v>>8)&255;pixels[at+2]=(v>>16)&255;}lv_display_flush_ready(display);}
static void updates(){for(int i=0;i<6;++i){lv_timer_handler();tick+=40;lv_tick_inc(40);}lv_refr_now(nullptr);}
static void capture(const std::filesystem::path& path){updates();std::ofstream out(path,std::ios::binary);out<<"P6\n1024 600\n255\n";assert(flushes);assert(*std::max_element(pixels.begin(),pixels.end())>128);for(size_t i=0;i<pixels.size();i+=3){out.put(pixels[i+2]);out.put(pixels[i+1]);out.put(pixels[i]);}}
static bool touching=false;static lv_point_t touch_at{};
static void touch_read(lv_indev_t*,lv_indev_data_t* data){data->point=touch_at;data->state=touching?LV_INDEV_STATE_PRESSED:LV_INDEV_STATE_RELEASED;}
static void tap(int x,int y){touch_at={x,y};touching=true;updates();touching=false;updates();}
static lv_obj_t* find(lv_obj_t* root,const char* text){if(lv_obj_check_type(root,&lv_label_class)&&!strcmp(lv_label_get_text(root),text))return root;for(uint32_t i=0;i<lv_obj_get_child_count(root);++i)if(auto* result=find(lv_obj_get_child(root,i),text))return result;return nullptr;}
static bool shown(lv_obj_t* object){for(;object;object=lv_obj_get_parent(object))if(lv_obj_has_flag(object,LV_OBJ_FLAG_HIDDEN))return false;return true;}
static bool visible(const char* text){auto* found=find(lv_screen_active(),text);return found&&shown(found);}
static std::string taken(){char line[128]="";return deck_model_take_line(line,sizeof(line))?std::string(line):std::string();}
int main(int argc,char** argv){
const std::filesystem::path output=argc>1?argv[1]:".";std::filesystem::create_directories(output);
lv_init();lv_tick_set_cb(millis);pixels.resize(1024*600*3);auto* display=lv_display_create(1024,600);
lv_display_set_color_format(display,LV_COLOR_FORMAT_XRGB8888);alignas(64)static uint32_t buffer[1024*600];
lv_display_set_buffers(display,buffer,nullptr,sizeof(buffer),LV_DISPLAY_RENDER_MODE_FULL);lv_display_set_flush_cb(display,flush);lv_tick_inc(tick);deck_model_init();
auto* touch=lv_indev_create();lv_indev_set_type(touch,LV_INDEV_TYPE_POINTER);lv_indev_set_read_cb(touch,touch_read);deck_model_note_host();

/* Keys: an even six-by-three deck; every key sits in the slot its id names, whatever order the host sends. */
deck_button_t parsed[18]{};int count=0;
assert(deck_model_buttons_from_json(R"({"buttons":[
 {"id":4,"label":"New tab","icon":"lc:e13d","color":"#F2B94B","hold":true},{"id":2,"label":"Reopen tab","icon":"lc:e2a6","color":"#F2B94B"},
 {"id":9,"label":"DevTools","icon":"lc:e09b","color":"#F2B94B"},{"id":1,"label":"Close tab","icon":"lc:e1b2","color":"#A3B2BC"},
 {"id":3,"label":"Back","icon":"lc:e04a","color":"#64B5F6"},{"id":5,"label":"Reload","icon":"lc:e145","color":"#64B5F6"},
 {"id":6,"label":"CPU","icon":"ok","color":"#58E09B","gauge":{"p":45,"t":"45%"}},{"id":7,"label":"Folder","icon":"folder","color":"#FFA868"},
 {"id":18,"label":"Home","icon":"lc:e0f5","color":"#64B5F6"}]})",parsed,18,&count));
assert(count==9&&parsed[0].has_hold&&!parsed[1].has_hold);
{deck_button_t twice[1]{};int twice_count=0;assert(deck_model_buttons_from_json(R"({"buttons":[{"id":1,"label":"Tap","double":true}]})",twice,1,&twice_count)&&twice[0].has_double&&!twice[0].has_hold);}
assert(deck_model_replace_buttons(parsed,count));deck_model_set_context("chrome","main",true);ui_init();updates();
assert(visible("<  Main")&&visible("Chrome")&&visible("New tab")&&visible("Home")&&visible("45%"));
char status[256];assert(ui_debug_visible_text(status,sizeof(status))==0);
assert(strstr(status,"\"screen\":\"deck\"")&&strstr(status,"\"view\":\"keys\"")&&strstr(status,"\"pc\":true"));
capture(output/"keys.ppm");
{/* A tap lands on the key in that slot: id 4 is the fourth tile of the first row, id 1 the first. */
int before=deck_model_last_event_id();tap(629,150);deck_event_t event{};
assert(deck_model_events_since(before,&event,1)==1&&event.button_id==4&&!event.hold&&!strcmp(event.label,"New tab"));
before=deck_model_last_event_id();tap(180,150);assert(deck_model_events_since(before,&event,1)==1&&event.button_id==1);}
{/* A touch on a dimmed panel only wakes it, even on a key; the next touch presses. */
const int before=deck_model_last_event_id();const uint32_t wake=deck_model_wake_sequence();deck_model_set_dimmed(true);
tap(180,150);assert(!deck_model_dimmed()&&deck_model_wake_sequence()==wake+1&&deck_model_last_event_id()==before);
tap(180,150);assert(deck_model_last_event_id()==before+1&&deck_model_wake_sequence()==wake+1);}
{/* A new label or gauge value updates the key in place: a rebuild would drop a touch in progress. */
deck_button_t live[18]{};int live_count=0;for(int n=0;n<deck_model_button_count();++n)deck_model_get_button(n,&live[live_count++]);
const uint32_t structure=deck_model_buttons_version();strcpy(live[0].label,"New tab 2");strcpy(live[6].gauge_text,"80%");
assert(deck_model_replace_buttons(live,live_count)&&deck_model_buttons_version()==structure);updates();
assert(visible("New tab 2")&&visible("80%")&&!find(lv_screen_active(),"45%"));}
{/* Wide keys: a media key three slots wide and a timer ring two slots wide; the slots they cover stay free of tiles. */
deck_button_t saved[18]{};int saved_count=0;for(int n=0;n<deck_model_button_count();++n)deck_model_get_button(n,&saved[saved_count++]);
deck_button_t wide[18]{};int wide_count=0;
assert(deck_model_buttons_from_json(R"({"buttons":[
 {"id":1,"label":"Midnight City","sub":"M83","icon":"lc:e12e","color":"#B388FF","span":3,"progress":38},
 {"id":4,"label":"04:56","sub":"Pomodoro","icon":"ok","color":"#FFB74D","span":2,"progress":80,"ring":true},
 {"id":6,"label":"Home","icon":"lc:e0f5","color":"#64B5F6"}]})",wide,18,&wide_count));
assert(wide_count==3&&wide[0].span==3&&!strcmp(wide[0].sub,"M83")&&wide[0].has_progress&&wide[0].progress==38&&wide[1].ring&&wide[2].span==1);
{deck_button_t refused[1]{};int refused_count=0;assert(!deck_model_buttons_from_json(R"({"buttons":[{"id":1,"label":"x","span":4}]})",refused,1,&refused_count));}
const uint32_t before_wide=deck_model_buttons_version();
assert(deck_model_replace_buttons(wide,3));updates();
assert(visible("Midnight City")&&visible("M83")&&visible("04:56")&&visible("Pomodoro")&&visible("Home"));
capture(output/"wide.ppm");
{/* A new title, artist or progress updates in place: no rebuild while a finger may be on the key. */
const uint32_t structure=deck_model_buttons_version();strcpy(wide[0].label,"Nightcall");strcpy(wide[0].sub,"Kavinsky");wide[0].progress=64;wide[1].progress=40;strcpy(wide[1].label,"02:00");
assert(deck_model_replace_buttons(wide,3)&&deck_model_buttons_version()==structure);updates();
assert(visible("Nightcall")&&visible("Kavinsky")&&visible("02:00")&&!find(lv_screen_active(),"Midnight City"));}
(void)before_wide;
deck_model_replace_buttons(saved,saved_count);deck_model_note_host();updates();}
{/* Confirmations queue in order instead of overwriting each other. */
int id=0;deck_feedback_t kind;deck_model_request_feedback(1,DECK_FEEDBACK_OK);deck_model_request_feedback(18,DECK_FEEDBACK_ALERT);
const uint32_t first=deck_model_take_feedback(&id,&kind);assert(first&&id==1&&kind==DECK_FEEDBACK_OK);
assert(deck_model_take_feedback(&id,&kind)==first+1&&id==18&&kind==DECK_FEEDBACK_ALERT);assert(!deck_model_take_feedback(&id,&kind));}
{/* Without host pings the rail says so. */
assert(!visible("NO PC"));tick+=4000;lv_tick_inc(4000);updates();assert(visible("NO PC"));
deck_model_note_host();updates();assert(!visible("NO PC"));}

{/* Agents: one lane each; a waiting agent offers Allow and Deny, and the answer goes to the host as one line. */
assert(deck_model_agents_from_json(R"({"agents":[
 {"id":"claude","name":"Claude Code","state":"waiting","text":"Wants to run: npm run build","sub":"tessera-deck-main"},
 {"id":"codex","name":"Codex","state":"working","text":"Editing host/win_input.py","sub":"tessera-deck-main"},
 {"id":"zcode","name":"ZCode","state":"idle","text":"Finished 14:05"}]})"));
tap(42,171);assert(ui_debug_visible_text(status,sizeof(status))==0&&strstr(status,"\"view\":\"agents\""));
assert(visible("Claude Code")&&visible("waiting for you")&&visible("Allow")&&visible("Deny")&&visible("Stop")&&visible("Open")&&visible("One needs you"));
assert(!visible("New tab 2"));
capture(output/"agents.ppm");
tap(912,145);assert(taken()==R"({"type":"agent","id":"claude","do":"allow"})"&&taken().empty());
/* A permission prompt is shown in full on up to three lines, and the host can bring the agents screen forward. */
assert(deck_model_agents_from_json(R"({"agents":[{"id":"claude","name":"Claude Code","state":"waiting","text":"Bash: python -m unittest discover -s tests && git status --short && git diff --stat HEAD~1 && echo finished-all-of-it-now-please-read","sub":"tessera-deck-main"}]})"));
ui_show_view(0);deck_model_request_view(1);updates();assert(ui_debug_visible_text(status,sizeof(status))==0&&strstr(status,"\"view\":\"agents\""));
capture(output/"question.ppm");
assert(visible("Allow")&&visible("Deny"));
/* A prompt that does not fit even in the smaller type offers Deny only; Claude then asks in its own dialog. */
assert(deck_model_agents_from_json(R"({"agents":[{"id":"claude","name":"Claude Code","state":"waiting","text":"Bash: WWWWWWWW WWWWWWWW WWWWWWWW WWWWWWWW WWWWWWWW WWWWWWWW WWWWWWWW WWWWWWWW WWWWWWWW WWWWWWWW WWWWWWWW WWWWWWWW WWWWWWWW WWWWWWWW WWWWWWWW WWWWWWWW","sub":""}]})"));
updates();assert(visible("Deny")&&!visible("Allow"));
assert(deck_model_agents_from_json(R"({"agents":[
 {"id":"claude","name":"Claude Code","state":"waiting","text":"Wants to run: npm run build","sub":"tessera-deck-main"},
 {"id":"codex","name":"Codex","state":"working","text":"Editing host/win_input.py","sub":"tessera-deck-main"},
 {"id":"zcode","name":"ZCode","state":"idle","text":"Finished 14:05"}]})"));updates();
assert(!deck_model_agents_from_json(R"({"agents":[{"id":"a\"b","name":"x"}]})"));
assert(!deck_model_agents_from_json(R"({"agents":[{"id":"a","name":"x"},{"id":"b","name":"x"},{"id":"c","name":"x"},{"id":"d","name":"x"}]})"));}

{/* Mixer: dragging a fader and tapping mute both tell the host which sound and what to do. */
assert(deck_model_faders_from_json(R"({"faders":[
 {"id":"speaker","name":"Master","level":62,"color":"#58E09B"},{"id":"app:Spotify.exe","name":"Spotify","level":38,"color":"#B388FF"},
 {"id":"app:chrome.exe","name":"Chrome","level":80,"color":"#F2B94B"},{"id":"app:Discord.exe","name":"Discord","level":45,"muted":true,"color":"#7C8CF8"},
 {"id":"mic","name":"Mic","level":70,"mic":true,"color":"#4DD0E1"}]})"));
ui_show_view(2);updates();assert(visible("Master")&&visible("62 %")&&visible("Muted")&&visible("Mic"));
capture(output/"mixer.ppm");
tap(190,171);const std::string moved=taken();
assert(moved.rfind(R"({"type":"fader","id":"speaker","level":7)",0)==0);while(!taken().empty()){}
assert(!visible("62 %"));
tap(191,523);assert(taken()==R"({"type":"mute","id":"speaker"})");
assert(!deck_model_faders_from_json(R"({"faders":[{"id":"x","name":"x","color":"red"}]})"));}

{/* The rail: the host chooses the screens and adds shortcuts to a page; a shortcut tells the host and shows the keys. */
assert(deck_model_rail_from_json(R"({"rail":[{"k":"keys"},{"k":"agents"},{"k":"status"},{"k":"page","i":"lc:e0e8","p":"Chrome","g":"main"},{"k":"page","i":"lc:e093","p":"coding","g":"main"}]})"));
assert(!deck_model_rail_from_json(R"({"rail":[{"k":"weather"}]})")&&!deck_model_rail_from_json(R"({"rail":[{"k":"page","i":"lc:e0e8"}]})"));
ui_show_view(1);updates();capture(output/"rail.ppm");
tap(42,84+3*60+27);
assert(taken()==R"({"type":"rail","i":3})"&&taken().empty());
assert(ui_debug_visible_text(status,sizeof(status))==0&&strstr(status,"\"view\":\"keys\""));
tap(42,84+2*60+27);assert(ui_debug_visible_text(status,sizeof(status))==0&&strstr(status,"\"view\":\"status\""));
assert(deck_model_rail_from_json(R"({"rail":[{"k":"agents"}]})"));updates();
tap(42,84+1*60+27);assert(ui_debug_visible_text(status,sizeof(status))==0&&strstr(status,"\"view\":\"agents\""));
assert(deck_model_rail_from_json(R"({"rail":[{"k":"keys"},{"k":"agents"},{"k":"mixer"},{"k":"status"}]})"));updates();ui_show_view(0);updates();}
{/* Status: the PC's readings, and the first one over its limit is named in the heading. */
assert(deck_model_stats_from_json(R"({"stats":[
 {"name":"CPU load","value":"3","unit":"%","p":3,"color":"#58E09B"},{"name":"CPU temp","value":"50","unit":"C","p":50,"color":"#58E09B"},
 {"name":"RAM","value":"55","unit":"%","p":55,"color":"#64B5F6"},{"name":"Disk","value":"90","unit":"%","p":90,"color":"#FFB74D","warn":true},
 {"name":"GPU load","value":"0","unit":"%","p":0,"color":"#B388FF"},{"name":"GPU temp","value":"31","unit":"C","p":31,"color":"#B388FF"},
 {"name":"VRAM","value":"14","unit":"%","p":14,"color":"#B388FF"},{"name":"Network","value":"244","unit":"KB/s","p":20,"color":"#A3B2BC"}]})"));
ui_show_view(3);updates();assert(visible("CPU load")&&visible("Disk is high")&&visible("244")&&visible("KB/s"));
capture(output/"status.ppm");
assert(deck_model_stats_from_json(R"({"stats":[{"name":"CPU load","value":"9","unit":"%","p":9}]})"));updates();assert(visible("9")&&visible("All good"));
ui_show_view(0);updates();assert(visible("New tab 2"));}
{/* Image cache: animated frames are counted, the 8 MiB limit holds, least recently used images go first, referenced ones stay. */
auto upload=[&](unsigned n,int frames)->std::string{
std::vector<uint8_t> blob={'A','D','I','1',72,72,static_cast<uint8_t>(frames)};
for(int f=0;f<frames;++f){std::vector<uint8_t> runs;int left=72*72;while(left>0){const int run=left>255?255:left;runs.push_back(static_cast<uint8_t>(run));runs.push_back(static_cast<uint8_t>(n));runs.push_back(static_cast<uint8_t>(f));runs.push_back(7);runs.push_back(255);left-=run;}
blob.push_back(100);blob.push_back(0);const uint32_t len=runs.size();for(int i=0;i<4;++i)blob.push_back((len>>(8*i))&255);blob.insert(blob.end(),runs.begin(),runs.end());}
uint32_t c=~0u;for(auto b:blob){c^=b;for(int k=0;k<8;++k)c=(c>>1)^(0xedb88320u&(0u-(c&1)));}c=~c;
char id[32];snprintf(id,sizeof id,"im:%012x",n);std::string reply;
deck_image_command((std::string("AD_IMG_BEGIN ")+id+" "+std::to_string(blob.size())+" "+std::to_string(c)).c_str(),reply);
for(size_t at=0;at<blob.size();at+=300){std::string hexed;for(size_t i=at;i<blob.size()&&i<at+300;++i){char two[3];snprintf(two,3,"%02x",blob[i]);hexed+=two;}deck_image_command(("AD_IMG_DATA "+std::to_string(at)+" "+hexed).c_str(),reply);}
reply.clear();deck_image_command("AD_IMG_END",reply);return reply;};
auto id_of=[](unsigned n){static char buffer[4][32];static int slot=0;char* id=buffer[slot++&3];snprintf(id,32,"im:%012x",n);return static_cast<const char*>(id);};
size_t bytes=0,count=0;
for(unsigned n=1;n<=40;++n){assert(upload(n,12)==std::string("AD_IMG_END OK ")+id_of(n));deck_image_cache_stats(&bytes,&count);assert(bytes<=8u*1024*1024);}
assert(count>=30&&count<=33&&deck_image_get(id_of(40))&&!deck_image_get(id_of(1)));
{std::vector<std::shared_ptr<const DeckImage>> shown;for(unsigned n=40;n>=1&&shown.size()<count;--n)if(auto image=deck_image_get(id_of(n)))shown.push_back(image);
const size_t before=bytes;assert(upload(99,12)=="AD_IMG_END FULL");deck_image_cache_stats(&bytes,&count);assert(bytes==before&&!deck_image_get(id_of(99)));}
const size_t stable=bytes;for(int round=0;round<5;++round){assert(upload(40,12).rfind("AD_IMG_END OK",0)==0);deck_image_cache_stats(&bytes,&count);assert(bytes==stable);}
assert(upload(41,1)==std::string("AD_IMG_END OK ")+id_of(41));}
{/* Styling: own colors replace the defaults; a bad color rejects the whole page. */
deck_button_t styled[2]{};int styled_count=0;
assert(deck_model_buttons_from_json(R"({"buttons":[{"id":1,"label":"Hot","bg":"#102030","text_color":"#FFAA00","border":"#00FF00"},{"id":2,"label":"Plain"}]})",styled,2,&styled_count));
assert(styled_count==2&&styled[0].style==(DECK_STYLE_BG|DECK_STYLE_TEXT|DECK_STYLE_BORDER)&&styled[0].bg==0x102030&&styled[0].text==0xFFAA00&&styled[0].border==0x00FF00&&styled[1].style==0);
assert(!deck_model_buttons_from_json(R"({"buttons":[{"id":1,"label":"Bad","bg":"red"}]})",styled,2,&styled_count));}
{/* Ambient clock: shown on request, rendered, and a touch returns to the deck and tells the host once. */
deck_model_set_ambient("12 C, clear sky - Oslo");deck_model_request_screen(DECK_SCREEN_AMBIENT);updates();
assert(deck_model_screen()==DECK_SCREEN_AMBIENT);capture(output/"ambient.ppm");
char shown[256];assert(ui_debug_visible_text(shown,sizeof(shown))==0&&strstr(shown,"\"screen\":\"ambient\""));
tap(512,300);assert(deck_model_screen()==DECK_SCREEN_DECK&&deck_model_take_touch_return()&&!deck_model_take_touch_return());
assert(ui_debug_visible_text(shown,sizeof(shown))==0&&strstr(shown,"\"screen\":\"deck\""));}
char glyph[5];unsigned resolved=0;for(uint32_t code=DECK_LUCIDE_FIRST;code<=DECK_LUCIDE_LAST;++code){char name[16];snprintf(name,sizeof(name),"lc:%04x",code);if(deck_lucide_glyph(name,glyph))++resolved;}assert(resolved==DECK_LUCIDE_COUNT);capture(output/"deck.ppm");puts("Standalone Deck model, context and render checks passed.");}
