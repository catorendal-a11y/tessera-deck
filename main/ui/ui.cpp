// Standalone full-screen Tessera UI.
#include "ui.h"
#include "icon_pack.h"
#include "deck_images.h"
#include "deck_model.h"
#include "time_service.h"
#include <Arduino.h>
#include <cstdio>
#include <cstring>
#include <memory>
#include <lvgl.h>
#include "src/misc/cache/instance/lv_image_cache.h"

extern const lv_font_t fq_font_dejavu_16;
extern const lv_font_t fq_font_dejavu_20;
extern const lv_font_t fq_font_dejavu_24;
extern const lv_font_t fq_font_dejavu_28;
extern const lv_font_t fq_font_dejavu_bold_20;
extern const lv_font_t fq_font_dejavu_bold_24;
extern const lv_font_t fq_font_dejavu_bold_28;

namespace {
constexpr int W=1024,H=600,Header=76,Cell=150,Gap=17,X=19,Y=17;
constexpr uint32_t Bg=0x091014,HeaderBg=0x101A1F,Surface=0x172329;
constexpr uint32_t Border=0x31444D,Text=0xE8F4EF,Muted=0x78909A,Accent=0x58E09B;
constexpr uint32_t PressedBg=0x254E3B,OkBg=0x1E6042,AlertBg=0x6E2633,Amber=0xFFB74D;
/* The host pings every second; three missed pings mean nobody runs the keys. */
constexpr int64_t HostTimeoutMs=3500;
/* A pressed key stays highlighted until the host confirms it. Long multi-step
 * actions confirm late, so the highlight only gives up after this long. */
constexpr uint32_t PendingMs=10000;
lv_obj_t *screen=nullptr,*grid=nullptr,*profile_label=nullptr,*page_label=nullptr,*clock_label=nullptr;
lv_obj_t *link_pill=nullptr,*link_dot=nullptr,*link_label=nullptr;
int link_shown=-1;
lv_obj_t *keys[DECK_MAX_BUTTONS]{};
int ids[DECK_MAX_BUTTONS]{};
uint32_t button_version=0,live_version=0,context_version=0;
lv_obj_t *gauge_arc[DECK_MAX_BUTTONS]{},*gauge_value[DECK_MAX_BUTTONS]{};
uint32_t flash_until[DECK_MAX_BUTTONS]{};

struct ImageTile {
    std::shared_ptr<const DeckImage> image;
    lv_obj_t *widget=nullptr;
    lv_image_dsc_t descriptor{};
    uint32_t due=0;
    size_t frame=0;
};
ImageTile images[DECK_MAX_BUTTONS];

void flat(lv_obj_t *object,uint32_t color) {
    lv_obj_set_style_bg_color(object,lv_color_hex(color),0);
    lv_obj_set_style_bg_opa(object,LV_OPA_COVER,0);
    lv_obj_set_style_border_width(object,0,0);lv_obj_set_style_pad_all(object,0,0);
    lv_obj_set_style_shadow_width(object,0,0);lv_obj_set_scrollable(object,false);
}
lv_obj_t *label(lv_obj_t *parent,const char *value,int x,int y,int width,const lv_font_t *font,uint32_t color) {
    auto *result=lv_label_create(parent);lv_obj_set_pos(result,x,y);lv_obj_set_width(result,width);
    lv_label_set_text(result,value);lv_label_set_long_mode(result,LV_LABEL_LONG_DOT);
    lv_obj_set_style_text_font(result,font,0);lv_obj_set_style_text_color(result,lv_color_hex(color),0);
    return result;
}
const char *fallback_icon(const char *name) {
    struct Entry{const char *name,*symbol;};
    static const Entry values[]={
      {"ok",LV_SYMBOL_OK},{"close",LV_SYMBOL_CLOSE},{"settings",LV_SYMBOL_SETTINGS},
      {"home",LV_SYMBOL_HOME},{"folder",LV_SYMBOL_DIRECTORY},{"download",LV_SYMBOL_DOWNLOAD},
      {"refresh",LV_SYMBOL_REFRESH},{"play",LV_SYMBOL_PLAY},{"pause",LV_SYMBOL_PAUSE},
      {"stop",LV_SYMBOL_STOP},{"plus",LV_SYMBOL_PLUS},{"minus",LV_SYMBOL_MINUS},
      {"loop",LV_SYMBOL_LOOP},{"list",LV_SYMBOL_LIST},{"upload",LV_SYMBOL_UPLOAD},
      {"bolt",LV_SYMBOL_CHARGE},{"bell",LV_SYMBOL_BELL},{"wifi",LV_SYMBOL_WIFI},
      {"trash",LV_SYMBOL_TRASH},{"edit",LV_SYMBOL_EDIT}};
    for(const auto& item:values)if(!strcmp(name,item.name))return item.symbol;
    return LV_SYMBOL_OK;
}
const lv_font_t *title_font(const deck_button_t& value) {
    switch(value.title_size) {
      case 20:return value.title_bold?&fq_font_dejavu_bold_20:&fq_font_dejavu_20;
      case 24:return value.title_bold?&fq_font_dejavu_bold_24:&fq_font_dejavu_24;
      case 28:return value.title_bold?&fq_font_dejavu_bold_28:&fq_font_dejavu_28;
      default:return value.title_bold?&fq_font_dejavu_bold_20:&fq_font_dejavu_16;
    }
}
void image_frame(ImageTile& value) {
    value.descriptor.header.magic=LV_IMAGE_HEADER_MAGIC;value.descriptor.header.cf=LV_COLOR_FORMAT_ARGB8888;
    value.descriptor.header.w=value.image->width;value.descriptor.header.h=value.image->height;
    value.descriptor.header.stride=value.image->width*4;value.descriptor.data=value.image->frames[value.frame].data();
    value.descriptor.data_size=value.image->frames[value.frame].size();lv_image_cache_drop(&value.descriptor);
    lv_image_set_src(value.widget,&value.descriptor);lv_obj_invalidate(value.widget);
    value.due=millis()+value.image->durations[value.frame];
}
void flash(int slot,uint32_t color,uint32_t ms) {
    lv_obj_set_style_bg_color(keys[slot],lv_color_hex(color),0);flash_until[slot]=millis()+ms;
}
void press(lv_event_t *event) {
    const int slot=static_cast<int>(reinterpret_cast<intptr_t>(lv_event_get_user_data(event)));
    if(slot<0||slot>=DECK_MAX_BUTTONS||!ids[slot])return;
    if(!deck_model_record_press(ids[slot]))return;
    /* Without a host nothing runs the action: say so at once instead of
     * flashing as if it worked. */
    if(deck_model_host_linked(HostTimeoutMs))flash(slot,PressedBg,PendingMs);
    else flash(slot,AlertBg,500);
}
/* A touch on a dimmed panel only wakes it, wherever it lands, and never
 * reaches a key: the indev ignores the rest of the touch until release. */
void wake_touch(lv_event_t *event) {
    if(!deck_model_dimmed())return;
    deck_model_request_wake();
    auto *indev=static_cast<lv_indev_t*>(lv_event_get_target(event));
    lv_indev_stop_processing(indev);lv_indev_wait_release(indev);
}
void update_link() {
    const int linked=deck_model_host_linked(HostTimeoutMs)?1:0;
    if(linked==link_shown)return;
    link_shown=linked;
    lv_obj_set_style_bg_color(link_pill,lv_color_hex(linked?0x16372A:0x3A2E1A),0);
    lv_obj_set_style_bg_color(link_dot,lv_color_hex(linked?Accent:Amber),0);
    lv_obj_set_style_text_color(link_label,lv_color_hex(linked?0xA8F2CA:0xFFD699),0);
    lv_label_set_text(link_label,linked?"PC CONNECTED":"NO PC");
}
void style_gauge(int slot,const deck_button_t& value) {
    if(!gauge_arc[slot]||!gauge_value[slot])return;
    lv_arc_set_value(gauge_arc[slot],value.gauge_percent);
    lv_obj_set_style_arc_color(gauge_arc[slot],lv_color_hex(value.color),LV_PART_INDICATOR);
    lv_label_set_text(gauge_value[slot],value.gauge_text);
    lv_obj_set_style_text_color(gauge_value[slot],lv_color_hex(value.color),0);
    lv_obj_set_style_text_font(gauge_value[slot],strlen(value.gauge_text)>3?&fq_font_dejavu_bold_24:&fq_font_dejavu_bold_28,0);
}
void make_gauge(int slot,lv_obj_t *tile,const deck_button_t& value) {
    constexpr int D=108,Top=6;
    auto *arc=lv_arc_create(tile);gauge_arc[slot]=arc;
    lv_obj_set_size(arc,D,D);lv_obj_set_pos(arc,(Cell-D)/2,Top);
    lv_arc_set_range(arc,0,100);lv_arc_set_bg_angles(arc,135,45);
    lv_obj_remove_style(arc,nullptr,LV_PART_KNOB);lv_obj_set_clickable(arc,false);
    lv_obj_set_style_arc_width(arc,11,LV_PART_MAIN);lv_obj_set_style_arc_width(arc,11,LV_PART_INDICATOR);
    lv_obj_set_style_arc_color(arc,lv_color_hex(0x25343C),LV_PART_MAIN);
    lv_obj_set_style_arc_rounded(arc,true,LV_PART_MAIN);lv_obj_set_style_arc_rounded(arc,true,LV_PART_INDICATOR);
    gauge_value[slot]=label(tile,"",0,Top+D/2-16,Cell,&fq_font_dejavu_bold_28,Text);
    lv_obj_set_style_text_align(gauge_value[slot],LV_TEXT_ALIGN_CENTER,0);
    style_gauge(slot,value);
}
void update_live() {
    for(int n=0;n<deck_model_button_count();++n){deck_button_t item{};
        if(deck_model_get_button(n,&item)&&item.has_gauge&&item.id>=1&&item.id<=DECK_MAX_BUTTONS)style_gauge(item.id-1,item);}
    live_version=deck_model_live_version();
}
void rebuild() {
    memset(gauge_arc,0,sizeof(gauge_arc));memset(gauge_value,0,sizeof(gauge_value));
    lv_obj_clean(grid);for(auto& image:images){lv_image_cache_drop(&image.descriptor);image=ImageTile{};}
    memset(keys,0,sizeof(keys));memset(ids,0,sizeof(ids));memset(flash_until,0,sizeof(flash_until));
    for(int slot=0;slot<DECK_MAX_BUTTONS;++slot) {
        deck_button_t value{};bool assigned=false;
        for(int n=0;n<deck_model_button_count();++n){deck_button_t item{};if(deck_model_get_button(n,&item)&&item.id==slot+1){value=item;assigned=true;break;}}
        auto *tile=lv_button_create(grid);keys[slot]=tile;
        lv_obj_set_pos(tile,X+(slot%6)*(Cell+Gap),Y+(slot/6)*(Cell+Gap));lv_obj_set_size(tile,Cell,Cell);
        flat(tile,assigned?Surface:0x0E171B);lv_obj_set_style_radius(tile,20,0);
        lv_obj_set_style_border_width(tile,1,0);lv_obj_set_style_border_color(tile,lv_color_hex(assigned?Border:0x1B2A30),0);
        lv_obj_set_style_bg_color(tile,lv_color_hex(0x244D3A),LV_STATE_PRESSED);
        if(!assigned){lv_obj_set_clickable(tile,false);auto *plus=label(tile,"+",0,51,Cell,&fq_font_dejavu_28,0x263940);lv_obj_set_style_text_align(plus,LV_TEXT_ALIGN_CENTER,0);continue;}
        ids[slot]=value.id;char packed[5]{};const bool lucide=deck_lucide_glyph(value.icon,packed);auto image=deck_image_get(value.icon);
        if(value.has_gauge){make_gauge(slot,tile,value);}
        else if(image){auto& target=images[slot];target.image=image;target.widget=lv_image_create(tile);lv_obj_set_pos(target.widget,(Cell-image->width)/2,value.title_position==1?57:18);image_frame(target);}
        else {auto *glyph=label(tile,lucide?packed:fallback_icon(value.icon),0,value.title_position==1?61:(lucide?17:25),Cell,lucide?&deck_lucide_60:&lv_font_montserrat_48,value.color);lv_obj_set_style_text_align(glyph,LV_TEXT_ALIGN_CENTER,0);}
        const int size=value.title_size?value.title_size:16;const int y=value.title_position==1?10:value.title_position==2?(Cell-size)/2:Cell-size-17;
        auto *name=label(tile,value.label,9,y,Cell-18,title_font(value),Text);lv_obj_set_style_text_align(name,LV_TEXT_ALIGN_CENTER,0);lv_obj_set_hidden(name,value.title_position==3);
        lv_obj_add_event_cb(tile,press,LV_EVENT_CLICKED,reinterpret_cast<void*>(static_cast<intptr_t>(slot)));
    }
    button_version=deck_model_buttons_version();live_version=deck_model_live_version();
}
void update_context() {
    const auto context=deck_model_context();char profile[64];snprintf(profile,sizeof(profile),"PROFILE  %s",context.profile);
    char page[80];snprintf(page,sizeof(page),"%s%s",context.can_go_back?"<  ":"",context.page);
    lv_label_set_text(profile_label,profile);lv_label_set_text(page_label,page);context_version=deck_model_context_version();
}
void update(lv_timer_t*) {
    if(button_version!=deck_model_buttons_version())rebuild();
    else if(live_version!=deck_model_live_version())update_live();
    if(context_version!=deck_model_context_version())update_context();
    for(auto& image:images)if(image.image&&image.image->frames.size()>1&&static_cast<int32_t>(millis()-image.due)>=0){image.frame=(image.frame+1)%image.image->frames.size();image_frame(image);}
    int id=0;deck_feedback_t result;
    while(deck_model_take_feedback(&id,&result))for(int i=0;i<DECK_MAX_BUTTONS;++i)if(ids[i]==id&&keys[i])flash(i,result==DECK_FEEDBACK_ALERT?AlertBg:OkBg,500);
    for(int i=0;i<DECK_MAX_BUTTONS;++i)if(flash_until[i]&&static_cast<int32_t>(millis()-flash_until[i])>=0){lv_obj_set_style_bg_color(keys[i],lv_color_hex(Surface),0);flash_until[i]=0;}
    update_link();
    lv_label_set_text(clock_label,time_service_time_text());
}
}

