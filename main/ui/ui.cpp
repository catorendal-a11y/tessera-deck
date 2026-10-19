// Standalone full-screen Agent Deck UI.
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
lv_obj_t *screen=nullptr,*grid=nullptr,*profile_label=nullptr,*page_label=nullptr,*clock_label=nullptr;
lv_obj_t *keys[DECK_MAX_BUTTONS]{};
int ids[DECK_MAX_BUTTONS]{};
uint32_t button_version=0,context_version=0,feedback_version=0;
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
void press(lv_event_t *event) {
    const int slot=static_cast<int>(reinterpret_cast<intptr_t>(lv_event_get_user_data(event)));
    if(slot<0||slot>=DECK_MAX_BUTTONS||!ids[slot])return;
    if(deck_model_record_press(ids[slot])){lv_obj_set_style_bg_color(keys[slot],lv_color_hex(0x254E3B),0);flash_until[slot]=millis()+160;}
}
void rebuild() {
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
        if(image){auto& target=images[slot];target.image=image;target.widget=lv_image_create(tile);lv_obj_set_pos(target.widget,(Cell-image->width)/2,value.title_position==1?57:18);image_frame(target);}
        else {auto *glyph=label(tile,lucide?packed:fallback_icon(value.icon),0,value.title_position==1?61:(lucide?17:25),Cell,lucide?&deck_lucide_60:&lv_font_montserrat_48,value.color);lv_obj_set_style_text_align(glyph,LV_TEXT_ALIGN_CENTER,0);}
        const int size=value.title_size?value.title_size:16;const int y=value.title_position==1?10:value.title_position==2?(Cell-size)/2:Cell-size-17;
        auto *name=label(tile,value.label,9,y,Cell-18,title_font(value),Text);lv_obj_set_style_text_align(name,LV_TEXT_ALIGN_CENTER,0);lv_obj_set_hidden(name,value.title_position==3);
        lv_obj_add_event_cb(tile,press,LV_EVENT_CLICKED,reinterpret_cast<void*>(static_cast<intptr_t>(slot)));
    }
    button_version=deck_model_buttons_version();
}
void update_context() {
    const auto context=deck_model_context();char profile[64];snprintf(profile,sizeof(profile),"PROFIL  %s",context.profile);
    char page[80];snprintf(page,sizeof(page),"%s%s",context.can_go_back?"<  ":"",context.page);
    lv_label_set_text(profile_label,profile);lv_label_set_text(page_label,page);context_version=deck_model_context_version();
}
void update(lv_timer_t*) {
    if(button_version!=deck_model_buttons_version())rebuild();
    if(context_version!=deck_model_context_version())update_context();
    for(auto& image:images)if(image.image&&image.image->frames.size()>1&&static_cast<int32_t>(millis()-image.due)>=0){image.frame=(image.frame+1)%image.image->frames.size();image_frame(image);}
    int id=0;deck_feedback_t result;const auto feedback=deck_model_take_feedback(&id,&result);
    if(feedback&&feedback!=feedback_version){feedback_version=feedback;for(int i=0;i<DECK_MAX_BUTTONS;++i)if(ids[i]==id&&keys[i]){lv_obj_set_style_bg_color(keys[i],lv_color_hex(result==DECK_FEEDBACK_ALERT?0x6E2633:0x1E6042),0);flash_until[i]=millis()+500;}}
    for(int i=0;i<DECK_MAX_BUTTONS;++i)if(flash_until[i]&&static_cast<int32_t>(millis()-flash_until[i])>=0){lv_obj_set_style_bg_color(keys[i],lv_color_hex(Surface),0);flash_until[i]=0;}
    lv_label_set_text(clock_label,time_service_time_text());
}
}

extern "C" void ui_show_destination(int) {if(screen)lv_screen_load(screen);}
extern "C" void ui_init(void) {
    screen=lv_obj_create(nullptr);flat(screen,Bg);auto *header=lv_obj_create(screen);flat(header,HeaderBg);lv_obj_set_size(header,W,Header);
    auto *mark=lv_obj_create(header);flat(mark,Accent);lv_obj_set_pos(mark,20,18);lv_obj_set_size(mark,8,40);lv_obj_set_style_radius(mark,4,0);
    label(header,"AGENT DECK",43,15,205,&fq_font_dejavu_bold_24,Text);label(header,"CONTROL SURFACE",44,45,190,&lv_font_montserrat_10,Muted);
    profile_label=label(header,"PROFIL  LOKAL",266,16,250,&lv_font_montserrat_12,Muted);page_label=label(header,"HOVED",266,35,360,&fq_font_dejavu_bold_24,Text);
    auto *pill=lv_obj_create(header);flat(pill,0x16372A);lv_obj_set_pos(pill,718,19);lv_obj_set_size(pill,150,38);lv_obj_set_style_radius(pill,19,0);
    auto *dot=lv_obj_create(pill);flat(dot,Accent);lv_obj_set_pos(dot,15,15);lv_obj_set_size(dot,8,8);lv_obj_set_style_radius(dot,4,0);label(pill,"USB KLAR",32,11,100,&lv_font_montserrat_12,0xA8F2CA);
    clock_label=label(header,"--:--",885,22,115,&lv_font_montserrat_22,Text);lv_obj_set_style_text_align(clock_label,LV_TEXT_ALIGN_RIGHT,0);
    grid=lv_obj_create(screen);flat(grid,Bg);lv_obj_set_pos(grid,0,Header);lv_obj_set_size(grid,W,H-Header);
    rebuild();update_context();lv_screen_load(screen);update(nullptr);lv_timer_create(update,40,nullptr);
}
extern "C" int ui_debug_visible_text(char *out,size_t size) {
    if(!out||!size)return -1;
    const auto context=deck_model_context();
    const int n=snprintf(out,size,"{\"screen\":\"deck\",\"buttons\":%d,\"profile\":\"%s\",\"page\":\"%s\",\"canBack\":%s}",
                         deck_model_button_count(),context.profile,context.page,context.can_go_back?"true":"false");
    return n>0&&n<static_cast<int>(size)?0:-1;
}
