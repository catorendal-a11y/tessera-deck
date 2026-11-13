#include <lvgl.h>
#include <algorithm>
#include <cassert>
#include <cmath>
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
#include "ui/ui_palette.h"
#include "ui/icon_pack.h"

static uint32_t tick=10000;static std::vector<uint8_t> pixels;static unsigned flushes=0;
uint32_t millis(){return tick;}
extern "C" int64_t esp_timer_get_time(){return static_cast<int64_t>(tick)*1000;}
static const char *clock_text="14:32",*clock_meridiem="";
extern "C" const char* time_service_time_text(){return clock_text;}
extern "C" const char* time_service_meridiem(){return clock_meridiem;}
extern "C" const char* time_service_date_text(){return "Tue 20 Oct 2026";}
static void flush(lv_display_t* display,const lv_area_t* area,uint8_t* data){++flushes;const auto* source=reinterpret_cast<const uint32_t*>(data);int offset=0;for(int y=area->y1;y<=area->y2;++y)for(int x=area->x1;x<=area->x2;++x){const uint32_t v=source[offset++];const int at=(y*1024+x)*3;pixels[at]=v&255;pixels[at+1]=(v>>8)&255;pixels[at+2]=(v>>16)&255;}lv_display_flush_ready(display);}
static void step(uint32_t ms=40){lv_timer_handler();tick+=ms;lv_tick_inc(ms);}
static void updates(){for(int i=0;i<6;++i)step();lv_refr_now(nullptr);}
static std::filesystem::path output;
static void capture(const char* name){updates();std::ofstream out(output/name,std::ios::binary);out<<"P6\n1024 600\n255\n";assert(flushes);assert(*std::max_element(pixels.begin(),pixels.end())>128);for(size_t i=0;i<pixels.size();i+=3){out.put(pixels[i+2]);out.put(pixels[i+1]);out.put(pixels[i]);}}
static bool touching=false;static lv_point_t touch_at{};
static void touch_read(lv_indev_t*,lv_indev_data_t* data){data->point=touch_at;data->state=touching?LV_INDEV_STATE_PRESSED:LV_INDEV_STATE_RELEASED;}
static void tap(int x,int y){touch_at={x,y};touching=true;updates();touching=false;updates();}
/* Keeps a finger down for about `ms` and lifts it. */
static void hold(int x,int y,uint32_t ms){touch_at={x,y};touching=true;for(uint32_t t=0;t<ms;t+=40)step();touching=false;updates();}
/* A finger sliding from one point to another over ten reads. */
static void drag(int x0,int y0,int x1,int y1){touching=true;for(int s=0;s<=10;++s){touch_at={x0+(x1-x0)*s/10,y0+(y1-y0)*s/10};step();}touching=false;updates();}
static lv_obj_t* find(lv_obj_t* root,const char* text){if(lv_obj_check_type(root,&lv_label_class)&&!strcmp(lv_label_get_text(root),text))return root;for(uint32_t i=0;i<lv_obj_get_child_count(root);++i)if(auto* result=find(lv_obj_get_child(root,i),text))return result;return nullptr;}
static bool shown(lv_obj_t* object){for(;object;object=lv_obj_get_parent(object))if(lv_obj_has_flag(object,LV_OBJ_FLAG_HIDDEN))return false;return true;}
static bool visible(const char* text){auto* found=find(lv_screen_active(),text);return found&&shown(found);}
/* The next line for the host; the activity note a screen switch sends is skipped. */
static std::string taken(){char line[128]="";while(deck_model_take_line(line,sizeof(line)))if(strncmp(line,R"({"type":"view")",14))return line;return std::string();}
static char status[256];
static bool view_is(const char* name){char want[32];snprintf(want,sizeof(want),"\"view\":\"%s\"",name);return ui_debug_visible_text(status,sizeof(status))==0&&strstr(status,want);}
static lv_obj_t* arc_in(lv_obj_t* parent){for(uint32_t i=0;i<lv_obj_get_child_count(parent);++i)if(lv_obj_check_type(lv_obj_get_child(parent,i),&lv_arc_class))return lv_obj_get_child(parent,i);return nullptr;}
static bool bg_is(lv_obj_t* object,uint32_t rgb){return lv_color_eq(lv_obj_get_style_bg_color(object,LV_PART_MAIN),lv_color_hex(rgb));}
static int arcs_in(lv_obj_t* parent){int n=0;for(uint32_t i=0;i<lv_obj_get_child_count(parent);++i)n+=lv_obj_check_type(lv_obj_get_child(parent,i),&lv_arc_class);return n;}
/* Key slot centres: the keys start at (110, 72), 150 px apart across and 172 down. */
static int key_x(int id){return 110+((id-1)%6)*150+69;}
static int key_y(int id){return 72+((id-1)/6)*172+80;}
static void keep_host(uint32_t ms){for(uint32_t t=0;t<ms;t+=1000){deck_model_note_host();tick+=1000;lv_tick_inc(1000);updates();}}

static deck_button_t parsed[18]{};static int count=0;
static void saved_buttons(deck_button_t* out,int* n){*n=0;for(int i=0;i<deck_model_button_count();++i)deck_model_get_button(i,&out[(*n)++]);}

static double luminance(uint32_t rgb){
    auto channel=[](uint32_t v){const double c=v/255.0;return c<=0.03928?c/12.92:std::pow((c+0.055)/1.055,2.4);};
    return 0.2126*channel((rgb>>16)&255)+0.7152*channel((rgb>>8)&255)+0.0722*channel(rgb&255);}