extern "C" void ui_show_destination(int) {if(screen)lv_screen_load(screen);}
extern "C" void ui_init(void) {
    screen=lv_obj_create(nullptr);flat(screen,Bg);auto *header=lv_obj_create(screen);flat(header,HeaderBg);lv_obj_set_size(header,W,Header);
    auto *mark=lv_obj_create(header);flat(mark,Accent);lv_obj_set_pos(mark,20,18);lv_obj_set_size(mark,8,40);lv_obj_set_style_radius(mark,4,0);
    label(header,"TESSERA",43,15,205,&fq_font_dejavu_bold_24,Text);label(header,"CONTROL SURFACE",44,45,190,&lv_font_montserrat_10,Muted);
    profile_label=label(header,"PROFILE  LOCAL",266,16,250,&lv_font_montserrat_12,Muted);page_label=label(header,"MAIN",266,35,360,&fq_font_dejavu_bold_24,Text);
    link_pill=lv_obj_create(header);flat(link_pill,0x16372A);lv_obj_set_pos(link_pill,718,19);lv_obj_set_size(link_pill,150,38);lv_obj_set_style_radius(link_pill,19,0);
    link_dot=lv_obj_create(link_pill);flat(link_dot,Accent);lv_obj_set_pos(link_dot,15,15);lv_obj_set_size(link_dot,8,8);lv_obj_set_style_radius(link_dot,4,0);
    link_label=label(link_pill,"",32,11,110,&lv_font_montserrat_12,0xA8F2CA);link_shown=-1;update_link();
    clock_label=label(header,"--:--",885,22,115,&lv_font_montserrat_22,Text);lv_obj_set_style_text_align(clock_label,LV_TEXT_ALIGN_RIGHT,0);
    grid=lv_obj_create(screen);flat(grid,Bg);lv_obj_set_pos(grid,0,Header);lv_obj_set_size(grid,W,H-Header);
    for(lv_indev_t *indev=lv_indev_get_next(nullptr);indev;indev=lv_indev_get_next(indev))lv_indev_add_event_cb(indev,wake_touch,LV_EVENT_PRESSED,nullptr);
    rebuild();update_context();lv_screen_load(screen);update(nullptr);lv_timer_create(update,40,nullptr);
}
extern "C" int ui_debug_visible_text(char *out,size_t size) {
    if(!out||!size)return -1;
    const auto context=deck_model_context();
    const int n=snprintf(out,size,"{\"screen\":\"deck\",\"buttons\":%d,\"profile\":\"%s\",\"page\":\"%s\",\"canBack\":%s,\"pc\":%s}",
                         deck_model_button_count(),context.profile,context.page,context.can_go_back?"true":"false",link_shown==1?"true":"false");
    return n>0&&n<static_cast<int>(size)?0:-1;
}