static double contrast(uint32_t a,uint32_t b){const double x=luminance(a),y=luminance(b);return (std::max(x,y)+0.05)/(std::min(x,y)+0.05);}
static void test_text_contrast(){
    /* WCAG AA for body text: every text colour against every surface it is drawn on. */
    using namespace ui_palette;
    const struct{uint32_t ink,ground;}pairs[]={
     {Text,Bg},{Text,Card},{Text,RailBg},{Soft,Bg},{Soft,Card},{Soft,RailBg},{Soft,WarnBg},{Muted,Bg},{Muted,Card},{Muted,WarnBg},
     {Dim,Bg},{Dim,Card},{Dim,RailBg},{Amber,Bg},{Amber,Card},{Amber,WarnBg},{Amber,RailBg},{Accent,Card},{Cyan,Card}};
    for(const auto& pair:pairs){const double ratio=contrast(pair.ink,pair.ground);
        if(ratio<4.5){printf("contrast %06X on %06X is %.2f\n",pair.ink,pair.ground,ratio);assert(false);}}
}
static void test_keys_layout(){
    /* Keys: an even six-by-three deck; every key sits in the slot its id names, whatever order the host sends. */
    assert(deck_model_buttons_from_json(R"({"buttons":[
 {"id":4,"label":"New tab","icon":"lc:e13d","color":"#F2B94B","hold":true},{"id":2,"label":"Reopen tab","icon":"lc:e2a6","color":"#F2B94B"},
 {"id":9,"label":"DevTools","icon":"lc:e09b","color":"#F2B94B"},{"id":1,"label":"Close tab","icon":"lc:e1b2","color":"#A3B2BC"},
 {"id":3,"label":"Back","icon":"lc:e04a","color":"#64B5F6"},{"id":5,"label":"Reload","icon":"lc:e145","color":"#64B5F6"},
 {"id":6,"label":"CPU","icon":"ok","color":"#58E09B","gauge":{"p":45,"t":"45%"}},{"id":7,"label":"Folder","icon":"folder","color":"#FFA868"},
 {"id":18,"label":"Home","icon":"lc:e0f5","color":"#64B5F6"}]})",parsed,18,&count));
    assert(count==9&&parsed[0].has_hold&&!parsed[1].has_hold&&!parsed[0].confirm);
    {deck_button_t twice[1]{};int twice_count=0;assert(deck_model_buttons_from_json(R"({"buttons":[{"id":1,"label":"Tap","double":true}]})",twice,1,&twice_count)&&twice[0].has_double&&!twice[0].has_hold);}
    assert(deck_model_replace_buttons(parsed,count));deck_model_set_context("chrome","main",true);
    ui_set_firmware_version("9.8.7");ui_init();updates();
    assert(visible("<  Main")&&visible("Chrome")&&visible("New tab")&&visible("Home")&&visible("45%"));
    assert(view_is("keys")&&strstr(status,"\"screen\":\"deck\"")&&strstr(status,"\"pc\":true"));
    capture("keys.ppm");
}
static void test_titles(){
    /* The editor's text size, position and bold reach the panel; a hidden title is not drawn. */
    deck_button_t titled[3]{};int titled_count=0;
    assert(deck_model_buttons_from_json(R"({"buttons":[{"id":1,"label":"Top","icon":"lc:e13d","title":{"size":24,"position":"top","bold":true}},
 {"id":2,"label":"Middle","title":{"size":20,"position":"middle"}},{"id":3,"label":"Hidden","icon":"lc:e13d","title":{"position":"hidden"}}]})",titled,3,&titled_count));
    assert(titled_count==3&&titled[0].title_position==1&&titled[0].title_bold&&titled[0].title_size==24&&titled[1].title_position==2);
    assert(deck_model_replace_buttons(titled,titled_count));updates();
    assert(visible("Top")&&visible("Middle")&&!visible("Hidden"));capture("titles.ppm");
    assert(deck_model_replace_buttons(parsed,count));updates();
}
static void test_tap_lands_in_slot(){
    /* A tap lands on the key in that slot: id 4 is the fourth tile of the first row, id 1 the first. */
    int before=deck_model_last_event_id();tap(629,150);deck_event_t event{};
    assert(deck_model_events_since(before,&event,1)==1&&event.button_id==4&&!event.hold&&!strcmp(event.label,"New tab"));
    before=deck_model_last_event_id();tap(180,150);assert(deck_model_events_since(before,&event,1)==1&&event.button_id==1);
}
static void test_long_press_reports_hold(){
    /* A key with a hold action reports a hold past the long-press time, and nothing else. */
    const int before=deck_model_last_event_id();hold(key_x(4),key_y(4),700);deck_event_t events[2]{};
    assert(deck_model_events_since(before,events,2)==1&&events[0].button_id==4&&events[0].hold);
    /* A key without one still reports a single plain press however long it is held. */
    const int again=deck_model_last_event_id();hold(key_x(1),key_y(1),700);
    assert(deck_model_events_since(again,events,2)==1&&events[0].button_id==1&&!events[0].hold);
}
static void test_dimmed_touch_only_wakes(){
    /* A touch on a dimmed panel only wakes it, even on a key; the next touch presses. */
    const int before=deck_model_last_event_id();const uint32_t wake=deck_model_wake_sequence();deck_model_set_dimmed(true);
    tap(180,150);assert(!deck_model_dimmed()&&deck_model_wake_sequence()==wake+1&&deck_model_last_event_id()==before);
    tap(180,150);assert(deck_model_last_event_id()==before+1&&deck_model_wake_sequence()==wake+1);
}
static void test_pending_key_times_out(){
    /* A pressed key pulses until the host confirms; with no answer the pulse stops after ten seconds. */
    keep_host(1000);tap(key_x(2),key_y(2));
    auto* tile=lv_obj_get_parent(find(lv_screen_active(),"Reopen tab"));assert(tile&&lv_anim_get(tile,nullptr));
    keep_host(5000);assert(lv_anim_get(tile,nullptr));
    keep_host(6000);assert(!lv_anim_get(tile,nullptr)&&lv_obj_get_style_bg_opa(tile,LV_PART_MAIN)==LV_OPA_COVER);
    assert(lv_color_eq(lv_obj_get_style_bg_color(tile,LV_PART_MAIN),lv_color_hex(ui_palette::Card)));
}
static void test_live_update_in_place(){
    /* A new label or gauge value updates the key in place: a rebuild would drop a touch in progress. */
    deck_button_t live[18]{};int live_count=0;saved_buttons(live,&live_count);
    auto* ring=arc_in(lv_obj_get_parent(find(lv_screen_active(),"45%")));assert(ring&&lv_arc_get_value(ring)==45);  /* the gauge ring shows p */
    const uint32_t structure=deck_model_buttons_version();strcpy(live[0].label,"New tab 2");strcpy(live[6].gauge_text,"80%");live[6].gauge_percent=80;
    assert(deck_model_replace_buttons(live,live_count)&&deck_model_buttons_version()==structure);updates();
    assert(visible("New tab 2")&&visible("80%")&&!find(lv_screen_active(),"45%"));
    assert(arc_in(lv_obj_get_parent(find(lv_screen_active(),"80%")))==ring&&lv_arc_get_value(ring)==80);
}
static void test_wide_keys(){
    /* Wide keys: a media key three slots wide and a timer ring two slots wide; the slots they cover stay free of tiles. */
    deck_button_t saved[18]{};int saved_count=0;saved_buttons(saved,&saved_count);
    deck_button_t wide[18]{};int wide_count=0;
    assert(deck_model_buttons_from_json(R"({"buttons":[
 {"id":1,"label":"Midnight City","sub":"M83","icon":"lc:e12e","color":"#B388FF","span":3,"progress":38},
 {"id":4,"label":"04:56","sub":"Pomodoro","icon":"ok","color":"#FFB74D","span":2,"progress":80,"ring":true},
 {"id":6,"label":"Home","icon":"lc:e0f5","color":"#64B5F6"}]})",wide,18,&wide_count));
    assert(wide_count==3&&wide[0].span==3&&!strcmp(wide[0].sub,"M83")&&wide[0].has_progress&&wide[0].progress==38&&wide[1].ring&&wide[2].span==1);
    {deck_button_t refused[1]{};int refused_count=0;assert(!deck_model_buttons_from_json(R"({"buttons":[{"id":1,"label":"x","span":4}]})",refused,1,&refused_count));}
    assert(deck_model_replace_buttons(wide,3));updates();
    assert(visible("Midnight City")&&visible("M83")&&visible("04:56")&&visible("Pomodoro")&&visible("Home"));
    capture("wide.ppm");
    /* A new title, artist or progress updates in place: no rebuild while a finger may be on the key. */
    const uint32_t structure=deck_model_buttons_version();strcpy(wide[0].label,"Nightcall");strcpy(wide[0].sub,"Kavinsky");wide[0].progress=64;wide[1].progress=40;strcpy(wide[1].label,"02:00");
    assert(deck_model_replace_buttons(wide,3)&&deck_model_buttons_version()==structure);updates();
    assert(visible("Nightcall")&&visible("Kavinsky")&&visible("02:00")&&!find(lv_screen_active(),"Midnight City"));
    deck_model_replace_buttons(saved,saved_count);deck_model_note_host();updates();
}
/* cJSON recurses once per level on small task stacks: a deeply nested key in a pushed layout (which is also saved
 * and parsed again at boot) must be refused, while the protocol's real depth still parses. */
static void test_deep_nesting_refused(){
    deck_button_t keys[2]{};int n=0;
    assert(deck_model_buttons_from_json(R"({"buttons":[{"id":1,"label":"Top","title":{"size":24,"x":[[1]]}}]})",keys,2,&n)&&n==1);
    std::string deep=R"({"buttons":[{"id":1,"label":"x","junk":)";
    for(int i=0;i<64;++i)deep+='[';
    for(int i=0;i<64;++i)deep+=']';
    deep+="}]}";
    assert(!deck_model_buttons_from_json(deep.c_str(),keys,2,&n));
}
static void test_long_labels_stay_inside(){
    /* The longest label and second line the panel keeps end in dots on one line, inside their key. */
    deck_button_t saved[18]{};int saved_count=0;saved_buttons(saved,&saved_count);
    deck_button_t longest[2]{};int n=0;
    assert(deck_model_buttons_from_json(R"({"buttons":[{"id":1,"label":"WWWWWWWWWWWWWWWWWWWWWWWW","title":{"size":28,"bold":true}},
 {"id":2,"label":"WWWWWWWWWWWWWWWWWWWWWWWW","sub":"WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW","span":2,"progress":10}]})",longest,2,&n));
    assert(n==2&&deck_model_replace_buttons(longest,n));updates();
    int checked=0;
    std::vector<lv_obj_t*> stack{lv_screen_active()};
    while(!stack.empty()){auto* at=stack.back();stack.pop_back();for(uint32_t i=0;i<lv_obj_get_child_count(at);++i)stack.push_back(lv_obj_get_child(at,i));
        /* LONG_DOT writes the dots into the text, so the shown text is a shorter run of W ending in "..." */
        if(!lv_obj_check_type(at,&lv_label_class)||strncmp(lv_label_get_text(at),"WWW",3))continue;
        assert(strstr(lv_label_get_text(at),"..."));
        lv_area_t text,key;lv_obj_get_coords(at,&text);lv_obj_get_coords(lv_obj_get_parent(at),&key);
        const int line=lv_font_get_line_height(lv_obj_get_style_text_font(at,LV_PART_MAIN));
        assert(text.x1>=key.x1&&text.x2<=key.x2&&text.y1>=key.y1&&text.y2<=key.y2&&lv_area_get_height(&text)==line);++checked;}
    assert(checked==3);capture("long_labels.ppm");
    deck_model_replace_buttons(saved,saved_count);updates();
}
static void test_confirm_key(){
    /* "cf":1: a press needs a 600 ms hold while a ring fills; lifting the finger earlier sends nothing. */
    deck_button_t saved[18]{};int saved_count=0;saved_buttons(saved,&saved_count);
    deck_button_t keys[3]{};int n=0;
    assert(deck_model_buttons_from_json(R"({"buttons":[{"id":1,"label":"Shut down","cf":1},{"id":2,"label":"Also","cf":true},{"id":3,"label":"Plain","cf":0}]})",keys,3,&n));
    assert(n==3&&keys[0].confirm&&keys[1].confirm&&!keys[2].confirm);
    assert(deck_model_replace_buttons(keys,n));keep_host(1000);
    auto* tile=lv_obj_get_parent(find(lv_screen_active(),"Shut down"));assert(tile&&!arcs_in(tile));
    const int before=deck_model_last_event_id();
    tap(key_x(1),key_y(1));assert(deck_model_last_event_id()==before&&!arcs_in(tile));
    touch_at={key_x(1),key_y(1)};touching=true;for(int i=0;i<5;++i)step();
    assert(arcs_in(tile)==1&&deck_model_last_event_id()==before);capture("confirm.ppm");
    touching=true;for(int i=0;i<5;++i)step();
    deck_event_t event{};assert(deck_model_events_since(before,&event,1)==1&&event.button_id==1&&!event.hold&&!arcs_in(tile));
    touching=false;updates();assert(deck_model_last_event_id()==before+1);
    /* Sliding off the key before the ring is full cancels too. */
    touch_at={key_x(1),key_y(1)};touching=true;for(int i=0;i<4;++i)step();touch_at={key_x(5),key_y(5)};for(int i=0;i<12;++i)step();
    touching=false;updates();assert(deck_model_last_event_id()==before+1&&!arcs_in(tile));
    /* A plain key still presses on a tap. */
    tap(key_x(3),key_y(3));assert(deck_model_last_event_id()==before+2);
    deck_model_replace_buttons(saved,saved_count);updates();
}
static void test_swipe_goes_back(){
    /* No next or previous page exists: a swipe right asks for Back (the Keys line), a swipe left or up does nothing,
       and the key under the finger is not pressed. */
    keep_host(1000);while(!taken().empty()){}
    const int before=deck_model_last_event_id();
    drag(key_x(7),key_y(7),key_x(7)+400,key_y(7));assert(taken()==R"({"type":"rail","i":0})"&&taken().empty());
    drag(key_x(10),key_y(10),key_x(10)-400,key_y(10));assert(taken().empty());
    drag(key_x(8),key_y(8),key_x(8),key_y(8)-160);assert(taken().empty());
    assert(deck_model_last_event_id()==before&&view_is("keys"));
}
static void test_feedback_queue(){
    /* Confirmations queue in order instead of overwriting each other. */
    int id=0;deck_feedback_t kind;deck_model_request_feedback(1,DECK_FEEDBACK_OK);deck_model_request_feedback(18,DECK_FEEDBACK_ALERT);
    const uint32_t first=deck_model_take_feedback(&id,&kind);assert(first&&id==1&&kind==DECK_FEEDBACK_OK);
    assert(deck_model_take_feedback(&id,&kind)==first+1&&id==18&&kind==DECK_FEEDBACK_ALERT);assert(!deck_model_take_feedback(&id,&kind));
}
static void test_feedback_after_page_change(){
    /* A folder key's answer arrives after the page it opened: it must not flash the key now in that slot. */
    deck_button_t before[18]{};int before_count=0;saved_buttons(before,&before_count);
    keep_host(1000);ui_show_view(0);updates();tap(key_x(1),key_y(1));
    deck_button_t other{};other.id=1;strcpy(other.label,"Other page");other.color=0xA3B2BC;
    assert(deck_model_replace_buttons(&other,1));updates();auto* tile=lv_obj_get_parent(find(lv_screen_active(),"Other page"));
    deck_model_request_feedback(1,DECK_FEEDBACK_OK);updates();assert(tile&&!bg_is(tile,ui_palette::OkBg));
    /* Feedback nobody pressed for (the control API) still shows. */
    deck_model_request_feedback(1,DECK_FEEDBACK_OK);updates();assert(bg_is(tile,ui_palette::OkBg));
    assert(deck_model_replace_buttons(before,before_count));keep_host(1000);
}
static void test_host_disconnect_reconnect(){
    /* Without host pings the rail says NO PC, the cockpit screens say so, a key flashes red; pings bring it all back. */
    keep_host(1000);assert(!visible("NO PC"));tick+=4000;lv_tick_inc(4000);updates();
    assert(visible("NO PC")&&ui_debug_visible_text(status,sizeof(status))==0&&strstr(status,"\"pc\":false"));
    ui_show_view(1);updates();assert(visible("PC not connected")&&visible("Start Tessera on the PC, or check the USB cable"));
    ui_show_view(0);updates();
    const int before=deck_model_last_event_id();tap(key_x(1),key_y(1));assert(deck_model_last_event_id()==before+1);
    auto* tile=lv_obj_get_parent(find(lv_screen_active(),"Close tab"));
    assert(lv_color_eq(lv_obj_get_style_bg_color(tile,LV_PART_MAIN),lv_color_hex(ui_palette::AlertBg))&&!lv_anim_get(tile,nullptr));
    ui_show_view(1);deck_model_note_host();updates();
    assert(!visible("NO PC")&&!visible("Start Tessera on the PC, or check the USB cable")&&!visible("PC not connected"));
    assert(ui_debug_visible_text(status,sizeof(status))==0&&strstr(status,"\"pc\":true"));
    ui_show_view(0);updates();
}
static const char* const ThreeAgents=R"({"agents":[
 {"id":"claude","name":"Claude Code","state":"waiting","q":1,"text":"Wants to run: npm run build","sub":"tessera-deck-main"},
 {"id":"codex","name":"Codex","state":"working","text":"Editing host/win_input.py","sub":"tessera-deck-main"},
 {"id":"zcode","name":"ZCode","state":"idle","text":"Finished 14:05"}]})";
static void test_agents(){
    /* Agents: one lane each; a waiting agent offers Allow and Deny. */
    assert(deck_model_agents_from_json(ThreeAgents));
    tap(42,171);assert(view_is("agents"));
    assert(visible("Claude Code")&&visible("waiting for you")&&visible("Allow")&&visible("Deny")&&visible("Stop")&&visible("Open")&&visible("One needs you"));
    assert(!visible("New tab 2"));
    capture("agents.ppm");
}
static void test_agent_allow_deny(){
    /* Allow and Deny each go to the host as one line naming the agent; Stop on a working one too. */
    tap(912,145);assert(taken()==R"({"type":"agent","id":"claude","do":"allow"})"&&taken().empty());
    tap(912-144,145);assert(taken()==R"({"type":"agent","id":"claude","do":"deny"})"&&taken().empty());
    tap(912,145+160);assert(taken()==R"({"type":"agent","id":"codex","do":"stop"})"&&taken().empty());
    /* Without the PC nobody would hear the answer: nothing is sent. */
    tick+=4000;lv_tick_inc(4000);updates();tap(912,145);assert(taken().empty());deck_model_note_host();updates();
}
static void test_agent_tap_follows_its_lane(){
    /* A tap answers the agent its lane showed, even when the list changed before the lanes were redrawn. */
    keep_host(1000);while(!taken().empty()){}
    auto* allow=lv_obj_get_parent(find(lv_screen_active(),"Allow"));assert(allow);
    assert(deck_model_agents_from_json(R"({"agents":[{"id":"codex","name":"Codex","state":"working","text":"x"},{"id":"claude","name":"Claude Code","state":"waiting","q":1,"text":"y"}]})"));
    lv_obj_send_event(allow,LV_EVENT_CLICKED,nullptr);assert(taken()==R"({"type":"agent","id":"claude","do":"allow"})");
    assert(deck_model_agents_from_json(R"({"agents":[{"id":"claude","name":"Claude Code","state":"working","text":"y"}]})"));
    lv_obj_send_event(allow,LV_EVENT_CLICKED,nullptr);assert(taken().empty());  /* the question is gone: nothing to allow */
    assert(deck_model_agents_from_json(ThreeAgents));updates();
}
static void test_agent_questions(){
    /* A permission prompt is shown in full on up to three lines, and the host can bring the agents screen forward. */
    assert(deck_model_agents_from_json(R"({"agents":[{"id":"claude","name":"Claude Code","state":"waiting","q":1,"text":"Bash: python -m unittest discover -s tests && git status --short && git diff --stat HEAD~1 && echo finished-all-of-it-now-please-read","sub":"tessera-deck-main"}]})"));
    ui_show_view(0);deck_model_request_view(1);updates();assert(view_is("agents"));
    capture("question.ppm");
    assert(visible("Allow")&&visible("Deny"));
    /* A prompt that does not fit even in the smaller type offers Deny only; Claude then asks in its own dialog. */
    assert(deck_model_agents_from_json(R"({"agents":[{"id":"claude","name":"Claude Code","state":"waiting","q":1,"text":"Bash: WWWWWWWW WWWWWWWW WWWWWWWW WWWWWWWW WWWWWWWW WWWWWWWW WWWWWWWW WWWWWWWW WWWWWWWW WWWWWWWW WWWWWWWW WWWWWWWW WWWWWWWW WWWWWWWW WWWWWWWW WWWWWWWW","sub":""}]})"));
    updates();assert(visible("Deny")&&!visible("Allow"));
    assert(deck_model_agents_from_json(ThreeAgents));updates();
    assert(!deck_model_agents_from_json(R"({"agents":[{"id":"a\"b","name":"x"}]})"));
    assert(!deck_model_agents_from_json(R"({"agents":[{"id":"a","name":"x"},{"id":"b","name":"x"},{"id":"c","name":"x"},{"id":"d","name":"x"}]})"));
}
static void test_mixer(){
    /* Mixer: dragging a fader and tapping mute both tell the host which sound and what to do. */
    assert(deck_model_faders_from_json(R"({"faders":[
 {"id":"speaker","name":"Master","level":62,"color":"#58E09B"},{"id":"app:Spotify.exe","name":"Spotify","level":38,"color":"#B388FF"},
 {"id":"app:chrome.exe","name":"Chrome","level":80,"color":"#F2B94B"},{"id":"app:Discord.exe","name":"Discord","level":45,"muted":true,"color":"#7C8CF8"},
 {"id":"mic","name":"Mic","level":70,"mic":true,"color":"#4DD0E1"}]})"));
    ui_show_view(2);updates();assert(visible("Master")&&visible("62 %")&&visible("Muted")&&visible("Mic"));
    capture("mixer.ppm");
    tap(190,171);const std::string moved=taken();
    assert(moved.rfind(R"({"type":"fader","id":"speaker","level":7)",0)==0);while(!taken().empty()){}
    assert(!visible("62 %"));
    tap(191,523);assert(taken()==R"({"type":"mute","id":"speaker"})");
    assert(!deck_model_faders_from_json(R"({"faders":[{"id":"x","name":"x","color":"red"}]})"));
}
static void test_rail_shortcuts(){
    /* The rail: the host chooses the screens and adds shortcuts to a page; a shortcut tells the host and shows the keys. */
    assert(deck_model_rail_from_json(R"({"rail":[{"k":"keys"},{"k":"agents"},{"k":"status"},{"k":"page","i":"lc:e0e8","p":"Chrome","g":"main"},{"k":"page","i":"lc:e093","p":"coding","g":"main"}]})"));
    assert(!deck_model_rail_from_json(R"({"rail":[{"k":"weather"}]})")&&!deck_model_rail_from_json(R"({"rail":[{"k":"page","i":"lc:e0e8"}]})"));
    ui_show_view(1);updates();capture("rail.ppm");
    deck_model_note_host();  /* a shortcut does something only with the PC there */
    tap(42,84+3*60+27);
    assert(taken()==R"({"type":"rail","i":3})"&&taken().empty()&&view_is("keys"));
}
static void test_rail_back_after_shortcut(){
    /* Keys while the keys show (after a shortcut) asks the host to go back; from another screen it only switches. */
    tap(42,84+0*60+27);assert(taken()==R"({"type":"rail","i":0})"&&taken().empty());
    tap(42,84+2*60+27);assert(view_is("status"));
    tap(42,84+0*60+27);assert(taken().empty()&&view_is("keys"));
    /* A shortcut that runs steps tells the host and keeps the screen: here, status. */
    tap(42,84+2*60+27);
    assert(deck_model_rail_from_json(R"({"rail":[{"k":"keys"},{"k":"agents"},{"k":"status"},{"k":"act","i":"lc:e09e"}]})"));updates();
    tap(42,84+3*60+27);assert(taken()==R"({"type":"rail","i":3})"&&view_is("status"));
    tap(42,84+0*60+27);assert(taken().empty()&&view_is("keys"));
    tap(42,84+2*60+27);
    assert(deck_model_rail_from_json(R"({"rail":[{"k":"agents"}]})"));updates();
    tap(42,84+1*60+27);assert(view_is("agents"));
    assert(deck_model_rail_from_json(R"({"rail":[{"k":"keys"},{"k":"agents"},{"k":"mixer"},{"k":"status"}]})"));updates();ui_show_view(0);updates();
}
static void test_panel_lock(){
    /* AD_PANEL_LOCK 1: keys and the rail ignore taps; the logo becomes a lock badge, and only a 2 s hold on it
       unlocks the panel and tells the host. */
    keep_host(1000);while(!taken().empty()){}
    deck_model_set_locked(true);updates();capture("locked.ppm");
    const int before=deck_model_last_event_id();
    tap(key_x(1),key_y(1));hold(key_x(4),key_y(4),700);assert(deck_model_last_event_id()==before);
    tap(42,84+1*60+27);assert(view_is("keys"));
    drag(key_x(7),key_y(7),key_x(7)+400,key_y(7));assert(taken().empty());
    hold(42,41,1000);assert(deck_model_locked()&&taken().empty());
    hold(42,41,2200);assert(!deck_model_locked()&&taken()==R"({"type":"unlocked"})"&&taken().empty());
    updates();tap(key_x(1),key_y(1));assert(deck_model_last_event_id()==before+1);
}
static void test_lock_covers_agents_and_mixer(){
    /* A locked panel still shows a question, but Allow, the faders and mute do nothing until it is unlocked. */
    keep_host(1000);while(!taken().empty()){}
    deck_model_set_locked(true);ui_show_view(1);updates();assert(visible("Allow"));
    tap(912,145);tap(912-144,145);assert(taken().empty());
    ui_show_view(2);updates();tap(190,171);tap(191,523);assert(taken().empty());
    deck_model_set_locked(false);updates();tap(191,523);assert(taken()==R"({"type":"mute","id":"speaker"})");
    tap(191,523);while(!taken().empty()){}ui_show_view(0);updates();
}
static void test_about_sheet(){
    /* A long press on the logo opens a sheet with the firmware, the PC link and a brightness slider; a tap outside closes it. */
    keep_host(1000);tap(42,41);assert(!visible("Brightness"));
    hold(42,41,700);assert(visible("Tessera")&&visible("Firmware 9.8.7")&&visible("PC connected")&&visible("Brightness")&&visible("100 %"));
    capture("about.ppm");
    int level=0;bool save=false;while(deck_model_take_brightness_request(&level,&save)){}
    tap(330,250);assert(deck_model_take_brightness_request(&level,&save)&&save&&level>30&&level<70&&deck_model_brightness()==level);
    char shown_level[8];snprintf(shown_level,sizeof(shown_level),"%d %%",level);assert(visible(shown_level));
    const int before=deck_model_last_event_id();
    tap(key_x(12),key_y(12));assert(!visible("Brightness")&&deck_model_last_event_id()==before);
    /* A locked panel has no logo to hold. */
    deck_model_set_locked(true);updates();hold(42,41,700);assert(!visible("Brightness"));deck_model_set_locked(false);updates();
    while(!taken().empty()){}
}
static void test_status_screen(){
    /* Status: the PC's readings, and the first one over its limit is named in the heading. */
    assert(deck_model_stats_from_json(R"({"stats":[
 {"name":"CPU load","value":"3","unit":"%","p":3,"color":"#58E09B"},{"name":"CPU temp","value":"50","unit":"C","p":50,"color":"#58E09B"},
 {"name":"RAM","value":"55","unit":"%","p":55,"color":"#64B5F6"},{"name":"Disk","value":"90","unit":"%","p":90,"color":"#FFB74D","warn":true},
 {"name":"GPU load","value":"0","unit":"%","p":0,"color":"#B388FF"},{"name":"GPU temp","value":"31","unit":"C","p":31,"color":"#B388FF"},
 {"name":"VRAM","value":"14","unit":"%","p":14,"color":"#B388FF"},{"name":"Network","value":"244","unit":"KB/s","p":20,"color":"#A3B2BC"}]})"));
    ui_show_view(3);updates();assert(visible("CPU load")&&visible("Disk is high")&&visible("244")&&visible("KB/s"));
    capture("status.ppm");
    assert(deck_model_stats_from_json(R"({"stats":[{"name":"CPU load","value":"9","unit":"%","p":9}]})"));updates();assert(visible("9")&&visible("All good"));
    ui_show_view(0);updates();assert(visible("New tab 2"));
}
static void test_image_cache(){
    /* Image cache: animated frames are counted, the 8 MiB limit holds, least recently used images go first, referenced ones stay. */
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
    size_t bytes=0,cached=0;
    /* Each page shows one image: the layout trims the cache to 8 MiB, oldest first, as the host trims its record. */
    for(unsigned n=1;n<=40;++n){assert(upload(n,12)==std::string("AD_IMG_END OK ")+id_of(n));deck_image_keep({id_of(n)});deck_image_cache_stats(&bytes,&cached);assert(bytes<=8u*1024*1024);}
    assert(cached>=30&&cached<=33&&deck_image_get(id_of(40))&&!deck_image_get(id_of(1)));
    {/* A page reusing an old image plus a new one: the upload evicts nothing, the layout drops the oldest other. */
    const unsigned oldest=41-cached;assert(deck_image_get(id_of(oldest))&&deck_image_get(id_of(oldest+1)));
    assert(upload(50,12)==std::string("AD_IMG_END OK ")+id_of(50)&&deck_image_get(id_of(oldest)));
    deck_image_keep({id_of(50),id_of(oldest)});deck_image_cache_stats(&bytes,&cached);
    assert(bytes<=8u*1024*1024&&deck_image_get(id_of(oldest))&&deck_image_get(id_of(50))&&!deck_image_get(id_of(oldest+1)));}
    {/* Uploads alone may pass 8 MiB by one page; past that, with every image on screen, the panel says FULL. */
    std::vector<std::shared_ptr<const DeckImage>> held;for(unsigned n=1;n<=50;++n)if(auto image=deck_image_get(id_of(n)))held.push_back(image);
    std::string reply;unsigned n=100;while((reply=upload(n,12))!="AD_IMG_END FULL"){assert(reply==std::string("AD_IMG_END OK ")+id_of(n)&&n<200);if(auto image=deck_image_get(id_of(n)))held.push_back(image);++n;}
    deck_image_cache_stats(&bytes,&cached);assert(bytes>8u*1024*1024&&bytes<=8u*1024*1024+18u*72*72*4*12&&!deck_image_get(id_of(n)));
    held.clear();deck_image_keep({id_of(n-1)});deck_image_cache_stats(&bytes,&cached);assert(bytes<=8u*1024*1024&&deck_image_get(id_of(n-1)));
    /* Replacing a cached image keeps the size and count but still counts as a new image for a waiting key. */
    const size_t stable=bytes;for(int round=0;round<5;++round){const uint32_t gen=deck_image_generation();const size_t was=cached;assert(upload(n-1,12).rfind("AD_IMG_END OK",0)==0);deck_image_cache_stats(&bytes,&cached);assert(bytes==stable&&cached==was&&deck_image_generation()!=gen);}}
    assert(upload(41,1)==std::string("AD_IMG_END OK ")+id_of(41));
}
static void test_key_styling(){
    /* Styling: own colors replace the defaults; a bad color rejects the whole page. */
    deck_button_t styled[2]{};int styled_count=0;
    assert(deck_model_buttons_from_json(R"({"buttons":[{"id":1,"label":"Hot","bg":"#102030","text_color":"#FFAA00","border":"#00FF00"},{"id":2,"label":"Plain"}]})",styled,2,&styled_count));
    assert(styled_count==2&&styled[0].style==(DECK_STYLE_BG|DECK_STYLE_TEXT|DECK_STYLE_BORDER)&&styled[0].bg==0x102030&&styled[0].text==0xFFAA00&&styled[0].border==0x00FF00&&styled[1].style==0);
    assert(!deck_model_buttons_from_json(R"({"buttons":[{"id":1,"label":"Bad","bg":"red"}]})",styled,2,&styled_count));
}
static void test_ambient_clock(){
    /* Ambient clock: shown on request, rendered, and a touch returns to the deck and tells the host once. */
    deck_model_set_ambient("12 C, clear sky - Oslo");deck_model_request_screen(DECK_SCREEN_AMBIENT);updates();
    assert(deck_model_screen()==DECK_SCREEN_AMBIENT);capture("ambient.ppm");
    assert(ui_debug_visible_text(status,sizeof(status))==0&&strstr(status,"\"screen\":\"ambient\"")&&strstr(status,"\"weather\":\"lc:e178\""));
    /* Precipitation wins over cloud, and the place after " - " never picks the icon. */
    const char *const lines[][2]={{"3 C, Snow showers - Oslo","lc:e090"},{"8 C, Rain showers - Oslo","lc:e08e"},{"1 C, Freezing rain - Oslo","lc:e08e"},
        {"9 C, Light drizzle - Oslo","lc:e08a"},{"20 C, Thunderstorm with hail - Oslo","lc:e08c"},{"5 C, Rime fog - Oslo","lc:e214"},
        {"7 C, Partly cloudy - Oslo","lc:e216"},{"2 C, Clear night - Oslo","lc:e11e"},{"2 C, Partly cloudy night - Oslo","lc:e215"},{"7 C, Overcast - Snowflake","lc:e088"},{"7 C - Rainham","",}};
    for(const auto& line:lines){
        char want[40];snprintf(want,sizeof(want),"\"weather\":\"%s\"",line[1]);
        deck_model_set_ambient(line[0]);updates();
        assert(ui_debug_visible_text(status,sizeof(status))==0&&strstr(status,want));
    }
    deck_model_set_ambient("12 C, clear sky - Oslo");updates();
    /* 12-hour clocks with PM beside them, centred on the lit tiles: a leading "1" has empty outer columns. */
    const char *const twelve[][2]={{"2:32","ambient-12h.ppm"},{"10:49","ambient-12h-10.ppm"},{"12:59","ambient-12h-12.ppm"}};
    for(const auto& item:twelve){clock_text=item[0];clock_meridiem="PM";updates();capture(item[1]);}
    clock_text="14:32";clock_meridiem="";updates();
    tap(512,300);assert(deck_model_screen()==DECK_SCREEN_DECK&&deck_model_take_touch_return()&&!deck_model_take_touch_return());
    assert(ui_debug_visible_text(status,sizeof(status))==0&&strstr(status,"\"screen\":\"deck\""));
}
static void test_icon_pack(){
    char glyph[5];unsigned resolved=0;
    for(uint32_t code=DECK_LUCIDE_FIRST;code<=DECK_LUCIDE_LAST;++code){char name[16];snprintf(name,sizeof(name),"lc:%04x",code);if(deck_lucide_glyph(name,glyph))++resolved;}
    assert(resolved==DECK_LUCIDE_COUNT&&deck_lucide_glyph("lc:e10b",glyph));  /* the lock badge's glyph */
}

int main(int argc,char** argv){
    output=argc>1?argv[1]:".";std::filesystem::create_directories(output);
    lv_init();lv_tick_set_cb(millis);pixels.resize(1024*600*3);auto* display=lv_display_create(1024,600);
    lv_display_set_color_format(display,LV_COLOR_FORMAT_XRGB8888);alignas(64)static uint32_t buffer[1024*600];
    lv_display_set_buffers(display,buffer,nullptr,sizeof(buffer),LV_DISPLAY_RENDER_MODE_FULL);lv_display_set_flush_cb(display,flush);lv_tick_inc(tick);deck_model_init();
    auto* touch=lv_indev_create();lv_indev_set_type(touch,LV_INDEV_TYPE_POINTER);lv_indev_set_read_cb(touch,touch_read);deck_model_note_host();
    struct Test{const char* name;void(*run)();};
    const Test tests[]={
     {"text contrast",test_text_contrast},{"keys layout",test_keys_layout},{"titles",test_titles},
     {"tap lands in its slot",test_tap_lands_in_slot},{"long press reports a hold",test_long_press_reports_hold},
     {"a dimmed touch only wakes",test_dimmed_touch_only_wakes},{"pending key times out",test_pending_key_times_out},
     {"live update in place",test_live_update_in_place},{"wide keys",test_wide_keys},{"deep nesting refused",test_deep_nesting_refused},{"long labels stay inside",test_long_labels_stay_inside},
     {"confirm key",test_confirm_key},{"swipe goes back",test_swipe_goes_back},{"feedback queue",test_feedback_queue},
     {"feedback after a page change",test_feedback_after_page_change},
     {"host disconnect and reconnect",test_host_disconnect_reconnect},{"agents",test_agents},{"agent allow and deny",test_agent_allow_deny},
     {"agent tap follows its lane",test_agent_tap_follows_its_lane},
     {"agent questions",test_agent_questions},{"mixer",test_mixer},{"rail shortcuts",test_rail_shortcuts},
     {"rail back after a shortcut",test_rail_back_after_shortcut},{"panel lock",test_panel_lock},{"lock covers agents and mixer",test_lock_covers_agents_and_mixer},{"about sheet",test_about_sheet},
     {"status screen",test_status_screen},{"image cache",test_image_cache},{"key styling",test_key_styling},
     {"ambient clock",test_ambient_clock},{"icon pack",test_icon_pack}};
    for(const auto& test:tests){printf("- %s\n",test.name);fflush(stdout);test.run();}
    capture("deck.ppm");puts("Standalone Deck model, context and render checks passed.");
}
